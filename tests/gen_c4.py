#!/usr/bin/env python3
"""Generate tests/c4_fp.s — CONFORMANCE.md group C4, floating point.

Vector sources, all independent of any emulator:
- tests/fpvec/fpvec.dat: host-C-computed vectors (arithmetic, I->F,
  F->F; committed output of tests/fpvec/fpvec.c per toolchain-prompt).
- This file: F->I conversions in exact bigint arithmetic (RTZ + spec
  saturation/NV, ISA-SPEC 10.4 — pure integer math, no host FP);
  FMIN/FMAX 754-2019 minimum/maximum in exact logic (C's fmin/fmax
  implement the wrong 2008 semantics, see fpvec.c header); RMM and
  inexact-i128 vectors hand-derived (host cannot set RMM; libgcc's
  i128->FP path is bound to RNE).
- Handwritten epilogue: FCMP NaN semantics, sticky flags, reserved
  rounding mode trap timing, illegal-encoding traps (raw words from
  defs.s).

Bounded coverage — deliberately NOT here:
- UF tininess-edge vectors: blocked on SPEC-ISSUES 13 (before/after
  rounding unfrozen). Every UF vector is tiny under both readings.
- The non-trap side of SPEC-ISSUES 19 (FMIN/FCMP after a reserved rm
  write must NOT trap) is unasserted; asserting it would bake in the
  chosen reading twice.
- FCVT with FP-128 destination (no such format) has no raw word here;
  RAW_FCVTFF_F32F32 / RAW_FCVT_BADMOD cover the illegal-encoding trap
  path.

Deterministic given fpvec.dat; output is committed.
"""

import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import encoding as E  # noqa: E402

MASK128 = (1 << 128) - 1
GARB = 0x5AA5_C33C_0FF0_9669 << 64   # high-bits garbage for FP inputs

FLAG_BIT = {n: 1 << b for n, b in E.FCSR_FLAG_BITS.items()}
RM = dict(E.ROUNDING)
RM_LSB = E.FCSR_RM_LSB
RM_NAME = {"rne": "RNE", "rtz": "RTZ", "rdn": "RDN", "rup": "RUP",
           "rmm": "RMM"}


def canon(v, w):
    """ISA-SPEC 3.4 canonical form: sign-extend from bit w-1 to 128."""
    v &= (1 << w) - 1
    if w < 128 and v >> (w - 1):
        v |= MASK128 ^ ((1 << w) - 1)
    return v


def flags_val(s):
    if s == "-":
        return 0
    return sum(FLAG_BIT[f] for f in s.split(","))


OUT = []


def emit(line=""):
    OUT.append(line)


test_id = 0


def next_id():
    global test_id
    test_id += 1
    return test_id


def li(reg, val):
    emit(f"        li {reg}, 0x{val & MASK128:x}")


def check_eq(got_reg, want_reg):
    emit(f"        cmpeq p1, {got_reg}, {want_reg}")
    emit("        (!p1) b fail")


def vec_header(comment):
    emit()
    emit(f"        # -- {comment}")


def fp_vec(op, sfmt, dfmt, rm, a, b, c, res, flags, garble=False):
    """One generated vector: set fcsr, run op, compare canonical result
    and fcsr (rm bits + accumulated flags)."""
    tid = next_id()
    fw = {"f32": 32, "f64": 64, "i32": 32, "i64": 64, "i128": 128}
    vec_header(f"[{tid}] {op} {sfmt}->{dfmt} {rm} "
               f"a={a:#x} b={b:#x} c={c:#x} -> {res:#x} flags={flags}")
    emit(f"        li r27, {tid}")
    ga = GARB if garble and fw[sfmt] < 128 else 0
    li("r19", a | ga)
    if b or op in ("fadd", "fsub", "fmul", "fdiv", "fmin", "fmax",
                   "fmadd"):
        li("r20", b | ga)
    if op == "fmadd":
        li("r21", c)
    rmv = RM[RM_NAME[rm]] << RM_LSB
    li("r22", rmv)
    emit("        mtsr fcsr, r22")
    if op in ("fadd", "fsub", "fmul", "fdiv", "fmin", "fmax"):
        emit(f"        {op}.{dfmt} r23, r19, r20")
        want = canon(res, fw[dfmt])
    elif op == "fsqrt":
        emit(f"        fsqrt.{dfmt} r23, r19")
        want = canon(res, fw[dfmt])
    elif op == "fmadd":
        emit(f"        fmadd.{dfmt} r23, r19, r20, r21")
        want = canon(res, fw[dfmt])
    elif op in ("fcvtif", "fcvtuif"):
        emit(f"        {op}.{dfmt} r23, r19, {sfmt}")
        want = canon(res, fw[dfmt])
    elif op in ("fcvtfi", "fcvtfiu"):
        emit(f"        {op}.{fw[dfmt]} r23, r19, {sfmt}")
        want = canon(res, fw[dfmt])
    elif op == "fcvtff":
        emit(f"        fcvtff.{dfmt} r23, r19, {sfmt}")
        want = canon(res, fw[dfmt])
    else:
        raise SystemExit(f"gen_c4: unhandled op {op}")
    li("r19", want)
    check_eq("r23", "r19")
    tid2 = next_id()
    emit(f"        li r27, {tid2}          # fcsr after: rm | flags")
    emit("        mfsr r23, fcsr")
    li("r19", rmv | flags_val(flags))
    check_eq("r23", "r19")


