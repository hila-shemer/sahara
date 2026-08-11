# Work order: RNG device — spec first, both emulators, new conformance tests

Branch: `dev-rng`, in a worktree with full repo access. Read
`emu-common-prompt.md`, `emu-c-prompt.md`, and `emu-py-prompt.md` first; they
govern the CLI contract and per-emulator conventions. House-style models:
`devspec/nic.md` (E-lettered DEVERR catalog, determinism section §7.1),
`devspec/input.md` (queue device), `devspec/display.md` (access-matrix
vectors), `devspec/boot.md` (device table), `devspec/trace.md` (EVENT payload
ownership). The design below is FINAL — owner-approved for the accelerator
wave. Your job is execution, not redesign. Where this document says
"(settled)", implement it as written; where it says "(flag)", note it for the
wave judge in your hand-off, do not solve it.

## Why this exists

Peripherals in Sahara are optional accelerators, not complex hardware. The RNG
device is the wave's device that makes the determinism boundary explicit:
every entropy bit a guest observes through the queue entered the machine as an
EVENT record — feed-supplied under `--replay`, front-end-recorded in live mode
(the NIC-RX pattern exactly). A separate guest-selected PRNG mode exists as
pure architectural state: it can never silently substitute for recorded
entropy, because switching modes is a DEVW-traced MMIO store in the guest's
own instruction stream and the emulator has no path that switches modes on its
own. Empty is a first-class, loud, testable state.

Deliverables, IN THIS ORDER — each builds on the previous, and the spec is
written before any code so the code answers to it:

1. `devspec/rng.md` + companion edit `devspec/trace.md` §4.6 + `devspec/INDEX.md` row.
2. Both emulator implementations (emu-c and emu-py), byte-identical under difftest.
3. New conformance tests — pure additions to `tests/`.
4. `devspec/CONFORMANCE-DELTA.md` entry.

## Binding decisions (settled)

**R1 — Queue shape.** One FIFO of 64-bit entropy words, depth exactly 256
(2 KB), matching input.md §4's depth/drain/visibility model so the suite's
five shared parameterized queue rules instantiate cleanly. `DATA` (R) pops the
oldest word; `STATUS` (R) returns depth 0–256, side-effect-free.
Predicated-false accesses pop nothing, fault nothing, retire in 1 cycle
(frozen rule). Words become guest-visible only at the EVENT boundary cycle
(trace.md §3.3; frozen WFI wake rules — an event wake lands at exactly the
event cycle).

**R2 — Empty pop is DEVERR.** In QUEUE mode, a `DATA` load with depth 0 traps
DEVERR (cause 12, baddr = ea, zero state change). No sentinel (every u64 is a
legal entropy word, so no sentinel is unambiguous), no silent 0-return (a
silent-garbage security bug). Consumer contract: read STATUS (or take the
IRQ), then pop exactly `depth` words; the trap is the loud backstop. This
follows the NIC empty-pop DEVERR precedent (emu-c dev.c, NIC E6) — a
deliberate, documented divergence from the input sentinel. STATUS-then-pop
cannot race: events land only at boundaries and only add words, so observed
depth is a floor.

**R3 — PRNG mode: guest-selected, architecturally traced, never a fallback.**
`CTRL` bit 0 `MODE` (0 = QUEUE, reset default; 1 = PRNG) plus write-only
`SEED`. In PRNG mode `DATA` returns the next output of SplitMix64, normative
in the spec:

    state += 0x9E3779B97F4A7C15
    z = state
    z ^= z >> 30;  z *= 0xBF58476D1CE4E5B9
    z ^= z >> 27;  z *= 0x94D049BB133111EB
    z ^= z >> 31;  return z

