#!/usr/bin/env bash
# Trace-level assertions for dma_copy (args: trace sym img) — the
# no-records clause: one doorbell DEVW, zero writes in the destination
# range, zero traps; logic in dma_copy.py.
set -u
exec python3 "$(dirname "$0")/dma_copy.py" "$1"
