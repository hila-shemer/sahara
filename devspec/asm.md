# Sahara Assembler — Detailed Specification

**Version 1.0-draft, devspec layer.** Companion to TOOLING-SPEC.md section 4,
which is frozen and authoritative; this document expands it to full
implementability. Where this document states something TOOLING-SPEC.md,
ISA-SPEC.md, PLATFORM-SPEC.md, or `encoding.py` already state, those documents
win. Everything encoding-shaped (field positions, opcode values, register and
sreg names, cause codes) is defined by `encoding.py`; the assembler must
consume `encoding.py` or its generated header as its sole source of that data
and may not hardcode any of it. The worked examples in this document are
derived from `encoding.py` and are test fixtures, not definitions.

Non-normative rationale appears in indented *Note:* lines. Everything else is
normative.

---

## 1. Invocation and outputs

The assembler is the command `sasm`:

    sasm [-o OUT.img] IN1.s [IN2.s ...]

- Inputs are concatenated in command-line order into one assembly unit
  (TOOLING-SPEC 4: two passes, no linker in v1.0).
- `-o` names the image output. Default: the first input's basename with the
  extension replaced by `.img`.
- The symbol sidecar is always written next to the image: the image path with
  `.img` replaced by `.sym` (appended if the image path does not end in
  `.img`).
- Exit codes: `0` success; `1` any assembly error; `2` usage or I/O error
  (missing input, unwritable output, bad flags).
- On any assembly error, **no output file is written** and any partially
  written output is removed. Errors are fatal; there are no warnings
  (TOOLING-SPEC 4.6).
- Error message format, one line per error on stderr, first error is
  sufficient (the assembler may stop at the first error; if it continues, all
  reported errors must use this format):

      FILE:LINE: Ennn: message

  `FILE` is the input path as given on the command line, `LINE` is 1-based,
  `Ennn` is a code from the catalog in section 10.
- Output is deterministic: the same inputs in the same order produce
  byte-identical `.img` and `.sym` files on every run and every host.

---

## 2. Lexical structure

Input is a byte stream interpreted as ASCII; bytes ≥ 0x80 outside string and
character literals are erroneous (E001). Processing is line-oriented: lines
end at LF; a final line without LF is accepted; CR immediately before LF is
stripped (CRLF tolerated).

### 2.1 Tokens

| token | rule |
|-------|------|
| whitespace | spaces and tabs; separates tokens, otherwise ignored |
| comment | `#` up to end of line, ignored. A `#` inside a string or character literal is literal text. Strings are scanned before comment stripping. |
| identifier | `[A-Za-z_][A-Za-z0-9_.$]*` (the `.sym` name charset of TOOLING-SPEC 2). Mnemonic width suffixes (`add.32`) are part of the identifier token; the split into base mnemonic and suffix happens at parse time. |
| directive | `.` immediately followed by an identifier, in statement position (`.org`, `.byte`, ...) |
| number | `0x[0-9A-Fa-f]+` hex, `0b[01]+` binary, `[0-9]+` decimal. Prefixes case-insensitive. No sign (use unary `-`), no digit separators. A number too large for 128 bits is E002. |
| character literal | `'c'` or `'\e'` with the escapes of 2.2; value is the single byte, 0–255. Empty or multi-character literals are E005. |
| string literal | `"..."` with the escapes of 2.2, only as the operand of `.ascii`/`.asciiz`. Unterminated at end of line is E003. |
| punctuation | `,` `:` `(` `)` `[` `]` `+` `-` `*` `!` |

Any other byte is E001.

### 2.2 Escapes (strings and character literals)

