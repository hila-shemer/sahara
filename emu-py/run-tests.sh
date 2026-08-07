#!/bin/sh
# emu-py build/test entry point: encoding self-check + crosscheck against
# ISA-SPEC.md (CI-forever per TOOLING-SPEC), then the unit/smoke suite
# (includes decoder fuzz and CLI determinism double-runs).
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python3 encoding.py check
python3 crosscheck.py ISA-SPEC.md
python3 -m pytest emu-py/tests -q "$@"
# Shared conformance suite (toolchain-owned; lands via merges). The
# harness itself runs every test twice and diffs traces.
if [ -x "$ROOT/tests/run-tests.sh" ]; then
    EMU="$ROOT/emu-py/sahara-emu-py" "$ROOT/tests/run-tests.sh"
fi
