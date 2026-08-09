#!/usr/bin/env python3
"""devspec/asm.md conformance — the T1-T5 test vectors and the testable
ASM-1..ASM-22 requirements, enforced byte-exactly against asm/asm.py.

The vectors are PARSED OUT OF devspec/asm.md itself (T1/T2/T4 blocks), so
this file cannot drift from the spec: edit asm.md and this test follows.

Coverage bounds (stated per toolchain-prompt "no silent gaps"):
  - ASM-19 is checked in-process by monkeypatching one encoding.py opcode
    value and observing the output change; the "generated header" half of
    the requirement (a C consumer) has no Python-side test.
  - Line attribution for whole-image errors (E042/E045/E046/E047/E048/
    E049) is not pinned by asm.md; this suite pins the conventions in
    SPEC-ISSUES.md 34 (E042 -> the later .org line, E045 -> the empty
    .org line, E046-E048 -> the .entry line, E049 -> the first .org
    line).
  - SPEC-ISSUES.md 33: asm.md 8.2's parenthetical trim rule ("index of
    the last non-zero byte + 1") would give T4 segment 1 file_len 25,
    but the T4 dump says 32 and trace.md TV-1 (sha-pinned into TV-2's
    META) agrees: instruction-emitted bytes are never trimmed. The
    assembler implements that fixture-consistent reading, and this suite
    enforces T4 byte-identically (ASM-9 as written).

Run: python3 asm/test_asmmd.py   (exit 0 = pass)
"""

import os
import re
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

SPEC = os.path.join(ROOT, "devspec", "asm.md")
with open(SPEC) as f:
    MD = f.read()

FAILURES = []


def check(cond, msg):
    if not cond:
        FAILURES.append(msg)
        print("FAIL:", msg)


def strip_src(src):
    return src.split("#", 1)[0].strip()


# ------------------------------------------------------------ assembly aids


def assemble(source):
    """In-process assemble; returns the Assembler (or raises AsmError)."""
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.s")
        with open(path, "w") as f:
            f.write(source)
        return A.assemble([path], os.path.join(td, "t.img"),
                          os.path.join(td, "t.sym"))


def words_of(asm, seg_index=0):
    """Leading 8-byte words of a segment (data tails may misalign it)."""
    data = bytes(asm.segments[seg_index].data)
    n = len(data) // 8
    return list(struct.unpack(f"<{n}Q", data[:n * 8]))


def run_cli(source, name="t.s", extra_files=(), out="t.img",
            pre_outputs=False):
    """CLI-level run; returns (rc, stderr, img bytes|None, sym text|None,
    img exists, sym exists)."""
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, name)
        with open(path, "w") as f:
            f.write(source)
        img = os.path.join(td, out)
        sym = (img[:-4] if img.endswith(".img") else img) + ".sym"
        if pre_outputs:
            for p in (img, sym):
                with open(p, "w") as f:
                    f.write("stale")
        r = subprocess.run(
            [sys.executable, os.path.join(HERE, "asm.py"), "-o", img,
             path],
            capture_output=True, text=True)
        img_b = open(img, "rb").read() if os.path.exists(img) else None
        sym_t = open(sym).read() if os.path.exists(sym) else None
        return r.returncode, r.stderr, img_b, sym_t


# --------------------------------------------------- T1: single encodings

T1_RE = re.compile(r"^T1\.(\d+) \| 0x([0-9A-F]{16}) \| (.+)$", re.M)
T1 = [(int(n), int(h, 16), s.rstrip()) for n, h, s in T1_RE.findall(MD)]
check(len(T1) == 60, f"T1: parsed {len(T1)} vectors, want 60")

NOPS = "    nop\n"


def t1_program(vid, src):
    """Build the minimal program for one T1 row (asm.md 11 ASM-1: a
    minimal .org 0x1000 program; pc-relative rows use the context stated
    in the row's comment). Returns (program, index of the vector word)."""
    if vid == 29:    # b target, target = pc - 32
        return (".org 0x1000\ntarget:\n" + NOPS * 4 + f"    {src}\n", 4)
    if vid == 30:    # (p1) b target, target = pc + 48
        return (f".org 0x1000\n    {src}\n" + NOPS * 5 +
                "target:\n    halt\n", 0)
    if vid == 31:    # jal target, target = pc + 512
        return (f".org 0x1000\n    {src}\n" + NOPS * 63 +
                "target:\n    halt\n", 0)
    if vid == 36:    # lap r2, target, target = pc + 0x800
        return (f".org 0x1000\n    {src}\n    halt\n"
                "    .space 0x800 - 16\ntarget:\n    .byte 1\n", 0)
    return (f".org 0x1000\n    {src}\n", 0)


