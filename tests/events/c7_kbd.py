#!/usr/bin/env python3
"""Event feed for tests/c7_kbd.s — keyboard pop-with-content plus a
mouse batch for the EXTINT drain phase.

Keyboard (device 1): the input.md 8.2 Shift+A sequence, first pair at
cycle 5000 (same cycle: applied in trace order, trace.md 3.3 rule 1),
release pair at 5001/5002. Mouse (device 2): MV-01 then MV-02 (input.md
8.3), both at cycle 10000 so both are visible atomically at one
boundary (STATUS jumps 0 -> 2; input.md 4.3).

Cycle margins: the guest's pre-arrival checks run within the first few
hundred cycles (1 cycle per retired instruction, ISA-SPEC 4), far
below 5000 — INPUT-21's "invisible before C" leg is real.

Mirrors tests/c7_kbd.s and checks/c7_kbd.py — change all three
together.
"""

import evlib as V

EVENTS = [
    (5000, V.DEV_KBD, V.kbd_event(0xE1, press=True)),    # KV-06 LShift v
    (5000, V.DEV_KBD, V.kbd_event(0x04, press=True)),    # KV-01 A v
    (5001, V.DEV_KBD, V.kbd_event(0x04, press=False)),   # KV-02 A ^
    (5002, V.DEV_KBD, V.kbd_event(0xE1, press=False)),   # KV-07 LShift ^
    (10000, V.DEV_MOUSE, V.mouse_event(100, 200, 1)),    # MV-01
    (10000, V.DEV_MOUSE, V.mouse_event(100, 200, 0)),    # MV-02
]

if __name__ == "__main__":
    img, out = V.main_two_args()
    V.write_feed(img, out, EVENTS)
