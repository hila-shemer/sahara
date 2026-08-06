# CONSTRAINTS.md — findings from the Sahara vertical-slice spike

This document is the sole surviving artifact of a deliberately shoddy vertical
slice: a C emulator (sparse memory, radix MMU, traps/interrupts, MMIO
framebuffer + keyboard, deterministic virtual time), a Python assembler with a
parameterized encoding, a Python toy compiler (ints, pointers, structs, arrays,
if/while, functions), and a compiled demo that draws rectangles, takes a
keyboard interrupt mid-computation, and rings an MMIO doorbell whose ordering
against ordinary stores was made observable. Everything ran end to end; the
compiled test program returned bit-exact expected values, and two full demo
runs produced byte-identical 305,122-line traces (replay determinism held).

The slice code is in `slice/` and is disposable. Numbers below come from it.

---

## 1. Answers

### 1.1 What immediate width does the compiler need?

Measured over every immediate the assembler finalized (482 values across all
programs: compiled code + handwritten boot/handler code), smallest signed width
that holds each value:

| kind                | n   | p50 | p90 | max |
|---------------------|-----|-----|-----|-----|
| load/store offsets  | 227 | 11  | 12  | 12  |
| constants (LDI)     | 127 | 4   | 15  | 23  |
| ALU immediates      | 49  | 8   | 12  | 14  |
| branch displacements| 45  | 5   | 9   | 9   |
| SHORI chunks        | 25  | 14  | 25  | 25  |

93.4% of all immediates fit in **12** bits; 99.2% in 24; 100% in 28.

The only immediates that pressure 24 bits are **addresses** (MMIO windows at
0x1F000000/0x20000000 took a 2-instruction LDI+SHORI sequence under the 24-bit
config). Widening to 28 bits did not remove those sequences — a 32-bit address
still needs 2 instructions, and in a sparse 128-bit address space "the address
fits the immediate" is never going to be the common case anyway. Both configs
(24-bit and 28-bit immediate) were built, assembled, and run: program behavior
and even image sizes were identical; the 28-bit config saved a handful of SHORI
instructions (25 → 5 on the demo corpus, mostly in handwritten code).

**Recommendation: 24 bits is enough — provided a PC-relative address-formation
instruction exists** (see 1.9). Without one, address materialization dominates
and even 32 bits doesn't fix it. Spend the 4 recovered bits on the mod field
(shift amounts to 63) as config A does.

Caveat: the corpus is small and has no large struct offsets, no big switch
tables, no linker-relaxed globals. The 12-bit p90 will grow with real programs;
the 24-vs-28 conclusion (addresses are the only pressure, and they need 2+
instructions regardless) should survive.

### 1.2 Does the single format force awkwardness?

Four places, none fatal:

1. **Loads/stores want both an index and a displacement.** The "I-flag means
   imm replaces src2" convention breaks for memory ops, which use
   `src1 + mod(src2) + imm` with all three populated. Resolution: memory ops
   define I=0 and always consume the imm field as displacement. This is a
   definition wrinkle, not an encoding change.
2. **CMP writes a predicate register** — the 5-bit dst field is reinterpreted
   as a 3-bit predicate index. Two bits wasted, decode unaffected.
3. **MFSR/MTSR** use imm as the special-register index. Fine.
4. **SHORI's shift amount equals the immediate width**, so constant-synthesis
   sequences are encoding-config-dependent. Mildly annoying for the assembler;
   invisible to the compiler (it emits a `li` pseudo).

The single format otherwise paid off exactly as hoped: the emulator's decode is
seven shift-and-mask expressions, the assembler is ~300 lines, and the compiler
has no per-instruction operand legality logic at all. Stores carrying data in
src3 is what the third source operand buys on every store; MADD and shifted-
index addressing used it too.

### 1.3 Does predication earn its 4 bits?

**Yes, decisively, and not for the reason expected.** Three distinct uses fell
out of a zero-optimization compiler:

- **All control flow.** There are no conditional-branch opcodes at all; a
  branch is an unconditional jump with a predicate. The entire
  compare-and-branch design problem (flags vs. fused vs. compare-to-register)
  disappeared.
- **If-conversion.** The compiler predicates single-assignment if/else bodies
  instead of branching (9 predicated instructions in the arithmetic test's
  main). Trivial to implement — 30 lines — because *every* instruction takes
  the predicate; no legality checks.
- **Boolean materialization.** `x < y` as a value is CMP + two predicated LDIs.

Dynamic counts from the demo: 17,084 of 322,063 executed instructions (5.3%)
carried a non-default predicate; 16,941 were squashed (dominated by
loop-back-edge branches evaluated false once per loop exit... i.e. mostly the
loop-exit branches tested every iteration). A useful semantic discovered along
the way: **a false-predicated instruction must not fault** — squash before
translation. This makes if-converted speculative loads safe and needs to be in
the spec explicitly.

### 1.4 Are 32 registers correct?

Maximum simultaneous live values observed: **15**, and that was a deliberately
constructed 18-argument function. The realistic peak was **12** (draw_rect: 6
reg-passed params + 2 loop variables + 4 expression temps). The callee-saved
pool (12) was never exhausted; expression-temp depth peaked at 4 of 15.

32 is comfortable and produces zero pressure. The slice cannot justify more,
and gives weak evidence that even 24 would have been livable. No change
recommended; note only that a no-optimizer compiler is register-hungry in a
specific shallow way (it never keeps values live across statements), so real
pressure will come from an optimizer keeping loop invariants — pressure the
slice cannot measure.

### 1.5 How many argument registers?

With 16 argument registers, **no realistic function in the slice touched the
stack path** — the widest natural signature was 6 (framebuffer, x, y, w, h,
color). Stack passing was exercised only by an artificial 18-arg function. The
compiler was re-run with the argument-register count set to 4, 8, and 16 (a
parameter); all three produced correct runs (bit-identical final values), with
stack traffic appearing only below 8.

Answer to the question as posed: **~6–8 registers already starve the
stack-passing path in realistic code; 16 guarantees it is dead code.** That is
an argument *for* 16 only if the goal is "stack args never happen." The risk is
a permanently untested ABI path in every future compiler and unwinder. If 16 is
kept, the real system should carry a conformance test that forces >16-arg calls
forever. (Slice-scale evidence; big variadic/struct-heavy code could change it.)

### 1.6 Full proposed calling convention

Frozen at slice scale, proposed for real:

- **r0–r15 caller-saved.** Arguments in r0–r15 in order; return value in r0
  (r0:r1 if a two-register return is ever needed). r0–r15 are also the
  scratch/temp pool.
- **r16–r27 callee-saved** (12): a function saves exactly the ones it uses.
- **r28 = sp.** 16-byte alignment at all times, grows down.
- **r29 = ra.** Written by JAL/JALR (it is just a dst-field register — the ISA
  has no hidden link register). Caller-saved; non-leaf functions spill it.
- **r30 = k0, kernel-reserved.** Never used by user code; the trap handler's
  only immediately-free register (see 1.8).
- **r31 = zero**, hardwired.
- **Arguments beyond 16** go in 16-byte stack slots at [sp+0] of the caller's
  frame at call time; the callee addresses them at [sp + framesize + 16·i].
  Every stack slot is 16 bytes (pointer-sized); this wasted a third of each
  frame and cost nothing measurable — recommended for its uniformity.
- **No frame pointer.** Fixed-size frames + sp-relative addressing sufficed,
  including for recursion and 18-arg calls. Debug backtraces come from the
  trace API (section 1.11), not a frame chain — this is a real simplification
  the deterministic-trace decision buys.
- Predicate registers are **caller-saved and never preserved across calls**
  (there is currently no way to save them — see 1.8/3.4).

### 1.7 MMU: fanout, node size, depth, walk cost

