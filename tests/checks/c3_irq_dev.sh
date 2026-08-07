#!/usr/bin/env bash
# Trace-level assertions for c3_irq_dev (args: trace sym img) — the
# atomicity-under-interrupts contract lives in the record stream, not
# in register results; logic in c3_irq_dev.py (needs the level-2 trace
# this test's MANIFEST line requests).
set -u
exec python3 "$(dirname "$0")/c3_irq_dev.py" "$1"
