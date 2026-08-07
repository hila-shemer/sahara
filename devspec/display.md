# Sahara Display Device — Detailed Specification

**Version 1.0-draft.** Companion to ISA-SPEC.md and PLATFORM-SPEC.md,
expanding PLATFORM-SPEC.md section 4 (display) into an independently
implementable specification. Where this document restates a value fixed by
a frozen spec, the frozen spec wins on any discrepancy; restated values are
marked with their source. Non-normative material appears in indented
*Note:* lines. Everything else is normative.

Shared semantics owned elsewhere are referenced, never defined here:

- Resize EVENT payload encoding and event/trace record formats: per
  devspec/trace.md §EVENT.
- Device table byte layout: per devspec/boot.md (values summarized in
  section 2 below from PLATFORM-SPEC §2).
- Instruction-level ordering and trap semantics: ISA-SPEC.md sections 3.2,
  4, 5.4, 7.1, 9.2.

---

## 1. Overview and discovery

The display is an output device: a guest-writable pixel buffer plus a
control-register window. The guest draws pixels into the buffer, then
writes the PRESENT register; the emulator shows the resulting frame to the
host user (GUI mode) or records it (headless mode). The only guest-visible
inputs from the display are the geometry registers and the resize
interrupt.

The guest discovers the display from the device table (PLATFORM-SPEC §2,
layout owned by devspec/boot.md): a device entry with `type = 1`, whose
`base` is the control-window physical address, `size` the control-window
size, `params[0]` the pixel buffer physical address, `params[1]` the pixel
buffer window size in bytes, and `params[2]`–`params[3]` zero.

Reference platform defaults (PLATFORM-SPEC §1; the device table is
authoritative):

| item | value |
|------|-------|
| control window base | PA 0x0F00_0000 |
| control window size | 64 KB (0x1_0000 bytes) |
| pixel buffer base | PA 0x1000_0000 |
| pixel buffer window size | 16 MB (0x100_0000 bytes) — reference default fixed by this document |
| initial mode | WIDTH 640, HEIGHT 480, STRIDE 2560, FORMAT 1 — reference default fixed by this document |

Both windows are device space in the sense of ISA-SPEC §9.2. The pixel
buffer base PA must be 16-byte aligned; the control window base must be
64 KB aligned.

The initial mode is emulator configuration, fixed before reset and
identical between a recording run and its replay; it is recorded in the
trace META record (key catalog per devspec/trace.md §META).

---

## 2. Control window access model

Restated from PLATFORM-SPEC §1 (frozen): control-window registers are 64
bits wide, naturally aligned, and must be accessed with 64-bit loads and
stores; any other access size traps `DEVERR` with `baddr` = the effective
address. This document adds the following normative access rules for the
display control window, per the project loud-failure policy:

1. A load (any width) from a write-only register (PRESENT, IRQ_ACK) traps
   `DEVERR`, `baddr` = ea.
2. A store (any width) to a read-only register (WIDTH, HEIGHT, STRIDE,
   FORMAT, IRQ_STATUS) traps `DEVERR`, `baddr` = ea.
3. Any atomic operation (CAS, AMO*) targeting the control window or the
   pixel buffer traps `DEVERR` (ISA-SPEC §5.4 / §9.2; both windows are
   device space).
4. A misaligned access traps `UNALIGNED` before any device semantics apply
   (ISA-SPEC §5.3); `DEVERR` checks are reached only by aligned accesses.
5. Offsets 0x38 through the end of the control window are the reserved
   extension window (section 8): 64-bit reads return 0, 64-bit writes are
   ignored, no fault (frozen by PLATFORM-SPEC §4). Non-64-bit accesses to
   reserved offsets trap `DEVERR` like any other control-window access.
6. An instruction whose predicate evaluates false performs no device
   access and cannot trap (ISA-SPEC §3.2): a predicated-false store to
   PRESENT presents nothing; a predicated-false wrong-size access does not
   trap `DEVERR`.

Register map (offsets from control window base; frozen by PLATFORM-SPEC
§4; semantics elaborated by this document):

