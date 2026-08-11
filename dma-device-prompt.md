# Work order: DMA engine — memory offload and the descriptor lingua franca

Branch: `dev-dma` (worktree of the main repo, full spec access). Read
`emu-common-prompt.md`, `emu-c-prompt.md`, and `emu-py-prompt.md` first;
they govern. Read `devspec/nic.md`, `devspec/display.md`, and
`devspec/boot.md` §3–§5 IN FULL — they are the house style and the
device-table contract your spec must slot into — and `devspec/trace.md`
§3.3/§5 for the boundary-phase ordering your completion semantics pin.

The design below was settled in advance (owner-approved wave, merged
final design) and is **binding**. Do not relitigate the resolved
decisions — the Appendix of resolved divergences is closed. Where you
must invent a reading the design does not give, take the conservative
loud-failure reading and record it in SPEC-ISSUES.md before merge, per
house protocol.

## Why this exists

The owner's doctrine: peripherals are optional accelerators, not
complex hardware. The DMA engine is the first accelerator of the wave
and goes first **because its descriptor format becomes the lingua
franca later descriptor-consuming devices reuse** — the 64-byte layout,
the opcode registry, and the CAPS versioning contract you write in
`devspec/dma.md` §4 are what the next wave builds on. Get them right
here; they are never repurposed afterward.

The device itself is deliberately small: memory-to-memory COPY and
FILL, offloaded, with a spec-pinned deterministic cycle-cost model
(`C_done = C_doorbell + K + LEN/8`, K=8, W=8 bytes/cycle — a genuine
~3× win over a guest LD/ST loop without being magic). The determinism
story is the axiom everything else follows from:

> A DMA job is a pure function of (descriptor bytes latched at
> doorbell, RAM contents at the completion boundary, doorbell cycle).
> No EVENT feed, no host input, no internal buffering, no live-mode
> path. The transfer emits ZERO trace records (frozen precedent:
> emulator-internal writes such as NIC RX buffer fill emit no
> MEMW/DEVW). Replay reproduces every transfer from the guest's own
> doorbell DEVW already in the trace. trace.md v1 stays closed — no
> new record type.

That axiom is why this device is the cheapest of the three to build:
no EVENT payload spec, no trace.md change, no sahara-gui change, no
`validate_event` case, no evlib payload builder. Both emulators do the
same integer arithmetic on the same latched bytes and write RAM
silently at the same boundary — byte-identity under difftest is by
construction, and your job is to not break the construction.

## What already exists — do not rebuild it

- **The boundary device phase.** `apply_events` in emu-c/cpu.c and
  `process_events` in emu-py/machine.py already run at inter-instruction
  boundaries, before interrupt recognition (trace.md §3.3 order:
  EVENTs, then TRAP, then next instruction). DMA completion is a new
  step in that phase — after EVENT apply, before interrupt
  recognition — not a new phase.
- **The DEVERR machinery.** emu-c: `data_access` funnels register
  windows through `SeDev_reg_read/write` with the frozen check order
  (alignment → translate → classify), central size==8 check,
  `acc_fault()` = no side effect, `RWC_ASSERT(0)` default case. emu-py:
  per-device `load/store` raising `mem.AccessError`, size checked
  in-device. The NIC's E1–E7 catalog + precedence chain is your model.
- **The WFI wake plumbing.** `wfi_wait`/`wfi_wake_exists` (emu-c) and
  `wfi_stall` (emu-py) enumerate wake sources: already-pending, sreg
  timecmp, feed-head event cycle. You are adding a fourth source
  (`comp_cycle`), which is the known structural change this wave
  forces — shared with the timer device, so keep the seam clean.
- **The weak-store queue discipline.** Any device access flushes the
  ordq before the device sees it (emu-c `ordq_flush`, emu-py D10).
  At a boundary the queue is already drained — your completion step
  asserts that, it does not re-flush.
- **The device-table writer pair.** `se_plat_write_devtable` (emu-c)
  and `image.write_device_table` fed by `dev_entries` (emu-py) must
  emit byte-identical tables; emu-c/test_dev.c asserts the bytes.
