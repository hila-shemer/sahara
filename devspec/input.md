# Sahara Input Devices: Keyboard and Mouse

**Version 1.0-draft. Companion to ISA-SPEC.md and PLATFORM-SPEC.md.**
Detailed specification of the reference platform's keyboard and mouse
devices. This document plus ISA-SPEC.md is sufficient to implement both
devices with no further questions; facts owned by other documents are
restated here with their owner cited and must not be redefined from this
document.

Normative except where marked *Note:* or in Appendix A.

Ownership (per the devspec ownership matrix):

- **This document owns:** the USB HID usage-ID subset; keyboard/mouse
  behavioral policy (modifiers, repeat, lock keys, alternation, emission
  and clamping rules, queue depth and overflow, empty-read and error
  semantics).
- **Frozen elsewhere, restated here:** device register offsets, widths,
  and event word layouts (PLATFORM-SPEC §5, §6); device-space access and
  ordering rules (ISA-SPEC §9.2); the synchronous event-queue model
  (ISA-SPEC §4, PLATFORM-SPEC §8).
- **Referenced, never defined here:** trace EVENT payload encodings and
  replay record semantics (per devspec/trace.md §EVENT); device table
  entries (per devspec/boot.md); display WIDTH/HEIGHT/resize semantics
  (per devspec/display.md).

---

## 1. Register interface (both devices)

Base physical addresses on the reference platform (defaults; the device
table per devspec/boot.md is authoritative at boot):

| device | base PA | window size | device table type |
|--------|---------|-------------|------------------:|
| keyboard | 0x0F01_0000 | 64 KB | 2 |
| mouse    | 0x0F02_0000 | 64 KB | 3 |

Both windows are device space in the sense of ISA-SPEC §9.2: accesses are
mutually ordered in program order, a store to device space is a release
fence, and atomic operations (CAS/AMO) targeting these windows trap
`DEVERR` (ISA-SPEC §5.4, §9.2).

Register layout, identical for both devices (frozen in PLATFORM-SPEC §5,
§6). All registers are 64 bits, little-endian, naturally aligned:

| offset | register | access | semantics |
|-------:|----------|--------|-----------|
| 0 | DATA   | R | pop and return the oldest queued event; all-ones (0xFFFF_FFFF_FFFF_FFFF) if the queue is empty |
| 8 | STATUS | R | current queue depth (number of pending events, 0 to 256) |

Access rules:

1. **Size.** DATA and STATUS must be accessed with 64-bit loads (`lds.64`
   / `ldz.64` / `ld128` is *not* acceptable: 128-bit access is not
   64-bit). Any access of size other than 64 bits anywhere in the window
   traps `DEVERR` with `baddr` = the offending address (PLATFORM-SPEC §1;
   ISA-SPEC §9.2, §7.1).
2. **Writes.** Both registers are read-only. Any store anywhere in a
   keyboard or mouse window — including a 64-bit store to DATA or STATUS
   — traps `DEVERR` with `baddr` = the offending address. *(Decision
   under the project loud-failure policy; PLATFORM-SPEC is silent on
   writes to these windows.)*
