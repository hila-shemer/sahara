#!/usr/bin/env bash
# Same image as c7_dev but run under --check-devorder 4 (see the
# MANIFEST line): the store-queue check mode must be semantics-neutral,
# so the identical trace-level assertions apply; logic in c7_dev.py.
set -u
exec python3 "$(dirname "$0")/c7_dev.py" "$1"
