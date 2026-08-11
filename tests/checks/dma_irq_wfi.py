#!/usr/bin/env python3
"""Trace-level assertions for dma_irq_wfi (level-1 trace). Mirrors
tests/dma_irq_wfi.s — change together: LEN 4096 for the WFI leg.

The wake-cycle pin, hand-derived (dma work order risk 2 — both
emulators could get the wake rule wrong SYMMETRICALLY and difftest
would not notice; this arithmetic is the only guard):

1. Exactly 2 doorbell DEVWs and exactly 2 TRAP records, both EXTINT.
2. The FIRST trap's cycle equals the FIRST doorbell's cycle
   + 8 + 4096/8 EXACTLY — the WFI stall ended with the boundary at
   C_done (the event-wake rule), not C_done+1 (the timecmp rule) and
   not later.
3. Two ack DEVWs of value 1 (one per delivery — level dropped each
   time, single delivery each).
4. No writes in the transfer destinations (0x300000 / 0x310000).
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evcheck as C  # noqa: E402
import tracefile as T  # noqa: E402
import encoding as E  # noqa: E402

WHO = "dma_irq_wfi"
DMA = 0x0F070000
K = 8
LEN1 = 4096


def main():
    if len(sys.argv) != 2:
        C.fail(WHO, "usage: dma_irq_wfi.py TRACE")
    recs = T.read_records(sys.argv[1])

    C.check_classification(WHO, recs)
    C.check_trap_census(WHO, recs, {E.CAUSES["EXTINT"]: 2})
    bells = [r for r in recs if r.type == T.T_DEVW
             and r.fields["ea"] == DMA + 0x10]
    if len(bells) != 2:
        C.fail(WHO, f"want exactly 2 doorbell DEVWs, got {len(bells)}")
    traps = [r for r in recs if r.type == T.T_TRAP]
    c_done = bells[0].fields["cycle"] + K + LEN1 // 8
    if traps[0].fields["cycle"] != c_done:
        C.fail(WHO, f"WFI woke at cycle {traps[0].fields['cycle']}, "
                    f"want EXACTLY C_done = doorbell {bells[0].fields['cycle']}"
                    f" + {K} + {LEN1 // 8} = {c_done} (event-wake rule, "
                    f"not timecmp's T+1)")
    acks = C.devw_vals(recs, DMA + 0x18)
    if acks != [1, 1]:
        C.fail(WHO, f"want two ack DEVWs of 1, got "
                    f"{[hex(v) for v in acks]}")
    for i, r in enumerate(recs):
        if r.type in (T.T_MEMW, T.T_DEVW) \
                and 0x300000 <= r.fields["ea"] < 0x320000:
            C.fail(WHO, f"record {i}: write at 0x{r.fields['ea']:x} "
                        f"inside a destination range (dma.md 7.2)")
    sys.exit(0)


if __name__ == "__main__":
    main()
