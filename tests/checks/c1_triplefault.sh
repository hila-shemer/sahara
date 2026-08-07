#!/usr/bin/env bash
# Trace-level assertions for c1_triplefault (args: trace sym img).
# The run halts by triple fault. The trace must show exactly three TRAP
# records: the UNALIGNED delivery (tl=1), the double-fault ILLEGAL
# delivery (tl=2), and the diagnostic triple-fault record of
# devspec/trace.md 2.3.4 — the cause/epc/baddr the third trap WOULD
# have delivered, tl_after=3, corresponding to no sreg writes, ending
# the trace (SPEC-ISSUES 12/17 as revised by 27).
set -u
trc="$1" sym="$2"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
out=$(python3 "$ROOT/trace-q/trace-q" trapdump "$trc" --sym "$sym") || {
    echo "checks/c1_triplefault: trace-q failed" >&2; exit 1; }
n=$(printf '%s\n' "$out" | grep -c "cause=")
if [ "$n" -ne 3 ]; then
    echo "checks/c1_triplefault: expected exactly 3 TRAP records, got $n:" >&2
    printf '%s\n' "$out" >&2
    exit 1
fi
printf '%s\n' "$out" | sed -n 1p | grep -q "cause=UNALIGNED.*tl=1" || {
    echo "checks/c1_triplefault: first TRAP not UNALIGNED/tl=1:" >&2
    printf '%s\n' "$out" >&2; exit 1; }
printf '%s\n' "$out" | sed -n 2p | grep -q "cause=ILLEGAL.*tl=2" || {
    echo "checks/c1_triplefault: second TRAP not ILLEGAL/tl=2:" >&2
    printf '%s\n' "$out" >&2; exit 1; }
printf '%s\n' "$out" | sed -n 3p | grep -q "cause=ILLEGAL.*tl=3" || {
    echo "checks/c1_triplefault: third TRAP not the ILLEGAL/tl=3" \
         "triple-fault diagnostic:" >&2
    printf '%s\n' "$out" >&2; exit 1; }
exit 0
