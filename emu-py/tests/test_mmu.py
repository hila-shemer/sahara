"""C2-shaped smoke tests: page-table walk, permissions, PF vs PERM,
U-bit, malformed structures, and the --check-invtp phantom cache."""

import pytest

import encoding as E
import machine
from helpers import (HANDLER_PA, asm, cause_handler, halt, jalr, ldi, lds,
                     li128, make_machine, mtsr, pt_leaf, pt_node, pt_table,
                     run_words, st, vbase_setup, wbytes)

S = 1 << E.STATUS_BITS["S"]
MMU = 1 << E.STATUS_BITS["MMU_EN"]

ROOT_PA = 0x100000
CHILD_PA = 0x110000
VPN_MASK = (1 << E.VPN_BITS) - 1

leaf, table, node = pt_leaf, pt_table, pt_node


def tree(child_extra=None, root_extra=None):
    """Two-level tree: root(shift=8) -> child(shift=0). Child maps VPN 0
    (code+low RAM) RWX with U=1; extras per test."""
    child_entries = {0: leaf(0, r=1, w=1, x=1, u=1)}
    child_entries.update(child_extra or {})
    root_entries = {0: table(CHILD_PA)}
    root_entries.update(root_extra or {})
    return [
        (ROOT_PA, node(8, 0, 0, root_entries)),
        (CHILD_PA, node(0, 0, VPN_MASK & ~0xFF, child_entries)),
    ]


def enable(status=S | MMU):
    return [ldi(19, ROOT_PA), mtsr("ptbase", 19),
            ldi(19, status), mtsr("status", 19)]


def test_basic_map_and_store_through():
    data = tree({1: leaf(0x30000)})
    prog = (enable()
            + [ldi(1, 0x10000), ldi(2, 0x77), st(2, 1, 0, w=64),
               lds(0, 1, 0, w=64), halt()])
    m, out = run_words(prog, data=data)
    assert out == "halt"
    assert m.regs[0] == 0x77
    # the store landed in the mapped frame, not at the VA
    assert m.phys.read_raw(0x30000, 8) == (0x77).to_bytes(8, "little")
    assert m.phys.read_raw(0x10000, 8) != (0x77).to_bytes(8, "little")


def test_pf_load_unmapped():
    data = tree() + [(HANDLER_PA, wbytes(cause_handler()))]
    prog = (vbase_setup() + enable()
            + [ldi(1, 0x20000), lds(0, 1, 0, w=64), halt()])
    m, _ = run_words(prog, data=data)
    assert m.regs[10] == E.CAUSES["PF_LOAD"]
    assert m.regs[11] == 0x20000


def test_perm_store_vs_load():
    data = tree({1: leaf(0x30000, r=1, w=0)}) \
        + [(HANDLER_PA, wbytes(cause_handler()))]
    prog = (vbase_setup() + enable()
            + [ldi(1, 0x10000), lds(5, 1, 0, w=64),      # load OK
               ldi(2, 1), st(2, 1, 0, w=64), halt()])    # store PERM
    m, _ = run_words(prog, data=data)
    assert m.regs[10] == E.CAUSES["PERM_STORE"]
    assert m.regs[11] == 0x10000


def test_perm_fetch():
    data = tree({1: leaf(0x30000, r=1, w=1, x=0)}) \
        + [(HANDLER_PA, wbytes(cause_handler()))]
    prog = (vbase_setup() + enable()
            + [ldi(1, 0x10000), jalr(5, 1), halt()])
    m, _ = run_words(prog, data=data)
    assert m.regs[10] == E.CAUSES["PERM_FETCH"]
    assert m.regs[11] == 0x10000


def test_user_ubit_gating():
    # user mode: U=0 page faults PERM, U=1 page works
    data = tree({1: leaf(0x30000, u=0), 2: leaf(0x40000, u=1)}) \
        + [(HANDLER_PA, wbytes(cause_handler()))]
    prog = (vbase_setup() + enable()
            + [ldi(19, MMU), mtsr("status", 19),          # drop to user
               ldi(1, 0x20000), lds(5, 1, 0, w=64),       # U=1: OK
               ldi(1, 0x10000), lds(6, 1, 0, w=64),       # U=0: PERM_LOAD
               halt()])
    m, _ = run_words(prog, data=data)
    assert m.regs[10] == E.CAUSES["PERM_LOAD"]
    assert m.regs[11] == 0x10000