for vid, want, raw in T1:
    src = strip_src(raw)
    prog, idx = t1_program(vid, src)
    try:
        a = assemble(prog)
    except A.AsmError as e:
        check(False, f"T1.{vid:02d} {src!r}: {e}")
        continue
    got = words_of(a)[idx]
    check(got == want,
          f"T1.{vid:02d} {src!r}: 0x{got:016X} != 0x{want:016X}")

# ASM-14: case-insensitive mnemonics/registers/keywords
a_lo = words_of(assemble(".org 0x1000\nadd.32 r1, sp, 100\n"))[0]
a_up = words_of(assemble(".org 0x1000\nADD.32 R1, SP, 100\n"))[0]
check(a_lo == a_up, "ASM-14: ADD.32 R1, SP, 100 != add.32 r1, sp, 100")


# ---------------------------------------------------------- T2: li chains

T2_HDR = re.compile(r"^T2\.(\d+) \| (li .+)$", re.M)
T2_WORD = re.compile(r"^ {5}\| 0x([0-9A-F]{16}) \|", re.M)


def parse_t2():
    cases = []
    block = MD[MD.index("### T2"):MD.index("### T3")]
    for m in T2_HDR.finditer(block):
        start = m.end()
        nxt = T2_HDR.search(block, start)
        seg = block[start:nxt.start() if nxt else len(block)]
        wordlist = [int(h, 16) for h in T2_WORD.findall(seg)]
        cases.append((int(m.group(1)), m.group(2).strip(), wordlist))
    return cases


T2 = parse_t2()
check(len(T2) == 5, f"T2: parsed {len(T2)} cases, want 5")
T2_LENGTHS = {1: 1, 2: 1, 3: 2, 4: 3, 5: 6}   # asm.md minimality note

for cid, src, want in T2:
    check(len(want) == T2_LENGTHS[cid],
          f"T2.{cid}: md lists {len(want)} words, expected "
          f"{T2_LENGTHS[cid]}")
    got = words_of(assemble(f".org 0x1000\n    {src}\n"))
    check(got == want,
          f"T2.{cid} {src!r}: {[hex(w) for w in got]} != "
          f"{[hex(w) for w in want]}")

# ASM-17: predication distributes over the whole expansion
pred_lsb, _ = E.FIELDS["pred"]
t23 = dict((c, (s, w)) for c, s, w in T2)[3]
got = words_of(assemble(f".org 0x1000\n    (p1) {t23[0]}\n"))
want = [w | (0b0010 << pred_lsb) for w in t23[1]]
check(got == want, f"ASM-17: (p1) {t23[0]!r} chain pred wrong")


# ------------------------------------------- T3: la form selection + relax

# T3.1 (la at 0x1008 -> msg at 0x2000, 1 insn) is exercised inside T4.
# T3.2: la at 0x1000, far at 0x300000.
a = assemble(".org 0x1000\n    la r3, far\n    halt\n"
             ".org 0x300000\nfar:\n    halt\n")
got = words_of(a)[:2]
check(got == [0x7FFFFC0000003058, 0x3FC0060000063003],
      f"T3.2 la r3, far: {[hex(w) for w in got]}")

# ASM-7 relaxation iteration: la2's promotion pushes la1 out of range,
# so la1 must promote in a second sweep (asm.md 6.2 sticky fixed point).
RELAX_SRC = """\
    .org 0x1000
    la r1, sym1
    la r2, sym2
    .space 0x1FFFEF
sym1:
    .byte 1
    .space 0x10000
sym2:
    .byte 1
"""
a = assemble(RELAX_SRC)
ws = words_of(a)[:4]
lap_op = E.OPCODES["LAP"][0]
addi_op = E.OPCODES["ADD"][0] + 1
check([w & 0xFF for w in ws] == [lap_op, addi_op, lap_op, addi_op],
      f"relaxation: leading opcodes {[hex(w & 0xFF) for w in ws]} are "
      f"not LAP,ADD-I,LAP,ADD-I (both la must promote)")


