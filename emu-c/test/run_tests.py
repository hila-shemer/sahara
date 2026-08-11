#!/usr/bin/env python3
"""Image-level tests for the C Sahara emulator.

Bootstrap harness per emu-common-prompt.md: until the shared assembler
lands on main, instructions are assembled programmatically from
encoding.py (the single source of encoding truth -- nothing here
hardcodes a field position or opcode value). Covers smoke semantics,
trap flows, timer/WFI, MULH-vs-bigint, determinism double-runs, and
decoder fuzz.
"""
import pathlib
import random
import struct
import subprocess
import sys
import tempfile

EMU_DIR = pathlib.Path(__file__).resolve().parents[1]
ROOT = EMU_DIR.parent
sys.path.insert(0, str(ROOT))
import encoding as E  # noqa: E402

sys.path.insert(0, str(EMU_DIR / "test"))
import fp_oracle as O  # noqa: E402

EMU = EMU_DIR / "bazel-bin" / "sahara-emu"
IMM_MASK = (1 << E.IMM_BITS) - 1
W128 = 2  # ALU/CMP/ATOMIC width-field value for 128-bit

failures = []


def enc(op, dst=0, src1=0, src2=0, src3=0, pred=0, mod=0, width=0, imm=0,
        iform=False):
    val, fam, _ops = E.OPCODES[op]
    if iform:
        assert E.FAMILIES[fam]["iflag"], op
        val += 1
    fields = dict(opcode=val, pred=pred, dst=dst, src1=src1, src2=src2,
                  src3=src3, mod=mod, width=width, imm=imm & IMM_MASK)
    insn = 0
    for name, (lsb, bits) in E.FIELDS.items():
        v = fields[name]
        assert 0 <= v < (1 << bits), (op, name, v)
        insn |= v << lsb
    return insn


def li64(rd, value):
    """Load an arbitrary 64-bit constant: LDI + 2x SHORI (66 bits)."""
    value &= (1 << 64) - 1
    top = value >> 44  # 20 bits: sext-safe in a 22-bit immediate
    return [
        enc("LDI", dst=rd, imm=top),
        enc("SHORI", dst=rd, src1=rd, imm=(value >> 22) & IMM_MASK),
        enc("SHORI", dst=rd, src1=rd, imm=value & IMM_MASK),
    ]


def li128(rd, value):
    """Full 128-bit constant: LDI + 5x SHORI (132 bits)."""
    value &= (1 << 128) - 1
    # top chunk is 18 bits (128 - 5*22), so LDI's sign-extend never fires
    words = [enc("LDI", dst=rd, imm=(value >> 110) & IMM_MASK)]
    for k in range(4, -1, -1):
        words.append(enc("SHORI", dst=rd, src1=rd, imm=(value >> (22 * k))
                         & IMM_MASK))
    return words


def image(words_by_addr, entry=0x1000):
    """Build a .img: words_by_addr maps load PA -> list of insn words."""
    segs = []
    blob = b""
    hdr_len = 32 + 48 * len(words_by_addr)
    for pa, words in words_by_addr.items():
        code = b"".join(struct.pack("<Q", w) for w in words)
        segs.append((pa, hdr_len + len(blob), len(code)))
        blob += code
    out = struct.pack("<Q", int.from_bytes(b"SAHIMG01", "little"))
    out += entry.to_bytes(16, "little") + struct.pack("<Q", len(segs))
    for pa, off, ln in segs:
        out += pa.to_bytes(16, "little")
        out += struct.pack("<QQQQ", off, ln, ln, 0)
    return out + blob


def run(words_by_addr, args=(), entry=0x1000):
    with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as f:
        f.write(image(words_by_addr, entry))
        path = f.name
    try:
        return subprocess.run([str(EMU), path, *args], capture_output=True,
                              text=False, timeout=60)
    finally:
        pathlib.Path(path).unlink()


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        failures.append(name)


def expect_halt(name, words_by_addr, r0, args=()):
    p = run(words_by_addr, args)
    want = b"HALT r0=%032x\n" % (r0 & ((1 << 128) - 1))
    check(name, p.returncode == 0 and p.stdout == want,
          f"rc={p.returncode} out={p.stdout!r} err={p.stderr!r}")


HALT = enc("HALT")


def test_basic():
    expect_halt("halt-42", {0x1000: [enc("LDI", dst=0, imm=42), HALT]}, 42)
    expect_halt("add-imm", {0x1000: [
        enc("LDI", dst=1, imm=5),
        enc("ADD", dst=0, src1=1, width=W128, imm=7, iform=True),
        HALT]}, 12)
    expect_halt("add-reg-mod-shl", {0x1000: [
        enc("LDI", dst=1, imm=5),
        enc("LDI", dst=2, imm=3),
        # r0 = r1 + (r2 shl 4) = 5 + 48
        enc("ADD", dst=0, src1=1, src2=2, mod=(4 << 2) | 1, width=W128),
        HALT]}, 53)
    # canonical form: OR.32 of 0x80000000 sign-extends (C5's core rule)
    expect_halt("canon32-unsigned", {0x1000: [
        enc("LDI", dst=1, imm=1),
        enc("SHL", dst=1, src1=1, width=W128, imm=31, iform=True),
        enc("OR", dst=0, src1=1, width=0, imm=0, iform=True),
        HALT]}, (1 << 128) - (1 << 31))
    expect_halt("neg-imm-canon32", {0x1000: [
        enc("ADD", dst=0, src1=31, width=0, imm=IMM_MASK, iform=True),  # -1
        HALT]}, (1 << 128) - 1)
    expect_halt("shr32", {0x1000: [
        enc("LDI", dst=1, imm=1),
        enc("SHL", dst=1, src1=1, width=W128, imm=31, iform=True),
        enc("ADD", dst=1, src1=1, width=W128, imm=1, iform=True),
        enc("SHR", dst=0, src1=1, width=0, imm=1, iform=True),  # 0x40000000
        HALT]}, 0x40000000)
    expect_halt("sdiv-by-zero", {0x1000: [
        enc("LDI", dst=1, imm=100),
        enc("SDIV", dst=0, src1=1, src2=31, width=W128),
        HALT]}, (1 << 128) - 1)
    expect_halt("urem-by-zero", {0x1000: [
        enc("LDI", dst=1, imm=100),
        enc("UREM", dst=0, src1=1, src2=31, width=W128),
        HALT]}, 100)
    expect_halt("shori-chain", {0x1000: li64(0, 0x123456789ABCDEF0) + [HALT]},
                0x123456789ABCDEF0)


