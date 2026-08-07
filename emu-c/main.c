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
#include "gen/spec_version.h"
#include "hostmem.h"
#include "image.h"
#include "mem.h"
#include "trace.h"
#include "u128.h"

/* PLATFORM-SPEC version for the META platform= key; the literal is
 * pinned by devspec/trace.md 2.3.7 (no machine-readable source exists
 * for it the way encoding.py carries SPEC_VERSION). */
#define PLATFORM_SPEC_VERSION "1.0-draft"

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

/* Find the LF-terminated value of key in META text, or NULL. */
static const char *meta_find(const char *text, const char *key)
{
    size_t klen = strlen(key);
    for (const char *p = text; *p != '\0';) {
        const char *eol = strchr(p, '\n');
        if (!eol)
            break;
        if ((size_t)(eol - p) > klen && memcmp(p, key, klen) == 0 &&
            p[klen] == '=')
            return p + klen + 1u;
        p = eol + 1;
    }
    return NULL;
}

static void meta_expect(const char *text, const char *key, const char *want)
{
    const char *v = meta_find(text, key);
    if (!v) {
        fprintf(stderr, "sahara-emu: --replay META missing key %s\n", key);
        exit(1);
    }
    const char *eol = strchr(v, '\n'); /* non-NULL: meta_find matched it */
    size_t wlen = strlen(want);
    if ((size_t)(eol - v) != wlen || memcmp(v, want, wlen) != 0) {
        fprintf(stderr,
                "sahara-emu: --replay META %s mismatch: recorded %.*s, "
                "this run %s\n",
                key, (int)(eol - v), v, want);
        exit(1);
    }
}

/* Replay input validation (devspec/trace.md 5.1): record 0 must be a
 * META record whose trace/encoding/image_sha256 keys match this run;
 * any mismatch is fatal and the run must not start. EVENT records are
 * still rejected outright: the device phase that would consume them
 * does not exist yet (they would silently vanish otherwise -- loud
 * failure instead). */
static void validate_replay(const char *path, const char *sha_hex)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        die("cannot open --replay file");
    uint8_t hdr[8];
    bool saw_meta = false;
    while (fread(hdr, 1u, 8u, f) == 8u) {
        uint32_t plen = 0;
        for (unsigned i = 0; i < 4u; i++)
            plen |= (uint32_t)hdr[4u + i] << (8u * i);
        if (!saw_meta) {
            /* 64 KB cap: the v1 catalog is seven short lines; anything
             * bigger is malformed long before it is that large. */
            if (hdr[0] != 7u || plen == 0u || plen > 65536u)
                die("--replay file does not start with a META record");
            char *meta = se_host_alloc((size_t)plen + 1u);
            if (fread(meta, 1u, plen, f) != plen)
                die("truncated --replay META record");
            meta[plen] = '\0';
            if (memchr(meta, '\0', plen) != NULL || meta[plen - 1u] != '\n')
                die("malformed --replay META record");
            meta_expect(meta, "trace", "1");
            meta_expect(meta, "encoding", SE_ENCODING_SPEC_VERSION);
            meta_expect(meta, "image_sha256", sha_hex);
            se_host_free(meta, (size_t)plen + 1u);
            saw_meta = true;
            continue;
        }
        if (hdr[0] == 5u) /* EVENT */
            die("--replay contains EVENT records; device phase not "
                "implemented yet");
        if (fseek(f, (long)plen, SEEK_CUR) != 0)
            die("truncated --replay file");
    }
    if (!saw_meta)
        die("--replay file has no META record");
    fclose(f);
}

static void meta_record(SeTrace *tr, const char *image_arg,
                        const char *sha_hex, int level, bool replay)
{
    /* v1 catalog of devspec/trace.md 2.3.7: exactly these seven keys,
     * in this order, no others. image= is the path exactly as given on
     * the command line (run-variant, excluded from trace comparison
     * along with mode=). */
    char buf[640];
    int n = snprintf(buf, sizeof buf,
                     "trace=1\n"
                     "encoding=" SE_ENCODING_SPEC_VERSION "\n"
                     "level=%d\n"
                     "mode=%s\n"
                     "image=%s\n"
                     "image_sha256=%s\n"
                     "platform=" PLATFORM_SPEC_VERSION "\n",
                     level, replay ? "replay" : "live", image_arg, sha_hex);
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

    SeMem mem;
    SeMem_init(&mem, ram);
    write_device_table(&mem, ram);

    se_u128 entry = 0;
    uint8_t sha[32];
    const char *err = se_image_load(&mem, image, &entry, sha);
    if (err)
        die(err);
    char sha_hex[65];
    for (unsigned i = 0; i < 32u; i++)
        snprintf(sha_hex + 2u * i, 3u, "%02x", sha[i]);

    if (replay_path)
        validate_replay(replay_path, sha_hex);

    SeTrace tr = { .f = NULL, .level = level };
    if (trace_path) {
        tr.f = fopen(trace_path, "wb");
        if (!tr.f)
            die("cannot open --trace output file");
        meta_record(&tr, image, sha_hex, level, replay_path != NULL);
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
