#!/usr/bin/env bash
# Trace-level assertions for dma_regs (args: trace sym img) — register
# MEMR values, exact DEVERR/UNALIGNED census, single benign ack DEVW;
# logic in dma_regs.py (needs the level-2 trace the MANIFEST requests).
set -u
exec python3 "$(dirname "$0")/dma_regs.py" "$1"