def test_predication():
    expect_halt("pred-taken", {0x1000: [
        enc("CMPLT", dst=1, src1=31, width=W128, imm=5, iform=True),  # 0<5
        enc("LDI", dst=0, imm=7, pred=(1 << 1)),        # (p1)
        enc("LDI", dst=2, imm=9, pred=(1 << 1) | 1),    # (!p1) squashed
        HALT]}, 7)
    expect_halt("pred-false-cannot-fault", {0x1000: [
        # (!p0): predicated-false SYSCALL, illegal word, and load from
        # unmapped-ish address all retire silently (C1)
        enc("SYSCALL", pred=1),
        enc("LDI", dst=0, imm=1, pred=1) | 0x01,  # would-be illegal opcode
        # would-be lds.64 at ~0 - 8: misaligned AND far outside RAM
        enc("LDS", dst=2, src1=31, width=3, imm=(-9) & IMM_MASK, pred=1),
        enc("LDI", dst=0, imm=33),
        HALT]}, 33)
    expect_halt("loop-sum", {0x1000: [
        enc("LDI", dst=2, imm=5),
        enc("ADD", dst=1, src1=1, src2=2, width=W128),          # loop:
        enc("SUB", dst=2, src1=2, width=W128, imm=1, iform=True),
        enc("CMPEQ", dst=1, src1=2, width=W128, imm=0, iform=True),
        enc("B", imm=(-3) & IMM_MASK, pred=(1 << 1) | 1),       # (!p1) b loop
        enc("OR", dst=0, src1=1, src2=31, width=W128),
        HALT]}, 15)
    expect_halt("prd-pwr", {0x1000: [
        enc("LDI", dst=1, imm=0b10101010),
        enc("PWR", src1=1),
        enc("PRD", dst=0),
        HALT]}, 0b10101011)  # p0 stays 1


def test_memory():
    expect_halt("st-lds-sign", {0x1000: [
        enc("LDI", dst=1, imm=0x2000)] + li64(3, 0x123456789ABCDEF0) + [
        enc("ST", src1=1, src3=3, width=3, imm=8),        # st.64 [r1+8]
        enc("LDS", dst=0, src1=1, width=2, imm=8),        # lds.32 -> sext
        HALT]}, ((1 << 128) - (1 << 32)) | 0x9ABCDEF0)
    expect_halt("st-ldz", {0x1000: [
        enc("LDI", dst=1, imm=0x2000)] + li64(3, 0x123456789ABCDEF0) + [
        enc("ST", src1=1, src3=3, width=3, imm=8),
        enc("LDZ", dst=0, src1=1, width=1, imm=8),        # ldz.16
        HALT]}, 0xDEF0)
    expect_halt("ld128-roundtrip", {0x1000: [
        enc("LDI", dst=1, imm=0x3000)] + li128(3, (0xAABB << 100) | 0x77) + [
        enc("ST128", src1=1, src3=3),
        enc("LD128", dst=0, src1=1),
        HALT]}, (0xAABB << 100) | 0x77)
    expect_halt("ea-composition", {0x1000: [
        enc("LDI", dst=1, imm=0x2000),
        enc("LDI", dst=2, imm=2),
        enc("LDI", dst=3, imm=0x5A),
        # st.8 [r1 + r2 shl 3 + 1] = 0x2011
        enc("ST", src1=1, src2=2, src3=3, mod=(3 << 2) | 1, width=0, imm=1),
        enc("LDZ", dst=0, src1=1, width=0, imm=0x11),
        HALT]}, 0x5A)
    expect_halt("amoadd", {0x1000: [
        enc("LDI", dst=1, imm=0x2000),
        enc("LDI", dst=2, imm=40),
        enc("ST", src1=1, src3=2, width=3),
        enc("LDI", dst=2, imm=2),
        enc("AMOADD", dst=4, src1=1, src2=2, width=1),   # old -> r4
        enc("LDS", dst=5, src1=1, width=3),
        enc("ADD", dst=0, src1=4, src2=5, width=W128),   # 40 + 42
        HALT]}, 82)
    expect_halt("cas-success-fail", {0x1000: [
        enc("LDI", dst=1, imm=0x2000),
        enc("LDI", dst=2, imm=7),
        enc("ST", src1=1, src3=2, width=3),
        enc("LDI", dst=3, imm=9),
        enc("CAS", dst=4, src1=1, src2=2, src3=3, width=1),  # 7==7: -> 9
        enc("LDI", dst=2, imm=5),
        enc("LDI", dst=3, imm=1),
        enc("CAS", dst=5, src1=1, src2=2, src3=3, width=1),  # 5!=9: no write
        enc("LDS", dst=6, src1=1, width=3),
        # r0 = old1*100 + old2*10 + final = 7*100 + 9*10 + 9
        enc("MUL", dst=4, src1=4, width=W128, imm=100, iform=True),
        enc("MUL", dst=5, src1=5, width=W128, imm=10, iform=True),
        enc("ADD", dst=0, src1=4, src2=5, width=W128),
        enc("ADD", dst=0, src1=0, src2=6, width=W128),
        HALT]}, 799)


def handler_img(main_words, handler_words, handler_pa=0x2000):
    """main at 0x1000 sets vbase=handler then runs main_words."""
    prologue = [
        enc("LDI", dst=10, imm=handler_pa),
        enc("MTSR", src1=10, imm=E.SREGS["vbase"]),
    ]
    return {0x1000: prologue + main_words, handler_pa: handler_words}


def cause_check_handler(want_cause, ok=111, bad=222):
    return [
        enc("MFSR", dst=5, imm=E.SREGS["cause0"]),
        enc("CMPEQ", dst=1, src1=5, width=W128, imm=want_cause, iform=True),
        enc("LDI", dst=0, imm=ok, pred=(1 << 1)),
        enc("LDI", dst=0, imm=bad, pred=(1 << 1) | 1),
        HALT,
    ]


