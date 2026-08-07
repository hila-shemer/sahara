# Sahara conformance suite

Self-checking assembly per CONFORMANCE.md. One file per group; each test
block sets a test ID, computes a result, and compares it against an
expected value computed independently of any emulator (by hand or by the
committed generator scripts — never by running an emulator under test).

## Conventions

- **Success:** HALT with `r0 = 0x600D`. The harness expects stdout
  `HALT r0=0000000000000000000000000000600d` exactly (lowercase hex —
  SPEC-ISSUES.md entry 3).
- **Failure:** store the failing test ID as u64 to **PA 0x700**, then
  HALT with `r0 = <test ID>`. Diagnose with
  `trace-q last-write 0x700 out.trc` and
  `trace-q at <pc>` / `range` around the failing block.
- **Scratch addresses** (all in RAM below the device table, never part
  of any image segment):
  - `0x700` failing test ID (u64)
  - `0x710` squash box — no access may ever touch it (checked from the
    trace by `checks/*.sh`)
  - `0x718` sentinel box — general readback scratch
  - `0x720`-`0x738` trap record slots (cause/baddr/epc; c6, later c1)
  - `0x740` atomic box (16-byte aligned; c3)
  - `0x750`-`0x7f8` free for later groups
- **Register conventions inside tests:** r24 = 0x700, r27 = current
  test ID, r19-r23 vector scratch. Nothing else is reserved.

## Running

    EMU=path/to/emulator tests/run-tests.sh [test names...]

Runs every manifest test twice (`--trace`), requires byte-identical
traces (determinism is the harness's job), `--check-invtp` always on.
Per-test extra emulator flags and trace level come from `MANIFEST`.
If `checks/NAME.sh` exists it runs after a passing run with arguments
`<trace> <sym> <img>` — trace-level assertions (e.g. squashed
instructions performed no memory access) live there.

    tests/difftest.sh path/to/emu-A path/to/emu-B [test names...]

Cross-implementation diff: full suite on both at trace level 1,
`trace-q diverge --ignore-meta` per pair, first divergence reported.
A test failing *identically* on both is reported as a shared failure,
not a divergence.

`MANIFEST` line format: `NAME SRC [level=N] [extra emulator flags...]`
(`#` comments). Generated sources (`c5_base.s`) are committed; their
generators are deterministic — regenerate and diff if in doubt.

## Harness self-test (no emulator needed)

    tests/selftest.sh

Assembles every manifest source and exercises run-tests.sh + difftest.sh
against the stub in `harness-selftest/` (prints the HALT contract line
and emits a trivial fixed trace — it executes nothing and is not an
emulator). Validates plumbing only: the real semantic expectations are
first exercised when a real emulator arrives.
