#!/usr/bin/env python3
"""Trace-level assertions for c7_timer_wfi (level-2 trace). Mirrors
tests/c7_timer_wfi.s — change together.

1. W = the arming store's DEVW stamp; the two post-WFI COUNT MEMRs
   read exactly W+50 and W+100 (TMR-18: the wake lands AT next_fire,
   the event-style ISA 7.6 reading, not timecmp's T+1) — and every
   COUNT MEMR value equals its own record cycle (TMR-02 shape).
2. Exactly 2 EXTINT deliveries: the first at exactly W+150 (level
   recognized at the fire boundary — the main flow is mid-spin, IE
   on), the second at first+7 — the re-trap one boundary after
   h_lvl's no-ACK IRET (7 instructions to that IRET; TMR-16).
3. PERIOD/ACK DEVW sequences and T-12 classification.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evcheck as C  # noqa: E402
import tracefile as T  # noqa: E402
import encoding as E  # noqa: E402

WHO = "c7_timer_wfi"

TIMER = 0x0F060000
N = 50
HANDLER_RETRAP_DELTA = 7    # h_lvl: 6 insns + the (p2) iret


def main():
    if len(sys.argv) != 2:
        C.fail(WHO, "usage: c7_timer_wfi.py TRACE")
    recs = T.read_records(sys.argv[1])

    C.check_classification(WHO, recs)
    C.check_trap_census(WHO, recs, {E.CAUSES["EXTINT"]: 2})

    periods = [(r.fields["cycle"], r.fields["val"]) for r in recs
               if r.type == T.T_DEVW and r.fields["ea"] == TIMER + 8]
    if [v for _, v in periods] != [N, 0]:
        C.fail(WHO, f"PERIOD writes {[v for _, v in periods]}, want "
                    f"[50, 0]")
    w = periods[0][0]

    counts = [(r.fields["cycle"], r.fields["val"]) for r in recs
              if r.type == T.T_MEMR and r.fields["ea"] == TIMER]
    for cyc, val in counts:
        if val != cyc:
            C.fail(WHO, f"COUNT MEMR at cycle {cyc} returned {val}: "
                        f"must equal its own boundary cycle (TMR-02)")
    # the .s reads COUNT once pre-arm and once after each WFI wake
    vals = [v for _, v in counts]
    if vals[1:] != [w + N, w + 2 * N]:
        C.fail(WHO, f"post-WFI COUNT reads {vals[1:]}, want "
                    f"[W+50, W+100] = {[w + N, w + 2 * N]}: the wake "
                    f"must land at exactly next_fire (TMR-18)")

    fires = [r.fields["cycle"] for r in recs if r.type == T.T_TRAP]
    if fires[0] != w + 3 * N:
        C.fail(WHO, f"delivery at {fires[0]}, want W+150 = {w + 3 * N}")
    if fires[1] != fires[0] + HANDLER_RETRAP_DELTA:
        C.fail(WHO, f"re-trap at {fires[1]}, want first+"
                    f"{HANDLER_RETRAP_DELTA} = the boundary after the "
                    f"no-ACK IRET (TMR-16)")

    acks = [r.fields["val"] for r in recs
            if r.type == T.T_DEVW and r.fields["ea"] == TIMER + 0x18]
    if acks != [1, 1, 1]:
        C.fail(WHO, f"ACK stores {acks}, want three of value 1")
    sys.exit(0)


if __name__ == "__main__":
    main()
