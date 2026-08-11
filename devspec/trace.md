# Sahara Execution Trace — Detailed Specification

**Status:** devspec, expands TOOLING-SPEC.md §3 (and PLATFORM-SPEC.md §8).
Frozen and authoritative above this document: ISA-SPEC.md, PLATFORM-SPEC.md,
TOOLING-SPEC.md, CONFORMANCE.md, `encoding.py`. Where those documents speak,
this document only elaborates; it never overrides.

**Ownership** (per the devspec ownership matrix): this document owns the
**EVENT payload encoding for every device** (keyboard, mouse, NIC frame,
display resize). Every other devspec document references §4 of this document
and defines no local version. This document in turn only *references*:

- device register offsets/widths — frozen in PLATFORM-SPEC.md;
- instruction encodings — frozen in `encoding.py`;
- the HID usage-ID subset — per `devspec/input.md`;
- the device table layout and reference device ordering — per
  `devspec/boot.md`;
- NIC live-mode cycle-assignment policy and frame validity — per
  `devspec/nic.md`;
- assembler surface grammar — TOOLING-SPEC.md §4 as elaborated by
  `devspec/asm.md` (see §6.4 note).

Contents: §1 conventions, §2 file format, §3 stream semantics, §4 EVENT
payload encodings, §5 replay semantics, §6 `trace-q`, §7 conformance
requirements, §8 test vectors.

---

## 1. Conventions

1. All multi-byte integers in a trace file are **little-endian**. `u8`,
   `u16`, `u32`, `u64` are unsigned of that bit width; `u128` is 16 bytes,
   little-endian.
2. Records and payload fields are **packed**: no padding bytes anywhere, no
   alignment requirement on any record or field. A trace is a flat byte
   stream.
3. Hexadecimal in `trace-q` output is lowercase. 128-bit quantities print as
   `0x` + exactly 32 hex digits (zero-padded); 64-bit instruction words as
   `0x` + exactly 16 hex digits. Cycles print in decimal.
4. "Cycle" always means the value of the `cycle` sreg (ISA-SPEC §4) as
   stamped by the rules of §3.2.

## 2. File format

Extension `.trc`. A trace file is a sequence of records with no file header
other than the mandatory first record (META, §2.3.7).

### 2.1 Record framing

Every record (TOOLING-SPEC §3.2):

| offset | field | value |
|-------:|-------|-------|
| 0 | type u8 | 1–7, table below |
| 1 | reserved u8 | must be 0 |
| 2 | reserved u16 | must be 0 |
| 4 | payload length u32 | exact byte count of the payload |
| 8 | payload | `payload length` bytes |

The next record begins immediately after the payload.

Fixed payload lengths (a reader must verify these; see §2.4):

| type | name | payload length |
|-----:|------|---------------|
| 1 | EXEC  | 50 |
| 2 | MEMW  | 41 |
| 3 | MEMR  | 41 |
| 4 | TRAP  | 49 |
| 5 | EVENT | 20 + n (n = device payload bytes) |
| 6 | DEVW  | 41 |
| 7 | META  | variable (text) |

### 2.2 Record ordinals

Records are numbered from 0 in file order (META is record 0). `trace-q
diverge` reports ordinals; nothing in the file stores them.

### 2.3 Payload layouts

All offsets are within the payload (i.e. relative to record offset 8).

#### 2.3.1 EXEC (type 1) — one retired instruction

| off | field | meaning |
|----:|-------|---------|
| 0  | cycle u64 | stamp per §3.2 |
| 8  | pc u128 | virtual address the instruction was fetched from |
| 24 | insn u64 | the raw 64-bit instruction word |
| 40 | wb u128 | destination-register writeback value; 0 if `wrote-dst` = 0 |
| 56 | flags u8 | bit 0 `predicated-false` (squashed), bit 1 `wrote-dst`, bit 2 `wrote-pred`; bits 7:3 must be 0 |
| 57 | pred_wb u8 | when `wrote-pred` = 1: the **entire 8-bit predicate file after the write** (bit i = P[i]); otherwise 0 |

Rules:

- `wrote-dst` = 1 iff an architectural GPR write occurred. A write with
  `dst` = r31 is discarded by hardware (ISA §2.1) and records
  `wrote-dst` = 0, `wb` = 0. A squashed instruction records flags bit 0 = 1
  and bits 1–2 = 0, `wb` = 0, `pred_wb` = 0.
- `pred_wb` carries the whole file (not a single bit) because PWR writes
  p1–p7 at once; for a compare, exactly one bit differs from the prior
  file. TOOLING-SPEC §3.2 leaves the content of this u8 open; this is the
  normative resolution.
- A genuine writeback value of 0 is distinguished from "no writeback" only
  by flags bit 1, never by the `wb` field.

#### 2.3.2 MEMW (type 2) — data store to RAM

| off | field |
|----:|-------|
| 0  | cycle u64 |
| 8  | ea u128 (virtual effective address) |
| 24 | size u8 (bytes: 1, 2, 4, 8, or 16) |
| 25 | new u128 — the value written; bytes above `size` must be 0 |

#### 2.3.3 MEMR (type 3) — data load (RAM or device space)

Same layout as MEMW with field `val u128` at offset 25: the value the load
returned, bytes above `size` zero. Device-space loads (including
side-effecting reads such as a keyboard DATA pop) are MEMR records; there
is no DEVR type. Instruction fetches and page-table-walk reads are **not**
data accesses and are never recorded.

#### 2.3.4 TRAP (type 4) — one trap/interrupt delivery

| off | field |
|----:|-------|
| 0  | cycle u64 (the cycle consumed by delivery, §3.2) |
| 8  | cause u64 (code per `encoding.py` `CAUSES`) |
| 24 | epc u128 (the value written to the epc sreg) |
| 40 | baddr u128 — the value written to the baddr sreg; must be 0 for causes with no baddr (TIMER, EXTINT, ILLEGAL, SYSCALL, PRIV) |
| 48 | tl_after u8 — `status.TL` after delivery (1 or 2), or **3** for the diagnostic triple-fault record below |