def fp_vec_i128(op, dfmt, rm, hi, lo, res, flags):
    """i128-source conversion: build the 128-bit source from halves."""
    tid = next_id()
    vec_header(f"[{tid}] {op} i128->{dfmt} {rm} "
               f"src={hi:#x}:{lo:#x} -> {res:#x} flags={flags}")
    emit(f"        li r27, {tid}")
    li("r19", ((hi << 64) | lo) & MASK128)
    rmv = RM[RM_NAME[rm]] << RM_LSB
    li("r22", rmv)
    emit("        mtsr fcsr, r22")
    emit(f"        {op}.{dfmt} r23, r19, i128")
    want = canon(res, 32 if dfmt == "f32" else 64)
    li("r19", want)
    check_eq("r23", "r19")
    tid2 = next_id()
    emit(f"        li r27, {tid2}")
    emit("        mfsr r23, fcsr")
    li("r19", rmv | flags_val(flags))
    check_eq("r23", "r19")


# ------------------------------------------------- F->I in exact math

def f_unpack(bits, fmt):
    """Return ('nan',), ('inf', sign), or ('num', Fraction-free exact
    value as (sign, mant, exp2)) for an IEEE bit pattern."""
    if fmt == "f32":
        w, eb, mb = 32, 8, 23
    else:
        w, eb, mb = 64, 11, 52
    sign = bits >> (w - 1)
    exp = (bits >> mb) & ((1 << eb) - 1)
    mant = bits & ((1 << mb) - 1)
    bias = (1 << (eb - 1)) - 1
    if exp == (1 << eb) - 1:
        return ("nan",) if mant else ("inf", sign)
    if exp == 0:
        if mant == 0:
            return ("num", sign, 0, 0)
        return ("num", sign, mant, 1 - bias - mb)
    return ("num", sign, mant | (1 << mb), exp - bias - mb)


def fcvt_f2i(bits, sfmt, dw, signed):
    """ISA-SPEC 10.4: RTZ always; saturate + NV on out-of-range/inf/
    NaN; NX iff inexact and not NV. Returns (result, 'flags')."""
    lo = -(1 << (dw - 1)) if signed else 0
    hi = (1 << (dw - 1)) - 1 if signed else (1 << dw) - 1
    u = f_unpack(bits, sfmt)
    if u[0] == "nan":
        return hi, "NV"
    if u[0] == "inf":
        return (lo if u[1] else hi), "NV"
    _, sign, mant, e2 = u
    if e2 >= 0:
        val, inexact = mant << e2, False
    else:
        val = mant >> -e2
        inexact = (mant & ((1 << -e2) - 1)) != 0
    if sign:
        val = -val
    if val < lo:
        return lo, "NV"
    if val > hi:
        return hi, "NV"
    return val, ("NX" if inexact else "-")


