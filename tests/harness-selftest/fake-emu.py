#!/usr/bin/env python3
"""Harness-selftest STUB. Not an emulator: executes nothing.

Speaks just enough of the frozen CLI contract (emu-common-prompt.md) to
let tests/selftest.sh validate run-tests.sh and difftest.sh plumbing:
parses the image header, writes a minimal deterministic trace (META +
one EXEC of the entry word), prints the HALT contract line, exits 0.

Replay input (--replay FILE) is actually read: its EVENT records are
echoed byte-for-byte into the output trace (cycle-merged), which is
what makes the events= plumbing and the recorded-trace replay check
testable without an emulator — and means the stub loudly rejects a
malformed feed (tracefile's reader validates it).

Knobs for exercising the harness's failure paths:
  FAKE_WB=<n>    put n in the EXEC record's wb field (difftest must
                 report the divergence)
  FAKE_RC=<n>    exit with code n after printing nothing (run-tests
                 must fail the test)
  FAKE_CASE=upper  print the HALT line in uppercase hex (harness must
                 reject it — SPEC-ISSUES entry 3)
  FAKE_R0=<hex>  print this r0 value regardless of everything (lets
                 selftest prove the harness enforces expect=)
  FAKE_DROP_EVENT=1  omit the last echoed EVENT record (checks/*.py
                 feed-equality must catch the missing event)

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


DISPLAY, KBD, MOUSE, NIC = 0x0F000000, 0x0F010000, 0x0F020000, 0x0F030000
PIX = 0x10000000
SENT = 0xFFFFFFFFFFFFFFFF


def emit_furniture(rec, name, entry, events):
    """Per-test record furniture mirroring what checks/<name>.py
    demands. Keyed on the image basename because different checks
    assert conflicting shapes. For event-fed keys the device-read
    values are derived from the feed's own EVENT records (device 1 =
    kbd, 2 = mouse — boot.md V1 indices) so the furniture cannot
    drift from the feed; cycles start at 1000000, after every feed
    event. Not an execution claim."""
    cyc = [1000000 if events else 10]

    def emit(rtype, payload_fn, *a):
        rec(cyc[0], rtype, payload_fn(cyc[0], *a))
        cyc[0] += 1

    def memr(ea, v):
        emit(T.T_MEMR, T.mem_payload, ea, 8, v)

    def word_of(payload):
        return struct.unpack_from("<Q", payload, 20)[0]

    def flags_of(payload):
        return payload[28]

    kbd_ev = [p for c, p in events
              if struct.unpack_from("<Q", p, 8)[0] == 1]
    mou_ev = [p for c, p in events
              if struct.unpack_from("<Q", p, 8)[0] == 2]

    if name == "c7_kbd":
        # checks/c7_kbd.py: pops = the four feed words then sentinel;
        # mouse pops = pre-event sentinel, both words, sentinel; one
        # EXTINT; STATUS reads within the possible depth sets.
        memr(KBD + 8, 0)
        memr(MOUSE + 8, 0)
        memr(MOUSE + 0, SENT)
        memr(KBD + 8, 4)
        memr(KBD + 8, 4)
        memr(KBD + 0, word_of(kbd_ev[0]))
        memr(KBD + 8, 3)
        for p in kbd_ev[1:]:
            memr(KBD + 0, word_of(p))
        memr(KBD + 8, 0)
        memr(KBD + 0, SENT)
        memr(MOUSE + 8, 2)
        emit(T.T_TRAP, T.trap_payload, E.CAUSES["EXTINT"], entry, 0, 1)
        for p in mou_ev:
            memr(MOUSE + 0, word_of(p))
        memr(MOUSE + 0, SENT)
        memr(MOUSE + 8, 0)
        memr(KBD + 8, 0)
    elif name == "c7_kbd_ovf":
        # checks/c7_kbd_ovf.py: STATUS 0, then 256 and 255..0; pops =
        # every non-dropped feed word in order, then sentinel; no traps.
        kept = [p for p in kbd_ev if not flags_of(p) & 1]
        memr(KBD + 8, 0)
        memr(KBD + 8, len(kept))
        for i, p in enumerate(kept):
            memr(KBD + 0, word_of(p))
            memr(KBD + 8, len(kept) - 1 - i)
        memr(KBD + 0, SENT)
    elif name == "c7_resize":
        # checks/c7_resize.py: geometry read triples per resize wave
        # (latest-wins for the same-cycle double), three acks with the
        # handler's ack BEFORE its geometry reads, one pixel DEVW, the
        # two mouse pops, one EXTINT.
        memr(DISPLAY + 0x28, 0)
        emit(T.T_DEVW, T.mem_payload, PIX, 4, 0x00FF0000)
        memr(DISPLAY + 0x28, 1)
        memr(DISPLAY + 0x08, 800)
        memr(DISPLAY + 0x10, 600)
        memr(DISPLAY + 0x18, 3200)
        memr(DISPLAY + 0x20, 1)
        emit(T.T_DEVW, T.mem_payload, DISPLAY + 0x30, 8, 1)
        memr(DISPLAY + 0x28, 0)
        memr(MOUSE + 8, 1)
        memr(DISPLAY + 0x28, 1)
        memr(DISPLAY + 0x08, 640)
        memr(DISPLAY + 0x10, 480)
        memr(DISPLAY + 0x18, 2560)
        emit(T.T_DEVW, T.mem_payload, DISPLAY + 0x30, 8, 1)
        memr(DISPLAY + 0x28, 0)
        memr(MOUSE + 0, word_of(mou_ev[0]))
        memr(MOUSE + 8, 0)
        memr(MOUSE + 8, 1)
        memr(MOUSE + 0, word_of(mou_ev[1]))
        emit(T.T_TRAP, T.trap_payload, E.CAUSES["EXTINT"], entry, 0, 1)
        emit(T.T_DEVW, T.mem_payload, DISPLAY + 0x30, 8, 1)
        memr(DISPLAY + 0x08, 800)
        memr(DISPLAY + 0x10, 600)
        memr(DISPLAY + 0x18, 3200)
        memr(DISPLAY + 0x28, 0)
        memr(DISPLAY + 0x20, 1)
    elif name.startswith("c7_dev"):
        # what checks/c7_dev.py demands: register-read MEMRs with the
        # pinned reference values, two PRESENT DEVWs with the D-13
        # pixel writes around the last one, and a 3-UNALIGNED +
        # 10-DEVERR trap census.
        for ea, v in [(DISPLAY + 8, 640), (DISPLAY + 16, 480),
                      (DISPLAY + 24, 2560), (DISPLAY + 32, 1),
                      (NIC + 32, 0x0000563412005452),
                      (KBD + 0, SENT)]:
            memr(ea, v)
        for _ in range(3):
            emit(T.T_TRAP, T.trap_payload, E.CAUSES["UNALIGNED"],
                 entry, KBD + 2, 1)
        for _ in range(10):
            emit(T.T_TRAP, T.trap_payload, E.CAUSES["DEVERR"],
                 entry, KBD, 1)
        emit(T.T_DEVW, T.mem_payload, DISPLAY, 8, 0)
        emit(T.T_DEVW, T.mem_payload, PIX, 4, 0x00FF0000)
        emit(T.T_DEVW, T.mem_payload, PIX + 4, 4, 0x0000FF00)
        emit(T.T_DEVW, T.mem_payload, DISPLAY, 8, 0)
        emit(T.T_DEVW, T.mem_payload, PIX + 8, 4, 0x000000FF)
    elif name == "c3_irq_dev":
        # what checks/c3_irq_dev.py demands: 32 paired MEMR/MEMW at
        # the atomic box, 8 TIMER deliveries (several inside the AMO
        # cycle span), 1 unpaired readback MEMR, nothing in device
        # space.
        cyc[0] = 100
        for k in range(32):
            rec(cyc[0], T.T_MEMR, T.mem_payload(cyc[0], 0x740, 8, k))
            rec(cyc[0], T.T_MEMW,
                T.mem_payload(cyc[0], 0x740, 8, k + 1))
            if k % 4 == 3:
                rec(cyc[0] + 1, T.T_TRAP, T.trap_payload(
                    cyc[0] + 1, E.CAUSES["TIMER"], entry, 0, 1))
            cyc[0] += 2
        rec(cyc[0], T.T_MEMR, T.mem_payload(cyc[0], 0x740, 8, 32))
    else:
        # default: the UNALIGNED->ILLEGAL->diagnostic shape that
        # checks/c1_triplefault.sh greps for (the tl=3 record is
        # trace.md 2.3.4's triple-fault diagnostic).
        rec(1, T.T_TRAP, T.trap_payload(
            1, E.CAUSES["UNALIGNED"], entry, 0x719, 1))
        rec(2, T.T_TRAP, T.trap_payload(
            2, E.CAUSES["ILLEGAL"], entry, 0, 2))
        rec(3, T.T_TRAP, T.trap_payload(
            3, E.CAUSES["ILLEGAL"], entry, 0, 3))


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit("fake-emu: no image")
    image_path = args[0]
    trace_path, level, replay_path = None, 0, None
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
            replay_path = args[i + 1]
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

    # Under --replay, read the input trace (loudly — a malformed feed
    # dies here) and collect its EVENT records for byte-exact echo.
    events = []
    if replay_path:
        try:
            for r in T.read_records(replay_path):
                if r.type == T.T_EVENT:
                    events.append((r.fields["cycle"], r.payload))
        except T.TraceError as e:
            sys.exit(f"fake-emu: bad replay input: {e}")

    if trace_path:
        wb = int(os.environ.get("FAKE_WB", "0"))
        # FAKE_REPLAY_WB: diverge only under --replay, so selftest can
        # prove the harness catches a replay that fails to reproduce.
        if replay_path and os.environ.get("FAKE_REPLAY_WB"):
            wb = int(os.environ["FAKE_REPLAY_WB"])

        # Records after META are collected as (cycle, type, payload)
        # and stably cycle-sorted before writing so the echoed EVENT
        # cycles (feed-chosen) and the furniture cycles interleave
        # without violating trace.md 3.1 monotonicity.
        post = []

        def rec(cycle, rtype, payload):
            post.append((cycle, rtype, payload))

        rec(0, T.T_EXEC, T.exec_payload(
            0, entry, word, wb, T.FLAG_WROTE_DST if wb else 0))
        echo = events
        if os.environ.get("FAKE_DROP_EVENT"):
            echo = events[:-1]
        for cyc_ev, payload in echo:
            rec(cyc_ev, T.T_EVENT, payload)

        # Trace furniture so checks/*.sh run their real record
        # logic against the stub instead of being skipped. Keyed
        # on the image basename because different checks assert
        # CONFLICTING record shapes (exactly-2 traps vs exactly-8
        # timers). Not an execution claim. Event-fed keys place
        # furniture at cycles >= 1000000, after every feed event.
        name = os.path.basename(image_path)
        name = name[:-4] if name.endswith(".img") else name
        emit_furniture(rec, name, entry, events)

        with open(trace_path, "wb") as f:
            T.write_record(f, T.T_META, T.meta_payload(T.meta_text(
                level,
                mode="replay" if replay_path else "live",
                image=image_path,
                image_sha256=hashlib.sha256(img).hexdigest(),
                encoding_version=E.SPEC_VERSION)))
            for _, rtype, payload in sorted(post, key=lambda t: t[0]):
                T.write_record(f, rtype, payload)

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