C escapes, exactly this set: `\n` (0x0A), `\t` (0x09), `\r` (0x0D), `\b`
(0x08), `\f` (0x0C), `\0` (0x00), `\\`, `\"`, `\'`, and `\xHH` with exactly
two hex digits. Any other `\` sequence is E004.

### 2.3 Case sensitivity and reserved names

Mnemonics, pseudo-mnemonics, directives, register names and aliases,
predicate register names, sreg names, the modifier keywords `shl`/`sxt`/
`zxt`, and the conversion format tokens `f32 f64 i32 i64 i128` are all
case-insensitive (`ADD.32`, `Sp`, `STATUS` are valid). Labels and `.equ`
names are case-sensitive (`Loop` and `loop` are distinct symbols).

**Reserved names.** A user symbol (label or `.equ` name) whose spelling
case-insensitively equals any of the following is an error (E032):

- `r0`–`r31`, `sp`, `ra`, `k0`, `zero`
- `p0`–`p7`
- the sreg names of `encoding.py` (`status`, `epc0`, `cause0`, `baddr0`,
  `vbase`, `dfbase`, `ptbase`, `asid`, `cycle`, `timecmp`, `scratch0`,
  `scratch1`, `epc1`, `cause1`, `baddr1`, `fcsr`)
- every mnemonic of `encoding.py`, with or without any of its valid width
  suffixes (`add`, `add.32`, `lds.8`, `fadd.f64`, ...)
- the pseudo-mnemonics `li`, `la`, `la.abs`, `mov`, `nop`, `not`, `neg`,
  `ret`
- `shl`, `sxt`, `zxt`, `f32`, `f64`, `i32`, `i64`, `i128`

### 2.4 Registers and names

`r0`–`r31`; aliases `sp` = r28, `ra` = r29, `k0` = r30, `zero` = r31
(TOOLING-SPEC 4.2, ISA-SPEC 12). Predicates `p0`–`p7`. `r32`, `p8`, etc. are
not registers; where a register is required they are E012/E013.

---

## 3. Grammar

EBNF. Terminals in quotes; `IDENT NUMBER CHARLIT STRING` are the tokens of
2.1; `EOL` is end of line. Whitespace between tokens is implicit.

    program     = { line } ;
    line        = { labeldef } [ statement ] [ comment ] EOL ;
    labeldef    = IDENT ":" ;
    statement   = instruction | directive ;

    instruction = [ predication ] mnemonic [ operand { "," operand } ] ;
    predication = "(" [ "!" ] preg ")" ;
    mnemonic    = IDENT ;                    (* base name + optional width
                                                suffix, split per section 5 *)
    operand     = memop | reg [ modspec ] | preg | fmt | expr ;
    modspec     = ( "shl" | "sxt" | "zxt" ) expr ;
    memop       = "[" reg [ "+" reg [ modspec ] ]
                      [ ( "+" | "-" ) expr ] "]" ;
    reg         = "r0" .. "r31" | "sp" | "ra" | "k0" | "zero" ;
    preg        = "p0" .. "p7" ;
    fmt         = "f32" | "f64" | "i32" | "i64" | "i128" ;

    directive   = ".org"    expr
                | ".entry"  IDENT
                | ".align"  expr
                | ".byte"   expr { "," expr }
                | ".half"   expr { "," expr }
                | ".word"   expr { "," expr }
                | ".quad"   expr { "," expr }
                | ".oct"    expr { "," expr }
                | ".ascii"  STRING
                | ".asciiz" STRING
                | ".space"  expr
                | ".equ"    IDENT "," expr ;

    expr        = term  { ( "+" | "-" ) term } ;
    term        = factor { "*" factor } ;
    factor      = NUMBER | CHARLIT | IDENT | "(" expr ")"
                | ( "-" | "+" ) factor ;

Which `operand` alternatives are legal in which position is fixed per
mnemonic by the operand-shape tables of sections 5–7; a mismatch is
E011/E012/E013/E014/E027 as applicable. Multiple `labeldef`s on one line each
define the current location. An unknown mnemonic or directive in statement
position is E010.

---

## 4. Expressions and symbols

### 4.1 Arithmetic

Expressions evaluate in 128-bit two's-complement arithmetic; overflow wraps
modulo 2^128. Operators: binary `+ - *`, unary `+ -`, parentheses. There is
no division, shift, or bitwise operator in v1.0. Precedence, high to low:
unary `+ -`; `*`; binary `+ -`. Binary operators associate left.

Operands: numbers, character literals, symbols (labels and `.equ` names).

### 4.2 Value kinds and label arithmetic

Every expression result has a kind, **CONST** or **ADDR**:

- numbers and character literals are CONST; labels are ADDR; an `.equ` name
  has the kind of its defining expression;
- ADDR − ADDR = CONST (legal across segments; all addresses are absolute
  PAs);
- ADDR ± CONST = ADDR; CONST + ADDR = ADDR;
- CONST op CONST = CONST;
- ADDR + ADDR, ADDR * anything, anything * ADDR, unary `-` on ADDR, and
  CONST − ADDR are E033.

An expression result is range-checked against the context that consumes it
(field width, directive size); a value that does not fit is an error, never
truncated (E020/E021/E035). This is the normative reading of TOOLING-SPEC
4.5 "labels only in contexts wide enough to hold them": a label-valued
result is legal anywhere its *value* passes the context's range check.

### 4.3 Symbols

- A label `name:` defines `name` as the current location (ADDR). Definition
  before the first `.org` is E041. Duplicate definition of any symbol is
  E031.
- `.equ NAME, expr` defines `NAME` with the expression's value and kind.
  Redefinition is E031.
- An undefined symbol referenced anywhere is E030 (reported even if the
  referencing instruction is predicated).
- A reserved name (2.3) appearing in expression context is not a symbol
  reference and cannot resolve to one; it is E030 (registers and keywords
  have no value in expressions).

### 4.4 Assembly-time-constant contexts

The following contexts must be evaluable during pass 1 at the point of use:
`.org`, `.align`, `.space`, modifier amounts (`shl`/`sxt`/`zxt` N), the
`li` operand, and repeat/size arguments generally. In these contexts the
expression must (a) contain no label, directly or through `.equ` chains, and
(b) reference only symbols textually defined earlier in the input. Violation
is E034. All other operand contexts (instruction immediates, branch targets,
data directive values) are evaluated in pass 2 and may reference any symbol,
forward or backward.

---

## 5. Instruction assembly

### 5.1 General form

    [(pred)] MNEMONIC[.SUFFIX] operands

Fields not used by an instruction are emitted as zero (ISA-SPEC 3). The one
systematic exception-by-design: the index register of a load/store effective
address is architecturally always read (`ea = R[src1] + mod(R[src2]) +
sext(imm22)`), so an omitted index term encodes `src2 = 31` (the zero
register) with `mod = 0` — see 5.5. Instructions are 8 bytes, little-endian,
and must land on an 8-byte-aligned location; emitting an instruction at a
misaligned location is E043.

### 5.2 Predication prefix

`(pN)` = execute-when-true, `(!pN)` = execute-when-false, N in 0–7. The pred
field is `(N << 1) | polarity` with polarity 1 for `!`. No prefix encodes
pred = 0 (p0, positive — always execute). The prefix is legal on every
instruction and every pseudo; on a pseudo it is applied to **every**
instruction of the expansion (the expansions in section 6 only write `rd`,
so an all-squashed chain is equivalent to a squashed single instruction).
A malformed prefix is E017.

### 5.3 Width suffixes

| mnemonic class | suffix | width field |
|---|---|---|
| ALU (`add sub and or xor shl shr sar mul mulh mulhu madd udiv sdiv urem srem`) and compare (`cmpeq cmplt cmpltu cmple cmpleu`) and atomic (`cas amoadd amoand amoor amoxor amoswap amomin amomax amominu amomaxu`) | optional `.32` / `.64` / `.128`; none = 128 | 0 / 1 / 2 |
| `lds`, `ldz`, `st` | mandatory `.8` / `.16` / `.32` / `.64` | 0 / 1 / 2 / 3 |
| `ld128`, `st128` | none (distinct opcodes; width ignored, emitted 0) | 0 |
| FP arithmetic (`fadd fsub fmul fdiv fsqrt fmadd fmin fmax`) and FP compare (`fcmpeq fcmplt fcmple`) | mandatory `.f32` / `.f64` | 0 / 1 |
| `fcvtfi`, `fcvtfiu` | mandatory `.32` / `.64` / `.128` (integer destination) | 0 / 1 / 2 |
| `fcvtif`, `fcvtuif`, `fcvtff` | mandatory `.f32` / `.f64` (FP destination) | 0 / 1 |
| everything else (`b jal jalr ldi shori lap prd pwr mfsr mtsr syscall iret invtp ifence wfi halt`) | none allowed | 0 |

A suffix a mnemonic does not take, or an invalid one, is E015. A missing
mandatory suffix is E016.

### 5.4 ALU and compare operands; the I-flag

- Register form: `add rd, rs1, rs2` — third operand a register, optionally
  with a modifier: `add rd, rs1, rs2 shl 3`, `... sxt N`, `... zxt N`.
  Opcode = the even value from `encoding.py`; `mod` = `(amount << 2) | kind`
  with kind 1 = shl, 2 = sxt, 3 = zxt; no modifier = mod 0. Amount is an
  assembly-time constant in 0–63, else E024. (`sxt 0` / `zxt 0` are legal
  no-ops per ISA-SPEC 3.3; shifts ≥ 64 are inexpressible in `mod` — use the
  `shl` instruction.)
- Immediate form: `add rd, rs1, expr` — third operand an expression. Opcode
  = even value + 1 (the I-form). The value must fit signed 22 bits,
  [−2^21, 2^21−1], else E020. A modifier after an immediate is a parse
  error (E019): the `mod` field is ignored in I-forms and the assembler
  emits it as 0.
- The assembler selects the form purely by the syntactic class of the third
  operand: register token → register form, anything else → immediate form.
- `madd` takes four operands: `madd rd, rs1, rs2|imm, rs3` (dst = rs1 * b +
  rs3); the third operand chooses the I-form exactly as above.
- Compares write a predicate: `cmplt p3, rs1, rs2|imm`. The `dst` field is
  the predicate index (0–7); its upper two bits are emitted 0. `p0` is a
  legal destination (the write is discarded by hardware).

### 5.5 Loads and stores

    lds.W  rd, [base + index mod + disp]     W in 8/16/32/64
    ldz.W  rd, [base + index mod + disp]
    ld128  rd, [ ... ]
    st.W   [ ... ], rs        (data register last)
    st128  [ ... ], rs

Memory operand: base register required; then optionally `+ index-register`
(with optional modifier); then optionally `+ expr` or `- expr` (displacement;
`- e` means displacement `−e`). Exactly this order; the displacement fits
signed 22 bits (E020). Field mapping: base → src1, index → src2 (or 31 if
omitted), modifier → mod (or 0), displacement → imm (or 0), data register of
stores → src3, dst of stores emitted 0. A malformed operand — missing base,
two index registers, index after displacement — is E014.

### 5.6 Atomics

    cas.W     rd, [base + disp], rexpected, rnew
    amoOP.W   rd, [base + disp], rs

W in 32/64/none(=128). The atomic effective address is `R[src1] +
sext(imm22)` only (ISA-SPEC 5.4): an index register inside the brackets is
E014. Mapping: base → src1, disp → imm, `rexpected` → src2 and `rnew` → src3
(CAS), `rs` → src2 (AMO); mod emitted 0. An immediate where `rexpected`,
`rnew`, or `rs` belongs is E027.

### 5.7 Control flow

    b     target
    (pN) b target
    jal   rd, target
    jal   target            (= jal ra, target)
    jalr  rd, rs1, disp

`target` is an expression (ADDR or CONST) giving the destination **byte
address**. For `b`/`jal` the assembler computes `delta = target − pc_of_this_
instruction`; `delta` must be a multiple of 8 (else E022) and `delta/8` must
fit signed 22 bits (else E023); `imm = delta/8` (displacements count
instructions, ISA-SPEC 5.5). For `jalr`, `disp` is a byte-offset expression
fitting signed 22 bits (E020); target alignment is a runtime matter
(UNALIGNED trap), not checked at assembly. `b` writes no register (dst
emitted 0).

### 5.8 Constants and addresses

    ldi   rd, expr          imm = expr, signed 22-bit (E020)
    shori rd, rs1, expr     imm = expr, unsigned 22-bit [0, 2^22−1] (E021)
    lap   rd, target        imm = target − pc, byte delta, signed 22-bit (E023)

`lap`'s operand is the target byte address (symmetric with `b`/`jal`), not a
raw immediate; the assembler encodes the pc-relative delta. No multiple-of-8
requirement (LAP is byte-granular).

### 5.9 Predicate file and system

    prd  rd                 dst = rd
    pwr  rs                 src1 = rs
    mfsr rd, SREG           dst = rd, imm = sreg index
    mtsr SREG, rs           src1 = rs, imm = sreg index
    syscall | iret | invtp | ifence | wfi | halt      (no operands)

`SREG` is a sreg name from `encoding.py` or a CONST expression in
[0, 2^21−1]; anything else is E026. In this operand position E026 takes
precedence over the general expression errors: a lone identifier that is
neither a sreg name nor a defined CONST symbol reports E026, not E030. Numeric indices beyond 15 are
deliberately assemblable so conformance tests can exercise the ILLEGAL trap
on unlisted indices (ISA-SPEC 2.3). `invtp` takes no operand and emits
imm = 0 (ISA-SPEC 5.8: other values reserved). All-zero unused fields apply
(a bare `syscall` is the 64-bit value 0x00000000000000F4).

### 5.10 Conversions

    fcvtfi.W   rd, rs1, SRC      W in 32/64/128,  SRC in f32/f64
    fcvtfiu.W  rd, rs1, SRC      same
    fcvtif.FW  rd, rs1, SRC      FW in f32/f64,   SRC in i32/i64/i128
    fcvtuif.FW rd, rs1, SRC      same
    fcvtff.FW  rd, rs1, SRC      FW in f32/f64,   SRC in f32/f64, SRC ≠ FW

The width field encodes the destination format, `mod` bits 1:0 the source
format (codes 0 = 32-bit, 1 = 64-bit, 2 = 128-bit integer-only; ISA-SPEC
10.4); `mod` bits 7:2 are emitted 0. The assembler rejects at assembly time
every combination the ISA traps ILLEGAL on: an integer source token on
`fcvtfi`/`fcvtfiu`, an FP source on `fcvtif`/`fcvtuif`, `i128`-as-FP,
`fcvtff` with SRC = FW — all E025. (Programs that want the runtime trap
emit the raw encoding with `.quad`.)

### 5.11 FP operand restriction

FP arithmetic and FP compares are register-only (ISA-SPEC 10.2): an
immediate operand there is E027. No `mod` syntax is accepted on FP operands
(E019); mod is emitted 0 except as used by conversions (5.10).

---

## 6. Pseudo-instructions

All pseudos expand to base instructions before encoding; the listed
expansions are normative and exact (byte-for-byte, so `.sym`/trace tooling
sees ordinary instructions). A predication prefix distributes over every
expanded instruction (5.2).

### 6.1 `li rd, expr` — load immediate, minimal chain

The operand must be an assembly-time constant (4.4); a label-dependent
operand is E029 (use `la`/`la.abs`). Let `V` = value mod 2^128. Chain
selection:

1. For n = 1, 2, 3, 4, 5 in order: let W = 22·n. If sign-extending the low
   W bits of V from bit W−1 to 128 bits reproduces V exactly, select n and
   stop.
2. Otherwise n = 6.

Emit, with chunk `c_i = (V >> 22·i) & 0x3FFFFF`:

    ldi   rd, c_{n−1}            (imm field = c_{n−1} verbatim)
    shori rd, rd, c_{n−2}
    ...
    shori rd, rd, c_0

This is minimal: LDI sign-extends, each SHORI appends 22 low bits, and the
result equals sign-extension of the 22n-bit chunk string, which by the
selection rule equals V (n = 6 always works because 132 ≥ 128 and excess
high bits shift out). `li rd, 0` is a single `ldi rd, 0`.

### 6.2 `la rd, label-expr` — load address, position-independent

The operand is any ADDR-valued expression. Let `delta = target −
pc_of_the_LAP`. Two forms:

- **1 instruction** when −2^21 ≤ delta ≤ 2^21−1:  `lap rd, target`.
- **2 instructions** otherwise: with `d1 = clamp(delta, −2^21, 2^21−1)` and
  `d2 = delta − d1`:

      lap rd, (pc + d1)          imm = d1
      add rd, rd, d2             I-form, width 128, imm = d2

  If `d2` does not fit signed 22 bits (i.e. delta outside
  [−2^22, 2^22−2]), the position-independent form is out of range: E028,
  whose message directs the user to `la.abs`.

**Form selection is by relaxation, so the frozen rule "LAP if the label is
within ±2 MB of the LAP itself" holds exactly:** during pass 1 every `la` is
provisionally 1 instruction (8 bytes); addresses are assigned; any `la`
whose delta (computed from current addresses) is out of the 1-instruction
range is promoted to 2 instructions (16 bytes); promotion is sticky
(never reverted); addresses are recomputed and the step repeats until no
promotion occurs. Growth only increases within-segment distances (segment
bases are fixed by `.org`), so any `la` whose final delta is in range stays
1 instruction, and the process terminates in at most (number of `la`s)
iterations. The fixed point is unique and deterministic.

### 6.3 `la.abs rd, label-expr` — absolute address

Always the full 6-instruction `ldi` + 5×`shori` chain (fixed length, so
pass-1 layout never depends on the address value) encoding the target's
absolute 128-bit value per the chunk rule of 6.1 with n = 6. Not
position-independent.

### 6.4 One-instruction pseudos

| pseudo | expansion |
|--------|-----------|
| `nop` | `or zero, zero, zero` (width 128) |
| `mov rd, rs` | `or rd, rs, zero` (width 128) |
| `not[.W] rd, rs` | `xor[.W] rd, rs, -1` (I-form, imm = −1) |
| `neg[.W] rd, rs` | `sub[.W] rd, zero, rs` (register form, src1 = 31) |
| `ret` | `jalr zero, ra, 0` |
| `jal target` (bare) | `jal ra, target` |
| `sub rd, imm, rs` (immediate-first operand order) | legal only when `imm` evaluates to 0: `sub rd, zero, rs` (≡ `neg`). Any other value is E036 — the ISA has no reverse-subtract, so no one-instruction expansion exists; the message directs the user to an explicit `li`/`sub` or `neg`/`add` sequence. |

`not`/`neg` accept the ALU width suffixes of 5.3 and pass them through.

---

## 7. Directives, segments, and layout

### 7.1 `.org PA`

Closes the current segment (if any) and opens a new one whose load address
is `PA` (assembly-time constant, ≥ 0, < 2^128; E034/E035). The location
counter becomes `PA`. Emitting anything — instructions, data, `.align`
padding, `.space` — before the first `.org` is E040; defining a label before
the first `.org` is E041. `.equ` and `.entry` are legal anywhere.

### 7.2 Data directives

| directive | effect |
|-----------|--------|
| `.byte v, ...` | 1 byte per value |
| `.half v, ...` | 2 bytes per value, little-endian |
| `.word v, ...` | 4 bytes per value, little-endian |
| `.quad v, ...` | 8 bytes per value, little-endian |
| `.oct v, ...`  | 16 bytes per value, little-endian |
| `.ascii "s"`   | the string's bytes, no terminator |
| `.asciiz "s"`  | the string's bytes plus one 0x00 |
| `.space N`     | N zero bytes (N an assembly-time constant ≥ 0) |
| `.align N`     | zero bytes up to the next multiple of N; N an assembly-time constant, a power of two ≥ 1, else E044 |

Each value `v` of an n-byte directive must lie in
[−2^(8n−1), 2^(8n)−1] — the union of the signed and unsigned n-byte ranges —
else E035; it is stored as its value mod 2^(8n). Data directives perform no
implicit alignment. `.align` padding is zero bytes; in code this decodes as
opcode 0x00 = ILLEGAL, which faults loudly if executed (intended).

### 7.3 `.equ NAME, expr`

Defines `NAME` (section 4.3). Emits nothing.

### 7.4 `.entry LABEL`

Sets the image header's `entry` field to the address of `LABEL` (which may
be defined anywhere in the input, forward references allowed). At most one
`.entry`; a second, or an undefined label, is E046. If absent, entry =
0x1000 (the reset PC, `encoding.py` RESET_PC). The entry address must be
8-aligned (E047) and must lie inside some segment's [load_pa, load_pa +
mem_len) (E048).

### 7.5 Segment layout rules (checked after pass 2)

- A segment's extent is [load_pa, load_pa + mem_len), where mem_len is the
  total bytes the location counter advanced in it.
- A segment that emitted zero bytes is E045 (a `.org` immediately followed
  by another `.org` or end of input; a labels-only segment is also empty —
  use `.space` for reserved regions).
- Segment extents must be pairwise disjoint, and disjoint from the device
  table window [0x0800, 0x1000) — 2 KB at PA 0x0800 per PLATFORM-SPEC 1/2
  and TOOLING-SPEC 1. Any overlap is E042.
- Some segment must cover the reset PC 0x1000 (the reference boot flow
  requirement of TOOLING-SPEC 1, enforced loudly), else E049.

---

## 8. Passes and image generation

### 8.1 Pass structure

**Pass 1**: lex and parse every line; define symbols; expand pseudo sizes
(`li` from its constant, `la` by the relaxation of 6.2, `la.abs` fixed 6);
assign every statement an address; record segment boundaries. **Pass 2**:
evaluate all remaining expressions, select I-forms, range-check every field,
encode instructions, emit data bytes; then run the layout checks of 7.5 and
write outputs.

### 8.2 `.img` emission

Per TOOLING-SPEC 1. Header: magic bytes `53 41 48 49 4D 47 30 31`
("SAHIMG01"), entry u128, nsegs u64. Segment descriptors follow in **source
order** (order of `.org` appearance), 48 bytes each; payloads follow the
descriptor table, packed in the same order with no padding, so the first
segment's `file_off` = 32 + 48·nsegs (the TOOLING-SPEC 1 header is 32
bytes: magic u64, entry u128, nsegs u64). Per segment:

- `load_pa` = the `.org` address; `mem_len` = full segment size;
- `file_len` = mem_len minus the trailing run of zero bytes (i.e. index of
  the last non-zero byte + 1; 0 if the segment is all zero). The loader
  zero-fills [file_len, mem_len), reproducing the bytes exactly;
- `flags` = 0; file bytes = the segment's first `file_len` bytes.

### 8.3 `.sym` emission

Per TOOLING-SPEC 2. One line per symbol, LF-terminated:

    <addr:32 lowercase hex digits> <kind> <name>

- Every label gets a row: `addr` = its 128-bit address zero-padded to 32
  digits; kind `T` if the first item emitted at or after the label's
  location in its segment is an instruction (or pseudo expansion), `D`
  otherwise (data directive, or nothing follows).
- Every CONST-kind `.equ` gets a row: kind `A`, `addr` = its value mod
  2^128. ADDR-kind `.equ`s (address aliases) get no row — they are not
  labels, and `A` is documented as non-address (TOOLING-SPEC 2).
- Rows sorted ascending by the addr field, ties broken bytewise by name.

---

## 9. Encoding reference (derived, non-authoritative)

For reading the worked examples. From `encoding.py` (which is authoritative;
this table is a convenience copy):

    bits  0–7   opcode      bits 17–21  src1        bits 32–39  mod
    bits  8–11  pred        bits 22–26  src2        bits 40–41  width
    bits 12–16  dst         bits 27–31  src3        bits 42–63  imm (masked
                                                    to 22 bits, low bits of
                                                    the value, verbatim)

`pred = (index << 1) | polarity`; `mod = (amount << 2) | kind`. Instructions
are stored little-endian: the byte at the lowest address holds insn bits
7:0 (the opcode).

---

## 10. Error catalog

Numbered, complete, and closed: every diagnostic the assembler can produce
for its input is one of these codes (exit 1); anything else (I/O, usage) is
exit 2 without an E-code. Message text after the code is informative;
the code and trigger condition are normative. Each trigger example is a
minimal input (prefixed by `.org 0x1000` plus a trailing `halt` where needed
to avoid triggering layout errors instead) and is a normative test vector
(see T5).

| code | trigger condition | minimal trigger example |
|------|-------------------|-------------------------|
| E001 | illegal character outside string/char literal | `add r1, r2, r3 @` |
| E002 | malformed number, or number ≥ 2^128 | `ldi r1, 0x1G` |
| E003 | unterminated or malformed string literal | `.ascii "abc` |
| E004 | unknown escape sequence | `.ascii "\q"` |
| E005 | malformed character literal (empty, multi-char, unterminated) | `ldi r1, 'ab'` |
| E010 | unknown mnemonic or directive | `frob r1, r2` |
| E011 | wrong operand count or malformed operand list | `add r1, r2` |
| E012 | register required but operand is not a register | `add 3, r2, r1` |
| E013 | predicate register required | `cmpeq r1, r2, r3` |
| E014 | malformed memory operand (missing base, index in atomic ea, index after displacement, two indexes) | `amoadd.64 r1, [r2 + r3], r4` |
| E015 | width suffix invalid for this mnemonic | `b.32 somewhere` |
| E016 | missing mandatory width suffix | `lds r1, [r2]` |
| E017 | malformed predication prefix | `(p9) add r1, r2, r3` |
| E018 | malformed label definition (e.g. `:` with no preceding name, `:` after an operand) | `: halt` |
| E019 | malformed src2 modifier (bad keyword, modifier after immediate, modifier on FP/atomic operand) | `add r1, r2, 5 shl 3` |
| E020 | immediate out of signed-22-bit range [−2^21, 2^21−1] | `add r1, r2, 0x200000` |
| E021 | `shori` immediate out of unsigned-22-bit range [0, 2^22−1] | `shori r1, r1, -1` |
| E022 | branch target minus pc not a multiple of 8 | `b target` with `target = pc + 4` |
| E023 | pc-relative displacement out of range (`b`/`jal`: ±2^21 instructions; `lap`: ±2^21 bytes) | `b target` with `target = pc + 8*2^21` |
| E024 | modifier amount out of range 0–63 | `add r1, r2, r3 shl 64` |
| E025 | illegal conversion format combination | `fcvtff.f32 r1, r2, f32` |
| E026 | sreg operand not a known name nor CONST in [0, 2^21−1] | `mfsr r1, nosuch` |
| E027 | immediate where only a register is permitted (FP operands, atomic data operands) | `fadd.f32 r1, r2, 3` |
| E028 | `la` target outside position-independent reach [−2^22, 2^22−2] bytes | `la r1, sym` with delta = 2^23 |
| E029 | `li` operand depends on a label | `li r1, somelabel` |
| E030 | undefined symbol | `b nowhere` |
| E031 | duplicate symbol definition (label or `.equ`) | `x: nop` / `x: halt` |
| E032 | user symbol collides with a reserved name (2.3) | `sp: halt` |
| E033 | illegal address arithmetic (4.2) | `.quad lab1 + lab2` |
| E034 | assembly-time constant required: expression uses a label or a not-yet-defined symbol (4.4) | `.org sz` before `.equ sz, 0x1000` |
| E035 | value does not fit the consuming context (data directive size, `.org` range) | `.byte 256` |
| E036 | `sub rd, imm, rs` with imm ≠ 0 | `sub r1, 5, r2` |
| E040 | emission before the first `.org` | `nop` as the first statement |
| E041 | label defined before the first `.org` | `start:` as the first line |
| E042 | segment overlap, or overlap with the device table window [0x0800, 0x1000) | two `.org 0x2000` segments |
| E043 | instruction at a non-8-byte-aligned location | `.byte 1` then `nop` |
| E044 | `.align` argument not a power of two ≥ 1 | `.align 3` |
| E045 | empty segment | `.org 0x2000` at end of input |
| E046 | `.entry` label undefined, or multiple `.entry` | `.entry nowhere` |
| E047 | entry address not 8-aligned | `.entry e` with `e` at 0x1004 |
| E048 | entry address not inside any segment | `.org 0x1000` / `nop` / `e:` / `.entry e` — `e` = 0x1008, the segment end, not inside [0x1000, 0x1008) |
| E049 | no segment covers PA 0x1000 | single segment `.org 0x2000` |

