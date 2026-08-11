#!/usr/bin/env python3
"""Trace-level assertions for c7_timer_deverr (level-2 trace). Mirrors
tests/c7_timer_deverr.s — change together.

The .s checks causes and state through RAM; the trace adds what it
cannot see:

1. Exact trap census {DEVERR: 18, UNALIGNED: 2} — under an exact
   count, the predicated-false ACK's absence from the census IS the
   TMR-15 squash proof (a 19th DEVERR would be the squashed access
   reaching the device).
2. Faulting accesses leave no access records: DEVW in the timer
   window happens only at PERIOD (the two legal arm/disarm pairs) and
   ACK (the two legal value-1 stores); MEMR only at PERIOD/STATUS
   (the readback probes). Nothing at 0x20/0xFFF8/COUNT, no atomic
   MEMR footprint (T-08/TMR-14).
3. Every DEVERR baddr lands in the timer window; the UNALIGNED baddrs
   are exactly the two misaligned eas (precedence, TMR-15).
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evcheck as C  # noqa: E402
import tracefile as T  # noqa: E402
import encoding as E  # noqa: E402

WHO = "c7_timer_deverr"

TIMER = 0x0F060000
WIN_END = TIMER + 0x10000


def main():
    if len(sys.argv) != 2:
        C.fail(WHO, "usage: c7_timer_deverr.py TRACE")
    recs = T.read_records(sys.argv[1])

    C.check_classification(WHO, recs)
    C.check_trap_census(WHO, recs, {E.CAUSES["DEVERR"]: 18,
                                    E.CAUSES["UNALIGNED"]: 2})

    unaligned_baddrs = []
    for r in recs:
        if r.type == T.T_TRAP:
            b = r.fields["baddr"]
            if r.fields["cause"] == E.CAUSES["DEVERR"] \
                    and not TIMER <= b < WIN_END:
                C.fail(WHO, f"DEVERR baddr 0x{b:x} outside the timer "
                            f"window")
            if r.fields["cause"] == E.CAUSES["UNALIGNED"]:
                unaligned_baddrs.append(b)
    if unaligned_baddrs != [TIMER + 4, TIMER + 1]:
        C.fail(WHO, f"UNALIGNED baddrs {[hex(b) for b in unaligned_baddrs]},"
                    f" want [TB+4, TB+1] (precedence order in the .s)")

    devw = [(r.fields["ea"], r.fields["val"]) for r in recs
            if r.type == T.T_DEVW and TIMER <= r.fields["ea"] < WIN_END]
    # arm N=1, good ACK, disarm — the only device stores that may land
    if devw != [(TIMER + 8, 1), (TIMER + 0x18, 1), (TIMER + 8, 0)]:
        C.fail(WHO, f"timer-window DEVW records {devw}: a faulting or "
                    f"squashed store left a footprint")
    memr_eas = {r.fields["ea"] for r in recs
                if r.type == T.T_MEMR and TIMER <= r.fields["ea"] < WIN_END}
    if not memr_eas <= {TIMER + 8, TIMER + 0x10}:
        C.fail(WHO, f"timer-window MEMR eas {sorted(hex(a) for a in memr_eas)}"
                    f": only the PERIOD/STATUS readback probes may read")
    sys.exit(0)


if __name__ == "__main__":
    main()
