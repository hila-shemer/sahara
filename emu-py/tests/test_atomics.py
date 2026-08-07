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
