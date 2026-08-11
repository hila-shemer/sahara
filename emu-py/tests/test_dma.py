"""DMA engine (devspec/dma.md): register matrix, the two error
classes, cost arithmetic, latch-vs-sample, memmove overlap, the
no-records rule, and the WFI wake gate. Device-level tests drive the
Dma object directly with a fake clock; machine-level tests go through
the boundary phase and the tracer."""

import pytest

import devices
import encoding as E
import mem
from helpers import (OrderedTracer, asm, cause_handler, ldi, li128,
                     make_machine, mtsr, nop, st, vbase_setup, wbytes,
                     HANDLER_PA)

DMA = devices.DMA_BASE
DESC = 0x10000
SRC = 0x20000
DST = 0x30000

CAPS = 0x18080301
ST = devices.Dma


def make_dma(ram=1 << 20):
    phys = mem.PhysMap(ram)
    d = devices.Dma(devices.DMA_BASE, devices.DMA_SIZE, phys)
    phys.add_device(d)
    d.clock = lambda: 1000
    return d, phys


def write_desc(phys, op, src, dst, length, next_=0, r56=0):
    words = [op, src, dst, length, next_, 0, 0, r56]
    phys.write_raw(DESC, b"".join(w.to_bytes(8, "little") for w in words))


def test_reset_and_read_matrix():
    d, phys = make_dma()
    assert d.load(0x00, 8) == CAPS
    assert d.load(0x08, 8) == ST.IDLE
    assert d.load(0x20, 8) == 0
    for off in (0x00, 0x08, 0x10, 0x18, 0x20):
        for size in (1, 2, 4):
            with pytest.raises(mem.AccessError):
                d.load(off, size)
        with pytest.raises(mem.AccessError):
            d.store(off, 4, 0)
    # wrong direction (E3/E4)
    for off in (0x10, 0x18):
        with pytest.raises(mem.AccessError):
            d.load(off, 8)
    for off in (0x00, 0x08, 0x20):
        with pytest.raises(mem.AccessError):
            d.store(off, 8, 0)
    # unlisted offsets: DEVERR in BOTH directions (root SPEC-ISSUES 40)
    for off in (0x28, 0xFFF8):
        with pytest.raises(mem.AccessError):
            d.load(off, 8)
        with pytest.raises(mem.AccessError):
            d.store(off, 8, 0)


def test_irq_ack_values():
    d, phys = make_dma()
    d.irq_pending = True
    for bad in (0, 2, (1 << 63) | 1):
        with pytest.raises(mem.AccessError):
            d.store(0x18, 8, bad)
        assert d.irq_pending          # E8 clears nothing
    d.store(0x18, 8, 1)
    assert not d.irq_pending
    d.store(0x18, 8, 1)               # no-op ack: race-free, no fault
    assert not d.irq_pending


def test_doorbell_access_errors():
    d, phys = make_dma()
    write_desc(phys, 1, SRC, DST, 64)
    # E6: PA not 64-aligned; E7: descriptor range leaves RAM
    for bad in (DESC + 8, (1 << 20), (1 << 64) - 64):
        with pytest.raises(mem.AccessError):
            d.store(0x10, 8, bad)
    assert d.load(0x08, 8) == ST.IDLE and d.load(0x20, 8) == 0
    # E5: doorbell while BUSY, in-flight job unharmed
    d.store(0x10, 8, DESC)
    assert d.load(0x08, 8) == ST.BUSY
    with pytest.raises(mem.AccessError):
        d.store(0x10, 8, DESC)
    assert d.load(0x08, 8) == ST.BUSY
    assert d.load(0x20, 8) == 1000 + 8 + 8


def test_content_errors_first_failure_wins():
    d, phys = make_dma()
    rows = [
        (dict(op=0), ST.BAD_OP),
        (dict(op=7), ST.BAD_OP),
        (dict(op=1 | (1 << 9)), ST.BAD_FORMAT),
        (dict(next_=1), ST.BAD_FORMAT),
        (dict(r56=1), ST.BAD_FORMAT),
        (dict(src=SRC + 1), ST.BAD_ALIGN),
        (dict(dst=DST + 4), ST.BAD_ALIGN),
        (dict(length=12), ST.BAD_ALIGN),
        # FILL: src is a pattern, no align rule — falls to LEN=0
        (dict(op=2, src=SRC + 1, length=0), ST.BAD_RANGE),
        (dict(length=0), ST.BAD_RANGE),
        (dict(length=ST.LEN_MAX + 8), ST.BAD_RANGE),
        (dict(dst=0x10000000), ST.BAD_RANGE),      # pixel buffer
        (dict(src=(1 << 20) - 0x1000, length=0x2000), ST.BAD_RANGE),
        # precedence
        (dict(op=(1 << 9), src=SRC + 1, length=0), ST.BAD_OP),
        (dict(op=1 | (1 << 9), src=SRC + 1, length=0), ST.BAD_FORMAT),
        (dict(src=SRC + 1, length=0), ST.BAD_ALIGN),
    ]
    for i, (kw, want) in enumerate(rows):
        base = dict(op=1, src=SRC, dst=DST, length=64)
        base.update(kw)
        write_desc(phys, base["op"], base["src"], base["dst"],
                   base["length"], base.get("next_", 0), base.get("r56", 0))
        d.clock = lambda c=1000 + i: c
        d.store(0x10, 8, DESC)          # retires: content never traps
        assert d.load(0x08, 8) == want, kw
        assert d.load(0x20, 8) == 1000 + i   # COMP_CYCLE = doorbell cycle
        assert not d.irq_pending             # bit 8 clear everywhere here
        assert phys.read_raw(DST, 8) == bytes(8)
    # error with IRQ_ON_COMPLETE: pending rises at the doorbell
    write_desc(phys, 1 << 8, SRC, DST, 64)   # opcode 0, bit 8
    d.store(0x10, 8, DESC)
    assert d.load(0x08, 8) == ST.BAD_OP and d.irq_pending