def la_value(w0, w1, pc):
    def sx(v):
        return v - (1 << 22) if v >= 1 << 21 else v
    imm0 = (w0 >> E.FIELDS["imm"][0]) & ((1 << 22) - 1)
    imm1 = (w1 >> E.FIELDS["imm"][0]) & ((1 << 22) - 1)
    return pc + sx(imm0) + sx(imm1)


check(la_value(ws[0], ws[1], 0x1000) == a.labels["sym1"],
      "relaxation: la r1 does not build sym1")
check(la_value(ws[2], ws[3], 0x1010) == a.labels["sym2"],
      "relaxation: la r2 does not build sym2")

# ASM-8: la.abs always emits exactly 6 instructions, even for a near label
a = assemble(".org 0x1000\n    la.abs r1, x\nx:\n    halt\n")
ws = words_of(a)
check(len(ws) == 7, f"ASM-8: la.abs emitted {len(ws) - 1} words, want 6")
ldi_op = E.OPCODES["LDI"][0]
shori_op = E.OPCODES["SHORI"][0]
check((ws[0] & 0xFF) == ldi_op and
      all((w & 0xFF) == shori_op for w in ws[1:6]),
      "ASM-8: la.abs chain is not LDI + 5x SHORI")


# --------------------------------------- T4: complete program, .img + .sym

T4_SRC = MD[MD.index("### T4"):MD.index("### T5")]
m = re.search(r"```\n(        \.org 0x1000\n.*?)```", T4_SRC, re.S)
t4_source = m.group(1)
dump = re.search(r"```\n((?:[0-9a-f]{4}: [0-9a-f ]+\n)+)```", T4_SRC)
t4_img_md = bytes(int(b, 16) for line in dump.group(1).splitlines()
                  for b in line.split(":")[1].split())
check(len(t4_img_md) == 162, f"T4 md dump: {len(t4_img_md)} bytes")
symm = re.search(r"```\n((?:[0-9a-f]{32} [TDA] \S+\n)+)```", T4_SRC)
t4_sym_md = symm.group(1)


# ASM-9: byte-identical to the md dump (see header note / SPEC-ISSUES 33
# on the 8.2 trim rule: fixtures pin instruction bytes as untrimmable,
# and the dump's segment 2 shows the data-byte trim, file_len 2 of 3).
t4_img_want = t4_img_md
rc, err, img, sym = run_cli(t4_source, name="t4.s", out="t4.img")
check(rc == 0, f"T4: assembler failed: {err!r}")
check(img == t4_img_want,
      f"T4 .img mismatch: got {len(img or b'')} bytes, want "
      f"{len(t4_img_want)} (first diff at "
      f"{next((i for i, (x, y) in enumerate(zip(img or b'', t4_img_want)) if x != y), 'len')})")
check(sym == t4_sym_md, f"T4 .sym mismatch:\n{sym!r}\n!=\n{t4_sym_md!r}")

# ASM-13: determinism — a second run is byte-identical
rc2, _, img2, sym2 = run_cli(t4_source, name="t4.s", out="t4.img")
check(rc2 == 0 and img2 == img and sym2 == sym,
      "ASM-13: two runs on T4 differ")

# ASM-20: absent .entry defaults to 0x1000
_, _, img3, _ = run_cli(".org 0x1000\n    halt\n")
lo, hi = struct.unpack_from("<QQ", img3, 8)
check(lo == 0x1000 and hi == 0, "ASM-20: default entry != 0x1000")


# ----------------------------------- T5 + section 10 catalog error vectors

