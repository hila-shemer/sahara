#!/usr/bin/env python3
"""Generate tests/c3_atomics.s — CONFORMANCE.md group C3, atomics.

Expected values computed here from ISA-SPEC 5.4 with Python bigints —
never an emulator. Deterministic; output is committed.

Coverage (C3 outline):
- CAS success and failure at each width; old-value canonicalization;
  garbage above width w in expected/new is ignored at width w; a
  width-w CAS/AMO writes only the low w bits of the location (verified
  by ld128 readback of the full 16-byte box)
- every AMO at every width; signed vs unsigned min/max boundary values
- ABA-freedom demonstrator: 64+64 fat-pointer CAS (documentation test)

Bounded coverage — deliberately NOT here (tests/README.md rule: no
silent gaps), all owned elsewhere in the suite:
- atomicity under interrupts and AMO/CAS-to-device-space DEVERR:
  tests/c3_irq_dev.s (+ checks/c3_irq_dev.py trace assertions)
- atomic permission-fault ordering (load-before-store): c2_mmu
  tests [27]/[28]
- atomic UNALIGNED traps: C7's alignment sweep (gen_c7.py)
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import encoding as E  # noqa: E402, F401  (encoding-as-data availability)

MASK128 = (1 << 128) - 1
GARB = 0x5AA5_C33C_0FF0_9669_1234_ABCD_EF55_AA11


def mask(w):
    return (1 << w) - 1


def sgn(v, w):
    v &= mask(w)
    return v - (1 << w) if v >> (w - 1) else v


def canon(v, w):
    v &= mask(w)
    if w < 128 and v >> (w - 1):
        v |= MASK128 ^ mask(w)
    return v


def garb(x, w):
    if w == 128:
        return x & MASK128
    return (x & mask(w)) | ((GARB << w) & MASK128 & ~mask(w))


def merge(old128, new_low, w):
    """A width-w atomic write replaces only the low w bits of the
    16-byte location (it is a w-bit store)."""
    return (old128 & ~mask(w)) | (new_low & mask(w)) if w < 128 \
        else new_low & MASK128


def ref_amo(op, w, old128, b128):
    """Returns (dst_value, new_memory_low_w)."""
    old, b = old128 & mask(w), b128 & mask(w)
    olds, bs = sgn(old, w), sgn(b, w)
    if op == "amoadd":
        new = old + b
    elif op == "amoand":
        new = old & b
    elif op == "amoor":
        new = old | b
    elif op == "amoxor":
        new = old ^ b
    elif op == "amoswap":
        new = b
    elif op == "amomin":
        new = olds if olds <= bs else bs
    elif op == "amomax":
        new = olds if olds >= bs else bs
    elif op == "amominu":
        new = old if old <= b else b
    elif op == "amomaxu":
        new = old if old >= b else b
    else:
        raise AssertionError(op)
    return canon(old, w), new & mask(w)


def ref_cas(w, old128, exp128, new128):
    """Returns (dst_value, new_memory_low_w, succeeded)."""
    old, exp, new = old128 & mask(w), exp128 & mask(w), new128 & mask(w)
    if old == exp:
        return canon(old, w), new, True
    return canon(old, w), old, False


# self-checks
assert ref_amo("amomin", 32, 1 << 31, 0) == (canon(1 << 31, 32), 1 << 31)
assert ref_amo("amominu", 32, 1 << 31, 0) == (canon(1 << 31, 32), 0)
assert ref_amo("amomax", 64, mask(64), 1) == (MASK128, 1)
assert ref_amo("amomaxu", 64, mask(64), 1) == (MASK128, mask(64))
assert ref_cas(32, 5, garb(5, 32), garb(9, 32)) == (5, 9, True)
assert ref_cas(32, canon(-1, 32), 1, 9)[2] is False
assert merge(0xAABBCCDD_11223344_55667788_99AA0000, 0x9, 32) \
    == 0xAABBCCDD_11223344_55667788_00000009

OUT = []
TESTID = [0]


def emit(line=""):
    OUT.append(line)


def hexv(v):
    return f"0x{v & MASK128:x}"


def begin(comment):
    TESTID[0] += 1
    emit(f"        # test {TESTID[0]}: {comment}")
    emit(f"        li r27, {TESTID[0]}")


def sfx(w):
    return "" if w == 128 else f".{w}"


def check_box_and_dst(old128, dst_expect, newmem_low, w):
    """r19 = atomic dst; box readback compared against merged value."""
    emit(f"        li r20, {hexv(dst_expect)}")
    emit("        cmpeq p1, r19, r20")
    emit("        (!p1) b fail")
    emit("        ld128 r18, [r21]")
    emit(f"        li r20, {hexv(merge(old128, newmem_low, w))}")
    emit("        cmpeq p1, r18, r20")
    emit("        (!p1) b fail")
    emit()


AMO_OPS = ["amoadd", "amoand", "amoor", "amoxor", "amoswap",
           "amomin", "amomax", "amominu", "amomaxu"]
WIDTHS = [32, 64, 128]

OLD_PATTERN = 0xAABB_CCDD_1122_3344_5566_7788_99AA_F001  # box background


def amo_vectors(op, w):
    minw, maxs = 1 << (w - 1), (1 << (w - 1)) - 1
    v = [
        (garb(minw, w), MASK128),            # MIN vs -1
        (garb(maxs, w), garb(minw, w)),      # MAX vs MIN
        (garb(0x0F0F_A5A5, w), garb(0x1111_0FF0, w)),
    ]
    if op in ("amomin", "amomax", "amominu", "amomaxu"):
        v.append((0, MASK128))               # 0 vs -1/UMAX: sign heart
        v.append((garb(minw, w), 0))
    return v


def gen_amo():
    emit("        # ---- C3.1 every AMO, every width, boundaries ----")
    for op in AMO_OPS:
        for w in WIDTHS:
            for old_low, b in amo_vectors(op, w):
                old128 = merge(OLD_PATTERN, old_low, w)
                dst, newmem = ref_amo(op, w, old128, b)
                begin(f"{op}{sfx(w)} old={hexv(old128)} b={hexv(b)}")
                emit("        li r21, ATOMIC_BOX")
                emit(f"        li r22, {hexv(old128)}")
                emit("        st128 [r21], r22")
                emit(f"        li r23, {hexv(b)}")
                emit(f"        {op}{sfx(w)} r19, [r21], r23")
                check_box_and_dst(old128, dst, newmem, w)


def gen_cas():
    emit("        # ---- C3.2 CAS success/failure, canonicalization ----")
    for w in WIDTHS:
        minw = 1 << (w - 1)
        cases = [
            # (old_low, exp, new, label)
            (5, garb(5, w), garb(9, w),
             "success; garbage above w in exp/new ignored"),
            (5, garb(6, w), garb(9, w), "failure: exp differs"),
            (minw, garb(minw, w), 0,
             "success on negative-pattern old; dst canonicalized"),
            (mask(w), MASK128, garb(1, w), "success: all-ones old"),
            (0, MASK128 ^ mask(w), garb(7, w),
             "success: exp garbage-only above w, low bits equal (0)"),
        ]
        for old_low, exp, new, why in cases:
            old128 = merge(OLD_PATTERN, old_low, w)
            dst, newmem, _ok = ref_cas(w, old128, exp, new)
            begin(f"cas{sfx(w)} {why}")
            emit("        li r21, ATOMIC_BOX")
            emit(f"        li r22, {hexv(old128)}")
            emit("        st128 [r21], r22")
            emit(f"        li r25, {hexv(exp)}")
            emit(f"        li r26, {hexv(new)}")
            emit(f"        cas{sfx(w)} r19, [r21], r25, r26")
            check_box_and_dst(old128, dst, newmem, w)
    # displacement form ea = src1 + imm
    old128 = merge(OLD_PATTERN, 0x42, 64)
    dst, newmem, _ = ref_cas(64, old128, 0x42, 0x77)
    begin("cas.64 with [base + imm] addressing")
    emit("        li r21, ATOMIC_BOX - 0x20")
    emit(f"        li r22, {hexv(old128)}")
    emit("        st128 [r21 + 0x20], r22")
    emit(f"        li r25, {hexv(0x42)}")
    emit(f"        li r26, {hexv(0x77)}")
    emit("        cas.64 r19, [r21 + 0x20], r25, r26")
    emit(f"        li r20, {hexv(dst)}")
    emit("        cmpeq p1, r19, r20")
    emit("        (!p1) b fail")
    emit("        li r21, ATOMIC_BOX")
    emit("        ld128 r18, [r21]")
    emit(f"        li r20, {hexv(merge(old128, newmem, 64))}")
    emit("        cmpeq p1, r18, r20")
    emit("        (!p1) b fail")
    emit()


def gen_aba():
    emit("        # ---- C3.3 ABA-freedom demonstrator (docs test) ----")
    emit("        # 64+64 software fat pointer: low 64 = pointer, high")
    emit("        # 64 = generation counter, swapped as one 128-bit CAS.")
    emit("        # The pointer alone returning to a seen value does not")
    emit("        # let a stale CAS win: the generation moved.")
    ptr_a, ptr_b = 0x2000, 0x3000
    fat = lambda p, g: (g << 64) | p  # noqa: E731
    v1 = fat(ptr_a, 1)
    v2 = fat(ptr_b, 2)
    v3 = fat(ptr_a, 3)   # pointer is back to A, generation is not 1
    begin("fat-pointer CAS: fresh swap succeeds")
    emit("        li r21, ATOMIC_BOX")
    emit(f"        li r22, {hexv(v1)}")
    emit("        st128 [r21], r22")
    emit(f"        li r25, {hexv(v1)}")
    emit(f"        li r26, {hexv(v2)}")
    emit("        cas r19, [r21], r25, r26")
    check_box_and_dst(v1, v1, v2, 128)
    begin("fat-pointer CAS: stale (A,1) loses against (A,3)")
    emit(f"        li r22, {hexv(v3)}")
    emit("        st128 [r21], r22")
    emit(f"        li r25, {hexv(v1)}    # stale snapshot")
    emit(f"        li r26, {hexv(fat(ptr_b, 4))}")
    emit("        cas r19, [r21], r25, r26")
    check_box_and_dst(v3, v3, v3, 128)


def generate():
    emit("# c3_atomics.s — C3 atomics (CONFORMANCE.md)")
    emit("# GENERATED by tests/gen_c3.py — DO NOT EDIT; edit the")
    emit("# generator and rerun (deterministic; output is committed).")
    emit("# Bounded coverage: interrupt-atomicity and device DEVERR live")
    emit("# in c3_irq_dev.s; permission order in c2_mmu; atomic UNALIGNED")
    emit("# in the C7 sweep. Conventions per tests/README.md.")
    emit()
    emit("        .org 0x1000")
    emit("start:")
    emit("        li r24, FAIL_ADDR")
    emit()
    gen_amo()
    gen_cas()
    gen_aba()
    emit("pass:")
    emit("        li r0, PASS_MAGIC")
    emit("        halt")
    emit("fail:")
    emit("        st.64 [r24], r27")
    emit("        mov r0, r27")
    emit("        halt")
    return "\n".join(OUT) + "\n"


def main():
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "c3_atomics.s")
    text = generate()
    with open(out_path, "w") as f:
        f.write(text)
    print(f"wrote {out_path}: {TESTID[0]} tests, "
          f"{len(text.splitlines())} lines")


if __name__ == "__main__":
    main()
