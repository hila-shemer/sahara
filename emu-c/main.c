/* sahara-emu: headless front end implementing the frozen CLI contract
 * (emu-common-prompt.md):
 *
 *   sahara-emu IMAGE [--replay events.trc] [--trace out.trc
 *              --trace-level N] [--maxcycles N] [--ram BYTES]
 *              [--check-invtp] [--check-devorder N]
 *
 * HALT        -> "HALT r0=<32 hex digits>" on stdout, exit 0
 * maxcycles   -> "MAXCYCLES", exit 2
 * check fired -> "CHECKFAIL <reason>", exit 3
 * internal    -> message on stderr, nonzero exit
 */
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cpu.h"
#include "hostmem.h"
#include "image.h"
#include "mem.h"
#include "trace.h"
#include "u128.h"

#define DEFAULT_RAM (256ull * 1024u * 1024u)
#define DEVTAB_PA 0x800ull
#define DEVTAB_MAGIC 0x5450415241484153ull /* "SAHARAPT" little-endian */

static void die(const char *msg)
{
    fprintf(stderr, "sahara-emu: %s\n", msg);
    exit(1);
}

static uint64_t parse_u64(const char *s, const char *what)
{
    char *end = NULL;
    unsigned long long v = strtoull(s, &end, 0);
    if (!end || *end != '\0' || end == s) {
        fprintf(stderr, "sahara-emu: bad %s: %s\n", what, s);
        exit(1);
    }
    return (uint64_t)v;
}

/* The emulator writes the device table before reset (PLATFORM-SPEC 2).
 * Headless core phase: one RAM region, no devices yet. */
static void write_device_table(SeMem *m, uint64_t ram_len)
{
    SeMem_write(m, DEVTAB_PA + 0u, 8u, DEVTAB_MAGIC);
    SeMem_write(m, DEVTAB_PA + 8u, 8u, 1u);  /* version */
    SeMem_write(m, DEVTAB_PA + 16u, 8u, 1u); /* cpu_count */
    SeMem_write(m, DEVTAB_PA + 24u, 8u, 1u); /* ram_region_count */
    SeMem_write(m, DEVTAB_PA + 32u, 8u, 0u); /* device_count */
    SeMem_write(m, DEVTAB_PA + 40u, 16u, 0u);              /* region base */
    SeMem_write(m, DEVTAB_PA + 56u, 16u, (se_u128)ram_len); /* region len */
}

/* Replay input: scan a .trc file and reject EVENT records until the
 * device phase exists to consume them (they would silently vanish
 * otherwise -- loud failure instead). */
static void scan_replay(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        die("cannot open --replay file");
    uint8_t hdr[8];
    while (fread(hdr, 1u, 8u, f) == 8u) {
        uint32_t plen = 0;
        for (unsigned i = 0; i < 4u; i++)
            plen |= (uint32_t)hdr[4u + i] << (8u * i);
        if (hdr[0] == 5u) { /* EVENT */
            fclose(f);
            die("--replay contains EVENT records; device phase not "
                "implemented yet");
        }
        if (fseek(f, (long)plen, SEEK_CUR) != 0) {
            fclose(f);
            die("truncated --replay file");
        }
    }
    fclose(f);
}

static void meta_record(SeTrace *tr, const char *image, uint64_t fnv,
                        int level, bool check_invtp, uint64_t devorder)
{
    /* Deterministic key=value text; format choice recorded in
     * SPEC-ISSUES.md (TOOLING-SPEC 3.2 leaves it open). Basename, not
     * path, so runs from different directories stay comparable. */
    const char *base = strrchr(image, '/');
    base = base ? base + 1 : image;
    char buf[512];
    int n = snprintf(buf, sizeof buf,
                     "sahara-trace\nencoding=1.0-draft\nlevel=%d\n"
                     "image=%s\nimage_fnv64=%016" PRIx64 "\n"
                     "check_invtp=%d\ncheck_devorder=%" PRIu64 "\n",
                     level, base, fnv, check_invtp ? 1 : 0, devorder);
    if (n < 0 || (size_t)n >= sizeof buf)
        die("META record overflow");
    SeTrace_meta(tr, buf, (uint32_t)n);
}