def test_devspace():
    """The devspec/boot.md physical map (emu-c/platform.h, SPEC-ISSUES
    32 resolution): RAM region 0 ends at 0x0F00_0000; the register
    windows have per-device semantics (dev.c; the shared c7_dev image
    owns the full matrix -- these are the harness-level boundary
    probes); the NIC buffers and the pixel window are memory-like
    device space; [0x0F06_0000, 0x1000_0000) and everything past the
    pixel window are holes trapping DEVERR (BOOT-15)."""
    KBD = 0x0F010000       # keyboard window base
    BELOW = 0x0EFFFFF8     # last 8 RAM bytes below the windows
    HOLE = 0x0F060000      # first hole byte after the NIC window
    RXTOP = 0x0F05FFF8     # last 8 bytes of the NIC RX buffer
    PIXBUF = 0x10000000    # pixel window base
    PIXEND = 0x11000000    # first byte past the 16 MB pixel window
    expect_halt("dev-unlisted-offset-deverr",
                handler_img(li64(1, KBD) +
                            [enc("LDS", dst=2, src1=1, width=3, imm=16)],
                            cause_check_handler(E.CAUSES["DEVERR"])), 111)
    expect_halt("dev-store-deverr",
                handler_img(li64(1, KBD) +
                            [enc("LDI", dst=2, imm=7),
                             enc("ST", src1=1, src3=2, width=3)],
                            cause_check_handler(E.CAUSES["DEVERR"])), 111)
    expect_halt("dev-hole-deverr",
                handler_img(li64(1, HOLE) +
                            [enc("LDS", dst=2, src1=1, width=3)],
                            cause_check_handler(E.CAUSES["DEVERR"])), 111)
    expect_halt("dev-pixbuf-end-hole-deverr",
                handler_img(li64(1, PIXEND) +
                            [enc("LDS", dst=2, src1=1, width=3)],
                            cause_check_handler(E.CAUSES["DEVERR"])), 111)
    expect_halt("dev-fetch-deverr",
                handler_img(li64(1, KBD) +
                            [enc("JALR", dst=29, src1=1)],
                            cause_check_handler(E.CAUSES["DEVERR"])), 111)
    expect_halt("dev-below-window-ram",
                {0x1000: li64(1, BELOW) +
                 [enc("LDI", dst=2, imm=7),
                  enc("ST", src1=1, src3=2, width=3),
                  enc("LDS", dst=0, src1=1, width=3),
                  HALT]}, 7)
    expect_halt("dev-rxbuf-memory-like",
                {0x1000: li64(1, RXTOP) +
                 [enc("LDI", dst=2, imm=9),
                  enc("ST", src1=1, src3=2, width=3),
                  enc("LDS", dst=0, src1=1, width=3),
                  HALT]}, 9)
    expect_halt("dev-pixbuf-zero-then-store",
                {0x1000: li64(1, PIXBUF) +
                 [enc("LDZ", dst=3, src1=1, width=3),   # reads 0 (D-08)
                  enc("LDI", dst=2, imm=0x5A),
                  enc("ST", src1=1, src3=2, width=0),   # st.8
                  enc("LDZ", dst=0, src1=1, width=0),
                  enc("ADD", dst=0, src1=0, src2=3, width=W128),
                  HALT]}, 0x5A)
    expect_halt("dev-kbd-sentinel",
                {0x1000: li64(1, KBD) +
                 [enc("LDS", dst=2, src1=1, width=3),   # sext all-ones
                  enc("CMPEQ", dst=1, src1=2, width=W128,
                      imm=(-1) & IMM_MASK, iform=True),
                  enc("LDI", dst=0, imm=44, pred=(1 << 1)),
                  enc("LDI", dst=0, imm=55, pred=(1 << 1) | 1),
                  HALT]}, 44)


def test_traps():
    expect_halt("syscall-cause",
                handler_img([enc("SYSCALL")],
                            cause_check_handler(E.CAUSES["SYSCALL"])), 111)
    expect_halt("illegal-cause",
                handler_img([0x0000000000000000],
                            cause_check_handler(E.CAUSES["ILLEGAL"])), 111)
    expect_halt("odd-sibling-illegal",
                handler_img([enc("LDS", dst=1, src1=31, imm=0x2000) | 0x01],
                            cause_check_handler(E.CAUSES["ILLEGAL"])), 111)
    expect_halt("jalr-unaligned",
                handler_img([
                    enc("LDI", dst=1, imm=0x1004),
                    enc("JALR", dst=29, src1=1)],
                    cause_check_handler(E.CAUSES["UNALIGNED"])), 111)
    expect_halt("unaligned-baddr",
                handler_img([
                    enc("LDI", dst=1, imm=0x2003),
                    enc("LDS", dst=2, src1=1, width=2)],  # lds.32 @0x2003
                    [enc("MFSR", dst=0, imm=E.SREGS["baddr0"]), HALT]),
                0x2003)
    expect_halt("syscall-iret-resume",
                handler_img(
                    [enc("SYSCALL"), enc("LDI", dst=0, imm=55), HALT],
                    [enc("MFSR", dst=5, imm=E.SREGS["epc0"]),
                     enc("ADD", dst=5, src1=5, width=W128, imm=8, iform=True),
                     enc("MTSR", src1=5, imm=E.SREGS["epc0"]),
                     enc("IRET")]), 55)
    # double fault: handler faults before saving state -> dfbase, bank 1
    expect_halt("double-fault-banks", {
        0x1000: [
            enc("LDI", dst=10, imm=0x2000),
            enc("MTSR", src1=10, imm=E.SREGS["vbase"]),
            enc("LDI", dst=11, imm=0x3000),
            enc("MTSR", src1=11, imm=E.SREGS["dfbase"]),
            enc("SYSCALL")],
        0x2000: [0x0000000000000000],  # handler prologue faults ILLEGAL
        0x3000: [
            enc("MFSR", dst=5, imm=E.SREGS["cause0"]),   # SYSCALL = 10
            enc("MFSR", dst=6, imm=E.SREGS["cause1"]),   # ILLEGAL = 8
            enc("MUL", dst=5, src1=5, width=W128, imm=100, iform=True),
            enc("ADD", dst=0, src1=5, src2=6, width=W128),
            HALT]},
        E.CAUSES["SYSCALL"] * 100 + E.CAUSES["ILLEGAL"])
    # triple fault: machine halts (exit 0), r0 preserved
    p = run({0x1000: [enc("LDI", dst=0, imm=77),
                      enc("SYSCALL")]})  # vbase=0 -> ILLEGAL cascade
    check("triple-fault-halts",
          p.returncode == 0 and p.stdout == b"HALT r0=%032x\n" % 77,
          f"rc={p.returncode} out={p.stdout!r} err={p.stderr!r}")


def test_interrupts():
    # timer: arm timecmp, enable IE, spin; handler checks cause TIMER
    expect_halt("timer-interrupt",
                handler_img([
                    enc("LDI", dst=6, imm=50),
                    enc("MTSR", src1=6, imm=E.SREGS["timecmp"]),
                    enc("MFSR", dst=7, imm=E.SREGS["status"]),
                    enc("OR", dst=7, src1=7, width=W128, imm=1, iform=True),
                    enc("MTSR", src1=7, imm=E.SREGS["status"]),
                    enc("B", imm=0)],  # spin
                    cause_check_handler(E.CAUSES["TIMER"])),
                111, args=("--maxcycles", "1000"))
    # WFI: jumps virtual time straight to timecmp
    expect_halt("wfi-timer",
                handler_img([
                    enc("LDI", dst=6, imm=5000),
                    enc("MTSR", src1=6, imm=E.SREGS["timecmp"]),
                    enc("MFSR", dst=7, imm=E.SREGS["status"]),
                    enc("OR", dst=7, src1=7, width=W128, imm=1, iform=True),
                    enc("MTSR", src1=7, imm=E.SREGS["status"]),
                    enc("WFI")],
                    cause_check_handler(E.CAUSES["TIMER"])),
                111, args=("--maxcycles", "6000"))
    # WFI with nothing armed: deadlock halt, loud note on stderr
    p = run({0x1000: [enc("LDI", dst=0, imm=1), enc("WFI")]})
    check("wfi-deadlock",
          p.returncode == 0 and p.stdout == b"HALT r0=%032x\n" % 1
          and b"deadlock" in p.stderr,
          f"rc={p.returncode} out={p.stdout!r} err={p.stderr!r}")
    # IE=0 defers the timer
    expect_halt("ie0-defers-timer", {0x1000: [
        enc("LDI", dst=6, imm=5),
        enc("MTSR", src1=6, imm=E.SREGS["timecmp"]),
        enc("LDI", dst=1, imm=100),
        enc("ADD", dst=2, src1=2, width=W128, imm=1, iform=True),   # loop:
        enc("CMPEQ", dst=1, src1=2, src2=1, width=W128),
        enc("B", imm=(-2) & IMM_MASK, pred=(1 << 1) | 1),
        enc("LDI", dst=0, imm=123),
        HALT]}, 123, args=("--maxcycles", "1000"))


