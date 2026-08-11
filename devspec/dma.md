# Sahara DMA Engine — Detailed Device Specification

**Version 1.0-draft.** Companion to ISA-SPEC.md and PLATFORM-SPEC.md. The
DMA engine is the first device of the accelerator wave: a deliberately
small memory-to-memory offload engine (COPY and FILL) whose **descriptor
format is the lingua franca** later descriptor-consuming accelerators
reuse. Where this document restates a value fixed by a frozen spec, the
frozen spec wins on any discrepancy; restated values are marked with
their source. Non-normative material appears in indented *Note:* lines.
Everything else is normative.

Ownership (per the devspec ownership matrix):

- **This document owns:** the 64-byte descriptor format and its
  versioning/reuse contract, the opcode registry shared by future
  descriptor-consuming devices (§4), the DMA register window and its
  access rules (§2–§3), the deterministic cycle-cost model (§6), and the
  STATUS code space (§3.2).
- **Restated, owned elsewhere:** DEVERR semantics and the 64-bit-only
  register access rule — PLATFORM-SPEC §1 (frozen); inter-instruction
  boundary ordering — devspec/trace.md §3.3; device table layout —
  devspec/boot.md §3; virtual-time rules — ISA-SPEC §4.
- **Referenced, never defined here:** trace record formats
  (devspec/trace.md §2), the EVENT payload catalog (devspec/trace.md §4
  — the DMA engine has **no entry** there and never will in v1: it is
  not an EVENT-fed device), RAM region semantics (devspec/boot.md §3.4),
  the WFI stall rules (ISA-SPEC §7.6 as elaborated by the frozen wake
  rules — see §7.5).

---

## 1. Overview and discovery

The DMA engine is a memory-to-memory offload accelerator: the guest
builds a 64-byte descriptor in ordinary RAM, writes its physical address
to a doorbell register, and the engine performs the described COPY or
FILL after a spec-pinned, deterministic number of cycles. Completion is
observable by polling STATUS, by reading COMP_CYCLE, or — when the
descriptor asks for it — by a level-triggered EXTINT contribution.

The engine is an *optional accelerator*, not complex hardware: it has no
queue (one job in flight), no channels, no scatter/gather in v1, and no
interaction with any host resource. A DMA job is a pure function of
(descriptor bytes latched at the doorbell, RAM contents at the
completion boundary, doorbell cycle) — §7 makes this the load-bearing
determinism axiom.

The guest discovers the engine from the device table (layout owned by
devspec/boot.md §3.5): a device record with `type = 6`, whose `base` is
the register window physical address and `size` the window length.
`params[0]`–`params[3]` are 0 in v1; per boot.md §4.4 guests must ignore
(not fault on) nonzero values in params slots they do not use. All
operating limits are spec-pinned and surfaced in CAPS (§3.1), not in the
table.

Guests must locate the engine by **scanning device records for type
code 6**, never by table position: record order is unspecified
(boot.md §3.5) and the engine's index among the device records is not
stable across platform revisions. No EVENT record ever names the DMA
engine, so nothing anywhere depends on its device-table index.

Reference platform defaults (fixed by this document; the device table is
authoritative for base and size):

| item | value |
|------|-------|
| register window base | PA 0x0F07_0000 |
| register window size | 64 KB (0x1_0000 bytes) |
| K (fixed job overhead) | 8 cycles |
| W (transfer width) | 8 bytes/cycle |
| LEN_MAX | 2^24 bytes (16 MB) |
| CAPS value (§3.1 encoding) | 0x0000_0000_1808_0301 |

The window sits between the timer window at 0x0F06_0000
(devspec/timer.md §1) and the RNG window at 0x0F08_0000 (devspec/rng.md
§1) — the accelerator wave carved up the old post-NIC hole completely,
so the contiguous device run now ends at 0x0F09_0000. What remains —
[0x0F09_0000, 0x1000_0000) — is an undeclared hole and traps `DEVERR`
per boot.md BOOT-15. The window base is 64 KB aligned (boot.md §3.5).
The whole window is device space in the sense of ISA-SPEC §9.2: stores
to it are release fences, loads/stores are mutually program-ordered, and
atomics trap `DEVERR`.

> *Note: the OS is expected to adopt the DMA engine for bulk copies
> (page zeroing, buffer moves) once the accelerator wave integrates; a
> guest LD/ST loop moves at best 16 bytes per 2 cycles of loop body,
> while the engine moves 8 bytes per cycle with an 8-cycle setup — a
> genuine ~3× win on large copies without being magic. Nothing in this
> document requires any OS change; software that ignores type-6 records
> keeps working unmodified.*

---

## 2. Register window access model

Restated from PLATFORM-SPEC §1 (frozen): device-window registers are 64
bits wide, naturally aligned, and must be accessed with 64-bit loads and
stores; any other access size traps `DEVERR` with `baddr` = the
effective address. This document adds the following normative access
rules for the DMA register window, per the project loud-failure policy:

1. A load (any width) from a write-only register (DOORBELL, IRQ_ACK)
   traps `DEVERR`, `baddr` = ea.
2. A store (any width) to a read-only register (CAPS, STATUS,
   COMP_CYCLE) traps `DEVERR`, `baddr` = ea.
3. An aligned 64-bit access — load **or** store — at any window offset
   not in {0x00, 0x08, 0x10, 0x18, 0x20} traps `DEVERR`, `baddr` = ea.
   Unlike the display's reserved extension window (read-0/write-ignore,
   frozen by PLATFORM-SPEC §4), the DMA window has **no inert reserved
   region**: v1 offsets outside the map fail loudly in both directions,
   and future registers are discovered through CAPS, never by probing
   (§9).
4. Any atomic operation (CAS, AMO*) targeting the window traps `DEVERR`
   (ISA-SPEC §5.4 / §9.2).
