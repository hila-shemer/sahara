#!/usr/bin/env python3
"""Sahara two-pass assembler `sasm` — TOOLING-SPEC.md section 4 as expanded
by devspec/asm.md (grammar, value kinds, pseudo expansion algorithms, image
emission, and the closed E001-E049 error catalog).

Input: one or more .s files, concatenated in order.
Output: IMAGE.img (TOOLING-SPEC section 1) + IMAGE.sym (section 2).

Every encoding fact (field positions, opcode values, sreg names, width
tables) comes from encoding.py. Nothing here hardcodes any of it.

Errors are fatal, one line on stderr, `FILE:LINE: Ennn: message`, exit 1;
usage/IO problems exit 2 without an E-code. On any error no output file
survives (asm.md ASM-12). Warnings do not exist.
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
SREG_MAX = (1 << (E.IMM_BITS - 1)) - 1   # asm.md 5.9: CONST in [0, 2^21-1]
DEVTAB_BASE, DEVTAB_END = 0x0800, 0x1000  # asm.md 7.5 window [0x800,0x1000)

REG_ALIASES = {"sp": 28, "ra": 29, "k0": 30, "zero": 31}
ZERO_REG = REG_ALIASES["zero"]
RA_REG = REG_ALIASES["ra"]

MOD_KINDS = {"shl": 1, "sxt": 2, "zxt": 3}
FMT_TOKENS = ("f32", "f64", "i32", "i64", "i128")

LABEL_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_.$]*)\s*:")
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.$]*$")
IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.$]*")
NUM_RE = re.compile(r"0[xX][0-9A-Fa-f]+|0[bB][01]+|[0-9]+")
IDENT_CHAR_RE = re.compile(r"[A-Za-z0-9_.$]")

CONST, ADDR = "CONST", "ADDR"


class AsmError(Exception):
    """One diagnostic from the closed catalog (asm.md section 10)."""

    def __init__(self, pos, code, msg):
        super().__init__(f"{pos[0]}:{pos[1]}: {code}: {msg}")
        self.pos, self.code = pos, code


# ---------------------------------------------------------- reserved names


def _valid_suffixes(name, fam):
    """Width suffixes a mnemonic accepts (asm.md 5.3), for 2.3 reservation."""
    if fam in ("ALU", "CMP", "ATOMIC"):
        return ("32", "64", "128")
    if fam == "MEM":
        return ("8", "16", "32", "64")
    if fam == "FP":
        return ("f32", "f64")
    if fam == "FCVT":
        if name in ("FCVTFI", "FCVTFIU"):
            return ("32", "64", "128")
        return ("f32", "f64")
    return ()


def _build_reserved():
    s = set(REG_ALIASES)
    s.update(f"r{i}" for i in range(32))
    s.update(f"p{i}" for i in range(8))
    s.update(E.SREGS)
    for name, (_opv, fam, _spec) in E.OPCODES.items():
        base = name.lower()
        s.add(base)
        for sfx in _valid_suffixes(name, fam):
            s.add(base + "." + sfx)
    s.update(("li", "la", "la.abs", "mov", "nop", "not", "neg", "ret"))
    for sfx in ("32", "64", "128"):   # not/neg pass ALU widths through (6.4)
        s.add("not." + sfx)
        s.add("neg." + sfx)
    s.update(MOD_KINDS)
    s.update(FMT_TOKENS)
    return s


RESERVED = _build_reserved()


# ------------------------------------------------------------------- values


class Val:
    """Expression result: 128-bit wrapped value + kind (asm.md 4.2) +
    whether a label participated anywhere (for 4.4/E029)."""

    __slots__ = ("v", "kind", "label")

    def __init__(self, v, kind, label):
        self.v = v & MASK128
        self.kind = kind
        self.label = label


def sv(val):
    """Signed (two's-complement 128-bit) view of a Val or raw value."""
    v = val.v if isinstance(val, Val) else (val & MASK128)
    return v - (1 << 128) if v >= (1 << 127) else v


# ----------------------------------------------------------------- lexical

ESCAPES = {"n": 10, "t": 9, "r": 13, "b": 8, "f": 12, "0": 0,
           "\\": 92, '"': 34, "'": 39}


def read_escape(text, i, pos):
    """text[i] == '\\'. Returns (byte value, index after escape). E004."""
    if i + 1 >= len(text):
        raise AsmError(pos, "E004", "escape at end of literal")
    e = text[i + 1]
    if e in ESCAPES:
        return ESCAPES[e], i + 2
    if e == "x":
        h = text[i + 2:i + 4]
        if len(h) == 2 and all(c in "0123456789abcdefABCDEF" for c in h):
            return int(h, 16), i + 4
        raise AsmError(pos, "E004", r"\x needs exactly two hex digits")
    raise AsmError(pos, "E004", f"unknown escape sequence \\{e}")


def strip_comment(line):
    """Remove '#'-to-EOL outside literals. Returns (text, open_quote)."""
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
    return "".join(out), quote


# Characters legal outside string/char literals (asm.md 2.1). Anything
# else, and any byte >= 0x80, is E001.
LEGAL_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
                  "0123456789_.$ \t,:()[]+-*!'\"")


def check_chars(text, pos):
    quote = None
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if quote:
            if c == "\\" and i + 1 < n:
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "'\"":
            quote = c
        elif c not in LEGAL_CHARS or ord(c) >= 0x80:
            raise AsmError(pos, "E001", f"illegal character {c!r}")
        i += 1


def tokenize_expr(text, pos):
    """Expression tokens: numbers (incl. char literals), symbols, + - * ( ).
    E001/E002/E004/E005/E011 per catalog."""
    toks, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t":
            i += 1
            continue
        if c == "'":
            if i + 1 < n and text[i + 1] == "\\":
                b, j = read_escape(text, i + 1, pos)
            elif i + 1 < n and text[i + 1] != "'":
                b, j = ord(text[i + 1]), i + 2
            else:
                raise AsmError(pos, "E005", "empty character literal")
            if j >= n or text[j] != "'":
                raise AsmError(pos, "E005", "malformed character literal "
                                            "(multi-character or "
                                            "unterminated)")
            toks.append(("num", b))
            i = j + 1
            continue
        if c.isdigit():
            m = NUM_RE.match(text, i)
            j = m.end()
            if j < n and IDENT_CHAR_RE.match(text[j]):
                raise AsmError(pos, "E002",
                               f"malformed number {text[i:j + 1]!r}")
            t = m.group(0)
            if t[:2].lower() == "0x":
                v = int(t[2:], 16)
            elif t[:2].lower() == "0b":
                v = int(t[2:], 2)
            else:
                v = int(t, 10)
            if v >= 1 << 128:
                raise AsmError(pos, "E002",
                               f"number {t} does not fit in 128 bits")
            toks.append(("num", v))
            i = j
            continue
        m = IDENT_RE.match(text, i)
        if m:
            toks.append(("sym", m.group(0)))
            i = m.end()
            continue
        if c in "+-*()":
            toks.append(("op", c))
            i += 1
            continue
        if c in "[]!:,":
            raise AsmError(pos, "E011", f"misplaced {c!r} in expression")
        raise AsmError(pos, "E001", f"illegal character {c!r}")
    return toks


