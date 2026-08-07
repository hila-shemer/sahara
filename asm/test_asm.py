#!/usr/bin/env python3
"""Assembler validation — independent of any emulator.

Checks, per toolchain-prompt "Validating without an emulator":
  1. Field-level round-trip: assemble source, decode the emitted words
     field-by-field via encoding.py FIELDS, compare against expected
     field values written out longhand here.
  2. li/la chain semantics: simulate LDI/SHORI/LAP per ISA-SPEC 5.6 (an
     independent implementation of their semantics, ~5 lines) and check
     the chain reconstructs the constant exactly.
  3. Image format per TOOLING-SPEC section 1, symbol sidecar per
     section 2, parsed byte-by-byte here.
  4. Loud failure: every listed bad input must be rejected with an error
     naming file:line.

Run: python3 asm/test_asm.py   (exit 0 = pass)
"""

import os
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
import encoding as E  # noqa: E402
import asm as A       # noqa: E402

FAILURES = []


def check(cond, msg):
    if not cond:
        FAILURES.append(msg)
        print("FAIL:", msg)


def decode(word):
    out = {}
    for name, (lsb, width) in E.FIELDS.items():
        out[name] = (word >> lsb) & ((1 << width) - 1)
    return out


def opc(name, iform=False):
    return E.OPCODES[name][0] + (1 if iform else 0)


def widx(fam, w):
    return E.FAMILIES[fam]["widths"].index(w)


def simm(v):
    return v & ((1 << E.IMM_BITS) - 1)


def asm_words(source, org=0x1000):
    """Assemble a snippet; return (words, asm object, image bytes)."""
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "t.s")
        img = os.path.join(td, "t.img")
        with open(src, "w") as f:
            f.write(source)
        a = A.assemble([src], img, img[:-4] + ".sym")
        with open(img, "rb") as f:
            image = f.read()
        with open(img[:-4] + ".sym") as f:
            sym = f.read()
    words = []
    for seg in a.segments:
        if seg.data:
            words.extend(struct.unpack(f"<{len(seg.data)//8}Q",
                                       bytes(seg.data))
                         if len(seg.data) % 8 == 0 else [])
    return words, a, image, sym


def expect_fields(line, **want):
    """Assemble a single instruction line, compare decoded fields."""
    words, _, _, _ = asm_words(f"{line}\n")
    if len(words) != 1:
        check(False, f"{line!r}: expected 1 word, got {len(words)}")
        return
    got = decode(words[0])
    full = {k: 0 for k in E.FIELDS}
    full.update(want)
    for k in E.FIELDS:
        check(got[k] == full[k],
              f"{line!r}: field {k} = {got[k]:#x}, want {full[k]:#x}")


def expect_error(source, why):
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "t.s")
        with open(src, "w") as f:
            f.write(source)
        r = subprocess.run(
            [sys.executable, os.path.join(HERE, "asm.py"), "-o",
             os.path.join(td, "t.img"), src],
            capture_output=True, text=True)
        check(r.returncode != 0, f"{why}: assembler accepted bad input")
        if r.returncode != 0:
            check("error" in r.stderr and ":" in r.stderr,
                  f"{why}: error not in file:line form: {r.stderr!r}")


# ------------------------------------------------- 1. field-level round-trip

W32, W64, W128 = widx("ALU", 32), widx("ALU", 64), widx("ALU", 128)

expect_fields("add r1, r2, r3",
              opcode=opc("ADD"), dst=1, src1=2, src2=3, width=W128)
expect_fields("add.32 r1, r2, 5",
              opcode=opc("ADD", True), dst=1, src1=2, imm=5, width=W32)
expect_fields("sub.64 r4, r5, -6",
              opcode=opc("SUB", True), dst=4, src1=5, imm=simm(-6),
              width=W64)
