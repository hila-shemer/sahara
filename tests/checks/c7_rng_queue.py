#!/usr/bin/env python3
"""Trace-level assertions for c7_rng_queue (level-2 trace). Mirrors
tests/c7_rng_queue.s and tests/events/c7_rng_queue.py — change all
three together.

What the .s cannot see about itself:
1. The recorded EVENT records equal the feed byte-for-byte (nothing
   here truncates, so recorded == arrival — evcheck rationale; on the
   WFI-woken record the cycle equality is exact because the wake
   lands AT the event cycle).
2. The DATA pop sequence is EXACTLY the six feed words in feed order
   — six device reads, no more: the predicated-false pop (RNG-10)
   must NOT appear as a MEMR, and nothing popped early.
3. STATUS reads: every read before cycle 5000 is 0 (RNG-18's
   invisible-before leg, cycle-exact), and the read sequence from the
   poll exit on is exactly [4, 4, 4, 3, 2, 1, 0, 2, 0].
4. No traps at all (IE off at both levels; nothing faults — the
   STATUS-then-pop contract never trips E6).
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evcheck as C  # noqa: E402
import tracefile as T  # noqa: E402

WHO = "c7_rng_queue"
RNG = 0x0F080000

POPS = [0xD1CE00000000A001, 0xD1CE00000000A002, 0xD1CE00000000A003,
        0xD1CE00000000A004, 0xD1CE00000000B001, 0xD1CE00000000B002]
STATUS_TAIL = [4, 4, 4, 3, 2, 1, 0, 2, 0]


def main():
    if len(sys.argv) != 2:
        C.fail(WHO, "usage: c7_rng_queue.py TRACE")
    recs = T.read_records(sys.argv[1])

    C.check_classification(WHO, recs)
    C.check_events_match_feed(WHO, recs, "c7_rng_queue")
    C.check_seq(WHO, recs, RNG + 0, POPS, "rng DATA")
    C.check_trap_census(WHO, recs, {})

    status = [(r.fields["cycle"], r.fields["val"]) for r in recs
              if r.type == T.T_MEMR and r.fields["ea"] == RNG + 8]
    vals = [v for _, v in status]
    if len(vals) < len(STATUS_TAIL) or vals[-len(STATUS_TAIL):] != \
            STATUS_TAIL:
        C.fail(WHO, f"STATUS tail is {vals[-len(STATUS_TAIL):]}, want "
                    f"{STATUS_TAIL}")
    for cyc, v in status:
        if cyc < 5000 and v != 0:
            C.fail(WHO, f"nonzero STATUS read {v} at cycle {cyc} < "
                        f"5000 (RNG-18)")
    head = vals[:-len(STATUS_TAIL)]
    if not head or any(v != 0 for v in head):
        C.fail(WHO, f"pre-batch STATUS reads {head}: the invisible-"
                    f"before leg needs at least one 0 and nothing else")
    sys.exit(0)


if __name__ == "__main__":
    main()
