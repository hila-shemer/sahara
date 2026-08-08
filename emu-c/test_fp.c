/* Directed known-answer tests for the software FP core (fp.c).
 *
 * Vector provenance: every row's expected bits and flags were computed
 * by emu-c/test/fp_oracle.py, the exact-rational IEEE 754-2019
 * reference (itself sanity-checked against host-hardware doubles at
 * RNE). The image-level suite (run_tests.py) re-derives all of these
 * plus randomized vectors from the same oracle through the full
 * instruction path; this table pins the library API directly. */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#include "fp.h"
#include "gen/sahara_isa.h"
#include "rwc/status.h"

static const struct {
    uint8_t op; unsigned w, rm;
    uint64_t a, b, c, want; uint8_t flags;
} ARITH[] = {
    { OPC_FADD, 32u, RM_RNE, 0x3f800000u, 0x40000000u, 0x0u, 0x40400000u, 0x00u },
    { OPC_FADD, 32u, RM_RNE, 0x3dcccccdu, 0x3e4ccccdu, 0x0u, 0x3e99999au, 0x10u },
    { OPC_FADD, 32u, RM_RNE, 0x3f800000u, 0x33800000u, 0x0u, 0x3f800000u, 0x10u },
    { OPC_FADD, 32u, RM_RNE, 0x3f800000u, 0xb3800000u, 0x0u, 0x3f7fffffu, 0x00u },
    { OPC_FADD, 32u, RM_RTZ, 0x3f800000u, 0x33800000u, 0x0u, 0x3f800000u, 0x10u },
    { OPC_FADD, 32u, RM_RTZ, 0x3f800000u, 0xb3800000u, 0x0u, 0x3f7fffffu, 0x00u },
    { OPC_FADD, 32u, RM_RDN, 0x3f800000u, 0x33800000u, 0x0u, 0x3f800000u, 0x10u },
    { OPC_FADD, 32u, RM_RDN, 0x3f800000u, 0xb3800000u, 0x0u, 0x3f7fffffu, 0x00u },
    { OPC_FADD, 32u, RM_RUP, 0x3f800000u, 0x33800000u, 0x0u, 0x3f800001u, 0x10u },
    { OPC_FADD, 32u, RM_RUP, 0x3f800000u, 0xb3800000u, 0x0u, 0x3f7fffffu, 0x00u },
    { OPC_FADD, 32u, RM_RMM, 0x3f800000u, 0x33800000u, 0x0u, 0x3f800001u, 0x10u },
    { OPC_FADD, 32u, RM_RMM, 0x3f800000u, 0xb3800000u, 0x0u, 0x3f7fffffu, 0x00u },
    { OPC_FADD, 32u, RM_RNE, 0x7f7fffffu, 0x7f7fffffu, 0x0u, 0x7f800000u, 0x14u },
    { OPC_FADD, 32u, RM_RTZ, 0x7f7fffffu, 0x7f7fffffu, 0x0u, 0x7f7fffffu, 0x14u },
    { OPC_FADD, 32u, RM_RNE, 0x3f800000u, 0xbf800000u, 0x0u, 0x0u, 0x00u },
    { OPC_FADD, 32u, RM_RDN, 0x3f800000u, 0xbf800000u, 0x0u, 0x80000000u, 0x00u },
    { OPC_FADD, 32u, RM_RNE, 0x0u, 0x80000000u, 0x0u, 0x0u, 0x00u },
    { OPC_FADD, 32u, RM_RDN, 0x0u, 0x80000000u, 0x0u, 0x80000000u, 0x00u },
    { OPC_FADD, 32u, RM_RNE, 0x7f800000u, 0xff800000u, 0x0u, 0x7fc00000u, 0x01u },
    { OPC_FADD, 32u, RM_RNE, 0x7f800001u, 0x3f800000u, 0x0u, 0x7fc00000u, 0x01u },
    { OPC_FADD, 32u, RM_RNE, 0x7fc00000u, 0x3f800000u, 0x0u, 0x7fc00000u, 0x00u },
    { OPC_FADD, 32u, RM_RNE, 0x1u, 0x1u, 0x0u, 0x2u, 0x00u },
    { OPC_FADD, 32u, RM_RNE, 0x800000u, 0x80000001u, 0x0u, 0x7fffffu, 0x00u },
    { OPC_FSUB, 32u, RM_RDN, 0x3f800000u, 0x3f800000u, 0x0u, 0x80000000u, 0x00u },
    { OPC_FSUB, 32u, RM_RNE, 0x3e4ccccdu, 0x3dcccccdu, 0x0u, 0x3dcccccdu, 0x00u },
    { OPC_FMUL, 32u, RM_RNE, 0x3dcccccdu, 0x3e4ccccdu, 0x0u, 0x3ca3d70bu, 0x10u },
    { OPC_FMUL, 32u, RM_RNE, 0x1u, 0x3f000000u, 0x0u, 0x0u, 0x18u },
    { OPC_FMUL, 32u, RM_RMM, 0x1u, 0x3f000000u, 0x0u, 0x1u, 0x18u },
    { OPC_FMUL, 32u, RM_RNE, 0x7f7fffffu, 0x40000000u, 0x0u, 0x7f800000u, 0x14u },
    { OPC_FMUL, 32u, RM_RNE, 0x7f800000u, 0x0u, 0x0u, 0x7fc00000u, 0x01u },
    { OPC_FDIV, 32u, RM_RNE, 0x3f800000u, 0x40400000u, 0x0u, 0x3eaaaaabu, 0x10u },
    { OPC_FDIV, 32u, RM_RNE, 0x3f800000u, 0x0u, 0x0u, 0x7f800000u, 0x02u },
    { OPC_FDIV, 32u, RM_RNE, 0x0u, 0x0u, 0x0u, 0x7fc00000u, 0x01u },
    { OPC_FDIV, 32u, RM_RNE, 0x3f800000u, 0x1u, 0x0u, 0x7f800000u, 0x14u },
    { OPC_FDIV, 32u, RM_RNE, 0x1u, 0x40400000u, 0x0u, 0x0u, 0x18u },
    { OPC_FSQRT, 32u, RM_RNE, 0x40800000u, 0x0u, 0x0u, 0x40000000u, 0x00u },
    { OPC_FSQRT, 32u, RM_RNE, 0x40000000u, 0x0u, 0x0u, 0x3fb504f3u, 0x10u },
    { OPC_FSQRT, 32u, RM_RNE, 0xbf800000u, 0x0u, 0x0u, 0x7fc00000u, 0x01u },
    { OPC_FSQRT, 32u, RM_RNE, 0x80000000u, 0x0u, 0x0u, 0x80000000u, 0x00u },
    { OPC_FSQRT, 32u, RM_RNE, 0x1u, 0x0u, 0x0u, 0x1a3504f3u, 0x10u },
    { OPC_FMIN, 32u, RM_RNE, 0x0u, 0x80000000u, 0x0u, 0x80000000u, 0x00u },
    { OPC_FMAX, 32u, RM_RNE, 0x0u, 0x80000000u, 0x0u, 0x0u, 0x00u },
    { OPC_FMIN, 32u, RM_RNE, 0x3f800000u, 0x7fc00000u, 0x0u, 0x7fc00000u, 0x00u },
    { OPC_FMIN, 32u, RM_RNE, 0x3f800000u, 0x7f800001u, 0x0u, 0x7fc00000u, 0x01u },
    { OPC_FMIN, 32u, RM_RNE, 0x3f800000u, 0x40000000u, 0x0u, 0x3f800000u, 0x00u },
    { OPC_FMAX, 32u, RM_RNE, 0xbf800000u, 0xc0000000u, 0x0u, 0xbf800000u, 0x00u },
    { OPC_FADD, 64u, RM_RNE, 0x3ff0000000000000u, 0x4000000000000000u, 0x0u, 0x4008000000000000u, 0x00u },
    { OPC_FADD, 64u, RM_RNE, 0x3fb999999999999au, 0x3fc999999999999au, 0x0u, 0x3fd3333333333334u, 0x10u },
    { OPC_FADD, 64u, RM_RNE, 0x3ff0000000000000u, 0x3ca0000000000000u, 0x0u, 0x3ff0000000000000u, 0x10u },
    { OPC_FADD, 64u, RM_RNE, 0x3ff0000000000000u, 0xbca0000000000000u, 0x0u, 0x3fefffffffffffffu, 0x00u },
    { OPC_FADD, 64u, RM_RTZ, 0x3ff0000000000000u, 0x3ca0000000000000u, 0x0u, 0x3ff0000000000000u, 0x10u },
    { OPC_FADD, 64u, RM_RTZ, 0x3ff0000000000000u, 0xbca0000000000000u, 0x0u, 0x3fefffffffffffffu, 0x00u },
    { OPC_FADD, 64u, RM_RDN, 0x3ff0000000000000u, 0x3ca0000000000000u, 0x0u, 0x3ff0000000000000u, 0x10u },
    { OPC_FADD, 64u, RM_RDN, 0x3ff0000000000000u, 0xbca0000000000000u, 0x0u, 0x3fefffffffffffffu, 0x00u },
    { OPC_FADD, 64u, RM_RUP, 0x3ff0000000000000u, 0x3ca0000000000000u, 0x0u, 0x3ff0000000000001u, 0x10u },
    { OPC_FADD, 64u, RM_RUP, 0x3ff0000000000000u, 0xbca0000000000000u, 0x0u, 0x3fefffffffffffffu, 0x00u },
    { OPC_FADD, 64u, RM_RMM, 0x3ff0000000000000u, 0x3ca0000000000000u, 0x0u, 0x3ff0000000000001u, 0x10u },
    { OPC_FADD, 64u, RM_RMM, 0x3ff0000000000000u, 0xbca0000000000000u, 0x0u, 0x3fefffffffffffffu, 0x00u },
    { OPC_FADD, 64u, RM_RNE, 0x7fefffffffffffffu, 0x7fefffffffffffffu, 0x0u, 0x7ff0000000000000u, 0x14u },
    { OPC_FADD, 64u, RM_RTZ, 0x7fefffffffffffffu, 0x7fefffffffffffffu, 0x0u, 0x7fefffffffffffffu, 0x14u },
    { OPC_FADD, 64u, RM_RNE, 0x3ff0000000000000u, 0xbff0000000000000u, 0x0u, 0x0u, 0x00u },
    { OPC_FADD, 64u, RM_RDN, 0x3ff0000000000000u, 0xbff0000000000000u, 0x0u, 0x8000000000000000u, 0x00u },
    { OPC_FADD, 64u, RM_RNE, 0x0u, 0x8000000000000000u, 0x0u, 0x0u, 0x00u },
    { OPC_FADD, 64u, RM_RDN, 0x0u, 0x8000000000000000u, 0x0u, 0x8000000000000000u, 0x00u },
    { OPC_FADD, 64u, RM_RNE, 0x7ff0000000000000u, 0xfff0000000000000u, 0x0u, 0x7ff8000000000000u, 0x01u },
    { OPC_FADD, 64u, RM_RNE, 0x7ff0000000000001u, 0x3ff0000000000000u, 0x0u, 0x7ff8000000000000u, 0x01u },
    { OPC_FADD, 64u, RM_RNE, 0x7ff8000000000000u, 0x3ff0000000000000u, 0x0u, 0x7ff8000000000000u, 0x00u },
    { OPC_FADD, 64u, RM_RNE, 0x1u, 0x1u, 0x0u, 0x2u, 0x00u },
    { OPC_FADD, 64u, RM_RNE, 0x10000000000000u, 0x8000000000000001u, 0x0u, 0xfffffffffffffu, 0x00u },
    { OPC_FSUB, 64u, RM_RDN, 0x3ff0000000000000u, 0x3ff0000000000000u, 0x0u, 0x8000000000000000u, 0x00u },
    { OPC_FSUB, 64u, RM_RNE, 0x3fc999999999999au, 0x3fb999999999999au, 0x0u, 0x3fb999999999999au, 0x00u },
    { OPC_FMUL, 64u, RM_RNE, 0x3fb999999999999au, 0x3fc999999999999au, 0x0u, 0x3f947ae147ae147cu, 0x10u },
    { OPC_FMUL, 64u, RM_RNE, 0x1u, 0x3fe0000000000000u, 0x0u, 0x0u, 0x18u },
    { OPC_FMUL, 64u, RM_RMM, 0x1u, 0x3fe0000000000000u, 0x0u, 0x1u, 0x18u },
    { OPC_FMUL, 64u, RM_RNE, 0x7fefffffffffffffu, 0x4000000000000000u, 0x0u, 0x7ff0000000000000u, 0x14u },
    { OPC_FMUL, 64u, RM_RNE, 0x7ff0000000000000u, 0x0u, 0x0u, 0x7ff8000000000000u, 0x01u },
    { OPC_FDIV, 64u, RM_RNE, 0x3ff0000000000000u, 0x4008000000000000u, 0x0u, 0x3fd5555555555555u, 0x10u },
    { OPC_FDIV, 64u, RM_RNE, 0x3ff0000000000000u, 0x0u, 0x0u, 0x7ff0000000000000u, 0x02u },
    { OPC_FDIV, 64u, RM_RNE, 0x0u, 0x0u, 0x0u, 0x7ff8000000000000u, 0x01u },
    { OPC_FDIV, 64u, RM_RNE, 0x3ff0000000000000u, 0x1u, 0x0u, 0x7ff0000000000000u, 0x14u },
    { OPC_FDIV, 64u, RM_RNE, 0x1u, 0x4008000000000000u, 0x0u, 0x0u, 0x18u },
    { OPC_FSQRT, 64u, RM_RNE, 0x4010000000000000u, 0x0u, 0x0u, 0x4000000000000000u, 0x00u },
    { OPC_FSQRT, 64u, RM_RNE, 0x4000000000000000u, 0x0u, 0x0u, 0x3ff6a09e667f3bcdu, 0x10u },
    { OPC_FSQRT, 64u, RM_RNE, 0xbff0000000000000u, 0x0u, 0x0u, 0x7ff8000000000000u, 0x01u },
    { OPC_FSQRT, 64u, RM_RNE, 0x8000000000000000u, 0x0u, 0x0u, 0x8000000000000000u, 0x00u },
    { OPC_FSQRT, 64u, RM_RNE, 0x1u, 0x0u, 0x0u, 0x1e60000000000000u, 0x00u },
    { OPC_FMIN, 64u, RM_RNE, 0x0u, 0x8000000000000000u, 0x0u, 0x8000000000000000u, 0x00u },
    { OPC_FMAX, 64u, RM_RNE, 0x0u, 0x8000000000000000u, 0x0u, 0x0u, 0x00u },
    { OPC_FMIN, 64u, RM_RNE, 0x3ff0000000000000u, 0x7ff8000000000000u, 0x0u, 0x7ff8000000000000u, 0x00u },
    { OPC_FMIN, 64u, RM_RNE, 0x3ff0000000000000u, 0x7ff0000000000001u, 0x0u, 0x7ff8000000000000u, 0x01u },
    { OPC_FMIN, 64u, RM_RNE, 0x3ff0000000000000u, 0x4000000000000000u, 0x0u, 0x3ff0000000000000u, 0x00u },
    { OPC_FMAX, 64u, RM_RNE, 0xbff0000000000000u, 0xc000000000000000u, 0x0u, 0xbff0000000000000u, 0x00u },
    { OPC_FMADD, 64u, RM_RNE, 0x3ff0000000000001u, 0x3ff0000000000001u, 0xbff0000000000002u, 0x3970000000000000u, 0x00u },
    { OPC_FMADD, 32u, RM_RNE, 0x3f800001u, 0x3f800001u, 0xbf800002u, 0x28800000u, 0x00u },
    { OPC_FMADD, 64u, RM_RNE, 0x0u, 0x7ff0000000000000u, 0x7ff8000000000000u, 0x7ff8000000000000u, 0x01u },
    { OPC_FMADD, 64u, RM_RNE, 0x7ff0000000000000u, 0x3ff0000000000000u, 0xfff0000000000000u, 0x7ff8000000000000u, 0x01u },
    { OPC_FMADD, 64u, RM_RNE, 0x3ff0000000000000u, 0x3ff0000000000000u, 0xbff0000000000000u, 0x0u, 0x00u },
    { OPC_FMADD, 64u, RM_RDN, 0x3ff0000000000000u, 0x3ff0000000000000u, 0xbff0000000000000u, 0x8000000000000000u, 0x00u },
    { OPC_FMADD, 64u, RM_RNE, 0x4008000000000000u, 0x4014000000000000u, 0x401c000000000000u, 0x4036000000000000u, 0x00u },
    { OPC_FMADD, 32u, RM_RNE, 0x40400000u, 0x40a00000u, 0xc0e00000u, 0x41000000u, 0x00u },
    { OPC_FMADD, 64u, RM_RNE, 0x1u, 0x3fe0000000000000u, 0x1u, 0x2u, 0x18u },
};