def has_mod_keyword(toks):
    return any(k == "sym" and t.lower() in MOD_KINDS for k, t in toks)


# --------------------------------------------------------------- expressions


class ExprEval:
    """+ - * ( ) over numbers, .equ names, and labels, with CONST/ADDR
    kind tracking per asm.md 4.2 and 128-bit wrapping per 4.1.

    atc = None for pass-2 contexts; (cutoff_ord, label_code) for
    assembly-time-constant contexts (asm.md 4.4): labels are label_code
    (E034, or E029 for li), symbols not textually earlier are E034."""

    def __init__(self, asm, pos, atc=None):
        self.asm, self.pos, self.atc = asm, pos, atc

    def eval(self, text):
        self.toks = tokenize_expr(text, self.pos)
        self.i = 0
        if not self.toks:
            raise AsmError(self.pos, "E011", "empty expression")
        v = self.expr()
        if self.i != len(self.toks):
            raise AsmError(self.pos, "E011",
                           f"trailing junk in expression: {text!r}")
        return v

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def next(self):
        t = self.peek()
        self.i += 1
        return t

    def expr(self):
        a = self.term()
        while self.peek() in (("op", "+"), ("op", "-")):
            _, op = self.next()
            b = self.term()
            if op == "+":
                if a.kind == ADDR and b.kind == ADDR:
                    raise AsmError(self.pos, "E033", "ADDR + ADDR is not "
                                                     "a value (asm.md 4.2)")
                kind = ADDR if (a.kind == ADDR or b.kind == ADDR) else CONST
                a = Val(a.v + b.v, kind, a.label or b.label)
            else:
                if a.kind == CONST and b.kind == ADDR:
                    raise AsmError(self.pos, "E033",
                                   "CONST - ADDR is not a value (asm.md 4.2)")
                kind = CONST if a.kind == b.kind else ADDR
                a = Val(a.v - b.v, kind, a.label or b.label)
        return a

    def term(self):
        a = self.factor()
        while self.peek() == ("op", "*"):
            self.next()
            b = self.factor()
            if a.kind == ADDR or b.kind == ADDR:
                raise AsmError(self.pos, "E033",
                               "multiplication involving an address "
                               "(asm.md 4.2)")
            a = Val(a.v * b.v, CONST, a.label or b.label)
        return a

    def factor(self):
        kind, val = self.next()
        if kind == "num":
            return Val(val, CONST, False)
        if kind == "op" and val == "-":
            f = self.factor()
            if f.kind == ADDR:
                raise AsmError(self.pos, "E033",
                               "unary minus on an address (asm.md 4.2)")
            return Val(-f.v, CONST, f.label)
        if kind == "op" and val == "+":
            return self.factor()
        if kind == "op" and val == "(":
            v = self.expr()
            if self.next() != ("op", ")"):
                raise AsmError(self.pos, "E011", "missing ')' in expression")
            return v
        if kind == "sym":
            return self.asm.resolve(val, self.pos, self.atc)
        raise AsmError(self.pos, "E011", "malformed expression")


# ------------------------------------------------------------------- parsing


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
                raise AsmError(pos, "E011", "unbalanced brackets")
        elif c == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
            i += 1
            continue
        cur.append(c)
        i += 1
    if depth != 0:
        raise AsmError(pos, "E011", "unbalanced brackets")
    last = "".join(cur).strip()
    if last or parts:
        parts.append(last)
    return parts


def parse_reg(tok):
    t = tok.strip().lower()
    if t in REG_ALIASES:
        return REG_ALIASES[t]
    m = re.fullmatch(r"r([0-9]|[12][0-9]|3[01])", t)  # no leading zeros
    if m:
        return int(m.group(1))
    return None


def parse_predreg(tok):
    m = re.fullmatch(r"p([0-7])", tok.strip().lower())
    if m:
        return int(m.group(1))
    return None


PRED_PREFIX_RE = re.compile(r"^\(\s*(!?)\s*([A-Za-z0-9_]+)\s*\)\s*(.*)$")


class Stmt:
    __slots__ = ("pos", "ord", "kind", "labels", "mnem", "suffix", "pred",
                 "operands", "size", "chain", "li_val", "la_promoted",
                 "addr", "seg", "data_bytes", "org_base", "align_n",
                 "unit")

    def __init__(self, pos, ordn):
        self.pos = pos
        self.ord = ordn
        self.labels = []
        self.kind = None      # "insn" | "directive"
        self.mnem = None      # lowercase mnemonic or directive (with '.')
        self.suffix = None    # width suffix text or None
        self.pred = 0         # encoded pred field
        self.operands = []
        self.size = 0
        self.chain = None     # li/la.abs chain length (pass 1)
        self.li_val = None    # li constant (pass 1, ATC)
        self.la_promoted = False
        self.addr = None
        self.seg = None
        self.data_bytes = None
        self.org_base = None
        self.align_n = None
        self.unit = None


class Segment:
    def __init__(self, base, pos, ordn):
        self.base = base
        self.pos = pos
        self.ord = ordn       # source order, for E042 attribution
        self.size = 0         # layout size (bytes)
        self.data = bytearray()
        self.insn_end = 0     # end of last instruction emission (8.2 trim
                              # floor: never trim into instruction bytes)


DATA_UNITS = {".byte": 1, ".half": 2, ".word": 4, ".quad": 8, ".oct": 16}
DIRECTIVES = set(DATA_UNITS) | {".org", ".entry", ".align", ".byte",
                                ".half", ".word", ".quad", ".oct",
                                ".ascii", ".asciiz", ".space", ".equ"}


# ----------------------------------------------------------------- assembler


