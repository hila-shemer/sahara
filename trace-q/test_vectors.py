#!/usr/bin/env python3
"""devspec/trace.md section 8 acceptance vectors, byte-exact.

TV-1  reference image: assembled by asm/ and compared to the spec's 112
      bytes (also pins the image format and the store operand order).
TV-2  complete level-1 trace: parsed by tracefile.py (all class-2
      validation passes), rebuilt record-by-record with the writer
      helpers, byte-identical; record offsets match the spec's map.
TV-7/TV-8  the 12 trace-q command fixtures: exact stdout + exit codes.
TV-9  torn tail + reserved-byte malformation.
TV-10 diverge fixtures including run-variant META exclusion.

The embedded hex is transcribed mechanically from devspec/trace.md; the
TV-1 bytes hash to the image_sha256 the spec states, which pins the
transcription.

Run: python3 trace-q/test_vectors.py   (exit 0 = pass)
"""

import hashlib
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

import tracefile as T  # noqa: E402
import asm as A        # noqa: E402

TRACE_Q = os.path.join(HERE, "trace-q")
FAILURES = []

TV1_IMG = bytes.fromhex(
    "534148494d47303100100000000000000000000000000000010000000000000000"
    "1000000000000000000000000000005000000000000000200000000000000020"
    "000000000000000000000000000000541000000014000003200200001e000036"
    "00c40f00130000fe00000000000000")
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

TV1_SOURCE = """\
    .org 0x1000
    .entry _start
_start:
    ldi r1, 0x5
    add r2, r1, 0x7
    st.64 [r2 + 0x4], r1
    halt
"""

TV7_SYM = (f"{0x10:032x} D result\n"
           f"{0x1000:032x} T _start\n"
           f"{0x1010:032x} T store_it\n")


def check(cond, msg):
    if not cond:
        FAILURES.append(msg)
        print("FAIL:", msg)


