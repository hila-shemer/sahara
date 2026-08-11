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
#include "dev.h"
#include "gen/spec_version.h"
#include "hostmem.h"
#include "image.h"
#include "mem.h"
#include "platform.h"
#include "trace.h"
#include "u128.h"

/* PLATFORM-SPEC version for the META platform= key; the literal is
 * pinned by devspec/trace.md 2.3.7 (no machine-readable source exists
 * for it the way encoding.py carries SPEC_VERSION). */
#define PLATFORM_SPEC_VERSION "1.0-draft"

/* --ram is the address budget below the pixel buffer (devspec/boot.md
 * 5 / devspec SPEC-ISSUES 1): the default 256 MB yields RAM region 0 =
 * [0, 0x0F00_0000) -- 240 MB -- ending where the device windows begin. */
#define DEFAULT_RAM (256ull * 1024u * 1024u)

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

/* A malformed replay input (devspec/trace.md 2.4 class 2) is a fatal
 * error: readers must reject the file. Offset is the record's start. */
static void malformed(uint64_t off, const char *why)
{
    fprintf(stderr,
            "sahara-emu: --replay malformed record at offset %" PRIu64
            ": %s\n",
            off, why);
    exit(1);
}

/* META line grammar per devspec/trace.md 2.3.7: lines of key=value, LF
 * terminated, keys [a-z0-9_]+, values NUL/LF-free; the seven v1 keys
 * are all mandatory (unknown extras are ignored -- forward compat). */
static void meta_check_grammar(const char *text, uint64_t off)
{
    for (const char *p = text; *p != '\0';) {
        const char *eol = strchr(p, '\n');
        if (!eol)
            malformed(off, "META line without LF terminator");
        const char *eq = memchr(p, '=', (size_t)(eol - p));
        if (!eq || eq == p)
            malformed(off, "META line is not key=value");
        for (const char *k = p; k < eq; k++)
            if (!((*k >= 'a' && *k <= 'z') || (*k >= '0' && *k <= '9') ||
                  *k == '_'))
                malformed(off, "META key has chars outside [a-z0-9_]");
        p = eol + 1;
    }
    static const char *const mandatory[] = { "trace",  "encoding",
                                             "level",  "mode",
                                             "image",  "image_sha256",
                                             "platform" };
    for (unsigned i = 0; i < sizeof mandatory / sizeof mandatory[0]; i++)
        if (!meta_find(text, mandatory[i]))
            malformed(off, "META missing a mandatory v1 key");
}

static uint64_t get_u64(const uint8_t *b)
{
    uint64_t v = 0;
    for (unsigned i = 0; i < 8u; i++)
        v |= (uint64_t)b[i] << (8u * i);
    return v;
}

/* Double the event array; the old allocation is returned to the host. */
static SeEvRec *ev_grow(SeEvRec *evs, uint64_t *cap, uint64_t count)
{
    if (count < *cap)
        return evs;
    uint64_t ncap = *cap ? *cap * 2u : 64u;
    SeEvRec *nv = se_host_alloc((size_t)ncap * sizeof *nv);
    if (*cap) {
        memcpy(nv, evs, (size_t)count * sizeof *evs);
        se_host_free(evs, (size_t)*cap * sizeof *evs);
    }
    *cap = ncap;
    return nv;
}

/* An EVENT record's device index and inner payload, validated per
 * devspec/trace.md 4 against the reference device table (index 0
 * display, 1 kbd, 2 mouse, 3 nic, 4 rng -- this branch's table order,
 * rng.md V-T): unknown
 * index or a payload violating its device's encoding is a malformed
 * trace (4.5 / 2.4 class 2). The drop flag VALUE is not checked --
 * replay recomputes it (5.4) -- but its reserved bits are. inner is
 * the payload bytes at head + 20 (at most a full NIC frame; validated
 * before anything is copied out of head). */
