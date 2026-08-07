#!/usr/bin/env python3
"""Sahara disassembler — all encoding facts from encoding.py metadata.

Renders in the assembler's syntax (TOOLING-SPEC 4.3) so disassembly is
directly re-assemblable where the instruction is valid. Never raises on
malformed words: renders `invalid <reason>` instead (traces may contain
fuzzed or trapping words).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import encoding as E  # noqa: E402

# opcode value -> (name, iform, family, operand spec)
OPC_TABLE = {}
for _name, (_val, _fam, _ops) in E.OPCODES.items():
    OPC_TABLE[_val] = (_name, False, _fam, _ops)
    if E.FAMILIES[_fam]["iflag"]:
        OPC_TABLE[_val + 1] = (_name, True, _fam, _ops)

SREG_NAMES = {v: k for k, v in E.SREGS.items()}
CAUSE_NAMES = {v: k for k, v in E.CAUSES.items()}

REG_ALIAS = {28: "sp", 29: "ra", 30: "k0", 31: "zero"}
MOD_KIND_NAMES = {1: "shl", 2: "sxt", 3: "zxt"}

IMM_BITS = E.IMM_BITS


def field(word, name):
    lsb, width = E.FIELDS[name]
    return (word >> lsb) & ((1 << width) - 1)


def sext_imm(v):
    return v - (1 << IMM_BITS) if v >= 1 << (IMM_BITS - 1) else v


def reg(n):
    return f"r{n}"


def imm_str(v):
    return str(v) if -4096 < v < 4096 else hex(v) if v >= 0 \
        else f"-0x{-v:x}"


def mod_operand(word):
    """Render `rN [shl|sxt|zxt AMOUNT]` from src2+mod; None if malformed."""
    src2, mod = field(word, "src2"), field(word, "mod")
    kind, amount = mod & 3, mod >> 2
    if kind == 0:
        return reg(src2) if amount == 0 else None
    return f"{reg(src2)} {MOD_KIND_NAMES[kind]} {amount}"


def width_suffix(fam, wc):
    widths = E.FAMILIES[fam]["widths"]
    if fam in ("ALU", "CMP", "ATOMIC"):
        w = widths[wc]
        if w is None:
            return None
        return "" if w == 128 else f".{w}"
    if fam == "MEM":
        return f".{widths[wc]}"
    if fam == "FP":
        w = widths[wc]
        if w is None:
            return None
        return ".f32" if w == "FP32" else ".f64"
    return ""


def mem_operand(word, with_index=True):
    parts = [reg(field(word, "src1"))]
    if with_index:
        idx = mod_operand(word)
        if idx is None:
            return None
        src2, mod = field(word, "src2"), field(word, "mod")
        if not (src2 == 31 and mod == 0):
            parts.append(idx)
    imm = sext_imm(field(word, "imm"))
    if imm > 0:
        parts.append(imm_str(imm))
    elif imm < 0:
        return "[" + " + ".join(parts) + f" - {imm_str(-imm)}]"
    return "[" + " + ".join(parts) + "]"


INT_FMT = {0: "32", 1: "64", 2: "128"}
FP_FMT = {0: "f32", 1: "f64"}


def target_str(addr, symtab):
    s = symtab.lookup(addr) if symtab else None
    return f"0x{addr:x}" + (f" <{s}>" if s else "")


def disasm(word, pc=None, symtab=None):
    opval = field(word, "opcode")
    entry = OPC_TABLE.get(opval)
    if entry is None:
        return f"invalid opcode=0x{opval:02x}"
    name, iform, fam, ops = entry
    mnem = name.lower()
    pred = field(word, "pred")
    prefix = ""
    if pred != 0:
        prefix = f"({'!' if pred & 1 else ''}p{pred >> 1}) "
    wc = field(word, "width")
    dst, src1 = field(word, "dst"), field(word, "src1")
    src2, src3 = field(word, "src2"), field(word, "src3")
    imm_u = field(word, "imm")
    imm = sext_imm(imm_u)

    if fam in ("ALU", "CMP"):
        sfx = width_suffix(fam, wc)
        if sfx is None:
            return f"invalid {mnem} width={wc}"
        d = f"p{dst & 7}" if ops.startswith("p") else reg(dst)
        if iform:
            b = imm_str(imm)
        else:
            b = mod_operand(word)
            if b is None:
                return f"invalid {mnem} mod=0x{field(word, 'mod'):02x}"
        tail = f", {reg(src3)}" if "3" in ops else ""
        return f"{prefix}{mnem}{sfx} {d}, {reg(src1)}, {b}{tail}"

    if fam == "MEM":
        sfx = width_suffix(fam, wc)
        m = mem_operand(word)
        if m is None:
            return f"invalid {mnem} mod=0x{field(word, 'mod'):02x}"
        if ops == "dm":
            return f"{prefix}{mnem}{sfx} {reg(dst)}, {m}"
        return f"{prefix}{mnem}{sfx} {reg(src3)}, {m}"

    if fam == "MEM128":
        m = mem_operand(word)
        if m is None:
            return f"invalid {mnem} mod=0x{field(word, 'mod'):02x}"
        if ops == "dm":
            return f"{prefix}{mnem} {reg(dst)}, {m}"
        return f"{prefix}{mnem} {reg(src3)}, {m}"

    if fam == "ATOMIC":
        sfx = width_suffix(fam, wc)
        if sfx is None:
            return f"invalid {mnem} width={wc}"
        m = mem_operand(word, with_index=False)
        if ops == "da23":
            return (f"{prefix}{mnem}{sfx} {reg(dst)}, {m}, {reg(src2)}, "
                    f"{reg(src3)}")
        return f"{prefix}{mnem}{sfx} {reg(dst)}, {m}, {reg(src2)}"

    if fam == "CTRL":
        if name == "B":
            if pc is not None:
                return f"{prefix}b {target_str(pc + imm * 8, symtab)}"
            return f"{prefix}b .{imm:+d}"
        if name == "JAL":
            t = target_str(pc + imm * 8, symtab) if pc is not None \
                else f".{imm:+d}"
            return f"{prefix}jal {reg(dst)}, {t}"
        return f"{prefix}jalr {reg(dst)}, {reg(src1)}, {imm_str(imm)}"

    if fam == "CONST":
        if name == "LDI":
            return f"{prefix}ldi {reg(dst)}, {imm_str(imm)}"
        if name == "SHORI":
            return f"{prefix}shori {reg(dst)}, {reg(src1)}, 0x{imm_u:x}"
        # LAP
        if pc is not None:
            return f"{prefix}lap {reg(dst)}, {target_str(pc + imm, symtab)}"
        return f"{prefix}lap {reg(dst)}, .{imm:+d}"

    if fam == "PREDF":
        if name == "PRD":
            return f"{prefix}prd {reg(dst)}"
        return f"{prefix}pwr {reg(src1)}"

    if fam == "SYS":
        if name == "MFSR":
            nm = SREG_NAMES.get(imm_u, str(imm_u))
            return f"{prefix}mfsr {reg(dst)}, {nm}"
        if name == "MTSR":
            nm = SREG_NAMES.get(imm_u, str(imm_u))
            return f"{prefix}mtsr {nm}, {reg(src1)}"
        return f"{prefix}{mnem}"

    if fam == "FP":
        sfx = width_suffix(fam, wc)
        if sfx is None:
            return f"invalid {mnem} width={wc}"
        d = f"p{dst & 7}" if ops.startswith("p") else reg(dst)
        srcs = [reg(src1)]
        if "2" in ops:
            srcs.append(reg(src2))
        if "3" in ops:
            srcs.append(reg(src3))
        return f"{prefix}{mnem}{sfx} {d}, " + ", ".join(srcs)

    if fam == "FCVT":
        sf = field(word, "mod") & 3
        if name in ("FCVTFI", "FCVTFIU"):
            dfmt, sfmt = INT_FMT.get(wc), FP_FMT.get(sf)
        elif name in ("FCVTIF", "FCVTUIF"):
            dfmt = FP_FMT.get(wc)
            sfmt = {0: "i32", 1: "i64", 2: "i128"}.get(sf)
        else:  # FCVTFF
            dfmt, sfmt = FP_FMT.get(wc), FP_FMT.get(sf)
        if dfmt is None or sfmt is None:
            return f"invalid {mnem} width={wc} srcfmt={sf}"
        return f"{prefix}{mnem}.{dfmt} {reg(dst)}, {reg(src1)}, {sfmt}"

    return f"invalid family {fam}"
