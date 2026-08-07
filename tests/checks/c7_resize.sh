#!/usr/bin/env bash
# Trace-level assertions for c7_resize (args: trace sym img) — EVENT-vs-
# feed byte equality, pop/geometry read sequences, trap census;
# logic in c7_resize.py (needs the level-2 trace the MANIFEST requests).
set -u
exec python3 "$(dirname "$0")/c7_resize.py" "$1"