Test vector: seed 0 → first output `0xE220A8397B1DCDAF`. Writing SEED sets
PRNG state = value and restarts the stream. PRNG state resets to 0 at machine
reset. The queue is untouched by PRNG pops; STATUS always reports queue depth;
arriving EVENTs still enqueue regardless of mode. Empty-pop DEVERR applies
only in QUEUE mode. Replay safety is by construction: MODE/SEED are guest
stores in the instruction stream, DEVW-traced, so replay reproduces mode
selection; there is no emulator auto-fallback, no config key, no device-table
param (SPEC-ISSUES #12 is avoided, nothing new to log there).

**R4 — EVENT payload + overflow rule.** trace.md gains §4.6 — RNG entropy:
payload = N little-endian u64 words, 8·N bytes, 1 ≤ N ≤ 128 (≤ 1024 B, under
emu-c's 1514-byte inline cap). On apply at the boundary the model enqueues
`min(N, 256 − depth)` words from the front and records EXACTLY the accepted
words (truncate-to-fit; zero accepted → no EVENT record at all). This is the
NIC-discard asymmetry, deliberately not the input drop-flag one: entropy words
are fungible, and recording only accepted words makes the record→replay fixed
point trivial (replayed payloads always fit exactly). No trailing count byte —
rejected. Under replay, any needed truncation means feed ≠ model: emu-c
`RWC_ASSERT` (the NIC `c->ev == c->feed` pattern), emu-py `ValueError`
(malformed trace). Malformed encodings — len 0, len not a multiple of 8,
len > 1024 — are feed-validation failures (emu-c `validate_event`, emu-py
`event()` ValueError).

**R5 — Interrupt.** `CTRL` bit 1 `IE` (R/W, reset 0). Pending contribution to
the standard level-triggered EXTINT OR: `IE == 1 AND depth > 0`, in any mode.
Reset-off keeps the device invisible to old kernels (positional skip, no
spurious EXTINT); enable-qualified pending is NIC-precedented and deliberately
diverges from input's always-pending. Even with IE = 0, a live feed record is
itself a WFI wake source landing at exactly the event cycle (frozen).

**R6 — Live path (sahara-gui), non-normative.** Watermark top-up: one 32×u64
batch at session start, then each pump iteration, if guest-visible depth < 64,
read 32×u64 from host `getrandom(2)` and
`SeCpu_feed(cpu, SE_DEVIDX_RNG, words, 256, g->pump_earliest)`, stamped like
input batches (max of earliest/current/last-queued; queue stays sorted).
Feeding clears `wfi_idle`. Recording is the apply path — live sessions
self-record; replay is byte-identical.

**R7 — Device table.** Type code **7** (wave-fixed: timer = 5, dma = 6,
rng = 7). Window base **0x0F08_0000**, size 64 KB. `params[0..3] = 0` — all
defaults fixed by the spec ("0 = v1 behavior"; guests ignore-not-fault
nonzero; kbd/mouse all-zero precedent; depth 256 is spec-fixed, not a param).
Old kernels skip the unknown type-7 record positionally (boot.md §4.3); no
version bump.

**R8 — EVENT device index = device-table position.** See W1 below for the
branch-local value.

## Branch-local decisions (this work order resolves them — implement as written)

**W1 — Table position on this branch is 4, wave target is 6.** The wave order
is display 0, kbd 1, mouse 2, nic 3, timer 4, dma 5, rng 6 — but timer and dma
do not exist on `dev-rng`, and table records are positional with no gaps. Do
NOT emit placeholder records (a table that advertises devices that aren't
there lies to guests). On this branch the RNG record is the FIFTH record,
index **4**, `device_count = 5`. Keep the index in exactly one named constant
per component — `SE_DEVIDX_RNG` (emu-c dev.h), the `event_devices` list
position (emu-py front end), one `RNG_DEV_INDEX` constant in the evlib
builder — each carrying the comment `WAVE-RENUMBER: becomes 6 when timer/dma
records land ahead of this one`. Feeds are regenerated from generators at test
time, so the renumber is a constants-only change. (flag) List this in your
hand-off for the wave judge.

**W2 — Window address is pinned at 0x0F08_0000 even though 0x0F06/0x0F07 stay
holes here.** Classify keeps two DEVERR holes: [0x0F06_0000, 0x0F08_0000) and
[0x0F09_0000, pixel buffer). Addresses are guest-visible and expensive to
move; table positions are one constant. If the timer/dma branches claim
differently, the judge re-slots — (flag) note it, don't coordinate yourself.

**W3 — boot.md is untouched.** The byte-exact 5-record reference table dump
for this branch lives in `devspec/rng.md`'s test vectors, and emu-c's
`test_dev.c` asserts against it (the existing V1 assert changes to the new
vector — that is an emu-c unit test, not one of the 18). boot.md's V1 stays
frozen; the wave judge adds one combined boot vector carrying all three new
records later. (flag)

## Register window (base 0x0F08_0000; 64-bit naturally-aligned accesses only)

| off  | reg    | access | semantics |
|------|--------|--------|-----------|
| 0x00 | DATA   | R  | QUEUE mode: pop and return oldest word; DEVERR if depth = 0. PRNG mode: return next SplitMix64 output and advance state; queue untouched |
| 0x08 | STATUS | R  | queue depth 0–256; no side effects; unaffected by mode or PRNG pops |
| 0x10 | CTRL   | RW | bit 0 MODE (0 = QUEUE, 1 = PRNG), bit 1 IE; bits 63:2 reserved — read 0, write with any set → DEVERR, no state change; reset 0 |
| 0x18 | SEED   | W  | store: PRNG state = value, stream restarts; load → DEVERR |

DEVERR catalog (nic-style; all cause 12, baddr = ea, zero device effect):
**E1** unlisted offset; **E2** wrong direction (store to DATA/STATUS, load
from SEED); **E3** size ≠ 8; **E4** any atomic in the window; **E5** CTRL
reserved bits set on write; **E6** empty pop in QUEUE mode. Check precedence
copies the nic.md chain: predication → translation → UNALIGNED → atomic →
size → offset/direction → value/state. A faulting access has NO device side
effect — no pop, no PRNG advance. Predicated-false accesses never fault, never
pop, never advance PRNG state, retire in 1 cycle.

Reset state: queue empty, CTRL = 0 (QUEUE mode, IE off), PRNG state = 0.

## Deliverable 1 — devspec/rng.md (write this FIRST)

House style per the models named above. Section skeleton:

1. Title/preamble + Ownership block (owns: register map, queue +
   truncate-to-fit rule, PRNG algorithm + mode semantics, type-7 record,
   defaults, live-policy statement; frozen-elsewhere-restated: DEVERR cause
   12, 64-bit access rule PLATFORM §1, EXTINT OR §3, event-boundary rule
   trace.md §3.3; referenced-never-defined: EVENT payload bytes → trace.md
   §4.6). Slot the row into `devspec/INDEX.md`'s ownership matrix.
2. Overview & discovery (type 7, table record, params table, defaults
   "reference default fixed by this document").
3. Register window & access rules (the table above, numbered rules).
4. Entropy queue: §4.1 FIFO/depth/boundary visibility; §4.2 truncate-to-fit
   acceptance, recorded = accepted prefix; §4.3 ordering.
5. PRNG mode: normative SplitMix64 + constants + seed-0 vector; MODE/SEED
   rules; the replay-safety argument (guest-architectural, DEVW-traced, no
   emulator fallback path, resets to QUEUE).
6. Interrupts: IE-qualified level pending into the EXTINT OR; WFI interaction.
7. Determinism & trace — clone nic.md §7.1's structure: boundary effect,
   monotonicity, causality, live-mode freedom; headless reference cycle
   policy C = trigger+1 stated but explicitly NOT test-assumable; replay
   isolation (host never consulted); the no-silent-substitution statement
   covering both queue and PRNG.
8. Errors E1–E6 + precedence chain.
9. Reserved/extension rules (reserved CTRL bits, params, offsets — display §8
   pattern: opt-in only, never repurpose v1 offsets).
10. Conformance clauses RNG-01… (~20), one testable behavior each, citing
    vectors; replay clauses segregated at the end, marked "(reference
    implementation)".
11. Test vectors: access-matrix table (display style); feed→pop-sequence
    scripts; SplitMix64 output table; overflow vector with the exact expected
    recorded bytes; the 5-record device-table byte dump (W3).
12. Cross-document dependencies, §-exact.

Companion edits: `devspec/trace.md` — new §4.6 (type-7 payload = N×u64,
1 ≤ N ≤ 128, recorded = accepted words, zero-accepted records nothing) and
extend the §4 preamble type list (5 timer, 6 dma, 7 rng — listing the wave's
codes is fine, only 7 gets a payload section now). trace.md §4 remains the
sole owner of payload bytes; rng.md references, never defines.

## Deliverable 2 — both emulators

Difftest must stay byte-identical: DEVW (type 6) records for successful
register writes, MEMR (level ≥ 2) for register reads, EVENT payloads
recomputed identically. Faulting accesses record nothing.

**emu-c** (all under `emu-c/`):
- `platform.h` — `SE_PLAT_RNG_BASE 0x0F080000`, `SE_SPACE_RNG` enum member,
  classify branch; two holes per W2 (adjust the `SE_PLAT_DEV_END` / hole
  comments to match).
- `dev.h` — `SE_DEVIDX_RNG = 4` (W1 comment), `SE_DEVIDX_COUNT = 5`; state
  `{u64 rng_q[256]; u32 rng_head, rng_count; u64 rng_ctrl, rng_prng_state;}`;
  `RWC_WARN_UNUSED` `SeDev_inject_rng(...)` returning the accepted count.
- `dev.c` — private offsets enum; `case SE_SPACE_RNG:` in BOTH
  `SeDev_reg_read` and `SeDev_reg_write` (`acc_fault` for E1–E6 including the
  E6 empty pop, `acc_val` otherwise; DATA pop / SplitMix64 advance as read
  side effects); reset zeros; `ext_pending` term
  `(d->rng_ctrl & 2u) && d->rng_count` — pure state, NO cycle plumbing and NO
  WFI changes (unlike timer/DMA, this device needs none — do not touch
  `wfi_wait`/`wfi_wake_exists`); `se_plat_write_devtable` count 4u → 5u + the
  type-7 record `{7, 0x0F080000, 64K, 0,0,0,0}`; `test_dev.c` table-bytes
  assert updated to the rng.md vector (W3).
- `cpu.c` — `case SE_DEVIDX_RNG:` in `apply_events`: enqueue truncate-to-fit,
  record exactly the accepted words via `SeTrace_event` stamped with the
  boundary cycle (zero accepted → no record); on replay, truncation trips the
  NIC-style `RWC_ASSERT(c->ev == c->feed)` assertion. Payload ≤ 1024 B fits
  the existing `SE_NIC_FRAME_MAX` inline cap — do not grow it.
- `main.c` — `validate_event` case: `len % 8 == 0 && 8 <= len && len <= 1024`.
- `trace.c` — nothing (records are generic).

**emu-py** (all under `emu-py/`):
- `devices.py` — `class Rng(Device)`: `load`/`store` with the full E1–E6
  mapping to `AccessError` (size ≠ 8 checked inside the device, per emu-py
  convention), `pending()`, and `event(payload)` validating the encoding
  (ValueError on malformed or on replay-overflow), enqueuing, returning the
  accepted-prefix bytes for recording. Mind Python integer width: mask every
  SplitMix64 step with `& 0xFFFFFFFFFFFFFFFF`.
- `sahara-emu-py` front end — `phys.add_device(rng)`, append rng to
  `event_devices` (position 4, W1 comment), `dev_entries` gains
  `(7, 0x0F080000, 64K, 0,0,0,0)`. The written device table must byte-match
  emu-c's exactly.
- `machine.py` — untouched (state-only pending; `process_events` is generic).

**sahara-gui** (`emu-c/gui/sdl_main.c`) — minimal per R6: session-start
32-word batch + watermark top-up in the pump via `SeCpu_feed`, stamped like
the input batches. No UI, no options. Prove record→replay: drive one
entropy-consuming session through the seam harness (`gui/seam_driver.c`
pattern), then `--replay` its recorded trace and `trace-q diverge` must report
identical. If `run-gui-tests.sh` exists on the branch, add that as a test
there (pure addition).

## Deliverable 3 — conformance tests (pure additions)

Follow the recipe conventions exactly: defs.s assembled first, FAIL_ADDR
0x700 / PASS_MAGIC 0x600D idiom, `expect=` only where needed, checkers as
5-line sh shims over sibling .py importing `trace-q/tracefile.py` and
`encoding.py`, reusing `checks/evcheck.py` helpers. Claim scratch at **0x7c0**
and update `tests/README.md`'s map. Add `DEV_RNG_BASE` to `tests/gen_defs.py`
and regenerate `tests/defs.s` (committed generated file — selftest diffs it).
Give `tests/events/evlib.py` an additive `rng_words()` payload builder
targeting `RNG_DEV_INDEX = 4` (W1 comment). Feed generation must be
deterministic byte-for-byte given identical image bytes.

Five new MANIFEST lines, appended at the end:

- **c7_rng_err** (no feed, headless): reset STATUS = 0; full E1–E6 census
  including empty-pop DEVERR, wrong size, wrong direction (store DATA/STATUS,
  load SEED), unlisted offset, CTRL reserved bits, atomics;
  UNALIGNED-before-DEVERR precedence; predicated-false pop is a no-fault
  no-op; CTRL write/readback. Checker: `check_trap_census` with an exact
  census dict (the .s fault section and the dict change together — say so in
  both headers).
- **c7_rng_queue** (`events=rng_feed.py`, level=2): known words at known
  cycles; STATUS counts up and down; `check_seq` proves FIFO pop order on
  DATA MEMRs and that squashed pops emit no records; visibility cycle-exact
  at the boundary (INPUT-21 analog); WFI wake at exactly the event cycle;
  `check_events_match_feed` byte-exact; `check_classification`.
- **c7_rng_prng** (no `events=`, so it runs without the REPLAY gate and in
  the gate's difftest): SEED write; first 8 outputs compared against
  hand-derived SplitMix64 constants embedded in the .s (derive them from the
  spec by hand or an independent one-off script — never from either
  emulator); reseed restarts the stream; MODE flips both ways; STATUS and
  queue unchanged by PRNG pops; no empty-pop DEVERR in PRNG mode.
- **c7_rng_overflow** (feed of 256+K words across records, including one
  record arriving at depth 256): STATUS caps at 256; pops return exactly the
  first 256 accepted words; dedicated checker asserts the recorded EVENT
  payload equals the accepted words only (truncated bytes, not raw feed) and
  that the zero-accepted record recorded nothing.
- **c7_rng_irq** (`events=`): IE=0 → no EXTINT with depth > 0; IE=1 → level
  asserted; deasserts on drain to 0; WFI wake lands at exactly the event
  cycle even with IE=0.

REPLAY=1 legs run automatically for all five; the truncated-record fixed
point (recorded trace replays diverge-clean) is exercised for free. Update
`tests/selftest.sh`'s count arithmetic (NTESTS and the events=-skip counts) —
that is an update to selftest's expectations, not to any existing test.

Expectations must be derived independently of any emulator: hand-derived from
the spec, or committed deterministic generators.

## Deliverable 4 — CONFORMANCE-DELTA entry

Per `devspec/CONFORMANCE-DELTA.md`'s structure: one C7 row for rng.md's
register/DEVERR/queue/PRNG clauses (source §, requirement range, one-line
scope); one Reference-implementation-only row for the EVENT/replay clauses;
extend the five "Deliberate instantiations (not duplicates)" lists
(atomics-DEVERR, predicated-false-no-fault, non-64-bit DEVERR,
event-visibility-at-boundary, per-device EXTINT level) with the RNG
instances. CONFORMANCE.md itself is frozen — never touch it.

## Definition of done (exact commands, from the worktree root)

    (cd emu-c && ./build.sh)
    ./run_tests.sh
    tests/selftest.sh
    tests/difftest.sh emu-py/sahara-emu-py emu-c/bazel-bin/sahara-emu
    REPLAY=1 tests/difftest.sh emu-py/sahara-emu-py emu-c/bazel-bin/sahara-emu

- `emu-c/build.sh` green end to end: bazel unit tests (incl. the updated
  `test_dev.c` table assert) + the full conformance suite with REPLAY=1 — 23
  tests, the five new ones included, every test double-run byte-identical
  (run-tests.sh checks determinism for free) and the replay-of-own-trace leg
  diverge-clean.
- `./run_tests.sh` (root wrapper → emu-py/run-tests.sh) green, REPLAY=1 leg
  included.
- `tests/selftest.sh` green with the updated count arithmetic.
- difftest without REPLAY: 100% IDENTICAL — this is what the gate runs, and
  it covers the new register-model tests (c7_rng_err, c7_rng_prng).
- difftest with REPLAY=1: 100% IDENTICAL — the gate does not run this leg
  (known wave-wide gap, out of scope to fix here), but you run it locally as
  the cross-emulator EVENT byte-comparison evidence.
- If `emu-c/run-gui-tests.sh` exists: green, including the rng record→replay
  seam test.
- Existing-18-untouched check:

      git diff main...HEAD --name-status -- tests/

  must show only `A` lines plus `M` for exactly: `tests/MANIFEST` (appended
  lines only), `tests/defs.s` + `tests/gen_defs.py` (regenerated/extended),
  `tests/selftest.sh` (count arithmetic), `tests/README.md` (scratch map),
  `tests/events/evlib.py` (additive builder). None of the 18 existing .s
  files, their checkers, their feeds, `tests/run-tests.sh`, or
  `tests/difftest.sh` may appear.
- Commit in small green steps on `dev-rng`, spec commit first.

## Scope boundaries

- **No Oasis changes.** Note in your hand-off what the OS adopts later: the
  kernel can seed its entropy pool from the queue (STATUS-then-pop under the
  EXTINT handler's table-scan discovery) and may use PRNG mode in test rigs;
  sreg timecmp and the timer device are unrelated to this branch.
- **sahara-gui: the minimal R6 live path only** — it is required for rng (the
  recorded-entropy story needs a recorder), but nothing beyond watermark
  top-up + the record→replay proof.
- **No changes to other devices' specs.** display.md, input.md, nic.md,
  boot.md untouched (W3). trace.md gets exactly §4.6 + the type-list line —
  it is the payload owner, that edit is the mechanism, not an exception.
- **Frozen files stay frozen**: ISA-SPEC.md, PLATFORM-SPEC.md,
  TOOLING-SPEC.md, CONFORMANCE.md, CONSTRAINTS.md. A conflict with a frozen
  spec gets a conservative-loud reading recorded in SPEC-ISSUES.md, not a
  silent fix. Expected new SPEC-ISSUES entries: none (#12 is avoided by
  design — no config keys, seed is guest-written, defaults pinned).
- **One-time grant, precisely scoped**: this branch may ADD test files and
  MANIFEST lines, and update selftest arithmetic / README map / defs
  generator / evlib additively — it may never modify the 18 existing tests,
  existing checkers, `run-tests.sh`, `difftest.sh`, or anything under
  `trace-q/`. If a suite bug blocks you, record it in SPEC-ISSUES.md and
  stop rather than patching around it.

## Risks and traps

- **The byte-match risk is concentrated in one rule**: "recorded = accepted
  prefix". Both emulators must express it identically — same truncation
  arithmetic, same zero-accepted-records-nothing behavior. difftest with
  REPLAY=1 is your line-holder; run it early, not last.
- **EVENT stamp asymmetry**: emu-c records with the boundary cycle
  (`c->cycle`), emu-py with the feed record's cycle. They agree today because
  recorded stamps are always boundary cycles and event wakes land exactly at
  the event cycle. Preserve that fixed point — do not "fix" either side.
- **Faulting accesses have zero side effects**: E6 must be detected before
  the pop; a predicated-false or faulting DATA access must not advance PRNG
  state either. Order your checks per the precedence chain.
- **No WFI/cycle plumbing.** RNG pending is pure state. If you find yourself
  editing `wfi_wait`, `wfi_wake_exists`, or `machine.py wfi_stall`, stop —
  that is the timer/DMA branches' structural change, not yours.
- **`li` on a label is assembler error E029** — use `la`/`la.abs` in the .s.
- **Python SplitMix64 needs 64-bit masking** at every step or the two
  emulators diverge on the first PRNG pop.
- **selftest count arithmetic** breaks the moment MANIFEST grows — update it
  in the same commit as the MANIFEST lines.
- **W1 renumber discipline**: the table index must appear as a literal in as
  few places as possible (one constant per component, each with the
  WAVE-RENUMBER comment). Grep for `SE_DEVIDX_RNG|RNG_DEV_INDEX` before you
  finish and confirm nothing else hardcodes 4.

## Hand-off notes to include when done

Report: the three (flag) items for the wave judge — W1 index renumber 4 → 6,
W2 window slotting 0x0F08_0000 with holes either side, W3 the combined boot
vector carrying all three wave records; the difftest REPLAY=1 gate gap
(inherited, unfixed); and the Oasis adoption note above.
