#!/usr/bin/env python3
"""Sahara ISA encoding — machine-readable form of ISA-SPEC.md.

ISA-SPEC.md is normative; this file must match it (Appendix A and the field
table of section 3). `python3 encoding.py check` verifies internal
consistency. `python3 encoding.py cheader FILE` emits the C header used by
the emulator, assembler-checker, disassembler, and trace decoder.

Everything the toolchain knows about the encoding comes from here. Nothing
may hardcode a field position or opcode value elsewhere.
"""
import sys

SPEC_VERSION = "1.0-draft"

# ---------------------------------------------------------------- fields
# name -> (lsb, bit width)   (ISA-SPEC section 3)
FIELDS = {
    "opcode": (0, 8),
    "pred":   (8, 4),
    "dst":    (12, 5),
    "src1":   (17, 5),
    "src2":   (22, 5),
    "src3":   (27, 5),
    "mod":    (32, 8),
    "width":  (40, 2),
    "imm":    (42, 22),
}
INSN_BITS = 64
INSN_BYTES = 8
IMM_BITS = FIELDS["imm"][1]

# ------------------------------------------------------------- families
# Family determines width-field meaning (spec 3.4) and operand usage.
#   widths: tuple of meanings for width values 0..3; None = reserved (traps)
FAMILIES = {
    "ALU":    dict(widths=(32, 64, 128, None), iflag=True),
    "CMP":    dict(widths=(32, 64, 128, None), iflag=True),
    "MEM":    dict(widths=(8, 16, 32, 64), iflag=False),
    "MEM128": dict(widths=None, iflag=False),   # width ignored
    "ATOMIC": dict(widths=(32, 64, 128, None), iflag=False),
    "CTRL":   dict(widths=None, iflag=False),
    "CONST":  dict(widths=None, iflag=False),
    "PREDF":  dict(widths=None, iflag=False),
    "SYS":    dict(widths=None, iflag=False),
    "FP":     dict(widths=("FP32", "FP64", None, None), iflag=False),
    "FCVT":   dict(widths="special", iflag=False),  # spec 10.4
}