static void validate_event(uint64_t off, uint64_t device, uint32_t inner,
                           const uint8_t *p)
{
    switch (device) {
    case SE_DEVIDX_DISPLAY: {
        if (inner != 32u)
            malformed(off, "resize payload is not 32 bytes (trace.md 4.4)");
        uint64_t w = get_u64(p), h = get_u64(p + 8u);
        uint64_t s = get_u64(p + 16u), fmt = get_u64(p + 24u);
        /* Geometry must satisfy display.md 3.4 at all times; a feed
         * publishing an invalid mode is not a v1 trace. */
        uint64_t win = se_lo64(SE_PLAT_PIXBUF_SIZE);
        if (fmt != 1u)
            malformed(off, "resize format is not 1 (trace.md 4.4)");
        if (w == 0u || h == 0u || w > 0xFFFFFFFFull || h > 0xFFFFFFFFull)
            malformed(off, "resize width/height not nonzero 32-bit "
                           "(display.md 3.4)");
        if (s < 4u * w || s % 16u != 0u)
            malformed(off, "resize stride under 4*width or not 16-aligned "
                           "(display.md 3.4)");
        if (h > win / s || w > win / s)
            malformed(off, "resize frame exceeds the pixel window "
                           "(display.md 3.4)");
        return;
    }
    case SE_DEVIDX_KBD:
    case SE_DEVIDX_MOUSE: {
        if (inner != 9u)
            malformed(off, "input event payload is not 9 bytes "
                           "(trace.md 4.1/4.2)");
        uint64_t word = get_u64(p);
        if (p[8] & 0xFEu)
            malformed(off, "input event flags bits 7:1 set");
        if (device == SE_DEVIDX_KBD ? (word >> 33) != 0u
                                    : (word >> 40) != 0u)
            malformed(off, "input event word reserved bits set");
        return;
    }
    case SE_DEVIDX_NIC:
        /* Frame bytes, opaque (trace.md 4.3): the model admits only
         * padded legal frames, so any other length is not a v1 trace.
         * Content is not validated -- the trace stores whatever the
         * NIC accepted, byte-for-byte. */
        if (inner < SE_NIC_FRAME_MIN || inner > SE_NIC_FRAME_MAX)
            malformed(off, "NIC frame payload outside [60, 1514] "
                           "(nic.md 3.1)");
        return;
    case SE_DEVIDX_RNG:
        /* N whole u64 words, 1..128 (trace.md 4.6). Content is
         * entropy -- nothing to validate; acceptance is recomputed at
         * apply time, never trusted from the feed. */
        if (inner == 0u || inner % 8u != 0u ||
            inner > 8u * SE_RNG_EV_WORDS_MAX)
            malformed(off, "RNG payload not 1..128 whole u64 words "
                           "(trace.md 4.6)");
        return;
    default:
        malformed(off, "EVENT device index outside the reference device "
                       "table (trace.md 4.5)");
    }
}

/* Replay input validation: a strict trace read per devspec/trace.md
 * 2.4 + 5.1. Record 0 must be a META record whose trace/encoding/
 * image_sha256 keys match this run; any malformed record (bad reserved
 * bytes, type, fixed payload length, EVENT inner length or encoding,
 * EXEC flag bits 7:3, duplicate META, decreasing cycle) is fatal; a
 * torn tail (killed-emulator artifact) keeps the complete-record
 * prefix and gets a stderr diagnostic with the offset and bytes
 * discarded. EVENT records are collected -- they are the replay's sole
 * input source (5.2) -- and returned in file order for the CPU's
 * boundary phase; *count_out receives how many. */
