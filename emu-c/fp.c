#include "fp.h"

#include "gen/sahara_isa.h"
#include "rw/status.h"

/* ------------------------------------------------------------ formats */

typedef struct Fmt {
    unsigned w;  /* total bits */
    unsigned p;  /* precision incl. implicit bit (24 / 53) */
    int emax;    /* also the bias; emin = 1 - emax */
} Fmt;

static const Fmt FMT32 = { 32u, 24u, 127 };
static const Fmt FMT64 = { 64u, 53u, 1023 };

static const Fmt *fmt_of(unsigned fmtw)
{
    RW_ASSERT(fmtw == 32u || fmtw == 64u);
    return (fmtw == 32u) ? &FMT32 : &FMT64;
}

static uint64_t low_bits(const Fmt *f, uint64_t v)
{
    return (f->w == 64u) ? v : (v & ((1ull << f->w) - 1u));
}

/* ------------------------------------------------------ unpack / pack */

enum { K_ZERO, K_FIN, K_INF, K_NAN };

typedef struct Uf {
    int kind;
    bool sign, snan;
    int exp;       /* K_FIN: value = (-1)^sign * mant * 2^exp */
    uint64_t mant; /* K_FIN: nonzero, < 2^p */
} Uf;

static Uf fp_unpack(const Fmt *f, uint64_t bits)
{
    unsigned eb = f->w - f->p; /* exponent field width */
    uint64_t frac = bits & ((1ull << (f->p - 1u)) - 1u);
    unsigned ef = (unsigned)((bits >> (f->p - 1u)) & ((1ull << eb) - 1u));
    Uf u = { .kind = K_ZERO, .sign = ((bits >> (f->w - 1u)) & 1u) != 0u,
             .snan = false, .exp = 0, .mant = 0u };
    if (ef == (1u << eb) - 1u) {
        u.kind = (frac == 0u) ? K_INF : K_NAN;
        u.snan = (u.kind == K_NAN) &&
                 ((frac >> (f->p - 2u)) & 1u) == 0u;
    } else if (ef == 0u) {
        if (frac != 0u) { /* subnormal */
            u.kind = K_FIN;
            u.mant = frac;
            u.exp = 1 - f->emax - ((int)f->p - 1);
        }
    } else {
        u.kind = K_FIN;
        u.mant = frac | (1ull << (f->p - 1u));
        u.exp = (int)ef - f->emax - ((int)f->p - 1);
    }
    return u;
}

static uint64_t pack_raw(const Fmt *f, bool sign, unsigned ef, uint64_t frac)
{
    return ((uint64_t)(sign ? 1u : 0u) << (f->w - 1u)) |
           ((uint64_t)ef << (f->p - 1u)) | frac;
}

static uint64_t bits_zero(const Fmt *f, bool sign)
{
    return pack_raw(f, sign, 0u, 0u);
}

static uint64_t bits_inf(const Fmt *f, bool sign)
{
    return pack_raw(f, sign, (1u << (f->w - f->p)) - 1u, 0u);
}

/* The canonical quiet NaN of the format (10.2): positive, top fraction
 * bit set, rest zero. 0x7FC00000 / 0x7FF8000000000000. */
static uint64_t bits_qnan(const Fmt *f)
{
    return pack_raw(f, false, (1u << (f->w - f->p)) - 1u,
                    1ull << (f->p - 2u));
}

static uint64_t bits_maxfin(const Fmt *f, bool sign)
{
    return pack_raw(f, sign, (1u << (f->w - f->p)) - 2u,
                    (1ull << (f->p - 1u)) - 1u);
}

/* --------------------------------------------------------- bit tools */

static unsigned msb128(se_u128 v)
{
    RW_ASSERT(v != 0u);
    unsigned n = 0u;
    if (se_hi64(v) != 0u) {
        n = 64u;
        v >>= 64;
    }
    uint64_t x = se_lo64(v);
    while ((x >> 1) != 0u) {
        x >>= 1;
        n++;
    }
    return n;
}

/* Integer square root with remainder (restoring, bit pairs). */
static se_u128 isqrt128(se_u128 v, se_u128 *rem)
{
    RW_ASSERT(v != 0u);
    se_u128 r = 0u, bit = (se_u128)1 << 126;
    while (bit > v)
        bit >>= 2;
    while (bit != 0u) {
        if (v >= r + bit) {
            v -= r + bit;
            r = (r >> 1) + bit;
        } else {
            r >>= 1;
        }
        bit >>= 2;
    }
    *rem = v;
    return r;
}

