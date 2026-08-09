"""C3-shaped smoke tests: CAS/AMO semantics, canonicalization, widths,
device/alignment faults."""

import encoding as E
from helpers import (HANDLER_PA, MASK128, W, asm, cause_handler, halt, ldi,
                     li128, run_words, st, vbase_setup, wbytes)

DATA = 0x8000


def canon(v, w):
    v &= (1 << w) - 1
    if w < 128 and v & (1 << (w - 1)):
        v |= MASK128 ^ ((1 << w) - 1)
    return v


def amo(name, dst, addr_reg, src2, w=64, imm=0, src3=0):
    return asm(name, dst=dst, src1=addr_reg, src2=src2, src3=src3,
               width=W[w], imm=imm)


def test_amoadd():
    prog = [ldi(1, DATA), ldi(2, 10), st(2, 1, 0, w=64),
            ldi(3, 5), amo("AMOADD", 0, 1, 3, w=64), halt()]
    m, _ = run_words(prog)
    assert m.regs[0] == 10                    # old value returned
    assert m.phys.read_raw(DATA, 8) == (15).to_bytes(8, "little")


def test_cas_success_and_failure():
    prog = [ldi(1, DATA), ldi(2, 7), st(2, 1, 0, w=32),
            ldi(3, 7), ldi(4, 99),
            amo("CAS", 0, 1, 3, w=32, src3=4),           # succeeds
            ldi(3, 1234),
            amo("CAS", 5, 1, 3, w=32, src3=2),           # fails (99 != 1234)
            halt()]
    m, _ = run_words(prog)
    assert m.regs[0] == 7
    assert m.regs[5] == 99
    assert m.phys.read_raw(DATA, 4) == (99).to_bytes(4, "little")


def test_cas_high_garbage_ignored_at_w32():
    # expected/new have garbage above bit 31; comparison is at w=32
    prog = ([ldi(1, DATA), ldi(2, 7), st(2, 1, 0, w=32)]
            + li128(3, (0xDEAD << 64) | 7)               # low32 == 7
            + li128(4, (0xBEEF << 64) | 55)
            + [amo("CAS", 0, 1, 3, w=32, src3=4), halt()])
    m, _ = run_words(prog)
    assert m.regs[0] == 7
    assert m.phys.read_raw(DATA, 4) == (55).to_bytes(4, "little")


def test_old_value_canonicalized():
    prog = ([ldi(1, DATA)] + li128(2, 0x80000001)
            + [st(2, 1, 0, w=32), ldi(3, 0),
               amo("AMOADD", 0, 1, 3, w=32), halt()])
    m, _ = run_words(prog)
    assert m.regs[0] == canon(0x80000001, 32)


def test_amo_min_max_signed_vs_unsigned():
    neg1 = MASK128                            # -1
    prog = ([ldi(1, DATA)] + li128(2, neg1)
            + [st(2, 1, 0, w=64), ldi(3, 5),
               amo("AMOMIN", 4, 1, 3, w=64),   # signed: min(-1,5) = -1
               st(2, 1, 8, w=64),
               amo("AMOMINU", 5, 1, 3, w=64, imm=8),  # unsigned: 5
               halt()])
    m, _ = run_words(prog)
    assert m.phys.read_raw(DATA, 8) == (MASK128 & ((1 << 64) - 1)) \
        .to_bytes(8, "little")                # still -1
    assert m.phys.read_raw(DATA + 8, 8) == (5).to_bytes(8, "little")


def test_amoswap_128():
    v = (0x1234 << 100) | 0x5678
    prog = ([ldi(1, DATA)] + li128(2, v)
            + [st(2, 1, 0, w=64)]             # seed low half only
            + li128(3, 1 << 127)
            + [asm("AMOSWAP", dst=0, src1=1, src2=3, width=W[128]),
               halt()])
    m, _ = run_words(prog)
    assert m.regs[0] == canon(v & ((1 << 64) - 1), 128)
    assert m.phys.read_raw(DATA, 16) == (1 << 127).to_bytes(16, "little")


def test_atomic_width3_reserved():
    prog = vbase_setup() + [ldi(1, DATA),
                            asm("AMOADD", dst=0, src1=1, src2=2, width=3),
                            halt()]
    m, _ = run_words(prog, data=[(HANDLER_PA, wbytes(cause_handler()))])
    assert m.regs[10] == E.CAUSES["ILLEGAL"]


def test_atomic_alignment():
    prog = vbase_setup() + [ldi(1, DATA + 4),
                            amo("AMOADD", 0, 1, 2, w=64), halt()]
    m, _ = run_words(prog, data=[(HANDLER_PA, wbytes(cause_handler()))])
    assert m.regs[10] == E.CAUSES["UNALIGNED"]
    assert m.regs[11] == DATA + 4