expect_fields("add r1, r2, r3 shl 3",
              opcode=opc("ADD"), dst=1, src1=2, src2=3, mod=(3 << 2) | 1,
              width=W128)
expect_fields("add r1, r2, r3 sxt 8",
              opcode=opc("ADD"), dst=1, src1=2, src2=3, mod=(8 << 2) | 2,
              width=W128)
expect_fields("and.64 r1, r2, r3 zxt 16",
              opcode=opc("AND"), dst=1, src1=2, src2=3, mod=(16 << 2) | 3,
              width=W64)
expect_fields("madd r1, r2, r3, r4",
              opcode=opc("MADD"), dst=1, src1=2, src2=3, src3=4,
              width=W128)
expect_fields("madd.32 r1, r2, 7, r4",
              opcode=opc("MADD", True), dst=1, src1=2, imm=7, src3=4,
              width=W32)
expect_fields("mulhu.64 r9, r10, r11",
              opcode=opc("MULHU"), dst=9, src1=10, src2=11, width=W64)
expect_fields("cmplt p3, r1, r2",
              opcode=opc("CMPLT"), dst=3, src1=1, src2=2,
              width=widx("CMP", 128))
expect_fields("cmpeq.64 p5, r1, -1",
              opcode=opc("CMPEQ", True), dst=5, src1=1, imm=simm(-1),
              width=widx("CMP", 64))
expect_fields("cmpleu.32 p7, r30, r0",
              opcode=opc("CMPLEU"), dst=7, src1=30, src2=0,
              width=widx("CMP", 32))
# predication: pred field = index<<1 | polarity
expect_fields("(p3) add r1, r2, r3",
              opcode=opc("ADD"), pred=6, dst=1, src1=2, src2=3, width=W128)
expect_fields("(!p7) or r1, r2, r3",
              opcode=opc("OR"), pred=15, dst=1, src1=2, src2=3, width=W128)
# register aliases
expect_fields("add r1, sp, ra",
              opcode=opc("ADD"), dst=1, src1=28, src2=29, width=W128)
expect_fields("add r1, k0, zero",
              opcode=opc("ADD"), dst=1, src1=30, src2=31, width=W128)
# memory
expect_fields("lds.32 r1, [r2 + r3 shl 2 + 8]",
              opcode=opc("LDS"), dst=1, src1=2, src2=3, mod=(2 << 2) | 1,
              imm=8, width=widx("MEM", 32))
expect_fields("ldz.8 r1, [r2]",
              opcode=opc("LDZ"), dst=1, src1=2, src2=31,
              width=widx("MEM", 8))
expect_fields("lds.64 r1, [r2 - 16]",
              opcode=opc("LDS"), dst=1, src1=2, src2=31, imm=simm(-16),
              width=widx("MEM", 64))
expect_fields("ld128 r1, [r2 - 16]",
              opcode=opc("LD128"), dst=1, src1=2, src2=31, imm=simm(-16))
expect_fields("st.16 r5, [r6 + 4]",
              opcode=opc("ST"), src3=5, src1=6, src2=31, imm=4,
              width=widx("MEM", 16))
expect_fields("st128 r5, [r6 + r7]",
              opcode=opc("ST128"), src3=5, src1=6, src2=7)
# atomics
expect_fields("cas.64 r1, [r2 + 8], r3, r4",
              opcode=opc("CAS"), dst=1, src1=2, src2=3, src3=4, imm=8,
              width=widx("ATOMIC", 64))
expect_fields("amoadd.32 r1, [r2], r3",
              opcode=opc("AMOADD"), dst=1, src1=2, src2=3,
              width=widx("ATOMIC", 32))
expect_fields("amomaxu r1, [r2 - 4], r3",
              opcode=opc("AMOMAXU"), dst=1, src1=2, src2=3, imm=simm(-4),
              width=widx("ATOMIC", 128))