# Each entry: code -> (program, 1-based line of the diagnostic).
# Framing per asm.md 10: ".org 0x1000" prefix + trailing halt where
# needed so only the intended error can fire.
CATALOG = {
    "E001": (".org 0x1000\nadd r1, r2, r3 @\n", 2),
    "E002": (".org 0x1000\nldi r1, 0x1G\n", 2),
    "E003": ('.org 0x1000\n.ascii "abc\n', 2),
    "E004": ('.org 0x1000\n.ascii "\\q"\n', 2),
    "E005": (".org 0x1000\nldi r1, 'ab'\n", 2),
    "E010": (".org 0x1000\nfrob r1, r2\n", 2),
    "E011": (".org 0x1000\nadd r1, r2\nhalt\n", 2),
    "E012": (".org 0x1000\nadd 3, r2, r1\nhalt\n", 2),
    "E013": (".org 0x1000\ncmpeq r1, r2, r3\nhalt\n", 2),
    "E014": (".org 0x1000\namoadd.64 r1, [r2 + r3], r4\nhalt\n", 2),
    "E015": (".org 0x1000\nb.32 somewhere\nhalt\n", 2),
    "E016": (".org 0x1000\nlds r1, [r2]\nhalt\n", 2),
    "E017": (".org 0x1000\n(p9) add r1, r2, r3\nhalt\n", 2),
    "E018": (".org 0x1000\n: halt\nhalt\n", 2),
    "E019": (".org 0x1000\nadd r1, r2, 5 shl 3\nhalt\n", 2),
    "E020": (".org 0x1000\nadd r1, r2, 0x200000\nhalt\n", 2),
    "E021": (".org 0x1000\nshori r1, r1, -1\nhalt\n", 2),
    "E022": (".org 0x1000\nb target\n.equ target, 0x1004\nhalt\n", 2),
    "E023": (".org 0x1000\nb target\n.equ target, 0x1001000\nhalt\n", 2),
    "E024": (".org 0x1000\nadd r1, r2, r3 shl 64\nhalt\n", 2),
    "E025": (".org 0x1000\nfcvtff.f32 r1, r2, f32\nhalt\n", 2),
    "E026": (".org 0x1000\nmfsr r1, nosuch\nhalt\n", 2),
    "E027": (".org 0x1000\nfadd.f32 r1, r2, 3\nhalt\n", 2),
    "E028": (".org 0x1000\nla r1, sym\nhalt\n"
             ".org 0x801000\nsym: halt\n", 2),
    "E029": (".org 0x1000\nli r1, somelabel\nsomelabel: halt\n", 2),
    "E030": (".org 0x1000\nb nowhere\nhalt\n", 2),
    "E031": (".org 0x1000\nx: nop\nx: halt\n", 3),
    "E032": (".org 0x1000\nsp: halt\n", 2),
    "E033": (".org 0x1000\nlab1: nop\nlab2: halt\n"
             ".quad lab1 + lab2\n", 4),
    "E034": (".org sz\n.equ sz, 0x1000\nhalt\n", 1),
    # no trailing halt: after .byte it would misalign and E043 first
    "E035": (".org 0x1000\n.byte 256\n", 2),
    "E036": (".org 0x1000\nsub r1, 5, r2\nhalt\n", 2),
    "E040": ("nop\n", 1),
    "E041": ("start:\n", 1),
    "E042": (".org 0x1000\nnop\n.org 0x1000\nhalt\n", 3),      # T5.2
    "E043": (".org 0x1000\n.byte 1\nnop\n", 3),
    "E044": (".org 0x1000\n.align 3\nhalt\n", 2),
    "E045": (".org 0x1000\nhalt\n.org 0x2000\n", 3),
    "E046": (".org 0x1000\nhalt\n.entry nowhere\n", 3),
    "E047": (".org 0x1000\nhalt\n.byte 0,0,0,0\ne:\n.byte 1\n"
             ".entry e\n", 6),
    "E048": (".org 0x1000\nnop\ne:\n.entry e\n", 4),
    "E049": (".org 0x2000\nhalt\n", 1),                        # T5.3
}
# every catalog row of asm.md section 10 must be covered
md_codes = set(re.findall(r"^\| (E\d{3}) \|", MD, re.M))
check(md_codes == set(CATALOG),
      f"catalog coverage mismatch: md has {sorted(md_codes - set(CATALOG))}"
      f" uncovered; extra {sorted(set(CATALOG) - md_codes)}")

for code, (prog, line) in sorted(CATALOG.items()):
    rc, err, img, sym = run_cli(prog, name="t.s")
    check(rc == 1, f"{code}: exit {rc} != 1 ({err!r})")
    check(img is None and sym is None,
          f"{code}: output files exist after an error (ASM-12)")
    first = err.strip().splitlines()[0] if err.strip() else ""
    check("\n" not in err.strip(),
          f"{code}: diagnostic is not a single line: {err!r}")
    m = re.match(r"^(.*):(\d+): (E\d{3}): ", first)
    if not m:
        check(False, f"{code}: bad diagnostic format: {first!r}")
        continue
    check(m.group(3) == code,
          f"{code}: wrong code {m.group(3)} ({first!r})")
    check(int(m.group(2)) == line,
          f"{code}: reported line {m.group(2)}, want {line} "
          f"({first!r})")

