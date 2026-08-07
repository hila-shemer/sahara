#!/usr/bin/env python3
"""trace-q validation against hand-built traces with known contents.

1. Golden bytes: records are packed here with raw struct.pack calls
   (independent of tracefile.py's writer helpers) and the writer helpers
   are checked against them byte-for-byte.
2. Every query is run through the real CLI on a small hand-built trace
   whose correct answers are known by construction.
3. Disassembler round-trip: assemble a program covering every mnemonic
   family, disassemble each word, re-assemble the disassembly, and
   require identical words.

Run: python3 trace-q/test_traceq.py   (exit 0 = pass)
"""

import os
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "asm"))

import encoding as E   # noqa: E402
import tracefile as T  # noqa: E402
import disasm as D     # noqa: E402
import asm as A        # noqa: E402

TRACE_Q = os.path.join(HERE, "trace-q")
FAILURES = []


def check(cond, msg):
    if not cond:
        FAILURES.append(msg)
        print("FAIL:", msg)


def run_q(*args):
    r = subprocess.run([sys.executable, TRACE_Q] + list(args),
                       capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def u128(v):
    return struct.pack("<QQ", v & (1 << 64) - 1, v >> 64)


def hdr(rtype, plen):
    return struct.pack("<BBHI", rtype, 0, 0, plen)


# --------------------------------- 1. golden record bytes vs writer helpers

golden_exec = (struct.pack("<Q", 5) + u128(0x1000)
               + struct.pack("<Q", 0xDEAD) + u128(0x77)
               + bytes([T.FLAG_WROTE_DST, 0]))
check(golden_exec == T.exec_payload(5, 0x1000, 0xDEAD, 0x77,
                                    T.FLAG_WROTE_DST, 0),
      "exec_payload disagrees with hand-packed bytes")
check(len(golden_exec) == 50, "EXEC payload must be 50 bytes")

golden_memw = struct.pack("<Q", 7) + u128(0x700) + bytes([8]) + u128(0x2A)
check(golden_memw == T.mem_payload(7, 0x700, 8, 0x2A),
      "mem_payload disagrees with hand-packed bytes")
check(len(golden_memw) == 41, "MEMW payload must be 41 bytes")

golden_trap = (struct.pack("<QQ", 9, E.CAUSES["SYSCALL"]) + u128(0x1010)
               + u128(0) + bytes([1]))
check(golden_trap == T.trap_payload(9, E.CAUSES["SYSCALL"], 0x1010, 0, 1),
      "trap_payload disagrees with hand-packed bytes")
check(len(golden_trap) == 49, "TRAP payload must be 49 bytes")

golden_event = struct.pack("<QQI", 3, 2, 4) + b"\x01\x02\x03\x04"
check(golden_event == T.event_payload(3, 2, b"\x01\x02\x03\x04"),
      "event_payload disagrees with hand-packed bytes")

# ------------------------------------------ 2. hand-built trace + queries


def enc(mnem_fields):
    """Build an instruction word from explicit fields (via E.FIELDS)."""
    w = 0
    for name, val in mnem_fields.items():
        lsb, width = E.FIELDS[name]
        assert 0 <= val < (1 << width)
        w |= val << lsb
    return w


OPC = {k: v[0] for k, v in E.OPCODES.items()}
W128 = E.FAMILIES["ALU"]["widths"].index(128)

# a tiny imagined program at 0x1000:
#   cycle 0: ldi r1, 5           (writes r1=5)
#   cycle 1: add r2, r1, r1      (writes r2=10)
#   cycle 2: st.64 r2, [r3]      -> MEMW at 0x700 size 8 val 10
#   cycle 3: cmpeq p1, r2, 10    (writes p1=1; pred file = 0b00000011)
#   cycle 4: (p1) b -4           (taken)
#   cycle 5: syscall             -> TRAP, then handler
i_ldi = enc({"opcode": OPC["LDI"], "dst": 1, "imm": 5})
i_add = enc({"opcode": OPC["ADD"], "dst": 2, "src1": 1, "src2": 1,
             "width": W128})
i_st = enc({"opcode": OPC["ST"], "src3": 2, "src1": 3,
            "src2": 31, "width": E.FAMILIES["MEM"]["widths"].index(64)})
i_cmp = enc({"opcode": OPC["CMPEQ"] + 1, "dst": 1, "src1": 2, "imm": 10,
             "width": E.FAMILIES["CMP"]["widths"].index(128)})
i_b = enc({"opcode": OPC["B"], "pred": 1 << 1,
           "imm": (-4) & ((1 << E.IMM_BITS) - 1)})
i_sys = enc({"opcode": OPC["SYSCALL"]})

FW, FP_ = T.FLAG_WROTE_DST, T.FLAG_WROTE_PRED


def build_trace(path, meta_text="image=test\nlevel=1\n"):
    with open(path, "wb") as f:
        T.write_record(f, T.T_META, T.meta_payload(meta_text))
        T.write_record(f, T.T_EXEC, T.exec_payload(0, 0x1000, i_ldi, 5, FW))
        T.write_record(f, T.T_EXEC, T.exec_payload(1, 0x1008, i_add, 10,
                                                   FW))
        T.write_record(f, T.T_EXEC, T.exec_payload(2, 0x1010, i_st))
        T.write_record(f, T.T_MEMW, T.mem_payload(2, 0x700, 8, 10))
        T.write_record(f, T.T_EXEC, T.exec_payload(3, 0x1018, i_cmp, 0,
                                                   FP_, 0b00000011))
        T.write_record(f, T.T_EXEC, T.exec_payload(4, 0x1020, i_b))
        T.write_record(f, T.T_EXEC, T.exec_payload(5, 0x1000, i_sys))
        T.write_record(f, T.T_TRAP,
                       T.trap_payload(5, E.CAUSES["SYSCALL"], 0x1000, 0, 1))
        T.write_record(f, T.T_EVENT, T.event_payload(6, 2, b"\x11\x22"))


td = tempfile.mkdtemp(prefix="traceq-test-")
trc = os.path.join(td, "a.trc")
build_trace(trc)
sym = os.path.join(td, "a.sym")
with open(sym, "w") as f:
    f.write(f"{0x1000:032x} T start\n")
    f.write(f"{0x700:032x} D failbox\n")

rc, out, err = run_q("exec", "1", trc, "--sym", sym)
check(rc == 0, f"exec: rc={rc} err={err}")
check("cycle=1" in out and "pc=0x1008" in out, f"exec fields: {out}")
check("sym=start+0x8" in out, f"exec symbolization: {out}")
check('asm="add r2, r1, r1"' in out, f"exec disasm: {out}")
check("wb=0xa" in out, f"exec wb: {out}")

rc, out, err = run_q("at", "0x1000", trc)
check(rc == 0 and out.split("\n") == ["0", "5"], f"at: {out!r}")

rc, out, err = run_q("last-write", "0x700", trc)
check(rc == 0 and "cycle=2" in out and "val=0xa" in out,
      f"last-write: {out}")
rc, out, err = run_q("last-write", "0x704", trc)
check(rc == 0 and "cycle=2" in out, f"last-write covering: {out}")
rc, out, err = run_q("last-write", "0x700", "--before", "2", trc)
check(rc == 0 and out == "none", f"last-write --before: {out}")
rc, out, err = run_q("last-write", "0x708", trc)
check(rc == 0 and out == "none", f"last-write miss: {out}")

rc, out, err = run_q("reg", "r2", "--at", "5", trc)
check(rc == 0 and out == "r2=0xa", f"reg r2: {out}")
rc, out, err = run_q("reg", "r2", "--at", "0", trc)
check(rc == 0 and out == "r2=0x0", f"reg r2 at 0: {out}")
rc, out, err = run_q("reg", "r1", "--at", "0", trc)
check(rc == 0 and out == "r1=0x5", f"reg r1 post-retire at 0: {out}")
rc, out, err = run_q("reg", "p1", "--at", "5", trc)
check(rc == 0 and out == "p1=1", f"reg p1: {out}")
rc, out, err = run_q("reg", "p1", "--at", "2", trc)
check(rc == 0 and out == "p1=0", f"reg p1 before write: {out}")
rc, out, err = run_q("reg", "p0", "--at", "0", trc)
check(rc == 0 and out == "p0=1", f"reg p0 hardwired: {out}")
rc, out, err = run_q("reg", "zero", "--at", "5", trc)
check(rc == 0 and out == "r31=0x0", f"reg zero: {out}")

rc, out, err = run_q("find", "--pc", "0x1010", trc)
check(rc == 0 and "cycle=2" in out, f"find --pc: {out}")
rc, out, err = run_q("find", "--wrote-reg", "r2=10", trc)
check(rc == 0 and "cycle=1" in out, f"find --wrote-reg: {out}")
rc, out, err = run_q("find", "--touched", "0x701", trc)
check(rc == 0 and "cycle=2" in out, f"find --touched: {out}")
rc, out, err = run_q("find", "--pc", "0x1000", "--from", "1", trc)
check(rc == 0 and "cycle=5" in out, f"find --from: {out}")
rc, out, err = run_q("find", "--pc", "0x1000", "--last", trc)
check(rc == 0 and "cycle=5" in out, f"find --last: {out}")
rc, out, err = run_q("find", "--pc", "0x1000", "--to", "4", "--last", trc)
check(rc == 0 and "cycle=0" in out, f"find --to --last: {out}")
rc, out, err = run_q("find", "--pc", "0x9999", trc)
check(rc == 0 and out == "none", f"find miss: {out}")

rc, out, err = run_q("range", "0", "1", trc)
check(rc == 0 and len(out.split("\n")) == 2, f"range: {out}")

rc, out, err = run_q("trapdump", trc, "--sym", sym)
check(rc == 0 and "cause=SYSCALL" in out and "tl_after=1" in out
      and "epc_sym=start" in out, f"trapdump: {out}")

# diverge: identical, meta-only difference, real difference, length diff
trc2 = os.path.join(td, "b.trc")
build_trace(trc2)
rc, out, err = run_q("diverge", trc, trc2)
check(rc == 0 and out.startswith("identical"), f"diverge identical: {out}")

build_trace(trc2, meta_text="image=other-path\nlevel=1\n")
rc, out, err = run_q("diverge", trc, trc2)
check(rc == 1 and "record=0" in out, f"diverge meta differs: {out}")
rc, out, err = run_q("diverge", trc, trc2, "--ignore-meta")
check(rc == 0 and out.startswith("identical"),
      f"diverge --ignore-meta: {out}")

with open(trc2, "wb") as f:
    T.write_record(f, T.T_META, T.meta_payload("image=test\nlevel=1\n"))
    T.write_record(f, T.T_EXEC, T.exec_payload(0, 0x1000, i_ldi, 5, FW))
    T.write_record(f, T.T_EXEC, T.exec_payload(1, 0x1008, i_add, 11, FW))
rc, out, err = run_q("diverge", trc, trc2)
check(rc == 1 and "record=2" in out and "a: " in out and "b: " in out,
      f"diverge real difference: {out}")

with open(trc2, "wb") as f:
    T.write_record(f, T.T_META, T.meta_payload("image=test\nlevel=1\n"))
    T.write_record(f, T.T_EXEC, T.exec_payload(0, 0x1000, i_ldi, 5, FW))
rc, out, err = run_q("diverge", trc, trc2)
check(rc == 1 and "end of trace" in out, f"diverge length: {out}")

# loud failures
bad = os.path.join(td, "bad.trc")
with open(bad, "wb") as f:
    f.write(b"\x01\x00\x00\x00\x05\x00\x00\x00abc")   # truncated payload
rc, out, err = run_q("exec", "0", bad)
check(rc != 0 and "truncated" in err, f"truncated trace not fatal: {err}")

with open(bad, "wb") as f:
    T.write_record(f, T.T_EXEC, T.exec_payload(0, 0x1000, i_ldi, 5, FW))
rc, out, err = run_q("exec", "0", bad)
check(rc != 0 and "META" in err, f"missing META not fatal: {err}")

with open(bad, "wb") as f:
    T.write_record(f, T.T_META, T.meta_payload("x"))
    T.write_record(f, 99, b"junk")
rc, out, err = run_q("exec", "0", bad)
check(rc != 0 and "unknown record type" in err,
      f"unknown type not fatal: {err}")

# ----------------------------- 3. disasm round-trip through the assembler

SRC = """\
start:
    add r1, r2, r3
    add.32 r1, r2, 5
    sub.64 r4, r5, -6
    add r1, r2, r3 shl 3
    or r1, r2, r3 sxt 8
    xor.64 r1, r2, r3 zxt 16
    madd r1, r2, r3, r4
    madd.32 r1, r2, 7, r4
    mulhu.64 r9, r10, r11
    sdiv.32 r1, r2, r3
    cmplt p3, r1, r2
    cmpeq.64 p5, r1, -1
    (p3) add r1, r2, r3
    (!p7) or r1, r2, r3
    lds.32 r1, [r2 + r3 shl 2 + 8]
    ldz.8 r1, [r2]
    lds.64 r1, [r2 - 16]
    ld128 r1, [r2 - 16]
    st.16 r5, [r6 + 4]
    st128 r5, [r6 + r7]
    cas.64 r1, [r2 + 8], r3, r4
    amoadd.32 r1, [r2], r3
    amomaxu r1, [r2 - 4], r3
    amoswap.64 r1, [r2], r3
    ldi r1, -100
    shori r1, r1, 0x3fffff
    prd r3
    pwr r4
    jalr r1, r2, 16
    mfsr r1, status
    mfsr r1, 99
    mtsr timecmp, r2
    syscall
    iret
    invtp
    ifence
    wfi
    halt
    fadd.f32 r1, r2, r3
    fdiv.f64 r4, r5, r6
    fmadd.f64 r1, r2, r3, r4
    fsqrt.f64 r1, r2
    fmin.f32 r1, r2, r3
    fcmplt.f32 p2, r1, r2
    fcmpeq.f64 p1, r3, r4
    fcvtfi.32 r1, r2, f64
    fcvtfi.128 r1, r2, f32
    fcvtfiu.64 r1, r2, f32
    fcvtif.f64 r1, r2, i32
    fcvtuif.f32 r1, r2, i128
    fcvtff.f64 r1, r2, f32
"""


def assemble_words(source):
    src = os.path.join(td, "rt.s")
    with open(src, "w") as f:
        f.write(source)
    a = A.assemble([src], os.path.join(td, "rt.img"),
                   os.path.join(td, "rt.sym"))
    data = bytes(a.segments[0].data)
    return list(struct.unpack(f"<{len(data)//8}Q", data))


words = assemble_words(SRC)
texts = [D.disasm(w) for w in words]
for t in texts:
    check("invalid" not in t, f"disasm produced invalid: {t!r}")
words2 = assemble_words("start:\n" + "".join(f"    {t}\n" for t in texts))
check(len(words) == len(words2), "round-trip changed instruction count")
for i, (w1, w2) in enumerate(zip(words, words2)):
    check(w1 == w2,
          f"round-trip mismatch at insn {i}: {texts[i]!r} "
          f"0x{w1:016x} -> 0x{w2:016x}")

# branches need pc-aware rendering; check displacement text without pc
b_words = assemble_words("start:\n    nop\n    b start\n    jal r5, "
                         "start\n    lap r1, start\n")
check(D.disasm(b_words[1]) == "b .-1", f"b disasm: {D.disasm(b_words[1])}")
check(D.disasm(b_words[2]) == "jal r5, .-2",
      f"jal disasm: {D.disasm(b_words[2])}")
check(D.disasm(b_words[3]) == "lap r1, .-24",
      f"lap disasm: {D.disasm(b_words[3])}")
check(D.disasm(b_words[1], pc=0x1008) == "b 0x1000",
      f"b pc disasm: {D.disasm(b_words[1], pc=0x1008)}")

# fuzz: disasm must never raise
import random
random.seed(1234)
for _ in range(20000):
    w = random.getrandbits(64)
    try:
        D.disasm(w)
    except Exception as e:  # noqa: BLE001
        check(False, f"disasm raised on 0x{w:016x}: {e}")
        break

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURES")
    sys.exit(1)
print("trace-q/test_traceq.py: all checks passed")
