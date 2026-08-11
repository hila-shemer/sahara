# Sahara TIMER Device — Detailed Specification

**Version 1.0-draft.** Companion to ISA-SPEC.md and PLATFORM-SPEC.md.
Where this document restates a value fixed by a frozen spec, the frozen
spec wins on any discrepancy; restated values are marked with their
source. Non-normative material appears in indented *Note:* lines.
Everything else is normative.

Ownership (per the devspec ownership matrix):

- **This document owns:** the timer register window and its semantics
  (COUNT/PERIOD/STATUS/ACK), the device-table type-5 record's parameters
  and reference defaults, and the TMR conformance clauses.
- **Frozen elsewhere, restated here (source marked):** the DEVERR
  access rules for register windows (PLATFORM-SPEC §1), the per-device
  EXTINT pending OR (PLATFORM-SPEC §3), the inter-instruction boundary
  order (devspec/trace.md §3.3), the architectural cycle counter
  (ISA-SPEC §4, sreg 8 per §2.3), and WFI (ISA-SPEC §7.6).
- **Referenced, never defined here:** the device-table byte layout
  (devspec/boot.md §3), EVENT record framing and payload ownership
  (devspec/trace.md §2.3.5, §4), the devspec/INDEX.md ownership matrix
  slot.

---

## 1. Overview and discovery

The timer is a periodic-tick accelerator: a free-running MMIO view of
the architectural cycle counter plus one guest-programmed periodic
compare that raises the external interrupt through the standard
per-device pending OR (PLATFORM-SPEC §3 — no interrupt controller).
It exists so the OS scheduling tick has a compare source of its own:
sreg `timecmp` (sreg 9, ISA-SPEC §2.3) stays the kernel's exclusive
precision instrument (single-stepping, one-shot deadlines) and this
device carries the tick. The two are fully independent (§4.6).

The whole device is a pure function of guest register writes (and their
DEVW cycles) and the architectural cycle counter. It has no host-side
input, no EVENT payload, no META configuration, and no GUI presence:
live, headless, and replay behavior are identical by construction (§5).

Device state is exactly `{period : u64, next_fire : u128}`. Everything
else a guest can observe (COUNT, STATUS) is derived at read time.

*Note: kernel adoption story, for a later work order — scan the device
table for type 5, write PERIOD = the tick quantum, read STATUS and store
ACK = 1 in the EXTINT handler; sreg timecmp is thereby freed for the
debugger's timecmp-arithmetic single-stepping.*

The guest discovers the timer from the device table (layout owned by
devspec/boot.md §3): a device record with `type = 5`, `base` = the
control-window PA, `size` = the window size, `params[0..3] = 0`.
Guests must ignore, not fault on, nonzero values in `params` (boot.md
§4.4); later revisions may assign meanings only under boot.md §4.3's
"0 = v1 behavior" rule. Old kernels skip the unknown type-5 record
positionally (boot.md §4.2); the table `version` does not change.

Reference platform defaults (the device table is authoritative):

