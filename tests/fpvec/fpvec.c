/* fpvec.c — C4 expected-value generator (toolchain-prompt: "generate
 * expected values with a small host C program at build time, commit
 * the generated data file").
 *
 * Emits one vector per line to stdout:
 *     op srcfmt dstfmt rm a b c result flags
 * a/b/c/result are raw bit patterns in 16-digit hex (low bits
 * significant per format; unused operands 0), rm in {rne,rtz,rdn,rup},
 * flags a comma list of NV,DZ,OF,UF,NX or "-".
 *
 * Correctness notes (each a known way to get this wrong):
 * - Compile -O0 -frounding-math; all operands volatile — otherwise the
 *   compiler folds at translation-time RNE and fesetround is a no-op.
 * - RMM is not a C rounding mode; RMM vectors are hand-derived in
 *   gen_c4.py, not here.
 * - NaN results are canonicalized here (0x7fc00000 / 0x7ff8000000000000)
 *   because ISA-SPEC 10.1 requires the canonical quiet NaN; the host's
 *   payload propagation must not leak into the vectors.
 * - fma()/fmaf() are used for FMADD (glibc: correctly rounded, single
 *   rounding); a mul-then-add here would defeat the FMADD vectors.
 * - __int128 -> FP vectors are restricted to exactly-representable
 *   values: libgcc's __floattidf is bound to RNE and would silently
 *   ignore the rounding mode on inexact conversions. Inexact i128
 *   cases are hand-derived in gen_c4.py.
 * - FMIN/FMAX are NOT generated here: C's fmin/fmax implement 754-2008
 *   minNum/maxNum (NaN-favoring the number), while ISA-SPEC 10.2
 *   requires 754-2019 minimum/maximum (NaN-propagating). gen_c4.py
 *   computes those in exact logic.
 * - UF vectors avoid the before/after-rounding tininess edge
 *   (SPEC-ISSUES 13): every UF case here is tiny under both readings.
 *
 * Flag expectations come from fetestexcept on the host; x86-64 and
 * aarch64 agree on all vectors below (tininess edge avoided).
 */

#include <fenv.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#pragma STDC FENV_ACCESS ON

static const struct { int mode; const char *name; } RMS[] = {
    { FE_TONEAREST, "rne" }, { FE_TOWARDZERO, "rtz" },
    { FE_DOWNWARD,  "rdn" }, { FE_UPWARD,     "rup" },
};

static uint32_t f32bits(float f)  { uint32_t u; memcpy(&u, &f, 4); return u; }
static uint64_t f64bits(double d) { uint64_t u; memcpy(&u, &d, 8); return u; }
static float  bits32(uint32_t u)  { float f;  memcpy(&f, &u, 4); return f; }
static double bits64(uint64_t u)  { double d; memcpy(&d, &u, 8); return d; }

static void print_flags(void)
{
    int ex = fetestexcept(FE_ALL_EXCEPT);
    int first = 1;
    if (!ex) { printf("-"); return; }
    /* fixed order NV,DZ,OF,UF,NX; gen_c4.py maps names to bit
     * positions via encoding.py */
    struct { int f; const char *n; } M[] = {
        { FE_INVALID, "NV" }, { FE_DIVBYZERO, "DZ" },
        { FE_OVERFLOW, "OF" }, { FE_UNDERFLOW, "UF" },
        { FE_INEXACT, "NX" },
    };
    for (unsigned i = 0; i < 5; i++)
        if (ex & M[i].f) { printf(first ? "%s" : ",%s", M[i].n); first = 0; }
}

static void emit(const char *op, const char *sf, const char *df,
                 const char *rm, uint64_t a, uint64_t b, uint64_t c,
                 uint64_t res)
{
    printf("%s %s %s %s %016llx %016llx %016llx %016llx ",
           op, sf, df, rm, (unsigned long long)a, (unsigned long long)b,
           (unsigned long long)c, (unsigned long long)res);
    print_flags();
    printf("\n");
}

/* ---------------------------------------------------------------- f32 */

struct v32 { const char *op; const char *rm; uint32_t a, b, c; };

