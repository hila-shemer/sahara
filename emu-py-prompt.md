# Sahara emulator — Python implementation (emu-py/)

Read `emu-common-prompt.md` first; it governs. This file adds only what is
specific to the Python implementation.

## Role

This is **the independent cross-check** of the C reference. Its value is
divergence detection: same suite, same traces, different implementation
substrate. Write it spec-shaped — the code should read like the spec text
executed. Where the C implementation must fight its language (128-bit
arithmetic, sign extension), Python's unbounded ints make the spec's
arithmetic literal; lean into that rather than imitating C idioms.

Headless only. No GUI, no live NIC — replay mode covers every device
behavior the suite exercises. (The C implementation owns the interactive
front end.)

## Language specifics

- Python ≥ 3.10, stdlib only (pytest permitted for your own unit tests).
  Import `encoding.py` directly; hardcode nothing.
- Entry point `emu-py/sahara-emu-py` implementing the frozen CLI contract
  from the common prompt.
- 128-bit and MULH-128 are natural bigint operations — mask to width
  explicitly and canonically at each writeback per ISA-SPEC's canonical-
  form rules; C5 hunts exactly the high-garbage mistakes Python's
  unbounded ints invite.
- **FP is the hard part in Python** — native floats give you double
  precision, round-to-nearest-even only, no flags. Recommended: implement
  the specced binary32/binary64 operation set as pure-integer softfloat
  (deterministic, host-FPU-independent, and an honest cross-check of the
  C side's host-FP assumptions). The op set is small; performance is
  explicitly a non-goal. If you choose another route (e.g. ctypes into
  libm + fesetround), record the decision and its determinism argument in
  SPEC-ISSUES.md. C4's committed vectors are the arbiter either way.
- Performance is a non-goal, but the full suite must complete in CI;
  `--maxcycles` discipline in tests covers this — do not optimize, do not
  add JIT/caching cleverness that risks determinism.