Triple fault (ISA §7.2 step 1) halts the machine with no architectural
state written. The trace still records it, loudly: a final TRAP record is
emitted with the cause/epc/baddr the third trap *would* have delivered and
`tl_after` = 3, and the trace ends. This record is diagnostic only; it
corresponds to no sreg writes.

#### 2.3.5 EVENT (type 5) — one external-input event

| off | field |
|----:|-------|
| 0  | cycle u64 (cycle at which the event was applied, §3.3) |
| 8  | device u64 — 0-based index of the device's entry among the device table's device entries (table layout per `devspec/boot.md`; PLATFORM-SPEC §2) |
| 16 | payload_len u32 — must equal the record's payload length − 20 |
| 20 | payload bytes — encoding per §4, selected by the *type* field of the indexed device-table entry |

#### 2.3.6 DEVW (type 6) — data store to device space

Same layout as MEMW (field named `val`). A store lands in exactly one of
MEMW/DEVW depending on whether the physical target is device space
(PLATFORM-SPEC §1); the display pixel buffer and NIC TX/RX buffers are
device space, so stores to them are DEVW.

#### 2.3.7 META (type 7) — run metadata; first record of every trace

Payload is UTF-8 text: a sequence of lines `key=value`, each terminated by
a single LF (0x0A). Keys match `[a-z0-9_]+`; values contain no NUL and no
LF. Exactly one META record exists per trace and it is record 0.

v1 key catalog — all seven keys are mandatory, written in exactly this
order, no others emitted:

| key | value | run-variant? |
|-----|-------|--------------|
| `trace` | trace-format version: `1` | no |
| `encoding` | `SPEC_VERSION` from `encoding.py` (`1.0-draft`) | no |
| `level` | recording level: `0`, `1`, or `2` | no |
| `mode` | `live` or `replay` | **yes** |
| `image` | image path exactly as given on the emulator command line | **yes** |
| `image_sha256` | lowercase hex SHA-256 of the `.img` file bytes | no |
| `platform` | PLATFORM-SPEC version (`1.0-draft`) | no |

Readers must ignore unknown keys (forward compatibility); v1 writers must
not emit any. "Run-variant" keys are excluded from trace comparison (§5.3,
§6.5.6).

### 2.4 Malformation and truncation

Loud-failure policy applies. Two classes:

1. **Torn tail** (the expected artifact of a killed emulator): the file
   ends before a complete record — fewer than 8 bytes of header remain, or
   fewer than `payload length` payload bytes remain. Readers use the
   complete-record prefix and **must** emit a diagnostic to stderr
   containing the decimal file offset of the incomplete record and the
   number of bytes discarded. This does not change any exit code; the
   prefix is a valid trace.
2. **Malformed record** — any of the following, anywhere except a torn
   tail: nonzero reserved header bytes; a type outside 1–7; a fixed-type
   payload length differing from §2.1's table; EVENT inner `payload_len`
   ≠ payload length − 20; nonzero EXEC flags bits 7:3; META not record 0,
   missing, duplicated, or violating §2.3.7's line grammar; missing
   mandatory META key; a record whose `cycle` decreases (§3.1). Readers
   must reject the file with a fatal error (for `trace-q`: exit 2).

Writers must emit records in a single append-only stream in emission
order, with no compression and no padding, and must flush completely on
machine halt.

## 3. Stream semantics

### 3.1 Global invariants

1. Record 0 is META; no other META exists.
2. The `cycle` fields of all records are non-decreasing in file order.
3. Cycle values may skip only across a WFI stall (ISA §7.6); every other
   consecutive pair of stamped cycles differs by 0 or 1.
4. Recording levels (TOOLING-SPEC §3.2) select record types:
   level 0 = META + EXEC + TRAP + EVENT; level 1 adds MEMW + DEVW;
   level 2 adds MEMR. `level` in META must match the types present.
   Conformance runs use level 1.

### 3.2 Cycle stamping

The `cycle` sreg starts at 0 at reset and increments by exactly 1 per
retired instruction and per trap delivery (ISA §4). Every record is
stamped with the **pre-increment** value:

- An EXEC record's cycle is the value `cycle` held while the instruction
  executed (an MFSR of `cycle` by that instruction reads the same value).
  The first instruction after reset has cycle 0.
- A TRAP record's cycle is the value held during the delivery.
- MEMW/MEMR/DEVW records carry the cycle of the instruction that made the
  access.
- EVENT records carry the cycle current at the boundary where the event
  was applied (§3.3).

Traces always begin at reset: cycle 0 is in every trace, and `trace-q reg`
reconstruction (§6.5.4) assumes the reset register state as its base.

### 3.3 Per-cycle emission order

An **inter-instruction boundary** is the point between two instruction
executions (equivalently: before the first, after the last). At each
boundary, in order:

1. All input events being applied at this boundary take effect on their
   device models and are recorded as EVENT records, in application order.
2. Interrupts are recognized (ISA §7.5). A delivery emits one TRAP record.
3. Otherwise the next instruction executes.

For one executed instruction, records are emitted in this order, all with
the same cycle:

1. Its data-access records, in the instruction's own access order
   (for atomics: MEMR first, then MEMW — and the MEMW is present only if
   the write was performed, so a failed CAS emits MEMR only).
2. Its EXEC record, last (the EXEC is the commit marker; a reader
   attributes access records to the next EXEC of equal cycle).

Emission rules:

- **EXEC** is emitted for every retired instruction, including
  predicated-false (squashed) ones. A squashed instruction emits no
  access records (it makes no accesses, ISA §3.2).
- An instruction that **traps** (fault or SYSCALL) does not retire: it
  emits **no EXEC** and no access records for the faulting access; the
  delivery's TRAP record is what appears. Only the delivery consumes a
  cycle (see issues note at end).
- An **interrupt** delivery emits a TRAP at its own cycle, after any
  EVENT records applied at that boundary (which therefore share its cycle
  value).
- The architectural **timer** is not a device and produces no EVENT
  records; it appears only as TRAP cause TIMER.