class Assembler:
    def __init__(self):
        self.stmts = []
        self.labels = {}          # name -> address (per layout)
        self.label_kinds = {}     # name -> 'T' | 'D'
        self.label_names = set()  # syntactic (known after parse)
        self.sym_defined = set()  # labels + equ names, for E031
        self.equs = {}            # name -> (expr text, pos, ord)
        self.equ_values = {}      # memoized Vals (cleared per layout)
        self.equ_evaluating = set()
        self.segments = []
        self.entry = None         # (label name, pos)

    # ------------------------------------------------------------- symbols

    def resolve(self, name, pos, atc):
        if name.lower() in RESERVED:
            raise AsmError(pos, "E030",
                           f"{name!r} is a reserved name and has no value "
                           f"in expressions (asm.md 4.3)")
        if atc is not None:
            cutoff, label_code = atc
            if name in self.equs:
                _text, _epos, ordn = self.equs[name]
                if ordn >= cutoff:
                    raise AsmError(pos, "E034",
                                   f"{name!r} is not defined before this "
                                   f"point (assembly-time constant, "
                                   f"asm.md 4.4)")
                return self.eval_equ(name, atc)
            if name in self.label_names:
                raise AsmError(pos, label_code,
                               f"{name!r} is a label; an assembly-time "
                               f"constant is required here")
            raise AsmError(pos, "E030", f"undefined symbol {name!r}")
        if name in self.labels:
            return Val(self.labels[name], ADDR, True)
        if name in self.equs:
            return self.eval_equ(name, None)
        raise AsmError(pos, "E030", f"undefined symbol {name!r}")

    def eval_equ(self, name, atc):
        if atc is None and name in self.equ_values:
            return self.equ_values[name]
        text, epos, _ordn = self.equs[name]
        if name in self.equ_evaluating:
            raise AsmError(epos, "E030",
                           f".equ cycle involving {name!r} never resolves "
                           f"to a value")
        self.equ_evaluating.add(name)
        try:
            v = ExprEval(self, epos, atc).eval(text)
        finally:
            self.equ_evaluating.discard(name)
        if atc is None:
            self.equ_values[name] = v
        return v

    def eval_val(self, text, pos, atc=None):
        return ExprEval(self, pos, atc).eval(text)

    def eval_atc(self, text, pos, stmt, label_code="E034"):
        return self.eval_val(text, pos, (stmt.ord, label_code))

    def def_symbol(self, name, pos, is_label):
        if name.lower() in RESERVED:
            raise AsmError(pos, "E032",
                           f"{name!r} collides with a reserved name "
                           f"(asm.md 2.3)")
        if name in self.sym_defined:
            raise AsmError(pos, "E031", f"duplicate symbol {name!r}")
        self.sym_defined.add(name)
        if is_label:
            self.label_names.add(name)

    # ------------------------------------------------------------- parsing

    def parse_files(self, paths):
        for path in paths:
            try:
                # latin-1: byte-faithful; >=0x80 outside literals is E001.
                with open(path, encoding="latin-1") as f:
                    lines = f.readlines()
            except OSError as e:
                usage_exit(f"cannot read {path}: {e}")
            for lineno, line in enumerate(lines, 1):
                self.parse_line(path, lineno, line)

    def parse_line(self, path, lineno, line):
        pos = (path, lineno)
        line = line.rstrip("\n")
        if line.endswith("\r"):
            line = line[:-1]
        text, open_quote = strip_comment(line)
        if open_quote == '"':
            raise AsmError(pos, "E003", "unterminated string literal")
        if open_quote == "'":
            raise AsmError(pos, "E005", "unterminated character literal")
        check_chars(text, pos)
        text = text.strip()
        stmt = Stmt(pos, len(self.stmts))
        while True:
            m = LABEL_RE.match(text)
            if not m:
                break
            stmt.labels.append(m.group(1))
            text = text[m.end():].strip()
        if text.startswith(":"):
            raise AsmError(pos, "E018", "malformed label definition")
        if not text:
            if stmt.labels:
                self.stmts.append(stmt)
            return
        # a ':' surviving into statement text is a malformed label (E018)
        rest_nq, _ = _strip_literals(text)
        if ":" in rest_nq:
            raise AsmError(pos, "E018",
                           "':' outside a label definition")
        if text.startswith("("):
            m = PRED_PREFIX_RE.match(text)
            if not m:
                raise AsmError(pos, "E017", "malformed predication prefix")
            preg = parse_predreg(m.group(2))
            if preg is None:
                raise AsmError(pos, "E017",
                               f"bad predicate register {m.group(2)!r}")
            stmt.pred = (preg << 1) | (1 if m.group(1) else 0)
            text = m.group(3).strip()
            if not text or text.startswith("."):
                raise AsmError(pos, "E017",
                               "predication prefix must precede an "
                               "instruction")
        parts = text.split(None, 1)
        head = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""
        if head.startswith("."):
            stmt.kind = "directive"
            stmt.mnem = head
            if head not in DIRECTIVES:
                raise AsmError(pos, "E010", f"unknown directive {head}")
            stmt.operands = split_operands(rest, pos)
        else:
            stmt.kind = "insn"
            if "." in head:
                base, suffix = head.split(".", 1)
                stmt.mnem, stmt.suffix = base, suffix
            else:
                stmt.mnem = head
            if stmt.mnem not in PSEUDOS and stmt.mnem.upper() not in \
                    E.OPCODES:
                raise AsmError(pos, "E010",
                               f"unknown mnemonic {stmt.mnem!r}")
            stmt.operands = split_operands(rest, pos)
        self.stmts.append(stmt)

    # ------------------------------------------------------------- prescan

    def prescan(self):
        for stmt in self.stmts:
            pos = stmt.pos
            for lbl in stmt.labels:
                self.def_symbol(lbl, pos, is_label=True)
            if stmt.kind != "directive":
                continue
            d, ops = stmt.mnem, stmt.operands
            if d == ".equ":
                if len(ops) != 2:
                    raise AsmError(pos, "E011", ".equ takes NAME, expr")
                name = ops[0]
                if not NAME_RE.match(name):
                    raise AsmError(pos, "E011", f"bad .equ name {name!r}")
                self.def_symbol(name, pos, is_label=False)
                self.equs[name] = (ops[1], pos, stmt.ord)
            elif d == ".entry":
                if len(ops) != 1 or not NAME_RE.match(ops[0]):
                    raise AsmError(pos, "E011", ".entry takes one label "
                                                "name")
                if self.entry is not None:
                    raise AsmError(pos, "E046", "multiple .entry")
                self.entry = (ops[0], pos)
            elif d in (".org", ".align", ".space"):
                if len(ops) != 1:
                    raise AsmError(pos, "E011", f"{d} takes one operand")
            elif d in DATA_UNITS:
                if not ops:
                    raise AsmError(pos, "E011",
                                   f"{d} needs at least one value")
            elif d in (".ascii", ".asciiz"):
                if len(ops) != 1:
                    raise AsmError(pos, "E011", f"{d} takes one string")
                stmt.data_bytes = self.string_bytes(stmt)

    def string_bytes(self, stmt):
        pos = stmt.pos
        s = stmt.operands[0].strip()
        if len(s) < 2 or s[0] != '"' or s[-1] != '"':
            raise AsmError(pos, "E003",
                           f"{stmt.mnem}: expected a quoted string")
        body, i = s[1:-1], 0
        out = bytearray()
        while i < len(body):
            if body[i] == "\\":
                b, i = read_escape(body, i, pos)
                out.append(b)
            else:
                out.append(ord(body[i]))
                i += 1
        if stmt.mnem == ".asciiz":
            out.append(0)
        return bytes(out)

    # ------------------------------------------------- sizing (pass 1)

    def size_stmts(self):
        for stmt in self.stmts:
            pos = stmt.pos
            if stmt.kind == "directive":
                d = stmt.mnem
                if d == ".org":
                    v = self.eval_atc(stmt.operands[0], pos, stmt)
                    if sv(v) < 0:
                        raise AsmError(pos, "E035",
                                       ".org address must be >= 0")
                    stmt.org_base = v.v
                elif d == ".align":
                    n = sv(self.eval_atc(stmt.operands[0], pos, stmt))
                    if n < 1 or (n & (n - 1)) != 0:
                        raise AsmError(pos, "E044",
                                       f".align {n}: not a power of two "
                                       f">= 1")
                    stmt.align_n = n
                elif d == ".space":
                    n = sv(self.eval_atc(stmt.operands[0], pos, stmt))
                    if n < 0:
                        raise AsmError(pos, "E035",
                                       f".space {n}: negative size")
                    stmt.size = n
                elif d in DATA_UNITS:
                    stmt.unit = DATA_UNITS[d]
                    stmt.size = stmt.unit * len(stmt.operands)
                elif d in (".ascii", ".asciiz"):
                    stmt.size = len(stmt.data_bytes)
                continue
            if stmt.kind != "insn":
                continue
            m = stmt.mnem
            if m == "li":
                if stmt.suffix is not None:
                    raise AsmError(pos, "E015", "li takes no width suffix")
                if len(stmt.operands) != 2:
                    raise AsmError(pos, "E011", "li takes rd, constant")
                v = self.eval_atc(stmt.operands[1], pos, stmt,
                                  label_code="E029")
                stmt.li_val = v.v
                stmt.chain = minimal_chain_len(v.v)
                stmt.size = stmt.chain * E.INSN_BYTES
            elif m == "la" and stmt.suffix == "abs":
                if len(stmt.operands) != 2:
                    raise AsmError(pos, "E011", "la.abs takes rd, target")
                stmt.chain = 6
                stmt.size = 6 * E.INSN_BYTES
            elif m == "la":
                if stmt.suffix is not None:
                    raise AsmError(pos, "E015",
                                   "la takes no width suffix (la.abs for "
                                   "absolute)")
                if len(stmt.operands) != 2:
                    raise AsmError(pos, "E011", "la takes rd, target")
                stmt.size = E.INSN_BYTES  # provisional; relaxation promotes
            else:
                stmt.size = E.INSN_BYTES

    # -------------------------------------------------------------- layout

    def layout(self):
        self.segments = []
        self.labels = {}
        self.label_kinds = {}
        self.equ_values = {}      # label addresses may have moved
        pending = []
        seg = None

        def flush(kind):
            for lbl in pending:
                self.label_kinds[lbl] = kind
            pending.clear()

        for stmt in self.stmts:
            pos = stmt.pos
            if stmt.labels:
                if seg is None:
                    raise AsmError(pos, "E041",
                                   "label defined before the first .org")
                for lbl in stmt.labels:
                    self.labels[lbl] = seg.base + seg.size
                    pending.append(lbl)
            if stmt.kind is None:
                continue
            if stmt.kind == "directive":
                d = stmt.mnem
                if d == ".org":
                    flush("D")
                    seg = Segment(stmt.org_base, pos, len(self.segments))
                    self.segments.append(seg)
                    stmt.seg = seg.ord
                    continue
                if d in (".equ", ".entry"):
                    continue
                if seg is None:
                    raise AsmError(pos, "E040",
                                   f"{d} before the first .org")
                if d == ".align":
                    stmt.size = (-(seg.base + seg.size)) % stmt.align_n
                stmt.addr = seg.base + seg.size
                stmt.seg = seg.ord
                seg.size += stmt.size
                if stmt.size:
                    flush("D")
                continue
            # instruction
            if seg is None:
                raise AsmError(pos, "E040",
                               "instruction before the first .org")
            if stmt.mnem == "la" and stmt.suffix is None:
                stmt.size = (2 if stmt.la_promoted else 1) * E.INSN_BYTES
            addr = seg.base + seg.size
            if addr % E.INSN_BYTES != 0:
                raise AsmError(pos, "E043",
                               f"instruction at 0x{addr:x} is not "
                               f"{E.INSN_BYTES}-byte aligned")
            stmt.addr = addr
            stmt.seg = seg.ord
            seg.size += stmt.size
            flush("T")
        flush("D")

    def relax(self):
        """One promotion sweep of asm.md 6.2; True if anything grew."""
        changed = False
        for stmt in self.stmts:
            if (stmt.kind == "insn" and stmt.mnem == "la"
                    and stmt.suffix is None and not stmt.la_promoted):
                target = self.eval_val(stmt.operands[1], stmt.pos)
                delta = sv(target) - stmt.addr
                if not IMM_SIGNED_MIN <= delta <= IMM_SIGNED_MAX:
                    stmt.la_promoted = True
                    changed = True
        return changed

    def pass1(self):
        self.prescan()
        self.size_stmts()
        self.layout()
        while self.relax():
            self.layout()

    # -------------------------------------------------------------- pass 2

    def pass2(self):
        for seg in self.segments:
            seg.data = bytearray()
        for stmt in self.stmts:
            if stmt.kind == "directive":
                self.pass2_directive(stmt)
                continue
            if stmt.kind != "insn":
                continue
            seg = self.segments[stmt.seg]
            assert seg.base + len(seg.data) == stmt.addr, \
                f"{stmt.pos}: pass1/pass2 layout mismatch"
            words = self.encode(stmt)
            assert len(words) * E.INSN_BYTES == stmt.size, \
                f"{stmt.pos}: pass1/pass2 size mismatch"
            for w in words:
                seg.data.extend(struct.pack("<Q", w))
            seg.insn_end = len(seg.data)
        for seg in self.segments:
            assert len(seg.data) == seg.size, "segment length mismatch"

    def pass2_directive(self, stmt):
        d, pos = stmt.mnem, stmt.pos
        if d in (".org", ".entry", ".equ"):
            return
        seg = self.segments[stmt.seg]
        if d in (".align", ".space"):
            seg.data.extend(b"\0" * stmt.size)
            return
        if d in DATA_UNITS:
            unit = stmt.unit
            lo, hi = -(1 << (unit * 8 - 1)), (1 << (unit * 8)) - 1
            for op in stmt.operands:
                v = sv(self.eval_val(op, pos))
                if not lo <= v <= hi:
                    raise AsmError(pos, "E035",
                                   f"{d} value {v} does not fit in "
                                   f"{unit} byte(s)")
                seg.data.extend((v % (1 << (unit * 8)))
                                .to_bytes(unit, "little"))
            return
        if d in (".ascii", ".asciiz"):
            seg.data.extend(stmt.data_bytes)
            return
        raise AssertionError(f"unhandled directive {d}")

    # ------------------------------------------------------------ encoding

    def field(self, word, name, value):
        lsb, width = E.FIELDS[name]
        assert 0 <= value < (1 << width), f"field {name} value {value}"
        return word | (value << lsb)

    def build(self, opval, pred=0, **fields):
        w = self.field(0, "opcode", opval)
        w = self.field(w, "pred", pred)
        for name, val in fields.items():
            w = self.field(w, name, val)
        return w

    def imm_signed(self, v, pos, code="E020", what="immediate"):
        if not IMM_SIGNED_MIN <= v <= IMM_SIGNED_MAX:
            raise AsmError(pos, code,
                           f"{what} {v} does not fit in signed "
                           f"{E.IMM_BITS}-bit field")
        return v & IMM_UNSIGNED_MAX

    def imm_unsigned(self, v, pos, code="E021", what="immediate"):
        if not 0 <= v <= IMM_UNSIGNED_MAX:
            raise AsmError(pos, code,
                           f"{what} {v} does not fit in unsigned "
                           f"{E.IMM_BITS}-bit field")
        return v

    def need_reg(self, tok, pos, what, code="E012"):
        parts = tok.split()
        r = parse_reg(parts[0]) if parts else None
        if r is None:
            raise AsmError(pos, code,
                           f"{what}: expected a register, got {tok!r}")
        if len(parts) > 1:
            if parts[1].lower() in MOD_KINDS:
                raise AsmError(pos, "E019",
                               f"{what}: no modifier allowed here")
            raise AsmError(pos, code, f"{what}: junk after register "
                                      f"{tok!r}")
        return r

    def need_pred(self, tok, pos, what):
        p = parse_predreg(tok)
        if p is None:
            raise AsmError(pos, "E013",
                           f"{what}: expected a predicate register "
                           f"(p0-p7), got {tok!r}")
        return p

    def width_code(self, stmt, fam):
        """Suffix -> width field per asm.md 5.3; E015/E016."""
        pos, sfx = stmt.pos, stmt.suffix
        widths = E.FAMILIES[fam]["widths"]
        if fam in ("ALU", "CMP", "ATOMIC"):
            if sfx is None:
                return widths.index(128)
            if sfx in ("32", "64", "128"):
                return widths.index(int(sfx))
            raise AsmError(pos, "E015",
                           f"bad width suffix .{sfx} for {stmt.mnem}")
        if fam == "MEM":
            if sfx is None:
                raise AsmError(pos, "E016",
                               f"{stmt.mnem} needs a width suffix "
                               f".8/.16/.32/.64")
            if sfx in ("8", "16", "32", "64"):
                return widths.index(int(sfx))
            raise AsmError(pos, "E015",
                           f"bad width suffix .{sfx} for {stmt.mnem}")
        if fam == "FP":
            if sfx is None:
                raise AsmError(pos, "E016",
                               f"{stmt.mnem} needs .f32 or .f64")
            if sfx in ("f32", "f64"):
                return widths.index("FP32" if sfx == "f32" else "FP64")
            raise AsmError(pos, "E015",
                           f"bad width suffix .{sfx} for {stmt.mnem}")
        if sfx is not None:
            raise AsmError(pos, "E015",
                           f"{stmt.mnem} takes no width suffix")
        return 0

    def mod_amount(self, text, pos, stmt):
        amount = sv(self.eval_atc(text, pos, stmt))
        if not 0 <= amount <= 63:
            raise AsmError(pos, "E024",
                           f"modifier amount {amount} out of range 0-63")
        return amount

    def parse_b_operand(self, stmt, tok, pos):
        """ALU/CMP operand b: register [mod amount] or expression.
        Returns ("reg", src2, mod) or ("imm", signed value)."""
        parts = tok.split()
        r = parse_reg(parts[0]) if parts else None
        if r is not None:
            if len(parts) == 1:
                return ("reg", r, 0)
            kind = parts[1].lower()
            if kind not in MOD_KINDS or len(parts) < 3:
                raise AsmError(pos, "E019",
                               f"malformed src2 modifier in {tok!r}")
            amount = self.mod_amount(" ".join(parts[2:]), pos, stmt)
            return ("reg", r, (amount << 2) | MOD_KINDS[kind])
        toks = tokenize_expr(tok, pos)
        if has_mod_keyword(toks):
            raise AsmError(pos, "E019",
                           "modifier after an immediate operand")
        v = self.eval_val(tok, pos)
        return ("imm", sv(v))

    def parse_mem(self, stmt, tok, pos, allow_index=True):
        """[base + index mod n + disp] -> (src1, src2, mod, disp)."""
        t = tok.strip()
        if not (t.startswith("[") and t.endswith("]")):
            raise AsmError(pos, "E014",
                           f"expected memory operand [..], got {tok!r}")
        inner = t[1:-1].strip()
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
            raise AsmError(pos, "E014", "empty memory operand")
        base = parse_reg(terms[0][1])
        if base is None or terms[0][0] == "-":
            raise AsmError(pos, "E014",
                           f"memory operand must start with a base "
                           f"register: {tok!r}")
        src2, mod, disp_terms, have_index = ZERO_REG, 0, [], False
        for sign, term in terms[1:]:
            parts = term.split()
            r = parse_reg(parts[0])
            if r is not None:
                if not allow_index:
                    raise AsmError(pos, "E014",
                                   "atomic address is [base + imm] only "
                                   "(no index register, ISA-SPEC 5.4)")
                if sign == "-":
                    raise AsmError(pos, "E014",
                                   "index register cannot be negated")
                if have_index:
                    raise AsmError(pos, "E014",
                                   "more than one index register")
                if disp_terms:
                    raise AsmError(pos, "E014",
                                   "index register after displacement")
                have_index = True
                if len(parts) >= 2:
                    kind = parts[1].lower()
                    if kind not in MOD_KINDS or len(parts) < 3:
                        raise AsmError(pos, "E019",
                                       f"malformed index modifier "
                                       f"{term!r}")
                    amount = self.mod_amount(" ".join(parts[2:]), pos,
                                             stmt)
                    mod = (amount << 2) | MOD_KINDS[kind]
                src2 = r
            else:
                toks = tokenize_expr(term, pos)
                if has_mod_keyword(toks):
                    raise AsmError(pos, "E019",
                                   "modifier after an immediate term")
                disp_terms.append((sign, term))
        disp = 0
        for sign, term in disp_terms:
            v = sv(self.eval_val(term, pos))
            disp += v if sign == "+" else -v
        return base, src2, mod, disp

    def nops(self, stmt, n):
        if len(stmt.operands) != n:
            raise AsmError(stmt.pos, "E011",
                           f"{stmt.mnem} takes {n} operand(s), got "
                           f"{len(stmt.operands)}")

    def encode(self, stmt):
        m = stmt.mnem
        pos = stmt.pos
        if m in PSEUDOS:
            return PSEUDOS[m](self, stmt)
        name = m.upper()
        if name not in E.OPCODES:
            raise AsmError(pos, "E010", f"unknown mnemonic {stmt.mnem!r}")
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
            b = self.parse_b_operand(stmt, btok, pos)
            if b[0] == "reg":
                return [self.build(opval, pred, dst=dst, src1=src1,
                                   src2=b[1], mod=b[2], src3=src3,
                                   width=wc)]
            return [self.build(opval + 1, pred, dst=dst, src1=src1,
                               imm=self.imm_signed(b[1], pos), src3=src3,
                               width=wc)]

        if fam in ("MEM", "MEM128"):
            wc = self.width_code(stmt, "MEM") if fam == "MEM" else \
                self.width_code(stmt, "MEM128")
            self.nops(stmt, 2)
            if opspec == "dm":           # loads: rd, [ea]
                dst = self.need_reg(stmt.operands[0], pos, "destination")
                base, src2, mod, disp = self.parse_mem(stmt,
                                                       stmt.operands[1],
                                                       pos)
                return [self.build(opval, pred, dst=dst, src1=base,
                                   src2=src2, mod=mod, width=wc,
                                   imm=self.imm_signed(disp, pos,
                                                       what="displacement"
                                                       ))]
            # stores: [ea], rs (data register last, asm.md 5.5)
            src3 = self.need_reg(stmt.operands[1], pos, "store value")
            base, src2, mod, disp = self.parse_mem(stmt, stmt.operands[0],
                                                   pos)
            return [self.build(opval, pred, src3=src3, src1=base,
                               src2=src2, mod=mod, width=wc,
                               imm=self.imm_signed(disp, pos,
                                                   what="displacement"))]

        if fam == "ATOMIC":
            wc = self.width_code(stmt, fam)
            if opspec == "da23":         # CAS: rd, [ea], rexp, rnew
                self.nops(stmt, 4)
                dst = self.need_reg(stmt.operands[0], pos, "destination")
                base, _, _, disp = self.parse_mem(stmt, stmt.operands[1],
                                                  pos, allow_index=False)
                src2 = self.need_reg(stmt.operands[2], pos,
                                     "expected value", code="E027")
                src3 = self.need_reg(stmt.operands[3], pos, "new value",
                                     code="E027")
                return [self.build(opval, pred, dst=dst, src1=base,
                                   src2=src2, src3=src3, width=wc,
                                   imm=self.imm_signed(disp, pos,
                                                       what="displacement"
                                                       ))]
            self.nops(stmt, 3)           # AMO*: rd, [ea], rs2
            dst = self.need_reg(stmt.operands[0], pos, "destination")
            base, _, _, disp = self.parse_mem(stmt, stmt.operands[1], pos,
                                              allow_index=False)
            src2 = self.need_reg(stmt.operands[2], pos, "operand",
                                 code="E027")
            return [self.build(opval, pred, dst=dst, src1=base, src2=src2,
                               width=wc,
                               imm=self.imm_signed(disp, pos,
                                                   what="displacement"))]

        if fam == "CTRL":
            if stmt.suffix is not None:
                raise AsmError(pos, "E015",
                               f"{stmt.mnem} takes no width suffix")
            if name == "B":
                self.nops(stmt, 1)
                return [self.build(opval, pred,
                                   imm=self.branch_disp(stmt.operands[0],
                                                        stmt.addr, pos))]
            if name == "JAL":
                if len(stmt.operands) == 1:      # bare jal target (6.4)
                    dst, target = RA_REG, stmt.operands[0]
                else:
                    self.nops(stmt, 2)
                    dst = self.need_reg(stmt.operands[0], pos, "link")
                    target = stmt.operands[1]
                return [self.build(opval, pred, dst=dst,
                                   imm=self.branch_disp(target, stmt.addr,
                                                        pos))]
            # JALR: byte-offset immediate, E020 (asm.md 5.7)
            self.nops(stmt, 3)
            dst = self.need_reg(stmt.operands[0], pos, "link")
            src1 = self.need_reg(stmt.operands[1], pos, "target base")
            off = sv(self.eval_val(stmt.operands[2], pos))
            return [self.build(opval, pred, dst=dst, src1=src1,
                               imm=self.imm_signed(off, pos))]

        if fam == "CONST":
            if stmt.suffix is not None:
                raise AsmError(pos, "E015",
                               f"{stmt.mnem} takes no width suffix")
            if name == "LDI":
                self.nops(stmt, 2)
                dst = self.need_reg(stmt.operands[0], pos, "destination")
                v = sv(self.eval_val(stmt.operands[1], pos))
                return [self.build(opval, pred, dst=dst,
                                   imm=self.imm_signed(v, pos))]
            if name == "SHORI":
                self.nops(stmt, 3)
                dst = self.need_reg(stmt.operands[0], pos, "destination")
                src1 = self.need_reg(stmt.operands[1], pos, "source")
                v = sv(self.eval_val(stmt.operands[2], pos))
                return [self.build(opval, pred, dst=dst, src1=src1,
                                   imm=self.imm_unsigned(v, pos))]
            # LAP: operand is the target byte address; imm = target - pc
            self.nops(stmt, 2)
            dst = self.need_reg(stmt.operands[0], pos, "destination")
            target = sv(self.eval_val(stmt.operands[1], pos))
            delta = target - stmt.addr
            return [self.build(opval, pred, dst=dst,
                               imm=self.imm_signed(delta, pos,
                                                   code="E023",
                                                   what="lap "
                                                        "displacement"))]

        if fam == "PREDF":
            if stmt.suffix is not None:
                raise AsmError(pos, "E015",
                               f"{stmt.mnem} takes no width suffix")
            self.nops(stmt, 1)
            if name == "PRD":
                dst = self.need_reg(stmt.operands[0], pos, "destination")
                return [self.build(opval, pred, dst=dst)]
            src1 = self.need_reg(stmt.operands[0], pos, "source")
            return [self.build(opval, pred, src1=src1)]

        if fam == "SYS":
            if stmt.suffix is not None:
                raise AsmError(pos, "E015",
                               f"{stmt.mnem} takes no width suffix")
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

        raise AssertionError(f"unhandled family {fam}")

    def branch_disp(self, target_expr, pc, pos):
        target = sv(self.eval_val(target_expr, pos))
        delta = target - pc
        if delta % E.INSN_BYTES != 0:
            raise AsmError(pos, "E022",
                           f"branch target 0x{target & MASK128:x} minus "
                           f"pc is not a multiple of {E.INSN_BYTES}")
        return self.imm_signed(delta // E.INSN_BYTES, pos, code="E023",
                               what="branch displacement (instructions)")

    def sreg_index(self, tok, pos):
        """asm.md 5.9: sreg name, or CONST in [0, 2^21-1]; E026 with
        precedence over E030 for a lone unresolvable identifier."""
        t = tok.strip()
        low = t.lower()
        if low in E.SREGS:
            return E.SREGS[low]
        if NAME_RE.match(t):
            defined = t in self.labels or t in self.equs
            if not defined:
                raise AsmError(pos, "E026",
                               f"{t!r} is neither a sreg name nor a "
                               f"defined CONST symbol")
            v = self.eval_val(t, pos)
            if v.kind != CONST or not 0 <= sv(v) <= SREG_MAX:
                raise AsmError(pos, "E026",
                               f"{t!r} is not a CONST in [0, 2^21-1]")
            return sv(v)
        v = self.eval_val(tok, pos)
        if v.kind != CONST or not 0 <= sv(v) <= SREG_MAX:
            raise AsmError(pos, "E026",
                           f"sreg operand must be a name or a CONST in "
                           f"[0, 2^21-1]")
        return sv(v)

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
            # FP sources are register-only: E027 (asm.md 5.11)
            src1 = self.need_reg(ops[1], pos, "src1", code="E027")
            src2 = self.need_reg(ops[2], pos, "src2", code="E027") \
                if regs_needed >= 3 else 0
            src3 = self.need_reg(ops[3], pos, "src3", code="E027") \
                if regs_needed == 4 else 0
            return [self.build(opval, pred, dst=dst, src1=src1, src2=src2,
                               src3=src3, width=wc)]
        # FCVT: width = dest format code, mod bits 1:0 = source format
        sfx = stmt.suffix
        if sfx is None:
            raise AsmError(pos, "E016",
                           f"{stmt.mnem} needs a destination format "
                           f"suffix")
        dst_map = self.INT_DST_SFX if name in ("FCVTFI", "FCVTFIU") \
            else self.FP_DST_SFX
        if sfx not in dst_map:
            raise AsmError(pos, "E015",
                           f"bad width suffix .{sfx} for {stmt.mnem}")
        self.nops(stmt, 3)
        dst = self.need_reg(stmt.operands[0], pos, "destination")
        src1 = self.need_reg(stmt.operands[1], pos, "source")
        srcfmt_tok = stmt.operands[2].strip().lower()
        wc = dst_map[sfx]
        if name in ("FCVTFI", "FCVTFIU"):     # FP -> int
            src_map = self.FP_SRC_FMT
        elif name in ("FCVTIF", "FCVTUIF"):   # int -> FP
            src_map = self.INT_SRC_FMT
        else:                                 # FCVTFF: FP -> FP, 32<->64
            src_map = self.FP_SRC_FMT
        if srcfmt_tok not in src_map:
            raise AsmError(pos, "E025",
                           f"{stmt.mnem}: illegal source format "
                           f"{stmt.operands[2].strip()!r} (asm.md 5.10)")
        sf = src_map[srcfmt_tok]
        if name == "FCVTFF" and wc == sf:
            raise AsmError(pos, "E025",
                           "fcvtff source and destination formats must "
                           "differ (32 <-> 64)")
        return [self.build(opval, pred, dst=dst, src1=src1, width=wc,
                           mod=sf)]

    # ------------------------------------------------------------- output

    def check_layout(self):
        first_pos = self.segments[0].pos if self.segments else \
            self.stmts[0].pos if self.stmts else ("<input>", 1)
        for seg in self.segments:                       # E045 first
            if seg.size == 0:
                raise AsmError(seg.pos, "E045",
                               f"empty segment at 0x{seg.base:x} (use "
                               f".space for reserved regions)")
        exts = sorted(((seg.base, seg.base + seg.size, seg)
                       for seg in self.segments),
                      key=lambda t: (t[0], t[1]))
        for (a0, a1, sa), (b0, b1, sb) in zip(exts, exts[1:]):  # E042
            if b0 < a1:
                later = sb if sb.ord > sa.ord else sa
                raise AsmError(later.pos, "E042",
                               f"segment [0x{b0:x},0x{b1:x}) overlaps "
                               f"segment [0x{a0:x},0x{a1:x})")
        for seg in self.segments:                       # E042 (devtab)
            if seg.base < DEVTAB_END and seg.base + seg.size > DEVTAB_BASE:
                raise AsmError(seg.pos, "E042",
                               f"segment [0x{seg.base:x},"
                               f"0x{seg.base + seg.size:x}) overlaps the "
                               f"device table window [0x{DEVTAB_BASE:x},"
                               f"0x{DEVTAB_END:x})")
        if not any(seg.base <= E.RESET_PC < seg.base + seg.size
                   for seg in self.segments):           # E049
            raise AsmError(first_pos, "E049",
                           f"no segment covers the reset PC "
                           f"0x{E.RESET_PC:x}")

    def entry_value(self):
        if self.entry is None:
            return E.RESET_PC
        name, pos = self.entry
        if name not in self.labels:
            raise AsmError(pos, "E046",
                           f".entry label {name!r} is not defined")
        v = self.labels[name]
        if v % E.INSN_BYTES != 0:
            raise AsmError(pos, "E047",
                           f"entry 0x{v:x} is not {E.INSN_BYTES}-byte "
                           f"aligned")
        if not any(seg.base <= v < seg.base + seg.size
                   for seg in self.segments):
            raise AsmError(pos, "E048",
                           f"entry 0x{v:x} is not inside any segment")
        return v

    def write_image(self, out_img):
        self.check_layout()
        entry = self.entry_value()
        header = b"SAHIMG01" + pack_u128(entry) + \
            struct.pack("<Q", len(self.segments))
        file_off = len(header) + 48 * len(self.segments)
        descs, blobs = [], []
        for seg in self.segments:
            # asm.md 8.2: file_len trims the trailing zero-byte run —
            # but never into instruction-emitted bytes: T4's segment 1
            # (file_len 32, halt's zero bytes kept) and trace.md TV-1
            # (whose sha256 is embedded in TV-2's META) both pin whole
            # instruction words in the file. SPEC-ISSUES.md 33.
            flen = len(seg.data)
            while flen > seg.insn_end and seg.data[flen - 1] == 0:
                flen -= 1
            descs.append(pack_u128(seg.base) +
                         struct.pack("<QQQQ", file_off, flen,
                                     len(seg.data), 0))
            blobs.append(bytes(seg.data[:flen]))
            file_off += flen
        with open(out_img, "wb") as f:
            f.write(header)
            for d in descs:
                f.write(d)
            for b in blobs:
                f.write(b)

    def write_sym(self, out_sym):
        entries = []
        for name, addr in self.labels.items():
            entries.append((addr & MASK128, self.label_kinds[name], name))
        for name in self.equs:
            v = self.eval_equ(name, None)
            if v.kind == CONST:      # ADDR-kind .equs get no row (8.3)
                entries.append((v.v, "A", name))
        entries.sort(key=lambda e: (e[0], e[2]))
        with open(out_sym, "w") as f:
            for addr, kind, name in entries:
                f.write(f"{addr:032x} {kind} {name}\n")


