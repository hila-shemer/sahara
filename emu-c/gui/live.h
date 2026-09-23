#ifndef SE_GUI_LIVE_H
#define SE_GUI_LIVE_H

#include <stdbool.h>
#include <stdint.h>

/* The live session, split from its window system (docs/2026-09-23-
 * remote-frontend-plan.md step 1). gui/live_main.c owns everything a
 * live front end does -- argument parsing, the recorder, pacing,
 * feeding, the NIC and RNG authors, --script -- and calls a backend
 * for the four things that differ between a local window and a remote
 * viewer: a wall clock, host input, frame output and blocking. Two
 * backends link against it: gui/be_sdl.c (sahara-gui) and gui/be_svp.c
 * (sahara-serve). Everything guest-visible stays in live_main.c, so
 * both binaries author EVENTs through the identical path and a
 * session from either replays under the frozen `sahara-emu --replay`.
 *
 * The backend sees host input as raw host facts (page-7 usage, press,
 * repeat; absolute pointer position and button mask; capture loss) and
 * hands them to the SeLive_host_* entry points below; translation
 * (gui/translate.c) happens inside the live session, never in a
 * backend. */

typedef struct SeLive SeLive;

/* Implemented once per backend TU; exactly one backend links into a
 * binary. `prog` names the binary in diagnostics. */
extern const char *const se_live_prog;

/* Window/connection up at the reset mode (w x h). scripted: --script
 * owns input and the clock, so a backend with no local window (the
 * SVP server) opens nothing and drops frames. */
void SeLiveBe_init(SeLive *lv, uint64_t w, uint64_t h, bool scripted);
void SeLiveBe_fini(void);
/* Real milliseconds; only the pacing heuristic reads it (never
 * semantics). Not called under --script. */
uint64_t SeLiveBe_now_ms(void);
/* Drain pending host input without blocking, calling SeLive_host_*. */
void SeLiveBe_poll(SeLive *lv);
/* A frame snapshot (4 * w * h bytes, XRGB8888 LE rows, display.md
 * 3.3) the guest PRESENTed since the last call. Output only: frames
 * are outside the deterministic boundary (display.md 7). */
void SeLiveBe_present(const uint8_t *frame, uint64_t w, uint64_t h);
/* Block until host input may be pending or timeout_ms passes. */
void SeLiveBe_wait_input(int timeout_ms);
/* Sleep ms without waiting on input (pacing between chunks). */
void SeLiveBe_delay(uint64_t ms);
/* Capture was lost (focus loss, release chord): drop pointer grab. */
void SeLiveBe_release_capture(void);

/* Host input entry points, called from SeLiveBe_poll. */
void SeLive_host_key(SeLive *lv, uint32_t usage, bool press, bool repeat);
void SeLive_host_mouse(SeLive *lv, int64_t x, int64_t y, uint8_t buttons);
void SeLive_host_capture_lost(SeLive *lv);
void SeLive_host_quit(SeLive *lv);
/* The capture-release chord (Left Ctrl + Left Alt held), for backends
 * that own a pointer grab. */
bool SeLive_chord(const SeLive *lv);

#endif /* SE_GUI_LIVE_H */
