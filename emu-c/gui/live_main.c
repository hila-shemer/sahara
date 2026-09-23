/* The live session shared by the interactive front ends: sahara-gui
 * (gui/be_sdl.c, the platform's interactive face, emu-c-prompt.md;
 * design fixed by emu-c-gui-frontend-prompt.md) and sahara-serve
 * (gui/be_svp.c, the same session driven by a remote viewer; see
 * gui/live.h and docs/2026-09-23-remote-frontend-plan.md). Until the
 * split, this file was sdl_main.c; the backend calls below replaced its
 * SDL calls one for one.
 *
 *   sahara-gui|sahara-serve [IMAGE] [--rom PATH] [--serve-image PATH]
 *              [--trace OUT.trc] [--trace-level {0,1,2}]
 *              [--hz N] [--ram BYTES] [--maxcycles N] [--script FILE]
 *              [--nic host|off|fake] [--untethered]
 *
 * No IMAGE boots the embedded netboot ROM (rom/netboot/), which
 * fetches a boot image over SBP/1 from the local plane's 10.0.2.2:69
 * - the file --serve-image names. Mechanism is materialize-then-load:
 * the ROM bytes are written next to the trace as
 * <trace-basename>.rom.img (untethered-<epoch>.rom.img under
 * --untethered, which has no trace) and loaded through the ordinary
 * image loader, so META image_sha256, --replay validation and the printed
 * replay command work unchanged and the (trace, rom) pair is
 * self-contained on disk. --rom PATH substitutes a ROM file; IMAGE
 * plus --rom together is a usage error. The frozen headless CLI is
 * untouched: replay is always `sahara-emu <rom file> --replay ...`
 * with the path explicit.
 *
 * The front end is a device-event author: host input is translated
 * (gui/translate.c) and fed through SeCpu_feed, where the unchanged
 * boundary path applies, drop-flags and records it -- so the session
 * trace replays byte-identically under the frozen headless CLI. The
 * NIC is the fourth author: the doorbell hook runs the sans-IO
 * translator (gui/nic.c) and every arrival -- synthesized reply or
 * socket return traffic -- enters the machine only as a fed EVENT, so
 * a networked session replays offline. --nic defaults to host live
 * (images are trusted by default; gui/nic-notes.md) and to off under
 * --script, where host is rejected: the scripted gate is socket-free
 * by construction.
 * Recording is mandatory (default session-<timestamp>.trc, level 0);
 * on exit the exact reproducing `sahara-emu --replay` command is
 * printed. --untethered is the one owner-sanctioned opt-out
 * (untethered-mode-prompt.md, SPEC-ISSUES 44): the recorder is never
 * attached (g.tr.f stays NULL, the same off switch headless uses
 * without --trace), so no trace, no META, no replay command - the
 * session is announced as unreproducible at startup AND exit, and
 * combining it with --trace/--trace-level is a startup error.
 * This binary is the only component that reads real time,
 * and only to timestamp events into virtual cycles: the wall<->cycle
 * map is a pacing heuristic, never semantics.
 *
 * --script (test-only) swaps the backend's input and clock for a line
 * script and a fake millisecond counter: same translation, feeding,
 * pacing and rendering code, deterministic end to end. Grammar (one
 * command per line, '#' comments):
 *   wait MS | keydown U | keyup U | keyrepeat U | mouse X Y BTN |
 *   focuslost | close        (U = page-7 usage, BTN = sahara mask)
 *
 * This TU keeps sdl_main.c's carve-out (allow_banned: stdio, getrandom,
 * strtoull) and is linked with exactly one backend; everything
 * unit-testable lives in gui_core, under full doctrine. */
#include <inttypes.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/random.h>
#include <time.h>

#include "cpu.h"
#include "dev.h"
#include "gen/sahara_isa.h"
#include "gen/spec_version.h"
#include "gui/blit.h"
#include "gui/live.h"
#include "gui/netboot_rom.h"
#include "gui/nic.h"
#include "gui/nic_fake.h"
#include "gui/nic_host.h"
#include "gui/translate.h"
#include "hostmem.h"
#include "image.h"
#include "mem.h"
#include "platform.h"
#include "trace.h"
#include "u128.h"