---

## 11. Conformance requirements

Numbered, testable. "Assembling X" means running `sasm` on X per section 1.

- **ASM-1.** For every row of test vector T1, assembling the source line (in
  a minimal `.org 0x1000` program) emits exactly the 64-bit little-endian
  value shown, byte-for-byte at the stated location.
- **ASM-2.** Every field not used by an instruction is emitted as zero;
  specifically, the T1 rows for `syscall`, `iret`, `invtp`, `ifence`, `wfi`,
  `halt` are the 64-bit values 0xF4, 0xF6, 0xF8, 0xFA, 0xFC, 0xFE.
- **ASM-3.** I-form selection is purely syntactic: a register third operand
  assembles to the even opcode, an expression to odd, for every ALU/compare
  mnemonic and `madd` (T1 contains at least one pair per family).
- **ASM-4.** A load/store with no index term encodes src2 = 31 and mod = 0
  (T1 rows `ldz.8 r5, [r6]` and following).
- **ASM-5.** An out-of-range immediate is rejected with the exact catalog
  code (E020/E021), never truncated; `li` and `la` are the only forms that
  expand instead (TOOLING-SPEC 4.4).
- **ASM-6.** `li` emits exactly the chains of test vector T2 — chain length
  minimal per the rule of 6.1.
- **ASM-7.** `la` emits 1 instruction when the final delta is within
  [−2^21, 2^21−1] bytes and exactly the 2-instruction split of 6.2
  otherwise; test vector T3 must be reproduced exactly, including under
  layouts requiring relaxation iteration.
