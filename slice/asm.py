#!/usr/bin/env python3
# Sahara slice assembler. Text in, image out. Crude on purpose.
# Syntax:
#   [(p3)|(!p3)] op operands   # comment
#   add rd, rs1, rs2 | add rd, rs1, 42 | add rd, rs1, rs2<<3 | rs2 sx 32 | rs2 zx 8
#   madd rd, rs1, rs2, rs3
#   cmplt p1, rs1, rs2
#   ld32u rd, [rs1 + rs2<<2 + 8] ; st64 [rs1 + 16], rs3
#   b label ; jal ra, label ; jalr rd, rs, 0
#   ldi rd, imm ; shori rd, rs, imm ; li rd, bigimm ; la rd, label
#   mov rd, rs ; nop ; mfsr rd, status ; mtsr status, rs ; iret ; invtp ; halt
# Directives: .org ADDR  .entry LABEL  .data64 v,v,...  .data32/16/8/128  .space N
import sys, re, argparse
from encoding import Enc, MAJOR, SREGS, REG_ALIASES, MOD_NONE, MOD_SHL, MOD_SXT, MOD_ZXT

def parse_reg(t):
    t = t.strip()
    if t in REG_ALIASES: return REG_ALIASES[t]
    m = re.fullmatch(r'r(\d+)', t)
    if m and int(m.group(1)) < 32: return int(m.group(1))
    raise ValueError(f"bad register {t!r}")

def parse_pred(t):
    m = re.fullmatch(r'p(\d)', t.strip())
    if m and int(m.group(1)) < 8: return int(m.group(1))
    raise ValueError(f"bad predicate {t!r}")

def parse_int(t):
    t = t.strip()
    return int(t, 0)

class Asm:
    def __init__(self, enc):
        self.enc = enc
        self.imm_log = []   # (kind, value) for the width experiment

    # returns (mod, src2reg) from an operand string like "r5<<3" / "r5 sx 32" / "r5"
    def parse_src2(self, t):
        t = t.strip()
        m = re.fullmatch(r'(\S+)\s*<<\s*(\d+)', t)
        if m: return self.mk_mod(MOD_SHL, int(m.group(2))), parse_reg(m.group(1))
        m = re.fullmatch(r'(\S+)\s+(sx|zx)\s+(\d+)', t)
        if m:
            kind = MOD_SXT if m.group(2) == 'sx' else MOD_ZXT
            return self.mk_mod(kind, int(m.group(3))), parse_reg(m.group(1))
        return 0, parse_reg(t)

    def mk_mod(self, kind, amount):
        amt_bits = self.enc.MOD_BITS - 2
        assert 0 <= amount < (1 << amt_bits), f"mod amount {amount} needs >{amt_bits} bits"
        return kind | (amount << 2)

    def imm_fits(self, v, signed=True):
        n = self.enc.IMM_BITS
        if signed: return -(1 << (n-1)) <= v < (1 << (n-1))
        return 0 <= v < (1 << n)

    def enc_imm(self, v, kind, signed=True):
        assert self.imm_fits(v, signed), f"imm {v} does not fit {self.enc.IMM_BITS} bits ({kind})"
        self.imm_log.append((kind, v))
        return v & ((1 << self.enc.IMM_BITS) - 1)

    def li_len(self, v):  # number of instructions `li` expands to
        if -(1 << (self.enc.IMM_BITS-1)) <= v < (1 << (self.enc.IMM_BITS-1)): return 1
        vv = v & ((1 << 128) - 1)
        bits = vv.bit_length()
        n = 1
        while (self.enc.IMM_BITS * n) < bits: n += 1
        return n

    def la_len(self):  # fixed-size 64-bit address synthesis
        n = 1
        while self.enc.IMM_BITS * n < 64: n += 1
        return n

def tokenize_lines(path):
    for ln, raw in enumerate(open(path), 1):
        line = raw.split('#', 1)[0].strip()
        if line: yield ln, line