/* ------------------------------------------------------- the rounder */

/* Round (-1)^sign * mant * 2^exp -- plus, if sticky, some nonzero value
 * strictly below mant's units -- into format f under rm, OR-ing the
 * IEEE flags into *fl. mant must be nonzero. Underflow uses tininess
 * after rounding and is raised only together with inexact (the SSE
 * convention; SPEC-ISSUES.md). */
static uint64_t fp_round(const Fmt *f, bool sign, se_u128 mant, int exp,
                         bool sticky, unsigned rm, uint8_t *fl)
{
    RW_ASSERT(mant != 0u);
    unsigned n = msb128(mant);
    int e_val = exp + (int)n; /* value in [2^e_val, 2^(e_val+1)) */
    int emin = 1 - f->emax;
    int q = ((e_val >= emin) ? e_val : emin) - ((int)f->p - 1);
    int sh = q - exp; /* bits to drop below the result's lsb */
    uint64_t kept;
    bool g, s;
    if (sh <= 0) {
        /* fewer than p significant bits above the quantum: exact shift
         * up; -sh <= p-1-n so this cannot overflow */
        kept = se_lo64(mant << (unsigned)-sh);
        g = false;
        s = sticky;
    } else if ((unsigned)sh <= n) {
        kept = se_lo64(mant >> (unsigned)sh);
        g = ((se_lo64(mant >> ((unsigned)sh - 1u))) & 1u) != 0u;
        s = sticky ||
            (mant & ((((se_u128)1) << ((unsigned)sh - 1u)) - 1u)) != 0u;
    } else if ((unsigned)sh == n + 1u) {
        kept = 0u;
        g = true; /* the msb is exactly the guard bit */
        s = sticky || (mant & ((((se_u128)1) << n) - 1u)) != 0u;
    } else {
        kept = 0u;
        g = false;
        s = true; /* mant nonzero, wholly below the guard */
    }
    bool inexact = g || s;
    bool inc;
    switch (rm) {
    case RM_RNE: inc = g && (s || (kept & 1u) != 0u); break;
    case RM_RTZ: inc = false; break;
    case RM_RDN: inc = inexact && sign; break;
    case RM_RUP: inc = inexact && !sign; break;
    case RM_RMM: inc = g; break; /* >= half: away from zero */
    default:
        RW_ASSERT(0); /* reserved modes trap ILLEGAL before execution */
        inc = false;
        break;
    }
    kept += inc ? 1u : 0u;
    if ((kept >> f->p) != 0u) { /* carry out of p bits: 10..0 * 2^(q+1) */
        kept >>= 1;
        q += 1;
    }
    if (kept == 0u) { /* rounded all the way down to zero */
        *fl |= (uint8_t)(FCSR_UF | FCSR_NX);
        return bits_zero(f, sign);
    }
    bool subn = (kept >> (f->p - 1u)) == 0u;
    int e_res = q + (int)f->p - 1;
    if (!subn && e_res > f->emax) {
        *fl |= (uint8_t)(FCSR_OF | FCSR_NX);
        bool to_inf = (rm == RM_RNE || rm == RM_RMM ||
                       (rm == RM_RDN && sign) || (rm == RM_RUP && !sign));
        return to_inf ? bits_inf(f, sign) : bits_maxfin(f, sign);
    }
    if (inexact) {
        *fl |= FCSR_NX;
        if (subn)
            *fl |= FCSR_UF;
    }
    unsigned ef = subn ? 0u : (unsigned)(e_res + f->emax);
    return pack_raw(f, sign, ef, kept & ((1ull << (f->p - 1u)) - 1u));
}

/* ------------------------------------------------- exact signed sums */

typedef struct Ex {
    bool sign;
    se_u128 mant;
    int exp;
    bool sticky;
    bool zero; /* exact cancellation */
} Ex;

/* Exact signed sum of two finite nonzero values (-1)^sign*mant*2^exp.
 * Precondition: mantissas of at most 107 bits (a p<=53 operand or a
 * 2p<=106-bit product), no incoming sticky. The wide operand is shifted
 * up to bit 126 before the narrow one sheds alignment bits, so a
 * shifted-out (sticky) operand is always far smaller than the kept one:
 * cancellation and precision loss cannot coincide. */