def pack_u128(v):
    return struct.pack("<QQ", v & 0xFFFFFFFFFFFFFFFF,
                       (v >> 64) & 0xFFFFFFFFFFFFFFFF)


def _strip_literals(text):
    """Replace string/char literal bodies with spaces; returns
    (stripped text, open quote or None)."""
    out, i, n = [], 0, len(text)
    quote = None
    while i < n:
        c = text[i]
        if quote:
            out.append(" ")
            if c == "\\" and i + 1 < n:
                out.append(" ")
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "'\"":
            quote = c
            out.append(" ")
        else:
            out.append(c)
        i += 1
    return "".join(out), quote


# ------------------------------------------------------------------ pseudos


def minimal_chain_len(value):
    """Minimal LDI + (n-1) x SHORI chain length per asm.md 6.1."""
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
    """Emit LDI + SHORI words building `value` in register dst.

    asm.md 6.1: imm of the leading LDI is chunk c_{n-1} VERBATIM —
    (V >> 22(n-1)) & 0x3FFFFF, no sign adjustment (for n = 6 the chunk
    has only 18 significant bits and is emitted as-is; LDI's
    sign-extension excess shifts out of bit 127)."""
    v = value & MASK128
    k = E.IMM_BITS * (n - 1)
    ldi_val, _, _ = E.OPCODES["LDI"]
    shori_val, _, _ = E.OPCODES["SHORI"]
    words = [asm.build(ldi_val, pred, dst=dst,
                       imm=(v >> k) & IMM_UNSIGNED_MAX)]
    for i in range(1, n):
        chunk = (v >> (k - E.IMM_BITS * i)) & IMM_UNSIGNED_MAX
        words.append(asm.build(shori_val, pred, dst=dst, src1=dst,
                               imm=chunk))
    return words