def assemble(srcs, encname):
    enc = Enc(encname)
    a = Asm(enc)
    # ---- pass 1: label addresses
    labels, items = {}, []   # items: (kind, payload, addr, ln, srcfile)
    addr = 0
    entry = None
    for src in srcs:
        for ln, line in tokenize_lines(src):
            where = f"{src}:{ln}"
            if line.endswith(':'):
                labels[line[:-1].strip()] = addr; continue
            if line.startswith('.'):
                parts = line.split(None, 1)
                d = parts[0]; rest = parts[1] if len(parts) > 1 else ''
                if d == '.org': addr = parse_int(rest)
                elif d == '.entry': entry = rest.strip()
                elif d == '.space':
                    items.append(('space', parse_int(rest), addr, where)); addr += parse_int(rest)
                elif d.startswith('.data'):
                    w = int(d[5:]) // 8
                    vals = [v.strip() for v in rest.split(',')]
                    items.append(('data', (w, vals), addr, where)); addr += w * len(vals)
                else: raise ValueError(f"{where}: unknown directive {d}")
                continue
            # instruction
            mnem = line.split(None, 1)[0].lstrip('(!p0123456789)')
            first = line.split(None, 1)
            op = first[1].split(None, 1)[0] if first[0].startswith('(') else first[0]
            n = 1
            if op == 'li':
                val = parse_int(line.rsplit(',', 1)[1])
                n = a.li_len(val)
            elif op == 'la':
                n = a.la_len()
            items.append(('insn', line, addr, where)); addr += 8 * n
    # ---- pass 2: encode
    chunks = []   # (addr, bytes)
    for kind, payload, iaddr, where in items:
        try:
            if kind == 'space':
                chunks.append((iaddr, bytes(payload)))
            elif kind == 'data':
                w, vals = payload
                out = b''
                for v in vals:
                    x = labels[v] if v in labels else parse_int(v)
                    out += (x & ((1 << (8*w)) - 1)).to_bytes(w, 'little')
                chunks.append((iaddr, out))
            else:
                words = encode_insn(a, payload, iaddr, labels)
                out = b''.join(w.to_bytes(8, 'little') for w in words)
                chunks.append((iaddr, out))
        except Exception as e:
            raise SystemExit(f"{where}: {e}\n  {payload}")
    return chunks, (labels[entry] if entry else 0), a.imm_log