def test_copy_cost_latch_sample():
    d, phys = make_dma()
    src_data = bytes(range(256)) * 16                    # 4 KB
    phys.write_raw(SRC, src_data)
    write_desc(phys, 1, SRC, DST, 4096)
    d.store(0x10, 8, DESC)
    assert d.load(0x08, 8) == ST.BUSY
    assert d.load(0x20, 8) == 1520          # dma.md V3, during BUSY
    # latch: corrupting the descriptor mid-flight changes nothing
    write_desc(phys, 0, 0, 0, 0)
    # sample: source stores before C_done ARE copied
    phys.write_raw(SRC, b"\xEE" * 8)
    d.advance(1519)
    assert d.load(0x08, 8) == ST.BUSY
    assert phys.read_raw(DST, 8) == bytes(8)
    d.advance(1520)
    assert d.load(0x08, 8) == ST.DONE
    assert not d.irq_pending                # bit 8 was clear
    assert phys.read_raw(DST, 4096) == b"\xEE" * 8 + src_data[8:]
    assert phys.read_raw(DST + 4096, 8) == bytes(8)      # fence


def test_fill_and_rearm_from_done():
    d, phys = make_dma()
    pattern = 0x0123456789ABCDEF
    write_desc(phys, 2 | (1 << 8), pattern, DST, 32768)
    d.store(0x10, 8, DESC)
    assert d.load(0x20, 8) == 1000 + 8 + 4096
    assert d.wake_cycle() == 1000 + 8 + 4096
    d.advance(1000 + 8 + 4096)
    assert d.load(0x08, 8) == ST.DONE and d.irq_pending
    assert d.wake_cycle() is None
    assert phys.read_raw(DST, 32768) == \
        pattern.to_bytes(8, "little") * 4096
    d.store(0x18, 8, 1)
    # re-arm from DONE without any reset
    write_desc(phys, 1, DST, SRC, 8)
    d.store(0x10, 8, DESC)
    assert d.load(0x08, 8) == ST.BUSY


def test_overlap_is_memmove():
    d, phys = make_dma()
    words = b"".join((100 + i).to_bytes(8, "little") for i in range(64))
    phys.write_raw(SRC, words)
    write_desc(phys, 1, SRC, SRC + 8, 512)              # forward overlap
    d.store(0x10, 8, DESC)
    d.advance(2000)
    assert phys.read_raw(SRC, 8) == (100).to_bytes(8, "little")
    assert phys.read_raw(SRC + 8, 512) == words
    phys.write_raw(DST, words)
    write_desc(phys, 1, DST + 8, DST, 512)              # backward overlap
    d.store(0x10, 8, DESC)
    d.advance(4000)
    assert phys.read_raw(DST, 504) == words[8:]
    # the last source word sat past the written buffer: zeros moved in
    assert phys.read_raw(DST + 504, 8) == bytes(8)


def _dma_prog(op_bit8, length):
    """Doorbell a COPY descriptor (built as data), enable IE, WFI;
    the EXTINT handler records cause/baddr/epc and halts."""
    desc = b"".join(v.to_bytes(8, "little") for v in
                    (1 | (op_bit8 << 8), SRC, DST, length, 0, 0, 0, 0))
    prog = (vbase_setup()
            + li128(1, DESC)
            + li128(2, devices.DMA_BASE)
            + [st(1, 2, 0x10, w=64),            # doorbell
               ldi(3, 9),                        # status: S | IE
               mtsr("status", 3),
               asm("WFI"),
               nop(),
               asm("HALT")])
    return prog, [(DESC, desc), (HANDLER_PA, wbytes(cause_handler()))]


def test_wfi_wakes_at_exactly_c_done():
    prog, data = _dma_prog(op_bit8=1, length=4096)
    tr = OrderedTracer()
    m = make_machine(prog, data=data, tracer=tr, with_dma=True)
    outcome = m.run(100000)
    assert outcome == "halt"
    assert m.regs[10] == E.CAUSES["EXTINT"]
    devw = [r for r in tr.recs if r[0] == "devw"
            and r[2] == devices.DMA_BASE + 0x10]
    assert len(devw) == 1
    c_done = devw[0][1] + 8 + 4096 // 8
    traps = [r for r in tr.recs if r[0] == "trap"]
    assert len(traps) == 1
    assert traps[0][1] == c_done            # wake at EXACTLY C_done
    assert m.dma.status == ST.DONE and m.dma.irq_pending


def test_wfi_bit8_clear_job_is_not_a_wake_source():
    prog, data = _dma_prog(op_bit8=0, length=4096)
    m = make_machine(prog, data=data, with_dma=True)
    outcome = m.run(100000)
    # nothing can deliver: the stall deadlocks loudly (root
    # SPEC-ISSUES 42), the job never reaches its completion boundary
    assert outcome == "halt" and m.halted
    assert m.dma.status == ST.BUSY


def test_transfer_emits_no_records():
    prog, data = _dma_prog(op_bit8=1, length=4096)
    tr = OrderedTracer()
    m = make_machine(prog, data=data, tracer=tr, with_dma=True)
    m.run(100000)
    assert m.dma.status == ST.DONE
    for r in tr.recs:
        if r[0] in ("memw", "devw", "memr"):
            assert not (DST <= r[2] < DST + 4096), r
        if r[0] in ("memw", "memr"):
            assert not (devices.DMA_BASE <= r[2]
                        < devices.DMA_BASE + devices.DMA_SIZE), r
    assert m.phys.read_raw(DST, 8) == m.phys.read_raw(SRC, 8)
