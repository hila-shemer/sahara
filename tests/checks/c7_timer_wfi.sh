#!/usr/bin/env bash
# Trace-level assertions for c7_timer_wfi (args: trace sym img) —
# timer.md grid/census pins re-derived from DEVW stamps; logic in
# c7_timer_wfi.py (needs the level-2 trace the MANIFEST requests).
set -u
exec python3 "$(dirname "$0")/c7_timer_wfi.py" "$1"
