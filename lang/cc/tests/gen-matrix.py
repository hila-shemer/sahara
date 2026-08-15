#!/usr/bin/env python3
# gen-matrix.py - the signedness x width x operation differential
# matrix (work-order decision 10). Emits case files into cases/:
#
#   matrix-oracle-*.c  - forms where C89 and cc semantics PROVABLY
#       coincide (same-type pairs; mixed signedness at width >= 32,
#       where C's usual arithmetic conversions equal cc's balancing;
#       casts to unsigned / in-range casts to signed; no signed
#       overflow, no negative / % >>, in-range shift counts). gcc runs
#       them as a true second implementation via the oracle leg.
#   matrix-corners-*.c - the cc deviation semantics (sub-32 promotion
#       to 64 bits, wrap at width, shift-mod-width, the ISA division
#       corners, narrowing casts). '// oracle: no'; expects computed
#       HERE from cc-m1.md's own semantics - a third implementation.
#       Generator, compiler, and both emulators must all agree.
#
# Cases are CHECKED IN. --update rewrites them; --check regenerates to
# a temp dir and diffs (the DoD no-op gate). Everything is enumerated
# deterministically - no randomness, no set iteration.

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CASES = os.path.join(HERE, "cases")

TYPES = {"i8": (8, True), "u8": (8, False),
         "i16": (16, True), "u16": (16, False),
         "i32": (32, True), "u32": (32, False),
         "i64": (64, True), "u64": (64, False)}

# ---- cc semantics (cc-m1.md 4/5; the third implementation) ---------


def wrap(v, bits):
    return v & ((1 << bits) - 1)


def as_type(v, bits, signed):
    """Conversion semantics: value mod 2^bits, reinterpreted."""
    v = wrap(v, bits)
    if signed and v >> (bits - 1):
        v -= 1 << bits
    return v


def promote(bits, signed):
    return (64, signed) if bits < 32 else (bits, signed)


def common(t1, t2):
    (b1, s1), (b2, s2) = t1, t2
    if b1 != b2:
        return t1 if b1 > b2 else t2
    return t1 if not s1 else t2


def cc_div(a, b, signed, bits):
    """ISA 5.1: /0 -> all-ones at width; MIN/-1 -> MIN; else trunc."""
    if b == 0:
        return -1 if signed else (1 << bits) - 1
    if signed and a == -(1 << (bits - 1)) and b == -1:
        return a
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q


def cc_rem(a, b, signed, bits):
    if b == 0:
        return a
    if signed and a == -(1 << (bits - 1)) and b == -1:
        return 0
    return a - cc_div(a, b, signed, bits) * b


def cc_bin(op, v1, t1, v2, t2):
    """Operands (value, (bits,signed)) AFTER promotion. Returns
    (value, (bits, signed)) of the result, cc semantics."""
    p1, p2 = promote(*t1), promote(*t2)
    if op in ("<<", ">>"):
        bits, signed = p1
        sh = wrap(v2, 64) & (bits - 1)          # count mod width
        if op == "<<":
            return as_type(v1 << sh, bits, signed), p1
        if signed:
            return as_type(v1, bits, True) >> sh, p1
        return wrap(v1, bits) >> sh, p1
    bits, signed = common(p1, p2)
    a = as_type(v1, bits, signed)
    b = as_type(v2, bits, signed)
    if op in ("<", "<=", "==", "!=", ">", ">="):
        r = {"<": a < b, "<=": a <= b, "==": a == b,
             "!=": a != b, ">": a > b, ">=": a >= b}[op]
        return (1 if r else 0), (64, True)
    if op == "/":
        v = cc_div(a, b, signed, bits)
    elif op == "%":
        v = cc_rem(a, b, signed, bits)
    else:
        v = {"+": a + b, "-": a - b, "*": a * b,
             "&": a & b, "|": a | b, "^": a ^ b}[op]
    return as_type(v, bits, signed), (bits, signed)


def to_u64(v, t):
    """(u64)expr - the checksum fold cast."""
    return wrap(as_type(v, *t), 64)


