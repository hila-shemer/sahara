#!/usr/bin/env python3
"""Device-state snapshot-diff — the assertion primitive of
toolchain-prompt deliverable 3, trace-side.

Device windows behave as memory only through their DEVW records
(guest-visible state = last write wins per byte; emulator-internal
writes like NIC RX exposure produce no records, trace.md 2.3).
Reconstructing the byte state at two points of a trace and diffing
gives checks a precise "exactly these device bytes changed, nothing
else" assertion — used for D-13-style before/after-PRESENT reasoning.

Import from checks/*.py; not a standalone tool.
"""


def device_state(recs, lo, hi, upto_index=None):
    """Byte state {addr: value} of [lo, hi) built from DEVW records
    with record index < upto_index (None = whole trace). Bytes never
    written are absent (device buffers read 0 before first store —
    display.md D-08 — so absent == 0 for asserts that care)."""
    import tracefile as T
    state = {}
    n = len(recs) if upto_index is None else upto_index
    for r in recs[:n]:
        if r.type != T.T_DEVW:
            continue
        ea, size, val = r.fields["ea"], r.fields["size"], r.fields["val"]
        for k in range(size):
            a = ea + k
            if lo <= a < hi:
                state[a] = (val >> (8 * k)) & 0xFF
    return state


def state_diff(before, after):
    """{addr: (before_byte_or_None, after_byte_or_None)} for every
    address whose byte differs between the two states."""
    out = {}
    for a in set(before) | set(after):
        b, c = before.get(a), after.get(a)
        if b != c:
            out[a] = (b, c)
    return out