# constants
expect_fields("ldi r1, -100", opcode=opc("LDI"), dst=1, imm=simm(-100))
expect_fields("shori r1, r1, 0x3fffff",
              opcode=opc("SHORI"), dst=1, src1=1, imm=0x3FFFFF)
# predicate file
expect_fields("prd r3", opcode=opc("PRD"), dst=3)
expect_fields("pwr r4", opcode=opc("PWR"), src1=4)
# system
expect_fields("mfsr r1, status",
              opcode=opc("MFSR"), dst=1, imm=E.SREGS["status"])
expect_fields("mfsr r1, epc1",
              opcode=opc("MFSR"), dst=1, imm=E.SREGS["epc1"])
expect_fields("mfsr r1, 99", opcode=opc("MFSR"), dst=1, imm=99)
expect_fields("mtsr timecmp, r2",
              opcode=opc("MTSR"), src1=2, imm=E.SREGS["timecmp"])
for bare in ("syscall", "iret", "invtp", "ifence", "wfi", "halt",
             "illegal"):
    expect_fields(bare, opcode=opc(bare.upper()))
# jalr is imm-based, no label
expect_fields("jalr r1, r2, 16",
              opcode=opc("JALR"), dst=1, src1=2, imm=16)
expect_fields("ret", opcode=opc("JALR"), dst=31, src1=29, imm=0)
# FP
expect_fields("fadd.f32 r1, r2, r3",
              opcode=opc("FADD"), dst=1, src1=2, src2=3,
              width=widx("FP", "FP32"))
expect_fields("fmadd.f64 r1, r2, r3, r4",
              opcode=opc("FMADD"), dst=1, src1=2, src2=3, src3=4,
              width=widx("FP", "FP64"))
expect_fields("fsqrt.f64 r1, r2",
              opcode=opc("FSQRT"), dst=1, src1=2, width=widx("FP", "FP64"))
expect_fields("fcmplt.f32 p2, r1, r2",
              opcode=opc("FCMPLT"), dst=2, src1=1, src2=2,
              width=widx("FP", "FP32"))
# FCVT: width = dest format code, mod bits 1:0 = source format code
expect_fields("fcvtfi.32 r1, r2, f64",
              opcode=opc("FCVTFI"), dst=1, src1=2, width=0, mod=1)
expect_fields("fcvtfi.128 r1, r2, f32",
              opcode=opc("FCVTFI"), dst=1, src1=2, width=2, mod=0)
expect_fields("fcvtfiu.64 r1, r2, f32",
              opcode=opc("FCVTFIU"), dst=1, src1=2, width=1, mod=0)
expect_fields("fcvtif.f64 r1, r2, i32",
              opcode=opc("FCVTIF"), dst=1, src1=2, width=1, mod=0)
expect_fields("fcvtuif.f32 r1, r2, i128",
              opcode=opc("FCVTUIF"), dst=1, src1=2, width=0, mod=2)
expect_fields("fcvtff.f64 r1, r2, f32",
              opcode=opc("FCVTFF"), dst=1, src1=2, width=1, mod=0)
# pseudos with fixed expansions
expect_fields("mov r3, r7",
              opcode=opc("OR"), dst=3, src1=7, src2=31, width=W128)
expect_fields("nop", opcode=opc("OR"), dst=31, src1=31, src2=31,
              width=W128)
expect_fields("not r3, r7",
              opcode=opc("XOR", True), dst=3, src1=7, imm=simm(-1),
              width=W128)
expect_fields("neg.64 r3, r7",
              opcode=opc("SUB"), dst=3, src1=31, src2=7, width=W64)
expect_fields("sub r3, 0, r7",
              opcode=opc("SUB"), dst=3, src1=31, src2=7, width=W128)

# ------------------------------------------------------- branch arithmetic