static const struct v32 V32[] = {
    /* FADD: exact, tie-to-even at every settable mode, zeros, inf-inf,
     * qNaN propagation, overflow incl. directed-mode max-finite,
     * exact subnormal sum (no flush, no UF when exact) */
    { "fadd", "rne", 0x3F800000, 0x40000000, 0 },  /* 1+2 = 3 exact */
    { "fadd", "rne", 0x3F800000, 0x33800000, 0 },  /* 1 + 2^-24 tie */
    { "fadd", "rup", 0x3F800000, 0x33800000, 0 },
    { "fadd", "rdn", 0x3F800000, 0x33800000, 0 },
    { "fadd", "rtz", 0x3F800000, 0x33800000, 0 },
    { "fadd", "rne", 0x00000000, 0x80000000, 0 },  /* +0 + -0 = +0 */
    { "fadd", "rdn", 0x00000000, 0x80000000, 0 },  /* ... = -0 under RDN */
    { "fadd", "rne", 0x80000000, 0x80000000, 0 },  /* -0 + -0 = -0 */
    { "fadd", "rne", 0x7F800000, 0xFF800000, 0 },  /* inf + -inf: NV */
    { "fadd", "rne", 0x7FC00000, 0x3F800000, 0 },  /* qNaN + 1: no NV */
    { "fadd", "rne", 0x7F7FFFFF, 0x7F7FFFFF, 0 },  /* OF -> +inf */
    { "fadd", "rdn", 0x7F7FFFFF, 0x7F7FFFFF, 0 },  /* OF -> maxfinite */
    { "fadd", "rne", 0x00000001, 0x00000002, 0 },  /* subnormal exact */
    /* FSUB: cancellation exact, inf - inf via a-b, rounding down a ulp */
    { "fsub", "rne", 0x40400000, 0x40400000, 0 },  /* 3-3 = +0 */
    { "fsub", "rdn", 0x40400000, 0x40400000, 0 },  /* 3-3 = -0 under RDN */
    { "fsub", "rne", 0x7F800000, 0x7F800000, 0 },  /* inf-inf: NV */
    { "fsub", "rne", 0x3F800000, 0x33000000, 0 },  /* 1 - 2^-25 */
    /* FMUL: exact, exact subnormal result, halfway-into-subnormal (UF),
     * overflow, inf*0 */
    { "fmul", "rne", 0x40400000, 0x40400000, 0 },  /* 3*3 = 9 */
    { "fmul", "rne", 0x00800000, 0x3E800000, 0 },  /* minnorm*0.25 exact
                                                    * subnormal: no UF */
    { "fmul", "rne", 0x00000001, 0x3F000000, 0 },  /* minsub*0.5: UF|NX */
    { "fmul", "rne", 0x7F000000, 0x7F000000, 0 },  /* OF */
    { "fmul", "rne", 0x7F800000, 0x00000000, 0 },  /* inf*0: NV */
    /* FDIV: mode-distinguishing 1/3 incl. negatives, DZ, 0/0, exact */
    { "fdiv", "rne", 0x3F800000, 0x40400000, 0 },
    { "fdiv", "rtz", 0x3F800000, 0x40400000, 0 },
    { "fdiv", "rdn", 0x3F800000, 0x40400000, 0 },
    { "fdiv", "rup", 0x3F800000, 0x40400000, 0 },
    { "fdiv", "rdn", 0xBF800000, 0x40400000, 0 },
    { "fdiv", "rup", 0xBF800000, 0x40400000, 0 },
    { "fdiv", "rne", 0x3F800000, 0x00000000, 0 },  /* 1/0: DZ, +inf */
    { "fdiv", "rne", 0xBF800000, 0x00000000, 0 },  /* -1/0: DZ, -inf */
    { "fdiv", "rne", 0x00000000, 0x00000000, 0 },  /* 0/0: NV, qNaN */
    { "fdiv", "rne", 0x40C00000, 0x40000000, 0 },  /* 6/2 = 3 exact */
    /* FSQRT */
    { "fsqrt", "rne", 0x40800000, 0, 0 },          /* sqrt(4) = 2 */
    { "fsqrt", "rne", 0x40000000, 0, 0 },          /* sqrt(2): NX */
    { "fsqrt", "rtz", 0x40000000, 0, 0 },
    { "fsqrt", "rne", 0xBF800000, 0, 0 },          /* sqrt(-1): NV */
    { "fsqrt", "rne", 0x80000000, 0, 0 },          /* sqrt(-0) = -0 */
    { "fsqrt", "rne", 0x7F800000, 0, 0 },          /* sqrt(inf) = inf */
    /* FMADD: the single-rounding distinguisher —
     * (1+2^-12)(1-2^-12) - 1 = -2^-24 exactly; separate mul rounds
     * the product to 1.0 and would give -0 */
    { "fmadd", "rne", 0x3F800800, 0x3F7FF000, 0xBF800000 },
    { "fmadd", "rne", 0x40000000, 0x40400000, 0x40800000 }, /* 2*3+4 */
    { "fmadd", "rne", 0x7F800000, 0x00000000, 0x3F800000 }, /* inf*0+1: NV */
    { "fmadd", "rne", 0x7FC00000, 0x3F800000, 0x3F800000 }, /* qNaN in */
};