# ---- C89-coincidence filters (oracle family) ------------------------


def c_ok_bin(op, v1, t1, v2, t2):
    """True when the C89 result provably equals the cc result for
    this operand pair - the coincide-by-construction restriction."""
    (b1, s1), (b2, s2) = t1, t2
    if b1 != b2:
        return False                      # cross-width: promotion diverges
    if (s1 != s2) and b1 < 32:
        return False                      # C promotes both to int32
    bits, signed = common(promote(*t1), promote(*t2))
    if op in ("<<", ">>"):
        if b1 < 32 or b1 != b2 or s1 != s2:
            return False                  # C shifts sub-32 at width 32
        sh = v2
        if sh < 0 or sh >= b1:
            return False
        if op == "<<" and s1 and (v1 < 0 or (v1 << sh) > (1 << (b1-1))-1):
            return False
        if op == ">>" and s1 and v1 < 0:
            return False                  # impl-defined in C89
        return True
    a = as_type(v1, bits, signed)
    b = as_type(v2, bits, signed)
    if op in ("/", "%"):
        if b == 0:
            return False
        if (signed or b1 < 32) and (a < 0 or b < 0):
            return False                  # C89 rounding impl-defined
        return True
    if op in ("+", "-", "*"):
        if b1 < 32:
            # C computes these at int32 (promotion) - overflow is UB
            # there even for unsigned sub-32 operand types
            r = {"+": v1 + v2, "-": v1 - v2, "*": v1 * v2}[op]
            if not (-(1 << 31) <= r <= (1 << 31) - 1):
                return False
        elif signed:
            r = {"+": a + b, "-": a - b, "*": a * b}[op]
            lo, hi = -(1 << (bits - 1)), (1 << (bits - 1)) - 1
            if not (lo <= r <= hi):
                return False              # signed overflow: C UB
    return True


def c_ok_cast(to, v, frm):
    """C89-defined and coinciding: casts to unsigned always; casts to
    signed only when the value is in range."""
    tb, ts = TYPES[to]
    if not ts:
        return True
    val = as_type(v, *frm)
    return -(1 << (tb - 1)) <= val <= (1 << (tb - 1)) - 1


# ---- corner vectors --------------------------------------------------


def corners(bits, signed):
    if signed:
        return [0, 1, -1, -(1 << (bits - 1)), (1 << (bits - 1)) - 1]
    return [0, 1, (1 << bits) - 1, 1 << (bits - 1), 90 % (1 << bits)]


def literal(v, bits, signed):
    """A setup literal that is defined and identical in C89 and cc."""
    if signed:
        if bits >= 32 and v == -(1 << (bits - 1)):
            return f"(-{(1 << (bits - 1)) - 1} - 1)"
        return str(v)
    return hex(v)


# ---- emission --------------------------------------------------------

MUL = 1000003
SEED = 0x5EED
OPS = ["+", "-", "*", "/", "%", "<<", ">>",
       "<", "<=", "==", "!=", ">", ">=", "&", "|", "^"]
# corners files: one representative per comparison-lowering pair and
# no duplicate-polarity rows, to keep every file under the ~200k-cycle
# emu-py budget
CORNER_OPS = ["+", "-", "*", "/", "%", "<", "<=", "==", ">",
              "&", "|", "^"]


