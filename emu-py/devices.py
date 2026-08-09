"""Sahara headless device model: display, keyboard/mouse input, NIC.

Phase 2a (the headless tranche, CURRENT_TASK.md): register windows, the
pixel/TX/RX buffer windows, and correct *empty* queue behaviour. Event
injection (`Device.event`) and interrupt delivery for these devices are
phase 2b — the queues here are built empty and stay empty; nothing feeds
them yet.

Addresses and register maps are the reference-platform defaults of
PLATFORM-SPEC.md section 1 and devspec/display.md, devspec/input.md,
devspec/nic.md.
"""

import mem

MASK64 = (1 << 64) - 1

# ---- reference platform addresses (PLATFORM-SPEC 1, devspec bases) ----
DISPLAY_BASE = 0x0F000000
DISPLAY_SIZE = 0x10000          # 64 KB control window

KBD_BASE = 0x0F010000
KBD_SIZE = 0x10000

MOUSE_BASE = 0x0F020000
MOUSE_SIZE = 0x10000

NIC_BASE = 0x0F030000
NIC_REG_SIZE = 0x10000          # register region only (nic.md 2.1)
NIC_TX_OFFSET = 0x10000
NIC_RX_OFFSET = 0x20000
NIC_WINDOW_SIZE = 0x30000       # registers + TX buf + RX buf = 192 KB

PIXBUF_BASE = 0x10000000
PIXBUF_SIZE = 0x1000000         # 16 MB (devspec/display.md 1, reference default)

# reference MAC 52:54:00:12:34:56 (SPEC-ISSUES #12 pinned default)
REFERENCE_MAC_OCTETS = (0x52, 0x54, 0x00, 0x12, 0x34, 0x56)


def pack_mac(octets):
    """boot.md 3.6 / nic.md 2.5 packing: wire byte 0 in bits 7:0, ...
    byte 5 in bits 47:40."""
    m0, m1, m2, m3, m4, m5 = octets
    return m0 | (m1 << 8) | (m2 << 16) | (m3 << 24) | (m4 << 32) | (m5 << 40)


class Buffer(mem.Device):
    """A memory-like device window: any of sizes 1/2/4/8/16, naturally
    aligned (checked upstream by exec_mem), last-write-wins, reads 0
    before the first store. Used for the pixel buffer and the NIC TX/RX
    buffers (PLATFORM-SPEC 1; display.md 3.1; nic.md 2.6)."""

    def __init__(self, base, size):
        super().__init__(base, size)
        self.data = bytearray(size)

    def load(self, off, size):
        return int.from_bytes(self.data[off:off + size], "little")

    def store(self, off, size, val):
        self.data[off:off + size] = \
            (val & ((1 << (8 * size)) - 1)).to_bytes(size, "little")


class Display(mem.Device):
    """Control window: PRESENT/WIDTH/HEIGHT/STRIDE/FORMAT/IRQ_STATUS/
    IRQ_ACK plus the reserved extension window (display.md 2, 4, 8).

    Geometry starts at the pinned reference default (SPEC-ISSUES #12)
    and never changes in this phase: no resize event exists yet
    (phase 2b)."""

    OFF_PRESENT = 0x00
    OFF_WIDTH = 0x08
    OFF_HEIGHT = 0x10
    OFF_STRIDE = 0x18
    OFF_FORMAT = 0x20
    OFF_IRQ_STATUS = 0x28
    OFF_IRQ_ACK = 0x30
    OFF_RESERVED_START = 0x38

    def __init__(self, base=DISPLAY_BASE, size=DISPLAY_SIZE):
        super().__init__(base, size)
        self.width = 640
        self.height = 480
        self.stride = 2560
        self.irq_status = 0

    def load(self, off, size):
        # display.md 2 rule: control-window registers are 64-bit-only;
        # any other size traps DEVERR everywhere in the window,
        # including the reserved extension (rule 5).
        if size != 8:
            raise mem.AccessError(self.base + off)
        if off in (self.OFF_PRESENT, self.OFF_IRQ_ACK):
            raise mem.AccessError(self.base + off)   # write-only (D-03)
        if off == self.OFF_WIDTH:
            return self.width
        if off == self.OFF_HEIGHT:
            return self.height
        if off == self.OFF_STRIDE:
            return self.stride
        if off == self.OFF_FORMAT:
            return 1
        if off == self.OFF_IRQ_STATUS:
            return self.irq_status & 1
        if off >= self.OFF_RESERVED_START:
            return 0                                  # D-05
        raise mem.AccessError(self.base + off)

    def store(self, off, size, val):
        if size != 8:
            raise mem.AccessError(self.base + off)
        if off == self.OFF_PRESENT:
            # PRESENT is pure output (display.md 5): no register or
            # buffer state changes here. The pixel buffer's own writes
            # already happened via the Buffer device; the emulator does
            # not model rendering in headless mode.
            return
        if off == self.OFF_IRQ_ACK:
            if val & ~1:
                raise mem.AccessError(self.base + off)   # D-18
            if val & 1:
                self.irq_status &= ~1
            return
        if off >= self.OFF_RESERVED_START:
            return                                       # D-05: ignored
        raise mem.AccessError(self.base + off)            # read-only regs

    def pending(self):
        return self.irq_status != 0


