#!/usr/bin/env bash
# Trace-level assertions for dma_irq_wfi (args: trace sym img) — the
# hand-derived wake pin: first EXTINT at exactly doorbell + 8 + LEN/8;
# logic in dma_irq_wfi.py.
set -u
exec python3 "$(dirname "$0")/dma_irq_wfi.py" "$1"