# -------------------------------------------------------------- opcodes
# name -> (opcode value, family, operands)
# For iflag families the value is the even (register-form) opcode; value+1
# is the immediate form. For all others the odd sibling is reserved.
# operands: which fields the instruction reads/writes (for disasm/trace).
OPCODES = {
    "ILLEGAL": (0x00, "SYS",    ""),
    "ADD":     (0x02, "ALU",    "d1b"),
    "SUB":     (0x04, "ALU",    "d1b"),
    "AND":     (0x06, "ALU",    "d1b"),
    "OR":      (0x08, "ALU",    "d1b"),
    "XOR":     (0x0A, "ALU",    "d1b"),
    "SHL":     (0x0C, "ALU",    "d1b"),
    "SHR":     (0x0E, "ALU",    "d1b"),
    "SAR":     (0x10, "ALU",    "d1b"),
    "MUL":     (0x12, "ALU",    "d1b"),
    "MULH":    (0x14, "ALU",    "d1b"),
    "MULHU":   (0x16, "ALU",    "d1b"),
    "MADD":    (0x18, "ALU",    "d1b3"),
    "UDIV":    (0x1A, "ALU",    "d1b"),
    "SDIV":    (0x1C, "ALU",    "d1b"),
    "UREM":    (0x1E, "ALU",    "d1b"),
    "SREM":    (0x20, "ALU",    "d1b"),
    "CMPEQ":   (0x24, "CMP",    "p1b"),
    "CMPLT":   (0x26, "CMP",    "p1b"),
    "CMPLTU":  (0x28, "CMP",    "p1b"),
    "CMPLE":   (0x2A, "CMP",    "p1b"),
    "CMPLEU":  (0x2C, "CMP",    "p1b"),
    "LDS":     (0x30, "MEM",    "dm"),
    "LDZ":     (0x32, "MEM",    "dm"),
    "LD128":   (0x34, "MEM128", "dm"),
    "ST":      (0x36, "MEM",    "m3"),
    "ST128":   (0x38, "MEM128", "m3"),
    "B":       (0x3A, "CTRL",   "i"),
    "JAL":     (0x3C, "CTRL",   "di"),
    "JALR":    (0x3E, "CTRL",   "d1i"),
    "CAS":     (0x40, "ATOMIC", "da23"),
    "AMOADD":  (0x42, "ATOMIC", "da2"),
    "AMOAND":  (0x44, "ATOMIC", "da2"),
    "AMOOR":   (0x46, "ATOMIC", "da2"),
    "AMOXOR":  (0x48, "ATOMIC", "da2"),
    "AMOSWAP": (0x4A, "ATOMIC", "da2"),
    "AMOMIN":  (0x4C, "ATOMIC", "da2"),
    "AMOMAX":  (0x4E, "ATOMIC", "da2"),
    "AMOMINU": (0x50, "ATOMIC", "da2"),
    "AMOMAXU": (0x52, "ATOMIC", "da2"),
    "LDI":     (0x54, "CONST",  "di"),
    "SHORI":   (0x56, "CONST",  "d1i"),
    "LAP":     (0x58, "CONST",  "di"),
    "PRD":     (0x5A, "PREDF",  "d"),
    "PWR":     (0x5C, "PREDF",  "1"),
    "FADD":    (0x60, "FP",     "d12"),
    "FSUB":    (0x62, "FP",     "d12"),
    "FMUL":    (0x64, "FP",     "d12"),
    "FDIV":    (0x66, "FP",     "d12"),
    "FSQRT":   (0x68, "FP",     "d1"),
    "FMADD":   (0x6A, "FP",     "d123"),
    "FMIN":    (0x6C, "FP",     "d12"),
    "FMAX":    (0x6E, "FP",     "d12"),
    "FCMPEQ":  (0x70, "FP",     "p12"),
    "FCMPLT":  (0x72, "FP",     "p12"),
    "FCMPLE":  (0x74, "FP",     "p12"),
    "FCVTFI":  (0x76, "FCVT",   "d1"),
    "FCVTFIU": (0x78, "FCVT",   "d1"),
    "FCVTIF":  (0x7A, "FCVT",   "d1"),
    "FCVTUIF": (0x7C, "FCVT",   "d1"),
    "FCVTFF":  (0x7E, "FCVT",   "d1"),
    "MFSR":    (0xF0, "SYS",    "di"),
    "MTSR":    (0xF2, "SYS",    "1i"),
    "SYSCALL": (0xF4, "SYS",    ""),
    "IRET":    (0xF6, "SYS",    ""),
    "INVTP":   (0xF8, "SYS",    ""),
    "IFENCE":  (0xFA, "SYS",    ""),
    "WFI":     (0xFC, "SYS",    ""),
    "HALT":    (0xFE, "SYS",    ""),
}
RESERVED_RANGE = (0x80, 0xEF)   # extensions: TM, SIMD, FENCE (spec 13)

# operand-code legend (for disassembler/trace decoder):
#   d dst reg   p dst is predicate (low 3 bits)   1 src1   2 src2   3 src3
#   b src2-or-imm per I-flag   i imm used   m memory ea (src1+mod(src2)+imm)
#   a atomic ea (src1+imm)

# ---------------------------------------------------------------- sregs
SREGS = {
    "status": 0, "epc0": 1, "cause0": 2, "baddr0": 3, "vbase": 4,
    "dfbase": 5, "ptbase": 6, "asid": 7, "cycle": 8, "timecmp": 9,
    "scratch0": 10, "scratch1": 11, "epc1": 12, "cause1": 13, "baddr1": 14,
    "fcsr": 15,
}
SREG_USER_OK = {"cycle": "r", "fcsr": "rw"}   # everything else S-only

STATUS_BITS = {"IE": 0, "PIE": 1, "MMU_EN": 2, "S": 3, "PS": 4, "TL_LSB": 5}
TL_BITS = 2

# --------------------------------------------------------------- causes
CAUSES = {
    "TIMER": 0, "EXTINT": 1,
    "PF_FETCH": 2, "PF_LOAD": 3, "PF_STORE": 4,
    "PERM_FETCH": 5, "PERM_LOAD": 6, "PERM_STORE": 7,
    "ILLEGAL": 8, "UNALIGNED": 9, "SYSCALL": 10, "PRIV": 11, "DEVERR": 12,
}

