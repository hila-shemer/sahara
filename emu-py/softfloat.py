"""Deterministic IEEE 754-2019 binary32/binary64 for Sahara, in pure
integer/rational arithmetic (no host FPU anywhere).

Finite values are exact Fractions; every operation computes the exact
result and rounds once, so FMADD's single rounding is literal. sqrt of a
non-square is irrational, so its guard comparisons are done by squaring —
also exact. Flag bit positions and rounding-mode codes come from
encoding.py; nothing is hardcoded.

All entry points take and return raw format bit patterns (ints) plus a
flags bitmask (fcsr bits 4:0).
"""

from fractions import Fraction
from math import isqrt

import encoding as E

NV = 1 << E.FCSR_FLAG_BITS["NV"]
DZ = 1 << E.FCSR_FLAG_BITS["DZ"]
OF = 1 << E.FCSR_FLAG_BITS["OF"]
UF = 1 << E.FCSR_FLAG_BITS["UF"]
NX = 1 << E.FCSR_FLAG_BITS["NX"]

RNE = E.ROUNDING["RNE"]
RTZ = E.ROUNDING["RTZ"]
RDN = E.ROUNDING["RDN"]
RUP = E.ROUNDING["RUP"]
RMM = E.ROUNDING["RMM"]

HALF = Fraction(1, 2)


class Fmt:
    def __init__(self, ebits, mbits):
        self.ebits, self.mbits = ebits, mbits
        self.bias = (1 << (ebits - 1)) - 1
        self.emax = self.bias                 # max normal exponent
        self.emin = 1 - self.bias             # min normal exponent
        self.bits = 1 + ebits + mbits
        self.expmask = (1 << ebits) - 1
        self.mmask = (1 << mbits) - 1
        self.qnan = (self.expmask << mbits) | (1 << (mbits - 1))


F32 = Fmt(8, 23)
F64 = Fmt(11, 52)
BY_WIDTH = {0: F32, 1: F64}     # ISA width codes for FP families


class Un:
    """Unpacked value. kind: 'nan' | 'inf' | 'fin' (fin includes zero).
    For 'fin', v is a signed exact Fraction and sign carries the sign of
    zero. snan only meaningful for 'nan'."""

    __slots__ = ("kind", "sign", "v", "snan")

    def __init__(self, kind, sign, v=None, snan=False):
        self.kind, self.sign, self.v, self.snan = kind, sign, v, snan


def unpack(fmt, bits):
    bits &= (1 << fmt.bits) - 1
    sign = (bits >> (fmt.bits - 1)) & 1
    e = (bits >> fmt.mbits) & fmt.expmask
    m = bits & fmt.mmask
    if e == fmt.expmask:
        if m == 0:
            return Un("inf", sign)
        return Un("nan", sign, snan=not (m >> (fmt.mbits - 1)) & 1)
    if e == 0:
        mag = Fraction(m, 1) * Fraction(2) ** (fmt.emin - fmt.mbits)
    else:
        mag = Fraction(m + (1 << fmt.mbits), 1) * Fraction(2) ** (
            e - fmt.bias - fmt.mbits)
    return Un("fin", sign, -mag if sign else mag)


def _inf(fmt, sign):
    return (sign << (fmt.bits - 1)) | (fmt.expmask << fmt.mbits)


def _maxfinite(fmt, sign):
    return (sign << (fmt.bits - 1)) | ((fmt.expmask - 1) << fmt.mbits) \
        | fmt.mmask


def _zero(fmt, sign):
    return sign << (fmt.bits - 1)


def _signed_zero(fmt, rm, neg=None):
    """Sign of an exact-zero result from cancellation: +0, except RDN
    gives -0 (IEEE 754-2019 6.3). neg forces a sign (zero operands)."""
    if neg is None:
        neg = 1 if rm == RDN else 0
    return _zero(fmt, neg)


def _roundup(rm, sign, cmp_half, inexact, n_odd):
    """cmp_half: -1/0/+1 comparing the discarded fraction against 1/2."""
    if not inexact:
        return False
    if rm == RNE:
        return cmp_half > 0 or (cmp_half == 0 and n_odd)
    if rm == RTZ:
        return False
    if rm == RDN:
        return bool(sign)
    if rm == RUP:
        return not sign
    if rm == RMM:
        return cmp_half >= 0
    raise AssertionError("reserved rounding mode reached softfloat")


