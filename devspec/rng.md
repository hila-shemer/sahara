# Sahara RNG Device — Detailed Specification

**Version 1.0-draft.** Companion to ISA-SPEC.md and PLATFORM-SPEC.md. The
RNG is an accelerator-wave device: it does not exist in PLATFORM-SPEC's
frozen v1.0 window list, so this document is the sole owner of its
behavior. It is also the wave's device that makes the determinism boundary
explicit: every entropy bit a guest observes through the queue entered the
machine as an EVENT record — feed-supplied under replay, front-end-recorded
in live mode (the NIC-RX pattern exactly). A separate guest-selected PRNG
mode exists as pure architectural state and can never silently substitute
for recorded entropy (§5.3).

Normative except where marked *Note:*.

Ownership (per the devspec ownership matrix):

- **This document owns:** the RNG register map and access rules; the
  entropy queue (depth, boundary visibility, the truncate-to-fit
  acceptance rule and its recorded-equals-accepted consequence); the PRNG
  algorithm, mode and seed semantics; the type-7 device-table record and
  its parameter defaults; the live-mode top-up policy statement (§7.5,
  non-normative).
- **Frozen elsewhere, restated here:** DEVERR cause 12 and the no-effect
  rule for faulting accesses (ISA-SPEC §7.1, §4); the 64-bit-only
  register-access rule (PLATFORM-SPEC §1); the level-triggered EXTINT OR
  (PLATFORM-SPEC §3); the event-boundary visibility rule
  (devspec/trace.md §3.3).
- **Referenced, never defined here:** the EVENT payload byte encoding —
  devspec/trace.md §4.6 owns it; the device-table record layout —
  devspec/boot.md §3.5.

---

## 1. Overview and discovery

The RNG delivers host entropy to the guest through a FIFO of 64-bit words
(QUEUE mode, the reset default) and, alternatively, a deterministic
guest-seeded PRNG stream (PRNG mode). The guest discovers it from the
device table (layout per devspec/boot.md §3.5): a device record with
`type = 7`, `base` = the control-window PA, `size` = the window length,
and `params[0..3] = 0`.

Reference platform values (reference defaults fixed by this document):

| item | value |
|------|-------|
| device-table type code | 7 |
| control window base | PA 0x0F08_0000 |
| control window size | 64 KB (0x1_0000 bytes) |
| `params[0..3]` | 0, 0, 0, 0 |
| queue depth | exactly 256 words (2 KB) |

`params` semantics follow boot.md §4.3's growth rule: 0 in every slot
means exactly the v1 behavior specified here (depth 256 is fixed by this
document, not a parameter); guests must ignore, not fault on, a nonzero
value in a slot they do not use. Guests that predate type 7 skip the
record positionally (boot.md §4.2) and observe no other change: the
device's interrupt contribution is disabled at reset (§6), so the RNG is
invisible to software that never touches it.

The window is device space in the sense of ISA-SPEC §9.2: accesses are
mutually program-ordered, stores are release fences, and atomics trap
DEVERR. Classification of the surrounding physical space is unchanged:
[0x0F06_0000, 0x0F08_0000) and [0x0F09_0000, pixel buffer) are undeclared
holes and trap DEVERR (boot.md §3.4 hole rule).

## 2. Register window

Base 0x0F08_0000; all registers 64 bits, little-endian, naturally
aligned, 64-bit accesses only (PLATFORM-SPEC §1 rule, restated).

| off  | reg    | access | semantics |
|-----:|--------|--------|-----------|
| 0x00 | DATA   | R  | QUEUE mode: pop and return the oldest queued word; DEVERR if depth = 0 (E6). PRNG mode: return the next SplitMix64 output and advance the PRNG state; the queue is untouched |
| 0x08 | STATUS | R  | queue depth, 0–256; no side effects; unaffected by mode and by PRNG pops |
| 0x10 | CTRL   | RW | bit 0 `MODE` (0 = QUEUE, 1 = PRNG), bit 1 `IE`; bits 63:2 reserved — read 0, a write with any reserved bit set traps DEVERR (E5), no state change; reset 0 |
| 0x18 | SEED   | W  | store: PRNG state = the stored value, the PRNG stream restarts (§5.1); a load traps DEVERR (E2) |

Access rules, numbered:

1. **Size.** Any access of size other than 64 bits anywhere in the window
   traps DEVERR with `baddr` = ea (E3). 128-bit LD128/ST128 is not 64-bit.
2. **Direction.** A store to DATA or STATUS, or a load from SEED, traps
   DEVERR, `baddr` = ea (E2).
3. **Unlisted offsets.** Any access at an offset other than 0x00, 0x08,
   0x10, 0x18 traps DEVERR, `baddr` = ea (E1). Nothing in this window is
   reserved-readable; extension happens per §9.
4. **Atomics.** Any CAS or AMO targeting the window traps DEVERR (E4;
   ISA-SPEC §5.4/§9.2).
5. **Side effects.** A successful DATA load pops one word (QUEUE mode) or
   advances the PRNG state by one step (PRNG mode). STATUS and CTRL loads
   never have side effects. A **faulting** access has no device effect:
   no pop, no PRNG advance, no CTRL change (ISA-SPEC §4).
6. **Predication.** A predicated-false access performs no device access,
   cannot fault, pops nothing, advances no PRNG state, and retires in one
   cycle (ISA-SPEC §3.2, frozen).

Reset state: queue empty (STATUS = 0), CTRL = 0 (QUEUE mode, IE off),
PRNG state = 0.

## 3. Consumer contract

In QUEUE mode an empty-queue DATA pop is a DEVERR trap, not a sentinel
(§4.1 rule 4 gives the rationale). The supported consumption pattern is
**STATUS-then-pop**: read STATUS (or take the §6 interrupt), then pop
exactly that many words. This cannot race: words become visible only at
inter-instruction boundaries and arrivals only *add* words, so an
observed depth is a floor for every later pop in the same drain. The trap
is the loud backstop for a consumer that pops more than it counted.

## 4. Entropy queue

### 4.1 FIFO, depth, visibility

1. One FIFO of 64-bit entropy words, depth **exactly 256** (2 KB),
   matching the input-device queue model (input.md §4.1) so the shared
   parameterized queue rules instantiate unchanged.
2. Words become guest-visible — counted by STATUS, poppable via DATA,
   contributing to the §6 pending condition — only at the EVENT boundary
   (trace.md §3.3): an event with cycle C is invisible at every boundary
   where `cycle` < C and visible at the first boundary where
   `cycle` >= C, before the next instruction executes.
3. DATA pops strictly in arrival order (oldest first). Words are never
   discarded by the device for any reason other than a DATA pop; there is
   no flush operation, and PRNG-mode pops do not touch the queue.
4. A DATA load with depth 0 in QUEUE mode traps DEVERR (cause 12,
   `baddr` = ea, zero state change) — E6. No sentinel exists: every u64
   is a legal entropy word, so no in-band value is unambiguous, and a
   silent 0-return would be a silent-garbage security bug. This is a
   deliberate, documented divergence from the input devices' all-ones
   sentinel and follows the NIC empty-pop precedent (nic.md E6).

### 4.2 Arrival: truncate-to-fit, recorded = accepted

An RNG arrival event carries N words, 1 <= N <= 128 (encoding owned by
trace.md §4.6). On apply at its boundary:

1. The model enqueues `min(N, 256 − depth)` words **from the front** of
   the payload — the accepted prefix. The remaining words are discarded.
2. The trace records **exactly the accepted words**: the EVENT record's
   payload is the accepted prefix, 8 × accepted bytes. Zero accepted →
   **no EVENT record at all**.
3. Acceptance is recomputed by the device model from its own depth on
   every apply, live and replay alike — never copied from the feed
   (trace.md §5.4).

This is the NIC-discard asymmetry (nic.md §4.3), deliberately not the
input drop-flag one (trace.md §4.1): entropy words are fungible, so
nothing is lost by not recording which bytes were rejected, and recording
only accepted words makes record→replay a fixed point — a recorded trace's
payloads always fit exactly when replayed (§7.3). There is no trailing
count byte and no drop flag.

*Note: the reference live front end's top-up policy (§7.5) keeps arrival
depth at most 95, so truncation never occurs in a reference live session;
the rule exists so that an overflowing feed still has one exact, testable
meaning.*

### 4.3 Ordering

