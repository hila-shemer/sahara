"""C4-shaped smoke tests: softfloat against the host FPU (f64/RNE),
targeted rounding/flag/saturation cases, machine-level FP execution."""

import math
import random
import struct

import encoding as E
import softfloat as sf
from helpers import (HANDLER_PA, MASK128, asm, cause_handler, halt, ldi,
                     li128, mfsr, mtsr, run_words, vbase_setup, wbytes)

RNE = E.ROUNDING["RNE"]
RTZ = E.ROUNDING["RTZ"]
RDN = E.ROUNDING["RDN"]
RUP = E.ROUNDING["RUP"]
RMM = E.ROUNDING["RMM"]


def d2b(x):
    return struct.unpack("<Q", struct.pack("<d", x))[0]


def b2d(b):
    return struct.unpack("<d", struct.pack("<Q", b))[0]


def f2b(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


def canon(v, w):
    v &= (1 << w) - 1
    if w < 128 and v & (1 << (w - 1)):
        v |= MASK128 ^ ((1 << w) - 1)
    return v


# ------------------------------------------------- host FPU crosscheck
def test_f64_ops_vs_host():
    """The host's doubles are IEEE binary64 with RNE: an independent
    implementation to diff against for add/sub/mul/div/sqrt/fma."""
    rng = random.Random(1234)
    checked = 0
    for _ in range(1500):
        ab, bb = rng.getrandbits(64), rng.getrandbits(64)
        a, b = b2d(ab), b2d(bb)
        cases = [("add", sf.fadd(sf.F64, ab, bb, RNE))]
        cases.append(("sub", sf.fsub(sf.F64, ab, bb, RNE)))
        cases.append(("mul", sf.fmul(sf.F64, ab, bb, RNE)))
        if b != 0:
            cases.append(("div", sf.fdiv(sf.F64, ab, bb, RNE)))
        for name, (got, _fl) in cases:
            try:
                want = {"add": a + b, "sub": a - b, "mul": a * b,
                        "div": (a / b) if b != 0 else 0.0}[name]
            except OverflowError:
                continue
            if math.isnan(want) or math.isnan(b2d(got)):
                assert math.isnan(want) and math.isnan(b2d(got)), name
            else:
                assert got == d2b(want), (name, a, b)
            checked += 1
    assert checked > 4000


def test_f64_sqrt_vs_host():
    rng = random.Random(99)
    for _ in range(500):
        ab = rng.getrandbits(63)              # non-negative patterns
        a = b2d(ab)
        if math.isnan(a):
            continue
        got, _fl = sf.fsqrt(sf.F64, ab, RNE)
        assert got == d2b(math.sqrt(a)), a


def test_f64_fma_vs_host():
    rng = random.Random(7)
    for _ in range(500):
        ab, bb, cb = (rng.getrandbits(64) for _ in range(3))
        a, b, c = b2d(ab), b2d(bb), b2d(cb)
        got, _fl = sf.fmadd(sf.F64, ab, bb, cb, RNE)
        try:
            want = math.fma(a, b, c)
        except ValueError:                    # host raises on inf*0+nan etc.
            continue
        except OverflowError:
            continue
        if math.isnan(want) or math.isnan(b2d(got)):
            assert math.isnan(want) and math.isnan(b2d(got))
        else:
            assert got == d2b(want), (a, b, c)


# ------------------------------------------------------ targeted cases
def test_rounding_mode_relations():
    third = sf.fdiv(sf.F64, d2b(1.0), d2b(3.0), RNE)[0]
    rtz = sf.fdiv(sf.F64, d2b(1.0), d2b(3.0), RTZ)[0]
    rdn = sf.fdiv(sf.F64, d2b(1.0), d2b(3.0), RDN)[0]
    rup = sf.fdiv(sf.F64, d2b(1.0), d2b(3.0), RUP)[0]
    assert rtz == rdn                         # positive value
    assert rup == rtz + 1                     # adjacent ulps
    assert third in (rtz, rup)
    # negative: RDN rounds away from zero
    nrtz = sf.fdiv(sf.F64, d2b(-1.0), d2b(3.0), RTZ)[0]
    nrdn = sf.fdiv(sf.F64, d2b(-1.0), d2b(3.0), RDN)[0]
    nrup = sf.fdiv(sf.F64, d2b(-1.0), d2b(3.0), RUP)[0]
    assert nrup == nrtz
    assert nrdn == nrtz + 1


def test_f32_rne_tie_and_rup():
    big = f2b(16777216.0)                     # 2^24
    one = f2b(1.0)
    assert sf.fadd(sf.F32, big, one, RNE)[0] == big          # tie to even
    assert sf.fadd(sf.F32, big, one, RUP)[0] == f2b(16777218.0)
    assert sf.fadd(sf.F32, big, one, RNE)[1] & sf.NX


def test_fmadd_single_rounding():
    a = d2b(1.0 + 2.0 ** -52)
    c = d2b(-(1.0 + 2.0 ** -51))
    fused, _ = sf.fmadd(sf.F64, a, a, c, RNE)
    # a*a + c == 2^-104 exactly; mul-then-add loses it entirely
    assert b2d(fused) == 2.0 ** -104
    mul, _ = sf.fmul(sf.F64, a, a, RNE)
    then_add, _ = sf.fadd(sf.F64, mul, c, RNE)
    assert b2d(then_add) == 0.0


def test_nan_canonical_and_signaling():
    snan = 0x7FF0000000000001
    got, fl = sf.fadd(sf.F64, snan, d2b(1.0), RNE)
    assert got == sf.F64.qnan
    assert fl & sf.NV
    qnan = 0x7FF8000000000123                 # payload must not propagate
    got, fl = sf.fadd(sf.F64, qnan, d2b(1.0), RNE)
    assert got == sf.F64.qnan
    assert fl == 0


def test_fmin_fmax_2019_semantics():
    nz, pz = d2b(-0.0), d2b(0.0)
    assert sf.fminmax(sf.F64, nz, pz, want_max=False)[0] == nz
    assert sf.fminmax(sf.F64, pz, nz, want_max=False)[0] == nz
    assert sf.fminmax(sf.F64, nz, pz, want_max=True)[0] == pz
    # NaN propagates (754-2019 minimum, not minNum)
    got, fl = sf.fminmax(sf.F64, sf.F64.qnan, d2b(1.0), want_max=False)
    assert got == sf.F64.qnan and fl == 0
    got, fl = sf.fminmax(sf.F64, 0x7FF0000000000001, d2b(1.0),
                         want_max=False)
    assert got == sf.F64.qnan and fl & sf.NV


def test_fcmp_nan_semantics():
    qnan = sf.F64.qnan
    assert sf.fcmp(sf.F64, "eq", qnan, qnan) == (False, 0)
    assert sf.fcmp(sf.F64, "lt", qnan, d2b(1.0)) == (False, sf.NV)
    assert sf.fcmp(sf.F64, "le", d2b(1.0), qnan) == (False, sf.NV)
    assert sf.fcmp(sf.F64, "eq", d2b(-0.0), d2b(0.0)) == (True, 0)


def test_div_flags():
    _, fl = sf.fdiv(sf.F64, d2b(1.0), d2b(0.0), RNE)
    assert fl == sf.DZ
    _, fl = sf.fdiv(sf.F64, d2b(0.0), d2b(0.0), RNE)
    assert fl == sf.NV


def test_subnormals_exact_and_uf():
    # 2^-537 * 2^-537 = 2^-1074: the min subnormal, exact, no flags
    p537 = (1023 - 537) << 52
    got, fl = sf.fmul(sf.F64, p537, p537, RNE)
    assert got == 1 and fl == 0
    # 2^-540 * 2^-541 = 2^-1081: rounds to zero, UF|NX
    a, b = (1023 - 540) << 52, (1023 - 541) << 52
    got, fl = sf.fmul(sf.F64, a, b, RNE)
    assert got == 0
    assert fl == (sf.UF | sf.NX)
    # overflow: OF|NX
    huge = d2b(1.5e308)
    got, fl = sf.fmul(sf.F64, huge, huge, RNE)
    assert got == 0x7FF0000000000000
    assert fl == (sf.OF | sf.NX)


def test_f_to_int_saturation_and_rtz():
    f64 = sf.F64
    assert sf.f_to_int(f64, d2b(-1.5), 32, True) == (-1 & 0xFFFFFFFF, sf.NX)
    assert sf.f_to_int(f64, d2b(1e30), 32, True) == (0x7FFFFFFF, sf.NV)
    assert sf.f_to_int(f64, d2b(-1e30), 32, True) == (0x80000000, sf.NV)
    assert sf.f_to_int(f64, d2b(float("inf")), 64, True) == \
        ((1 << 63) - 1, sf.NV)
    assert sf.f_to_int(f64, f64.qnan, 32, True) == (0x7FFFFFFF, sf.NV)
    assert sf.f_to_int(f64, d2b(-2.0), 32, False) == (0, sf.NV)   # unsigned
    assert sf.f_to_int(f64, d2b(3.99), 32, False) == (3, sf.NX)
    assert sf.f_to_int(f64, d2b(4.0), 32, False) == (4, 0)


def test_int_to_f_and_f_to_f():
    assert sf.int_to_f(sf.F64, 1 << 60, RNE)[0] == d2b(float(1 << 60))
    # (2^60 + 1) is inexact in f64
    got, fl = sf.int_to_f(sf.F64, (1 << 60) + 1, RNE)
    assert fl == sf.NX
    got, fl = sf.f_to_f(sf.F32, sf.F64, f2b(1.5), RNE)
    assert got == d2b(1.5) and fl == 0
    got, fl = sf.f_to_f(sf.F64, sf.F32, d2b(1e50), RNE)
    assert got == f2b(float("inf")) and fl == (sf.OF | sf.NX)


# ------------------------------------------------------ machine level
def fpop(name, dst, src1, src2=0, src3=0, w=1, mod=0):
    return asm(name, dst=dst, src1=src1, src2=src2, src3=src3, width=w,
               mod=mod)


def test_machine_fadd_and_canonicalization():
    prog = (li128(1, d2b(1.5)) + li128(2, d2b(2.25))
            + [fpop("FADD", 0, 1, 2), halt()])
    m, _ = run_words(prog)
    assert m.regs[0] == d2b(3.75)             # top bit 0: no extension
    prog = (li128(1, d2b(-1.0)) + li128(2, d2b(0.0))
            + [fpop("FADD", 0, 1, 2), halt()])
    m, _ = run_words(prog)
    assert m.regs[0] == canon(d2b(-1.0), 64)  # sign-extended writeback


def test_machine_fp_ignores_upper_bits():
    garbage = 0xDEAD << 64
    prog = (li128(1, garbage | d2b(2.0)) + li128(2, garbage | d2b(3.0))
            + [fpop("FMUL", 0, 1, 2), halt()])
    m, _ = run_words(prog)
    assert m.regs[0] == d2b(6.0)


def test_machine_fcsr_flags_sticky():
    prog = (li128(1, d2b(1.0)) + li128(2, d2b(0.0))
            + [fpop("FDIV", 3, 1, 2),         # DZ
               fpop("FADD", 4, 1, 1),         # exact: no flags
               mfsr(0, "fcsr"), halt()])
    m, _ = run_words(prog)
    assert m.regs[0] & 0x1F == sf.DZ          # sticky, not cleared


def test_machine_reserved_rm_traps_at_next_rounding_op():
    rm5 = 5 << E.FCSR_RM_LSB
    prog = (vbase_setup()
            + [ldi(1, rm5), mtsr("fcsr", 1)]
            + li128(2, d2b(1.0))
            + [fpop("FMIN", 3, 2, 2),         # does not round: no trap
               fpop("FADD", 4, 2, 2),         # rounds: ILLEGAL
               halt()])
    m, _ = run_words(prog, data=[(HANDLER_PA, wbytes(cause_handler()))])
    assert m.regs[10] == E.CAUSES["ILLEGAL"]
    assert m.regs[3] == d2b(1.0)              # FMIN executed fine


def test_machine_fcmp_writes_pred_and_nv():
    prog = (li128(1, sf.F64.qnan) + li128(2, d2b(1.0))
            + [fpop("FCMPLT", 1, 1, 2),       # NaN: false, NV
               mfsr(0, "fcsr"), halt()])
    m, _ = run_words(prog)
    assert m.preds[1] == 0
    assert m.regs[0] & 0x1F == sf.NV


def test_machine_fcvt():
    # fcvtfi.32 from f64 (width=0 dest int32, mod=1 src f64)
    prog = (li128(1, d2b(-7.9))
            + [asm("FCVTFI", dst=0, src1=1, width=0, mod=1), halt()])
    m, _ = run_words(prog)
    assert m.regs[0] == canon(-7 & 0xFFFFFFFF, 32)
    # fcvtff same-format is illegal
    prog = (vbase_setup() + li128(1, d2b(1.0))
            + [asm("FCVTFF", dst=0, src1=1, width=1, mod=1), halt()])
    m, _ = run_words(prog, data=[(HANDLER_PA, wbytes(cause_handler()))])
    assert m.regs[10] == E.CAUSES["ILLEGAL"]


def test_machine_fcvt_int128():
    v = (1 << 100) + 12345
    prog = (li128(1, v)
            + [asm("FCVTUIF", dst=0, src1=1, width=1, mod=2),  # u128 -> f64
               halt()])
    m, _ = run_words(prog)
    assert m.regs[0] == d2b(float(1 << 100))  # nearest double


def b2f(b):
    return struct.unpack("<f", struct.pack("<I", b))[0]


def test_f32_ops_vs_host():
    """binary32 add/sub/mul/div/sqrt via the host: compute in binary64,
    round to binary32 with struct.pack. Double rounding is innocuous
    here because 53 >= 2*24 + 2, so the composite is correctly rounded
    - an independent check the f64 crosscheck can't give us."""
    rng = random.Random(4321)
    checked = 0
    for _ in range(1500):
        ab, bb = rng.getrandbits(32), rng.getrandbits(32)
        a, b = b2f(ab), b2f(bb)
        cases = [("add", sf.fadd(sf.F32, ab, bb, RNE), a + b),
                 ("sub", sf.fsub(sf.F32, ab, bb, RNE), a - b),
                 ("mul", sf.fmul(sf.F32, ab, bb, RNE), a * b)]
        if b != 0:
            cases.append(("div", sf.fdiv(sf.F32, ab, bb, RNE), a / b))
        for name, (got, _fl), want in cases:
            if math.isnan(want) or math.isnan(b2f(got)):
                assert math.isnan(want) and math.isnan(b2f(got)), name
                checked += 1
                continue
            try:
                want32 = struct.unpack(
                    "<I", struct.pack("<f", want))[0]
            except OverflowError:
                # host refuses to round to inf; softfloat must give inf
                assert got & 0x7FFFFFFF == 0x7F800000, (name, a, b)
                checked += 1
                continue
            assert got == want32, (name, a, b)
            checked += 1
    assert checked > 4000


def test_f32_sqrt_vs_host():
    rng = random.Random(31)
    for _ in range(500):
        ab = rng.getrandbits(31)              # non-negative patterns
        a = b2f(ab)
        if math.isnan(a):
            continue
        got, _fl = sf.fsqrt(sf.F32, ab, RNE)
        want32 = struct.unpack("<I", struct.pack("<f", math.sqrt(a)))[0]
        assert got == want32, a


def test_uf_tininess_detected_after_rounding():
    """Root SPEC-ISSUES 13 (recommended freeze: after rounding). The
    distinguishing edge: an exact pre-rounding value just below the
    smallest normal that rounds UP to it. Before-rounding detection
    would set UF; after-rounding must give NX only. FMADD makes the
    pre-rounding value exact: a*b + c with no intermediate rounding."""
    f64, f32 = sf.F64, sf.F32
    # f64: 2^-538 * -2^-538 + 2^-1022 = 2^-1022 - 2^-1076
    a = (1023 - 538) << 52
    na = (1 << 63) | a
    minn = 1 << 52                             # smallest normal
    got, fl = sf.fmadd(f64, a, na, minn, RNE)
    assert got == minn                         # rounded up into the normals
    assert fl == sf.NX                         # no UF: not tiny after rounding
    # companion: 2^-538 * 2^-538 + largest_subnormal stays subnormal -> UF|NX
    lsub = (1 << 52) - 1
    got2, fl2 = sf.fmadd(f64, a, a, lsub, RNE)
    assert got2 == lsub                        # rounded back down (fr = 1/4)
    assert fl2 == (sf.UF | sf.NX)
    # f32 same shape: 2^-75 * -2^-76 + 2^-126 = 2^-126 - 2^-151
    a32 = (127 - 75) << 23
    nb32 = (1 << 31) | ((127 - 76) << 23)
    minn32 = 1 << 23
    got3, fl3 = sf.fmadd(f32, a32, nb32, minn32, RNE)
    assert got3 == minn32
    assert fl3 == sf.NX