def test_atomic_out_of_map_deverr():
    prog = (vbase_setup() + li128(1, 1 << 90)
            + [amo("AMOADD", 0, 1, 2, w=64), halt()])
    m, _ = run_words(prog, data=[(HANDLER_PA, wbytes(cause_handler()))])
    assert m.regs[10] == E.CAUSES["DEVERR"]


def test_atomic_to_device_window_deverr_no_side_effect():
    """An atomic aimed at a MAPPED device window traps DEVERR before
    touching the device: the read-modify-write must not decompose into
    a device load + store (QueueDevice's load drains its queue, so a
    decomposed implementation would leave it empty). baddr = the ea."""
    from helpers import QueueDevice
    devbase = 0x100000
    dev = QueueDevice(devbase)
    prog = (vbase_setup() + [ldi(1, devbase),
                             amo("AMOADD", 0, 1, 2, w=64), halt()])
    m, _ = run_words(prog, data=[(HANDLER_PA, wbytes(cause_handler()))],
                     devices=[dev], events=[(0, 0, b"q")])
    assert m.regs[10] == E.CAUSES["DEVERR"]
    assert m.regs[11] == devbase
    assert dev.queue == [b"q"]           # never drained
    assert dev.stores == []              # never written


def test_atomic_to_platform_device_space_deverr_before_access():
    """c3_irq_dev phase 2's shape: no device instance exists, but the
    platform's fixed windows (PLATFORM-SPEC 1, PA >= 0x0F00_0000)
    classify as device space by address alone, so an AMO there traps
    DEVERR — dst untouched, epc = the AMO, and no MEMR/MEMW/DEVW
    footprint in the trace (SPEC-ISSUES 24 + root SPEC-ISSUES 17)."""
    import image
    from helpers import OrderedTracer
    ea = image.DEV_SPACE_BASE + 0x10000        # keyboard window
    tr = OrderedTracer()
    prog = (vbase_setup() + li128(1, ea)
            + [ldi(0, 0x5AFE), amo("AMOADD", 0, 1, 2, w=64), halt()])
    m, _ = run_words(prog, data=[(HANDLER_PA, wbytes(cause_handler()))],
                     ram=1 << 28, dev_base=image.DEV_SPACE_BASE, tracer=tr)
    assert m.regs[10] == E.CAUSES["DEVERR"]
    assert m.regs[11] == ea
    assert m.regs[12] == E.RESET_PC + 9 * 8    # the AMO's own pc
    assert m.regs[0] == 0x5AFE                 # dst survives the trap
    assert not [r for r in tr.recs if r[0] in ("memr", "memw", "devw")
                and r[2] >= image.DEV_SPACE_BASE]


def test_all_amos():
    ops = {
        "AMOAND": 0b1100 & 0b1010,
        "AMOOR": 0b1100 | 0b1010,
        "AMOXOR": 0b1100 ^ 0b1010,
        "AMOSWAP": 0b1010,
        "AMOMAX": 0b1100,
        "AMOMAXU": 0b1100,
    }
    for name, expected in ops.items():
        prog = [ldi(1, DATA), ldi(2, 0b1100), st(2, 1, 0, w=64),
                ldi(3, 0b1010), amo(name, 0, 1, 3, w=64), halt()]
        m, _ = run_words(prog)
        assert m.regs[0] == 0b1100, name
        assert m.phys.read_raw(DATA, 8) == expected.to_bytes(8, "little"), \
            name


# --------------------------------------- permission faults: R before W
# ISA-SPEC 7.1: an atomic requires both R and W and reports the first
# failing check in the order R then W. CONFORMANCE C3: "AMO permission
# faults report load-before-store order."

from helpers import mtsr, pred, pt_leaf, pt_node, pt_table, OrderedTracer

ROOT_PA = 0x100000
CHILD_PA = 0x110000
VPN_MASK = (1 << E.VPN_BITS) - 1


def _amo_tree(**leaf1_perms):
    return [
        (ROOT_PA, pt_node(8, 0, 0, {0: pt_table(CHILD_PA)})),
        (CHILD_PA, pt_node(0, 0, VPN_MASK & ~0xFF,
                           {0: pt_leaf(0, r=1, w=1, x=1, u=1),
                            1: pt_leaf(0x30000, **leaf1_perms)})),
        (HANDLER_PA, wbytes(cause_handler())),
    ]


def _amo_mmu_prog():
    import encoding
    S = 1 << encoding.STATUS_BITS["S"]
    MMU = 1 << encoding.STATUS_BITS["MMU_EN"]
    return (vbase_setup()
            + [ldi(19, ROOT_PA), mtsr("ptbase", 19),
               ldi(19, S | MMU), mtsr("status", 19),
               ldi(1, 0x10000), amo("AMOADD", 0, 1, 2, w=64), halt()])