def test_supervisor_ignores_u_honors_rwx():
    data = tree({1: leaf(0x30000, r=1, w=1, u=0)})
    prog = (enable()
            + [ldi(1, 0x10000), ldi(2, 5), st(2, 1, 0, w=64),
               lds(0, 1, 0, w=64), halt()])
    m, out = run_words(prog, data=data)
    assert out == "halt"
    assert m.regs[0] == 5


def test_leaf_at_nonzero_shift_faults():
    # root entry 1 (VPN >= 256) is a leaf in a shift=8 node -> PF
    data = tree(root_extra={1: leaf(0x30000)}) \
        + [(HANDLER_PA, wbytes(cause_handler()))]
    va = 256 << E.PAGE_BITS
    prog = (vbase_setup() + enable()
            + li128(1, va) + [lds(0, 1, 0, w=64), halt()])
    m, _ = run_words(prog, data=data)
    assert m.regs[10] == E.CAUSES["PF_LOAD"]
    assert m.regs[11] == va


def test_type3_entry_faults():
    data = tree({3: leaf(0x30000) | 3}) \
        + [(HANDLER_PA, wbytes(cause_handler()))]
    prog = (vbase_setup() + enable()
            + [ldi(1, 0x30000), lds(0, 1, 0, w=64), halt()])
    m, _ = run_words(prog, data=data)
    assert m.regs[10] == E.CAUSES["PF_LOAD"]


def test_leaf_reserved_bits_fault():
    data = tree({4: leaf(0x30000) | (1 << 7)}) \
        + [(HANDLER_PA, wbytes(cause_handler()))]
    prog = (vbase_setup() + enable()
            + [ldi(1, 0x40000), lds(0, 1, 0, w=64), halt()])
    m, _ = run_words(prog, data=data)
    assert m.regs[10] == E.CAUSES["PF_LOAD"]


def test_prefix_mismatch_faults():
    # child prefix covers VPN < 256; route a high VPN into it
    data = tree(root_extra={1: table(CHILD_PA)}) \
        + [(HANDLER_PA, wbytes(cause_handler()))]
    va = 256 << E.PAGE_BITS
    prog = (vbase_setup() + enable()
            + li128(1, va) + [lds(0, 1, 0, w=64), halt()])
    m, _ = run_words(prog, data=data)
    assert m.regs[10] == E.CAUSES["PF_LOAD"]


def test_mmu_off_identity():
    prog = [ldi(1, 0x30000), ldi(2, 3), st(2, 1, 0, w=64),
            lds(0, 1, 0, w=64), halt()]
    m, _ = run_words(prog)
    assert m.regs[0] == 3
    assert m.phys.read_raw(0x30000, 8) == (3).to_bytes(8, "little")


# entry PA of child slot for VPN 1, identity-mapped via VPN 0x11
_ENTRY1_VA = CHILD_PA + E.NODE_HEADER_BYTES + 1 * E.NODE_ENTRY_BYTES


def _remap_tree():
    return tree({1: leaf(0x30000),
                 CHILD_PA >> E.PAGE_BITS: leaf(CHILD_PA)})


def _remap_prog(*, with_invtp):
    return (enable()
            + [ldi(1, 0x10000), lds(5, 1, 0, w=64),       # load via map A
               ldi(2, leaf(0x40000)),                     # new PTE: frame B
               ldi(3, _ENTRY1_VA), st(2, 3, 0, w=64)]     # rewrite PTE
            + ([asm("INVTP")] if with_invtp else [])
            + [lds(6, 1, 0, w=64), halt()])


def test_invtp_check_detects_missing_invtp():
    data = _remap_tree() + [(0x30000, (111).to_bytes(8, "little")),
                            (0x40000, (222).to_bytes(8, "little"))]
    m = make_machine(_remap_prog(with_invtp=False), data=data,
                     check_invtp=True)
    with pytest.raises(machine.CheckFail):
        m.run(100000)


