#!/usr/bin/env python3
"""Trace-level assertions for c7_timer_tick (level-2 trace). Mirrors
tests/c7_timer_tick.s — change together.

The .s already checks the tick values through RAM; this re-derives the
whole fire grid from the trace's own DEVW stamps, per timer.md's rules
and nothing else:

1. W = the arming store's DEVW cycle (timer.md 4.2 — W is defined as
   the DEVW stamp, so the trace is the primary source, not the run).
2. Fires 1-3 (EXTINT TRAPs) at exactly W+100m; fire 4 late (past
   W+400, the masked gap) — exactly ONE delivery for >2 elapsed
   periods (TMR-17); fire 5 at exactly the first grid point past A4
   (the 4th ACK's DEVW cycle — TMR-08 phase-lock); fire 6 at W3+40
   where W3 is the rewrite store's DEVW cycle (TMR-06).
3. Handler COUNT stores (MEMW at TMR_TICK_SLOT) are each fire's
   TRAP cycle + 1.
4. Every COUNT MEMR's value equals its own record cycle — TMR-02's
   trace shape (the boundary-preceding-the-load rule).
5. PERIOD/ACK DEVW value sequences and the T-12 classification.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evcheck as C  # noqa: E402
import tracefile as T  # noqa: E402
import encoding as E  # noqa: E402

WHO = "c7_timer_tick"

TIMER = 0x0F060000
TMR_TICK_SLOT = 0x7C0
N = 100


def main():
    if len(sys.argv) != 2:
        C.fail(WHO, "usage: c7_timer_tick.py TRACE")
    recs = T.read_records(sys.argv[1])

    C.check_classification(WHO, recs)
    C.check_trap_census(WHO, recs, {E.CAUSES["EXTINT"]: 6})

    periods = [(r.fields["cycle"], r.fields["val"]) for r in recs
               if r.type == T.T_DEVW and r.fields["ea"] == TIMER + 8]
    if [v for _, v in periods] != [N, 0, 1000, 40, 0]:
        C.fail(WHO, f"PERIOD write sequence {[v for _, v in periods]}, "
                    f"want [100, 0, 1000, 40, 0]")
    w = periods[0][0]           # the arming DEVW stamp IS W
    w3 = periods[3][0]          # the rewrite's stamp
    if w3 != periods[2][0] + 1:
        C.fail(WHO, "rewrite store is not the instruction after the "
                    "1000-arm — the .s and this check drifted apart")

    acks = [(r.fields["cycle"], r.fields["val"]) for r in recs
            if r.type == T.T_DEVW and r.fields["ea"] == TIMER + 0x18]
    if len(acks) != 6 or any(v != 1 for _, v in acks):
        C.fail(WHO, f"want exactly 6 ACK stores of value 1, got {acks}")
    a4 = acks[3][0]

    fires = [r.fields["cycle"] for r in recs if r.type == T.T_TRAP]
    for m in (1, 2, 3):
        if fires[m - 1] != w + N * m:
            C.fail(WHO, f"fire {m} at cycle {fires[m-1]}, want "
                        f"W+{N*m} = {w + N*m} (TMR-03/08)")
    if fires[3] <= w + 4 * N:
        C.fail(WHO, f"fire 4 at {fires[3]} is not late (<= W+400): "
                    f"the masked-gap phase went vacuous")
    m5 = (a4 - w) // N + 1      # first grid point past A4 (timer.md 4.4)
    if fires[4] != w + N * m5:
        C.fail(WHO, f"fire 5 at {fires[4]}, want the phase-locked grid "
                    f"point W+{N*m5} = {w + N*m5} (TMR-08)")
    if fires[5] != w3 + 40:
        C.fail(WHO, f"fire 6 at {fires[5]}, want W3+40 = {w3 + 40}: "
                    f"rewrite must re-arm fresh from the new W (TMR-06)")

    ticks = [r.fields["val"] for r in recs
             if r.type == T.T_MEMW and r.fields["ea"] == TMR_TICK_SLOT]
    if ticks != [0] + [f + 1 for f in fires]:
        C.fail(WHO, f"handler COUNT stores {ticks}, want the init 0 "
                    f"then each fire's TRAP cycle + 1")

    for r in recs:
        if r.type == T.T_MEMR and r.fields["ea"] == TIMER:
            if r.fields["val"] != r.fields["cycle"]:
                C.fail(WHO, f"COUNT MEMR at cycle {r.fields['cycle']} "
                            f"returned {r.fields['val']}: must equal "
                            f"its own boundary cycle (TMR-02)")
    sys.exit(0)


if __name__ == "__main__":
    main()