int main(int argc, char **argv)
{
    const char *image = NULL, *trace_path = NULL, *replay_path = NULL;
    uint64_t maxcycles = 0, ram = DEFAULT_RAM, devorder = 0;
    int level = 1;
    bool check_invtp = false;

    for (int i = 1; i < argc; i++) {
        const char *a = argv[i];
        if (strcmp(a, "--replay") == 0 && i + 1 < argc) {
            replay_path = argv[++i];
        } else if (strcmp(a, "--trace") == 0 && i + 1 < argc) {
            trace_path = argv[++i];
        } else if (strcmp(a, "--trace-level") == 0 && i + 1 < argc) {
            uint64_t v = parse_u64(argv[++i], "--trace-level");
            if (v > 2u)
                die("--trace-level must be 0..2");
            level = (int)v;
        } else if (strcmp(a, "--maxcycles") == 0 && i + 1 < argc) {
            maxcycles = parse_u64(argv[++i], "--maxcycles");
        } else if (strcmp(a, "--ram") == 0 && i + 1 < argc) {
            ram = parse_u64(argv[++i], "--ram");
        } else if (strcmp(a, "--check-invtp") == 0) {
            check_invtp = true;
        } else if (strcmp(a, "--check-devorder") == 0 && i + 1 < argc) {
            devorder = parse_u64(argv[++i], "--check-devorder");
        } else if (a[0] == '-') {
            fprintf(stderr, "sahara-emu: unknown option %s\n", a);
            return 1;
        } else if (!image) {
            image = a;
        } else {
            die("more than one IMAGE argument");
        }
    }
    if (!image)
        die("usage: sahara-emu IMAGE [--replay F] [--trace F "
            "--trace-level N] [--maxcycles N] [--ram BYTES] "
            "[--check-invtp] [--check-devorder N]");
    if (ram < 0x20000u)
        die("--ram too small for device table + reset vector");

    if (replay_path)
        scan_replay(replay_path);

    SeMem mem;
    SeMem_init(&mem, ram);
    write_device_table(&mem, ram);

    se_u128 entry = 0;
    uint64_t fnv = 0;
    const char *err = se_image_load(&mem, image, &entry, &fnv);
    if (err)
        die(err);

    SeTrace tr = { .f = NULL, .level = level };
    if (trace_path) {
        tr.f = fopen(trace_path, "wb");
        if (!tr.f)
            die("cannot open --trace output file");
        meta_record(&tr, image, fnv, level, check_invtp, devorder);
    }

    SeCpu *cpu = se_host_alloc(sizeof *cpu); /* one startup allocation */
    SeCpu_reset(cpu, &mem, &tr);
    cpu->check_invtp = check_invtp;
    cpu->devorder_depth = devorder;

    bool out_of_cycles = false;
    while (cpu->state == SE_RUN_RUNNING) {
        if (maxcycles != 0u && cpu->cycle >= (se_u128)maxcycles) {
            out_of_cycles = true;
            break;
        }
        SeCpu_step(cpu);
    }

    if (tr.f && fclose(tr.f) != 0)
        die("error closing trace file");

    if (out_of_cycles) {
        printf("MAXCYCLES\n");
        return 2;
    }
    if (cpu->state == SE_RUN_CHECKFAIL) {
        printf("CHECKFAIL %s\n", cpu->checkfail);
        return 3;
    }
    if (cpu->halt_note)
        fprintf(stderr, "sahara-emu: note: %s\n", cpu->halt_note);
    printf("HALT r0=%016" PRIx64 "%016" PRIx64 "\n", se_hi64(cpu->r[0]),
           se_lo64(cpu->r[0]));
    return 0;
}