def f2i_vectors():
    f32 = lambda x: struct.unpack("<I", struct.pack("<f", x))[0]  # noqa
    f64 = lambda x: struct.unpack("<Q", struct.pack("<d", x))[0]  # noqa
    cases = [
        # (op, srcfmt, srcbits, dstwidth, garble)
        ("fcvtfi", "f32", f32(3.7), 32, True),      # trunc toward zero
        ("fcvtfi", "f32", f32(-3.7), 32, False),
        ("fcvtfi", "f32", f32(2.0 ** 31), 32, False),    # sat max, NV
        ("fcvtfi", "f32", f32(-(2.0 ** 31)), 32, False),  # exactly MIN: ok
        ("fcvtfi", "f32", f32(-3e9), 32, False),         # sat min, NV
        ("fcvtfi", "f32", 0x7FC00000, 32, False),        # NaN -> max, NV
        ("fcvtfi", "f32", 0x7F800000, 64, False),        # +inf -> max, NV
        ("fcvtfi", "f32", 0xFF800000, 64, False),        # -inf -> min, NV
        ("fcvtfi", "f64", f64(3.7), 64, False),
        ("fcvtfi", "f64", f64(-0.5), 64, False),         # -> 0, NX only
        ("fcvtfi", "f64", f64(1e300), 64, False),        # sat, NV
        ("fcvtfi", "f64", f64(1.5 * 2 ** 100), 128, False),  # exact i128
        ("fcvtfi", "f64", f64(-1e300), 128, False),      # >> i128: sat, NV
        ("fcvtfi", "f64", 0x7FF8000000000000, 128, False),  # NaN, NV
        ("fcvtfiu", "f32", f32(2.0 ** 31), 32, False),   # bit31 set: canon
        ("fcvtfiu", "f32", f32(-0.5), 32, False),        # -> 0, NX
        ("fcvtfiu", "f32", f32(-1.5), 32, False),        # sat 0, NV
        ("fcvtfiu", "f64", f64(4e9), 32, True),          # fits u32
        ("fcvtfiu", "f64", f64(2.0 ** 64), 64, False),   # sat max, NV
        ("fcvtfiu", "f64", f64(float(2 ** 64 - 2 ** 12)), 64, False),
        ("fcvtfiu", "f64", f64(2.0 ** 127), 128, False),  # exact, huge
    ]
    emit()
    emit("        # ==== F->I conversions: expectations from exact")
    emit("        # bigint math in gen_c4.py (RTZ + saturation/NV per")
    emit("        # ISA-SPEC 10.4), never host casts ================")
    for op, sfmt, bits, dw, garble in cases:
        res, fl = fcvt_f2i(bits, sfmt, dw, signed=(op == "fcvtfi"))
        dfmt = f"i{dw}"
        fp_vec(op, sfmt, dfmt, "rne", bits, 0, 0, res & ((1 << dw) - 1),
               fl, garble=garble)
    # F->I ignores fcsr rounding mode (RTZ always): same input, RUP set,
    # same truncated result.
    res, fl = fcvt_f2i(f32(3.7), "f32", 32, True)
    fp_vec("fcvtfi", "f32", "i32", "rup", f32(3.7), 0, 0,
           res & 0xFFFFFFFF, fl)


# --------------------------------------- FMIN/FMAX 754-2019 in logic

def minmax_vectors():
    f32 = lambda x: struct.unpack("<I", struct.pack("<f", x))[0]  # noqa
    QNAN32, QNAN64 = 0x7FC00000, 0x7FF8000000000000
    cases = [
        # (op, fmt, a, b, result) — 754-2019 minimum/maximum:
        # NaN propagates (unlike C fmin/fmax); -0 < +0. qNaN operands
        # raise nothing.
        ("fmin", "f32", f32(1.0), f32(2.0), f32(1.0)),
        ("fmax", "f32", f32(1.0), f32(2.0), f32(2.0)),
        ("fmin", "f32", 0x00000000, 0x80000000, 0x80000000),  # min(+0,-0)=-0
        ("fmax", "f32", 0x00000000, 0x80000000, 0x00000000),  # max(+0,-0)=+0
        ("fmin", "f32", 0x80000000, 0x00000000, 0x80000000),
        ("fmin", "f32", QNAN32, f32(5.0), QNAN32),   # NaN propagates
        ("fmax", "f32", f32(5.0), QNAN32, QNAN32),
        ("fmin", "f32", QNAN32, QNAN32, QNAN32),
        ("fmin", "f64", 0x8000000000000000, 0x0000000000000000,
         0x8000000000000000),
        ("fmax", "f64", QNAN64, 0x3FF0000000000000, QNAN64),
        ("fmin", "f64", 0xFFF0000000000000, 0x0000000000000001,
         0xFFF0000000000000),                        # -inf wins
    ]
    emit()
    emit("        # ==== FMIN/FMAX: 754-2019 minimum/maximum semantics")
    emit("        # (NaN-PROPAGATING — not C fmin/fmax; -0 < +0);")
    emit("        # expectations from exact logic here ==============")
    for op, fmt, a, b, res in cases:
        fp_vec(op, fmt, fmt, "rne", a, b, 0, res, "-")


# --------------------------------- hand-derived RMM / inexact i128

