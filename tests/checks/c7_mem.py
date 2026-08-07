#!/usr/bin/env python3
"""Trace-level assertion for c7_mem: the DEVERR'd device accesses in
section C7.5 must leave no store footprint in device space — a
faulting instruction does not retire and performs no access
(SPEC-ISSUES 17). Level-1 trace suffices (MEMW/DEVW are recorded).
A negative assertion, so it is exercised for real against any trace.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "trace-q"))
import tracefile as T  # noqa: E402

DEV_SPACE_BASE = 0x0F000000  # PLATFORM-SPEC 1


def main():
    if len(sys.argv) != 2:
        print("checks/c7_mem: usage: c7_mem.py TRACE", file=sys.stderr)
        sys.exit(1)
    for i, r in enumerate(T.read_records(sys.argv[1])):
        if r.type in (T.T_MEMW, T.T_MEMR, T.T_DEVW) \
                and r.fields["ea"] >= DEV_SPACE_BASE:
            print(f"checks/c7_mem: record {i}: access at device-space "
                  f"ea 0x{r.fields['ea']:x} — DEVERR'd accesses must "
                  f"leave no footprint", file=sys.stderr)
            sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