def pseudo_li(asm, stmt):
    dst = asm.need_reg(stmt.operands[0], stmt.pos, "destination")
    return chain_words(asm, dst, stmt.li_val, stmt.chain, stmt.pred,
                       stmt.pos)


def pseudo_la(asm, stmt):
    pos = stmt.pos
    if stmt.suffix == "abs":         # asm.md 6.3: fixed 6-chain
        dst = asm.need_reg(stmt.operands[0], pos, "destination")
        v = asm.eval_val(stmt.operands[1], pos)
        return chain_words(asm, dst, v.v, 6, stmt.pred, pos)
    dst = asm.need_reg(stmt.operands[0], pos, "destination")
    target = sv(asm.eval_val(stmt.operands[1], pos))
    lap_val, _, _ = E.OPCODES["LAP"]
    add_val, _, _ = E.OPCODES["ADD"]
    delta = target - stmt.addr
    if not stmt.la_promoted:
        return [asm.build(lap_val, stmt.pred, dst=dst,
                          imm=asm.imm_signed(delta, pos, code="E023",
                                             what="la displacement"))]
    # LAP + immediate ADD: d1 = clamp(delta), d2 = delta - d1 (asm.md 6.2)
    d1 = max(IMM_SIGNED_MIN, min(delta, IMM_SIGNED_MAX))
    d2 = delta - d1
    if not IMM_SIGNED_MIN <= d2 <= IMM_SIGNED_MAX:
        raise AsmError(pos, "E028",
                       f"la target is {delta:#x} bytes away, beyond the "
                       f"position-independent LAP+ADD range - use la.abs")
    w128 = E.FAMILIES["ALU"]["widths"].index(128)
    return [asm.build(lap_val, stmt.pred, dst=dst,
                      imm=asm.imm_signed(d1, pos)),
            asm.build(add_val + 1, stmt.pred, dst=dst, src1=dst,
                      width=w128, imm=asm.imm_signed(d2, pos))]


