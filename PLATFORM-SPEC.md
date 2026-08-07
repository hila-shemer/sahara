# Sahara Reference Platform Specification

**Version 1.0-draft.** Companion to ISA-SPEC.md; covers everything Appendix B
of the ISA spec defers to the platform except tooling (see TOOLING-SPEC.md).
Normative for the reference platform. Boot firmware, OS, and device drivers
are written against this document.

The reference platform is a single-CPU Sahara machine with RAM, a display, a
keyboard, a mouse, and a network interface, implemented by an emulator that
runs as an interactive GUI application on a host, with a headless mode for
testing.

---

## 1. Physical memory map

All addresses physical. The device table is authoritative; the fixed
addresses below are the reference platform's defaults and are what the table
will contain on this platform.

| PA | size | contents |
|----|------|----------|
| 0x0000_0800 | 2 KB | device table (section 2), written by the emulator before reset |
| 0x0000_1000 | -- | reset PC (ISA-SPEC section 11); RAM |
| 0x0 .. ram_len | default 256 MB | RAM region 0 (contains both of the above) |
| 0x0F00_0000 | 64 KB | display control |
| 0x0F01_0000 | 64 KB | keyboard |
| 0x0F02_0000 | 64 KB | mouse |
| 0x0F03_0000 | 192 KB | NIC (registers + TX buffer + RX buffer) |
| 0x1000_0000 | per table | display pixel buffer |

The device table lives in ordinary RAM: the emulator writes it once before
reset and never again; the guest should treat it as read-only by convention.
Everything at 0x0F00_0000 and above in this map is device space in the sense
of ISA-SPEC section 9.2.

Device registers are 64 bits, naturally aligned, and must be accessed with
64-bit loads and stores; any other size traps DEVERR. The display pixel
buffer and the NIC TX/RX buffers are exceptions: they accept all access
sizes and behave as memory (reads return last written), while still being
device space for ordering purposes.

## 2. Device table

At PA 0x0800. All fields little-endian, naturally aligned.

Header (40 bytes):

| offset | field | value |
|-------:|-------|-------|
| 0  | magic u64 | 0x5450_4152_4148_4153 ("SAHARAPT" as bytes) |
| 8  | version u64 | 1 |
| 16 | cpu_count u64 | 1 in v1.0 |
| 24 | ram_region_count u64 | |
| 32 | device_count u64 | |

Followed by ram_region_count RAM regions (32 bytes each): base u128,
len u128. Followed by device_count device entries (64 bytes each):

| offset | field |
|-------:|-------|
| 0  | type u64 (table below) |
| 8  | base u128 (control-register window PA) |
| 24 | size u64 (window bytes) |
| 32 | params\[4\] u64 (per-type, below) |

| type | device | params |
|-----:|--------|--------|
| 1 | display  | \[0\] pixel buffer PA, \[1\] pixel buffer window size, \[2\]-\[3\] 0 |
| 2 | keyboard | 0 |
| 3 | mouse    | 0 |
| 4 | nic      | \[0\] MAC address (low 48 bits), \[1\]-\[3\] 0 |

Unknown types must be skipped by the guest (forward compatibility). Boot
code discovers everything -- RAM size, CPU count, devices -- from this table
and from it alone.

## 3. Interrupts

The platform has no interrupt controller. The ISA's single external
interrupt (EXTINT, cause 1) is the logical OR of every device's pending
condition:

- keyboard: event queue non-empty
- mouse: event queue non-empty
- nic: at least one received frame pending
- display: IRQ_STATUS non-zero

EXTINT is level-triggered: it remains pending until the handler clears every
device's condition (by draining queues / acknowledging). The handler
discovers sources by scanning the device table and reading each device's
status register. The architectural timer (ISA-SPEC 7.5) is independent of
all of this.

## 4. Display

Control window at base; registers at 64-bit offsets:

| off | reg | access | semantics |
|----:|-----|--------|-----------|
| 0  | PRESENT | W | present the current pixel buffer contents as a frame; value ignored |
| 8  | WIDTH  | R | current width, pixels |
| 16 | HEIGHT | R | current height, pixels |
| 24 | STRIDE | R | bytes per row |
| 32 | FORMAT | R | 1 = XRGB8888 little-endian (the only v1.0 format) |
| 40 | IRQ_STATUS | R | bit 0: mode changed (resize) |
| 48 | IRQ_ACK | W | write bit 0 to clear mode-changed |
| 56+ | reserved | | reads 0; writes ignored. Reserved for the dirty-rectangle / command extension. |

