/* sahara-gui: the interactive SDL2 front end (the platform's
 * interactive face, emu-c-prompt.md; design fixed by
 * emu-c-gui-frontend-prompt.md).
 *
 *   sahara-gui IMAGE [--trace OUT.trc] [--trace-level {0,1,2}]
 *              [--hz N] [--ram BYTES] [--maxcycles N] [--script FILE]
 *
 * The front end is a device-event author: host input is translated
 * (gui/translate.c) and fed through SeCpu_feed, where the unchanged
 * boundary path applies, drop-flags and records it -- so the session
 * trace replays byte-identically under the frozen headless CLI.
 * Recording is mandatory (default session-<timestamp>.trc, level 0);
 * on exit the exact reproducing `sahara-emu --replay` command is
 * printed. This binary is the only component that reads real time,
 * and only to timestamp events into virtual cycles: the wall<->cycle
 * map is a pacing heuristic, never semantics.
 *
 * --script (test-only) swaps SDL's event queue and clock for a line
 * script and a fake millisecond counter: same translation, feeding,
 * pacing and rendering code, deterministic end to end. Grammar (one
 * command per line, '#' comments):
 *   wait MS | keydown U | keyup U | keyrepeat U | mouse X Y BTN |
 *   focuslost | close        (U = page-7 usage, BTN = sahara mask)
 *
 * This TU is the sanctioned SDL carve-out (allow_banned): everything
 * unit-testable lives in gui_core, under full doctrine. */
#include <SDL2/SDL.h>

#include <inttypes.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "cpu.h"
#include "dev.h"
#include "gen/sahara_isa.h"
#include "gen/spec_version.h"
#include "gui/blit.h"
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
    fprintf(stderr, "sahara-gui: %s\n", msg);
    exit(1);
}

static uint64_t parse_u64(const char *s, const char *what)
{
    char *end = NULL;
    unsigned long long v = strtoull(s, &end, 0);
    if (!end || *end != '\0' || end == s) {
        fprintf(stderr, "sahara-gui: bad %s: %s\n", what, s);
        exit(1);
    }
    return (uint64_t)v;
}

typedef struct Gui {
    SeMem mem;
    SeDev dev;
    SeTrace tr;
    SeCpu *cpu;
    SeGxl xl;
    uint64_t hz; /* cycles per wall second; 0 = free-run */
    uint64_t maxcycles;
    /* pacing anchor: cycle c0 was reached at wall time t0_ms */
    uint64_t t0_ms, c0;
    /* fake host (--script): event source + clock */
    bool script_mode;
    char *script; /* whole file, NUL-terminated; pos walks it */
    size_t script_pos;
    uint64_t fake_now_ms;
    /* SDL side */
    SDL_Window *win;
    SDL_Renderer *ren;
    SDL_Texture *tex;
    uint8_t *staging; /* 4 * W * H frame snapshot */
    bool captured;    /* pointer grabbed + hidden */
    uint8_t btn_mask; /* current sahara button state (live mode) */
    int32_t ptr_x, ptr_y;
    bool quit;         /* window closed / script ended */
    bool out_of_cycles;
    /* one stamp per pump iteration: all events polled together feed
     * at the same cycle, in poll order (work-order rule 3/8) */
    uint64_t pump_earliest;
} Gui;

