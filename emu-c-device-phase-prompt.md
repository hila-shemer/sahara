# Work order: emu-c EVENT device phase for --replay

Branch: `emu-c`. Read `emu-common-prompt.md` and `emu-c-prompt.md` first;
they govern. This continues the branch's own build order: the headless
device tranche exists (registers, devorder queue), what's missing is the
replay-side device phase.

## Why this exists

Quilt's pairwise probe (emu-c x toolchain tip) fails exactly three tests —
c7_kbd, c7_kbd_ovf, c7_resize — with:

    sahara-emu: --replay contains EVENT records; device phase not implemented yet

That message is emu-c's own honest stub. The toolchain tip added the
events= manifest class: tests/events/GEN.py emits a feed trace (META +
EVENT records, trace.md 4/5.1) that every run consumes via --replay, gated
behind REPLAY=1 — which emu-c's build.sh already sets (it is the reference
implementation; bit-exact replay is a CONFORMANCE.md obligation).

## Scope

- Implement the device phase of --replay: at each EVENT record's cycle,
  inject the payload into the corresponding device (keyboard event words,
  resize u64x4 per trace.md 4.4; device = 0-based table index) with the
  cycle-stamping and per-cycle ordering rules of trace.md 5.
- WFI must wake at the event cycle (nic.md NIC-C-36 states the general
  rule; input events bind the same way).
- Determinism contract unchanged: two runs of an event-fed test must
  produce byte-identical traces; replay of the produced trace must be
  byte-identical at level.

## Note on the REPLAY=1 overload (flag for the human, do not decide here)

Diagnosis observed that REPLAY=1 originally meant "validate --replay of
recorded traces" and the events= class overloaded it to also un-skip
EVENT-fed tests. If during this work the overload still feels wrong (e.g.
a future emulator supporting replay but not devices), raise it in
SPEC-ISSUES.md as a proposal for a separate EVENTS=1 gate — the fix here
makes the question moot for emu-c, but the suite-design point stands.

## Definition of done

- `git merge toolchain` (current tip) committed on emu-c.
- `emu-c/build.sh` green end to end — bazel test, image tests, and the
  merged conformance suite with REPLAY=1, event-fed tests included.
