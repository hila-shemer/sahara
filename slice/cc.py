#!/usr/bin/env python3
# Sahara slice toy compiler. C-like subset -> slice assembly. No optimizer.
# Types: int (64-bit signed), i32, i128, T*, struct, arrays of scalars/structs.
# Measurements: max simultaneous live values, predication use, stack-arg use.
import sys, argparse

KEYWORDS = {'int', 'i32', 'i128', 'void', 'struct', 'if', 'else', 'while', 'return'}
PUNCT2 = ['==', '!=', '<=', '>=', '->', '<<', '>>']

def lex(src):
    toks, i = [], 0
    while i < len(src):
        c = src[i]
        if c.isspace(): i += 1; continue
        if src.startswith('//', i):
            while i < len(src) and src[i] != '\n': i += 1
            continue
        if c.isalpha() or c == '_':
            j = i
            while j < len(src) and (src[j].isalnum() or src[j] == '_'): j += 1
            w = src[i:j]
            toks.append(('kw' if w in KEYWORDS else 'id', w)); i = j; continue
        if c.isdigit():
            j = i
            while j < len(src) and (src[j].isalnum()): j += 1
            toks.append(('num', int(src[i:j], 0))); i = j; continue
        two = src[i:i+2]
        if two in PUNCT2: toks.append(('p', two)); i += 2; continue
        toks.append(('p', c)); i += 1
    toks.append(('eof', ''))
    return toks

class P:
    def __init__(self, toks): self.t, self.i = toks, 0
    def peek(self): return self.t[self.i]
    def next(self): tk = self.t[self.i]; self.i += 1; return tk
    def accept(self, kind, val=None):
        k, v = self.peek()
        if k == kind and (val is None or v == val): self.i += 1; return v
        return None
    def expect(self, kind, val=None):
        r = self.accept(kind, val)
        if r is None: raise SystemExit(f"parse error at {self.t[self.i]} (wanted {kind} {val})")
        return r
    def at_type(self):
        k, v = self.peek()
        return k == 'kw' and v in ('int', 'i32', 'i128', 'void', 'struct')

structs = {}   # name -> (fields: [(name, type, offset)], size, align)

def type_align(t):
    if t[0] == 'int': return 8
    if t[0] == 'i32': return 4
    if t[0] in ('i128', 'ptr'): return 16
    if t[0] == 'struct': return structs[t[1]][2]
    raise SystemExit(f"align of {t}")

def type_size(t):
    if t[0] == 'int': return 8
    if t[0] == 'i32': return 4
    if t[0] in ('i128', 'ptr'): return 16
    if t[0] == 'struct': return structs[t[1]][1]
    raise SystemExit(f"size of {t}")

def parse_type(p):
    if p.accept('kw', 'struct'):
        name = p.expect('id'); t = ('struct', name)
    else:
        t = (p.expect('kw'),)
    while p.accept('p', '*'): t = ('ptr', t)
    return t

def parse_program(src):
    p = P(lex(src))
    funcs = []
    while p.peek()[0] != 'eof':
        if p.peek() == ('kw', 'struct') and p.t[p.i+2] == ('p', '{'):
            p.next(); name = p.expect('id'); p.expect('p', '{')
            fields, off, maxal = [], 0, 1
            while not p.accept('p', '}'):
                ft = parse_type(p); fn = p.expect('id'); p.expect('p', ';')
                al = type_align(ft); off = (off + al - 1) & ~(al - 1)
                fields.append((fn, ft, off)); off += type_size(ft); maxal = max(maxal, al)
            p.expect('p', ';')
            size = (off + maxal - 1) & ~(maxal - 1)
            structs[name] = (fields, size, maxal)
            continue
        rt = parse_type(p); name = p.expect('id')
        p.expect('p', '(')
        params = []
        if not p.accept('p', ')'):
            while True:
                pt = parse_type(p); pn = p.expect('id')
                params.append((pn, pt))
                if p.accept('p', ')'): break
                p.expect('p', ',')
        body = parse_block(p)
        funcs.append((name, rt, params, body))
    return funcs

def parse_block(p):
    p.expect('p', '{')
    stmts = []
    while not p.accept('p', '}'):
        stmts.append(parse_stmt(p))
    return ('block', stmts)