def test_mulh_bigint():
    rng = random.Random(20260807)
    m128 = (1 << 128) - 1
    for i in range(6):
        a = rng.getrandbits(128)
        b = rng.getrandbits(128)

        def s(x):
            return x - (1 << 128) if x >> 127 else x

        cases = [
            ("MULH", (s(a) * s(b)) >> 128 & m128),
            ("MULHU", (a * b) >> 128),
        ]
        for op, want in cases:
            words = li128(1, a) + li128(2, b) + [
                enc(op, dst=0, src1=1, src2=2, width=W128), HALT]
            expect_halt(f"{op.lower()}128-vec{i}", {0x1000: words}, want)


def _canon_low64(bits, w):
    """Low 64 bits of the canonical (sign-extended) register value."""
    if w == 32 and (bits >> 31) & 1:
        bits |= 0xFFFFFFFF00000000
    return bits & ((1 << 64) - 1)


def _fp_epilogue():
    """r0 <- (fcsr << 64) | low64(r0)."""
    return [
        enc("MFSR", dst=5, imm=E.SREGS["fcsr"]),
        enc("SHL", dst=0, src1=0, width=W128, imm=64, iform=True),
        enc("SHR", dst=0, src1=0, width=W128, imm=64, iform=True),
        enc("SHL", dst=5, src1=5, width=W128, imm=64, iform=True),
        enc("OR", dst=0, src1=0, src2=5, width=W128),
        HALT,
    ]


def _set_rm(rm):
    return [
        enc("LDI", dst=4, imm=rm << E.FCSR_RM_LSB),
        enc("MTSR", src1=4, imm=E.SREGS["fcsr"]),
    ]


_FP_ORACLE = {
    "FADD": O.fadd, "FSUB": O.fsub, "FMUL": O.fmul, "FDIV": O.fdiv,
    "FMIN": O.fmin, "FMAX": O.fmax,
}


def fp_arith_vec(name, opname, w, rm, a, b, c=None):
    f = O.fmt_of(w)
    if opname == "FSQRT":
        want, fl = O.fsqrt(f, a, rm)
    elif opname == "FMADD":
        want, fl = O.ffma(f, a, b, c, rm)
    else:
        want, fl = _FP_ORACLE[opname](f, a, b, rm)
    wf = 0 if w == 32 else 1
    words = li64(1, a) + li64(2, b) + (li64(3, c) if c is not None else [])
    words += _set_rm(rm)
    words += [enc(opname, dst=0, src1=1, src2=2, src3=3, width=wf)]
    words += _fp_epilogue()
    exp = ((fl | (rm << E.FCSR_RM_LSB)) << 64) | _canon_low64(want, w)
    expect_halt(name, {0x1000: words}, exp)


def fp_cmp_vec(name, opname, w, a, b):
    f = O.fmt_of(w)
    want, fl = O.fcmp(f, {"FCMPEQ": "eq", "FCMPLT": "lt",
                          "FCMPLE": "le"}[opname], a, b)
    wf = 0 if w == 32 else 1
    words = li64(1, a) + li64(2, b) + _set_rm(0)
    words += [enc(opname, dst=1, src1=1, src2=2, width=wf),
              enc("PRD", dst=0)]
    words += _fp_epilogue()
    exp = (fl << 64) | (1 | (int(want) << 1))  # p0 stays 1
    expect_halt(name, {0x1000: words}, exp)


def _rand_fp_bits(rng, w):
    f = O.fmt_of(w)
    p = f["p"]
    emask = ((1 << (w - p)) - 1) << (p - 1)
    sign = rng.getrandbits(1) << (w - 1)
    r = rng.random()
    if r < 0.06:
        return sign  # zero
    if r < 0.11:
        return sign | emask  # inf
    if r < 0.16:  # NaN, quiet or signaling
        return sign | emask | (1 << (p - 2) if rng.random() < 0.5 else 1)
    if r < 0.30:
        return sign | rng.getrandbits(p - 1)  # subnormal or small
    return sign | rng.getrandbits(w - 1)


