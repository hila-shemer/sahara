#include "gui/translate.h"

#include <string.h>

#include "dev.h"
#include "gui/hid_map.h"
#include "rwc/status.h"

void SeGxl_reset(SeGxl *g)
{
    memset(g, 0, sizeof *g);
}

static void put_event(SeGxlEv *out, uint8_t device, uint64_t word)
{
    out->device = device;
    for (unsigned i = 0; i < 8u; i++)
        out->payload[i] = (uint8_t)(word >> (8u * i));
    out->payload[8] = 0; /* drop flag: recomputed by the model */
}

uint32_t SeGxl_key(SeGxl *g, uint32_t usage, bool press, bool repeat,
                   SeGxlEv *out)
{
    if (repeat)
        return 0; /* host auto-repeat never becomes an event (2.4) */
    if (!se_hid_in_subset(usage))
        return 0; /* silent discard (2.2) */
    if (g->key_down[usage] == press)
        return 0; /* alternation guard: press only from released and
                     vice versa (2.6); host dup transitions vanish */
    g->key_down[usage] = press;
    put_event(out, SE_DEVIDX_KBD,
              (uint64_t)usage | ((uint64_t)(press ? 1u : 0u) << 32));
    return 1;
}

static uint16_t clamp_dim(int64_t v, uint64_t dim)
{
    /* x = min(max(v, 0), min(dim-1, 65535)) -- input.md 3.3; the
     * 65535 bound keeps the 16-bit field well-formed (MV-07). */
    uint64_t lim = dim - 1u;
    if (lim > 65535u)
        lim = 65535u;
    if (v < 0)
        return 0;
    if ((uint64_t)v > lim)
        return (uint16_t)lim;
    return (uint16_t)v;
}

static uint64_t mouse_word(uint16_t x, uint16_t y, uint8_t btn)
{
    return (uint64_t)x | ((uint64_t)y << 16) | ((uint64_t)btn << 32);
}

uint32_t SeGxl_mouse(SeGxl *g, int64_t x, int64_t y, uint8_t buttons,
                     uint64_t disp_w, uint64_t disp_h, SeGxlEv *out)
{
    RWC_ASSERT((buttons & 0xF8u) == 0u); /* bits 7:3 must be 0 (3.1) */
    RWC_ASSERT(disp_w >= 1u && disp_h >= 1u);
    uint16_t cx = clamp_dim(x, disp_w);
    uint16_t cy = clamp_dim(y, disp_h);
    if (cx == g->last_x && cy == g->last_y && buttons == g->last_btn)
        return 0; /* emission rule: clamped triple unchanged (3.2) */
    g->last_x = cx;
    g->last_y = cy;
    g->last_btn = buttons;
    put_event(out, SE_DEVIDX_MOUSE, mouse_word(cx, cy, buttons));
    return 1;
}

uint32_t SeGxl_capture_lost(SeGxl *g, SeGxlEv *out)
{
    uint32_t n = 0;
    for (uint32_t u = 0; u < 256u; u++) {
        if (!g->key_down[u])
            continue;
        g->key_down[u] = false;
        put_event(&out[n], SE_DEVIDX_KBD, (uint64_t)u);
        n++;
    }
    if (g->last_btn != 0u) {
        /* Position unchanged, buttons cleared: differs from the last
         * generated triple by construction, so it is always emitted. */
        g->last_btn = 0;
        put_event(&out[n], SE_DEVIDX_MOUSE,
                  mouse_word(g->last_x, g->last_y, 0));
        n++;
    }
    return n;
}

bool SeGxl_chord(const SeGxl *g)
{
    return g->key_down[0xE0] && g->key_down[0xE2];
}