Arrival events follow the global event rules (trace.md §3.3, elaborated
by nic.md §7.1 within the frozen ISA-SPEC §4 / PLATFORM-SPEC §8):
assigned cycles are non-decreasing in trace order; records sharing a
cycle apply in trace order; within one record, words enqueue in payload
order. Multiple records applying at one boundary are one atomic
depth-jump as far as the guest can observe: no instruction executes
between them.

## 5. PRNG mode

### 5.1 Algorithm (normative): SplitMix64

PRNG state is one u64. Each PRNG-mode DATA load performs, in order, all
arithmetic modulo 2^64:

    state += 0x9E3779B97F4A7C15
    z = state
    z ^= z >> 30;  z *= 0xBF58476D1CE4E5B9
    z ^= z >> 27;  z *= 0x94D049BB133111EB
    z ^= z >> 31;  return z

Test vector: from state 0, the first output is `0xE220A8397B1DCDAF`
(full table in §11.3).

A SEED store sets `state = value` and thereby restarts the stream: the
next PRNG-mode DATA load returns the first output for that seed. SEED is
writable in either mode. PRNG state resets to 0 at machine reset, and is
untouched by mode changes (§5.2), queue pops, and arrivals.

### 5.2 MODE

CTRL bit 0 selects what DATA returns; nothing else. Flipping MODE has no
side effect on the queue or the PRNG state: switching to PRNG and back
loses nothing, and the PRNG stream continues from where it stopped.
Arriving events enqueue regardless of mode; STATUS always reports queue
depth. The empty-pop DEVERR (E6) applies only in QUEUE mode — a PRNG-mode
DATA load never faults for emptiness, since it does not read the queue.

### 5.3 Replay safety (the no-silent-substitution rule)

PRNG mode is guest-selected architectural state, never an emulator
fallback:

1. MODE and SEED change **only** by guest stores in the instruction
   stream. Those stores are DEVW-traced like every device store, so a
   replay reproduces every mode selection and reseed at the same cycles.
2. The emulator has **no path** that switches modes or writes SEED on its
   own: no config key, no device-table parameter, no empty-queue
   fallback. An implementation that returns PRNG output for a QUEUE-mode
   pop — or queue words for a PRNG-mode pop — is non-conforming, however
   it got there.
3. Consequently the determinism argument needs no new machinery: queue
   words are EVENT records (replay-supplied), PRNG words are a pure
   function of DEVW-traced guest writes, and the two never mix.

## 6. Interrupts

CTRL bit 1 `IE` (R/W, reset 0) qualifies the device's contribution to the
level-triggered EXTINT OR (PLATFORM-SPEC §3):

    pending  =  IE == 1  AND  depth > 0        (in any mode)

- Reset-off keeps the device invisible to old kernels: a type-7-unaware
  guest never observes a spurious EXTINT (contrast input.md §5's
  always-pending queues; enable-qualified pending follows the
  NIC-precedented shape of a device the guest must opt into).
- The contribution is level-triggered and deasserts by draining to
  depth 0 or clearing IE; there is no acknowledge register.
- PRNG mode does not mask it: pending depends only on IE and depth.

WFI interaction (frozen rules, restated): an EXTINT made pending by an
arrival wakes WFI; and independently of IE, a feed event is itself a WFI
wake source landing at **exactly the event's cycle** — the woken boundary
applies the event, so the first instruction after WFI observes it
(trace.md §3.3; nic.md NIC-C-36 is the same rule for the NIC).

## 7. Determinism and trace

Structure per nic.md §7.1, binding the RNG to the same frozen rules.

### 7.1 Arrival events and cycle assignment

1. **Boundary effect.** An arrival takes effect at an inter-instruction
   boundary: its consequences (enqueue, STATUS, pending) are visible to
   the first instruction beginning with `cycle >= C` and invisible
   before. Events never take effect mid-instruction.
2. **Monotonicity.** Assigned cycles are non-decreasing in trace order;
   records sharing a cycle apply in trace order.
3. **Causality.** The RNG has no TX side and synthesizes no replies;
   arrivals are external only, so no causality edge exists beyond
   monotonicity.
4. **Live-mode freedom.** A live front end may feed entropy at any
   boundary it chooses (§7.5 states the reference policy); the recorded
   EVENT cycle must equal the cycle at the boundary of application — the
   trace records what happened, never an intention.