def encode_insn(a, line, addr, labels):
    enc = a.enc
    pred = 0
    m = re.match(r'\((!?)(p\d)\)\s+(.*)', line)
    if m:
        pol = 1 if m.group(1) else 0
        pred = (parse_pred(m.group(2)) << 1) | pol
        line = m.group(3)
    parts = line.split(None, 1)
    op = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ''
    Z = REG_ALIASES['zero']

    def E(major, I=0, **kw):
        return enc.pack(opcode=(MAJOR[major] << 1) | I, pred=pred, **kw)

    def resolve(t):
        t = t.strip()
        if t in labels: return labels[t]
        return parse_int(t)

    # pseudos first
    if op == 'nop':
        return [E('ADD', dst=Z, src1=Z, src2=Z, src3=Z)]
    if op == 'mov':
        d, s = [x.strip() for x in rest.split(',')]
        return [E('ADD', dst=parse_reg(d), src1=parse_reg(s), src2=Z, src3=Z)]
    if op in ('li', 'la'):
        d, s = [x.strip() for x in rest.split(',')]
        rd = parse_reg(d)
        val = resolve(s)
        nints = a.la_len() if op == 'la' else a.li_len(val)
        vv = val & ((1 << 128) - 1)
        # big-endian chunks of IMM_BITS, first via LDI (sign-extended: use
        # zero-leading chunk sequence so sext never corrupts), rest via SHORI
        chunks = []
        x = vv
        for i in range(nints):
            chunks.append(x & ((1 << enc.IMM_BITS) - 1)); x >>= enc.IMM_BITS
        chunks.reverse()
        if nints == 1:
            return [E('LDI', I=1, dst=rd, imm=a.enc_imm(val, 'ldi'))]
        out = [E('LDI', I=1, dst=rd, imm=a.enc_imm(chunks[0], 'ldi', signed=False))]
        # NB: top chunk must not have its sign bit set or LDI sext corrupts;
        # li_len/la_len guarantee one spare bit only when value fits — assert.
        assert chunks[0] < (1 << (enc.IMM_BITS - 1)) or nints * enc.IMM_BITS >= 129, \
            "top chunk sign-extends wrong; widen li"
        for c in chunks[1:]:
            out.append(E('SHORI', I=1, dst=rd, src1=rd, imm=a.enc_imm(c, 'shori', signed=False)))
        return out

    if op in ('iret', 'invtp', 'halt'):
        return [E(op.upper())]
    if op == 'mfsr':
        d, s = [x.strip() for x in rest.split(',')]
        return [E('MFSR', I=1, dst=parse_reg(d), imm=SREGS[s])]
    if op == 'mtsr':
        s, r = [x.strip() for x in rest.split(',')]
        return [E('MTSR', I=1, src1=parse_reg(r), imm=SREGS[s])]
    if op == 'b':
        disp = (resolve(rest) - addr) // 8
        return [E('B', I=1, imm=a.enc_imm(disp, 'branch'))]
    if op == 'jal':
        d, t = [x.strip() for x in rest.split(',')]
        disp = (resolve(t) - addr) // 8
        return [E('JAL', I=1, dst=parse_reg(d), imm=a.enc_imm(disp, 'branch'))]
    if op == 'jalr':
        d, s, i = [x.strip() for x in rest.split(',')]
        return [E('JALR', I=1, dst=parse_reg(d), src1=parse_reg(s),
                  imm=a.enc_imm(parse_int(i), 'jalr_off'))]
    if op == 'ldi':
        d, i = [x.strip() for x in rest.split(',')]
        return [E('LDI', I=1, dst=parse_reg(d), imm=a.enc_imm(resolve(i), 'ldi'))]
    if op == 'shori':
        d, s, i = [x.strip() for x in rest.split(',')]
        return [E('SHORI', I=1, dst=parse_reg(d), src1=parse_reg(s),
                  imm=a.enc_imm(parse_int(i), 'shori', signed=False))]

    if op.startswith('ld') and op.upper() in MAJOR:
        d, mem = rest.split(',', 1)
        base, s2mod, s2, off = parse_mem(a, mem)
        return [E(op.upper(), I=1, dst=parse_reg(d), src1=base, src2=s2,
                  mod=s2mod, imm=a.enc_imm(off, 'ldst_off'))]
    if op.startswith('st') and op.upper() in MAJOR:
        mem, s3 = rest.rsplit(',', 1)
        base, s2mod, s2, off = parse_mem(a, mem)
        return [E(op.upper(), I=1, src1=base, src2=s2, src3=parse_reg(s3),
                  mod=s2mod, imm=a.enc_imm(off, 'ldst_off'))]

    if op.startswith('cmp') and op.upper() in MAJOR:
        p, s1, s2 = [x.strip() for x in rest.split(',')]
        pd = parse_pred(p)
        try:
            mod, r2 = a.parse_src2(s2)
            return [E(op.upper(), dst=pd, src1=parse_reg(s1), src2=r2, mod=mod)]
        except ValueError:
            return [E(op.upper(), I=1, dst=pd, src1=parse_reg(s1),
                      imm=a.enc_imm(parse_int(s2), 'aluimm'))]

    if op.upper() in MAJOR:   # generic ALU, incl. madd
        ops = [x.strip() for x in rest.split(',')]
        rd = parse_reg(ops[0]); rs1 = parse_reg(ops[1])
        s3 = parse_reg(ops[3]) if len(ops) > 3 else Z
        try:
            mod, r2 = a.parse_src2(ops[2])
            return [E(op.upper(), dst=rd, src1=rs1, src2=r2, src3=s3, mod=mod)]
        except ValueError:
            return [E(op.upper(), I=1, dst=rd, src1=rs1, src3=s3,
                      imm=a.enc_imm(parse_int(ops[2]), 'aluimm'))]
    raise ValueError(f"unknown op {op!r}")

def parse_mem(a, t):
    t = t.strip()
    assert t.startswith('[') and t.endswith(']'), f"bad mem operand {t!r}"
    inner = t[1:-1]
    base, s2, mod, off = None, REG_ALIASES['zero'], 0, 0
    for piece in re.split(r'\+(?![^ ]*\])', inner):
        piece = piece.strip()
        if not piece: continue
        try:
            if base is None: base = parse_reg(piece); continue
        except ValueError: pass
        if re.match(r'r\d+|sp|ra|k0|zero', piece) and base is not None and s2 == REG_ALIASES['zero'] \
           and not re.fullmatch(r'-?\d+|0x[0-9a-fA-F]+', piece):
            mod, s2 = a.parse_src2(piece)
        else:
            off += parse_int(piece)
    assert base is not None, f"no base register in {t!r}"
    return base, mod, s2, off

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('srcs', nargs='+')
    ap.add_argument('-o', default='out.img')
    ap.add_argument('--enc', default='A')
    ap.add_argument('--immlog')
    args = ap.parse_args()
    chunks, entry, imm_log = assemble(args.srcs, args.enc)
    with open(args.o, 'w') as f:
        f.write(f"ENTRY {entry:#x}\n")
        for addr, data in chunks:
            if data: f.write(f"@{addr:x} {data.hex()}\n")
    if args.immlog:
        with open(args.immlog, 'a') as f:
            for kind, v in imm_log: f.write(f"{kind} {v}\n")

if __name__ == '__main__':
    main()