def _overflow(fmt, sign, rm):
    if rm in (RNE, RMM):
        return _inf(fmt, sign)
    if rm == RTZ:
        return _maxfinite(fmt, sign)
    if rm == RDN:
        return _inf(fmt, sign) if sign else _maxfinite(fmt, sign)
    if rm == RUP:
        return _maxfinite(fmt, sign) if sign else _inf(fmt, sign)
    raise AssertionError("reserved rounding mode reached softfloat")


def _pack(fmt, sign, n, q, cmp_half, inexact, rm):
    """Value = (-1)^sign * (n + fr) * 2^q with fr in [0,1), fr's relation
    to 1/2 given by cmp_half, q = quantum exponent (either e-mbits for the
    normal binade or emin-mbits at the subnormal floor). Rounds and packs."""
    flags = NX if inexact else 0
    if _roundup(rm, sign, cmp_half, inexact, n & 1):
        n += 1
    if n == 0:
        return _signed_zero(fmt, rm, neg=sign), flags | (UF if inexact else 0)
    e = n.bit_length() - 1 + q                              # unbiased exp
    if e > fmt.emax:
        return _overflow(fmt, sign, rm), flags | OF | NX
    if e < fmt.emin:
        # subnormal: q must already be the subnormal quantum
        assert q == fmt.emin - fmt.mbits
        if inexact:
            flags |= UF
        return (sign << (fmt.bits - 1)) | n, flags
    # normal: align n to mbits+1 bits
    k = n.bit_length() - 1
    mant = (n << (fmt.mbits - k)) if k <= fmt.mbits else (n >> (k - fmt.mbits))
    # k > mbits+... : n came from rounding 2^(mbits+1); shifting drops only
    # zero bits there (n is then a power of two), so no information is lost.
    mant &= fmt.mmask
    return (sign << (fmt.bits - 1)) | ((e + fmt.bias) << fmt.mbits) | mant, \
        flags


def round_frac(fmt, sign, mag, rm):
    """Round exact positive Fraction mag to fmt. Returns (bits, flags)."""
    assert mag > 0
    # e = floor(log2 mag)
    e = mag.numerator.bit_length() - mag.denominator.bit_length()
    if _cmp_pow2(mag, e) < 0:
        e -= 1
    q = max(e - fmt.mbits, fmt.emin - fmt.mbits)
    x = mag * Fraction(2) ** (-q)
    n = x.numerator // x.denominator
    fr = x - n
    inexact = fr != 0
    cmp_half = -1 if fr < HALF else (0 if fr == HALF else 1)
    return _pack(fmt, sign, n, q, cmp_half, inexact, rm)


def _cmp_pow2(mag, e):
    """Compare Fraction mag with 2**e exactly."""
    if e >= 0:
        lhs, rhs = mag.numerator, mag.denominator << e
    else:
        lhs, rhs = mag.numerator << -e, mag.denominator
    return (lhs > rhs) - (lhs < rhs)


def _round_signed(fmt, v, rm):
    """Round signed nonzero Fraction."""
    if v < 0:
        return round_frac(fmt, 1, -v, rm)
    return round_frac(fmt, 0, v, rm)


def _nan_result(fmt, ops):
    flags = NV if any(o.kind == "nan" and o.snan for o in ops) else 0
    return fmt.qnan, flags


# ------------------------------------------------------------------ ops

def fadd(fmt, a, b, rm, negate_b=False):
    ua, ub = unpack(fmt, a), unpack(fmt, b)
    if negate_b:
        ub.sign ^= 1
        if ub.kind == "fin":
            ub.v = -ub.v
    if ua.kind == "nan" or ub.kind == "nan":
        return _nan_result(fmt, (ua, ub))
    if ua.kind == "inf" and ub.kind == "inf":
        if ua.sign != ub.sign:
            return fmt.qnan, NV
        return _inf(fmt, ua.sign), 0
    if ua.kind == "inf":
        return _inf(fmt, ua.sign), 0
    if ub.kind == "inf":
        return _inf(fmt, ub.sign), 0
    s = ua.v + ub.v
    if s == 0:
        if ua.v == 0 and ub.v == 0:
            if ua.sign == ub.sign:
                return _zero(fmt, ua.sign), 0
            return _signed_zero(fmt, rm), 0
        return _signed_zero(fmt, rm), 0      # exact cancellation
    return _round_signed(fmt, s, rm)