static Ex ex_add(Ex x, Ex y)
{
    if (x.exp < y.exp) {
        Ex t = x;
        x = y;
        y = t;
    }
    unsigned head = 126u - msb128(x.mant);
    unsigned d = (unsigned)(x.exp - y.exp);
    unsigned up = (d < head) ? d : head;
    x.mant <<= up;
    x.exp -= (int)up;
    d -= up;
    if (d != 0u) {
        unsigned ny = msb128(y.mant);
        if (d > ny) {
            y.sticky = true;
            y.mant = 0u;
        } else {
            y.sticky = (y.mant & ((((se_u128)1) << d) - 1u)) != 0u;
            y.mant >>= d;
        }
        y.exp += (int)d;
    }
    Ex r = { .sign = x.sign, .mant = 0u, .exp = x.exp, .sticky = false,
             .zero = false };
    if (x.sign == y.sign) {
        r.mant = x.mant + y.mant;
        r.sticky = y.sticky;
    } else if (x.mant > y.mant) {
        /* subtracting (y + sticky-tail): borrow one unit into the tail */
        r.mant = x.mant - y.mant - (y.sticky ? 1u : 0u);
        r.sticky = y.sticky;
        RW_ASSERT(r.mant != 0u || !r.sticky);
    } else if (y.mant > x.mant) {
        r.sign = y.sign;
        r.mant = y.mant - x.mant;
        r.sticky = y.sticky;
    } else {
        RW_ASSERT(!y.sticky); /* equal mants only when y kept every bit */
        r.zero = true;
    }
    return r;
}

/* ------------------------------------------------------- operations */

static SeFpRes res_bits(uint64_t bits)
{
    return (SeFpRes){ .bits = bits, .flags = 0u };
}

static SeFpRes res_invalid(const Fmt *f)
{
    return (SeFpRes){ .bits = bits_qnan(f), .flags = FCSR_NV };
}

static SeFpRes fp_addsub(const Fmt *f, uint64_t ab, uint64_t bb, bool neg_b,
                         unsigned rm)
{
    Uf a = fp_unpack(f, ab), b = fp_unpack(f, bb);
    if (neg_b)
        b.sign = !b.sign;
    if (a.kind == K_NAN || b.kind == K_NAN) {
        SeFpRes r = res_bits(bits_qnan(f));
        if (a.snan || b.snan)
            r.flags |= FCSR_NV;
        return r;
    }
    if (a.kind == K_INF && b.kind == K_INF) {
        if (a.sign != b.sign)
            return res_invalid(f); /* inf - inf */
        return res_bits(bits_inf(f, a.sign));
    }
    if (a.kind == K_INF)
        return res_bits(bits_inf(f, a.sign));
    if (b.kind == K_INF)
        return res_bits(bits_inf(f, b.sign));
    if (a.kind == K_ZERO && b.kind == K_ZERO) {
        bool sign = (a.sign == b.sign) ? a.sign : (rm == RM_RDN);
        return res_bits(bits_zero(f, sign));
    }
    if (a.kind == K_ZERO) /* 0 + b is exactly b (as negated for FSUB) */
        return res_bits(low_bits(f, bb) ^
                        (neg_b ? (1ull << (f->w - 1u)) : 0u));
    if (b.kind == K_ZERO)
        return res_bits(low_bits(f, ab));
    Ex sum = ex_add(
        (Ex){ .sign = a.sign, .mant = a.mant, .exp = a.exp },
        (Ex){ .sign = b.sign, .mant = b.mant, .exp = b.exp });
    if (sum.zero)
        return res_bits(bits_zero(f, rm == RM_RDN));
    SeFpRes r = res_bits(0u);
    r.bits = fp_round(f, sum.sign, sum.mant, sum.exp, sum.sticky, rm,
                      &r.flags);
    return r;
}

static SeFpRes fp_mul(const Fmt *f, uint64_t ab, uint64_t bb, unsigned rm)
{
    Uf a = fp_unpack(f, ab), b = fp_unpack(f, bb);
    bool sign = a.sign != b.sign;
    if (a.kind == K_NAN || b.kind == K_NAN) {
        SeFpRes r = res_bits(bits_qnan(f));
        if (a.snan || b.snan)
            r.flags |= FCSR_NV;
        return r;
    }
    if ((a.kind == K_INF && b.kind == K_ZERO) ||
        (a.kind == K_ZERO && b.kind == K_INF))
        return res_invalid(f);
    if (a.kind == K_INF || b.kind == K_INF)
        return res_bits(bits_inf(f, sign));
    if (a.kind == K_ZERO || b.kind == K_ZERO)
        return res_bits(bits_zero(f, sign));
    SeFpRes r = res_bits(0u);
    r.bits = fp_round(f, sign, (se_u128)a.mant * b.mant, a.exp + b.exp,
                      false, rm, &r.flags);
    return r;
}

