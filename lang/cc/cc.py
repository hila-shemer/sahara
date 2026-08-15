#!/usr/bin/env python3
# cc.py - the CC-M1 compiler. One .c translation unit in, one SABI-v0
# conformant .s out; lang/cc/cc-m1.md is the contract this file
# implements, asm/asm.py assembles the output (the unit goes LAST on
# the assembler command line - it owns the section seams).
#
# Deliberately no optimizer: locals are memory-resident, expressions
# evaluate on a temp stack over r8-r15 with automatic spill, and the
# only folding is literal-on-literal (cc-m1.md 5.5). Determinism is a
# contract: no unordered iteration reaches the emitter, label counters
# are per-function and source-order derived, the header comment
# carries the input basename only.

import sys
import os
import argparse

MASK128 = (1 << 128) - 1


def to_signed(pattern):
    """128-bit canonical image -> the signed value li emits (minimal chain)."""
    return pattern - (1 << 128) if pattern >> 127 else pattern


def sext(value, bits):
    """Canonical image of a bits-wide result (ISA 3.4): sign-extend from
    bit bits-1, signed and unsigned alike."""
    value &= (1 << bits) - 1
    if value >> (bits - 1):
        value -= 1 << bits
    return value & MASK128


# --------------------------------------------------------------- errors

class Cc(Exception):
    def __init__(self, line, msg):
        super().__init__(msg)
        self.line = line
        self.msg = msg


# ---------------------------------------------------- reserved names
# asm.md 2.3, dot-free subset: C identifiers cannot contain '.', so the
# suffixed forms (add.32, la.abs, ...) can never collide.

def build_reserved():
    s = set()
    s.update(f"r{i}" for i in range(32))
    s.update(("sp", "ra", "k0", "zero"))
    s.update(f"p{i}" for i in range(8))
    s.update(("status", "epc0", "cause0", "baddr0", "vbase", "dfbase",
              "ptbase", "asid", "cycle", "timecmp", "scratch0",
              "scratch1", "epc1", "cause1", "baddr1", "fcsr"))
    s.update(("add", "sub", "and", "or", "xor", "shl", "shr", "sar",
              "mul", "mulh", "mulhu", "madd", "udiv", "sdiv", "urem",
              "srem", "cmpeq", "cmplt", "cmpltu", "cmple", "cmpleu",
              "lds", "ldz", "ld128", "st", "st128", "cas", "amoadd",
              "amoand", "amoor", "amoxor", "amoswap", "amomin",
              "amomax", "amominu", "amomaxu", "b", "jal", "jalr",
              "ldi", "shori", "lap", "prd", "pwr", "mfsr", "mtsr",
              "syscall", "iret", "invtp", "ifence", "wfi", "halt",
              "fadd", "fsub", "fmul", "fdiv", "fsqrt", "fmadd", "fmin",
              "fmax", "fcmpeq", "fcmplt", "fcmple", "fcvtfi",
              "fcvtfiu", "fcvtif", "fcvtuif", "fcvtff"))
    s.update(("li", "la", "mov", "nop", "not", "neg", "ret"))
    s.update(("sxt", "zxt", "f32", "f64", "i32", "i64", "i128"))
    return s


RESERVED = build_reserved()


# ----------------------------------------------------------------- lexer

KEYWORDS = {"u8", "i8", "u16", "i16", "u32", "i32", "i64", "u64",
            "i128", "u128", "void", "struct",
            "extern", "if", "else", "while", "break", "continue",
            "return", "sizeof",
            "switch", "case", "default", "for", "do", "goto"}
PUNCT2 = ("==", "!=", "<=", ">=", "->", "<<", ">>", "&&", "||")
PUNCT1 = "()[]{};,.=<>+-*/%&|^!:?"

ESCAPES = {"n": 0x0A, "t": 0x09, "r": 0x0D, "b": 0x08, "f": 0x0C,
           "0": 0x00, "\\": 0x5C, '"': 0x22, "'": 0x27}


def lex(src):
    toks = []
    i, line = 0, 1
    n = len(src)

    def esc(j):
        # j points at the char after '\'; returns (byte, next_index)
        if j >= n:
            raise Cc(line, "unterminated escape")
        c = src[j]
        if c in ESCAPES:
            return ESCAPES[c], j + 1
        if c == "x":
            h = src[j + 1:j + 3]
            if len(h) == 2 and all(x in "0123456789abcdefABCDEF" for x in h):
                return int(h, 16), j + 3
            raise Cc(line, "\\x needs exactly two hex digits")
        raise Cc(line, f"unknown escape '\\{c}'")

    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if c in " \t\r":
            i += 1
            continue
        if src.startswith("//", i):
            while i < n and src[i] != "\n":
                i += 1
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            if j < 0:
                raise Cc(line, "unterminated /* comment")
            line += src.count("\n", i, j)
            i = j + 2
            continue
        if c.isalpha() or c == "_":
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            w = src[i:j]
            toks.append(("kw" if w in KEYWORDS else "id", w, line))
            i = j
            continue
        if c.isdigit():
            j = i
            while j < n and src[j].isalnum():
                j += 1
            text = src[i:j]
            try:
                v = int(text, 16) if text[:2].lower() == "0x" else int(text, 10)
            except ValueError:
                raise Cc(line, f"bad integer literal '{text}'")
            if v >= 1 << 128:
                raise Cc(line, f"integer literal does not fit 128 bits")
            toks.append(("num", v, line))
            i = j
            continue
        if c == "'":
            j = i + 1
            if j < n and src[j] == "\\":
                v, j = esc(j + 1)
            elif j < n and src[j] not in "'\n":
                v, j = ord(src[j]), j + 1
            else:
                raise Cc(line, "bad character literal")
            if j >= n or src[j] != "'":
                raise Cc(line, "bad character literal")
            toks.append(("num", v, line))
            i = j + 1
            continue
        if c == '"':
            data = bytearray()
            j = i + 1
            while True:
                if j >= n or src[j] == "\n":
                    raise Cc(line, "unterminated string literal")
                if src[j] == '"':
                    break
                if src[j] == "\\":
                    v, j = esc(j + 1)
                    data.append(v)
                else:
                    data.append(ord(src[j]) & 0xFF)
                    j += 1
            toks.append(("str", bytes(data), line))
            i = j + 1
            continue
        two = src[i:i + 2]
        if two in PUNCT2:
            toks.append(("p", two, line))
            i += 2
            continue
        if c in PUNCT1:
            toks.append(("p", c, line))
            i += 1
            continue
        raise Cc(line, f"stray character {c!r}")
    toks.append(("eof", "", line))
    return toks


# ----------------------------------------------------------------- types
# Scalars are ('int', bits, signed); also ('void',), ('ptr', T),
# ('arr', T, n), ('struct', name). The (size, signedness) pair is the
# whole scalar model - m2's i8..u32 are new rows, not new machinery.

TYPE_KW = {"u8": ("int", 8, False), "i8": ("int", 8, True),
           "u16": ("int", 16, False), "i16": ("int", 16, True),
           "u32": ("int", 32, False), "i32": ("int", 32, True),
           "i64": ("int", 64, True), "u64": ("int", 64, False),
           "i128": ("int", 128, True), "u128": ("int", 128, False),
           "void": ("void",)}

T_I64 = ("int", 64, True)
T_U64 = ("int", 64, False)
T_I128 = ("int", 128, True)
T_U128 = ("int", 128, False)


def is_int(t):
    return t[0] == "int"


def is_ptr(t):
    return t[0] == "ptr"


def is_scalar(t):
    return t[0] in ("int", "ptr")


def type_str(t):
    if t[0] == "int":
        return ("i" if t[2] else "u") + str(t[1])
    if t[0] == "void":
        return "void"
    if t[0] == "ptr":
        if t[1][0] == "func":
            f = t[1]
            args = ", ".join(type_str(p) for p in f[2]) or "void"
            return f"{type_str(f[1])} (*)({args})"
        return type_str(t[1]) + "*"
    if t[0] == "arr":
        return f"{type_str(t[1])}[{t[2]}]"
    if t[0] == "func":
        args = ", ".join(type_str(p) for p in t[2]) or "void"
        return f"{type_str(t[1])} ({args})"
    return "struct " + t[1]


class Unit:
    """One translation unit: struct/function/global tables + the AST."""

    def __init__(self):
        self.structs = {}    # name -> (fields:[(name, type, off)], size, align)
        self.funcs = {}      # name -> (ret, params, body|None, line)
        self.globals = {}    # name -> dict(type, init, extern, line)
        self.gorder = []     # global names, declaration order
        self.forder = []     # function-definition names, source order
        self.strings = {}    # bytes -> label, first-use order

    def t_align(self, t):
        if t[0] == "int":
            return t[1] // 8
        if t[0] == "ptr":
            return 16
        if t[0] == "arr":
            return self.t_align(t[1])
        if t[0] == "struct":
            return self.structs[t[1]][2]
        raise AssertionError(t)

    def t_size(self, t):
        if t[0] == "int":
            return t[1] // 8
        if t[0] == "ptr":
            return 16
        if t[0] == "arr":
            return self.t_size(t[1]) * t[2]
        if t[0] == "struct":
            return self.structs[t[1]][1]
        raise AssertionError(t)

    def field(self, sname, fname, line):
        for fn, ft, off in self.structs[sname][0]:
            if fn == fname:
                return ft, off
        raise Cc(line, f"struct {sname} has no member '{fname}'")

    def intern_string(self, data):
        if data not in self.strings:
            self.strings[data] = f"cc.str.{len(self.strings)}"
        return self.strings[data]


