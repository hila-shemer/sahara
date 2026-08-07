#!/usr/bin/env python3
"""Sahara two-pass assembler — TOOLING-SPEC.md section 4.

Input: one or more .s files, concatenated in order.
Output: IMAGE.img (TOOLING-SPEC section 1) + IMAGE.sym (section 2).

Every encoding fact (field positions, opcode values, sreg names, width
tables) comes from encoding.py. Nothing here hardcodes any of it.

All errors are fatal and name file:line. Warnings do not exist.
"""

import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import encoding as E  # noqa: E402

MASK128 = (1 << 128) - 1
IMM_SIGNED_MIN = -(1 << (E.IMM_BITS - 1))
IMM_SIGNED_MAX = (1 << (E.IMM_BITS - 1)) - 1
IMM_UNSIGNED_MAX = (1 << E.IMM_BITS) - 1
DEFAULT_ORG = E.RESET_PC          # implicit first segment / default entry
DEVTAB_BASE, DEVTAB_SIZE = 0x0800, 2048  # PLATFORM-SPEC section 1/2

REG_ALIASES = {"sp": 28, "ra": 29, "k0": 30, "zero": 31}
ZERO_REG = REG_ALIASES["zero"]
RA_REG = REG_ALIASES["ra"]

MOD_KINDS = {"shl": 1, "sxt": 2, "zxt": 3}

LABEL_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_.$]*):")
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.$]*$")


class AsmError(Exception):
    def __init__(self, pos, msg):
        super().__init__(f"{pos[0]}:{pos[1]}: error: {msg}")
        self.pos = pos


class Unresolved(Exception):
    """Expression references a symbol not yet defined (pass-1 only)."""


# --------------------------------------------------------------- expressions

TOKEN_RE = re.compile(
    r"\s*(?:"
    r"(?P<hex>0[xX][0-9a-fA-F]+)|"
    r"(?P<bin>0[bB][01]+)|"
    r"(?P<dec>\d+)|"
    r"(?P<char>'(?:\\.|[^\\'])')|"
    r"(?P<sym>[A-Za-z_][A-Za-z0-9_.$]*)|"
    r"(?P<op>[-+*()])"
    r")"
)

ESCAPES = {"n": 10, "t": 9, "r": 13, "0": 0, "\\": 92, "'": 39, '"': 34}


def char_value(lit, pos):
    body = lit[1:-1]
    if body.startswith("\\"):
        e = body[1:]
        if e in ESCAPES:
            return ESCAPES[e]
        if e.startswith("x") and len(e) == 3:
            try:
                return int(e[1:], 16)
            except ValueError:
                pass
        raise AsmError(pos, f"unknown escape {body!r}")
    return ord(body)


def tokenize_expr(text, pos):
    toks, i = [], 0
    while i < len(text):
        m = TOKEN_RE.match(text, i)
        if not m or m.end() == m.start():
            rest = text[i:].strip()
            if not rest:
                break
            raise AsmError(pos, f"bad token in expression: {rest!r}")
        i = m.end()
        if m.group("hex"):
            toks.append(("num", int(m.group("hex"), 16)))
        elif m.group("bin"):
            toks.append(("num", int(m.group("bin"), 2)))
        elif m.group("dec"):
            toks.append(("num", int(m.group("dec"), 10)))
        elif m.group("char"):
            toks.append(("num", char_value(m.group("char"), pos)))
        elif m.group("sym"):
            toks.append(("sym", m.group("sym")))
        else:
            toks.append(("op", m.group("op")))
    return toks


class ExprEval:
    """+ - * ( ) over numbers, .equ names, and labels (TOOLING-SPEC 4.5).

    Hand-written recursive-descent evaluator over the tokens above only;
    Python's eval() is never used (no arbitrary code execution)."""

    def __init__(self, asm, pos):
        self.asm, self.pos = asm, pos

    def eval(self, text):
        self.toks = tokenize_expr(text, self.pos)
        self.i = 0
        if not self.toks:
            raise AsmError(self.pos, "empty expression")
        v = self.expr()
        if self.i != len(self.toks):
            raise AsmError(self.pos, f"trailing junk in expression: {text!r}")
        return v

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def next(self):
        t = self.peek()
        self.i += 1
        return t

    def expr(self):
        v = self.term()
        while self.peek() == ("op", "+") or self.peek() == ("op", "-"):
            _, op = self.next()
            w = self.term()
            v = v + w if op == "+" else v - w
        return v

    def term(self):
        v = self.factor()
        while self.peek() == ("op", "*"):
            self.next()
            v = v * self.factor()
        return v

    def factor(self):
        kind, val = self.next()
        if kind == "num":
            return val
        if kind == "op" and val == "-":
            return -self.factor()
        if kind == "op" and val == "+":
            return self.factor()
        if kind == "op" and val == "(":
            v = self.expr()
            if self.next() != ("op", ")"):
                raise AsmError(self.pos, "missing ')' in expression")
            return v
        if kind == "sym":
            return self.asm.symbol_value(val, self.pos)
        raise AsmError(self.pos, f"unexpected token in expression")


# ------------------------------------------------------------------- parsing


