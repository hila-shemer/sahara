# Sahara ISA Specification

**Version 1.0-draft.** This is the normative architecture document. An
implementer with no other context must be able to build a conforming emulator
from this document alone. Where this document and any other artifact disagree,
this document wins; the machine-readable encoding file used by the toolchain
must be generated to match Appendix A.

Non-normative rationale appears in indented *Note:* lines. Everything else is
normative.

---

## 1. Overview

Sahara is a byte-addressed, little-endian, 128-bit machine with:

- 32 x 128-bit general-purpose registers, shared between integer and
  floating-point use
- 8 x 1-bit predicate registers; full predication of every instruction
- One 64-bit instruction format, fixed field positions
- A 128-bit flat virtual address space, translated by a
  radix page table with 64 KB pages
- Supervisor/user privilege, traps, interrupts, syscalls, double-fault
  handling
- Deterministic virtual time

There is no hardware TLB, no caches, and no speculation in version 1.0. Two
instructions (`INVTP`, `IFENCE`) are architectural no-ops that exist so
software contracts are exercised before caching implementations appear.

Performance is a non-goal of this specification.

---

## 2. Machine state

### 2.1 General-purpose registers

32 registers, `r0`-`r31`, each 128 bits wide.

- `r31` is hardwired to zero: reads return 0, writes are discarded.
- All other registers are general purpose at the ISA level. Software roles
  (sp, ra, k0) are defined by the ABI (section 12), not enforced by
  hardware.

Floating-point values occupy the same registers (section 10).

### 2.2 Predicate registers

8 one-bit registers, `p0`-`p7`.

- `p0` is hardwired to 1: reads return 1, writes are discarded.
- Compare instructions write a predicate register selected by the low 3 bits
  of the `dst` field.
- `PRD`/`PWR` move the whole file to/from a GPR (section 5.7).

### 2.3 Special registers (sregs)

Accessed by `MFSR`/`MTSR` with the sreg index in the immediate field.

| idx | name     | access | contents |
|----:|----------|--------|----------|
| 0   | status   | S      | b0 `IE`, b1 `PIE`, b2 `MMU_EN`, b3 `S`, b4 `PS`, b6:5 `TL` |
| 1   | epc0     | S      | trap bank 0: faulting/return PC |
| 2   | cause0   | S      | trap bank 0: cause code |
| 3   | baddr0   | S      | trap bank 0: faulting virtual address |
| 4   | vbase    | S      | trap vector (normal) |
| 5   | dfbase   | S      | trap vector (double fault) |
| 6   | ptbase   | S      | physical address of page-table root node |
| 7   | asid     | S      | address-space identifier (section 8.6) |
| 8   | cycle    | read: S+U; write: none | virtual cycle counter (read-only) |
| 9   | timecmp  | S      | timer compare value |
| 10  | scratch0 | S      | supervisor scratch |
| 11  | scratch1 | S      | supervisor scratch |
| 12  | epc1     | S      | trap bank 1 (double fault) |
| 13  | cause1   | S      | trap bank 1 |
| 14  | baddr1   | S      | trap bank 1 |
| 15  | fcsr     | S+U    | FP rounding mode and flags (section 10.3) |

Access column: `S` = supervisor only; `S+U` = also permitted in user mode.
Any access not permitted traps with cause `PRIV`. Writes to `cycle` trap
`PRIV` from any mode. Access to unlisted indices traps `ILLEGAL`.

All sregs are 128 bits wide; unused high bits read as zero and must be
written as zero.

### 2.4 Privilege modes

Two modes: supervisor (`status.S = 1`) and user (`status.S = 0`).

Supervisor-only operations: `MFSR`/`MTSR` per the table above, `IRET`,
`INVTP`, `WFI`, and `HALT`. Executing any of these in user mode traps
`PRIV`. `SYSCALL` and `IFENCE` are permitted in both modes.

---

## 3. Instruction format

Instructions are 64 bits, little-endian, and must be 8-byte aligned.

One format. Fields, LSB to MSB:

| field  | bits | position | meaning |
|--------|-----:|---------:|---------|
| opcode | 8    | 0-7      | bit 0 = I-flag where applicable; see Appendix A |
| pred   | 4    | 8-11     | bit 0 = polarity (1 = execute when false); bits 3:1 = predicate index |
| dst    | 5    | 12-16    | destination register (predicate index for compares, low 3 bits) |
| src1   | 5    | 17-21    | source 1 |
| src2   | 5    | 22-26    | source 2 |
| src3   | 5    | 27-31    | source 3 |
| mod    | 8    | 32-39    | src2 modifier (section 3.3) |
| width  | 2    | 40-41    | operation width (section 3.4) |
| imm    | 22   | 42-63    | immediate, sign-extended unless stated otherwise |

Fields not used by an instruction are ignored by hardware. Assemblers must
emit zero in unused fields; future revisions may assign meaning to them.

### 3.1 The I-flag

For ALU and compare opcodes, opcode bit 0 selects the second operand:

- `I = 0`: operand `b = mod(R[src2])`
- `I = 1`: operand `b = sext(imm22)`; the `mod` field is ignored

Register and immediate forms of the same operation occupy adjacent opcode
values. Memory, atomic, FP, and system opcodes do not use the I-flag; their
use of `imm` is fixed per instruction, and their odd sibling opcode values
are reserved (executing one traps `ILLEGAL`).

### 3.2 Predication

Every instruction is predicated. Execute condition:
`P[pred.index] XOR pred.polarity == 1`. The encoding `pred = 0000` means
(p0, positive polarity) -- always execute -- and is the unpredicated form.

An instruction whose predicate evaluates false has **no architectural
effect and cannot fault**. It performs no memory access, no translation, no
sreg access, and raises no trap. It retires and consumes one cycle.

### 3.3 The mod field

Applies to the value read from `src2`, before use. Layout: bits 1:0 = kind,
bits 7:2 = amount (0-63).

| kind | meaning |
|-----:|---------|
| 0    | none (amount must be 0) |
| 1    | `shl`: value << amount |
| 2    | `sxt`: sign-extend from the low *amount* bits; amount 0 = no-op |
| 3    | `zxt`: zero-extend from the low *amount* bits; amount 0 = no-op |

Shifts of 64 or more cannot be expressed in `mod`; use the `SHL`
instruction.

### 3.4 The width field

Meaning depends on the opcode family:

| family | width 0 | width 1 | width 2 | width 3 |
|--------|--------:|--------:|--------:|--------:|
| ALU, compare, CAS, AMO | 32 | 64 | 128 | reserved |
| LDS, LDZ, ST           | 8  | 16 | 32  | 64 |
| FP arithmetic, FCMP    | FP32 | FP64 | reserved | reserved |
| FP conversions         | see section 10.4 | | | |

`LD128` and `ST128` are separate opcodes and ignore the width field.
Instructions for which width is meaningless ignore it. Reserved width values
trap `ILLEGAL`.

**Narrow-width ALU semantics** (width w in {32, 64}): operands are the low w
bits of the inputs (after `mod`/immediate substitution), interpreted as
signed or unsigned per the operation; the result is computed at w bits and
**sign-extended from bit w-1 to 128 bits** -- including for unsigned
operations. Width 128 is the native width; no truncation or extension
occurs.

> *Note: sign-extending even unsigned narrow results follows RV64
> (`DIVUW` etc.) and preserves a single canonical form: a w-bit value in a
> register always has bits 127:w equal to bit w-1.*

Shift counts are taken modulo the operation width.

---

## 4. Execution model and virtual time

Execution is sequential: one instruction at a time, in program order, each
fully completed before the next begins. A faulting instruction has no
architectural effect (all checks precede all writes). Atomic instructions
are all-or-nothing.

`cycle` (sreg 8) increments by exactly 1 for every retired instruction --
including predicated-false instructions -- and by 1 for every trap delivery.
Nothing else advances it, except WFI (section 7.6).

All device input is scheduled at (cycle, payload) pairs in a synchronous
event queue. Given the same memory image and the same event trace, execution
is bit-exact reproducible. A conforming implementation must not consult wall
clocks, host randomness, or any non-deterministic source.

---

## 5. Instruction set

Throughout: `b` = `I ? sext(imm22) : mod(R[src2])` for I-capable opcodes.
`w` = operation width per section 3.4. Semantics are given at width w with
the canonical-form rule of 3.4 applied to results.