static uint64_t now_ms(const Gui *g)
{
    return g->script_mode ? g->fake_now_ms : SDL_GetTicks64();
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

/* Capture loss for any reason (focus loss, release chord): the guest
 * must never observe stuck keys or buttons (input.md 2.6, Appendix A). */
static void capture_lost(Gui *g)
{
    SeGxlEv burst[SE_GXL_MAX_BURST];
    feed_events(g, burst, SeGxl_capture_lost(&g->xl, burst));
    if (g->captured) {
        g->captured = false;
        SDL_SetWindowGrab(g->win, SDL_FALSE);
        SDL_ShowCursor(SDL_ENABLE);
    }
    g->btn_mask = 0;
}

/* ------------------------------------------------------- SDL host side */

static uint8_t sdl_button_bit(uint8_t sdl_button)
{
    /* SDL numbers left/middle/right 1/2/3; the platform packs bit 0
     * left, bit 1 right, bit 2 middle (PLATFORM-SPEC 6). */
    switch (sdl_button) {
    case SDL_BUTTON_LEFT: return 1u;
    case SDL_BUTTON_RIGHT: return 2u;
    case SDL_BUTTON_MIDDLE: return 4u;
    default: return 0u; /* X1/X2: no field, discarded */
    }
}

static void handle_sdl_event(Gui *g, const SDL_Event *e)
{
    switch (e->type) {
    case SDL_QUIT:
        g->quit = true;
        return;
    case SDL_KEYDOWN:
    case SDL_KEYUP: {
        /* SDL scancodes are page-7 usages; the subset filter and the
         * alternation guard live in the translator. Keyboard capture
         * follows window focus (Appendix A): SDL only routes key
         * events to the focused window, so no extra gate is needed. */
        uint32_t usage = (uint32_t)e->key.keysym.scancode;
        host_key(g, usage, e->type == SDL_KEYDOWN, e->key.repeat != 0);
        if (g->captured && SeGxl_chord(&g->xl))
            capture_lost(g); /* left Ctrl+Alt releases the pointer */
        return;
    }
    case SDL_WINDOWEVENT:
        if (e->window.event == SDL_WINDOWEVENT_FOCUS_LOST)
            capture_lost(g);
        return;
    case SDL_MOUSEBUTTONDOWN:
        if (!g->captured) {
            /* Click-to-capture; the capturing click itself is
             * delivered to the guest (Appendix A). */
            g->captured = true;
            SDL_SetWindowGrab(g->win, SDL_TRUE);
            SDL_ShowCursor(SDL_DISABLE);
        }
        g->btn_mask |= sdl_button_bit(e->button.button);
        g->ptr_x = e->button.x;
        g->ptr_y = e->button.y;
        host_mouse(g, g->ptr_x, g->ptr_y, g->btn_mask);
        return;
    case SDL_MOUSEBUTTONUP:
        if (!g->captured)
            return;
        g->btn_mask &= (uint8_t)~sdl_button_bit(e->button.button);
        g->ptr_x = e->button.x;
        g->ptr_y = e->button.y;
        host_mouse(g, g->ptr_x, g->ptr_y, g->btn_mask);
        return;
    case SDL_MOUSEMOTION:
        if (!g->captured)
            return; /* uncaptured motion is invisible to the guest */
        g->ptr_x = e->motion.x;
        g->ptr_y = e->motion.y;
        host_mouse(g, g->ptr_x, g->ptr_y, g->btn_mask);
        return;
    default:
        return;
    }
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
    (void)SDL_UpdateTexture(g->tex, NULL, g->staging, (int)(4u * w));
    (void)SDL_RenderClear(g->ren);
    (void)SDL_RenderCopy(g->ren, g->tex, NULL, NULL);
    SDL_RenderPresent(g->ren);
}

/* ------------------------------------------------------------ stepping */

/* Step until the pacing target, the chunk deadline, an idle WFI, halt,
 * or --maxcycles. Returns false when the run is over. */
static bool step_chunk(Gui *g, uint64_t target)
{
    uint64_t deadline =
        g->script_mode ? 0u : SDL_GetTicks64() + CHUNK_MS;
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
            SDL_GetTicks64() >= deadline)
            break;
    }
    return g->cpu->state == SE_RUN_RUNNING;
}

/* ---------------------------------------------------------------- meta */

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