- **ASM-8.** `la.abs` always emits exactly 6 instructions.
- **ASM-9.** Assembling test program T4 produces the `.img` byte stream and
  `.sym` text shown, byte-identically.
- **ASM-10.** Segment overlap — with another segment or with
  [0x0800, 0x1000) — is rejected with E042; T5 covers both cases.
- **ASM-11.** For every catalog row in section 10, assembling its minimal
  trigger example fails with exit code 1 and a single-line diagnostic
  matching `FILE:LINE: Ennn:` with that row's code and the correct 1-based
  line number.
- **ASM-12.** On any assembly error no `.img` or `.sym` file exists
  afterward, even if one existed before the run.
- **ASM-13.** Two consecutive runs on the same inputs produce
  byte-identical `.img` and `.sym` outputs.
- **ASM-14.** Mnemonics, directives, register/sreg names, and keyword
  tokens are case-insensitive: `ADD.32 R1, SP, 100` assembles identically
  to `add.32 r1, sp, 100`.
- **ASM-15.** Labels are case-sensitive: a program defining `Loop` and
  referencing `loop` fails E030.
- **ASM-16.** A user symbol equal (case-insensitively) to any reserved name
  of 2.3 is rejected E032.
- **ASM-17.** A predication prefix on a pseudo predicates every expanded
  instruction: `(p1) li r1, 0x123456789A` emits the T2 chain with pred =
  0b0010 on both instructions.