def alu_reg_word(asm, name, stmt, dst, src1, src2, width_bits=128):
    opval, fam, _ = E.OPCODES[name]
    wc = E.FAMILIES[fam]["widths"].index(width_bits)
    return asm.build(opval, stmt.pred, dst=dst, src1=src1, src2=src2,
                     width=wc)


def pseudo_mov(asm, stmt):
    if stmt.suffix is not None:
        raise AsmError(stmt.pos, "E015", "mov takes no width suffix")
    asm.nops(stmt, 2)
    dst = asm.need_reg(stmt.operands[0], stmt.pos, "destination")
    src = asm.need_reg(stmt.operands[1], stmt.pos, "source")
    return [alu_reg_word(asm, "OR", stmt, dst, src, ZERO_REG)]


def pseudo_nop(asm, stmt):
    if stmt.suffix is not None:
        raise AsmError(stmt.pos, "E015", "nop takes no width suffix")
    asm.nops(stmt, 0)
    return [alu_reg_word(asm, "OR", stmt, ZERO_REG, ZERO_REG, ZERO_REG)]


def _alu_width(asm, stmt, base):
    """Width code for not/neg width pass-through (asm.md 6.4)."""
    opval, fam, _ = E.OPCODES[base]
    saved = stmt.mnem
    stmt.mnem = base.lower()
    try:
        return opval, asm.width_code(stmt, fam)
    finally:
        stmt.mnem = saved