def test_fp():
    # RMM tie-away vs RNE tie-even, through the instruction path
    one64 = 0x3FF0000000000000
    tie64 = 0x3C90000000000000  # 2^-53, half-ulp of 1.0
    fp_arith_vec("fadd64-tie-rne", "FADD", 64, O.RNE, one64, tie64)
    fp_arith_vec("fadd64-tie-rmm", "FADD", 64, O.RMM, one64, tie64)
    fp_arith_vec("fadd64-tie-rup", "FADD", 64, O.RUP, one64, tie64)
    # FMADD is fused: (1+2^-52)^2 - (1+2^-51) == 2^-104 only unrounded
    fp_arith_vec("fmadd64-fused", "FMADD", 64, O.RNE,
                 0x3FF0000000000001, 0x3FF0000000000001,
                 0xBFF0000000000002)
    fp_arith_vec("fdiv64-dz", "FDIV", 64, O.RNE, one64, 0)
    fp_arith_vec("fsqrt64-nv", "FSQRT", 64, O.RNE, one64 | (1 << 63), 0)
    fp_arith_vec("fmin-zeros", "FMIN", 64, O.RNE, 0, 1 << 63)

    # randomized differential vectors against the exact-rational oracle
    rng = random.Random(0xF10A7)
    modes = (O.RNE, O.RTZ, O.RDN, O.RUP, O.RMM)
    for w in (32, 64):
        for opname in ("FADD", "FSUB", "FMUL", "FDIV", "FSQRT", "FMADD",
                       "FMIN", "FMAX"):
            for i in range(10):
                a = _rand_fp_bits(rng, w)
                b = _rand_fp_bits(rng, w)
                c = _rand_fp_bits(rng, w) if opname == "FMADD" else None
                rm = modes[rng.randrange(5)]
                fp_arith_vec(f"rnd-{opname.lower()}{w}-{i}", opname, w,
                             rm, a, b, c)
        for opname in ("FCMPEQ", "FCMPLT", "FCMPLE"):
            for i in range(5):
                fp_cmp_vec(f"rnd-{opname.lower()}{w}-{i}", opname, w,
                           _rand_fp_bits(rng, w), _rand_fp_bits(rng, w))

    # flags are sticky until fcsr is rewritten (10.3)
    words = li64(1, one64) + _set_rm(0) + [
        enc("FDIV", dst=2, src1=1, src2=31, width=1),   # DZ
        enc("FADD", dst=3, src1=1, src2=1, width=1),    # exact: no flags
        enc("MFSR", dst=0, imm=E.SREGS["fcsr"]),
        HALT]
    expect_halt("fcsr-sticky", {0x1000: words},
                1 << E.FCSR_FLAG_BITS["DZ"])

    # reserved rounding mode: traps at the next op that rounds, not at
    # MTSR and not at FMIN/FCMP; all FCVT forms round (root
    # SPEC-ISSUES 19), so FCVTFI is the op that trips here
    expect_halt("reserved-rm-traps-at-round",
                handler_img(_set_rm(5) + [
                    enc("FMIN", dst=2, src1=1, src2=1, width=1),
                    enc("FCMPLT", dst=1, src1=1, src2=1, width=1),
                    enc("FCVTFI", dst=2, src1=1, width=1, mod=1)],
                    cause_check_handler(E.CAUSES["ILLEGAL"])), 111)
    # ... and MTSR of a good mode afterwards unwedges it
    fp_arith_vec("rm-rewrite-recovers", "FADD", 64, O.RTZ,
                 0x3FF0000000000000, 0x3CA0000000000000)

    # ILLEGAL format encodings (3.4, 10.4)
    for name, word in (
            ("fp-width2-illegal",
             enc("FADD", dst=0, src1=1, src2=2, width=2)),
            ("fcvtff-same-fmt-illegal",
             enc("FCVTFF", dst=0, src1=1, width=1, mod=1)),
            ("fcvt-mod-hi-illegal",
             enc("FCVTFI", dst=0, src1=1, width=1, mod=(1 << 2) | 1)),
            ("fcvtif-fp128-illegal",
             enc("FCVTIF", dst=0, src1=1, width=2, mod=2)),
            ("fcvtfi-src128-illegal",
             enc("FCVTFI", dst=0, src1=1, width=1, mod=2)),
            ("fcvtfi-dst-w3-illegal",
             enc("FCVTFI", dst=0, src1=1, width=3, mod=1)),
    ):
        expect_halt(name, handler_img(
            [word], cause_check_handler(E.CAUSES["ILLEGAL"])), 111)


def _cvt_words(op, wf, mod, rm, load_words):
    return load_words + _set_rm(rm) + \
        [enc(op, dst=0, src1=1, width=wf, mod=mod)]


def test_fp_cvt():
    rng = random.Random(0xC47)
    modes = (O.RNE, O.RTZ, O.RDN, O.RUP, O.RMM)
    # FP -> int, dst 32/64: pack (fcsr, low64(canonical))
    for sw in (32, 64):
        for dw, wf in ((32, 0), (64, 1)):
            for uns in (False, True):
                for i in range(3):
                    a = _rand_fp_bits(rng, sw)
                    want, fl = O.fcvt_f_to_i(O.fmt_of(sw), a, dw, uns)
                    op = "FCVTFIU" if uns else "FCVTFI"
                    words = _cvt_words(op, wf, 0 if sw == 32 else 1,
                                       0, li64(1, a)) + _fp_epilogue()
                    exp = (fl << 64) | (want & ((1 << 64) - 1))
                    expect_halt(f"f2i-{sw}-{dw}-{int(uns)}-{i}",
                                {0x1000: words}, exp)
    # FP -> int128: full canonical value, then flags separately
    for a, uns in ((0x47E0000000000000, False), (0x47E0000000000000, True),
                   (0xFFF0000000000000, False), (0xC3E0000000000001, True)):
        want, fl = O.fcvt_f_to_i(O.F64, a, 128, uns)
        op = "FCVTFIU" if uns else "FCVTFI"
        words = _cvt_words(op, 2, 1, 0, li64(1, a)) + [HALT]
        expect_halt(f"f2i128-{a:x}-{int(uns)}", {0x1000: words}, want)
        words = _cvt_words(op, 2, 1, 0, li64(1, a)) + [
            enc("MFSR", dst=0, imm=E.SREGS["fcsr"]), HALT]
        expect_halt(f"f2i128-flags-{a:x}-{int(uns)}", {0x1000: words}, fl)
    # int -> FP at every source width, incl. the u128->fp32 overflow
    for sw, sfmt in ((32, 0), (64, 1), (128, 2)):
        for dw, wf in ((32, 0), (64, 1)):
            for uns in (False, True):
                for i in range(3):
                    v = rng.getrandbits(sw)
                    rm = modes[rng.randrange(5)]
                    want, fl = O.fcvt_i_to_f(O.fmt_of(dw), v, sw, uns, rm)
                    op = "FCVTUIF" if uns else "FCVTIF"
                    load = li128(1, v) if sw == 128 else li64(1, v)
                    words = _cvt_words(op, wf, sfmt, rm, load) + \
                        _fp_epilogue()
                    exp = ((fl | (rm << E.FCSR_RM_LSB)) << 64) | \
                        _canon_low64(want, dw)
                    expect_halt(f"i2f-{sw}-{dw}-{int(uns)}-{i}",
                                {0x1000: words}, exp)
    for rm, tag in ((O.RNE, "rne"), (O.RTZ, "rtz")):
        want, fl = O.fcvt_i_to_f(O.F32, (1 << 128) - 1, 128, True, rm)
        words = _cvt_words("FCVTUIF", 0, 2, rm,
                           li128(1, (1 << 128) - 1)) + _fp_epilogue()
        exp = ((fl | (rm << E.FCSR_RM_LSB)) << 64) | _canon_low64(want, 32)
        expect_halt(f"u128max-to-f32-{tag}", {0x1000: words}, exp)
    # FP <-> FP both directions
    for i in range(8):
        a = _rand_fp_bits(rng, 64)
        rm = modes[rng.randrange(5)]
        want, fl = O.fcvt_f_to_f(O.F64, O.F32, a, rm)
        words = _cvt_words("FCVTFF", 0, 1, rm, li64(1, a)) + _fp_epilogue()
        exp = ((fl | (rm << E.FCSR_RM_LSB)) << 64) | _canon_low64(want, 32)
        expect_halt(f"f64-to-f32-{i}", {0x1000: words}, exp)
    for i in range(4):
        a = _rand_fp_bits(rng, 32)
        want, fl = O.fcvt_f_to_f(O.F32, O.F64, a, O.RNE)
        words = _cvt_words("FCVTFF", 1, 0, O.RNE, li64(1, a)) + \
            _fp_epilogue()
        exp = (fl << 64) | _canon_low64(want, 64)
        expect_halt(f"f32-to-f64-{i}", {0x1000: words}, exp)


