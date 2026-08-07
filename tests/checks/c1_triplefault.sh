#!/usr/bin/env bash
# Trace-level assertions for c1_triplefault (args: trace sym img).
# The run halts by triple fault. The trace must show exactly two TRAP
# records — the UNALIGNED delivery (tl_after=1) and the double-fault
# ILLEGAL delivery (tl_after=2). The triple fault itself delivers
# nothing and writes no third record (SPEC-ISSUES entries 12 and 17).
set -u
trc="$1" sym="$2"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
out=$(python3 "$ROOT/trace-q/trace-q" trapdump "$trc" --sym "$sym") || {
    echo "checks/c1_triplefault: trace-q failed" >&2; exit 1; }
n=$(printf '%s\n' "$out" | grep -c "tl_after=")
if [ "$n" -ne 2 ]; then
    echo "checks/c1_triplefault: expected exactly 2 TRAP records, got $n:" >&2
    printf '%s\n' "$out" >&2
    exit 1
fi
printf '%s\n' "$out" | sed -n 1p | grep -q "cause=UNALIGNED.*tl_after=1" || {
    echo "checks/c1_triplefault: first TRAP not UNALIGNED/tl_after=1:" >&2
    printf '%s\n' "$out" >&2; exit 1; }
printf '%s\n' "$out" | sed -n 2p | grep -q "cause=ILLEGAL.*tl_after=2" || {
    echo "checks/c1_triplefault: second TRAP not ILLEGAL/tl_after=2:" >&2
    printf '%s\n' "$out" >&2; exit 1; }
exit 0