static SeEvRec *validate_replay(const char *path, const char *sha_hex,
                                uint64_t *count_out)
{
    /* Fixed payload lengths per trace.md 2.1; 0 = variable. */
    static const uint32_t fixed_plen[8] = { 0, 50u, 41u, 41u, 49u, 0, 41u,
                                            0 };
    FILE *f = fopen(path, "rb");
    if (!f)
        die("cannot open --replay file");
    uint8_t hdr[8];
    uint64_t off = 0, records = 0, prev_cycle = 0;
    bool saw_meta = false;
    SeEvRec *evs = NULL;
    uint64_t ev_cap = 0, ev_count = 0;
    for (;;) {
        size_t got = fread(hdr, 1u, 8u, f);
        if (got == 0u)
            break; /* clean end at a record boundary */
        if (got < 8u) {
            fprintf(stderr,
                    "sahara-emu: --replay torn tail: incomplete record at "
                    "offset %" PRIu64 ", %zu bytes discarded\n",
                    off, got);
            break;
        }
        uint32_t plen = 0;
        for (unsigned i = 0; i < 4u; i++)
            plen |= (uint32_t)hdr[4u + i] << (8u * i);
        uint8_t type = hdr[0];
        if (hdr[1] != 0u || hdr[2] != 0u || hdr[3] != 0u)
            malformed(off, "nonzero reserved header bytes");
        if (type < 1u || type > 7u)
            malformed(off, "record type outside 1-7");
        if (records == 0u && type != 7u)
            malformed(off, "record 0 is not META");
        if (type == 7u && records != 0u)
            malformed(off, "duplicate META record");
        if (fixed_plen[type] != 0u && plen != fixed_plen[type])
            malformed(off, "wrong payload length for fixed-size type");
        if (type == 5u && plen < 20u)
            malformed(off, "EVENT payload shorter than its fixed part");
        if (type == 7u) {
            /* 64 KB cap: the v1 catalog is seven short lines; anything
             * bigger is malformed long before it is that large. */
            if (plen == 0u || plen > 65536u)
                malformed(off, "META payload empty or over 64 KB");
            char *meta = se_host_alloc((size_t)plen + 1u);
            size_t mgot = fread(meta, 1u, plen, f);
            if (mgot != plen) {
                fprintf(stderr,
                        "sahara-emu: --replay torn tail: incomplete record "
                        "at offset %" PRIu64 ", %zu bytes discarded\n",
                        off, 8u + mgot);
                se_host_free(meta, (size_t)plen + 1u);
                break;
            }
            meta[plen] = '\0';
            if (memchr(meta, '\0', plen) != NULL || meta[plen - 1u] != '\n')
                malformed(off, "META payload has NUL or no final LF");
            meta_check_grammar(meta, off);
            meta_expect(meta, "trace", "1");
            meta_expect(meta, "encoding", SE_ENCODING_SPEC_VERSION);
            meta_expect(meta, "image_sha256", sha_hex);
            se_host_free(meta, (size_t)plen + 1u);
            saw_meta = true;
            records++;
            off += 8u + plen;
            continue;
        }
        /* Types 1-6: stream the payload (fseek cannot detect a torn
         * tail), keeping the leading bytes every field check needs --
         * cycle at 0, EVENT inner length at 16, EXEC flags at 48 --
         * plus the largest EVENT inner payload (a NIC frame). */
        uint8_t head[20u + SE_NIC_FRAME_MAX] = { 0 };
        uint8_t chunk[4096];
        size_t total = 0;
        while (total < plen) {
            size_t want = plen - total;
            if (want > sizeof chunk)
                want = sizeof chunk;
            size_t r = fread(chunk, 1u, want, f);
            if (r > 0u && total < sizeof head) {
                size_t keep = sizeof head - total;
                if (keep > r)
                    keep = r;
                memcpy(head + total, chunk, keep);
            }
            total += r;
            if (r < want)
                break;
        }
        if (total < plen) {
            fprintf(stderr,
                    "sahara-emu: --replay torn tail: incomplete record at "
                    "offset %" PRIu64 ", %zu bytes discarded\n",
                    off, 8u + total);
            break;
        }
        uint64_t cycle = get_u64(head);
        if (records > 1u && cycle < prev_cycle)
            malformed(off, "record cycle decreases");
        prev_cycle = cycle;
        if (type == 1u && (head[48] & 0xF8u) != 0u)
            malformed(off, "nonzero EXEC flags bits 7:3");
        if (type == 5u) {
            uint32_t inner = 0;
            for (unsigned i = 0; i < 4u; i++)
                inner |= (uint32_t)head[16u + i] << (8u * i);
            if (inner != plen - 20u)
                malformed(off, "EVENT inner payload_len mismatch");
            uint64_t device = get_u64(head + 8u);
            validate_event(off, device, inner, head + 20u);
            evs = ev_grow(evs, &ev_cap, ev_count);
            SeEvRec *e = &evs[ev_count++];
            e->cycle = cycle;
            e->device = (uint8_t)device;
            e->len = (uint16_t)inner;
            memcpy(e->payload, head + 20u, inner);
        }
        records++;
        off += 8u + plen;
    }
    if (!saw_meta)
        die("--replay file has no META record");
    fclose(f);
    *count_out = ev_count;
    return evs;
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
    if (ram % 0x10000u != 0u)
        die("--ram must be a multiple of 64 KB (devspec/boot.md 3.4)");
    if (ram > 0x10000000ull)
        die("--ram above 256 MB needs a second RAM region above the "
            "pixel buffer; not implemented (SPEC-ISSUES 32)");
    uint64_t region_len = ram > se_lo64(SE_PLAT_RAM_MAX)
                              ? se_lo64(SE_PLAT_RAM_MAX)
                              : ram;

    SeMem mem;
    SeMem_init(&mem, region_len);
    se_plat_write_devtable(&mem, region_len);

    se_u128 entry = 0;
    uint8_t sha[32];
    const char *err = se_image_load(&mem, image, &entry, sha);
    if (err)
        die(err);
    char sha_hex[65];
    for (unsigned i = 0; i < 32u; i++)
        snprintf(sha_hex + 2u * i, 3u, "%02x", sha[i]);

    SeEvRec *evs = NULL;
    uint64_t ev_count = 0;
    if (replay_path)
        evs = validate_replay(replay_path, sha_hex, &ev_count);

    SeTrace tr = { .f = NULL, .level = level };
    if (trace_path) {
        tr.f = fopen(trace_path, "wb");
        if (!tr.f)
            die("cannot open --trace output file");
        meta_record(&tr, image, sha_hex, level, replay_path != NULL);
    }

    if (devorder > (1ull << 20))
        die("--check-devorder depth over 2^20 (bound the queue alloc)");

    SeDev dev;
    SeDev_reset(&dev);
    dev.mem = &mem; /* NIC RX exposure writes through the device */

    SeCpu *cpu = se_host_alloc(sizeof *cpu); /* one startup allocation */
    SeCpu_reset(cpu, &mem, &tr);
    cpu->dev = &dev;
    cpu->ev = evs;
    cpu->ev_count = ev_count;
    cpu->check_invtp = check_invtp;
    cpu->devorder_depth = devorder;
    if (devorder != 0u)
        cpu->ordq = se_host_alloc((size_t)devorder * sizeof *cpu->ordq);

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