def test_determinism():
    words = {0x1000: [
        enc("LDI", dst=2, imm=200),
        enc("LDI", dst=3, imm=0x4000),
        enc("ADD", dst=1, src1=1, src2=2, width=W128),            # loop:
        enc("ST", src1=3, src2=2, src3=1, width=3),
        enc("SUB", dst=2, src1=2, width=W128, imm=1, iform=True),
        enc("CMPEQ", dst=1, src1=2, width=W128, imm=0, iform=True),
        enc("B", imm=(-4) & IMM_MASK, pred=(1 << 1) | 1),
        enc("OR", dst=0, src1=1, src2=31, width=W128),
        HALT]}
    img_bytes = image(words)
    with tempfile.TemporaryDirectory() as d:
        ip = pathlib.Path(d) / "det.img"
        ip.write_bytes(img_bytes)
        for level in ("0", "1", "2"):
            traces = []
            for run_i in range(2):
                tp = pathlib.Path(d) / f"t{level}-{run_i}.trc"
                p = subprocess.run(
                    [str(EMU), str(ip), "--trace", str(tp), "--trace-level",
                     level, "--check-invtp"],
                    capture_output=True, timeout=60)
                check(f"det-run-l{level}-{run_i}", p.returncode == 0,
                      f"rc={p.returncode} err={p.stderr!r}")
                traces.append(tp.read_bytes())
            check(f"det-identical-l{level}", traces[0] == traces[1],
                  "traces differ")


# devspec/trace.md TV-1 (112-byte reference image) and TV-2 (its complete
# 449-byte level-1 trace). Bytes extracted mechanically from the spec's
# hex dumps; the image's SHA-256 is re-checked below against the digest
# the spec publishes, so a transcription error cannot pass silently.
TV1_IMG = bytes.fromhex(
    "534148494d473031001000000000000000000000000000000100000000000000"
    "0010000000000000000000000000000050000000000000002000000000000000"
    "20000000000000000000000000000000541000000014000003200200001e0000"
    "3600c40f00130000fe00000000000000")
TV1_SHA = "f9d6f74caea6168036806d42309781440c66f16e46c60cadf8230eabb98d60e8"
TV2_TRC = bytes.fromhex(
    "07000000a000000074726163653d310a656e636f64696e673d312e302d647261"
    "66740a6c6576656c3d310a6d6f64653d6c6976650a696d6167653d6578616d70"
    "6c652e696d670a696d6167655f7368613235363d663964366637346361656136"
    "3136383033363830366434323330393738313434306336366631366534366336"
    "30636164663832333065616262393864363065380a706c6174666f726d3d312e"
    "302d64726166740a010000003200000000000000000000000010000000000000"
    "0000000000000000541000000014000005000000000000000000000000000000"
    "0200010000003200000001000000000000000810000000000000000000000000"
    "000003200200001e00000c000000000000000000000000000000020002000000"
    "2900000002000000000000001000000000000000000000000000000008050000"
    "0000000000000000000000000001000000320000000200000000000000101000"
    "000000000000000000000000003600c40f001300000000000000000000000000"
    "0000000000000001000000320000000300000000000000181000000000000000"
    "00000000000000fe000000000000000000000000000000000000000000000000"
    "00")


def _post_meta(trc):
    """Byte offset just past record 0 (META)."""
    assert trc[0] == 7, "record 0 not META"
    plen = int.from_bytes(trc[4:8], "little")
    return 8 + plen


def test_trace_golden():
    import hashlib
    check("tv1-selfcheck", hashlib.sha256(TV1_IMG).hexdigest() == TV1_SHA,
          "embedded TV-1 bytes corrupt")
    with tempfile.TemporaryDirectory() as d:
        dp = pathlib.Path(d)
        (dp / "example.img").write_bytes(TV1_IMG)
        # Live run: the whole file, META included, must equal TV-2
        # (image= is the exact CLI argument, hence cwd=d).
        p = subprocess.run(
            [str(EMU), "example.img", "--trace", "t.trc",
             "--trace-level", "1"],
            capture_output=True, timeout=60, cwd=d)
        got = (dp / "t.trc").read_bytes()
        check("tv2-golden-trace",
              p.returncode == 0 and p.stdout == b"HALT r0=%032x\n" % 0
              and got == TV2_TRC,
              f"rc={p.returncode} err={p.stderr!r} "
              f"diff@{next((i for i in range(min(len(got), len(TV2_TRC))) if got[i] != TV2_TRC[i]), min(len(got), len(TV2_TRC)))} "
              f"len={len(got)}/{len(TV2_TRC)}")
        # Replay of that trace: post-META records byte-identical
        # (trace.md 5.2/5.3), META mode=replay.
        p = subprocess.run(
            [str(EMU), "example.img", "--replay", "t.trc", "--trace",
             "t2.trc", "--trace-level", "1"],
            capture_output=True, timeout=60, cwd=d)
        t2 = (dp / "t2.trc").read_bytes()
        check("tv2-replay-identical",
              p.returncode == 0
              and t2[_post_meta(t2):] == TV2_TRC[_post_meta(TV2_TRC):]
              and b"mode=replay\n" in t2[:_post_meta(t2)],
              f"rc={p.returncode} err={p.stderr!r}")
        # Tampered image_sha256 in META: replay must refuse to start
        # (trace.md 5.1).
        bad = bytearray(TV2_TRC)
        i = TV2_TRC.index(b"image_sha256=") + len(b"image_sha256=")
        bad[i] = ord("0") if bad[i] != ord("0") else ord("1")
        (dp / "bad.trc").write_bytes(bytes(bad))
        p = subprocess.run(
            [str(EMU), "example.img", "--replay", "bad.trc"],
            capture_output=True, timeout=60, cwd=d)
        check("replay-sha-mismatch-refused",
              p.returncode not in (0, 2, 3) and b"mismatch" in p.stderr,
              f"rc={p.returncode} err={p.stderr!r}")
        # Triple fault trace: exactly three TRAP records, the third the
        # diagnostic tl_after = 3 record of devspec/trace.md 2.3.4 --
        # the toolchain's devspec reconciliation overturned root
        # SPEC-ISSUES 17's two-record reading, and the suite's
        # checks/c1_triplefault.sh now asserts three (emu-c/SPEC-ISSUES
        # 33, resolved). vbase = dfbase = 0 turns one SYSCALL into the
        # ILLEGAL cascade.
        (dp / "tf.img").write_bytes(
            image({0x1000: [enc("LDI", dst=0, imm=77), enc("SYSCALL")]}))
        p = subprocess.run(
            [str(EMU), "tf.img", "--trace", "tf.trc", "--trace-level", "1"],
            capture_output=True, timeout=60, cwd=d)
        t = (dp / "tf.trc").read_bytes()
        off, traps = 0, []
        while off + 8 <= len(t):
            plen = int.from_bytes(t[off + 4:off + 8], "little")
            if t[off] == 4:  # TRAP
                traps.append(t[off + 8:off + 8 + plen])
            off += 8 + plen
        check("triplefault-diagnostic-trap",
              p.returncode == 0 and off == len(t) and len(traps) == 3
              and [tp[48] for tp in traps] == [1, 2, 3],
              f"rc={p.returncode} tl_afters={[tp[48] for tp in traps]}")


