"""C5-shaped smoke tests: base integer semantics, canonical form,
division rules, MULH at 128, mod field, SHORI chaining."""

import random

import encoding as E
from helpers import (MASK128, W, alui, alur, cmpi, halt, ldi, li128,
                     mod_shl, mod_sxt, mod_zxt, nop, run_words, shori)

MASK64 = (1 << 64) - 1


def canon(v, w):
    v &= (1 << w) - 1
    if w < 128 and v & (1 << (w - 1)):
        v |= MASK128 ^ ((1 << w) - 1)
    return v


def test_add_imm():
    m, out = run_words([ldi(1, 5), alui("ADD", 0, 1, 7), halt()])
    assert out == "halt"
    assert m.regs[0] == 12
    assert m.cycle == 3


def test_imm_sign_extension():
    m, _ = run_words([alui("ADD", 0, 31, -3 & 0x3FFFFF), halt()])
    assert m.regs[0] == MASK128 - 2          # -3 canonical


def test_narrow_canonical_form_signed_and_unsigned():
    # 0x7FFFFFFF + 1 at w=32 -> 0x80000000 sign-extended to 128
    prog = li128(1, 0x7FFFFFFF) + [alui("ADD", 0, 1, 1, w=32), halt()]
    m, _ = run_words(prog)
    assert m.regs[0] == canon(0x80000000, 32)
    # unsigned op also sign-extends: SHR.32 of high-garbage input
    prog = li128(1, (0xDEAD << 64) | 0xFFFFFFFF) + [
        alui("SHR", 0, 1, 0, w=32), halt()]
    m, _ = run_words(prog)
    assert m.regs[0] == canon(0xFFFFFFFF, 32)   # low32 all-ones, sext


def test_width128_native_no_extension():
    prog = li128(1, 1 << 100) + [alui("ADD", 0, 1, 0, w=128), halt()]
    m, _ = run_words(prog)
    assert m.regs[0] == 1 << 100


def test_div_by_zero():
    m, _ = run_words([ldi(1, 5), alui("SDIV", 0, 1, 0, w=64),
                      alui("UDIV", 2, 1, 0, w=32),
                      alui("UREM", 3, 1, 0, w=64),
                      alui("SREM", 4, 1, 0, w=64), halt()])
    assert m.regs[0] == MASK128              # all-ones canonicalized
    assert m.regs[2] == MASK128              # canon(0xFFFFFFFF, 32)
    assert m.regs[3] == 5                    # remainder = dividend
    assert m.regs[4] == 5


def test_signed_overflow_min_div_minus1():
    prog = li128(1, 0x80000000) + [
        alui("SDIV", 0, 1, -1 & 0x3FFFFF, w=32),
        alui("SREM", 2, 1, -1 & 0x3FFFFF, w=32), halt()]
    m, _ = run_words(prog)
    assert m.regs[0] == canon(0x80000000, 32)
    assert m.regs[2] == 0


def test_signed_division_truncates_toward_zero():
    m, _ = run_words([ldi(1, -7 & 0x3FFFFF), alui("ADD", 1, 31, -7 & 0x3FFFFF),
                      alui("SDIV", 0, 1, 2, w=64),
                      alui("SREM", 2, 1, 2, w=64), halt()])
    assert m.regs[0] == canon(-3 & MASK64, 64)
    assert m.regs[2] == canon(-1 & MASK64, 64)


def test_mulh_128():
    rng = random.Random(1)
    a = rng.getrandbits(128)
    b = rng.getrandbits(128)

    def s(v):
        return v - (1 << 128) if v >> 127 else v

    prog = li128(1, a) + li128(2, b) + [
        alur("MULH", 0, 1, 2, w=128),
        alur("MULHU", 3, 1, 2, w=128),
        alur("MUL", 4, 1, 2, w=128), halt()]
    m, _ = run_words(prog)
    assert m.regs[0] == ((s(a) * s(b)) >> 128) & MASK128
    assert m.regs[3] == (a * b) >> 128
    assert m.regs[4] == (a * b) & MASK128


def test_madd():
    m, _ = run_words([ldi(1, 6), ldi(2, 7), ldi(3, 100),
                      alur("MADD", 0, 1, 2, src3=3), halt()])
    assert m.regs[0] == 142


def test_mod_field():
    prog = li128(1, 0x1234) + [
        alur("ADD", 0, 31, 1, mod=mod_shl(8)),           # 0x1234 << 8
        alur("ADD", 2, 31, 1, mod=mod_zxt(8)),           # 0x34
        alur("ADD", 3, 31, 1, mod=mod_sxt(8)),           # sext8(0x34)=0x34
        halt()]
    m, _ = run_words(prog)
    assert m.regs[0] == 0x123400
    assert m.regs[2] == 0x34
    assert m.regs[3] == 0x34
    # sxt with a negative low byte
    prog = li128(1, 0x80) + [alur("ADD", 0, 31, 1, mod=mod_sxt(8)), halt()]
    m, _ = run_words(prog)
    assert m.regs[0] == canon(0x80, 8)


def test_mod_ignored_when_iform():
    # I=1: mod field ignored entirely
    m, _ = run_words([alui("ADD", 0, 31, 42), halt()])
    assert m.regs[0] == 42


def test_shift_count_mod_width():
    prog = li128(1, 1) + [alui("SHL", 0, 1, 33, w=32),   # 33 mod 32 = 1
                          alui("SHL", 2, 1, 33, w=64),   # 33 mod 64 = 33
                          halt()]
    m, _ = run_words(prog)
    assert m.regs[0] == 2
    assert m.regs[2] == 1 << 33


def test_sar():
    prog = li128(1, 0x80000000) + [alui("SAR", 0, 1, 4, w=32), halt()]
    m, _ = run_words(prog)
    assert m.regs[0] == canon(0xF8000000, 32)


def test_shori_chain_exact():
    v = 0xFEDCBA9876543210_0123456789ABCDEF
    m, _ = run_words(li128(0, v) + [halt()])
    assert m.regs[0] == v


def test_shori_field_use():
    m, _ = run_words([ldi(1, 1), shori(0, 1, 0x2A), halt()])
    assert m.regs[0] == (1 << 22) | 0x2A


def test_r31_zero_and_discard():
    m, _ = run_words([alui("ADD", 31, 31, 99), alui("ADD", 0, 31, 1),
                      halt()])
    assert m.regs[31] == 0
    assert m.regs[0] == 1


def test_compares():
    m, _ = run_words([ldi(1, -5 & 0x3FFFFF), alui("ADD", 1, 31, -5 & 0x3FFFFF),
                      ldi(2, 3),
                      cmpi("CMPLT", 1, 1, 3, w=64),     # -5 < 3 signed
                      cmpi("CMPLTU", 2, 1, 3, w=64),    # huge < 3 unsigned: no
                      cmpi("CMPEQ", 3, 2, 3),
                      cmpi("CMPLE", 4, 2, 3),
                      halt()])
    assert m.preds[1] == 1
    assert m.preds[2] == 0
    assert m.preds[3] == 1
    assert m.preds[4] == 1


def test_cmp_dst0_discarded():
    m, _ = run_words([cmpi("CMPEQ", 0, 31, 0), halt()])
    assert m.preds[0] == 1                    # p0 still hardwired 1


def test_nop_and_cycle_counting():
    m, _ = run_words([nop(), nop(), nop(), halt()])
    assert m.cycle == 4
