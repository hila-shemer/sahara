#!/usr/bin/env python3
"""Trace-level assertions for c7_rng_overflow (level-2 trace).
Mirrors tests/c7_rng_overflow.s and tests/events/c7_rng_overflow.py —
change all three together.

THE assertion of this test lives here, not in the .s: the recorded
EVENT records are the generator's ACCEPTED list — the third record's
payload is its accepted 8-word PREFIX (64 bytes, truncated bytes and
not raw feed), and the zero-accepted fourth record recorded NOTHING
(rng.md 4.2, trace.md 4.6, RNG-R2). The .s can only see what popped;
what got recorded is exactly what a replay will be fed, so this is
the record->replay fixed point checked at its source.

Also: the DATA pops are exactly the 256 accepted words in order, the
drain count stored at RNG_SCRATCH is 256, no STATUS read ever shows a
value other than 0 or the 256 cap (one-boundary arrival, RNG-19), and
no traps fired.
"""

import importlib.util
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evcheck as C  # noqa: E402
import tracefile as T  # noqa: E402

WHO = "c7_rng_overflow"
RNG = 0x0F080000
RNG_SCRATCH = 0x7C0
BASE = 0xC0FFEE0000000000


def load_feed_module(name):
    evdir = os.path.join(C.ROOT, "tests", "events")
    sys.path.insert(0, evdir)
    spec = importlib.util.spec_from_file_location(
        f"feed_{name}", os.path.join(evdir, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    if len(sys.argv) != 2:
        C.fail(WHO, "usage: c7_rng_overflow.py TRACE")
    recs = T.read_records(sys.argv[1])

    C.check_classification(WHO, recs)
    C.check_trap_census(WHO, recs, {})

    # Recorded EVENTs == the generator's ACCEPTED list, byte-exact —
    # NOT its EVENTS list: recorded is the accepted prefix, and the
    # zero-accepted record is absent (RNG-R2).
    feed = load_feed_module("c7_rng_overflow")
    want = [(c, d, bytes(p)) for c, d, p in feed.ACCEPTED]
    got = [(r.fields["cycle"], r.fields["device"], bytes(r.fields["bytes"]))
           for r in recs if r.type == T.T_EVENT]
    if len(got) != len(want):
        C.fail(WHO, f"{len(got)} EVENT records, want {len(want)} (the "
                    f"zero-accepted record must record nothing)")
    for i, (g, w) in enumerate(zip(got, want)):
        if g != w:
            C.fail(WHO, f"EVENT {i}: recorded (cycle={g[0]} dev={g[1]} "
                        f"len={len(g[2])} payload={g[2][:24].hex()}...) "
                        f"!= accepted (cycle={w[0]} dev={w[1]} "
                        f"len={len(w[2])})")

    # Pops: exactly the 256 accepted words, in order.
    C.check_seq(WHO, recs, RNG + 0, [BASE + i for i in range(256)],
                "rng DATA")

    # STATUS never shows anything but 0 and the cap.
    for r in recs:
        if r.type == T.T_MEMR and r.fields["ea"] == RNG + 8:
            if r.fields["val"] not in (0, 256):
                C.fail(WHO, f"STATUS read {r.fields['val']} — the "
                            f"4-record pile must land as one 0 -> 256 "
                            f"jump (RNG-19)")

    # The .s's own drain count, cross-checked from the trace.
    counts = [r.fields["val"] for r in recs
              if r.type == T.T_MEMW and r.fields["ea"] == RNG_SCRATCH]
    if counts != [256]:
        C.fail(WHO, f"RNG_SCRATCH writes {counts}, want [256]")
    sys.exit(0)


if __name__ == "__main__":
    main()