# ---------------------------------------------------------------- parser

class Parser:
    def __init__(self, toks, unit):
        self.t = toks
        self.i = 0
        self.u = unit

    def peek(self, ahead=0):
        return self.t[min(self.i + ahead, len(self.t) - 1)]

    def next(self):
        tk = self.t[self.i]
        self.i += 1
        return tk

    def line(self):
        return self.peek()[2]

    def accept(self, kind, val=None):
        k, v, _ = self.peek()
        if k == kind and (val is None or v == val):
            self.i += 1
            return v if val is None else True
        return None

    def expect(self, kind, val=None, what=None):
        k, v, line = self.peek()
        r = self.accept(kind, val)
        if r is None:
            want = what or (f"'{val}'" if val else kind)
            got = repr(v) if v != "" else "end of file"
            raise Cc(line, f"expected {want}, got {got}")
        return r

    def at_type(self):
        k, v, _ = self.peek()
        return k == "kw" and (v in TYPE_KW or v == "struct")

    def parse_base_type(self):
        """Base type specifier only - no declarator parts."""
        line = self.line()
        if self.accept("kw", "struct"):
            name = self.expect("id", what="struct name")
            if name not in self.u.structs:
                raise Cc(line, f"struct {name} not declared")
            return ("struct", name)
        k, v, _ = self.peek()
        if not (k == "kw" and v in TYPE_KW):
            raise Cc(line, "expected a type")
        self.next()
        return TYPE_KW[v]

    # ---- declarators: the standard two-stage C parser. A declarator
    # is parsed structurally first (tokens are consumed left to right),
    # then the type is built inside-out: pointer stars consume the base,
    # postfixes wrap right to left, a parenthesized inner declarator
    # wraps last. This reproduces the m1 types for m1 syntax exactly
    # and carries multi-dim arrays and function declarators.

    def parse_declarator(self, base, abstract=False):
        """-> (type, name-or-None, fparams-or-None). fparams is the
        named parameter list when the declared entity is a function."""
        name, build, _ = self._declarator(abstract)
        t, fparams = build(base)
        return t, name, fparams

    def _declarator(self, abstract):
        line = self.line()
        stars = 0
        while self.accept("p", "*"):
            stars += 1
        name, innerb = None, None
        if self.peek()[0] == "id":
            name = self.next()[1]
        elif self.peek()[:2] == ("p", "(") and self._paren_is_declarator():
            self.next()
            name, innerb, trivial = self._declarator(abstract)
            self.expect("p", ")")
            if trivial:
                innerb = None                # (name) == name
        elif not abstract:
            raise Cc(self.line(), "expected a declarator name")
        posts = []
        while True:
            pl = self.line()
            if self.accept("p", "["):
                cnt = self.const_expr("array size")
                if cnt <= 0:
                    raise Cc(pl, "array size must be > 0")
                self.expect("p", "]")
                posts.append(("arr", cnt, pl))
            elif self.peek()[:2] == ("p", "(") and (posts or stars
                                                    or innerb is not None
                                                    or name is not None
                                                    or abstract):
                self.next()
                ptypes, pnamed = self.parse_params(pl)
                posts.append(("fn", ptypes, pnamed, pl))
            else:
                break

        def build(t):
            fparams = None
            for _ in range(stars):
                if t == ("void",):
                    raise Cc(line, "void* is not in m1 (see the roadmap)")
                t = ("ptr", t)
            for p in reversed(posts):
                if p[0] == "arr":
                    if t[0] == "func":
                        raise Cc(p[2], "array of functions (array of "
                                       "function pointers: (*a[N])(...))")
                    if t == ("void",):
                        raise Cc(p[2], "array of void")
                    t = ("arr", t, p[1])
                    fparams = None
                else:
                    if t[0] in ("arr", "func"):
                        kind = "an array" if t[0] == "arr" else "a function"
                        raise Cc(p[3], f"a function cannot return {kind}")
                    t = ("func", t, p[1])
                    fparams = p[2]
            if innerb is not None:
                t, fparams = innerb(t)
            return t, fparams

        trivial = not stars and not posts and innerb is None
        return name, build, trivial

    def _paren_is_declarator(self):
        """At '(' in declarator position: a parenthesized declarator
        starts with '*', '(' or an identifier; a parameter list starts
        with a type, 'void', or ')'."""
        k, v, _ = self.peek(1)
        if k == "kw":
            return False                     # type keyword: params
        if k == "p" and v == ")":
            return False                     # empty parameter list
        return k in ("id",) or (k == "p" and v in ("*", "("))

    def parse_params(self, line):
        """After the '(' of a function declarator.
        -> (types tuple, [(name-or-None, type, line), ...])"""
        if self.accept("p", ")"):
            return (), []
        if self.peek()[:2] == ("kw", "void") \
                and self.peek(1)[:2] == ("p", ")"):
            self.next()
            self.next()
            return (), []
        named = []
        while True:
            pl = self.line()
            base = self.parse_base_type()
            pt, pn, _ = self.parse_declarator(base, abstract=True)
            if pt == ("void",):
                raise Cc(pl, "void parameter")
            if pt[0] == "func":
                pt = ("ptr", pt)     # C: function parameter adjusts
            if not is_scalar(pt):
                raise Cc(pl, "parameters must be scalars or "
                             "pointers in m1 (structs/arrays: "
                             "pass a pointer)")
            if pn is not None and any(pn == q[0] for q in named):
                raise Cc(pl, f"duplicate parameter '{pn}'")
            named.append((pn, pt, pl))
            if self.accept("p", ")"):
                return tuple(q[1] for q in named), named
            self.expect("p", ",")

    def parse_typename(self):
        """A type-name: base type + abstract declarator (casts, sizeof)."""
        line = self.line()
        base = self.parse_base_type()
        t, name, _ = self.parse_declarator(base, abstract=True)
        if name is not None:
            raise Cc(line, f"unexpected name '{name}' in a type name")
        return t

    # ---- file scope

    def parse_unit(self):
        while self.peek()[0] != "eof":
            if (self.peek() == ("kw", "struct", self.peek()[2])
                    and self.peek(1)[0] == "id"
                    and self.peek(2)[:2] == ("p", "{")):
                self.parse_struct()
                continue
            line = self.line()
            is_extern = bool(self.accept("kw", "extern"))
            base = self.parse_base_type()
            while True:
                t, name, fparams = self.parse_declarator(base)
                if t[0] == "func":
                    if self.parse_func(t, name, fparams, is_extern, line):
                        break                # a definition ends the list
                else:
                    self.parse_global(t, name, is_extern, line)
                if self.accept("p", ";"):
                    break
                self.expect("p", ",")

    def parse_struct(self):
        line = self.line()
        self.next()                      # struct
        name = self.expect("id")
        if name in self.u.structs:
            raise Cc(line, f"struct {name} redefined")
        self.expect("p", "{")
        fields, off, maxal = [], 0, 1
        while not self.accept("p", "}"):
            fl = self.line()
            base = self.parse_base_type()
            while True:
                ft, fn, _ = self.parse_declarator(base)
                if ft == ("void",):
                    raise Cc(fl, "void member")
                if ft[0] == "func":
                    raise Cc(fl, f"member '{fn}' is a function (use a "
                                 f"function pointer)")
                if any(fn == f[0] for f in fields):
                    raise Cc(fl, f"duplicate member '{fn}'")
                al = self.u.t_align(ft)
                off = (off + al - 1) & ~(al - 1)
                fields.append((fn, ft, off))
                off += self.u.t_size(ft)
                maxal = max(maxal, al)
                if self.accept("p", ";"):
                    break
                self.expect("p", ",")
        self.expect("p", ";")
        size = (off + maxal - 1) & ~(maxal - 1)
        if not fields:
            raise Cc(line, f"struct {name} is empty")
        self.u.structs[name] = (fields, size, maxal)

    def check_label_name(self, name, line):
        if name.lower() in RESERVED:
            raise Cc(line, f"'{name}' collides with an assembler reserved "
                           f"name (asm.md 2.3) - rename it (cc-m1.md "
                           f"section 2)")

    def parse_func(self, ftype, name, fparams, is_extern, line):
        """Register a function prototype or definition. ftype is
        ('func', ret, ptypes); fparams the named parameter list.
        Returns True when a body was parsed (ends the declarator list)."""
        _, ret, ptypes = ftype
        self.check_label_name(name, line)
        if name in self.u.globals:
            raise Cc(line, f"'{name}' already declared as a variable")
        sig = (ret, ptypes)
        old = self.u.funcs.get(name)
        if old is not None:
            if (old[0], tuple(p[1] for p in old[1])) != sig:
                raise Cc(line, f"conflicting declaration of {name}()")
        if self.peek()[:2] != ("p", "{"):
            if old is None:
                params = [(p[0], p[1]) for p in fparams]
                self.u.funcs[name] = (ret, params, None, line)
            return False
        if old is not None and old[2] is not None:
            raise Cc(line, f"{name}() redefined")
        for pn, pt, pl in fparams:
            if pn is None:
                raise Cc(pl, f"parameter of {name}() needs a name in a "
                             f"definition")
        params = [(p[0], p[1]) for p in fparams]
        body = self.parse_block()
        self.u.funcs[name] = (ret, params, body, line)
        self.u.forder.append(name)
        return True

    def parse_global(self, t, name, is_extern, line):
        self.check_label_name(name, line)
        if t == ("void",):
            raise Cc(line, "void variable")
        init = None
        if self.accept("p", "="):
            if is_extern:
                raise Cc(line, "extern declaration with initializer")
            if t[0] == "arr":
                if not is_int(t[1]):
                    raise Cc(line, "only integer arrays can be "
                                   "initialized in m1")
                self.expect("p", "{")
                init = []
                while True:
                    init.append(self.const_expr("initializer"))
                    if self.accept("p", "}"):
                        break
                    self.expect("p", ",")
                    if self.accept("p", "}"):
                        break
                if len(init) > t[2]:
                    raise Cc(line, f"too many initializers ({len(init)} "
                                   f"for {t[2]} elements)")
            elif is_int(t):
                init = self.const_expr("initializer")
            else:
                raise Cc(line, "only integer scalars and arrays take "
                               "initializers in m1 (no address "
                               "initializers)")
        old = self.u.globals.get(name)
        if old is not None:
            if old["type"] != t:
                raise Cc(line, f"conflicting declaration of '{name}'")
            if not old["extern"] and not is_extern:
                raise Cc(line, f"'{name}' redefined")
            if is_extern:
                return
            old["extern"] = False
            old["init"] = init
            return
        if name in self.u.funcs:
            raise Cc(line, f"'{name}' already declared as a function")
        self.u.globals[name] = {"type": t, "init": init,
                                "extern": is_extern, "line": line}
        self.u.gorder.append(name)

    # ---- constant expressions (global inits, array sizes)

    def const_expr(self, what):
        line = self.line()
        v = const_eval(self.parse_expr(), self.u)
        if v is None:
            raise Cc(line, f"{what} must be a constant expression")
        return to_signed(v[2])

    # ---- statements

    def parse_block(self):
        self.expect("p", "{")
        stmts = []
        while not self.accept("p", "}"):
            stmts.append(self.parse_stmt())
        return ("block", stmts)

    def parse_stmt(self):
        line = self.line()
        if self.peek()[:2] == ("p", "{"):
            return self.parse_block()
        if self.at_type():
            base = self.parse_base_type()
            decls = []
            while True:
                t, name, _ = self.parse_declarator(base)
                if t == ("void",):
                    raise Cc(line, "void variable")
                if t[0] == "func":
                    raise Cc(line, "no function declarations at block "
                                   "scope (declare it at file scope)")
                init = None
                if self.accept("p", "="):
                    if not is_scalar(t):
                        raise Cc(line, "arrays and structs cannot be "
                                       "initialized in m1")
                    init = self.parse_expr()
                decls.append(("decl", line, t, name, init))
                if self.accept("p", ";"):
                    break
                self.expect("p", ",")
            return decls[0] if len(decls) == 1 else ("multi", line, decls)
        if self.accept("kw", "if"):
            self.expect("p", "(")
            cond = self.parse_expr()
            self.expect("p", ")")
            then = self.parse_stmt()
            els = self.parse_stmt() if self.accept("kw", "else") else None
            return ("if", line, cond, then, els)
        if self.accept("kw", "while"):
            self.expect("p", "(")
            cond = self.parse_expr()
            self.expect("p", ")")
            return ("while", line, cond, self.parse_stmt())
        if self.accept("kw", "for"):
            self.expect("p", "(")
            init = cond = step = None
            if self.peek()[:2] != ("p", ";"):
                init = self.parse_expr()
            self.expect("p", ";")
            if self.peek()[:2] != ("p", ";"):
                cond = self.parse_expr()
            self.expect("p", ";")
            if self.peek()[:2] != ("p", ")"):
                step = self.parse_expr()
            self.expect("p", ")")
            return ("for", line, init, cond, step, self.parse_stmt())
        if self.accept("kw", "do"):
            body = self.parse_stmt()
            self.expect("kw", "while")
            self.expect("p", "(")
            cond = self.parse_expr()
            self.expect("p", ")")
            self.expect("p", ";")
            return ("do", line, body, cond)
        if self.accept("kw", "switch"):
            self.expect("p", "(")
            e = self.parse_expr()
            self.expect("p", ")")
            return ("switch", line, e, self.parse_stmt())
        if self.accept("kw", "case"):
            v = self.parse_expr()
            self.expect("p", ":")
            return ("case", line, v, self.parse_stmt())
        if self.accept("kw", "default"):
            self.expect("p", ":")
            return ("default", line, self.parse_stmt())
        if self.accept("kw", "goto"):
            name = self.expect("id", what="a label name")
            self.expect("p", ";")
            return ("goto", line, name)
        if self.peek()[0] == "id" and self.peek(1)[:2] == ("p", ":"):
            name = self.next()[1]
            self.next()
            return ("label", line, name, self.parse_stmt())
        if self.accept("kw", "break"):
            self.expect("p", ";")
            return ("break", line)
        if self.accept("kw", "continue"):
            self.expect("p", ";")
            return ("continue", line)
        if self.accept("kw", "return"):
            e = None if self.peek()[:2] == ("p", ";") else self.parse_expr()
            self.expect("p", ";")
            return ("return", line, e)
        if self.accept("p", ";"):
            return ("empty", line)
        e = self.parse_expr()
        self.expect("p", ";")
        return ("expr", line, e)

    # ---- expressions (C precedence, cc-m1.md 5.2)

    def parse_expr(self):
        return self.parse_assign()

    def parse_assign(self):
        lhs = self.parse_or()
        if self.peek()[:2] == ("p", "="):
            line = self.line()
            self.next()
            return ("assign", line, lhs, self.parse_assign())
        return lhs

    BINLEVELS = [("||",), ("&&",), ("|",), ("^",), ("&",),
                 ("==", "!="), ("<", ">", "<=", ">="), ("<<", ">>"),
                 ("+", "-"), ("*", "/", "%")]

    def parse_or(self):
        return self.parse_bin(0)

    def parse_bin(self, lvl):
        if lvl == len(self.BINLEVELS):
            return self.parse_unary()
        e = self.parse_bin(lvl + 1)
        while True:
            k, v, line = self.peek()
            if k == "p" and v in self.BINLEVELS[lvl]:
                self.next()
                rhs = self.parse_bin(lvl + 1)
                kind = "logic" if v in ("&&", "||") else "bin"
                e = (kind, line, v, e, rhs)
            else:
                return e

    def parse_unary(self):
        k, v, line = self.peek()
        if (k, v) == ("p", "("):
            # cast?  '(' type ... ')'
            nk, nv, _ = self.peek(1)
            if nk == "kw" and (nv in TYPE_KW or nv == "struct"):
                self.next()
                t = self.parse_typename()
                self.expect("p", ")")
                if not is_scalar(t):
                    raise Cc(line, "casts are scalar-to-scalar only")
                return ("cast", line, t, self.parse_unary())
        if self.accept("p", "-"):
            return ("neg", line, self.parse_unary())
        if self.accept("p", "!"):
            return ("not", line, self.parse_unary())
        if self.accept("p", "*"):
            return ("deref", line, self.parse_unary())
        if self.accept("p", "&"):
            return ("addr", line, self.parse_unary())
        if self.accept("kw", "sizeof"):
            self.expect("p", "(")
            t = self.parse_typename()
            self.expect("p", ")")
            if not is_scalar(t) and t[0] != "struct":
                raise Cc(line, "sizeof takes a scalar, pointer, or "
                               "struct type")
            return ("num", line, self.u.t_size(t) & MASK128, T_U64)
        return self.parse_postfix()

    def parse_postfix(self):
        k, v, line = self.next()
        if k == "num":
            e = ("num", line, v & MASK128, literal_type(v))
        elif k == "str":
            e = ("strlit", line, v)
        elif k == "id":
            e = ("var", line, v)
        elif (k, v) == ("p", "("):
            e = self.parse_expr()
            self.expect("p", ")")
        else:
            got = repr(v) if v != "" else "end of file"
            raise Cc(line, f"expected an expression, got {got}")
        while True:
            line = self.line()
            if self.accept("p", "["):
                e = ("index", line, e, self.parse_expr())
                self.expect("p", "]")
            elif self.accept("p", "."):
                e = ("field", line, e, self.expect("id"), False)
            elif self.accept("p", "->"):
                e = ("field", line, e, self.expect("id"), True)
            elif self.peek()[:2] == ("p", "("):
                # call: the callee is whatever postfix expression is up
                self.next()
                args = []
                if not self.accept("p", ")"):
                    while True:
                        args.append(self.parse_expr())
                        if self.accept("p", ")"):
                            break
                        self.expect("p", ",")
                e = ("call", line, e, args)
            else:
                return e