- **The test harness recipe.** run-tests.sh assembles
  `tests/defs.s` + your source, runs twice with byte-identical-trace
  determinism checking for free, then the REPLAY=1 replay-of-own-trace
  leg, then `tests/checks/<name>.sh` on run a. `tests/defs.s` is a
  committed generated file — new constants go into `tests/gen_defs.py`
  and get regenerated (selftest diffs it).

## Binding decisions

### 1. Identity and device table

1. Device type code **6** (wave convention: timer=5, dma=6, rng=7 —
   these are pinned across the wave; do not renumber).
2. Window base **0x0F07_0000**, size **0x1_0000**, carved from the
   DEVERR hole [0x0F06_0000, 0x1000_0000). 0x0F06_0000 is RESERVED for
   the timer device on its own branch — do not touch it.
3. **params[0..3] = 0.** All limits are spec-pinned and surfaced in
   CAPS. Table stays minimal; guests ignore-not-fault nonzero unknown
   params per boot.md §4.4.
4. No device-table format version bump: old kernels skip the unknown
   type-6 record positionally (boot.md §4.2; the §4.3 growth
   mechanism, already vectored by V2's unknown type-9).
5. **On this branch** the reference table has five device records and
   DMA sits at table index 4 (display 0, kbd 1, mouse 2, nic 3,
   dma 4). The wave-final index 5 (timer sorting first at
   0x0F06_0000) materializes at integration, when each branch's record
   merges in ascending-base order. Nothing durable may depend on DMA's
   index: DMA is not EVENT-fed, so no trace record ever names it, and
   the EVENT device indices 0–3 stay frozen. Add a NEW boot.md test
   vector pinning this branch's full table bytes (V1 and V2 untouched,
   byte-for-byte), marked as superseded-at-integration by the
   wave-final vector; emu-c/test_dev.c covers it via an ADDED case,
   never by editing the V1 case.

### 2. Descriptor format (dma.md §4 owns it — the wave's lingua franca)

**64 bytes in ordinary RAM, 64-byte aligned** (boot.md record grain;
arrays pack, never straddle). All fields u64 little-endian.

| off | field | v1 meaning |
|---|---|---|
| 0 | OP | bits 7:0 opcode: 0 reserved-never-assigned (zeroed-RAM guard), 1=COPY, 2=FILL. Bit 8 IRQ_ON_COMPLETE. Bits 63:9 reserved, MBZ |
| 8 | SRC | COPY: source PA. FILL: the 8-byte pattern itself, replicated over DST |
| 16 | DST | destination PA |
| 24 | LEN | bytes; > 0, multiple of 8, ≤ 2^24 (16 MB) |
| 32 | NEXT | reserved for v2 chaining; MBZ in v1 |
| 40–63 | — | reserved; MBZ |

- **Alignment doctrine (normative prose in the spec):** SRC, DST
  8-aligned; LEN multiple of 8. Bulk offload is the accelerator's job;
  byte-granular edges are three guest instructions. Keeps datapath,
  cost model, and FILL integer-exact.
- **No in-descriptor version field.** The consuming device's CAPS
  states the descriptor-format major version; reserved-MBZ fields are
  the extension mechanism — a later rev assigns meaning only to fields
  v1 required to be zero, and a v1 device rejects them (BAD_FORMAT),
  never default-on (display.md §8 precedent). NEXT is pre-reserved so
  chaining lands without relayout. v1 offsets and opcodes are never
  repurposed.
- **Opcode registry:** dma.md §4 owns the opcode space shared by
  future descriptor-consuming accelerators; 0 never assigned; 1–2
  assigned here; later devices claim from CAPS-gated ranges recorded
  in this registry. Write the registry as a section future specs
  append to.
- LEN=0 is BAD_RANGE, not a no-op (loud-failure house policy; also
  keeps C_done > C_doorbell doubly guaranteed). Overlap of
  [SRC,SRC+LEN) and [DST,DST+LEN) is **legal and defined** — memmove
  semantics, free under atomic-at-boundary completion.

