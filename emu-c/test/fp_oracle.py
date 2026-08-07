"""Independent IEEE 754-2019 oracle for the emulator's FP tests.

Reference computation for ISA-SPEC section 10: operand bit patterns are
decoded to exact rationals, the operation is performed exactly (Fraction
arithmetic; integer square root for FSQRT), and the exact result is
rounded once. This is deliberately a different formulation from the C
implementation (which sums aligned integer mantissas in a 128-bit
window), so agreement between the two is meaningful evidence.

Flag conventions match SPEC-ISSUES.md rulings: UF = tiny-after-rounding
AND inexact; NV on any sNaN operand; NaN results are the canonical
quiet NaN.
"""
from fractions import Fraction
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import encoding as E  # noqa: E402

NV = 1 << E.FCSR_FLAG_BITS["NV"]
DZ = 1 << E.FCSR_FLAG_BITS["DZ"]
OF = 1 << E.FCSR_FLAG_BITS["OF"]
UF = 1 << E.FCSR_FLAG_BITS["UF"]
NX = 1 << E.FCSR_FLAG_BITS["NX"]
RNE, RTZ, RDN, RUP, RMM = (E.ROUNDING[k]
                           for k in ("RNE", "RTZ", "RDN", "RUP", "RMM"))

F32 = {"p": 24, "emax": 127, "w": 32}
F64 = {"p": 53, "emax": 1023, "w": 64}


def fmt_of(w):
    return F32 if w == 32 else F64


# ---------------------------------------------------------------- bits

def unpack(f, bits):
    """-> ('nan', snan) | ('inf', sign) | ('zero', sign) |
          ('fin', sign, Fraction magnitude)"""
    p, emax, w = f["p"], f["emax"], f["w"]
    bits &= (1 << w) - 1
    sign = bool(bits >> (w - 1))
    ef = (bits >> (p - 1)) & ((1 << (w - p)) - 1)
    frac = bits & ((1 << (p - 1)) - 1)
    if ef == (1 << (w - p)) - 1:
        if frac == 0:
            return ("inf", sign)
        return ("nan", not (frac >> (p - 2)))
    if ef == 0:
        if frac == 0:
            return ("zero", sign)
        return ("fin", sign, Fraction(frac) * Fraction(2)**(1 - emax - (p - 1)))
    mant = frac | (1 << (p - 1))
    return ("fin", sign, Fraction(mant) * Fraction(2)**(ef - emax - (p - 1)))


def pack(f, sign, ef, frac):
    return (int(sign) << (f["w"] - 1)) | (ef << (f["p"] - 1)) | frac


def zero(f, sign=False):
    return pack(f, sign, 0, 0)


def inf(f, sign=False):
    return pack(f, sign, (1 << (f["w"] - f["p"])) - 1, 0)


def qnan(f):
    return pack(f, False, (1 << (f["w"] - f["p"])) - 1, 1 << (f["p"] - 2))


def maxfin(f, sign=False):
    return pack(f, sign, (1 << (f["w"] - f["p"])) - 2, (1 << (f["p"] - 1)) - 1)


# -------------------------------------------------------------- rounder

def _finish(f, sign, k, q, remcls, rm):
    """Round magnitude (k + rem) * 2^q where remcls classifies rem
    against 1/2: 'zero' | 'lo' | 'half' | 'hi'."""
    p, emax = f["p"], f["emax"]
    inexact = remcls != "zero"
    if rm == RNE:
        inc = remcls == "hi" or (remcls == "half" and (k & 1))
    elif rm == RTZ:
        inc = False
    elif rm == RDN:
        inc = inexact and sign
    elif rm == RUP:
        inc = inexact and not sign
    else:
        assert rm == RMM
        inc = remcls in ("half", "hi")
    k += int(inc)
    if k >> p:
        k >>= 1
        q += 1
    if k == 0:
        return zero(f, sign), UF | NX
    subn = (k >> (p - 1)) == 0
    e_res = q + p - 1
    if not subn and e_res > emax:
        to_inf = rm in (RNE, RMM) or (rm == RDN and sign) or \
                 (rm == RUP and not sign)
        return (inf(f, sign) if to_inf else maxfin(f, sign)), OF | NX
    fl = 0
    if inexact:
        fl |= NX
        if subn:
            fl |= UF
    ef = 0 if subn else e_res + emax
    return pack(f, sign, ef, k & ((1 << (p - 1)) - 1)), fl


def _remcls(rem):
    half = Fraction(1, 2)
    if rem == 0:
        return "zero"
    if rem < half:
        return "lo"
    if rem == half:
        return "half"
    return "hi"


