#!/usr/bin/env python3
"""Event feed for tests/c7_kbd_ovf.s — the input.md 8.5 overflow
scenario (INPUT-18): 257 keyboard events at one cycle.

128 press/release pairs of key A (256 events) fill the exactly-256
queue (input.md 4.1); the 257th (a press, alternation intact per
INPUT-19) arrives with the queue full and is dropped-newest — its
feed record carries flags bit 0 = 1 (trace.md 4.1), and a conforming
replayer must RECOMPUTE the same drop decision (trace.md 5.4), so the
recorded EVENT records byte-match this feed.

All 257 share cycle 5000: at the first boundary >= 5000 the whole
batch applies in trace order, so the guest observes STATUS jump
0 -> 256 with no intermediate values.

Mirrors tests/c7_kbd_ovf.s and checks/c7_kbd_ovf.py — change all
three together.
"""

import evlib as V

EVENTS = []
for i in range(256):
    EVENTS.append((5000, V.DEV_KBD, V.kbd_event(0x04, press=(i % 2 == 0))))
# the 257th: press (alternation continues), dropped on arrival
EVENTS.append((5000, V.DEV_KBD, V.kbd_event(0x04, press=True,
                                            dropped=True)))

if __name__ == "__main__":
    img, out = V.main_two_args()
    V.write_feed(img, out, EVENTS)
