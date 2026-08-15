#!/usr/bin/env python3
"""Decode the ROM's error screen out of a level-1 netboot trace.

The one fbcheck-style leg of the netboot gate (run-gui-tests): replay
pixel-window MEMW/DEVW records into a shadow buffer, snapshot at each
PRESENT, decode the final snapshot's 8x16 cells against the ROM's own
font (parsed straight from rom/netboot/font.s - one truth, two
consumers), and require --expect-sub TEXT in some decoded row. The
distinct HALT code stays the primary CI assertion; this proves the
human-facing message actually rendered.

Self-contained on purpose: the ROM must not track the Oasis font or
checker. Reference-platform constants (display window, pixel buffer,
initial mode) are test-side knowledge, exactly as in the Oasis suite.

usage: screencheck.py TRACE.trc --expect-sub TEXT
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, "trace-q"))
import tracefile as T  # noqa: E402

DISP = 0x0F000000              # display control window (PLATFORM-SPEC 1)
PB, PBSZ = 0x10000000, 0x01000000
W, H, STRIDE = 640, 480, 2560  # display.md 1 initial mode (never
                               # resized by the ROM)
WHITE = 0x00FFFFFF             # the console's one foreground color


def fail(msg):
    print(f"screencheck: FAIL: {msg}")
    sys.exit(1)


def load_font():
    glyphs, rows = {}, []
    code = 0x20
    for line in open(os.path.join(HERE, "..", "font.s")):
        line = line.strip()
        if line.startswith(".byte"):
            rows.append(int(line.split()[1], 16))
            if len(rows) == 16:
                glyphs[bytes(rows)] = chr(code)
                code += 1
                rows = []
    if code != 0x7F or rows:
        fail(f"font.s parse: got {code - 0x20} glyphs + {len(rows)} rows")
    return glyphs


def main():
    if len(sys.argv) != 4 or sys.argv[2] != "--expect-sub":
        sys.exit(__doc__)
    trace, want = sys.argv[1], sys.argv[3]

    sig = load_font()
    buf = bytearray(H * STRIDE)
    snap = None
    for r in T.read_records(trace):
        if r.name not in ("MEMW", "DEVW"):
            continue
        ea, size, val = r.fields["ea"], r.fields["size"], r.fields["val"]
        if ea == DISP and r.name == "DEVW":
            snap = bytes(buf)  # PRESENT
        elif PB <= ea and ea + size <= PB + PBSZ:
            off = ea - PB
            if off + size <= len(buf):
                buf[off:off + size] = val.to_bytes(size, "little")
    if snap is None:
        fail("no PRESENT in the trace - the error paint never ran")

    lines = []
    for row in range(H // 16):
        chars = []
        for col in range(W // 8):
            g = bytearray(16)
            base = row * 16 * STRIDE + col * 32
            for y in range(16):
                for x in range(8):
                    o = base + y * STRIDE + 4 * x
                    px = int.from_bytes(snap[o:o + 4], "little")
                    if px & 0x00FFFFFF == WHITE:
                        g[y] |= 0x80 >> x
            chars.append(sig.get(bytes(g), "?" if any(g) else " "))
        lines.append("".join(chars).rstrip())

    for ln in lines:
        if want in ln:
            print(f"screencheck: ok: {ln.strip()!r}")
            return
    shown = [ln for ln in lines if ln]
    fail(f"{want!r} not on screen; rendered rows: {shown!r}")


if __name__ == "__main__":
    main()
