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
    print("interrupts:")
    test_interrupts()
    print("mulh vs bigint:")
    test_mulh_bigint()
    print("determinism:")
    test_determinism()
    print("cli:")
    test_cli_contract()
    print("fuzz:")
    test_fuzz()
    if failures:
        print(f"\n{len(failures)} FAILURES: {failures}")
        return 1
    print("\nall image tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