class Case:
    """One generated case file: setup decls + checksum statements,
    with the running checksum evaluated as it is emitted."""

    def __init__(self, name, oracle, comment):
        self.name = name
        self.oracle = oracle
        self.comment = comment
        self.decls = []
        self.stmts = []
        self.chk = SEED
        self.vars = {}                    # (tname, value) -> var name

    def var(self, tname, v):
        key = (tname, v)
        if key not in self.vars:
            n = f"v{len(self.vars)}_{tname}"
            bits, signed = TYPES[tname]
            self.decls.append(f"    {tname} {n} = "
                              f"{literal(v, bits, signed)};")
            self.vars[key] = n
        return self.vars[key]

    def fold(self, expr_text, value_u64):
        self.stmts.append(f"    chk = chk * {MUL} + (u64)({expr_text});")
        self.chk = wrap(self.chk * MUL + value_u64, 64)

    def bin(self, op, tn1, v1, tn2, v2):
        a = self.var(tn1, v1)
        b = self.var(tn2, v2)
        rv, rt = cc_bin(op, v1, TYPES[tn1], v2, TYPES[tn2])
        self.fold(f"{a} {op} {b}", to_u64(rv, rt))

    def neg(self, tn, v):
        a = self.var(tn, v)
        bits, signed = promote(*TYPES[tn])
        rv = as_type(-as_type(v, bits, signed), bits, signed)
        self.fold(f"-{a}", to_u64(rv, (bits, signed)))

    def bitnot(self, tn, v):
        a = self.var(tn, v)
        bits, signed = promote(*TYPES[tn])
        rv = as_type(~as_type(v, bits, signed), bits, signed)
        self.fold(f"~{a}", to_u64(rv, (bits, signed)))

    def cast(self, to, tn, v):
        a = self.var(tn, v)
        tb, ts = TYPES[to]
        rv = as_type(v, tb, ts)
        # the cast result participates promoted, like any rvalue
        pb, ps = promote(tb, ts)
        self.fold(f"({to}){a}", to_u64(rv, (pb, ps)))

    def render(self):
        signed_chk = self.chk - (1 << 64) if self.chk >> 63 else self.chk
        out = [f"// expect: {signed_chk}"]
        if not self.oracle:
            out.append("// oracle: no")
        out.append(f"// GENERATED by gen-matrix.py - do not edit "
                   f"(regenerate: gen-matrix.py --update)")
        out.append(f"// {self.comment}")
        out.append("i64 main() {")
        out.append("    u64 chk = 0x5EED;")
        out.extend(self.decls)
        out.extend(self.stmts)
        out.append("    return (i64)chk;")
        out.append("}")
        return "\n".join(out) + "\n"


def gen_oracle_pair_file(name, tnames, comment):
    c = Case(name, True, comment)
    for tn1 in tnames:
        b1, s1 = TYPES[tn1]
        for tn2 in tnames:
            b2, s2 = TYPES[tn2]
            for v1 in corners(b1, s1):
                for v2 in corners(b2, s2):
                    for op in OPS:
                        if c_ok_bin(op, v1, (b1, s1), v2, (b2, s2)):
                            c.bin(op, tn1, v1, tn2, v2)
    for tn in tnames:
        b, s = TYPES[tn]
        for v in corners(b, s):
            if not (s and b >= 32 and v == -(1 << (b - 1))):
                c.neg(tn, v)
            c.bitnot(tn, v)   # ~ commutes with sign-extension: always
    return c


def gen_oracle_casts(name, comment):
    c = Case(name, True, comment)
    order = ["i8", "u8", "i16", "u16", "i32", "u32", "i64", "u64"]
    for frm in order:
        fb, fs = TYPES[frm]
        for to in order:
            if to == frm:
                continue
            for v in corners(fb, fs):
                if c_ok_cast(to, v, (fb, fs)):
                    c.cast(to, frm, v)
    return c


def gen_corners_mixed(name, pairs, comment):
    c = Case(name, False, comment)
    for tn1, tn2 in pairs:
        b1, s1 = TYPES[tn1]
        b2, s2 = TYPES[tn2]
        for v1 in corners(b1, s1)[:4]:
            for v2 in corners(b2, s2)[:4]:
                for op in CORNER_OPS:
                    c.bin(op, tn1, v1, tn2, v2)
    return c