src = """\
start:
    nop
    b start
    b fwd
    jal r5, start
    jal fwd
    (p1) b start
fwd:
    jalr r1, r2, -8
"""
words, a, _, _ = asm_words(src)
d = [decode(w) for w in words]
check(d[1]["opcode"] == opc("B") and d[1]["imm"] == simm(-1),
      f"b start: imm {d[1]['imm']:#x} != -1")
check(d[2]["imm"] == simm(4), f"b fwd: imm {d[2]['imm']:#x} != 4")
check(d[3]["opcode"] == opc("JAL") and d[3]["dst"] == 5
      and d[3]["imm"] == simm(-3), "jal r5, start wrong")
check(d[4]["dst"] == 29 and d[4]["imm"] == simm(2),
      "bare jal fwd: must link ra and reach fwd")
check(d[5]["pred"] == 2 and d[5]["imm"] == simm(-5), "(p1) b start wrong")
check(d[6]["opcode"] == opc("JALR") and d[6]["imm"] == simm(-8),
      "jalr negative imm wrong")

# lap: operand is a target address; imm = target - pc
words, _, _, _ = asm_words("here:\n    lap r1, here\n    lap r2, there\n"
                           "there:\n    nop\n")
d = [decode(w) for w in words]
check(d[0]["opcode"] == opc("LAP") and d[0]["imm"] == 0, "lap here wrong")
check(d[1]["imm"] == simm(8), "lap there: imm != 8")

# ------------------------------------- 2. li / la chain semantics (indep.)


def sext(v, bits):
    v &= (1 << bits) - 1
    return v - (1 << bits) if v >= 1 << (bits - 1) else v


def run_chain(words):
    """Independent LDI/SHORI interpreter per ISA-SPEC 5.6."""
    regs = {}
    for w in words:
        f = decode(w)
        if f["opcode"] == opc("LDI"):
            regs[f["dst"]] = sext(f["imm"], E.IMM_BITS) & A.MASK128
        elif f["opcode"] == opc("SHORI"):
            regs[f["dst"]] = ((regs.get(f["src1"], 0) << E.IMM_BITS)
                             | f["imm"]) & A.MASK128
        else:
            raise AssertionError(f"non-chain opcode {f['opcode']:#x}")
    return regs


LI_CASES = [0, 1, -1, 0x600D, -(1 << 21), (1 << 21) - 1, 1 << 21,
            0x123456, 0xDEADBEEF, 1 << 63, (1 << 64) - 1, 1 << 64,
            0x0123456789ABCDEF_FEDCBA9876543210, (1 << 127), -(1 << 127),
            (1 << 128) - 1, 0x700, 0x0F030000, 0x10000000]
for v in LI_CASES:
    words, _, _, _ = asm_words(f"li r1, {v}\n")
    n = len(words)
    check(n == A.minimal_chain_len(v),
          f"li {v:#x}: chain len {n} != minimal "
          f"{A.minimal_chain_len(v)}")
    got = run_chain(words).get(1, 0)
    check(got == v & A.MASK128,
          f"li {v:#x}: chain builds {got:#x}")

# minimality spot checks
check(A.minimal_chain_len(0) == 1, "chain(0) != 1")
check(A.minimal_chain_len(-1) == 1, "chain(-1) != 1")
check(A.minimal_chain_len((1 << 21) - 1) == 1, "chain(2^21-1) != 1")
check(A.minimal_chain_len(1 << 21) == 2, "chain(2^21) != 2")
check(A.minimal_chain_len((1 << 128) - 1) == 1, "chain(all-ones) != 1")
check(A.minimal_chain_len(1 << 127) == 6, "chain(2^127) != 6")

# la: near = single LAP; far = LAP + ADD; la.abs = LDI/SHORI chain
words, _, _, _ = asm_words("x:\n    la r1, x\n")
check(len(words) == 1 and decode(words[0])["opcode"] == opc("LAP")
      and decode(words[0])["imm"] == 0, "la near must be a single LAP")