#define PLATFORM_SPEC_VERSION "1.0-draft" /* trace.md 2.3.7, as main.c */
#define DEFAULT_RAM (256ull * 1024u * 1024u)
#define DEFAULT_HZ 2000000ull /* SPEC-ISSUES 38 */
#define CHUNK_MS 16u          /* UI pump tick */
#define IDLE_TICK_MS 250      /* housekeeping wake while WFI-idle */

static void die(const char *msg)
{
    fprintf(stderr, "%s: %s\n", se_live_prog, msg);
    exit(1);
}

static uint64_t parse_u64(const char *s, const char *what)
{
    char *end = NULL;
    unsigned long long v = strtoull(s, &end, 0);
    if (!end || *end != '\0' || end == s) {
        fprintf(stderr, "%s: bad %s: %s\n", se_live_prog, what, s);
        exit(1);
    }
    return (uint64_t)v;
}

typedef enum NicMode {
    NIC_OFF = 0, /* dead wire: hook NULL, exactly the pre-NIC phase */
    NIC_HOST,    /* real sockets (nic_host.c); the live default */
    NIC_FAKE,    /* echo backend (nic_fake.c); test-only */
} NicMode;

typedef struct SeLive Gui;

struct SeLive {
    SeMem mem;
    SeDev dev;
    SeTrace tr;
    SeCpu *cpu;
    SeGxl xl;
    NicMode nic_mode;
    SeNic nic;
    SeNicFake nic_fake;
    SeNicHost nic_host;
    /* Stamp for the next fed NIC frame: doorbell cycle + 1 inside the
     * TX hook (nic.md 7.1 rules 3/5), pump_earliest during the pump
     * sweep -- socket return traffic rides the same stamping rule as
     * keyboard input, WFI-idle included (NIC-C-36 for free). */
    uint64_t nic_earliest;
    uint64_t hz; /* cycles per wall second; 0 = free-run */
    uint64_t maxcycles;
    /* pacing anchor: cycle c0 was reached at wall time t0_ms */
    uint64_t t0_ms, c0;
    /* fake host (--script): event source + clock */
    bool script_mode;
    char *script; /* whole file, NUL-terminated; pos walks it */
    size_t script_pos;
    uint64_t fake_now_ms;
    /* host side: pointer grab state lives in the backend */
    uint8_t *staging; /* 4 * W * H frame snapshot */
    bool quit;         /* window closed / script ended */
    bool out_of_cycles;
    /* one stamp per pump iteration: all events polled together feed
     * at the same cycle, in poll order (work-order rule 3/8) */
    uint64_t pump_earliest;
    /* --script fake entropy source (rng.md 7.5): a fixed-seed
     * SplitMix64 stands in for getrandom so the scripted gate never
     * touches real entropy and double-runs stay byte-identical. */
    uint64_t script_rng_state;
};

static uint64_t now_ms(const Gui *g)
{
    return g->script_mode ? g->fake_now_ms : SeLiveBe_now_ms();
}

static uint64_t cycle_target(const Gui *g, uint64_t now)
{
    if (g->hz == 0u)
        return UINT64_MAX; /* free-run */
    return g->c0 + (now - g->t0_ms) * g->hz / 1000u;
}

/* ------------------------------------------------------------ feeding */

static void feed_events(Gui *g, const SeGxlEv *evs, uint32_t n)
{
    for (uint32_t i = 0; i < n; i++)
        SeCpu_feed(g->cpu, evs[i].device, evs[i].payload,
                   SE_GXL_EV_BYTES, g->pump_earliest);
}

static void host_key(Gui *g, uint32_t usage, bool press, bool repeat)
{
    SeGxlEv ev;
    feed_events(g, &ev, SeGxl_key(&g->xl, usage, press, repeat, &ev));
}

static void host_mouse(Gui *g, int64_t x, int64_t y, uint8_t buttons)
{
    SeGxlEv ev;
    feed_events(g, &ev,
                SeGxl_mouse(&g->xl, x, y, buttons, g->dev.disp_width,
                            g->dev.disp_height, &ev));
}

