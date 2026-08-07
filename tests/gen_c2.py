#!/usr/bin/env python3
"""Generate tests/c2_mmu.s — CONFORMANCE.md group C2, MMU runtime remap.

Page-table nodes are emitted as image data segments, computed here from
encoding.py's MMU constants (node layout, entry types, PTE bits) — no
hand-packed magic numbers in the .s. The parts of C2 whose *point* is
runtime table manipulation (OS-owned mapping built with stores, remap
under fire, INVTP contract) modify the tables through an identity-
mapped table page with the MMU ON — the OS pattern, not a test cheat.

Address plan (PA):
  0x20000 ROOT   shift 80: entry[0x00]->NODEA, [0x10]->NODED (VA 2^100),
                 [0x40]->NODEE (VA 2^102) — three scattered regions,
                 depth scales with regions (ISA-SPEC 8.5)
  0x22000 NODEA  shift 8, covers VPN 0x0000-0xFFFF: [0]->NODEB,
                 [1]->NODEC, [2]=leaf-at-shift!=0 (illegal)
  0x24000 NODEB  shift 0, VPN 0x00-0xFF: the low 16 MB map (below)
  0x26000 NODEC  shift 0, VPN 0x100-0x1FF: [0x23]->frame (multi-level)
  0x28000 NODED  shift 0, prefix 2^84:  [0]->frame M_HI1
  0x2A000 NODEE  shift 0, prefix 2^86:  [0]->frame M_HI2
  0x2C000 ROOT2  shift 0 single-node space for the ASID switch test

NODEB (VA page = VPN * 64 KB):
  [0] frame 0x0     RWX U  code + scratch slots, user-runnable
  [1] frame 0x30000 RW  U  the remap-under-fire page (P1 -> P2)
  [2] frame 0x20000 RW     identity window over all table nodes
  [3] invalid              PF_LOAD/PF_STORE/PF_FETCH targets
  [4] type-3 entry         reserved type faults PF
  [5] frame 0x70000 RW     alias A |
  [6] frame 0x70000 RW     alias B | one frame, two VAs
  [7] invalid              runtime-built mapping goes here (stores)
  [8] frame 0x90000 R      PERM_STORE target; U=0 for the user test
  [9] frame 0xA0000 W      PERM_LOAD target (store through it works)
  [10] frame 0xB0000 RW    no X: PERM_FETCH target
  [12] frame 0xC0000 RW + reserved bits set: malformed leaf faults PF

The check-mode ASSERTION side (CONFORMANCE C2 "check-mode assertion
fires") cannot live in a passing run: it ends exit 3 with an
implementation-worded reason line. It lives in two additional images
this generator also emits, carried as expect=checkfail in MANIFEST
(SPEC-ISSUES 22/23):
- c2_noinvtp_remap.s   — PTE rewritten through the identity window,
  no INVTP, reuse of the old translation must CHECKFAIL.
- c2_noinvtp_ptbase.s  — ptbase changed alone (same asid, no INVTP),
  next data access translates differently and must CHECKFAIL. The code
  page is mapped result-identically (frame AND permissions, U included)
  under both roots so the fetches inside the switch window cannot trip
  a result-comparing stale check (SPEC-ISSUES 21).

Bounded coverage — deliberately NOT here:
- Superpages do not exist in v1.0 (leaf at shift!=0 is the *fault*
  test here).

Deterministic; output is committed (all three .s files).
"""

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)
import encoding as E  # noqa: E402

M112 = (1 << 112) - 1

PTE = {n: 1 << b for n, b in E.PTE_BITS.items()}
T_TABLE, T_LEAF = E.PTE_TYPE_TABLE, E.PTE_TYPE_LEAF

ROOT, NODEA, NODEB, NODEC = 0x20000, 0x22000, 0x24000, 0x26000
NODED, NODEE, ROOT2 = 0x28000, 0x2A000, 0x2C000