/* Shift a subnormal mantissa up to the implicit-bit position. */
static void uf_norm(const Fmt *f, Uf *u)
{
    unsigned up = (f->p - 1u) - msb128(u->mant);
    u->mant <<= up;
    u->exp -= (int)up;
}

static SeFpRes fp_div(const Fmt *f, uint64_t ab, uint64_t bb, unsigned rm)
{
    Uf a = fp_unpack(f, ab), b = fp_unpack(f, bb);
    bool sign = a.sign != b.sign;
    if (a.kind == K_NAN || b.kind == K_NAN) {
        SeFpRes r = res_bits(bits_qnan(f));
        if (a.snan || b.snan)
            r.flags |= FCSR_NV;
        return r;
    }
    if (a.kind == K_INF && b.kind == K_INF)
        return res_invalid(f);
    if (a.kind == K_ZERO && b.kind == K_ZERO)
        return res_invalid(f);
    if (a.kind == K_INF)
        return res_bits(bits_inf(f, sign));
    if (b.kind == K_INF)
        return res_bits(bits_zero(f, sign));
    if (b.kind == K_ZERO) { /* finite nonzero / 0 */
        SeFpRes r = res_bits(bits_inf(f, sign));
        r.flags |= FCSR_DZ;
        return r;
    }
    if (a.kind == K_ZERO)
        return res_bits(bits_zero(f, sign));
    uf_norm(f, &a);
    uf_norm(f, &b);
    se_u128 num = (se_u128)a.mant << (f->p + 2u);
    se_u128 quo = num / b.mant;
    se_u128 remv = num % b.mant;
    SeFpRes r = res_bits(0u);
    r.bits = fp_round(f, sign, quo, a.exp - b.exp - (int)(f->p + 2u),
                      remv != 0u, rm, &r.flags);
    return r;
}

static SeFpRes fp_sqrt(const Fmt *f, uint64_t ab, unsigned rm)
{
    Uf a = fp_unpack(f, ab);
    if (a.kind == K_NAN) {
        SeFpRes r = res_bits(bits_qnan(f));
        if (a.snan)
            r.flags |= FCSR_NV;
        return r;
    }
    if (a.kind == K_ZERO)
        return res_bits(bits_zero(f, a.sign)); /* sqrt(-0) = -0 */
    if (a.sign)
        return res_invalid(f);
    if (a.kind == K_INF)
        return res_bits(bits_inf(f, false));
    uf_norm(f, &a);
    unsigned k = f->p + 6u;
    if (((a.exp - (int)k) & 1) != 0)
        k += 1u; /* radicand exponent must be even */
    se_u128 remv;
    se_u128 root = isqrt128((se_u128)a.mant << k, &remv);
    SeFpRes r = res_bits(0u);
    r.bits = fp_round(f, false, root, (a.exp - (int)k) / 2, remv != 0u, rm,
                      &r.flags);
    return r;
}