def _records(trc):
    """Walk trace framing: yields (offset, type, payload_len)."""
    off = 0
    while off + 8 <= len(trc):
        plen = int.from_bytes(trc[off + 4:off + 8], "little")
        yield off, trc[off], plen
        off += 8 + plen
    assert off == len(trc), "trace does not end on a record boundary"


def _filter_level(trc, types):
    """Post-META bytes of trc keeping only record types in `types`."""
    out = b""
    for off, typ, plen in _records(trc):
        if typ != 7 and typ in types:
            out += trc[off:off + 8 + plen]
    return out


def test_replay_reader():
    """--replay is a strict trace reader: devspec/trace.md 2.4 (torn
    tail tolerated with a diagnostic, malformation fatal) and 5.3
    (level nesting) on top of the 5.1 META validation tested above."""
    with tempfile.TemporaryDirectory() as d:
        dp = pathlib.Path(d)
        (dp / "example.img").write_bytes(TV1_IMG)

        def replay(trc_bytes, name):
            (dp / name).write_bytes(trc_bytes)
            return subprocess.run(
                [str(EMU), "example.img", "--replay", name],
                capture_output=True, timeout=60, cwd=d)

        recs = list(_records(TV2_TRC))
        last_off, _, last_plen = recs[-1]
        halt = b"HALT r0=%032x\n" % 0

        # Torn tail mid-payload: prefix runs, diagnostic names the
        # decimal offset of the incomplete record and bytes discarded.
        torn = TV2_TRC[:last_off + 8 + last_plen - 5]
        discarded = 8 + last_plen - 5
        p = replay(torn, "torn-payload.trc")
        check("torn-tail-mid-payload",
              p.returncode == 0 and p.stdout == halt
              and str(last_off).encode() in p.stderr
              and str(discarded).encode() in p.stderr,
              f"rc={p.returncode} err={p.stderr!r}")
        # Torn tail mid-header (3 of 8 header bytes present).
        p = replay(TV2_TRC[:last_off + 3], "torn-header.trc")
        check("torn-tail-mid-header",
              p.returncode == 0 and p.stdout == halt
              and str(last_off).encode() in p.stderr
              and b"3 bytes discarded" in p.stderr,
              f"rc={p.returncode} err={p.stderr!r}")
        # Truncation exactly at a record boundary: a valid prefix, no
        # diagnostic.
        p = replay(TV2_TRC[:last_off], "prefix.trc")
        check("clean-prefix-no-diagnostic",
              p.returncode == 0 and p.stdout == halt and p.stderr == b"",
              f"rc={p.returncode} err={p.stderr!r}")

        # Malformation classes (trace.md 2.4): each rejected fatally,
        # the run never starts (no HALT on stdout).
        r1_off, r1_type, r1_plen = recs[1]
        assert r1_type == 1, "TV-2 record 1 expected EXEC"

        def expect_reject(name, trc_bytes, why):
            p = replay(trc_bytes, name + ".trc")
            check(name,
                  p.returncode not in (0, 2, 3) and b"HALT" not in p.stdout
                  and why in p.stderr,
                  f"rc={p.returncode} out={p.stdout!r} err={p.stderr!r}")

        bad = bytearray(TV2_TRC)
        bad[r1_off + 1] = 1
        expect_reject("malformed-reserved-byte", bytes(bad), b"reserved")
        bad = bytearray(TV2_TRC)
        bad[r1_off] = 8
        expect_reject("malformed-bad-type", bytes(bad), b"type")
        bad = bytearray(TV2_TRC)
        bad[r1_off + 4] = 49  # EXEC fixed payload length is 50
        expect_reject("malformed-wrong-fixed-len", bytes(bad),
                      b"payload length")
        meta_len = 8 + recs[0][2]
        expect_reject("malformed-duplicate-meta",
                      TV2_TRC + TV2_TRC[:meta_len], b"duplicate META")
        bad = bytearray(TV2_TRC)
        bad[r1_off + 8 + 48] |= 0x80  # EXEC flags bits 7:3 (payload @48)
        expect_reject("malformed-exec-flags-high", bytes(bad), b"flags")
        # Decreasing cycle: zero the last record's cycle stamp; some
        # earlier record must carry a larger one for the test to bite.
        cycles = [int.from_bytes(TV2_TRC[o + 8:o + 16], "little")
                  for o, t, _ in recs if t != 7]
        assert max(cycles[:-1]) > 0, "TV-2 cycles all zero?"
        bad = bytearray(TV2_TRC)
        bad[last_off + 8:last_off + 16] = bytes(8)
        expect_reject("malformed-cycle-decrease", bytes(bad), b"decreases")
        # EVENT with inner payload_len != payload length - 20.
        maxc = max(cycles).to_bytes(8, "little")
        ev = bytes([5, 0, 0, 0]) + (24).to_bytes(4, "little") + maxc \
            + bytes(8) + (99).to_bytes(4, "little") + bytes(4)
        expect_reject("malformed-event-innerlen", TV2_TRC + ev,
                      b"payload_len")
        # EVENT payload validation (trace.md 4): device index resolves
        # against the fixed reference table, payload shape per type.
        def ev_rec(device, payload):
            return bytes([5, 0, 0, 0]) \
                + (20 + len(payload)).to_bytes(4, "little") + maxc \
                + device.to_bytes(8, "little") \
                + len(payload).to_bytes(4, "little") + payload

        kbd = (0x100000004).to_bytes(8, "little") + b"\x00"
        p = replay(TV2_TRC + ev_rec(1, kbd), "wellformed-kbd.trc")
        check("wellformed-event-accepted",
              p.returncode == 0 and p.stdout == halt,
              f"rc={p.returncode} out={p.stdout!r} err={p.stderr!r}")
        expect_reject("event-device-oob", TV2_TRC + ev_rec(5, kbd),
                      b"device index")
        expect_reject("event-resize-bad-len", TV2_TRC + ev_rec(0, kbd),
                      b"32 bytes")
        resize_fmt2 = b"".join(v.to_bytes(8, "little")
                               for v in (640, 480, 2560, 2))
        expect_reject("event-resize-bad-format",
                      TV2_TRC + ev_rec(0, resize_fmt2), b"format")
        kbd_hi = (1 << 40 | 4).to_bytes(8, "little") + b"\x00"
        expect_reject("event-kbd-reserved-word-bits",
                      TV2_TRC + ev_rec(1, kbd_hi), b"reserved bits")
        kbd_flags = (0x100000004).to_bytes(8, "little") + b"\x02"
        expect_reject("event-flags-reserved-bits",
                      TV2_TRC + ev_rec(1, kbd_flags), b"flags bits")
        # NIC EVENTs load into the RX model (SPEC-ISSUES 35's gap is
        # closed): frame-length payloads are accepted and injected,
        # anything outside [60, 1514] is not a v1 trace (nic.md 3.1).
        p = replay(TV2_TRC + ev_rec(3, bytes(64)), "wellformed-nic.trc")
        check("nic-event-accepted",
              p.returncode == 0 and p.stdout == halt,
              f"rc={p.returncode} out={p.stdout!r} err={p.stderr!r}")
        expect_reject("nic-event-under-min",
                      TV2_TRC + ev_rec(3, bytes(59)), b"1514")
        expect_reject("nic-event-over-max",
                      TV2_TRC + ev_rec(3, bytes(1515)), b"1514")
        # RNG EVENTs (trace.md 4.6): whole u64 words, 1..128 of them.
        p = replay(TV2_TRC + ev_rec(4, bytes(16)), "wellformed-rng.trc")
        check("rng-event-accepted",
              p.returncode == 0 and p.stdout == halt,
              f"rc={p.returncode} out={p.stdout!r} err={p.stderr!r}")
        expect_reject("rng-event-ragged",
                      TV2_TRC + ev_rec(4, bytes(9)), b"u64 words")
        expect_reject("rng-event-over-max",
                      TV2_TRC + ev_rec(4, bytes(1032)), b"u64 words")

        # Level nesting (trace.md 5.3): filtering the level-2 trace to
        # level-1 record types must equal the level-1 trace post-META,
        # and likewise level 1 -> level 0.
        by_level = {}
        for level in ("0", "1", "2"):
            p = subprocess.run(
                [str(EMU), "example.img", "--trace", f"n{level}.trc",
                 "--trace-level", level],
                capture_output=True, timeout=60, cwd=d)
            check(f"nesting-run-l{level}", p.returncode == 0,
                  f"rc={p.returncode} err={p.stderr!r}")
            by_level[level] = (dp / f"n{level}.trc").read_bytes()
        l1_types = {1, 4, 5, 2, 6}   # EXEC TRAP EVENT + MEMW DEVW
        l0_types = {1, 4, 5}
        check("level-nesting-l2-to-l1",
              _filter_level(by_level["2"], l1_types)
              == by_level["1"][_post_meta(by_level["1"]):])
        check("level-nesting-l1-to-l0",
              _filter_level(by_level["1"], l0_types)
              == by_level["0"][_post_meta(by_level["0"]):])


