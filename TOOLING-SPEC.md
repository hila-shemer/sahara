# Sahara Tooling Specification

**Version 1.0-draft.** Companion to ISA-SPEC.md and PLATFORM-SPEC.md.
Defines the contracts between toolchain components: the image format and
symbol sidecar, the execution trace format and its query interface, and the
assembler. These sit at the platform layer for practical reasons (the
emulator and assembler are built together), though the assembler is
logically a toolchain citizen.

Everything encoding-shaped (field positions, opcode values, register and
sreg names, cause codes) is defined by `encoding.py`, which is generated to
match ISA-SPEC.md and cross-checked by `crosscheck.py`. No tool may
hardcode any of it independently.

---

## 1. Image format

Binary, little-endian, extension `.img`.

Header:

| offset | field |
|-------:|-------|
| 0  | magic u64: ASCII "SAHIMG01" |
| 8  | entry u128 (initial PC; must be 8-aligned; PA on this platform) |
| 24 | nsegs u64 |

Followed by nsegs segment descriptors (48 bytes each):

| offset | field |
|-------:|-------|
| 0  | load_pa u128 |
| 16 | file_off u64 |
| 24 | file_len u64 |
| 32 | mem_len u64 (>= file_len; the excess is zero-filled) |
| 40 | flags u64 (reserved, 0) |

Loader semantics: for each segment, copy file bytes [file_off, file_off +
file_len) to [load_pa, ...), zero to mem_len; then start at entry. On this
platform the reference boot flow requires one segment to cover PA 0x1000
(the reset PC) -- entry is convention, reset PC is architecture; images
place a jump at 0x1000 when entry differs. Segments must not overlap each
other or the device table at 0x0800.

## 2. Symbol sidecar

Text file, same basename as the image, extension `.sym`, produced by the
assembler alongside every image. One line per symbol:

    <addr:32 hex digits> <kind> <name>

kind: `T` code, `D` data, `A` absolute (non-address constant). Sorted by
address. Names: [A-Za-z_][A-Za-z0-9_.$]*. Every label in the assembled
program appears; the trace tools consume this file for symbolization. The
format is deliberately trivial: greppable, diffable, mergeable.

## 3. Execution trace

### 3.1 Requirements

The trace is the platform's debugging story (there is no frame pointer and
no interactive debugger; see ISA-SPEC 12). It must be complete enough to
answer, post hoc: what executed at cycle N; who last wrote address A before
cycle N; where two runs first diverge; what any register held at any time
(reconstructible from writebacks). Recording must be deterministic:
identical runs produce byte-identical traces.

### 3.2 Format

Binary stream, extension `.trc`, sequence of records. Every record begins:

    u8  type
    u8  reserved (0)
    u16 reserved (0)
    u32 payload length in bytes

followed by the payload. Types:

| type | name | payload |
|-----:|------|---------|
| 1 | EXEC  | cycle u64, pc u128, insn u64, wb u128 (dst writeback value; 0 if none), flags u8 (bit 0 predicated-false, bit 1 wrote-dst, bit 2 wrote-pred), pred_wb u8 |
| 2 | MEMW  | cycle u64, ea u128, size u8, new u128 (low `size` bytes significant) |
| 3 | MEMR  | cycle u64, ea u128, size u8, val u128 |
| 4 | TRAP  | cycle u64, cause u64, epc u128, baddr u128, tl_after u8 |
| 5 | EVENT | cycle u64, device u64 (table index), payload_len u32, bytes |
| 6 | DEVW  | cycle u64, ea u128, size u8, val u128 |
| 7 | META  | key/value text (image path+hash, encoding version, mode flags); first record of every trace |

EXEC is emitted for every retired instruction including squashed ones.
MEMW/MEMR/DEVW are emitted per data access (fetches are implied by EXEC).
Recording levels: level 0 = EXEC+TRAP+EVENT+META; level 1 adds MEMW/DEVW;
level 2 adds MEMR. The level is recorded in META. Conformance runs use
level 1; determinism comparison uses any level consistently.

The event trace of PLATFORM-SPEC section 8 is the subsequence of EVENT
records; the emulator can re-run from an image plus EVENT records alone
(replay mode), and must reproduce the remaining records byte-identically.

### 3.3 Query interface

One CLI tool, `trace-q`, whose subcommands are the normative query set --
designed for an agent consumer: every output is plain text, one fact per
line, symbolized when a `.sym` file is given.