def round_mag(f, sign, mag, rm):
    """Round exact rational magnitude mag > 0 into format f."""
    assert mag > 0
    e = mag.numerator.bit_length() - mag.denominator.bit_length()
    if Fraction(2)**e > mag:
        e -= 1
    if Fraction(2)**(e + 1) <= mag:
        e += 1
    q = max(e, 1 - f["emax"]) - (f["p"] - 1)
    scaled = mag * Fraction(2)**(-q)
    k = scaled.numerator // scaled.denominator
    return _finish(f, sign, k, q, _remcls(scaled - k), rm)


def round_val(f, v, rm, zero_sign=False):
    """Round exact rational v; zero_sign is the sign of an exact 0."""
    if v == 0:
        return zero(f, zero_sign), 0
    return round_mag(f, v < 0, abs(v), rm)


# ----------------------------------------------------------- operations

def _snan_flags(*us):
    return NV if any(u[0] == "nan" and u[1] for u in us) else 0


def _exact_zero_sign(sa, sb, rm):
    return sa if sa == sb else rm == RDN


def fadd(f, a, b, rm):
    ua, ub = unpack(f, a), unpack(f, b)
    if ua[0] == "nan" or ub[0] == "nan":
        return qnan(f), _snan_flags(ua, ub)
    if ua[0] == "inf" and ub[0] == "inf":
        if ua[1] != ub[1]:
            return qnan(f), NV
        return inf(f, ua[1]), 0
    if ua[0] == "inf":
        return inf(f, ua[1]), 0
    if ub[0] == "inf":
        return inf(f, ub[1]), 0
    if ua[0] == "zero" and ub[0] == "zero":
        return zero(f, _exact_zero_sign(ua[1], ub[1], rm)), 0
    va = 0 if ua[0] == "zero" else (-ua[2] if ua[1] else ua[2])
    vb = 0 if ub[0] == "zero" else (-ub[2] if ub[1] else ub[2])
    return round_val(f, va + vb, rm, zero_sign=(rm == RDN))


def fsub(f, a, b, rm):
    return fadd(f, a, b ^ (1 << (f["w"] - 1)), rm)


def fmul(f, a, b, rm):
    ua, ub = unpack(f, a), unpack(f, b)
    sign = (a >> (f["w"] - 1) & 1) != (b >> (f["w"] - 1) & 1)
    if ua[0] == "nan" or ub[0] == "nan":
        return qnan(f), _snan_flags(ua, ub)
    kinds = {ua[0], ub[0]}
    if kinds == {"inf", "zero"}:
        return qnan(f), NV
    if "inf" in kinds:
        return inf(f, sign), 0
    if "zero" in kinds:
        return zero(f, sign), 0
    return round_mag(f, sign, ua[2] * ub[2], rm)


def fdiv(f, a, b, rm):
    ua, ub = unpack(f, a), unpack(f, b)
    sign = (a >> (f["w"] - 1) & 1) != (b >> (f["w"] - 1) & 1)
    if ua[0] == "nan" or ub[0] == "nan":
        return qnan(f), _snan_flags(ua, ub)
    if ua[0] == "inf" and ub[0] == "inf":
        return qnan(f), NV
    if ua[0] == "zero" and ub[0] == "zero":
        return qnan(f), NV
    if ua[0] == "inf":
        return inf(f, sign), 0
    if ub[0] == "inf":
        return zero(f, sign), 0
    if ub[0] == "zero":
        return inf(f, sign), DZ
    if ua[0] == "zero":
        return zero(f, sign), 0
    return round_mag(f, sign, ua[2] / ub[2], rm)


def fsqrt(f, a, rm):
    ua = unpack(f, a)
    if ua[0] == "nan":
        return qnan(f), _snan_flags(ua)
    if ua[0] == "zero":
        return zero(f, ua[1]), 0
    if ua[1]:
        return qnan(f), NV
    if ua[0] == "inf":
        return inf(f), 0
    mag = ua[2]
    e = (mag.numerator.bit_length() - mag.denominator.bit_length()) // 2
    while Fraction(4)**e > mag:
        e -= 1
    while Fraction(4)**(e + 1) <= mag:
        e += 1
    q = max(e, 1 - f["emax"]) - (f["p"] - 1)
    g = mag * Fraction(4)**(-q)  # sqrt(g) is the scaled result
    k = math.isqrt(g.numerator * g.denominator) // g.denominator
    if Fraction(k)**2 == g:
        remcls = "zero"
    else:
        half_pt = (Fraction(k) + Fraction(1, 2))**2
        remcls = "hi" if g > half_pt else ("half" if g == half_pt else "lo")
    return _finish(f, False, k, q, remcls, rm)