### 3. Register window (base + offset; all u64; 64-bit access only)

| off | reg | access | semantics |
|---|---|---|---|
| 0x00 | CAPS | R | bits 7:0 descriptor-format version = 1; bits 15:8 log2 W = 3; bits 23:16 K = 8; bits 31:24 log2 LEN_MAX = 24; bits 63:32 = 0 |
| 0x08 | STATUS | R | bits 7:0 state: 0 IDLE, 1 BUSY, 2 DONE, 3 BAD_OP, 4 BAD_FORMAT, 5 BAD_ALIGN, 6 BAD_RANGE; bits 63:8 = 0 |
| 0x10 | DOORBELL | W | descriptor PA; submits (validation synchronous at the store) |
| 0x18 | IRQ_ACK | W | write 1 clears the device's EXTINT pending level (no-op if not pending — race-free); any other value DEVERR |
| 0x20 | COMP_CYCLE | R | cycle at which the most recent job reached its terminal state: C_done for accepted jobs, the doorbell cycle for content-error jobs; 0 after reset |

There is NO CTRL register (IRQ policy is per-descriptor OP bit 8) and
NO DESC_PA readback register — resolved, dropped, do not add them.
Reset: STATUS=IDLE, COMP_CYCLE=0, pending clear. STATUS is overwritten
only by the next doorbell (→ BUSY, or straight to a terminal code);
IRQ_ACK never touches STATUS. A new doorbell is legal from IDLE, DONE,
and every error state; only BUSY rejects it (DEVERR).

### 4. Submission, completion, cycle model

1. **One-register submission.** Writing the descriptor PA to DOORBELL
   is the single atomic submission point; one DEVW record marks the op
   in the trace. The device reads the 64 descriptor bytes synchronously
   at the doorbell instruction as a device-internal read — **no MEMR
   records** (NIC internal TX-buffer read precedent). **Descriptor
   bytes are latched at doorbell**: later guest stores to them do not
   affect the in-flight op (normative, tested).
2. **Cost model:** `C_done = C_doorbell + K + LEN/8`, K=8, W=8. LEN is
   a multiple of 8, so no ceil — integer-exact and hand-computable.
   Constants are "reference defaults fixed by this document"
   (display.md precedent) and mirrored in CAPS. C_done > C_doorbell
   always.
3. **Completion is fully atomic at one boundary:** the first
   inter-instruction boundary B with cycle(B) ≥ C_done, in the boundary
   device phase, **after feed EVENTs bound to B, before interrupt
   recognition** (matches trace.md §3.3 events-first; pin the order
   normatively in the spec even though v1 state is disjoint and it is
   unobservable today). At B: COPY reads all LEN source bytes, then
   writes all LEN destination bytes, as-if through an intermediate
   buffer; FILL writes the replicated pattern. Consequences, all
   normative and tested: overlap = memmove result; source bytes are
   **sampled at completion** (a guest store into [SRC,SRC+LEN) after
   doorbell but before C_done IS copied); no partially-copied state is
   ever observable.
4. **Signaling — both poll and interrupt.** STATUS→DONE at B;
   COMP_CYCLE=C_done; if latched OP bit 8 was set, the device's term
   in the level-triggered EXTINT OR asserts until IRQ_ACK.
5. **WFI:** DMA completion is a wake source; a WFI sleeping past
   C_done wakes with the boundary at **exactly C_done** (the frozen
   event-wake rule, NOT the timecmp T+1 rule — this is an internal
   event at a known cycle).
6. **Content-error path:** descriptor-content errors terminate at the
   doorbell boundary itself: BUSY never sets, STATUS reads the error
   code on the very next instruction, COMP_CYCLE = doorbell cycle,
   destination untouched, pending raises iff latched OP bit 8 = 1
   (one wait-path for software). No "busy then fail" window exists.

### 5. Errors — two classes, split by where the badness lives

