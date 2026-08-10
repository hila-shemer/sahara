#!/usr/bin/env bash
# Headless demo run: build, generate the smoke feed (types a couple of
# commands, ends with halt), replay it under $EMU. The kernel never
# knows whether a window exists; this is the only way M1 runs.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
EMU="${EMU:-$ROOT/emu-c/bazel-bin/sahara-emu}"

"$HERE/build.sh"
mkdir -p "$HERE/tests/feeds"
python3 "$HERE/tests/mkfeed.py" demo "$HERE/build/oasis.img" \
    "$HERE/tests/feeds/demo.trc"
exec "$EMU" "$HERE/build/oasis.img" --replay "$HERE/tests/feeds/demo.trc" \
    --maxcycles 20000000
