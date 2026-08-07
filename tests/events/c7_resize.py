#!/usr/bin/env python3
"""Event feed for tests/c7_resize.s — display resize delivery, the
double-event latest-wins case, INPUT-17 no-re-clamp, and the V5
ack-first interrupt phase.

Timeline (all deliveries at exact cycles: the guest never idles, so
every cycle value is an instruction boundary):
  5000   resize 800x600x3200        (display.md V5 steps 2-6)
  7000   mouse (790,590,none)       E1 of input.md 8.6, valid in
                                    800x600, enqueued pre-shrink
  10000  resize 1024x768x4096  \\    same cycle: applied in trace
  10000  resize 640x480x2560   /    order, registers show the LATEST
                                    (V5 steps 7-9, 6.4)
  13000  mouse (639,479,left)       post-shrink word, already clamped
                                    to 640x480 (8.6 E2 adapted; replay
                                    applies words verbatim)
  15000  resize 800x600x3200        delivered with IE=1 -> EXTINT,
                                    ack-first handler (V5 steps 12-13)

The guest pops E1 after the shrink: its coordinates (790,590) exceed
the new mode and must pop unmodified (INPUT-17). Margins: the guest
reaches each wait loop thousands of cycles before the event it waits
for; the E1-pop/STATUS==0 check completes near cycle 10000, well
before E2 at 13000.

Mirrors tests/c7_resize.s and checks/c7_resize.py — change all three
together.
"""

import evlib as V

EVENTS = [
    (5000, V.DEV_DISPLAY, V.resize_event(800, 600, 3200)),
    (7000, V.DEV_MOUSE, V.mouse_event(790, 590, 0)),      # 8.6 E1
    (10000, V.DEV_DISPLAY, V.resize_event(1024, 768, 4096)),
    (10000, V.DEV_DISPLAY, V.resize_event(640, 480, 2560)),
    (13000, V.DEV_MOUSE, V.mouse_event(639, 479, 1)),     # 8.6 E2 adapted
    (15000, V.DEV_DISPLAY, V.resize_event(800, 600, 3200)),
]

if __name__ == "__main__":
    img, out = V.main_two_args()
    V.write_feed(img, out, EVENTS)