int main(int argc, char **argv)
{
    const char *image = NULL, *trace_path = NULL, *script_path = NULL;
    uint64_t maxcycles = 0, ram = DEFAULT_RAM, hz = DEFAULT_HZ;
    int level = 0; /* the cheapest legal level (SPEC-ISSUES 39) */

    for (int i = 1; i < argc; i++) {
        const char *a = argv[i];
        if (strcmp(a, "--trace") == 0 && i + 1 < argc) {
            trace_path = argv[++i];
        } else if (strcmp(a, "--trace-level") == 0 && i + 1 < argc) {
            uint64_t v = parse_u64(argv[++i], "--trace-level");
            if (v > 2u)
                die("--trace-level must be 0..2");
            level = (int)v;
        } else if (strcmp(a, "--hz") == 0 && i + 1 < argc) {
            hz = parse_u64(argv[++i], "--hz");
        } else if (strcmp(a, "--maxcycles") == 0 && i + 1 < argc) {
            maxcycles = parse_u64(argv[++i], "--maxcycles");
        } else if (strcmp(a, "--ram") == 0 && i + 1 < argc) {
            ram = parse_u64(argv[++i], "--ram");
        } else if (strcmp(a, "--script") == 0 && i + 1 < argc) {
            script_path = argv[++i];
        } else if (a[0] == '-') {
            fprintf(stderr, "sahara-gui: unknown option %s\n", a);
            return 1;
        } else if (!image) {
            image = a;
        } else {
            die("more than one IMAGE argument");
        }
    }
    if (!image)
        die("usage: sahara-gui IMAGE [--trace OUT.trc] [--trace-level N] "
            "[--hz N] [--ram BYTES] [--maxcycles N] [--script FILE]");
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

    /* Recording is mandatory: it is the session's source of truth. */
    char default_trace[64];
    if (!trace_path) {
        snprintf(default_trace, sizeof default_trace,
                 "session-%llu.trc",
                 (unsigned long long)time(NULL));
        trace_path = default_trace;
    }
    g.tr.level = level;
    g.tr.f = fopen(trace_path, "wb");
    if (!g.tr.f)
        die("cannot open trace output file");
    /* Level 0 at 2 MHz is still one EXEC per instruction: give stdio a
     * real buffer so fwrite-per-record never gates throughput. */
    setvbuf(g.tr.f, NULL, _IOFBF, 1u << 20);
    meta_record(&g.tr, image, sha_hex, level);

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

    /* Window at the reset mode, non-resizable: META cannot carry a
     * display mode, so replay depends on the fixed reset default
     * (display.md 1); resize is deferred to v2 (frontend-notes.md). */
    uint64_t win_w = g.dev.disp_width, win_h = g.dev.disp_height;
    if (SDL_Init(SDL_INIT_VIDEO) != 0)
        die("SDL_Init failed");
    g.win = SDL_CreateWindow("sahara", SDL_WINDOWPOS_UNDEFINED,
                             SDL_WINDOWPOS_UNDEFINED, (int)win_w,
                             (int)win_h, 0);
    if (!g.win)
        die("SDL_CreateWindow failed");
    g.ren = SDL_CreateRenderer(g.win, -1, 0);
    if (!g.ren)
        die("SDL_CreateRenderer failed");
    g.tex = SDL_CreateTexture(g.ren, SDL_PIXELFORMAT_ARGB8888,
                              SDL_TEXTUREACCESS_STREAMING, (int)win_w,
                              (int)win_h);
    if (!g.tex)
        die("SDL_CreateTexture failed");
    g.staging = se_host_alloc(4u * win_w * win_h);

    g.t0_ms = now_ms(&g);
    g.c0 = 0;

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
            SDL_Event e;
            while (SDL_PollEvent(&e))
                handle_sdl_event(&g, &e);
        }
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
                uint64_t now2 = SDL_GetTicks64();
                timeout = due > now2 ? (int)(due - now2) : 1;
            }
            (void)SDL_WaitEventTimeout(NULL, timeout);
        } else {
            uint64_t now2 = SDL_GetTicks64();
            uint64_t next = now + CHUNK_MS;
            if (next > now2)
                SDL_Delay((Uint32)(next - now2));
        }
    }

    /* Finalize: flush the trace, then print the exact replaying
     * invocation -- --maxcycles pins the endpoint so a session ended
     * by window close terminates under replay too. */
    if (fclose(g.tr.f) != 0)
        die("error closing trace file");
    uint64_t end_cycle = se_lo64(g.cpu->cycle);
    if (end_cycle == 0u)
        end_cycle = 1u; /* --maxcycles 0 means unlimited */
    printf("sahara-emu %s --replay %s --trace %s.replay.trc "
           "--trace-level %d --ram %" PRIu64 " --maxcycles %" PRIu64 "\n",
           image, trace_path, trace_path, level, ram, end_cycle);

    SDL_DestroyTexture(g.tex);
    SDL_DestroyRenderer(g.ren);
    SDL_DestroyWindow(g.win);
    SDL_Quit();

    if (g.out_of_cycles) {
        printf("MAXCYCLES\n");
        return 2;
    }
    if (g.cpu->state == SE_RUN_HALT) {
        if (g.cpu->halt_note)
            fprintf(stderr, "sahara-gui: note: %s\n", g.cpu->halt_note);
        printf("HALT r0=%016" PRIx64 "%016" PRIx64 "\n",
               se_hi64(g.cpu->r[0]), se_lo64(g.cpu->r[0]));
        return 0;
    }
    return 0; /* window closed / script ended mid-run: clean exit */
}
