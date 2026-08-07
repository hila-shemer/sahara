"""C2-shaped smoke tests: page-table walk, permissions, PF vs PERM,
U-bit, malformed structures, and the --check-invtp phantom cache."""

import pytest

import encoding as E
import machine
from helpers import (HANDLER_PA, asm, cause_handler, halt, jalr, ldi, lds,
                     li128, make_machine, mtsr, run_words, st, vbase_setup,
                     wbytes)

S = 1 << E.STATUS_BITS["S"]
MMU = 1 << E.STATUS_BITS["MMU_EN"]

ROOT_PA = 0x100000
CHILD_PA = 0x110000
VPN_MASK = (1 << E.VPN_BITS) - 1


def leaf(frame, r=1, w=1, x=0, u=0):
    return (frame | E.PTE_TYPE_LEAF | (r << E.PTE_BITS["R"])
            | (w << E.PTE_BITS["W"]) | (x << E.PTE_BITS["X"])
            | (u << E.PTE_BITS["U"]))


def table(child_pa):
    return child_pa | E.PTE_TYPE_TABLE


def node(shift, prefix, prefix_mask, entries):
    blob = bytearray(E.NODE_BYTES)
    blob[0:8] = shift.to_bytes(8, "little")
    blob[8:24] = prefix.to_bytes(16, "little")
    blob[24:40] = prefix_mask.to_bytes(16, "little")
    for idx, ent in entries.items():
        off = E.NODE_HEADER_BYTES + idx * E.NODE_ENTRY_BYTES
        blob[off:off + 16] = ent.to_bytes(16, "little")
    return bytes(blob)


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
