# Work order: TIMER device — the periodic-tick accelerator (device type 5)

Branch: `dev-timer` (worktree of the main repo, full spec access). Read
`emu-common-prompt.md`, `emu-c-prompt.md`, and `emu-py-prompt.md` first;
they govern. Read `devspec/nic.md` and `devspec/display.md` IN FULL —
they are the house-style models the new spec must match — plus
`devspec/boot.md` §3–§5, `devspec/trace.md` §2–§5, ISA-SPEC.md §7.5/§7.6,
and PLATFORM-SPEC.md §1–§3.

This is the first device of the accelerators wave (owner-approved
2026-08-12: timer=5, dma=6, rng=7 — the type codes are fixed by that
convention). The design below was settled in advance and is **binding**.
Do not relitigate the resolved decisions; the "Explicitly rejected"
section at the end exists so you do not reintroduce them. Where frozen
text genuinely conflicts with a decision here, the house protocol
applies: conservative-loud reading, SPEC-ISSUES.md entry, never a silent
fix and never an edit to a frozen file.

## Why this exists

The sreg timer (`timecmp`, sreg 9) is one shared resource, and today it
has two masters: the OS scheduling tick and the debugger's
timecmp-arithmetic single-stepping (`timecmp = iret_cycle + 2` retires
exactly one user instruction). The TIMER device takes over the OS tick —
a periodic MMIO compare counting **cycles**, deterministic by
construction, raising the external interrupt through the standard
per-device pending OR (PLATFORM §3, no interrupt controller). sreg
timecmp is thereby freed to be the kernel's exclusive precision
instrument. Zero sreg changes; the owner's motivating conflict dissolves.

Doctrine check that shapes everything below: the timer's behavior is a
pure function of (guest register writes + their DEVW cycles, the
architectural cycle counter). Both inputs are already deterministic, so
**the timer needs no EVENT records, no META keys, and no GUI changes** —
headless == live == replay by construction. It is the simplest possible
new device and it establishes the doorbell-cycle idiom (`W` = the DEVW
stamp of the arming store) that the DMA engine will reuse as
`doorbell + f(bytes)`.

## The device in one paragraph

Four 64-bit registers in a 64 KB window at reference base 0x0F06_0000
(carved from today's DEVERR hole; confirmed free — emu-c classifies it
SE_SPACE_HOLE, `SE_PLAT_DEV_END = 0x0F060000` in platform.h). Periodic
mode only. Device state is exactly `{u64 period, u128 next_fire}`.
Writing `N > 0` to PERIOD arms with `next_fire = W + N` where W is the
cycle stamped in that store's DEVW record; writing 0 disarms. Pending is
**derived, never stored**: `pending(C) = (period > 0) && (C >= next_fire)`,
evaluated at inter-instruction boundaries in the frozen order (trace.md
§3.3: EVENT apply → device phase → interrupt recognition). ACK (store of
exactly 1) advances `next_fire` by the smallest `k ≥ 1` periods that puts
it strictly past the ACK cycle — phase-locked to the original arming
cycle, so fire targets are `W + m·N` forever and handler latency never
accumulates drift. A late handler sees one level-high interrupt no matter
how many periods elapsed. COUNT is a read-only mirror of the low 64 bits
of the architectural cycle counter; STATUS bit 0 is the derived pending
bit.

## Binding decisions

1. **Periodic-only; no one-shot mode, no CTRL/COMPARE/MODE registers.**
   The OS tick needs periodic; one-shot is exactly what sreg timecmp
   already provides. Software gets one-shot anyway: arm, take the
   interrupt, write `PERIOD = 0` in the handler. One mode = one pending
   rule, fewer DEVERR rows, fewer tests.

2. **COUNT mirrors the architectural cycle counter.** No second clock
   domain — nothing to reset, pause, or drift. Value rule: the low 64
   bits of the counter at the inter-instruction boundary immediately
   preceding the load (this spec, loud-failure). **Normative equivalence
   clause:** COUNT must equal the low 64 bits of what `MFSR` of sreg 8
   returns at the same program point (sreg 8 is already readable S+U,
   ISA §2.3 — COUNT's justification is MMIO-side consistency, not a new
   capability). Any observed divergence between the two read paths is a
   SPEC-ISSUES.md entry, never a silent fix.