5. A misaligned access traps `UNALIGNED` before any device semantics
   apply (ISA-SPEC §5.3); `DEVERR` checks are reached only by aligned
   accesses.
6. An instruction whose predicate evaluates false performs no device
   access and cannot trap (ISA-SPEC §3.2).
7. Instruction fetch from the window traps `DEVERR` at the fetch (the
   conservative platform-wide reading recorded in devspec
   SPEC-ISSUES #2).
8. A faulting access has no architectural or device effect (ISA-SPEC
   §4): it changes no register, submits nothing, clears nothing, and
   leaves no access record in the trace.

Register map (offsets from the window base):

| off | reg | access | semantics |
|----:|-----|--------|-----------|
| 0x00 | CAPS | R | capability/limits word, §3.1; constant 0x1808_0301 in v1 |
| 0x08 | STATUS | R | job state code, §3.2; bits 63:8 read 0 |
| 0x10 | DOORBELL | W | descriptor PA; the single submission point (§5) |
| 0x18 | IRQ_ACK | W | value 1 clears the engine's EXTINT pending level; any other value traps `DEVERR` (§3.4) |
| 0x20 | COMP_CYCLE | R | terminal-state cycle of the most recent job, §3.5; 0 after reset |

There is deliberately **no CTRL register** (interrupt policy is
per-descriptor, OP bit 8 — §4.1) and **no DESC_PA readback register**
(the guest wrote the PA; it knows it).

### 2.1 DEVERR catalog and check precedence

All of the following trap `DEVERR` (cause 12) with `baddr` = the
offending effective address; a faulting access has no effect:

| # | condition | source |
|--:|---|---|
| E1 | access anywhere in the window with size ≠ 8 bytes | PLATFORM-SPEC §1 (frozen) |
| E2 | 8-byte aligned access (either direction) at an offset not in {0x00, 0x08, 0x10, 0x18, 0x20} | this spec (loud-failure) |
| E3 | load of DOORBELL or IRQ_ACK | this spec |
| E4 | store to CAPS, STATUS, or COMP_CYCLE | this spec |
| E5 | DOORBELL store while STATUS = BUSY | this spec (state-dependent, NIC empty-pop precedent) |
| E6 | DOORBELL store whose value (the descriptor PA) is not 64-byte aligned | this spec |
| E7 | DOORBELL store where [PA, PA+64) is not wholly inside a declared RAM region | this spec |
| E8 | IRQ_ACK store with value ≠ 1 | this spec |
| E9 | any atomic (CAS/AMO) anywhere in the window | ISA-SPEC §5.4 (frozen) |

Check precedence for an access to the window, first failure wins
(the NIC chain of devspec/nic.md §5.2, copied verbatim):
predication (a predicated-false access does nothing and cannot fault) →
translation and permission (PF_*/PERM_*) → natural alignment
(UNALIGNED) → atomic-to-device (E9) → size (E1) → offset/direction
(E2–E4) → value/state (E5 → E6 → E7 for the doorbell; E8 for IRQ_ACK).

A faulting DOORBELL store (E5–E7) submits nothing and leaves the
in-flight job, STATUS, COMP_CYCLE, and the pending level untouched.
Descriptor **content** problems are not in this catalog at all: they
never trap (§5.3, §8).

---

## 3. Register semantics in detail

### 3.1 CAPS (0x00, read-only)

Constant capability/limits word; mirrors the §1 reference defaults so a
guest need parse nothing but the device table and this register:

| bits | field | v1 value |
|---|---|---|
| 7:0 | descriptor-format major version | 1 |
| 15:8 | log2 W (bytes per cycle) | 3 |
| 23:16 | K (fixed job overhead, cycles) | 8 |
| 31:24 | log2 LEN_MAX | 24 |
| 63:32 | reserved, read 0 | 0 |

v1 value: `0x0000_0000_1808_0301`. The descriptor-format version in
bits 7:0 is the version of the §4 layout the engine consumes; §4.3
defines what a version bump means. Future capability bits appear only
in bits 63:32 and only accompanied by a revision of this document (§9).

### 3.2 STATUS (0x08, read-only)

Bits 7:0 are the state code of the most recent doorbell; bits 63:8 read
0. Reading STATUS has no side effect.

| code | name | meaning |
|---:|---|---|
| 0 | IDLE | no doorbell since reset |
| 1 | BUSY | a job is in flight (accepted, not yet completed) |
| 2 | DONE | the last job completed successfully |
| 3 | BAD_OP | descriptor opcode not assigned (§5.3) |
| 4 | BAD_FORMAT | reserved-MBZ violation in the descriptor (§5.3) |
| 5 | BAD_ALIGN | SRC/DST/LEN alignment violation (§5.3) |
| 6 | BAD_RANGE | LEN or address range violation (§5.3) |

STATUS is written **only** by a doorbell (to BUSY or straight to a
terminal error code) and by job completion (BUSY → DONE). IRQ_ACK never
touches STATUS. There is no way to reset STATUS to IDLE except machine
reset; IDLE means exactly "no doorbell yet".

A new DOORBELL store is legal from IDLE, DONE, and every error state
(3–6); only BUSY rejects it (E5). Software that lost track of the
engine's state recovers by polling STATUS until it leaves BUSY.

### 3.3 DOORBELL (0x10, write-only)

The stored 64-bit value is the physical address of a 64-byte descriptor
(§4). The store is the **single atomic submission point**: access
validation (E5–E7) happens at the store; on success the 64 descriptor
bytes are latched and content-validated synchronously (§5), all before
the store retires. One DEVW record — the store's own — marks the
submission in the trace; the descriptor read is a device-internal read
and emits **no MEMR records** (§7.2).

### 3.4 IRQ_ACK (0x18, write-only)

A store of value 1 clears the engine's EXTINT pending level. Clearing
an already-clear level is a no-op, not an error — this makes the ack
race-free: software may ack on any suspicion without first checking.
Any stored value other than 1 — including 0 — traps `DEVERR` (E8) and
clears nothing (loud-failure policy; the display's tolerated ack-0 is
not carried over into new devices). IRQ_ACK never changes STATUS or
COMP_CYCLE.

### 3.5 COMP_CYCLE (0x20, read-only)

The cycle at which the most recent job reached (or will reach) its
terminal state:

- After reset, before any doorbell: 0.
- Content-error job (§5.3): the doorbell store's cycle. Terminal
  immediately; COMP_CYCLE is exact history.
- Accepted job: `C_done` per §6. COMP_CYCLE is written **at the
  doorbell**, when `C_done` becomes determined; a read while STATUS =
  BUSY therefore returns the *scheduled* completion cycle. This is
  normative and deterministic — the schedule is pure arithmetic on the
  doorbell cycle — and gives polling software an exact deadline.

### 3.6 Reset state

STATUS = IDLE (0), COMP_CYCLE = 0, EXTINT pending level clear, no job
in flight. CAPS is constant. The engine holds no other guest-visible
state; latched descriptor fields (§5.2) are unobservable except through
the job they describe.

---

## 4. Descriptor format (owned here — the accelerator wave's lingua franca)

A descriptor is **64 bytes in ordinary RAM, 64-byte aligned**. All
fields are u64, little-endian. 64 bytes is the boot.md record grain:
descriptor arrays pack with no padding and never straddle the alignment
grain.

| off | field | v1 meaning |
|----:|-------|------------|
| 0 | OP | bits 7:0 opcode (§4.2); bit 8 IRQ_ON_COMPLETE; bits 63:9 reserved, MBZ |
| 8 | SRC | COPY: source PA. FILL: the 8-byte pattern itself, replicated over the destination |
| 16 | DST | destination PA |
| 24 | LEN | length in bytes; > 0, a multiple of 8, ≤ 2^24 |
| 32 | NEXT | reserved for v2 chaining; MBZ in v1 |
| 40 | — | reserved, MBZ |
| 48 | — | reserved, MBZ |
| 56 | — | reserved, MBZ |

**Alignment doctrine (normative).** SRC and DST must be 8-byte aligned
(COPY: both; FILL: DST only — the FILL SRC is a pattern, not an
address, and carries no alignment constraint); LEN must be a positive
multiple of 8. Bulk offload is the accelerator's job; byte-granular
edges are three guest instructions. The doctrine keeps the datapath
uniform (whole u64 words), the cost model integer-exact (LEN/8 with no
ceiling), and FILL exact (whole patterns, never a torn replica).

**Latching rule (normative).** The 64 descriptor bytes are read once,
at the doorbell store, and latched. Guest stores to the descriptor
bytes after the doorbell — including immediately, in the very next
instruction — have **no effect** on the in-flight job. (Source *data*
is the opposite: sampled at completion, §5.4.)

**IRQ_ON_COMPLETE (OP bit 8).** When bit 8 of the latched OP field is
1, the engine raises its EXTINT pending level when the job reaches its
terminal state — at completion for accepted jobs, at the doorbell for
content-error jobs (§5.3), giving software a single wait-path for both
outcomes. When bit 8 is 0, no job outcome ever touches the pending
level. Interrupt policy is strictly per-descriptor; there is no enable
register.

### 4.1 Versioning and reuse contract

- **No in-descriptor version field.** The consuming device's CAPS
  states the descriptor-format major version it implements (bits 7:0,
  §3.1). Version fields inside descriptors would cost 8 bytes in every
  descriptor to defend against a mismatch CAPS already rules out.
- **Reserved-MBZ fields are the extension mechanism.** A later revision
  may assign meaning **only** to bits and fields v1 requires to be zero
  (OP bits 63:9, NEXT, offsets 40–63). A v1 device presented with a
  descriptor using such an extension rejects it deterministically with
  BAD_FORMAT — extensions are never default-on and can never be
  silently misinterpreted (display.md §8 precedent).
- **NEXT is pre-reserved for chaining** so descriptor chaining lands in
  a v2 without relayout: offset 32 will never mean anything else.
- **v1 field offsets and assigned opcodes are never repurposed.** A
  future major version may extend; it may not reinterpret. Any change
  that alters the meaning of a v1-legal descriptor bumps the major
  version in CAPS bits 7:0, and consumers must treat an unknown major
  version as an unusable device (fail loudly, boot.md §4.1 spirit).

### 4.2 Opcode registry (owned here; future specs append)

This registry governs OP bits 7:0 for **every** descriptor-consuming
Sahara device that adopts this descriptor format. Later accelerator
specifications claim opcodes by appending rows here — never by
redefining existing rows, and never outside a CAPS-gated device
revision that names the claimed range.

| opcode | operation | consumer | status |
|---:|---|---|---|
| 0 | — | — | reserved, **never assigned** (a zeroed descriptor — fresh RAM — must never be a valid job; it fails BAD_OP) |
| 1 | COPY | DMA engine (this document) | assigned, v1 |
| 2 | FILL | DMA engine (this document) | assigned, v1 |
| 3–255 | — | — | unassigned; claimable only by a future revision of this registry, each claim gated by a CAPS capability of its consuming device |

Operation semantics, v1:

- **COPY (1):** the LEN bytes at [SRC, SRC+LEN) are copied to
  [DST, DST+LEN), as if read entirely into an internal buffer and then
  written entirely (§5.4). Overlapping source and destination ranges
  are **legal and defined** with exactly these (memmove) semantics.
- **FILL (2):** the 8-byte SRC pattern is written to every 8-byte-
  aligned slot in [DST, DST+LEN): byte `DST + i` receives byte `i mod 8`
  of the pattern's little-endian image.

---

## 5. Job lifecycle

### 5.1 State machine

```
                 doorbell, content OK
   IDLE ────────────────────────────────► BUSY
   DONE ─┤ (E5: doorbell while BUSY          │ completion boundary
  BAD_* ─┘        traps DEVERR)              ▼ (§5.5)
                 doorbell, content bad     DONE
   IDLE/DONE/BAD_* ───────────────────► BAD_OP / BAD_FORMAT /
                                        BAD_ALIGN / BAD_RANGE
```

Exactly one job exists at a time; there is no queue. Every transition
out of IDLE/DONE/BAD_* is a doorbell store; the only other transition
is BUSY → DONE at the completion boundary.

### 5.2 Submission (doorbell store, in order)

1. **Access checks** (trap DEVERR, no effect — §2.1 precedence):
   E5 (BUSY), then E6 (PA not 64-aligned), then E7 ([PA, PA+64) not
   wholly inside declared RAM).
2. **Latch:** the 64 descriptor bytes are read from RAM
   (device-internally, no trace records) and latched.
3. **Content validation** on the latched bytes, order fixed (§5.3):
   BAD_OP → BAD_FORMAT → BAD_ALIGN → BAD_RANGE; first failure is
   reported and checking stops.
4. **Failure:** STATUS ← the error code; COMP_CYCLE ← the doorbell
   store's cycle; if latched OP bit 8 = 1, the pending level rises.
   BUSY is never entered; no destination byte is written; the store
   itself retires normally (the badness lives in RAM data, not in the
   access — no trap). The very next instruction already reads the
   terminal STATUS.
5. **Acceptance:** STATUS ← BUSY; COMP_CYCLE ← `C_done` (§6); the job
   is in flight. The pending level is not touched at acceptance.

### 5.3 Content validation (first failure wins)

| order | code | condition |
|---:|---|---|
| 1 | BAD_OP (3) | OP bits 7:0 not an assigned opcode: not 1 and not 2 (0 included — the zeroed-RAM guard) |
| 2 | BAD_FORMAT (4) | any reserved-MBZ violation: OP bits 63:9 nonzero, NEXT ≠ 0, or any of the words at offsets 40, 48, 56 nonzero |
| 3 | BAD_ALIGN (5) | SRC not 8-aligned (COPY only), DST not 8-aligned, or LEN not a multiple of 8 |
| 4 | BAD_RANGE (6) | LEN = 0, LEN > 2^24, or an operand range not wholly inside declared RAM: [SRC, SRC+LEN) (COPY only) or [DST, DST+LEN) |

BAD_FORMAT is split from BAD_OP so forward-compatibility rejection — a
v2 descriptor offered to a v1 device — is distinguishable and directly
testable (§4.1).

The engine touches **ordinary RAM only**: device register windows, the
NIC TX/RX buffers, the display pixel buffer, and undeclared holes are
all BAD_RANGE for SRC and DST alike. The device-table window
[0x0800, 0x1000) is ordinary RAM (boot.md §3.1) and is a legal source
or destination. Pixel-buffer blit is a named v2 extension candidate
(§9), CAPS-gated, not a v1 behavior.

Range arithmetic is exact and unbounded: `SRC + LEN` and `DST + LEN`
do not wrap (operands are u64, LEN ≤ 2^24; a conforming implementation
must not truncate the sum).

### 5.4 Data semantics

- **Sources are sampled at completion.** The transfer reads RAM as it
  is at the completion boundary, not at the doorbell: a guest store
  into [SRC, SRC+LEN) after the doorbell but before `C_done` **is**
  reflected in the copy. (Descriptor bytes are the opposite — latched
  at the doorbell, §4.)
- **Completion is fully atomic.** At the completion boundary the engine
  reads all LEN source bytes, then writes all LEN destination bytes, as
  if through an intermediate buffer. Consequences, all normative:
  overlapping COPY yields exactly the memmove result; no instruction
  ever observes a partially-copied destination; there is no
  intermediate observable state whatsoever between BUSY and DONE.
- **Bytes outside [DST, DST+LEN) are never written.** FILL and COPY
  write exactly LEN bytes.

### 5.5 Completion

An accepted job completes at the first inter-instruction boundary B
with `cycle(B) ≥ C_done`, in the boundary device phase: **after** the
feed EVENTs bound to B are applied, **before** interrupt recognition
(the trace.md §3.3 order — EVENTs, then TRAP, then the next
instruction). At B, as one atomic action:

1. the transfer is performed (§5.4);
2. STATUS ← DONE;
3. if latched OP bit 8 = 1, the engine's EXTINT pending level rises.

Because the guest cannot execute between the doorbell and the next
boundary faster than the K = 8 cycle overhead, and LEN > 0 forces
LEN/8 ≥ 1, `C_done > C_doorbell` always: BUSY is observable for at
least one instruction after every accepted doorbell, and completion
never lands on the doorbell's own boundary.

> *Note: in v1 the EVENTs-before-DMA order inside one boundary is
> unobservable — no v1 EVENT payload can touch engine state or any RAM
> the engine reads mid-boundary — but the order is pinned normatively
> now so descriptor-consuming devices added later inherit a defined
> interleaving instead of an accident.*

### 5.6 Signaling

Both signaling styles are always available; the descriptor chooses
whether the interrupt fires:

- **Poll:** STATUS leaves BUSY exactly at B; COMP_CYCLE gives the
  deadline in advance (§3.5).
- **Interrupt:** with latched OP bit 8 = 1, the engine's term in the
  level-triggered EXTINT OR (PLATFORM-SPEC §3) asserts at the job's
  terminal state and holds until an IRQ_ACK store of 1. Delivery
  follows ISA-SPEC §7.5: between instructions, only when
  `status.IE` = 1; masking defers, never cancels, a level condition.

---

## 6. Cycle-cost model

For an accepted job:

    C_done = C_doorbell + K + LEN/8        (K = 8, W = 8 bytes/cycle)

where `C_doorbell` is the cycle stamped on the doorbell store's DEVW
record (the executing instruction's cycle, devspec/trace.md §3.2). LEN
is a multiple of 8, so LEN/8 is exact — no ceiling function anywhere.
K and W are reference defaults **fixed by this document** (display.md
precedent) and mirrored in CAPS; they are not configuration and no
mechanism changes them at run time.

Worked example: doorbell store retires at cycle 1000 with a valid COPY
descriptor, LEN = 4096.

    C_done = 1000 + 8 + 4096/8 = 1000 + 8 + 512 = 1520

COMP_CYCLE reads 1520 from the doorbell on; STATUS reads BUSY (1) at
every read whose cycle is < 1520 and DONE (2) at every read whose
cycle is ≥ 1520; a load retiring at cycle 1519 still sees BUSY, a load
retiring at cycle 1520 sees DONE (§5.5: the boundary before the load
at cycle 1520 satisfies `cycle ≥ C_done` and completes the job). With
OP bit 8 set and interrupts enabled, EXTINT delivery is recognized at
the same boundary B and its TRAP record is stamped cycle 1520.

Content-error jobs have no cost model: they terminate at the doorbell
itself and COMP_CYCLE equals the doorbell cycle.

---

## 7. Determinism and trace

### 7.1 The axiom

A DMA job is a pure function of (descriptor bytes latched at the
doorbell, RAM contents at the completion boundary, doorbell cycle).
There is **no EVENT feed, no host input, no internal buffering across
boundaries, and no live-mode path**. The engine consults nothing but
guest RAM and the cycle counter; both emulators perform the same
integer arithmetic on the same latched bytes and write RAM at the same
boundary. Byte-identity between implementations is by construction.

### 7.2 The no-records rule

The transfer emits **zero trace records**:

- The descriptor read at the doorbell is a device-internal read: no
  MEMR records (the NIC's internal TX-buffer capture precedent,
  nic.md §7.2 / trace.md §2.3.3 — access records are per-instruction
  data accesses, and no instruction performs these reads).
- The completion-time source reads and destination writes are
  device-internal: no MEMR, no MEMW, no DEVW records (the NIC's RX
  buffer fill precedent — frozen: emulator-internal writes emit no
  records). A 16 MB COPY adds exactly zero bytes to the trace.

The only DMA-related trace records are the guest's own accesses: the
doorbell and IRQ_ACK stores appear as ordinary DEVW records, register
loads appear as MEMR records at trace level 2. trace.md v1 stays
closed: no new record type, no META key, no EVENT payload section.

### 7.3 Replay

Replay reproduces every transfer from the guest's own doorbell DEVW
already implied by the instruction stream — the replayer re-executes
the doorbell store and the same pure function runs again. No EVENT
records name the engine (there is no payload encoding to name it
with), the frozen EVENT device indices 0–3 are untouched, and replay
consults no host resource on the engine's behalf.

### 7.4 Boundary ordering

Within one inter-instruction boundary the order is: (1) feed EVENTs
bound to this boundary, in record order; (2) DMA completion, if
`cycle ≥ C_done`; (3) interrupt recognition; (4) the next instruction.
This refines trace.md §3.3 rule order without changing it — DMA
completion is a new step in the existing boundary device phase, not a
new phase, and it produces no record of its own.

### 7.5 WFI

An in-flight job with latched OP bit 8 = 1 is a **wake source** for
WFI: a WFI stalling past `C_done` resumes with the boundary at
**exactly `C_done`** — the frozen event-wake rule (an internal
occurrence at a known cycle), NOT the timecmp T+1 rule. At that
boundary the job completes, the pending level rises, and (IE
permitting) EXTINT is delivered at cycle `C_done` exactly.

An in-flight job with OP bit 8 = 0 is **not** a wake source: its
completion cannot make an interrupt pending, so it cannot terminate a
WFI stall (ISA-SPEC §7.6 — WFI wakes only on conditions that can
deliver). Software that polls must not WFI; software that WFIs must
set bit 8. A WFI whose only outstanding future condition is a
bit-8-clear DMA job deadlocks (and halts loudly) exactly as if the job
did not exist.

---

## 8. Errors — two classes, split by where the badness lives

**Access and value errors trap DEVERR** (§2.1, catalog E1–E9): the
guest performed a bad *access* — wrong size, wrong direction, wrong
offset, an unacceptable stored value (bad doorbell PA, doorbell while
BUSY, IRQ_ACK ≠ 1). The ISA no-effect rule applies: nothing changes.

**Descriptor content errors set a STATUS code and never trap** (§5.3):
the *access* was flawless — an aligned 64-bit store of a valid,
in-RAM, 64-aligned descriptor PA — and the badness lives in RAM data.
The store retires; the error is reported through the same STATUS /
COMP_CYCLE / optional-EXTINT path as success, one wait-path for
software.

Mixing the classes is non-conforming both ways: a DEVERR on a bad
opcode (content) breaks the split as surely as a silent STATUS code on
a misaligned doorbell PA (access). The two precedence chains are
disjoint and each is fixed: E5 → E6 → E7 within the doorbell's access
class; BAD_OP → BAD_FORMAT → BAD_ALIGN → BAD_RANGE within content.

---

## 9. Reserved and extension rules

1. Window offsets outside {0x00–0x20} trap `DEVERR` in both directions
   (§2 rule 3). There is no probeable reserved window: feature
   discovery is CAPS bits 63:32, which read 0 in v1.
2. Every future feature must be **opt-in and CAPS-gated**: inert until
   the guest explicitly enables it through a mechanism advertised by a
   set CAPS bit. A v1 guest that never examines CAPS bits 63:32 must
   observe exactly v1 behavior on every future engine.
3. A future revision may never repurpose the v1 register offsets, the
   v1 descriptor field offsets, the assigned opcodes 1–2, opcode 0's
   never-assigned status, or the meaning of CAPS bits 31:0.
4. Descriptor extensions live in the reserved-MBZ fields only, under
   the §4.1 contract; a v1 engine rejects every such descriptor with
   BAD_FORMAT.
5. Named v2 extension candidates (reserved here so the registry and
   CAPS space grow coherently; none of these is v1 behavior):
   descriptor **chaining** via NEXT; **scatter/gather** lists;
   **XOR/compose** ops (new opcodes from the §4.2 pool);
   **pixel-buffer blit** (DST in the display pixel window — BAD_RANGE
   in v1). Each requires a CAPS bit and a revision of this document.

---

## 10. Conformance requirements

Numbered, testable; each is a required behavior of a conforming
implementation. "ea" = the access's effective address; DMA = the
engine's window base from the device table. These feed CONFORMANCE.md
group C7 (memory and devices) via CONFORMANCE-DELTA.md, except the
clauses marked "(reference implementation)", which feed the
reference-implementation-only checks.

**Registers and errors**

- **DMA-C-01** After reset: CAPS reads 0x0000_0000_1808_0301, STATUS
  reads 0 (IDLE), COMP_CYCLE reads 0. (Vector V1 rows 1–3; dma_regs.)
- **DMA-C-02** An aligned access of size 1, 2, 4, or 16 anywhere in
  the window traps `DEVERR`, `baddr` = ea, no state change (E1).
- **DMA-C-03** An aligned 64-bit load or store at a window offset not
  in {0x00, 0x08, 0x10, 0x18, 0x20} traps `DEVERR` (E2) — both
  directions, including the last aligned offset 0xFFF8.
- **DMA-C-04** A load of DOORBELL or IRQ_ACK traps `DEVERR` (E3); a
  store to CAPS, STATUS, or COMP_CYCLE traps `DEVERR` (E4) and the
  register is unchanged afterward.
- **DMA-C-05** Any CAS or AMO* with ea in the window traps `DEVERR`
  (E9).
- **DMA-C-06** A misaligned access to the window traps `UNALIGNED`,
  not `DEVERR` (precedence §2.1); a predicated-false access — any
  offset, any size, either direction — retires with no trap and no
  device effect.
- **DMA-C-07** IRQ_ACK ← 1 clears the pending level (no-op when
  already clear, no trap either way); IRQ_ACK ← v for any v ≠ 1
  (0 and 2 included) traps `DEVERR` (E8) and the pending level is
  unchanged.
- **DMA-C-08** DOORBELL while STATUS = BUSY traps `DEVERR` (E5) with
  zero effect on the in-flight job: it still completes at its
  original `C_done` with its original data.
- **DMA-C-09** DOORBELL with a PA not 64-byte aligned (E6), or with
  [PA, PA+64) not wholly inside declared RAM (E7), traps `DEVERR`;
  STATUS and COMP_CYCLE are unchanged.

**Descriptor and jobs**

- **DMA-C-10** Content validation reports the first failure in the
  fixed order BAD_OP → BAD_FORMAT → BAD_ALIGN → BAD_RANGE, with the
  §5.3 conditions exactly: opcode 0 and every unassigned opcode are
  BAD_OP; OP bits 63:9, NEXT, and reserved words 40–63 nonzero are
  BAD_FORMAT; unaligned SRC (COPY)/DST/LEN are BAD_ALIGN; LEN = 0,
  LEN > 2^24, and out-of-RAM ranges are BAD_RANGE. (Vector V2;
  dma_err.)
- **DMA-C-11** A content-error doorbell never enters BUSY: the very
  next instruction reads the error code in STATUS; COMP_CYCLE equals
  the doorbell store's cycle; no destination byte is written; no trap
  is delivered; the pending level rises iff latched OP bit 8 = 1.
- **DMA-C-12** Descriptor bytes are latched at the doorbell: guest
  stores to [PA, PA+64) after the doorbell store do not affect the
  in-flight job. (dma_boundary.)
- **DMA-C-13** COPY writes exactly the LEN bytes [SRC, SRC+LEN) to
  [DST, DST+LEN); FILL writes the SRC pattern's little-endian image
  replicated over [DST, DST+LEN); no byte outside [DST, DST+LEN)
  changes. FILL's SRC is a pattern: it carries no alignment or range
  constraint. (dma_copy, dma_fill.)
- **DMA-C-14** Overlapping COPY produces exactly the memmove result,
  in both overlap directions. (dma_boundary.)
- **DMA-C-15** Source bytes are sampled at completion: a guest store
  into [SRC, SRC+LEN) after the doorbell and before `C_done` is
  reflected in the destination. (dma_boundary.)
- **DMA-C-16** A doorbell is accepted from DONE and from every error
  state (a completed or failed engine re-arms without any reset).
- **DMA-C-17** The device-table window is a legal COPY source or
  destination; a SRC or DST range touching any device window, the
  pixel buffer, or an undeclared hole is BAD_RANGE.

**Completion timing**

- **DMA-C-18** For an accepted job, COMP_CYCLE reads
  `C_doorbell + 8 + LEN/8` from the doorbell on (during BUSY
  included); a STATUS load retiring at cycle `C_done − 1` reads BUSY
  and one retiring at `C_done` reads DONE. (Vector V3; dma_copy,
  dma_fill, dma_boundary.)
- **DMA-C-19** Completion is atomic at one boundary: no instruction
  observes a partially-written destination or any state between BUSY
  and DONE.
- **DMA-C-20** The engine's EXTINT contribution rises at the terminal
  state iff latched OP bit 8 = 1, holds until IRQ_ACK ← 1, and obeys
  ISA-SPEC §7.5 (masking with IE = 0 defers delivery, never loses the
  level). (dma_irq_wfi, dma_err.)
- **DMA-C-21** A WFI stalling past an in-flight bit-8 job's `C_done`
  wakes with the boundary at exactly `C_done`; the EXTINT TRAP record
  is stamped cycle `C_done`. A bit-8-clear job is not a wake source.
  (Vector V5; dma_irq_wfi.)

**Reference implementation (trace and replay)**

- **DMA-C-22** (reference implementation) A transfer emits zero trace
  records: no MEMR for the descriptor read, no MEMR/MEMW/DEVW for the
  transferred bytes. In any DMA test trace, no MEMW or DEVW record has
  ea inside [DST, DST+LEN), and the only records at DMA-window
  addresses are the guest's own DEVW (doorbell, IRQ_ACK) and MEMR
  (register loads, level 2). (dma_copy's checker enforces this.)
- **DMA-C-23** (reference implementation) Replaying a recorded DMA
  run reproduces every post-META record byte-identically with no
  EVENT records naming the engine and no host resource consulted; the
  EVENT device indices 0–3 of devspec/boot.md §5 are unchanged by the
  engine's existence.
- **DMA-C-24** (reference implementation) Two identical headless runs
  of any DMA test produce byte-identical traces (TOOLING-SPEC §3.1;
  the suite's double-run check).

---

## 11. Test vectors

DMA = register window base (reference: 0x0F07_0000). All values
little-endian; machine state: reset defaults, supervisor, MMU off,
unless stated.

### V1 — register access matrix (§2, §3; DMA-C-01..07)

Rows execute in order.

| # | address | op | size | value | expected |
|--:|---------|----|-----:|-------|----------|
| 1 | DMA+0x00 | LD | 8 | | OK=0x18080301 |
| 2 | DMA+0x08 | LD | 8 | | OK=0 (IDLE) |
| 3 | DMA+0x20 | LD | 8 | | OK=0 |
| 4 | DMA+0x00 | LD | 4 | | DEVERR |
| 5 | DMA+0x00 | LD | 2 | | DEVERR |
| 6 | DMA+0x00 | LD | 1 | | DEVERR |
| 7 | DMA+0x00 | LD | 16 | | DEVERR |
| 8 | DMA+0x08 | ST | 4 | 0 | DEVERR |
| 9 | DMA+0x04 | LD | 8 | | UNALIGNED (alignment outranks E-checks) |
| 10 | DMA+0x02 | LD | 4 | | UNALIGNED |
| 11 | DMA+0x00 | AMOADD | 8 | 1 | DEVERR (E9) |
| 12 | DMA+0x10 | CAS | 8 | — | DEVERR (E9) |
| 13 | DMA+0x10 | LD | 8 | | DEVERR (E3) |
| 14 | DMA+0x18 | LD | 8 | | DEVERR (E3) |
| 15 | DMA+0x00 | ST | 8 | 0 | DEVERR (E4) |
| 16 | DMA+0x08 | ST | 8 | 0 | DEVERR (E4) |
| 17 | DMA+0x20 | ST | 8 | 0 | DEVERR (E4) |
| 18 | DMA+0x28 | LD | 8 | | DEVERR (E2) |
| 19 | DMA+0x28 | ST | 8 | 0 | DEVERR (E2) |
| 20 | DMA+0xFFF8 | LD | 8 | | DEVERR (E2) |
| 21 | DMA+0x18 | ST | 8 | 0 | DEVERR (E8 — ack-0 is not tolerated) |
| 22 | DMA+0x18 | ST | 8 | 2 | DEVERR (E8) |
| 23 | DMA+0x18 | ST | 8 | 0x8000000000000001 | DEVERR (E8) |
| 24 | DMA+0x18 | ST | 8 | 1 | OK (no-op ack, nothing pending) |
| 25 | DMA+0x08 | LD | 8 | | OK=0 (nothing above changed STATUS) |
| 26 | DMA+0x20 | LD | 8 | | OK=0 |

Rows 4–23 each trap with `baddr` = the row's address and leave every
register unchanged. Predicated-false repeats of rows 4, 11, 13 raise
no trap and read/write nothing (DMA-C-06).

### V2 — descriptor validation (§4, §5.3; DMA-C-10, DMA-C-11)

Byte image of a valid v1 COPY descriptor
(OP=1, SRC=0x20_0000, DST=0x30_0000, LEN=0x1000, rest MBZ):

```
01 00 00 00 00 00 00 00  00 00 20 00 00 00 00 00
00 00 30 00 00 00 00 00  00 10 00 00 00 00 00 00
00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00
00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00
```

Byte image of a valid v1 FILL descriptor with IRQ_ON_COMPLETE
(OP=0x102, pattern 0x0123456789ABCDEF, DST=0x40_0000, LEN=0x8000):

```
02 01 00 00 00 00 00 00  ef cd ab 89 67 45 23 01
00 00 40 00 00 00 00 00  00 80 00 00 00 00 00 00
00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00
00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00
```

Content-validation rows: each is the valid COPY descriptor above with
the named fields overridden, doorbelled from a non-BUSY state.
`expect status` is the STATUS value on the very next instruction;
in every row `expect comp_cycle = <doorbell cycle>` and no
destination byte changes.

| # | overrides | expect status |
|--:|---|---|
| 1 | OP = 0 | 3 (BAD_OP — zeroed RAM is never a job) |
| 2 | OP = 7 | 3 (BAD_OP) |
| 3 | NEXT = 1 | 4 (BAD_FORMAT) |
| 4 | OP = 0x201 (bit 9 set) | 4 (BAD_FORMAT) |
| 5 | word at offset 56 = 1 | 4 (BAD_FORMAT) |
| 6 | SRC = 0x20_0001 | 5 (BAD_ALIGN) |
| 7 | DST = 0x30_0004 | 5 (BAD_ALIGN) |
| 8 | LEN = 12 | 5 (BAD_ALIGN) |
| 9 | LEN = 0 | 6 (BAD_RANGE — not a no-op) |
| 10 | LEN = 0x100_0008 | 6 (BAD_RANGE — above 2^24) |
| 11 | DST = 0x1000_0000 (pixel buffer) | 6 (BAD_RANGE) |
| 12 | SRC = 0x0EFF_F000, LEN = 0x2000 | 6 (BAD_RANGE — crosses the RAM top) |
| 13 | OP = 0, NEXT = 1, SRC = 0x20_0001, LEN = 0 | 3 (first failure wins) |
| 14 | NEXT = 1, SRC = 0x20_0001, LEN = 0 | 4 (first failure wins) |
| 15 | SRC = 0x20_0001, LEN = 0 | 5 (first failure wins) |
| 16 | OP = 0x100 (opcode 0, bit 8) | 3, and the EXTINT pending level rises (DMA-C-11) |

### V3 — cost model (§6; DMA-C-18)

```
input  C_doorbell = 1000, opcode = COPY, LEN = 4096
expect C_done      = 1520
expect comp_cycle  = 1520          # readable from cycle 1000 on
expect status@1519 = 1             # load retiring at 1519: BUSY
expect status@1520 = 2             # load retiring at 1520: DONE

input  C_doorbell = 2000, opcode = FILL, LEN = 32768
expect C_done      = 2000 + 8 + 4096 = 6104
```

### V4 — latch, sample, overlap (§4, §5.4; DMA-C-12/14/15)

| step | action | expected |
|-----:|--------|----------|
| 1 | build COPY desc D (SRC=A, DST=B, LEN=64) at PA P; doorbell P | STATUS=BUSY |
| 2 | store OP=0 over P+0 (corrupt the descriptor in RAM) | in-flight job unaffected (latched) |
| 3 | store new value N over A+0 (source data, before C_done) | — |
| 4 | poll STATUS to DONE; read B | B[0..7] = N (sampled at completion); B[8..63] = A[8..63]; STATUS=DONE, never BAD_OP |
| 5 | fill E with words f(0)..f(63); COPY SRC=E, DST=E+8, LEN=512 | after DONE: word at E+8*(1+j) = f(j) for all j (memmove, not a forward smear); E[0..7] = f(0) |
| 6 | fill F likewise; COPY SRC=F+8, DST=F, LEN=512 | word at F+8*j = f(j+1)... i.e. the memmove result in the other direction |

### V5 — IRQ and WFI (§5.6, §7.5; DMA-C-20/21)

| step | action | expected |
|-----:|--------|----------|
| 1 | doorbell COPY, OP bit 8 = 1, LEN = 4096, at cycle X | COMP_CYCLE = X+520 |
| 2 | set IE = 1; WFI (retires before X+520) | stall |
| 3 | — | wake at boundary X+520 exactly; EXTINT TRAP record cycle = X+520; epc = instruction after WFI |
| 4 | handler: MFSR cycle | reads X+521 (delivery consumed one cycle) |
| 5 | handler: IRQ_ACK ← 1; IRET | pending level drops; no second delivery |
| 6 | doorbell bit-8 job with IE = 0; poll STATUS to DONE; then set IE = 1 | delivery immediately after IE is set — masking deferred, never lost |

### V6 — reference device table with the DMA engine (byte-exact, vector V-D)

**V-D** — the wave-final 7-device reference platform table: boot.md V1's
header and four records with `device_count` = 7, then the type-7 rng
record fifth (rng.md §11.5 — its vector V-T is this same table), the
type-5 timer record sixth (timer.md §8 — vector V1-T, same table), and
this document's type-6 engine seventh. 520 bytes at `[0x0800, 0x0A08)`;
the emulator writes zeros through the end of the 2 KB window.

```
00000800: 53 41 48 41 52 41 50 54 01 00 00 00 00 00 00 00
00000810: 01 00 00 00 00 00 00 00 01 00 00 00 00 00 00 00
00000820: 07 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
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
000009c0: 00 00 00 00 00 00 00 00 06 00 00 00 00 00 00 00
000009d0: 00 00 07 0f 00 00 00 00 00 00 00 00 00 00 00 00
000009e0: 00 00 01 00 00 00 00 00 00 00 00 00 00 00 00 00
000009f0: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00000a00: 00 00 00 00 00 00 00 00
```

```
expect device_count       = 7
expect dev[6].type        = 6
expect dev[6].base        = 0x0F070000
expect dev[6].size        = 0x10000
expect dev[6].params[0]   = 0
expect dev[6].params[1]   = 0
expect dev[6].params[2]   = 0
expect dev[6].params[3]   = 0
expect table_end_pa       = 0x0A08
```

The `dev[6]` index above pins this vector's bytes only: guests still
locate the engine by type-code scan (§1), and nothing else anywhere may
key on the record's position.

---

## 12. Cross-document dependencies

| dependency | resolution |
|---|---|
| devspec/boot.md §3.5 / §7 V1 | device table record layout and the pre-wave 4-record reference bytes; the wave-final 7-record table is pinned here (V-D) and in timer.md V1-T / rng.md V-T |
| devspec/trace.md §2.3.3 / §2.3.6 | MEMR/DEVW are per-instruction data accesses — the basis of the §7.2 no-records rule; no trace.md change is made or needed |
| devspec/trace.md §3.3 | boundary order (EVENTs → interrupt recognition) that §5.5/§7.4 refine with the DMA completion step |
| devspec/nic.md §2.2 / §7.2 | the device-internal-access precedents (TX capture reads, RX buffer fill writes emit no records) that §3.3/§7.2 follow |
| devspec/boot.md §3.4 / BOOT-15 | declared-RAM semantics behind E7 and BAD_RANGE; hole accesses trap DEVERR |
| ISA-SPEC §5.4, §7.5, §7.6, §9.2 | atomics-to-device DEVERR, EXTINT level semantics, WFI stall, device-space ordering (all frozen; restated only) |

This document defines nothing owned by another devspec document. The
descriptor format and opcode registry defined in §4 are owned here and
referenced by future accelerator specifications.
