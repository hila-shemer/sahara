#ifndef SE_GUI_TRANSLATE_H
#define SE_GUI_TRANSLATE_H

#include <stdbool.h>
#include <stdint.h>

#include "rwc/attrs.h"

/* Host-input -> Sahara-event translation, all outside the device
 * models per input.md: repeat suppression (2.4), per-key press/release
 * alternation with focus-loss release synthesis (2.6), mouse clamping
 * (3.3) and the differs-from-last-generated emission rule (3.2). This
 * TU is SDL-free -- scancodes arrive as plain page-7 usage integers
 * (SDL scancodes are USB page-7 usages) and pointer state as plain
 * coordinates -- so the unit tests drive it without a window system.
 * Output is finished 9-byte EVENT payloads (trace.md 4.1/4.2) for
 * SeCpu_feed; the flags byte is left 0, the device model recomputes
 * the drop flag at application. */

enum { SE_GXL_EV_BYTES = 9 };

/* Worst case one capture loss can synthesize: every subset key held
 * (103 releases) plus one buttons-clear mouse event. */
enum { SE_GXL_MAX_BURST = 104 };

typedef struct SeGxlEv {
    uint8_t device; /* SE_DEVIDX_KBD or SE_DEVIDX_MOUSE */
    uint8_t payload[SE_GXL_EV_BYTES];
} SeGxlEv;

typedef struct SeGxl {
    bool key_down[256];      /* per-usage alternation state (2.6) */
    uint16_t last_x, last_y; /* last GENERATED mouse triple (3.2); */
    uint8_t last_btn;        /* (0, 0, 0) at reset */
} SeGxl;

void SeGxl_reset(SeGxl *g);

/* One host key transition; repeat marks host auto-repeat. Returns the
 * number of events written to out: 0 (suppressed repeat, out-of-table
 * usage, or an alternation-violating transition) or 1. */
RWC_WARN_UNUSED uint32_t SeGxl_key(SeGxl *g, uint32_t usage, bool press,
                                   bool repeat, SeGxlEv *out);

/* Full host pointer state (absolute position, button mask bit 0 left /
 * 1 right / 2 middle). Clamps against the mode geometry in effect at
 * the injection boundary and emits iff the clamped triple differs from
 * the last generated one. Returns 0 or 1. */
RWC_WARN_UNUSED uint32_t SeGxl_mouse(SeGxl *g, int64_t x, int64_t y,
                                     uint8_t buttons, uint64_t disp_w,
                                     uint64_t disp_h, SeGxlEv *out);

/* Capture/focus loss (input.md 2.6, Appendix A): synthesize releases
 * for every held key, ascending usage order, then a buttons-clear
 * mouse event if any button is held. out must have room for
 * SE_GXL_MAX_BURST events. */
RWC_WARN_UNUSED uint32_t SeGxl_capture_lost(SeGxl *g, SeGxlEv *out);

/* The capture-release chord: Left Ctrl and Left Alt both down. */
RWC_WARN_UNUSED bool SeGxl_chord(const SeGxl *g);

#endif /* SE_GUI_TRANSLATE_H */