| item | value |
|------|-------|
| control window base | PA 0x0F06_0000 — reference default fixed by this document |
| control window size | 64 KB (0x1_0000 bytes) |
| device-table type | 5 |
| device-table position | index 5, after the type-7 rng record (the wave's settled table order, §8 / rng.md §11.5) — frozen once assigned |
| params | `[0, 0, 0, 0]` |

The window is carved from what boot.md §3.4 declared a hole on the
4-device platform (`[0x0F06_0000, 0x1000_0000)`); with the timer
present the hole starts at 0x0F07_0000. The window is device space in
the sense of ISA-SPEC §9.2.

---

## 2. Register window and access model

Base = the device-table `base`. Restated from PLATFORM-SPEC §1
(frozen): registers are 64 bits, naturally aligned, and must be
accessed with 64-bit loads and stores; any other size traps `DEVERR`
(cause 12) with `baddr` = the effective address.

| off  | reg    | access | semantics |
|-----:|--------|--------|-----------|
| 0x00 | COUNT  | R      | low 64 bits of the architectural cycle counter at the inter-instruction boundary immediately preceding the load (§4.1). No read side effect. |
| 0x08 | PERIOD | RW     | read: last value written (0 at reset). Write N > 0: arm, `next_fire = W + N` where W is the store's DEVW cycle (§4.2). Write 0: disarm. A rewrite while armed re-arms fresh from the new W. |
| 0x10 | STATUS | R      | bit 0 = derived pending (§4.3), evaluated at the boundary immediately preceding the load; bits 63:1 read 0. No read side effect. |
| 0x18 | ACK    | W      | stored value must be exactly 1 (§4.4). Pending: phase-locked advance of `next_fire`. Armed-but-not-pending or disarmed: no-op. Any other value: DEVERR, no state change. |

Numbered access rules (the project loud-failure policy):

1. A load (any width) from ACK traps `DEVERR`, `baddr` = ea.
2. A store (any width) to COUNT or STATUS traps `DEVERR`, `baddr` = ea.
3. An 8-byte-aligned 64-bit access, either direction, to a window
   offset not in {0x00, 0x08, 0x10, 0x18} traps `DEVERR` (there is no
   read-as-zero extension window on this device; contrast display.md
   §8 — see §6).
4. Any atomic (CAS, AMO*) anywhere in the window traps `DEVERR`
   (ISA-SPEC §5.4/§9.2, frozen; the window is device space).
5. A misaligned access traps `UNALIGNED` before any device semantics
   apply (ISA-SPEC §5.3); `DEVERR` checks are reached only by aligned
   accesses.
6. An instruction whose predicate evaluates false performs no device
   access and cannot trap (ISA-SPEC §3.2): a predicated-false store to
   ACK — legal value or not — retires in one cycle with no trap, no
   device effect, and no access record.

### 2.1 DEVERR catalog

Cause 12, `baddr` = the effective (virtual) address of the access. A
faulting access has no architectural or device effect (ISA-SPEC §4):
in particular a faulting ACK advances nothing and a faulting PERIOD
store re-arms nothing.

| # | condition | authority |
|---|-----------|-----------|
| E1 | 8-byte-aligned access (either direction) to a window offset not in {0x00, 0x08, 0x10, 0x18} | this spec |
| E2 | wrong direction on a listed offset: store to COUNT or STATUS, load from ACK | this spec |
| E3 | access with size ≠ 8 bytes anywhere in the window | PLATFORM-SPEC §1 (frozen) |
| E4 | any atomic (CAS/AMO) anywhere in the window | ISA-SPEC §5.4 (frozen) |
| E5 | ACK write with value ≠ 1 | this spec (loud-failure) |

### 2.2 Check precedence

For an access to the timer window, checks apply in this order, first
failure wins (the frozen chain, nic.md §5.2 pattern): predication (a
predicated-false access does nothing and cannot fault — no trap, no
record, 1 cycle) → translation and permission (PF_*/PERM_*) → natural
alignment (UNALIGNED) → atomic-to-device (E4) → size (E3) →
offset/direction (E1/E2) → value (E5). In particular a misaligned
sub-8-byte access traps UNALIGNED, not DEVERR.

Instruction fetch from the timer window traps DEVERR at the fetch (the
conservative reading used for every register window; boot.md BOOT-15
pattern, nic.md §5.2).

### 2.3 Reset

PERIOD = 0, `next_fire` = 0, pending false. A disarmed timer never
becomes pending (§4.3), so no source exists at cycle 0 and boot code
need not race to mask anything.

---

## 3. Arithmetic domain

PERIOD is a u64. `next_fire` lives in the **full cycle-counter
domain** — 128 bits, the width of sreg 8 (ISA-SPEC §2.3) — so `W + N`
(§4.2) and the ACK advance (§4.4) are exact. There are no mod-2^64
caveats anywhere in this specification. COUNT reads the low 64 bits of
the counter; STATUS bits 63:1 read 0.

---

## 4. Timing semantics

### 4.1 COUNT and the boundary-cycle rule

Every timer register access is evaluated against **the value of the
architectural cycle counter at the inter-instruction boundary
immediately preceding the accessing instruction** (boundary order per
devspec/trace.md §3.3, restated in §4.3 below). Because the counter
advances by exactly 1 per retired instruction and per trap delivery
(ISA-SPEC §4), that boundary value equals the cycle stamped into the
access's own MEMR/DEVW trace record.

- COUNT returns the low 64 bits of that boundary value.
- **Normative equivalence clause:** COUNT must equal the low 64 bits of
  what an `MFSR` of sreg 8 returns at the same program point (sreg 8 is
  already readable S+U, ISA-SPEC §2.3 — COUNT's justification is
  MMIO-side consistency, not a new capability). Two COUNT reads differ
  by exactly the retired-instruction/trap-delivery/WFI-jump cycle delta
  between them. Any observed divergence between the two read paths is a
  SPEC-ISSUES.md entry, never a silent fix.

### 4.2 Arming, disarm, rewrite

Let W be the cycle of the PERIOD store — the value stamped in that
store's DEVW record (observable, byte-pinned in traces).

- Store N > 0 to PERIOD: the timer is **armed**, `next_fire = W + N`.
- Store 0 to PERIOD: the timer is **disarmed**. Pending drops because
  it is derived (§4.3), with no further handshake.
- Store N' > 0 while already armed: re-arm fresh, `next_fire = W' + N'`
  from the new store's cycle W'. There is no reprogram fault and no
  arm/disarm state machine: on a deterministic single-CPU machine there
  is no race to outlaw.

PERIOD reads back the last value written, 0 at reset; a read never
changes state.

### 4.3 Derived pending and recognition

Pending is **derived, never stored**:

    pending(C) = (PERIOD > 0) and (C >= next_fire)

evaluated at inter-instruction boundaries in the frozen order of
devspec/trace.md §3.3: input events apply, **then device conditions
hold their boundary values, then interrupts are recognized** (ISA-SPEC
§7.5), then the next instruction executes. Consequences:

1. Pending first becomes true at the first boundary whose cycle
   satisfies `cycle >= next_fire`. With the timer as the only pending
   source, `status.IE = 1`, and the CPU not already in a handler, the
   EXTINT TRAP record's cycle is exactly `next_fire`.
2. The timer's contribution to the EXTINT level OR (PLATFORM-SPEC §3,
   frozen) is exactly `pending`. Standard level semantics: the handler
   must ACK (§4.4) or disarm before IRET or the interrupt re-delivers
   at the next boundary; masking with IE defers, never cancels.