| off | reg | access | semantics |
|----:|-----|--------|-----------|
| 0x00 | PRESENT | W | present a frame (section 5); the 64-bit stored value is ignored |
| 0x08 | WIDTH | R | current frame width in pixels; >= 1; fits in 32 bits (bits 63:32 read 0) |
| 0x10 | HEIGHT | R | current frame height in pixels; >= 1; fits in 32 bits (bits 63:32 read 0) |
| 0x18 | STRIDE | R | bytes from the start of row y to the start of row y+1; constraints in section 4.3 |
| 0x20 | FORMAT | R | pixel format code; always 1 (XRGB8888 little-endian) in v1.0 |
| 0x28 | IRQ_STATUS | R | bit 0 = mode-changed (resize) pending; bits 63:1 reserved, read 0 |
| 0x30 | IRQ_ACK | W | bit 0 = 1 clears IRQ_STATUS bit 0; bit 0 = 0 is a no-op; a store with any of bits 63:1 set traps `DEVERR`, `baddr` = ea, and clears nothing |
| 0x38+ | reserved | | extension window, section 8 |

A guest reading FORMAT != 1 must treat the display as unusable and fail
loudly; it must not guess a pixel layout.

> *Note: PLATFORM-SPEC §4 gives the offsets in decimal (0, 8, 16, 24, 32,
> 40, 48, 56+); the hex values above are the same offsets.*

---

## 3. Pixel buffer

### 3.1 Memory-like semantics

The pixel buffer window (`params[1]` bytes starting at `params[0]`)
accepts all access sizes (1, 2, 4, 8, 16 bytes), naturally aligned, with
ordinary load/store instructions (frozen by PLATFORM-SPEC §1). It behaves
as memory: a load returns the bytes most recently stored at those
addresses. Loads have no side effects. At reset the entire window reads as
zero. The emulator never writes the pixel buffer: no operation of the
display device — including PRESENT and resize — modifies buffer contents.
Bytes outside the current frame geometry but inside the window are stored
and readable like any others; they merely do not appear in presented
frames.

Atomics to the window trap `DEVERR` (section 2 rule 3). For ordering the
window is device space: pixel-buffer accesses and control-register
accesses are mutually ordered in program order (ISA-SPEC §9.2 rule 2).

Accesses outside both display windows are governed by the platform memory
map, not this document.

### 3.2 Pixel format: XRGB8888 little-endian

FORMAT code 1, the only v1.0 format. Each pixel is 4 bytes. As a 32-bit
little-endian value:

    bits  7:0  = B (blue,  0-255)
    bits 15:8  = G (green, 0-255)
    bits 23:16 = R (red,   0-255)
    bits 31:24 = X (ignored)

Equivalently, in increasing byte-address order in memory: byte 0 = B,
byte 1 = G, byte 2 = R, byte 3 = X.

The X byte has no semantics: it is not alpha, it does not affect the
presented image in any way, the guest may store any value there, and the
emulator must neither interpret it nor alter it (it reads back exactly as
stored, per section 3.1). Two buffer states differing only in X bytes
present identical images.

Color values are full-range (0 = none, 255 = full intensity), sRGB by
convention; the emulator passes them to the host display system unmodified.

### 3.3 Geometry and addressing

The address of pixel (x, y), 0 <= x < WIDTH, 0 <= y < HEIGHT:

    pixel_pa(x, y) = params[0] + y * STRIDE + 4 * x

**Frame snapshot** (the unit tests and presentation operate on): the byte
string formed by concatenating, for y = 0 to HEIGHT-1 in order, the
4*WIDTH bytes at [params[0] + y*STRIDE, params[0] + y*STRIDE + 4*WIDTH).
Its length is 4 * WIDTH * HEIGHT. Padding bytes (offsets 4*WIDTH .. STRIDE-1
of each row) are not part of the snapshot.

**Presented image**: the WIDTH x HEIGHT array of (R, G, B) triples decoded
from the frame snapshot per section 3.2, X bytes discarded.

### 3.4 Geometry constraints

At all times — at reset and after every resize — the published geometry
must satisfy all of:

1. `WIDTH >= 1`, `HEIGHT >= 1`; both fit in 32 bits.
2. `STRIDE >= 4 * WIDTH`.
3. `STRIDE mod 16 == 0` (with the 16-byte-aligned buffer base, every row
   start is 16-byte aligned, so rows can be filled with ST128).
