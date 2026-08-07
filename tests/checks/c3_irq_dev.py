#!/usr/bin/env python3
"""Trace-level assertions for c3_irq_dev (level-2 trace).

The atomicity contract (ISA-SPEC 5.4: no other access ordered between
an atomic's read and its write) is invisible to the .s test itself — a
delivery inside an AMO would still add up. It IS visible in the trace:
an AMO's MEMR and MEMW carry the instruction's cycle, and a delivery
between them would interpose records with a different cycle
(SPEC-ISSUES 25). Asserted here:

1. Exactly 32 MEMR@ATOMIC_BOX are AMO reads: each followed by the
   matching MEMW@ATOMIC_BOX before any record with a different cycle
   appears. Exactly 1 more is the test's plain readback (unpaired).
2. Exactly 8 TIMER TRAP records (one per armed iteration).
3. Non-vacuity: at least 2 of those deliveries land strictly inside
   the AMO cycle span — the sweep really put deliveries near bursts.
4. No MEMR/MEMW/DEVW at or above the device-space base: the DEVERR'd
   atomics of phase 2 must leave no access footprint (SPEC-ISSUES 17).

Counts 32/1/8 mirror the .s (8 bursts x 4 amoadds, one readback, one
delivery per arm) — change both together.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "trace-q"))
sys.path.insert(0, ROOT)
import tracefile as T  # noqa: E402
import encoding as E  # noqa: E402

ATOMIC_BOX = 0x740          # tests/README.md scratch map
DEV_SPACE_BASE = 0x0F000000  # PLATFORM-SPEC 1: device space starts here


def fail(msg):
    print(f"checks/c3_irq_dev: {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    if len(sys.argv) != 2:
        fail("usage: c3_irq_dev.py TRACE")
    recs = T.read_records(sys.argv[1])

    paired = unpaired = 0
    amo_cycles = []
    timer_cycles = []
    for i, r in enumerate(recs):
        if (r.type == T.T_TRAP
                and r.fields["cause"] == E.CAUSES["TIMER"]):
            timer_cycles.append(r.fields["cycle"])
        if r.type in (T.T_MEMR, T.T_MEMW, T.T_DEVW) \
                and r.fields["ea"] >= DEV_SPACE_BASE:
            fail(f"record {i}: access at device-space ea "
                 f"0x{r.fields['ea']:x} — a DEVERR'd atomic must not "
                 f"touch the device")
        if r.type == T.T_MEMR and r.fields["ea"] == ATOMIC_BOX:
            c = r.fields["cycle"]
            j = i + 1
            found = False
            while j < len(recs) and recs[j].fields.get("cycle") == c:
                if (recs[j].type == T.T_MEMW
                        and recs[j].fields["ea"] == ATOMIC_BOX):
                    found = True
                    break
                j += 1
            if found:
                paired += 1
                amo_cycles.append(c)
            else:
                unpaired += 1

    if paired != 32 or unpaired != 1:
        fail(f"expected 32 paired (AMO) + 1 unpaired (readback) "
             f"MEMR@0x{ATOMIC_BOX:x}, got {paired} paired + "
             f"{unpaired} unpaired — a split AMO shows up here as a "
             f"pairing failure")
    if len(timer_cycles) != 8:
        fail(f"expected exactly 8 TIMER deliveries, got "
             f"{len(timer_cycles)}")
    lo, hi = min(amo_cycles), max(amo_cycles)
    inside = [c for c in timer_cycles if lo < c < hi]
    if len(inside) < 2:
        fail(f"vacuous run: only {len(inside)} TIMER deliveries inside "
             f"the AMO span [{lo},{hi}] (cycles {timer_cycles}) — the "
             f"offset sweep no longer straddles the bursts")
    sys.exit(0)


if __name__ == "__main__":
    main()