- **WFI**: the WFI instruction emits a normal EXEC; the cycle jump is
  visible as a gap before the next record. WFI-deadlock halt (ISA §7.6)
  ends the trace after that EXEC.
- **HALT** emits its EXEC; the trace ends.
- **Triple fault** emits the diagnostic TRAP of §2.3.4 and the trace ends.

## 4. EVENT payload encodings (owned here)

The payload of an EVENT record is interpreted according to the *type*
field of the device-table entry named by `device`. All integers
little-endian. Devices and type codes per PLATFORM-SPEC §2: 1 display,
2 keyboard, 3 mouse, 4 nic; accelerator-wave codes 5 timer, 6 dma,
7 rng (devspec/rng.md) — of these, only type 7 carries an event payload,
defined in §4.6.

### 4.1 Keyboard (device type 2) — 9 bytes

| off | field |
|----:|-------|
| 0 | event u64 — the event word exactly as the DATA register returns it (PLATFORM-SPEC §5): bits 31:0 USB HID usage ID (subset per `devspec/input.md`), bit 32 = 1 press / 0 release, bits 63:33 = 0 |
| 8 | flags u8 — bit 0 = **dropped-on-arrival** (the device queue was full and this event was discarded, PLATFORM-SPEC §5); bits 7:1 = 0 |

A dropped event is applied to the device model like any other arrival; the
model's deterministic overflow rule discards it. Recording the drop makes
it trace-visible and replay-checkable (§5.4).

### 4.2 Mouse (device type 3) — 9 bytes

Identical shape to §4.1; the event u64 is the mouse event word of
PLATFORM-SPEC §6 (bits 15:0 x, 31:16 y, 39:32 buttons, 63:40 zero), and
the flags byte is the same dropped-on-arrival flag.

### 4.3 NIC received frame (device type 4) — n bytes

The payload is exactly the Ethernet II frame bytes the emulator will
expose in the RX buffer, with no FCS and no added framing; `payload_len`
is the frame length (the value RX_LEN will report). Validity constraints
on length and content are owned by `devspec/nic.md`; the trace stores
whatever the NIC model accepted as an arrival, byte-for-byte.

### 4.4 Display resize (device type 1) — 32 bytes

| off | field |
|----:|-------|
| 0  | width u64 — new WIDTH register value (pixels) |
| 8  | height u64 — new HEIGHT register value (pixels) |
| 16 | stride u64 — new STRIDE register value (bytes) |
| 24 | format u64 — new FORMAT register value; must be 1 in v1.0 |

Applying the event performs the register update + IRQ_STATUS/EXTINT
behavior of PLATFORM-SPEC §4 atomically at the boundary.

### 4.5 Reservations

Type 5 (timer, per devspec/timer.md): no EVENT payload is defined; an
EVENT record whose device index resolves to a type-5 device-table
record makes the trace malformed (§2.4 class 2).

Type 6 (DMA engine, per devspec/dma.md §7): same rule — the engine is
cycle-driven, no EVENT payload is defined, and an EVENT record whose
device index resolves to a type-6 record makes the trace malformed
(§2.4 class 2).

Future device types define their payloads here (in this document) when
they are added. A v1 reader encountering an EVENT whose `device` index
does not exist in the image's device table, or whose device type it does
not know, must treat the trace as malformed (§2.4 class 2).

### 4.6 RNG entropy (device type 7) — 8·N bytes

The payload is N 64-bit entropy words, little-endian, packed with no
count field and no flags: `payload_len` = 8·N, with 1 ≤ N ≤ 128 (so a
payload is 8 to 1024 bytes). A length of 0, a length not a multiple of
8, or a length above 1024 is malformed (§2.4 class 2).

The recorded words are **exactly the words the device model accepted**
at the boundary — the accepted prefix under devspec/rng.md §4.2's
truncate-to-fit rule, not the raw arrival. An arrival of which zero
words were accepted produces **no EVENT record at all** (the NIC-discard
asymmetry of §4.3, not the input drop-flag one of §4.1: entropy words
are fungible, and recording only accepted words makes a recorded trace
replay without truncation — the record→replay fixed point). Acceptance
is recomputed by the replayed model per §5.4, like the input drop flag.

## 5. Replay semantics

### 5.1 What replay consumes

Replay mode runs the emulator from: the `.img` file, plus **only** the
EVENT records of a trace (the "event trace" of PLATFORM-SPEC §8), plus the
META record for validation. Before executing, the replayer must check:

- `image_sha256` matches the SHA-256 of the image it was given;
- `encoding` matches the replayer's own encoding version;
- `trace` = 1.

Any mismatch is a fatal error; the run must not start.

### 5.2 What replay reproduces

Each EVENT record (cycle C, device D, payload P) is applied at the
boundary where the machine's cycle counter first reaches C, in record
order, per §3.3 — the trace order *is* the application order. The
replaying emulator, recording at the same level, must produce a trace in
which **every record after META — including the EVENT records themselves —
is byte-identical** to the original, in the same order.

Replay is isolated: host input, host network, and the host clock must not
be consulted (the NIC-side statement of this guarantee is in
`devspec/nic.md`; the trace-level guarantee is that EVENT records are the
sole input source).

### 5.3 What "byte-identical" quantifies over

At recording level L, byte-identical means: the byte sequences of the two
traces, each starting at record 1 (i.e. excluding META), are equal. META
is compared key-by-key: the run-variant keys of §2.3.7 (`mode`, `image`)
are excluded; all other keys must be equal.

Per level:

- level 0: quantifies over EXEC + TRAP + EVENT records;
- level 1: additionally MEMW + DEVW;
- level 2: additionally MEMR.

Levels nest: for one run, filtering the level-2 trace down to level-1
record types must yield exactly the level-1 trace's post-META bytes, and
likewise level 1 → level 0. (Equivalently: raising the level only inserts
records; it never changes existing ones.)

### 5.4 Determinism cross-checks

