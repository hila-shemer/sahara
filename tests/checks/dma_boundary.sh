#!/usr/bin/env bash
# Trace-level assertions for dma_boundary (args: trace sym img) — 7
# doorbell DEVWs (the BUSY-rejected one recordless), census exactly
# one DEVERR, record-free destinations; logic in dma_boundary.py.
set -u
exec python3 "$(dirname "$0")/dma_boundary.py" "$1"
