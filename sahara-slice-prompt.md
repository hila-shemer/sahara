# Sahara — Vertical Slice Spike

## What this is

Sahara is a from-scratch computer: instruction set, emulator, assembler, self-hosting
compiler, operating system, libraries, GUI. It is a toy in the sense that it is
unoptimized, and complete in the sense that it is meant to actually run interactive
applications.

This task is **not** building Sahara. It is building a deliberately shoddy vertical
slice through the whole stack in order to discover what the real ISA needs to be.

**The code you write here is disposable and will be deleted.** The deliverable is a
document. Do not become attached to the implementation, do not polish it, do not
refactor it, do not write it to be extensible. Write the fastest thing that answers
the questions in section 4.

Budget: this should take a small fraction of the effort of the real system. If you
find yourself building infrastructure, stop and ask whether it answers a question.

## 1. Frozen decisions

These are settled. Do not redesign them. If the slice produces evidence that one of
them is wrong, **record that in the output document** — do not act on it.

**Registers**
- 128-bit general purpose registers
- 32 of them, split ~16 caller-saved / 12 callee-saved / 4 special
- Separate predicate registers (see below). No global condition-flags word.

**Pointers and memory**
- Pointers are 128 bits, flat, with no hardware-interpreted structure
- Memory is byte-addressed
- No tagged memory, no capabilities, no unforgeable pointers. The hardware does not
  know about types. That belongs to a language runtime, not a CPU.
- The address space is expected to be used sparsely and wastefully. Nothing is ever
  reused if it can be avoided.

**Instructions**
- 64-bit fixed-width instructions
- **One instruction format.** Fixed field positions for opcode, destination, three
  sources, predicate, and immediate. Instructions that do not need a field ignore it.
  This is the single most important property of the encoding: decode is shifts and
  masks with no format dispatch, and the compiler never has a "this operand can be an
  immediate here but not there" special case.
- Full predication: every instruction carries a predicate register selector and a
  polarity bit
- Three source operands (enables multiply-add, shift-add for array indexing,
  bitfield insert, select)
- Operand modifiers on src2: shift-by-N, sign-extend-from-width, zero-extend
- 8-byte instruction alignment, so branch displacements count instructions

**MMU**
- 64KB pages
- Forward-mapped radix tree with path compression
- Aliasing allowed (multiple virtual mappings to one physical frame)
- No ASIDs — there is no TLB, so they would mean nothing
- **Define an invalidate-translation instruction now.** It is architecturally a nop in
  this version. The OS must be written to issue it after every mapping change, so
  that adding a translation cache later does not require auditing every page-table
  write site.

**Emulator**
- Written in C
- Memory is sparse from day one: a hash map from page number to allocated block,
  faulting on miss. Never a flat allocation.
- **Deterministic virtual time.** Cycle-counted, driven by a synchronous event queue.
  Never wall clock, never host RNG, never host time. An input trace must replay
  bit-exactly.

**Non-goals**
- Performance, of the emulator or of emitted code. Ignore it entirely except where
  section 4 asks for a measurement.
- Code density.
- Do not apply the `rightwayc` doctrine here. This is throwaway code.

## 2. What to build

The smallest thing that exercises every layer:

1. **Emulator** — sparse memory, radix MMU, the instruction subset needed below,
   trap/interrupt delivery, virtual-time event queue.
2. **Assembler** — enough to assemble the programs below. Text in, image out. It may
   be crude.
3. **Toy compiler** — a tiny C-like language: integers, pointers, functions, `if`,
   `while`, arrays, struct field access. No optimizer. Written in whatever host
   language is fastest for you (Python is fine and probably correct).
4. **Peripherals** — a framebuffer and a keyboard or pointer device, both driven
   through MMIO, both on the virtual-time event queue.
5. **Demo program** — draws a rectangle to the framebuffer, in the toy language,
   compiled by the toy compiler, running on the emulator.
6. **One interrupt** — a timer or input interrupt that is taken, handled, and
   returned from, with observable effect.
7. **One MMIO write** with ordering that matters relative to a surrounding memory
   access.

