#!/usr/bin/env python3
"""Trace-level assertions for c7_timer_indep (level-2 trace). Mirrors
tests/c7_timer_indep.s — change together.

T is re-derived from the trace alone: the arming store's DEVW stamp W
plus its value N (the .s arranges timecmp = W + N). Pinned:

1. Exactly one TIMER and one EXTINT delivery; the TIMER's TRAP cycle
   is exactly T and it precedes the EXTINT in the record stream —
   ISA 7.5's fixed priority at the simultaneous boundary (TMR-19).
2. The in-handler STATUS snapshot (MEMW at TMR_W_SLOT) is 1: draining
   the sreg side left the device pending.
3. The two recorded causes land in the right slots; classification.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evcheck as C  # noqa: E402
import tracefile as T  # noqa: E402
import encoding as E  # noqa: E402

WHO = "c7_timer_indep"

TIMER = 0x0F060000
TMR_TICK_SLOT = 0x7C0
TMR_W_SLOT = 0x7F0
TMR_AUX_SLOT = 0x7F8


def memw_vals(recs, ea):
    return [r.fields["val"] for r in recs
            if r.type == T.T_MEMW and r.fields["ea"] == ea]


def main():
    if len(sys.argv) != 2:
        C.fail(WHO, "usage: c7_timer_indep.py TRACE")
    recs = T.read_records(sys.argv[1])

    C.check_classification(WHO, recs)
    C.check_trap_census(WHO, recs, {E.CAUSES["TIMER"]: 1,
                                    E.CAUSES["EXTINT"]: 1})

    periods = [(r.fields["cycle"], r.fields["val"]) for r in recs
               if r.type == T.T_DEVW and r.fields["ea"] == TIMER + 8]
    if len(periods) != 2 or periods[1][1] != 0:
        C.fail(WHO, f"PERIOD writes {periods}, want [arm, disarm]")
    w, n = periods[0]
    t = w + n

    traps = [(r.fields["cause"], r.fields["cycle"]) for r in recs
             if r.type == T.T_TRAP]
    if traps[0][0] != E.CAUSES["TIMER"]:
        C.fail(WHO, f"first delivery is cause {traps[0][0]}: TIMER "
                    f"must outrank EXTINT at the shared boundary "
                    f"(ISA 7.5, TMR-19)")
    if traps[0][1] != t:
        C.fail(WHO, f"TIMER delivered at {traps[0][1]}, want exactly "
                    f"T = W+N = {t}")
    if traps[1][1] <= t:
        C.fail(WHO, f"EXTINT delivered at {traps[1][1]}, not after T")

    if memw_vals(recs, TMR_TICK_SLOT) != [E.CAUSES["TIMER"]]:
        C.fail(WHO, "first recorded cause is not TIMER")
    if memw_vals(recs, TMR_W_SLOT) != [1]:
        C.fail(WHO, "device STATUS inside the TIMER handler was not 1: "
                    "draining timecmp must leave the device pending")
    if memw_vals(recs, TMR_AUX_SLOT) != [E.CAUSES["EXTINT"]]:
        C.fail(WHO, "second recorded cause is not EXTINT")
    sys.exit(0)


if __name__ == "__main__":
    main()