def pseudo_not(asm, stmt):
    asm.nops(stmt, 2)
    dst = asm.need_reg(stmt.operands[0], stmt.pos, "destination")
    src = asm.need_reg(stmt.operands[1], stmt.pos, "source")
    opval, wc = _alu_width(asm, stmt, "XOR")
    return [asm.build(opval + 1, stmt.pred, dst=dst, src1=src, width=wc,
                      imm=asm.imm_signed(-1, stmt.pos))]


def pseudo_neg(asm, stmt):
    asm.nops(stmt, 2)
    dst = asm.need_reg(stmt.operands[0], stmt.pos, "destination")
    src = asm.need_reg(stmt.operands[1], stmt.pos, "source")
    opval, wc = _alu_width(asm, stmt, "SUB")
    return [asm.build(opval, stmt.pred, dst=dst, src1=ZERO_REG, src2=src,
                      width=wc)]


def pseudo_ret(asm, stmt):
    if stmt.suffix is not None:
        raise AsmError(stmt.pos, "E015", "ret takes no width suffix")
    asm.nops(stmt, 0)
    opval, _, _ = E.OPCODES["JALR"]
    return [asm.build(opval, stmt.pred, dst=ZERO_REG, src1=RA_REG, imm=0)]


def pseudo_sub(asm, stmt):
    """sub rd, imm, rs — reverse-subtract form; legal only for imm = 0
    (asm.md 6.4), anything else is E036."""
    pos = stmt.pos
    if len(stmt.operands) == 3 and \
            parse_reg(stmt.operands[1]) is None and \
            parse_reg(stmt.operands[2]) is not None:
        v = sv(asm.eval_val(stmt.operands[1], pos))
        if v != 0:
            raise AsmError(pos, "E036",
                           "sub rd, imm, rs has no one-instruction "
                           "expansion for imm != 0 - use li + sub, or "
                           "neg + add")
        dst = asm.need_reg(stmt.operands[0], pos, "destination")
        src = asm.need_reg(stmt.operands[2], pos, "source")
        opval, wc = _alu_width(asm, stmt, "SUB")
        return [asm.build(opval, stmt.pred, dst=dst, src1=ZERO_REG,
                          src2=src, width=wc)]
    del PSEUDOS["sub"]                       # ordinary sub
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


def usage_exit(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(2)                      # usage / I-O errors: exit 2 (asm.md 1)


def main(argv):
    out = None
    inputs = []
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "-o":
            if i + 1 >= len(argv):
                usage_exit("-o needs an argument")
            out = argv[i + 1]
            i += 2
            continue
        if a.startswith("-"):
            usage_exit(f"unknown option {a}\n"
                       f"usage: sasm [-o OUT.img] IN1.s [IN2.s ...]")
        inputs.append(a)
        i += 1
    if not inputs:
        usage_exit("usage: sasm [-o OUT.img] IN1.s [IN2.s ...]")
    if out is None:
        out = os.path.splitext(inputs[0])[0] + ".img"
    out_sym = (out[:-4] if out.endswith(".img") else out) + ".sym"

    def remove_outputs():
        """ASM-12: on any assembly error no output file exists afterward,
        even if one existed before the run."""
        for p in (out, out_sym):
            try:
                os.unlink(p)
            except OSError:
                pass

    try:
        assemble(inputs, out, out_sym)
    except AsmError as e:
        remove_outputs()
        print(str(e), file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        remove_outputs()
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv)
