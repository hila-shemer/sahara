#!/usr/bin/env bash
# Trace-level assertions for c7_dev (args: trace sym img) — record
# classification, pinned register-read values, D-13 present ordering
# via the devstate snapshot-diff primitive, trap census; logic in
# c7_dev.py (needs the level-2 trace the MANIFEST line requests).
set -u
exec python3 "$(dirname "$0")/c7_dev.py" "$1"
