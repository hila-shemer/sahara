# Sahara conformance suite

Self-checking assembly per CONFORMANCE.md. One file per group; each test
block sets a test ID, computes a result, and compares it against an
expected value computed independently of any emulator (by hand or by the
committed generator scripts — never by running an emulator under test).

## Conventions

- **Success:** HALT with `r0 = 0x600D`. The harness expects stdout
  `HALT r0=0000000000000000000000000000600d` exactly (lowercase hex —
  SPEC-ISSUES.md entry 3). Tests that end in an architectural halt that
  is not the HALT instruction (triple fault, WFI deadlock — SPEC-ISSUES
  entry 12) put a marker in r0 instead and carry
  `expect=<32 lowercase hex>` on their MANIFEST line. Tests whose
  CORRECT outcome is a check-mode assertion (the c2_noinvtp_* pair)
  carry `expect=checkfail`: exit 3 + first stdout word CHECKFAIL, the
  implementation-worded reason is not compared (SPEC-ISSUES 22/23).
- **Failure:** store the failing test ID as u64 to **PA 0x700**, then
  HALT with `r0 = <test ID>`. Diagnose with
  `trace-q last-write 0x700 out.trc` and
  `trace-q at <pc>` / `range` around the failing block.
- **Scratch addresses** (all in RAM below the device table, never part
  of any image segment):
  - `0x700` failing test ID (u64)
  - `0x710` squash box — no access may ever touch it (checked from the
    trace by `checks/*.sh`)
  - `0x718` sentinel box — general readback scratch (odd offsets
    `0x719`/`0x71a`/`0x71b` double as UNALIGNED fault targets in c1)
  - `0x720`-`0x738` trap record slots (cause/baddr/epc/status; c1, c6)
  - `0x740` atomic box (16-byte aligned; c3)
  - `0x750`-`0x760` c1 user-mode slots (PRIV count, user epc/status)
  - `0x768`-`0x780` c1 TL-lowering save area (epc/cause/baddr/status)
  - `0x788` timer delivery count (c3_irq_dev; the c7_timer_* group
    reuses it as its EXTINT delivery counter)
  - `0x790`-`0x7b8` devorder store-queue slots (c7_dev, ORDQ_SLOTS)
  - `0x7c0` TMR_TICK_SLOT — c7_timer_* handler COUNT store / first
    delivered cause (c7_timer_indep)
  - `0x7c8`-`0x7e8` event-fed tests' handler slots (EVT_FLAG /
    EVT_COUNT / EVT_SLOTS; c7_kbd, c7_resize)
  - `0x7f0` TMR_W_SLOT, `0x7f8` TMR_AUX_SLOT — c7_timer_* aux
    (in-handler STATUS snapshot, second delivered cause)

  Device window base addresses (PLATFORM-SPEC 1) are also in defs.s
  as `DEV_*_BASE`; everything at 0x0F00_0000 and up is device space.
- **Register conventions inside tests:** r24 = 0x700, r27 = current
  test ID, r19-r23 vector scratch, r26 handler scratch where a handler
  needs more than k0. Nothing else is reserved.

## Running

    EMU=path/to/emulator tests/run-tests.sh [test names...]

Runs every manifest test twice (`--trace`), requires byte-identical
traces (determinism is the harness's job), `--check-invtp` always on.
Per-test extra emulator flags and trace level come from `MANIFEST`.
If `checks/NAME.sh` exists it runs after a passing run with arguments
`<trace> <sym> <img>` — trace-level assertions (e.g. squashed
instructions performed no memory access, no delivery inside an AMO)
live there; record-level logic sits in a sibling `checks/NAME.py`
importing `trace-q/tracefile.py`.

`REPLAY=1` additionally re-runs each passing test with `--replay` fed
the recorded trace of run a (per devspec/trace.md 5.1 the replayer
consumes its EVENT records and validates META) and requires identical
stdout plus a diverge-clean trace pair — the reference-implementation
"bit-exact replay" check (trace.md 5.2/5.3, T-18), env-gated until
both emulators implement `--replay` (SPEC-ISSUES 26 as resolved by
trace.md).

**Event-fed tests** (`events=GEN.py` on the MANIFEST line — c7_kbd,
c7_kbd_ovf, c7_resize): `tests/events/GEN.py` is run with the
assembled image to emit a *feed* — a minimal trace of META (real
image sha256, so trace.md 5.1 validation passes) plus hand-built
EVENT records (payloads per trace.md 4.1/4.2/4.4) — and every run of
the test consumes it via `--replay`. This is the CLI's only headless
event-injection path, and the only way to exercise queue pops WITH
content, overflow, resize delivery, and EXTINT from a real device
source. Because they need the emulator to implement `--replay`, these
tests are SKIPPED (loudly, counted in the summary) unless `REPLAY=1`.
Live-mode-only behavior (event *generation*: clamping, alternation,
dedup — INPUT-10..12/15/16/19) cannot be exercised by a feed, which
carries finished event words verbatim (SPEC-ISSUES 31). Each feed
generator, its `.s`, and its `checks/*.py` mirror one another —
change the three together; the checker imports the generator's EVENTS
list and requires the recorded EVENT records to match it
byte-for-byte (drop flags included: the emulator must *recompute* the
8.5 overflow drop, trace.md 5.4).

    tests/difftest.sh path/to/emu-A path/to/emu-B [test names...]

Cross-implementation diff: full suite on both at trace level 1,
`trace-q diverge` per pair (run-variant META keys `mode`/`image`
excluded per trace.md 6.5.6), first divergence reported. A test
failing *identically* on both is reported as a shared failure, not a
divergence.

`MANIFEST` line format:
`NAME SRC [level=N] [expect=<hex32>|expect=checkfail]
[events=GEN.py] [flags...]` (`#` comments). Generated sources (`c2_mmu.s` + the `c2_noinvtp_*`
pair, `c3_atomics.s`, `c4_fp.s`, `c5_base.s`, `c7_mem.s`, `defs.s`)
are committed; their generators are deterministic — regenerate and
diff if in doubt (selftest does exactly that). C4's FP expectations
come from `fpvec/fpvec.c` (host C, IEEE hardware, build-time — its
output `fpvec.dat` is committed and re-verified by selftest) plus
exact bigint/logic computations in `gen_c4.py` for the paths where
host C is the wrong tool (F->I saturation, 754-2019 FMIN/FMAX, RMM,
inexact i128 sources); provenance notes in both files' headers.

The harness sets `HARNESS_EXPECT_R0` in the emulator's environment; it
is not part of the CLI contract and real emulators must ignore it —
only the selftest stub reads it (so `expect=` plumbing is testable
without an emulator).

## Harness self-test (no emulator needed)

    tests/selftest.sh

Assembles every manifest source and exercises run-tests.sh + difftest.sh
against the stub in `harness-selftest/` (prints the HALT contract line
and emits a trivial fixed trace — it executes nothing and is not an
emulator). Validates plumbing only: the real semantic expectations are
first exercised when a real emulator arrives.

Step 0 runs the component unit suites, including `asm/test_asmmd.py` —
the devspec/asm.md conformance pass: T1-T5 vectors parsed out of the
spec itself, the closed E001-E049 error catalog with exact codes and
line numbers, and the testable ASM-1..22 requirements. Consequence for
suite sources: `li` on a label is E029 (asm.md 6.1) — label addresses
use `la`/`la.abs`.