def hand_vectors():
    emit()
    emit("        # ==== hand-derived vectors: RMM (no host rounding")
    emit("        # mode) and inexact i128->FP (libgcc is RNE-bound).")
    emit("        # Derivations in gen_c4.py comments ===============")
    # RMM: round to nearest, ties away from zero.
    # 1 + 2^-24 in f32 is exactly halfway between 1.0 and 1+2^-23:
    # RNE picks 1.0 (even), RMM must pick 1+2^-23 (away).
    fp_vec("fadd", "f32", "f32", "rmm", 0x3F800000, 0x33800000, 0,
           0x3F800001, "NX")
    fp_vec("fadd", "f32", "f32", "rmm", 0xBF800000, 0xB3800000, 0,
           0xBF800001, "NX")
    # Non-tie under RMM rounds to nearest: 1 + 2^-25 -> 1.0.
    fp_vec("fadd", "f32", "f32", "rmm", 0x3F800000, 0x33000000, 0,
           0x3F800000, "NX")
    # f64 tie: 1 + 2^-53 -> RMM away -> 1 + 2^-52.
    fp_vec("fadd", "f64", "f64", "rmm", 0x3FF0000000000000,
           0x3CA0000000000000, 0, 0x3FF0000000000001, "NX")
    # i128 -> f64, inexact. 2^100 + 1: f64 grid step at 2^100 is 2^48,
    # so RTZ/RDN/RNE -> 2^100 (0x4630000000000000), RUP -> next up.
    hi100 = 1 << (100 - 64)
    fp_vec_i128("fcvtif", "f64", "rtz", hi100, 1,
                0x4630000000000000, "NX")
    fp_vec_i128("fcvtif", "f64", "rup", hi100, 1,
                0x4630000000000001, "NX")
    fp_vec_i128("fcvtif", "f64", "rne", hi100, 1,
                0x4630000000000000, "NX")
    # -(2^100 + 1): RTZ -> -2^100, RDN -> -(2^100 + 2^48).
    neg = ((1 << 128) - ((1 << 100) + 1))
    fp_vec_i128("fcvtif", "f64", "rtz", neg >> 64, neg & ((1 << 64) - 1),
                0xC630000000000000, "NX")
    fp_vec_i128("fcvtif", "f64", "rdn", neg >> 64, neg & ((1 << 64) - 1),
                0xC630000000000001, "NX")


# ------------------------------------------------------------- FCMP

def fcmp_vectors():
    emit()
    emit("        # ==== FCMP: NaN compares false; NV on LT/LE with a")
    emit("        # NaN operand, never on EQ (ISA-SPEC 10.2) =========")
    QNAN32 = 0x7FC00000
    cases = [
        # (op, fmt, a, b, expect_true, flags)
        ("fcmpeq", "f32", 0x3F800000, 0x3F800000, 1, "-"),
        ("fcmpeq", "f32", 0x00000000, 0x80000000, 1, "-"),  # +0 == -0
        ("fcmplt", "f32", 0x3F800000, 0x40000000, 1, "-"),
        ("fcmplt", "f32", 0x40000000, 0x3F800000, 0, "-"),
        ("fcmple", "f32", 0x40400000, 0x40400000, 1, "-"),
        ("fcmpeq", "f32", QNAN32, 0x3F800000, 0, "-"),      # false, no NV
        ("fcmplt", "f32", QNAN32, 0x3F800000, 0, "NV"),
        ("fcmple", "f32", 0x3F800000, QNAN32, 0, "NV"),
        ("fcmplt", "f64", 0xBFF0000000000000, 0x0000000000000000, 1, "-"),
        ("fcmple", "f64", 0x7FF8000000000000, 0x7FF8000000000000, 0, "NV"),
    ]
    for op, fmt, a, b, want, fl in cases:
        tid = next_id()
        vec_header(f"[{tid}] {op}.{fmt} a={a:#x} b={b:#x} -> {want} "
                   f"flags={fl}")
        emit(f"        li r27, {tid}")
        li("r19", a)
        li("r20", b)
        emit("        mtsr fcsr, zero")
        emit(f"        {op}.{fmt} p2, r19, r20")
        if want:
            emit("        (!p2) b fail")
        else:
            emit("        (p2) b fail")
        tid2 = next_id()
        emit(f"        li r27, {tid2}")
        emit("        mfsr r23, fcsr")
        li("r19", flags_val(fl))
        check_eq("r23", "r19")


# -------------------------------------------------------- epilogue

