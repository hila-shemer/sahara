#!/usr/bin/env bash
# Trace-level assertions for c7_rng_err (args: trace sym img) — exact
# 2-UNALIGNED + 17-DEVERR census, DEVW/MEMW classification, and the
# faulting-stores-record-nothing rule; logic in c7_rng_err.py.
set -u
exec python3 "$(dirname "$0")/c7_rng_err.py" "$1"
