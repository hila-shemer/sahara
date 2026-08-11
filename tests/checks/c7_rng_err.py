#!/usr/bin/env python3
"""Trace-level assertions for c7_rng_err (level-1 trace). Mirrors
tests/c7_rng_err.s — change together.

What the .s cannot see about itself:
1. The trap census is EXACTLY 2 UNALIGNED + 17 DEVERR — the .s fault
   section and this dict change together. No EXTINT, nothing else.
2. Store classification (T-12): device stores are DEVW, never MEMW.
3. The only successful device stores in the whole run are the four
   CTRL write/readback values 1, 3, 2, 0 (every other store faulted
   and a faulting access records nothing) plus the fail-path
   never-taken store; the CTRL DEVW value sequence is asserted.
4. No EVENT records exist: this test runs with no feed — the empty
   well stays empty.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evcheck as C  # noqa: E402
import tracefile as T  # noqa: E402
import encoding as E  # noqa: E402

WHO = "c7_rng_err"
RNG = 0x0F080000


def main():
    if len(sys.argv) != 2:
        C.fail(WHO, "usage: c7_rng_err.py TRACE")
    recs = T.read_records(sys.argv[1])

    C.check_classification(WHO, recs)
    C.check_trap_census(WHO, recs, {E.CAUSES["DEVERR"]: 17,
                                    E.CAUSES["UNALIGNED"]: 2})

    if any(r.type == T.T_EVENT for r in recs):
        C.fail(WHO, "EVENT records in a feedless run")

    ctrl_writes = C.devw_vals(recs, RNG + 0x10)
    if ctrl_writes != [1, 3, 2, 0]:
        C.fail(WHO, f"CTRL DEVW sequence {ctrl_writes}, want [1, 3, 2, "
                    f"0] (faulting stores must record nothing)")
    for off in (0x00, 0x08, 0x18, 0x20, 0x28):
        if C.devw_vals(recs, RNG + off):
            C.fail(WHO, f"a faulting store to RNG+0x{off:x} left a DEVW")
    sys.exit(0)


if __name__ == "__main__":
    main()
