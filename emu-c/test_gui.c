/* Short-tier unit tests for the SDL-free half of the GUI front end:
 * the HID subset filter (input.md 2.2), the key alternation state
 * machine with repeat suppression and capture-loss release synthesis
 * (2.4/2.6, Appendix A), mouse clamping + the emission rule against
 * the input.md 8.3 vectors (3.2/3.3), and the page-walking frame blit
 * (display.md 3.3, V4) across 64 KB seams and odd strides. The SDL
 * shim above these is deliberately too thin to unit-test; the
 * scripted-session gate in run-gui-tests.sh covers the assembled
 * pipeline. */
#include <stdio.h>
#include <string.h>

#include "dev.h"
#include "gui/blit.h"
#include "gui/hid_map.h"
#include "gui/translate.h"
#include "mem.h"
#include "platform.h"
#include "rwc/status.h"
#include "u128.h"

static uint64_t ev_word(const SeGxlEv *e)
{
    uint64_t v = 0;
    for (unsigned i = 0; i < 8u; i++)
        v |= (uint64_t)e->payload[i] << (8u * i);
    return v;
}

static void test_hid_subset(void)
{
    /* Exactly 103 usages (input.md 2.2). */
    uint32_t n = 0;
    for (uint32_t u = 0; u < 0x200u; u++)
        if (se_hid_in_subset(u))
            n++;
    RWC_ASSERT(n == 103u);
    /* Edges of every included run. */
    static const uint32_t in[] = { 0x04, 0x1D, 0x1E, 0x27, 0x28, 0x31,
                                   0x33, 0x39, 0x3A, 0x45, 0x46, 0x52,
                                   0x53, 0x63, 0xE0, 0xE7 };
    for (unsigned i = 0; i < sizeof in / sizeof in[0]; i++)
        RWC_ASSERT(se_hid_in_subset(in[i]));
    /* The explicit exclusions: rollover codes, Non-US #, Non-US \,
     * Application, media/power land, and everything past 0xE7. */
    static const uint32_t out[] = { 0x00, 0x01, 0x02, 0x03, 0x32,
                                    0x64, 0x65, 0x66, 0xDF, 0xE8,
                                    0x100, 0xFFFF };
    for (unsigned i = 0; i < sizeof out / sizeof out[0]; i++)
        RWC_ASSERT(!se_hid_in_subset(out[i]));
}

static void test_key_alternation(void)
{
    SeGxl g;
    SeGxlEv ev;
    SeGxl_reset(&g);
    /* KV-01/KV-02: press then release A. */
    RWC_ASSERT(SeGxl_key(&g, 0x04u, true, false, &ev) == 1u);
    RWC_ASSERT(ev.device == SE_DEVIDX_KBD);
    RWC_ASSERT(ev_word(&ev) == 0x0000000100000004ull);
    RWC_ASSERT(ev.payload[8] == 0u);
    /* Host auto-repeat while held: nothing (INPUT-12). */
    RWC_ASSERT(SeGxl_key(&g, 0x04u, true, true, &ev) == 0u);
    /* A second press without a release: alternation guard eats it. */
    RWC_ASSERT(SeGxl_key(&g, 0x04u, true, false, &ev) == 0u);
    RWC_ASSERT(SeGxl_key(&g, 0x04u, false, false, &ev) == 1u);
    RWC_ASSERT(ev_word(&ev) == 0x0000000000000004ull);
    /* Release of a key not down: nothing (INPUT-11). */
    RWC_ASSERT(SeGxl_key(&g, 0x04u, false, false, &ev) == 0u);
    /* Out-of-table keys are discarded silently in every direction. */
    RWC_ASSERT(SeGxl_key(&g, 0x65u, true, false, &ev) == 0u);
    RWC_ASSERT(SeGxl_key(&g, 0x65u, false, false, &ev) == 0u);
    RWC_ASSERT(SeGxl_key(&g, 0x32u, true, false, &ev) == 0u);
    /* Modifiers are ordinary keys (KV-06/KV-08). */
    RWC_ASSERT(SeGxl_key(&g, 0xE1u, true, false, &ev) == 1u);
    RWC_ASSERT(ev_word(&ev) == 0x00000001000000E1ull);
    RWC_ASSERT(SeGxl_key(&g, 0xE7u, true, false, &ev) == 1u);
    RWC_ASSERT(ev_word(&ev) == 0x00000001000000E7ull);
}