def run_q(*args):
    r = subprocess.run([sys.executable, TRACE_Q] + list(args),
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


td = tempfile.mkdtemp(prefix="traceq-tv-")

# ------------------------------------------------------------------ TV-1

check(hashlib.sha256(TV1_IMG).hexdigest() == TV1_SHA,
      "embedded TV-1 bytes do not hash to the spec's image_sha256")
src = os.path.join(td, "tv1.s")
with open(src, "w") as f:
    f.write(TV1_SOURCE)
img_path = os.path.join(td, "tv1.img")
A.assemble([src], img_path, os.path.join(td, "tv1.sym"))
with open(img_path, "rb") as f:
    built = f.read()
check(built == TV1_IMG,
      f"assembled TV-1 image differs from the spec bytes "
      f"({len(built)} vs {len(TV1_IMG)} bytes; first diff at "
      f"{next((i for i, (a, b) in enumerate(zip(built, TV1_IMG)) if a != b), 'len')})")

# ------------------------------------------------------------------ TV-2

check(len(TV2_TRC) == 449, f"TV-2 must be 449 bytes, got {len(TV2_TRC)}")
trc = os.path.join(td, "t.trc")
with open(trc, "wb") as f:
    f.write(TV2_TRC)
recs = T.read_records(trc)
check([r.type for r in recs] ==
      [T.T_META, T.T_EXEC, T.T_EXEC, T.T_MEMW, T.T_EXEC, T.T_EXEC],
      "TV-2 record types wrong")
check([r.offset for r in recs] == [0, 168, 226, 284, 333, 391],
      f"TV-2 record offsets wrong: {[r.offset for r in recs]}")

rebuilt = bytearray()
m = recs[0].fields["meta"]
meta_text = "".join(f"{k}={m[k]}\n" for k in T.META_KEYS)


class _W:
    def __init__(self):
        self.buf = bytearray()

    def write(self, b):
        self.buf += b


w = _W()
T.write_record(w, T.T_META, T.meta_payload(meta_text))
for r in recs[1:]:
    f = r.fields
    if r.type == T.T_EXEC:
        p = T.exec_payload(f["cycle"], f["pc"], f["insn"], f["wb"],
                           f["flags"], f["pred_wb"])
    else:
        p = T.mem_payload(f["cycle"], f["ea"], f["size"], f["val"])
    T.write_record(w, r.type, p)
check(bytes(w.buf) == TV2_TRC,
      "writer helpers do not reproduce TV-2 byte-for-byte")

# ------------------------------------------------------- TV-7/TV-8 fixtures

sym = os.path.join(td, "t.sym")
with open(sym, "w") as f:
    f.write(TV7_SYM)

E1 = ("cycle=2 pc=0x00000000000000000000000000001010 sym=store_it "
      "insn=0x000013000fc40036 squashed=0 wb=- pred=- "
      "asm=st.64 [r2 + 0x4], r1\n")
E2 = E1.replace("sym=store_it", "sym=-")
E4 = ("cycle=1 pc=0x00000000000000000000000000001008 sym=- "
      "insn=0x00001e0000022003 squashed=0 "
      "wb=0x0000000000000000000000000000000c pred=- "
      "asm=add r2, r1, 0x7\n")
E5 = ("type=MEMW cycle=2 ea=0x00000000000000000000000000000010 "
      "sym=result size=8 val=0x00000000000000000000000000000005\n")
E7 = "reg=r2 cycle=3 val=0x0000000000000000000000000000000c\n"
E8 = "reg=r9 cycle=3 val=0x00000000000000000000000000000000\n"
E11 = ("cycle=0 pc=0x00000000000000000000000000001000 sym=- "
       "insn=0x0000140000001054 squashed=0 "
       "wb=0x00000000000000000000000000000005 pred=- asm=ldi r1, 0x5\n"
       + E4 + E2 +
       "cycle=3 pc=0x00000000000000000000000000001018 sym=- "
       "insn=0x00000000000000fe squashed=0 wb=- pred=- asm=halt\n")

FIXTURES = [
    (["--sym", sym, "exec", "2", trc], 0, E1),
    (["exec", "2", trc], 0, E2),
    (["exec", "5", trc], 1, ""),
    (["at", "0x1008", trc], 0, E4),
    (["--sym", sym, "last-write", "0x12", trc], 0, E5),
    (["last-write", "0x12", "--before", "2", trc], 1, ""),
    (["reg", "r2", "--at", "3", trc], 0, E7),
    (["reg", "r9", "--at", "3", trc], 0, E8),
    (["find", "--wrote-reg", "r2=0xc", trc], 0, E4),
    (["find", "--touched", "0x10", "--from", "0", "--to", "3", trc], 0,
     E5.replace("sym=result", "sym=-")),
    (["range", "0", "3", trc], 0, E11),
    (["trapdump", trc], 1, ""),
]

for i, (cmd, want_rc, want_out) in enumerate(FIXTURES, 1):
    rc, out, err = run_q(*cmd)
    check(rc == want_rc, f"TV-8 fixture {i}: rc={rc}, want {want_rc} "
                         f"({err.strip()})")
    check(out == want_out,
          f"TV-8 fixture {i} stdout:\n  got  {out!r}\n  want {want_out!r}")

# ------------------------------------------------------------------ TV-9

t430 = os.path.join(td, "t430.trc")
with open(t430, "wb") as f:
    f.write(TV2_TRC[:430])
rc, out, err = run_q("exec", "3", t430)
check(rc == 1 and out == "", f"TV-9 exec 3: rc={rc} out={out!r}")
check("391" in err and "39" in err,
      f"TV-9 diagnostic must name offset 391 and count 39: {err!r}")
rc, out, err = run_q("exec", "2", t430)
check(rc == 0 and out == E2, f"TV-9 exec 2: rc={rc} out={out!r}")

flipped = bytearray(TV2_TRC)
flipped[1] = 0x01  # reserved header byte of record 0
bad = os.path.join(td, "bad.trc")
with open(bad, "wb") as f:
    f.write(bytes(flipped))
for q in (["exec", "2", bad], ["trapdump", bad], ["at", "0x1008", bad]):
    rc, out, err = run_q(*q)
    check(rc == 2, f"TV-9 reserved-byte flip: {q[0]} rc={rc}, want 2")

# ------------------------------------------------------------------ TV-10

u = bytearray(TV2_TRC)
check(u[266] == 0x0c, f"TV-10 anchor byte at 266 is 0x{u[266]:02x}")
u[266] = 0x0d
u_trc = os.path.join(td, "u.trc")
with open(u_trc, "wb") as f:
    f.write(bytes(u))
rc, out, err = run_q("diverge", trc, u_trc)
want = ("record=2 offset_a=226 offset_b=226\n"
        "a=" + E4.replace("\n", "") + "\n"
        "b=" + E4.replace("0x0000000000000000000000000000000c",
                          "0x0000000000000000000000000000000d")
                 .replace("\n", "") + "\n")
check(rc == 0, f"TV-10 diverge rc={rc}")
check(out == want, f"TV-10 diverge:\n  got  {out!r}\n  want {want!r}")

rc, out, err = run_q("diverge", trc, trc)
check(rc == 1 and out == "", f"TV-10 identical: rc={rc} out={out!r}")

meta_v = meta_text.replace("image=example.img", "image=other.img")
v_trc = os.path.join(td, "v.trc")
with open(v_trc, "wb") as f:
    T.write_record(f, T.T_META, T.meta_payload(meta_v))
    f.write(TV2_TRC[168:])
rc, out, err = run_q("diverge", trc, v_trc)
check(rc == 1 and out == "",
      f"TV-10 run-variant image key must be excluded: rc={rc} out={out!r}")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURES")
    sys.exit(1)
print("trace-q/test_vectors.py: all checks passed")