/* Deliver one translator-synthesized RX frame: fed like any other
 * host event, applied and recorded by the unchanged boundary path. */
static void gui_nic_deliver(void *ctx, const uint8_t *frame, uint16_t len)
{
    Gui *g = ctx;
    SeCpu_feed(g->cpu, SE_DEVIDX_NIC, frame, len, g->nic_earliest);
}

/* The SeDev TX hook: capture TX buffer bytes [0, len) synchronously
 * (the guest cannot run until the doorbell store completes -- nic.md
 * 2.2's rule for free) and classify. Local replies feed at doorbell
 * cycle + 1: strictly after the trigger (nic.md 7.1 rule 3) and the
 * reference "+1" policy under --script's fake clock (rule 5). */
static void gui_nic_tx(void *ctx, uint32_t len)
{
    Gui *g = ctx;
    uint8_t buf[SE_NIC_FRAME_MAX];
    for (uint32_t i = 0; i < len; i++)
        buf[i] = (uint8_t)se_lo64(
            SeMem_read(&g->mem, SE_PLAT_NIC_TXBUF + i, 1u));
    g->nic_earliest = se_lo64(g->cpu->cycle) + 1u;
    SeNic_tx(&g->nic, buf, (uint16_t)len);
}

/* One nonblocking backend sweep per pump tick, stamped exactly like
 * the input batch polled alongside it. During WFI idle the 250 ms
 * housekeeping tick bounds arrival latency (nic-notes.md). */
static void nic_pump(Gui *g)
{
    if (g->nic_mode == NIC_OFF)
        return;
    g->nic_earliest = g->pump_earliest;
    if (g->nic_mode == NIC_FAKE)
        SeNicFake_pump(&g->nic_fake, &g->nic);
    else
        SeNicHost_pump(&g->nic_host, &g->nic);
}

/* RNG watermark top-up (rng.md 7.5, non-normative reference policy):
 * one 32-word batch whenever guest-visible depth is below 64, stamped
 * like the input batch polled alongside it. Arrival depth therefore
 * never exceeds 95, so live truncation cannot happen and every fed
 * word is recorded (the apply path IS the recording path). Under
 * --script the words come from a fixed-seed SplitMix64 instead of
 * getrandom: the scripted gate is real-entropy-free by construction,
 * exactly like --nic fake. */
#define RNG_BATCH_WORDS 32u
#define RNG_WATERMARK 64u

static void rng_topup(Gui *g)
{
    if (g->dev.rng_count >= RNG_WATERMARK)
        return;
    uint8_t buf[RNG_BATCH_WORDS * 8u];
    if (g->script_mode) {
        for (unsigned w = 0; w < RNG_BATCH_WORDS; w++) {
            g->script_rng_state += 0x9E3779B97F4A7C15ull;
            uint64_t z = g->script_rng_state;
            z ^= z >> 30;
            z *= 0xBF58476D1CE4E5B9ull;
            z ^= z >> 27;
            z *= 0x94D049BB133111EBull;
            z ^= z >> 31;
            for (unsigned i = 0; i < 8u; i++)
                buf[8u * w + i] = (uint8_t)(z >> (8u * i));
        }
    } else {
        size_t got = 0;
        while (got < sizeof buf) {
            ssize_t r = getrandom(buf + got, sizeof buf - got, 0);
            if (r < 0)
                die("getrandom failed");
            got += (size_t)r;
        }
    }
    SeCpu_feed(g->cpu, SE_DEVIDX_RNG, buf, (uint16_t)sizeof buf,
               g->pump_earliest);
}

/* Capture loss for any reason (focus loss, release chord): the guest
 * must never observe stuck keys or buttons (input.md 2.6, Appendix A). */
static void capture_lost(Gui *g)
{
    SeGxlEv burst[SE_GXL_MAX_BURST];
    feed_events(g, burst, SeGxl_capture_lost(&g->xl, burst));
    SeLiveBe_release_capture();
}

/* ----------------------------------------------- backend entry points */

