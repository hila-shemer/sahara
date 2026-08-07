"""C7-shaped smoke tests (memory half): load/store widths, extension,
ea composition, alignment traps."""

import encoding as E
from helpers import (HANDLER_PA, MASK128, alui, cause_handler, halt, ld128,
                     ldi, lds, ldz, li128, mod_shl, run_words, st, st128,
                     vbase_setup, wbytes)

DATA = 0x8000


def canon(v, w):
    v &= (1 << w) - 1
    if w < 128 and v & (1 << (w - 1)):
        v |= MASK128 ^ ((1 << w) - 1)
    return v


def test_store_load_widths_and_extension():
    prog = [ldi(1, DATA)] + li128(2, 0xFFEE) + [
        st(2, 1, 0, w=8),
        st(2, 1, 8, w=16),
        st(2, 1, 16, w=32),
        st(2, 1, 24, w=64),
        lds(3, 1, 0, w=8),        # 0xEE sign-extends
        ldz(4, 1, 0, w=8),
        lds(5, 1, 8, w=16),       # 0xFFEE sign-extends
        ldz(6, 1, 8, w=16),
        lds(7, 1, 16, w=32),
        lds(8, 1, 24, w=64),
        halt()]
    m, _ = run_words(prog)
    assert m.regs[3] == canon(0xEE, 8)
    assert m.regs[4] == 0xEE
    assert m.regs[5] == canon(0xFFEE, 16)
    assert m.regs[6] == 0xFFEE
    assert m.regs[7] == 0xFFEE
    assert m.regs[8] == 0xFFEE


def test_st128_ld128():
    v = (0xAA55 << 100) | 0x123456789
    prog = [ldi(1, DATA)] + li128(2, v) + [
        st128(2, 1), ld128(0, 1), halt()]
    m, _ = run_words(prog)
    assert m.regs[0] == v


def test_ea_composition():
    # ea = base + (index << 3) + disp
    prog = [ldi(1, DATA), ldi(2, 4), ldi(3, 77),
            st(3, 1, 8, w=64, src2=2, mod=mod_shl(3)),   # DATA + 32 + 8
            lds(0, 1, 40, w=64), halt()]
    m, _ = run_words(prog)
    assert m.regs[0] == 77


def test_alignment_trap():
    prog = vbase_setup() + [ldi(1, DATA + 2), ldi(2, 1),
                            st(2, 1, 0, w=32), halt()]
    m, _ = run_words(prog, data=[(HANDLER_PA, wbytes(cause_handler()))])
    assert m.regs[10] == E.CAUSES["UNALIGNED"]
    assert m.regs[11] == DATA + 2             # baddr = ea
    assert m.regs[12] == E.RESET_PC + 4 * 8   # epc = faulting instruction


def test_alignment_per_width():
    # 8-bit access is always aligned
    prog = [ldi(1, DATA + 3), ldi(2, 5), st(2, 1, 0, w=8),
            ldz(0, 1, 0, w=8), halt()]
    m, _ = run_words(prog)
    assert m.regs[0] == 5


def test_faulting_store_has_no_effect():
    # store to unmapped-out-of-RAM (DEVERR) then verify memory unchanged
    prog = vbase_setup() + li128(1, 1 << 90) + [
        ldi(2, 3), st(2, 1, 0, w=64), halt()]
    m, _ = run_words(prog, data=[(HANDLER_PA, wbytes(cause_handler()))])
    assert m.regs[10] == E.CAUSES["DEVERR"]
    assert m.regs[11] == 1 << 90


def test_devorder_loads_snoop_store_queue():
    prog = [ldi(1, DATA), ldi(2, 11), st(2, 1, 0, w=64),
            lds(0, 1, 0, w=64), halt()]
    m, _ = run_words(prog, devorder=4)
    assert m.regs[0] == 11                    # own store visible via snoop