def literal_type(v):
    """cc-m1.md 5.4: first of i64, u64, i128, u128 that holds the value."""
    if v < 1 << 63:
        return T_I64
    if v < 1 << 64:
        return T_U64
    if v < 1 << 127:
        return T_I128
    return T_U128


# ------------------------------------------------------- constant folding
# cc-m1.md 5.5: literal-on-literal only, never / or %, exact machine
# semantics (wrap at width, shift counts mod width).

def common_type(a, b):
    """Balance two promoted integer types: larger size wins; at equal
    size, unsigned wins (cc-m1.md 5.1)."""
    if a[1] != b[1]:
        return a if a[1] > b[1] else b
    return a if not a[2] else b


def promote(t):
    """Sub-32 types promote to their 64-bit signedness twin (the ALU
    has no 8/16-bit form, ISA 3.4); 32-bit types are first-class at
    width 32. The u8 row is frozen m1 surface; the new rows follow it."""
    if t[0] == "int" and t[1] < 32:
        return ("int", 64, t[2])
    return t


FOLDABLE = ("+", "-", "*", "&", "|", "^", "<<", ">>")


def fold(e, unit):
    op = e[0]
    if op in ("num", "strlit", "var", "call"):
        if op == "call":
            e = ("call", e[1], fold(e[2], unit),
                 [fold(a, unit) for a in e[3]])
        return e
    parts = [fold(x, unit) if isinstance(x, tuple) else x for x in e]
    e = tuple(parts)
    if e[0] == "neg" and e[2][0] == "num":
        _, line, pat, t = e[2]
        t = promote(t)
        return ("num", line, sext(-to_val(pat, t), t[1]), t)
    if e[0] == "bin" and e[2] in FOLDABLE \
            and e[3][0] == "num" and e[4][0] == "num":
        v = fold_bin(e[2], e[3], e[4])
        if v is not None:
            return v
    return e