def fsub(fmt, a, b, rm):
    return fadd(fmt, a, b, rm, negate_b=True)


def fmul(fmt, a, b, rm):
    ua, ub = unpack(fmt, a), unpack(fmt, b)
    sign = ua.sign ^ ub.sign
    if ua.kind == "nan" or ub.kind == "nan":
        return _nan_result(fmt, (ua, ub))
    if ua.kind == "inf" or ub.kind == "inf":
        other = ub if ua.kind == "inf" else ua
        if other.kind == "fin" and other.v == 0:
            return fmt.qnan, NV               # 0 * inf
        return _inf(fmt, sign), 0
    p = ua.v * ub.v
    if p == 0:
        return _zero(fmt, sign), 0
    return _round_signed(fmt, p, rm)


def fdiv(fmt, a, b, rm):
    ua, ub = unpack(fmt, a), unpack(fmt, b)
    sign = ua.sign ^ ub.sign
    if ua.kind == "nan" or ub.kind == "nan":
        return _nan_result(fmt, (ua, ub))
    if ua.kind == "inf":
        if ub.kind == "inf":
            return fmt.qnan, NV               # inf / inf
        return _inf(fmt, sign), 0
    if ub.kind == "inf":
        return _zero(fmt, sign), 0
    if ub.v == 0:
        if ua.v == 0:
            return fmt.qnan, NV               # 0 / 0
        return _inf(fmt, sign), DZ
    if ua.v == 0:
        return _zero(fmt, sign), 0
    return _round_signed(fmt, ua.v / ub.v, rm)