3. **Single level, no overrun state.** However many periods elapse
   before software attends to the timer, `pending` is one bit and one
   level-high interrupt. A late handler computes elapsed periods
   itself: fire targets are always `W + m·N` (§4.4), so
   `(COUNT_read − W) / N` arithmetic is exact. No OVERRUN bit exists.
4. STATUS bit 0 returns `pending` evaluated at the boundary preceding
   the load; reading it has no side effect.

### 4.4 ACK: strict value, phase-locked advance

A store of value exactly 1 to ACK at DEVW cycle A:

- **Pending** (`pending(A)` true): `next_fire ← next_fire + k·PERIOD`
  for the smallest integer k ≥ 1 giving `next_fire > A`.
- **Armed but not yet pending, or disarmed:** no-op (idempotent; not a
  fault — an ACK racing a disarm has no meaning to attack).

A store of any value ≠ 1 traps DEVERR (E5) and changes nothing — the
NIC IRQ-ack strictness precedent (nic.md E5/E6, display.md IRQ_ACK).

The advance is **phase-locked to the arming cycle**: `next_fire` only
ever takes values `W + m·N`, so fire targets never accumulate handler
latency drift. If the handler ACKs within one period, k = 1. If k
periods elapsed, one ACK collapses them all and the next fire is the
first grid point strictly after A.

*Note: `pending(A)` true implies `A >= next_fire`, so
k = floor((A − next_fire) / PERIOD) + 1 — always well-defined.*

### 4.5 WFI

Restated from ISA-SPEC §7.6 (frozen): if no interrupt is pending, WFI
stalls and virtual time advances directly to the next cycle at which
one becomes pending; if no future event could make one pending, the
machine halts (deadlock is loud).

An **armed timer is such a future event**, and by §4.3 rule 1 its
pending first becomes true at cycle `next_fire`; therefore a WFI stall
whose earliest wake source is the armed timer resumes with
`cycle = next_fire` **exactly** — the instruction after the WFI (IE=0)
or the EXTINT delivery (IE=1) lands at that cycle. WFI with only the
timer armed never deadlock-halts. This is not a spec extension: the
frozen §7.6 text already quantifies over every future pending source;
this document only enumerates the timer as one.

