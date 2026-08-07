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
  FAKE_R0=<hex>  print this r0 value regardless of everything (lets
                 selftest prove the harness enforces expect=)

The stub honors HARNESS_EXPECT_R0 (set by run-tests.sh/difftest.sh for
every test) so tests whose MANIFEST line carries expect= pass under the
stub. Real emulators never read it.
"""

import hashlib
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "trace-q"))
sys.path.insert(0, ROOT)
import tracefile as T  # noqa: E402
import encoding as E  # noqa: E402


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit("fake-emu: no image")
    image_path = args[0]
    trace_path, level, replaying = None, 0, False
    i = 1
    while i < len(args):
        a = args[i]
        if a == "--trace":
            trace_path = args[i + 1]
            i += 2
        elif a == "--trace-level":
            level = int(args[i + 1])
            i += 2
        elif a == "--replay":
            replaying = True
            i += 2
        elif a in ("--maxcycles", "--ram", "--check-devorder"):
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
        # FAKE_REPLAY_WB: diverge only under --replay, so selftest can
        # prove the harness catches a replay that fails to reproduce.
        if replaying and os.environ.get("FAKE_REPLAY_WB"):
            wb = int(os.environ["FAKE_REPLAY_WB"])
        with open(trace_path, "wb") as f:
            # Full 7-key v1 META (trace.md 2.3.7): the reconciled
            # tracefile reader rejects anything less, and the replay
            # diverge check exercises the run-variant `mode` exclusion.
            T.write_record(f, T.T_META, T.meta_payload(T.meta_text(
                level,
                mode="replay" if replaying else "live",
                image=image_path,
                image_sha256=hashlib.sha256(img).hexdigest(),
                encoding_version=E.SPEC_VERSION)))
            T.write_record(f, T.T_EXEC, T.exec_payload(
                0, entry, word, wb,
                T.FLAG_WROTE_DST if wb else 0))
            # Trace furniture so checks/*.sh run their real record
            # logic against the stub instead of being skipped. Keyed
            # on the image basename because different checks assert
            # CONFLICTING record shapes (exactly-2 traps vs exactly-8
            # timers). Not an execution claim.
            name = os.path.basename(image_path)
            name = name[:-4] if name.endswith(".img") else name
            if name == "c3_irq_dev":
                # what checks/c3_irq_dev.py demands: 32 paired
                # MEMR/MEMW at the atomic box, 8 TIMER deliveries
                # (several inside the AMO cycle span), 1 unpaired
                # readback MEMR, nothing in device space.
                cyc = 100
                for k in range(32):
                    T.write_record(f, T.T_MEMR,
                                   T.mem_payload(cyc, 0x740, 8, k))
                    T.write_record(f, T.T_MEMW,
                                   T.mem_payload(cyc, 0x740, 8, k + 1))
                    if k % 4 == 3:
                        T.write_record(f, T.T_TRAP, T.trap_payload(
                            cyc + 1, E.CAUSES["TIMER"], entry, 0, 1))
                    cyc += 2
                T.write_record(f, T.T_MEMR,
                               T.mem_payload(cyc, 0x740, 8, 32))
            else:
                # default: the UNALIGNED->ILLEGAL->diagnostic shape
                # that checks/c1_triplefault.sh greps for (the tl=3
                # record is trace.md 2.3.4's triple-fault diagnostic).
                T.write_record(f, T.T_TRAP, T.trap_payload(
                    1, E.CAUSES["UNALIGNED"], entry, 0x719, 1))
                T.write_record(f, T.T_TRAP, T.trap_payload(
                    2, E.CAUSES["ILLEGAL"], entry, 0, 2))
                T.write_record(f, T.T_TRAP, T.trap_payload(
                    3, E.CAUSES["ILLEGAL"], entry, 0, 3))

    expect = os.environ.get("HARNESS_EXPECT_R0", "")
    if expect == "checkfail" and not os.environ.get("FAKE_R0"):
        # Expected-CHECKFAIL manifest class (SPEC-ISSUES 22/23): the
        # correct outcome is exit 3 + a CHECKFAIL first word. FAKE_R0
        # overrides so selftest can prove the harness rejects a HALT
        # where a CHECKFAIL was required.
        print("CHECKFAIL stub assertion (harness-selftest, not real)")
        sys.exit(3)
    r0 = int(os.environ.get("FAKE_R0")
             or (expect if expect != "checkfail" else "")
             or "600d", 16)
    line = f"HALT r0={r0:032x}"
    if os.environ.get("FAKE_CASE") == "upper":
        line = f"HALT r0={r0:032X}"
    print(line)
    sys.exit(0)


if __name__ == "__main__":
    main()