5. **Headless reference cycle policy.** The reference implementations
   stamp a fed event at C = max(feed stamp, current cycle); conformance
   tests must **not** assume any particular assignment beyond rules 1–2 —
   they poll STATUS or use WFI.

### 7.2 EVENT payload

Owned by trace.md §4.6: N little-endian u64 words, 8·N bytes. This
document constrains only the information content: the recorded payload
must equal the words the model accepted, in order (§4.2 rule 2), such
that replay reproduces every DATA pop without consulting the host.

### 7.3 Replay

In replay mode the trace is the sole entropy source: the host RNG is
never consulted (no getrandom, no /dev/urandom, nothing — the isolation
statement of nic.md §7.3, applied to entropy). Acceptance is recomputed
per §4.2 rule 3; because a recorded trace carries only accepted words,
replaying it re-accepts every word exactly and re-records byte-identical
EVENT records — the fixed point. If a replayed feed *does* force
truncation (possible only for a hand-built or tampered feed, never for a
conforming recording), the model truncates deterministically per §4.2 and
the recorded output differs from the input feed; the normative
divergence check is trace comparison (trace.md §5.4), and a replayer may
additionally abort loudly at the first divergent record.

*Note: a zero-accepted arrival leaves no record, so it must not be the
sole WFI wake source of a recording — replaying the recording would not
wake there. The reference live policy (§7.5) cannot produce zero-accepted
arrivals; hand-built feeds for conformance tests must poll instead of
WFI-ing on a batch that can truncate to nothing.*

### 7.4 No host state in guest-visible values

Every guest-visible RNG value is a pure function of (reset state, guest
execution, EVENT records): QUEUE-mode DATA values are recorded words,
PRNG-mode DATA values follow §5.1 from DEVW-traced seeds, STATUS/CTRL
follow from the above. Two identical headless invocations produce
byte-identical traces (TOOLING-SPEC §3.1).

### 7.5 Live top-up policy (non-normative, reference front end)

*Note: the reference GUI front end feeds one 32-word batch at session
start, then, on each pump iteration where guest-visible depth < 64, one
further 32-word batch read from host `getrandom(2)`, stamped like input
batches. Arrival depth therefore never exceeds 95 and truncation cannot
occur live. Under the front end's deterministic script mode the batches
come from a fixed-seed generator instead — a scripted session must not
consume host entropy. Live sessions self-record: the apply path IS the
recording path, so any session replays byte-identically (§7.3).*

## 8. Errors

DEVERR catalog (all cause 12, `baddr` = ea, zero device effect — the
faulting access pops nothing, advances nothing, changes nothing):

| # | condition | source |
|--:|---|---|
| E1 | access at an offset not in {0x00, 0x08, 0x10, 0x18} | this spec (loud-failure) |
| E2 | wrong direction: store to DATA or STATUS, load from SEED | this spec |
| E3 | access size ≠ 8 bytes anywhere in the window | PLATFORM-SPEC §1 (frozen) |
| E4 | any atomic (CAS/AMO) anywhere in the window | ISA-SPEC §5.4 (frozen) |
| E5 | CTRL store with any of bits 63:2 set | this spec |
| E6 | DATA load with depth 0 in QUEUE mode | this spec (§4.1 rule 4) |

