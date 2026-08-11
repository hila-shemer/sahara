#!/usr/bin/env python3
"""Framebuffer + trap-census checker over a level-1 Oasis trace.

Replays the trace's pixel-window DEVW records into a shadow buffer,
snapshots at each PRESENT (DEVW to display control +0x00), decodes the
final snapshot's glyph grid through the SAME font module the kernel
renders from (gen/genfont.py - one truth, two consumers), and asserts:

  --expect TEXT       some decoded row, right-stripped, equals TEXT
  --expect-sub TEXT   some decoded row contains TEXT
  --absent TEXT       no decoded row equals TEXT
  --syscalls N        exactly N TRAP cause-10 records
  --min-extint N      at least N TRAP cause-1 records
  --min-timer N       at least N TRAP cause-0 records
  --min-presents N    at least N PRESENT stores
  --golden FILE       final snapshot as PPM byte-equals FILE
  --write-golden FILE write the PPM instead of comparing
  --allow-cause N     tolerate TRAP cause N (M2 kill tests: exactly
                      the expected user-fault cause, nothing else)

Always-on gates: only causes {TIMER, EXTINT, SYSCALL} + the explicit
allow list ever trap, tl_after is always 1 (no double faults), and
the trace ends in a HALT.

Reference-platform constants (display base, pixbuf base/size, initial
mode) are test-side knowledge, like tests/defs.s uses - the KERNEL
derives them from the table; the checker may know the platform it runs
tests on. Geometry tracks resize EVENT records (trace.md 4.4).
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OASIS = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(OASIS))
sys.path.insert(0, os.path.join(ROOT, "trace-q"))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(OASIS, "gen"))
import tracefile as T          # noqa: E402
import encoding as E           # noqa: E402
import genfont as F            # noqa: E402

CW = 0x0F000000                # display control window (PLATFORM-SPEC 1)
PB = 0x10000000                # pixel buffer PA
PBSZ = 0x01000000              # pixel buffer window size
INIT_W, INIT_H, INIT_S = 640, 480, 2560   # display.md 1 initial mode

CELL_W, CELL_H = 8, 16

# glyph signature -> char (uniqueness self-tested in genfont)
SIG = {bytes(rows): ch for ch, rows in F.FONT_BYTES.items()}


def fail(msg):
    print(f"fbcheck: FAIL: {msg}")
    sys.exit(1)


def decode_grid(buf, w, h, stride):
    cols, rows = w // CELL_W, h // CELL_H
    lines = []
    for r in range(rows):
        line = []
        for c in range(cols):
            sig = bytearray(16)
            base = r * CELL_H * stride + c * CELL_W * 4
            for y in range(CELL_H):
                off = base + y * stride
                b = 0
                for x in range(CELL_W):
                    px = buf[off + 4 * x:off + 4 * x + 3]
                    if px != b"\x00\x00\x00":
                        b |= 0x80 >> x
                sig[y] = b
            line.append(SIG.get(bytes(sig), "?"))
        lines.append("".join(line).rstrip())
    return lines


def to_ppm(buf, w, h, stride):
    out = bytearray(f"P6\n{w} {h}\n255\n".encode())
    for y in range(h):
        row = buf[y * stride:y * stride + 4 * w]
        for x in range(w):
            b, g, r = row[4 * x], row[4 * x + 1], row[4 * x + 2]
            out += bytes((r, g, b))
    return bytes(out)


def main():
    args = sys.argv[1:]
    trace = None
    expects, subs, absents = [], [], []
    syscalls = None
    min_extint = min_timer = min_presents = 0
    golden = wgolden = None
    allow_causes = []
    it = iter(args)
    for a in it:
        if a == "--expect":
            expects.append(next(it))
        elif a == "--expect-sub":
            subs.append(next(it))
        elif a == "--absent":
            absents.append(next(it))
        elif a == "--syscalls":
            syscalls = int(next(it))
        elif a == "--min-extint":
            min_extint = int(next(it))
        elif a == "--min-timer":
            min_timer = int(next(it))
        elif a == "--min-presents":
            min_presents = int(next(it))
        elif a == "--golden":
            golden = next(it)
        elif a == "--write-golden":
            wgolden = next(it)
        elif a == "--allow-cause":
            allow_causes.append(int(next(it), 0))
        elif trace is None:
            trace = a
        else:
            fail(f"unknown arg {a}")
    if trace is None:
        fail("no trace given")

    recs = T.read_records(trace)
    buf = bytearray(PBSZ)
    w, h, s = INIT_W, INIT_H, INIT_S
    presents = 0
    snap = None                # (bytes, w, h, s) at last PRESENT
    causes = {}
    ok_causes = {E.CAUSES["TIMER"], E.CAUSES["EXTINT"],
                 E.CAUSES["SYSCALL"]} | set(allow_causes)
    halted = False
    last = None
    for r in recs:
        last = r
        if r.type == T.T_DEVW:
            ea, size, val = r.fields["ea"], r.fields["size"], r.fields["val"]
            if PB <= ea < PB + PBSZ:
                buf[ea - PB:ea - PB + size] = val.to_bytes(16, "little")[:size]
            elif ea == CW + 0x00:
                presents += 1
                snap = (bytes(buf[:h * s]), w, h, s)
        elif r.type == T.T_EVENT and r.fields["device"] == 0:
            p = r.fields["bytes"]
            w = int.from_bytes(p[0:8], "little")
            h = int.from_bytes(p[8:16], "little")
            s = int.from_bytes(p[16:24], "little")
        elif r.type == T.T_TRAP:
            c = r.fields["cause"]
            causes[c] = causes.get(c, 0) + 1
            if c not in ok_causes:
                fail(f"forbidden trap cause {c} at cycle {r.fields['cycle']}")
            if r.fields["tl_after"] != 1:
                fail(f"tl_after {r.fields['tl_after']} (double fault?) "
                     f"at cycle {r.fields['cycle']}")
    if last is None or last.type != T.T_EXEC:
        fail("trace does not end in an EXEC record")
    # the final instruction must be HALT (opcode 0xFE)
    if (last.fields["insn"] & 0xFF) != 0xFE:
        fail("trace does not end at a HALT instruction")

    if syscalls is not None:
        got = causes.get(E.CAUSES["SYSCALL"], 0)
        if got != syscalls:
            fail(f"SYSCALL count {got}, expected {syscalls}")
    if causes.get(E.CAUSES["EXTINT"], 0) < min_extint:
        fail(f"EXTINT count {causes.get(E.CAUSES['EXTINT'], 0)} "
             f"< required {min_extint}")
    if causes.get(E.CAUSES["TIMER"], 0) < min_timer:
        fail(f"TIMER count {causes.get(E.CAUSES['TIMER'], 0)} "
             f"< required {min_timer}")
    if presents < min_presents:
        fail(f"{presents} PRESENTs < required {min_presents}")

    if expects or subs or absents or golden or wgolden:
        if snap is None:
            fail("no PRESENT in trace but screen assertions requested")
        sb, sw, sh, ss = snap
        lines = decode_grid(sb, sw, sh, ss)
        for want in expects:
            if want not in lines:
                print("decoded screen (non-blank rows):")
                for i, ln in enumerate(lines):
                    if ln:
                        print(f"  {i:2}: {ln!r}")
                fail(f"no row equals {want!r}")
        for want in subs:
            if not any(want in ln for ln in lines):
                fail(f"no row contains {want!r}")
        for nope in absents:
            if nope in lines:
                fail(f"row {nope!r} present but must not be")
        if wgolden:
            with open(wgolden, "wb") as fh:
                fh.write(to_ppm(sb, sw, sh, ss))
        if golden:
            with open(golden, "rb") as fh:
                if fh.read() != to_ppm(sb, sw, sh, ss):
                    fail(f"final frame differs from golden {golden}")
    print("fbcheck: ok")


if __name__ == "__main__":
    main()
