#!/usr/bin/env bash
# Trace-level assertion for c7_mem (args: trace sym img) — no access
# footprint in device space; logic in c7_mem.py.
set -u
exec python3 "$(dirname "$0")/c7_mem.py" "$1"
