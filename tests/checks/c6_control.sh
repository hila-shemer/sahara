#!/usr/bin/env bash
# Trace-level assertions for c6_control (args: trace sym img).
# The squashed loads/stores/atomics in section C6.6 target SQUASH_BOX
# (0x710); ISA-SPEC 3.2 says a squashed instruction performs no memory
# access, so at trace level 2 (MEMR recorded too) NOTHING may touch it.
set -u
trc="$1"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
out=$(python3 "$ROOT/trace-q/trace-q" find --touched 0x710 "$trc") || {
    echo "checks/c6_control: trace-q failed" >&2; exit 1; }
if [ "$out" != "none" ]; then
    echo "checks/c6_control: squashed access reached memory: $out" >&2
    exit 1
fi
exit 0
