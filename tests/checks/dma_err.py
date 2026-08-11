#!/usr/bin/env python3
"""Trace-level assertions for dma_err (level-1 trace). Mirrors
tests/dma_err.s — change together.

The two-class error split, trace side:
1. All sixteen content-error doorbells RETIRED — sixteen DEVWs at the
   doorbell, value = the descriptor PA. Content badness never traps.
2. Trap census is exactly {EXTINT: 1} — the error-with-IRQ leg's
   delivery. Zero DEVERR: no access in this test is bad.
3. The destination page received exactly one write: the guest's own
   canary MEMW at DST. Sixteen failed jobs wrote nothing (no BUSY
   window ever existed).
4. One ack DEVW (the handler's).
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evcheck as C  # noqa: E402
import tracefile as T  # noqa: E402
import encoding as E  # noqa: E402

WHO = "dma_err"
DMA = 0x0F070000
DST = 0x300000
DESC = 0x100000


def main():
    if len(sys.argv) != 2:
        C.fail(WHO, "usage: dma_err.py TRACE")
    recs = T.read_records(sys.argv[1])

    C.check_classification(WHO, recs)
    C.check_trap_census(WHO, recs, {E.CAUSES["EXTINT"]: 1})
    bells = C.devw_vals(recs, DMA + 0x10)
    if bells != [DESC] * 16:
        C.fail(WHO, f"want exactly 16 doorbell DEVWs of 0x{DESC:x}, "
                    f"got {len(bells)}: {[hex(v) for v in bells]}")
    acks = C.devw_vals(recs, DMA + 0x18)
    if acks != [1]:
        C.fail(WHO, f"want exactly one ack DEVW of 1, got "
                    f"{[hex(v) for v in acks]}")
    writes = [r for r in recs if r.type in (T.T_MEMW, T.T_DEVW)
              and DST <= r.fields["ea"] < DST + 0x1000]
    if len(writes) != 1 or writes[0].type != T.T_MEMW \
            or writes[0].fields["ea"] != DST:
        C.fail(WHO, f"destination page must see exactly the guest's "
                    f"canary MEMW at 0x{DST:x}; got "
                    f"{[(hex(r.fields['ea']), r.type) for r in writes]}")
    sys.exit(0)


if __name__ == "__main__":
    main()
