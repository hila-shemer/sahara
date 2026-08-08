# Work order: bring emu-py up to the current toolchain contract

Branch: `emu-py`. Read `emu-common-prompt.md` and `emu-py-prompt.md` first;
they govern. This is a catch-up pass, not new scope: merge `toolchain` into
`emu-py` and make the merged tree pass the merged suite.

## Why this exists

Quilt's pairwise probe (emu-py x toolchain tip) fails while each branch is
green alone. Two contracts moved after emu-py's last toolchain merge:

1. **META catalog** — devspec/trace.md 2.3.7 now mandates seven keys, in
   catalog order: `trace, encoding, level, mode, image, image_sha256,
   platform`. `emu-py/sahara-emu-py` still emits the legacy five
   (`image, sha256, encoding, level, modes`), so the devspec-conformant
   trace-q rejects every trace at the replay leg
   ("META missing mandatory key trace").
2. **Suite conventions** — the assembler was rewritten to the asm.md
   contract (kinds, relaxation, closed E-catalog) and the test sources were
   regenerated. Under the merged suite emu-py fails 16 of 18 tests with
   `HALT r0=0` instead of the PASS magic — diagnose this properly (trace
   the first divergence with trace-q; do not guess) before touching code.
3. **EVENT-fed tests** — the events= manifest class (c7_kbd, c7_kbd_ovf,
   c7_resize) feeds EVENT records through --replay per trace.md 4/5.1.
   emu-py opts into REPLAY=1 in run-tests.sh, so these run; its --replay
   must honor the EVENT payload contract (trace.md 4.3) for the input and
   resize devices.

## Definition of done

- `git merge toolchain` (current tip) committed on emu-py, conflicts
  resolved without weakening either side.
- `emu-py/run-tests.sh` green end to end, REPLAY=1 leg included.
- No changes under `tests/` or `trace-q/` beyond what the merge brings in —
  those are toolchain-owned; if a suite bug blocks you, record it in
  SPEC-ISSUES.md and stop rather than patching around it.
