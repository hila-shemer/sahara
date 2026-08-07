#!/usr/bin/env python3
"""Generate tests/c7_mem.s — CONFORMANCE.md group C7, memory.

Expected values are computed HERE from ISA-SPEC 5.3 (ea composition,
width, natural alignment) and 3.4 (canonical extension), with Python
bigints over an explicit little-endian byte model (ISA-SPEC 1) — an
independent calculation, never an emulator run.

Coverage (C7 outline):
- LDS/LDZ at 8/16/32/64 from every aligned offset of a 16-byte box
  whose bytes force both sign cases; LD128; canonicalization of the
  loaded value (sign- vs zero-extension to 128)
- ST at each width writes exactly its low w bits at the addressed
  bytes and nothing else (ld128 readback against a byte-model merge);
  register high-bit garbage is ignored; ST128
- cross-width overlap (st.64 then byte loads) pins little-endian
- ea composition: base alone, +/-disp, plain index, index shl/sxt/zxt,
  index+disp; a store through a composed ea
- alignment: every width's misaligned classes trap UNALIGNED with
  baddr = the exact ea, epc = the access; 8-bit never traps; faulting
  loads leave dst untouched; atomics (AMO/CAS at 32/64/128) trap
  UNALIGNED too (the C3 bounded-coverage bullet lands here)
- device access size: non-64-bit loads/stores on a device register
  window trap DEVERR (PLATFORM-SPEC 1); checks/c7_mem.sh asserts no
  store footprint ever lands in device space

Bounded coverage — deliberately NOT here (no silent gaps):
- successful 64-bit device-register accesses, device ordering rules
  1-2 (--check-devorder, PRESENT/doorbell), device read side effects,
  and the UNALIGNED-before-DEVERR precedence (SPEC-ISSUES 25, decided
  by devspec) live in tests/c7_dev.s now that devspec/ landed.
- device behavior that needs EVENT injection or the NIC translator
  (queue pops with content, overflow, resize, TX/RX flows) remains
  gated on the device-phase fixtures — see c7_dev.s's header.

Deterministic; output is committed.
"""

import os

MASK128 = (1 << 128) - 1
GARB = 0x5A5A_C3C3_0FF0_A5A5_9669_3CC3_FF00_D00D

# The load/store box (ATOMIC_BOX, 16-byte aligned, tests/README.md).
BOX = 0x740
DEV_KBD_BASE = 0x0F010000     # PLATFORM-SPEC 1 (also in defs.s)

# 16 seed bytes, little-endian byte i lives at BOX+i. Chosen so every
# width at every offset sees both a sign-set and a sign-clear case
# somewhere in the sweep: includes 0x80, 0x7F, 0xFF, 0x00, 0x01.
SEED_BYTES = [0x80, 0xFF, 0x7F, 0x01, 0x00, 0xA5, 0x5A, 0xFE,
              0x01, 0x80, 0xC3, 0x7F, 0xE9, 0x00, 0xFF, 0x10]
SEED = int.from_bytes(bytes(SEED_BYTES), "little")


def mask(w):
    return (1 << w) - 1


def sext(v, w):
    v &= mask(w)
    if w < 128 and v >> (w - 1):
        v |= MASK128 ^ mask(w)
    return v


def garb(x, w):
    """x at width w with deterministic garbage above bit w-1."""
    if w == 128:
        return x & MASK128
    return (x & mask(w)) | ((GARB << w) & MASK128 & ~mask(w))