**Access/value errors → DEVERR** (cause 12, baddr = offending EA, ISA
no-effect rule). E-catalog E1–En with the NIC check-precedence chain
copied verbatim: predication → translation → UNALIGNED → atomic →
size ≠ 8 → offset/direction (unlisted offset; load of
DOORBELL/IRQ_ACK; store to CAPS/STATUS/COMP_CYCLE) → value/state.
Value/state-class: DOORBELL while STATUS=BUSY (state-dependent DEVERR,
input empty-pop precedent); DOORBELL PA not 64-aligned or [PA,PA+64)
not wholly inside RAM; IRQ_ACK value ≠ 1.

**Descriptor-content errors → STATUS code, not trap** (the doorbell
store retires; the badness is RAM data, not the access). Check order:
BAD_OP → BAD_FORMAT → BAD_ALIGN → BAD_RANGE, first failure reported.

- BAD_OP (3): opcode not 1 or 2 (including 0).
- BAD_FORMAT (4): any reserved-MBZ violation — OP bits 63:9 nonzero,
  NEXT ≠ 0, reserved words 40–63 nonzero. (Split from BAD_OP so
  forward-compat rejection — a v2 descriptor on a v1 device — is
  distinguishable and directly testable.)
- BAD_ALIGN (5): SRC or DST not 8-aligned (COPY: both; FILL: DST
  only), or LEN not a multiple of 8.
- BAD_RANGE (6): LEN = 0, LEN > 2^24, or [SRC,SRC+LEN) /
  [DST,DST+LEN) not wholly inside RAM regions. DMA touches **ordinary
  RAM only**: device windows, the pixel buffer, and holes are
  BAD_RANGE (the device-table region is ordinary RAM and legal).
  Pixel-buffer blit is an explicit v2 extension candidate, CAPS-gated
  — name it in the spec's extension section, do not implement it.

## Deliverables — in this order

### 1. `devspec/dma.md` — written FIRST, house style

The spec precedes the code; both emulators implement the document, not
each other. Skeleton (mirror display.md/nic.md anatomy):

1. Preamble: Version 1.0-draft, companion to ISA-SPEC.md and
   PLATFORM-SPEC.md, frozen-spec-wins, notes-are-non-normative.
   Ownership block — owns: descriptor format + opcode registry,
   register window, cost model, STATUS codes; restates: DEVERR per
   PLATFORM-SPEC, boundary order per trace.md §3.3, device table per
   boot.md §3; referenced-never-defined list. Add the INDEX.md row.
2. Overview and discovery: type 6, params-zero, reference defaults
   "fixed by this document" table (base, size, K, W, LEN_MAX).
3. Register window: the §3 table above + numbered access rules +
   E-catalog with the precedence chain.
4. Descriptor format: layout, alignment doctrine, latching rule,
   versioning/reuse contract, opcode registry.
5. Job lifecycle: submit/validate/BUSY/terminal state machine;
   content-error path.
6. Cycle-cost model with a worked C_done arithmetic example.
7. Determinism and trace: the pure-function axiom; the no-records
   rule; replay isolation (no EVENT feed, no host consulted);
   EVENTs-before-DMA boundary order; WFI wake at exactly C_done.
8. Errors: catalog + both precedence chains.
9. Reserved/extension rules: reads-0/writes-DEVERR outside the map;
   CAPS-gated opt-in only; never repurpose v1 offsets/opcodes.
10. Conformance clauses DMA-C-01… grouped (registers and errors /
    descriptor and jobs / completion timing), one testable behavior
    each, citing vectors; replay/trace clauses segregated at the end
    and marked "(reference implementation)" — including the
    no-records clause.
11. Test vectors: access-matrix rows (display.md style); descriptor
    hex dumps + boot.md-style `expect key = value` lines; a worked
    cost vector; this branch's full reference-table dump.
12. Cross-document dependencies, §-exact.

Plus the additive boot.md vector (deliverable of this section, per
Binding decision 1.5) and the SPEC-ISSUES.md check: the design needs
**no new entries** (no config keys, constants spec-pinned) — if you
find yourself writing one, stop and re-read the design first.

