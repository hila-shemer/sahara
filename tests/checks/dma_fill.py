#!/usr/bin/env python3
"""Trace-level assertions for dma_fill (level-1 trace). Mirrors
tests/dma_fill.s — change together: DESC 0x100000, DST 0x300000,
LEN 32768.

Same no-records clause as dma_copy, at a different LEN: one doorbell
DEVW, zero MEMW/DEVW inside [DST, DST+LEN) — 32 KB of pattern written
with zero trace bytes — and zero traps.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evcheck as C  # noqa: E402
import tracefile as T  # noqa: E402

WHO = "dma_fill"
DMA = 0x0F070000
DST = 0x300000
LEN = 32768
DESC = 0x100000


def main():
    if len(sys.argv) != 2:
        C.fail(WHO, "usage: dma_fill.py TRACE")
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