# ------------------------------------------------------------------ MMU
PAGE_BITS = 16                      # 64 KB pages
VPN_BITS = 128 - PAGE_BITS          # 112
CHUNK_BITS = 8
NODE_HEADER_BYTES = 64
NODE_ENTRIES = 1 << CHUNK_BITS
NODE_ENTRY_BYTES = 16
NODE_BYTES = NODE_HEADER_BYTES + NODE_ENTRIES * NODE_ENTRY_BYTES  # 4160
NODE_ALIGN = 64
PTE_TYPE_INVALID, PTE_TYPE_TABLE, PTE_TYPE_LEAF = 0, 1, 2
PTE_BITS = {"R": 2, "W": 3, "X": 4, "U": 5}

# ---------------------------------------------------------------- misc
RESET_PC = 0x1000
FCSR_FLAG_BITS = {"NV": 0, "DZ": 1, "OF": 2, "UF": 3, "NX": 4}
FCSR_RM_LSB, FCSR_RM_BITS = 5, 3
ROUNDING = {"RNE": 0, "RTZ": 1, "RDN": 2, "RUP": 3, "RMM": 4}


# ---------------------------------------------------------------- check
def check():
    errs = []
    # field layout covers exactly 64 bits, no overlap
    bits = [None] * INSN_BITS
    for name, (lsb, w) in FIELDS.items():
        for b in range(lsb, lsb + w):
            if b >= INSN_BITS or bits[b] is not None:
                errs.append(f"field overlap/overflow at bit {b} ({name})")
                break
            bits[b] = name
    if None in bits:
        errs.append(f"uncovered bits: {[i for i, v in enumerate(bits) if v is None]}")
    # opcode uniqueness, evenness, pairing, reserved range
    seen = {}
    for name, (val, fam, _ops) in OPCODES.items():
        if fam not in FAMILIES:
            errs.append(f"{name}: unknown family {fam}")
            continue
        if name != "ILLEGAL" and val % 2 != 0:
            errs.append(f"{name}: opcode 0x{val:02X} not even")
        occupied = [val, val + 1] if FAMILIES[fam]["iflag"] else [val]
        for v in occupied:
            if v in seen:
                errs.append(f"opcode 0x{v:02X} assigned to both {seen[v]} and {name}")
            seen[v] = name
        if RESERVED_RANGE[0] <= val <= RESERVED_RANGE[1]:
            errs.append(f"{name}: opcode 0x{val:02X} in reserved range")
    if 0x00 not in seen or seen[0x00] != "ILLEGAL":
        errs.append("opcode 0x00 must be ILLEGAL")
    # sreg indices unique and dense-ish
    if len(set(SREGS.values())) != len(SREGS):
        errs.append("duplicate sreg index")
    if len(set(CAUSES.values())) != len(CAUSES):
        errs.append("duplicate cause code")
    if NODE_BYTES != 4160:
        errs.append(f"node size {NODE_BYTES} != 4160")
    return errs