### 2. Both emulator implementations

Difftest must stay byte-identical: same integer C_done arithmetic,
silent RAM writes on both sides, the only DMA-related records are the
guest's own generic DEVW (doorbell/IRQ_ACK stores) and MEMR (register
reads at level ≥ 2).

**emu-c:**
- platform.h: `SE_PLAT_DMA_BASE 0x0F070000`, `SE_SPACE_DMA` enum
  member, classify branch; the hole comment shrinks accordingly.
- dev.h: `SE_DEVIDX_DMA`, COUNT bump; SeDev fields: status,
  comp_cycle, irq_pending, latched {op, src, dst, len} (FILL pattern
  lives in src). **No inject fn** — not EVENT-fed.
- dev.c: private register-offset enum; `case SE_SPACE_DMA:` in both
  SeDev_reg_read and SeDev_reg_write. Doorbell: read 64 bytes from
  mem, validate content, latch-and-arm or set terminal status;
  `acc_fault()` on every DEVERR class with zero side effects.
  SeDev_reset init. SeDev_ext_pending gains only the stored
  `irq_pending` term — **the signature stays cycle-free** (the pending
  flip happens in the boundary advance, not in the predicate).
  se_plat_write_devtable: +type-6 record, count literal bump;
  test_dev.c asserts the new vector's bytes via an added case, V1 case
  untouched.
