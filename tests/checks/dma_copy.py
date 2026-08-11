#!/usr/bin/env python3
"""Trace-level assertions for dma_copy (level-1 trace). Mirrors
tests/dma_copy.s — change together: DESC 0x100000, SRC 0x200000,
DST 0x300000, LEN 4096.

The no-records clause (dma.md 7.2, DMA-C-22), enforced: the 4 KB
transfer must add ZERO records to the trace —
1. exactly ONE DEVW at the doorbell, value = the descriptor PA (the
   submission's only trace footprint);
2. zero MEMW/DEVW records anywhere in [DST, DST+LEN) — the engine's
   destination writes are device-internal, and the guest never stores
   there;
3. no MEMR/MEMW at the descriptor either after the doorbell? — NOT
   asserted: the guest may re-read; what IS asserted is no records
   from the engine's own descriptor read, which at level 1 reduces to
   the MEMW/DEVW claims above;
4. zero traps (the whole test is the happy path).
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evcheck as C  # noqa: E402
import tracefile as T  # noqa: E402

WHO = "dma_copy"
DMA = 0x0F070000
DST = 0x300000
LEN = 4096
DESC = 0x100000


def main():
    if len(sys.argv) != 2:
        C.fail(WHO, "usage: dma_copy.py TRACE")
    recs = T.read_records(sys.argv[1])

    C.check_classification(WHO, recs)
    C.check_trap_census(WHO, recs, {})
    bells = C.devw_vals(recs, DMA + 0x10)
    if bells != [DESC]:
        C.fail(WHO, f"doorbell DEVWs are {[hex(v) for v in bells]}, "
                    f"want exactly [0x{DESC:x}]")
    for i, r in enumerate(recs):
        if r.type in (T.T_MEMW, T.T_DEVW) \
                and DST <= r.fields["ea"] < DST + LEN:
            C.fail(WHO, f"record {i}: write at 0x{r.fields['ea']:x} "
                        f"inside the destination range — the transfer "
                        f"must emit no records (dma.md 7.2)")
    sys.exit(0)


if __name__ == "__main__":
    main()