Layout used: forward-mapped radix over the 112-bit VPN, path compression via a
per-node prefix check (each node stores its chunk's bit position, a prefix, and
a prefix mask; a mismatch faults). Nodes: 64-byte header + 2^IB entries × 16
bytes. Built for a "realistic sparse" layout of 10 regions: four low
(code/data, framebuffer, two MMIO windows) and six scattered across the full
128-bit space (including VAs above 2^64 and 2^100).

| index bits | node size | nodes | total table bytes | max depth | accesses/walk |
|-----------:|----------:|------:|------------------:|----------:|--------------:|
| 8          | 4,160 B   | 14    | **58,240 B**      | 7         | 14.0          |
| 13         | 131,136 B | 11    | **1,442,496 B**   | 5         | 10.0          |

With only the four "OS-like" low regions mapped, IB=8 gave depth 2 and **4
memory accesses per walk**. The wide fanout bought a 30% shallower tree for
**25× the memory** — decisively wrong for a sparse-and-wasteful address-space
policy where regions are many and small. **Recommend 8 (or 9) index bits.**

Path compression did what it was supposed to: worst-case depth for 112-bit VPNs
at IB=8 is 14 levels; observed depth was bounded by the number of
prefix-divergence points among mapped regions (≤7 with 10 scattered regions),
not by address width. Depth scales with log(number of regions), not VPN bits.

Accesses per walk = 2 per level (header + entry). This halves if the entry
format carries the child's chunk position and the prefix check moves into the
child's first line — or drops to 1/level if prefix+shift pack into spare entry
bits. Worth doing in the real design; see sketch (§4.5).

Walk frequency is the elephant: the demo performed 338,940 walks for 322,063
instructions — **1.05 walks per instruction** (every fetch + every load/store,
no caching). Emulator-fine, silicon-fatal; see §3.1.

### 1.8 Trap / interrupt / MMIO semantics (as exercised)

What was built, tested (page fault with cause+address readback and
fault-instruction skip; timer interrupt; keyboard interrupt taken mid-
computation with observable mailbox effect; return via single IRET), and is
proposed:

- **Delivery** (trap or interrupt): `epc ← pc` (faulting instruction for
  faults, next-to-execute for interrupts), `cause ← code`, `baddr ← faulting
  VA` (faults only), `status.PIE ← status.IE`, `status.IE ← 0`,
  `pc ← vbase`. Single vector; software dispatches on cause. One cycle,
  nothing else banked.
- **Return**: IRET does `pc ← epc; IE ← PIE`. **One instruction** sufficed
  precisely because delivery banks almost nothing.
- **Precision**: interrupts are recognized only between instructions; a
  faulting instruction has no architectural effect (checks precede writes); a
  false-predicated instruction cannot fault. Page faults report cause
  (load/store/fetch distinguished) in `cause` and the faulting VA in `baddr`;
  `epc` points at the faulting instruction so software can fix-and-rerun or
  skip (`epc += 8`) — both patterns used in tests.
- **Handler register problem — the real discovery.** A handler cannot save any
  GPR without a free GPR. The slice needed all three of: k0 (reserved GPR) and
  two scratch special registers reachable via MTSR. That was the workable
  minimum. What it still cannot do: save/restore the *predicate* file (no
  pred↔GPR instruction exists — the slice handler silently clobbers p7), and
  it cannot survive a nested fault (a page fault inside a handler overwrites
  epc/cause silently). Both must be fixed in the real design: add PRD/PWR
  (move predicate file to/from a GPR as an 8-bit mass), and either a
  status-stack one level deeper or a documented "handlers pin their memory"
  OS obligation.
- **Masking**: IE=0 during handlers masks interrupts only; faults always
  deliver. No priorities beyond fixed probe order (timer, then input); fine at
  this scale.

**MMIO ordering — measured, not argued.** The emulator has a mode that delays
ordinary stores in a 64-cycle store queue while MMIO stores go straight
through. A compiled program that writes 1000 pixels and immediately writes the
doorbell (no intervening loads) then produces a **torn frame** — the device
snapshot missed the in-flight pixel writes (4 trailing pixels differed). With
the single guarantee "*a store to device space drains all prior program-order
stores first*," output is byte-identical to the strong-order run. Proposed
minimum, and it is genuinely minimal because the failure was reproduced without
it:

1. Device stores act as a release fence for all prior ordinary stores.
2. Device loads/stores are mutually ordered in program order (device registers
   with side effects, e.g. the keyboard-pop, break under reordering).
3. Nothing else. Ordinary↔ordinary ordering needs no guarantee until SMP
   exists; a future FENCE instruction slots into the format trivially.

### 1.9 External oracle viability (lua, sqlite) — done early, in parallel

**The differential-oracle plan is viable.** Result summary (full recipe
preserved below since the scratchpad is ephemeral):

- Both gcc 16 and clang 22 on x86-64 compile **unmodified lua 5.4.7 and the
  sqlite 3.46 amalgamation with 128-bit `size_t`, `ptrdiff_t`, `intptr_t`,
  `uintptr_t`**, by overriding the compiler's predefined type macros:
  `-ffreestanding -U__SIZE_TYPE__ '-D__SIZE_TYPE__=unsigned __int128'` (and
  likewise PTRDIFF/INTPTR/UINTPTR and the `__*_MAX__`/`__*_WIDTH__` macros).
  `-ffreestanding` is required so the compiler's own stdint.h honors the
  overrides; glibc headers still work alongside. gcc additionally needs
  `-D__intptr_t_defined -include stdint.h`; clang needs nothing extra and
  compiles both projects with **zero warnings**.
- Linking against host glibc breaks in exactly two mechanical patterns
  (verified in gdb): functions *returning* size_t (garbage upper half from
  rdx — strlen, fread...) and functions with a *non-trailing* size_t argument
  (later args shift a register — snprintf, fread, mmap...). Trailing size_t
  args are accidentally ABI-compatible. A **6–11 function `-Wl,--wrap` shim**
  fixes it per project.
- So patched: the 128-bit lua passes the **full official lua test suite**
  ("final OK !!!"), and 128-bit sqlite produces **byte-identical output to a
  stock host build** on a 20k-row workload (WAL, window functions, VACUUM,
  integrity_check) — for both compilers.
- One genuine portability bug surfaced, of exactly the class the real target
  will hit: lua's `LUAI_MAXALIGN` union guarantees only 8-byte alignment, but
  a 128-bit size_t member inside a userdata payload needs 16; clang's
  `movaps` faulted. One-line source patch. **Expect this class (max-align
  unions, hardcoded 8-byte alignment) to be the top recurring patch in
  oracle-built code.**
- Known limits of the oracle: host pointers are still 64-bit, so >2^64
  addresses/sizes can be compiled but not executed; `#if` arithmetic on
  SIZE_MAX is capped at 64 bits by the preprocessor spec (neither project
  cares); size_t through varargs to libc would break (neither project does
  it). No off-the-shelf 128-bit-pointer target exists (CHERI/Morello is
  128-bit *capabilities* over a 64-bit address space — answers a different
  question); the eventual real cross-target is a custom clang DataLayout.

**Recommendation:** adopt the macro-override host oracle now, prefer clang,
keep gcc as a free second opinion (its pointer↔int cast warnings inventory
every provenance-relevant site in the target source).

### 1.10 What does 128-bit int cost the compiler?

At slice scale, **nothing where hardware cooperates, one policy decision where
it doesn't**:

- With 128-bit registers and full-width ALU/MUL/DIV/REM instructions, i128 is
  the *native* type; the toy compiler's codegen is type-width-agnostic
  (shift/div/rem on i128 all worked first try, verified against Python
  bigints). The emulator got division free from C's `__int128`.
- Division is only a compiler problem **if the real ISA omits it**. Then
  128-bit divide becomes the largest soft routine the compiler must emit or
  the runtime must carry (~100+ instruction loop). Decide hardware-vs-soft
  divide once, early; everything else about i128 is free.