void SeLive_host_key(SeLive *lv, uint32_t usage, bool press, bool repeat)
{
    host_key(lv, usage, press, repeat);
}

void SeLive_host_mouse(SeLive *lv, int64_t x, int64_t y, uint8_t buttons)
{
    host_mouse(lv, x, y, buttons);
}

void SeLive_host_capture_lost(SeLive *lv)
{
    capture_lost(lv);
}

void SeLive_host_quit(SeLive *lv)
{
    lv->quit = true;
}

bool SeLive_chord(const SeLive *lv)
{
    return SeGxl_chord(&lv->xl);
}

/* ---------------------------------------------------- script host side */

static char *script_next_line(Gui *g)
{
    while (g->script[g->script_pos] != '\0') {
        char *line = g->script + g->script_pos;
        char *nl = strchr(line, '\n');
        if (nl) {
            *nl = '\0';
            g->script_pos = (size_t)(nl - g->script) + 1u;
        } else {
            g->script_pos += strlen(line);
        }
        char *p = line;
        while (*p == ' ' || *p == '\t')
            p++;
        if (*p != '\0' && *p != '#')
            return p;
    }
    return NULL;
}

/* Apply one script command; returns false when the session should
 * close (explicit `close` or end of script). Script events bypass the
 * capture/focus UX -- the script IS the fake host. */
static bool script_command(Gui *g)
{
    char *line = script_next_line(g);
    if (!line)
        return false;
    char *sp = strchr(line, ' ');
    const char *a1 = NULL;
    if (sp) {
        *sp = '\0';
        a1 = sp + 1u;
    }
    if (strcmp(line, "close") == 0)
        return false;
    if (strcmp(line, "focuslost") == 0) {
        capture_lost(g);
        return true;
    }
    if (!a1)
        die("script: command missing its argument");
    if (strcmp(line, "wait") == 0) {
        g->fake_now_ms += parse_u64(a1, "script wait");
        return true;
    }
    if (strcmp(line, "keydown") == 0 || strcmp(line, "keyup") == 0 ||
        strcmp(line, "keyrepeat") == 0) {
        uint64_t usage = parse_u64(a1, "script usage");
        host_key(g, (uint32_t)usage, line[3] != 'u',
                 strcmp(line, "keyrepeat") == 0);
        return true;
    }
    if (strcmp(line, "mouse") == 0) {
        char *rest = NULL;
        long long x = strtoll(a1, &rest, 0);
        long long y = strtoll(rest, &rest, 0);
        unsigned long long b = strtoull(rest, &rest, 0);
        if (rest && *rest != '\0')
            die("script: bad mouse line");
        host_mouse(g, x, y, (uint8_t)b);
        return true;
    }
    die("script: unknown command");
    return false;
}

/* ------------------------------------------------------------- render */

static void render_if_pending(Gui *g)
{
    if (!g->dev.present_pending)
        return; /* no PRESENT since the last repaint: nothing to do */
    g->dev.present_pending = false;
    uint64_t w = g->dev.disp_width, h = g->dev.disp_height;
    SeGuiBlit_frame(&g->mem, w, h, g->dev.disp_stride, g->staging);
    SeLiveBe_present(g->staging, w, h);
}

/* ------------------------------------------------------------ stepping */

/* Step until the pacing target, the chunk deadline, an idle WFI, halt,
 * or --maxcycles. Returns false when the run is over. */
static bool step_chunk(Gui *g, uint64_t target)
{
    uint64_t deadline =
        g->script_mode ? 0u : SeLiveBe_now_ms() + CHUNK_MS;
    while (g->cpu->state == SE_RUN_RUNNING && !g->cpu->wfi_idle &&
           se_lo64(g->cpu->cycle) < target) {
        if (g->maxcycles != 0u &&
            g->cpu->cycle >= (se_u128)g->maxcycles) {
            g->out_of_cycles = true;
            return false;
        }
        SeCpu_step(g->cpu);
        /* Check the wall clock once per ~4k cycles, not per step. */
        if (!g->script_mode && (se_lo64(g->cpu->cycle) & 0xFFFu) == 0u &&
            SeLiveBe_now_ms() >= deadline)
            break;
    }
    return g->cpu->state == SE_RUN_RUNNING;
}