- The drop flag (§4.1/§4.2) is recomputed by the replayed device model;
  §5.2's byte-identity requirement therefore catches a divergent drop
  decision. A replayer may additionally abort with an error at the first
  divergent record (recommended; loud), but the normative check is trace
  comparison.
- Live-mode cycle assignment: the emulator may apply host input at any
  inter-instruction boundary it chooses (NIC policy per `devspec/nic.md`),
  but the recorded EVENT cycle must equal the cycle at the boundary of
  application — the trace records what happened, never an intention.
- Identical invocations (same image bytes, same event feed, same level,
  same mode, same image path argument) produce byte-identical `.trc`
  files in their entirety, META included (TOOLING-SPEC §3.1).

## 6. `trace-q`

One CLI tool; its subcommands are the normative query set (TOOLING-SPEC
§3.3). No interactive mode.

### 6.1 Invocation

```
trace-q [--sym FILE] exec CYCLE TRACE
trace-q [--sym FILE] at PC TRACE
trace-q [--sym FILE] last-write ADDR [--before CYCLE] TRACE
trace-q            reg R --at CYCLE TRACE
trace-q [--sym FILE] find (--pc X | --wrote-reg R=V | --touched A) [--from C] [--to C] TRACE
trace-q            diverge A.trc B.trc
trace-q [--sym FILE] range C1 C2 TRACE
trace-q [--sym FILE] trapdump TRACE
```

Input numbers accept decimal, `0x` hex, and `0b` binary. Register names
accept `r0`–`r31` and the aliases `sp`, `ra`, `k0`, `zero`
(TOOLING-SPEC §4.2), case-insensitive; predicates `p0`–`p7`.

### 6.2 Exit codes (uniform)

| code | meaning |
|-----:|---------|
| 0 | the query produced at least one output line |
| 1 | valid query, zero matching facts (empty stdout) — includes `diverge` on identical traces and `trapdump` on a trap-free trace |
| 2 | error: bad usage, unreadable file, malformed trace or `.sym`, META validation failure |

stdout carries only facts; all diagnostics (including the torn-tail
warning of §2.4) go to stderr.

### 6.3 Output line grammar

Every stdout line is a sequence of space-separated `key=value` tokens.
Only the **final** token of a line (`asm=`, `a=`, `b=`) may contain
spaces; it extends to end of line. Absent/inapplicable values print as
`-`. Formats of numbers per §1.3.

Record line formats (used by several queries):

- EXEC line:
  `cycle=<dec> pc=<hex128> sym=<S> insn=<hex64> squashed=<0|1> wb=<hex128|-> pred=<hex8|-> asm=<disassembly>`
  where `wb` is `-` iff `wrote-dst` = 0, `pred` is `-` iff `wrote-pred` = 0
  and otherwise the two-hex-digit `pred_wb` file (`0x` + 2 digits).
- MEMW/MEMR/DEVW line:
  `type=<MEMW|MEMR|DEVW> cycle=<dec> ea=<hex128> sym=<S> size=<dec> val=<hex128>`
- TRAP line:
  `cycle=<dec> cause=<NAME> epc=<hex128> sym=<S> baddr=<hex128|-> tl=<dec>`
  `cause` is the name from `encoding.py` `CAUSES`; `baddr` prints `-` for
  the causes listed in §2.3.4 as baddr-less; `tl` is `tl_after`.
- EVENT line (rendered only by `diverge`):
  `type=EVENT cycle=<dec> device=<dec> payload_len=<dec> data=<hex bytes, no separators>`

### 6.4 Symbolization and disassembly

**`.sym` resolution.** With `--sym`, the file is parsed per TOOLING-SPEC
§2. For an address A being symbolized (`pc`, `epc`, `ea`): consider only
kinds `T` and `D` (`A` symbols never resolve addresses); choose the symbol
with the largest address ≤ A; ties break to the lexicographically smallest
name. Output `name` when exact, `name+0x<offset hex>` otherwise, `-` when
no candidate exists or `--sym` was not given. There is no distance limit.
A `.sym` line not matching the TOOLING-SPEC §2 grammar is fatal (exit 2).

**Disassembly canonical form** (the `asm=` value). Surface syntax follows
TOOLING-SPEC §4.3; where that section is silent this document fixes a
canonical rendering (`devspec/asm.md` owns the assembler grammar;
integration verified the two agree — store operand order
`st.W [ea], rs3`, MADD shape `madd rd, rs1, rs2|imm, rs3`, and the FCVT
suffix/source-format tokens all match asm.md §5):

1. Mnemonics and register names lowercase; registers always `rN`/`pN`
   (never aliases). Predication prefix `(p3) ` / `(!p3) ` printed iff the
   pred field ≠ 0 (index = pred bits 3:1, `!` iff bit 0 = 1).
2. Width suffix: ALU/compare/atomic — `.32`/`.64`, no suffix for 128.
   Loads/stores — `.8`/`.16`/`.32`/`.64`; `ld128`/`st128` bare. FP
   arithmetic and FCMP — `.f32`/`.f64`. FCVT: integer destinations
   `.32`/`.64`/`.128`, FP destinations `.f32`/`.f64`; source format as
   trailing operand `f32`/`f64` (FP source) or `i32`/`i64`/`i128`
   (integer source).
3. Immediates print as lowercase hex `0x…` (minimal digits); a negative
   sign-extended imm22 prints as `-0x…` of its magnitude. Exceptions:
   B/JAL displacements print as **signed decimal** instruction counts;
   SHORI's zero-extended immediate prints as unsigned hex.
4. src2 modifier: append ` shl N` / ` sxt N` / ` zxt N` to the src2
   register iff mod ≠ 0 (kind ≠ 0 or amount ≠ 0 with kind 1–3).
5. Memory operand: `[rB]`, `[rB + rI]`, `[rB + rI shl N]`, `[rB + 0xD]`,
   `[rB - 0xD]`, or combinations in the order base, index, displacement.
   The index term is omitted iff src2 = 31 and mod = 0; the displacement
   iff imm = 0. Atomic ea has no index term: `[rB]` / `[rB + 0xD]`.