def gen_corners_shift_div(name, comment):
    c = Case(name, False, comment)
    counts = [0, 1, 7, 8, 15, 16, 31, 32, 33, 63, 64, 65, -1]
    for tn in ("i8", "u8", "i16", "u16", "i32", "u32", "i64", "u64"):
        b, s = TYPES[tn]
        for v in corners(b, s):
            for sh in counts:
                for op in ("<<", ">>"):
                    c.bin(op, tn, v, "i64", sh)
    # division corners at every width: /0, MIN/-1, negative operands
    for tn in ("i8", "i16", "i32", "i64"):
        b, s = TYPES[tn]
        mn = -(1 << (b - 1))
        for a, d in [(mn, -1), (7, 0), (mn, 0), (-7, 3), (7, -3),
                     (-7, -3), (mn, 3)]:
            c.bin("/", tn, a, tn, d)
            c.bin("%", tn, a, tn, d)
    for tn in ("u8", "u16", "u32", "u64"):
        b, s = TYPES[tn]
        mx = (1 << b) - 1
        hb = 1 << (b - 1)
        for a, d in [(7, 0), (mx, 0), (hb, 0), (mx, hb), (hb, mx),
                     (hb, 3)]:
            c.bin("/", tn, a, tn, d)
            c.bin("%", tn, a, tn, d)
    return c


def gen_corners_casts(name, comment):
    c = Case(name, False, comment)
    order = ["i8", "u8", "i16", "u16", "i32", "u32", "i64", "u64"]
    for frm in order:
        fb, fs = TYPES[frm]
        for to in order:
            if to == frm:
                continue
            for v in corners(fb, fs):
                if not c_ok_cast(to, v, (fb, fs)):
                    c.cast(to, frm, v)    # exactly the rows oracle skips
    return c


def build_all():
    return [
        gen_oracle_pair_file(
            "matrix-oracle-sub16",
            ["i8", "u8", "i16", "u16"],
            "same-type/same-signedness sub-32 pairs; C's int promotion "
            "and cc's 64-bit promotion coincide on these forms"),
        gen_oracle_pair_file(
            "matrix-oracle-32",
            ["i32", "u32"],
            "32-bit pairs incl. mixed signedness (C converts to u32; "
            "cc balances to u32 - same rule) and in-range shifts"),
        gen_oracle_pair_file(
            "matrix-oracle-64",
            ["i64", "u64"],
            "64-bit pairs incl. mixed signedness and in-range shifts"),
        gen_oracle_casts(
            "matrix-oracle-casts",
            "conversion rows where C89 defines the same result: casts "
            "to unsigned, in-range casts to signed"),
        gen_corners_mixed(
            "matrix-corners-promote",
            [("i8", "u8"), ("u8", "i8"), ("i16", "u16"), ("u16", "i16"),
             ("i8", "u16"), ("u16", "i8"),
             ("u16", "i32"), ("i16", "u32"),
             ("i32", "u64"), ("u32", "i64"),
             ("i32", "i32"), ("u32", "u32"), ("i32", "u32")],
            "the promotion/balancing deviation family: sub-32 mixing "
            "(cc promotes to 64, C to int32), cross-width balancing, "
            "u32/i32 wrap at width 32 - cc-m1.md 5.1/5.3 semantics, "
            "generator-computed expects"),
        gen_corners_shift_div(
            "matrix-corners-shift-div",
            "shift counts mod width (incl. counts >= width and -1) "
            "and the ISA division corners (/0, MIN/-1, negatives) at "
            "8/16/32/64 bits"),
        gen_corners_casts(
            "matrix-corners-casts",
            "narrowing casts to signed types out of range: two's-"
            "complement wrap semantics (C89 leaves these "
            "implementation-defined)"),
    ]


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
    cases = build_all()
    if mode == "--update":
        for c in cases:
            with open(os.path.join(CASES, c.name + ".c"), "w") as f:
                f.write(c.render())
            print(f"wrote {c.name}.c ({len(c.stmts)} folds)")
        return 0
    if mode == "--check":
        bad = 0
        for c in cases:
            path = os.path.join(CASES, c.name + ".c")
            want = c.render()
            got = open(path).read() if os.path.exists(path) else None
            if got != want:
                print(f"gen-matrix: STALE {c.name}.c "
                      f"(run gen-matrix.py --update and review)")
                bad = 1
        if not bad:
            print(f"gen-matrix: OK ({len(cases)} files match)")
        return bad
    print("usage: gen-matrix.py [--check|--update]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