### 5.1 ALU

| op | semantics |
|----|-----------|
| ADD | `dst = src1 + b` |
| SUB | `dst = src1 - b` |
| AND | `dst = src1 & b` |
| OR  | `dst = src1 \| b` |
| XOR | `dst = src1 ^ b` |
| SHL | `dst = src1 << (b mod w)` |
| SHR | `dst = src1 >> (b mod w)` (logical) |
| SAR | `dst = src1 >> (b mod w)` (arithmetic) |
| MUL | `dst = low w bits of src1 * b` |
| MULH | `dst = high w bits of the 2w-bit signed product src1 * b` |
| MULHU | `dst = high w bits of the 2w-bit unsigned product` |
| MADD | `dst = src1 * b + src3` (low w bits) |
| SDIV / UDIV | `dst = src1 / b` signed / unsigned |
| SREM / UREM | `dst = src1 mod b` signed / unsigned |

Division by zero does not trap: quotient = all ones (at width w, then
canonicalized), remainder = dividend. Signed overflow (`MIN_w / -1`):
quotient = MIN_w, remainder = 0.

### 5.2 Compare

`CMPEQ, CMPLT, CMPLTU, CMPLE, CMPLEU` -- compare `src1` with `b` at width w
and write the boolean to `P[dst & 7]`. The remaining `dst` bits are ignored.
Negated conditions are obtained with predicate polarity at the consumer.

### 5.3 Memory

Effective address for all memory operations:
`ea = R[src1] + mod(R[src2]) + sext(imm22)`.

| op | semantics |
|----|-----------|
| LDS | load w in {8,16,32,64} bits, sign-extend to 128, into `dst` |
| LDZ | load w in {8,16,32,64} bits, zero-extend to 128, into `dst` |
| LD128 | load 128 bits into `dst` |
| ST | store low w in {8,16,32,64} bits of `R[src3]` |
| ST128 | store all 128 bits of `R[src3]` |

Natural alignment is required (an n-byte access must be n-byte aligned);
violation traps `UNALIGNED` with `baddr` = ea.

### 5.4 Atomics

Effective address: `ea = R[src1] + sext(imm22)`. Width w in {32, 64, 128};
natural alignment required. Each executes atomically: no other access is
ordered between its read and its write. `dst` receives the old memory
value, canonicalized per width.

| op | semantics |
|----|-----------|
| CAS | `old = mem[ea]; if (low w of old == low w of R[src2]) mem[ea] = low w of R[src3]; dst = old` |
| AMOADD / AMOAND / AMOOR / AMOXOR / AMOSWAP | `old = mem[ea]; mem[ea] = op(old, R[src2]); dst = old` |
| AMOMIN / AMOMAX | signed min/max of old and `R[src2]` |
| AMOMINU / AMOMAXU | unsigned min/max |

Atomic operations targeting device address space trap `DEVERR`.

### 5.5 Control flow

Branch displacements count **instructions** (multiples of 8 bytes),
relative to the branch instruction itself.

| op | semantics |
|----|-----------|
| B    | `pc += sext(imm22) * 8`. Conditional branching is B with a predicate. |
| JAL  | `dst = pc + 8; pc += sext(imm22) * 8` |
| JALR | `dst = pc + 8; pc = R[src1] + sext(imm22)` (byte address). Target not 8-aligned traps `UNALIGNED` with `baddr` = target. |

There are no conditional-branch opcodes.

### 5.6 Constants and addresses

| op | semantics |
|----|-----------|
| LDI   | `dst = sext(imm22)` |
| SHORI | `dst = (R[src1] << 22) \| zext(imm22)` |
| LAP   | `dst = pc + sext(imm22)` (byte address) |

A full 128-bit constant is `LDI` + 5 x `SHORI`. `LAP` reaches +/-2 MB;
position-independent access beyond that combines `LAP` with an immediate
`ADD`.

### 5.7 Predicate file access

| op | semantics |
|----|-----------|
| PRD | `dst = zext(P7..P0)` (bit i = P[i]) |
| PWR | `P[i] = bit i of R[src1]` for i = 1..7; bit 0 ignored (p0 immutable) |

### 5.8 System