*Note: the sreg-timer wake rule is different — a timecmp wake resumes
at T + 1 (the frozen §7.6 reading recorded in the emulators'
SPEC-ISSUES). The device timer follows the event-style
land-at-the-cycle rule because its pending derives at boundaries, and
TV-T4 pins it.*

### 4.6 sreg timecmp independence

None. sreg `timecmp` (cause 0, TIMER) and this device (cause 1,
EXTINT, via the OR) are fully independent compare sources over the
same architectural counter. Arming, firing, ACKing, or disarming
either has no effect on the other. When both become pending at the
same boundary, ISA-SPEC §7.5's fixed priority (frozen) applies for
free: TIMER delivers before EXTERNAL; draining one leaves the other
pending. TMR-19 pins the simultaneous case.

---

## 5. Determinism

Timer behavior is a **pure function of (the guest's PERIOD/ACK stores
with their DEVW cycles, the architectural cycle counter)**. Both
inputs are already deterministic (ISA-SPEC §4), so the timer needs no
event feed, no configuration, and no host anything:

1. **No EVENT payload exists for device type 5.** devspec/trace.md §4
   owns all EVENT payload encodings and defines none for type 5: an
   EVENT record whose device index resolves to a type-5 device record
   makes the trace malformed (trace.md §2.4 class 2, §4.5). Both
   reference emulators reject such a trace with a fatal error.
2. **No META keys.** PERIOD is guest-programmed; there is nothing to
   configure. The closed v1 META catalog (trace.md §2.3.7) is
   unchanged.
3. **Replay isolation holds trivially.** Replay reconstructs the timer
   from the replayed guest's own stores; there is nothing external to
   isolate from. live == headless == replay by construction, and
   record→replay byte identity (trace.md §5.2/§5.3) follows from the
   general rule with no timer-specific machinery.
4. **No GUI presence.** There is no live path, no feed path, and no
   host timestamping for this device.

---

## 6. Reserved offsets and extension rules

Offsets 0x20 through 0xFFF8 (8-byte steps; every unlisted offset in
the window) are **E1: DEVERR**, both directions. Unlike the display's
reserved extension window (display.md §8, read-0/write-ignored —
frozen for that device by PLATFORM-SPEC §4), the timer's unlisted
offsets fault loudly; a v1 guest touching them is buggy and hears so.

Future revisions (display.md §8 pattern):

1. May define new registers only in 0x20+ and only behind a
   CAPS-style discovery mechanism defined at that time; every future
   feature must be opt-in and inert until enabled.
2. May never repurpose or alter the semantics of offsets
   0x00–0x18, the E1–E5 catalog for v1 offsets, or the §4 timing
   rules for guests that have enabled nothing.
3. May assign device-table `params` meanings only under boot.md §4.3's
   "0 = v1 behavior" rule.

---

## 7. Conformance requirements

Numbered, testable. "traps DEVERR" always also asserts the no-effect
rule (ISA-SPEC §4: device and architectural state unchanged by the
faulting access). These feed CONFORMANCE.md group C7 via
devspec/CONFORMANCE-DELTA.md, except TMR-20/TMR-21 (reference
implementation).

**Registers and errors**

- **TMR-01** Reset state: PERIOD reads 0, STATUS reads 0, and no
  timer interrupt ever becomes pending before the first arming store.
- **TMR-02** COUNT read rule (§4.1): two COUNT reads return values
  differing by exactly the inter-instruction cycle delta between them,
  and COUNT equals an adjacent `MFSR` sreg-8 read (low 64 bits) modulo
  the known delta between the two instructions. Trace-level shape:
  every COUNT MEMR record's value equals its own record's cycle field.
- **TMR-03** A PERIOD store of N > 0 at DEVW cycle W arms with
  `next_fire = W + N`: the first fire is observable at exactly W + N
  (recognition per §4.3 rule 1).
- **TMR-04** A PERIOD store of 0 disarms; STATUS bit 0 reads 0 at the
  next boundary and no further fire occurs, with no ACK required.