def ffma(f, a, b, c, rm):
    ua, ub, uc = unpack(f, a), unpack(f, b), unpack(f, c)
    ps = (a >> (f["w"] - 1) & 1) != (b >> (f["w"] - 1) & 1)
    if {ua[0], ub[0]} == {"inf", "zero"}:
        return qnan(f), NV  # NV even when c is a quiet NaN
    if "nan" in (ua[0], ub[0], uc[0]):
        return qnan(f), _snan_flags(ua, ub, uc)
    if ua[0] == "inf" or ub[0] == "inf":
        if uc[0] == "inf" and uc[1] != ps:
            return qnan(f), NV
        return inf(f, ps), 0
    if uc[0] == "inf":
        return inf(f, uc[1]), 0
    if ua[0] == "zero" or ub[0] == "zero":
        if uc[0] == "zero":
            return zero(f, _exact_zero_sign(ps, uc[1], rm)), 0
        return c & ((1 << f["w"]) - 1), 0
    prod = (-1 if ps else 1) * ua[2] * ub[2]
    vc = 0 if uc[0] == "zero" else (-uc[2] if uc[1] else uc[2])
    return round_val(f, prod + vc, rm, zero_sign=(rm == RDN))


def _key(f, u):
    if u[0] == "zero":
        return (0, 0)
    if u[0] == "inf":
        return (-2, 0) if u[1] else (2, 0)
    return (-1, -u[2]) if u[1] else (1, u[2])


def fmin(f, a, b, rm=None):
    return _minmax(f, a, b, False)


def fmax(f, a, b, rm=None):
    return _minmax(f, a, b, True)


def _minmax(f, a, b, is_max):
    ua, ub = unpack(f, a), unpack(f, b)
    if ua[0] == "nan" or ub[0] == "nan":
        return qnan(f), _snan_flags(ua, ub)
    if ua[0] == "zero" and ub[0] == "zero":
        sign = (ua[1] and ub[1]) if is_max else (ua[1] or ub[1])
        return zero(f, sign), 0
    a_lt = _key(f, ua) < _key(f, ub)
    pick = b if a_lt == is_max else a
    return pick & ((1 << f["w"]) - 1), 0


def fcmp(f, op, a, b):
    """op in ('eq', 'lt', 'le') -> (bool, flags)"""
    ua, ub = unpack(f, a), unpack(f, b)
    if ua[0] == "nan" or ub[0] == "nan":
        return False, (0 if op == "eq" else NV)
    ka, kb = _key(f, ua), _key(f, ub)
    if op == "eq":
        return ka == kb, 0
    if op == "lt":
        return ka < kb, 0
    return ka <= kb, 0


# ---------------------------------------------------------- conversions

def fcvt_f_to_i(f, a, dstw, uns):
    """-> (canonical 128-bit value, flags)"""
    ua = unpack(f, a)
    umax, smax, nmag = (1 << dstw) - 1, (1 << (dstw - 1)) - 1, 1 << (dstw - 1)

    def canon(x):
        x &= (1 << dstw) - 1
        if x >> (dstw - 1):
            x |= ((1 << 128) - 1) ^ ((1 << dstw) - 1)
        return x

    if ua[0] == "nan":
        return canon(umax if uns else smax), NV
    if ua[0] == "inf":
        if uns:
            return (0 if ua[1] else canon(umax)), NV
        return canon(nmag if ua[1] else smax), NV
    if ua[0] == "zero":
        return 0, 0
    mag = ua[2]
    trunc = mag.numerator // mag.denominator
    inx = Fraction(trunc) != mag
    if uns:
        if ua[1]:
            if trunc != 0:
                return 0, NV
            return 0, NX if inx else 0
        if trunc > umax:
            return canon(umax), NV
        return canon(trunc), NX if inx else 0
    if trunc > (nmag if ua[1] else smax):
        return canon(nmag if ua[1] else smax), NV
    return canon(-trunc if ua[1] else trunc), NX if inx else 0


def fcvt_i_to_f(f, v, srcw, uns, rm):
    v &= (1 << srcw) - 1
    if uns:
        sv = v
    else:
        sv = v - (1 << srcw) if v >> (srcw - 1) else v
    if sv == 0:
        return zero(f), 0
    return round_mag(f, sv < 0, Fraction(abs(sv)), rm)


def fcvt_f_to_f(fs, fd, a, rm):
    ua = unpack(fs, a)
    if ua[0] == "nan":
        return qnan(fd), _snan_flags(ua)
    if ua[0] == "inf":
        return inf(fd, ua[1]), 0
    if ua[0] == "zero":
        return zero(fd, ua[1]), 0
    return round_mag(fd, ua[1], ua[2], rm)


ARITH = {"fadd": fadd, "fsub": fsub, "fmul": fmul, "fdiv": fdiv,
         "fmin": fmin, "fmax": fmax}
