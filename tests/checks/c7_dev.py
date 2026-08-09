#!/usr/bin/env python3
"""Trace-level assertions for c7_dev / c7_dev_ordq (level-2 trace).

What the .s cannot see about itself lives here:

1. Access classification (trace.md T-12): stores to device space are
   DEVW, stores to RAM are MEMW — no MEMW at or above the device base,
   no DEVW below it.
2. Register reads really happened as device loads with the pinned
   reference values (MEMR at the register ea with the expected val):
   WIDTH/HEIGHT/STRIDE/FORMAT, NIC MAC, and the kbd DATA all-ones
   sentinel.
3. D-13 ordering: the trace is split at the LAST PRESENT DEVW
   (display+0). Both pre-present pixels (+0, +4) are written before
   it; the device-state diff across the split over the whole pixel
   window is EXACTLY the post-present blue pixel at +8 — the
   snapshot-diff primitive from checks/devstate.py.
4. Trap census: exactly 3 UNALIGNED and 10 DEVERR deliveries, nothing
   else — mirrors the fault section of c7_dev.s (change together).

Counts and constants mirror tests/c7_dev.s and PLATFORM-SPEC 1/4-7.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "trace-q"))
sys.path.insert(0, ROOT)
import devstate  # noqa: E402
import tracefile as T  # noqa: E402
import encoding as E  # noqa: E402

DEV_BASE = 0x0F000000
DISPLAY = 0x0F000000
KBD = 0x0F010000
NIC = 0x0F030000
PIXBUF = 0x10000000
PIXBUF_END = PIXBUF + (16 << 20)   # 16 MB window (devspec reference)

EXPECT_MEMR = [                     # (ea, value) — must each appear
    (DISPLAY + 8, 640),
    (DISPLAY + 16, 480),
    (DISPLAY + 24, 2560),
    (DISPLAY + 32, 1),
    (NIC + 32, 0x0000563412005452),
    (KBD + 0, 0xFFFFFFFFFFFFFFFF),
]
EXPECT_UNALIGNED = 3
EXPECT_DEVERR = 10


def fail(msg):
    print(f"checks/c7_dev: {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    if len(sys.argv) != 2:
        fail("usage: c7_dev.py TRACE")
    recs = T.read_records(sys.argv[1])

    memr_seen = set()
    causes = {}
    present_indices = []
    for i, r in enumerate(recs):
        f = r.fields
        if r.type == T.T_MEMW and f["ea"] >= DEV_BASE:
            fail(f"record {i}: MEMW at device ea 0x{f['ea']:x} — "
                 f"device stores must be DEVW (T-12)")
        if r.type == T.T_DEVW:
            if f["ea"] < DEV_BASE:
                fail(f"record {i}: DEVW at RAM ea 0x{f['ea']:x}")
            if f["ea"] == DISPLAY and f["size"] == 8:
                present_indices.append(i)
        if r.type == T.T_MEMR and (f["ea"], f["val"]) in \
                set(EXPECT_MEMR) - memr_seen:
            memr_seen.add((f["ea"], f["val"]))
        if r.type == T.T_TRAP:
            causes[f["cause"]] = causes.get(f["cause"], 0) + 1

    missing = set(EXPECT_MEMR) - memr_seen
    if missing:
        fail("expected register-read MEMRs absent or wrong-valued: "
             + ", ".join(f"ea=0x{a:x} val=0x{v:x}"
                         for a, v in sorted(missing)))

    # trap census (change tests/c7_dev.s and these numbers together)
    want = {E.CAUSES["UNALIGNED"]: EXPECT_UNALIGNED,
            E.CAUSES["DEVERR"]: EXPECT_DEVERR}
    if causes != want:
        names = {v: k for k, v in E.CAUSES.items()}
        fail("trap census mismatch: got {"
             + ", ".join(f"{names.get(c, c)}: {n}"
                         for c, n in sorted(causes.items()))
             + f"}}, want 3 UNALIGNED + 10 DEVERR")

    # D-13 around the LAST PRESENT: exactly 2 PRESENT DEVWs exist
    # (the ordering-drain one and the D-13 one)
    if len(present_indices) != 2:
        fail(f"expected exactly 2 PRESENT DEVWs, got "
             f"{len(present_indices)}")
    split = present_indices[-1]
    before = devstate.device_state(recs, PIXBUF, PIXBUF_END,
                                   upto_index=split)
    after = devstate.device_state(recs, PIXBUF, PIXBUF_END)
    for a in (PIXBUF, PIXBUF + 4):
        if a not in before:
            fail(f"pre-present pixel store at 0x{a:x} missing from the "
                 f"state at the last PRESENT (D-13)")
    diff = devstate.state_diff(before, after)
    want_diff = {PIXBUF + 8: (None, 0xFF),
                 PIXBUF + 9: (None, 0x00),
                 PIXBUF + 10: (None, 0x00),
                 PIXBUF + 11: (None, 0x00)}
    if diff != want_diff:
        fail(f"post-present pixel-window diff wrong: "
             f"{{{', '.join(f'0x{a:x}: {v}' for a, v in sorted(diff.items()))}}} "
             f"— D-13 says only the post-PRESENT store may differ")
    sys.exit(0)


if __name__ == "__main__":
    main()