static const struct {
    uint8_t op; unsigned w;
    uint64_t a, b; bool want; uint8_t flags;
} CMPS[] = {
    { OPC_FCMPEQ, 32u, 0x3f800000u, 0x40000000u, false, 0x00u },
    { OPC_FCMPEQ, 32u, 0x40000000u, 0x3f800000u, false, 0x00u },
    { OPC_FCMPEQ, 32u, 0x3f800000u, 0x3f800000u, true, 0x00u },
    { OPC_FCMPEQ, 32u, 0x0u, 0x80000000u, true, 0x00u },
    { OPC_FCMPEQ, 32u, 0x7fc00000u, 0x3f800000u, false, 0x00u },
    { OPC_FCMPEQ, 32u, 0x7f800001u, 0x3f800000u, false, 0x00u },
    { OPC_FCMPEQ, 32u, 0xbf800000u, 0x3f800000u, false, 0x00u },
    { OPC_FCMPLT, 32u, 0x3f800000u, 0x40000000u, true, 0x00u },
    { OPC_FCMPLT, 32u, 0x40000000u, 0x3f800000u, false, 0x00u },
    { OPC_FCMPLT, 32u, 0x3f800000u, 0x3f800000u, false, 0x00u },
    { OPC_FCMPLT, 32u, 0x0u, 0x80000000u, false, 0x00u },
    { OPC_FCMPLT, 32u, 0x7fc00000u, 0x3f800000u, false, 0x01u },
    { OPC_FCMPLT, 32u, 0x7f800001u, 0x3f800000u, false, 0x01u },
    { OPC_FCMPLT, 32u, 0xbf800000u, 0x3f800000u, true, 0x00u },
    { OPC_FCMPLE, 32u, 0x3f800000u, 0x40000000u, true, 0x00u },
    { OPC_FCMPLE, 32u, 0x40000000u, 0x3f800000u, false, 0x00u },
    { OPC_FCMPLE, 32u, 0x3f800000u, 0x3f800000u, true, 0x00u },
    { OPC_FCMPLE, 32u, 0x0u, 0x80000000u, true, 0x00u },
    { OPC_FCMPLE, 32u, 0x7fc00000u, 0x3f800000u, false, 0x01u },
    { OPC_FCMPLE, 32u, 0x7f800001u, 0x3f800000u, false, 0x01u },
    { OPC_FCMPLE, 32u, 0xbf800000u, 0x3f800000u, true, 0x00u },
    { OPC_FCMPEQ, 64u, 0x3ff0000000000000u, 0x4000000000000000u, false, 0x00u },
    { OPC_FCMPEQ, 64u, 0x4000000000000000u, 0x3ff0000000000000u, false, 0x00u },
    { OPC_FCMPEQ, 64u, 0x3ff0000000000000u, 0x3ff0000000000000u, true, 0x00u },
    { OPC_FCMPEQ, 64u, 0x0u, 0x8000000000000000u, true, 0x00u },
    { OPC_FCMPEQ, 64u, 0x7ff8000000000000u, 0x3ff0000000000000u, false, 0x00u },
    { OPC_FCMPEQ, 64u, 0x7ff0000000000001u, 0x3ff0000000000000u, false, 0x00u },
    { OPC_FCMPEQ, 64u, 0xbff0000000000000u, 0x3ff0000000000000u, false, 0x00u },
    { OPC_FCMPLT, 64u, 0x3ff0000000000000u, 0x4000000000000000u, true, 0x00u },
    { OPC_FCMPLT, 64u, 0x4000000000000000u, 0x3ff0000000000000u, false, 0x00u },
    { OPC_FCMPLT, 64u, 0x3ff0000000000000u, 0x3ff0000000000000u, false, 0x00u },
    { OPC_FCMPLT, 64u, 0x0u, 0x8000000000000000u, false, 0x00u },
    { OPC_FCMPLT, 64u, 0x7ff8000000000000u, 0x3ff0000000000000u, false, 0x01u },
    { OPC_FCMPLT, 64u, 0x7ff0000000000001u, 0x3ff0000000000000u, false, 0x01u },
    { OPC_FCMPLT, 64u, 0xbff0000000000000u, 0x3ff0000000000000u, true, 0x00u },
    { OPC_FCMPLE, 64u, 0x3ff0000000000000u, 0x4000000000000000u, true, 0x00u },
    { OPC_FCMPLE, 64u, 0x4000000000000000u, 0x3ff0000000000000u, false, 0x00u },
    { OPC_FCMPLE, 64u, 0x3ff0000000000000u, 0x3ff0000000000000u, true, 0x00u },
    { OPC_FCMPLE, 64u, 0x0u, 0x8000000000000000u, true, 0x00u },
    { OPC_FCMPLE, 64u, 0x7ff8000000000000u, 0x3ff0000000000000u, false, 0x01u },
    { OPC_FCMPLE, 64u, 0x7ff0000000000001u, 0x3ff0000000000000u, false, 0x01u },
    { OPC_FCMPLE, 64u, 0xbff0000000000000u, 0x3ff0000000000000u, true, 0x00u },
};