- **ASM-18.** Every conversion-format combination the ISA defines as
  ILLEGAL (10.4) is rejected at assembly with E025; every legal combination
  (6 for fcvtfi/fcvtfiu each, 6 for fcvtif/fcvtuif each, 2 for fcvtff)
  assembles.
- **ASM-19.** The assembler's opcode values, field positions, sreg indices,
  and register numbering are consumed from `encoding.py` or its generated
  header; changing a value there and rebuilding changes the assembler's
  output without any assembler source edit.
- **ASM-20.** `.entry` absent defaults entry to 0x1000; `.entry` present
  sets the header entry field to the label's address (T4 uses an explicit
  `.entry`).
- **ASM-21.** `file_len` trims exactly the trailing zero-byte run of each
  segment and `mem_len` is the full size (T4's second segment has file_len
  2, mem_len 3).
- **ASM-22.** The `.sym` output is sorted ascending by address field with
  bytewise name tiebreak, uses 32 lowercase hex digits, and classifies
  labels T/D per 8.3 (T4).

---

## 12. Test vectors

All hex is the 64-bit instruction **value**; in memory it is stored
little-endian (value 0x0000020000C41002 = bytes `02 10 C4 00 00 02 00 00`).
Format of T1–T3: `id | hex64 | source`, one vector per row, machine-
consumable. Where a vector needs a pc-relative context, the context is given
in the source column and pinned by the T4/T3 layouts.