def load_val(byts, off, w, signed):
    raw = int.from_bytes(bytes(byts[off:off + w // 8]), "little")
    return sext(raw, w) if signed else raw


def store_merge(byts, off, w, val):
    out = list(byts)
    out[off:off + w // 8] = (val & mask(w)).to_bytes(w // 8, "little")
    return out


# ---- reference self-checks (fail the generator, not the suite) ------
assert load_val(SEED_BYTES, 0, 8, True) == sext(0x80, 8)
assert load_val(SEED_BYTES, 0, 8, False) == 0x80
assert load_val(SEED_BYTES, 2, 8, True) == 0x7F
assert load_val(SEED_BYTES, 0, 16, False) == 0xFF80
assert load_val(SEED_BYTES, 8, 64, False) == 0x10FF00E97FC38001
assert int.from_bytes(bytes(store_merge([0] * 16, 4, 16, 0xABCD)),
                      "little") == 0xABCD << 32

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


def seed_box():
    emit("        li r19, " + hexv(SEED))
    emit("        st128 [r25], r19")


def sfx(w):
    return {8: ".8", 16: ".16", 32: ".32", 64: ".64"}[w]


def gen_loads():
    emit("        # ---- C7.1 load width/extension sweep over the box --")
    seed_box()
    for w in (8, 16, 32, 64):
        for off in range(0, 16, w // 8):
            for op, signed in (("lds", True), ("ldz", False)):
                exp = load_val(SEED_BYTES, off, w, signed)
                begin(f"{op}{sfx(w)} [box+{off}] -> {hexv(exp)}")
                emit(f"        {op}{sfx(w)} r19, [r25 + {off}]")
                check_r19(exp)
    begin("ld128 [box] returns the full seed")
    emit("        ld128 r19, [r25]")
    check_r19(SEED)


def gen_stores():
    emit("        # ---- C7.2 store width sweep: exact-byte merges ----")
    for w in (8, 16, 32, 64):
        pat = {8: 0x3C, 16: 0xBEEF, 32: 0x8BADF00D,
               64: 0xFEEDFACE_8BADF00D}[w]
        for off in range(0, 16, w // 8):
            v = garb(pat + off, w)      # per-offset value, garbage high
            exp_bytes = store_merge(SEED_BYTES, off, w, v)
            exp = int.from_bytes(bytes(exp_bytes), "little")
            begin(f"st{sfx(w)} [box+{off}] writes only bytes "
                  f"{off}..{off + w // 8 - 1}")
            seed_box()
            emit(f"        li r21, {hexv(v)}")
            emit(f"        st{sfx(w)} [r25 + {off}], r21")
            emit("        ld128 r19, [r25]")
            check_r19(exp)
    v = 0x0123_4567_89AB_CDEF_1122_3344_5566_7788
    begin("st128 replaces the whole box")
    seed_box()
    emit(f"        li r21, {hexv(v)}")
    emit("        st128 [r25], r21")
    emit("        ld128 r19, [r25]")
    check_r19(v)
    # cross-width overlap pins byte order: ISA-SPEC 1 says the machine
    # is little-endian; the byte of a stored u64 visible at [ea+k] is
    # bits 8k+7:8k.
    q = 0x1032_5476_98BA_DCFE
    begin("little-endian: st.64 then ldz.8 at each byte")
    seed_box()
    emit(f"        li r21, {hexv(q)}")
    emit("        st.64 [r25], r21")
    emit("        ldz.8 r19, [r25 + 3]")
    check_r19((q >> 24) & 0xFF)
    begin("little-endian: st.64 then ldz.16 at offset 6")
    emit("        ldz.16 r19, [r25 + 6]")
    check_r19((q >> 48) & 0xFFFF)


def gen_ea():
    emit("        # ---- C7.3 ea composition: base + mod(idx) + disp --")
    vals = [0x1111_0001 * (i + 1) + (i << 40) for i in range(8)]
    emit("        la r21, c7_data")
    begin("base alone")
    emit("        lds.64 r19, [r21]")
    check_r19(vals[0])
    begin("base + positive disp")
    emit("        lds.64 r19, [r21 + 24]")
    check_r19(vals[3])
    begin("base + negative disp")
    emit("        add r22, r21, 32")
    emit("        lds.64 r19, [r22 + -8]")
    check_r19(vals[3])
    begin("base + plain index register")
    emit("        li r22, 32")
    emit("        lds.64 r19, [r21 + r22]")
    check_r19(vals[4])
    begin("base + index shl 3")
    emit("        li r22, 5")
    emit("        lds.64 r19, [r21 + r22 shl 3]")
    check_r19(vals[5])
    begin("base + index shl 3 + negative disp")
    emit("        lds.64 r19, [r21 + r22 shl 3 + -16]")
    check_r19(vals[3])
    begin("index sxt 8: 0xf8 indexes backward by 8")
    emit("        add r22, r21, 16")
    emit("        li r23, 0xf8")
    emit("        lds.64 r19, [r22 + r23 sxt 8]")
    check_r19(vals[1])
    begin("index zxt 8: high garbage in the index register ignored")
    emit(f"        li r23, {hexv(garb(0x18, 8))}")
    emit("        lds.64 r19, [r21 + r23 zxt 8]")
    check_r19(vals[3])
    begin("store through a composed ea, plain readback")
    emit("        li r22, 6")
    emit("        li r23, 0x51DE")
    emit("        st.64 [r21 + r22 shl 3 + 8], r23   # slot 7")
    emit("        lds.64 r19, [r21 + 56]")
    check_r19(0x51DE)


def gen_align():
    emit("        # ---- C7.4 alignment: UNALIGNED, baddr = ea --------")
    emit("        la.abs r21, h_rec")
    emit("        mtsr vbase, r21")
    emit()

    def trap_case(comment, access_lines, ea, check_epc=False):
        begin(comment)
        site = f"c7a_{TESTID[0]}"
        emit(f"{site}:")
        for line in access_lines:
            emit(f"        {line}")
        emit("        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]")
        check_r19_named("CAUSE_UNALIGNED")
        begin(f"...baddr = {hexv(ea)}")
        emit("        lds.64 r19, [r24 + TRAP_BADDR_SLOT - FAIL_ADDR]")
        check_r19(ea)
        if check_epc:
            begin("...epc = the faulting access")
            emit("        lds.64 r19, [r24 + TRAP_EPC_SLOT - FAIL_ADDR]")
            emit(f"        la.abs r20, {site}")
            emit("        cmpeq p1, r19, r20")
            emit("        (!p1) b fail")
            emit()

    first = True
    for mnem, off in [("lds.16", 1), ("lds.32", 1), ("lds.32", 2),
                      ("lds.64", 1), ("lds.64", 4), ("ldz.16", 1),
                      ("ld128", 1), ("ld128", 8)]:
        trap_case(f"{mnem} [box+{off}] traps UNALIGNED",
                  [f"{mnem} r19, [r25 + {off}]"], BOX + off,
                  check_epc=first)
        first = False
    for mnem, off in [("st.16", 1), ("st.32", 2), ("st.64", 4),
                      ("st128", 8)]:
        trap_case(f"{mnem} [box+{off}] traps UNALIGNED",
                  [f"{mnem} [r25 + {off}], r19"], BOX + off)
    # atomics: natural alignment required at 32/64/128 (ISA-SPEC 5.4);
    # the C3 generator's bounded-coverage bullet lands here.
    for mnem, off in [("amoadd.32", 2), ("amoadd.64", 4),
                      ("amoswap", 8)]:
        trap_case(f"{mnem} [box+{off}] traps UNALIGNED",
                  [f"{mnem} r19, [r25 + {off}], r22"], BOX + off)
    trap_case("cas.64 [box+4] traps UNALIGNED",
              ["cas.64 r19, [r25 + 4], r22, r23"], BOX + 4)

    begin("faulting load leaves dst untouched")
    emit("        li r19, 0x5AFE")
    emit("        lds.64 r19, [r25 + 1]     # traps, skipped")
    check_r19(0x5AFE)

    emit("        # 8-bit accesses never trap, any address")
    seed_box()
    begin("st.8 / ldz.8 at odd offsets succeed")
    emit("        li r21, 0xC7")
    emit("        st.8 [r25 + 3], r21")
    emit("        ldz.8 r19, [r25 + 3]")
    check_r19(0xC7)
    begin("lds.8 at offset 9 (0x80 seeded: sign-extends)")
    seed_box()
    emit("        lds.8 r19, [r25 + 9]")
    check_r19(sext(SEED_BYTES[9], 8))


def check_r19_named(equ_name):
    emit(f"        cmpeq p1, r19, {equ_name}")
    emit("        (!p1) b fail")
    emit()


def gen_devsize():
    emit("        # ---- C7.5 device register access size: DEVERR -----")
    emit("        # PLATFORM-SPEC 1: device registers are 64-bit only;")
    emit("        # any other size traps DEVERR. The trap is address+")
    emit("        # size classification — no device internals — so it")
    emit("        # is not devspec-gated. Successful 64-bit accesses")
    emit("        # (values, side effects) ARE devspec-gated: none here.")
    emit("        li r21, DEV_KBD_BASE")
    for mnem, off in [("lds.8", 0), ("lds.16", 0), ("lds.32", 0),
                      ("ldz.32", 0), ("ld128", 0)]:
        begin(f"{mnem} on a device register traps DEVERR")
        emit(f"        {mnem} r19, [r21 + {off}]")
        emit("        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]")
        check_r19_named("CAUSE_DEVERR")
        begin("...baddr = the device ea")
        emit("        lds.64 r19, [r24 + TRAP_BADDR_SLOT - FAIL_ADDR]")
        emit("        cmpeq p1, r19, r21")
        emit("        (!p1) b fail")
        emit()
    for mnem in ("st.8", "st.16", "st.32", "st128"):
        begin(f"{mnem} on a device register traps DEVERR")
        emit("        li r22, 0x11")
        emit(f"        {mnem} [r21], r22")
        emit("        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]")
        check_r19_named("CAUSE_DEVERR")


def generate():
    emit("# c7_mem.s — C7 memory (CONFORMANCE.md)")
    emit("# GENERATED by tests/gen_c7.py — DO NOT EDIT; edit the")
    emit("# generator and rerun (deterministic; output is committed).")
    emit("# Expected values computed in the generator from ISA-SPEC")
    emit("# 5.3/3.4 over an explicit little-endian byte model,")
    emit("# independent of any emulator. Device ordering, successful")
    emit("# 64-bit register access, and the UNALIGNED-before-DEVERR")
    emit("# precedence live in tests/c7_dev.s (bounded-coverage notes")
    emit("# in gen_c7.py's docstring). Conventions per tests/README.md.")
    emit()
    emit("        .org 0x1000")
    emit("start:")
    emit("        li r24, FAIL_ADDR")
    emit("        li r25, ATOMIC_BOX")
    emit()
    gen_loads()
    gen_stores()
    gen_ea()
    gen_align()
    gen_devsize()
    emit("pass:")
    emit("        li r0, PASS_MAGIC")
    emit("        halt")
    emit("fail:")
    emit("        st.64 [r24], r27")
    emit("        mov r0, r27")
    emit("        halt")
    emit()
    emit("        # record cause/baddr/epc/status, skip the faulter")
    emit("h_rec:")
    emit("        mfsr k0, cause0")
    emit("        st.64 [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR], k0")
    emit("        mfsr k0, baddr0")
    emit("        st.64 [r24 + TRAP_BADDR_SLOT - FAIL_ADDR], k0")
    emit("        mfsr k0, epc0")
    emit("        st.64 [r24 + TRAP_EPC_SLOT - FAIL_ADDR], k0")
    emit("        mfsr k0, status")
    emit("        st.64 [r24 + TRAP_STATUS_SLOT - FAIL_ADDR], k0")
    emit("        mfsr k0, epc0")
    emit("        add k0, k0, 8")
    emit("        mtsr epc0, k0")
    emit("        iret")
    emit()
    emit("        .align 8")
    emit("c7_data:")
    vals = [0x1111_0001 * (i + 1) + (i << 40) for i in range(8)]
    for i, v in enumerate(vals):
        emit(f"        .quad {hexv(v)}   # slot {i}")
    return "\n".join(OUT) + "\n"


def main():
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "c7_mem.s")
    text = generate()
    with open(out_path, "w") as f:
        f.write(text)
    print(f"wrote {out_path}: {TESTID[0]} tests, "
          f"{len(text.splitlines())} lines")


if __name__ == "__main__":
    main()