src = "    la r1, far\n    .org 0x400000\nfar:\n    nop\n"
words, a2, _, _ = asm_words(src)
f0, f1 = decode(words[0]), decode(words[1])
check(f0["opcode"] == opc("LAP"), "la far word0 not LAP")
check(f1["opcode"] == opc("ADD", True) and f1["width"] == W128
      and f1["dst"] == 1 and f1["src1"] == 1, "la far word1 not ADD.128 imm")
lap_pc = 0x1000
got = (lap_pc + sext(f0["imm"], E.IMM_BITS)
       + sext(f1["imm"], E.IMM_BITS)) & A.MASK128
check(got == 0x400000, f"la far builds {got:#x} != 0x400000")

words, _, _, _ = asm_words("    la.abs r1, far\n"
                           "    .org 0x400000\nfar:\n    nop\n")
got = run_chain([w for w in words[:-1]]).get(1, 0)
check(got == 0x400000, f"la.abs builds {got:#x} != 0x400000")

# forward-reference li reserves the full 6-word chain (documented policy)
words, _, _, _ = asm_words("    li r1, fwd\nfwd:\n    nop\n")
check(len(words) == 7, f"forward li: {len(words)-1} chain words, want 6")
got = run_chain(words[:-1]).get(1, 0)
check(got == 0x1000 + 48, f"forward li builds {got:#x}")

# ------------------------------------------- 3. image + sym byte formats

src = """\
    .equ MAGIC, 0x600D
start:
    li r0, MAGIC
    halt
data1:
    .byte 1, 2, 0xFF
    .half 0x1234
    .word 0xDEADBEEF
    .quad -1
    .oct 0x10000000000000000
    .asciiz "hi\\n"
    .align 8
aligned:
    .space 4
    .org 0x8000
seg2:
    .word 42
"""
words, a3, image, sym = asm_words(src)
check(image[:8] == b"SAHIMG01", "image magic wrong")
entry_lo, entry_hi = struct.unpack_from("<QQ", image, 8)
check(entry_lo == 0x1000 and entry_hi == 0, "default entry != 0x1000")
nsegs, = struct.unpack_from("<Q", image, 24)
check(nsegs == 2, f"nsegs {nsegs} != 2")
mem = {}
off = 32
for i in range(nsegs):
    lo, hi, foff, flen, mlen, flags = struct.unpack_from("<QQQQQQ",
                                                         image, off)
    base = lo | (hi << 64)
    check(mlen >= flen and flags == 0, f"segment {i} descriptor invalid")
    for j in range(flen):
        mem[base + j] = image[foff + j]
    for j in range(flen, mlen):
        mem[base + j] = 0
    off += 48
check(mem[0x8000] == 42, "segment 2 payload wrong")
lbl = a3.labels
d1 = lbl["data1"]
check(mem[d1] == 1 and mem[d1 + 1] == 2 and mem[d1 + 2] == 0xFF,
      ".byte payload wrong")
check(mem[d1 + 3] | (mem[d1 + 4] << 8) == 0x1234, ".half payload wrong")
w = mem[d1 + 5] | (mem[d1 + 6] << 8) | (mem[d1 + 7] << 16) | \
    (mem[d1 + 8] << 24)
check(w == 0xDEADBEEF, ".word payload wrong")
q = sum(mem[d1 + 9 + i] << (8 * i) for i in range(8))
check(q == (1 << 64) - 1, ".quad -1 payload wrong")
o = sum(mem[d1 + 17 + i] << (8 * i) for i in range(16))
check(o == 1 << 64, ".oct payload wrong")
s0 = d1 + 33
check(bytes(mem[s0 + i] for i in range(4)) == b"hi\n\0",
      ".asciiz payload wrong")
check(lbl["aligned"] % 8 == 0, ".align result not aligned")
sym_lines = sym.strip().split("\n")
for line in sym_lines:
    parts = line.split()
    check(len(parts) == 3 and len(parts[0]) == 32,
          f"bad sym line {line!r}")