def to_val(pattern, t):
    """Interpret a canonical 128-bit image as t's mathematical value."""
    v = pattern & ((1 << t[1]) - 1)
    if t[2] and v >> (t[1] - 1):
        v -= 1 << t[1]
    return v


def fold_bin(op, l, r):
    lt, rt = promote(l[3]), promote(r[3])
    if op in ("<<", ">>"):
        t = lt
        a = to_val(l[2], t)
        sh = to_val(r[2], rt) % t[1]
        if op == "<<":
            v = a << sh
        elif t[2]:
            v = a >> sh                      # arithmetic
        else:
            v = (a & ((1 << t[1]) - 1)) >> sh  # logical
        return ("num", l[1], sext(v, t[1]), t)
    t = common_type(lt, rt)
    a, b = to_val(l[2], t), to_val(r[2], t)
    v = {"+": a + b, "-": a - b, "*": a * b, "&": a & b,
         "|": a | b, "^": a ^ b}[op]
    return ("num", l[1], sext(v, t[1]), t)


# ------------------------------------------------- constant expressions
# (M2) The C89 constant-expression grammar for case labels, array
# sizes, enum values, and global initializers: comparisons, && || !,
# ?: , ~, casts among integer types - and / % ARE evaluated here, with
# the ISA's division semantics, because .space and case labels need
# values. At RUNTIME / % are still never folded (the m1 rule, 5.5):
# fold() above is the optimizer, this is front-end necessity.


def ce_div(a, b, signed, bits):
    """ISA 5.1 division: /0 -> all-ones at width; MIN/-1 -> MIN; else
    truncation toward zero."""
    if b == 0:
        return -1 if signed else (1 << bits) - 1
    if signed and a == -(1 << (bits - 1)) and b == -1:
        return a
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q


def ce_rem(a, b, signed, bits):
    if b == 0:
        return a
    if signed and a == -(1 << (bits - 1)) and b == -1:
        return 0
    return a - ce_div(a, b, signed, bits) * b


def const_eval(e, unit):
    """-> ("num", line, image128, type) or None if not constant."""
    op = e[0]
    if op == "num":
        return e
    if op == "cast":
        t = e[2]
        if not is_int(t):
            return None
        v = const_eval(e[3], unit)
        if v is None:
            return None
        return ("num", e[1], sext(to_val(v[2], v[3]), t[1]), t)
    if op in ("neg", "bitnot", "uplus"):
        v = const_eval(e[2], unit)
        if v is None or not is_int(v[3]):
            return None
        t = promote(v[3])
        val = to_val(v[2], t)
        if op == "neg":
            val = -val
        elif op == "bitnot":
            val = ~val
        return ("num", e[1], sext(val, t[1]), t)
    if op == "not":
        v = const_eval(e[2], unit)
        if v is None or not is_int(v[3]):
            return None
        return ("num", e[1], 0 if to_val(v[2], v[3]) else 1, T_I64)
    if op == "logic":
        l = const_eval(e[3], unit)
        r = const_eval(e[4], unit)
        if l is None or r is None:
            return None
        lv = to_val(l[2], l[3]) != 0
        rv = to_val(r[2], r[3]) != 0
        res = (lv and rv) if e[2] == "&&" else (lv or rv)
        return ("num", e[1], 1 if res else 0, T_I64)
    if op == "ternary":
        c = const_eval(e[2], unit)
        a = const_eval(e[3], unit)
        b = const_eval(e[4], unit)
        if c is None or a is None or b is None:
            return None
        if not (is_int(a[3]) and is_int(b[3])):
            return None
        pick = a if to_val(c[2], c[3]) else b
        t = common_type(promote(a[3]), promote(b[3]))
        return ("num", e[1], sext(to_val(pick[2], pick[3]), t[1]), t)
    if op == "bin":
        l = const_eval(e[3], unit)
        r = const_eval(e[4], unit)
        if l is None or r is None:
            return None
        if not (is_int(l[3]) and is_int(r[3])):
            return None
        lt, rt = promote(l[3]), promote(r[3])
        o = e[2]
        if o in ("<<", ">>"):
            t = lt
            sh = r[2] & (t[1] - 1)          # count mod width (low bits)
            a = to_val(l[2], t)
            if o == "<<":
                return ("num", e[1], sext(a << sh, t[1]), t)
            if t[2]:
                return ("num", e[1], sext(a >> sh, t[1]), t)
            return ("num", e[1],
                    sext((a & ((1 << t[1]) - 1)) >> sh, t[1]), t)
        t = common_type(lt, rt)
        a, b = to_val(l[2], t), to_val(r[2], t)
        if o in ("<", "<=", ">", ">=", "==", "!="):
            res = {"<": a < b, "<=": a <= b, ">": a > b,
                   ">=": a >= b, "==": a == b, "!=": a != b}[o]
            return ("num", e[1], 1 if res else 0, T_I64)
        if o == "/":
            v = ce_div(a, b, t[2], t[1])
        elif o == "%":
            v = ce_rem(a, b, t[2], t[1])
        else:
            v = {"+": a + b, "-": a - b, "*": a * b, "&": a & b,
                 "|": a | b, "^": a ^ b}[o]
        return ("num", e[1], sext(v, t[1]), t)
    return None


# ---------------------------------------------------------------- codegen

# Loads keyed by (bits, signed): the extension IS the promoted image -
# lds for signed (and for 32-bit unsigned too: canonical-32 is the
# sign-extension from bit 31, the u64/lds.64 argument one octave down),
# ldz for u8/u16 (bit 15 < 63, so zero-extension is canonical).
LOADS = {(8, True): "lds.8", (8, False): "ldz.8",
         (16, True): "lds.16", (16, False): "ldz.16",
         (32, True): "lds.32", (32, False): "lds.32",
         (64, True): "lds.64", (64, False): "lds.64"}
STORES = {8: "st.8", 16: "st.16", 32: "st.32", 64: "st.64"}
ALU = {"+": "add", "-": "sub", "*": "mul", "&": "and", "|": "or",
       "^": "xor", "<<": "shl"}


def suffix(t):
    """ALU/compare width suffix for a scalar type (width discipline)."""
    if is_ptr(t):
        return ""
    bits = promote(t)[1]
    if bits == 32:
        return ".32"
    return ".64" if bits == 64 else ""