EPILOGUE = """
        # ==== sticky flags: accumulate across ops, cleared only by
        # writing fcsr (ISA-SPEC 10.3) ============================
        li r27, 900
        mtsr fcsr, zero
        li r19, 0x3f800000
        li r20, 0
        fdiv.f32 r23, r19, r20    # DZ
        li r20, 0x40400000
        fdiv.f32 r23, r19, r20    # NX; DZ must stick
        mfsr r23, fcsr
        li r19, FCSR_DZ + FCSR_NX
        cmpeq p1, r23, r19
        (!p1) b fail
        li r27, 901               # write clears
        mtsr fcsr, zero
        mfsr r23, fcsr
        cmpeq p1, r23, 0
        (!p1) b fail

        # ==== reserved rounding mode: MTSR is permitted; the NEXT FP
        # op that rounds traps ILLEGAL (ISA-SPEC 10.3, SPEC-ISSUES 19)
        li r27, 910
        la.abs r21, h_rec
        mtsr vbase, r21
        li r19, 12345
        st.64 [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR], r19  # sentinel
        li r22, 5 * RM_UNIT       # rm=5 (reserved)
        mtsr fcsr, r22            # must NOT trap here
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, r19        # still sentinel: MTSR did not trap
        (!p1) b fail
        li r27, 911
        li r19, 0x3f800000
        li r20, 0x40000000
rm5_site:
        fadd.f32 r23, r19, r20    # first rounding op: ILLEGAL
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_ILLEGAL
        (!p1) b fail
        li r27, 912
        lds.64 r22, [r24 + TRAP_EPC_SLOT - FAIL_ADDR]
        la.abs r20, rm5_site
        cmpeq p1, r22, r20
        (!p1) b fail
        mtsr fcsr, zero           # back to RNE, flags clear
        li r27, 913               # rm=6 and rm=7 trap the same way
        li r22, 6 * RM_UNIT
        mtsr fcsr, r22
        fadd.f32 r23, r19, r19
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_ILLEGAL
        (!p1) b fail
        li r27, 914
        li r22, 7 * RM_UNIT
        mtsr fcsr, r22
        fadd.f32 r23, r19, r19
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_ILLEGAL
        (!p1) b fail
        mtsr fcsr, zero

        # ==== illegal FCVT encodings (raw words from defs.s; the
        # assembler refuses to emit these) ========================
        li r27, 920               # fcvtff f32->f32 (SPEC-ISSUES 7)
        .quad RAW_FCVTFF_F32F32
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_ILLEGAL
        (!p1) b fail
        li r27, 921               # FP width=2 reserved (ISA-SPEC 3.4)
        .quad RAW_FADD_W2
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_ILLEGAL
        (!p1) b fail
        li r27, 922               # FCVT mod junk (SPEC-ISSUES 18)
        .quad RAW_FCVT_BADMOD
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_ILLEGAL
        (!p1) b fail

pass:
        li r0, PASS_MAGIC
        halt
fail:
        st.64 [r24], r27
        mov r0, r27
        halt

        # trap handler: record cause/epc, skip the faulting instruction
h_rec:
        mfsr k0, cause0
        st.64 [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR], k0
        mfsr k0, epc0
        st.64 [r24 + TRAP_EPC_SLOT - FAIL_ADDR], k0
        mfsr k0, epc0
        add k0, k0, 8
        mtsr epc0, k0
        iret
"""


def main():
    emit("# c4_fp — GENERATED by tests/gen_c4.py — DO NOT EDIT.")
    emit("# CONFORMANCE.md group C4: floating point. Assembled after")
    emit("# tests/defs.s. Vector provenance and bounded-coverage notes")
    emit("# in gen_c4.py's docstring. Test IDs: generated vectors")
    emit("# count up from 1 (two IDs per vector: result, fcsr);")
    emit("# handwritten epilogue uses 900+.")
    emit()
    emit("        .org 0x1000")
    emit("start:")
    emit("        li r24, FAIL_ADDR")

    dat = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "fpvec", "fpvec.dat")
    emit()
    emit("        # ==== vectors from tests/fpvec/fpvec.dat (host C,")
    emit("        # IEEE hardware + libm; see fpvec.c header) =======")
    n = 0
    with open(dat) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            op, sfmt, dfmt, rm, a, b, c, res, fl = line.split()
            a, b, c, res = (int(x, 16) for x in (a, b, c, res))
            if sfmt == "i128":
                fp_vec_i128(op, dfmt, rm, a, b, res, fl)
            else:
                # garble the upper source bits on every 5th vector:
                # FP reads low 32/64 bits only (ISA-SPEC 10.1)
                fp_vec(op, sfmt, dfmt, rm, a, b, c, res, fl,
                       garble=(n % 5 == 4))
            n += 1

    f2i_vectors()
    minmax_vectors()
    hand_vectors()
    fcmp_vectors()
    OUT.append(EPILOGUE)

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "c4_fp.s")
    with open(out, "w") as f:
        f.write("\n".join(OUT) + "\n")
    print(f"wrote {out} ({test_id} vector checks + epilogue)")


if __name__ == "__main__":
    main()