def leaf(frame, *perms, junk=0):
    v = frame | T_LEAF | junk
    for p in perms:
        v |= PTE[p]
    return v


def table(child):
    assert child % E.NODE_ALIGN == 0
    return child | T_TABLE


def mask_above(shift):
    """prefix_mask: every VPN bit strictly above this node's own chunk.
    That re-checks chunks ancestors already indexed — legal (the
    indexed value is consistent with the prefix by construction) and
    exercises the prefix comparison hardest. A node must never mask
    bits at or below its own chunk: those are indexed here or by a
    child."""
    return M112 & ~((1 << (shift + E.CHUNK_BITS)) - 1)


OUT = []


def emit(s=""):
    OUT.append(s)


def node(pa, shift, prefix, mask, entries):
    emit(f"        .org 0x{pa:x}")
    emit(f"        .quad {shift}          # shift")
    emit(f"        .oct 0x{prefix:x}   # prefix")
    emit(f"        .oct 0x{mask:x}   # prefix_mask")
    emit(f"        .space {E.NODE_HEADER_BYTES - 40}   # reserved, zero")
    nxt = 0
    for idx in sorted(entries):
        assert 0 <= idx < E.NODE_ENTRIES
        if idx > nxt:
            emit(f"        .space {(idx - nxt) * E.NODE_ENTRY_BYTES}")
        emit(f"        .oct 0x{entries[idx]:x}   # entry[{idx}]")
        nxt = idx + 1
    if nxt < E.NODE_ENTRIES:
        emit(f"        .space {(E.NODE_ENTRIES - nxt) * E.NODE_ENTRY_BYTES}")


def emit_equates():
    for name, v in [
        ("ROOT_PA", ROOT), ("NODEA_PA", NODEA), ("NODEB_PA", NODEB),
        ("ROOT2_PA", ROOT2),
        ("VA_P1", 0x10000), ("VA_TABLES", 0x20000),
        ("VA_UNMAPPED", 0x30000), ("VA_TYPE3", 0x40000),
        ("VA_ALIAS_A", 0x50000), ("VA_ALIAS_B", 0x60000),
        ("VA_RUNTIME", 0x70000), ("VA_RONLY", 0x80000),
        ("VA_WONLY", 0x90000), ("VA_NOX", 0xA0000),
        ("VA_BADLEAF", 0xC0000),
        ("VA_MULTI", 0x123_0000), ("VA_SHIFTLEAF", 0x200_0000),
        # markers fit the signed 22-bit imm so checks can compare
        # against them directly
        ("M1", 0x1111), ("M2", 0x2222),
        ("M_ML", 0x3333), ("M_HI1", 0x4444),
        ("M_HI2", 0x5555), ("M_ASID", 0x6666),
        ("M_RO", 0x7777),
        # runtime-installed leaf for VA_RUNTIME and remap leaf for VA_P1,
        # computed here so the .s stores encoding-correct entries
        ("PTE_RUNTIME_LEAF", leaf(0x80000, "R", "W")),
        ("PTE_REMAP_LEAF", leaf(0x40000, "R", "W", "U")),
        ("NODEB_E1_ADDR", NODEB + E.NODE_HEADER_BYTES
         + 1 * E.NODE_ENTRY_BYTES),
        ("NODEB_E7_ADDR", NODEB + E.NODE_HEADER_BYTES
         + 7 * E.NODE_ENTRY_BYTES),
        ("STATUS_MMU_ON", (1 << E.STATUS_BITS["S"])
         | (1 << E.STATUS_BITS["MMU_EN"])),
        ("STATUS_MMU_OFF", 1 << E.STATUS_BITS["S"]),
    ]:
        emit(f"        .equ {name}, 0x{v:x}")