- **TMR-05** PERIOD reads back the last value written (0 at reset),
  unchanged by fires, ACKs, and STATUS/COUNT reads.
- **TMR-06** A PERIOD store of N' > 0 while armed re-arms fresh:
  `next_fire = W' + N'` from the new store's cycle, the old target
  dead, no fault.
- **TMR-07** STATUS returns bit 0 = pending evaluated at the boundary
  preceding the load, bits 63:1 = 0, and reading it changes nothing
  (two back-to-back STATUS reads with no boundary-crossing state
  change return equal values).
- **TMR-08** ACK = 1 while pending advances `next_fire` by the
  smallest k ≥ 1 periods giving `next_fire > A` (A = the ACK store's
  DEVW cycle); the subsequent fire lands on the original `W + m·N`
  grid (§4.4).
- **TMR-09** ACK = 1 while armed-but-not-pending or disarmed is a
  no-op: no fault, no state change (`next_fire` and PERIOD unchanged).
- **TMR-10** ACK with any value ≠ 1 traps DEVERR (E5) with no state
  change: STATUS and PERIOD read the same before and after, and the
  fire schedule is unaltered.
- **TMR-11** An 8-byte-aligned 64-bit access to any unlisted window
  offset (e.g. 0x20, 0xFFF8) traps DEVERR (E1), both directions.
- **TMR-12** A 64-bit store to COUNT or STATUS, and a 64-bit load from
  ACK, trap DEVERR (E2).
- **TMR-13** An access of size 1, 2, 4, or 16 bytes anywhere in the
  window (aligned) traps DEVERR (E3), listed offsets included.
- **TMR-14** Every atomic (CAS, AMO*) targeting the window traps
  DEVERR (E4) and leaves no access record.
- **TMR-15** Precedence (§2.2): a misaligned sub-8-byte access to the
  window traps UNALIGNED, not DEVERR; a predicated-false access —
  including an ACK store with an illegal value — retires in one cycle
  with no trap, no device effect, and no access record.

**Pending and interrupts**

- **TMR-16** The timer's EXTINT contribution is level-triggered
  pending exactly per §4.3: with IE = 1 it delivers at the first
  boundary with `cycle >= next_fire` (EXTINT, cause 1); a handler that
  returns without ACK or disarm re-traps at the boundary after its
  IRET; ACK or disarm before IRET ends delivery.
- **TMR-17** Pending is a single level regardless of elapsed periods:
  an interrupt masked or unserviced across k > 1 periods delivers
  exactly once when unmasked/serviced, and one ACK = 1 clears it (with
  the §4.4 collapse).
- **TMR-18** WFI with the armed timer as the earliest wake source
  wakes at exactly `next_fire`: the post-WFI instruction (IE = 0) or
  the EXTINT delivery (IE = 1) is stamped `cycle = next_fire`. An
  armed timer counts as a future event for §7.6's deadlock analysis:
  WFI with only the timer armed never deadlock-halts.
- **TMR-19** timecmp independence (§4.6): with sreg timecmp and the
  device armed for the same cycle, TIMER (cause 0) delivers before
  EXTINT (cause 1); disarming timecmp leaves the device pending, and
  vice versa.

**Determinism (reference implementation)**

- **TMR-20** No EVENT payload: an EVENT record whose device index
  resolves to a type-5 record is a malformed trace (trace.md §2.4
  class 2); both reference emulators refuse it with a fatal error.
- **TMR-21** Record→replay byte identity: replaying any recorded run
  that exercises the timer reproduces every post-META record
  byte-identically (trace.md §5.2/§5.3) with no timer-specific replay
  input.

---

## 8. Test vectors

TB = timer control window base (reference: 0x0F06_0000). All loads and
stores 64-bit unless a size is given. "W", "A" name DEVW cycles as in
§4.

### TV-T1 — access matrix (§2; TMR-10..15 plus each legal access)

Machine state: reset defaults, supervisor, MMU off, timer disarmed.
Rows execute in order. `OK[=v]` = succeeds (load returns v); `DEVERR` =
trap cause 12, baddr = address; `UNALIGNED` = trap cause 9.

