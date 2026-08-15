# Work order: untethered mode — sahara-gui without the recorder

Branch: `untethered` (worktree of the main repo). Read
emu-c-gui-frontend-prompt.md (the live-mode architecture this amends)
and emu-c/gui/frontend-notes.md first.

## Why this exists

PLATFORM-SPEC §8 and the GUI work order's decision 9 made session
recording mandatory: every live session is a trace, every trace
replays byte-exact. That stays the default and the only mode any gate
runs. Owner ruling 2026-08-15 adds an explicit opt-out: sessions that
retire instructions in bulk — DOOM-class workloads now, the GPU later
— may run **untethered**: no trace, no replay guarantee, correctness
judged by results rather than byte-accuracy. The ruling's test-policy
half: heavy suites may check outcomes (exit contract, memory,
framebuffer state) and skip byte-identity — that convention gets
documented here and used by future streams, not retrofitted onto any
existing gate.

## Binding decisions

1. **`--untethered` is a sahara-gui flag only.** The headless
   `sahara-emu` CLI is already untethered when `--trace` is absent and
   is not touched in any way.
2. **Semantics: the recorder is not attached at all.** No session
   trace file, no META, no record emission on the hot path (this is
   the point — measure and report the free-run instr/s delta with the
   recorder detached vs level-0 recording in your final report; no
   other performance work is in scope). No replay command printed at
   exit. `--trace`/`--trace-level` together with `--untethered` is a
   loud startup error, not a silent override.
3. **Loud, twice.** A one-line banner at startup AND at exit:
   `untethered session: not recorded, not replayable`. Nobody
   discovers after the fact that their session left no artifact.
4. **Composes with everything else** (`--nic host|off|fake`, `--hz`,
   `--script`). Under `--script` it exists so the flag's own tests can
   run headless in CI; the determinism gates themselves always run
   recorded mode.
5. **Doctrine wall.** Recorded mode remains the default and the only
   gated mode. Untethered is never a default anywhere, and no
   existing gate or test may be converted to results-only in this
   work order — the convention is documented for FUTURE heavy suites.
6. **SPEC-ISSUES entry** (root): the owner-sanctioned opt-out of
   PLATFORM-SPEC §8's always-record rule, stating: opt-in flag,
   banner contract, recorded mode unchanged as default and test
   substrate, and the results-only test convention for
   high-instruction-volume suites.

## Deliverables

1. The flag, the not-attached recorder path, the banners, the
   `--trace` conflict error (emu-c/gui/sdl_main.c and friends).
2. Tests in `emu-c/run-gui-tests.sh` (additions only): a scripted
   `--untethered` session asserting (a) no `.trc` is produced, (b)
   both banners appear, (c) the guest's result is correct (HALT
   magic); a `--untethered --trace` conflict test; and a recorded-mode
   regression leg proving a recorded session's trace is byte-identical
   to the same session on the merge base.
3. `emu-c/gui/frontend-notes.md`: the untethered section — what it is,
   what it forfeits, the results-only test convention, and the
   recommended pairing with `--hz 0` for throughput work.
4. The SPEC-ISSUES entry.

## Definition of done

- `(cd emu-c && ./build.sh)` green end to end (REPLAY=1 suite intact).
- `./run_tests.sh` green.
- `emu-c/run-gui-tests.sh` green including the new legs.
- Headless byte-identity vs merge base (the frontend work order's
  recipe verbatim): zero drift — recorded mode and headless behavior
  are provably unchanged.
- Measured instr/s: untethered free-run vs recorded free-run, in the
  final report.

## Scope boundaries

- No core (`cpu.c`/`dev.c`/`trace.c`) semantic changes; the recorder
  is simply never attached — if that requires more than wiring in
  sdl_main, stop and report.
- No headless CLI changes, no default changes, no `tests/` or
  `trace-q/` edits, no emu-py changes.
- No performance work beyond not-recording.