static SeFpRes fp_fmadd(const Fmt *f, uint64_t ab, uint64_t bb, uint64_t cb,
                        unsigned rm)
{
    Uf a = fp_unpack(f, ab), b = fp_unpack(f, bb), c = fp_unpack(f, cb);
    bool ps = a.sign != b.sign; /* product sign */
    bool any_snan = a.snan || b.snan || c.snan;
    bool inv_mul = (a.kind == K_INF && b.kind == K_ZERO) ||
                   (a.kind == K_ZERO && b.kind == K_INF);
    if (inv_mul) { /* NV even when c is a quiet NaN (SPEC-ISSUES.md) */
        SeFpRes r = res_bits(bits_qnan(f));
        r.flags |= FCSR_NV;
        return r;
    }
    if (a.kind == K_NAN || b.kind == K_NAN || c.kind == K_NAN) {
        SeFpRes r = res_bits(bits_qnan(f));
        if (any_snan)
            r.flags |= FCSR_NV;
        return r;
    }
    if (a.kind == K_INF || b.kind == K_INF) {
        if (c.kind == K_INF && c.sign != ps)
            return res_invalid(f);
        return res_bits(bits_inf(f, ps));
    }
    if (c.kind == K_INF)
        return res_bits(bits_inf(f, c.sign));
    if (a.kind == K_ZERO || b.kind == K_ZERO) {
        if (c.kind == K_ZERO) {
            bool sign = (ps == c.sign) ? ps : (rm == RM_RDN);
            return res_bits(bits_zero(f, sign));
        }
        return res_bits(low_bits(f, cb)); /* exact: 0 + c */
    }
    Ex prod = { .sign = ps, .mant = (se_u128)a.mant * b.mant,
                .exp = a.exp + b.exp };
    SeFpRes r = res_bits(0u);
    if (c.kind == K_ZERO) {
        r.bits = fp_round(f, prod.sign, prod.mant, prod.exp, false, rm,
                          &r.flags);
        return r;
    }
    Ex sum = ex_add(prod, (Ex){ .sign = c.sign, .mant = c.mant,
                                .exp = c.exp });
    if (sum.zero)
        return res_bits(bits_zero(f, rm == RM_RDN));
    r.bits = fp_round(f, sum.sign, sum.mant, sum.exp, sum.sticky, rm,
                      &r.flags);
    return r;
}

/* Monotone key: unsigned order of keys == IEEE order of values.
 * -0 and +0 map to adjacent keys; callers treat zeros as equal. */
static uint64_t ord_key(const Fmt *f, uint64_t bits)
{
    uint64_t m = low_bits(f, bits);
    uint64_t sb = 1ull << (f->w - 1u);
    return ((m & sb) != 0u ? ~m : (m | sb)) &
           ((f->w == 64u) ? ~0ull : ((1ull << f->w) - 1u));
}

static SeFpRes fp_minmax(const Fmt *f, uint64_t ab, uint64_t bb, bool is_max)
{
    Uf a = fp_unpack(f, ab), b = fp_unpack(f, bb);
    if (a.kind == K_NAN || b.kind == K_NAN) {
        /* 754-2019 minimum/maximum: NaN operands propagate */
        SeFpRes r = res_bits(bits_qnan(f));
        if (a.snan || b.snan)
            r.flags |= FCSR_NV;
        return r;
    }
    if (a.kind == K_ZERO && b.kind == K_ZERO) {
        bool sign = is_max ? (a.sign && b.sign) : (a.sign || b.sign);
        return res_bits(bits_zero(f, sign));
    }
    bool a_lt = ord_key(f, ab) < ord_key(f, bb);
    return res_bits(low_bits(f, (a_lt == is_max) ? bb : ab));
}

SeFpRes se_fp_arith(uint8_t op, unsigned fmtw, uint64_t a, uint64_t b,
                    uint64_t c, unsigned rm)
{
    const Fmt *f = fmt_of(fmtw);
    switch (op) {
    case OPC_FADD:  return fp_addsub(f, a, b, false, rm);
    case OPC_FSUB:  return fp_addsub(f, a, b, true, rm);
    case OPC_FMUL:  return fp_mul(f, a, b, rm);
    case OPC_FDIV:  return fp_div(f, a, b, rm);
    case OPC_FSQRT: return fp_sqrt(f, a, rm);
    case OPC_FMADD: return fp_fmadd(f, a, b, c, rm);
    case OPC_FMIN:  return fp_minmax(f, a, b, false);
    default:
        RW_ASSERT(op == OPC_FMAX);
        return fp_minmax(f, a, b, true);
    }
}

bool se_fp_cmp(uint8_t op, unsigned fmtw, uint64_t a, uint64_t b,
               uint8_t *flags)
{
    const Fmt *f = fmt_of(fmtw);
    Uf ua = fp_unpack(f, a), ub = fp_unpack(f, b);
    if (ua.kind == K_NAN || ub.kind == K_NAN) {
        /* 10.2: NaN compares false; LT/LE raise NV, EQ never */
        if (op != OPC_FCMPEQ)
            *flags |= FCSR_NV;
        return false;
    }
    bool both_zero = ua.kind == K_ZERO && ub.kind == K_ZERO;
    uint64_t ka = ord_key(f, a), kb = ord_key(f, b);
    switch (op) {
    case OPC_FCMPEQ: return both_zero || ka == kb;
    case OPC_FCMPLT: return !both_zero && ka < kb;
    default:
        RW_ASSERT(op == OPC_FCMPLE);
        return both_zero || ka <= kb;
    }
}

