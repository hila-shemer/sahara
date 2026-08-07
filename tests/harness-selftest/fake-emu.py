#!/usr/bin/env python3
"""Harness-selftest STUB. Not an emulator: executes nothing.

Speaks just enough of the frozen CLI contract (emu-common-prompt.md) to
let tests/selftest.sh validate run-tests.sh and difftest.sh plumbing:
parses the image header, writes a minimal deterministic trace (META +
one EXEC of the entry word), prints the HALT contract line, exits 0.

Knobs for exercising the harness's failure paths:
  FAKE_WB=<n>    put n in the EXEC record's wb field (difftest must
                 report the divergence)
  FAKE_RC=<n>    exit with code n after printing nothing (run-tests
                 must fail the test)
  FAKE_CASE=upper  print the HALT line in uppercase hex (harness must
                 reject it — SPEC-ISSUES entry 3)
"""

import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "trace-q"))
import tracefile as T  # noqa: E402


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit("fake-emu: no image")
    image_path = args[0]
    trace_path, level = None, 0
    i = 1
    while i < len(args):
        a = args[i]
        if a == "--trace":
            trace_path = args[i + 1]
            i += 2
        elif a == "--trace-level":
            level = int(args[i + 1])
            i += 2
        elif a in ("--maxcycles", "--ram", "--check-devorder", "--replay"):
            i += 2
        elif a == "--check-invtp":
            i += 1
        else:
            sys.exit(f"fake-emu: unknown arg {a}")

    if os.environ.get("FAKE_RC"):
        sys.exit(int(os.environ["FAKE_RC"]))

    with open(image_path, "rb") as f:
        img = f.read()
    if img[:8] != b"SAHIMG01":
        sys.exit("fake-emu: bad image magic")
    entry_lo, entry_hi = struct.unpack_from("<QQ", img, 8)
    entry = entry_lo | (entry_hi << 64)
    nsegs, = struct.unpack_from("<Q", img, 24)
    word = 0
    off = 32
    for _ in range(nsegs):
        lo, hi, foff, flen, _mlen, _flags = struct.unpack_from(
            "<QQQQQQ", img, off)
        base = lo | (hi << 64)
        if base <= entry < base + flen - 7:
            word, = struct.unpack_from("<Q", img, foff + (entry - base))
        off += 48

    if trace_path:
        wb = int(os.environ.get("FAKE_WB", "0"))
        with open(trace_path, "wb") as f:
            T.write_record(f, T.T_META, T.meta_payload(
                f"image={image_path}\nlevel={level}\nstub=1\n"))
            T.write_record(f, T.T_EXEC, T.exec_payload(
                0, entry, word, wb,
                T.FLAG_WROTE_DST if wb else 0))

    r0 = 0x600D
    line = f"HALT r0={r0:032x}"
    if os.environ.get("FAKE_CASE") == "upper":
        line = f"HALT r0={r0:032X}"
    print(line)
    sys.exit(0)


if __name__ == "__main__":
    main()
