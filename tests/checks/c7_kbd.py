#!/usr/bin/env python3
"""Trace-level assertions for c7_kbd (level-2 trace). Mirrors
tests/c7_kbd.s and tests/events/c7_kbd.py — change together.

What the .s cannot see about itself:
1. The recorded EVENT records equal the feed byte-for-byte (cycle,
   device, payload — evcheck rationale).
2. The kbd DATA pop sequence is EXACTLY the four 8.2 words then the
   sentinel — five device reads, no more: the predicated-false pop
   (INPUT-08) must NOT appear as a MEMR, and no pop happened early.
3. Mouse DATA reads are exactly: one pre-event sentinel, then MV-01,
   MV-02, sentinel (the handler's drain loop).
4. Exactly one trap: EXTINT, tl_after 1.
5. STATUS reads never show impossible depths, and stores never leak
   into input windows (T-12 classification).
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evcheck as C  # noqa: E402
import tracefile as T  # noqa: E402
import encoding as E  # noqa: E402

WHO = "c7_kbd"

POPS_KBD = [0x00000001000000E1, 0x0000000100000004,
            0x0000000000000004, 0x00000000000000E1, C.SENTINEL]
POPS_MOUSE = [C.SENTINEL, 0x0000000100C80064, 0x0000000000C80064,
              C.SENTINEL]


def main():
    if len(sys.argv) != 2:
        C.fail(WHO, "usage: c7_kbd.py TRACE")
    recs = T.read_records(sys.argv[1])

    C.check_classification(WHO, recs)
    C.check_events_match_feed(WHO, recs, "c7_kbd")
    C.check_seq(WHO, recs, C.KBD + 0, POPS_KBD, "kbd DATA")
    C.check_seq(WHO, recs, C.MOUSE + 0, POPS_MOUSE, "mouse DATA")
    C.check_trap_census(WHO, recs, {E.CAUSES["EXTINT"]: 1})
    for r in recs:
        if r.type == T.T_TRAP and r.fields["tl_after"] != 1:
            C.fail(WHO, f"EXTINT tl_after {r.fields['tl_after']}, want 1")
    # STATUS depths: kbd can only ever read 0/2/3/4 (batch cycles
    # 5000,5000,5001,5002 and the guest's read points); mouse 0/2
    # (both events share one cycle). Which intermediates the 3-insn
    # poll loop samples is cycle-phase-dependent — membership, not
    # sequence, is the deterministic claim here.
    for v in C.memr_vals(recs, C.KBD + 8):
        if v not in (0, 2, 3, 4):
            C.fail(WHO, f"impossible kbd STATUS read 0x{v:x}")
    for v in C.memr_vals(recs, C.MOUSE + 8):
        if v not in (0, 2):
            C.fail(WHO, f"impossible mouse STATUS read 0x{v:x}")
    sys.exit(0)


if __name__ == "__main__":
    main()