class Input(mem.Device):
    """Keyboard/mouse register window: DATA (pop) / STATUS (depth),
    both read-only, 64-bit only, no other offset defined (input.md 1).

    The queue starts empty and stays empty in this phase: event
    injection is phase 2b."""

    OFF_DATA = 0x00
    OFF_STATUS = 0x08

    def __init__(self, base, size):
        super().__init__(base, size)
        self.queue = []

    def load(self, off, size):
        if size != 8:
            raise mem.AccessError(self.base + off)        # rule 1
        if off == self.OFF_DATA:
            if not self.queue:
                return MASK64                              # empty sentinel
            return self.queue.pop(0)
        if off == self.OFF_STATUS:
            return len(self.queue)
        raise mem.AccessError(self.base + off)              # rule 3

    def store(self, off, size, val):
        raise mem.AccessError(self.base + off)               # rule 2

    def pending(self):
        return bool(self.queue)


class Nic(mem.Device):
    """NIC register region only (nic.md 2.1): TX_DOORBELL/TX_STATUS/
    RX_LEN/RX_POP/MAC. The TX and RX buffers are separate `Buffer`
    device windows at +0x1_0000 / +0x2_0000 (see NIC_TX_OFFSET/
    NIC_RX_OFFSET), instantiated alongside this one.

    Scope boundary (DECISIONS.md D8): the translator (nic.md 6.3-6.9 —
    ARP/DHCP/UDP/DNS/TCP/ICMP) is not implemented. Every TX_DOORBELL
    frame therefore reaches nic.md 6.2's "matches nothing" leaf and is
    dropped silently: no reply, no event, no trap beyond the length
    check below. Do not read this as a stub for the translator; it is
    the deliberately out-of-scope gap, tracked in D8/SPEC-ISSUES.md."""

    OFF_TX_DOORBELL = 0x00
    OFF_TX_STATUS = 0x08
    OFF_RX_LEN = 0x10
    OFF_RX_POP = 0x18
    OFF_MAC = 0x20

    def __init__(self, base, size, mac):
        super().__init__(base, size)
        self.mac = mac & ((1 << 48) - 1)
        self.rx_len = 0             # no admitted frames in this phase

    def load(self, off, size):
        if size != 8:
            raise mem.AccessError(self.base + off)          # E1
        if off == self.OFF_TX_DOORBELL:
            raise mem.AccessError(self.base + off)          # E3
        if off == self.OFF_TX_STATUS:
            return 0                                        # always 0
        if off == self.OFF_RX_LEN:
            return self.rx_len
        if off == self.OFF_RX_POP:
            raise mem.AccessError(self.base + off)          # E3
        if off == self.OFF_MAC:
            return self.mac
        raise mem.AccessError(self.base + off)               # E2

    def store(self, off, size, val):
        if size != 8:
            raise mem.AccessError(self.base + off)          # E1
        if off == self.OFF_TX_DOORBELL:
            if val < 60 or val > 1514:
                raise mem.AccessError(self.base + off)      # E5
            # Frame captured synchronously (nic.md 4.5). No translator
            # is implemented (D8): every frame matches nothing in the
            # nic.md 6.2 decision tree and is dropped silently here —
            # no reply, no event, no trap.
            return
        if off in (self.OFF_TX_STATUS, self.OFF_MAC):
            raise mem.AccessError(self.base + off)          # E4
        if off == self.OFF_RX_LEN:
            raise mem.AccessError(self.base + off)          # E4
        if off == self.OFF_RX_POP:
            if self.rx_len == 0:
                raise mem.AccessError(self.base + off)      # E6
            self.rx_len = 0     # no queued frames to expose in 2a
            return
        raise mem.AccessError(self.base + off)               # E2

    def pending(self):
        return self.rx_len != 0