/* ---------------------------------------------------------------- meta */

/* Slurp a whole binary file (the --serve-image blob); the blob is
 * handed to the sans-IO translator as bytes, so nic.c stays file-free
 * and the service is backend-independent by construction. */
static uint8_t *read_blob(const char *path, uint32_t *len_out)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        die("cannot open --serve-image file");
    if (fseek(f, 0, SEEK_END) != 0)
        die("cannot size --serve-image file");
    long flen = ftell(f);
    if (flen < 0)
        die("cannot size --serve-image file");
    if ((unsigned long)flen > 0xFFFFFFFFul)
        die("--serve-image file exceeds 4 GB");
    if (fseek(f, 0, SEEK_SET) != 0)
        die("cannot size --serve-image file");
    uint8_t *buf = se_host_alloc((size_t)flen + 1u);
    if (fread(buf, 1u, (size_t)flen, f) != (size_t)flen)
        die("cannot read --serve-image file");
    fclose(f);
    *len_out = (uint32_t)flen;
    return buf;
}

static void meta_record(SeTrace *tr, const char *image_arg,
                        const char *sha_hex, int level)
{
    char buf[640];
    int n = snprintf(buf, sizeof buf,
                     "trace=1\n"
                     "encoding=" SE_ENCODING_SPEC_VERSION "\n"
                     "level=%d\n"
                     "mode=live\n"
                     "image=%s\n"
                     "image_sha256=%s\n"
                     "platform=" PLATFORM_SPEC_VERSION "\n",
                     level, image_arg, sha_hex);
    if (n < 0 || (size_t)n >= sizeof buf)
        die("META record overflow");
    SeTrace_meta(tr, buf, (uint32_t)n);
}

/* Decision 3 of the untethered work order: loud, twice. The banner is
 * one fixed line on stderr at startup and again at exit, so nobody
 * discovers after the fact that a session left no artifact. */
static void untethered_banner(void)
{
    fprintf(stderr, "untethered session: not recorded, not replayable\n");
}

