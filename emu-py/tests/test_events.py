"""EVENT records in the trace during replay — local SPEC-ISSUES 22.

The chosen reading: an EVENT with cycle C is applied (device queue fed,
EVENT record re-emitted stamped with C, not with the machine cycle at
application) at the first between-instruction point where machine cycle
>= C, before interrupt recognition at that point. TOOLING-SPEC 3.2 makes
EVENT a level-0 record: it appears at every trace level. These tests pin
each clause so the cross-impl trace diff has a frozen target when the
replay harness (toolchain task E) lands.
"""

import io
import struct

import encoding as E
import trc
from helpers import (OrderedTracer, QueueDevice, asm, halt, ldi, lds, mfsr,
                     mtsr, nop, run_words, vbase_setup, wbytes, HANDLER_PA)

S = 1 << E.STATUS_BITS["S"]
IE = 1 << E.STATUS_BITS["IE"]
DEVBASE = 0x100000


def test_event_record_stamped_with_event_cycle():
    """Event scheduled for cycle 3 mid-nop-stream: the EVENT record
    carries cycle 3 and sits between the cycle-2 and cycle-3 EXEC
    records (applied at the first boundary where cycle >= C)."""
    t = OrderedTracer()
    dev = QueueDevice(DEVBASE)
    prog = [nop()] * 5 + [halt()]
    m, out = run_words(prog, tracer=t, devices=[dev],
                       events=[(3, 0, b"x")])
    assert out == "halt"
    idx = t.kinds().index("event")
    assert t.recs[idx] == ("event", 3, 0, b"x")
    assert t.recs[idx - 1][:2] == ("exec", 2)
    assert t.recs[idx + 1][:2] == ("exec", 3)
    assert dev.queue == [b"x"]          # fed exactly once, never drained


def test_event_at_cycle_zero_precedes_first_exec():
    """An event whose cycle is not in the future is applied at the very
    first boundary — before any instruction executes."""
    t = OrderedTracer()
    dev = QueueDevice(DEVBASE)
    m, out = run_words([nop(), halt()], tracer=t, devices=[dev],
                       events=[(0, 0, b"z")])
    assert out == "halt"
    assert t.recs[0] == ("event", 0, 0, b"z")


def test_event_applied_before_interrupt_recognition():
    """SPEC-ISSUES 22's 'before interrupt recognition': the event that
    makes the device pending is recognized at the SAME boundary — the
    trace shows EVENT then TRAP(EXTINT) back to back, same cycle, with
    no EXEC between."""
    t = OrderedTracer()
    dev = QueueDevice(DEVBASE)
    handler = [mfsr(10, "cause0"),
               ldi(3, DEVBASE), lds(4, 3, 0, w=64),    # drain
               halt()]
    prog = (vbase_setup()
            + [ldi(1, S | IE), mtsr("status", 1)]
            + [nop()] * 8 + [halt()])
    # IE becomes visible at the boundary after mtsr retires (cycle 4).
    m, out = run_words(prog, data=[(HANDLER_PA, wbytes(handler))],
                       tracer=t, devices=[dev], events=[(6, 0, b"k")])
    assert out == "halt"
    assert m.regs[10] == E.CAUSES["EXTINT"]
    assert m.regs[4] == 1                # drain saw the one payload
    idx = t.kinds().index("event")
    assert t.recs[idx][:2] == ("event", 6)
    nxt = t.recs[idx + 1]
    assert nxt[0] == "trap"
    assert nxt[1] == 6                   # delivery begins that same cycle
    assert nxt[2] == E.CAUSES["EXTINT"]


def test_event_applied_during_wfi_stall():
    """WFI whose only wake source is a future replay event: virtual time
    jumps, the event is applied (record stamped with the event's own
    cycle), and with IE=0 execution falls through at T+1 (root
    SPEC-ISSUES 20 accounting)."""
    t = OrderedTracer()
    dev = QueueDevice(DEVBASE)
    prog = [asm("WFI"),
            ldi(3, DEVBASE), lds(4, 3, 0, w=64),       # drain
            halt()]
    m, out = run_words(prog, tracer=t, devices=[dev],
                       events=[(100, 0, b"w")])
    assert out == "halt"
    assert m.regs[4] == 1
    idx = t.kinds().index("event")
    assert t.recs[idx] == ("event", 100, 0, b"w")
    assert t.recs[idx + 1][:2] == ("exec", 101)        # T=100 -> resume T+1


def test_event_record_binary_format_and_level0():
    """TOOLING-SPEC 3.2: EVENT is type 5, payload cycle u64 + device u64
    + payload_len u32 + bytes — and it is a level-0 record, present even
    when MEMW/DEVW are suppressed."""
    buf = io.BytesIO()
    w = trc.TraceWriter(buf, level=0)
    w.event(7, 2, b"pay")
    w.memw(7, 0x1000, 8, 1)             # level-1 record: suppressed
    w.close()
    raw = buf.getvalue()
    typ, z1, z2, plen = struct.unpack("<BBHI", raw[:8])
    assert (typ, z1, z2) == (trc.T_EVENT, 0, 0)
    assert plen == 8 + 8 + 4 + 3
    assert raw[8:] == (b"\x07" + b"\x00" * 7 + b"\x02" + b"\x00" * 7
                       + b"\x03\x00\x00\x00" + b"pay")
    buf.seek(0)
    recs = list(trc.read_records(buf))
    assert [r[0] for r in recs] == [trc.T_EVENT]
    assert trc.parse_event(recs[0][1]) == (7, 2, b"pay")