def test_amo_write_only_page_faults_perm_load():
    # R check runs first: a W-only page reports PERM_LOAD, not PERM_STORE
    m, _ = run_words(_amo_mmu_prog(), data=_amo_tree(r=0, w=1))
    assert m.regs[10] == E.CAUSES["PERM_LOAD"]
    assert m.regs[11] == 0x10000


def test_amo_read_only_page_faults_perm_store():
    m, _ = run_words(_amo_mmu_prog(), data=_amo_tree(r=1, w=0))
    assert m.regs[10] == E.CAUSES["PERM_STORE"]
    assert m.regs[11] == 0x10000


def test_amo_unmapped_faults_pf_load():
    # both translations fail: PF_LOAD wins (R before W)
    import encoding
    S = 1 << encoding.STATUS_BITS["S"]
    MMU = 1 << encoding.STATUS_BITS["MMU_EN"]
    prog = (vbase_setup()
            + [ldi(19, ROOT_PA), mtsr("ptbase", 19),
               ldi(19, S | MMU), mtsr("status", 19),
               ldi(1, 0x20000), amo("AMOADD", 0, 1, 2, w=64), halt()])
    m, _ = run_words(prog, data=_amo_tree(r=1, w=1))
    assert m.regs[10] == E.CAUSES["PF_LOAD"]
    assert m.regs[11] == 0x20000


# ------------------------------------------- atomicity under interrupts
# CONFORMANCE C3: timer armed to fire "during" an AMO -- delivery must be
# before or after, never between read and write (verified via trace).

def test_amo_read_write_pair_unsplit_by_timer():
    import encoding
    S = 1 << encoding.STATUS_BITS["S"]
    IE = 1 << encoding.STATUS_BITS["IE"]
    prefix = (vbase_setup()
              + [ldi(1, DATA), ldi(2, 10), st(2, 1, 0, w=64),
                 ldi(3, 5)])
    amo_cycle = len(prefix) + 4          # after the 4 timecmp/IE insns
    prog = (prefix
            + [ldi(4, amo_cycle + 1), mtsr("timecmp", 4),
               ldi(5, S | IE), mtsr("status", 5),
               amo("AMOADD", 0, 1, 3, w=64),
               halt()])
    t = OrderedTracer()
    m, out = run_words(prog, data=[(HANDLER_PA, wbytes(cause_handler()))],
                       tracer=t)
    assert out == "halt"
    kinds = t.kinds()
    ri = next(i for i, r in enumerate(t.recs)
              if r[0] == "memr" and r[2] == DATA)
    wi = next(i for i, r in enumerate(t.recs)
              if r[0] == "memw" and r[2] == DATA and i > ri)
    assert wi == ri + 1                  # nothing between read and write
    assert t.recs[ri][1] == t.recs[wi][1] == amo_cycle
    trap = next(r for r in t.recs if r[0] == "trap")
    assert trap[1] == amo_cycle + 1      # delivered after, never between
    assert trap[2] == E.CAUSES["TIMER"]
    assert "trap" not in kinds[ri:wi + 1]
    assert m.regs[10] == E.CAUSES["TIMER"]
    assert m.phys.read_raw(DATA, 8) == (15).to_bytes(8, "little")


def test_cas_failure_traces_read_no_write():
    prog = [ldi(1, DATA), ldi(2, 7), st(2, 1, 0, w=32),
            ldi(3, 8),                       # expected != 7: CAS fails
            amo("CAS", 0, 1, 3, w=32, src3=2), halt()]
    t = OrderedTracer()
    m, _ = run_words(prog, tracer=t)
    reads = [r for r in t.recs if r[0] == "memr"]
    writes = [r for r in t.recs if r[0] == "memw"]
    assert len(reads) == 1 and reads[0][2] == DATA
    assert len(writes) == 1              # only the seeding ST, not the CAS
    assert writes[0][1] == 2             # the ST's cycle
    assert m.phys.read_raw(DATA, 4) == (7).to_bytes(4, "little")


def test_squashed_cas_and_store_no_memory_access():
    # CONFORMANCE C6: "CAS squash -- no memory access on squash,
    # verified by trace." p1 is 0 at reset -> pred(1) is false.
    import trc
    npred = pred(1)
    prog = [ldi(1, DATA), ldi(2, 7),
            st(2, 1, 0, w=64, p=npred),          # squashed store
            amo("CAS", 0, 1, 2, w=64, src3=2) | (npred << 8),  # squashed
            halt()]
    t = OrderedTracer()
    m, out = run_words(prog, tracer=t)
    assert out == "halt"
    assert not any(k in ("memr", "memw") for k in t.kinds())
    squashed = [r for r in t.recs
                if r[0] == "exec" and r[5] & trc.F_SQUASHED]
    assert len(squashed) == 2
    assert m.regs[0] == 0                # squashed CAS wrote no dst
