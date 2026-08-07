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
trap 'rm -f "$regen"' EXIT
python3 ../encoding.py cheader "$regen" >/dev/null
diff -u ../sahara_isa.h "$regen"     # committed root header is fresh
diff -u gen/sahara_isa.h "$regen"    # the copy we compile against matches

bazel build //...
bazel test //...

python3 test/run_tests.py

# Shared conformance suite (consumed from the toolchain, never edited
# here). Each test runs twice, byte-identical traces required,
# --check-invtp always on; this is the stop-condition gate.
EMU="$PWD/bazel-bin/sahara-emu" ../tests/run-tests.sh