def test_invtp_clears_phantom_cache():
    data = _remap_tree() + [(0x30000, (111).to_bytes(8, "little")),
                            (0x40000, (222).to_bytes(8, "little"))]
    m, out = run_words(_remap_prog(with_invtp=True), data=data,
                       check_invtp=True)
    assert out == "halt"
    assert m.regs[5] == 111
    assert m.regs[6] == 222


def test_remap_without_check_mode_reads_new_mapping():
    # no translation cache exists: remap without INVTP is visible (the
    # check mode exists precisely to flag this as a contract violation)
    data = _remap_tree() + [(0x30000, (111).to_bytes(8, "little")),
                            (0x40000, (222).to_bytes(8, "little"))]
    m, out = run_words(_remap_prog(with_invtp=False), data=data)
    assert out == "halt"
    assert m.regs[6] == 222


def test_asid_change_avoids_stale_assert():
    # changing asid re-keys the phantom cache: no INVTP needed
    data = _remap_tree() + [(0x30000, (111).to_bytes(8, "little")),
                            (0x40000, (222).to_bytes(8, "little"))]
    prog = (enable()
            + [ldi(1, 0x10000), lds(5, 1, 0, w=64),
               ldi(2, leaf(0x40000)), ldi(3, _ENTRY1_VA),
               st(2, 3, 0, w=64),
               ldi(4, 1), mtsr("asid", 4),
               lds(6, 1, 0, w=64), halt()])
    m, out = run_words(prog, data=data, check_invtp=True)
    assert out == "halt"
    assert m.regs[6] == 222


def test_aliasing_two_vas_one_frame():
    data = tree({1: leaf(0x30000), 2: leaf(0x30000)})
    prog = (enable()
            + [ldi(1, 0x10000), ldi(2, 0x20000), ldi(3, 42),
               st(3, 1, 0, w=64), lds(0, 2, 0, w=64), halt()])
    m, _ = run_words(prog, data=data)
    assert m.regs[0] == 42


# ------------------------------------------- path compression, high VAs
# CONFORMANCE C2: "Path-compression: ... regions above 2^64 and 2^100."
# Two-node walks over the 112-bit VPN space: the root dispatches on the
# highest differing chunk, prefix_mask compresses every chunk in between.

CHILD_HI_PA = 0x120000                 # VPN 0x12: identity-mappable
HI64_VA = 1 << 70                      # VPN bit 54 -> chunk 6, value 64
HI100_VA = 1 << 100                    # VPN bit 84 -> chunk 10, value 16

CODE_LEAF = leaf(0, r=1, w=1, x=1, u=1)


def hi_tree(root_shift, hi_idx, hi_prefix, hi_extra=None, lo_extra=None):
    """Root at root_shift dispatching {0: low child, hi_idx: high child};
    prefix_mask on the root compresses all chunks above it, on each child
    all chunks below the root's."""
    above_root = VPN_MASK & ~((1 << (root_shift + 8)) - 1)
    lo_entries = {0: CODE_LEAF}
    lo_entries.update(lo_extra or {})
    hi_entries = {0: leaf(0x30000)}
    hi_entries.update(hi_extra or {})
    return [
        (ROOT_PA, node(root_shift, 0, above_root,
                       {0: table(CHILD_PA), hi_idx: table(CHILD_HI_PA)})),
        (CHILD_PA, node(0, 0, VPN_MASK & ~0xFF, lo_entries)),
        (CHILD_HI_PA, node(0, hi_prefix, VPN_MASK & ~0xFF, hi_entries)),
    ]


def test_region_above_2_64():
    data = hi_tree(48, 64, HI64_VA >> E.PAGE_BITS)
    prog = (enable() + li128(1, HI64_VA)
            + [ldi(2, 0x77), st(2, 1, 0, w=64),
               lds(0, 1, 0, w=64), halt()])
    m, out = run_words(prog, data=data, check_invtp=True)
    assert out == "halt"
    assert m.regs[0] == 0x77
    assert m.phys.read_raw(0x30000, 8) == (0x77).to_bytes(8, "little")