def emit_tables_and_seeds():
    # ---- page tables and frame seeds as data segments ----
    emit("# ==== page tables (layout from encoding.py MMU constants) ====")
    node(ROOT, 80, 0, mask_above(80), {
        0x00: table(NODEA),
        0x10: table(NODED),
        0x40: table(NODEE),
    })
    node(NODEA, 8, 0, mask_above(8), {
        0: table(NODEB),
        1: table(NODEC),
        2: leaf(0xD0000, "R", "W"),   # leaf at shift!=0: walk must fault
    })
    node(NODEB, 0, 0, mask_above(0), {
        0: leaf(0x00000, "R", "W", "X", "U"),
        1: leaf(0x30000, "R", "W", "U"),
        2: leaf(0x20000, "R", "W"),
        # 3 invalid
        4: (0xD0000 | 3),             # type-3 (reserved) entry
        5: leaf(0x70000, "R", "W"),
        6: leaf(0x70000, "R", "W"),
        # 7 invalid until built at runtime
        8: leaf(0x90000, "R"),
        9: leaf(0xA0000, "W"),
        10: leaf(0xB0000, "R", "W"),
        12: leaf(0xC0000, "R", "W", junk=0x1FC0),  # reserved bits 15:6
    })
    node(NODEC, 0, 0x100, mask_above(0), {
        0x23: leaf(0xD0000, "R", "W"),
    })
    node(NODED, 0, 1 << 84, mask_above(0), {
        0: leaf(0xE0000, "R", "W"),
    })
    node(NODEE, 0, 1 << 86, mask_above(0), {
        0: leaf(0xF0000, "R", "W"),
    })
    # ROOT2 maps VPN0 to the SAME frame AND permissions as ROOT's path
    # does (NODEB[0]: RWX+U): the fetches between the ptbase and asid
    # writes in c2_mmu test [32] — and after the lone ptbase write in
    # c2_noinvtp_ptbase — then translate result-identically under
    # either table, so the switch window cannot trip a result-comparing
    # stale check (SPEC-ISSUES 21). The U bit is part of the result: a
    # mismatch there would legitimately fire the assertion on a fetch.
    node(ROOT2, 0, 0, mask_above(0), {
        0: leaf(0x00000, "R", "W", "X", "U"),
        1: leaf(0x100000, "R", "W"),
    })

    emit()
    emit("# ==== frame seeds ====")
    for pa, marker in sorted([(0x30000, "M1"), (0x40000, "M2"),
                              (0xD0000, "M_ML"), (0xE0000, "M_HI1"),
                              (0xF0000, "M_HI2"), (0x100000, "M_ASID"),
                              (0x90000, "M_RO")]):
        emit(f"        .org 0x{pa:x}")
        emit(f"        .quad {marker}")


def write_image(basename, header_lines, code):
    OUT.clear()
    for line in header_lines:
        emit(line)
    emit()
    emit_equates()
    emit()
    emit(code)
    emit_tables_and_seeds()
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       basename)
    with open(out, "w") as f:
        f.write("\n".join(OUT) + "\n")
    print(f"wrote {out}")


def main():
    write_image("c2_mmu.s", [
        "# c2_mmu — GENERATED by tests/gen_c2.py — DO NOT EDIT.",
        "# CONFORMANCE.md group C2: MMU runtime remap. Assembled after",
        "# tests/defs.s. Layout rationale + bounded-coverage notes in",
        "# gen_c2.py's docstring.",
    ], CODE)
    write_image("c2_noinvtp_remap.s", [
        "# c2_noinvtp_remap — GENERATED by tests/gen_c2.py — DO NOT",
        "# EDIT. CONFORMANCE C2: remap WITHOUT INVTP must fire the",
        "# --check-invtp stale-translation assertion (CHECKFAIL exit 3;",
        "# expect=checkfail in MANIFEST — SPEC-ISSUES 21/22/23). Any",
        "# HALT here means the check mode is absent or broken.",
    ], CODE_NOINVTP_REMAP)
    write_image("c2_noinvtp_ptbase.s", [
        "# c2_noinvtp_ptbase — GENERATED by tests/gen_c2.py — DO NOT",
        "# EDIT. CONFORMANCE C2: changing ptbase alone (same asid, no",
        "# INVTP) must fire the --check-invtp assertion at the next",
        "# data access whose fresh walk disagrees with the cached",
        "# translation (CHECKFAIL exit 3; expect=checkfail in MANIFEST",
        "# — SPEC-ISSUES 21/22/23). The code page translates result-",
        "# identically under both roots, so fetches must NOT trip it.",
    ], CODE_NOINVTP_PTBASE)


