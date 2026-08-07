#!/usr/bin/env python3
"""Generate tests/c5_base.s — CONFORMANCE.md group C5, base integer
semantics.

Expected values are computed HERE, from the ISA-SPEC formulas, with
Python bigints — an independent calculation, never an emulator run
(toolchain-prompt, "Validating without an emulator"). encoding.py is
imported only to build the two raw `.quad` instruction words (the cases
an assembler cannot express: mod garbage under I=1, compare dst high
bits) — encoding-as-data, no semantics.

Deterministic: rerunning must reproduce tests/c5_base.s byte-identically.

Coverage (C5 outline):
- every W-form ALU op at 32/64/128, register and immediate forms,
  canonical-form (sign-extended) results including unsigned ops with
  high garbage in inputs
- division by zero, MIN/-1, at each width
- MULH/MULHU at each width including 128x128->256 high half
- mod field: shl/sxt/zxt amount classes, amount 0, mod ignored when I=1
- shifts: counts mod w; SHL vs mod-shl equivalence for counts <= 63
- immediates: 22-bit sext boundaries; li/SHORI chain vs .oct data;
  LDI/SHORI/LAP directly
- r31 discard/zero; p0 immutable via PWR and via CMP dst=0 (raw word)
- all five compares, signed/unsigned boundaries, at each width
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import encoding as E  # noqa: E402

MASK128 = (1 << 128) - 1
GARB = 0xA5C3_5A3C_96F0_0F69_DEAD_BEEF_CAFE_F00D  # high-bit garbage seed


def mask(w):
    return (1 << w) - 1


def sgn(v, w):
    v &= mask(w)
    return v - (1 << w) if v >> (w - 1) else v


def canon(v, w):
    """ISA-SPEC 3.4: sign-extend from bit w-1 to 128, unsigned ops too."""
    v &= mask(w)
    if w < 128 and v >> (w - 1):
        v |= MASK128 ^ mask(w)
    return v


def garb(x, w):
    """Value x at width w with deterministic garbage in bits 127:w."""
    if w == 128:
        return x & MASK128
    return (x & mask(w)) | ((GARB << w) & MASK128 & ~mask(w))


def trunc_div(a, b):
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q


def ref_alu(op, w, a128, b128, c128=0):
    """ISA-SPEC 5.1 semantics; a/b/c are full 128-bit register values."""
    au, bu, cu = a128 & mask(w), b128 & mask(w), c128 & mask(w)
    as_, bs = sgn(au, w), sgn(bu, w)
    if op == "add":
        r = au + bu
    elif op == "sub":
        r = au - bu
    elif op == "and":
        r = au & bu
    elif op == "or":
        r = au | bu
    elif op == "xor":
        r = au ^ bu
    elif op == "shl":
        r = au << (bu % w)
    elif op == "shr":
        r = au >> (bu % w)
    elif op == "sar":
        r = as_ >> (bu % w)
    elif op == "mul":
        r = au * bu
    elif op == "mulh":
        r = (as_ * bs) >> w
    elif op == "mulhu":
        r = (au * bu) >> w
    elif op == "madd":
        r = au * bu + cu
    elif op == "udiv":
        r = mask(w) if bu == 0 else au // bu
    elif op == "sdiv":
        if bs == 0:
            r = -1                       # all ones at width w
        elif as_ == -(1 << (w - 1)) and bs == -1:
            r = as_                      # overflow: quotient = MIN_w
        else:
            r = trunc_div(as_, bs)
    elif op == "urem":
        r = au if bu == 0 else au % bu
    elif op == "srem":
        if bs == 0:
            r = as_                      # remainder = dividend
        elif as_ == -(1 << (w - 1)) and bs == -1:
            r = 0
        else:
            r = as_ - trunc_div(as_, bs) * bs
    else:
        raise AssertionError(op)
    return canon(r, w)


def ref_cmp(op, w, a128, b128):
    au, bu = a128 & mask(w), b128 & mask(w)
    as_, bs = sgn(au, w), sgn(bu, w)
    return int({"cmpeq": au == bu, "cmplt": as_ < bs, "cmpltu": au < bu,
                "cmple": as_ <= bs, "cmpleu": au <= bu}[op])


def ref_mod(kind, amount, v):
    """ISA-SPEC 3.3: applied to the full 128-bit src2 value, before use."""
    v &= MASK128
    if kind == "shl":
        return (v << amount) & MASK128
    if amount == 0:
        return v
    low = v & mask(amount)
    if kind == "zxt":
        return low
    if kind == "sxt":
        if low >> (amount - 1):
            low |= MASK128 ^ mask(amount)
        return low
    raise AssertionError(kind)


def build_word(**fields):
    w = 0
    for name, val in fields.items():
        lsb, width = E.FIELDS[name]
        assert 0 <= val < (1 << width), (name, val)
        w |= val << lsb
    return w


# ---- reference self-checks (fail the generator, not the suite) ----------
assert ref_alu("sdiv", 32, 1 << 31, MASK128) == canon(1 << 31, 32)
assert ref_alu("sdiv", 32, 5, 0) == MASK128
assert ref_alu("srem", 64, garb(7, 64), 0) == 7
assert ref_alu("udiv", 32, garb(100, 32), garb(7, 32)) == 14
assert ref_alu("add", 32, mask(32), 1) == 0
assert ref_alu("shr", 32, garb(1 << 31, 32), 31) == 1
assert ref_alu("mulhu", 32, mask(32), mask(32)) == canon(0xFFFFFFFE, 32)
assert ref_cmp("cmplt", 32, 1 << 31, 0) == 1
assert ref_cmp("cmpltu", 32, 1 << 31, 0) == 0
assert ref_mod("sxt", 3, 5) == MASK128 - 2   # 0b101 sxt 3 = -3

# -------------------------------------------------------------- emission

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
    return TESTID[0]


def check_r19(expected):
    emit(f"        li r20, {hexv(expected)}")
    emit("        cmpeq p1, r19, r20")
    emit("        (!p1) b fail")
    emit()


IMM_MIN, IMM_MAX = -(1 << 21), (1 << 21) - 1

ALU_OPS = ["add", "sub", "and", "or", "xor", "shl", "shr", "sar", "mul",
           "mulh", "mulhu", "madd", "udiv", "sdiv", "urem", "srem"]
CMP_OPS = ["cmpeq", "cmplt", "cmpltu", "cmple", "cmpleu"]
WIDTHS = [32, 64, 128]


def sfx(w):
    return "" if w == 128 else f".{w}"


def vectors(op, w):
    minw, maxs = 1 << (w - 1), (1 << (w - 1)) - 1
    base = [
        (0, 0),
        (1, MASK128),                       # 1, -1 canonical
        (garb(maxs, w), garb(1, w)),        # MAX with high garbage
        (garb(minw, w), MASK128),           # MIN, -1 (div overflow case)
        (garb(0x1234_5678_9ABC_DEF0, w), garb(0x0F0F_1111, w)),
    ]
    if op in ("udiv", "sdiv", "urem", "srem"):
        base.append((garb(0xDEAD_BEEF, w), 0))          # divide by zero
        base.append((garb(100, w), garb(7, w)))
    if op in ("shl", "shr", "sar"):
        # counts: 0, 1, w-1, w (mod->0), w+3, 130 — via full-width b
        base = [(garb(0x8000_0000_F0F0_A5A5_00FF_00FF_1234_8001, w), c)
                for c in (0, 1, w - 1, w, w + 3, 130)]
    if op in ("mulh", "mulhu"):
        base.append((garb(minw, w), garb(minw, w)))
        base.append((MASK128, MASK128))
        if w == 128:
            base.append((0x0123_4567_89AB_CDEF_FEDC_BA98_7654_3210,
                         0xF0E1_D2C3_B495_A687_7869_5A4B_3C2D_1E0F))
    return base


def gen_alu():
    emit("        # ---- C5.1 ALU ops, all widths, register form ----")
    for op in ALU_OPS:
        for w in WIDTHS:
            for a, b in vectors(op, w):
                if op == "madd":
                    c = garb(0x1111_2222_3333_4444, w)
                    begin(f"{op}{sfx(w)} a={hexv(a)} b={hexv(b)} "
                          f"c={hexv(c)}")
                    emit(f"        li r21, {hexv(a)}")
                    emit(f"        li r22, {hexv(b)}")
                    emit(f"        li r23, {hexv(c)}")
                    emit(f"        madd{sfx(w)} r19, r21, r22, r23")
                    check_r19(ref_alu(op, w, a, b, c))
                else:
                    begin(f"{op}{sfx(w)} a={hexv(a)} b={hexv(b)}")
                    emit(f"        li r21, {hexv(a)}")
                    emit(f"        li r22, {hexv(b)}")
                    emit(f"        {op}{sfx(w)} r19, r21, r22")
                    check_r19(ref_alu(op, w, a, b))


def gen_alu_imm():
    emit("        # ---- C5.2 ALU immediate forms (I-flag, sext22) ----")
    for op in ALU_OPS:
        if op == "madd":
            continue
        for w in WIDTHS:
            for imm in (-5, 100, IMM_MIN, IMM_MAX):
                a = garb(0x2468_ACE0_1357_9BDF, w)
                b128 = imm & MASK128
                begin(f"{op}{sfx(w)} a={hexv(a)} imm={imm}")
                emit(f"        li r21, {hexv(a)}")
                emit(f"        {op}{sfx(w)} r19, r21, {imm}")
                check_r19(ref_alu(op, w, a, b128))
    # madd immediate form
    for w in WIDTHS:
        a, c = garb(7, w), garb(0x99, w)
        begin(f"madd{sfx(w)} imm form")
        emit(f"        li r21, {hexv(a)}")
        emit(f"        li r23, {hexv(c)}")
        emit(f"        madd{sfx(w)} r19, r21, -3, r23")
        check_r19(ref_alu("madd", w, a, (-3) & MASK128, c))


def gen_mod():
    emit("        # ---- C5.3 mod field: shl/sxt/zxt amount classes ----")
    val = 0x8765_4321_0FED_CBA9_A5A5_5A5A_00FF_8001
    for kind in ("shl", "sxt", "zxt"):
        amounts = [1, 5, 21, 63] if kind == "shl" else [0, 1, 5, 21, 63]
        for amt in amounts:
            for w in (32, 128):
                bmod = ref_mod(kind, amt, val)
                begin(f"add{sfx(w)} b = r22 {kind} {amt}")
                emit(f"        li r21, {hexv(3)}")
                emit(f"        li r22, {hexv(val)}")
                emit(f"        add{sfx(w)} r19, r21, r22 {kind} {amt}")
                check_r19(ref_alu("add", w, 3, bmod))
    # shl 0 is encodable (kind=shl amount=0) and is a no-op
    begin("add b = r22 shl 0")
    emit(f"        li r21, 1")
    emit(f"        li r22, {hexv(val)}")
    emit("        add r19, r21, r22 shl 0")
    check_r19(ref_alu("add", 128, 1, val))
    # SHL instruction vs mod-shl equivalence for counts <= 63
    emit("        # SHL instruction == mod-shl for counts <= 63")
    for amt in (0, 7, 63):
        begin(f"shl vs mod-shl, count {amt}")
        emit(f"        li r21, {hexv(val)}")
        emit(f"        add r19, zero, r21 shl {amt}")
        emit(f"        li r22, {amt}")
        emit("        shl r18, r21, r22")
        emit("        cmpeq p1, r19, r18")
        emit("        (!p1) b fail")
        check_r19(ref_mod("shl", amt, val))


def gen_raw_words():
    emit("        # ---- C5.4 hand-built words (assembler can't emit) --")
    # (a) I=1 with garbage in mod: mod must be ignored (ISA-SPEC 3.1).
    w32 = E.FAMILIES["ALU"]["widths"].index(32)
    a = garb(0x1000_0001, 32)
    word = build_word(opcode=E.OPCODES["ADD"][0] + 1, dst=19, src1=21,
                      mod=0xFF, width=w32, imm=7)
    begin("add.32 I-form with mod=0xff: mod ignored when I=1")
    emit(f"        li r21, {hexv(a)}")
    emit(f"        .quad {hexv(word)}   # add.32 r19, r21, 7 + mod junk")
    check_r19(ref_alu("add", 32, a, 7))
    # (b) compare dst high bits ignored: dst = 0b01001 -> writes p1.
    w128 = E.FAMILIES["CMP"]["widths"].index(128)
    word = build_word(opcode=E.OPCODES["CMPEQ"][0], dst=0b01001, src1=21,
                      src2=21, width=w128)
    begin("cmpeq with dst=0b01001: only low 3 bits select the predicate")
    emit(f"        li r21, 5")
    emit("        li r19, 0")
    emit(f"        .quad {hexv(word)}   # cmpeq p(dst=9->1), r21, r21")
    emit("        (p1) add r19, zero, 1")
    check_r19(1)


def gen_imm_edges():
    emit("        # ---- C5.5 immediates: LDI/SHORI/LAP, chains ----")
    begin("ldi sext boundary -2^21")
    emit(f"        ldi r19, {IMM_MIN}")
    check_r19(IMM_MIN & MASK128)
    begin("ldi sext boundary 2^21-1")
    emit(f"        ldi r19, {IMM_MAX}")
    check_r19(IMM_MAX)
    begin("shori zext: (r << 22) | imm")
    emit("        ldi r19, -1")
    emit("        shori r19, r19, 0")
    check_r19(MASK128 ^ mask(22))
    # li chain vs .oct data path: same constant through both routes
    big = 0x0123_4567_89AB_CDEF_FEDC_BA98_7654_3210
    begin("li 6-word chain == ld128 of .oct")
    emit(f"        li r19, {hexv(big)}")
    emit("        la r21, oct_big")
    emit("        ld128 r22, [r21]")
    emit("        cmpeq p1, r19, r22")
    emit("        (!p1) b fail")
    check_r19(big)
    begin("negative li == .oct two's complement")
    emit(f"        li r19, -2")
    emit("        la r21, oct_minus2")
    emit("        ld128 r22, [r21]")
    emit("        cmpeq p1, r19, r22")
    emit("        (!p1) b fail")
    check_r19((-2) & MASK128)
    # LAP: la (LAP-based, backward label) == absolute address via li
    begin("lap: pc-relative address == absolute")
    emit("        la r19, start")
    emit("        li r20, start")
    emit("        cmpeq p1, r19, r20")
    emit("        (!p1) b fail")
    emit()


def gen_zero_regs():
    emit("        # ---- C5.6 r31 hardwired zero, p0 immutable ----")
    begin("write to r31 discarded, reads as zero")
    emit("        li r21, 123")
    emit("        add zero, r21, r21")
    emit("        or r19, zero, zero")
    check_r19(0)
    begin("ldi to r31 discarded")
    emit("        ldi zero, -1")
    emit("        add r19, zero, 0")
    check_r19(0)
    begin("jal link to r31 discarded, still branches")
    emit("        jal zero, jalzero_target")
    emit("        b fail                    # skipped by the jump")
    emit("jalzero_target:")
    emit("        or r19, zero, zero")
    check_r19(0)
    begin("p0 immutable via CMP dst=0: write of 0 discarded")
    emit("        li r21, 1")
    emit("        li r22, 2")
    emit("        cmpeq p0, r21, r22        # false: tries to clear p0")
    emit("        li r19, 0")
    emit("        (p0) add r19, zero, 1     # p0 must still read 1")
    check_r19(1)
    begin("p0 immutable via PWR bit 0 = 0; PRD round-trip")
    emit("        li r21, 0xaa              # bit0 clear, p1/p3/p5/p7 set")
    emit("        pwr r21")
    emit("        prd r19")
    check_r19(0xAB)                          # bit0 forced 1
    begin("restore predicate file to reset state for later groups")
    emit("        li r21, 1")
    emit("        pwr r21                   # p1-p7 = 0")
    emit("        prd r19")
    check_r19(1)


def gen_cmp():
    emit("        # ---- C5.7 compares: signed/unsigned boundaries ----")
    for op in CMP_OPS:
        for w in WIDTHS:
            minw, maxs = 1 << (w - 1), (1 << (w - 1)) - 1
            cases = [(0, 0), (1, 2), (2, 1),
                     (garb(minw, w), 0),          # signed min vs 0
                     (0, garb(minw, w)),
                     (garb(maxs, w), garb(minw, w)),
                     (MASK128, 0), (0, MASK128)]  # -1 vs 0 both ways
            for a, b in cases:
                exp = ref_cmp(op, w, a, b)
                begin(f"{op}{sfx(w)} a={hexv(a)} b={hexv(b)} -> {exp}")
                emit(f"        li r21, {hexv(a)}")
                emit(f"        li r22, {hexv(b)}")
                emit(f"        {op}{sfx(w)} p1, r21, r22")
                emit("        li r19, 0")
                emit("        (p1) add r19, zero, 1")
                check_r19(exp)
    # immediate form of compare
    for w in WIDTHS:
        a = garb(0x50, w)
        begin(f"cmplt{sfx(w)} immediate form")
        emit(f"        li r21, {hexv(a)}")
        emit(f"        cmplt{sfx(w)} p1, r21, -1")
        emit("        li r19, 0")
        emit("        (p1) add r19, zero, 1")
        check_r19(ref_cmp("cmplt", w, a, MASK128))


def generate():
    emit("# c5_base.s — C5 base integer semantics (CONFORMANCE.md)")
    emit("# GENERATED by tests/gen_c5.py — DO NOT EDIT; edit the")
    emit("# generator and rerun (deterministic; output is committed).")
    emit("# Expected values computed in the generator from ISA-SPEC")
    emit("# formulas with Python bigints, independent of any emulator.")
    emit("# Conventions per tests/README.md.")
    emit()
    emit("        .org 0x1000")
    emit("start:")
    emit("        li r24, 0x700")
    emit()
    gen_alu()
    gen_alu_imm()
    gen_mod()
    gen_raw_words()
    gen_imm_edges()
    gen_zero_regs()
    gen_cmp()
    emit("pass:")
    emit("        li r0, 0x600D")
    emit("        halt")
    emit("fail:")
    emit("        st.64 r27, [r24]")
    emit("        mov r0, r27")
    emit("        halt")
    emit()
    emit("        .align 16")
    emit("oct_big:")
    emit("        .oct 0x0123456789abcdeffedcba9876543210")
    emit("oct_minus2:")
    emit("        .oct -2")
    return "\n".join(OUT) + "\n"


def main():
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "c5_base.s")
    text = generate()
    with open(out_path, "w") as f:
        f.write(text)
    n = TESTID[0]
    print(f"wrote {out_path}: {n} tests, {len(text.splitlines())} lines")


if __name__ == "__main__":
    main()