| op | semantics |
|----|-----------|
| MFSR | `dst = sreg[imm22]` |
| MTSR | `sreg[imm22] = R[src1]` |
| SYSCALL | traps with cause `SYSCALL`; `epc` = address of the SYSCALL instruction |
| IRET | return from trap (section 7.4) |
| INVTP | invalidate cached translations (section 8.7). Architectural no-op until a translation cache exists. `imm` = 0; other values reserved. |
| IFENCE | order instruction fetch after prior stores (section 9.3). Architectural no-op until instruction caching exists. |
| WFI | stall until an interrupt is pending (section 7.6) |
| HALT | stop the machine |

---

## 6. Opcode map

See Appendix A. Opcode value 0x00 is `ILLEGAL` and traps, so zeroed memory
faults loudly when executed. All unassigned opcode values trap `ILLEGAL`.

---

## 7. Traps, interrupts, and privilege

### 7.1 Cause codes

| code | name | epc points at | baddr |
|-----:|------|---------------|-------|
| 0  | TIMER      | next instruction to execute | -- |
| 1  | EXTINT     | next instruction to execute | -- |
| 2  | PF_FETCH   | faulting instruction | faulting VA |
| 3  | PF_LOAD    | faulting instruction | faulting VA |
| 4  | PF_STORE   | faulting instruction | faulting VA |
| 5  | PERM_FETCH | faulting instruction | faulting VA |
| 6  | PERM_LOAD  | faulting instruction | faulting VA |
| 7  | PERM_STORE | faulting instruction | faulting VA |
| 8  | ILLEGAL    | faulting instruction | -- |
| 9  | UNALIGNED  | faulting instruction | offending address / target |
| 10 | SYSCALL    | the SYSCALL instruction | -- |
| 11 | PRIV       | faulting instruction | -- |
| 12 | DEVERR     | faulting instruction | offending address |

`PF_*` = translation failed (no valid mapping); `PERM_*` = mapping exists
but the permission check failed. An atomic operation requires both R and W
permission; it reports the first failing check in the order R then W
(`PF_LOAD`/`PERM_LOAD` before `PF_STORE`/`PERM_STORE`).

The SYSCALL handler resumes past the syscall by adding 8 to epc before
IRET. Fault handlers may fix-and-rerun (epc unchanged) or skip (epc += 8).

### 7.2 Trap levels and banks

`status.TL` (2 bits) counts nesting. Two banks of (epc, cause, baddr) sregs
exist: bank 0 (indices 1-3) and bank 1 (indices 12-14).

Delivery of any trap or interrupt:

1. If `TL = 2`: **triple fault** -- the machine halts. No state is written.
2. Otherwise: `TL += 1`. Bank `TL - 1` receives epc/cause/baddr.
3. `status.PIE <- status.IE`; `status.IE <- 0`.
4. `status.PS <- status.S`; `status.S <- 1`.
5. `pc <- vbase` if TL is now 1, `dfbase` if TL is now 2 (**double
   fault**).

Delivery consumes one cycle. There is a single copy of PIE/PS; a double
fault overwrites them. Double faults are diagnostic endpoints: the handler
at `dfbase` can report both banks, but returning from a double fault is not
an expected pattern.

### 7.3 Nested faults by software consent

`TL` is writable via MTSR. The intended supervisor pattern for code that
must legitimately fault while handling a trap (e.g. touching pageable user
memory): save bank 0 and status to memory, write `TL <- 0`, proceed.
Subsequent faults then deliver normally. A fault taken before the handler
has saved its state is, by construction, a double fault -- loud, not
silent.

### 7.4 IRET

`pc <- epc[bank]` where bank = 1 if TL = 2, else bank 0;
`IE <- PIE`; `S <- PS`; `TL <- max(TL - 1, 0)`. Supervisor only.

### 7.5 Interrupts

Interrupts are recognized only between instructions, and only when
`status.IE = 1`. Faults always deliver regardless of IE.

- **Timer**: pending while `cycle >= timecmp` and `timecmp != 0`.
- **External** (device input): level-triggered -- pending while any device
  asserts it (for the reference input device: while its queue is
  non-empty; the handler clears it by draining the device).

Fixed priority: timer, then external. No other interrupt sources exist in
v1.0.

