#!/usr/bin/env bash
# Harness contract entry point. Thin wrapper: delegates to the real test
# entry point (emu-py/run-tests.sh — unit suite + conformance suite) and
# tees combined stdout+stderr to test_results.txt, preserving its exit
# status. See DECISIONS.md D4.
set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"

"$ROOT/emu-py/run-tests.sh" 2>&1 | tee "$ROOT/test_results.txt"
exit "${PIPESTATUS[0]}"