CODE = r"""
        .org 0x1000
start:
        li r24, FAIL_ADDR
        li r21, h_rec
        mtsr vbase, r21

        # -- [1] enable mid-stream: ptbase/asid, INVTP, MMU_EN on ------
        li r27, 1
        li r19, 0xAB
        st.64 r19, [r24 + SENTINEL_BOX - FAIL_ADDR]
        li r21, ROOT_PA
        mtsr ptbase, r21
        li r21, 0xA
        mtsr asid, r21
        invtp                     # tables were loaded before this point
        li r21, STATUS_MMU_ON
        mtsr status, r21          # next fetch is translated (VPN 0)
        lds.64 r22, [r24 + SENTINEL_BOX - FAIL_ADDR]
        cmpeq p1, r22, r19        # VPN0 maps identity: still readable
        (!p1) b fail

        # -- [2] mapped load through VPN1 -> P1 ------------------------
        li r27, 2
        li r25, VA_P1
        lds.64 r22, [r25]
        cmpeq p1, r22, M1
        (!p1) b fail

        # -- [3] mapped store lands in the frame, not at the VA --------
        li r27, 3
        li r19, 0xC0DE
        st.64 r19, [r25 + 8]
        lds.64 r22, [r25 + 8]     # readback through the mapping
        cmpeq p1, r22, r19
        (!p1) b fail
        li r21, STATUS_MMU_OFF    # drop to identity and look at the PA
        mtsr status, r21
        li r27, 4
        li r20, 0x30008
        lds.64 r22, [r20]
        cmpeq p1, r22, r19
        (!p1) b fail
        li r21, STATUS_MMU_ON
        mtsr status, r21

        # -- [5] multi-level walk (ROOT -> NODEA -> NODEC -> leaf) -----
        li r27, 5
        li r25, VA_MULTI
        lds.64 r22, [r25]
        cmpeq p1, r22, M_ML
        (!p1) b fail

        # -- [6][7] scattered regions above 2^64 and 2^100 -------------
        li r27, 6
        li r25, 0x10000000000000000000000000    # 2^100
        lds.64 r22, [r25]
        cmpeq p1, r22, M_HI1
        (!p1) b fail
        li r27, 7
        li r25, 0x40000000000000000000000000    # 2^102
        lds.64 r22, [r25]
        cmpeq p1, r22, M_HI2
        (!p1) b fail

        # -- [8] aliasing: two VAs, one frame --------------------------
        li r27, 8
        li r25, VA_ALIAS_A
        li r23, VA_ALIAS_B
        li r19, 0xA11A5
        st.64 r19, [r25]
        lds.64 r22, [r23]
        cmpeq p1, r22, r19
        (!p1) b fail

        # ==== fault paths: cause + baddr + epc via h_rec ==============
        # -- [9] PF_LOAD on invalid entry ------------------------------
        li r27, 9
        li r25, VA_UNMAPPED
c2_pf_site:
        lds.64 r22, [r25]
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_PF_LOAD
        (!p1) b fail
        li r27, 10
        lds.64 r22, [r24 + TRAP_BADDR_SLOT - FAIL_ADDR]
        cmpeq p1, r22, r25
        (!p1) b fail
        li r27, 11
        lds.64 r22, [r24 + TRAP_EPC_SLOT - FAIL_ADDR]
        li r20, c2_pf_site
        cmpeq p1, r22, r20
        (!p1) b fail

        # -- [12] PF_STORE on invalid entry ----------------------------
        li r27, 12
        st.64 r19, [r25]
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_PF_STORE
        (!p1) b fail

        # -- [13] type-3 entry faults PF -------------------------------
        li r27, 13
        li r25, VA_TYPE3
        lds.64 r22, [r25]
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_PF_LOAD
        (!p1) b fail

        # -- [14] leaf in a shift!=0 node faults PF --------------------
        li r27, 14
        li r25, VA_SHIFTLEAF
        lds.64 r22, [r25]
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_PF_LOAD
        (!p1) b fail

        # -- [15] malformed leaf (reserved bits 15:6 set) faults PF ----
        li r27, 15
        li r25, VA_BADLEAF
        lds.64 r22, [r25]
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_PF_LOAD
        (!p1) b fail

        # -- [16] prefix mismatch (VA 2^40: VPN bits [16,80) nonzero) --
        li r27, 16
        li r25, 0x10000000000    # 2^40
        lds.64 r22, [r25]
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_PF_LOAD
        (!p1) b fail
        li r27, 17
        lds.64 r22, [r24 + TRAP_BADDR_SLOT - FAIL_ADDR]
        cmpeq p1, r22, r25
        (!p1) b fail

        # -- [18] R-only page: load ok, store PERM_STORE ---------------
        li r27, 18
        li r25, VA_RONLY
        lds.64 r22, [r25]
        cmpeq p1, r22, M_RO
        (!p1) b fail
        li r27, 19
        st.64 r19, [r25]
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_PERM_STORE
        (!p1) b fail
        li r27, 20
        lds.64 r22, [r24 + TRAP_BADDR_SLOT - FAIL_ADDR]
        cmpeq p1, r22, r25
        (!p1) b fail

        # -- [21] W-only page: store lands, load PERM_LOAD -------------
        li r27, 21
        li r25, VA_WONLY
        li r19, 0x570CE
        st.64 r19, [r25]          # allowed: W set
        lds.64 r22, [r25]         # PERM_LOAD, recorded and skipped
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_PERM_LOAD
        (!p1) b fail
        li r21, STATUS_MMU_OFF    # verify the store reached the frame
        mtsr status, r21
        li r27, 22
        li r20, 0xA0000
        lds.64 r22, [r20]
        cmpeq p1, r22, r19
        (!p1) b fail
        li r21, STATUS_MMU_ON
        mtsr status, r21

        # -- [23] PERM_FETCH: jump into an RW-noX page -----------------
        li r27, 23
        li r21, h_fetch
        mtsr vbase, r21
        li r21, c2_after_nox
        st.64 r21, [r24 + SENTINEL_BOX - FAIL_ADDR]   # h_fetch target
        li r25, VA_NOX
        jalr zero, r25, 0
c2_after_nox:
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_PERM_FETCH
        (!p1) b fail
        li r27, 24                # baddr = epc = the fetch target
        lds.64 r22, [r24 + TRAP_BADDR_SLOT - FAIL_ADDR]
        cmpeq p1, r22, r25
        (!p1) b fail
        li r27, 25
        lds.64 r22, [r24 + TRAP_EPC_SLOT - FAIL_ADDR]
        cmpeq p1, r22, r25
        (!p1) b fail

        # -- [26] PF_FETCH: jump into an unmapped page -----------------
        li r27, 26
        li r21, c2_after_pff
        st.64 r21, [r24 + SENTINEL_BOX - FAIL_ADDR]
        li r25, VA_UNMAPPED
        jalr zero, r25, 0
c2_after_pff:
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_PF_FETCH
        (!p1) b fail
        li r21, h_rec
        mtsr vbase, r21

        # -- [27] atomics report load-before-store order (C3 bullet) ---
        li r27, 27
        li r25, VA_RONLY          # R ok, W missing -> PERM_STORE
        amoadd.64 r22, [r25], r19
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_PERM_STORE
        (!p1) b fail
        li r27, 28
        li r25, VA_UNMAPPED       # nothing mapped -> PF_LOAD first
        amoadd.64 r22, [r25], r19
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_PF_LOAD
        (!p1) b fail

        # -- [29] false-predicated load to unmapped VA cannot fault ----
        #    (the C1 bullet that needed a real MMU)
        li r27, 29
        li r19, 12345
        st.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]  # sentinel
        li r21, 7
        cmpeq p2, r21, 8          # p2 = 0
        li r25, VA_UNMAPPED
        (p2) lds.64 r22, [r25]    # squashed: no translation, no fault
        (p2) st.64 r22, [r25]
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        li r19, 12345
        cmpeq p1, r22, r19
        (!p1) b fail

        # ==== the OS patterns: runtime table writes ===================
        # -- [30] build a mapping with stores, INVTP, use it -----------
        li r27, 30
        li r25, VA_TABLES + NODEB_E7_ADDR - 0x20000   # entry[7] via the
        li r19, PTE_RUNTIME_LEAF                      # identity window
        st128 r19, [r25]
        invtp
        li r25, VA_RUNTIME
        li r19, 0xB007ED
        st.64 r19, [r25]
        lds.64 r22, [r25]
        cmpeq p1, r22, r19
        (!p1) b fail

        # -- [31] remap under fire: P1 -> P2, INVTP, read --------------
        li r27, 31
        li r25, VA_P1
        lds.64 r22, [r25]         # touch through the old mapping first
        li r25, VA_TABLES + NODEB_E1_ADDR - 0x20000
        li r19, PTE_REMAP_LEAF
        st128 r19, [r25]
        invtp                     # the contract move (ISA-SPEC 8.7)
        li r25, VA_P1
        lds.64 r22, [r25]
        cmpeq p1, r22, M2         # new frame's seed, not M1
        (!p1) b fail

        # -- [32] ptbase+asid switch without INVTP is legal ------------
        li r27, 32
        li r21, ROOT2_PA
        mtsr ptbase, r21
        li r21, 0xB
        mtsr asid, r21            # new space: no INVTP required
        li r25, VA_P1
        lds.64 r22, [r25]
        cmpeq p1, r22, M_ASID
        (!p1) b fail
        li r27, 33                # and back: asid A translations are
        li r21, ROOT_PA           # still valid (tables unchanged)
        mtsr ptbase, r21
        li r21, 0xA
        mtsr asid, r21
        lds.64 r22, [r25]
        cmpeq p1, r22, M2
        (!p1) b fail

        # ==== U-bit gating in user mode ===============================
        li r27, 34
        li r21, h_user
        mtsr vbase, r21
        li r19, 0
        st.64 r19, [r24 + PRIV_COUNT_SLOT - FAIL_ADDR]
        li r21, user_entry
        mtsr epc0, r21
        li r21, STATUS_MMU_ON     # PS=0 -> IRET drops to user, MMU on
        mtsr status, r21
        iret
user_entry:
        li r25, VA_P1             # U=1 page: user load succeeds
        lds.64 r22, [r25]
        cmpeq p1, r22, M2
        (!p1) b fail
        li r27, 35
        li r25, VA_RONLY          # U=0 page: PERM_LOAD (counted+skipped)
        lds.64 r22, [r25]
        lds.64 r22, [r24 + PRIV_COUNT_SLOT - FAIL_ADDR]
        cmpeq p1, r22, 1
        (!p1) b fail
        syscall                   # exit to supervisor (h_user)
        b fail
u_cont:
        # supervisor ignores U but honors R/W/X (already exercised: [18]
        # R-only and [21] W-only pages are U=0 and were driven from
        # supervisor mode above)

pass:
        li r0, PASS_MAGIC
        halt
fail:
        st.64 r27, [r24]
        mov r0, r27
        halt

        # record cause/baddr/epc, skip the faulting instruction
h_rec:
        mfsr k0, cause0
        st.64 k0, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        mfsr k0, baddr0
        st.64 k0, [r24 + TRAP_BADDR_SLOT - FAIL_ADDR]
        mfsr k0, epc0
        st.64 k0, [r24 + TRAP_EPC_SLOT - FAIL_ADDR]
        mfsr k0, epc0
        add k0, k0, 8
        mtsr epc0, k0
        iret

        # fetch-fault handler: record, then resume at the continuation
        # the test parked in SENTINEL_BOX (epc points into the dead
        # page; +8 would not help)
h_fetch:
        mfsr k0, cause0
        st.64 k0, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        mfsr k0, baddr0
        st.64 k0, [r24 + TRAP_BADDR_SLOT - FAIL_ADDR]
        mfsr k0, epc0
        st.64 k0, [r24 + TRAP_EPC_SLOT - FAIL_ADDR]
        lds.64 k0, [r24 + SENTINEL_BOX - FAIL_ADDR]
        mtsr epc0, k0
        iret

        # user-phase handler: count PERM faults and skip; SYSCALL exits
        # to the supervisor continuation
h_user:
        mfsr k0, cause0
        cmpeq p1, k0, CAUSE_SYSCALL
        (p1) b h_user_sys
        cmpeq p1, k0, CAUSE_PERM_LOAD
        (!p1) b fail
        li r26, PRIV_COUNT_SLOT
        lds.64 k0, [r26]
        add k0, k0, 1
        st.64 k0, [r26]
        mfsr k0, epc0
        add k0, k0, 8
        mtsr epc0, k0
        iret
h_user_sys:
        li k0, STATUS_MMU_ON      # supervisor, MMU stays on, TL=0
        mtsr status, k0
        b u_cont
"""