Pixel buffer: at the PA given in the device table, WIDTH x HEIGHT pixels,
4 bytes each, row start = buffer + y*STRIDE. Guest draws, then writes
PRESENT. The ordering rule of ISA-SPEC 9.2 makes PRESENT a release fence,
so all pixel writes are visible in the presented frame.

Resize: when the host window size changes, the emulator (at a
deterministic event cycle -- section 7) updates WIDTH/HEIGHT/STRIDE, sets
IRQ_STATUS bit 0, and raises EXTINT. The pixel buffer PA and window size do
not change; WIDTH*STRIDE never exceeds the window size in the table.
Frames presented between the resize and the guest's next PRESENT display
letterboxed or cropped; this is cosmetic and unspecified.

## 5. Keyboard

| off | reg | access | semantics |
|----:|-----|--------|-----------|
| 0 | DATA   | R | pop and return next event; all-ones if queue empty |
| 8 | STATUS | R | queue depth |

Event encoding (64 bits): bits 31:0 = USB HID keyboard usage ID; bit 32 =
1 press, 0 release; bits 63:33 = 0. DATA reads have a side effect (the
pop) and are ordered per ISA-SPEC 9.2. Queue depth is at least 256; on
overflow the newest events are dropped (and this is recorded in the event
trace so replay is exact).

## 6. Mouse

Same register layout as the keyboard. Event encoding (64 bits): bits 15:0
= x, bits 31:16 = y (unsigned pixel coordinates within the current display
mode, clamped), bits 39:32 = button state (bit 0 left, 1 right, 2 middle),
bits 63:40 = 0. Every event carries the full current state; an event is
emitted on any movement or button change. Coordinates are absolute.

## 7. Network interface

The emulator terminates and translates: guest Ethernet frames are NAT-ed
onto the host's network, slirp-style. No host-side promiscuous access; the
guest sees a private network:

- guest IP by convention 10.0.2.15/24, gateway 10.0.2.2, DNS 10.0.2.3
  (the emulator answers DHCP on this network, so static config is optional)
- MAC from the device table

Window layout (base = table entry base):

| off | region | semantics |
|----:|--------|-----------|
| 0x0_0000 | registers | below |
| 0x1_0000 | TX buffer, 64 KB | guest writes frame bytes here |
| 0x2_0000 | RX buffer, 64 KB | emulator writes received frame here |

Registers:

| off | reg | access | semantics |
|----:|-----|--------|-----------|
| 0  | TX_DOORBELL | W | transmit TX buffer bytes \[0, value); value in \[60, 1514\], else DEVERR |
| 8  | TX_STATUS | R | always 0 in v1.0 (transmit completes synchronously in virtual time) |
| 16 | RX_LEN | R | length of the frame currently in the RX buffer; 0 = none |
| 24 | RX_POP | W | consume the current RX frame; the next (if any) becomes visible |
| 32 | MAC | R | low 48 bits |

Frames are Ethernet II. Exactly one received frame is exposed at a time;
further arrivals queue inside the emulator. EXTINT pending while RX_LEN
is non-zero.

Determinism: received frames are events -- in live mode the emulator
assigns each arrival a virtual cycle and records (cycle, frame bytes) in
the event trace; in replay mode the trace is the only source and the host
network is not touched. Transmit is output, like the framebuffer.

## 8. Event trace and virtual time

All external input enters through the event queue of ISA-SPEC section 4:
keyboard events, mouse events, NIC arrivals, and display resizes, each as
(cycle, device, payload). An interactive GUI session records its inputs as
a trace as it runs; any session is therefore replayable bit-exactly in
headless mode. The trace file format is in TOOLING-SPEC.md.

## 9. Boot protocol

At reset (ISA-SPEC section 11) the machine executes at PA 0x1000,
supervisor, MMU off, interrupts off. The boot image has been loaded per
its image-format headers (TOOLING-SPEC.md) before reset. Boot code reads
the device table, sizes RAM, sets vbase/dfbase, builds page tables if it
wants translation, and proceeds. Nothing else is promised: no firmware
services, no callbacks -- the table is the entire hand-off.