3. **Pending is derived, not stored; no OVERRUN bit.** Missed-tick
   counting needs no sticky state: the handler reads COUNT and computes
   elapsed periods from `W + k·N` — fully deterministic, and ACK's
   phase-lock makes the arithmetic exact.

4. **Arming, disarm, rewrite.** Store `N > 0` → arm, `next_fire = W + N`
   (W = the store's DEVW cycle — observable, byte-pinned in traces).
   Store 0 → disarm; pending drops because it is derived. Rewrite while
   armed re-arms fresh from the new W. There is no reprogram race to
   outlaw on a deterministic single-CPU machine — no
   DEVERR-on-reprogram, no arm/disarm state machine.

5. **ACK: strict value, phase-locked advance.** Store of exactly `1` at
   DEVW cycle A: if pending, `next_fire ← next_fire + k·PERIOD` for the
   smallest `k ≥ 1` giving `next_fire > A`. Armed-but-not-yet-pending or
   disarmed: no-op (idempotent). Any value ≠ 1: DEVERR, no state change
   (the NIC IRQ-ack strictness precedent).

6. **Widths and arithmetic domain.** PERIOD is u64. `next_fire` lives in
   the **full cycle-counter domain** — `se_u128` in emu-c (cpu.h:62),
   unbounded int in emu-py — so `W + N` and the ACK advance are exact.
   No mod-2^64 caveats anywhere in the spec. COUNT reads the low 64
   bits. STATUS bits 63:1 read 0.

7. **Recognition and WFI.** Pending first becomes true at the first
   boundary with `cycle ≥ next_fire`; it joins the level-triggered
   EXTINT OR; the handler must ACK or disarm before IRET or it re-traps
   — standard level semantics. **WFI wake is NOT a spec extension:**
   frozen ISA §7.6 already says virtual time advances directly to the
   next cycle at which an interrupt becomes pending, and that the
   machine halts only if no future event could make one pending. An
   armed timer is such a future event: the wake lands at **exactly
   `next_fire`**, and WFI with only the timer armed never
   deadlock-halts. The emulator change is enumerating the wake source,
   nothing more. (`c1_wfihang` arms nothing, so its deadlock-halt
   expectation is unaffected. File a SPEC-ISSUES entry only if you find
   frozen text that enumerates wake sources exhaustively.)

8. **sreg timecmp interaction: none.** Fully independent compare sources
   over the same counter. ISA §7.5's fixed priority (TIMER before
   EXTERNAL) applies for free; the spec states independence explicitly
   and a test pins the simultaneous case.

9. **EVENT records: none, normatively.** trace.md §4 owns all EVENT
   payload encodings, and as written it only makes absent-index /
   unknown-type EVENTs malformed — so once type 5 is a known type, the
   no-EVENT rule needs one explicit **pure addition** to trace.md §4:
   "type 5 (timer): no EVENT payload is defined; an EVENT record whose
   device index resolves to a type-5 record makes the trace malformed
   (§2.4 class 2)." That one line is the only sanctioned edit outside
   timer.md's own files. Both emulators treat a timer-index EVENT as
   fatal malformed. No META config keys — PERIOD is guest-programmed,
   nothing to configure (SPEC-ISSUES issue 12's closed META catalog
   stays closed). GUI: **zero changes** — there is no feed path.