static const struct {
    unsigned srcw; uint64_t a; unsigned dstw; bool uns;
    uint64_t want_hi, want_lo; uint8_t flags;
} F2I[] = {
    { 64u, 0xbff8000000000000u, 32u, false, 0xffffffffffffffffu, 0xffffffffffffffffu, 0x10u },
    { 64u, 0xbff8000000000000u, 32u, true, 0x0u, 0x0u, 0x01u },
    { 64u, 0xbfeccccccccccccdu, 32u, true, 0x0u, 0x0u, 0x10u },
    { 32u, 0x4f000000u, 32u, false, 0x0u, 0x7fffffffu, 0x01u },
    { 32u, 0x4f000000u, 32u, true, 0xffffffffffffffffu, 0xffffffff80000000u, 0x00u },
    { 32u, 0xbf800000u, 32u, true, 0x0u, 0x0u, 0x01u },
    { 64u, 0x7ff8000000000000u, 64u, false, 0x0u, 0x7fffffffffffffffu, 0x01u },
    { 64u, 0x7ff0000000000000u, 128u, false, 0x7fffffffffffffffu, 0xffffffffffffffffu, 0x01u },
    { 64u, 0xfff0000000000000u, 128u, false, 0x8000000000000000u, 0x0u, 0x01u },
    { 64u, 0x47d0000000000000u, 128u, false, 0x4000000000000000u, 0x0u, 0x00u },
    { 64u, 0x47e0000000000000u, 128u, false, 0x7fffffffffffffffu, 0xffffffffffffffffu, 0x01u },
    { 64u, 0x47e0000000000000u, 128u, true, 0x8000000000000000u, 0x0u, 0x00u },
    { 64u, 0x3ffc000000000000u, 64u, false, 0x0u, 0x1u, 0x10u },
    { 32u, 0x0u, 64u, false, 0x0u, 0x0u, 0x00u },
    { 32u, 0x80000000u, 64u, false, 0x0u, 0x0u, 0x00u },
    { 64u, 0xc3e0000000000000u, 64u, false, 0xffffffffffffffffu, 0x8000000000000000u, 0x00u },
    { 64u, 0xc3e0000000000000u, 64u, true, 0x0u, 0x0u, 0x01u },
};