4. `HEIGHT * STRIDE <= params[1]` (the frame fits in the window).
5. `WIDTH * STRIDE <= params[1]` (PLATFORM-SPEC §4, restated verbatim; see
   the *Note* below).

`FORMAT`, the pixel buffer PA (`params[0]`), and the window size
(`params[1]`) never change after the device table is written; only WIDTH,
HEIGHT, and STRIDE change, and only via the resize mechanism of section 6.
STRIDE is chosen by the emulator; guests must always compute row addresses
from STRIDE and must not assume `STRIDE == 4 * WIDTH`.

> *Note: PLATFORM-SPEC §4 states the bound as "WIDTH*STRIDE never exceeds
> the window size", but the frame actually occupies HEIGHT*STRIDE bytes.
> This document conservatively requires both products to be within the
> window; the discrepancy is recorded as a spec issue for resolution.*

---

## 4. Register semantics in detail

- **WIDTH, HEIGHT, STRIDE**: read the current geometry. The three values
  read by any sequence of loads with no intervening resize event are
  mutually consistent (they update atomically; section 6.2).
- **FORMAT**: reads 1. No mechanism changes it in v1.0; a resize never
  changes FORMAT.
- **IRQ_STATUS**: bit 0 reads 1 from the delivery of a resize event until
  the next IRQ_ACK store with bit 0 set; otherwise 0. Bits 63:1 read 0.
  Reading IRQ_STATUS has no side effect.
- **IRQ_ACK**: store of value 1 clears IRQ_STATUS bit 0 unconditionally
  (no-op if already clear). Store of value 0 does nothing. Store of any
  value with bits 63:1 nonzero traps `DEVERR` and does not clear.
- **PRESENT**: section 5.

---

## 5. PRESENT

A 64-bit store to PRESENT presents one frame. The stored value is ignored
(frozen by PLATFORM-SPEC §4); any 64-bit value is legal.

**Snapshot semantics.** The presented frame is the frame snapshot (section
3.3) computed from the pixel buffer contents and the geometry (WIDTH,
HEIGHT, STRIDE) as they are at the moment the PRESENT store takes effect —
after every prior store in program order, before every later access.

**Ordering.** Two frozen rules of ISA-SPEC §9.2 make this exact:

1. The PRESENT store is a store to device space, hence a release fence:
   all prior *ordinary* (non-device) stores in program order are complete
   before it takes effect. Any staging of pixel data through ordinary RAM
   that was copied into the buffer by prior stores is therefore included.
2. The pixel buffer is itself device space, and device loads/stores are
   mutually ordered in program order, so every pixel-buffer store that
   precedes the PRESENT store in program order is included in the
   snapshot, and no later store is.

Consequently a conforming guest needs no barrier instruction: draw, then
store PRESENT.

**Effect.** Presentation is pure output. It does not modify the pixel
buffer, the registers, IRQ_STATUS, or any architectural state; it raises
no interrupt; it consumes no extra cycles beyond the store instruction
itself. In the execution trace it appears as the store's DEVW record (per
devspec/trace.md); no additional record type exists for frames, because
the frame content is a deterministic function of the trace up to that
point.

**Frequency.** Any number of PRESENT stores is legal, including zero
(nothing is ever displayed) and back-to-back stores (each presents a
frame; the host may drop displayed frames visually, but the architectural
sequence of presented snapshots is well defined and is what conformance
tests check).

If the machine halts or traps between drawing and PRESENT, no frame is
presented; there is no implicit presentation.

---

## 6. Resize

### 6.1 Model

The host window size is not architectural state. When it changes, the
emulator *may* (GUI mode) generate a **resize event**: an entry in the
synchronous event queue of ISA-SPEC §4, `(cycle, device, payload)`, where
the payload carries the new WIDTH, HEIGHT, and STRIDE (payload encoding
owned by devspec/trace.md §EVENT). The chosen geometry must satisfy
section 3.4. In replay mode resize events come exclusively from the trace
and the host window is not consulted (PLATFORM-SPEC §§7-8 pattern; trace
semantics per devspec/trace.md).