### T1 — single-instruction encodings

Every operand shape, both I-forms, both predication polarities, all three
mod kinds, and every width family (ALU 32/64/128, MEM 8/16/32/64, MEM128,
ATOMIC 32/64/128, CMP, CTRL, CONST, PREDF, FP f32/f64, FCVT, SYS).

```
T1.01 | 0x0000020000C41002 | add r1, r2, r3
T1.02 | 0x0001900000041003 | add.32 r1, r2, 100
T1.03 | 0xFFFFFD00000A4005 | sub.64 r4, r5, -1
T1.04 | 0x00000200020E6602 | (p3) add r6, r7, r8
T1.05 | 0x0000020002D49504 | (!p2) sub r9, r10, r11
T1.06 | 0x0000020D00C41002 | add r1, r2, r3 shl 3
T1.07 | 0x0000012200C41006 | and.64 r1, r2, r3 sxt 8
T1.08 | 0x0000024300C41008 | or r1, r2, r3 zxt 16
T1.09 | 0x00055400001AC00B | xor.32 r12, r13, 0x155
T1.10 | 0x00001500000E700D | shl.64 r7, r7, 5
T1.11 | 0x0000020001063010 | sar r3, r3, r4
T1.12 | 0x0000000029062018 | madd.32 r2, r3, r4, r5
T1.13 | 0xFFFFFE0028062019 | madd r2, r3, -1, r5
T1.14 | 0x000000000292801A | udiv.32 r8, r9, r10
T1.15 | 0x0000000000823026 | cmplt.32 p3, r1, r2
T1.16 | 0x0000AA0000081025 | cmpeq p1, r4, 42
T1.17 | 0x0000010001CC502C | cmpleu.64 p5, r6, r7
T1.18 | 0x0000220900C41030 | lds.32 r1, [r2 + r3 shl 2 + 8]
T1.19 | 0x0000000007CC5032 | ldz.8 r5, [r6]
T1.20 | 0xFFFFF90007D07030 | lds.16 r7, [r8 - 2]
T1.21 | 0x0000030002D49032 | ldz.64 r9, [r10 + r11]
T1.22 | 0x0000400007C83034 | ld128 r3, [r4 + 16]
T1.23 | 0x000043004FC40036 | st.64 [r2 + 16], r9
T1.24 | 0x0000000029060036 | st.8 [r3 + r4], r5
T1.25 | 0xFFFFC00007F80038 | st128 [sp - 16], r0
T1.26 | 0x0000210020C41040 | cas.64 r1, [r2 + 8], r3, r4
T1.27 | 0x0000000001CC5042 | amoadd.32 r5, [r6], r7
T1.28 | 0x0001020002928052 | amomaxu r8, [r9 + 64], r10
T1.29 | 0xFFFFF0000000003A | b target          # target = pc - 32 (disp -4 insns)
T1.30 | 0x000018000000023A | (p1) b target     # target = pc + 48 (disp +6 insns)
T1.31 | 0x000100000001D03C | jal target        # bare form; target = pc + 512 (disp +64 insns)
T1.32 | 0x000020000002003E | jalr r0, r1, 8
T1.33 | 0x00000000003BF03E | ret               # = jalr zero, ra, 0
T1.34 | 0xFFFFEC0000001054 | ldi r1, -5
T1.35 | 0x0AAF340000021056 | shori r1, r1, 0x2ABCD
T1.36 | 0x0020000000002058 | lap r2, target    # target = pc + 0x800
T1.37 | 0x000000000000405A | prd r4
T1.38 | 0x00000000000A005C | pwr r5
T1.39 | 0x0000010000C41060 | fadd.f64 r1, r2, r3
T1.40 | 0x00000000000E6068 | fsqrt.f32 r6, r7
T1.41 | 0x0000000020C4106A | fmadd.f32 r1, r2, r3, r4
T1.42 | 0x000001000292806C | fmin.f64 r8, r9, r10
T1.43 | 0x0000000000822072 | fcmplt.f32 p2, r1, r2
T1.44 | 0x0000000100041076 | fcvtfi.32 r1, r2, f64
T1.45 | 0x0000020000083078 | fcvtfiu.128 r3, r4, f32
T1.46 | 0x000001020008307A | fcvtif.f64 r3, r4, i128
T1.47 | 0x00000001000C507C | fcvtuif.f32 r5, r6, i64
T1.48 | 0x00000100000C507E | fcvtff.f64 r5, r6, f32
T1.49 | 0x00000000000010F0 | mfsr r1, status
T1.50 | 0x00002400000400F2 | mtsr timecmp, r2
T1.51 | 0x00000000000000F4 | syscall
T1.52 | 0x00000000000000F6 | iret
T1.53 | 0x00000000000000F8 | invtp
T1.54 | 0x00000000000000FA | ifence
T1.55 | 0x00000000000000FC | wfi
T1.56 | 0x00000000000000FE | halt
T1.57 | 0x0000020007FFF008 | nop               # = or zero, zero, zero
T1.58 | 0x0000020007D23008 | mov r3, r9        # = or r3, r9, zero
T1.59 | 0xFFFFFE000006200B | not r2, r3        # = xor r2, r3, -1
T1.60 | 0x00000100017E4004 | neg.64 r4, r5     # = sub.64 r4, zero, r5
```