def parse_stmt(p):
    if p.peek() == ('p', '{'): return parse_block(p)
    if p.at_type():
        t = parse_type(p); name = p.expect('id')
        count = None
        if p.accept('p', '['): count = p.expect('num'); p.expect('p', ']')
        init = None
        if p.accept('p', '='): init = parse_expr(p)
        p.expect('p', ';')
        return ('decl', t, name, count, init)
    if p.accept('kw', 'if'):
        p.expect('p', '('); cond = parse_expr(p); p.expect('p', ')')
        then = parse_stmt(p)
        els = parse_stmt(p) if p.accept('kw', 'else') else None
        return ('if', cond, then, els)
    if p.accept('kw', 'while'):
        p.expect('p', '('); cond = parse_expr(p); p.expect('p', ')')
        return ('while', cond, parse_stmt(p))
    if p.accept('kw', 'return'):
        e = None if p.peek() == ('p', ';') else parse_expr(p)
        p.expect('p', ';')
        return ('return', e)
    e = parse_expr(p); p.expect('p', ';')
    return ('expr', e)

def parse_expr(p): return parse_assign(p)
def parse_assign(p):
    lhs = parse_bin(p, 0)
    if p.accept('p', '='):
        return ('assign', lhs, parse_assign(p))
    return lhs

BINLEVELS = [['|'], ['^'], ['&'], ['==', '!='], ['<', '>', '<=', '>='],
             ['<<', '>>'], ['+', '-'], ['*', '/', '%']]
def parse_bin(p, lvl):
    if lvl == len(BINLEVELS): return parse_unary(p)
    e = parse_bin(p, lvl + 1)
    while True:
        k, v = p.peek()
        if k == 'p' and v in BINLEVELS[lvl]:
            p.next()
            e = ('bin', v, e, parse_bin(p, lvl + 1))
        else:
            return e

def parse_unary(p):
    if p.accept('p', '-'): return ('neg', parse_unary(p))
    if p.accept('p', '!'): return ('not', parse_unary(p))
    if p.accept('p', '*'): return ('deref', parse_unary(p))
    if p.accept('p', '&'): return ('addr', parse_unary(p))
    return parse_postfix(p)

def parse_postfix(p):
    k, v = p.next()
    if k == 'num': e = ('num', v)
    elif k == 'id': e = ('var', v)
    elif (k, v) == ('p', '('):
        e = parse_expr(p); p.expect('p', ')')
    else: raise SystemExit(f"parse error at {(k, v)}")
    while True:
        if p.accept('p', '['):
            e = ('index', e, parse_expr(p)); p.expect('p', ']')
        elif p.accept('p', '.'):
            e = ('field', e, p.expect('id'), 0)
        elif p.accept('p', '->'):
            e = ('field', e, p.expect('id'), 1)
        elif p.accept('p', '('):
            args = []
            if not p.accept('p', ')'):
                while True:
                    args.append(parse_expr(p))
                    if p.accept('p', ')'): break
                    p.expect('p', ',')
            e = ('call', e[1], args)
        else:
            return e

# ---------------------------------------------------------------- codegen
NTEMPS = 15          # r1..r15 (r0 reserved for arg0/return)
CALLEE = list(range(16, 28))
MAXNEST = 3          # call nesting levels with distinct arg-staging areas

class Mem:
    """Address expression a load/store can consume directly: base + idx<<sh + off."""
    def __init__(self, base, idx=None, sh=0, off=0):
        self.base, self.idx, self.sh, self.off = base, idx, sh, off
    def __str__(self):
        s = self.base
        if self.idx is not None:
            s += f" + {self.idx}<<{self.sh}" if self.sh else f" + {self.idx}"
        if self.off: s += f" + {self.off}"
        return s

