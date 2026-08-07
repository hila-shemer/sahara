#!/usr/bin/env bash
# Trace-level assertions for c6_control (args: trace sym img).
# The squashed loads/stores/atomics in section C6.6 target SQUASH_BOX
# (0x710); ISA-SPEC 3.2 says a squashed instruction performs no memory
# access, so at trace level 2 (MEMR recorded too) NOTHING may touch it.
set -u
trc="$1"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# trace-q exit codes (devspec/trace.md 6.2): 1 = zero matching facts
# (what we want here), 0 = a record touched the box, 2 = harness error.
out=$(python3 "$ROOT/trace-q/trace-q" find --touched 0x710 "$trc")
rc=$?
case $rc in
    1) exit 0;;
    0) echo "checks/c6_control: squashed access reached memory: $out" >&2
       exit 1;;
    *) echo "checks/c6_control: trace-q failed (rc=$rc)" >&2; exit 1;;
esac
