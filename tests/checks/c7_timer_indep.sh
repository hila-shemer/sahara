#!/usr/bin/env bash
# Trace-level assertions for c7_timer_indep (args: trace sym img) —
# timer.md grid/census pins re-derived from DEVW stamps; logic in
# c7_timer_indep.py (needs the level-2 trace the MANIFEST requests).
set -u
exec python3 "$(dirname "$0")/c7_timer_indep.py" "$1"