/* ---------------------------------------------------------------- f64 */

struct v64 { const char *op; const char *rm; uint64_t a, b, c; };

static const struct v64 V64[] = {
    { "fadd", "rne", 0x3FF0000000000000, 0x4000000000000000, 0 },
    { "fadd", "rne", 0x3FF0000000000000, 0x3CA0000000000000, 0 }, /* tie */
    { "fadd", "rup", 0x3FF0000000000000, 0x3CA0000000000000, 0 },
    { "fadd", "rne", 0x7FF0000000000000, 0xFFF0000000000000, 0 }, /* NV */
    { "fadd", "rne", 0x7FF8000000000000, 0x3FF0000000000000, 0 },
    { "fadd", "rne", 0x7FEFFFFFFFFFFFFF, 0x7FEFFFFFFFFFFFFF, 0 }, /* OF */
    { "fadd", "rtz", 0x7FEFFFFFFFFFFFFF, 0x7FEFFFFFFFFFFFFF, 0 },
    { "fadd", "rne", 0x0000000000000001, 0x0000000000000002, 0 },
    { "fsub", "rne", 0x3FF0000000000000, 0x3C90000000000000, 0 },
    { "fmul", "rne", 0x0010000000000000, 0x3FD0000000000000, 0 },
    { "fmul", "rne", 0x0000000000000001, 0x3FE0000000000000, 0 }, /* UF|NX */
    { "fmul", "rne", 0x7FE0000000000000, 0x7FE0000000000000, 0 }, /* OF */
    { "fdiv", "rne", 0x3FF0000000000000, 0x4008000000000000, 0 },
    { "fdiv", "rtz", 0x3FF0000000000000, 0x4008000000000000, 0 },
    { "fdiv", "rdn", 0x3FF0000000000000, 0x4008000000000000, 0 },
    { "fdiv", "rup", 0x3FF0000000000000, 0x4008000000000000, 0 },
    { "fdiv", "rne", 0x3FF0000000000000, 0x0000000000000000, 0 }, /* DZ */
    { "fdiv", "rne", 0x0000000000000000, 0x0000000000000000, 0 }, /* NV */
    { "fsqrt", "rne", 0x4000000000000000, 0, 0 },
    { "fsqrt", "rne", 0xBFF0000000000000, 0, 0 },
    /* (1+2^-30)(1-2^-30) - 1 = -2^-60 exactly under fma */
    { "fmadd", "rne", 0x3FF0000000400000, 0x3FEFFFFFFF800000,
                      0xBFF0000000000000 },
    { "fmadd", "rne", 0x7FF0000000000000, 0x0000000000000000,
                      0x3FF0000000000000 },                       /* NV */
};

/* ---------------------------------------------------------- conversions */

static float run32(const char *op, float a, float b, float c)
{
    if (!strcmp(op, "fadd"))  return a + b;
    if (!strcmp(op, "fsub"))  return a - b;
    if (!strcmp(op, "fmul"))  return a * b;
    if (!strcmp(op, "fdiv"))  return a / b;
    if (!strcmp(op, "fsqrt")) return sqrtf(a);
    if (!strcmp(op, "fmadd")) return fmaf(a, b, c);
    fprintf(stderr, "fpvec: bad op %s\n", op);
    __builtin_trap();
}