### 7.6 WFI

Supervisor only. If no interrupt is pending, execution stalls and virtual
time advances directly to the next cycle at which one becomes pending;
`cycle` reflects the jump. Then: if `IE = 1`, the interrupt is delivered
(epc = the instruction after WFI); if `IE = 0`, execution continues at the
next instruction. If no future event exists that could make an interrupt
pending, the machine halts (deadlock is loud).

---

## 8. Memory management

### 8.1 Addressing

Virtual and physical addresses are 128 bits. Pages are 64 KB:
`VPN = VA[127:16]`, page offset = `VA[15:0]`.

When `status.MMU_EN = 0`, physical address = virtual address (identity).
Permission checks do not apply with the MMU off.

### 8.2 Page table structure

A forward-mapped, path-compressed radix tree over the 112-bit VPN, walked
in fixed 8-bit chunks: chunk k covers VPN bits [8k, 8k+8). `ptbase` holds
the physical address of the root node, 64-byte aligned.

**Node** (4160 bytes, 64-byte aligned):

- Header, 64 bytes: `shift` (u64) -- the chunk position this node indexes,
  a multiple of 8 in [0, 104]; `prefix` (u128); `prefix_mask` (u128); the
  remainder of the 64 bytes is reserved and must be zero.
- 256 entries x 16 bytes.

**Entry** (128 bits), low 2 bits = type:

| type | meaning |
|-----:|---------|
| 0 | invalid |
| 1 | table: child node physical address = entry with low 6 bits cleared |
| 2 | leaf: frame physical address = entry with low 16 bits cleared; bit 2 = R, bit 3 = W, bit 4 = X, bit 5 = U; bits 15:6 reserved, must be zero |
| 3 | reserved |

Leaves are legal only in nodes with `shift = 0`. A leaf elsewhere, a type-3
entry, or a malformed node encountered during a walk causes the access to
fault `PF_*`.

> *Note: no superpages in v1.0; reserved for a future revision.*

### 8.3 Walk

At each node: if `(VPN & prefix_mask) != prefix`, fault `PF_*`. Otherwise
`entry = entries[(VPN >> shift) & 0xFF]`; type invalid -> fault, type
table -> descend to the child node, type leaf (at shift 0) -> physical
address = frame | `VA[15:0]`.

### 8.4 Permissions

Checked on every translated access: fetch requires X, load requires R,
store requires W. Violation faults `PERM_*`. The U bit gates user-mode
access: in user mode, an access to a page with U = 0 faults `PERM_*`.
Supervisor mode ignores U but honors R/W/X.

> *Note: supervisor access to user pages is unrestricted in v1.0
> (no SMAP equivalent).*

### 8.5 Coupled decision -- sparsity and fanout

Normative statement of a dependency: the 8-bit chunk width is chosen
because the system's address-space policy is many small scattered regions
in a vast space. Path compression makes tree depth scale with the number
of mapped regions, not with address width. A future revision changing
either the chunk width or the sparsity policy must reconsider both
together.

### 8.6 ASID

`asid` (sreg 7) names the current address space. The walk itself does not
consult it. Its sole architectural function: an implementation with a
translation cache must key cached translations by (asid, VA). Software
that changes `ptbase` must either change `asid` to a value whose
translations are not stale, or issue `INVTP`.

### 8.7 INVTP

Invalidates all cached translations, all ASIDs. Must be issued by software
after any page-table modification, before the next access that depends on
it -- including in implementations with no translation cache, where it is
a no-op. Supervisor only.

---

## 9. Memory model, devices, ordering

### 9.1 Ordering

Single-processor v1.0: all memory accesses appear to execute in program
order with respect to the processor itself. No FENCE instruction exists
yet; one is reserved for SMP (section 13).

### 9.2 Device access

Platforms designate physical address windows as device space. Accesses use
ordinary loads and stores. Rules:

1. A store to device space acts as a release fence: all prior ordinary
   stores in program order are complete before it takes effect.
2. Loads and stores to device space are mutually ordered in program order.
   Device reads may have side effects.
3. No other ordering is guaranteed.

Atomic operations to device space trap `DEVERR`. Access sizes supported
per device window are platform-defined; an unsupported size traps
`DEVERR`.