# -------------------------------------------------------------- cheader
def cheader(out):
    L = []
    A = L.append
    A("/* Generated by encoding.py — DO NOT EDIT.")
    A(f" * Sahara ISA {SPEC_VERSION}. Normative source: ISA-SPEC.md. */")
    A("#ifndef SAHARA_ISA_H")
    A("#define SAHARA_ISA_H")
    A("")
    A(f"#define SAHARA_INSN_BYTES {INSN_BYTES}")
    A(f"#define SAHARA_IMM_BITS   {IMM_BITS}")
    A(f"#define SAHARA_RESET_PC   0x{RESET_PC:X}u")
    A("")
    A("/* --- instruction fields: F_<name>_LSB / _BITS / _MASK(insn) --- */")
    for name, (lsb, w) in FIELDS.items():
        up = name.upper()
        A(f"#define F_{up}_LSB  {lsb}")
        A(f"#define F_{up}_BITS {w}")
        A(f"#define F_{up}(x)   (((x) >> {lsb}) & ((1ull << {w}) - 1))")
    A("")
    A("/* --- opcodes (even value; +1 = immediate form where OPC_HAS_I) --- */")
    for name, (val, fam, _o) in sorted(OPCODES.items(), key=lambda kv: kv[1][0]):
        A(f"#define OPC_{name:<8} 0x{val:02X}")
    A("")
    A("/* per-opcode metadata table, indexed by full 8-bit opcode value */")
    A("typedef struct { const char *name; unsigned char valid, iflag_form,")
    A("                 family; const char *operands; } sahara_opc_info;")
    fam_ids = {f: i for i, f in enumerate(FAMILIES)}
    for f, i in fam_ids.items():
        A(f"#define FAM_{f} {i}")
    A("static const sahara_opc_info sahara_opc[256] = {")
    table = {}
    for name, (val, fam, ops) in OPCODES.items():
        table[val] = (name, 0, fam, ops)
        if FAMILIES[fam]["iflag"]:
            table[val + 1] = (name, 1, fam, ops)
    for v in range(256):
        if v in table:
            name, iform, fam, ops = table[v]
            A(f'  [0x{v:02X}] = {{"{name}", 1, {iform}, FAM_{fam}, "{ops}"}},')
    A("};")
    A("")
    A("/* --- width decode per family: value -> bits (0 = reserved/ignored) */")
    A("static const unsigned short sahara_width[][4] = {")
    for f in FAMILIES:
        wt = FAMILIES[f]["widths"]
        if wt is None or wt == "special":
            row = "{0, 0, 0, 0}"
        else:
            row = "{" + ", ".join(
                "0" if x is None else ("32" if x == "FP32" else "64" if x == "FP64" else str(x))
                for x in wt) + "}"
        A(f"  [FAM_{f}] = {row},")
    A("};")
    A("")
    A("/* --- special registers --- */")
    for name, idx in SREGS.items():
        A(f"#define SREG_{name.upper():<8} {idx}")
    A("")
    A("/* --- status bits --- */")
    for name, b in STATUS_BITS.items():
        A(f"#define STATUS_{name:<7} (1ull << {b})" if not name.endswith("LSB")
          else f"#define STATUS_{name} {b}")
    A(f"#define STATUS_TL_BITS {TL_BITS}")
    A("")
    A("/* --- cause codes --- */")
    for name, c in CAUSES.items():
        A(f"#define CAUSE_{name:<11} {c}")
    A("")
    A("/* --- MMU --- */")
    A(f"#define PAGE_BITS   {PAGE_BITS}")
    A(f"#define CHUNK_BITS  {CHUNK_BITS}")
    A(f"#define NODE_BYTES  {NODE_BYTES}")
    A(f"#define NODE_ALIGN  {NODE_ALIGN}")
    A(f"#define NODE_HEADER_BYTES {NODE_HEADER_BYTES}")
    A(f"#define PTE_INVALID {PTE_TYPE_INVALID}")
    A(f"#define PTE_TABLE   {PTE_TYPE_TABLE}")
    A(f"#define PTE_LEAF    {PTE_TYPE_LEAF}")
    for name, b in PTE_BITS.items():
        A(f"#define PTE_{name} (1u << {b})")
    A("")
    A("/* --- fcsr --- */")
    for name, b in FCSR_FLAG_BITS.items():
        A(f"#define FCSR_{name} (1u << {b})")
    A(f"#define FCSR_RM_LSB {FCSR_RM_LSB}")
    for name, v in ROUNDING.items():
        A(f"#define RM_{name} {v}")
    A("")
    A("#endif /* SAHARA_ISA_H */")
    with open(out, "w") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    errs = check()
    if sys.argv[1:2] == ["check"]:
        for e in errs:
            print("FAIL:", e)
        print("OK" if not errs else f"{len(errs)} errors")
        sys.exit(1 if errs else 0)
    if errs:
        sys.exit("encoding inconsistent; run `encoding.py check`")
    if sys.argv[1:2] == ["cheader"]:
        cheader(sys.argv[2])
        print(f"wrote {sys.argv[2]}")
    else:
        sys.exit("usage: encoding.py check | cheader FILE")
