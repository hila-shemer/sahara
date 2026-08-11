#!/usr/bin/env python3
# abicheck.py - static SABI-v0 conformance check over cc.py output
# (cc-m1.md section 8; work-order decision 4). Every function carries a
# machine-readable marker:
#
#     # cc: func NAME frame=N calls=0|1
#
# and this checker holds each one to the single permitted shape:
# prologue/epilogue pairing, N % 16 == 0 and N <= 2^20, ra in the top
# slot iff calls=1, every st128/ld128 displacement a multiple of 16,
# no writes to r16-r27/r28(sp)/r29(ra)/r30(k0) outside the sanctioned
# spots, predicates limited to p1, exactly one ret and it closes the
# epilogue, every internal branch staying inside the function.
#
# Runs on the compiler's .s only - the hand-written runtime is reviewed
# prose, not marker-checked.

import re
import sys

MARKER = re.compile(r"^# cc: func (\S+) frame=(\d+) calls=([01])$")
LABEL = re.compile(r"^([A-Za-z_][A-Za-z0-9_.$]*):$")
MEM = re.compile(r"^\[\s*([a-z0-9]+)\s*(?:\+\s*(-?\d+)\s*)?\]$")

# dst-writing mnemonics we may see in cc output (base names)
DST_OPS = {"add", "sub", "mul", "udiv", "sdiv", "urem", "srem", "and",
           "or", "xor", "shl", "shr", "sar", "lds", "ldz", "ld128",
           "li", "la", "mov"}
CMP_OPS = {"cmpeq", "cmplt", "cmpltu", "cmple", "cmpleu"}
NO_DST = {"st", "st128", "b", "ret", "jal"}

CALLER_SAVED = {f"r{i}" for i in range(16)}


class Fail(Exception):
    pass


def parse_insn(line):
    """-> (pred, mnem_base, [operands]) for an instruction line."""
    s = line.strip()
    pred = None
    m = re.match(r"^\((!?p[0-7])\)\s+", s)
    if m:
        pred = m.group(1)
        s = s[m.end():]
    parts = s.split(None, 1)
    mnem = parts[0]
    base = mnem.split(".")[0]
    ops = [o.strip() for o in parts[1].split(",")] if len(parts) > 1 else []
    return pred, base, ops


def check_function(fname, name, frame, calls, body, start):
    def fail(i, msg):
        raise Fail(f"{fname}:{start + i + 1}: {name}: {msg}")

    if frame % 16:
        fail(-1, f"frame={frame} not a multiple of 16")
    if frame > 1 << 20:
        fail(-1, f"frame={frame} exceeds 2^20")
    if calls and frame < 16:
        fail(-1, "calls=1 needs an ra slot (frame >= 16)")

    if not body or body[0].strip() != f"{name}:":
        fail(0, "marker not followed by the function label")

    i = 1
    if frame:
        if body[i].strip() != f"add sp, sp, -{frame}":
            fail(i, f"prologue must be 'add sp, sp, -{frame}', got "
                    f"{body[i].strip()!r}")
        i += 1
    if calls:
        if body[i].strip() != f"st128 [sp + {frame - 16}], ra":
            fail(i, f"ra must be saved to the top slot [sp + {frame - 16}]")
        i += 1

    # locate the single epilogue
    ret_label = f"{name}.Lret:"
    lrets = [j for j, l in enumerate(body) if l.strip() == ret_label]
    if len(lrets) != 1:
        fail(0, f"expected exactly one {ret_label}")
    e = lrets[0] + 1
    if calls:
        if body[e].strip() != f"ld128 ra, [sp + {frame - 16}]":
            fail(e, "epilogue must restore ra from the top slot")
        e += 1
    if frame:
        if body[e].strip() != f"add sp, sp, {frame}":
            fail(e, f"epilogue must be 'add sp, sp, {frame}'")
        e += 1
    if body[e].strip() != "ret":
        fail(e, "epilogue must end in ret")
    if e != len(body) - 1:
        fail(e, "code after the epilogue ret")

    njal = 0
    for j, line in enumerate(body[1:], start=1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        lm = LABEL.match(s)
        if lm:
            if not lm.group(1).startswith(f"{name}.L"):
                fail(j, f"foreign label {lm.group(1)!r} inside function")
            continue
        pred, base, ops = parse_insn(s)
        in_epilogue = j > lrets[0]
        in_prologue = j < i

        if s == "ret":
            if j != len(body) - 1:
                fail(j, "naked ret off the epilogue path")
            continue
        if pred is not None and pred not in ("p1", "!p1"):
            fail(j, f"predicate {pred} used; the compiler owns p1 only")

        if base in CMP_OPS:
            if ops[0] != "p1":
                fail(j, f"compare writes {ops[0]}; only p1 is allowed")
        elif base == "jal":
            njal += 1
            if calls == 0:
                fail(j, "jal present but marker says calls=0")
        elif base in DST_OPS:
            dst = ops[0]
            if dst == "sp":
                ok = (in_prologue and s == f"add sp, sp, -{frame}") or \
                     (in_epilogue and s == f"add sp, sp, {frame}")
                if not ok:
                    fail(j, f"sp written outside prologue/epilogue: {s!r}")
            elif dst == "ra":
                if not (in_epilogue and calls):
                    fail(j, f"ra written outside the epilogue: {s!r}")
            elif dst not in CALLER_SAVED:
                fail(j, f"write to forbidden register {dst}: {s!r}")
        elif base in NO_DST:
            pass
        else:
            fail(j, f"unexpected mnemonic {base!r} in cc output")

        # every st128/ld128 displacement must be 16-aligned
        if base in ("st128", "ld128"):
            memop = ops[0] if base == "st128" else ops[1]
            mm = MEM.match(memop)
            if not mm:
                fail(j, f"unparseable {base} operand {memop!r}")
            disp = int(mm.group(2) or 0)
            if disp % 16:
                fail(j, f"{base} displacement {disp} not 16-aligned")

        if base == "b":
            tgt = ops[0]
            if not tgt.startswith(f"{name}.L"):
                fail(j, f"branch out of function: {s!r}")

    if calls and njal == 0:
        raise Fail(f"{fname}: {name}: marker says calls=1 but no jal")


def check_file(fname):
    lines = open(fname).read().splitlines()
    funcs = []
    cur = None
    for idx, line in enumerate(lines):
        m = MARKER.match(line)
        if m:
            if cur:
                funcs.append(cur)
            cur = (m.group(1), int(m.group(2)), int(m.group(3)), idx, [])
            continue
        if line.strip() == "__etext:" or (line.strip().startswith(".align")
                                          and cur and cur[4]
                                          and cur[4][-1].strip() == "ret"):
            if cur:
                funcs.append(cur)
                cur = None
            continue
        if cur is not None:
            cur[4].append(line)
    if cur:
        funcs.append(cur)
    if not funcs:
        raise Fail(f"{fname}: no '# cc: func' markers found")
    for name, frame, calls, idx, body in funcs:
        check_function(fname, name, frame, calls, body, idx + 1)
    return len(funcs)


def main():
    if len(sys.argv) < 2:
        print("usage: abicheck.py FILE.s [FILE.s ...]", file=sys.stderr)
        sys.exit(2)
    total = 0
    try:
        for f in sys.argv[1:]:
            total += check_file(f)
    except Fail as ex:
        print(f"abicheck: FAIL: {ex}", file=sys.stderr)
        sys.exit(1)
    print(f"abicheck: OK ({total} functions)")


if __name__ == "__main__":
    main()