/* ------------------------------------------------------- conversions */

SeFpInt se_fp_to_int(unsigned srcfmtw, uint64_t a, unsigned dstw, bool uns)
{
    const Fmt *f = fmt_of(srcfmtw);
    SeFpInt r = { .val = 0u, .flags = 0u };
    Uf u = fp_unpack(f, a);
    se_u128 umax = se_zext(~(se_u128)0, dstw);          /* 2^w - 1 */
    se_u128 smax = (((se_u128)1) << (dstw - 1u)) - 1u;  /* 2^(w-1) - 1 */
    se_u128 nmag = ((se_u128)1) << (dstw - 1u);         /* |signed min| */
    if (u.kind == K_NAN) { /* NaN saturates to the maximum (10.4) */
        r.flags = FCSR_NV;
        r.val = se_canon(uns ? umax : smax, dstw);
        return r;
    }
    if (u.kind == K_INF) {
        r.flags = FCSR_NV;
        if (uns)
            r.val = u.sign ? 0u : se_canon(umax, dstw);
        else
            r.val = se_canon(u.sign ? nmag : smax, dstw);
        return r;
    }
    if (u.kind == K_ZERO)
        return r;
    se_u128 mag = 0u;
    bool inx = false, huge = false;
    unsigned n = msb128(u.mant);
    if (u.exp >= 0) {
        if ((int)n + u.exp >= 128)
            huge = true; /* magnitude >= 2^128: beyond every dstw */
        else
            mag = ((se_u128)u.mant) << (unsigned)u.exp;
    } else {
        unsigned down = (unsigned)-u.exp;
        if (down > n) {
            inx = true; /* |value| < 1 truncates to 0 */
        } else {
            mag = ((se_u128)u.mant) >> down;
            inx = (u.mant & ((1ull << down) - 1u)) != 0u;
        }
    }
    if (uns) {
        if (u.sign) {
            if (huge || mag != 0u) { /* <= -1: below unsigned range */
                r.flags = FCSR_NV;
                return r; /* saturate to 0 */
            }
        } else if (huge || mag > umax) {
            r.flags = FCSR_NV;
            r.val = se_canon(umax, dstw);
            return r;
        }
        r.val = se_canon(mag, dstw);
    } else {
        if (huge || mag > (u.sign ? nmag : smax)) {
            r.flags = FCSR_NV;
            r.val = se_canon(u.sign ? nmag : smax, dstw);
            return r;
        }
        r.val = se_canon(u.sign ? (se_u128)0u - mag : mag, dstw);
    }
    if (inx)
        r.flags |= FCSR_NX;
    return r;
}

SeFpRes se_fp_from_int(se_u128 v, unsigned srcw, bool uns, unsigned dstfmtw,
                       unsigned rm)
{
    const Fmt *f = fmt_of(dstfmtw);
    SeFpRes r = res_bits(0u);
    bool sign = false;
    se_u128 mag;
    if (uns) {
        mag = se_zext(v, srcw);
    } else {
        se_u128 sv = se_sext(v, srcw);
        sign = (se_s128)sv < 0;
        mag = sign ? (se_u128)0u - sv : sv;
    }
    if (mag == 0u) {
        r.bits = bits_zero(f, false);
        return r;
    }
    r.bits = fp_round(f, sign, mag, 0, false, rm, &r.flags);
    return r;
}

SeFpRes se_fp_to_fp(unsigned srcfmtw, uint64_t a, unsigned dstfmtw,
                    unsigned rm)
{
    const Fmt *fs = fmt_of(srcfmtw), *fd = fmt_of(dstfmtw);
    Uf u = fp_unpack(fs, a);
    SeFpRes r = res_bits(0u);
    switch (u.kind) {
    case K_NAN:
        r.bits = bits_qnan(fd);
        if (u.snan)
            r.flags |= FCSR_NV;
        return r;
    case K_INF:
        r.bits = bits_inf(fd, u.sign);
        return r;
    case K_ZERO:
        r.bits = bits_zero(fd, u.sign);
        return r;
    default:
        r.bits = fp_round(fd, u.sign, u.mant, u.exp, false, rm, &r.flags);
        return r;
    }
}