- The real cost surfaced elsewhere: **narrow types on wide registers need a
  declared canonical form**. The slice chose "int is 64-bit, kept
  sign-extended in 128-bit registers," maintained by sign-extending loads —
  and then never re-canonicalized after arithmetic, which is a latent bug on
  64-bit overflow (compares see the true 128-bit value). The sxt/zxt operand
  modifier exists precisely to make re-canonicalization free at the use site;
  a real compiler must pick canonical-on-write or extend-on-use and say so in
  the ABI.

### 1.11 Codegen wishlist (things reached for that didn't exist)

1. **PC-relative address formation** (`lap rd, imm` → rd = pc + sext(imm)).
   The #1 gap. All address materialization is absolute LDI/SHORI chains (2
   instructions for 32-bit, ~6 for full 128-bit), and images are position-
   dependent. One instruction fixes both, fits the format exactly, and is what
   makes 24-bit immediates sufficient (§1.1).
2. **Predicate↔GPR moves** (PRD/PWR, whole 8-bit file at once). Without them
   trap handlers cannot preserve predicate state (§1.8) and booleans
   materialize as two predicated LDIs.
3. That's the whole list. Notably absent: select (predication covers it),
   fused compare-branch (predicated jump covers it), scaled-index addressing
   (the mod field covers it), store-immediate (the zero register covers the
   common case). The shift-mod on src2 was used constantly by array codegen —
   it earns its field.

### 1.12 What the debugger needed and didn't have

