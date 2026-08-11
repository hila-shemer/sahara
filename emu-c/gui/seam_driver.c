/* gui-seam-driver: the record->replay keystone of the GUI phase, with
 * no SDL anywhere near it. It plays the front end's role against a
 * small guest -- SeCpu_feed at fabricated boundaries, live_yield WFI
 * idling, a mode=live trace -- and run-gui-tests.sh then replays the
 * recording through the frozen `sahara-emu --replay` and requires all
 * post-META records byte-identical. Scenarios:
 *
 *   wfi    press fed while the core is WFI-yielded, stamped beyond the
 *          WFI cycle (EXEC(WFI)@C, EVENT@E, TRAP@E; SPEC-ISSUES 36),
 *          then a release fed during a second idle ends the guest
 *   burst  300 keyboard events at one boundary: 256 kept, 44 dropped
 *          with the model-recomputed flag (INPUT-18/19)
 *   multi  keyboard + mouse + resize at one boundary with IE on:
 *          EVENT records before the EXTINT TRAP, one cycle (T-09)
 *   nicseam NIC frames through the live feed: one during WFI idle, a
 *          max-length frame + a short one sharing a cycle with a
 *          keyboard press, then a 70-frame burst against the 64-cap
 *          -- the 6 overflow discards leave NO event records
 *          (nic.md 4.3), and replay identity proves it
 *
 * usage: gui-seam-driver SCENARIO IMAGE OUT.trc */
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
#include "rwc/status.h"
#include "trace.h"
#include "u128.h"

#define PLATFORM_SPEC_VERSION "1.0-draft"
#define RAM_LEN 0x0F000000ull /* the 240 MB reference region 0 */
#define PASS_MAGIC 0x600Dull

static void die(const char *msg)
{
    fprintf(stderr, "gui-seam-driver: %s\n", msg);
    exit(1);
}

static void kbd_payload(uint8_t out[9], uint32_t usage, bool press)
{
    uint64_t word = (uint64_t)usage | ((uint64_t)(press ? 1u : 0u) << 32);
    for (unsigned i = 0; i < 8u; i++)
        out[i] = (uint8_t)(word >> (8u * i));
    out[8] = 0; /* drop flag: the model recomputes it */
}

static void mouse_payload(uint8_t out[9], uint16_t x, uint16_t y,
                          uint8_t btn)
{
    uint64_t word =
        (uint64_t)x | ((uint64_t)y << 16) | ((uint64_t)btn << 32);
    for (unsigned i = 0; i < 8u; i++)
        out[i] = (uint8_t)(word >> (8u * i));
    out[8] = 0;
}

static void resize_payload(uint8_t out[32], uint64_t w, uint64_t h,
                           uint64_t stride)
{
    const uint64_t f[4] = { w, h, stride, 1u /* format, v1.0 */ };
    for (unsigned k = 0; k < 4u; k++)
        for (unsigned i = 0; i < 8u; i++)
            out[8u * k + i] = (uint8_t)(f[k] >> (8u * i));
}

static void step_n(SeCpu *c, uint64_t n)
{
    for (uint64_t i = 0; i < n; i++) {
        RWC_ASSERT(c->state == SE_RUN_RUNNING && !c->wfi_idle);
        SeCpu_step(c);
    }
}

static void run_until_idle(SeCpu *c)
{
    for (uint64_t i = 0; i < 1000000u; i++) {
        if (c->wfi_idle)
            return;
        RWC_ASSERT(c->state == SE_RUN_RUNNING);
        SeCpu_step(c);
    }
    die("guest never reached WFI idle");
}

static void run_to_halt(SeCpu *c)
{
    for (uint64_t i = 0; i < 10000000u; i++) {
        if (c->state != SE_RUN_RUNNING)
            break;
        RWC_ASSERT(!c->wfi_idle); /* an idle here would spin forever */
        SeCpu_step(c);
    }
    if (c->state != SE_RUN_HALT)
        die("guest did not halt");
    if (se_lo64(c->r[0]) != PASS_MAGIC || se_hi64(c->r[0]) != 0u) {
        fprintf(stderr, "gui-seam-driver: guest failed: r0=%016" PRIx64
                        "%016" PRIx64 "\n",
                se_hi64(c->r[0]), se_lo64(c->r[0]));
        exit(1);
    }
}