class Func:
    def __init__(self, unit, name):
        self.u = unit
        self.name = name
        self.ret, self.params, self.body, self.dline = unit.funcs[name]
        self.lines = []          # body text; %%FRAME%% patched at render
        self.depth = 0
        self.peak = 0
        self.nlabel = 0
        self.scopes = []
        self.loopstack = []      # ("loop", cont, brk) | ("switch", None, brk)
        self.golabels = {}       # goto label name -> asm label
        self.gotos = []          # (name, line) for end-of-function check
        self.case_labels = {}    # id(case/default node) -> asm label
        self.slot_of = {}        # id(decl node) -> frame offset
        self.calls = False
        self.maxargs = 0
        # params first (one 16-byte home each), then decls in source
        # order - prescan continues the running offset.
        self.locals_size = 16 * len(self.params)
        self.prescan(self.body)
        self.out_size = 16 * max(0, self.maxargs - 8)
        self.locals_base = self.out_size
        self.spill_base = self.out_size + self.locals_size

    # ---- prescan: every decl gets a frame slot; calls/maxargs found.
    # Slot order = source order, so offsets are deterministic.

    def prescan(self, node):
        stack = [node]
        order = []
        while stack:
            n = stack.pop()
            if not isinstance(n, tuple):
                if isinstance(n, list):
                    stack.extend(reversed(n))
                continue
            order.append(n)
            stack.extend(reversed([x for x in n
                                   if isinstance(x, (tuple, list))]))
        for n in order:
            if n[0] == "decl":
                size = self.u.t_size(n[2])
                size = (size + 15) & ~15
                self.slot_of[id(n)] = self.locals_size
                self.locals_size += size
            elif n[0] == "call":
                self.calls = True
                self.maxargs = max(self.maxargs, len(n[3]))

    # ---- emit helpers

    def emit(self, s):
        self.lines.append("        " + s)

    def emit_label(self, l):
        self.lines.append(l + ":")

    def label(self):
        self.nlabel += 1
        return f"{self.name}.L{self.nlabel}"

    def home(self, slot):
        return self.spill_base + 16 * slot

    def reg(self, slot):
        return f"r{8 + slot % 8}"

    def push(self):
        d = self.depth
        if d >= 8:
            self.emit(f"st128 [sp + {self.home(d - 8)}], {self.reg(d)}")
        self.depth += 1
        self.peak = max(self.peak, self.depth)
        return self.reg(d)

    def pop(self):
        self.depth -= 1
        d = self.depth
        if d >= 8:
            self.emit(f"ld128 {self.reg(d)}, [sp + {self.home(d - 8)}]")

    def top(self):
        return self.reg(self.depth - 1)

    # ---- scoping

    def lookup(self, name, line):
        for sc in reversed(self.scopes):
            if name in sc:
                return sc[name]
        g = self.u.globals.get(name)
        if g is not None:
            return ("global", name, g["type"])
        f = self.u.funcs.get(name)
        if f is not None:
            return ("func", name, ("func", f[0], tuple(p[1]
                                                       for p in f[1])))
        raise Cc(line, f"'{name}' is not declared")

    # ---- conversions (cc-m1.md section 4); operate on register r

    def convert(self, r, src, dst, line):
        # src is always a promoted (or pointer/128) type: 32/64/128
        # bits. dst may be any scalar type; a sub-width dst leaves the
        # promoted image of the narrowed value in r (cc-m1.md 4).
        if src == dst:
            return
        if is_ptr(src) and is_ptr(dst):
            return
        sbits = src[1] if is_int(src) else 128
        if is_int(dst) and dst[1] < 32:
            if dst == ("int", 8, False):
                self.emit(f"and.64 {r}, {r}, 0xff")   # frozen m1 row
            elif dst[2]:
                self.emit(f"or.64 {r}, zero, {r} sxt {dst[1]}")
            else:
                self.emit(f"or.64 {r}, zero, {r} zxt 16")
            return
        dbits = dst[1] if is_int(dst) else 128
        if dbits == 32:
            if sbits != 32:
                self.emit(f"or.32 {r}, {r}, 0")   # re-canonicalize at 32
            return                # i32<->u32: same canonical image
        if dbits == 64:
            if sbits == 32:
                if not src[2]:    # u32: canonical-32 image reads negative
                    self.emit(f"or.64 {r}, zero, {r} zxt 32")
                return            # i32: the image already is the sext
            if sbits != 64:
                self.emit(f"or.64 {r}, {r}, 0")   # 128 -> 64 truncate
            return
        # dbits == 128 (or pointer)
        if sbits == 128:
            return
        if sbits == 32:
            if not src[2]:
                self.emit(f"or.64 {r}, zero, {r} zxt 32")
            return                # i32 image is the correct 128-bit value
        if is_int(src) and src == T_U64:
            self.emit(f"shl {r}, {r}, 64")   # zxt mod caps at 63:
            self.emit(f"shr {r}, {r}, 64")   # the pinned pair lowering
            return
        return                                # i64 image is the sext

    def implicit(self, r, src, dst, line, what):
        if src == dst or (is_int(src) and is_int(dst)):
            self.convert(r, promote(src) if is_int(src) else src, dst, line)
            return
        raise Cc(line, f"{what}: cannot convert {type_str(src)} to "
                       f"{type_str(dst)} implicitly (cast needed?)")

    # ---- lvalues: push the address, return the object type

    def lvalue(self, e):
        op = e[0]
        if op == "var":
            kind = self.lookup(e[2], e[1])
            r = self.push()
            if kind[0] == "local":
                self.emit(f"add {r}, sp, {kind[1]}")
                return kind[2]
            self.emit(f"la {r}, {kind[1]}")
            return kind[2]
        if op == "deref":
            t = self.rvalue(e[2])
            if not is_ptr(t):
                raise Cc(e[1], f"cannot dereference {type_str(t)}")
            return t[1]
        if op == "index":
            bt = self.rvalue(e[2])
            if not is_ptr(bt):
                raise Cc(e[1], f"cannot index {type_str(bt)}")
            it = self.rvalue(e[3])
            if not is_int(it):
                raise Cc(e[1], "index must be an integer")
            self.index_to_128(self.top(), it)
            self.scale_index(bt[1])
            rl, rr = self.reg(self.depth - 2), self.top()
            self.emit(f"add {rl}, {rl}, {rr}")
            self.pop()
            return bt[1]
        if op == "field":
            _, line, base, fname, arrow = e
            if arrow:
                bt = self.rvalue(base)
                if not (is_ptr(bt) and bt[1][0] == "struct"):
                    raise Cc(line, f"-> needs a struct pointer, got "
                                   f"{type_str(bt)}")
                st = bt[1]
            else:
                st = self.lvalue(base)
                if st[0] != "struct":
                    raise Cc(line, f". needs a struct, got {type_str(st)}")
            ft, off = self.u.field(st[1], fname, line)
            if off:
                self.emit(f"add {self.top()}, {self.top()}, {off}")
            return ft
        raise Cc(e[1], "not an lvalue")

    def index_to_128(self, r, t):
        """Pointer arithmetic runs at width 128: an unsigned offset
        must be zero-extended from its own width first (its canonical
        image is the sign-extension, cc-m1.md section 4). i32/i64
        indexes need nothing - the canonical image IS the value."""
        if t == T_U64:
            self.emit(f"shl {r}, {r}, 64")
            self.emit(f"shr {r}, {r}, 64")
        elif t == ("int", 32, False):
            self.emit(f"or.64 {r}, zero, {r} zxt 32")

    def scale_index(self, elem):
        """Top of stack: index value. Scale by sizeof(elem), width 128."""
        size = self.u.t_size(elem)
        r = self.top()
        if size == 1:
            return
        if size & (size - 1) == 0:
            self.emit(f"shl {r}, {r}, {size.bit_length() - 1}")
        else:
            self.emit(f"mul {r}, {r}, {size}")

    # ---- rvalues: push one slot with the value, return its type

    def rvalue(self, e):
        op = e[0]
        if op == "num":
            r = self.push()
            self.emit(f"li {r}, {to_signed(e[2])}")
            return promote(e[3])
        if op == "strlit":
            label = self.u.intern_string(e[2])
            r = self.push()
            self.emit(f"la {r}, {label}")
            return ("ptr", ("int", 8, False))
        if op == "var":
            kind = self.lookup(e[2], e[1])
            t = kind[2]
            if kind[0] == "local" and is_scalar(t):
                r = self.push()
                bits = t[1] if is_int(t) else 128
                if bits == 128:
                    self.emit(f"ld128 {r}, [sp + {kind[1]}]")
                else:
                    self.emit(f"{LOADS[(bits, t[2])]} {r}, "
                              f"[sp + {kind[1]}]")
                return promote(t)
        if op in ("var", "deref", "index", "field"):
            t = self.lvalue(e)
            r = self.top()
            if t[0] == "arr":
                return ("ptr", t[1])          # decay: address already up
            if t[0] == "func":
                return ("ptr", t)             # designator decay (M2)
            if t[0] == "struct":
                raise Cc(e[1], "struct values are not usable directly "
                               "in m1 (no struct assignment/copy)")
            self.load(r, t)
            return promote(t)
        if op == "addr":
            t = self.lvalue(e[2])
            if t[0] == "arr":
                raise Cc(e[1], "&array is not in m1 - the array itself "
                               "already decays to a pointer")
            return ("ptr", t)
        if op == "neg":
            t = self.rvalue(e[2])
            if not is_int(t):
                raise Cc(e[1], f"unary - needs an integer, got {type_str(t)}")
            r = self.top()
            self.emit(f"sub{suffix(t)} {r}, zero, {r}")
            return t
        if op == "not":
            t = self.rvalue(e[2])
            if not is_scalar(t):
                raise Cc(e[1], "! needs a scalar")
            r = self.top()
            self.emit(f"cmpeq{suffix(t)} p1, {r}, 0")
            self.emit(f"li {r}, 1")
            self.emit(f"(!p1) li {r}, 0")
            return T_I64
        if op == "cast":
            t = self.rvalue(e[3])
            src = t if is_ptr(t) else promote(t)
            dst = e[2]
            self.convert(self.top(), src, dst, e[1])
            return promote(dst) if is_int(dst) else dst
        if op == "bin":
            return self.gen_bin(e)
        if op == "logic":
            return self.gen_logic(e)
        if op == "assign":
            return self.gen_assign(e)
        if op == "call":
            return self.gen_call(e)
        raise AssertionError(op)

    def load(self, r, t):
        bits = t[1] if is_int(t) else 128
        if bits == 128:
            self.emit(f"ld128 {r}, [{r} + 0]")
        else:
            self.emit(f"{LOADS[(bits, t[2])]} {r}, [{r} + 0]")

    def store_to(self, addr_reg, val_reg, t):
        bits = t[1] if is_int(t) else 128
        if bits == 128:
            self.emit(f"st128 [{addr_reg} + 0], {val_reg}")
        else:
            self.emit(f"{STORES[bits]} [{addr_reg} + 0], {val_reg}")

    CMP = {"==": ("cmpeq", False, False), "!=": ("cmpeq", True, False),
           "<": ("cmplt", False, False), ">=": ("cmplt", True, False),
           "<=": ("cmple", False, False), ">": ("cmple", True, True)}
    # (mnemonic, invert, swap): '>' is cmple inverted-and-swapped-free?
    # No - see gen_cmp: a > b  ==  !(a <= b); a >= b  ==  !(a < b).

    def gen_bin(self, e):
        _, line, opname, l, r = e
        if opname in self.CMP:
            return self.gen_cmp(e)
        lt = self.rvalue(l)
        rt = self.rvalue(r)
        rl, rr = self.reg(self.depth - 2), self.top()

        # pointer arithmetic (cc-m1.md 5.3)
        if opname in ("+", "-") and (is_ptr(lt) or is_ptr(rt)):
            if is_ptr(lt) and is_ptr(rt):
                if opname != "-" or lt != rt:
                    raise Cc(line, "pointer +/- pointer: only p - q of "
                                   "the same type")
                size = self.u.t_size(lt[1])
                self.emit(f"sub {rl}, {rl}, {rr}")
                if size > 1:
                    self.emit(f"li {rr}, {size}")
                    self.emit(f"sdiv {rl}, {rl}, {rr}")
                self.pop()
                return T_I128
            if is_ptr(rt):
                # n + p: the integer sits in rl, the pointer in rr.
                if opname == "-":
                    raise Cc(line, "integer - pointer is meaningless")
                if not is_int(lt):
                    raise Cc(line, "pointer arithmetic needs an integer")
                self.index_to_128(rl, lt)
                size = self.u.t_size(rt[1])
                if size > 1:
                    if size & (size - 1) == 0:
                        self.emit(f"shl {rl}, {rl}, {size.bit_length() - 1}")
                    else:
                        self.emit(f"mul {rl}, {rl}, {size}")
                self.emit(f"add {rl}, {rl}, {rr}")
                self.pop()
                return rt
            if not is_int(rt):
                raise Cc(line, "pointer arithmetic needs an integer")
            self.index_to_128(rr, rt)
            size = self.u.t_size(lt[1])
            if size > 1:
                if size & (size - 1) == 0:
                    self.emit(f"{ALU[opname]} {rl}, {rl}, {rr} shl "
                              f"{size.bit_length() - 1}")
                    self.pop()
                    return lt
                self.emit(f"mul {rr}, {rr}, {size}")
            self.emit(f"{ALU[opname]} {rl}, {rl}, {rr}")
            self.pop()
            return lt

        if not (is_int(lt) and is_int(rt)):
            raise Cc(line, f"operator {opname} needs integers, got "
                           f"{type_str(lt)} and {type_str(rt)}")

        if opname in ("<<", ">>"):
            t = lt
            if opname == "<<":
                mnem = "shl"
            else:
                mnem = "sar" if t[2] else "shr"
            self.emit(f"{mnem}{suffix(t)} {rl}, {rl}, {rr}")
            self.pop()
            return t

        t = common_type(lt, rt)
        self.balance(lt, rt, t, line)
        if opname in ("/", "%"):
            table = {("/", True): "sdiv", ("/", False): "udiv",
                     ("%", True): "srem", ("%", False): "urem"}
            mnem = table[(opname, t[2])]
        else:
            mnem = ALU[opname]
        self.emit(f"{mnem}{suffix(t)} {rl}, {rl}, {rr}")
        self.pop()
        return t

    def balance(self, lt, rt, t, line):
        """Convert the two top slots (lhs below rhs) to common type t."""
        if lt != t:
            self.convert(self.reg(self.depth - 2), lt, t, line)
        if rt != t:
            self.convert(self.top(), rt, t, line)

    def gen_cmp(self, e):
        _, line, opname, l, r = e
        lt = self.rvalue(l)
        rt = self.rvalue(r)
        rl, rr = self.reg(self.depth - 2), self.top()
        if is_ptr(lt) or is_ptr(rt):
            ok = (lt == rt) \
                or (is_ptr(lt) and r[0] == "num" and r[2] == 0) \
                or (is_ptr(rt) and l[0] == "num" and l[2] == 0)
            if not ok:
                raise Cc(line, f"cannot compare {type_str(lt)} with "
                               f"{type_str(rt)}")
            t = lt if is_ptr(lt) else rt
            unsigned = True
            sfx = ""
        else:
            if not (is_int(lt) and is_int(rt)):
                raise Cc(line, "comparison needs scalars")
            t = common_type(lt, rt)
            self.balance(lt, rt, t, line)
            unsigned = not t[2]
            sfx = suffix(t)
        if opname in ("==", "!="):
            mnem, inv = "cmpeq", opname == "!="
            a, b = rl, rr
        elif opname == "<":
            mnem, inv, a, b = "cmplt", False, rl, rr
        elif opname == ">=":
            mnem, inv, a, b = "cmplt", True, rl, rr
        elif opname == "<=":
            mnem, inv, a, b = "cmple", False, rl, rr
        else:                                     # >  ==  !(a <= b)
            mnem, inv, a, b = "cmple", True, rl, rr
        if unsigned and mnem in ("cmplt", "cmple"):
            mnem += "u"
        self.emit(f"{mnem}{sfx} p1, {a}, {b}")
        self.pop()
        rl = self.top()
        self.emit(f"li {rl}, {0 if inv else 1}")
        self.emit(f"(!p1) li {rl}, {1 if inv else 0}")
        return T_I64

    def gen_logic(self, e):
        _, line, opname, l, r = e
        end = self.label()
        lt = self.rvalue(l)
        if not is_scalar(lt):
            raise Cc(line, f"{opname} needs scalar operands")
        rl = self.top()
        self.emit(f"cmpeq{suffix(lt)} p1, {rl}, 0")
        if opname == "&&":
            self.emit(f"li {rl}, 0")
            self.emit(f"(p1) b {end}")       # lhs false decides: 0
        else:
            self.emit(f"li {rl}, 1")
            self.emit(f"(!p1) b {end}")      # lhs true decides: 1
        rt = self.rvalue(r)
        if not is_scalar(rt):
            raise Cc(line, f"{opname} needs scalar operands")
        rr = self.top()
        self.emit(f"cmpeq{suffix(rt)} p1, {rr}, 0")
        self.emit(f"li {rl}, 1")
        self.emit(f"(p1) li {rl}, 0")
        self.pop()
        self.emit_label(end)
        return T_I64

    def gen_assign(self, e):
        _, line, lhs, rhs = e
        # Simple scalar variable: nothing observable in the lvalue, so
        # the direct-addressing form is semantics-preserving.
        if lhs[0] == "var":
            kind = self.lookup(lhs[2], line)
            t = kind[2]
            if is_scalar(t):
                vt = self.rvalue(rhs)
                rv = self.top()
                self.implicit(rv, vt, t, line, "assignment")
                if kind[0] == "local":
                    self.store_direct(kind[1], rv, t)
                else:
                    ra = self.push()
                    self.emit(f"la {ra}, {kind[1]}")
                    self.store_to(ra, rv, t)
                    self.pop()
                return promote(t) if is_int(t) else t
        # General: lvalue address first (left-to-right), then the value.
        t = self.lvalue(lhs)
        if not is_scalar(t):
            raise Cc(line, f"cannot assign to {type_str(t)}")
        vt = self.rvalue(rhs)
        ra, rv = self.reg(self.depth - 2), self.top()
        self.implicit(rv, vt, t, line, "assignment")
        self.store_to(ra, rv, t)
        self.emit(f"mov {ra}, {rv}")
        self.pop()
        return promote(t) if is_int(t) else t

    def store_direct(self, off, val_reg, t):
        bits = t[1] if is_int(t) else 128
        if bits == 128:
            self.emit(f"st128 [sp + {off}], {val_reg}")
        else:
            self.emit(f"{STORES[bits]} [sp + {off}], {val_reg}")

    def gen_call(self, e):
        _, line, callee, args = e
        # Direct call: a bare identifier naming a declared function,
        # not shadowed by any local - keeps the m1 jal path verbatim.
        direct = None
        if callee[0] == "var" \
                and not any(callee[2] in sc for sc in self.scopes):
            name = callee[2]
            if name in self.u.funcs:
                direct = name
            elif name not in self.u.globals:
                raise Cc(line, f"call to undeclared function '{name}'")
        base = self.depth
        if direct is not None:
            ret, params, _, _ = self.u.funcs[direct]
            ptypes = [p[1] for p in params]
            what = f"{direct}()"
            astart = base
        else:
            # Indirect: callee expression first (left-to-right rule),
            # then the arguments; the callee value rides slot `base`.
            ct = self.rvalue(callee)
            if not (is_ptr(ct) and ct[1][0] == "func"):
                raise Cc(line, f"called object is not a function or "
                               f"function pointer ({type_str(ct)})")
            _, ret, ptypes = ct[1]
            ptypes = list(ptypes)
            what = "call through a function pointer"
            astart = base + 1
        if len(args) != len(ptypes):
            raise Cc(line, f"{what} takes {len(ptypes)} arguments, "
                           f"got {len(args)}")
        for i, a in enumerate(args):
            at = self.rvalue(a)
            self.implicit(self.top(), at, ptypes[i], line,
                          f"argument {i + 1} of {what}")
        # Spill every live register slot to its home (r8-r15 are
        # caller-saved; homes double as the argument staging area).
        lo = max(0, self.depth - 8)
        for s in range(lo, self.depth):
            self.emit(f"st128 [sp + {self.home(s)}], {self.reg(s)}")
        # Stack-slot arguments (SABI/ISA 12: [sp + 0], 16 bytes each).
        for i in range(8, len(args)):
            self.emit(f"ld128 r8, [sp + {self.home(astart + i)}]")
            self.emit(f"st128 [sp + {16 * (i - 8)}], r8")
        # Register arguments.
        for i in range(min(8, len(args))):
            self.emit(f"ld128 r{i}, [sp + {self.home(astart + i)}]")
        if direct is not None:
            self.emit(f"jal {direct}")
        else:
            self.emit(f"ld128 r8, [sp + {self.home(base)}]")
            self.emit("jalr ra, r8, 0")
        # Result: slot `base`; its home already holds the pre-call
        # value of any displaced deeper slot, so no push() spill here.
        self.depth = base + 1
        self.peak = max(self.peak, self.depth)
        self.emit(f"mov {self.reg(base)}, r0")
        for s in range(max(0, self.depth - 8), base):
            self.emit(f"ld128 {self.reg(s)}, [sp + {self.home(s)}]")
        if ret == ("void",):
            return ("void",)
        return promote(ret) if is_int(ret) else ret

    # ---- conditions: set p1, return the polarity that means "true"

    def cond(self, e):
        """Emit compare(s); afterwards the condition is true iff
        p1 == returned polarity."""
        if e[0] == "bin" and e[2] in self.CMP:
            _, line, opname, l, r = e
            lt = self.rvalue(l)
            rt = self.rvalue(r)
            rl, rr = self.reg(self.depth - 2), self.top()
            if is_ptr(lt) or is_ptr(rt):
                t, unsigned, sfx = None, True, ""
            else:
                if not (is_int(lt) and is_int(rt)):
                    raise Cc(line, "comparison needs scalars")
                t = common_type(lt, rt)
                self.balance(lt, rt, t, line)
                unsigned, sfx = not t[2], suffix(t)
            table = {"==": ("cmpeq", True), "!=": ("cmpeq", False),
                     "<": ("cmplt", True), ">=": ("cmplt", False),
                     "<=": ("cmple", True), ">": ("cmple", False)}
            mnem, pol = table[opname]
            if unsigned and mnem in ("cmplt", "cmple"):
                mnem += "u"
            self.emit(f"{mnem}{sfx} p1, {rl}, {rr}")
            self.pop()
            self.pop()
            return pol
        if e[0] == "not":
            pol = self.cond(e[2])
            return not pol
        t = self.rvalue(e)
        if not is_scalar(t):
            raise Cc(e[1], "condition must be a scalar")
        self.emit(f"cmpeq{suffix(t)} p1, {self.top()}, 0")
        self.pop()
        return False          # p1 set means the condition is FALSE

    def branch_unless(self, e, target):
        """Branch to target when the condition is false."""
        pol = self.cond(e)
        self.emit(f"({'!' if pol else ''}p1) b {target}")

    # ---- statements

    def gen_stmt(self, s):
        op = s[0]
        if op == "block":
            self.scopes.append({})
            for x in s[1]:
                self.gen_stmt(x)
            self.scopes.pop()
        elif op == "multi":
            for x in s[2]:               # one declaration, N declarators
                self.gen_stmt(x)
        elif op == "decl":
            _, line, t, name, init = s
            if name in self.scopes[-1]:
                raise Cc(line, f"'{name}' redeclared in the same block")
            off = self.locals_base + self.slot_of[id(s)]
            self.scopes[-1][name] = ("local", off, t)
            if init is not None:
                vt = self.rvalue(init)
                rv = self.top()
                self.implicit(rv, vt, t, line, "initializer")
                self.store_direct(off, rv, t)
                self.pop()
        elif op == "expr":
            self.rvalue(s[2])
            self.pop()
        elif op == "empty":
            pass
        elif op == "return":
            _, line, e = s
            if e is None:
                if self.ret != ("void",):
                    raise Cc(line, "return without a value in a "
                                   "non-void function")
            else:
                if self.ret == ("void",):
                    raise Cc(line, "return with a value in a void "
                                   "function")
                t = self.rvalue(e)
                self.implicit(self.top(), t, self.ret, line, "return")
                self.emit(f"mov r0, {self.top()}")
                self.pop()
            self.emit(f"b {self.name}.Lret")
        elif op == "if":
            _, line, cond, then, els = s
            if els is None:
                end = self.label()
                self.branch_unless(cond, end)
                self.gen_stmt(then)
                self.emit_label(end)
            else:
                lelse = self.label()
                end = self.label()
                self.branch_unless(cond, lelse)
                self.gen_stmt(then)
                self.emit(f"b {end}")
                self.emit_label(lelse)
                self.gen_stmt(els)
                self.emit_label(end)
        elif op == "while":
            _, line, cond, body = s
            top = self.label()
            end = self.label()
            self.emit_label(top)
            self.branch_unless(cond, end)
            self.loopstack.append(("loop", top, end))
            self.gen_stmt(body)
            self.loopstack.pop()
            self.emit(f"b {top}")
            self.emit_label(end)
        elif op == "for":
            _, line, init, cond, step, body = s
            if init is not None:
                self.rvalue(init)
                self.pop()
            top = self.label()
            cont = self.label()
            end = self.label()
            self.emit_label(top)
            if cond is not None:
                self.branch_unless(cond, end)
            self.loopstack.append(("loop", cont, end))
            self.gen_stmt(body)
            self.loopstack.pop()
            self.emit_label(cont)
            if step is not None:
                self.rvalue(step)
                self.pop()
            self.emit(f"b {top}")
            self.emit_label(end)
        elif op == "do":
            _, line, body, cond = s
            top = self.label()
            cont = self.label()
            end = self.label()
            self.emit_label(top)
            self.loopstack.append(("loop", cont, end))
            self.gen_stmt(body)
            self.loopstack.pop()
            self.emit_label(cont)
            pol = self.cond(cond)
            self.emit(f"({'p1' if pol else '!p1'}) b {top}")
            self.emit_label(end)
        elif op == "switch":
            self.gen_switch(s)
        elif op == "case":
            lab = self.case_labels.get(id(s))
            if lab is None:
                raise Cc(s[1], "case label outside a switch")
            self.emit_label(lab)
            self.gen_stmt(s[3])
        elif op == "default":
            lab = self.case_labels.get(id(s))
            if lab is None:
                raise Cc(s[1], "default label outside a switch")
            self.emit_label(lab)
            self.gen_stmt(s[2])
        elif op == "label":
            _, line, name, stmt = s
            if name in self.golabels:
                raise Cc(line, f"label '{name}' redefined")
            lab = f"{self.name}.L.{name}"
            self.golabels[name] = lab
            self.emit_label(lab)
            self.gen_stmt(stmt)
        elif op == "goto":
            _, line, name = s
            self.gotos.append((name, line))
            self.emit(f"b {self.name}.L.{name}")
        elif op == "break":
            if not self.loopstack:
                raise Cc(s[1], "break outside a loop or switch")
            self.emit(f"b {self.loopstack[-1][2]}")
        elif op == "continue":
            for ent in reversed(self.loopstack):
                if ent[0] == "loop":
                    self.emit(f"b {ent[1]}")
                    break
            else:
                raise Cc(s[1], "continue outside a loop")
        else:
            raise AssertionError(op)

    def gen_switch(self, s):
        """Linear compare chain (work-order decision 5, binding): one
        cmpeq + branch per case in source order, default last - no
        jump table (that is optimizer-stream work, and the chain is
        abicheck-transparent and deterministic)."""
        _, line, e, body = s
        t = self.rvalue(e)
        if not is_int(t):
            raise Cc(line, "switch controlling expression must be an "
                           "integer")
        cases = []               # (image-at-t, label, line), source order
        defaults = []

        def collect(n):
            if isinstance(n, list):
                for x in n:
                    collect(x)
                return
            if not isinstance(n, tuple):
                return
            if n[0] == "switch":
                return           # a nested switch owns its own cases
            if n[0] == "case":
                v = const_eval(n[2], self.u)
                if v is None or not is_int(v[3]):
                    raise Cc(n[1], "case label must be an integer "
                                   "constant expression")
                image = sext(to_val(v[2], v[3]), t[1])
                lab = self.label()
                self.case_labels[id(n)] = lab
                cases.append((image, lab, n[1]))
                collect(n[3])
                return
            if n[0] == "default":
                lab = self.label()
                self.case_labels[id(n)] = lab
                defaults.append((lab, n[1]))
                collect(n[2])
                return
            for x in n:
                collect(x)

        collect(body)
        if len(defaults) > 1:
            raise Cc(defaults[1][1], "duplicate default label")
        seen = {}
        for image, lab, cline in cases:
            if image in seen:
                raise Cc(cline, f"duplicate case value "
                               f"{to_signed(image)} (first at line "
                               f"{seen[image]})")
            seen[image] = cline
        rx = self.top()
        sfx = suffix(t)
        for image, lab, cline in cases:
            sval = to_signed(image)
            if -(1 << 21) <= sval < (1 << 21):
                self.emit(f"cmpeq{sfx} p1, {rx}, {sval}")
            else:
                ry = self.push()
                self.emit(f"li {ry}, {sval}")
                self.emit(f"cmpeq{sfx} p1, {rx}, {ry}")
                self.pop()
            self.emit(f"(p1) b {lab}")
        self.pop()
        end = self.label()
        self.emit(f"b {defaults[0][0] if defaults else end}")
        self.loopstack.append(("switch", None, end))
        self.gen_stmt(body)
        self.loopstack.pop()
        self.emit_label(end)

    # ---- whole function

    def generate(self):
        # entry: bind parameters, spill r0-r7 / copy stack args
        self.scopes.append({})
        entry = []
        for i, (pn, pt) in enumerate(self.params):
            off = self.locals_base + 16 * i
            self.scopes[0][pn] = ("local", off, pt)
            bits = pt[1] if is_int(pt) else 128
            stmn = "st128" if bits == 128 else STORES[bits]
            if i < 8:
                entry.append(f"        {stmn} [sp + {off}], r{i}")
            else:
                # incoming stack slot i-8 lives above the frame
                # (ISA 12: [sp + framesize + 16*(i-8)])
                entry.append(f"        ld128 r8, [sp + %%ARG{16 * (i - 8)}%%]")
                entry.append(f"        {stmn} [sp + {off}], r8")
        self.gen_stmt(self.body)
        if self.depth != 0:
            raise AssertionError(f"{self.name}: temp stack leak "
                                 f"({self.depth})")
        for gname, gline in self.gotos:
            if gname not in self.golabels:
                raise Cc(gline, f"goto to undefined label '{gname}'")
        self.scopes.pop()

        if self.calls:
            spill_size = 16 * self.peak
        else:
            spill_size = 16 * max(0, self.peak - 8)
        frame = self.out_size + self.locals_size + spill_size
        if self.calls:
            frame += 16                     # ra slot on top
        if frame > 1 << 20:
            raise Cc(self.dline, f"{self.name}(): frame size {frame} "
                                 f"exceeds the m1 limit of 2^20 bytes "
                                 f"(cc-m1.md section 11)")

        def patch(line):
            if "%%ARG" in line:
                pre, rest = line.split("%%ARG", 1)
                extra, post = rest.split("%%", 1)
                return pre + str(frame + int(extra)) + post
            return line

        out = [f"# cc: func {self.name} frame={frame} "
               f"calls={1 if self.calls else 0}",
               f"{self.name}:"]
        if frame:
            out.append(f"        add sp, sp, -{frame}")
        if self.calls:
            out.append(f"        st128 [sp + {frame - 16}], ra")
        out.extend(patch(x) for x in entry)
        out.extend(patch(x) for x in self.lines)
        if self.ret != ("void",):
            out.append("        li r0, 0")   # end of a non-void body:
        out.append(f"{self.name}.Lret:")      # defined return 0
        if self.calls:
            out.append(f"        ld128 ra, [sp + {frame - 16}]")
        if frame:
            out.append(f"        add sp, sp, {frame}")
        out.append("        ret")
        return out