def test_region_above_2_100():
    data = hi_tree(80, 16, HI100_VA >> E.PAGE_BITS)
    prog = (enable() + li128(1, HI100_VA)
            + [ldi(2, 0x5A), st(2, 1, 0, w=64),
               lds(0, 1, 0, w=64), halt()])
    m, out = run_words(prog, data=data, check_invtp=True)
    assert out == "halt"
    assert m.regs[0] == 0x5A
    assert m.phys.read_raw(0x30000, 8) == (0x5A).to_bytes(8, "little")


def test_prefix_mismatch_above_2_64_full_baddr():
    # routes into the high child by chunk 10, then fails its prefix
    # check; baddr must carry all 128 bits of the VA.
    data = (hi_tree(80, 16, HI100_VA >> E.PAGE_BITS)
            + [(HANDLER_PA, wbytes(cause_handler()))])
    va = HI100_VA | (1 << 90)
    prog = (vbase_setup() + enable()
            + li128(1, va) + [lds(0, 1, 0, w=64), halt()])
    m, _ = run_words(prog, data=data)
    assert m.regs[10] == E.CAUSES["PF_LOAD"]
    assert m.regs[11] == va


# entry PA of the high child's slot 0, identity-mapped via VPN 0x12
_HI_ENTRY0_VA = CHILD_HI_PA + E.NODE_HEADER_BYTES


def _hi_remap_data():
    return (hi_tree(80, 16, HI100_VA >> E.PAGE_BITS,
                    lo_extra={CHILD_HI_PA >> E.PAGE_BITS:
                              leaf(CHILD_HI_PA)})
            + [(0x30000, (111).to_bytes(8, "little")),
               (0x40000, (222).to_bytes(8, "little"))])


def _hi_remap_prog(*, with_invtp):
    return (enable() + li128(1, HI100_VA)
            + [lds(5, 1, 0, w=64),                        # load via frame A
               ldi(2, leaf(0x40000)),                     # new PTE: frame B
               ldi(3, _HI_ENTRY0_VA), st(2, 3, 0, w=64)]  # rewrite deep PTE
            + ([asm("INVTP")] if with_invtp else [])
            + [lds(6, 1, 0, w=64), halt()])


def test_remap_above_2_100_missing_invtp_asserts():
    m = make_machine(_hi_remap_prog(with_invtp=False), data=_hi_remap_data(),
                     check_invtp=True)
    with pytest.raises(machine.CheckFail):
        m.run(100000)


def test_remap_above_2_100_with_invtp():
    m, out = run_words(_hi_remap_prog(with_invtp=True),
                       data=_hi_remap_data(), check_invtp=True)
    assert out == "halt"
    assert m.regs[5] == 111
    assert m.regs[6] == 222


# -------------------------------------------------- ptbase switch, ASID
# CONFORMANCE C2: "change ptbase+asid without INVTP (legal), change
# ptbase alone without INVTP (illegal -- check-mode assertion fires)."

ROOT_B_PA = 0x130000
CHILD_B_PA = 0x140000


def _two_trees():
    """Tree A (at ROOT_PA) maps VA 0x10000 -> 0x30000; tree B (at
    ROOT_B_PA) maps it -> 0x40000. Both map VPN 0 identically so code
    fetches translate the same either way."""
    return (tree({1: leaf(0x30000)})
            + [(ROOT_B_PA, node(8, 0, 0, {0: table(CHILD_B_PA)})),
               (CHILD_B_PA, node(0, 0, VPN_MASK & ~0xFF,
                                 {0: CODE_LEAF, 1: leaf(0x40000)})),
               (0x30000, (111).to_bytes(8, "little")),
               (0x40000, (222).to_bytes(8, "little"))])


def test_ptbase_change_alone_asserts():
    prog = (enable()
            + [ldi(1, 0x10000), lds(5, 1, 0, w=64),
               ldi(2, ROOT_B_PA), mtsr("ptbase", 2),
               lds(6, 1, 0, w=64), halt()])
    m = make_machine(prog, data=_two_trees(), check_invtp=True)
    with pytest.raises(machine.CheckFail):
        m.run(100000)