The emulator may coalesce rapid host resizes into fewer events; which
host changes become events, and at what cycles, is the emulator's choice
in live mode — but once assigned, each event is in the trace and its
delivery is deterministic. Every delivered resize event appears as an
EVENT record.

### 6.2 Delivery

A resize event with cycle C is processed at the first between-instructions
boundary at which `cycle >= C` (the same recognition points as interrupts,
ISA-SPEC §7.5; exact interleaving with instruction retirement and trace
records is elaborated by devspec/trace.md). Processing performs, as one
atomic action:

1. WIDTH, HEIGHT, STRIDE are set to the event's values — all three
   together. No instruction can observe a partial update: any instruction
   executes either entirely before or entirely after the update.
2. IRQ_STATUS bit 0 is set to 1 (idempotent if already 1).

The pixel buffer PA, the window size, FORMAT, and the pixel buffer
*contents* do not change (frozen by PLATFORM-SPEC §4 and section 3.1).
Event processing consumes no cycles by itself; if it causes an interrupt,
the delivery consumes one cycle per ISA-SPEC §7.2.

### 6.3 Interrupt

The display's contribution to EXTINT (cause 1) is level-triggered:
pending exactly while `IRQ_STATUS != 0` (frozen by PLATFORM-SPEC §3).
EXTINT is the OR of all devices' conditions; clearing the display (IRQ_ACK
bit 0) deasserts only the display's contribution. Delivery follows
ISA-SPEC §7.5 (only between instructions, only when `status.IE = 1`;
masking defers, never cancels, a level condition).

### 6.4 Pending/ack protocol and resizes outpacing acks

There is no queue of pending geometries: the registers always hold the
geometry of the most recent delivered event, and bit 0 is a single sticky
flag.

- Several resize events delivered before the guest acks: each updates the
  registers; bit 0 simply stays 1. Intermediate geometries are observable
  only if the guest happens to read between deliveries; a guest that reads
  only after its interrupt sees the latest. Nothing is lost that matters:
  the flag says "geometry changed at least once", the registers say what
  it is now.
- A resize event delivered after an IRQ_ACK sets bit 0 again, asserting a
  new interrupt.
- An IRQ_ACK store and an event delivery never interleave: the store is an
  instruction, the delivery is between instructions, and the trace fixes
  their order deterministically. Whichever is architecturally later wins
  (ack-then-event leaves bit 0 = 1; event-then-ack leaves bit 0 = 0 with
  the new geometry in the registers).

**Race-free handler pattern** (normative recommendation): on a display
interrupt, *first* store IRQ_ACK = 1, *then* read WIDTH/HEIGHT/STRIDE.
Device accesses are program-ordered, so a resize event landing after the
ack but before the reads sets bit 0 (a new interrupt will follow) *and*
the reads already return its geometry — the guest may redundantly handle
one geometry twice but can never miss the final one. The reverse order
(read, then ack) can ack away an event that arrived between read and ack,
leaving the guest with stale geometry and no pending interrupt until the
next event.

### 6.5 Letterbox/crop

Between a resize event and the guest's next PRESENT, the host-visible
window may show the previous frame letterboxed, cropped, scaled, or
blanked. This is cosmetic, unspecified, has no guest-visible effect,
produces no trace records, and is exempt from determinism requirements
(frozen by PLATFORM-SPEC §4). The architectural sequence of presented
frame snapshots is unaffected.

Headless mode never generates resize events on its own; it delivers
exactly the events in the input trace.

---

## 7. Determinism

All display behavior is a deterministic function of (initial mode, guest
execution, resize events). Given the same image, the same initial mode,
and the same event trace: every register read returns the same value at
the same cycle, IRQ_STATUS transitions at the same cycles, and the
sequence of (cycle, frame snapshot) pairs produced by PRESENT stores is
byte-identical. The emulator must not consult the host window, wall
clocks, or any non-deterministic source for any guest-visible display
value (ISA-SPEC §4). Host-side rendering (vsync, frame dropping, window
decoration) is outside the deterministic boundary.

---

## 8. Reserved extension window (dirty-rect / command)