# T5.1: overlap with the device table window [0x0800, 0x1000)
rc, err, _, _ = run_cli(".org 0x900\nnop\nhalt\n")
check(rc == 1 and ": E042: " in err,
      f"T5.1 device-window overlap: rc={rc} err={err!r}")

# ASM-12: a failing run REMOVES pre-existing outputs
rc, err, img, sym = run_cli(".org 0x1000\nb nowhere\nhalt\n",
                            pre_outputs=True)
check(rc == 1 and img is None and sym is None,
      "ASM-12: pre-existing .img/.sym survived a failing run")

# ASM-15: labels are case-sensitive
rc, err, _, _ = run_cli(".org 0x1000\nLoop: b loop\n")
check(rc == 1 and ": E030: " in err,
      f"ASM-15: Loop/loop must be distinct (E030): {err!r}")

# ASM-16: more reserved-name collisions (E032 vector covers `sp`)
for bad in ("STATUS", "Add.32", "la.abs", "ZERO", "f32", "shl"):
    rc, err, _, _ = run_cli(f".org 0x1000\nhalt\n.equ {bad}, 1\n")
    check(rc == 1 and ": E032: " in err,
          f"ASM-16: .equ {bad} accepted: rc={rc} {err!r}")

# usage / IO errors exit 2 without an E-code (asm.md 1)
r = subprocess.run([sys.executable, os.path.join(HERE, "asm.py")],
                   capture_output=True, text=True)
check(r.returncode == 2, f"no-input usage error: rc={r.returncode}")
r = subprocess.run([sys.executable, os.path.join(HERE, "asm.py"),
                    "--bogus", "x.s"], capture_output=True, text=True)
check(r.returncode == 2, f"unknown-flag usage error: rc={r.returncode}")
r = subprocess.run([sys.executable, os.path.join(HERE, "asm.py"),
                    "/nonexistent/in.s"], capture_output=True, text=True)
check(r.returncode == 2, f"missing-input error: rc={r.returncode}")


# ------------------------------------- ASM-18: conversion format matrix

CVT_LEGAL = 0
for mnem, sfxes, src_ok in (
        ("fcvtfi", ("32", "64", "128"), ("f32", "f64")),
        ("fcvtfiu", ("32", "64", "128"), ("f32", "f64")),
        ("fcvtif", ("f32", "f64"), ("i32", "i64", "i128")),
        ("fcvtuif", ("f32", "f64"), ("i32", "i64", "i128")),
        ("fcvtff", ("f32", "f64"), ("f32", "f64"))):
    for sfx in sfxes:
        for src in ("f32", "f64", "i32", "i64", "i128"):
            legal = src in src_ok and not (mnem == "fcvtff" and src == sfx)
            line = f"{mnem}.{sfx} r1, r2, {src}"
            try:
                assemble(f".org 0x1000\n    {line}\n")
                ok = True
            except A.AsmError as e:
                ok = False
                if legal:
                    check(False, f"ASM-18: {line!r} rejected: {e}")
                else:
                    check(e.code == "E025",
                          f"ASM-18: {line!r} rejected with {e.code}, "
                          f"want E025")
            if ok and not legal:
                check(False, f"ASM-18: {line!r} accepted, want E025")
            if ok and legal:
                CVT_LEGAL += 1
check(CVT_LEGAL == 6 + 6 + 6 + 6 + 2,
      f"ASM-18: {CVT_LEGAL} legal combinations assembled, want 26")


# ---------------------- ASM-19: encoding facts consumed from encoding.py

saved = E.OPCODES["ADD"]
try:
    E.OPCODES["ADD"] = (saved[0] ^ 0x40, saved[1], saved[2])
    w_patched = words_of(assemble(".org 0x1000\n    add r1, r2, r3\n"))[0]
finally:
    E.OPCODES["ADD"] = saved
w_normal = words_of(assemble(".org 0x1000\n    add r1, r2, r3\n"))[0]
check((w_patched & 0xFF) == (saved[0] ^ 0x40) and
      (w_normal & 0xFF) == saved[0],
      "ASM-19: assembler does not track encoding.py opcode values")


print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURES")
    sys.exit(1)
print(f"asm/test_asmmd.py: all checks passed "
      f"({len(T1)} T1 + {len(T2)} T2 vectors, {len(CATALOG)} error "
      f"vectors, T3/T4/T5 + ASM requirement checks)")