def test_ptbase_change_with_asid_ok():
    prog = (enable()
            + [ldi(1, 0x10000), lds(5, 1, 0, w=64),
               ldi(3, 1), mtsr("asid", 3),
               ldi(2, ROOT_B_PA), mtsr("ptbase", 2),
               lds(6, 1, 0, w=64), halt()])
    m, out = run_words(prog, data=_two_trees(), check_invtp=True)
    assert out == "halt"
    assert m.regs[5] == 111
    assert m.regs[6] == 222


def test_cyclic_table_walk_faults():
    # root entry 1 points back at the root: the walk must terminate and
    # fault PF rather than loop (emu-py SPEC-ISSUES 13, depth guard).
    data = [(ROOT_PA, node(8, 0, 0, {0: table(CHILD_PA),
                                     1: table(ROOT_PA)})),
            (CHILD_PA, node(0, 0, VPN_MASK & ~0xFF, {0: CODE_LEAF})),
            (HANDLER_PA, wbytes(cause_handler()))]
    va = 256 << E.PAGE_BITS
    prog = (vbase_setup() + enable()
            + li128(1, va) + [lds(0, 1, 0, w=64), halt()])
    m, _ = run_words(prog, data=data)
    assert m.regs[10] == E.CAUSES["PF_LOAD"]
    assert m.regs[11] == va


# ------------- MMU enable while pc's own page is unfetchable: the MTSR
# retires, the very NEXT fetch faults, baddr = epc = that pc.
def test_mmu_enable_pc_page_noexec_perm_fetch_next_fetch():
    handler_va, handler_pa = 0x10000, 0x30000
    data = tree({0: leaf(0, r=1, w=1, x=0, u=1),        # code page: no X
                 1: leaf(handler_pa, r=1, w=1, x=1)}) \
        + [(handler_pa, wbytes(cause_handler()))]
    prog = vbase_setup(handler_va) + enable() + [halt()]
    m, out = run_words(prog, data=data)
    assert out == "halt"
    fault_pc = E.RESET_PC + 6 * 8              # insn right after the MTSR
    assert m.regs[10] == E.CAUSES["PERM_FETCH"]
    assert m.regs[11] == fault_pc              # baddr = fetch VA
    assert m.regs[12] == fault_pc              # epc = same: nothing retired


def test_mmu_enable_pc_page_unmapped_pf_fetch_next_fetch():
    handler_va, handler_pa = 0x10000, 0x30000
    data = [(ROOT_PA, node(8, 0, 0, {0: table(CHILD_PA)})),
            (CHILD_PA, node(0, 0, VPN_MASK & ~0xFF,
                            {1: leaf(handler_pa, r=1, w=1, x=1)})),
            (handler_pa, wbytes(cause_handler()))]     # VPN 0 absent
    prog = vbase_setup(handler_va) + enable() + [halt()]
    m, out = run_words(prog, data=data)
    assert out == "halt"
    fault_pc = E.RESET_PC + 6 * 8
    assert m.regs[10] == E.CAUSES["PF_FETCH"]
    assert m.regs[11] == fault_pc
    assert m.regs[12] == fault_pc


def test_walk_node_in_device_window_faults():
    """SPEC-ISSUES 13: table reads come from plain RAM. A root entry
    pointing the walk at a device window is malformed - the access
    faults PF, the walker never issues a device load."""
    from helpers import QueueDevice
    DEV_PA = 0x200000
    dev = QueueDevice(DEV_PA, size=64)
    data = tree(root_extra={1: table(DEV_PA)}) \
        + [(HANDLER_PA, wbytes(cause_handler()))]
    bad_va = 0x100 << E.PAGE_BITS              # root idx 1 -> device
    prog = (vbase_setup() + enable()
            + li128(1, bad_va)
            + [lds(0, 1, 0, w=64), halt()])
    m, _ = run_words(prog, data=data, devices=[dev])
    assert m.regs[10] == E.CAUSES["PF_LOAD"]
    assert m.regs[11] == bad_va