Offsets 0x38 up to the end of the control window (0xFFF8 inclusive on the
reference platform's 64 KB window) are reserved. In v1.0: 64-bit reads
return 0, 64-bit writes are ignored, no fault (frozen by PLATFORM-SPEC
§4).

Assignments for future versions (reserved now so v1.0 guests and the v1.0
emulator behave compatibly later):

- **0x38 CAPS (R)**: capability bit vector. v1.0's read-as-0 is the
  defined "no capabilities" value; a future version sets one bit per
  optional feature. Bit 0 is reserved for the dirty-rectangle extension.
- **0x40–0x78**: reserved for the dirty-rectangle extension (rectangle
  coordinate registers and a submit doorbell — precise layout defined by
  the future revision that sets CAPS bit 0).
- **0x80 and above**: reserved for a command-queue extension and future
  use.

What a future version may never do:

1. Repurpose or alter the semantics of offsets 0x00–0x30 (the v1.0
   registers) or of the CAPS register's read-0 meaning.
2. Give any reserved offset default-on behavior. Every future feature must
   be opt-in: inert (reads 0 or a discoverable constant, writes without
   architectural effect) until the guest explicitly enables it through a
   mechanism advertised by CAPS. A v1.0 guest that never reads CAPS and
   never writes the reserved window must observe exactly v1.0 behavior on
   every future emulator.
3. Make reads of any reserved offset have side effects while the feature
   owning that offset is disabled.
4. Move the pixel buffer, change FORMAT code 1's meaning, or change the
   resize/ack protocol of section 6 for guests that have enabled nothing.

---

## 9. Conformance requirements

Numbered, testable; each is a required behavior of a conforming
implementation. "ea" is the access's effective (physical) address; CW =
control window base; PB = pixel buffer base. These feed CONFORMANCE.md
group C7 (memory and devices) except D-22/D-23, which feed the
reference-implementation-only checks.

- **D-01** A 64-bit load from CW+0x20 (FORMAT) returns 1.
- **D-02** For every defined register offset (0x00–0x30) and every reserved
  offset, an aligned load or store of size 1, 2, 4, or 16 bytes traps
  `DEVERR` with cause 12 and `baddr` = ea; no register or buffer state
  changes.
- **D-03** A 64-bit load from CW+0x00 (PRESENT) or CW+0x30 (IRQ_ACK)
  traps `DEVERR`, `baddr` = ea.
- **D-04** A 64-bit store to CW+0x08, 0x10, 0x18, 0x20, or 0x28 traps
  `DEVERR`, `baddr` = ea; the register value is unchanged afterward.
- **D-05** A 64-bit load from any reserved offset (0x38 to end of window,
  8-byte steps) returns 0; a 64-bit store there is ignored (no fault, no
  observable state change).
- **D-06** Any CAS or AMO* instruction with ea in the control window or
  the pixel buffer traps `DEVERR`, `baddr` = ea; memory at ea is unchanged.
- **D-07** Pixel buffer stores of sizes 1, 2, 4, 8, and 16 (naturally
  aligned) succeed; a subsequent load of any size covering the same bytes
  returns exactly the stored bytes (last-write-wins per byte).
- **D-08** Every pixel buffer byte reads 0 before its first store after
  reset.
- **D-09** Neither a PRESENT store nor a resize event changes any pixel
  buffer byte.
- **D-10** At reset and after every resize event, the geometry satisfies:
  WIDTH >= 1; HEIGHT >= 1; WIDTH < 2^32; HEIGHT < 2^32; STRIDE >= 4*WIDTH;
  STRIDE mod 16 == 0; HEIGHT*STRIDE <= window size; WIDTH*STRIDE <=
  window size. WIDTH/HEIGHT/STRIDE loads return values with bits 63:32
  (63: any unused) zero.
- **D-11** The frame snapshot presented by a PRESENT store equals the
  concatenation over y in [0, HEIGHT) of the 4*WIDTH bytes at
  PB + y*STRIDE, using the geometry current at the PRESENT store; row
  padding bytes are excluded.
- **D-12** Two pixel buffer states identical except in X bytes (byte 3 of
  each pixel) produce identical presented images (R, G, B extraction per
  section 3.2: byte 0 = B, byte 1 = G, byte 2 = R).
- **D-13** All pixel-buffer stores preceding a PRESENT store in program
  order are reflected in its snapshot; no store following it is. (Trace
  check: every MEMW/DEVW to the snapshot's byte range before the PRESENT
  DEVW record is included.)
- **D-14** A PRESENT store's 64-bit value does not affect the presented
  frame or any state: storing 0, 1, and 0xFFFF_FFFF_FFFF_FFFF over the
  same buffer contents presents identical snapshots.
- **D-15** A predicated-false store to PRESENT presents no frame; a
  predicated-false 8-bit store to a register offset raises no `DEVERR`;
  both retire and advance `cycle` by 1 (ISA-SPEC §3.2).
- **D-16** Delivery of a resize event updates WIDTH, HEIGHT, and STRIDE
  atomically to the event's values and sets IRQ_STATUS bit 0; no
  instruction observes a mix of old and new geometry values.
- **D-17** IRQ_STATUS bit 0 reads 1 from resize delivery until an IRQ_ACK
  store with bit 0 set; bits 63:1 of IRQ_STATUS always read 0; reading
  IRQ_STATUS does not clear it.
- **D-18** Storing 1 to IRQ_ACK clears IRQ_STATUS bit 0; storing 0 changes
  nothing; storing any value with a bit other than bit 0 set (e.g. 2,
  0x8000_0000_0000_0001) traps `DEVERR` and IRQ_STATUS is unchanged.
- **D-19** The display's EXTINT contribution is pending exactly while
  IRQ_STATUS != 0: with IE = 1 and no other device pending, EXTINT (cause
  1) delivers after resize delivery and stops being pending after IRQ_ACK;
  with IE = 0 it stays pending (delivered when IE is set) and is never
  lost.
- **D-20** Two resize events delivered with no intervening IRQ_ACK leave
  the registers holding the second event's geometry and IRQ_STATUS bit
  0 = 1; a single IRQ_ACK then clears it.
- **D-21** A resize event delivered after an IRQ_ACK sets IRQ_STATUS bit 0
  again (a new interrupt becomes pending).
- **D-22** (reference implementation) Replaying a trace containing resize
  EVENT records and PRESENT stores reproduces byte-identical register read
  values, TRAP records, and the identical sequence of (cycle, frame
  snapshot) pairs, without consulting the host window system.
- **D-23** (reference implementation) FORMAT, the pixel buffer PA, and the
  pixel buffer window size are identical before and after every resize
  event in any trace.

---

## 10. Test vectors

All multi-byte values little-endian. CW = control window base (reference:
0x0F00_0000), PB = pixel buffer base (reference: 0x1000_0000). Each vector
is data for one executable fixture.

### V1 — pixel encoding (section 3.2)

Columns: name; (R,G,B,X); pixel as u32; bytes at increasing addresses.

| name | R | G | B | X | u32 value | byte 0 | byte 1 | byte 2 | byte 3 |
|------|---|---|---|---|-----------|--------|--------|--------|--------|
| black | 0x00 | 0x00 | 0x00 | 0x00 | 0x00000000 | 00 | 00 | 00 | 00 |
| white | 0xFF | 0xFF | 0xFF | 0x00 | 0x00FFFFFF | FF | FF | FF | 00 |
| red   | 0xFF | 0x00 | 0x00 | 0x00 | 0x00FF0000 | 00 | 00 | FF | 00 |
| green | 0x00 | 0xFF | 0x00 | 0x00 | 0x0000FF00 | 00 | FF | 00 | 00 |
| blue  | 0x00 | 0x00 | 0xFF | 0x00 | 0x000000FF | FF | 00 | 00 | 00 |
| gray  | 0x80 | 0x80 | 0x80 | 0x00 | 0x00808080 | 80 | 80 | 80 | 00 |
| X-junk | 0x12 | 0x34 | 0x56 | 0xFF | 0xFF123456 | 56 | 34 | 12 | FF |

Check for each row: store u32 at PB, load 4 bytes, compare; presented
color of the pixel is (R, G, B) — the X-junk row presents identically to
storing 0x00123456.

### V2 — pixel addressing (section 3.3)

Geometry: WIDTH = 640, HEIGHT = 480, STRIDE = 2560 (0xA00), PB =
0x1000_0000. Columns: (x, y); expected pixel_pa.

| x | y | pixel_pa |
|---:|---:|----------|
| 0 | 0 | 0x1000_0000 |
| 1 | 0 | 0x1000_0004 |
| 639 | 0 | 0x1000_09FC |
| 0 | 1 | 0x1000_0A00 |
| 5 | 7 | 0x1000_4614 |
| 639 | 479 | 0x1012_BFFC |

Check: pixel_pa = PB + y*STRIDE + 4*x. Frame snapshot length =
4*640*480 = 1,228,800 = 0x12_C000 bytes; last snapshot byte is at
0x1012_BFFF; HEIGHT*STRIDE = 1,228,800 <= 0x100_0000 (window).

### V3 — access matrix (sections 2, 4; conformance D-01..D-08)

Columns: address; operation (LD/ST/AMOADD); size in bytes; store value if
ST; expected outcome (`OK[=v]` = succeeds [load returns v], `DEVERR` =
trap cause 12 with baddr = address). Machine state: reset defaults,
supervisor, MMU off, IRQ_STATUS = 0. Rows execute in order.

| # | address | op | size | value | expected |
|--:|---------|----|-----:|-------|----------|
| 1 | CW+0x20 | LD | 8 | | OK=1 |
| 2 | CW+0x08 | LD | 8 | | OK=640 |
| 3 | CW+0x10 | LD | 8 | | OK=480 |
| 4 | CW+0x18 | LD | 8 | | OK=2560 |
| 5 | CW+0x28 | LD | 8 | | OK=0 |
| 6 | CW+0x00 | LD | 8 | | DEVERR |
| 7 | CW+0x30 | LD | 8 | | DEVERR |
| 8 | CW+0x08 | ST | 8 | 123 | DEVERR |
| 9 | CW+0x28 | ST | 8 | 0 | DEVERR |
| 10 | CW+0x20 | LD | 4 | | DEVERR |
| 11 | CW+0x20 | LD | 2 | | DEVERR |
| 12 | CW+0x20 | LD | 1 | | DEVERR |
| 13 | CW+0x20 | LD | 16 | | DEVERR |
| 14 | CW+0x00 | ST | 4 | 1 | DEVERR |
| 15 | CW+0x38 | LD | 8 | | OK=0 |
| 16 | CW+0x38 | ST | 8 | 0xFFFFFFFFFFFFFFFF | OK (ignored) |
| 17 | CW+0x38 | LD | 8 | | OK=0 |
| 18 | CW+0xFFF8 | LD | 8 | | OK=0 |
| 19 | CW+0x40 | LD | 4 | | DEVERR |
| 20 | CW+0x00 | AMOADD | 8 | 1 | DEVERR |
| 21 | PB+0x00 | AMOADD | 8 | 1 | DEVERR |
| 22 | PB+0x00 | ST | 1 | 0xAB | OK |
| 23 | PB+0x00 | LD | 1 | | OK=0xAB |
| 24 | PB+0x01 | LD | 1 | | OK=0 |
| 25 | PB+0x10 | ST | 16 | 0x000102030405060708090A0B0C0D0E0F | OK |
| 26 | PB+0x18 | LD | 8 | | OK=0x0001020304050607 |
| 27 | CW+0x30 | ST | 8 | 1 | OK (no-op ack) |
| 28 | CW+0x30 | ST | 8 | 2 | DEVERR |
| 29 | CW+0x00 | ST | 8 | 0 | OK (presents; see V4) |

Row 25/26: the 16-byte store places byte 0x0F at PB+0x10 (LE), so the
64-bit load at PB+0x18 returns the high half 0x0001020304050607.

### V4 — frame snapshot and PRESENT (sections 3.3, 5; D-11..D-14)

Test geometry: WIDTH = 2, HEIGHT = 2, STRIDE = 16, window >= 32 bytes.
Buffer contents after these stores (all other window bytes still 0):

| store addr | size | value (u32) | pixel |
|-----------|-----:|-------------|-------|
| PB+0  | 4 | 0x00FF0000 | (0,0) red |
| PB+4  | 4 | 0x0000FF00 | (1,0) green |
| PB+8  | 4 | 0xDEADBEEF | row-0 padding, excluded |
| PB+16 | 4 | 0x000000FF | (0,1) blue |
| PB+20 | 4 | 0xFFFFFFFF | (1,1) white, X=0xFF |

Then `ST` 64-bit value 0xDEAD_BEEF_DEAD_BEEF to CW+0x00 (PRESENT).

Expected frame snapshot (16 bytes, hex):

    00 00 FF 00  00 FF 00 00  FF 00 00 00  FF FF FF FF

Expected presented image, row-major (R,G,B):

    (255,0,0) (0,255,0)
    (0,0,255) (255,255,255)

Repeat with PRESENT value 0: identical snapshot and image (D-14). Repeat
with PB+21..23 (the X/high bytes of pixel (1,1)) rewritten to 00: snapshot
byte 15 becomes 00 but the presented image is unchanged (D-12).

### V5 — resize / ack sequence (section 6; D-16..D-21)

Initial mode 640 x 480 x 2560; IE = 0 throughout except step 12 (so
delivery points are explicit); "event(W,H,S) @ C" = a resize EVENT record
with cycle C (payload encoding per devspec/trace.md §EVENT). Steps execute
in order; loads are 64-bit.

| step | action | expected |
|-----:|--------|----------|
| 1 | LD CW+0x28 | 0 |
| 2 | event(800, 600, 3200) @ C1, C1 already reached | delivered between instructions |
| 3 | LD CW+0x28 | 1 |
| 4 | LD CW+0x08, CW+0x10, CW+0x18 | 800, 600, 3200 (all three consistent) |
| 5 | ST CW+0x30 = 1 | OK; display EXTINT contribution deasserts |
| 6 | LD CW+0x28 | 0 |
| 7 | event(1024, 768, 4096) @ C2; event(640, 480, 2560) @ C3; both delivered before next load | |
| 8 | LD CW+0x28 | 1 (still one flag) |
| 9 | LD CW+0x08, CW+0x10, CW+0x18 | 640, 480, 2560 (latest wins) |
| 10 | ST CW+0x30 = 1 | OK |
| 11 | LD CW+0x28 | 0 |
| 12 | set IE = 1, event(800, 600, 3200) @ C4 | EXTINT (cause 1) delivered between instructions; epc = next instruction; IRQ_STATUS reads 1 in the handler |
| 13 | in handler: ST CW+0x30 = 1, then LD CW+0x08/0x10/0x18 | ack-first pattern; reads return 800, 600, 3200 |
| 14 | LD CW+0x20 | 1 (FORMAT unchanged by all of the above) |

Throughout V5 the pixel buffer PA and window size are unchanged (D-23)
and no pixel buffer byte changes (D-09).

### V6 — geometry constraint check data (section 3.4; D-10)

Window size 0x100_0000. Columns: WIDTH, HEIGHT, STRIDE, verdict for an
emulator proposing this geometry (legal geometries may be published;
illegal ones must never be).

| WIDTH | HEIGHT | STRIDE | verdict | violated rule |
|------:|-------:|-------:|---------|---------------|
| 640 | 480 | 2560 | legal | |
| 800 | 600 | 3200 | legal | |
| 1 | 1 | 16 | legal | |
| 2048 | 2048 | 8192 | legal | HEIGHT*STRIDE = window exactly |
| 640 | 480 | 2556 | illegal | STRIDE mod 16 != 0 |
| 640 | 480 | 2544 | illegal | STRIDE < 4*WIDTH |
| 0 | 480 | 2560 | illegal | WIDTH < 1 |
| 640 | 0 | 2560 | illegal | HEIGHT < 1 |
| 2048 | 2049 | 8192 | illegal | HEIGHT*STRIDE > window |
| 4096 | 1024 | 16384 | illegal | WIDTH*STRIDE > window |

---

## Dependencies (placeholder references to resolve at integration)

1. devspec/trace.md §EVENT — the resize EVENT payload encoding (new WIDTH/
   HEIGHT/STRIDE) and the device-index convention; referenced in sections
   6.1–6.2 and vector V5.
2. devspec/trace.md — elaborated event-delivery interleaving with
   instruction retirement/trace records (section 6.2) and the META key for
   the initial display mode (section 1).
3. devspec/boot.md — device table byte layout for the type-1 (display)
   entry (section 1 summarizes PLATFORM-SPEC §2 values only).