6. Operand shapes per family (operand codes from `encoding.py`):
   ALU `add rd, rs1, rs2|imm`; MADD `madd rd, rs1, rs2|imm, rs3`;
   compare `cmplt p3, rs1, rs2|imm` (pred index = dst & 7);
   loads `lds.32 rd, [ea]`; stores `st.32 [ea], rs3`;
   branches `b <disp>`, `jal rd, <disp>`, `jalr rd, rs1, 0xI`;
   constants `ldi rd, 0xI`, `shori rd, rs1, 0xI`, `lap rd, 0xI`;
   predicate file `prd rd`, `pwr rs1`;
   atomics `cas.64 rd, [ea], rs2, rs3`, `amoadd.64 rd, [ea], rs2`;
   FP `fadd.f32 rd, rs1, rs2`, `fsqrt.f64 rd, rs1`,
   `fmadd.f32 rd, rs1, rs2, rs3`, `fcmplt.f64 p3, rs1, rs2`;
   conversions `fcvtfi.64 rd, rs1, f32`;
   system `mfsr rd, <sregname>`, `mtsr <sregname>, rs1`, and bare
   `syscall`, `iret`, `invtp`, `ifence`, `wfi`, `halt`. Sreg names from
   `encoding.py` `SREGS`.
7. Any encoding that would trap ILLEGAL if executed un-squashed (unknown
   or odd-reserved opcode, reserved width value, mod kind 0 with nonzero
   amount, reserved FCVT format combination, out-of-range sreg index,
   INVTP with imm ≠ 0) renders as exactly `invalid`. Such encodings occur
   in EXEC records only for squashed instructions.
8. Fields a family does not use are ignored for rendering, matching
   hardware (ISA §3).

### 6.5 Queries

Unless stated, `TRACE` must be well-formed per §2.4 (torn tail allowed).

#### 6.5.1 `exec CYCLE`

Prints the EXEC line of the EXEC record with cycle = CYCLE, or nothing
(exit 1) if none exists (no instruction at that cycle: a TRAP or WFI-gap
cycle, or beyond end of trace).

#### 6.5.2 `at PC`

Prints, in file order, the EXEC line of every EXEC record whose pc equals
PC exactly.

#### 6.5.3 `last-write ADDR [--before CYCLE]`

A MEMW/DEVW record *covers* ADDR iff ea ≤ ADDR < ea + size. Prints the
record line of the **last** covering MEMW or DEVW in file order, filtered
to cycle < CYCLE when `--before` is given. Requires level ≥ 1 content;
with a level-0 trace the answer is always exit 1.

#### 6.5.4 `reg R --at CYCLE`

Reconstructed architectural value **after** all records with cycle ≤
CYCLE. For a GPR `rN`: the `wb` of the last EXEC in file order with
cycle ≤ CYCLE, `wrote-dst` = 1, and dst field of `insn` = N; if none, the
reset value 0. `r31` is always 0. For a predicate `pN`: bit N of
`pred_wb` of the last EXEC with cycle ≤ CYCLE and `wrote-pred` = 1; if
none, the reset file (p0 = 1, p1–p7 = 0). `p0` is always 1.
Output: `reg=<rN|pN> cycle=<dec> val=<hex128 for rN | 0|1 for pN>`.
CYCLE beyond the last record's cycle: exit 1.

#### 6.5.5 `find (--pc X | --wrote-reg R=V | --touched A) [--from C] [--to C]`

Exactly one selector required. Prints the record line of the **first**
matching record in file order with cycle in [C_from, C_to] (both
inclusive; defaults 0 and ∞):

- `--pc X`: EXEC with pc = X.
- `--wrote-reg R=V`: EXEC with `wrote-dst` = 1, dst = R, wb = V (full
  128-bit compare; R must be a GPR).
- `--touched A`: MEMW, DEVW, or MEMR covering A (MEMR present only at
  level 2).

#### 6.5.6 `diverge A.trc B.trc`

Compares record-by-record. Record 0 (META) is compared key-by-key with
run-variant keys (`mode`, `image`) excluded; records 1..n are compared as
raw bytes (header + payload). On the first difference, prints:

```
record=<ordinal> offset_a=<dec> offset_b=<dec>
a=<rendered record line, or the 3 characters "eof">
b=<rendered record line, or "eof">
```

offsets are the byte offsets of that record in each file. For a META key
difference: `record=0 key=<key>` then `a=<value|->`, `b=<value|->` (first
differing key in catalog order). If one trace is a strict prefix of the
other, the divergence is at the first missing ordinal with `eof` on the
shorter side. Identical traces: no output, exit 1. `--sym` is not
accepted; `a=`/`b=` record lines render with `sym=-`.

#### 6.5.7 `range C1 C2`

Prints, in file order, the EXEC and TRAP lines of all EXEC/TRAP records
with C1 ≤ cycle ≤ C2.

#### 6.5.8 `trapdump`

Prints the TRAP line of every TRAP record, in file order.

## 7. Conformance requirements

