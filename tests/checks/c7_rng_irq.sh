#!/usr/bin/env bash
# Trace-level assertions for c7_rng_irq (args: trace sym img) —
# EVENT-vs-feed byte equality with the exact-cycle WFI wake, the
# single-EXTINT census, arm-before-delivery ordering; logic in
# c7_rng_irq.py (needs the level-2 trace the MANIFEST line requests).
set -u
exec python3 "$(dirname "$0")/c7_rng_irq.py" "$1"