Check precedence (nic.md §5.2's chain, first failure wins): predication
(a predicated-false access does nothing and cannot fault) → translation
and permission (PF_*/PERM_*) → natural alignment (UNALIGNED) → atomic
(E4) → size (E3) → offset/direction (E1, E2) → value/state (E5, E6). In
particular a misaligned 4-byte access traps UNALIGNED, not DEVERR, and a
misaligned DATA load pops nothing.

## 9. Reserved and extension rules

Display.md §8's pattern, applied here:

1. CTRL bits 63:2 are reserved. v1.0 reads them as 0 and rejects writes
   that set them (E5) — so a future revision can assign meaning to a bit
   knowing no v1.0 guest ever set it. Any future CTRL bit must be opt-in:
   value 0 must mean exactly v1.0 behavior.
2. Unlisted window offsets trap DEVERR in v1.0 (E1). A future revision
   may define new registers at currently-unlisted offsets, discoverable
   via a mechanism it defines; it may never repurpose or alter offsets
   0x00–0x18, the E6 rule, or the §5.1 algorithm behind CTRL bit 0.
3. `params[0..3]` grow per boot.md §4.3 only: 0 keeps meaning exactly
   this document's behavior.
4. Queue depth 256 is fixed for type 7. A device with a different depth
   is a different type code.

## 10. Conformance requirements

Numbered, testable; each names the vector or script (§11) that carries
its data. RW = the RNG window base. All accesses 64-bit unless stated.
These feed CONFORMANCE.md group C7 except the replay clauses at the end.

- **RNG-01.** After reset, STATUS reads 0 and CTRL reads 0 (V-A rows
  1–2).
- **RNG-02.** After n words arrive (n ≤ 256), STATUS reads n; each
  QUEUE-mode DATA load returns the oldest remaining word and decrements
  STATUS by 1; words pop in arrival order (S-1).
- **RNG-03.** STATUS and CTRL loads have no side effect: consecutive
  loads with no intervening arrival, pop, or CTRL store return equal
  values and change no pop sequence (S-1).
- **RNG-04.** A QUEUE-mode DATA load with STATUS = 0 traps DEVERR,
  `baddr` = RW+0, and afterward STATUS still reads 0 and the next
  arrival's words pop intact (E6; V-A row 17).
- **RNG-05.** Any access of size 1, 2, 4, or 16 bytes anywhere in the
  window traps DEVERR, `baddr` = ea (E3; V-A rows 5–8).
- **RNG-06.** A store to RW+0x00 or RW+0x08, and a load from RW+0x18,
  trap DEVERR, `baddr` = ea (E2; V-A rows 14–16).
- **RNG-07.** Any 64-bit access at an unlisted offset traps DEVERR,
  `baddr` = ea (E1; V-A rows 11–13).
- **RNG-08.** Any CAS or AMO targeting any window offset traps DEVERR
  (E4; V-A rows 9–10).
- **RNG-09.** A CTRL store with any of bits 63:2 set traps DEVERR and
  CTRL is unchanged afterward (E5; V-A rows 18–19).
- **RNG-10.** A misaligned access to the window traps UNALIGNED, not
  DEVERR (V-A rows 3–4); a predicated-false DATA load (empty queue
  included) and a predicated-false wrong-size access trap nothing, pop
  nothing, advance no PRNG state, and retire in 1 cycle (V-A rows
  20–21).
- **RNG-11.** CTRL is read-write over bits 1:0: each of the values 0, 1,
  2, 3 stored to CTRL reads back exactly (V-A row 22).
- **RNG-12.** A faulting access has zero device effect: after each V-A
  DEVERR row, STATUS, CTRL, the queue contents, and the PRNG stream
  position are what they were before the row.
- **RNG-13.** In PRNG mode with SEED = 0, eight consecutive DATA loads
  return exactly the §11.3 seed-0 table; the ninth after re-storing
  SEED = 0 returns the table's first entry again (stream restart) (S-2).
- **RNG-14.** SEED stores take effect in either mode: SEED written in
  QUEUE mode, then MODE flipped to PRNG, yields the same stream as
  seeding in PRNG mode (S-2).
- **RNG-15.** MODE flips lose nothing: after k PRNG pops, MODE 1→0→1
  leaves the next PRNG pop returning output k+1 (no restart, no skip)
  (S-2).
- **RNG-16.** PRNG pops leave the queue untouched: STATUS is identical
  before and after any number of PRNG-mode DATA loads, and the eventual
  QUEUE-mode pops return the same words in the same order as if no PRNG
  pop had happened (S-2). A PRNG-mode DATA load with STATUS = 0 does not
  trap.
- **RNG-17.** Arrivals enqueue regardless of mode: words arriving while
  MODE = 1 are present (STATUS counts them, pops return them) after
  flipping back to MODE = 0 (S-2).
- **RNG-18.** An arrival event with cycle C is invisible (STATUS, DATA,
  pending) at every boundary where `cycle` < C and visible at the first
  boundary where `cycle` >= C (S-1; INPUT-21's rule for this device).
- **RNG-19.** With 256 − d < N words of space, an N-word arrival
  enqueues exactly the first 256 − d words: STATUS caps at 256 and pops
  return exactly the accepted prefix, in order (V-B).
- **RNG-20.** EXTINT contribution: with CTRL.IE = 0, depth > 0 causes no
  EXTINT (absent other sources); setting IE = 1 with depth > 0 asserts
  it level-triggered; draining to depth 0 (or clearing IE) deasserts it
  with no other acknowledgment (S-3).
- **RNG-21.** A WFI with a future RNG feed event as the nearest wake
  source resumes at exactly the event's cycle, IE-independent: the first
  post-WFI instruction reads `cycle` = C and STATUS ≥ 1 (S-3).

Replay clauses (reference implementation):

- **RNG-R1.** Every guest-visible entropy word has exactly one EVENT
  record whose payload contains it (§4.2): the concatenation of recorded
  payloads equals the sequence of words ever visible to pops, in order.
- **RNG-R2.** The recorded payload of a truncated arrival is the
  accepted prefix only — 8 × accepted bytes, not the feed's bytes — and
  a zero-accepted arrival records nothing (V-B carries the exact bytes).
- **RNG-R3.** Replaying a recorded trace reproduces every DATA, STATUS,
  and CTRL load value and every EVENT record byte-identically, with the
  host entropy source untouched (trace.md §5.2/T-18/T-19).
- **RNG-R4.** In replay mode the host RNG is never consulted, in either
  MODE — a replayed session works on a machine with no entropy source at
  all.

## 11. Test vectors

### 11.1 V-A — access matrix (display.md V3 style)

Machine state: reset defaults (QUEUE mode, queue empty, PRNG state 0),
supervisor, MMU off. RW = 0x0F08_0000. Rows execute in order; `DEVERR`
means trap cause 12 with `baddr` = the row's address. All state checks
(RNG-12) hold between rows.

| # | address | op | size | value | expected |
|--:|---------|----|-----:|-------|----------|
| 1 | RW+0x08 | LD | 8 | | OK=0 (STATUS, reset) |
| 2 | RW+0x10 | LD | 8 | | OK=0 (CTRL, reset) |
| 3 | RW+0x02 | LD | 4 | | UNALIGNED (precedence) |
| 4 | RW+0x04 | LD | 8 | | UNALIGNED |
| 5 | RW+0x00 | LD | 4 | | DEVERR (E3) |
| 6 | RW+0x08 | LD | 1 | | DEVERR (E3) |
| 7 | RW+0x10 | ST | 4 | 0 | DEVERR (E3) |
| 8 | RW+0x00 | LD | 16 | | DEVERR (E3; LD128 is not 64-bit) |
| 9 | RW+0x00 | AMOADD | 8 | 1 | DEVERR (E4) |
| 10 | RW+0x10 | CAS | 8 | 0,1 | DEVERR (E4) |
| 11 | RW+0x20 | LD | 8 | | DEVERR (E1) |
| 12 | RW+0x28 | ST | 8 | 0 | DEVERR (E1) |
| 13 | RW+0xFFF8 | LD | 8 | | DEVERR (E1) |
| 14 | RW+0x00 | ST | 8 | 0 | DEVERR (E2) |
| 15 | RW+0x08 | ST | 8 | 0 | DEVERR (E2) |
| 16 | RW+0x18 | LD | 8 | | DEVERR (E2) |
| 17 | RW+0x00 | LD | 8 | | DEVERR (E6: QUEUE mode, depth 0) |
| 18 | RW+0x10 | ST | 8 | 0x4 | DEVERR (E5; CTRL still 0) |
| 19 | RW+0x10 | ST | 8 | 0x8000000000000001 | DEVERR (E5; CTRL still 0) |
| 20 | RW+0x00 | (p=false) LD | 8 | | no trap, no pop, retires (RNG-10) |
| 21 | RW+0x00 | (p=false) LD | 4 | | no trap (RNG-10) |
| 22 | RW+0x10 | ST/LD | 8 | 1;3;2;0 | each value stores OK and reads back exactly (RNG-11) |

### 11.2 S-1 — feed → pop script (QUEUE mode)

Feed: one EVENT of 1 word at cycle 5000, one EVENT of 3 words at cycle
5000, one EVENT of 2 words at cycle 20000. Words, in feed order:

    w1 = 0xD1CE00000000A001    w2 = 0xD1CE00000000A002
    w3 = 0xD1CE00000000A003    w4 = 0xD1CE00000000A004
    w5 = 0xD1CE00000000B001    w6 = 0xD1CE00000000B002

| step | action | expected |
|-----:|--------|----------|
| 1 | STATUS before cycle 5000 | 0 (RNG-18) |
| 2 | poll STATUS from before 5000 | first nonzero read is 4 — both records apply at one boundary, no intermediate depth is observable |
| 3 | STATUS again | 4 (RNG-03) |
| 4 | predicated-false DATA load | STATUS still 4 (RNG-10) |
| 5 | DATA ×4 | w1, w2, w3, w4 exactly (RNG-02); STATUS reads 3, 2, 1, 0 after each |
| 6 | WFI (no timer armed, IE off) | resumes at exactly cycle 20000: MFSR `cycle` = 20000, STATUS = 2 (RNG-21) |
| 7 | DATA ×2 | w5, w6 |

### 11.3 S-2 — SplitMix64 output table and mode script

Seed 0 (also the reset state), first eight outputs — normative:

| n | output |
|--:|--------|
| 1 | 0xE220A8397B1DCDAF |
| 2 | 0x6E789E6AA1B965F4 |
| 3 | 0x06C45D188009454F |
| 4 | 0xF88BB8A8724C81EC |
| 5 | 0x1B39896A51A8749B |
| 6 | 0x53CB9F0C747EA2EA |
| 7 | 0x2C829ABE1F4532E1 |
| 8 | 0xC584133AC916AB3C |

Seed 0x123456789ABCDEF0, first four outputs:

| n | output |
|--:|--------|
| 1 | 0x161922C645CE50E8 |
| 2 | 0xAD760CAFA1697B60 |
| 3 | 0x3501FF44902CA50D |
| 4 | 0x417CB9A826D831DF |

Script (from reset; exercises RNG-13..17):

| step | action | expected |
|-----:|--------|----------|
| 1 | ST SEED = 0 (in QUEUE mode); ST CTRL = 1 | no trap (RNG-14) |
| 2 | DATA ×3 | seed-0 outputs 1–3 |
| 3 | ST CTRL = 0; ST CTRL = 1 | no trap |
| 4 | DATA | seed-0 output 4 (RNG-15: no restart) |
| 5 | STATUS | unchanged by every pop above (RNG-16) |
| 6 | ST SEED = 0x123456789ABCDEF0; DATA ×2 | that seed's outputs 1–2 (restart) |
| 7 | ST SEED = 0; DATA | 0xE220A8397B1DCDAF (RNG-13) |

### 11.4 V-B — overflow / truncation vector (RNG-19, RNG-R2)

Queue depth 254 (e.g. after S-1-style feeds totalling 254 words, none
popped). One arrival event carries N = 4 words:

    0x1111111111111111  0x2222222222222222
    0x3333333333333333  0x4444444444444444

Accepted = min(4, 256 − 254) = 2. Expected:

- STATUS reads 256 afterward; the last two pops of a full drain return
  0x1111111111111111 then 0x2222222222222222; the 0x3333… and 0x4444…
  words are never observable.
- The recorded EVENT payload is exactly these 16 bytes (trace.md §4.6
  framing around them):

      11 11 11 11 11 11 11 11 22 22 22 22 22 22 22 22

- A further arrival at depth 256 (any N) enqueues nothing and produces
  **no EVENT record**; STATUS stays 256.

### 11.5 V-T — reference device table with the RNG record (byte-exact)

The reference emulator writes exactly these 456 bytes at
`[0x0800, 0x09C8)` (and zeros in `[0x09C8, 0x1000)`): boot.md V1's
header and first four device records with `device_count` = 6, the
type-7 rng record fifth, and the type-5 timer record sixth
(devspec/timer.md §8 — its vector V1-T is this same table; boot.md
itself is untouched).

```
00000800: 53 41 48 41 52 41 50 54 01 00 00 00 00 00 00 00
00000810: 01 00 00 00 00 00 00 00 01 00 00 00 00 00 00 00
00000820: 06 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00000830: 00 00 00 00 00 00 00 00 00 00 00 0f 00 00 00 00
00000840: 00 00 00 00 00 00 00 00 01 00 00 00 00 00 00 00
00000850: 00 00 00 0f 00 00 00 00 00 00 00 00 00 00 00 00
00000860: 00 00 01 00 00 00 00 00 00 00 00 10 00 00 00 00
00000870: 00 00 00 01 00 00 00 00 00 00 00 00 00 00 00 00
00000880: 00 00 00 00 00 00 00 00 02 00 00 00 00 00 00 00
00000890: 00 00 01 0f 00 00 00 00 00 00 00 00 00 00 00 00
000008a0: 00 00 01 00 00 00 00 00 00 00 00 00 00 00 00 00
000008b0: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
000008c0: 00 00 00 00 00 00 00 00 03 00 00 00 00 00 00 00
000008d0: 00 00 02 0f 00 00 00 00 00 00 00 00 00 00 00 00
000008e0: 00 00 01 00 00 00 00 00 00 00 00 00 00 00 00 00
000008f0: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00000900: 00 00 00 00 00 00 00 00 04 00 00 00 00 00 00 00
00000910: 00 00 03 0f 00 00 00 00 00 00 00 00 00 00 00 00
00000920: 00 00 03 00 00 00 00 00 52 54 00 12 34 56 00 00
00000930: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00000940: 00 00 00 00 00 00 00 00 07 00 00 00 00 00 00 00
00000950: 00 00 08 0f 00 00 00 00 00 00 00 00 00 00 00 00
00000960: 00 00 01 00 00 00 00 00 00 00 00 00 00 00 00 00
00000970: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00000980: 00 00 00 00 00 00 00 00 05 00 00 00 00 00 00 00
00000990: 00 00 06 0f 00 00 00 00 00 00 00 00 00 00 00 00
000009a0: 00 00 01 00 00 00 00 00 00 00 00 00 00 00 00 00
000009b0: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
000009c0: 00 00 00 00 00 00 00 00
```

Decode of the appended record (table offset 0x148, PA 0x0948):

```
expect dev[4].type      = 7
expect dev[4].base      = 0x0F080000
expect dev[4].size      = 0x10000
expect dev[4].params[0] = 0
expect dev[4].params[1] = 0
expect dev[4].params[2] = 0
expect dev[4].params[3] = 0
expect table_end_pa     = 0x09C8
```

### 11.6 S-3 — interrupt script (RNG-20/21)

Feed: 2 words at cycle 5000, 1 word at cycle 30000. Guest has a trap
handler counting EXTINT deliveries; status.IE = 1 throughout.

| step | action | expected |
|-----:|--------|----------|
| 1 | poll STATUS to 2 (CTRL.IE = 0) | no EXTINT delivered while depth > 0 |
| 2 | ST CTRL = 2 (IE on, QUEUE mode) | EXTINT delivers before the next instruction |
| 3 | handler: STATUS-then-pop drain (§3), IRET | exactly one delivery; the two words pop in order |
| 4 | after drain: depth 0, IE still 1 | no further delivery (level deasserted) |
| 5 | ST CTRL = 0; WFI | resumes at exactly cycle 30000 (RNG-21, IE-independent wake); STATUS = 1; no EXTINT |

## 12. Cross-document dependencies

| dependency | resolution |
|---|---|
| devspec/trace.md §4.6 | RNG arrival payload = N little-endian u64 words, 1 ≤ N ≤ 128, recorded = accepted prefix, zero-accepted records nothing — owned there, constrained here in §7.2 |
| devspec/trace.md §3.3, §5.2, §5.4 | boundary application order, replay application, model-recomputed acceptance |
| devspec/boot.md §3.5, §4.2, §4.3 | 64-byte device record layout; positional skip of unknown type 7 by old guests; params zero-means-v1 growth rule |
| devspec/input.md §4 | the shared queue model this device instantiates (depth/drain/visibility); the empty-read divergence is deliberate (§4.1 rule 4) |
| devspec/nic.md §5.2, §7.1, §7.3 | check-precedence chain; cycle-assignment rules 1–2/4–5; replay isolation phrasing |
| ISA-SPEC §3.2, §4, §5.4, §7.1, §9.2 | predication no-fault, faulting-access no-effect, atomics-to-device DEVERR, DEVERR cause 12, device-space ordering (all frozen) |
| PLATFORM-SPEC §1, §3 | 64-bit register access rule; EXTINT OR (frozen) |
