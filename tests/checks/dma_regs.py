#!/usr/bin/env python3
"""Trace-level assertions for dma_regs (level-2 trace). Mirrors
tests/dma_regs.s — change together.

What the .s cannot see about itself:
1. The three readable registers really returned the pinned values as
   device MEMRs (CAPS 0x18080301, STATUS 0, COMP_CYCLE 0).
2. Exact trap census: 18 DEVERR + 2 UNALIGNED, nothing else — a
   miscounted census means a fault leg silently stopped faulting (or
   a predicated-false leg faulted).
3. The only DEVW in the DMA window is the single benign ack at +0x18:
   every faulting store left no record (ISA no-effect), and no store
   leaked into another window (T-12 classification).
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evcheck as C  # noqa: E402
import tracefile as T  # noqa: E402
import encoding as E  # noqa: E402

WHO = "dma_regs"
DMA = 0x0F070000
DMA_END = DMA + 0x10000
CAPS = 0x18080301


def main():
    if len(sys.argv) != 2:
        C.fail(WHO, "usage: dma_regs.py TRACE")
    recs = T.read_records(sys.argv[1])

    C.check_classification(WHO, recs)
    for ea, val, what in ((DMA + 0x00, CAPS, "CAPS"),
                          (DMA + 0x08, 0, "STATUS"),
                          (DMA + 0x20, 0, "COMP_CYCLE")):
        got = C.memr_vals(recs, ea)
        if not got or any(v != val for v in got):
            C.fail(WHO, f"{what} MEMRs at 0x{ea:x} are "
                        f"{[hex(v) for v in got]}, want all 0x{val:x}")
    C.check_trap_census(WHO, recs, {E.CAUSES["DEVERR"]: 18,
                                    E.CAUSES["UNALIGNED"]: 2})
    devw = [r for r in recs if r.type == T.T_DEVW
            and DMA <= r.fields["ea"] < DMA_END]
    if len(devw) != 1 or devw[0].fields["ea"] != DMA + 0x18 \
            or devw[0].fields["val"] != 1:
        C.fail(WHO, f"DMA-window DEVWs must be exactly the one benign "
                    f"ack (ea +0x18, val 1); got "
                    f"{[(hex(r.fields['ea']), hex(r.fields['val'])) for r in devw]}")
    sys.exit(0)


if __name__ == "__main__":
    main()