# ----------------------------------------------------------------- output

DATA_DIRECTIVE = {1: ".byte", 2: ".half", 4: ".word", 8: ".quad",
                  16: ".oct"}


def escape_string(data):
    out = []
    for b in data:
        if b == 0x22:
            out.append('\\"')
        elif b == 0x5C:
            out.append("\\\\")
        elif 0x20 <= b <= 0x7E:
            out.append(chr(b))
        elif b == 0x0A:
            out.append("\\n")
        elif b == 0x09:
            out.append("\\t")
        else:
            out.append(f"\\x{b:02x}")
    return "".join(out)


def render(unit, basename):
    lines = [f"# {basename} - CC-M1 compiled output (lang/cc/cc.py; "
             f"spec lang/cc/cc-m1.md)"]

    # text
    lines.append("        .align 16")
    for fname in unit.forder:
        lines.extend(Func(unit, fname).generate())

    # rodata: string literals, first-use order (dict = insertion order)
    lines.append("        .align 16")
    lines.append("__etext:")
    for data, label in unit.strings.items():
        lines.append(f"{label}:")
        lines.append(f'        .asciiz "{escape_string(data)}"')

    # data: initialized globals, declaration order
    lines.append("        .align 16")
    lines.append("__erodata:")
    for name in unit.gorder:
        g = unit.globals[name]
        if g["extern"] or g["init"] is None:
            continue
        t, init = g["type"], g["init"]
        elem = t[1] if t[0] == "arr" else t
        size = unit.t_size(elem)
        align = unit.t_align(t)
        if align > 1:
            lines.append(f"        .align {align}")
        lines.append(f"{name}:")
        values = init if isinstance(init, list) else [init]
        if t[0] == "arr" and len(values) < t[2]:
            values = values + [0] * (t[2] - len(values))
        mask = (1 << (8 * size)) - 1
        directive = DATA_DIRECTIVE[size]
        for i in range(0, len(values), 8):
            chunk = ", ".join(f"0x{v & mask:x}" for v in values[i:i + 8])
            lines.append(f"        {directive} {chunk}")

    # bss: uninitialized globals, declaration order
    lines.append("        .align 16")
    lines.append("__edata:")
    for name in unit.gorder:
        g = unit.globals[name]
        if g["extern"] or g["init"] is not None:
            continue
        t = g["type"]
        align = unit.t_align(t)
        if align > 1:
            lines.append(f"        .align {align}")
        lines.append(f"{name}:")
        lines.append(f"        .space {unit.t_size(t)}")

    lines.append("        .align 16")
    lines.append("_end:")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------- main

