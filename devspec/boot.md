# Sahara Boot Protocol and Device Table — Detailed Specification

**Status:** devspec, version 1.0-draft. Companion to ISA-SPEC.md,
PLATFORM-SPEC.md, and TOOLING-SPEC.md. This document is the **owner** of the
device table layout (per the devspec ownership matrix); all other documents
reference it and define nothing about the table. Where PLATFORM-SPEC.md
states a value this document restates, the values are identical by
construction; PLATFORM-SPEC.md remains authoritative for device register
offsets/widths and the physical memory map defaults.

Everything here is normative except sections explicitly marked
*non-normative* (section 8, and indented *Note:* lines).

Conventions: `u64` = 64-bit little-endian unsigned integer; `u128` = 128-bit
little-endian unsigned integer (byte i holds bits [8i, 8i+8)); all offsets
are in bytes; "PA" = physical address; hex dumps are
`<PA:8 hex digits>: <up to 16 space-separated byte values>`.

---

## 1. Scope

This document specifies, byte-exactly:

1. The machine state at reset and the emulator's obligations before reset
   (the reset hand-off).
2. The device table: location, encoding, header, RAM region records, device
   records, per-type parameters.
3. Forward-compatibility rules: unknown versions, unknown device types,
   table growth, reserved-field discipline.
4. RAM region semantics: ordering, granularity, overlap prohibitions, and
   the behavior of physical accesses outside every declared region.

It does **not** specify device register behavior after boot (display,
keyboard, mouse, NIC internals — see PLATFORM-SPEC.md and the corresponding
devspec documents), the image file format (TOOLING-SPEC.md section 1), or
the trace format (devspec/trace.md).

---

## 2. Reset hand-off

### 2.1 Emulator obligations before reset

In this order, before the first instruction executes:

1. **Load the image.** Each segment of the `.img` file is copied to its
   `load_pa` and zero-filled to `mem_len`, per TOOLING-SPEC.md section 1.
   The loader must reject, with a fatal error (loud failure, no partial
   load), any image whose segments overlap each other or overlap the device
   table window `[0x0800, 0x1000)`.
2. **Write the device table** at PA `0x0800` (section 3). The emulator
   writes the table exactly once, before reset, and never modifies it
   afterward — not on resize, not on hot-anything (there is no hot-plug in
   v1.0). The table contents are constant for the lifetime of the machine.
3. **Initialize machine state** to the reset state of section 2.2.

The device table lives in ordinary RAM. The guest can physically overwrite
it; doing so is self-sabotage, not an error the platform detects. The guest
must treat the table as read-only by convention.

### 2.2 Machine state at reset

Restating ISA-SPEC.md section 11 precisely; this list is exhaustive:

| state | value at reset |
|---|---|
| `pc` | `0x1000` (a physical address; `MMU_EN = 0`) |
| `status` (sreg 0) | `0x8` — that is `S = 1`; `IE = PIE = MMU_EN = PS = 0`; `TL = 0` |
| all other sregs (1–15) | `0` |
| `r0`–`r30` | `0` |
| `r31` | hardwired zero |
| `p1`–`p7` | `0` |
| `p0` | hardwired `1` |
| `cycle` (sreg 8) | `0` (it is "all other sregs = 0"; the first retired instruction makes it 1) |
| memory | the loaded image (zero elsewhere in RAM) plus the device table at `0x0800` |

Consequences the boot author may rely on:

- The machine starts in supervisor mode with the MMU off and interrupts
  disabled. Physical address = virtual address until software sets
  `MMU_EN`.
- `vbase = dfbase = 0`. Any trap taken before boot code installs vectors
  transfers to PA `0` — which is RAM, normally zero-filled, whose contents
  execute as opcode `0x00` = `ILLEGAL`, which traps again; the second trap
  goes to `dfbase = 0` (double fault), the third is a triple fault and the
  machine halts (ISA-SPEC.md 7.2). Pre-vector faults are therefore loud:
  the machine reliably halts rather than wandering.
- `timecmp = 0` means the timer interrupt is never pending (ISA-SPEC.md
  7.5), so boot code need not race to mask anything: `IE = 0` and no
  pending source exists at cycle 0 unless a device event is scheduled at
  cycle 0.
- Nothing else is promised. There are no firmware services, no callbacks,
  no environment registers. The device table is the entire hand-off.

### 2.3 Boot code obligations

Boot code must derive **everything** — RAM size, CPU count, device
presence and addresses — from the device table and from it alone. Fixed
platform addresses (section 3.1's `0x0800` excepted, since the table must
be found somewhere) must not be hardcoded; the reference platform's
defaults in PLATFORM-SPEC.md section 1 are what the table will contain on
that platform, not a contract with the guest.

---

## 3. Device table

### 3.1 Location and size

- The table begins at PA `0x0800` on the reference platform. The table's
  address is a platform constant (it is the one address a guest may
  hardcode); future platforms may place it elsewhere and must document it.