### 9.3 IFENCE

Guarantees that instruction fetch after the IFENCE observes all stores
before it. Must be issued between writing instructions to memory and
executing them (loaders, JITs) -- including in implementations without
instruction caching, where it is a no-op.

---

## 10. Floating point

### 10.1 Formats and registers

IEEE 754-2019 binary32 (width 0) and binary64 (width 1), held in the
general-purpose registers. FP instructions read the low 32/64 bits of
their source registers and ignore the upper bits; results are written
sign-extended from the top bit of the format, per the uniform
canonicalization rule of 3.4. Bit-level manipulation of FP values (negate,
abs, sign-copy, moves) uses ordinary integer instructions; no dedicated
instructions exist for it.

No flush-to-zero; subnormals are supported and exact.

### 10.2 Operations

All FP operations are register-only (no immediate forms).

| op | semantics |
|----|-----------|
| FADD, FSUB, FMUL, FDIV | `dst = src1 op src2` |
| FSQRT | `dst = sqrt(src1)` |
| FMADD | `dst = src1 * src2 + src3`, single rounding (fused) |
| FMIN, FMAX | IEEE 754-2019 minimum/maximum semantics |
| FCMPEQ, FCMPLT, FCMPLE | write `P[dst & 7]`. Comparisons involving NaN produce false; FCMPLT and FCMPLE with a NaN operand raise NV, FCMPEQ does not. |

NaN results are the canonical quiet NaN of the format.

### 10.3 fcsr

Bits 4:0 accumulate exception flags NV, DZ, OF, UF, NX (sticky; cleared
only by writing fcsr). Bits 7:5 = rounding mode: 0 RNE, 1 RTZ, 2 RDN,
3 RUP, 4 RMM. Writing a reserved rounding-mode value (5-7) is permitted;
the next FP operation that rounds then traps `ILLEGAL`. FP exceptions
never trap; they set flags only.

### 10.4 Conversions

Conversions use `width` for the destination format and `mod` bits 1:0 for
the source format; `mod` bits 7:2 must be zero. Format codes: 0 = 32-bit,
1 = 64-bit, 2 = 128-bit (integer formats only; 128-bit FP does not
exist). Illegal format combinations trap `ILLEGAL`.

| op | conversion |
|----|-----------|
| FCVTFI  | FP (src fmt) -> signed integer (dest width) |
| FCVTFIU | FP -> unsigned integer |
| FCVTIF  | signed integer (src fmt) -> FP (dest width) |
| FCVTUIF | unsigned integer -> FP |
| FCVTFF  | FP -> FP (32 <-> 64) |

FP-to-integer rounds toward zero always (C cast semantics), regardless of
fcsr. Out-of-range, infinity, or NaN: the result saturates to the
destination's maximum (positive overflow, +inf, NaN) or minimum (negative
overflow, -inf), and NV is raised. Integer-to-FP and FP-to-FP round per
fcsr. Integer results are canonicalized per section 3.4.

---

## 11. Reset state

At reset: `pc = 0x1000` (physical), `status.S = 1` and all other status
bits 0 (MMU off, interrupts disabled, TL = 0), all other sregs 0, all GPRs
0, predicates p1-p7 = 0. Memory contents are platform-defined (the loaded
image).

---

## 12. ABI

Software standard; not hardware-enforced.

| registers | role |
|-----------|------|
| r0-r7   | arguments 0-7, in order; return value in r0 (r0:r1 for a two-register return). Caller-saved. |
| r8-r15  | temporaries. Caller-saved. |
| r16-r27 | callee-saved: a function preserves exactly the ones it uses. |
| r28     | sp. 16-byte aligned at all times. Grows down. |
| r29     | ra. Written by JAL/JALR (an ordinary dst; there is no hidden link register). Caller-saved. |
| r30     | k0. Reserved to the kernel at all times; user code must not use it. The trap handler's only immediately free register. |
| r31     | zero (hardware). |

- Predicate registers are caller-saved and not preserved across calls.
- Arguments beyond 8 are passed in 16-byte stack slots at [sp + 0] of the
  caller's frame at call time; the callee addresses them at
  [sp + framesize + 16*i]. Every stack slot is 16 bytes.