def fold_body(node, unit):
    if not isinstance(node, tuple):
        if isinstance(node, list):
            return [fold_body(x, unit) for x in node]
        return node
    if node[0] in ("num", "strlit", "var"):
        return node
    if node and isinstance(node[0], str) and node[0] in (
            "bin", "logic", "neg", "not", "cast", "addr", "deref",
            "index", "field", "call", "assign", "strlit"):
        return fold(tuple(fold_body(x, unit) for x in node), unit)
    return tuple(fold_body(x, unit) for x in node)


def compile_unit(path, out_path):
    try:
        src = open(path, "r").read()
    except OSError as ex:
        print(f"cc: cannot read {path}: {ex}", file=sys.stderr)
        sys.exit(1)
    unit = Unit()
    try:
        parser = Parser(lex(src), unit)
        parser.parse_unit()
        # fold literal subexpressions (cc-m1.md 5.5)
        for name, (ret, params, body, line) in list(unit.funcs.items()):
            if body is not None:
                unit.funcs[name] = (ret, params, fold_body(body, unit),
                                    line)
        m = unit.funcs.get("main")
        if m is None or m[2] is None:
            raise Cc(1, "no main() defined (cc-m1.md section 1)")
        if m[1] or m[0] not in (T_I64, T_U64):
            raise Cc(m[3], "main must be 'i64 main()' or 'u64 main()' "
                           "with no parameters")
        text = render(unit, os.path.basename(path))
    except Cc as ex:
        print(f"{path}:{ex.line}: error: {ex.msg}", file=sys.stderr)
        sys.exit(1)
    with open(out_path, "w") as f:
        f.write(text)


def main():
    ap = argparse.ArgumentParser(
        description="CC-M1 compiler (lang/cc/cc-m1.md)")
    ap.add_argument("input", help="one .c translation unit")
    ap.add_argument("-o", dest="output", required=True,
                    help="output .s path")
    args = ap.parse_args()
    compile_unit(args.input, args.output)


if __name__ == "__main__":
    main()