- The table window is 2 KB: `[0x0800, 0x1000)`. The encoded table
  (header + all records, section 3.3–3.5) must fit entirely within the
  window. Bytes of the window beyond the encoded table are written `0` by
  the emulator.
- With one RAM region, the 2 KB window bounds `device_count` at 30
  (`40 + 32·1 + 64·30 = 1992 ≤ 2048`). The general constraint is the
  window size, not any device count.
- The window lies in ordinary RAM and reads/writes at all access sizes as
  normal memory. It is **not** device space in the sense of ISA-SPEC.md
  9.2.

### 3.2 Encoding conventions

- All fields are little-endian. A `u128` field occupies 16 bytes, low
  64 bits first (byte 0 = bits 7:0).
- The table is packed: records follow each other with no padding beyond
  the fixed record sizes given below. All field offsets are exactly as
  tabulated; there are no implicit alignment gaps.
- **Alignment of fields.** Every `u64` field falls at a PA that is a
  multiple of 8. `u128` fields are guaranteed only 8-byte alignment, *not*
  16-byte alignment (e.g. the first RAM region's `base` sits at
  `0x0800 + 40 = 0x0828`, and a device record's `base` sits at
  record + 8). Since `LD128` requires 16-byte alignment (ISA-SPEC.md 5.3),
  guests must read `u128` table fields as **two 64-bit loads** (low then
  high). An `LD128` aimed at an 8-but-not-16-aligned field traps
  `UNALIGNED` (test vector V6).
- All multi-byte quantities the emulator writes into reserved or
  unused-in-v1 positions are `0` (section 4.4).

### 3.3 Header — 40 bytes

| offset | size | field | value / meaning |
|-------:|-----:|-------|-----------------|
| 0  | 8 | `magic` u64 | `0x5450_4152_4148_4153` — the bytes `53 41 48 41 52 41 50 54`, ASCII `"SAHARAPT"` |
| 8  | 8 | `version` u64 | `1` for this specification |
| 16 | 8 | `cpu_count` u64 | number of CPUs; `1` in v1.0 |
| 24 | 8 | `ram_region_count` u64 | number of RAM region records that follow; ≥ 1 |
| 32 | 8 | `device_count` u64 | number of device records that follow the RAM regions; ≥ 0 |

Immediately after the header, at table offset 40:
`ram_region_count` RAM region records (32 bytes each, section 3.4);
immediately after those, `device_count` device records (64 bytes each,
section 3.5). Total encoded size =
`40 + 32·ram_region_count + 64·device_count`.

Guest validation on boot (required of conforming boot code; each failure
is terminal — the guest must halt or otherwise fail loudly, never guess):

1. `magic` must equal `0x5450_4152_4148_4153`.
2. `version` must be a value this guest was written for (section 4.1).
3. The computed total size must fit the table window.

### 3.4 RAM region record — 32 bytes

| offset | size | field | meaning |
|-------:|-----:|-------|---------|
| 0  | 16 | `base` u128 | first PA of the region |
| 16 | 16 | `len` u128 | length in bytes; > 0 |

**RAM region semantics** (normative):

1. **Granularity.** `base` and `len` are each a multiple of `0x1_0000`
   (64 KB, the page size). This makes every region mappable page-exactly.
2. **Ordering.** Records are sorted by strictly ascending `base`.
3. **Disjointness.** Regions must not overlap:
   for consecutive records i, i+1: `base[i] + len[i] <= base[i+1]`.
4. **Maximality.** Consecutive regions must not be adjacent:
   `base[i] + len[i] < base[i+1]`. (Adjacent regions must be coalesced by
   the emulator; the region list is therefore canonical — a given physical
   RAM layout has exactly one valid encoding.)
5. **No overlap with non-RAM.** No region may overlap any device record's
   control window, the display pixel buffer window, or any other
   device-space window. RAM is RAM everywhere inside a declared region.
6. **Boot coverage.** On the reference platform, region 0 contains both
   the device table window `[0x0800, 0x1000)` and the reset PC `0x1000`.
   In general, the table window and the reset PC must each lie inside some
   declared RAM region.
7. **RAM size.** "Total RAM" = the sum of all `len`. "RAM top" = the
   maximum over regions of `base + len`. Boot code that wants a boot stack
   at the top of contiguous low RAM uses `base + len` of region 0.

On the reference platform the table declares **one** region:
`base = 0x0`, `len = 0x0F00_0000` (240 MB), ending exactly where the
device windows begin (see Issues note at the end of this document).

**Physical accesses outside every declared region and every device
window** (a "hole") trap `DEVERR`, with `baddr` = the (virtual) address of
the access — defined here under the project loud-failure policy: a hole
access is always a software bug, and silence would hide it. This applies
to data accesses; an instruction *fetch* from a hole also traps `DEVERR`.
A predicated-false instruction, as always, cannot fault (ISA-SPEC.md 3.2).

