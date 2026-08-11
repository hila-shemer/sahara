#!/usr/bin/env bash
# Trace-level assertions for c7_rng_overflow (args: trace sym img) —
# recorded EVENTs equal the ACCEPTED prefixes (truncated bytes, zero-
# accepted absent), exact 256-word pop sequence, STATUS cap; logic in
# c7_rng_overflow.py (needs the level-2 trace the MANIFEST requests).
set -u
exec python3 "$(dirname "$0")/c7_rng_overflow.py" "$1"