def test_replay_fuzz():
    """Arbitrary bytes fed to --replay must terminate cleanly: either
    the strict reader accepts a well-formed (possibly torn-tail) file
    and the run reaches HALT, or it rejects with exit 1 and a stderr
    diagnostic. Never a crash (signal), never a silent nonzero, never
    a hang (subprocess timeout would throw)."""
    rng = random.Random(20260807)
    bad = 0
    with tempfile.TemporaryDirectory() as d:
        dp = pathlib.Path(d)
        (dp / "example.img").write_bytes(TV1_IMG)

        def one(tag, data):
            nonlocal bad
            (dp / "fuzz.trc").write_bytes(data)
            p = subprocess.run(
                [str(EMU), "example.img", "--replay", "fuzz.trc"],
                capture_output=True, timeout=60, cwd=d)
            ok = (p.returncode == 0 and p.stdout.startswith(b"HALT r0=")) \
                or (p.returncode == 1 and p.stderr != b"")
            if not ok:
                bad += 1
                print(f"    replay fuzz {tag}: rc={p.returncode} "
                      f"len={len(data)} out={p.stdout[:80]!r} "
                      f"err={p.stderr[:200]!r}")

        # Pure random bytes at assorted lengths (incl. empty).
        for i in range(60):
            one(f"random #{i}", rng.randbytes(rng.randrange(0, 2500)))
        # Random byte mutations of a valid trace (1..8 corruptions):
        # exercises every reader path past the META gate.
        for i in range(90):
            data = bytearray(TV2_TRC)
            for _ in range(rng.randrange(1, 9)):
                data[rng.randrange(len(data))] = rng.randrange(256)
            one(f"mutate #{i}", bytes(data))
        # Every truncation point is either a clean prefix or a torn
        # tail -- both accepted, neither may crash.
        for i in range(40):
            one(f"truncate #{i}", TV2_TRC[:rng.randrange(len(TV2_TRC))])
        # Valid trace + random garbage appended (torn/malformed tail).
        for i in range(40):
            one(f"append #{i}",
                TV2_TRC + rng.randbytes(rng.randrange(1, 600)))
    check("replay-fuzz", bad == 0, f"{bad} runs crashed/misbehaved")


def test_fuzz():
    rng = random.Random(1234)
    bad = 0
    for i in range(250):
        word = rng.getrandbits(64)
        p = run({0x1000: [word]}, args=("--maxcycles", "400",
                                        "--check-invtp"))
        if p.returncode not in (0, 2):
            bad += 1
            print(f"    fuzz single #{i}: word={word:#018x} "
                  f"rc={p.returncode} err={p.stderr[:200]!r}")
    for i in range(60):
        words = [rng.getrandbits(64) for _ in range(16)]
        p = run({0x1000: words}, args=("--maxcycles", "400", "--check-invtp"))
        if p.returncode not in (0, 2):
            bad += 1
            print(f"    fuzz multi #{i}: rc={p.returncode} "
                  f"err={p.stderr[:200]!r}")
    check("decoder-fuzz", bad == 0, f"{bad} runs crashed/errored")


def test_cli_contract():
    p = run({0x1000: [enc("B", imm=0)]}, args=("--maxcycles", "10"))
    check("maxcycles-contract", p.returncode == 2 and p.stdout == b"MAXCYCLES\n",
          f"rc={p.returncode} out={p.stdout!r}")
    p = run({0x1000: [HALT]}, args=("--ram", str(1 << 20)))
    check("ram-flag", p.returncode == 0, f"rc={p.returncode} err={p.stderr!r}")


def main():
    if not EMU.exists():
        print(f"emulator binary missing: {EMU}", file=sys.stderr)
        return 1
    print("basic:")
    test_basic()
    print("predication:")
    test_predication()
    print("memory/atomics:")
    test_memory()
    print("traps:")
    test_traps()
    print("device-space decode:")
    test_devspace()
    print("interrupts:")
    test_interrupts()
    print("mulh vs bigint:")
    test_mulh_bigint()
    print("fp vs oracle:")
    test_fp()
    print("fp conversions:")
    test_fp_cvt()
    print("determinism:")
    test_determinism()
    print("trace golden (devspec/trace.md TV-1/TV-2):")
    test_trace_golden()
    print("replay reader (devspec/trace.md 2.4/5.3):")
    test_replay_reader()
    print("cli:")
    test_cli_contract()
    print("fuzz:")
    test_fuzz()
    print("replay-file fuzz:")
    test_replay_fuzz()
    if failures:
        print(f"\n{len(failures)} FAILURES: {failures}")
        return 1
    print("\nall image tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