class Fn:
    def __init__(self, cg, name, rt, params, body):
        self.cg = cg; self.name = name; self.rt = rt
        self.params = params; self.body = body
        self.lines = []
        self.tdepth = 0; self.tdepth_peak = 0
        self.pred_depth = 0
        self.pred_emitted = 0
        self.label_n = 0
        self.if_pred = None
        self.callnest = 0
        self.loc = {}; self.types = {}
        self.max_call_args = 0
        self.has_calls = False
        self.stack_args_out = 0
        self.decls = []
        self.prescan(body)
        self.addressed = set()
        self.find_addressed(body)
        stack_off = 0
        self.callee_used = []
        free = list(CALLEE)
        def place(name, t, count):
            nonlocal stack_off
            scalar = count is None and t[0] != 'struct'
            if scalar and name not in self.addressed and free:
                r = free.pop(0); self.callee_used.append(r)
                self.loc[name] = ('reg', r)
                self.types[name] = t
            else:
                n = (count or 1) * type_size(t)
                n = (n + 15) & ~15
                self.loc[name] = ('stack', stack_off); stack_off += n
                self.types[name] = ('arr', t, count) if count is not None else t
        for pn, pt in params: place(pn, pt, None)
        for (t, n2, count) in self.decls: place(n2, t, count)
        # frame: [outgoing stack args][15 temp spills][MAXNEST*16 arg stage][ra][saves][locals]
        out_bytes = max(0, self.max_call_args - cg.argregs) * 16
        self.spill_base = out_bytes
        self.stage_base = self.spill_base + 15*16
        self.ra_off = self.stage_base + MAXNEST*16*16
        self.cs_off = self.ra_off + 16
        self.locals_base = self.cs_off + 16*len(self.callee_used)
        self.frame = (self.locals_base + stack_off + 15) & ~15
        for n2, l in self.loc.items():
            if l[0] == 'stack': self.loc[n2] = ('stack', self.locals_base + l[1])

    def prescan(self, node):
        def walk(n):
            if not isinstance(n, tuple): return
            if n[0] == 'decl': self.decls.append((n[1], n[2], n[3]))
            if n[0] == 'call':
                self.has_calls = True
                self.max_call_args = max(self.max_call_args, len(n[2]))
            for x in n[1:]:
                if isinstance(x, tuple): walk(x)
                elif isinstance(x, list):
                    for y in x: walk(y)
        walk(node)

    def find_addressed(self, node):
        def walk(n):
            if not isinstance(n, tuple): return
            if n[0] == 'addr' and n[1][0] == 'var': self.addressed.add(n[1][1])
            for x in n[1:]:
                if isinstance(x, tuple): walk(x)
                elif isinstance(x, list):
                    for y in x: walk(y)
        walk(node)

    def emit(self, s):
        if self.if_pred is not None and not s.endswith(':'):
            assert not s.lstrip().startswith('('), "double predication"
            pd, pol = self.if_pred
            s = f"({'!' if pol else ''}p{pd}) " + s
        if s.lstrip().startswith('('): self.pred_emitted += 1
        self.lines.append('    ' + s if not s.endswith(':') else s)

    def label(self, base):
        self.label_n += 1
        return f".{self.name}_{base}_{self.label_n}"

    def tpush(self):
        if self.tdepth >= NTEMPS: raise SystemExit(f"{self.name}: temp pool exhausted")
        self.tdepth += 1
        self.tdepth_peak = max(self.tdepth_peak, self.tdepth)
        return f"r{self.tdepth}"
    def tpop(self): self.tdepth -= 1

    def npred(self):
        if self.pred_depth >= 7: raise SystemExit("out of predicate registers")
        self.pred_depth += 1
        return self.pred_depth
    def rpred(self): self.pred_depth -= 1

    def ldop(self, t): return {'int': 'ld64s', 'i32': 'ld32s'}.get(t[0], 'ld128')
    def stop(self, t): return {'int': 'st64', 'i32': 'st32'}.get(t[0], 'st128')

    # ---------- expressions: evaluate into a fresh temp; returns (reg, type)
    def rvalue(self, e):
        op = e[0]
        if op == 'num':
            r = self.tpush(); self.emit(f"li {r}, {e[1]}"); return r, ('int',)
        if op == 'var':
            t = self.types[e[1]]
            if t[0] == 'arr':
                r = self.tpush()
                self.emit(f"add {r}, sp, {self.loc[e[1]][1]}")
                return r, ('ptr', t[1])
            l = self.loc[e[1]]
            r = self.tpush()
            if l[0] == 'reg': self.emit(f"mov {r}, r{l[1]}")
            else: self.emit(f"{self.ldop(t)} {r}, [sp + {l[1]}]")
            return r, t
        if op == 'bin': return self.gen_bin(e)
        if op == 'neg':
            r, t = self.rvalue(e[1]); self.emit(f"sub {r}, zero, {r}"); return r, t
        if op == 'not':
            r, t = self.rvalue(e[1])
            pd = self.npred()
            self.emit(f"cmpeq p{pd}, {r}, zero")
            self.emit(f"(p{pd}) ldi {r}, 1")
            self.emit(f"(!p{pd}) ldi {r}, 0")
            self.rpred()
            return r, ('int',)
        if op in ('deref', 'index', 'field'):
            base, t, mem = self.lvalue(e)
            self.emit(f"{self.ldop(t)} {base}, [{mem}]")   # reuse base temp for value
            return base, t
        if op == 'addr':
            base, t, mem = self.lvalue(e[1])
            if mem.idx is not None:
                self.emit(f"add {base}, {mem.base}, {mem.idx}<<{mem.sh}" if mem.sh
                          else f"add {base}, {mem.base}, {mem.idx}")
            if mem.off:
                self.emit(f"add {base}, {base if mem.idx is not None else mem.base}, {mem.off}")
            return base, ('ptr', t)
        if op == 'call': return self.gen_call(e)
        if op == 'assign': return self.gen_assign(e[1], e[2])
        raise SystemExit(f"rvalue {op}")

    # lvalue: returns (base_temp, value_type, Mem). Net one temp pushed (base).
    # Mem may reference a popped idx temp; consume it with the NEXT emitted insn.
    def lvalue(self, e):
        op = e[0]
        if op == 'var':
            t = self.types[e[1]]
            l = self.loc[e[1]]
            assert l[0] == 'stack', "reg-located var has no address"
            r = self.tpush()
            self.emit(f"mov {r}, sp")
            return r, t, Mem(r, off=l[1])
        if op == 'deref':
            r, t = self.rvalue(e[1])
            assert t[0] == 'ptr', f"deref of {t}"
            return r, t[1], Mem(r)
        if op == 'index':
            base, bt = self.rvalue(e[1])
            assert bt[0] == 'ptr', f"index of {bt}"
            elt = bt[1]
            idx, _ = self.rvalue(e[2])
            sz = type_size(elt)
            if sz & (sz - 1) == 0:
                self.tpop()          # idx consumed by addressing mode
                return base, elt, Mem(base, idx, sz.bit_length() - 1)
            self.emit(f"mul {idx}, {idx}, {sz}")
            self.emit(f"add {base}, {base}, {idx}")
            self.tpop()
            return base, elt, Mem(base)
        if op == 'field':
            if e[3]:   # ->
                base, bt = self.rvalue(e[1])
                assert bt[0] == 'ptr' and bt[1][0] == 'struct'
                st = bt[1]
                mem = Mem(base)
            else:
                base, st, mem = self.lvalue(e[1])
                assert st[0] == 'struct', f".field of {st}"
            for fn, ft, off in structs[st[1]][0]:
                if fn == e[2]:
                    return base, ft, Mem(mem.base, mem.idx, mem.sh, mem.off + off)
            raise SystemExit(f"no field {e[2]} in {st}")
        raise SystemExit(f"lvalue {op}")

    CMP = {'==': ('cmpeq', 0), '!=': ('cmpeq', 1),
           '<': ('cmplt', 0), '>=': ('cmplt', 1),
           '<=': ('cmple', 0), '>': ('cmple', 1)}

    def gen_bin(self, e):
        _, op, l, r = e
        if op in self.CMP:
            pd, pol = self.cond(e)
            reg = self.tpush()
            self.emit(f"({'!' if pol else ''}p{pd}) ldi {reg}, 1")
            self.emit(f"({'' if pol else '!'}p{pd}) ldi {reg}, 0")
            self.rpred()
            return reg, ('int',)
        ra, ta = self.rvalue(l)
        rb, tb = self.rvalue(r)
        ins = {'+': 'add', '-': 'sub', '*': 'mul', '/': 'sdiv', '%': 'srem',
               '&': 'and', '|': 'or', '^': 'xor', '<<': 'shl', '>>': 'sar'}[op]
        if ta[0] == 'ptr' and op in ('+', '-') and tb[0] != 'ptr':
            sz = type_size(ta[1])
            if sz & (sz - 1) == 0:
                self.emit(f"{ins} {ra}, {ra}, {rb}<<{sz.bit_length()-1}")
            else:
                self.emit(f"mul {rb}, {rb}, {sz}")
                self.emit(f"{ins} {ra}, {ra}, {rb}")
            self.tpop()
            return ra, ta
        self.emit(f"{ins} {ra}, {ra}, {rb}")
        self.tpop()
        return ra, tb if tb[0] == 'ptr' else ta

    # condition -> predicate; true iff P[pd] XOR pol
    def cond(self, e):
        if e[0] == 'bin' and e[1] in self.CMP:
            ins, pol = self.CMP[e[1]]
            ra, _ = self.rvalue(e[2])
            rb, _ = self.rvalue(e[3])
            pd = self.npred()
            self.emit(f"{ins} p{pd}, {ra}, {rb}")
            self.tpop(); self.tpop()
            return pd, pol
        r, _ = self.rvalue(e)
        pd = self.npred()
        self.emit(f"cmpeq p{pd}, {r}, zero")
        self.tpop()
        return pd, 1

    def gen_call(self, e):
        _, name, args = e
        argregs = self.cg.argregs
        if self.callnest >= MAXNEST: raise SystemExit("call nesting too deep")
        d = self.tdepth
        for i in range(d):
            self.emit(f"st128 [sp + {self.spill_base + 16*i}], r{i+1}")
        stage = self.stage_base + self.callnest*16*16
        self.callnest += 1
        for k, a in enumerate(args):
            r, _ = self.rvalue(a)
            if k < argregs:
                self.emit(f"st128 [sp + {stage + 16*k}], {r}")
            else:
                if self.callnest > 1: raise SystemExit("nested call with stack args")
                self.emit(f"st128 [sp + {16*(k-argregs)}], {r}")
                self.stack_args_out += 1
            self.tpop()
        self.callnest -= 1
        for k in range(min(len(args), argregs)):
            self.emit(f"ld128 r{k}, [sp + {stage + 16*k}]")
        self.emit(f"jal ra, {name}")
        for i in range(d):
            self.emit(f"ld128 r{i+1}, [sp + {self.spill_base + 16*i}]")
        res = self.tpush()
        self.emit(f"mov {res}, r0")
        return res, ('int',)

    def gen_assign(self, lhs, rhs):
        if lhs[0] == 'var' and self.loc[lhs[1]][0] == 'reg':
            r, t = self.rvalue(rhs)
            self.emit(f"mov r{self.loc[lhs[1]][1]}, {r}")
            return r, self.types[lhs[1]]
        r, t = self.rvalue(rhs)
        base, lt, mem = self.lvalue(lhs)
        self.emit(f"{self.stop(lt)} [{mem}], {r}")
        self.tpop()   # base
        return r, lt

    # ---------- statements
    def gen_stmt(self, s):
        op = s[0]
        if op == 'block':
            for x in s[1]: self.gen_stmt(x)
        elif op == 'decl':
            if s[4] is not None:
                self.gen_assign(('var', s[2]), s[4])
                self.tpop()
        elif op == 'expr':
            self.rvalue(s[1]); self.tpop()
        elif op == 'return':
            if s[1] is not None:
                r, _ = self.rvalue(s[1])
                self.emit(f"mov r0, {r}")
                self.tpop()
            self.emit(f"b .{self.name}_ret")
        elif op == 'if':
            if self.if_convertible(s) and self.if_pred is None:
                pd, pol = self.cond(s[1])
                self.if_pred = (pd, pol)
                self.gen_stmt(s[2])
                if s[3] is not None:
                    self.if_pred = (pd, 1 - pol)
                    self.gen_stmt(s[3])
                self.if_pred = None
                self.rpred()
                return
            pd, pol = self.cond(s[1])
            els = self.label('else'); end = self.label('endif')
            self.emit(f"({'' if pol else '!'}p{pd}) b {els}")   # branch if cond false
            self.rpred()
            self.gen_stmt(s[2])
            self.emit(f"b {end}")
            self.emit(f"{els}:")
            if s[3] is not None: self.gen_stmt(s[3])
            self.emit(f"{end}:")
        elif op == 'while':
            top = self.label('loop'); end = self.label('endloop')
            self.emit(f"{top}:")
            pd, pol = self.cond(s[1])
            self.emit(f"({'' if pol else '!'}p{pd}) b {end}")
            self.rpred()
            self.gen_stmt(s[2])
            self.emit(f"b {top}")
            self.emit(f"{end}:")
        else:
            raise SystemExit(f"stmt {op}")

    def if_convertible(self, s):
        # then/else each a single assignment, no calls, no comparisons inside
        def simple(st):
            if st is None: return True
            if st[0] == 'block':
                return len(st[1]) == 1 and simple(st[1][0])
            if st[0] != 'expr' or st[1][0] != 'assign': return False
            bad = [False]
            def walk(n):
                if isinstance(n, tuple):
                    if n[0] in ('call', 'not') or (n[0] == 'bin' and n[1] in self.CMP):
                        bad[0] = True
                    for x in n[1:]:
                        if isinstance(x, tuple): walk(x)
                        elif isinstance(x, list):
                            for y in x: walk(y)
            walk(st[1])
            return not bad[0]
        return simple(s[2]) and simple(s[3])

    def generate(self):
        self.emit(f"{self.name}:")
        self.emit(f"sub sp, sp, {self.frame}")
        if self.has_calls:
            self.emit(f"st128 [sp + {self.ra_off}], ra")
        for i, r in enumerate(self.callee_used):
            self.emit(f"st128 [sp + {self.cs_off + 16*i}], r{r}")
        for k, (pn, pt) in enumerate(self.params):
            l = self.loc[pn]
            if k < self.cg.argregs:
                if l[0] == 'reg': self.emit(f"mov r{l[1]}, r{k}")
                else: self.emit(f"st128 [sp + {l[1]}], r{k}")
            else:
                src = self.frame + 16*(k - self.cg.argregs)
                if l[0] == 'reg': self.emit(f"ld128 r{l[1]}, [sp + {src}]")
                else:
                    tmp = self.tpush()
                    self.emit(f"ld128 {tmp}, [sp + {src}]")
                    self.emit(f"st128 [sp + {l[1]}], {tmp}")
                    self.tpop()
        self.gen_stmt(self.body)
        self.emit(f"ldi r0, 0")
        self.emit(f".{self.name}_ret:")
        for i, r in enumerate(self.callee_used):
            self.emit(f"ld128 r{r}, [sp + {self.cs_off + 16*i}]")
        if self.has_calls:
            self.emit(f"ld128 ra, [sp + {self.ra_off}]")
        self.emit(f"add sp, sp, {self.frame}")
        self.emit(f"jalr zero, ra, 0")
        return self.lines

class Cg:
    def __init__(self, argregs): self.argregs = argregs

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src'); ap.add_argument('-o', default='out.s')
    ap.add_argument('--argregs', type=int, default=16)
    ap.add_argument('--stats')
    args = ap.parse_args()
    funcs = parse_program(open(args.src).read())
    cg = Cg(args.argregs)
    out, stats = [], []
    for (name, rt, params, body) in funcs:
        f = Fn(cg, name, rt, params, body)
        out += f.generate()
        maxlive = len(f.callee_used) + f.tdepth_peak
        stats.append(f"{name}: max_live={maxlive} callee_used={len(f.callee_used)} "
                     f"temp_peak={f.tdepth_peak} pred_emitted={f.pred_emitted} "
                     f"stack_args_out={f.stack_args_out} frame={f.frame}")
    open(args.o, 'w').write('\n'.join(out) + '\n')
    report = '\n'.join(stats)
    if args.stats: open(args.stats, 'a').write(f"== {args.src} argregs={args.argregs}\n{report}\n")
    print(report)

if __name__ == '__main__':
    main()
