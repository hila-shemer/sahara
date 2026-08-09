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


# ----------------- weak-store queue (--check-devorder N), ISA-SPEC 9.2.
# C7 prep: pin the model root SPEC-ISSUES / emu-py SPEC-ISSUES 20 chose.
DEVBASE = 0x100000


def _steps(m, n):
    for _ in range(n):
        m.step()


def test_devorder_store_sits_in_queue_until_depth():
    """Ordinary stores are delayed in a depth-N queue; only overflow
    spills the oldest to RAM (stores may drain in any order, and the
    check mode models maximal delay)."""
    from helpers import make_machine
    prog = [ldi(1, DATA), ldi(2, 0xA1), st(2, 1, 0, w=64),
            ldi(2, 0xB2), st(2, 1, 8, w=64),
            ldi(2, 0xC3), st(2, 1, 16, w=64),
            halt()]
    m = make_machine(prog, devorder=2)
    _steps(m, 7)                               # everything but HALT
    assert len(m.phys.queue) == 2              # B2, C3 still queued
    assert int.from_bytes(m.phys.read_raw(DATA, 8), "little") == 0xA1
    assert int.from_bytes(m.phys.read_raw(DATA + 8, 8), "little") == 0
    m.step()                                   # HALT drains
    assert not m.phys.queue
    assert int.from_bytes(m.phys.read_raw(DATA + 8, 8), "little") == 0xB2
    assert int.from_bytes(m.phys.read_raw(DATA + 16, 8), "little") == 0xC3


def test_devorder_device_store_is_release_drain():
    """ISA-SPEC 9.2(1): a device store drains all earlier ordinary
    stores BEFORE the device sees the value. Sampled at store time via
    the device callback, not post-halt (HALT also drains)."""
    from helpers import QueueDevice, make_machine
    dev = QueueDevice(
        DEVBASE, on_store=lambda: int.from_bytes(m.phys.read_raw(DATA, 8),
                                                 "little"))
    prog = [ldi(1, DATA), ldi(2, 0xD4), st(2, 1, 0, w=64),
            ldi(3, DEVBASE), ldi(4, 1), st(4, 3, 0, w=64),
            halt()]
    m = make_machine(prog, devorder=8, devices=[dev])
    m.run(100)
    assert dev.stores, "device store never landed"
    off, size, val, ram_at_store = dev.stores[0]
    assert (off, val) == (0, 1)
    assert ram_at_store == 0xD4                # drained before device saw it


def test_devorder_ifence_drains():
    from helpers import asm, make_machine
    prog = [ldi(1, DATA), ldi(2, 0xE5), st(2, 1, 0, w=64),
            asm("IFENCE"), halt()]
    m = make_machine(prog, devorder=8)
    _steps(m, 3)
    assert len(m.phys.queue) == 1
    m.step()                                   # IFENCE
    assert not m.phys.queue
    assert int.from_bytes(m.phys.read_raw(DATA, 8), "little") == 0xE5


# --------------------- platform device space (PLATFORM-SPEC 1)
# "Everything at 0x0F00_0000 and above in this map is device space in
# the sense of ISA-SPEC section 9.2" — a property of the address, held
# before any device instance exists (checks/c3_irq_dev.py pins the same
# base). SPEC-ISSUES 24: the carve-out beats RAM region 0's extent, and
# the gaps between the fixed windows are device space too, not
# swiss-cheese RAM. Unmapped device space traps DEVERR (entry 8's rule).

import image  # noqa: E402  (emu-py dir is on sys.path via helpers)

DSB = image.DEV_SPACE_BASE


def _dev_space_run(prog, **kw):
    kw.setdefault("ram", 1 << 28)       # 256 MB: extent covers DSB
    kw.setdefault("dev_base", DSB)
    return run_words(vbase_setup() + prog,
                     data=[(HANDLER_PA, wbytes(cause_handler()))], **kw)


def test_load_in_device_window_without_device_deverr():
    # the keyboard window, before any keyboard device is registered
    prog = li128(1, DSB + 0x10000) + [lds(2, 1, 0, w=64), halt()]
    m, _ = _dev_space_run(prog)
    assert m.regs[10] == E.CAUSES["DEVERR"]
    assert m.regs[11] == DSB + 0x10000


def test_device_space_gap_is_not_ram():
    # between the NIC window's end (0x0F06_0000) and the pixel buffer
    prog = li128(1, DSB + 0x70000) + [st(2, 1, 0, w=64), halt()]
    m, _ = _dev_space_run(prog)
    assert m.regs[10] == E.CAUSES["DEVERR"]


def test_ram_extent_never_overrides_device_space():
    # even --ram 512 MB does not turn 0x0F00_0000 into RAM
    prog = li128(1, DSB) + [st(2, 1, 0, w=64), halt()]
    m, _ = _dev_space_run(prog, ram=1 << 29)
    assert m.regs[10] == E.CAUSES["DEVERR"]


def test_ram_up_to_device_space_base_still_ram():
    prog = (li128(1, DSB - 8)
            + [ldi(2, 0x77), st(2, 1, 0, w=64), lds(3, 1, 0, w=64), halt()])
    m, _ = _dev_space_run(prog)
    assert m.regs[10] == 0              # no trap
    assert m.regs[3] == 0x77


def test_fetch_from_device_space_deverr():
    from helpers import jalr
    prog = li128(1, DSB) + [jalr(31, 1), halt()]
    m, _ = _dev_space_run(prog)
    assert m.regs[10] == E.CAUSES["DEVERR"]
    assert m.regs[12] == DSB            # epc = the unfetchable pc


def test_misaligned_device_access_unaligned_wins():
    # root SPEC-ISSUES 25's recommended order (local 25): alignment is
    # a property of the ea, checked before any address classification
    prog = li128(1, DSB + 2) + [lds(2, 1, 0, w=32), halt()]
    m, _ = _dev_space_run(prog)
    assert m.regs[10] == E.CAUSES["UNALIGNED"]
    assert m.regs[11] == DSB + 2