Numbered, testable; these feed CONFORMANCE.md (reference-implementation
checks group unless a statement binds all implementations' tools).

Format:

- **T-01** Every trace begins with exactly one META record containing
  exactly the seven §2.3.7 keys in catalog order; META appears nowhere
  else.
- **T-02** All multi-byte fields are little-endian; records and fields are
  packed with no padding; each record's payload length equals §2.1's
  table (EVENT: 20 + inner `payload_len`).
- **T-03** Reserved header bytes (offsets 1–3) are 0 in every record;
  EXEC flags bits 7:3 are 0.
- **T-04** Record cycle fields are non-decreasing in file order, and
  consecutive stamped cycles differ by more than 1 only across a WFI
  stall.
- **T-05** Cycle stamps are pre-increment values (§3.2): the first
  post-reset instruction's EXEC has cycle 0; an MFSR of `cycle` records a
  `wb` equal to its own EXEC record's cycle field.
- **T-06** An EXEC record exists for every retired instruction, including
  every predicated-false one, and for nothing else; a trapping instruction
  produces a TRAP record and no EXEC.
- **T-07** A TRAP record exists for every delivery, with cause/epc/baddr
  equal to the sreg values written and `tl_after` = TL after delivery;
  `baddr` = 0 for TIMER, EXTINT, ILLEGAL, SYSCALL, PRIV. A triple fault
  produces a final TRAP with `tl_after` = 3 and ends the trace.
- **T-08** Within one instruction, access records precede its EXEC and all
  share its cycle; an atomic's MEMR precedes its MEMW with no record
  between them; a failed CAS emits no MEMW; a squashed instruction emits
  no access records.
- **T-09** EVENT records applied at a boundary precede the TRAP or EXEC of
  the same cycle and appear in application order.
- **T-10** Level contents: level 0 = META+EXEC+TRAP+EVENT; level 1 adds
  MEMW+DEVW; level 2 adds MEMR; META `level` matches. Filtering a
  higher-level trace of a run to a lower level's record types reproduces
  the lower-level trace's post-META bytes exactly.
- **T-11** EXEC `wb` = 0 and `wrote-dst` = 0 whenever no GPR write
  occurred, including writes to r31 and all squashed instructions;
  `pred_wb` is the full 8-bit predicate file after the write when
  `wrote-pred` = 1, else 0.
- **T-12** MEMW/MEMR/DEVW value bytes above `size` are 0; stores to
  device space (including pixel/TX/RX buffers) record DEVW, stores to RAM
  record MEMW, all data loads record MEMR; fetches and page-table-walk
  reads are never recorded.
- **T-13** Timer interrupts produce no EVENT record; every external input
  (keyboard, mouse, NIC arrival, resize) produces exactly one EVENT
  record with the §4 payload for its device type, and `device` names an
  existing device-table entry.
- **T-14** Keyboard/mouse EVENT flag bit 0 is 1 exactly when the device
  model dropped the event on arrival (queue full); bits 7:1 are 0.
- **T-15** Resize EVENT payload equals the register values the event
  installs, with format = 1 in v1.0.
- **T-16** NIC EVENT payload bytes equal the RX-buffer-exposed frame
  bytes and `payload_len` equals the RX_LEN value for that frame.

Determinism and replay:

- **T-17** Two identical invocations (same image bytes, event feed,
  level, mode, image path) produce byte-identical `.trc` files.
- **T-18** Replay from image + EVENT records reproduces every post-META
  record byte-identically at the same level, EVENT records included.
- **T-19** Replay consults no host input, network, or clock.
- **T-20** Replay refuses to run (fatal error) on `image_sha256`,
  `encoding`, or `trace` mismatch.

Readers / `trace-q`:

- **T-21** A torn tail is accepted: complete-record prefix used, stderr
  diagnostic with offset and discarded byte count, exit codes unaffected.
- **T-22** Every §2.4 class-2 malformation is rejected with exit 2.
- **T-23** Exit codes follow §6.2 exactly: 0 = output produced, 1 = no
  matching facts, 2 = error.
- **T-24** Output formats match §6.3/§6.5 byte-for-byte (the §8 vectors
  are the acceptance data).
- **T-25** Symbol resolution follows §6.4: largest T/D address ≤ target,
  lexicographic tie-break, `name+0x…` form, `A` symbols never used.
- **T-26** `reg` reconstruction matches §6.5.4 including reset defaults,
  r31 ≡ 0, p0 ≡ 1.
- **T-27** `diverge` ignores run-variant META keys and reports the first
  difference with correct ordinal and per-file byte offsets; identical
  traces exit 1.
- **T-28** Disassembly renders the §6.4 canonical form; encodings that
  would trap ILLEGAL render as `invalid`.

## 8. Test vectors

All bytes verified mechanically against `encoding.py` (which self-checks
`OK`). Hex dumps are little-endian file bytes, offset-prefixed. These are
fixtures: a test feeds the bytes and compares outputs byte-exactly.

### TV-1 — reference image

Program (4 instructions at PA 0x1000):

| pc | source | insn (u64) | LE bytes |
|----|--------|-----------|----------|
| 0x1000 | `ldi r1, 0x5` | `0x0000140000001054` | `54 10 00 00 00 14 00 00` |
| 0x1008 | `add r2, r1, 0x7` | `0x00001e0000022003` | `03 20 02 00 00 1e 00 00` |
| 0x1010 | `st.64 [r2 + 0x4], r1` | `0x000013000fc40036` | `36 00 c4 0f 00 13 00 00` |
| 0x1018 | `halt` | `0x00000000000000fe` | `fe 00 00 00 00 00 00 00` |

(Note: the store's index-free ea is encoded with src2 = r31, mod = 0.)

`.img` file (TOOLING-SPEC §1: 32-byte header, one segment descriptor,
32 code bytes; 112 bytes total):

```
0000: 53 41 48 49 4d 47 30 31 00 10 00 00 00 00 00 00
0010: 00 00 00 00 00 00 00 00 01 00 00 00 00 00 00 00
0020: 00 10 00 00 00 00 00 00 00 00 00 00 00 00 00 00
0030: 50 00 00 00 00 00 00 00 20 00 00 00 00 00 00 00
0040: 20 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
0050: 54 10 00 00 00 14 00 00 03 20 02 00 00 1e 00 00
0060: 36 00 c4 0f 00 13 00 00 fe 00 00 00 00 00 00 00
```

`image_sha256 = f9d6f74caea6168036806d42309781440c66f16e46c60cadf8230eabb98d60e8`

Executed effects: cycle 0 `r1 ← 5`; cycle 1 `r2 ← 0xc`; cycle 2 stores
u64 5 at PA 0x10; cycle 3 halt.

### TV-2 — complete level-1 trace of TV-1 (449 bytes)

Record map:

| ordinal | offset | type | length | content |
|--------:|-------:|------|-------:|---------|
| 0 | 0 (0x000) | META | 168 | 160-byte payload, text below |
| 1 | 168 (0x0a8) | EXEC | 58 | cycle 0, pc 0x1000, wb 0x5, flags 0x02 |
| 2 | 226 (0x0e2) | EXEC | 58 | cycle 1, pc 0x1008, wb 0xc, flags 0x02 |
| 3 | 284 (0x11c) | MEMW | 49 | cycle 2, ea 0x10, size 8, new 0x5 |
| 4 | 333 (0x14d) | EXEC | 58 | cycle 2, pc 0x1010, wb 0, flags 0x00 |
| 5 | 391 (0x187) | EXEC | 58 | cycle 3, pc 0x1018, wb 0, flags 0x00 |

META payload text (LF line ends):

```
trace=1
encoding=1.0-draft
level=1
mode=live
image=example.img
image_sha256=f9d6f74caea6168036806d42309781440c66f16e46c60cadf8230eabb98d60e8
platform=1.0-draft
```

Full file hex:

```
0000: 07 00 00 00 a0 00 00 00 74 72 61 63 65 3d 31 0a
0010: 65 6e 63 6f 64 69 6e 67 3d 31 2e 30 2d 64 72 61
0020: 66 74 0a 6c 65 76 65 6c 3d 31 0a 6d 6f 64 65 3d
0030: 6c 69 76 65 0a 69 6d 61 67 65 3d 65 78 61 6d 70
0040: 6c 65 2e 69 6d 67 0a 69 6d 61 67 65 5f 73 68 61
0050: 32 35 36 3d 66 39 64 36 66 37 34 63 61 65 61 36
0060: 31 36 38 30 33 36 38 30 36 64 34 32 33 30 39 37
0070: 38 31 34 34 30 63 36 36 66 31 36 65 34 36 63 36
0080: 30 63 61 64 66 38 32 33 30 65 61 62 62 39 38 64
0090: 36 30 65 38 0a 70 6c 61 74 66 6f 72 6d 3d 31 2e
00a0: 30 2d 64 72 61 66 74 0a 01 00 00 00 32 00 00 00
00b0: 00 00 00 00 00 00 00 00 00 10 00 00 00 00 00 00
00c0: 00 00 00 00 00 00 00 00 54 10 00 00 00 14 00 00
00d0: 05 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00e0: 02 00 01 00 00 00 32 00 00 00 01 00 00 00 00 00
00f0: 00 00 08 10 00 00 00 00 00 00 00 00 00 00 00 00
0100: 00 00 03 20 02 00 00 1e 00 00 0c 00 00 00 00 00
0110: 00 00 00 00 00 00 00 00 00 00 02 00 02 00 00 00
0120: 29 00 00 00 02 00 00 00 00 00 00 00 10 00 00 00
0130: 00 00 00 00 00 00 00 00 00 00 00 00 08 05 00 00
0140: 00 00 00 00 00 00 00 00 00 00 00 00 00 01 00 00
0150: 00 32 00 00 00 02 00 00 00 00 00 00 00 10 10 00
0160: 00 00 00 00 00 00 00 00 00 00 00 00 00 36 00 c4
0170: 0f 00 13 00 00 00 00 00 00 00 00 00 00 00 00 00
0180: 00 00 00 00 00 00 00 01 00 00 00 32 00 00 00 03
0190: 00 00 00 00 00 00 00 18 10 00 00 00 00 00 00 00
01a0: 00 00 00 00 00 00 00 fe 00 00 00 00 00 00 00 00
01b0: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
01c0: 00
```

Field-by-field decode of record 1 (EXEC, file offset 0x0a8):

| bytes (offset in record) | field | value |
|---|---|---|
| 0: `01` | type | 1 (EXEC) |
| 1–3: `00 00 00` | reserved | 0 |
| 4–7: `32 00 00 00` | payload length | 50 |
| 8–15: `00…00` | cycle | 0 |
| 16–31: `00 10 00…00` | pc | 0x1000 |
| 32–39: `54 10 00 00 00 14 00 00` | insn | 0x0000140000001054 |
| 40–55: `05 00…00` | wb | 0x5 |
| 56: `02` | flags | wrote-dst |
| 57: `00` | pred_wb | 0 |

Field-by-field decode of record 3 (MEMW, file offset 0x11c):

| bytes | field | value |
|---|---|---|
| `02` | type | 2 (MEMW) |
| `00 00 00` | reserved | 0 |
| `29 00 00 00` | payload length | 41 |
| `02 00 00 00 00 00 00 00` | cycle | 2 |
| `10 00…00` (16) | ea | 0x10 |
| `08` | size | 8 |
| `05 00…00` (16) | new | 0x5 |

### TV-3 — keyboard EVENT record

Key 'A' press (HID usage 0x04 — usage table owned by `devspec/input.md`),
applied at cycle 500, keyboard at device index 1 (reference table order
per `devspec/boot.md`: 0 display, 1 keyboard, 2 mouse, 3 nic). Payload
9 bytes; record 37 bytes:

```
05 00 00 00 1d 00 00 00 f4 01 00 00 00 00 00 00
01 00 00 00 00 00 00 00 09 00 00 00 04 00 00 00
01 00 00 00 00
```

Decode: type 5, len 29; cycle 500; device 1; payload_len 9; event word
`0x0000000100000004` (usage 4, press); flags 0x00 (not dropped).
The same event dropped on overflow differs in exactly the final byte:
`… 01` (flags bit 0).

### TV-4 — mouse EVENT payload (9 bytes)

x = 100, y = 50, left button down, not dropped:
word `0x0000000100320064`, payload `64 00 32 00 01 00 00 00 00`.

### TV-5 — display resize EVENT payload (32 bytes)

width 800, height 600, stride 3200, format 1:

```
20 03 00 00 00 00 00 00 58 02 00 00 00 00 00 00
80 0c 00 00 00 00 00 00 01 00 00 00 00 00 00 00
```

### TV-6 — NIC frame EVENT record (88 bytes)

A 60-byte ARP reply (10.0.2.2 is-at 52:55:0a:00:02:02 — the translator
peer MAC of `devspec/nic.md` §6.1 — unicast to the guest MAC
52:54:00:12:34:56; the frame is `devspec/nic.md` vector TV-2
byte-for-byte), arriving at cycle 1000, NIC at device index 3:

```
0000: 05 00 00 00 50 00 00 00 e8 03 00 00 00 00 00 00
0010: 03 00 00 00 00 00 00 00 3c 00 00 00 52 54 00 12
0020: 34 56 52 55 0a 00 02 02 08 06 00 01 08 00 06 04
0030: 00 02 52 55 0a 00 02 02 0a 00 02 02 52 54 00 12
0040: 34 56 0a 00 02 0f 00 00 00 00 00 00 00 00 00 00
0050: 00 00 00 00 00 00 00 00
```

Decode: type 5, len 80; cycle 1000; device 3; payload_len 60; then the
frame: dst 52:54:00:12:34:56, src 52:55:0a:00:02:02, ethertype 0x0806,
ARP reply, 18 zero pad bytes to the 60-byte minimum. (An ARP *request*
arriving at the guest cannot occur on the reference platform — the
translator never ARPs the guest, nic.md §6.3 — so the fixture uses the
reply the translator actually sends.)

### TV-7 — symbol sidecar and resolution

`example.sym`:

```
00000000000000000000000000000010 D result
00000000000000000000000000001000 T _start
00000000000000000000000000001010 T store_it
```

Expected resolutions:

| address | sym |
|---|---|
| 0x1000 | `_start` |
| 0x1008 | `_start+0x8` |
| 0x1010 | `store_it` |
| 0x1018 | `store_it+0x8` |
| 0x10 | `result` |
| 0x8 | `-` (no symbol ≤ address) |

### TV-8 — `trace-q` expected outputs against TV-2

Each entry: command, exact stdout (byte-for-byte, one trailing LF per
line), exit code. `t.trc` = TV-2 bytes; `t.sym` = TV-7.

1. `trace-q --sym t.sym exec 2 t.trc` — exit 0:

```
cycle=2 pc=0x00000000000000000000000000001010 sym=store_it insn=0x000013000fc40036 squashed=0 wb=- pred=- asm=st.64 [r2 + 0x4], r1
```

2. `trace-q exec 2 t.trc` (no sym) — exit 0: same line with `sym=-`.

3. `trace-q exec 5 t.trc` — no output, exit 1 (no cycle 5).

4. `trace-q at 0x1008 t.trc` — exit 0:

```
cycle=1 pc=0x00000000000000000000000000001008 sym=- insn=0x00001e0000022003 squashed=0 wb=0x0000000000000000000000000000000c pred=- asm=add r2, r1, 0x7
```

5. `trace-q --sym t.sym last-write 0x12 t.trc` — exit 0 (0x12 is covered
   by the 8-byte write at 0x10):

```
type=MEMW cycle=2 ea=0x00000000000000000000000000000010 sym=result size=8 val=0x00000000000000000000000000000005
```

6. `trace-q last-write 0x12 --before 2 t.trc` — no output, exit 1.

7. `trace-q reg r2 --at 3 t.trc` — exit 0:

```
reg=r2 cycle=3 val=0x0000000000000000000000000000000c
```

8. `trace-q reg r9 --at 3 t.trc` — exit 0 (reset value):

```
reg=r9 cycle=3 val=0x00000000000000000000000000000000
```

9. `trace-q find --wrote-reg r2=0xc t.trc` — exit 0: the same line as
   output 4.

10. `trace-q find --touched 0x10 --from 0 --to 3 t.trc` — exit 0: the
    same line as output 5 with `sym=-`.

11. `trace-q range 0 3 t.trc` — exit 0, four lines:

```
cycle=0 pc=0x00000000000000000000000000001000 sym=- insn=0x0000140000001054 squashed=0 wb=0x00000000000000000000000000000005 pred=- asm=ldi r1, 0x5
cycle=1 pc=0x00000000000000000000000000001008 sym=- insn=0x00001e0000022003 squashed=0 wb=0x0000000000000000000000000000000c pred=- asm=add r2, r1, 0x7
cycle=2 pc=0x00000000000000000000000000001010 sym=- insn=0x000013000fc40036 squashed=0 wb=- pred=- asm=st.64 [r2 + 0x4], r1
cycle=3 pc=0x00000000000000000000000000001018 sym=- insn=0x00000000000000fe squashed=0 wb=- pred=- asm=halt
```

    (Note `insn` always prints 16 hex digits: `0x00000000000000fe`.)

12. `trace-q trapdump t.trc` — no output, exit 1 (trap-free trace).

### TV-9 — truncation

`t430.trc` = the first 430 bytes of TV-2 (record 5 torn: 39 of its 58
bytes present). Any `trace-q` query on it must print a stderr diagnostic
containing the offset `391` and the count `39`, and behave as if the
trace had records 0–4 only: `trace-q exec 3 t430.trc` → no stdout,
exit 1; `trace-q exec 2 t430.trc` → identical stdout to TV-8 output 2,
exit 0.

By contrast, flipping byte 1 of TV-2 (a reserved header byte) to `01`
must make every query exit 2.

### TV-10 — diverge

`u.trc` = TV-2 with record 2's `wb` field changed from 0xc to 0xd (one
byte, file offset 266 (0x10a), value `0c` → `0d`).

`trace-q diverge t.trc u.trc` — exit 0:

```
record=2 offset_a=226 offset_b=226
a=cycle=1 pc=0x00000000000000000000000000001008 sym=- insn=0x00001e0000022003 squashed=0 wb=0x0000000000000000000000000000000c pred=- asm=add r2, r1, 0x7
b=cycle=1 pc=0x00000000000000000000000000001008 sym=- insn=0x00001e0000022003 squashed=0 wb=0x0000000000000000000000000000000d pred=- asm=add r2, r1, 0x7
```

`trace-q diverge t.trc t.trc` — no output, exit 1.

`v.trc` = TV-2 with META `image=other.img`: `diverge t.trc v.trc` — no
output, exit 1 (`image` is run-variant; note the offsets of later records
differ between the files, which is why diverge compares records, not
offsets).

---

*Issues raised against frozen specs and dependencies on sibling devspec
documents are reported in the authoring hand-off, not restated here.*