def strip_comment(line):
    out, i, n = [], 0, len(line)
    quote = None
    while i < n:
        c = line[i]
        if quote:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(line[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c == "#":
            break
        if c in "'\"":
            quote = c
        out.append(c)
        i += 1
    return "".join(out)


def split_operands(text, pos):
    """Split at top-level commas, respecting [ ] ( ) and quotes."""
    parts, depth, cur, i, n = [], 0, [], 0, len(text)
    quote = None
    while i < n:
        c = text[i]
        if quote:
            cur.append(c)
            if c == "\\" and i + 1 < n:
                cur.append(text[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "'\"":
            quote = c
        elif c in "[(":
            depth += 1
        elif c in "])":
            depth -= 1
            if depth < 0:
                raise AsmError(pos, "unbalanced brackets")
        elif c == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
            i += 1
            continue
        cur.append(c)
        i += 1
    if quote:
        raise AsmError(pos, "unterminated quote")
    if depth != 0:
        raise AsmError(pos, "unbalanced brackets")
    last = "".join(cur).strip()
    if last or parts:
        parts.append(last)
    return parts


def parse_reg(tok):
    t = tok.strip().lower()
    if t in REG_ALIASES:
        return REG_ALIASES[t]
    m = re.fullmatch(r"r(\d+)", t)
    if m and 0 <= int(m.group(1)) <= 31:
        return int(m.group(1))
    return None


def parse_predreg(tok):
    m = re.fullmatch(r"p(\d)", tok.strip().lower())
    if m and 0 <= int(m.group(1)) <= 7:
        return int(m.group(1))
    return None


PRED_PREFIX_RE = re.compile(r"^\(\s*(!?)\s*[pP](\d)\s*\)\s*(.*)$")


class Stmt:
    __slots__ = ("pos", "kind", "labels", "mnem", "suffix", "pred",
                 "operands", "raw", "size", "chain", "la_plan", "addr",
                 "seg")

    def __init__(self, pos):
        self.pos = pos
        self.labels = []
        self.kind = None      # "insn" | "directive"
        self.mnem = None      # lowercase mnemonic or directive (with '.')
        self.suffix = None    # width suffix text or None
        self.pred = 0         # encoded pred field
        self.operands = []
        self.raw = ""
        self.size = 0
        self.chain = None     # li/la.abs chain length decided in pass 1
        self.la_plan = None   # "lap" | "lap_add"
        self.addr = None      # assigned in pass 1
        self.seg = None


# ----------------------------------------------------------------- assembler


class Segment:
    def __init__(self, base, pos):
        self.base = base
        self.pos = pos
        self.data = bytearray()


class Assembler:
    def __init__(self):
        self.stmts = []
        self.labels = {}          # name -> address
        self.label_kinds = {}     # name -> 'T' | 'D'
        self.equs = {}            # name -> (expr text, pos)
        self.equ_values = {}      # memoized
        self.equ_evaluating = set()
        self.segments = []
        self.entry_expr = None    # (text, pos)
        self.pass_no = 0

    # ------------------------------------------------------------- symbols

    def symbol_value(self, name, pos):
        if name in self.labels:
            return self.labels[name]
        if name in self.equs:
            if name in self.equ_values:
                return self.equ_values[name]
            if name in self.equ_evaluating:
                raise AsmError(pos, f".equ cycle involving {name!r}")
            self.equ_evaluating.add(name)
            text, epos = self.equs[name]
            try:
                v = ExprEval(self, epos).eval(text)
            finally:
                self.equ_evaluating.discard(name)
            self.equ_values[name] = v
            return v
        if self.pass_no == 1:
            raise Unresolved(name)
        raise AsmError(pos, f"undefined symbol {name!r}")

    def try_eval(self, text, pos):
        try:
            return ExprEval(self, pos).eval(text)
        except Unresolved:
            return None

    def must_eval(self, text, pos, why):
        try:
            return ExprEval(self, pos).eval(text)
        except Unresolved as u:
            raise AsmError(pos, f"{why} must not use forward references "
                                f"(undefined here: {u.args[0]})")

    # ------------------------------------------------------------- parsing

    def parse_files(self, paths):
        for path in paths:
            try:
                with open(path) as f:
                    lines = f.readlines()
            except OSError as e:
                sys.exit(f"error: cannot read {path}: {e}")
            for lineno, line in enumerate(lines, 1):
                self.parse_line(path, lineno, line)

    def parse_line(self, path, lineno, line):
        pos = (path, lineno)
        text = strip_comment(line).strip()
        stmt = Stmt(pos)
        while True:
            m = LABEL_RE.match(text)
            if not m:
                break
            stmt.labels.append(m.group(1))
            text = text[m.end():].strip()
        if not text:
            if stmt.labels:
                self.stmts.append(stmt)
            return
        m = PRED_PREFIX_RE.match(text)
        if m:
            stmt.pred = (int(m.group(2)) << 1) | (1 if m.group(1) else 0)
            if int(m.group(2)) > 7:
                raise AsmError(pos, "predicate index out of range")
            text = m.group(3).strip()
            if not text:
                raise AsmError(pos, "predicate prefix without instruction")
        parts = text.split(None, 1)
        head = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""
        stmt.raw = text
        if head.startswith("."):
            stmt.kind = "directive"
            stmt.mnem = head
            if stmt.pred:
                raise AsmError(pos, "directives cannot be predicated")
            stmt.operands = split_operands(rest, pos)
        else:
            stmt.kind = "insn"
            if "." in head:
                base, suffix = head.split(".", 1)
                stmt.mnem, stmt.suffix = base, suffix
            else:
                stmt.mnem = head
            stmt.operands = split_operands(rest, pos)
        self.stmts.append(stmt)

    # ------------------------------------------------------------- layout

    def cur_seg(self, pos):
        if not self.segments:
            self.segments.append(Segment(DEFAULT_ORG, pos))
        return self.segments[-1]

    def cur_addr(self, pos):
        seg = self.cur_seg(pos)
        return seg.base + len(seg.data)

    # -------------------------------------------------------------- pass 1

    def pass1(self):
        self.pass_no = 1
        # .equ must be registered before use; scan them all up front so a
        # later .equ can be used by an earlier li (constant folding only —
        # label-forward-refs still raise Unresolved).
        for stmt in self.stmts:
            if stmt.kind == "directive" and stmt.mnem == ".equ":
                if len(stmt.operands) != 2:
                    raise AsmError(stmt.pos, ".equ takes NAME, expr")
                name = stmt.operands[0]
                if not NAME_RE.match(name):
                    raise AsmError(stmt.pos, f"bad .equ name {name!r}")
                if name in self.equs:
                    raise AsmError(stmt.pos, f"duplicate .equ {name!r}")
                self.equs[name] = (stmt.operands[1], stmt.pos)

        offset = 0  # emulated via segment data length; pass 1 tracks sizes
        pending_labels = []
        for stmt in self.stmts:
            pos = stmt.pos
            for lbl in stmt.labels:
                if lbl in self.labels or lbl in self.equs:
                    raise AsmError(pos, f"duplicate symbol {lbl!r}")
                self.labels[lbl] = self.cur_addr(pos)
                pending_labels.append(lbl)
            if stmt.kind is None:
                continue
            if stmt.kind == "directive":
                emitted = self.pass1_directive(stmt)
                if emitted and pending_labels:
                    for lbl in pending_labels:
                        self.label_kinds[lbl] = "D"
                    pending_labels = []
            else:
                stmt.size = self.insn_size(stmt)
                stmt.addr = self.cur_addr(pos)
                stmt.seg = len(self.segments) - 1
                if stmt.addr % E.INSN_BYTES != 0:
                    raise AsmError(pos, f"instruction at 0x{stmt.addr:x} is "
                                        f"not {E.INSN_BYTES}-byte aligned")
                self.cur_seg(pos).data.extend(b"\0" * stmt.size)
                for lbl in pending_labels:
                    self.label_kinds[lbl] = "T"
                pending_labels = []
        for lbl in pending_labels:
            self.label_kinds[lbl] = "D"
        # reset segment data for pass 2 (keep bases)
        for seg in self.segments:
            seg.pass1_len = len(seg.data)
            seg.data = bytearray()

    def pass1_directive(self, stmt):
        """Returns True if the directive emits data (decides label kind)."""
        d, pos, ops = stmt.mnem, stmt.pos, stmt.operands
        if d == ".org":
            if len(ops) != 1:
                raise AsmError(pos, ".org takes one operand")
            base = self.must_eval(ops[0], pos, ".org")
            if base < 0 or base > MASK128:
                raise AsmError(pos, ".org address out of 128-bit range")
            self.segments.append(Segment(base, pos))
            stmt.seg = len(self.segments) - 1
            return False
        if d == ".entry":
            if len(ops) != 1:
                raise AsmError(pos, ".entry takes one operand")
            if self.entry_expr is not None:
                raise AsmError(pos, "duplicate .entry")
            self.entry_expr = (ops[0], pos)
            return False
        if d == ".equ":
            return False  # handled in prescan
        if d == ".align":
            if len(ops) != 1:
                raise AsmError(pos, ".align takes one operand")
            n = self.must_eval(ops[0], pos, ".align")
            if n <= 0 or (n & (n - 1)) != 0:
                raise AsmError(pos, f".align {n}: not a power of two")
            stmt.size = (-self.cur_addr(pos)) % n
            self.cur_seg(pos).data.extend(b"\0" * stmt.size)
            return False  # alignment padding does not decide label kind
        if d == ".space":
            if len(ops) != 1:
                raise AsmError(pos, ".space takes one operand")
            n = self.must_eval(ops[0], pos, ".space")
            if n < 0:
                raise AsmError(pos, f".space {n}: negative")
            stmt.size = n
            self.cur_seg(pos).data.extend(b"\0" * n)
            return True
        if d in (".byte", ".half", ".word", ".quad", ".oct"):
            unit = {".byte": 1, ".half": 2, ".word": 4,
                    ".quad": 8, ".oct": 16}[d]
            if not ops:
                raise AsmError(pos, f"{d} needs at least one value")
            stmt.size = unit * len(ops)
            self.cur_seg(pos).data.extend(b"\0" * stmt.size)
            return True
        if d in (".ascii", ".asciiz"):
            data = self.string_bytes(stmt)
            stmt.size = len(data)
            self.cur_seg(pos).data.extend(b"\0" * stmt.size)
            return True
        raise AsmError(pos, f"unknown directive {d}")

    def string_bytes(self, stmt):
        pos = stmt.pos
        out = bytearray()
        if not stmt.operands:
            raise AsmError(pos, f"{stmt.mnem} needs a string")
        for op in stmt.operands:
            s = op.strip()
            if len(s) < 2 or s[0] != '"' or s[-1] != '"':
                raise AsmError(pos, f"{stmt.mnem}: expected quoted string")
            body, i = s[1:-1], 0
            while i < len(body):
                c = body[i]
                if c == "\\":
                    if i + 1 >= len(body):
                        raise AsmError(pos, "trailing backslash in string")
                    e = body[i + 1]
                    if e in ESCAPES:
                        out.append(ESCAPES[e])
                        i += 2
                        continue
                    if e == "x" and i + 3 < len(body) + 1:
                        try:
                            out.append(int(body[i + 2:i + 4], 16))
                            i += 4
                            continue
                        except ValueError:
                            pass
                    raise AsmError(pos, f"unknown escape \\{e} in string")
                out.append(ord(c))
                i += 1
            if stmt.mnem == ".asciiz":
                out.append(0)
        return bytes(out)

    # -------------------------------------------------- pseudo sizing (p1)

    def insn_size(self, stmt):
        m = stmt.mnem
        if m == "li" or (m == "la" and stmt.suffix == "abs"):
            if len(stmt.operands) != 2:
                raise AsmError(stmt.pos, f"{m} takes rd, value")
            v = self.try_eval(stmt.operands[1], stmt.pos)
            stmt.chain = 6 if v is None else minimal_chain_len(v)
            return stmt.chain * E.INSN_BYTES
        if m == "la":
            if len(stmt.operands) != 2:
                raise AsmError(stmt.pos, "la takes rd, label")
            target = self.try_eval(stmt.operands[1], stmt.pos)
            if target is None:
                stmt.la_plan = "lap_add"
                return 2 * E.INSN_BYTES
            delta = target - self.cur_addr(stmt.pos)
            if IMM_SIGNED_MIN <= delta <= IMM_SIGNED_MAX:
                stmt.la_plan = "lap"
                return E.INSN_BYTES
            stmt.la_plan = "lap_add"
            return 2 * E.INSN_BYTES
        return E.INSN_BYTES

    # -------------------------------------------------------------- pass 2

    def pass2(self):
        self.pass_no = 2
        seg_i = -1
        for stmt in self.stmts:
            pos = stmt.pos
            if stmt.kind == "directive":
                self.pass2_directive(stmt)
                continue
            if stmt.kind != "insn":
                continue
            seg = self.segments[stmt.seg]
            if len(seg.data) != stmt.addr - seg.base:
                raise AsmError(pos, "internal: pass1/pass2 layout mismatch")
            words = self.encode(stmt)
            if len(words) * E.INSN_BYTES != stmt.size:
                raise AsmError(pos, "internal: pass1/pass2 size mismatch")
            for w in words:
                seg.data.extend(struct.pack("<Q", w))
        for seg in self.segments:
            if len(seg.data) != seg.pass1_len:
                raise AsmError(seg.pos, "internal: segment length mismatch")

    def pass2_directive(self, stmt):
        d, pos, ops = stmt.mnem, stmt.pos, stmt.operands
        seg = self.segments[stmt.seg] if stmt.seg is not None else None
        if d == ".org":
            return
        if d in (".entry", ".equ"):
            return
        cur = self.cur_seg2()
        if d == ".align":
            cur.data.extend(b"\0" * stmt.size)
            return
        if d == ".space":
            cur.data.extend(b"\0" * stmt.size)
            return
        if d in (".byte", ".half", ".word", ".quad", ".oct"):
            unit = {".byte": 1, ".half": 2, ".word": 4,
                    ".quad": 8, ".oct": 16}[d]
            for op in ops:
                v = ExprEval(self, pos).eval(op)
                lo, hi = -(1 << (unit * 8 - 1)), (1 << (unit * 8)) - 1
                if not lo <= v <= hi:
                    raise AsmError(pos, f"{d} value {v} does not fit in "
                                        f"{unit} bytes")
                cur.data.extend((v & hi if v >= 0 else v + (1 << (unit * 8)))
                                .to_bytes(unit, "little"))
            return
        if d in (".ascii", ".asciiz"):
            cur.data.extend(self.string_bytes(stmt))
            return
        raise AsmError(pos, f"unknown directive {d}")

    def cur_seg2(self):
        # pass 2 walks segments in the same order; the current segment is
        # the last one whose data is still growing.
        for seg in self.segments:
            if len(seg.data) < seg.pass1_len:
                return seg
        return self.segments[-1]

    # ------------------------------------------------------------ encoding

    def field(self, word, name, value):
        lsb, width = E.FIELDS[name]
        if not 0 <= value < (1 << width):
            raise AssertionError(f"internal: field {name} value {value}")
        return word | (value << lsb)

    def build(self, opval, pred=0, **fields):
        w = self.field(0, "opcode", opval)
        w = self.field(w, "pred", pred)
        for name, val in fields.items():
            w = self.field(w, name, val)
        return w

    def imm_signed(self, v, pos, what="immediate"):
        if not IMM_SIGNED_MIN <= v <= IMM_SIGNED_MAX:
            raise AsmError(pos, f"{what} {v} does not fit in signed "
                                f"{E.IMM_BITS}-bit field")
        return v & IMM_UNSIGNED_MAX

    def imm_unsigned(self, v, pos, what="immediate"):
        if not 0 <= v <= IMM_UNSIGNED_MAX:
            raise AsmError(pos, f"{what} {v} does not fit in unsigned "
                                f"{E.IMM_BITS}-bit field")
        return v

    def need_reg(self, tok, pos, what):
        r = parse_reg(tok)
        if r is None:
            raise AsmError(pos, f"{what}: expected register, got {tok!r}")
        return r

    def need_pred(self, tok, pos, what):
        p = parse_predreg(tok)
        if p is None:
            raise AsmError(pos, f"{what}: expected predicate register, "
                                f"got {tok!r}")
        return p

    def width_code(self, stmt, fam):
        """Map a width suffix to the width-field value for a family."""
        pos, sfx = stmt.pos, stmt.suffix
        widths = E.FAMILIES[fam]["widths"]
        if fam in ("ALU", "CMP", "ATOMIC"):
            want = 128 if sfx is None else (
                int(sfx) if sfx in ("32", "64", "128") else None)
            if want is None or want not in widths:
                raise AsmError(pos, f"bad width suffix .{sfx} for "
                                    f"{stmt.mnem}")
            return widths.index(want)
        if fam == "MEM":
            if sfx not in ("8", "16", "32", "64"):
                raise AsmError(pos, f"{stmt.mnem} needs a width suffix "
                                    f".8/.16/.32/.64")
            return widths.index(int(sfx))
        if fam == "FP":
            m = {"f32": "FP32", "f64": "FP64"}
            if sfx not in m or m[sfx] not in widths:
                raise AsmError(pos, f"{stmt.mnem} needs .f32 or .f64")
            return widths.index(m[sfx])
        if sfx is not None:
            raise AsmError(pos, f"{stmt.mnem} takes no width suffix")
        return 0

    def parse_b_operand(self, tok, pos):
        """ALU/CMP operand b: register [mod amount] or expression.

        Returns ("reg", src2, mod) or ("imm", value).
        """
        parts = tok.split()
        r = parse_reg(parts[0]) if parts else None
        if r is not None:
            mod = 0
            if len(parts) == 3:
                kind = parts[1].lower()
                if kind not in MOD_KINDS:
                    raise AsmError(pos, f"unknown src2 modifier {parts[1]!r}")
                amount = self.must_eval(parts[2], pos, "modifier amount")
                if not 0 <= amount <= 63:
                    raise AsmError(pos, f"modifier amount {amount} out of "
                                        f"range 0-63")
                mod = (amount << 2) | MOD_KINDS[kind]
            elif len(parts) != 1:
                raise AsmError(pos, f"bad operand {tok!r}")
            return ("reg", r, mod)
        v = ExprEval(self, pos).eval(tok)
        return ("imm", v, None)

    def parse_mem(self, tok, pos, allow_index=True):
        """[base + index mod n + disp] -> (src1, src2, mod, disp)."""
        t = tok.strip()
        if not (t.startswith("[") and t.endswith("]")):
            raise AsmError(pos, f"expected memory operand [..], got {tok!r}")
        inner = t[1:-1].strip()
        # split at top-level + and - (keep sign with the term)
        terms, depth, cur, sign = [], 0, [], "+"
        for c in inner:
            if c in "([":
                depth += 1
            elif c in ")]":
                depth -= 1
            if depth == 0 and c in "+-" and "".join(cur).strip():
                terms.append((sign, "".join(cur).strip()))
                cur, sign = [], c
                continue
            cur.append(c)
        if "".join(cur).strip():
            terms.append((sign, "".join(cur).strip()))
        if not terms:
            raise AsmError(pos, "empty memory operand")
        base = parse_reg(terms[0][1])
        if base is None or terms[0][0] == "-":
            raise AsmError(pos, f"memory operand must start with a base "
                                f"register: {tok!r}")
        src2, mod, disp_terms = ZERO_REG, 0, []
        for sign, term in terms[1:]:
            parts = term.split()
            r = parse_reg(parts[0])
            if r is not None:
                if not allow_index:
                    raise AsmError(pos, "atomic address is [base + imm] "
                                        "only (no index register)")
                if sign == "-":
                    raise AsmError(pos, "index register cannot be negated")
                if src2 != ZERO_REG or mod != 0:
                    raise AsmError(pos, "more than one index register")
                if len(parts) == 3:
                    kind = parts[1].lower()
                    if kind not in MOD_KINDS:
                        raise AsmError(pos, f"unknown index modifier "
                                            f"{parts[1]!r}")
                    amount = self.must_eval(parts[2], pos, "modifier amount")
                    if not 0 <= amount <= 63:
                        raise AsmError(pos, f"modifier amount {amount} "
                                            f"out of range 0-63")
                    mod = (amount << 2) | MOD_KINDS[kind]
                elif len(parts) != 1:
                    raise AsmError(pos, f"bad index term {term!r}")
                src2 = r
                if src2 == ZERO_REG and mod == 0:
                    pass  # index zero: same encoding as no index
            else:
                disp_terms.append((sign, term))
        disp = 0
        for sign, term in disp_terms:
            v = ExprEval(self, pos).eval(term)
            disp += v if sign == "+" else -v
        return base, src2, mod, disp

    def nops(self, stmt, n):
        if len(stmt.operands) != n:
            raise AsmError(stmt.pos, f"{stmt.mnem} takes {n} operand(s), "
                                     f"got {len(stmt.operands)}")

    def encode(self, stmt):
        m = stmt.mnem
        pos = stmt.pos
        if m in PSEUDOS:
            return PSEUDOS[m](self, stmt)
        name = m.upper()
        if name not in E.OPCODES:
            raise AsmError(pos, f"unknown mnemonic {stmt.mnem!r}")
        opval, fam, opspec = E.OPCODES[name]
        pred = stmt.pred

        if fam in ("ALU", "CMP"):
            wc = self.width_code(stmt, fam)
            if opspec == "d1b3":         # MADD: rd, rs1, b, rs3
                self.nops(stmt, 4)
                dsttok, s1tok, btok, s3tok = stmt.operands
                src3 = self.need_reg(s3tok, pos, "src3")
            else:
                self.nops(stmt, 3)
                dsttok, s1tok, btok = stmt.operands
                src3 = 0
            if opspec.startswith("p"):
                dst = self.need_pred(dsttok, pos, "compare destination")
            else:
                dst = self.need_reg(dsttok, pos, "destination")
            src1 = self.need_reg(s1tok, pos, "src1")
            b = self.parse_b_operand(btok, pos)
            if b[0] == "reg":
                return [self.build(opval, pred, dst=dst, src1=src1,
                                   src2=b[1], mod=b[2], src3=src3, width=wc)]
            return [self.build(opval + 1, pred, dst=dst, src1=src1,
                               imm=self.imm_signed(b[1], pos), src3=src3,
                               width=wc)]

        if fam == "MEM" or fam == "MEM128":
            wc = self.width_code(stmt, "MEM") if fam == "MEM" else 0
            self.nops(stmt, 2)
            if opspec == "dm":           # loads: rd, [ea]
                dst = self.need_reg(stmt.operands[0], pos, "destination")
                base, src2, mod, disp = self.parse_mem(stmt.operands[1], pos)
                return [self.build(opval, pred, dst=dst, src1=base,
                                   src2=src2, mod=mod, width=wc,
                                   imm=self.imm_signed(disp, pos,
                                                       "displacement"))]
            else:                        # stores: [ea], rs3 (asm.md 5.5)
                src3 = self.need_reg(stmt.operands[1], pos, "store value")
                base, src2, mod, disp = self.parse_mem(stmt.operands[0], pos)
                return [self.build(opval, pred, src3=src3, src1=base,
                                   src2=src2, mod=mod, width=wc,
                                   imm=self.imm_signed(disp, pos,
                                                       "displacement"))]

        if fam == "ATOMIC":
            wc = self.width_code(stmt, fam)
            if opspec == "da23":         # CAS: rd, [ea], rexp, rnew
                self.nops(stmt, 4)
                dst = self.need_reg(stmt.operands[0], pos, "destination")
                base, _, _, disp = self.parse_mem(stmt.operands[1], pos,
                                                  allow_index=False)
                src2 = self.need_reg(stmt.operands[2], pos, "expected value")
                src3 = self.need_reg(stmt.operands[3], pos, "new value")
                return [self.build(opval, pred, dst=dst, src1=base,
                                   src2=src2, src3=src3, width=wc,
                                   imm=self.imm_signed(disp, pos,
                                                       "displacement"))]
            else:                        # AMO*: rd, [ea], rs2
                self.nops(stmt, 3)
                dst = self.need_reg(stmt.operands[0], pos, "destination")
                base, _, _, disp = self.parse_mem(stmt.operands[1], pos,
                                                  allow_index=False)
                src2 = self.need_reg(stmt.operands[2], pos, "operand")
                return [self.build(opval, pred, dst=dst, src1=base,
                                   src2=src2, width=wc,
                                   imm=self.imm_signed(disp, pos,
                                                       "displacement"))]

        if fam == "CTRL":
            if stmt.suffix is not None:
                raise AsmError(pos, f"{stmt.mnem} takes no width suffix")
            if name == "B":
                self.nops(stmt, 1)
                return [self.build(opval, pred,
                                   imm=self.branch_disp(stmt.operands[0],
                                                        stmt.addr, pos))]
            if name == "JAL":
                if len(stmt.operands) == 1:      # bare jal label
                    dst, target = RA_REG, stmt.operands[0]
                else:
                    self.nops(stmt, 2)
                    dst = self.need_reg(stmt.operands[0], pos, "link")
                    target = stmt.operands[1]
                return [self.build(opval, pred, dst=dst,
                                   imm=self.branch_disp(target, stmt.addr,
                                                        pos))]
            if name == "JALR":
                self.nops(stmt, 3)
                dst = self.need_reg(stmt.operands[0], pos, "link")
                src1 = self.need_reg(stmt.operands[1], pos, "target base")
                off = ExprEval(self, pos).eval(stmt.operands[2])
                return [self.build(opval, pred, dst=dst, src1=src1,
                                   imm=self.imm_signed(off, pos))]

        if fam == "CONST":
            if stmt.suffix is not None:
                raise AsmError(pos, f"{stmt.mnem} takes no width suffix")
            if name == "LDI":
                self.nops(stmt, 2)
                dst = self.need_reg(stmt.operands[0], pos, "destination")
                v = ExprEval(self, pos).eval(stmt.operands[1])
                return [self.build(opval, pred, dst=dst,
                                   imm=self.imm_signed(v, pos))]
            if name == "SHORI":
                self.nops(stmt, 3)
                dst = self.need_reg(stmt.operands[0], pos, "destination")
                src1 = self.need_reg(stmt.operands[1], pos, "source")
                v = ExprEval(self, pos).eval(stmt.operands[2])
                return [self.build(opval, pred, dst=dst, src1=src1,
                                   imm=self.imm_unsigned(v, pos))]
            if name == "LAP":
                # operand is a target address; imm = target - pc (bytes)
                self.nops(stmt, 2)
                dst = self.need_reg(stmt.operands[0], pos, "destination")
                target = ExprEval(self, pos).eval(stmt.operands[1])
                delta = target - stmt.addr
                return [self.build(opval, pred, dst=dst,
                                   imm=self.imm_signed(delta, pos,
                                                       "lap displacement"))]

        if fam == "PREDF":
            if stmt.suffix is not None:
                raise AsmError(pos, f"{stmt.mnem} takes no width suffix")
            self.nops(stmt, 1)
            if name == "PRD":
                dst = self.need_reg(stmt.operands[0], pos, "destination")
                return [self.build(opval, pred, dst=dst)]
            if name == "PWR":
                src1 = self.need_reg(stmt.operands[0], pos, "source")
                return [self.build(opval, pred, src1=src1)]

        if fam == "SYS":
            if stmt.suffix is not None:
                raise AsmError(pos, f"{stmt.mnem} takes no width suffix")
            if name == "MFSR":
                self.nops(stmt, 2)
                dst = self.need_reg(stmt.operands[0], pos, "destination")
                idx = self.sreg_index(stmt.operands[1], pos)
                return [self.build(opval, pred, dst=dst, imm=idx)]
            if name == "MTSR":
                self.nops(stmt, 2)
                idx = self.sreg_index(stmt.operands[0], pos)
                src1 = self.need_reg(stmt.operands[1], pos, "source")
                return [self.build(opval, pred, src1=src1, imm=idx)]
            self.nops(stmt, 0)
            return [self.build(opval, pred)]

        if fam in ("FP", "FCVT"):
            return self.encode_fp(stmt, opval, fam, opspec)

        raise AsmError(pos, f"internal: unhandled family {fam}")

    def branch_disp(self, target_expr, pc, pos):
        target = ExprEval(self, pos).eval(target_expr)
        delta = target - pc
        if delta % E.INSN_BYTES != 0:
            raise AsmError(pos, f"branch target 0x{target:x} not "
                                f"{E.INSN_BYTES}-byte aligned relative to "
                                f"branch")
        return self.imm_signed(delta // E.INSN_BYTES, pos,
                               "branch displacement (instructions)")

    def sreg_index(self, tok, pos):
        t = tok.strip().lower()
        if t in E.SREGS:
            return E.SREGS[t]
        v = ExprEval(self, pos).eval(tok)
        return self.imm_unsigned(v, pos, "sreg index")

    # FP format codes per ISA-SPEC 10.4: 0 = 32-bit, 1 = 64-bit,
    # 2 = 128-bit (integer only).
    FP_SRC_FMT = {"f32": 0, "f64": 1}
    INT_SRC_FMT = {"i32": 0, "i64": 1, "i128": 2}
    INT_DST_SFX = {"32": 0, "64": 1, "128": 2}
    FP_DST_SFX = {"f32": 0, "f64": 1}

    def encode_fp(self, stmt, opval, fam, opspec):
        pos, pred, name = stmt.pos, stmt.pred, stmt.mnem.upper()
        if fam == "FP":
            wc = self.width_code(stmt, "FP")
            regs_needed = {"d12": 3, "d1": 2, "d123": 4, "p12": 3}[opspec]
            self.nops(stmt, regs_needed)
            ops = stmt.operands
            if opspec.startswith("p"):
                dst = self.need_pred(ops[0], pos, "compare destination")
            else:
                dst = self.need_reg(ops[0], pos, "destination")
            src1 = self.need_reg(ops[1], pos, "src1")
            src2 = self.need_reg(ops[2], pos, "src2") if regs_needed >= 3 \
                else 0
            src3 = self.need_reg(ops[3], pos, "src3") if regs_needed == 4 \
                else 0
            return [self.build(opval, pred, dst=dst, src1=src1, src2=src2,
                               src3=src3, width=wc)]
        # FCVT: width = dest format code, mod bits 1:0 = source format code
        # Syntax: fcvtfi.32 rd, rs1, f64   (dest suffix, source trailing)
        self.nops(stmt, 3)
        dst = self.need_reg(stmt.operands[0], pos, "destination")
        src1 = self.need_reg(stmt.operands[1], pos, "source")
        srcfmt_tok = stmt.operands[2].strip().lower()
        sfx = stmt.suffix
        if name in ("FCVTFI", "FCVTFIU"):     # FP -> int
            if sfx not in self.INT_DST_SFX:
                raise AsmError(pos, f"{stmt.mnem} needs .32/.64/.128 "
                                    f"(integer destination width)")
            if srcfmt_tok not in self.FP_SRC_FMT:
                raise AsmError(pos, f"{stmt.mnem} source format must be "
                                    f"f32 or f64")
            wc = self.INT_DST_SFX[sfx]
            sf = self.FP_SRC_FMT[srcfmt_tok]
        elif name in ("FCVTIF", "FCVTUIF"):   # int -> FP
            if sfx not in self.FP_DST_SFX:
                raise AsmError(pos, f"{stmt.mnem} needs .f32/.f64 "
                                    f"(FP destination format)")
            if srcfmt_tok not in self.INT_SRC_FMT:
                raise AsmError(pos, f"{stmt.mnem} source format must be "
                                    f"i32, i64, or i128")
            wc = self.FP_DST_SFX[sfx]
            sf = self.INT_SRC_FMT[srcfmt_tok]
        elif name == "FCVTFF":                # FP -> FP, 32 <-> 64
            if sfx not in self.FP_DST_SFX:
                raise AsmError(pos, f"fcvtff needs .f32/.f64")
            if srcfmt_tok not in self.FP_SRC_FMT:
                raise AsmError(pos, f"fcvtff source format must be f32 "
                                    f"or f64")
            wc = self.FP_DST_SFX[sfx]
            sf = self.FP_SRC_FMT[srcfmt_tok]
            if wc == sf:
                raise AsmError(pos, "fcvtff source and destination formats "
                                    "must differ (32 <-> 64)")
        else:
            raise AsmError(pos, f"internal: unhandled FCVT {name}")
        return [self.build(opval, pred, dst=dst, src1=src1, width=wc,
                           mod=sf)]

    # ------------------------------------------------------------- output

    def check_layout(self):
        occupied = []
        if any(seg.data for seg in self.segments):
            occupied.append((DEVTAB_BASE, DEVTAB_BASE + DEVTAB_SIZE,
                             "(device table)"))
        for seg in self.segments:
            if not seg.data:
                continue
            occupied.append((seg.base, seg.base + len(seg.data),
                             f"segment at {seg.pos[0]}:{seg.pos[1]}"))
        occupied.sort()
        for (a0, a1, na), (b0, b1, nb) in zip(occupied, occupied[1:]):
            if b0 < a1:
                raise AsmError((na.split(" at ")[-1].split(":")[0], 0)
                               if " at " in na else ("<image>", 0),
                               f"overlap: {na} [0x{a0:x},0x{a1:x}) and "
                               f"{nb} [0x{b0:x},0x{b1:x})")

    def entry_value(self):
        if self.entry_expr is None:
            return DEFAULT_ORG
        text, pos = self.entry_expr
        v = ExprEval(self, pos).eval(text)
        if v % E.INSN_BYTES != 0:
            raise AsmError(pos, f"entry 0x{v:x} is not "
                                f"{E.INSN_BYTES}-byte aligned")
        if not 0 <= v <= MASK128:
            raise AsmError(pos, "entry out of 128-bit range")
        return v

    def write_image(self, out_img):
        entry = self.entry_value()
        segs = [s for s in self.segments if s.data]
        if not segs:
            sys.exit("error: nothing assembled (empty image)")
        self.check_layout()
        header = b"SAHIMG01" + pack_u128(entry) + struct.pack("<Q", len(segs))
        desc_bytes = 48 * len(segs)
        file_off = len(header) + desc_bytes
        descs, blobs = [], []
        for seg in segs:
            descs.append(pack_u128(seg.base) +
                         struct.pack("<QQQQ", file_off, len(seg.data),
                                     len(seg.data), 0))
            blobs.append(bytes(seg.data))
            file_off += len(seg.data)
        with open(out_img, "wb") as f:
            f.write(header)
            for d in descs:
                f.write(d)
            for b in blobs:
                f.write(b)

    def write_sym(self, out_sym):
        entries = []
        for name, addr in self.labels.items():
            kind = self.label_kinds.get(name, "D")
            entries.append((addr & MASK128, kind, name))
        for name in self.equs:
            v = self.symbol_value(name, self.equs[name][1])
            entries.append((v & MASK128, "A", name))
        entries.sort(key=lambda e: (e[0], e[2]))
        with open(out_sym, "w") as f:
            for addr, kind, name in entries:
                f.write(f"{addr:032x} {kind} {name}\n")


def pack_u128(v):
    return struct.pack("<QQ", v & 0xFFFFFFFFFFFFFFFF, (v >> 64) &
                       0xFFFFFFFFFFFFFFFF)


# ------------------------------------------------------------------ pseudos


def minimal_chain_len(value):
    """Minimal LDI + (n-1) x SHORI chain length for a 128-bit constant."""
    v = value & MASK128
    for n in range(1, 7):
        k = E.IMM_BITS * (n - 1)
        bits = 128 - k
        top = v >> k
        if top >= 1 << (bits - 1):
            top -= 1 << bits
        if IMM_SIGNED_MIN <= top <= IMM_SIGNED_MAX:
            return n
    raise AssertionError("unreachable: 6-chain always fits")


def chain_words(asm, dst, value, n, pred, pos):
    """Emit LDI + SHORI words building `value` in register dst."""
    v = value & MASK128
    k = E.IMM_BITS * (n - 1)
    bits = 128 - k
    top = v >> k
    if top >= 1 << (bits - 1):
        top -= 1 << bits
    ldi_val, _, _ = E.OPCODES["LDI"]
    shori_val, _, _ = E.OPCODES["SHORI"]
    words = [asm.build(ldi_val, pred, dst=dst,
                       imm=asm.imm_signed(top, pos))]
    for i in range(1, n):
        chunk = (v >> (k - E.IMM_BITS * i)) & IMM_UNSIGNED_MAX
        words.append(asm.build(shori_val, pred, dst=dst, src1=dst,
                               imm=chunk))
    return words


def pseudo_li(asm, stmt):
    pos = stmt.pos
    asm.nops(stmt, 2)
    if stmt.mnem == "li" and stmt.suffix is not None:
        raise AsmError(pos, "li takes no width suffix")
    dst = asm.need_reg(stmt.operands[0], pos, "destination")
    v = ExprEval(asm, pos).eval(stmt.operands[1])
    if not -(1 << 127) <= v < (1 << 128):
        raise AsmError(pos, f"li constant does not fit in 128 bits")
    n = stmt.chain
    if minimal_chain_len(v) > n:
        raise AsmError(pos, "internal: li chain shorter than value needs")
    return chain_words(asm, dst, v, n, stmt.pred, pos)


def pseudo_la(asm, stmt):
    pos = stmt.pos
    if stmt.suffix == "abs":
        return pseudo_li(asm, stmt)
    if stmt.suffix is not None:
        raise AsmError(pos, "la takes no width suffix (la.abs for absolute)")
    asm.nops(stmt, 2)
    dst = asm.need_reg(stmt.operands[0], pos, "destination")
    target = ExprEval(asm, pos).eval(stmt.operands[1])
    lap_val, _, _ = E.OPCODES["LAP"]
    add_val, _, _ = E.OPCODES["ADD"]
    delta = target - stmt.addr
    if stmt.la_plan == "lap":
        return [asm.build(lap_val, stmt.pred, dst=dst,
                          imm=asm.imm_signed(delta, pos,
                                             "la displacement"))]
    # LAP + immediate ADD: split delta across the two signed 22-bit fields.
    if delta >= 0:
        first = min(delta, IMM_SIGNED_MAX)
    else:
        first = max(delta, IMM_SIGNED_MIN)
    second = delta - first
    if not IMM_SIGNED_MIN <= second <= IMM_SIGNED_MAX:
        raise AsmError(pos, f"la target is 0x{abs(delta):x} bytes away; "
                            f"beyond LAP+ADD range — use la.abs")
    # ADD.128 immediate form: width code for 128 in the ALU family
    w128 = E.FAMILIES["ALU"]["widths"].index(128)
    return [asm.build(lap_val, stmt.pred, dst=dst,
                      imm=asm.imm_signed(first, pos)),
            asm.build(add_val + 1, stmt.pred, dst=dst, src1=dst, width=w128,
                      imm=asm.imm_signed(second, pos))]


def alu_reg_word(asm, name, stmt, dst, src1, src2, width_bits=128):
    opval, fam, _ = E.OPCODES[name]
    wc = E.FAMILIES[fam]["widths"].index(width_bits)
    return asm.build(opval, stmt.pred, dst=dst, src1=src1, src2=src2,
                     width=wc)


def pseudo_mov(asm, stmt):
    asm.nops(stmt, 2)
    if stmt.suffix is not None:
        raise AsmError(stmt.pos, "mov takes no width suffix")
    dst = asm.need_reg(stmt.operands[0], stmt.pos, "destination")
    src = asm.need_reg(stmt.operands[1], stmt.pos, "source")
    return [alu_reg_word(asm, "OR", stmt, dst, src, ZERO_REG)]


def pseudo_nop(asm, stmt):
    asm.nops(stmt, 0)
    return [alu_reg_word(asm, "OR", stmt, ZERO_REG, ZERO_REG, ZERO_REG)]


def pseudo_not(asm, stmt):
    asm.nops(stmt, 2)
    dst = asm.need_reg(stmt.operands[0], stmt.pos, "destination")
    src = asm.need_reg(stmt.operands[1], stmt.pos, "source")
    opval, fam, _ = E.OPCODES["XOR"]
    saved = stmt.mnem
    stmt.mnem = "xor"
    wc = asm.width_code(stmt, fam)
    stmt.mnem = saved
    return [asm.build(opval + 1, stmt.pred, dst=dst, src1=src, width=wc,
                      imm=asm.imm_signed(-1, stmt.pos))]


def pseudo_neg(asm, stmt):
    asm.nops(stmt, 2)
    dst = asm.need_reg(stmt.operands[0], stmt.pos, "destination")
    src = asm.need_reg(stmt.operands[1], stmt.pos, "source")
    opval, fam, _ = E.OPCODES["SUB"]
    saved = stmt.mnem
    stmt.mnem = "sub"
    wc = asm.width_code(stmt, fam)
    stmt.mnem = saved
    return [asm.build(opval, stmt.pred, dst=dst, src1=ZERO_REG, src2=src,
                      width=wc)]


def pseudo_ret(asm, stmt):
    asm.nops(stmt, 0)
    opval, _, _ = E.OPCODES["JALR"]
    return [asm.build(opval, stmt.pred, dst=ZERO_REG, src1=RA_REG, imm=0)]


def pseudo_sub(asm, stmt):
    """sub rd, imm, rs — reverse-subtract form. TOOLING-SPEC 4.4 lists it
    as a one-instruction expansion; only imm == 0 (neg) is expressible in
    one instruction. Anything else is a loud error (see SPEC-ISSUES.md)."""
    pos = stmt.pos
    if len(stmt.operands) == 3 and \
            parse_reg(stmt.operands[1]) is None and \
            parse_reg(stmt.operands[2]) is not None:
        v = ExprEval(asm, pos).eval(stmt.operands[1])
        if v != 0:
            raise AsmError(pos, "sub rd, imm, rs is only expressible for "
                                "imm = 0 (neg); use li + sub")
        dst = asm.need_reg(stmt.operands[0], pos, "destination")
        src = asm.need_reg(stmt.operands[2], pos, "source")
        opval, fam, _ = E.OPCODES["SUB"]
        saved = stmt.mnem
        stmt.mnem = "sub"
        wc = asm.width_code(stmt, fam)
        stmt.mnem = saved
        return [asm.build(opval, stmt.pred, dst=dst, src1=ZERO_REG,
                          src2=src, width=wc)]
    # ordinary sub
    del PSEUDOS["sub"]
    try:
        return asm.encode(stmt)
    finally:
        PSEUDOS["sub"] = pseudo_sub


PSEUDOS = {
    "li": pseudo_li,
    "la": pseudo_la,
    "mov": pseudo_mov,
    "nop": pseudo_nop,
    "not": pseudo_not,
    "neg": pseudo_neg,
    "ret": pseudo_ret,
    "sub": pseudo_sub,
}


# --------------------------------------------------------------------- main


def assemble(paths, out_img, out_sym):
    asm = Assembler()
    asm.parse_files(paths)
    asm.pass1()
    asm.pass2()
    asm.write_image(out_img)
    asm.write_sym(out_sym)
    return asm


def main(argv):
    out = None
    inputs = []
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "-o":
            if i + 1 >= len(argv):
                sys.exit("error: -o needs an argument")
            out = argv[i + 1]
            i += 2
            continue
        if a.startswith("-"):
            sys.exit(f"error: unknown option {a}\n"
                     f"usage: asm.py [-o OUT.img] input.s ...")
        inputs.append(a)
        i += 1
    if not inputs:
        sys.exit("usage: asm.py [-o OUT.img] input.s ...")
    if out is None:
        out = os.path.splitext(inputs[0])[0] + ".img"
    if not out.endswith(".img"):
        sys.exit("error: output must end in .img")
    out_sym = out[:-4] + ".sym"
    try:
        assemble(inputs, out, out_sym)
    except AsmError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main(sys.argv)
