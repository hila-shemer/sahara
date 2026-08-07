#!/usr/bin/env python3
"""trace-q validation against hand-built traces with known contents.

1. Golden bytes: records are packed here with raw struct.pack calls
   (independent of tracefile.py's writer helpers) and the writer helpers
   are checked against them byte-for-byte.
2. Every query is run through the real CLI on a small hand-built trace
   whose correct answers are known by construction. Output grammar and
   exit codes per devspec/trace.md 6 (the byte-exact acceptance
   fixtures live in test_vectors.py; this file covers behaviors the
   vectors do not reach).
3. Reader validation: trace.md 2.4 class-2 malformations exit 2, torn
   tails are tolerated with a stderr diagnostic.
4. Disassembler round-trip: assemble a program covering every mnemonic
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
    return r.returncode, r.stdout.rstrip("\n"), r.stderr.strip()


def u128(v):
    return struct.pack("<QQ", v & (1 << 64) - 1, v >> 64)


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
#   cycle 2: st.64 [r3], r2      -> MEMW at 0x700 size 8 val 10
#   cycle 3: cmpeq p1, r2, 10    (writes p1=1; pred file = 0b00000011)
#   cycle 4: (p1) b -4           (taken)
#   cycle 5: syscall             -> TRAP at the delivery cycle
i_ldi = enc({"opcode": OPC["LDI"], "dst": 1, "imm": 5})
i_add = enc({"opcode": OPC["ADD"], "dst": 2, "src1": 1, "src2": 1,
             "width": W128})
i_st = enc({"opcode": OPC["ST"], "src3": 2, "src1": 3,
            "src2": 31, "width": E.FAMILIES["MEM"]["widths"].index(64)})
i_cmp = enc({"opcode": OPC["CMPEQ"] + 1, "dst": 1, "src1": 2, "imm": 10,
             "width": E.FAMILIES["CMP"]["widths"].index(128)})
i_b = enc({"opcode": OPC["B"], "pred": 1 << 1,
           "imm": (-4) & ((1 << E.IMM_BITS) - 1)})

FW, FP_ = T.FLAG_WROTE_DST, T.FLAG_WROTE_PRED


def build_trace(path, meta_text=None):
    if meta_text is None:
        meta_text = T.meta_text(1)
    with open(path, "wb") as f:
        T.write_record(f, T.T_META, T.meta_payload(meta_text))
        T.write_record(f, T.T_EXEC, T.exec_payload(0, 0x1000, i_ldi, 5, FW))
        T.write_record(f, T.T_EXEC, T.exec_payload(1, 0x1008, i_add, 10,
                                                   FW))
        T.write_record(f, T.T_MEMW, T.mem_payload(2, 0x700, 8, 10))
        T.write_record(f, T.T_EXEC, T.exec_payload(2, 0x1010, i_st))
        T.write_record(f, T.T_EXEC, T.exec_payload(3, 0x1018, i_cmp, 0,
                                                   FP_, 0b00000011))
        T.write_record(f, T.T_EXEC, T.exec_payload(4, 0x1020, i_b))
        T.write_record(f, T.T_TRAP,
                       T.trap_payload(5, E.CAUSES["SYSCALL"], 0x1028, 0, 1))
        T.write_record(f, T.T_EVENT, T.event_payload(6, 2, b"\x11\x22"))


td = tempfile.mkdtemp(prefix="traceq-test-")
trc = os.path.join(td, "a.trc")
build_trace(trc)
sym = os.path.join(td, "a.sym")
with open(sym, "w") as f:
    f.write(f"{0x1000:032x} T start\n")
    f.write(f"{0x1000:032x} T aaaa\n")   # same-address tie: smallest name
    f.write(f"{0x700:032x} D failbox\n")
    f.write(f"{0x123:032x} A const\n")   # A symbols never resolve

rc, out, err = run_q("exec", "1", trc, "--sym", sym)
check(rc == 0, f"exec: rc={rc} err={err}")
check(out.startswith("cycle=1 pc=0x00000000000000000000000000001008 "
                     "sym=aaaa+0x8 "),
      f"exec line head / tie-break: {out}")
check(" wb=0x0000000000000000000000000000000a " in out
      and " squashed=0 " in out and " pred=- " in out,
      f"exec fields: {out}")
check(out.endswith("asm=add r2, r1, r1"), f"exec disasm: {out}")

# pred-writing EXEC renders the file; store EXEC renders wb=-
rc, out, err = run_q("exec", "3", trc)
check(rc == 0 and " wb=- " in out and " pred=0x03 " in out,
      f"exec pred_wb: {out}")
rc, out, err = run_q("exec", "4", trc)
check(rc == 0 and out.endswith("asm=(p1) b -4"),
      f"exec predicated branch: {out}")

# no EXEC at the trap-delivery cycle
rc, out, err = run_q("exec", "5", trc)
check(rc == 1 and out == "", f"exec at TRAP cycle: rc={rc} {out!r}")

rc, out, err = run_q("at", "0x1000", trc)
check(rc == 0 and len(out.split("\n")) == 1 and "cycle=0" in out,
      f"at: {out!r}")
rc, out, err = run_q("at", "0x9999", trc)
check(rc == 1 and out == "", f"at miss: rc={rc} {out!r}")

rc, out, err = run_q("last-write", "0x700", trc, "--sym", sym)
check(rc == 0 and out.startswith("type=MEMW cycle=2 ")
      and " sym=failbox " in out
      and out.endswith("val=0x0000000000000000000000000000000a"),
      f"last-write: {out}")
rc, out, err = run_q("last-write", "0x704", trc)
check(rc == 0 and "cycle=2" in out, f"last-write covering: {out}")
rc, out, err = run_q("last-write", "0x700", "--before", "2", trc)
check(rc == 1 and out == "", f"last-write --before: rc={rc} {out!r}")
rc, out, err = run_q("last-write", "0x708", trc)
check(rc == 1 and out == "", f"last-write miss: rc={rc} {out!r}")

rc, out, err = run_q("reg", "r2", "--at", "5", trc)
check(rc == 0 and out == "reg=r2 cycle=5 "
      "val=0x0000000000000000000000000000000a", f"reg r2: {out}")
rc, out, err = run_q("reg", "r2", "--at", "0", trc)
check(rc == 0 and out.endswith("val=0x" + "0" * 32), f"reg r2 at 0: {out}")
rc, out, err = run_q("reg", "r1", "--at", "0", trc)
check(rc == 0 and out.endswith("0005"), f"reg r1 post-retire at 0: {out}")
rc, out, err = run_q("reg", "p1", "--at", "5", trc)
check(rc == 0 and out == "reg=p1 cycle=5 val=1", f"reg p1: {out}")
rc, out, err = run_q("reg", "p1", "--at", "2", trc)
check(rc == 0 and out == "reg=p1 cycle=2 val=0",
      f"reg p1 before write: {out}")
rc, out, err = run_q("reg", "p0", "--at", "0", trc)
check(rc == 0 and out == "reg=p0 cycle=0 val=1", f"reg p0 hardwired: {out}")
rc, out, err = run_q("reg", "ZERO", "--at", "5", trc)
check(rc == 0 and out == "reg=r31 cycle=5 val=0x" + "0" * 32,
      f"reg zero alias: {out}")
rc, out, err = run_q("reg", "r2", "--at", "99", trc)
check(rc == 1 and out == "",
      f"reg beyond last cycle must exit 1: rc={rc} {out!r}")

rc, out, err = run_q("find", "--pc", "0x1010", trc)
check(rc == 0 and "cycle=2" in out, f"find --pc: {out}")
rc, out, err = run_q("find", "--wrote-reg", "r2=10", trc)
check(rc == 0 and "cycle=1" in out, f"find --wrote-reg: {out}")
rc, out, err = run_q("find", "--touched", "0x701", trc)
check(rc == 0 and out.startswith("type=MEMW cycle=2"),
      f"find --touched: {out}")
rc, out, err = run_q("find", "--pc", "0x9999", trc)
check(rc == 1 and out == "", f"find miss: rc={rc} {out!r}")
rc, out, err = run_q("find", "--wrote-reg", "p1=1", trc)
check(rc == 2, f"find --wrote-reg on a predicate must be exit 2: {rc}")

rc, out, err = run_q("range", "0", "5", trc)
lines = out.split("\n")
check(rc == 0 and len(lines) == 6, f"range must include TRAP: {out}")
check(lines[5].startswith("cycle=5 cause=SYSCALL epc=0x")
      and " baddr=- " in lines[5] and lines[5].endswith("tl=1"),
      f"range TRAP line: {lines[5]}")

rc, out, err = run_q("trapdump", trc, "--sym", sym)
check(rc == 0 and "cause=SYSCALL" in out and "sym=aaaa+0x28" in out
      and " baddr=- " in out, f"trapdump: {out}")

# baddr prints for a baddr-carrying cause
trc3 = os.path.join(td, "c.trc")
with open(trc3, "wb") as f:
    T.write_record(f, T.T_META, T.meta_payload(T.meta_text(1)))
    T.write_record(f, T.T_TRAP,
                   T.trap_payload(0, E.CAUSES["UNALIGNED"], 0x1000,
                                  0x719, 1))
rc, out, err = run_q("trapdump", trc3)
check(rc == 0 and "cause=UNALIGNED" in out
      and "baddr=0x00000000000000000000000000000719" in out,
      f"trapdump baddr: {out}")

# diverge: identical exits 1; run-variant META keys excluded; non-variant
# key difference reported; eof; EVENT rendering (byte-exact record form
# is in test_vectors.py)
trc2 = os.path.join(td, "b.trc")
build_trace(trc2)
rc, out, err = run_q("diverge", trc, trc2)
check(rc == 1 and out == "", f"diverge identical: rc={rc} {out!r}")

build_trace(trc2, meta_text=T.meta_text(1, mode="replay",
                                        image="other-path"))
rc, out, err = run_q("diverge", trc, trc2)
check(rc == 1 and out == "",
      f"diverge run-variant keys must be excluded: rc={rc} {out!r}")

build_trace(trc2, meta_text=T.meta_text(2))
rc, out, err = run_q("diverge", trc, trc2)
check(rc == 0 and out.split("\n") == ["record=0 key=level", "a=1", "b=2"],
      f"diverge META level: {out!r}")

with open(trc2, "wb") as f:
    T.write_record(f, T.T_META, T.meta_payload(T.meta_text(1)))
    T.write_record(f, T.T_EXEC, T.exec_payload(0, 0x1000, i_ldi, 5, FW))
rc, out, err = run_q("diverge", trc, trc2)
check(rc == 0 and "record=2" in out and "b=eof" in out,
      f"diverge eof: {out!r}")

trc4 = os.path.join(td, "d.trc")
with open(trc4, "wb") as f:
    T.write_record(f, T.T_META, T.meta_payload(T.meta_text(1)))
    T.write_record(f, T.T_EVENT, T.event_payload(6, 2, b"\x11\x23"))
trc5 = os.path.join(td, "e.trc")
with open(trc5, "wb") as f:
    T.write_record(f, T.T_META, T.meta_payload(T.meta_text(1)))
    T.write_record(f, T.T_EVENT, T.event_payload(6, 2, b"\x11\x22"))
rc, out, err = run_q("diverge", trc4, trc5)
check(rc == 0
      and "a=type=EVENT cycle=6 device=2 payload_len=2 data=1123" in out,
      f"diverge EVENT line: {out!r}")

rc, out, err = run_q("diverge", trc, trc2, "--sym", sym)
check(rc == 2, f"diverge must reject --sym: rc={rc}")

# ------------------------- reader validation: malformations and torn tail

bad = os.path.join(td, "bad.trc")

with open(bad, "wb") as f:  # torn payload: tolerated, prefix used
    T.write_record(f, T.T_META, T.meta_payload(T.meta_text(1)))
    torn_at = f.tell()
    f.write(b"\x01\x00\x00\x00\x32\x00\x00\x00abc")
rc, out, err = run_q("exec", "0", bad)
check(rc == 1 and str(torn_at) in err and "11" in err,
      f"torn tail: rc={rc} err={err!r}")

with open(bad, "wb") as f:  # no META
    T.write_record(f, T.T_EXEC, T.exec_payload(0, 0x1000, i_ldi, 5, FW))
rc, out, err = run_q("exec", "0", bad)
check(rc == 2 and "META" in err, f"missing META: rc={rc} {err!r}")

with open(bad, "wb") as f:  # type outside 1-7
    T.write_record(f, T.T_META, T.meta_payload(T.meta_text(1)))
    T.write_record(f, 9, b"junk")
rc, out, err = run_q("exec", "0", bad)
check(rc == 2 and "outside 1-7" in err, f"bad type: rc={rc} {err!r}")

with open(bad, "wb") as f:  # wrong fixed payload length
    T.write_record(f, T.T_META, T.meta_payload(T.meta_text(1)))
    T.write_record(f, T.T_EXEC, b"\x00" * 49)
rc, out, err = run_q("exec", "0", bad)
check(rc == 2 and "expected 50" in err, f"short EXEC: rc={rc} {err!r}")

with open(bad, "wb") as f:  # EXEC flags bits 7:3
    T.write_record(f, T.T_META, T.meta_payload(T.meta_text(1)))
    T.write_record(f, T.T_EXEC, T.exec_payload(0, 0x1000, i_ldi, 5, 0x88))
rc, out, err = run_q("exec", "0", bad)
check(rc == 2 and "flags" in err, f"high flag bits: rc={rc} {err!r}")

with open(bad, "wb") as f:  # decreasing cycle
    T.write_record(f, T.T_META, T.meta_payload(T.meta_text(1)))
    T.write_record(f, T.T_EXEC, T.exec_payload(5, 0x1000, i_ldi, 5, FW))
    T.write_record(f, T.T_EXEC, T.exec_payload(4, 0x1008, i_add, 10, FW))
rc, out, err = run_q("exec", "5", bad)
check(rc == 2 and "decreases" in err, f"cycle decrease: rc={rc} {err!r}")

with open(bad, "wb") as f:  # duplicate META
    T.write_record(f, T.T_META, T.meta_payload(T.meta_text(1)))
    T.write_record(f, T.T_META, T.meta_payload(T.meta_text(1)))
rc, out, err = run_q("exec", "0", bad)
check(rc == 2 and "duplicate META" in err, f"dup META: rc={rc} {err!r}")

with open(bad, "wb") as f:  # missing mandatory key
    T.write_record(f, T.T_META, T.meta_payload("trace=1\nlevel=1\n"))
rc, out, err = run_q("exec", "0", bad)
check(rc == 2 and "mandatory key" in err, f"META keys: rc={rc} {err!r}")

with open(bad, "wb") as f:  # EVENT inner payload_len mismatch
    T.write_record(f, T.T_META, T.meta_payload(T.meta_text(1)))
    T.write_record(f, T.T_EVENT,
                   struct.pack("<QQI", 0, 0, 5) + b"\x00" * 2)
rc, out, err = run_q("exec", "0", bad)
check(rc == 2 and "payload_len" in err, f"EVENT inner: rc={rc} {err!r}")

badsym = os.path.join(td, "bad.sym")
with open(badsym, "w") as f:
    f.write("nonsense line\n")
rc, out, err = run_q("exec", "1", trc, "--sym", badsym)
check(rc == 2 and "sym" in err, f"bad .sym: rc={rc} {err!r}")

# unknown META keys are ignored (forward compatibility)
with open(bad, "wb") as f:
    T.write_record(f, T.T_META,
                   T.meta_payload(T.meta_text(1) + "future_key=x\n"))
    T.write_record(f, T.T_EXEC, T.exec_payload(0, 0x1000, i_ldi, 5, FW))
rc, out, err = run_q("exec", "0", bad)
check(rc == 0, f"unknown META key must be ignored: rc={rc} {err!r}")

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
    st.16 [r6 + 4], r5
    st128 [r6 + r7], r5
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
    mfsr r1, fcsr
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
    check(t != "invalid", "disasm produced invalid for a valid word")
words2 = assemble_words("start:\n" + "".join(f"    {t}\n" for t in texts))
check(len(words) == len(words2), "round-trip changed instruction count")
for i, (w1, w2) in enumerate(zip(words, words2)):
    check(w1 == w2,
          f"round-trip mismatch at insn {i}: {texts[i]!r} "
          f"0x{w1:016x} -> 0x{w2:016x}")

# canonical branch/const rendering: signed decimal instruction counts
# for B/JAL (trace.md 6.4 rule 3); LAP immediate in hex
b_words = assemble_words("start:\n    nop\n    b start\n    jal r5, "
                         "start\n    lap r1, start\n")
check(D.disasm(b_words[1]) == "b -1", f"b disasm: {D.disasm(b_words[1])}")
check(D.disasm(b_words[2]) == "jal r5, -2",
      f"jal disasm: {D.disasm(b_words[2])}")
check(D.disasm(b_words[3]) == "lap r1, -0x18",
      f"lap disasm: {D.disasm(b_words[3])}")

# invalid renderings are exactly "invalid" (trace.md 6.4 rule 7)
i_mfsr_bad = enc({"opcode": OPC["MFSR"], "dst": 1, "imm": 99})
check(D.disasm(i_mfsr_bad) == "invalid",
      f"out-of-range sreg: {D.disasm(i_mfsr_bad)}")
i_invtp_bad = enc({"opcode": OPC["INVTP"], "imm": 1})
check(D.disasm(i_invtp_bad) == "invalid",
      f"INVTP imm!=0: {D.disasm(i_invtp_bad)}")
i_modkind0 = enc({"opcode": OPC["ADD"], "dst": 1, "src1": 2, "src2": 3,
                  "width": W128, "mod": 0b100})  # kind 0, amount 1
check(D.disasm(i_modkind0) == "invalid",
      f"mod kind 0 amount != 0: {D.disasm(i_modkind0)}")

# fuzz: disasm must never raise
import random  # noqa: E402
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
