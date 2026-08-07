#ifndef SE_FP_H
#define SE_FP_H

#include <stdbool.h>
#include <stdint.h>

#include "rw/attrs.h"
#include "rw/newtype.h"
#include "u128.h"

/* Software IEEE 754-2019 binary32/binary64 (ISA-SPEC section 10).
 *
 * Integer-only on purpose: fcsr rounding mode 4 (RMM, round to nearest
 * ties away from zero) has no C99 fenv equivalent, so the host-FP +
 * fesetround route of emu-c-prompt.md cannot express the full fcsr
 * contract. Instead every operation is computed exactly in integer
 * arithmetic and rounded once in software -- all five modes, exact
 * sticky flags, no host-FP dependence at all (which also serves the
 * determinism mandate). See SPEC-ISSUES.md for the enumerated rulings.
 *
 * `fmtw` selects the format by width: 32 or 64. Operand words carry the
 * value in their low fmtw bits; higher bits are ignored (10.1). Flags
 * use the FCSR_* bits of the generated header.
 *
 * The three scalar families at this boundary are newtypes because the
 * FCVT dispatcher derives them all from the same `32 << field` recipe
 * and they must not cross: a format width (32/64, selects binary32/64),
 * an integer width (32/64/128), and an fcsr rounding mode (RM_*). */

RW_NEWTYPE(SeFpFmtW_t, unsigned) /* FP format width: 32 or 64 */
RW_NEWTYPE(SeIntW_t, unsigned)   /* integer width: 32, 64 or 128 */
RW_NEWTYPE(SeFpRm_t, unsigned)   /* rounding mode: RM_RNE..RM_RMM */

typedef struct SeFpRes {
    uint64_t bits; /* result, low fmtw bits significant */
    uint8_t flags; /* FCSR_NV/DZ/OF/UF/NX raised by this op */
} SeFpRes;

typedef struct SeFpInt {
    se_u128 val; /* canonical (sign-extended from dstw, ISA-SPEC 3.4) */
    uint8_t flags;
} SeFpInt;

/* FADD/FSUB/FMUL/FDIV/FSQRT/FMADD/FMIN/FMAX by opcode. `c` is the
 * FMADD addend; FSQRT uses only `a`. rm must be a defined mode
 * (reserved values trap ILLEGAL before execution, 10.3). */
RW_WARN_UNUSED SeFpRes se_fp_arith(uint8_t op, SeFpFmtW_t fmtw, uint64_t a,
                                   uint64_t b, uint64_t c, SeFpRm_t rm);

/* FCMPEQ/FCMPLT/FCMPLE. NaN compares false; LT/LE raise NV on any NaN
 * operand, EQ never does (10.2). */
RW_WARN_UNUSED bool se_fp_cmp(uint8_t op, SeFpFmtW_t fmtw, uint64_t a,
                              uint64_t b, uint8_t *flags);

/* FCVTFI / FCVTFIU: truncate toward zero regardless of fcsr; saturate
 * with NV on out-of-range/inf/NaN (10.4). dstw in {32, 64, 128}. */
RW_WARN_UNUSED SeFpInt se_fp_to_int(SeFpFmtW_t srcfmtw, uint64_t a,
                                    SeIntW_t dstw, bool uns);

/* FCVTIF / FCVTUIF: the low srcw bits of v as a signed/unsigned
 * integer, rounded per rm. srcw in {32, 64, 128}. */
RW_WARN_UNUSED SeFpRes se_fp_from_int(se_u128 v, SeIntW_t srcw, bool uns,
                                      SeFpFmtW_t dstfmtw, SeFpRm_t rm);

/* FCVTFF: 32 <-> 64, rounded per rm (widening is exact). */
RW_WARN_UNUSED SeFpRes se_fp_to_fp(SeFpFmtW_t srcfmtw, uint64_t a,
                                   SeFpFmtW_t dstfmtw, SeFpRm_t rm);

#endif /* SE_FP_H */
