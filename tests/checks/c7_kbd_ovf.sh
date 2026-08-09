#!/usr/bin/env bash
# Trace-level assertions for c7_kbd_ovf (args: trace sym img) — EVENT-vs-
# feed byte equality, pop/geometry read sequences, trap census;
# logic in c7_kbd_ovf.py (needs the level-2 trace the MANIFEST requests).
set -u
exec python3 "$(dirname "$0")/c7_kbd_ovf.py" "$1"
