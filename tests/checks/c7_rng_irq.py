#!/usr/bin/env python3
"""Trace-level assertions for c7_rng_irq (level-2 trace). Mirrors
tests/c7_rng_irq.s and tests/events/c7_rng_irq.py — change all three
together.

What the .s cannot see about itself:
1. The recorded EVENT records equal the feed byte-for-byte (nothing
   truncates here); the WFI-woken record's recorded cycle is exactly
   30000 — the wake IS the event cycle.
2. Exactly ONE trap in the whole run: EXTINT, tl_after 1 — nothing
   delivered while CTRL.IE was 0 with depth 2 (the .s's poll loop ran
   many boundaries in that state), nothing on the IE-off WFI wake, and
   nothing after the drain deasserted the level.
3. The EXTINT delivery cycle is >= the cycle of the CTRL=2 DEVW that
   armed it — the enable-then-deliver ordering trace-side.
4. DATA pops are exactly the three feed words in order.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evcheck as C  # noqa: E402
import tracefile as T  # noqa: E402
import encoding as E  # noqa: E402

WHO = "c7_rng_irq"
RNG = 0x0F080000

POPS = [0x1BAD5EED00000001, 0x1BAD5EED00000002, 0x1BAD5EED00000003]


def main():
    if len(sys.argv) != 2:
        C.fail(WHO, "usage: c7_rng_irq.py TRACE")
    recs = T.read_records(sys.argv[1])

    C.check_classification(WHO, recs)
    C.check_events_match_feed(WHO, recs, "c7_rng_irq")
    C.check_seq(WHO, recs, RNG + 0, POPS, "rng DATA")
    C.check_trap_census(WHO, recs, {E.CAUSES["EXTINT"]: 1})

    evs = [r for r in recs if r.type == T.T_EVENT]
    if evs[-1].fields["cycle"] != 30000:
        C.fail(WHO, f"WFI-woken EVENT recorded at cycle "
                    f"{evs[-1].fields['cycle']}, want exactly 30000")

    arm = [r.fields["cycle"] for r in recs
           if r.type == T.T_DEVW and r.fields["ea"] == RNG + 0x10
           and r.fields["val"] == 2]
    trap = [r.fields["cycle"] for r in recs if r.type == T.T_TRAP]
    if not arm or trap[0] < arm[0]:
        C.fail(WHO, f"EXTINT at cycle {trap[0]} does not follow the "
                    f"CTRL.IE arm at {arm[0] if arm else None}")
    sys.exit(0)


if __name__ == "__main__":
    main()