static double run64(const char *op, double a, double b, double c)
{
    if (!strcmp(op, "fadd"))  return a + b;
    if (!strcmp(op, "fsub"))  return a - b;
    if (!strcmp(op, "fmul"))  return a * b;
    if (!strcmp(op, "fdiv"))  return a / b;
    if (!strcmp(op, "fsqrt")) return sqrt(a);
    if (!strcmp(op, "fmadd")) return fma(a, b, c);
    fprintf(stderr, "fpvec: bad op %s\n", op);
    __builtin_trap();
}

static int set_rm(const char *rm)
{
    for (unsigned i = 0; i < 4; i++)
        if (!strcmp(RMS[i].name, rm)) return fesetround(RMS[i].mode);
    fprintf(stderr, "fpvec: bad rm %s\n", rm);
    __builtin_trap();
}

int main(void)
{
    printf("# fpvec.dat — GENERATED by tests/fpvec/fpvec.c — DO NOT EDIT\n");
    printf("# op srcfmt dstfmt rm a b c result flags\n");

    for (unsigned i = 0; i < sizeof V32 / sizeof V32[0]; i++) {
        volatile float a = bits32(V32[i].a), b = bits32(V32[i].b),
                       c = bits32(V32[i].c);
        set_rm(V32[i].rm);
        feclearexcept(FE_ALL_EXCEPT);
        volatile float r = run32(V32[i].op, a, b, c);
        uint32_t rb = f32bits(r);
        if (isnan(r)) rb = 0x7FC00000u;        /* canonical qNaN */
        emit(V32[i].op, "f32", "f32", V32[i].rm,
             V32[i].a, V32[i].b, V32[i].c, rb);
    }
    for (unsigned i = 0; i < sizeof V64 / sizeof V64[0]; i++) {
        volatile double a = bits64(V64[i].a), b = bits64(V64[i].b),
                        c = bits64(V64[i].c);
        set_rm(V64[i].rm);
        feclearexcept(FE_ALL_EXCEPT);
        volatile double r = run64(V64[i].op, a, b, c);
        uint64_t rb = f64bits(r);
        if (isnan(r)) rb = 0x7FF8000000000000ull;
        emit(V64[i].op, "f64", "f64", V64[i].rm,
             V64[i].a, V64[i].b, V64[i].c, rb);
    }

    /* FCVTIF: signed int -> FP, rounds per fcsr */
    {
        static const struct { const char *rm; int32_t v; } t[] = {
            { "rne", 16777217 },      /* 2^24+1 -> f32: rounds */
            { "rup", 16777217 },
            { "rtz", -16777217 },
            { "rne", -7 },
        };
        for (unsigned i = 0; i < sizeof t / sizeof t[0]; i++) {
            volatile int32_t v = t[i].v;
            set_rm(t[i].rm); feclearexcept(FE_ALL_EXCEPT);
            volatile float r = (float)v;
            emit("fcvtif", "i32", "f32", t[i].rm,
                 (uint32_t)v, 0, 0, f32bits(r));
        }
        static const struct { const char *rm; int64_t v; } s[] = {
            { "rne", 0x7FFFFFFFFFFFFFFF },  /* -> f64 rounds up to 2^63 */
            { "rtz", 0x7FFFFFFFFFFFFFFF },  /* -> largest f64 < 2^63 */
            { "rne", -1 },
            { "rne", 1 },
        };
        for (unsigned i = 0; i < sizeof s / sizeof s[0]; i++) {
            volatile int64_t v = s[i].v;
            set_rm(s[i].rm); feclearexcept(FE_ALL_EXCEPT);
            volatile double r = (double)v;
            emit("fcvtif", "i64", "f64", s[i].rm,
                 (uint64_t)v, 0, 0, f64bits(r));
        }
        /* i64 -> f32: doubly narrowing */
        {
            volatile int64_t v = 0x0000000100000001; /* 2^32+1 */
            fesetround(FE_TONEAREST); feclearexcept(FE_ALL_EXCEPT);
            volatile float r = (float)v;
            emit("fcvtif", "i64", "f32", "rne",
                 (uint64_t)v, 0, 0, f32bits(r));
        }
        /* i128 -> FP: exact values only (libgcc RNE binding, header) */
        {
            volatile __int128 v = (__int128)1 << 100;
            fesetround(FE_TONEAREST); feclearexcept(FE_ALL_EXCEPT);
            volatile double r = (double)v;
            /* i128 sources: a = high 64 bits, b = low 64 bits */
            emit("fcvtif", "i128", "f64", "rne",
                 (uint64_t)((unsigned __int128)v >> 64),
                 (uint64_t)(unsigned __int128)v, 0, f64bits(r));
            v = -v;
            fesetround(FE_TONEAREST); feclearexcept(FE_ALL_EXCEPT);
            volatile double r2 = (double)v;
            emit("fcvtif", "i128", "f64", "rne",
                 (uint64_t)((unsigned __int128)v >> 64),
                 (uint64_t)(unsigned __int128)v, 0, f64bits(r2));
        }
    }

    /* FCVTUIF: unsigned int -> FP */
    {
        {
            volatile uint32_t v = 0xFFFFFFFFu;
            fesetround(FE_TONEAREST); feclearexcept(FE_ALL_EXCEPT);
            volatile float r = (float)v;
            emit("fcvtuif", "i32", "f32", "rne", v, 0, 0, f32bits(r));
            fesetround(FE_TONEAREST); feclearexcept(FE_ALL_EXCEPT);
            volatile double r2 = (double)v;
            emit("fcvtuif", "i32", "f64", "rne", v, 0, 0, f64bits(r2));
        }
        {
            volatile uint64_t v = 0xFFFFFFFFFFFFFFFFull;
            fesetround(FE_TONEAREST); feclearexcept(FE_ALL_EXCEPT);
            volatile float r = (float)v;
            emit("fcvtuif", "i64", "f32", "rne", v, 0, 0, f32bits(r));
            fesetround(FE_TOWARDZERO); feclearexcept(FE_ALL_EXCEPT);
            volatile double r2 = (double)v;
            emit("fcvtuif", "i64", "f64", "rtz", v, 0, 0, f64bits(r2));
        }
        {   /* the sign-bit pattern that a signed-conversion bug flips */
            volatile uint64_t v = 0x8000000000000000ull;
            fesetround(FE_TONEAREST); feclearexcept(FE_ALL_EXCEPT);
            volatile double r = (double)v;
            emit("fcvtuif", "i64", "f64", "rne", v, 0, 0, f64bits(r));
        }
    }

    /* FCVTFF */
    {
        static const struct { const char *rm; uint32_t v; } up[] = {
            { "rne", 0x3FC00000 },   /* 1.5: exact widen */
            { "rne", 0x7FC00000 },   /* qNaN -> canonical f64 qNaN */
            { "rne", 0x00000001 },   /* f32 min subnormal: exact widen */
            { "rne", 0xFF800000 },   /* -inf */
        };
        for (unsigned i = 0; i < sizeof up / sizeof up[0]; i++) {
            volatile float f = bits32(up[i].v);
            set_rm(up[i].rm); feclearexcept(FE_ALL_EXCEPT);
            volatile double r = (double)f;
            uint64_t rb = f64bits(r);
            if (isnan(r)) rb = 0x7FF8000000000000ull;
            emit("fcvtff", "f32", "f64", up[i].rm, up[i].v, 0, 0, rb);
        }
        static const struct { const char *rm; uint64_t v; } dn[] = {
            { "rne", 0x4008000000000000 },  /* 3.0 exact narrow */
            { "rne", 0x3FF0000000000001 },  /* 1+2^-52: NX */
            { "rne", 0x7E37E43C8800759C },  /* 1e300: OF -> inf */
            { "rtz", 0x7E37E43C8800759C },  /* 1e300: OF -> maxfinite */
            { "rne", 0x7FF8000000000000 },  /* qNaN */
            { "rne", 0x0000000010000000 },  /* ~1.3e-315: UF -> 0 */
            { "rne", 0x37B0000000000001 },  /* 2^-132*(1+2^-52): UF|NX ->
                                             * f32 subnormal 2^-132 */
        };
        for (unsigned i = 0; i < sizeof dn / sizeof dn[0]; i++) {
            volatile double d = bits64(dn[i].v);
            set_rm(dn[i].rm); feclearexcept(FE_ALL_EXCEPT);
            volatile float r = (float)d;
            uint32_t rb = f32bits(r);
            if (isnan(r)) rb = 0x7FC00000u;
            emit("fcvtff", "f64", "f32", dn[i].rm, dn[i].v, 0, 0, rb);
        }
    }

    fesetround(FE_TONEAREST);
    return 0;
}