### 3.5 Device record — 64 bytes

| offset | size | field | meaning |
|-------:|-----:|-------|---------|
| 0  | 8  | `type` u64 | device type code (table below) |
| 8  | 16 | `base` u128 | PA of the device's control-register window |
| 24 | 8  | `size` u64 | control window length, bytes |
| 32 | 32 | `params[4]` u64 × 4 | per-type parameters |

`base` is a multiple of `0x1_0000` (64 KB); `size` is a positive multiple
of `0x1_0000`. Device control windows must not overlap each other, any
RAM region, or the pixel buffer window.

Type codes assigned in version 1:

| type | device | `params[0]` | `params[1]` | `params[2]` | `params[3]` |
|-----:|--------|-------------|-------------|------|------|
| 0 | — reserved, never assigned (guards zeroed memory) | | | | |
| 1 | display  | pixel buffer PA (u64; the buffer's window semantics are per devspec/display.md) | pixel buffer window size, bytes | 0 | 0 |
| 2 | keyboard | 0 | 0 | 0 | 0 |
| 3 | mouse    | 0 | 0 | 0 | 0 |
| 4 | nic      | MAC address, packed per section 3.6 | 0 | 0 | 0 |

- The pixel buffer PA in `params[0]` of the display record is a `u64`
  because the reference platform keeps all device windows below 2^64; a
  future table version widening it would bump `version`.
- The pixel buffer PA and window size are constant for the machine's
  lifetime (resize never moves or resizes the buffer window —
  PLATFORM-SPEC.md section 4; details owned by devspec/display.md).
- Register offsets and semantics inside each control window are owned by
  PLATFORM-SPEC.md (frozen) and elaborated by the per-device devspec
  documents; this table only locates the windows.
- **Multiplicity.** Version 1 reference tables contain exactly one record
  of each of types 1–4, but multiple records of the same type are legal in
  the format. A guest supporting only one instance of a type must use the
  **first** record of that type in table order and ignore the rest.
- **Order.** Device record order is otherwise unspecified; guests must not
  assume any ordering by type or by base address.

### 3.6 MAC address packing (normative, defined here)

A 48-bit MAC address `o0:o1:o2:o3:o4:o5` (octets in wire/transmission
order, i.e. as printed) is packed into a u64 as:

    value = o0 | (o1 << 8) | (o2 << 16) | (o3 << 24) | (o4 << 32) | (o5 << 40)

Bits 63:48 are zero. Equivalently: in the little-endian byte image of the
u64, bytes 0–5 are the MAC octets in wire order and bytes 6–7 are zero.
The reference MAC `52:54:00:12:34:56` packs to `0x0000_5634_1200_5452`,
in-memory bytes `52 54 00 12 34 56 00 00`.

The NIC's `MAC` register (PLATFORM-SPEC.md section 7; devspec/nic.md)
reads back this same packed value, bit for bit.

---

## 4. Forward compatibility

### 4.1 Header version

- `version` names the table layout as a whole. It is bumped **only** for
  changes that break the version-1 parsing rules (record sizes, field
  offsets, count semantics, the skip rule).
- `magic` (offset 0) and `version` (offset 8) will remain at their offsets
  with their current sizes in **every** future version. They are the only
  fields a guest may read before checking `version`.
- A guest that reads a `version` it was not written for must **refuse the
  table** — treat boot discovery as failed and fail loudly (halt). Parsing
  a future layout under version-1 assumptions is forbidden: it produces
  silent garbage, which the project's loud-failure policy prohibits.

### 4.2 Unknown device types

- A guest encountering a device record whose `type` it does not recognize
  must **skip the entire 64-byte record** and continue with the next. This
  is required, not optional: unknown types are the format's growth
  mechanism, and a guest that halts on one is non-conforming.
- Skipping is purely positional — record size is fixed at 64 bytes in
  version 1 regardless of type, so no per-type size knowledge is needed.
- A guest must not access `base`, `size`, or `params` of a record it
  skipped (their meaning is unknown to it by definition).

### 4.3 Table growth within version 1

Without bumping `version`, a future revision may:

- add new `type` codes (guests skip unknown ones);
- increase `ram_region_count` or `device_count` (guests must parse by the
  counts, never assume the reference platform's 1 region / 4 devices);
- include multiple records of one type (section 3.5, multiplicity);
- assign meaning to a `params` slot that version 1 requires to be zero for
  an existing type — **only** under the rule that the value `0` in that
  slot must mean exactly the version-1 behavior, so old tables remain
  valid and old guests reading new tables see, at worst, a feature they
  ignore.

A future revision may **never**, without bumping `version`:

- change the size or field offsets of the header, RAM region record, or
  device record;
- repurpose a `params` slot already assigned a meaning for that type;
- change the packing of section 3.6;
- move `magic` or `version`.

### 4.4 Reserved-field discipline

Every field or slot this document marks `0` (unused `params`, window bytes
past the encoded table) must be written `0` by the emulator. Guests must
ignore (not check, not fault on) a nonzero value in a `params` slot they
do not use — that is how 4.3's growth rule works. The `magic`, `version`,
size/count arithmetic, and structural rules of 3.4/3.5 are the loud-checked
surface; `params` content of skipped or unused slots is the tolerated
surface.

*Note: this is the one deliberate exception to loud-failure: forward
compatibility requires old guests to tolerate new-but-defaultable
information. The boundary is precise: structure is checked loudly, unknown
content is skipped silently.*

---

## 5. Reference platform table (normative values)

The reference platform's emulator writes exactly this table (section 7,
vector V1, is its byte image):

| record | field | value |
|---|---|---|
| header | magic | `0x5450_4152_4148_4153` |
| header | version | 1 |
| header | cpu_count | 1 |
| header | ram_region_count | 1 |
| header | device_count | 4 |
| RAM region 0 | base | `0x0` |
| RAM region 0 | len | `0x0F00_0000` (240 MB) |
| device 0 | type=1 display, base `0x0F00_0000`, size `0x1_0000` | params `[0x1000_0000, 0x0100_0000, 0, 0]` (pixel buffer at 256 MB, 16 MB window) |
| device 1 | type=2 keyboard, base `0x0F01_0000`, size `0x1_0000` | params `[0,0,0,0]` |
| device 2 | type=3 mouse, base `0x0F02_0000`, size `0x1_0000` | params `[0,0,0,0]` |
| device 3 | type=4 nic, base `0x0F03_0000`, size `0x3_0000` | params `[0x0000_5634_1200_5452, 0, 0, 0]` (MAC `52:54:00:12:34:56`) |

The pixel-buffer window size (16 MB) is the reference default; it is
table-driven, not architectural. `ram_len` is configurable; the emulator
recomputes the RAM region record(s) accordingly, holding rules 3.4(1)–(6).

---

## 6. Boot sequence contract (what conforming boot code does)

In order; steps 4–6 may be reordered or omitted if unneeded:

1. Validate the header (section 3.3): magic, version, total size.
2. Walk RAM regions; compute RAM top / total RAM.
3. Walk device records, skipping unknown types; record base addresses and
   params of recognized devices.
4. Install `vbase` and `dfbase` (MTSR) before executing anything that can
   fault, if the default triple-fault-on-early-trap behavior (section 2.2)
   is not acceptable.
5. Build page tables (ISA-SPEC.md section 8), `MTSR ptbase`, `INVTP`,
   then set `status.MMU_EN` — in that order. `INVTP` after table
   construction is mandatory (ISA-SPEC.md 8.7) even though it is a no-op
   on cache-less implementations.
6. Set `status.IE` when ready to take interrupts.

---

## 7. Test vectors

Format: each vector is a numbered block. Hex dumps use
`<PA:8 hex>: <bytes>`. Expectation lines are `expect <key> = <value>` —
one fact per line, machine-consumable.

### V1 — reference platform device table, byte-exact

The emulator must produce exactly these 328 bytes at `[0x0800, 0x0948)`
(and zeros in `[0x0948, 0x1000)`):

```
00000800: 53 41 48 41 52 41 50 54 01 00 00 00 00 00 00 00
00000810: 01 00 00 00 00 00 00 00 01 00 00 00 00 00 00 00
00000820: 04 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
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
00000940: 00 00 00 00 00 00 00 00
```

Field decode (a parser over the bytes above must yield exactly):

```
expect magic            = 0x5450415241484153
expect version          = 1
expect cpu_count        = 1
expect ram_region_count = 1
expect device_count     = 4
expect ram[0].base      = 0x0
expect ram[0].len       = 0x0F000000
expect ram_top          = 0x0F000000
expect ram_total        = 0x0F000000
expect dev[0].type      = 1
expect dev[0].base      = 0x0F000000
expect dev[0].size      = 0x10000
expect dev[0].params[0] = 0x10000000
expect dev[0].params[1] = 0x01000000
expect dev[0].params[2] = 0
expect dev[0].params[3] = 0
expect dev[1].type      = 2
expect dev[1].base      = 0x0F010000
expect dev[1].size      = 0x10000
expect dev[2].type      = 3
expect dev[2].base      = 0x0F020000
expect dev[2].size      = 0x10000
expect dev[3].type      = 4
expect dev[3].base      = 0x0F030000
expect dev[3].size      = 0x30000
expect dev[3].params[0] = 0x0000563412005452
expect table_end_pa     = 0x0948
```

### V2 — unknown-type skip

A 264-byte table: header (1 RAM region, 3 devices), keyboard, an unknown
type-9 record with nonzero params, mouse:

```
00000800: 53 41 48 41 52 41 50 54 01 00 00 00 00 00 00 00
00000810: 01 00 00 00 00 00 00 00 01 00 00 00 00 00 00 00
00000820: 03 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00000830: 00 00 00 00 00 00 00 00 00 00 00 0f 00 00 00 00
00000840: 00 00 00 00 00 00 00 00 02 00 00 00 00 00 00 00
00000850: 00 00 01 0f 00 00 00 00 00 00 00 00 00 00 00 00
00000860: 00 00 01 00 00 00 00 00 00 00 00 00 00 00 00 00
00000870: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00000880: 00 00 00 00 00 00 00 00 09 00 00 00 00 00 00 00
00000890: 00 00 0f 0f 00 00 00 00 00 00 00 00 00 00 00 00
000008a0: 00 00 01 00 00 00 00 00 ef be ad de 00 00 00 00
000008b0: 44 33 22 11 00 00 00 00 00 00 00 00 00 00 00 00
000008c0: 00 00 00 00 00 00 00 00 03 00 00 00 00 00 00 00
000008d0: 00 00 02 0f 00 00 00 00 00 00 00 00 00 00 00 00
000008e0: 00 00 01 00 00 00 00 00 00 00 00 00 00 00 00 00
000008f0: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00000900: 00 00 00 00 00 00 00 00
```

```
expect parse_result           = ok
expect recognized_devices     = 2
expect skipped_devices        = 1
expect keyboard.base          = 0x0F010000
expect mouse.base             = 0x0F020000
expect dev_record[1].type     = 9        # present in the table, skipped by the guest
```

### V3 — unknown header version refused

Header with `version = 2` (counts zero; contents after the header are
irrelevant to the vector):

```
00000800: 53 41 48 41 52 41 50 54 02 00 00 00 00 00 00 00
00000810: 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00000820: 00 00 00 00 00 00 00 00
```

```
expect parse_result = refused
expect guest_action = loud_failure     # boot does not proceed; e.g. HALT
```

### V4 — bad magic refused

As V1 but with byte at `0x0800` changed from `53` to `54`:

```
expect parse_result = refused
expect guest_action = loud_failure
```

### V5 — MAC packing

```
input  mac_octets       = aa:bb:cc:dd:ee:ff
expect params0_value    = 0x0000FFEEDDCCBBAA
expect params0_bytes    = aa bb cc dd ee ff 00 00
input  mac_octets       = 52:54:00:12:34:56
expect params0_value    = 0x0000563412005452
expect params0_bytes    = 52 54 00 12 34 56 00 00
```

### V6 — u128 field alignment trap

Against the V1 table, MMU off, supervisor mode:

```
input  instruction = LD128 rd, [0x0828]    # ram[0].base field, 8- but not 16-aligned
expect trap        = UNALIGNED (cause 9)
expect baddr       = 0x0828
input  instruction = LDZ.64 rd, [0x0828]   # low half via 64-bit load
expect result      = 0x0
expect trap        = none
input  instruction = LDZ.64 rd, [0x0838]   # ram[0].len low half
expect result      = 0x0F000000
expect trap        = none
```

### V7 — RAM sizing over multiple regions

Given a table with `ram_region_count = 2` and records
(`base=0x0, len=0x0F00_0000`), (`base=0x2000_0000, len=0x1000_0000`)
— valid: ascending, disjoint, non-adjacent, 64 KB-granular:

```
expect ram_top   = 0x30000000
expect ram_total = 0x1F000000
```

Structural rejection cases (the *emulator generator / table checker* must
refuse to emit these; a table-validating guest may also treat them as
fatal):

```
input  regions = (0x0, 0x0F000000), (0x0E000000, 0x1000000)   # overlap
expect table_valid = no
input  regions = (0x0, 0x0F000000), (0x0F000000, 0x1000000)   # adjacent, not coalesced
expect table_valid = no
input  regions = (0x20000000, 0x1000000), (0x0, 0x0F000000)   # not ascending
expect table_valid = no
input  regions = (0x0, 0x0F008000)                            # len not 64 KB multiple
expect table_valid = no
```

### V8 — reset state

At cycle 0, before the first instruction retires:

```
expect pc        = 0x1000
expect sreg[0]   = 0x8          # status: S=1, all else 0
expect sreg[1..15] = 0          # each of epc0..fcsr reads 0
expect gpr[0..30] = 0
expect gpr[31]   = 0            # hardwired
expect pred[0]   = 1            # hardwired
expect pred[1..7] = 0
```

### V9 — hole access

Reference platform (V1 table), MMU off, supervisor. PA `0x0F06_0000`
(above the NIC window end, below the pixel buffer) is in no declared
region:

```
input  instruction = LDZ.64 rd, [0x0F060000]
expect trap        = DEVERR (cause 12)
expect baddr       = 0x0F060000
input  instruction = (p1=0 predicated-false) LDZ.64 rd, [0x0F060000]
expect trap        = none               # predicated-false cannot fault
expect cycle_delta = 1
```

### V10 — reference table with the DMA engine (dev-dma branch; superseded at integration)

Additive vector for the accelerator wave: the reference platform table
of V1 extended with the type-6 DMA engine record (devspec/dma.md;
window base `0x0F07_0000`, size `0x1_0000`, all params 0 — limits live
in the device's CAPS register, not the table). `device_count` = 5 and
the encoded table is 392 bytes, `[0x0800, 0x0988)`, zeros in
`[0x0988, 0x1000)`. V1 and V2 above are unchanged and remain valid
vectors for a table without the engine.

**Superseded-at-integration marker:** this vector pins the dev-dma
branch's emulator output only. When the accelerator wave integrates,
the wave-final table adds the sibling devices' records in ascending
base order and replaces this vector; the type-6 *record bytes* (the 64
bytes below at `0x0948`) carry over verbatim, at whatever offset the
final record order gives them. Guests must locate the engine by type
code (section 4.2's skip rule makes positional assumptions
non-conforming), so nothing durable may cite this vector's record
position or `device_count`.

```
00000800: 53 41 48 41 52 41 50 54 01 00 00 00 00 00 00 00
00000810: 01 00 00 00 00 00 00 00 01 00 00 00 00 00 00 00
00000820: 05 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
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
00000940: 00 00 00 00 00 00 00 00 06 00 00 00 00 00 00 00
00000950: 00 00 07 0f 00 00 00 00 00 00 00 00 00 00 00 00
00000960: 00 00 01 00 00 00 00 00 00 00 00 00 00 00 00 00
00000970: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00000980: 00 00 00 00 00 00 00 00
```

```
expect device_count       = 5        # this branch only; see marker above
expect dev[4].type        = 6
expect dev[4].base        = 0x0F070000
expect dev[4].size        = 0x10000
expect dev[4].params[0]   = 0
expect dev[4].params[1]   = 0
expect dev[4].params[2]   = 0
expect dev[4].params[3]   = 0
expect table_end_pa       = 0x0988
```

---

## 8. Annotated example boot sequence (non-normative)

*Non-normative in its entirety.* A minimal but honest boot: validates the
table, sizes RAM, locates the display, installs trap vectors, builds a
one-node page table identity-mapping the first 16 MB, and enables the MMU.
Assembler syntax per TOOLING-SPEC.md section 4; store operand order
(`st.W [addr], value`) per devspec/asm.md section 5.5.

Simplifications, called out so no one copies them blindly: it assumes
`u128` table fields fit in 64 bits (it checks the high halves and fails
loudly if not); it maps only 16 MB, so device windows and the rest of RAM
are unreachable once the MMU is on; its trap handlers just halt.

```asm
# ---------------------------------------------------------------------
# boot.s — minimal reference-platform boot (non-normative example)
# ---------------------------------------------------------------------
        .equ DT_BASE,     0x800        # device table PA (platform constant)
        .equ DT_VERSION,  1
        .equ PTE_LEAF_RWX, 0x1E        # type=2 | R(bit2) | W(bit3) | X(bit4)

        .org 0x1000                    # reset PC (ISA-SPEC 11)
        .entry _reset
_reset:
        # ---- 1. validate the device table header (boot.md section 3.3)
        li      r1, DT_BASE
        ldz.64  r2, [r1 + 0]           # magic
        li      r3, 0x5450415241484153
        cmpeq.64 p1, r2, r3
        (!p1) b  fail                  # bad magic: refuse loudly
        ldz.64  r2, [r1 + 8]           # version
        cmpeq.64 p1, r2, DT_VERSION
        (!p1) b  fail                  # unknown version: refuse loudly

        # ---- 2. size RAM: walk the region records (section 3.4)
        # u128 fields are only 8-aligned: read them as two 64-bit loads.
        ldz.64  r4, [r1 + 24]          # ram_region_count
        add     r5, r1, 40             # r5 -> first RAM region record
        mov     r6, zero               # r6 = RAM top so far
ram_loop:
        cmpeq.64 p1, r4, zero
        (p1) b   ram_done
        ldz.64  r7, [r5 + 0]           # base, low 64
        ldz.64  r8, [r5 + 8]           # base, high 64
        ldz.64  r9, [r5 + 16]          # len,  low 64
        ldz.64  r10, [r5 + 24]         # len,  high 64
        or      r8, r8, r10
        cmpeq.64 p1, r8, zero          # example handles < 2^64 only;
        (!p1) b  fail                  #   anything bigger: fail loudly
        add     r7, r7, r9             # region end = base + len
        cmpltu  p2, r6, r7
        (p2) mov r6, r7                # RAM top = max(region end)
        add     r5, r5, 32             # next record
        sub.64  r4, r4, 1
        b       ram_loop
ram_done:
        la      r11, ram_top
        st.64   [r11 + 0], r6          # publish RAM top for later stages

        # ---- 3. walk device records; find the display (section 3.5)
        # r5 already points one past the RAM records = first device record.
        ldz.64  r4, [r1 + 32]          # device_count
dev_loop:
        cmpeq.64 p1, r4, zero
        (p1) b   dev_done
        ldz.64  r7, [r5 + 0]           # type
        cmpeq.64 p2, r7, 1             # display?
        (p2) ldz.64 r8, [r5 + 32]      # params[0] = pixel buffer PA
        (p2) la  r12, fb_pa
        (p2) st.64 [r12 + 0], r8
        # unknown types need no special case: the unconditional
        # 64-byte advance below IS the required skip rule (section 4.2).
        add     r5, r5, 64
        sub.64  r4, r4, 1
        b       dev_loop
dev_done:

        # ---- 4. install trap vectors before anything that may fault
        la      r2, trap_vector
        mtsr    vbase, r2
        la      r2, df_vector
        mtsr    dfbase, r2

        # ---- 5. page table: one node, identity map of [0, 16 MB), RWX.
        # Node layout (ISA-SPEC 8.2): 64-byte header (shift u64, prefix
        # u128, prefix_mask u128, rest reserved-zero) + 256 x 16-byte
        # entries. This node has shift 0 and covers VPN 0..255.
        la      r10, pt_root           # 64-byte aligned (see .align below)
        st.64   [r10 + 0], zero        # shift = 0
        st.64   [r10 + 8], zero        # prefix       = 0   (low)
        st.64   [r10 + 16], zero       #                    (high)
        li      r7, 0xFFFFFFFFFFFFFF00
        st.64   [r10 + 24], r7         # prefix_mask, low:  bits 8..63
        li      r7, 0x0000FFFFFFFFFFFF
        st.64   [r10 + 32], r7         # prefix_mask, high: bits 64..111
        st.64   [r10 + 40], zero       # reserved header bytes must be 0
        st.64   [r10 + 48], zero
        st.64   [r10 + 56], zero
        add     r12, r10, 64           # r12 -> entries[0]
        mov     r11, zero              # i = 0
pt_loop:
        shl     r13, r11, 16           # frame PA = i << 16
        or      r13, r13, PTE_LEAF_RWX # leaf entry, R+W+X, U=0
        st.64   [r12 + 0], r13         # entry low half
        st.64   [r12 + 8], zero        # entry high half
        add     r12, r12, 16
        add     r11, r11, 1
        cmplt   p1, r11, 256
        (p1) b  pt_loop

        # ---- 6. turn translation on (order per boot.md section 6)
        mtsr    ptbase, r10            # physical address of root node
        invtp                          # mandatory after table writes (ISA 8.7)
        mfsr    r7, status
        or      r7, r7, 4              # set MMU_EN (status bit 2)
        mtsr    status, r7
        # From the next fetch on, addresses are virtual; this code and its
        # data are identity-mapped, so execution continues seamlessly.

        li      sp, 0x1000000          # boot stack: top of the mapped 16 MB,
                                       # 16-byte aligned (ABI), grows down
        # ... a real boot proceeds to load an OS; the example stops loudly.
        halt

fail:                                  # any validation failure: loud stop
        halt

trap_vector:                           # real handlers: save state per
        halt                           #   ISA-SPEC 12 / 7.3; example halts
df_vector:
        halt

        # ---- data
        .align 16
ram_top:
        .oct 0                         # RAM top (u128 slot)
fb_pa:
        .oct 0                         # display pixel buffer PA

        .align 64                      # page-table nodes: 64-byte aligned
pt_root:
        .space 4160                    # ISA-SPEC 8.2 node size
```

Walkthrough of the interesting choices:

- **Header check first, loudly.** Bad magic or unknown version reaches
  `fail: halt` — vector V3/V4 behavior.
- **Two 64-bit loads per u128** (section 3.2): `LD128` would trap
  `UNALIGNED` on these offsets.
- **The skip rule is free.** Because version-1 records are fixed-size, the
  loop's unconditional `add r5, r5, 64` skips unknown types with no
  special case.
- **Vectors before MMU.** Between `mtsr vbase` and MMU-enable, a fault
  lands in `trap_vector` with `pc` still physical; after MMU-enable the
  same (identity-mapped) address works as a VA. Non-identity mappings
  would need the vector installed at its virtual address.
- **`invtp` before `MMU_EN`.** Required by ISA-SPEC 8.7 even on
  implementations with no translation cache, so the software contract is
  exercised from day one (and so the reference emulator's check mode — 
  CONFORMANCE.md C2 — does not flag the boot path).
- **Why the map is 16 MB:** one shift-0 node covers exactly 256 pages
  (VPN 0..255). Mapping all 240 MB of RAM plus device windows needs a
  two-level tree (a shift-8 node over shift-0 nodes) — more code than an
  example wants; a real OS builds that.

---

## 9. Conformance requirements

Numbered, testable; `E` = obligation on the emulator, `G` = on conforming
guest/boot code, `EG` = both. These feed CONFORMANCE.md as a new group
(boot/device-table; suggested tag C9-B).

- **BOOT-1 (E).** At reset the machine state equals section 2.2 exactly:
  `pc = 0x1000`, `status = 0x8`, sregs 1–15 = 0, GPRs r0–r30 = 0, p1–p7 =
  0. (Vector V8.)
- **BOOT-2 (E).** Before the first instruction executes, PAs
  `[0x0800, 0x1000)` contain the device table per sections 3.3–3.5, with
  all bytes past the encoded table zero. On the default-configured
  reference platform the bytes equal vector V1 exactly.
- **BOOT-3 (E).** The emulator never writes the table window after reset:
  a level-1 trace of any run contains no emulator-originated MEMW to
  `[0x0800, 0x1000)` (guest stores excepted).
- **BOOT-4 (E).** The loader rejects, before executing any guest
  instruction, an image with overlapping segments or a segment
  intersecting `[0x0800, 0x1000)`.
- **BOOT-5 (E).** Table structure invariants hold in every emitted table:
  magic and version correct; total size `40 + 32·R + 64·D` fits the
  window; RAM regions 64 KB-granular, ascending, disjoint, non-adjacent
  (V7 rejection cases); no RAM region overlaps any device window or the
  pixel buffer; every device `base`/`size` 64 KB-granular and mutually
  non-overlapping; all reserved fields zero.
- **BOOT-6 (E).** The device table window `[0x0800, 0x1000)` and the reset
  PC `0x1000` lie within a declared RAM region.
- **BOOT-7 (E).** Every u64 field of the table lies at an 8-byte-aligned
  PA. (Follows from 3.2/3.3–3.5; testable over the byte layout.)
- **BOOT-8 (EG).** An `LD128` from an 8-but-not-16-aligned table field PA
  traps `UNALIGNED` with `baddr` = that PA (vector V6). Guests read u128
  table fields as two u64 loads.
- **BOOT-9 (G).** A conforming guest refuses (fails loudly, does not
  continue booting) a table with wrong magic (V4) or a version it was not
  written for (V3).
- **BOOT-10 (G).** A conforming guest skips unknown device types: given
  vector V2's table it discovers the keyboard and mouse, performs no
  access derived from the type-9 record's base/params, and completes
  discovery normally.
- **BOOT-11 (G).** A conforming guest parses by `ram_region_count` and
  `device_count`, not by assuming the reference counts: it discovers all
  devices in a table with counts different from (1, 4), e.g. vector V2
  (3 devices) and vector V7 (2 RAM regions).
- **BOOT-12 (G).** Guest RAM sizing derives from the table: given V7's
  two-region table, computed RAM top = `0x3000_0000` and total =
  `0x1F00_0000`.
- **BOOT-13 (G).** A guest supporting one instance of a device type uses
  the first record of that type in table order when several are present.
- **BOOT-14 (E).** MAC packing: for any configured MAC, the table's NIC
  `params[0]` equals the section 3.6 value (vector V5), and the NIC `MAC`
  register (devspec/nic.md) reads back the identical value.
- **BOOT-15 (E).** A data access or instruction fetch whose PA falls in no
  declared RAM region and no device window traps `DEVERR` with `baddr` =
  the accessed (virtual) address (vector V9); a predicated-false such
  access does not trap and consumes one cycle.
- **BOOT-16 (E).** Determinism: the table bytes are a pure function of the
  emulator configuration (RAM size, MAC, device set). Two runs with the
  same configuration produce byte-identical tables, hence byte-identical
  META-level trace prefixes.
- **BOOT-17 (G).** Boot code performs `INVTP` after its last page-table
  store and before setting `status.MMU_EN` (order of section 6); the
  reference emulator's translation-check mode (CONFORMANCE.md C2) reports
  a stale-translation assertion otherwise.

---

## Issues raised against frozen specs (recorded, conservative reading used)

1. **PLATFORM-SPEC.md section 2:** "All fields little-endian, naturally
   aligned" is unsatisfiable for the u128 fields as laid out: the first
   RAM region's `base` falls at table offset 40 and a device record's
   `base` at record offset 8 — 8-aligned, not 16-aligned. Conservative
   reading used: the stated offsets are normative and exact; u128 fields
   are guaranteed only 8-byte alignment; guests read them as two u64
   loads (sections 3.2, BOOT-8).
2. **PLATFORM-SPEC.md section 1:** RAM region 0 described as
   "0x0 .. ram_len, default 256 MB" would span `[0, 0x1000_0000)` and
   overlap the device windows at `0x0F00_0000`–`0x0F06_0000`. Conservative
   reading used: declared RAM must never overlap device space, so the
   reference table declares region 0 as `[0, 0x0F00_0000)` (240 MB); the
   "256 MB" default is read as the address budget below the pixel buffer.
   `[0x0F06_0000, 0x1000_0000)` is a hole (BOOT-15).