Items 6 and 7 are not optional garnish. Trap semantics, interrupt delivery, and MMIO
ordering are the parts of an ISA with the least useful prior art to copy and the
highest chance of latent error, and they stay invisible until something exercises
them. They are a primary reason this spike exists.

## 3. Method notes

- Make the instruction encoding a parameter, not a hardcoded layout. Field widths
  (register field bits, immediate width) should be changeable in one place, because
  section 4 asks you to try more than one.
- Keep a running log of every point where you had to invent a semantic that the
  frozen decisions did not specify. That log is most of the final document.
- Where you make an arbitrary choice, say so explicitly rather than presenting it as
  derived.

## 4. Questions the slice exists to answer

Answer each of these with evidence from the slice, not from reasoning alone. If a
question turns out to be unanswerable at this scale, say so and say why.

**Encoding**
- What immediate width does the toy compiler actually need? Measure the distribution
  of immediate magnitudes in emitted code. Candidate range is 24–32 bits.
- Does the single-format constraint force awkwardness anywhere, and where?
- Does predication earn its encoding cost, or does the compiler never use it? Report
  how many emitted instructions were predicated.
- Are 32 registers correct? Report the maximum simultaneous live values the toy
  compiler needed.

**ABI**
- How many argument registers are needed before the stack-passing path stops being
  exercised by realistic code? 16 is the candidate.
- Propose a full calling convention: argument registers, return value, caller/callee
  save split, frame pointer or not, where the return address lives. This freezes
  early and permanently, so it deserves disproportionate care relative to the rest of
  the slice.

**MMU**
- What radix node fanout is right? Try at least two index widths (e.g. 8–9 bits vs.
  13 bits) and report node size, tree depth, and total memory for a realistic sparse
  layout. Path compression should absorb most of the depth cost of narrow indices.
- How many actual memory accesses does a walk take for a typical sparse layout?

**Trap / interrupt / MMIO**
- Full proposed semantics: what state is saved and by whom, what is masked and when,
  what a precise fault means here, how a page fault reports its cause and faulting
  address, whether interrupt return is one instruction or several.
- What ordering guarantees do MMIO accesses need relative to ordinary memory
  accesses, and what is the minimum the hardware must provide?

**External oracle viability** *(do this early — it can invalidate later plans)*
- Cross-compile **lua** with a host toolchain configured for 128-bit `size_t`,
  `intptr_t`, and `ptrdiff_t`. Does it build clean? What breaks?
- Repeat for **sqlite** if lua succeeds.
- This matters because the plan for the real system is to defend against spec erosion
  by requiring the real compiler to build unmodified third-party source and
  differential-test its behavior against the host toolchain. If 128-bit pointers make
  that impossible, we need to know now, not at layer 4.

**Compiler**
- What does a 128-bit integer type cost the compiler? Division in particular.
- What instructions did you find yourself wishing existed while writing codegen?

**Debugging**
- What would you have needed from a debugger that you did not have? The real system
  will have a queryable trace API — reverse-continue, last-writer-to-address,
  first-divergent-cycle between two traces — aimed at an agent consumer rather than a
  human one. This slice is the cheapest place to find out what queries actually
  matter.

## 5. Output

Produce `CONSTRAINTS.md` at the repo root. It is the only artifact that survives.

Structure it as:

1. **Answers** — one section per question in section 4, with the evidence.
2. **Invented semantics** — everything you had to decide that the frozen list did not
   cover, each with the choice made and the rationale.
3. **Evidence against frozen decisions** — anything the slice suggests is wrong,
   stated plainly, with what you observed. Do not soften this. This section is
   valuable in proportion to how uncomfortable it is.
4. **Proposed ISA sketch** — encoding layout, instruction list, trap model, MMU
   interface. Precise enough that someone with no other context could implement an
   emulator from it. This is a proposal for the real design, not a description of
   what you built.
5. **What I would do differently** — construction-order and tooling notes for the
   real build.

Write it for a reader who has none of your context and will not read your code.

## 6. Rules

- Do not push to any remote. If you want to push, ask first, and only to a branch
  whose name has been approved.
- Patch files as artifacts are an acceptable substitute for pushing.
- Do not optimize anything.
- Do not build for extensibility.
- When the questions in section 4 are answered, stop. Do not continue building.