int main(int argc, char **argv)
{
    const char *image = NULL, *trace_path = NULL, *script_path = NULL;
    const char *nic_arg = NULL, *rom_path = NULL, *serve_path = NULL;
    uint64_t maxcycles = 0, ram = DEFAULT_RAM, hz = DEFAULT_HZ;
    int level = 0; /* the cheapest legal level (SPEC-ISSUES 39) */
    bool untethered = false, level_arg = false;

    for (int i = 1; i < argc; i++) {
        const char *a = argv[i];
        if (strcmp(a, "--trace") == 0 && i + 1 < argc) {
            trace_path = argv[++i];
        } else if (strcmp(a, "--trace-level") == 0 && i + 1 < argc) {
            uint64_t v = parse_u64(argv[++i], "--trace-level");
            if (v > 2u)
                die("--trace-level must be 0..2");
            level = (int)v;
            level_arg = true;
        } else if (strcmp(a, "--untethered") == 0) {
            untethered = true;
        } else if (strcmp(a, "--hz") == 0 && i + 1 < argc) {
            hz = parse_u64(argv[++i], "--hz");
        } else if (strcmp(a, "--maxcycles") == 0 && i + 1 < argc) {
            maxcycles = parse_u64(argv[++i], "--maxcycles");
        } else if (strcmp(a, "--ram") == 0 && i + 1 < argc) {
            ram = parse_u64(argv[++i], "--ram");
        } else if (strcmp(a, "--script") == 0 && i + 1 < argc) {
            script_path = argv[++i];
        } else if (strcmp(a, "--nic") == 0 && i + 1 < argc) {
            nic_arg = argv[++i];
        } else if (strcmp(a, "--rom") == 0 && i + 1 < argc) {
            rom_path = argv[++i];
        } else if (strcmp(a, "--serve-image") == 0 && i + 1 < argc) {
            serve_path = argv[++i];
        } else if (a[0] == '-') {
            fprintf(stderr, "%s: unknown option %s\n", se_live_prog, a);
            return 1;
        } else if (!image) {
            image = a;
        } else {
            die("more than one IMAGE argument");
        }
    }
    if (image && rom_path)
        die("usage: IMAGE and --rom are mutually exclusive (no IMAGE "
            "boots the embedded netboot ROM; --rom substitutes a ROM "
            "file)");
    /* Not a silent override in either direction (work-order decision
     * 2): asking to record and to not-record is a contradiction the
     * user resolves, not us. */
    if (untethered && (trace_path || level_arg))
        die("--untethered never records: it cannot be combined with "
            "--trace/--trace-level (drop them, or drop --untethered)");
    /* Mode-dependent default: bridging is the point of a live
     * session; the scripted gate is socket-free by construction, so
     * host is not even accepted there. */
    NicMode nic_mode;
    if (!nic_arg)
        nic_mode = script_path ? NIC_OFF : NIC_HOST;
    else if (strcmp(nic_arg, "host") == 0)
        nic_mode = NIC_HOST;
    else if (strcmp(nic_arg, "off") == 0)
        nic_mode = NIC_OFF;
    else if (strcmp(nic_arg, "fake") == 0)
        nic_mode = NIC_FAKE;
    else {
        die("--nic must be host, off, or fake");
        return 1;
    }
    if (script_path && nic_mode == NIC_HOST)
        die("--nic host is rejected under --script (the scripted gate "
            "must be deterministic and socket-free); use fake or off");
    /* RAM legality mirrors sahara-emu exactly (SPEC-ISSUES 34). */
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

    /* Recording is mandatory: it is the session's source of truth.
     * Resolved before the image because the materialized ROM's name
     * derives from the trace path. --untethered never records: the
     * path stays NULL (the recorder below never attaches) and the
     * materialized ROM falls back to its own timestamp name. */
    char default_trace[64];
    if (!untethered && !trace_path) {
        snprintf(default_trace, sizeof default_trace,
                 "session-%llu.trc",
                 (unsigned long long)time(NULL));
        trace_path = default_trace;
    }

    /* Materialize-then-load: with no IMAGE and no --rom, write the
     * embedded ROM bytes next to the trace and load that file through
     * the ordinary loader. Everything downstream - META image_sha256,
     * the printed replay command, --replay validation - sees a plain
     * image file; the frozen headless binary needs no default-ROM
     * behavior. */
    char rom_file[576];
    if (!image && rom_path) {
        image = rom_path;
    } else if (!image) {
        /* Under --untethered there is no trace for the ROM to sit
         * next to; fall back to the same timestamp convention
         * (untethered-<epoch>.rom.img) so the one artifact the
         * session must leave - the bytes the loader hashed - is
         * still findable and its provenance is in the name. */
        char untethered_base[64];
        const char *rom_base = trace_path;
        if (!rom_base) {
            snprintf(untethered_base, sizeof untethered_base,
                     "untethered-%llu",
                     (unsigned long long)time(NULL));
            rom_base = untethered_base;
        }
        size_t tl = strlen(rom_base);
        if (tl >= 4u && strcmp(rom_base + tl - 4u, ".trc") == 0)
            tl -= 4u;
        int n = snprintf(rom_file, sizeof rom_file, "%.*s.rom.img",
                         (int)tl, rom_base);
        if (n < 0 || (size_t)n >= sizeof rom_file)
            die("trace path too long for the materialized ROM name");
        FILE *rf = fopen(rom_file, "wb");
        if (!rf)
            die("cannot write the materialized ROM image");
        if (fwrite(se_netboot_rom, 1u, se_netboot_rom_len, rf) !=
                se_netboot_rom_len ||
            fclose(rf) != 0)
            die("cannot write the materialized ROM image");
        image = rom_file;
    }

    static Gui g; /* one instance; zero-initialized */
    g.hz = hz;
    g.maxcycles = maxcycles;
    SeMem_init(&g.mem, region_len);
    se_plat_write_devtable(&g.mem, region_len);

    se_u128 entry = 0;
    uint8_t sha[32];
    const char *err = se_image_load(&g.mem, image, &entry, sha);
    if (err)
        die(err);
    char sha_hex[65];
    for (unsigned i = 0; i < 32u; i++)
        snprintf(sha_hex + 2u * i, 3u, "%02x", sha[i]);
    /* --untethered is the sanctioned opt-out of mandatory recording:
     * g.tr.f stays NULL, which is the recorder's existing off switch
     * (every SeTrace_* call no-ops on it, exactly
     * headless-without---trace), so nothing is attached and nothing is
     * emitted on the hot path. */
    if (untethered) {
        untethered_banner();
    } else {
        g.tr.level = level;
        g.tr.f = fopen(trace_path, "wb");
        if (!g.tr.f)
            die("cannot open trace output file");
        /* Level 0 at 2 MHz is still one EXEC per instruction: give
         * stdio a real buffer so fwrite-per-record never gates
         * throughput. */
        setvbuf(g.tr.f, NULL, _IOFBF, 1u << 20);
        meta_record(&g.tr, image, sha_hex, level);
    }

    if (script_path) {
        g.script_mode = true;
        FILE *sf = fopen(script_path, "rb");
        if (!sf)
            die("cannot open --script file");
        fseek(sf, 0, SEEK_END);
        long slen = ftell(sf);
        if (slen < 0)
            die("cannot size --script file");
        fseek(sf, 0, SEEK_SET);
        g.script = se_host_alloc((size_t)slen + 1u);
        if (fread(g.script, 1u, (size_t)slen, sf) != (size_t)slen)
            die("cannot read --script file");
        g.script[slen] = '\0';
        fclose(sf);
    }

    SeDev_reset(&g.dev);
    g.dev.mem = &g.mem; /* NIC RX exposure writes through the device */
    g.cpu = se_host_alloc(sizeof *g.cpu);
    SeCpu_reset(g.cpu, &g.mem, &g.tr);
    g.cpu->dev = &g.dev;
    g.cpu->live_yield = true; /* live WFI idles instead of halting */
    SeGxl_reset(&g.xl);
    g.nic_mode = nic_mode;
    if (nic_mode != NIC_OFF) {
        if (nic_mode == NIC_FAKE) {
            SeNicFake_reset(&g.nic_fake);
            SeNic_reset(&g.nic, gui_nic_deliver, &g, SeNicFake_send,
                        &g.nic_fake);
        } else {
            SeNicHost_init(&g.nic_host);
            SeNic_reset(&g.nic, gui_nic_deliver, &g, SeNicHost_send,
                        &g.nic_host);
        }
        g.dev.tx_doorbell = gui_nic_tx;
        g.dev.tx_ctx = &g;
        /* SBP boot-image service: configured only when --serve-image
         * names a blob; the unconfigured service answers ERR 1 (loud,
         * rom/netboot/sbp.md). Blob bytes live for the whole run. */
        if (serve_path) {
            uint32_t blob_len = 0;
            uint8_t *blob = read_blob(serve_path, &blob_len);
            SeNic_serve_image(&g.nic, blob, blob_len, true);
        }
    }

    /* Window at the reset mode, non-resizable: META cannot carry a
     * display mode, so replay depends on the fixed reset default
     * (display.md 1); resize is deferred to v2 (frontend-notes.md). */
    uint64_t win_w = g.dev.disp_width, win_h = g.dev.disp_height;
    SeLiveBe_init(&g, win_w, win_h, g.script_mode);
    g.staging = se_host_alloc(4u * win_w * win_h);

    g.t0_ms = now_ms(&g);
    g.c0 = 0;

    /* Session-start entropy batch (rng.md 7.5): fed at cycle 0, so a
     * guest that reads STATUS early already sees a stocked well. */
    rng_topup(&g);

    /* The throttled chunked loop (work-order rule 7): step to the
     * pacing target in <=16 ms slices, pump host input, repaint on
     * PRESENT, sleep to the next tick; block properly while the guest
     * idles in WFI (rule 8). */
    bool running = true;
    while (running && !g.quit) {
        uint64_t now = now_ms(&g);
        uint64_t target = cycle_target(&g, now);
        uint64_t cyc = se_lo64(g.cpu->cycle);
        /* >100 ms of virtual time behind: slew the anchor forward
         * rather than bursting to catch up. Live-mode only -- under
         * --script a `wait` is exactly a deterministic burst. */
        if (!g.script_mode && g.hz != 0u && target > cyc &&
            target - cyc > g.hz / 10u) {
            g.t0_ms = now;
            g.c0 = cyc;
            target = cycle_target(&g, now);
        }
        running = step_chunk(&g, target);

        /* One stamp for everything polled this iteration: batch =
         * same cycle, poll order = record order. While WFI-idle the
         * stamp tracks the pacing clock, so virtual time keeps moving
         * with the wall during long idles (rule 8, SPEC-ISSUES 36). */
        cyc = se_lo64(g.cpu->cycle);
        g.pump_earliest =
            g.cpu->wfi_idle ? (target > cyc ? target : cyc + 1u) : 0u;

        if (g.script_mode) {
            if (running && !script_command(&g))
                g.quit = true;
        } else {
            SeLiveBe_poll(&g);
        }
        /* NIC backend sweep after input: one deterministic poll order
         * per tick (input batch, then flow-order return traffic),
         * then the entropy watermark - last, so its batch lands after
         * everything else fed this tick at the same stamp. */
        nic_pump(&g);
        rng_topup(&g);
        render_if_pending(&g);
        if (!running || g.quit)
            break;
        if (g.script_mode)
            continue; /* fake clock: no sleeping, no blocking */
        if (g.cpu->wfi_idle) {
            /* Nothing to execute until input arrives. If a timer is
             * armed, wake when the pacing clock will reach timecmp;
             * else sleep on the event queue with a housekeeping
             * tick. (A reachable armed timer never yields -- this
             * timeout only covers arming races.) */
            int timeout = IDLE_TICK_MS;
            uint64_t tc = se_lo64(g.cpu->sreg[SREG_TIMECMP]);
            if (g.hz != 0u && tc != 0u && tc > g.c0) {
                uint64_t ms = (tc - g.c0) * 1000u / g.hz;
                uint64_t due = g.t0_ms + ms;
                uint64_t now2 = SeLiveBe_now_ms();
                timeout = due > now2 ? (int)(due - now2) : 1;
            }
            SeLiveBe_wait_input(timeout);
        } else {
            uint64_t now2 = SeLiveBe_now_ms();
            uint64_t next = now + CHUNK_MS;
            if (next > now2)
                SeLiveBe_delay(next - now2);
        }
    }

    /* Finalize: flush the trace, then print the exact replaying
     * invocation -- --maxcycles pins the endpoint so a session ended
     * by window close terminates under replay too. Untethered has
     * nothing to finalize and nothing that could replay: it repeats
     * the banner instead, the second half of the loud-twice rule. */
    if (untethered) {
        untethered_banner();
    } else {
        if (fclose(g.tr.f) != 0)
            die("error closing trace file");
        uint64_t end_cycle = se_lo64(g.cpu->cycle);
        if (end_cycle == 0u)
            end_cycle = 1u; /* --maxcycles 0 means unlimited */
        printf("sahara-emu %s --replay %s --trace %s.replay.trc "
               "--trace-level %d --ram %" PRIu64 " --maxcycles %" PRIu64
               "\n",
               image, trace_path, trace_path, level, ram, end_cycle);
    }

    SeLiveBe_fini();

    if (g.out_of_cycles) {
        printf("MAXCYCLES\n");
        return 2;
    }
    if (g.cpu->state == SE_RUN_HALT) {
        if (g.cpu->halt_note)
            fprintf(stderr, "%s: note: %s\n", se_live_prog,
                    g.cpu->halt_note);
        printf("HALT r0=%016" PRIx64 "%016" PRIx64 "\n",
               se_hi64(g.cpu->r[0]), se_lo64(g.cpu->r[0]));
        return 0;
    }
    return 0; /* window closed / script ended mid-run: clean exit */
}