static void test_capture_loss(void)
{
    SeGxl g;
    SeGxlEv burst[SE_GXL_MAX_BURST];
    SeGxlEv ev;
    SeGxl_reset(&g);
    RWC_ASSERT(SeGxl_key(&g, 0xE1u, true, false, &ev) == 1u); /* Shift */
    RWC_ASSERT(SeGxl_key(&g, 0x04u, true, false, &ev) == 1u); /* A */
    RWC_ASSERT(SeGxl_mouse(&g, 10, 20, 1u, 640u, 480u, &ev) == 1u);
    /* Focus loss: releases for A then Shift (ascending usage), then
     * the buttons-clear mouse event at the last generated position. */
    uint32_t n = SeGxl_capture_lost(&g, burst);
    RWC_ASSERT(n == 3u);
    RWC_ASSERT(burst[0].device == SE_DEVIDX_KBD);
    RWC_ASSERT(ev_word(&burst[0]) == 0x0000000000000004ull);
    RWC_ASSERT(burst[1].device == SE_DEVIDX_KBD);
    RWC_ASSERT(ev_word(&burst[1]) == 0x00000000000000E1ull);
    RWC_ASSERT(burst[2].device == SE_DEVIDX_MOUSE);
    RWC_ASSERT(ev_word(&burst[2]) == 0x000000000014000Aull);
    /* State is fully reset: the next transitions are fresh presses,
     * and an identical pointer state generates nothing new. */
    RWC_ASSERT(SeGxl_key(&g, 0x04u, true, false, &ev) == 1u);
    RWC_ASSERT(ev_word(&ev) == 0x0000000100000004ull);
    RWC_ASSERT(SeGxl_mouse(&g, 10, 20, 0u, 640u, 480u, &ev) == 0u);
    /* Nothing held: capture loss synthesizes nothing. */
    SeGxl_reset(&g);
    RWC_ASSERT(SeGxl_capture_lost(&g, burst) == 0u);
}

static void test_chord(void)
{
    SeGxl g;
    SeGxlEv ev;
    SeGxl_reset(&g);
    RWC_ASSERT(!SeGxl_chord(&g));
    RWC_ASSERT(SeGxl_key(&g, 0xE0u, true, false, &ev) == 1u);
    RWC_ASSERT(!SeGxl_chord(&g)); /* LCtrl alone */
    RWC_ASSERT(SeGxl_key(&g, 0xE2u, true, false, &ev) == 1u);
    RWC_ASSERT(SeGxl_chord(&g)); /* LCtrl + LAlt */
    RWC_ASSERT(SeGxl_key(&g, 0xE0u, false, false, &ev) == 1u);
    RWC_ASSERT(!SeGxl_chord(&g));
    /* Right-hand modifiers do not form the chord (Appendix A: both
     * left). */
    SeGxl_reset(&g);
    RWC_ASSERT(SeGxl_key(&g, 0xE4u, true, false, &ev) == 1u);
    RWC_ASSERT(SeGxl_key(&g, 0xE6u, true, false, &ev) == 1u);
    RWC_ASSERT(!SeGxl_chord(&g));
}

static void test_mouse(void)
{
    SeGxl g;
    SeGxlEv ev;
    SeGxl_reset(&g);
    /* MV-01/MV-02 at 800x600, then MV-08 dedup. */
    RWC_ASSERT(SeGxl_mouse(&g, 100, 200, 1u, 800u, 600u, &ev) == 1u);
    RWC_ASSERT(ev.device == SE_DEVIDX_MOUSE);
    RWC_ASSERT(ev_word(&ev) == 0x0000000100C80064ull);
    RWC_ASSERT(SeGxl_mouse(&g, 100, 200, 0u, 800u, 600u, &ev) == 1u);
    RWC_ASSERT(ev_word(&ev) == 0x0000000000C80064ull);
    RWC_ASSERT(SeGxl_mouse(&g, 100, 200, 0u, 800u, 600u, &ev) == 0u);
    /* MV-03: clamped to (799, 599). */
    RWC_ASSERT(SeGxl_mouse(&g, 800, 600, 0u, 800u, 600u, &ev) == 1u);
    RWC_ASSERT(ev_word(&ev) == 0x000000000257031Full);
    /* Motion entirely beyond the clamped edge: same clamped triple,
     * no event (INPUT-16). */
    RWC_ASSERT(SeGxl_mouse(&g, 900, 700, 0u, 800u, 600u, &ev) == 0u);
    /* MV-04/MV-05/MV-06. */
    RWC_ASSERT(SeGxl_mouse(&g, 0, 0, 7u, 800u, 600u, &ev) == 1u);
    RWC_ASSERT(ev_word(&ev) == 0x0000000700000000ull);
    RWC_ASSERT(SeGxl_mouse(&g, 799, 0, 2u, 800u, 600u, &ev) == 1u);
    RWC_ASSERT(ev_word(&ev) == 0x000000020000031Full);
    RWC_ASSERT(SeGxl_mouse(&g, 0, 599, 4u, 800u, 600u, &ev) == 1u);
    RWC_ASSERT(ev_word(&ev) == 0x0000000402570000ull);
    /* MV-07: the 16-bit field bound in a >65536 mode. */
    SeGxl_reset(&g);
    RWC_ASSERT(SeGxl_mouse(&g, 70000, 70000, 7u, 70000u, 70000u, &ev) == 1u);
    RWC_ASSERT(ev_word(&ev) == 0x00000007FFFFFFFFull);
    /* Negative host coordinates clamp to 0. */
    SeGxl_reset(&g);
    RWC_ASSERT(SeGxl_mouse(&g, -5, -1, 1u, 640u, 480u, &ev) == 1u);
    RWC_ASSERT(ev_word(&ev) == 0x0000000100000000ull);
    /* The reset triple is (0,0,0): pointer parked there with no
     * buttons generates nothing at all (input.md 3.2). */
    SeGxl_reset(&g);
    RWC_ASSERT(SeGxl_mouse(&g, 0, 0, 0u, 640u, 480u, &ev) == 0u);
}