| # | address | op | size | value | expected |
|--:|---------|----|-----:|-------|----------|
| 1 | TB+0x00 | LD | 8 | | OK (= the boundary cycle, TMR-02) |
| 2 | TB+0x08 | LD | 8 | | OK=0 (reset) |
| 3 | TB+0x10 | LD | 8 | | OK=0 |
| 4 | TB+0x18 | LD | 8 | | DEVERR (E2) |
| 5 | TB+0x00 | ST | 8 | 5 | DEVERR (E2) |
| 6 | TB+0x10 | ST | 8 | 0 | DEVERR (E2) |
| 7 | TB+0x20 | LD | 8 | | DEVERR (E1) |
| 8 | TB+0x20 | ST | 8 | 0 | DEVERR (E1) |
| 9 | TB+0xFFF8 | LD | 8 | | DEVERR (E1) |
| 10 | TB+0x00 | LD | 4 | | DEVERR (E3; 4-aligned, so not UNALIGNED) |
| 11 | TB+0x00 | LD | 2 | | DEVERR (E3) |
| 12 | TB+0x00 | LD | 1 | | DEVERR (E3) |
| 13 | TB+0x00 | LD | 16 | | DEVERR (E3; TB is 64 KB-aligned, so 16-aligned) |
| 14 | TB+0x08 | ST | 4 | 1 | DEVERR (E3) |
| 15 | TB+0x04 | LD | 8 | | UNALIGNED (precedence §2.2) |
| 16 | TB+0x01 | LD | 2 | | UNALIGNED |
| 17 | TB+0x00 | AMOADD | 8 | 1 | DEVERR (E4) |
| 18 | TB+0x08 | CAS | 8 | | DEVERR (E4) |
| 19 | TB+0x18 | ST | 8 | 0 | DEVERR (E5) |
| 20 | TB+0x18 | ST | 8 | 2 | DEVERR (E5) |
| 21 | TB+0x18 | ST | 8 | 0x8000000000000001 | DEVERR (E5) |
| 22 | TB+0x08 | ST | 8 | 100 | OK (arms; W = this store's cycle) |
| 23 | TB+0x08 | LD | 8 | | OK=100 (TMR-05) |
| 24 | TB+0x18 | ST | 8 | 1 | OK (no-op: armed, not yet pending — TMR-09) |
| 25 | TB+0x08 | ST | 8 | 0 | OK (disarms — TMR-04) |
| 26 | TB+0x08 | LD | 8 | | OK=0 |
| 27 | TB+0x18 | ST | 8 | 1 | OK (no-op: disarmed — TMR-09) |
| 28 | (p, p=0) TB+0x18 | ST | 8 | 7 | no trap, no record, 1 cycle (TMR-15) |

After every DEVERR row, PERIOD and STATUS read back unchanged
(no-effect rule).

### TV-T2 — tick script (§4.2–§4.4; TMR-03/08/16/17)

N = 100. Steps in order; "fire m" = the boundary at which pending
first becomes true for grid point m.

| step | action | expected |
|-----:|--------|----------|
| 1 | LD TB+0x00 → c | returns the reading instruction's cycle c |
| 2 | ST TB+0x08 = 100 as the immediately-next instruction | W = c + 1; `next_fire` = W + 100 |
| 3 | run with IE = 1 | EXTINT TRAP at exactly W + 100 (fire 1) |
| 4 | handler: LD TB+0x10 | 1 (pending) |
| 5 | handler: ST TB+0x18 = 1 at cycle A₁ (A₁ − W < 200) | k = 1; `next_fire` = W + 200 |
| 6 | repeat | fires 2, 3 at exactly W + 200, W + 300, each ACKed with k = 1 |
| 7 | after ACK of fire 3: IE = 0; busy-wait > 250 cycles; IE = 1 | exactly ONE EXTINT delivers after IE is re-enabled (TMR-17), at the first boundary after the IE-setting instruction |
| 8 | handler: ST TB+0x18 = 1 at cycle A₄ (A₄ ≥ W + 600 say) | one ACK collapses the elapsed periods: `next_fire` = the first grid point W + 100·m > A₄, with k = ⌊(A₄ − (W + 400))/100⌋ + 1 |
| 9 | run | fire 5 at exactly W + 100·m₅ where m₅ = ⌊(A₄ − W)/100⌋ + 1 — back on the arming grid, drift-free (TMR-08) |
| 10 | ST TB+0x08 = 0 | disarmed; no further fires; STATUS reads 0 |

### TV-T3 — device table (type-5 record and the V1-T reference table)

The 64-byte type-5 record, boot.md §3.5 layout, at its position in the
reference table (`<PA:8 hex>: <bytes>` format, boot.md conventions):

```
00000988: 05 00 00 00 00 00 00 00 00 00 06 0f 00 00 00 00
00000998: 00 00 00 00 00 00 00 00 00 00 01 00 00 00 00 00
000009a8: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
000009b8: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
```

**V1-T** — the 6-device reference platform table, byte-exact: header
40 + one RAM region 32 + 6·64 = **456 encoded bytes** at
`[0x0800, 0x09C8)`, zeros in `[0x09C8, 0x1000)`. Identical to boot.md
vector V1 except `device_count` = 6 (byte at 0x0820) and the two
appended wave records: the type-7 rng record fifth (devspec/rng.md §11.5
— its vector V-T is this same table) and the type-5 timer record sixth.
boot.md's V1 remains the normative vector for the 4-device table; V1-T
is normative for a platform carrying the wave devices.

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

Machine-consumable expectations (boot.md §7 format):

```
expect device_count     = 6
expect dev[5].type      = 5
expect dev[5].base      = 0x0F060000
expect dev[5].size      = 0x10000
expect dev[5].params[0] = 0
expect dev[5].params[1] = 0
expect dev[5].params[2] = 0
expect dev[5].params[3] = 0
expect table_end_pa     = 0x09C8
```

### TV-T4 — WFI wake-cycle script (§4.5; TMR-18)

IE = 0 throughout (wakes continue in-line, so the cycles are naked in
the EXEC stream). N = 50.

| step | action | expected |
|-----:|--------|----------|
| 1 | LD TB+0x00 → c; ST TB+0x08 = 50 next | W = c + 1; `next_fire` = W + 50 |
| 2 | WFI (before W + 50) | stalls; wakes with cycle = W + 50 exactly |
| 3 | LD TB+0x00 as the first post-WFI instruction | returns exactly W + 50 |
| 4 | LD TB+0x10 | 1 (pending, level held) |
| 5 | ST TB+0x18 = 1 at cycle A (W + 50 < A < W + 100) | k = 1; `next_fire` = W + 100 |
| 6 | WFI | wakes with cycle = W + 100 exactly |
| 7 | LD TB+0x00 | returns exactly W + 100 |
| 8 | ST TB+0x08 = 0, then WFI with nothing else armed | deadlock-halt (ISA §7.6) — the disarmed timer is NOT a future event |

---

## 9. Cross-document dependencies

| dependency | resolution |
|---|---|
| devspec/trace.md §4 | owns EVENT payload encodings; carries the type-5 line: no EVENT payload is defined for type 5, an EVENT record naming a type-5 device is malformed (§2.4 class 2). This document defines no payload. |
| devspec/trace.md §3.3 | boundary order (events → device phase → interrupt recognition → instruction); §4.3's evaluation points restate it |
| devspec/boot.md §3.5, §4.2–§4.4 | device record layout, unknown-type skip, params zero-discipline; the type-5 record's field values are §1 of this document |
| devspec/boot.md §3.4 / V9 | the pre-timer hole `[0x0F06_0000, 0x1000_0000)`; with the timer present the hole is `[0x0F07_0000, 0x1000_0000)` and boot.md's V9 vector addresses inside the timer window no longer trap as hole accesses (V9's PA 0x0F06_0000 becomes a legal-window E3/E1 surface; the hole behavior moves to 0x0F07_0000) |
| ISA-SPEC §2.3, §4 | sreg 8 cycle counter, 1-per-retire/delivery advance; COUNT's §4.1 equivalence clause |
| ISA-SPEC §7.5 | recognition between instructions, TIMER-before-EXTERNAL priority (§4.6) |
| ISA-SPEC §7.6 | WFI stall/wake/deadlock rule; §4.5 enumerates the armed timer as a wake source |
| PLATFORM-SPEC §1, §3 | 64-bit-only register windows and DEVERR; the EXTINT per-device OR |