- No frame pointer. Backtraces come from the platform trace facility, not
  a frame chain.
- `int` is 32-bit; `long` and pointers are 128-bit. All integer values are
  kept in the canonical form of section 3.4 (sign-extended from their
  width, signed and unsigned alike); `zxt`, LDZ, and unsigned W-form
  operations supply zero-extended interpretation at the points of use that
  need it.
- Trap handler entry contract: k0 plus scratch0/1 are the free-register
  bootstrap; PRD/PWR preserve the predicate file; bank-0 sregs and status
  are saved to memory before `TL` is lowered (section 7.3).

---

## 13. Reserved extensions

Opcode space is reserved for, and v1.0 must not assign it to anything
else:

- **TBEGIN / TEND / TABORT** -- hardware transactional memory. When
  specified, aborts must be deterministic under virtual time (replay of an
  input trace reproduces identical abort points). CAS/AMO remain the
  required fallback path.
- **SIMD** -- integer and FP vector operations. The width field's
  per-family tables are the intended extension mechanism.
- **FENCE** -- required when SMP arrives.
- **Superpages** -- leaf entries at shift > 0.

---

## Appendix A -- Opcode map (normative)

8-bit opcode values. ALU and compare families occupy even/odd pairs: even
= register form (I = 0), odd = immediate form (I = 1). For all other
instructions the listed value is the only legal one and its unlisted odd
sibling is reserved. All values not listed, and value 0x00, trap
`ILLEGAL`.

| value | instruction | | value | instruction |
|------:|-------------|-|------:|-------------|
| 0x00 | ILLEGAL | | 0x40 | CAS |
| 0x02/03 | ADD | | 0x42 | AMOADD |
| 0x04/05 | SUB | | 0x44 | AMOAND |
| 0x06/07 | AND | | 0x46 | AMOOR |
| 0x08/09 | OR | | 0x48 | AMOXOR |
| 0x0A/0B | XOR | | 0x4A | AMOSWAP |
| 0x0C/0D | SHL | | 0x4C | AMOMIN |
| 0x0E/0F | SHR | | 0x4E | AMOMAX |
| 0x10/11 | SAR | | 0x50 | AMOMINU |
| 0x12/13 | MUL | | 0x52 | AMOMAXU |
| 0x14/15 | MULH | | 0x60 | FADD |
| 0x16/17 | MULHU | | 0x62 | FSUB |
| 0x18/19 | MADD | | 0x64 | FMUL |
| 0x1A/1B | UDIV | | 0x66 | FDIV |
| 0x1C/1D | SDIV | | 0x68 | FSQRT |
| 0x1E/1F | UREM | | 0x6A | FMADD |
| 0x20/21 | SREM | | 0x6C | FMIN |
| 0x24/25 | CMPEQ | | 0x6E | FMAX |
| 0x26/27 | CMPLT | | 0x70 | FCMPEQ |
| 0x28/29 | CMPLTU | | 0x72 | FCMPLT |
| 0x2A/2B | CMPLE | | 0x74 | FCMPLE |
| 0x2C/2D | CMPLEU | | 0x76 | FCVTFI |
| 0x30 | LDS | | 0x78 | FCVTFIU |
| 0x32 | LDZ | | 0x7A | FCVTIF |
| 0x34 | LD128 | | 0x7C | FCVTUIF |
| 0x36 | ST | | 0x7E | FCVTFF |
| 0x38 | ST128 | | 0xF0 | MFSR |
| 0x3A | B | | 0xF2 | MTSR |
| 0x3C | JAL | | 0xF4 | SYSCALL |
| 0x3E | JALR | | 0xF6 | IRET |
| 0x54 | LDI | | 0xF8 | INVTP |
| 0x56 | SHORI | | 0xFA | IFENCE |
| 0x58 | LAP | | 0xFC | WFI |
| 0x5A | PRD | | 0xFE | HALT |
| 0x5C | PWR | | | |

Values 0x80-0xEF are reserved for the extensions of section 13 and future
use.

---

## Appendix B -- Out of scope

Defined by companion documents, not this specification: the platform
memory map and device register layouts; the image format and its symbol
sidecar; the trace format and trace query API; the assembler syntax; the
syscall numbering and semantics.