### T2 — `li` chains

Each case: source, then the emitted instructions in order.

```
T2.1 | li r1, 0x2A
     | 0x0000A80000001054 | ldi r1, 0x00002A
T2.2 | li r1, -2
     | 0xFFFFF80000001054 | ldi r1, 0x3FFFFE
T2.3 | li r1, 0x123456789A
     | 0x0123440000001054 | ldi r1, 0x0048D1
     | 0x59E2680000021056 | shori r1, r1, 0x16789A
T2.4 | li r1, 0xFEDCBA9876543210
     | 0x3FB72C0000001054 | ldi r1, 0x0FEDCB
     | 0xA987640000021056 | shori r1, r1, 0x2A61D9
     | 0x50C8400000021056 | shori r1, r1, 0x143210
T2.5 | li r1, 0x80000000000000000000000000000005
     | 0x0800000000001054 | ldi r1, 0x020000
     | 0x0000000000021056 | shori r1, r1, 0x000000
     | 0x0000000000021056 | shori r1, r1, 0x000000
     | 0x0000000000021056 | shori r1, r1, 0x000000
     | 0x0000000000021056 | shori r1, r1, 0x000000
     | 0x0000140000021056 | shori r1, r1, 0x000005
```

Chain lengths (minimality check): T2.1 → 1, T2.2 → 1, T2.3 → 2, T2.4 → 3,
T2.5 → 6.

