#!/usr/bin/env bash
# Trace-level assertions for dma_err (args: trace sym img) — sixteen
# retired content-error doorbells, census exactly one EXTINT, canary-
# only destination writes; logic in dma_err.py.
set -u
exec python3 "$(dirname "$0")/dma_err.py" "$1"
