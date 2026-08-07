# Sahara emulator v1 — Claude Code build prompt

## Context files (read all before writing anything)

In the repo root, in this order:

1. `ISA-SPEC.md` — the normative architecture. Highest authority.
2. `PLATFORM-SPEC.md` — memory map, device table, display/keyboard/mouse/NIC,
   boot protocol.
3. `TOOLING-SPEC.md` — image format, symbol sidecar, trace format, `trace-q`
   queries, assembler.
4. `CONFORMANCE.md` — the test suite you are building toward. Groups C1–C4
   cover semantics that have never been validated anywhere; they are the
   point.
5. `encoding.py`, `crosscheck.py`, `sahara_isa.h` — encoding-as-data. The
   header is generated (`python3 encoding.py cheader sahara_isa.h`) and
   `crosscheck.py ISA-SPEC.md` must pass in CI. Nothing anywhere may
   hardcode a field position, opcode value, sreg index, or cause code:
   consume the generated header (C) or import encoding.py (Python).
6. `slice/` and `CONSTRAINTS.md` if present — the throwaway spike this
   design came from. You may read it for orientation. Do not copy code from
   it; it predates the spec and diverges from it (24-bit immediates, no
   width field, different opcode map, no privilege, no FP, no atomics).

Where any document is silent, the precedence is: ISA-SPEC, then
PLATFORM-SPEC, then TOOLING-SPEC. Where a document is ambiguous or seems
wrong: implement your best reading, and record it in `SPEC-ISSUES.md` —
file:section, the ambiguity, the reading you chose. Do not silently pick.
That file is a first-class deliverable.

## Deliverables

A repo that builds with `./build.sh` and passes `./run-tests.sh`:

1. **`emu/`** — the reference emulator, C11, portable. Core is a library
   with no GUI dependency; two front ends:
   - `sahara-emu` (headless): `sahara-emu IMAGE [--replay events.trc]
     [--trace out.trc --trace-level N] [--maxcycles N] [--ram BYTES]`
   - `sahara-gui`: SDL2 front end — display window, keyboard/mouse capture,
     NIC bridged to host (slirp-style; a minimal DHCP+NAT UDP/TCP/ICMP-echo
     translator you write is acceptable; document what subset works).
     Every GUI session records its event trace; any session replays
     headless bit-exactly.
2. **`asm/`** — the assembler per TOOLING-SPEC §4, Python, importing
   encoding.py.
3. **`trace-q/`** — the query tool per TOOLING-SPEC §3.3. Python is fine.
   Disassembly comes from encoding.py metadata.
4. **`tests/`** — the conformance suite: all of C1 through C7 from
   CONFORMANCE.md, plus the reference-implementation checks. Self-checking
   assembly per the harness rules there. FP vectors: generate expected
   values with a small host C program at build time, commit the generated
   data file.
5. **`SPEC-ISSUES.md`** — see above.

## Requirements with teeth

- **Determinism is non-negotiable.** The core library must not read wall
  clocks, host RNG, thread timing, or uninitialized memory. Every test in
  CI runs twice and diffs traces. The GUI front end is the only component
  allowed to touch real time, and only to *timestamp* events into virtual
  cycles.
- **Sparse memory from the first line.** Hash map page-number → block.
  No flat allocation, no fixed RAM ceiling baked into the core.
- **INVTP check mode** (`--check-invtp`): model a phantom translation
  cache whose only effect is to *assert* if a translation would have been
  served stale (i.e., software changed tables without INVTP/asid change).
  C2 requires it. Ship it on in all conformance runs.
- **Weak-store check mode** (`--check-devorder N`): a store queue of depth
  N for ordinary stores with device stores draining it, per ISA-SPEC 9.2.
  C7 uses it to prove the ordering rules are load-bearing.
- **Trap semantics exactly per spec 7.2–7.4** including the double-fault
  bank, triple-fault halt, TL writability, and squash-cannot-fault. These
  are C1 and they are the tests most likely to find spec bugs — when one
  does, SPEC-ISSUES.md, not a workaround.
- 128-bit arithmetic: `unsigned __int128` is available (gcc/clang). MULH
  at width 128 needs a manual 128×128→256 high half — test it against
  Python bigints in CI.
- FP: host `float`/`double` arithmetic is IEEE-conformant for the
  operations specced; set rounding via `fesetround` per fcsr, compute
  flags via `fetestexcept`. FCVT saturation/NV semantics are specced
  precisely — implement from the spec, not from C cast behavior.
- Fuzz the decoder: random 64-bit words must never crash the emulator;
  they either execute or trap ILLEGAL. Add this to run-tests.sh.

## Build order (roughly serial; keep commits small)

1. encoding regeneration + crosscheck wired into build.sh; trace writer +
   `trace-q diverge` (the debugging tools exist before the first bug).
2. Core: memory, decode dispatch, ALU/compare/predication; C5/C6 tests
   alongside.
3. Traps, privilege, MMU with check mode; C1/C2 (the hard ones — budget
   accordingly).
4. Atomics, FP; C3/C4.
5. Assembler full spec; image+sym; boot a real image.
6. Platform devices headless (device table, display-to-PPM, event
   injection from trace files); C7.
7. GUI front end + NIC last.

## Rules

- Do not push to any remote, ever, without asking Hila interactively
  first; pushes only to a newly created branch whose name she approved.
  Committing locally is unrestricted and encouraged.
- No performance work. No optimization flags beyond -O1. Clarity is the
  optimization target: this is the *reference* implementation other
  implementations will be diffed against.
- Plain portable C11 for the emulator core unless told otherwise. Do not
  apply the rightwayc doctrine to this repo. [Hila: flip this line if you
  want doctrine here.]
- When the conformance suite and the spec disagree, the spec wins; when
  the spec and your intuition disagree, the spec wins *and* SPEC-ISSUES.md
  gets an entry. The spec changes only by Hila editing it.
- Stop when run-tests.sh is green with determinism double-runs, decoder
  fuzz, and crosscheck all included. Do not begin the compiler, the OS, or
  anything not listed under Deliverables.