### T3 — `la` form selection

```
T3.1 | la r2, msg        # la at 0x1008, msg at 0x2000, delta = +0xFF8: 1 insn
     | 0x003FE00000002058 | lap r2, msg
T3.2 | la r3, far        # la at 0x1000, far at 0x300000, delta = +0x2FF000: 2 insns
     | 0x7FFFFC0000003058 | lap r3, .+0x1FFFFF      # d1 = 0x1FFFFF
     | 0x3FC0060000063003 | add r3, r3, 0x0FF001    # d2 = 0x0FF001
```

### T4 — complete program → `.img` + `.sym`

Source (one file, `t4.s`):

```
        .org 0x1000
        .entry start
start:  li   r1, 42
        la   r2, msg
        lds.8 r3, [r2]
        halt
        .org 0x2000
msg:    .asciiz "Hi"
```

Assembled instruction stream (T3.1 is this program's `la`):

```
0x1000: 0x0000A80000001054 | ldi r1, 42
0x1008: 0x003FE00000002058 | lap r2, msg      # delta 0xFF8
0x1010: 0x0000000007C43030 | lds.8 r3, [r2]
0x1018: 0x00000000000000FE | halt
0x2000: 48 69 00           | "Hi\0"
```

`t4.img`, complete, 162 bytes (segment 1: file_off 0x80, file_len 32,
mem_len 32; segment 2: file_off 0xA0, file_len 2 — the trailing NUL is
trimmed — mem_len 3):

```
0000: 53 41 48 49 4d 47 30 31 00 10 00 00 00 00 00 00
0010: 00 00 00 00 00 00 00 00 02 00 00 00 00 00 00 00
0020: 00 10 00 00 00 00 00 00 00 00 00 00 00 00 00 00
0030: 80 00 00 00 00 00 00 00 20 00 00 00 00 00 00 00
0040: 20 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
0050: 00 20 00 00 00 00 00 00 00 00 00 00 00 00 00 00
0060: a0 00 00 00 00 00 00 00 02 00 00 00 00 00 00 00
0070: 03 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
0080: 54 10 00 00 00 a8 00 00 58 20 00 00 00 e0 3f 00
0090: 30 30 c4 07 00 00 00 00 fe 00 00 00 00 00 00 00
00a0: 48 69
```

`t4.sym`, complete (two lines, LF-terminated):

```
00000000000000000000000000001000 T start
00000000000000000000000000002000 D msg
```

### T5 — error vectors

Every "minimal trigger example" row of the section 10 catalog is a
normative error vector: assembling it must exit 1 with the row's code on
the triggering line. Additionally:

```
T5.1 | .org 0x0900 / nop*  → E042   # overlaps device table window
T5.2 | .org 0x1000 / nop / .org 0x1000 / halt → E042   # segment overlap
T5.3 | .org 0x2000 / halt  → E049   # nothing covers reset PC 0x1000
```

(`nop*` = enough nops to make the segment non-empty.)

---

## 13. Dependencies on other devspec documents

None. This document references only the frozen inputs (ISA-SPEC.md,
PLATFORM-SPEC.md, TOOLING-SPEC.md, `encoding.py`). Disassembly text format
and trace symbolization consume this document's `.sym` output via
TOOLING-SPEC 2/3; they are owned by devspec/trace.md and define nothing the
assembler needs.