int main(int argc, char **argv)
{
    if (argc != 4)
        die("usage: gui-seam-driver SCENARIO IMAGE OUT.trc");
    const char *scenario = argv[1], *image = argv[2], *out = argv[3];

    SeMem mem;
    SeMem_init(&mem, RAM_LEN);
    se_plat_write_devtable(&mem, RAM_LEN);
    se_u128 entry = 0;
    uint8_t sha[32];
    const char *err = se_image_load(&mem, image, &entry, sha);
    if (err)
        die(err);
    char sha_hex[65];
    for (unsigned i = 0; i < 32u; i++)
        snprintf(sha_hex + 2u * i, 3u, "%02x", sha[i]);

    SeTrace tr = { .f = fopen(out, "wb"), .level = 1 };
    if (!tr.f)
        die("cannot open trace output");
    char meta[640];
    int n = snprintf(meta, sizeof meta,
                     "trace=1\n"
                     "encoding=" SE_ENCODING_SPEC_VERSION "\n"
                     "level=1\n"
                     "mode=live\n"
                     "image=%s\n"
                     "image_sha256=%s\n"
                     "platform=" PLATFORM_SPEC_VERSION "\n",
                     image, sha_hex);
    RWC_ASSERT(n > 0 && (size_t)n < sizeof meta);
    SeTrace_meta(&tr, meta, (uint32_t)n);

    SeDev dev;
    SeDev_reset(&dev);
    dev.mem = &mem; /* NIC RX exposure writes through the device */
    SeCpu *cpu = se_host_alloc(sizeof *cpu);
    SeCpu_reset(cpu, &mem, &tr);
    cpu->dev = &dev;
    cpu->live_yield = true;

    uint8_t p[32];
    if (strcmp(scenario, "wfi") == 0) {
        run_until_idle(cpu);
        /* Stamp beyond the WFI cycle, as a paced front end would:
         * E = max(wfi_cycle + 1, target). */
        kbd_payload(p, 0x04u, true);
        SeCpu_feed(cpu, SE_DEVIDX_KBD, p, 9u, se_lo64(cpu->cycle) + 700u);
        run_until_idle(cpu); /* woke, drained the press, WFI'd again */
        kbd_payload(p, 0x04u, false);
        SeCpu_feed(cpu, SE_DEVIDX_KBD, p, 9u, se_lo64(cpu->cycle) + 1300u);
        run_to_halt(cpu);
    } else if (strcmp(scenario, "burst") == 0) {
        step_n(cpu, 20u); /* guest is polling STATUS */
        for (uint32_t i = 0; i < 300u; i++) {
            /* Alternating press/release: dropped events still advance
             * the alternation state (INPUT-19), so the translator
             * upstream would emit exactly this shape. */
            kbd_payload(p, 0x04u, (i & 1u) == 0u);
            SeCpu_feed(cpu, SE_DEVIDX_KBD, p, 9u, 0u);
        }
        run_to_halt(cpu);
    } else if (strcmp(scenario, "multi") == 0) {
        step_n(cpu, 30u); /* guest is spinning with IE on */
        kbd_payload(p, 0x04u, true);
        SeCpu_feed(cpu, SE_DEVIDX_KBD, p, 9u, 0u);
        mouse_payload(p, 100u, 200u, 1u);
        SeCpu_feed(cpu, SE_DEVIDX_MOUSE, p, 9u, 0u);
        resize_payload(p, 800u, 600u, 3200u);
        SeCpu_feed(cpu, SE_DEVIDX_DISPLAY, p, 32u, 0u);
        run_to_halt(cpu);
    } else if (strcmp(scenario, "nicseam") == 0) {
        static uint8_t frame[SE_NIC_FRAME_MAX];
        /* One frame fed while the core is WFI-yielded, stamped beyond
         * the WFI cycle -- the NIC arrival wakes WFI at exactly its
         * cycle (NIC-C-36) through the unchanged wake rule. */
        run_until_idle(cpu);
        memset(frame, 0x11, 60u);
        SeCpu_feed(cpu, SE_DEVIDX_NIC, frame, 60u,
                   se_lo64(cpu->cycle) + 500u);
        run_until_idle(cpu);
        /* Keyboard + a max-length frame + a short frame at ONE
         * boundary: equal cycles order by feed order (nic.md 7.1
         * rule 2), and 1514 bytes proves the u16 length plumbing
         * end to end. */
        uint64_t e = se_lo64(cpu->cycle) + 700u;
        kbd_payload(p, 0x04u, true);
        SeCpu_feed(cpu, SE_DEVIDX_KBD, p, 9u, e);
        memset(frame, 0x22, sizeof frame);
        SeCpu_feed(cpu, SE_DEVIDX_NIC, frame, SE_NIC_FRAME_MAX, e);
        memset(frame, 0x33, 61u);
        SeCpu_feed(cpu, SE_DEVIDX_NIC, frame, 61u, e);
        run_until_idle(cpu);
        /* 70 frames at one boundary against the empty 64-cap: 64
         * admitted and recorded, 6 discarded with NO records -- the
         * guest counts 64, and replay applies exactly the recorded
         * 64 into the same occupancy (NIC-C-18). */
        e = se_lo64(cpu->cycle) + 900u;
        for (uint32_t i = 0; i < 70u; i++) {
            memset(frame, (int)(0x40u + i), 60u);
            SeCpu_feed(cpu, SE_DEVIDX_NIC, frame, 60u, e);
        }
        run_to_halt(cpu);
    } else {
        die("unknown scenario (wfi | burst | multi | nicseam)");
    }

    if (fclose(tr.f) != 0)
        die("error closing trace");
    printf("gui-seam-driver %s: HALT r0=%016" PRIx64 "%016" PRIx64 "\n",
           scenario, se_hi64(cpu->r[0]), se_lo64(cpu->r[0]));
    return 0;
}
