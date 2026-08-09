#!/usr/bin/env python3
"""Trace-level assertions for c7_kbd_ovf (level-2 trace). Mirrors
tests/c7_kbd_ovf.s and tests/events/c7_kbd_ovf.py — change together.

What the .s cannot see about itself:
1. EVENT records equal the feed byte-for-byte — 257 of them; and,
   asserted explicitly (not just via feed equality): record 257
   carries the dropped-on-arrival flag (bit 0) and records 1..256 do
   not. On a real emulator the flag is RECOMPUTED by the device model
   (trace.md 5.4) — this is INPUT-18's drop decision made
   trace-visible.
2. The kbd DATA pop sequence is exactly 128 press/release pairs then
   one sentinel (257 reads): the dropped press is absent (8.5 step 2).
3. STATUS reads: every pre-batch read is 0, and the reads from the
   poll-exit onward are exactly [256, 255, ..., 1, 0] — depth was
   never 257 and decremented once per pop (INPUT-02/18).
4. No traps at all (IE stays 0; nothing faults).
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evcheck as C  # noqa: E402
import tracefile as T  # noqa: E402

WHO = "c7_kbd_ovf"
PRESS = 0x0000000100000004
RELEASE = 0x0000000000000004


def main():
    if len(sys.argv) != 2:
        C.fail(WHO, "usage: c7_kbd_ovf.py TRACE")
    recs = T.read_records(sys.argv[1])

    C.check_classification(WHO, recs)
    C.check_events_match_feed(WHO, recs, "c7_kbd_ovf")

    evs = [r for r in recs if r.type == T.T_EVENT]
    for i, r in enumerate(evs):
        flags = r.fields["bytes"][8]
        want = 1 if i == 256 else 0
        if flags != want:
            C.fail(WHO, f"EVENT {i}: flags 0x{flags:02x}, want "
                        f"0x{want:02x} (only the 257th is dropped)")

    want_pops = [PRESS if i % 2 == 0 else RELEASE
                 for i in range(256)] + [C.SENTINEL]
    C.check_seq(WHO, recs, C.KBD + 0, want_pops, "kbd DATA")

    status = C.memr_vals(recs, C.KBD + 8)
    tail = list(range(256, -1, -1))          # 256, 255, ..., 0
    if len(status) < len(tail) or status[-len(tail):] != tail:
        C.fail(WHO, f"STATUS tail is not 256..0 (last reads: "
                    f"{status[-5:]}, {len(status)} total)")
    if any(v != 0 for v in status[:-len(tail)]):
        C.fail(WHO, "a pre-batch STATUS read was nonzero")

    C.check_trap_census(WHO, recs, {})
    sys.exit(0)


if __name__ == "__main__":
    main()