What was actually used, all of which the real trace API should subsume: the
per-instruction trace (cycle, pc, dst value), `diff` of two traces (the
determinism check — the real API's first-divergent-cycle), framebuffer dumps
compared byte-wise (device-state snapshot diff — this is how the MMIO ordering
bug was *observed*), and the emulator's counter file.

What was missed, concretely, during slice debugging:

- **Symbolization.** Traces show raw PCs; every lookup was a manual grep of
  the assembler listing. The image format needs a symbol sidecar from day one.
- **Disassembly in the trace** (it printed opcode numbers).
- **last-writer-to(addr)** — wanted while checking the interrupt handler's
  mailbox write; reasoned it out instead, on a 300k-line trace that stops
  scaling.
- **find-cycle-where(pc == X | wrote-reg r == v | touched-addr a)** — the
  general form of every question actually asked of the trace.
- Never wanted: single-stepping, breakpoints, a live REPL. With deterministic
  replay, *post-hoc queries over a completed trace* covered everything; the
  agent-consumer premise looks right. Reverse-continue is just
  find-last-cycle-where; it needs no interactive machinery.

---

## 2. Invented semantics

Everything the frozen decisions did not specify, decided in order to proceed.
(Running log with rationale: `slice/DECISIONS-LOG.md`.)

| # | Decision | Note |
|---|----------|------|
| 1 | 8 predicate registers; p0 hardwired true; pred field = 3-bit selector + polarity | forced by 4-bit field |
| 2 | Register roles: r0–r15 caller, r16–r27 callee, sp=r28, ra=r29, k0=r30, zero=r31 | zero-as-GPR makes mov/nop free |
| 3 | Opcode LSB is the I-flag (src2 ⇒ immediate); register and imm forms at adjacent opcodes | keeps compiler to one rule |
| 4 | mod field = 2-bit kind (none/shl/sxt/zxt) + amount | shifts ≥64 use SHL proper |
| 5 | Special registers via MFSR/MTSR, index in imm: status, epc, cause, baddr, vbase, ptbase, cycle, timecmp, scratch0/1 | |
| 6 | Trap-handler register budget: k0 + two scratch sregs | the workable minimum found |
| 7 | Trap model: single vector + cause register; epc/cause/baddr; IE/PIE one deep; IRET is one instruction | exercised by tests |
| 8 | Cause codes: timer=0 kbd=1 pf_load=2 pf_store=3 pf_fetch=4 illegal=5 unaligned=6 | arbitrary |
| 9 | Natural alignment required; unaligned access traps | smallest emulator, loud failures |
| 10 | Branch disp counts instructions relative to the branch; JALR is a byte address, must be 8-aligned | |
| 11 | CMP selects its predicate via dst-field low 3 bits | |
| 12 | Loads sized with explicit sx/zx to 128; stores carry data in src3; addr = src1+mod(src2)+imm | |
| 13 | LDI/SHORI constant synthesis; SHORI shifts by IMM_BITS | config-dependent sequence length |
| 14 | STATUS: IE=b0, PIE=b1, MMU_EN=b2; no user mode at all in the slice | real design needs a mode bit |
| 15 | Page tables built by "firmware" (emulator flag) before boot; guest only enables MMU and issues INVTP | runtime remap unexercised — honest gap |
| 16 | 1 instruction = 1 virtual cycle; walks are counted but don't advance time | |
| 17 | Memory ops ignore the I-flag and always use src2+imm | define I=0 for them in the real spec |
| 18 | Divide by zero: all-ones / dividend-unchanged, no trap | RISC-V-style |
| 19 | int is 64-bit sign-extended-canonical in 128-bit regs; compiler never re-canonicalizes | latent overflow class, accepted |
| 20 | Predicate file has no save/restore path; handler clobbers p7 | real hole → PRD/PWR proposed |
| 21 | Weak-store-queue mode in the emulator (64-cycle delay, loads drain, MMIO drains or bypasses) | experiment apparatus, not architecture |

---

## 3. Evidence against frozen decisions

Stated plainly, per the brief.

1. **"No TLB" is already false in spirit.** The demo executed 1.05 page walks
   per instruction (338,940 walks / 322,063 instructions), at 4 memory
   accesses per walk in the friendly layout and 14 in the scattered one. A
   translation cache is not a later optimization; it is the difference between
   4× and 1× memory traffic on *every* instruction. The INVTP-now decision is
   therefore the most load-bearing frozen decision, and the slice weakened it:
   with firmware-built static tables, the OS-side contract ("issue INVTP after
   every mapping change") was never actually exercised — one INVTP at boot is
   all that ever ran. The real system must bring up OS-owned page tables and
   runtime remap early, or the contract will erode exactly as feared. Also:
   when the cache arrives, "no ASIDs" makes every address-space switch a full
   invalidate; fine for a single-address-space OS, worth restating as a
   *consequence* in the spec.
2. **16 argument registers guarantee the stack-argument path is dead code**
   (§1.5). Nothing realistic in the slice passed more than 6. Keep 16 only
   with a standing conformance test that forces the stack path.
3. **The instruction set as frozen cannot save its own predicate state**
   (§1.8). "Separate predicate registers" + "no flags word" is right, but
   without a pred↔GPR move the predicate file is architecturally invisible to
   context switches and trap handlers. Not evidence against predication —
   evidence that the register-file decision is incomplete without PRD/PWR.
4. **Pointers-in-registers are 128-bit, but nothing in the slice ever needed
   an address above 2^33 except by construction.** The cost showed up only as
   constant-synthesis length and 16-byte stack slots — both cheap. No
   evidence against; recorded because the slice *cannot* falsify the 128-bit
   decision and shouldn't be read as having tried. The lua/sqlite oracle
   (§1.9) is the decision's real support.
5. **"Sparse and wasteful" collides with wide radix nodes.** At 13 index
   bits, ten mapped regions cost 1.4 MB of page table. The frozen sparsity
   policy effectively *forces* the narrow-fanout choice (§1.7); the two
   decisions are coupled and should be written down as such.
6. **Full predication + "squash cannot fault" has a hidden cost the slice
   didn't model:** a predicated-false load still occupies the pipeline and
   the predicate must resolve before the fault decision. Invisible in a
   1-cycle emulator; flagged for whoever does timing later. No action now.

---

## 4. Proposed ISA sketch

A proposal for the real design, incorporating the fixes above. Precise enough
to implement an emulator against. Little-endian throughout; byte-addressed
memory; all 32 GPRs are 128-bit; 8 one-bit predicate registers.

### 4.1 Instruction format

One 64-bit format, fields LSB→MSB (config A, the recommended one):

| field  | bits | position | meaning |
|--------|-----:|---------:|---------|
| opcode | 8    | 0–7      | bit 0 = I-flag (src2 is the immediate); bits 1–7 = major opcode |
| pred   | 4    | 8–11     | bit 8 = polarity (1 = execute when false); bits 9–11 = predicate index |
| dst    | 5    | 12–16    | destination register (predicate index for CMP*, low 3 bits) |
| src1   | 5    | 17–21    | source 1 |
| src2   | 5    | 22–26    | source 2 (ignored when I=1, except memory ops: always live) |
| src3   | 5    | 27–31    | source 3 (store data; MADD addend) |
| mod    | 8    | 32–39    | src2 modifier: bits 0–1 kind (0 none, 1 shl, 2 sxt, 3 zxt), bits 2–7 amount |
| imm    | 24   | 40–63    | immediate, sign-extended unless noted |

Instructions are 8-byte aligned; PC-relative displacements count instructions.
An instruction whose predicate evaluates false has **no architectural effect
and cannot fault**. Writes to r31 are discarded; reads return 0. Writes to p0
are discarded; reads return 1.

`mod` applies to the value read from src2: `shl` shifts left by amount (0–63);
`sxt`/`zxt` sign-/zero-extend from the low *amount* bits (amount 0 = no-op).

### 4.2 Registers and ABI

r0–r15 caller-saved (arguments 0–15, return in r0) · r16–r27 callee-saved ·
r28 sp (16-byte aligned) · r29 ra · r30 k0 (kernel scratch, off-limits to user
code) · r31 zero. Predicates caller-saved. Stack slots 16 bytes; excess args
at [sp+0] of the caller frame. No frame pointer.

### 4.3 Instruction list

`b` below = I ? sext(imm24) : mod(R[src2]); all ALU ops are full 128-bit.

- **ALU**: ADD, SUB, AND, OR, XOR, SHL, SHR, SAR (shift count = low 7 bits of
  b), MUL (low 128), MADD (dst = src1·b + src3), UDIV, SDIV, UREM, SREM
  (div-by-zero: all-ones / dividend; no trap).
- **Compare** (writes predicate dst&7): CMPEQ, CMPLT, CMPLTU, CMPLE, CMPLEU.
  Polarity at the *consumer* covers the negations.
- **Memory** (I=0 always; ea = R[src1] + mod(R[src2]) + sext(imm); natural
  alignment or trap): LD8U/8S/16U/16S/32U/32S/64U/64S/128 (extend to 128);
  ST8/16/32/64/128 (data in src3).
- **Control**: B (pc += sext(imm)·8; predication makes it conditional), JAL
  (dst = pc+8, pc += sext(imm)·8), JALR (dst = pc+8, pc = R[src1]+sext(imm),
  trap if not 8-aligned).
- **Constants/addresses**: LDI (dst = sext(imm)), SHORI (dst = R[src1]<<24 |
  zext(imm)), **LAP** (dst = pc + sext(imm), byte address) — new, per §1.11.
- **Predicates**: **PRD** (dst = predicate file as bits 7..0), **PWR**
  (predicate file ← low 8 bits of R[src1], bit 0 ignored) — new, per §1.8.
- **System**: MFSR/MTSR (special register index in imm), IRET, INVTP
  (invalidate cached translations — architectural nop until a translation
  cache exists; the OS must issue it after every mapping change before the
  next dependent access), HALT (slice artifact; becomes WFI-or-similar later).

Special registers: 0 status (b0 IE, b1 PIE, b2 MMU_EN), 1 epc, 2 cause,
3 baddr, 4 vbase, 5 ptbase, 6 cycle (RO), 7 timecmp, 8–9 scratch0/1.
Causes: 0 timer, 1 input, 2 pf_load, 3 pf_store, 4 pf_fetch, 5 illegal,
6 unaligned.

### 4.4 Trap model

As §1.8: single vector (vbase), delivery writes epc/cause/baddr and one-deep
IE→PIE, IRET restores in one instruction. Faults always deliver; interrupts
only when IE, between instructions. Timer fires while cycle ≥ timecmp ≠ 0;
input IRQ asserts while the device queue is non-empty (level-triggered — the
handler pops the device to clear). Handler contract: k0 + scratch0/1 to free
registers, PRD/PWR to preserve predicates, and no page faults inside handlers
until nested-trap support is designed (open issue, flagged).

### 4.5 MMU interface

64 KB pages; VPN = VA[127:16]. ptbase points at the root node. Radix tree,
**8-bit** index chunks on a fixed grid (chunk k covers VPN bits [8k, 8k+8)),
path-compressed. Node = 64-byte header {shift u64; prefix u128; prefix_mask
u128} + 256 entries × 16 bytes. Entry low 2 bits: 0 invalid, 1 table (bits
127:6 = child physical address, 64-byte aligned), 2 leaf (bits 127:16 =
frame). Walk: check `vpn & mask == prefix` (else fault), index by
`(vpn >> shift) & 255`, repeat; leaves are legal only at shift 0. Measured
cost §1.7. Recommended refinement before freezing: move each node's
shift+prefix into its parent entry's spare bits (a 64KB-aligned child pointer
leaves 6+16 low bits, and a leaf-vs-table redesign can free more) to halve
walk accesses; the slice did not implement this.

Aliasing is naturally supported (two leaves, one frame). No permissions bits
existed in the slice; the real design adds R/W/X in leaf low bits (4 spare
bits remain below the frame field) plus a user bit when a user mode exists.

### 4.6 MMIO and ordering

Devices occupy physical address windows; accesses are ordinary sized
loads/stores. Guarantees (measured minimum, §1.8): device stores drain all
prior ordinary stores; device accesses are mutually program-ordered; ordinary↔
ordinary unconstrained until SMP. Device reads may have side effects (the
input-queue pop does).

### 4.7 Virtual time

cycle increments by 1 per retired instruction and is readable (sreg 6). All
device events are (cycle, payload) items in a synchronous queue; input traces
replay bit-exactly (verified: two demo runs, 305,122-line traces, identical).

---

## 5. What I would do differently (for the real build)

1. **Keep encoding-as-data.** One Python file was the single source of truth
   for field layout, opcodes, and the generated C header; switching immediate
   width was a one-word rebuild. The real project should extend this to
   generate the disassembler and the trace decoder too — the slice printed
   raw opcode numbers in traces and paid for it in every debugging session.
2. **Build the trace/diff/symbolization harness before the compiler.**
   Determinism + trace-diff was the most valuable debugging property and it
   was nearly free. Symbol sidecars in the image format from day one.
3. **Bring up traps/interrupts/MMIO second, not last.** The brief was right:
   t2 (traps) found the three genuinely novel semantic problems (handler
   register budget, predicate save, nested faults) at a cost of ~80 assembly
   lines. Everything ALU-shaped was routine by comparison.
4. **Don't let "firmware" build the page tables in the real system.** It made
   the slice cheap but silently un-exercised the one contract the frozen
   decisions most care about (INVTP after remap). OS-owned tables + a
   remap-under-fire test early.
5. **Run the external-oracle experiment before designing the compiler.** It
   ran in parallel here and could have invalidated the plan; instead it
   produced the flag recipe, the shim pattern, and the alignment-bug class to
   watch for — all reusable verbatim later.
6. **A stack-discipline temp allocator + callee-saved locals is enough
   compiler for ISA questions.** ~600 lines of Python answered register
   pressure, immediates, predication, and ABI questions. Resist building SSA
   for a measurement instrument. But *do* write the compiler correctness test
   (t3-style, checked against host arithmetic) before the demo — it caught
   nothing here only because it ran first.
7. **Make every experiment a flag, not a fork.** argregs, index-bits,
   weak-store mode, encoding config — each being a command-line/env parameter
   is what made the measurement matrix cheap (the whole sweep is ~10 shell
   commands).
8. **Device-state snapshot diffing is a first-class test primitive.** The
   MMIO-ordering result is a byte-count between two PPM dumps. Keep "dump
   device state at doorbell, compare" in the permanent test vocabulary.