3. **Unlisted offsets.** A load from any offset in the window other than
   0 and 8 traps `DEVERR` with `baddr` = the offending address. *(Same
   loud-failure decision; nothing is reserved-readable in these windows,
   unlike the display's reserved offsets.)*
4. **Side effects.** A DATA load that returns an event pops it (queue
   depth decreases by 1). A DATA load from an empty queue returns
   all-ones and has no effect on device state. STATUS loads never have
   side effects. All these loads remain ordered per ISA-SPEC §9.2.
5. **Predication.** A predicated-false load from DATA performs no device
   access and pops nothing (ISA-SPEC §3.2).
6. The all-ones empty-queue value is unambiguous: every valid keyboard
   event has bits 63:33 = 0 and every valid mouse event has bits 63:40 =
   0, so no valid event equals 0xFFFF_FFFF_FFFF_FFFF.

---

## 2. Keyboard

### 2.1 Event word encoding

64 bits (frozen in PLATFORM-SPEC §5):

| bits | field |
|-----:|-------|
| 31:0 | USB HID keyboard usage ID (Keyboard/Keypad page 0x07), zero-extended |
| 32   | 1 = press, 0 = release |
| 63:33 | 0 |

An implementation must emit only usage IDs from the table in §2.2 and
must set bits 63:33 to zero. A guest receiving a word with bits 63:33
nonzero (other than the all-ones empty sentinel) is observing a
non-conforming device.

### 2.2 HID usage subset (owned by this document — the full table)

The platform emits exactly the following usage IDs from the USB HID
Keyboard/Keypad page (0x07). No other usage ID is ever emitted.

Letters:

| ID | key | ID | key | ID | key | ID | key |
|---:|-----|---:|-----|---:|-----|---:|-----|
| 0x04 | A | 0x0B | H | 0x12 | O | 0x19 | V |
| 0x05 | B | 0x0C | I | 0x13 | P | 0x1A | W |
| 0x06 | C | 0x0D | J | 0x14 | Q | 0x1B | X |
| 0x07 | D | 0x0E | K | 0x15 | R | 0x1C | Y |
| 0x08 | E | 0x0F | L | 0x16 | S | 0x1D | Z |
| 0x09 | F | 0x10 | M | 0x17 | T | | |
| 0x0A | G | 0x11 | N | 0x18 | U | | |

Digits (main row):

| ID | key | ID | key |
|---:|-----|---:|-----|
| 0x1E | 1 | 0x23 | 6 |
| 0x1F | 2 | 0x24 | 7 |
| 0x20 | 3 | 0x25 | 8 |
| 0x21 | 4 | 0x26 | 9 |
| 0x22 | 5 | 0x27 | 0 |

Editing, whitespace, punctuation:

| ID | key | ID | key |
|---:|-----|---:|-----|
| 0x28 | Enter | 0x31 | \ (backslash) |
| 0x29 | Escape | 0x33 | ; (semicolon) |
| 0x2A | Backspace | 0x34 | ' (apostrophe) |
| 0x2B | Tab | 0x35 | ` (grave) |
| 0x2C | Space | 0x36 | , (comma) |
| 0x2D | - (minus) | 0x37 | . (period) |
| 0x2E | = (equals) | 0x38 | / (slash) |
| 0x2F | [ (left bracket) | 0x39 | Caps Lock |
| 0x30 | ] (right bracket) | | |

Function keys:

| ID | key | ID | key | ID | key |
|---:|-----|---:|-----|---:|-----|
| 0x3A | F1 | 0x3E | F5 | 0x42 | F9 |
| 0x3B | F2 | 0x3F | F6 | 0x43 | F10 |
| 0x3C | F3 | 0x40 | F7 | 0x44 | F11 |
| 0x3D | F4 | 0x41 | F8 | 0x45 | F12 |

Navigation and system:

| ID | key | ID | key |
|---:|-----|---:|-----|
| 0x46 | PrintScreen | 0x4D | End |
| 0x47 | Scroll Lock | 0x4E | PageDown |
| 0x48 | Pause | 0x4F | RightArrow |
| 0x49 | Insert | 0x50 | LeftArrow |
| 0x4A | Home | 0x51 | DownArrow |
| 0x4B | PageUp | 0x52 | UpArrow |
| 0x4C | Delete | | |

Keypad:

| ID | key | ID | key |
|---:|-----|---:|-----|
| 0x53 | Num Lock | 0x5C | Keypad 4 |
| 0x54 | Keypad / | 0x5D | Keypad 5 |
| 0x55 | Keypad * | 0x5E | Keypad 6 |
| 0x56 | Keypad - | 0x5F | Keypad 7 |
| 0x57 | Keypad + | 0x60 | Keypad 8 |
| 0x58 | Keypad Enter | 0x61 | Keypad 9 |
| 0x59 | Keypad 1 | 0x62 | Keypad 0 |
| 0x5A | Keypad 2 | 0x63 | Keypad . |
| 0x5B | Keypad 3 | | |

Modifiers:

| ID | key | ID | key |
|---:|-----|---:|-----|
| 0xE0 | Left Control | 0xE4 | Right Control |
| 0xE1 | Left Shift | 0xE5 | Right Shift |
| 0xE2 | Left Alt | 0xE6 | Right Alt |
| 0xE3 | Left GUI | 0xE7 | Right GUI |

Total: 103 usage IDs. **Explicitly excluded** (never emitted): 0x00–0x03
(no-event/error rollover codes — the event-per-transition model has no
use for them), 0x32 (Non-US #), 0x64 (Non-US \), 0x65 (Application),
0x66+ (power, international, language, and media keys), and every other
HID page. Host key events whose translation falls outside this table are
discarded by the emulator: no event is generated, nothing is enqueued,
and nothing appears in the trace.

### 2.3 Modifier policy

Modifiers are ordinary keys. Each of 0xE0–0xE7 generates its own press
and release events, exactly like any other key. The platform provides no
modifier bitmap, no combined state, and applies no modifier translation:
pressing Shift+A produces (up to interleaving) press 0xE1, press 0x04,
release 0x04, release 0xE1 — four events. Character translation
(shift/caps semantics, keyboard layout) is entirely guest software's
concern; the platform reports physical-key transitions only, using the
US-layout HID position of each physical key.

### 2.4 Repeat policy

**There is no auto-repeat.** The platform emits one press event and one
release event per physical key transition and never synthesizes repeats.
The emulator must suppress host-OS auto-repeat (a host "repeat" key event
generates no Sahara event). Guests wanting repeat implement it themselves
with the architectural timer (ISA-SPEC §7.5).

*Note: host-side repeat timing is wall-clock-dependent and would leak
nondeterminism into event generation; a timer-driven guest repeat is
deterministic under replay for free.*

### 2.5 Lock keys and LEDs

Caps Lock, Num Lock, and Scroll Lock are ordinary keys: press and release
events, no latching, no state in the device. The platform has no LED
output (the windows are read-only, §1 rule 2); lock state, if any, is a
guest software concept. The emulator must translate the host's physical
lock-key transitions like any other key and must not apply host lock
state to translation.

### 2.6 Press/release alternation guarantee

For each usage ID, the sequence of generated events (counting dropped
events, §4.2) strictly alternates press, release, press, release, …
starting from released at reset. Consequently the platform never
generates two consecutive presses of the same key without an intervening
release, and never a release of a key not currently pressed. The emulator
enforces this at the capture boundary by synthesizing release events for
all held keys when input capture is lost (Appendix A); the synthesized
releases are ordinary events, enqueued and traced like any other.

A guest may therefore keep per-key state as a single bit and treat any
observed violation as a device error. (Because *dropped* events count
toward alternation but are invisible to the guest, the guest-visible
sequence may skip transitions after an overflow; a guest that saw
STATUS at 256 must treat its key-state model as stale. See §4.2.)

---

## 3. Mouse

### 3.1 Event word encoding

64 bits (frozen in PLATFORM-SPEC §6):

| bits | field |
|-----:|-------|
| 15:0 | x, unsigned pixel column, clamped (§3.3) |
| 31:16 | y, unsigned pixel row, clamped (§3.3) |
| 39:32 | button state: bit 0 left, bit 1 right, bit 2 middle; bits 7:3 = 0 |
| 63:40 | 0 |

Every event carries the full current state (absolute position plus all
three buttons); there are no delta events. There is no scroll wheel in
v1.0 (no field exists for it; a future revision may use bits 63:40 —
guests must ignore nothing: a nonzero bit in 63:40 from a v1.0 device is
non-conformance, and v1.0 guests must not be written to tolerate it).

### 3.2 Emission rule

The device state is the triple (x, y, buttons) after clamping. The
emulator generates an event exactly when the new triple differs from the
triple of the most recently *generated* event (generated = created and
assigned a cycle, whether or not it was subsequently dropped by queue
overflow, §4.2). The state at reset is (0, 0, 0); the first generated
event is the first host input whose clamped triple differs from
(0, 0, 0).

Consequences, all normative:

- Host pointer motion that does not change the clamped position (e.g.
  motion entirely beyond a clamped edge) and does not change buttons
  generates no event.
- A button press and a simultaneous position change may arrive as one
  event; guests must diff against their previous copy of the state, not
  assume one-change-per-event.
- Two consecutive generated mouse events never carry identical words.

### 3.3 Coordinate clamping

Let W and H be the display mode's current width and height in pixels
(per devspec/display.md; the values guest-visible in the display WIDTH
and HEIGHT registers). At event-generation time the emulator clamps:

    x = min(max(pointer_x, 0), min(W - 1, 65535))
    y = min(max(pointer_y, 0), min(H - 1, 65535))

The additional 65535 bound is forced by the 16-bit fields; on the
reference platform display modes are not expected to exceed 65535 in
either dimension (mode constraints per devspec/display.md).

Clamping interacts with resize as follows:

1. Clamping uses the W and H in effect at the cycle assigned to the
   mouse event: a mouse event whose cycle is greater than or equal to the
   cycle of a display-resize event clamps against the post-resize mode;
   one at an earlier cycle clamps against the pre-resize mode. Relative
   ordering of a mouse event and a resize event assigned the *same*
   cycle is defined by the trace's event ordering rules (per
   devspec/trace.md §EVENT).
2. Events already in the queue are never re-clamped. After a resize to a
   smaller mode, the guest may pop events whose coordinates exceed the
   new W-1/H-1; it must tolerate this (the events were valid when
   generated).
3. A resize by itself generates no mouse event. The guest's next mouse
   event after a resize carries coordinates clamped to the new mode per
   rule 1.

---

## 4. Queues

### 4.1 Depth

Each device has one FIFO queue of 64-bit event words. On the reference
platform the depth is **exactly 256 entries for both devices**.
(PLATFORM-SPEC §5 requires "at least 256"; the reference platform fixes
it so overflow behavior is deterministic and testable. STATUS therefore
reads 0–256.)

### 4.2 Overflow: drop-newest

When an event is generated for a device whose queue already holds 256
entries, the *new* event is dropped (drop-newest; PLATFORM-SPEC §5). A
dropped event:

- is never observable through DATA and never counts in STATUS;
- does not contribute to EXTINT pending;
- **is recorded in the trace** with its cycle and full payload, marked as
  dropped, so replay reproduces the drop exactly (encoding per
  devspec/trace.md §EVENT — the trace document owns the drop-marker
  representation);
- counts as generated for the keyboard alternation guarantee (§2.6) and
  as the comparison point for the mouse emission rule (§3.2).

Queued (non-dropped) events are never discarded by the device for any
reason other than a DATA pop; there is no flush operation.

### 4.3 FIFO and visibility semantics

- DATA pops strictly in generation order (oldest first) per device. The
  two devices' queues are independent; no cross-device ordering is
  visible through the registers (the trace's global event order is per
  devspec/trace.md).
- An event with assigned cycle C becomes visible — counted by STATUS,
  poppable via DATA, contributing to EXTINT — at the first
  between-instructions boundary at which the `cycle` sreg is ≥ C, before
  the next instruction executes. This elaborates the synchronous event
  queue of ISA-SPEC §4 and is consistent with interrupts being
  recognized only between instructions (ISA-SPEC §7.5). Within one
  instruction's execution the visible queue state does not change.
- Cycle *assignment* (which cycle an input gets in live mode, and its
  reproduction in replay) is governed by ISA-SPEC §4 and PLATFORM-SPEC
  §8 as elaborated by devspec/trace.md; this document does not define
  it.

---

## 5. Interrupts

Per PLATFORM-SPEC §3, each device's pending condition is "event queue
non-empty" (STATUS ≠ 0). EXTINT (cause 1) is the level-triggered OR of
all devices' pending conditions; it remains pending until every source is
cleared. For keyboard and mouse the only clearing mechanism is draining:
reading DATA until STATUS is 0 (equivalently, until DATA returns
all-ones — checking the sentinel saves one STATUS read per scan).

The canonical handler loop for one of these devices:

    drain:  lds.64  r8, [rDEV + 0]       # DATA: pop (lds sign-extends, so the
                                         # all-ones sentinel becomes 128-bit -1)
            cmpeq   p1, r8, -1           # sentinel? (imm -1 sign-extends to all-ones)
            (p1) b  done
            ...process event in r8...
            b       drain
    done:

If events keep arriving while the handler drains, EXTINT simply remains
pending and re-delivers after IRET when IE is restored — level triggering
makes the race benign. Delivery, masking, and epc semantics are ISA-SPEC
§7.5's; nothing device-specific applies.

---

## 6. Determinism and trace

Every generated event (including dropped ones, §4.2) is a trace EVENT
record carrying (cycle, device table index, payload); the payload
encoding for keyboard and mouse events is owned by devspec/trace.md
§EVENT and is expected to embed the 64-bit event words of §2.1 and §3.1
— this document defines the words, the trace document defines their
framing. In replay mode the trace is the sole event source: the emulator
must not consult the host's real input devices, and identical (image,
event trace) pairs must reproduce all register reads (DATA, STATUS)
bit-identically (ISA-SPEC §4; PLATFORM-SPEC §8; TOOLING-SPEC §3.2).

Live-mode generation timing (when the emulator samples the host and what
cycle it assigns) is inherently non-reproducible across live sessions and
is deliberately unspecified beyond the rules in this document; only the
recorded trace is authoritative.

---

## 7. Conformance requirements

Numbered, testable. "KBD" = keyboard window, "MSE" = mouse window; both
windows where the requirement names neither. All register accesses below
are 64-bit unless stated.

- **INPUT-01.** A DATA load with STATUS = 0 returns
  0xFFFF_FFFF_FFFF_FFFF and leaves STATUS = 0.
- **INPUT-02.** After n events are enqueued (n ≤ 256), STATUS reads n;
  each DATA load returns the oldest remaining event and decrements
  STATUS by 1; the n events are returned in generation order.
- **INPUT-03.** STATUS loads have no side effect: two consecutive STATUS
  loads with no intervening event return equal values, and a STATUS load
  between two DATA loads does not change which events the DATA loads
  return.
- **INPUT-04.** Any load or store of size 8, 16, or 32 bits, and any
  128-bit LD128/ST128, anywhere in KBD or MSE, traps DEVERR with baddr =
  the accessed address.
- **INPUT-05.** Any 64-bit store to offset 0 or 8 of KBD or MSE traps
  DEVERR with baddr = the accessed address.
- **INPUT-06.** Any 64-bit load from an offset other than 0 and 8 in KBD
  or MSE traps DEVERR with baddr = the accessed address.
- **INPUT-07.** Any CAS or AMO targeting any address in KBD or MSE traps
  DEVERR.
- **INPUT-08.** A predicated-false DATA load pops nothing: STATUS is
  unchanged and the next true-predicated DATA load returns the event the
  squashed load would have returned.
- **INPUT-09.** Every keyboard event word has bits 63:33 = 0 and bits
  31:0 equal to a usage ID listed in §2.2.
- **INPUT-10.** Keyboard events for usage IDs outside the §2.2 table are
  never generated: a replayed trace containing only in-table events
  produces only in-table DATA values, and the emulator's live translation
  layer emits no out-of-table ID for any host key.
- **INPUT-11.** For each usage ID the generated event sequence strictly
  alternates press (bit 32 = 1) then release (bit 32 = 0), starting with
  press after reset, counting dropped events.
- **INPUT-12.** No auto-repeat: a key held down contributes exactly one
  press event and (on release) one release event, regardless of hold
  duration in host time or virtual cycles.
- **INPUT-13.** Modifier keys 0xE0–0xE7 and lock keys 0x39, 0x47, 0x53
  generate ordinary press/release events; no event word ever encodes a
  modifier bitmap or latched lock state.
- **INPUT-14.** Every mouse event word has bits 63:40 = 0 and bits
  39:35 (button bits 7:3) = 0.
- **INPUT-15.** Every mouse event satisfies x ≤ min(W-1, 65535) and
  y ≤ min(H-1, 65535) for the display mode W×H in effect at the event's
  cycle (per §3.3 rule 1).
- **INPUT-16.** Two consecutive generated mouse events differ in at
  least one of x, y, buttons; host input producing no clamped-state
  change generates no event.
- **INPUT-17.** Mouse events already enqueued are not modified by a
  display resize: after a resize to a smaller mode, previously enqueued
  events pop with their original (now possibly out-of-mode) coordinates.
- **INPUT-18.** With 256 events enqueued on a device, a newly generated
  event for that device is dropped: STATUS stays 256, the queue contents
  are unchanged, and the drop appears in the trace as specified by
  devspec/trace.md §EVENT.
- **INPUT-19.** A dropped event still advances the §2.6/§3.2 generation
  state: after a dropped keyboard press of key K, the next generated
  event for K is a release; after a dropped mouse event with triple T,
  host state equal to T generates no further event.
- **INPUT-20.** EXTINT is pending whenever STATUS ≠ 0 on either device
  and (absent other EXTINT sources) not pending when both devices'
  STATUS = 0; draining both queues via DATA deasserts EXTINT with no
  further acknowledgment action.
- **INPUT-21.** An event with assigned cycle C is invisible (STATUS,
  DATA, EXTINT) at every instruction boundary where `cycle` < C and
  visible at the first boundary where `cycle` ≥ C.
- **INPUT-22.** Replay of a recorded trace reproduces every DATA and
  STATUS load's value bit-identically, with the host's real input
  devices untouched.
- **INPUT-23.** Reads of DATA are ordered with respect to other device
  accesses in program order (ISA-SPEC §9.2 rule 2): in a program that
  loads DATA twice, the first load pops the older event — observable in
  the trace's MEMR/DEVW-level records and never reordered.

---

## 8. Test vectors

Numbered, concrete, consumable as data. Addresses assume the default
bases of §1 (tests must in general take bases from the device table, per
devspec/boot.md).

### 8.1 Keyboard event words (stimulus → expected 64-bit DATA value)

| # | stimulus | expected word |
|---|----------|---------------|
| KV-01 | press A (0x04) | 0x0000_0001_0000_0004 |
| KV-02 | release A (0x04) | 0x0000_0000_0000_0004 |
| KV-03 | press Enter (0x28) | 0x0000_0001_0000_0028 |
| KV-04 | press Escape (0x29) | 0x0000_0001_0000_0029 |
| KV-05 | press Space (0x2C) | 0x0000_0001_0000_002C |
| KV-06 | press Left Shift (0xE1) | 0x0000_0001_0000_00E1 |
| KV-07 | release Left Shift (0xE1) | 0x0000_0000_0000_00E1 |
| KV-08 | press Right GUI (0xE7) | 0x0000_0001_0000_00E7 |
| KV-09 | press F12 (0x45) | 0x0000_0001_0000_0045 |
| KV-10 | press Caps Lock (0x39) | 0x0000_0001_0000_0039 |
| KV-11 | press Keypad Enter (0x58) | 0x0000_0001_0000_0058 |
| KV-12 | press Keypad . (0x63) | 0x0000_0001_0000_0063 |
| KV-13 | press UpArrow (0x52) | 0x0000_0001_0000_0052 |
| KV-14 | press digit 0 (0x27) | 0x0000_0001_0000_0027 |
| KV-15 | press Keypad 0 (0x62) | 0x0000_0001_0000_0062 |

### 8.2 Keyboard sequence: Shift+A typed (§2.3)

Stimulus: host types capital A (shift down, a down, a up, shift up).
Expected DATA pops, in order:

| order | word |
|------:|------|
| 1 | 0x0000_0001_0000_00E1 |
| 2 | 0x0000_0001_0000_0004 |
| 3 | 0x0000_0000_0000_0004 |
| 4 | 0x0000_0000_0000_00E1 |
| 5 (queue now empty) | 0xFFFF_FFFF_FFFF_FFFF |

### 8.3 Mouse event words (state → expected 64-bit DATA value)

Display mode 800×600 (W=800, H=600) unless stated.

| # | state (x, y, buttons) | expected word |
|---|----------------------|---------------|
| MV-01 | (100, 200, left) | 0x0000_0001_00C8_0064 |
| MV-02 | (100, 200, none) | 0x0000_0000_00C8_0064 |
| MV-03 | (800, 600, none) → clamped (799, 599) | 0x0000_0000_0257_031F |
| MV-04 | (0, 0, left+right+middle) | 0x0000_0007_0000_0000 |
| MV-05 | (799, 0, right) | 0x0000_0002_0000_031F |
| MV-06 | (0, 599, middle) | 0x0000_0004_0257_0000 |
| MV-07 | mode 65535×65535 or larger: (70000, 70000, all) → clamped (65535, 65535) | 0x0000_0007_FFFF_FFFF |
| MV-08 | (1, 1, none) after (1, 1, none) | no event generated (INPUT-16) |

### 8.4 Register-access fault vectors

Each row: one instruction against the default bases; expected trap cause
and baddr (cause codes per ISA-SPEC §7.1: DEVERR = 12).

| # | access | expected |
|---|--------|----------|
| FV-01 | ldz.32 from 0x0F01_0000 | DEVERR, baddr 0x0F01_0000 |
| FV-02 | ldz.8 from 0x0F01_0008 | DEVERR, baddr 0x0F01_0008 |
| FV-03 | ld128 from 0x0F02_0000 | DEVERR, baddr 0x0F02_0000 |
| FV-04 | st.64 to 0x0F01_0000 | DEVERR, baddr 0x0F01_0000 |
| FV-05 | st.64 to 0x0F02_0008 | DEVERR, baddr 0x0F02_0008 |
| FV-06 | ldz.64 from 0x0F01_0010 | DEVERR, baddr 0x0F01_0010 |
| FV-07 | ldz.64 from 0x0F02_FFF8 | DEVERR, baddr 0x0F02_FFF8 |
| FV-08 | amoadd.64 on 0x0F01_0000 | DEVERR |
| FV-09 | cas.64 on 0x0F02_0000 | DEVERR |
| FV-10 | ldz.64 from 0x0F01_0000, queue empty | no trap; loaded 64-bit value 0xFFFF_FFFF_FFFF_FFFF (zero-extended to 128 in the register by LDZ) |
| FV-11 | ldz.64 from 0x0F01_0008, queue empty | no trap; value 0 |
| FV-12 | (p1)=false predicated ldz.64 from 0x0F01_0000, one event queued | no trap, no pop; STATUS still 1 |

### 8.5 Overflow scenario (INPUT-18/19)

Stimulus: with the keyboard queue empty, generate 257 events: press then
release of key A repeated 128 times (256 events), then press A once more
(the 257th, dropped).

Expected observable sequence:

| step | check | expected |
|-----:|-------|----------|
| 1 | STATUS after all 257 generated | 256 |
| 2 | DATA pops 1–256 | alternating 0x0000_0001_0000_0004, 0x0000_0000_0000_0004 (128 pairs); the 257th press absent |
| 3 | STATUS after 256 pops | 0 |
| 4 | DATA pop 257 | 0xFFFF_FFFF_FFFF_FFFF |
| 5 | trace | 257 generated events recorded; the 257th marked dropped (encoding per devspec/trace.md §EVENT) |
| 6 | next generated event for key A after the drop | release (0x0000_0000_0000_0004), per INPUT-19 |

### 8.6 Resize-clamp scenario (INPUT-15/17)

Stimulus, in cycle order: mode is 800×600; mouse event E1 at (790, 590,
none) enqueued; display resize to 640×480 occurs (resize event, per
devspec/display.md); mouse event E2 generated by host pointer at
(790, 590, left).

| step | check | expected |
|-----:|-------|----------|
| 1 | pop E1 (enqueued pre-resize) | 0x0000_0000_024E_0316 (x=790=0x316, y=590=0x24E — not re-clamped) |
| 2 | pop E2 (generated post-resize) | 0x0000_0001_01DF_027F (clamped to x=639=0x27F, y=479=0x1DF) |

---

## Appendix A — GUI capture/release conventions (non-normative)

Recommended for the reference emulator's interactive mode; nothing here
affects guest-visible semantics except through the ordinary events it
generates (which are normative and traced like any others).

- **Keyboard capture** follows host window focus: while the emulator
  window is focused, all translatable key transitions become events;
  PrintScreen/GUI-key combinations the host OS intercepts may never
  reach the emulator and simply generate no event.
- **Mouse capture** is click-to-capture: a click inside the emulator
  window captures the pointer (hidden, confined); host pointer position
  maps 1:1 to guest pixels. The capturing click itself is delivered to
  the guest.
- **Release chord**: Ctrl+Alt (both left) releases capture. The chord
  keys' press events will already have been delivered; on release of
  capture the emulator synthesizes release events for every key and
  button currently held (normatively required by §2.6), so the guest
  never observes stuck keys.
- **Capture loss** for any other reason (focus loss, window minimize)
  synthesizes the same releases.
- While uncaptured, no keyboard or mouse events are generated at all;
  motion over the unfocused window is invisible to the guest.
- Headless mode has no capture concept: events come exclusively from a
  replay trace.
