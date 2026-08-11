#!/usr/bin/env python3
"""Trace-level assertions for dma_boundary (level-1 trace). Mirrors
tests/dma_boundary.s — change together.

1. Exactly 7 doorbell DEVWs, all carrying the descriptor PA: six
   accepted jobs plus leg 0 — and NOT eight: the BUSY-rejected
   doorbell faulted, and a faulting access leaves no record (ISA
   no-effect rule).
2. Trap census exactly {DEVERR: 1} — the doorbell-while-BUSY leg.
3. No MEMW/DEVW in the pure-destination ranges the engine alone
   writes (leg 1's B at 0x310000 and its smashed decoy at 0x320000,
   leg 2's D at 0x330000, leg 5's 64 KB at 0x340000, leg 6's table
   copy at 0x350000) — the transfers are record-free (dma.md 7.2).
   Overlap-leg regions (0x230000/0x240000) are guest-filled and NOT
   in this list.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evcheck as C  # noqa: E402
import tracefile as T  # noqa: E402
import encoding as E  # noqa: E402

WHO = "dma_boundary"
DMA = 0x0F070000
DESC = 0x100000
PURE_DST = [(0x300000, 0x1000), (0x310000, 0x1000), (0x320000, 0x1000),
            (0x330000, 0x1000), (0x340000, 0x10000), (0x350000, 0x1000)]


def main():
    if len(sys.argv) != 2:
        C.fail(WHO, "usage: dma_boundary.py TRACE")
    recs = T.read_records(sys.argv[1])

    C.check_classification(WHO, recs)
    C.check_trap_census(WHO, recs, {E.CAUSES["DEVERR"]: 1})
    bells = C.devw_vals(recs, DMA + 0x10)
    if bells != [DESC] * 7:
        C.fail(WHO, f"want exactly 7 doorbell DEVWs (the rejected one "
                    f"leaves no record), got {len(bells)}")
    for i, r in enumerate(recs):
        if r.type in (T.T_MEMW, T.T_DEVW):
            for base, ln in PURE_DST:
                if base <= r.fields["ea"] < base + ln:
                    C.fail(WHO, f"record {i}: write at "
                                f"0x{r.fields['ea']:x} inside a pure "
                                f"destination range (dma.md 7.2)")
    sys.exit(0)


if __name__ == "__main__":
    main()