symmap = {p[2]: (int(p[0], 16), p[1])
          for p in (line.split() for line in sym_lines)}
check(symmap["start"] == (0x1000, "T"), "start symbol wrong")
check(symmap["data1"][1] == "D", "data1 kind not D")
check(symmap["MAGIC"] == (0x600D, "A"), "MAGIC equ symbol wrong")
check(symmap["seg2"] == (0x8000, "D"), "seg2 symbol wrong")
addrs = [int(line.split()[0], 16) for line in sym_lines]
check(addrs == sorted(addrs), "sym file not sorted by address")

# .entry directive
words, a4, image, _ = asm_words("    nop\ne:\n    halt\n    .entry e\n")
entry_lo, entry_hi = struct.unpack_from("<QQ", image, 8)
check(entry_lo == 0x1008 and entry_hi == 0, ".entry not honored")

# ---------------------------------------------------- 4. loud failures

expect_error("    add r1, r2, 0x200000\n", "imm too big for signed 22")
expect_error("    add r1, r2, -0x200001\n", "imm too small")
expect_error("    shori r1, r1, -1\n", "shori imm must be unsigned")
expect_error("    shori r1, r1, 0x400000\n", "shori imm > 22 bits")
expect_error("    st r1, [r2]\n", "st needs width suffix")
expect_error("    lds.128 r1, [r2]\n", "lds.128 is not a width")
expect_error("    add.16 r1, r2, r3\n", "alu width 16 invalid")
expect_error("    fadd r1, r2, r3\n", "fp needs format suffix")
expect_error("    fcvtff.f32 r1, r2, f32\n", "fcvtff same format")
expect_error("    fcvtif.f32 r1, r2, f64\n", "fcvtif fp source")
expect_error("    cas.64 r1, [r2 + r3], r4, r5\n", "atomic index reg")
expect_error("    add r1, r2, r3 shl 64\n", "mod amount > 63")
expect_error("    b unknown_label\n", "undefined label")
expect_error("x:\nx:\n    nop\n", "duplicate label")
expect_error("    bogus r1, r2\n", "unknown mnemonic")
expect_error("    mfsr r1, nosuchsreg\n", "unknown sreg name")
expect_error("    .byte 256\n", ".byte range")
expect_error("    .byte\n", ".byte empty")
expect_error("    .org 0x800\n    nop\n", "overlap with device table")
expect_error("    .org 0x1000\n    nop\n    .org 0x1000\n    nop\n",
             "overlapping segments")
expect_error("    .align 3\n", ".align non-power-of-two")
expect_error("    .equ a, b\n    .equ b, a\n    .word a\n", ".equ cycle")
expect_error("    sub r3, 5, r7\n", "reverse-sub imm != 0")
expect_error("    jal r1, start\n    .byte 1\nstart2:\n    nop\n",
             "undefined branch target")
expect_error("    .byte 1\n    nop\n", "misaligned instruction")
expect_error("    li r1, 0x100000000000000000000000000000000\n",
             "li constant > 128 bits")
expect_error("(p8) nop\n", "predicate index 8")
expect_error("    ldi r1, 1 +\n", "trailing operator in expression")
expect_error('    .ascii "bad\\q"\n', "unknown string escape")

# multi-file concatenation
with tempfile.TemporaryDirectory() as td:
    p1, p2 = os.path.join(td, "a.s"), os.path.join(td, "b.s")
    with open(p1, "w") as f:
        f.write("start:\n    jal r5, other\n")
    with open(p2, "w") as f:
        f.write("other:\n    halt\n")
    a5 = A.assemble([p1, p2], os.path.join(td, "o.img"),
                    os.path.join(td, "o.sym"))
    check(a5.labels["other"] == 0x1008, "multi-file label address wrong")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURES")
    sys.exit(1)
print("asm/test_asm.py: all checks passed")
