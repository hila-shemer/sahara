#ifndef SE_U128_H
#define SE_U128_H

#include <stdint.h>

/* 128-bit machine words. The guest is a 128-bit machine; unsigned
 * __int128 is the natural host representation (emu-c-prompt.md). These
 * are value helpers, not domain newtypes: register values, addresses,
 * and immediates all flow through the same arithmetic core, and the
 * wrap/unwrap friction of a newtype would fight the clarity mandate.
 * Domain separation lives at the API boundaries (SeMem, SeCpu, SeTrace)
 * instead. */
typedef unsigned __int128 se_u128;
typedef __int128 se_s128;

static inline uint64_t se_lo64(se_u128 v) { return (uint64_t)v; }
static inline uint64_t se_hi64(se_u128 v) { return (uint64_t)(v >> 64); }
static inline se_u128 se_make128(uint64_t hi, uint64_t lo)
{
    return ((se_u128)hi << 64) | (se_u128)lo;
}

/* Zero-extend from the low `bits` bits (bits in 1..128). */
static inline se_u128 se_zext(se_u128 v, unsigned bits)
{
    if (bits >= 128u)
        return v;
    return v & ((((se_u128)1) << bits) - 1u);
}

/* Sign-extend from bit (bits-1) (bits in 1..128). */
static inline se_u128 se_sext(se_u128 v, unsigned bits)
{
    if (bits >= 128u)
        return v;
    se_u128 sign = ((se_u128)1) << (bits - 1u);
    return (se_zext(v, bits) ^ sign) - sign;
}

/* Canonical form (ISA-SPEC 3.4): a w-bit result is sign-extended from
 * bit w-1 to 128 bits, for signed and unsigned operations alike. */
static inline se_u128 se_canon(se_u128 v, unsigned w)
{
    return se_sext(v, w);
}

/* High half of the unsigned 128x128->256 product (MULHU at width 128).
 * Schoolbook over 64-bit limbs; checked against Python bigints by the
 * unit tests and the CI script. */
static inline se_u128 se_mulhu128(se_u128 a, se_u128 b)
{
    uint64_t a0 = se_lo64(a), a1 = se_hi64(a);
    uint64_t b0 = se_lo64(b), b1 = se_hi64(b);
    se_u128 p00 = (se_u128)a0 * b0;
    se_u128 p01 = (se_u128)a0 * b1;
    se_u128 p10 = (se_u128)a1 * b0;
    se_u128 p11 = (se_u128)a1 * b1;
    /* carry out of bits [64,128) of the full product */
    se_u128 mid = (se_u128)se_hi64(p00) + (se_u128)se_lo64(p01)
                + (se_u128)se_lo64(p10);
    return p11 + (se_u128)se_hi64(p01) + (se_u128)se_hi64(p10)
               + (se_u128)se_hi64(mid);
}

/* High half of the signed 128x128->256 product (MULH at width 128):
 * unsigned high half plus the two's-complement correction. */
static inline se_u128 se_mulhs128(se_u128 a, se_u128 b)
{
    se_u128 hi = se_mulhu128(a, b);
    if ((se_s128)a < 0)
        hi -= b;
    if ((se_s128)b < 0)
        hi -= a;
    return hi;
}

#endif /* SE_U128_H */