CODE_NOINVTP_REMAP = r"""
        .org 0x1000
start:
        li r24, FAIL_ADDR
        li r21, h_die             # no trap is legitimate in this image
        mtsr vbase, r21
        li r21, ROOT_PA
        mtsr ptbase, r21
        li r21, 0xA
        mtsr asid, r21
        invtp
        li r21, STATUS_MMU_ON
        mtsr status, r21
        li r25, VA_P1
        lds.64 r22, [r25]         # populate any translation cache: P1
        cmpeq p1, r22, M1
        (!p1) b fail
        li r25, VA_TABLES + NODEB_E1_ADDR - 0x20000
        li r19, PTE_REMAP_LEAF
        st128 r19, [r25]          # remap VA_P1 -> P2 ... but NO INVTP.
        li r25, VA_P1
        lds.64 r22, [r25]         # cached 0x30000 vs fresh 0x40000:
                                  # --check-invtp must CHECKFAIL here
        # Reaching this point means the check mode is absent or broken.
        # expect=checkfail makes ANY halt a harness failure; r0 = 0xbad
        # names the reason in the FAIL line.
fail:
        li r0, 0xbad
        halt
h_die:
        li r0, 0xdead             # unexpected trap
        halt
"""


CODE_NOINVTP_PTBASE = r"""
        .org 0x1000
start:
        li r24, FAIL_ADDR
        li r21, h_die             # no trap is legitimate in this image
        mtsr vbase, r21
        li r21, ROOT_PA
        mtsr ptbase, r21
        li r21, 0xA
        mtsr asid, r21
        invtp
        li r21, STATUS_MMU_ON
        mtsr status, r21
        li r25, VA_P1
        lds.64 r22, [r25]         # cache (asid A, VA_P1) -> 0x30000
        cmpeq p1, r22, M1
        (!p1) b fail
        li r21, ROOT2_PA
        mtsr ptbase, r21          # ptbase ALONE: same asid, no INVTP
        # fetches here translate result-identically under both roots
        # (ROOT2[0] == NODEB[0]: frame 0, RWX+U) — must not trip
        li r25, VA_P1
        lds.64 r22, [r25]         # cached 0x30000 vs fresh 0x100000:
                                  # --check-invtp must CHECKFAIL here
fail:
        li r0, 0xbad
        halt
h_die:
        li r0, 0xdead             # unexpected trap
        halt
"""


if __name__ == "__main__":
    main()
