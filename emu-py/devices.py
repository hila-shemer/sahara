"""Sahara headless device model: display, keyboard/mouse input, NIC,
timer.

Register windows, the pixel/TX/RX buffer windows, and event injection
(`Device.event`) for the four event-fed devices — the queue/mailbox
behaviour (input.md 4, display.md 6.2/6.4, nic.md 4) plus the register
model of phase 2a. The timer (devspec/timer.md) is deliberately NOT
event-fed: it is a pure function of guest DEVW writes and the cycle
counter, and has no `event` method at all.

Addresses and register maps are the reference-platform defaults of
PLATFORM-SPEC.md section 1 and devspec/display.md, devspec/input.md,
devspec/nic.md, devspec/timer.md.
"""

import struct

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

TIMER_BASE = 0x0F060000         # devspec/timer.md 1, reference default
TIMER_SIZE = 0x10000

DMA_BASE = 0x0F070000           # devspec/dma.md 1: fills the old hole
DMA_SIZE = 0x10000

RNG_BASE = 0x0F080000           # devspec/rng.md 1
RNG_SIZE = 0x10000

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
    and changes only via a resize event (display.md 6.2)."""

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

    def event(self, payload):
        """display.md 6.2 / trace.md 4.4: 32-byte resize payload (four
        u64: width, height, stride, format). Applied atomically: WIDTH/
        HEIGHT/STRIDE together, then IRQ_STATUS bit 0 set (idempotent).
        FORMAT, the pixel buffer, and the window size are untouched."""
        if len(payload) != 32:
            raise ValueError(
                f"display resize EVENT payload length {len(payload)}, "
                f"want 32")
        width, height, stride, fmt = struct.unpack("<QQQQ", payload)
        if fmt != 1:
            raise ValueError(f"display resize EVENT format {fmt}, want 1")
        self.width, self.height, self.stride = width, height, stride
        self.irq_status |= 1
        return payload


class Input(mem.Device):
    """Keyboard/mouse register window: DATA (pop) / STATUS (depth),
    both read-only, 64-bit only, no other offset defined (input.md 1).

    Same class, same rule, for both keyboard and mouse (nothing here is
    device-specific): a 256-entry FIFO queue (input.md 4.1), drop-newest
    on overflow (input.md 4.2)."""

    OFF_DATA = 0x00
    OFF_STATUS = 0x08
    QUEUE_DEPTH = 256

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

    def event(self, payload):
        """input.md 4.1/4.2, trace.md 4.1/4.2: 9-byte payload (u64
        event word + u8 flags). The incoming flags byte is the feed's
        own claim and is never trusted (DECISIONS.md D11): the drop
        decision is this queue's own, recomputed from its own depth,
        and that is what gets returned for the caller to record."""
        if len(payload) != 9:
            raise ValueError(
                f"input EVENT payload length {len(payload)}, want 9")
        word = payload[0:8]
        dropped = len(self.queue) >= self.QUEUE_DEPTH
        if not dropped:
            self.queue.append(int.from_bytes(word, "little"))
        return word + bytes([1 if dropped else 0])


class Rng(mem.Device):
    """RNG register window (devspec/rng.md): DATA (pop / PRNG output),
    STATUS (queue depth), CTRL (bit 0 MODE, bit 1 IE), SEED (W).

    The entropy queue is fed only by EVENT records; in QUEUE mode an
    empty pop is DEVERR (rng.md 4.1 rule 4 — every u64 is a legal
    entropy word, so no in-band sentinel exists; the input-device
    all-ones sentinel deliberately does not apply). PRNG mode is pure
    guest-selected architectural state: MODE/SEED move only via
    DEVW-traced stores, and nothing here ever falls back from queue to
    PRNG or consults the host (rng.md 5.3)."""

    OFF_DATA = 0x00
    OFF_STATUS = 0x08
    OFF_CTRL = 0x10
    OFF_SEED = 0x18
    QUEUE_DEPTH = 256           # spec-fixed, not a device-table param
    CTRL_MODE = 1
    CTRL_IE = 2

    def __init__(self, base=RNG_BASE, size=RNG_SIZE):
        super().__init__(base, size)
        self.queue = []
        self.ctrl = 0
        self.prng_state = 0

    def _splitmix64(self):
        """rng.md 5.1, normative; every step masked to 64 bits."""
        self.prng_state = (self.prng_state + 0x9E3779B97F4A7C15) & MASK64
        z = self.prng_state
        z ^= z >> 30
        z = (z * 0xBF58476D1CE4E5B9) & MASK64
        z ^= z >> 27
        z = (z * 0x94D049BB133111EB) & MASK64
        z ^= z >> 31
        return z

    def load(self, off, size):
        if size != 8:
            raise mem.AccessError(self.base + off)          # E3
        if off == self.OFF_DATA:
            if self.ctrl & self.CTRL_MODE:
                return self._splitmix64()   # queue untouched (rng.md 5.2)
            if not self.queue:
                raise mem.AccessError(self.base + off)      # E6
            return self.queue.pop(0)
        if off == self.OFF_STATUS:
            return len(self.queue)          # mode-independent depth
        if off == self.OFF_CTRL:
            return self.ctrl
        # SEED is write-only (E2); everything else is unlisted (E1).
        raise mem.AccessError(self.base + off)

    def store(self, off, size, val):
        if size != 8:
            raise mem.AccessError(self.base + off)          # E3
        if off == self.OFF_CTRL:
            if val & ~3:
                raise mem.AccessError(self.base + off)      # E5
            self.ctrl = val
            return
        if off == self.OFF_SEED:
            self.prng_state = val & MASK64  # stream restarts (rng.md 5.1)
            return
        raise mem.AccessError(self.base + off)              # E2 / E1

    def pending(self):
        # IE-qualified level (rng.md 6): reset-off keeps the device
        # invisible to type-7-unaware kernels.
        return bool(self.ctrl & self.CTRL_IE) and bool(self.queue)

    def event(self, payload):
        """rng.md 4.2, trace.md 4.6: N LE u64 words, 1 <= N <= 128.
        Truncate-to-fit against the 256 cap, recomputed here on every
        apply (live and replay alike, SPEC-ISSUES 40); the returned
        bytes are the ACCEPTED prefix — what the caller records, and
        b\"\" means record nothing at all."""
        if (len(payload) == 0 or len(payload) % 8 != 0
                or len(payload) > 8 * 128):
            raise ValueError(
                f"RNG EVENT payload length {len(payload)}, want 8*N "
                f"with 1 <= N <= 128 (trace.md 4.6)")
        space = self.QUEUE_DEPTH - len(self.queue)
        take = min(len(payload) // 8, space)
        for i in range(take):
            self.queue.append(
                int.from_bytes(payload[8 * i:8 * i + 8], "little"))
        return payload[:8 * take]

class Dma(mem.Device):
    """DMA engine register window (devspec/dma.md): CAPS/STATUS/
    DOORBELL/IRQ_ACK/COMP_CYCLE. Memory-to-memory COPY and FILL from a
    64-byte descriptor latched at the doorbell; completion is cycle
    arithmetic on the doorbell cycle (C_done = C_db + K + LEN/8),
    applied atomically in the boundary device phase (machine.step calls
    advance() after process_events, before interrupt recognition).

    No event() — deliberately. A job is a pure function of (latched
    descriptor, RAM at the completion boundary, doorbell cycle): no
    EVENT feed, no host input, no trace records for the transfer
    itself (dma.md 7). The descriptor read and the transfer go through
    phys.read_raw/write_raw — the device-internal path that emits
    nothing, mirroring the NIC RX-buffer fill.

    `clock` is wired by Machine: a callable returning the current
    cycle, i.e. the value stamped on the doorbell store's own DEVW
    record. Only the doorbell consumes it."""

    OFF_CAPS = 0x00
    OFF_STATUS = 0x08
    OFF_DOORBELL = 0x10
    OFF_IRQ_ACK = 0x18
    OFF_COMP_CYCLE = 0x20

    # STATUS codes (dma.md 3.2)
    IDLE, BUSY, DONE = 0, 1, 2
    BAD_OP, BAD_FORMAT, BAD_ALIGN, BAD_RANGE = 3, 4, 5, 6

    # spec-pinned constants, mirrored in CAPS (dma.md 1, 3.1, 6)
    K = 8
    W = 8
    LEN_MAX = 1 << 24
    CAPS = 1 | (3 << 8) | (K << 16) | (24 << 24)    # 0x18080301

    def __init__(self, base, size, phys):
        super().__init__(base, size)
        self.phys = phys
        self.clock = None               # wired by Machine
        self.status = self.IDLE
        self.comp_cycle = 0
        self.irq_pending = False
        self.op = self.src = self.dst = self.len = 0   # latched at doorbell

    def load(self, off, size):
        if size != 8:
            raise mem.AccessError(self.base + off)          # E1
        if off == self.OFF_CAPS:
            return self.CAPS
        if off == self.OFF_STATUS:
            return self.status
        if off == self.OFF_COMP_CYCLE:
            return self.comp_cycle
        # DOORBELL/IRQ_ACK are write-only (E3); unlisted offsets fault
        # in BOTH directions (E2 — no inert reserved window, root
        # SPEC-ISSUES 41).
        raise mem.AccessError(self.base + off)

    def store(self, off, size, val):
        if size != 8:
            raise mem.AccessError(self.base + off)          # E1
        if off == self.OFF_DOORBELL:
            # Access-class checks, fixed order E5 -> E6 -> E7
            # (dma.md 2.1): DEVERR with zero device effect.
            if self.status == self.BUSY:
                raise mem.AccessError(self.base + off)      # E5
            if val & 63:
                raise mem.AccessError(self.base + off)      # E6
            if not self.phys.in_ram(val, 64):
                raise mem.AccessError(self.base + off)      # E7
            self._doorbell(val, self.clock())
            return
        if off == self.OFF_IRQ_ACK:
            if val != 1:
                raise mem.AccessError(self.base + off)      # E8: 0 too
            self.irq_pending = False    # no-op if clear: race-free
            return
        raise mem.AccessError(self.base + off)   # E4 read-only, or E2

    def _doorbell(self, pa, cycle):
        """dma.md 5.2 steps 2-5: latch the 64 descriptor bytes (a
        device-internal read, no MEMR records), validate content in
        the fixed order BAD_OP -> BAD_FORMAT -> BAD_ALIGN -> BAD_RANGE
        (first failure wins), then arm or terminate. Content badness
        never traps: the store retires either way."""
        desc = self.phys.read_raw(pa, 64)
        op, src, dst, length = struct.unpack_from("<QQQQ", desc, 0)
        next_, r40, r48, r56 = struct.unpack_from("<QQQQ", desc, 32)
        opcode = op & 0xFF
        copy = opcode == 1

        if opcode not in (1, 2):
            status = self.BAD_OP        # 0 included: zeroed-RAM guard
        elif (op >> 9) or next_ or r40 or r48 or r56:
            status = self.BAD_FORMAT
        elif (copy and src & 7) or dst & 7 or length & 7:
            status = self.BAD_ALIGN     # FILL: src is a pattern
        elif (length == 0 or length > self.LEN_MAX
              or (copy and not self.phys.in_ram(src, length))
              or not self.phys.in_ram(dst, length)):
            status = self.BAD_RANGE
        else:
            status = self.BUSY

        self.status = status
        if status != self.BUSY:
            # Terminal at the doorbell itself: no BUSY window, nothing
            # written; pending rises iff the descriptor asked for it.
            self.comp_cycle = cycle
            if (op >> 8) & 1:
                self.irq_pending = True
            return
        self.op, self.src, self.dst, self.len = op, src, dst, length
        self.comp_cycle = cycle + self.K + length // self.W

    def advance(self, cycle):
        """The boundary device phase's completion step (dma.md 5.5):
        the whole transfer at the first boundary with cycle >= C_done,
        as if through an intermediate buffer — read_raw of the full
        source range then write_raw, which is exactly memmove under
        overlap. Sources are live RAM (sampled at completion, never a
        doorbell-time stash). The weak-store queue must already be
        drained here; assert, don't re-flush (D10 drains at the
        doorbell and any later device access)."""
        if self.status != self.BUSY or cycle < self.comp_cycle:
            return
        assert not self.phys.queue, \
            "ordinary stores still queued at a DMA completion boundary"
        if (self.op & 0xFF) == 1:
            self.phys.write_raw(self.dst, self.phys.read_raw(self.src,
                                                             self.len))
        else:
            self.phys.write_raw(self.dst,
                                self.src.to_bytes(8, "little")
                                * (self.len // 8))
        self.status = self.DONE
        if (self.op >> 8) & 1:
            self.irq_pending = True     # the ONLY completion-path flip

    def wake_cycle(self):
        """WFI wake source (dma.md 7.5): the in-flight job's C_done,
        but only when latched OP bit 8 is set — a bit-8-clear job
        cannot make an interrupt pending, so it cannot end a stall
        (root SPEC-ISSUES 43)."""
        if self.status == self.BUSY and (self.op >> 8) & 1:
            return self.comp_cycle
        return None

    def pending(self):
        return self.irq_pending


class Nic(mem.Device):
    """NIC register region only (nic.md 2.1): TX_DOORBELL/TX_STATUS/
    RX_LEN/RX_POP/MAC. The TX and RX buffers are separate `Buffer`
    device windows at +0x1_0000 / +0x2_0000 (see NIC_TX_OFFSET/
    NIC_RX_OFFSET); the RX one is also passed in here so the mailbox
    (nic.md 4.1) can write frame bytes into it directly.

    Scope boundary (DECISIONS.md D8): the translator (nic.md 6.3-6.9 —
    ARP/DHCP/UDP/DNS/TCP/ICMP) is not implemented. Every TX_DOORBELL
    frame therefore reaches nic.md 6.2's "matches nothing" leaf and is
    dropped silently: no reply, no event, no trap beyond the length
    check below. Do not read this as a stub for the translator; it is
    the deliberately out-of-scope gap, tracked in D8/SPEC-ISSUES.md.

    The RX *arrival* path (event admission, exposure, the 64-frame
    cap) is in scope (DECISIONS.md D12) and implemented in full."""

    OFF_TX_DOORBELL = 0x00
    OFF_TX_STATUS = 0x08
    OFF_RX_LEN = 0x10
    OFF_RX_POP = 0x18
    OFF_MAC = 0x20

    RX_CAPACITY = 64            # nic.md 4.1: 1 exposed + up to 63 queued

    def __init__(self, base, size, mac, rx_buffer):
        super().__init__(base, size)
        self.mac = mac & ((1 << 48) - 1)
        self.rx_buffer = rx_buffer
        self.rx_len = 0
        self.rx_queue = []      # admitted frames not yet exposed, FIFO

    def _expose(self, frame):
        self.rx_buffer.data[0:len(frame)] = frame
        self.rx_len = len(frame)

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
            if self.rx_queue:
                self._expose(self.rx_queue.pop(0))          # nic.md 2.4/4.2
            else:
                self.rx_len = 0
            return
        raise mem.AccessError(self.base + off)               # E2

    def pending(self):
        return self.rx_len != 0

    def event(self, payload):
        """nic.md 4.1-4.4, trace.md 4.3: payload is the frame bytes
        verbatim, exposed immediately if the mailbox is EMPTY, else
        queued (FIFO, admission order). Overflow past the 64-frame cap
        cannot occur in replay (nic.md 4.3) — an arrival past the cap
        here is a malformed feed, not a drop."""
        if len(payload) < 60 or len(payload) > 1514:
            raise ValueError(
                f"NIC EVENT frame length {len(payload)}, want [60, 1514]")
        held = (1 if self.rx_len else 0) + len(self.rx_queue)
        if held >= self.RX_CAPACITY:
            raise ValueError(
                "NIC EVENT arrival past the 64-frame cap: cannot occur "
                "in a well-formed replay feed (nic.md 4.3)")
        if self.rx_len == 0:
            self._expose(payload)
        else:
            self.rx_queue.append(payload)
        return payload


class Timer(mem.Device):
    """Periodic-tick accelerator (devspec/timer.md): COUNT/PERIOD/
    STATUS/ACK, guest state exactly {period, next_fire}, pending
    derived - never stored - as period > 0 and cycle >= next_fire.

    `tick(cycle)` runs in the boundary device phase (trace.md 3.3:
    after EVENT apply, before interrupt recognition): it caches the
    boundary cycle and recomputes pending. Register accesses read the
    cache as their C/W/A, which equals the accessing instruction's own
    record cycle - the byte-match contract with emu-c.

    No `event` method on purpose: the timer is a pure function of
    guest DEVW writes and the counter, and an EVENT naming it is a
    malformed trace (timer.md 5, trace.md 4.5) - an index that
    resolves here must never reach a device handler."""

    OFF_COUNT = 0x00
    OFF_PERIOD = 0x08
    OFF_STATUS = 0x10
    OFF_ACK = 0x18

    def __init__(self, base=TIMER_BASE, size=TIMER_SIZE):
        super().__init__(base, size)
        self.period = 0
        self.next_fire = 0
        self.now = 0                # boundary-cycle cache
        self.pend = False           # cached derived pending

    def tick(self, cycle):
        self.now = cycle
        self.pend = self.period > 0 and cycle >= self.next_fire

    def load(self, off, size):
        if size != 8:
            raise mem.AccessError(self.base + off)          # E3
        if off == self.OFF_COUNT:
            # low 64 bits of the counter at the boundary preceding the
            # load (timer.md 4.1) == this MEMR's own record cycle
            return self.now & MASK64
        if off == self.OFF_PERIOD:
            return self.period                              # last written
        if off == self.OFF_STATUS:
            return 1 if self.pend else 0
        if off == self.OFF_ACK:
            raise mem.AccessError(self.base + off)          # E2
        raise mem.AccessError(self.base + off)               # E1

    def store(self, off, size, val):
        if size != 8:
            raise mem.AccessError(self.base + off)          # E3
        if off == self.OFF_PERIOD:
            # Arm: next_fire = W + N, W = this store's DEVW cycle (the
            # cached boundary cycle). 0 disarms - pending derives from
            # period > 0, so next_fire goes stale harmlessly. Rewrite
            # while armed re-arms fresh (timer.md 4.2).
            self.period = val
            if val:
                self.next_fire = self.now + val
            return
        if off == self.OFF_ACK:
            if val != 1:
                raise mem.AccessError(self.base + off)      # E5
            if self.pend:
                # Phase-locked advance (timer.md 4.4): smallest k >= 1
                # with next_fire + k*period > A keeps fires on the
                # W + m*N grid; pending implies A >= next_fire.
                k = (self.now - self.next_fire) // self.period + 1
                self.next_fire += k * self.period
            return                                          # else no-op
        if off in (self.OFF_COUNT, self.OFF_STATUS):
            raise mem.AccessError(self.base + off)          # E2
        raise mem.AccessError(self.base + off)               # E1

    def pending(self):
        return self.pend
