#!/usr/bin/env bash
# emu-c build gate (emu-common-prompt.md build order step 1):
# encoding self-check, spec crosscheck, generated-header drift gates,
# bazel build (short tests run at build time), bazel test, then the
# image-level test suite (smoke, determinism double-run, decoder fuzz).
set -euo pipefail
cd "$(dirname "$0")"

python3 ../encoding.py check
(cd .. && python3 crosscheck.py ISA-SPEC.md)

regen="gen/.sahara_isa.h.regen"
svregen="gen/.spec_version.h.regen"
trap 'rm -f "$regen" "$svregen"' EXIT
python3 ../encoding.py cheader "$regen" >/dev/null
diff -u ../sahara_isa.h "$regen"     # committed root header is fresh
diff -u gen/sahara_isa.h "$regen"    # the copy we compile against matches
python3 - <<'EOF' > "$svregen"
import sys
sys.path.insert(0, "..")
import encoding
print("/* Generated from encoding.py SPEC_VERSION -- do not edit.")
print(" * Regenerated and drift-checked by build.sh; consumed by the trace")
print(" * META record's encoding= key (devspec/trace.md 2.3.7). */")
print(f'#define SE_ENCODING_SPEC_VERSION "{encoding.SPEC_VERSION}"')
EOF
diff -u gen/spec_version.h "$svregen" # META encoding= tracks encoding.py

bazel build //...
bazel test //...

python3 test/run_tests.py

# Shared conformance suite (consumed from the toolchain, never edited
# here). Each test runs twice, byte-identical traces required,
# --check-invtp always on; this is the stop-condition gate. REPLAY=1:
# bit-exact replay of every test's trace is a reference-implementation
# check (CONFORMANCE.md), and this is the reference implementation.
REPLAY=1 EMU="$PWD/bazel-bin/sahara-emu" ../tests/run-tests.sh