- cpu.c: the boundary device phase gains
  `SeDev_dma_advance(dev, mem, cycle)` performing the memmove/fill +
  STATUS/COMP_CYCLE/pending flip when cycle ≥ comp_cycle, called
  **after EVENT apply, before interrupt recognition**; wfi_wait /
  wfi_wake_exists add comp_cycle as a wake source; assert the ordq is
  empty at the boundary (drained, don't re-flush). No apply_events
  case, no main.c validate_event case, no SeEvRec growth.

**emu-py:**
- devices.py: `class Dma(mem.Device)` — load/store with AccessError
  per DEVERR class (size checked in-device, per emu-py convention),
  `pending()`, `advance(cycle)`, `wake_cycle()`. **No `event()`.**
- machine.py: boundary phase calls `dma.advance(self.cycle)` after
  process_events, before pending_interrupt; wfi_stall adds
  `dma.wake_cycle()` as a wake source.
- sahara-emu-py: `phys.add_device(dma)`; `dev_entries` +=
  `(6, 0x0F070000, 0x10000, 0, 0, 0, 0)`; **event_devices
  unchanged** — EVENT indices 0–3 stay stable.
- trc.py untouched.

### 3. Conformance tests — pure additions

This branch carries an explicit one-time grant to ADD test files and
MANIFEST lines. It may NEVER modify the existing 18 tests, their
checkers or feeds, run-tests.sh, difftest.sh, or trace-q. All new
tests are cycle-driven — **no `events=` line** — so every one of them
runs under difftest today (no REPLAY-gate gap for this device).

Recipe per the suite conventions: pass/fail via r24=FAIL_ADDR 0x700 /
PASS_MAGIC 0x600D, r27 test IDs, `la` not `li` for label addresses;
`DEV_DMA_BASE` added via tests/gen_defs.py and defs.s regenerated;
scratch slots claimed from the free 0x7c0/0x7f0–0x7f8 range with
tests/README.md's map updated; checkers reuse checks/evcheck.py
helpers with a 5-line sh shim + sibling .py; MANIFEST lines appended
at the end; tests/selftest.sh count arithmetic updated to track the
new lines (that is an update to selftest's expectations, not to any
existing test). Expected values hand-derived from the devspec, never
from an emulator run.

- **dma_regs** (level=2, checker): reset values pinned (exact CAPS
  encoding, STATUS=0, COMP_CYCLE=0); full DEVERR access matrix
  (size≠8, atomics, wrong direction, unlisted offsets, IRQ_ACK≠1)
  with an exact trap census; MEMR value assertions.
- **dma_copy** (difftest-visible, default flags): 4 KB COPY;
  sreg-cycle reads bracketing the doorbell; poll STATUS; assert
  COMP_CYCLE == C_doorbell + 8 + 512 exactly; guest checksums the
  destination. Checker: exactly one doorbell DEVW, **zero MEMW/DEVW
  records inside [DST, DST+LEN)** — the no-records clause, enforced.
- **dma_fill**: pattern replication; the cost formula at a different
  LEN.
- **dma_err**: one descriptor per STATUS code (BAD_OP incl. opcode 0;
  BAD_FORMAT via NEXT≠0 and via OP bit 9; BAD_ALIGN; BAD_RANGE incl.
  LEN=0 and a pixel-buffer DST); terminal immediately post-doorbell;
  COMP_CYCLE = doorbell cycle; destination proven untouched by guest
  re-reads; error-with-IRQ_ON_COMPLETE raises pending.
- **dma_boundary**: descriptor overwrite after doorbell → ignored
  (latch rule); store into SRC after doorbell, before C_done → copied
  (completion sampling); overlapping COPY → exact memmove result;
  doorbell-while-BUSY DEVERR.
- **dma_irq_wfi**: OP bit 8 + WFI; handler reads the cycle sreg;
  checker asserts wake at exactly C_done, single EXTINT delivery,
  IRQ_ACK drops the level; EXTINT source discovery by device-table
  scan (no interrupt controller exists).
- **dma_boot**: parse test against the new boot vector pinning the
  type-6 record bytes (unknown-type skip is already covered by V2 —
  do not re-test it).
- DMA instances for the five shared parameterized rules (atomics-
  DEVERR, predicated-false-no-fault, non-64-bit DEVERR,
  boundary-visibility, per-device EXTINT level): where the suite
  already parameterizes, extend the instantiation; where it does not,
  the instance lives inside dma_regs/dma_boundary/dma_irq_wfi and the
  CONFORMANCE-DELTA list records it as a deliberate instantiation, not
  a duplicate.

### 4. `devspec/CONFORMANCE-DELTA.md` entry

CONFORMANCE.md is frozen — never touch it. Add: one **C7 row**
(source §, DMA-C requirement range, one-line scope) for the
register/DEVERR/behavior clauses; one **reference-implementation
row** for the replay-isolation and no-records clauses; extend the
five **deliberate-instantiation lists** with the DMA instances named
above.

## Definition of done

Run from the `dev-dma` worktree root. If the worktree does not sit
next to `~/proj/rightwayc`, plant the sibling symlink first, exactly
as .quilt/gate-tests.sh does:
`ln -sfn /home/hila/proj/rightwayc "$(cd .. && pwd)/rightwayc"`.

- `tests/selftest.sh` green (its count arithmetic tracks the new
  MANIFEST lines).
- `(cd emu-c && ./build.sh)` green end to end — bazel test (including
  the new test_dev.c table-vector case), image tests, and the full
  conformance suite with REPLAY=1, all dma_* tests included. The
  suite's double-run `cmp` gives determinism, and the REPLAY=1 leg
  proves replay-of-own-trace reproduces every DMA transfer from the
  doorbell DEVW alone with `trace-q diverge` clean.
- `emu-py/run-tests.sh` green end to end, same suite, REPLAY=1 leg
  included.
- `tests/difftest.sh emu-py/sahara-emu-py emu-c/bazel-bin/sahara-emu`
  — 100% IDENTICAL across all lines, the new dma_* tests included
  (they are all cycle-driven, so none are REPLAY-gated); zero DIVERGE,
  zero BROKEN, no new SHARED-FAIL.
- Existing-18-untouched check:
  `git diff main --stat -- tests/` shows ONLY: new `dma_*.s` files,
  new `checks/dma_*` files, appended MANIFEST lines, the regenerated
  `defs.s` + its generator (new constants only), README.md scratch-map
  additions, and selftest.sh count updates. No existing `.s`, checker,
  feed, run-tests.sh, or difftest.sh hunk. Verify explicitly:
  `git diff main -- tests/c0_smoke.s ... tests/c7_resize.s tests/run-tests.sh tests/difftest.sh trace-q/` is empty.
- `devspec/dma.md`, the boot.md additive vector, INDEX.md row, and
  the CONFORMANCE-DELTA entry committed; every DMA-C clause maps to a
  test or a vector.
- Commit in small green steps on `dev-dma`; spec first, then each
  emulator, then tests.

## Scope boundaries

- **No Oasis changes.** The kernel does not learn about DMA in this
  order. Leave a one-paragraph note in the dma.md overview (`*Note:*`,
  non-normative) that the OS is expected to adopt DMA for bulk
  copies once the timer device lands and the wave integrates.
- **No sahara-gui changes.** DMA has no live path by design — the
  pure-function axiom means the GUI needs zero code. Only the RNG
  work order touches the live front end.
- **No changes to other devices' specs** — display.md, input.md,
  nic.md, trace.md stay byte-identical. boot.md changes are additive
  only (the new vector); frozen root specs are untouchable; conflicts
  go to SPEC-ISSUES.md, not into edits.
- **No timer, no RNG.** 0x0F06_0000 and type codes 5 and 7 belong to
  sibling branches. Do not pre-implement their records or wake
  sources beyond the shared comp_cycle seam your own device needs.
- **No trace format changes.** trace.md v1 is closed; no new record
  type, no META keys, no EVENT payload sections.
- **v1 ops only.** COPY and FILL. Chaining (NEXT), scatter/gather,
  XOR, pixel-buffer blit are named as CAPS-gated v2 candidates in the
  extension section and nothing more.

## Risks (mitigate, don't relitigate)

1. **The stale-pending trap.** SeDev_ext_pending is cycle-free by
   design here: pending flips only inside the boundary advance. If you
   plumb a cycle into the predicate "to be safe", the two emulators
   can disagree on WHEN pending becomes visible relative to the
   boundary phase and difftest diverges on interrupt delivery cycles.
   Keep the flip in advance(), keep the predicate dumb.
2. **WFI wake-rule confusion.** DMA completion wakes at exactly
   C_done (event rule), not C_done+1 (timecmp rule). dma_irq_wfi pins
   this; get it wrong symmetrically in both emulators and difftest
   won't save you — the hand-derived checker cycle assertion is the
   only guard. Derive the expected wake cycle on paper before writing
   the checker.
3. **Latch vs. sample asymmetry.** Descriptor bytes latch at doorbell;
   source bytes sample at completion. An implementation that reads
   source bytes eagerly at doorbell passes dma_copy and fails only
   dma_boundary's store-into-SRC leg. Implement completion as a
   boundary-time memmove from live RAM, never from a stash.
4. **Accidental trace records.** The transfer must write RAM through a
   path that emits nothing — mirror the NIC RX-buffer-fill internal
   write, not the guest store path. dma_copy's checker (zero
   MEMW/DEVW in the destination range) catches emu-c; emu-py has no
   checker leg in difftest, so eyeball its write path explicitly.
5. **Doorbell validation order.** The DEVERR chain (access-level:
   BUSY, PA alignment, PA range) runs at the store and can trap with
   no side effect; the content chain (BAD_OP → BAD_FORMAT →
   BAD_ALIGN → BAD_RANGE) runs after the store retires. Mixing the
   two chains — e.g. trapping DEVERR on a bad opcode — breaks the
   "badness lives in RAM data" split and dma_err's trap census.
6. **Table-index drift at integration.** This branch pins DMA at
   index 4; the wave-final table has it at 5. Anything you write that
   hardcodes the index outside the table-derived places (dev.h enum
   position, dev_entries order, the boot vector) is a merge bomb.
   Guest code discovers the device by type-code scan, never by index.
7. **selftest count arithmetic.** Adding MANIFEST lines without
   updating tests/selftest.sh's expected counts turns the fast gate
   red with a message that looks like a harness bug. Update the
   arithmetic in the same commit that appends the lines.