10. **Device-table record.** Type code **5**, table position / device
    index **4** (after nic) — frozen once assigned. Reference default
    base 0x0F06_0000 ("reference default fixed by this document"), size
    0x1_0000, `params[0..3] = 0` (guests ignore-not-fault nonzero;
    later meanings only under boot.md's "0 = v1 behavior" rule). Old
    kernels skip the unknown record positionally (boot.md §4.2/§4.3
    growth path); **no version bump**. boot.md's V1 dump stays normative
    for the 4-device table; timer.md adds a byte-exact 5-device
    reference vector **V1-T**: header 40 + one RAM region 32 + 5·64 =
    **392 encoded bytes** (verified against boot.md §3.3–§3.5).

## Register window (normative content for timer.md §3)

Base = device-table `base`; 64 KB window; 64-bit naturally-aligned
accesses only (frozen PLATFORM §1).

| off  | reg    | access | semantics |
|------|--------|--------|-----------|
| 0x00 | COUNT  | R      | Low 64 bits of the architectural cycle counter at the boundary preceding the load. Equals an MFSR sreg-8 read at the same point (low 64). |
| 0x08 | PERIOD | RW     | Read: last value written (0 at reset). Write N>0: arm, `next_fire = W + N` (W = the store's DEVW cycle). Write 0: disarm. Rewrite re-arms fresh. |
| 0x10 | STATUS | R      | bit0 = pending (evaluated at the boundary preceding the load); bits 63:1 = 0. No read side effect. |
| 0x18 | ACK    | W      | Value must be 1. Pending: phase-locked advance (smallest k≥1 with `next_fire + k·PERIOD > A`). Not pending: no-op. Other values: DEVERR. |

DEVERR catalog (nic.md E1–E7 style; cause 12, `baddr` = effective
virtual address, no device or architectural effect on fault):

| # | condition | authority |
|---|-----------|-----------|
| E1 | 8-byte-aligned access (either direction) to a window offset not in {0x00, 0x08, 0x10, 0x18} | this spec |
| E2 | wrong direction on a listed offset: store to COUNT or STATUS, load from ACK | this spec |
| E3 | access with size ≠ 8 anywhere in the window | PLATFORM-SPEC §1 (frozen) |
| E4 | any atomic (CAS/AMO) anywhere in the window | ISA-SPEC §5.4 (frozen) |
| E5 | ACK write with value ≠ 1 | this spec (loud-failure) |

Check precedence (frozen chain, nic.md §5.2 pattern): predicated-false
never faults (no record, 1 cycle) → translation faults → UNALIGNED →
atomic (E4) → size (E3) → offset/direction (E1/E2) → value (E5). A
misaligned sub-8 access traps UNALIGNED, not DEVERR.

Reset: PERIOD = 0, next_fire = 0, pending false.

## Deliverable 1 — devspec/timer.md (write this FIRST)

House style, section for section (display.md/input.md/nic.md anatomy):

1. Title + preamble (Version 1.0-draft; companion to ISA-SPEC.md and
   PLATFORM-SPEC.md; frozen-spec-wins; non-normative only in indented
   `*Note:*` lines) + Ownership block — **owns:** timer registers and
   semantics, the type-5 record, TMR clauses; **restates (marked with
   source):** DEVERR rules (PLATFORM §1), EXTINT OR (PLATFORM §3),
   boundary order (trace.md §3.3), cycle counter (ISA §5), WFI
   (ISA §7.6); **references, never defines:** device-table layout
   (boot.md §3), the INDEX.md matrix slot.
2. Overview and discovery: type 5, params, reference-defaults table
   ("the device table is authoritative").
3. Register window and access model: the table above, numbered access
   rules, the E1–E5 catalog, the precedence chain.
4. Timing semantics: arming W, the derived-pending rule, ACK
   phase-lock, the single-level rule, recognition boundary, WFI
   wake-at-next_fire + the future-event/deadlock-halt note, timecmp
   independence.
5. Determinism: the pure-function statement; no EVENT payload exists —
   an EVENT naming a type-5 device is malformed; cross-ref the
   trace.md §4 addition; replay isolation trivially holds; live ==
   headless == replay.
6. Reserved/extension rules: offsets 0x20–0xFFF8 are E1; future
   features CAPS-gated opt-in only, never repurposing v1 offsets
   (display §8 pattern).
7. Conformance requirements TMR-01…TMR-21 (list below), grouped under
   bold subheads, replay clauses segregated last and marked
   "(reference implementation)".
8. Test vectors TV-T1…TV-T4 (formats below).
9. Cross-document dependencies, §-exact.

Conformance clauses, verbatim intent (tighten wording, keep numbering):

*Registers and errors:* TMR-01 reset state; TMR-02 COUNT read rule —
two COUNT reads differ by the exact inter-instruction cycle delta, and
COUNT equals an adjacent MFSR sreg-8 read (low 64) modulo the known
delta; TMR-03 arm `next_fire = W + N`; TMR-04 write-0 disarms, pending
drops; TMR-05 PERIOD reads back last-written; TMR-06 rewrite while
armed re-arms fresh from the new W; TMR-07 STATUS encoding,
boundary-cycle evaluation, no read side effect; TMR-08 ACK phase-locked
advance (smallest k≥1, strictly > A); TMR-09 ACK no-op when not
pending; TMR-10 ACK value ≠ 1 DEVERRs with no state change; TMR-11 E1
unlisted offset; TMR-12 E2 direction; TMR-13 E3 size; TMR-14 E4
atomics; TMR-15 UNALIGNED precedence + predicated-false never faults
(no record).
*Pending and interrupts:* TMR-16 EXTINT level OR, frozen recognition
order, re-trap without ACK/disarm before IRET; TMR-17 single-level
pending regardless of elapsed periods; TMR-18 WFI wakes at exactly
`next_fire`; an armed timer counts as a future event (no
deadlock-halt); TMR-19 timecmp independence — simultaneous arming
delivers cause 0 (TIMER) before EXTINT, draining one leaves the other
pending.
*Determinism (reference implementation):* TMR-20 no EVENT payload; an
EVENT naming a type-5 device makes the trace malformed, both emulators
reject; TMR-21 record→replay byte identity.

Test vectors:

- **TV-T1** access-matrix table (display style: `# | address | op |
  size | value | OK=v/DEVERR`) covering every E1–E5 row plus each legal
  access.
- **TV-T2** tick script (step/action/expected columns): arm N=100 at a
  pinned W; fires at W+100k; one late-ACK case with explicit k>1
  proving the phase-lock collapse.
- **TV-T3** device table: the 64-byte type-5 record hex dump
  (boot.md `<PA:8 hex>: <bytes>` format) plus the full 392-byte V1-T
  table dump with machine-consumable `expect` lines (`dev[4].type = 5`,
  base, size, params).
- **TV-T4** WFI wake-cycle script: COUNT before WFI, COUNT after wake,
  delta pinned to exactly next_fire.

Also in this deliverable: the one-line trace.md §4 type-5 addition
(decision 9), and the INDEX.md ownership-matrix row for timer.md.

## Deliverable 2 — both emulators, byte-identical

Difftest must stay 100% identical; DEVW/MEMR records and the device
table must byte-match. All anchors below were verified in-tree.

### emu-c

- `platform.h`: `SE_PLAT_TIMER_BASE 0x0F060000`; `SE_PLAT_DEV_END` →
  `0x0F070000`; new `SE_SPACE_TIMER` enum member (before BUF/HOLE by
  convention); classify branch; update the hole comments (currently
  platform.h:12).
- `dev.h`: `SE_DEVIDX_TIMER = 4`, `SE_DEVIDX_COUNT = 5`; state fields
  `u64 tmr_period; se_u128 tmr_next;` plus cached
  `se_u128 tmr_now; bool tmr_pending;`. **No inject function** — the
  timer is not EVENT-fed.
- `dev.c`: private offset enum; `case SE_SPACE_TIMER:` in both
  `SeDev_reg_read` and `SeDev_reg_write` per the register contract
  (acc_fault = no device effect); reset zeroes everything.
  **Signature-preserving strategy:** a new
  `SeDev_timer_tick(SeDev*, se_u128 cycle)` runs in the boundary device
  phase before interrupt recognition; it caches the boundary cycle in
  `tmr_now` and recomputes `tmr_pending` from the derived rule.
  COUNT/STATUS reads and PERIOD/ACK writes use the cached boundary
  cycle as their C/W/A — the cached value equals the instruction's
  record cycle, i.e. exactly the DEVW stamp the spec pins.
  `SeDev_ext_pending` stays `const SeDev*`, cycle-free: it just adds
  `|| d->tmr_pending` to the OR (dev.c:239).
  `se_plat_write_devtable`: device count 4→5 plus the type-5
  `devtab_record` call.
- `cpu.c`: the boundary phase calls `SeDev_timer_tick`; `wfi_wait`
  (cpu.c:580) and `wfi_wake_exists` (cpu.c:629) gain the wake source
  `tmr_next` when `tmr_period > 0`, with the wake landing exactly at
  next_fire. **No apply_events case** — there is nothing to apply.
- `main.c`: `validate_event` — device index 4 ⇒ fatal malformed trace.
  SeEvRec cap unchanged.
- `test_dev.c`: the classify assert at 0x0F060000 becomes
  SE_SPACE_TIMER; the HOLE assert moves to 0x0F070000 (test_dev.c:82);
  the table-bytes assert becomes V1-T. These are emu-c unit tests, not
  among the 18 conformance tests — editing them is in scope.

### emu-py

- `devices.py`: `class Timer(mem.Device)` — `load/store` per the
  register table (size ≠ 8 checked in-device like the other devices;
  raise `mem.AccessError(self.base + off)` for every DEVERR class),
  `tick(cycle)` caches the boundary cycle and recomputes pending,
  `pending()` returns the cached bit. **No `event()` method** — an
  index-4 EVENT hits the absent-handler path and raises RuntimeError,
  matching C's fatal-malformed.
- `machine.py`: the boundary phase calls `timer.tick(self.cycle)`
  before interrupt recognition (adjacent to the event-apply loop at
  machine.py:147); `wfi_stall` (machine.py:727) gains the next_fire
  wake source; the timecmp check at machine.py:163 is untouched.
- `sahara-emu-py`: `phys.add_device(timer)`; **NOT** appended to
  `event_devices` (line 102 stays `[display, kbd, mouse, nic]` —
  indices 0–3 unchanged, timer=4 is never event-fed);
  `dev_entries += (5, 0x0F060000, 0x10000, 0, 0, 0, 0)` — the table
  bytes must match emu-c's output exactly.
- `trc.py`: untouched. GUI: untouched.

### Byte-match watchpoints

COUNT MEMR values, the DEVW-stamped W/A arming cycles, and WFI wake
cycles must use the identical boundary-cycle definition on both sides —
that is exactly why W and A are defined as DEVW stamps and why both
implementations derive them from the cached boundary cycle. Any
divergence here is a design-contract bug, not a tolerance to paper
over.

## Deliverable 3 — new conformance tests (pure additions)

**Pre-landing audit, do it before writing any test:** confirm none of
the 18 MANIFEST tests assert `device_count == 4` or the V1 table bytes
— `c7_dev` and `c3_irq_dev` are the suspects to check first. If any
does, that is a **blocking SPEC-ISSUES entry and a stop**, not an edit
to an existing test.

This branch has an explicit one-time grant to ADD test files and
MANIFEST lines. It may never modify the existing 18 tests, their
checkers, their feeds, `run-tests.sh`, `difftest.sh`, or `trace-q`.

Per the suite recipe: sources assemble as `defs.s` + `<name>.s`;
pass/fail is the 0x700/0x600D idiom (r24 = FAIL_ADDR, r27 = test ID,
`HALT r0=...600d`); checkers are the 5-line sh shim + sibling `.py`
importing `trace-q/tracefile.py` and reusing `checks/evcheck.py`
(fail/check_classification/check_seq/check_trap_census/devstate).
Expectations must be hand-derived from timer.md, never from an emulator
run. Claim scratch slots from the free 0x7c0/0x7f0–0x7f8 range and
update tests/README.md's map. `DEV_TIMER_BASE = 0x0F060000` goes into
defs.s **via its generator** (`tests/gen_defs.py` regenerates the
committed defs.s; selftest diffs it). Remember `li` on a label is E029
— use `la`/`la.abs`.

Four tests, MANIFEST lines appended at the end:

1. **c7_timer_tick** (`level=2`, checker `.py`): arm N at a
   hand-derived cycle; the EXTINT handler stores COUNT to a claimed
   scratch slot, ACKs; count K ticks including one deliberately-slow
   handler iteration proving fires stay at W+kN; disarm; PASS 0x600D.
   Checker: exact EXTINT trap census = K; pinned COUNT MEMR sequence;
   DEVW/MEMR classification.
2. **c7_timer_deverr**: full E1–E5 sweep + the UNALIGNED-precedence
   case + a predicated-false squashed access; STATUS/PERIOD re-read
   after each fault proves no state change; checker asserts the exact
   trap census {DEVERR: n, UNALIGNED: m} and no-record for the squashed
   access.
3. **c7_timer_wfi** (`level=2`): COUNT before WFI, COUNT after wake —
   delta pinned to next_fire exactly; two consecutive WFI periods;
   ACK-before-IRET level behavior.
4. **c7_timer_indep** (`level=2`): sreg timecmp and the device armed
   for the same cycle — cause 0 delivered before cause 1; draining one
   leaves the other pending.

No `events=` generators (nothing to feed), so all four run under
difftest without the REPLAY=1 gate gap, and the free REPLAY=1 leg
replays each run-a's own trace. selftest.sh derives NTESTS from the
MANIFEST, so its counts should track automatically — if any of its
arithmetic turns out hard-coded, update selftest's arithmetic, never a
test.

## Deliverable 4 — devspec/CONFORMANCE-DELTA.md entry

CONFORMANCE.md is frozen; the delta file maps timer.md onto it:

- One **C7 row** (memory and devices): timer.md §7, TMR-01…TMR-19,
  one-line scope.
- One **Reference-implementation-only** row: TMR-20/TMR-21.
- Extend **four** of the five parameterized "Deliberate instantiations"
  lists with the timer's instances: atomics-to-device, non-64-bit size,
  predicated-false, per-device EXTINT level-triggering.
  Event-visibility-at-boundary is N/A (no EVENTs) — say so.

## Definition of done

All from the worktree root; every gate green, in this order:

- `python3 tests/gen_defs.py` regenerates defs.s with DEV_TIMER_BASE;
  `tests/selftest.sh` green (it re-derives and diffs generated files
  and re-checks suite counts).
- `emu-c/build.sh` end to end — bazel build+test (including the updated
  test_dev V1-T assertions) and the REPLAY=1 conformance suite with the
  four new tests included.
- `./run_tests.sh` (repo root → emu-py/run-tests.sh, REPLAY=1 leg
  included) green: 22 passed, 0 failed.
- Difftest 100% identical, both forms:

      tests/difftest.sh emu-py/sahara-emu-py emu-c/bazel-bin/sahara-emu
      REPLAY=1 tests/difftest.sh emu-py/sahara-emu-py emu-c/bazel-bin/sahara-emu

  22 identical, 0 diverged — the new register-model tests included.
  (run-tests.sh's own double-run cmp already gives per-emulator
  determinism; difftest gives the cross-emulator byte identity.)
- **Existing-18-untouched check** — verified, not assumed:

      git diff --name-status "$(git merge-base main HEAD)" -- tests/

  The only `M` entries permitted: `tests/MANIFEST` (appended lines
  only), `tests/defs.s` + `tests/gen_defs.py` (the new constant),
  `tests/README.md` (scratch-map additions), and `tests/selftest.sh`
  only if its arithmetic proved hard-coded. Everything else must be
  `A`. Additionally, confirm zero diff on the 18 existing `.s` sources
  and everything under `tests/checks/` and `tests/events/` that existed
  at the merge base. Any other `M` or any `D` is stop-the-line.
- `git diff` on frozen files (ISA-SPEC.md, PLATFORM-SPEC.md,
  TOOLING-SPEC.md, CONFORMANCE.md, CONSTRAINTS.md, boot.md's V1 vector)
  is empty. trace.md shows exactly the one §4 type-5 line.
- SPEC-ISSUES.md entries committed for anything you had to invent or
  found contradictory (the COUNT/MFSR equivalence and WFI wake-source
  notes only become entries if divergence or exhaustive-enumeration
  text is actually observed).

## Scope boundaries

- **No Oasis / `os/` changes.** The kernel adoption story (scan for
  type 5, arm PERIOD = tick quantum, STATUS/ACK in the EXTINT handler,
  timecmp freed for the debugger) is noted in timer.md's overview as a
  *Note:* — implementation is a later work order.
- **No sahara-gui changes.** The timer has no live path, no feed path,
  no host anything. If you find yourself editing gui/, the design has
  been violated.
- **No changes to other devices' specs** (display.md, input.md, nic.md,
  boot.md beyond zero — the V1-T vector lives in timer.md). The single
  trace.md §4 line from decision 9 is the one sanctioned outside edit.
- **No edits to run-tests.sh, difftest.sh, trace-q, or the 18 existing
  tests/checkers/feeds** — toolchain-owned. If a suite bug blocks you,
  record it in SPEC-ISSUES.md and stop rather than patching around it.
- No new trace record types, levels, or META keys. No CLI changes to
  either emulator beyond the internal validate_event tightening.
- DMA and RNG are separate work orders. Do not pre-build descriptor
  plumbing or entropy queues "while you're in there."

## Risks

- **The boundary-cycle cache is the whole byte-match contract.** If
  emu-c's `tmr_now` and emu-py's `tick(cycle)` capture different
  notions of "the boundary preceding this access", COUNT MEMRs and
  arming cycles drift and difftest catches it on c7_timer_tick
  immediately. Get the tick call's position in the boundary sequence
  (after EVENT apply, before interrupt recognition) identical on both
  sides before writing any test.
- **WFI wake-at-next_fire vs timer-trap resume-at-T+1.** The frozen
  semantics differ: sreg-timer wakes resume at T+1, event wakes land AT
  the event cycle. The device timer follows the §7.6 "advances directly
  to the next cycle at which one becomes pending" rule — wake lands at
  exactly next_fire. c7_timer_wfi pins this; if the two emulators
  disagree on the landing cycle, re-read §7.6 before touching either.
- **`wfi_wake_exists` is the deadlock-halt analysis.** Forgetting the
  armed-timer term there makes WFI-with-only-timer-armed falsely halt
  as deadlock; c7_timer_wfi will hang or halt wrong. The symmetric
  emu-py omission in `wfi_stall` produces a difftest SHARED-FAIL only
  if both are wrong the same way — hand-derive the expected wake cycle,
  never crib it from a run.
- **Device-table byte drift.** emu-c's `se_plat_write_devtable` and
  emu-py's `dev_entries`/`image.write_device_table` must produce
  identical 392-byte tables; the guest reads them and test_dev asserts
  them. Diff the two outputs directly once before running the suite.
- **The hole moved.** Any stale assert or comment still claiming
  [0x0F060000, 0x10000000) is DEVERR hole (test_dev.c:82, platform.h
  comments) must move with SE_PLAT_DEV_END or emu-c's own unit tests go
  red in confusing ways.
- **Checker expectations leaking from emulator runs.** The trap
  censuses, COUNT sequences, and wake deltas in the four checkers must
  be derived on paper from timer.md's rules (1 cycle per retired
  instruction, 1 per trap delivery, the WFI jump rule). An expectation
  copied from a trace proves nothing and will hide a shared bug.

## Explicitly rejected — do not reintroduce

One-shot mode / COMPARE / CTRL / MODE bits (timecmp already is the
one-shot; PERIOD=0-in-handler covers the rest). OVERRUN sticky bit
(derivable from COUNT arithmetic; adds W1C state). Latched-pending as
*spec* semantics (kept only as an implementation cache recomputed every
boundary). DEVERR-on-reprogram-while-armed (no race exists on a
deterministic single CPU; rewrite-re-arm is simpler and well-defined).
ACK as a W1C bitmask (nothing to clear; strict value-1 is louder).
Mod-2^64 arithmetic caveats (next_fire lives in the full counter
domain). EVENT records or META keys of any kind for this device.
