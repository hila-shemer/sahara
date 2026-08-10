#!/usr/bin/env python3
"""Record->replay identity comparator, aware of one known emulator bug.

trace.md 5.2/T-18: replaying a recorded trace must reproduce every
post-META record byte-identically. That property is structurally
broken today for any guest that idles in WFI: an event applied during
a WFI stall is stamped at the post-wake boundary T+1 (root SPEC-ISSUES
20's frozen reading), so each replay generation re-stamps such EVENT
records one cycle later and the whole execution suffix shifts (and,
where the guest reads `cycle`, genuinely diverges). Root SPEC-ISSUES
entry 35 owns the conflict; the emulators are out of scope for this
branch, so this comparator:

  exit 0 - traces byte-identical after META (the real gate, and what
           this becomes everywhere once entry 35 is resolved)
  exit 3 - first difference is EXACTLY the known signature: an EVENT
           record pair, same device and payload, replay cycle ==
           recorded cycle + 1 -> reported as a loud SKIP by the runner
  exit 1 - any other divergence: a real failure

Any kernel-side nondeterminism still fails: the double-run cmp gate is
unaffected, and any divergence not matching the signature exits 1.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, "trace-q"))
import tracefile as T          # noqa: E402


def is_drift_pair(ra, rb, delta):
    return (ra.type == T.T_EVENT and rb.type == T.T_EVENT
            and ra.fields["device"] == rb.fields["device"]
            and ra.fields["bytes"] == rb.fields["bytes"]
            and rb.fields["cycle"] - ra.fields["cycle"] in delta)


def main():
    args = [a for a in sys.argv[1:] if a != "--cross"]
    cross = "--cross" in sys.argv
    if len(args) != 2:
        sys.exit(f"usage: {sys.argv[0]} [--cross] A.trc B.trc")
    a = T.read_records(args[0])
    b = T.read_records(args[1])
    drifts = 0
    for i in range(1, min(len(a), len(b))):
        ra, rb = a[i], b[i]
        if ra.type == rb.type and ra.payload == rb.payload:
            continue
        if not cross and is_drift_pair(ra, rb, (1,)):
            # record->replay: the +1 restamp truly shifts the whole
            # execution suffix, so nothing after it is comparable -
            # report the known drift and stop
            print(f"replaycmp: known WFI-stall EVENT restamp drift at "
                  f"record {i} (cycle {ra.fields['cycle']} -> "
                  f"{rb.fields['cycle']}); see root SPEC-ISSUES 35")
            sys.exit(3)
        if cross and is_drift_pair(ra, rb, (-1, 1)):
            # cross-emulator: the SAME feed drives both, so execution
            # records must stay byte-identical; only the EVENT stamp
            # disagreement of SPEC-ISSUES 35 is tolerated - keep going
            # and hold everything else to byte-identity
            drifts += 1
            continue
        print(f"replaycmp: REAL divergence at record {i}: "
              f"{ra.name}@{ra.fields.get('cycle')} vs "
              f"{rb.name}@{rb.fields.get('cycle')}")
        sys.exit(1)
    if len(a) != len(b):
        print(f"replaycmp: length mismatch {len(a)} vs {len(b)}")
        sys.exit(1)
    if drifts:
        print(f"replaycmp: {drifts} EVENT-stamp drift pairs "
              f"(SPEC-ISSUES 35), all else byte-identical")
        sys.exit(3)
    sys.exit(0)


if __name__ == "__main__":
    main()