static const struct {
    uint64_t v_hi, v_lo; unsigned srcw; bool uns;
    unsigned dstw, rm; uint64_t want; uint8_t flags;
} I2F[] = {
    { 0xffffffffffffffffu, 0xffffffffffffffffu, 128u, true, 32u, RM_RNE, 0x7f800000u, 0x14u },
    { 0xffffffffffffffffu, 0xffffffffffffffffu, 128u, true, 32u, RM_RTZ, 0x7f7fffffu, 0x10u },
    { 0xffffffffffffffffu, 0xffffffffffffffffu, 128u, false, 64u, RM_RNE, 0xbff0000000000000u, 0x00u },
    { 0x0u, 0x20000000000001u, 64u, false, 64u, RM_RNE, 0x4340000000000000u, 0x10u },
    { 0x0u, 0x20000000000001u, 64u, false, 64u, RM_RMM, 0x4340000000000001u, 0x10u },
    { 0x0u, 0x5u, 32u, false, 64u, RM_RNE, 0x4014000000000000u, 0x00u },
    { 0x0u, 0xfffffffbu, 32u, false, 64u, RM_RNE, 0xc014000000000000u, 0x00u },
    { 0x0u, 0xfffffffbu, 32u, true, 64u, RM_RNE, 0x41efffffff600000u, 0x00u },
    { 0x0u, 0x0u, 64u, false, 32u, RM_RNE, 0x0u, 0x00u },
    { 0x8000000000000000u, 0x0u, 128u, false, 64u, RM_RNE, 0xc7e0000000000000u, 0x00u },
};