static void test_blit(void)
{
    SeMem m;
    SeMem_init(&m, 0x20000u); /* RAM size irrelevant to the window */
    uint64_t pb = se_lo64(SE_PLAT_PIXBUF_BASE);
    /* V4 geometry: 2x2, stride 16 -- padding excluded, X byte copied
     * verbatim (presented ARGB ignores it, D-12). */
    SeMem_write(&m, pb + 0u, 4u, 0x00FF0000u);  /* (0,0) red */
    SeMem_write(&m, pb + 4u, 4u, 0x0000FF00u);  /* (1,0) green */
    SeMem_write(&m, pb + 8u, 4u, 0xDEADBEEFu);  /* padding, excluded */
    SeMem_write(&m, pb + 16u, 4u, 0x000000FFu); /* (0,1) blue */
    SeMem_write(&m, pb + 20u, 4u, 0xFFFFFFFFu); /* (1,1) white, X=FF */
    uint8_t snap[16];
    SeGuiBlit_frame(&m, 2u, 2u, 16u, snap);
    static const uint8_t want[16] = { 0x00, 0x00, 0xFF, 0x00,
                                      0x00, 0xFF, 0x00, 0x00,
                                      0xFF, 0x00, 0x00, 0x00,
                                      0xFF, 0xFF, 0xFF, 0xFF };
    RWC_ASSERT(memcmp(snap, want, sizeof want) == 0);

    /* 64 KB seam: at the reference stride, row 25 spans the first
     * page boundary (25*2560 = 64000, +2560 crosses 65536). Mark the
     * last byte before the seam and the first after; a row copied in
     * one page-blind memcpy would misread one side. */
    SeMem_write(&m, pb + 65535u, 1u, 0xAAu);
    SeMem_write(&m, pb + 65536u, 1u, 0xBBu);
    static uint8_t frame[640u * 480u * 4u];
    SeGuiBlit_frame(&m, 640u, 480u, 2560u, frame);
    /* offset within row 25: 65535 - 64000 = 1535; row starts at
     * 25*2560 in the packed snapshot too (stride == 4*width). */
    RWC_ASSERT(frame[25u * 2560u + 1535u] == 0xAAu);
    RWC_ASSERT(frame[25u * 2560u + 1536u] == 0xBBu);
    /* V4 pixels land at the packed origin as well. */
    RWC_ASSERT(frame[2] == 0xFFu);
    /* Untouched pages read zero: probe deep into the window. */
    RWC_ASSERT(frame[400u * 2560u + 100u] == 0u);

    /* Wider padding (stride 48 for width 3): rows land packed in the
     * snapshot, padding bytes never reach it. Fresh store so the V4
     * bytes above cannot mask a miscopy. */
    SeMem m2;
    SeMem_init(&m2, 0x20000u);
    for (uint64_t y = 0; y < 3u; y++)
        for (uint64_t x = 0; x < 3u; x++)
            SeMem_write(&m2, pb + y * 48u + 4u * x, 4u,
                        (se_u128)(0x10u * y + x + 1u));
    SeMem_write(&m2, pb + 12u, 4u, 0xEEEEEEEEu); /* row-0 padding */
    uint8_t s2[36];
    SeGuiBlit_frame(&m2, 3u, 3u, 48u, s2);
    for (uint64_t y = 0; y < 3u; y++)
        for (uint64_t x = 0; x < 3u; x++) {
            RWC_ASSERT(s2[(y * 3u + x) * 4u] ==
                       (uint8_t)(0x10u * y + x + 1u));
            RWC_ASSERT(s2[(y * 3u + x) * 4u + 1u] == 0u);
        }
}

int main(void)
{
    test_hid_subset();
    test_key_alternation();
    test_capture_loss();
    test_chord();
    test_mouse();
    test_blit();
    printf("test_gui: all passed\n");
    return 0;
}
