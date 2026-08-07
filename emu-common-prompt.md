# Sahara emulator — common build prompt (both implementations)

You are one of two agents independently implementing the Sahara emulator —
one in C (`emu-c/`), one in Python (`emu-py/`). Read this file plus your
language-specific prompt (`emu-c-prompt.md` or `emu-py-prompt.md`). The two
implementations exist to be diffed against each other: every conformance
test runs on both, traces are compared record-by-record, and every
divergence is either a bug in one implementation or a spec ambiguity. That
only works if the implementations are independent.

**Independence rule:** you never read the other implementation's directory,
branch, or worktree. You implement from the specs alone. If the repo has a
dispatched-subagent contract skill, you operate under it.

## Context files (read all before writing anything)

In the repo root, in this order:

1. `ISA-SPEC.md` — the normative architecture. Highest authority.
2. `PLATFORM-SPEC.md` — memory map, device table, display/keyboard/mouse/
   NIC, boot protocol.
3. `TOOLING-SPEC.md` — image format, symbol sidecar, trace format,
   `trace-q` queries, assembler.
4. `CONFORMANCE.md` — the suite you are building toward. C1–C4 cover
   semantics never validated anywhere; they are the point.
5. `encoding.py`, `crosscheck.py`, `sahara_isa.h` — encoding-as-data. The
   header is generated (`python3 encoding.py cheader sahara_isa.h`) and
   `crosscheck.py ISA-SPEC.md` must pass in CI. Nothing anywhere may
   hardcode a field position, opcode value, sreg index, or cause code:
   consume the generated header (C) or import encoding.py (Python).
6. `slice/` and `CONSTRAINTS.md` if present — a throwaway spike. You may
   read it for orientation. Do not copy code from it; it predates the spec
   and diverges from it.

Where any document is silent, the precedence is: ISA-SPEC, then
PLATFORM-SPEC, then TOOLING-SPEC. Where a document is ambiguous or seems
wrong: implement your best reading, and record it in your directory's
`SPEC-ISSUES.md` — file:section, the ambiguity, the reading you chose. Do
not silently pick. That file is a first-class deliverable. (It lives inside
your directory — `emu-c/SPEC-ISSUES.md` or `emu-py/SPEC-ISSUES.md` — so the
two branches never conflict on it.)

## Shared toolchain (consumed, not built)

`asm/`, `trace-q/`, and `tests/` are owned by a separate toolchain agent
and land on `main`. You do not write an assembler, a trace query tool, or
the conformance suite; you merge `main` into your branch periodically to
pick them up, and you never modify those directories. A test you believe is
wrong is a SPEC-ISSUES entry (say whether you think the bug is in the test
or the spec), not an edit.

Until the assembler lands, bootstrap by assembling test words
programmatically with encoding.py (it is importable and can emit single
instructions as data). Do not write a throwaway assembler.

## CLI contract (frozen — both implementations identical)

    <emulator> IMAGE [--replay events.trc] [--trace out.trc --trace-level N]
               [--maxcycles N] [--ram BYTES] [--check-invtp]
               [--check-devorder N]

On HALT: print exactly `HALT r0=<32 hex digits>` to stdout and exit 0.
On `--maxcycles` exhaustion: print `MAXCYCLES` and exit 2. On a check-mode
assertion: print `CHECKFAIL <one-line reason>` and exit 3. Internal errors
exit nonzero with a message on stderr. The shared test harness and the
cross-implementation diff depend on this contract byte-for-byte.

## Requirements with teeth

- **Determinism is non-negotiable.** The core must not read wall clocks,
  host RNG, thread timing, or uninitialized memory. Every test runs twice
  and diffs traces.
- **Sparse memory from the first line.** Map page-number → block. No flat
  allocation, no fixed RAM ceiling baked into the core.
- **Trace format exactly per TOOLING-SPEC §3.2.** Byte-identical output is
  the cross-implementation comparison medium; treat every field width and
  record ordering as normative.
- **INVTP check mode** (`--check-invtp`): a phantom translation cache whose
  only effect is to assert if a translation would have been served stale.
  C2 requires it. On in all conformance runs.
- **Weak-store check mode** (`--check-devorder N`): store queue of depth N
  for ordinary stores, device stores draining it, per ISA-SPEC 9.2. C7
  uses it.
- **Trap semantics exactly per ISA-SPEC 7.2–7.4** including the
  double-fault bank, triple-fault halt, TL writability, and
  squash-cannot-fault. These are C1 and the most likely to find spec bugs —
  when one does, SPEC-ISSUES.md, not a workaround.
- 128-bit arithmetic including MULH at width 128 (128×128→256 high half) —
  see your language prompt for the mechanism; test against an independent
  computation in CI.
- FP: FCVT saturation/NV semantics are specced precisely — implement from
  the spec, not from your language's cast behavior.
- Fuzz the decoder: random 64-bit words must never crash the emulator;
  they either execute or trap ILLEGAL. Add this to your test script.

## Device interface (in the core from day one)

Devices arrive as a later phase, but the core grows these seams first:
MMIO dispatch hooked off the sparse-memory path per PLATFORM-SPEC's map;
virtual-cycle event injection (the EVENT queue that replay feeds); trace
hooks for DEVW/EVENT. Detailed device behavior specs are being authored in
parallel under `devspec/`; that directory may appear on `main` mid-build.
PLATFORM-SPEC remains authoritative until `devspec/INDEX.md` exists; after
that, devspec documents govern their devices. Do not start device
internals before your core passes C1–C6.

## Build order (roughly serial; keep commits small)

1. Encoding consumption + crosscheck wired into your build script; trace
   writer first (the debugging tools exist before the first bug).
2. Core: memory, decode dispatch, ALU/compare/predication; run C5/C6 as
   they become available, encoding.py-assembled smoke tests before that.
3. Traps, privilege, MMU with check mode; C1/C2 (the hard ones — budget
   accordingly).
4. Atomics, FP; C3/C4.
5. Load real images (`.img` + `.sym`), boot path.
6. Platform devices headless (device table, display-to-PPM, event
   injection from trace files); C7 — gated on devspec/ as above.

## Rules

- Work only inside your own directory (`emu-c/` or `emu-py/`) plus your
  build/test entry points. Never touch the frozen specs, encoding files,
  `asm/`, `trace-q/`, `tests/`, or the other implementation.
- Do not push to any remote, ever, without asking Hila interactively
  first; pushes only to a newly created branch whose name she approved.
  Committing locally is unrestricted and encouraged.
- No performance work. Clarity is the optimization target.
- When the conformance suite and the spec disagree, the spec wins; when
  the spec and your intuition disagree, the spec wins *and* SPEC-ISSUES.md
  gets an entry. The spec changes only by Hila editing it.
- Stop when the shared suite is green under your emulator with
  determinism double-runs, decoder fuzz, and crosscheck included. Do not
  begin the compiler, the OS, or anything not listed in your prompts.
