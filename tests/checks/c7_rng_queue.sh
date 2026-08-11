#!/usr/bin/env bash
# Trace-level assertions for c7_rng_queue (args: trace sym img) —
# EVENT-vs-feed byte equality, exact DATA pop sequence, cycle-exact
# STATUS visibility, empty census; logic in c7_rng_queue.py (needs
# the level-2 trace the MANIFEST line requests).
set -u
exec python3 "$(dirname "$0")/c7_rng_queue.py" "$1"
