#!/usr/bin/env bash
# Trace-level assertions for dma_fill (args: trace sym img) — the
# no-records clause at LEN 32768; logic in dma_fill.py.
set -u
exec python3 "$(dirname "$0")/dma_fill.py" "$1"