| query | answers |
|-------|---------|
| `exec CYCLE` | the EXEC record at a cycle, disassembled |
| `at PC` | all cycles that executed PC |
| `last-write ADDR [--before CYCLE]` | most recent MEMW/DEVW covering ADDR |
| `reg R --at CYCLE` | value of register R at a cycle (reconstructed) |
| `find --pc X \| --wrote-reg R=V \| --touched A [--from C] [--to C]` | first matching cycle; the general query of slice finding 1.12 |
| `diverge A.trc B.trc` | first differing record between two traces |
| `range C1 C2` | disassembled listing of a cycle range |
| `trapdump` | all TRAP records, symbolized |

Reverse-continue is `find` with `--to` and taking the last match; no
interactive machinery exists or is wanted.

## 4. Assembler

Input: one or more `.s` files, concatenated in order. Output: `.img` +
`.sym`. Two passes; no linker in v1.0 (multi-file programs assemble
together).

### 4.1 Lexical

Line-oriented. `#` starts a comment. Labels: `name:` at line start.
Numbers: decimal, `0x` hex, `0b` binary; character literals 'a'. Strings
in `.ascii`/`.asciiz` with C escapes.

### 4.2 Registers and names

`r0`-`r31`; aliases `sp` (r28), `ra` (r29), `k0` (r30), `zero` (r31).
Predicates `p0`-`p7`. Sregs by the names in encoding.py (`status`, `epc0`,
...). All names case-insensitive; labels case-sensitive.

### 4.3 Instruction syntax

    [(pred)] MNEMONIC[.W] operands

- Predication prefix: `(p3)` execute-when-true, `(!p3)` when-false.
- Width suffix `.32` / `.64` on ALU/compare/atomic mnemonics; none = 128.
  Loads/stores: `lds.8/.16/.32/.64`, `ldz.8/.16/.32/.64`, `ld128`,
  `st.8/.16/.32/.64`, `st128`. FP: `.f32`/`.f64`.
- ALU: `add rd, rs1, rs2` | `add rd, rs1, imm` (assembler picks the I
  form). src2 modifier: `add rd, rs1, rs2 shl 3`, `... sxt N`, `... zxt N`.
- Memory: `lds.32 rd, [rs1 + rs2 shl 2 + imm]` -- base required, index
  term and displacement optional in any combination.
- Atomics: `cas.64 rd, [rs1 + imm], rexp, rnew`; `amoadd.64 rd,
  [rs1 + imm], rs2`.
- Compare: `cmplt p3, rs1, rs2|imm`.
- Branches: `b label`, `(p1) b label`, `jal rd, label`, `jalr rd, rs1, imm`.
  Bare `jal label` = `jal ra, label`; `ret` = `jalr zero, ra, 0`.
- Conversions: `fcvtfi.32 rd, rs1, f64` (dest width suffix, source format
  as the trailing operand).
- System: `mfsr rd, NAME`, `mtsr NAME, rs1`, bare `syscall`, `iret`,
  `invtp`, `ifence`, `wfi`, `halt`.

### 4.4 Pseudo-instructions

| pseudo | expansion |
|--------|-----------|
| `li rd, imm` | minimal LDI/SHORI chain for the constant's actual width |
| `la rd, label` | LAP if the label is within +/-2 MB of the LAP itself; else LAP + immediate `add` (position-independent within 2^22 * range); `la.abs` forces an absolute LDI/SHORI chain |
| `mov rd, rs` | `or rd, rs, zero` |
| `nop` | `or zero, zero, zero` |
| `not`, `neg`, `sub rd, imm, rs` forms | the obvious one-instruction expansions |

The assembler must reject an immediate that does not fit the 22-bit field
rather than truncate (loud failure), except inside `li`/`la` which expand.

### 4.5 Directives

`.org PA` (segment load address; opens a new segment), `.entry LABEL`,
`.align N`, `.byte/.half/.word/.quad/.oct v,...` (1/2/4/8/16 bytes),
`.ascii "s"`, `.asciiz "s"`, `.space N`, `.equ NAME, expr`. Constant
expressions: + - * ( ) over numbers, `.equ` names, and labels (labels only
in contexts wide enough to hold them).

### 4.6 Errors

All errors name file:line and are fatal. Warnings do not exist -- anything
worth flagging is an error (project loud-failure policy).