static const struct {
    unsigned srcw; uint64_t a; unsigned dstw, rm;
    uint64_t want; uint8_t flags;
} F2F[] = {
    { 64u, 0x7e37e43c8800759cu, 32u, RM_RNE, 0x7f800000u, 0x14u },
    { 64u, 0x7e37e43c8800759cu, 32u, RM_RTZ, 0x7f7fffffu, 0x14u },
    { 64u, 0x1a56e1fc2f8f359u, 32u, RM_RNE, 0x0u, 0x18u },
    { 64u, 0x3ff0000000400000u, 32u, RM_RNE, 0x3f800000u, 0x10u },
    { 64u, 0x3ff8000000000000u, 32u, RM_RNE, 0x3fc00000u, 0x00u },
    { 32u, 0x1u, 64u, RM_RNE, 0x36a0000000000000u, 0x00u },
    { 32u, 0x7f800001u, 64u, RM_RNE, 0x7ff8000000000000u, 0x01u },
    { 32u, 0x80000000u, 64u, RM_RNE, 0x8000000000000000u, 0x00u },
    { 64u, 0x3730000000000000u, 32u, RM_RNE, 0x200u, 0x00u },
};

int main(void)
{
    for (unsigned i = 0; i < sizeof ARITH / sizeof ARITH[0]; i++) {
        SeFpRes r = se_fp_arith(ARITH[i].op, SeFpFmtW_t_of(ARITH[i].w),
                                ARITH[i].a, ARITH[i].b, ARITH[i].c,
                                SeFpRm_t_of(ARITH[i].rm));
        if (r.bits != ARITH[i].want || r.flags != ARITH[i].flags) {
            (void)fprintf(stderr,
                          "ARITH[%u] op=%02x w=%u: got %016llx/%02x "
                          "want %016llx/%02x\n",
                          i, ARITH[i].op, ARITH[i].w,
                          (unsigned long long)r.bits, r.flags,
                          (unsigned long long)ARITH[i].want,
                          ARITH[i].flags);
            return 1;
        }
    }
    for (unsigned i = 0; i < sizeof CMPS / sizeof CMPS[0]; i++) {
        uint8_t fl = 0;
        bool t = se_fp_cmp(CMPS[i].op, SeFpFmtW_t_of(CMPS[i].w),
                           CMPS[i].a, CMPS[i].b, &fl);
        if (t != CMPS[i].want || fl != CMPS[i].flags) {
            (void)fprintf(stderr, "CMPS[%u]: got %d/%02x want %d/%02x\n",
                          i, (int)t, fl, (int)CMPS[i].want,
                          CMPS[i].flags);
            return 1;
        }
    }
    for (unsigned i = 0; i < sizeof F2I / sizeof F2I[0]; i++) {
        SeFpInt r = se_fp_to_int(SeFpFmtW_t_of(F2I[i].srcw), F2I[i].a,
                                 SeIntW_t_of(F2I[i].dstw), F2I[i].uns);
        se_u128 want = se_make128(F2I[i].want_hi, F2I[i].want_lo);
        if (r.val != want || r.flags != F2I[i].flags) {
            (void)fprintf(stderr,
                          "F2I[%u]: got %016llx%016llx/%02x want "
                          "%016llx%016llx/%02x\n",
                          i, (unsigned long long)se_hi64(r.val),
                          (unsigned long long)se_lo64(r.val), r.flags,
                          (unsigned long long)F2I[i].want_hi,
                          (unsigned long long)F2I[i].want_lo,
                          F2I[i].flags);
            return 1;
        }
    }
    for (unsigned i = 0; i < sizeof I2F / sizeof I2F[0]; i++) {
        SeFpRes r = se_fp_from_int(se_make128(I2F[i].v_hi, I2F[i].v_lo),
                                   SeIntW_t_of(I2F[i].srcw), I2F[i].uns,
                                   SeFpFmtW_t_of(I2F[i].dstw),
                                   SeFpRm_t_of(I2F[i].rm));
        if (r.bits != I2F[i].want || r.flags != I2F[i].flags) {
            (void)fprintf(stderr,
                          "I2F[%u]: got %016llx/%02x want %016llx/%02x\n",
                          i, (unsigned long long)r.bits, r.flags,
                          (unsigned long long)I2F[i].want, I2F[i].flags);
            return 1;
        }
    }
    for (unsigned i = 0; i < sizeof F2F / sizeof F2F[0]; i++) {
        SeFpRes r = se_fp_to_fp(SeFpFmtW_t_of(F2F[i].srcw), F2F[i].a,
                                SeFpFmtW_t_of(F2F[i].dstw),
                                SeFpRm_t_of(F2F[i].rm));
        if (r.bits != F2F[i].want || r.flags != F2F[i].flags) {
            (void)fprintf(stderr,
                          "F2F[%u]: got %016llx/%02x want %016llx/%02x\n",
                          i, (unsigned long long)r.bits, r.flags,
                          (unsigned long long)F2F[i].want, F2F[i].flags);
            return 1;
        }
    }
    (void)printf("test_fp: all vectors pass\n");
    return 0;
}