def fsqrt(fmt, a, rm):
    ua = unpack(fmt, a)
    if ua.kind == "nan":
        return _nan_result(fmt, (ua,))
    if ua.kind == "inf":
        if ua.sign:
            return fmt.qnan, NV
        return _inf(fmt, 0), 0
    if ua.v == 0:
        return _zero(fmt, ua.sign), 0         # sqrt(-0) = -0
    if ua.sign:
        return fmt.qnan, NV
    v = ua.v
    # exact case: sqrt(p/r) = sqrt(p*r)/r when p*r is a perfect square
    t = v.numerator * v.denominator
    s = isqrt(t)
    if s * s == t:
        return round_frac(fmt, 0, Fraction(s, v.denominator), rm)
    # irrational: n = floor(sqrt(v)/2^q); guard comparisons by squaring
    ev = v.numerator.bit_length() - v.denominator.bit_length()
    if _cmp_pow2(v, ev) < 0:
        ev -= 1
    e = ev >> 1                                # floor(log2 sqrt(v)), maybe -1
    while _cmp_pow2(v, 2 * (e + 1)) >= 0:      # ensure 4^e <= v < 4^(e+1)
        e += 1
    while _cmp_pow2(v, 2 * e) < 0:
        e -= 1
    q = max(e - fmt.mbits, fmt.emin - fmt.mbits)
    # y = v / 4^q; n = isqrt(floor(y))
    if q >= 0:
        yn, yd = v.numerator, v.denominator << (2 * q)
    else:
        yn, yd = v.numerator << (-2 * q), v.denominator
    n = isqrt(yn // yd)
    # discarded fraction vs 1/2:  y ? (n + 1/2)^2  <=>  4*yn ? yd*(2n+1)^2
    lhs, rhs = 4 * yn, yd * (2 * n + 1) ** 2
    cmp_half = (lhs > rhs) - (lhs < rhs)
    assert cmp_half != 0                       # irrational: never a tie
    return _pack(fmt, 0, n, q, cmp_half, True, rm)


def fmadd(fmt, a, b, c, rm):
    """a*b + c, single rounding."""
    ua, ub, uc = unpack(fmt, a), unpack(fmt, b), unpack(fmt, c)
    psign = ua.sign ^ ub.sign
    # invalid 0*inf (raised even when c is a quiet NaN; see SPEC-ISSUES)
    zero_times_inf = (
        (ua.kind == "inf" and ub.kind == "fin" and ub.v == 0)
        or (ub.kind == "inf" and ua.kind == "fin" and ua.v == 0))
    if ua.kind == "nan" or ub.kind == "nan" or uc.kind == "nan":
        bits, flags = _nan_result(fmt, (ua, ub, uc))
        if zero_times_inf:
            flags |= NV
        return bits, flags
    if zero_times_inf:
        return fmt.qnan, NV
    if ua.kind == "inf" or ub.kind == "inf":
        if uc.kind == "inf" and uc.sign != psign:
            return fmt.qnan, NV                # inf - inf
        return _inf(fmt, psign), 0
    if uc.kind == "inf":
        return _inf(fmt, uc.sign), 0
    r = ua.v * ub.v + uc.v
    if r == 0:
        if ua.v * ub.v == 0 and uc.v == 0:
            if psign == uc.sign:
                return _zero(fmt, psign), 0
            return _signed_zero(fmt, rm), 0
        return _signed_zero(fmt, rm), 0        # exact cancellation
    return _round_signed(fmt, r, rm)


def fminmax(fmt, a, b, want_max):
    """IEEE 754-2019 minimum/maximum: NaN propagates, -0 < +0."""
    ua, ub = unpack(fmt, a), unpack(fmt, b)
    if ua.kind == "nan" or ub.kind == "nan":
        return _nan_result(fmt, (ua, ub))

    def key(u):
        if u.kind == "inf":
            return (1 if not u.sign else -1) * Fraction(10) ** 9999
        return u.v

    ka, kb = key(ua), key(ub)
    if ka == kb:                                # covers -0 vs +0
        sa, sb = ua.sign, ub.sign
        if sa != sb:
            pick_a = (sa == 1) != want_max      # min -> -0, max -> +0
        else:
            pick_a = True
        return (a if pick_a else b), 0
    if (ka > kb) == bool(want_max):
        return a, 0
    return b, 0


def fcmp(fmt, op, a, b):
    """op in 'eq' 'lt' 'le'. Returns (bool, flags). NaN compares false;
    LT/LE raise NV on any NaN operand, EQ never does (ISA-SPEC 10.2)."""
    ua, ub = unpack(fmt, a), unpack(fmt, b)
    if ua.kind == "nan" or ub.kind == "nan":
        return False, (NV if op in ("lt", "le") else 0)

    def key(u):
        if u.kind == "inf":
            return (1 if not u.sign else -1) * Fraction(10) ** 9999
        return u.v

    ka, kb = key(ua), key(ub)
    if op == "eq":
        return ka == kb, 0
    if op == "lt":
        return ka < kb, 0
    return ka <= kb, 0


# ---------------------------------------------------------- conversions

def f_to_int(fmt, bits, dwidth, signed):
    """FP -> integer, round-toward-zero always. Returns (val, flags) where
    val is the canonical low-dwidth two's-complement pattern (as unsigned)."""
    if signed:
        imin, imax = -(1 << (dwidth - 1)), (1 << (dwidth - 1)) - 1
    else:
        imin, imax = 0, (1 << dwidth) - 1
    mask = (1 << dwidth) - 1
    ua = unpack(fmt, bits)
    if ua.kind == "nan":
        return imax & mask, NV
    if ua.kind == "inf":
        return (imax if not ua.sign else imin) & mask, NV
    n = int(ua.v)                              # Fraction truncates toward 0
    if n > imax:
        return imax & mask, NV
    if n < imin:
        return imin & mask, NV
    return n & mask, (NX if n != ua.v else 0)


def int_to_f(fmt, val, rm):
    """Signed python int -> FP. Returns (bits, flags)."""
    if val == 0:
        return _zero(fmt, 0), 0
    return _round_signed(fmt, Fraction(val), rm)


def f_to_f(sfmt, dfmt, bits, rm):
    ua = unpack(sfmt, bits)
    if ua.kind == "nan":
        return _nan_result(dfmt, (ua,))
    if ua.kind == "inf":
        return _inf(dfmt, ua.sign), 0
    if ua.v == 0:
        return _zero(dfmt, ua.sign), 0
    return _round_signed(dfmt, ua.v, rm)
