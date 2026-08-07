"""Sahara physical memory: sparse RAM, device windows, weak-store queue.

Sparse from the first line (page-number -> block); the RAM region bound is
platform configuration (the device table's RAM region), not a core limit.
Device windows are the MMIO seam of the common prompt: dispatch is hooked
off the physical path even while no devices exist yet.
"""

import encoding as E

PAGE_SIZE = 1 << E.PAGE_BITS
MASK128 = (1 << 128) - 1


class AccessError(Exception):
    """Physical access outside RAM and every device window, or a device
    rejecting the access. Maps to cause DEVERR at the ISA level (see
    SPEC-ISSUES.md on out-of-map physical accesses)."""

    def __init__(self, pa):
        super().__init__(f"physical access fault at 0x{pa:x}")
        self.pa = pa


class SparseMem:
    """page-number -> bytearray block. No flat allocation, no ceiling."""

    def __init__(self):
        self.pages = {}

    def _page(self, pn):
        blk = self.pages.get(pn)
        if blk is None:
            blk = self.pages[pn] = bytearray(PAGE_SIZE)
        return blk

    def read(self, pa, n):
        out = bytearray()
        while n:
            pn, off = pa >> E.PAGE_BITS, pa & (PAGE_SIZE - 1)
            take = min(n, PAGE_SIZE - off)
            blk = self.pages.get(pn)
            if blk is None:
                out += bytes(take)
            else:
                out += blk[off:off + take]
            pa, n = (pa + take) & MASK128, n - take
        return bytes(out)

    def write(self, pa, data):
        i, n = 0, len(data)
        while i < n:
            pn, off = pa >> E.PAGE_BITS, pa & (PAGE_SIZE - 1)
            take = min(n - i, PAGE_SIZE - off)
            self._page(pn)[off:off + take] = data[i:i + take]
            pa, i = (pa + take) & MASK128, i + take


class Device:
    """MMIO seam. Subclasses arrive in the device phase (gated)."""

    def __init__(self, base, size):
        self.base, self.size = base, size

    def load(self, off, size):          # -> int value
        raise AccessError(self.base + off)

    def store(self, off, size, val):
        raise AccessError(self.base + off)

    def pending(self):                  # contributes to EXTINT level
        return False

    def event(self, payload):           # virtual-cycle event injection
        raise AccessError(self.base)


class PhysMap:
    """Routes physical accesses to RAM or a device window.

    Optional weak-store check mode (--check-devorder N): ordinary stores
    sit in a queue of depth N; device stores drain it first (the release
    rule of ISA-SPEC 9.2); the processor's own loads/fetches snoop the
    queue so single-CPU program order is preserved.
    """

    def __init__(self, ram_len, devorder=None, dev_base=None):
        # dev_base: start of platform device space (PLATFORM-SPEC 1:
        # "everything at 0x0F00_0000 and above in this map is device
        # space"). The device windows overlap RAM region 0's extent in
        # the spec's map; the carve-out wins for routing: no PA at or
        # above dev_base is ever RAM, even before any device instance
        # is registered — an access there with no mapped device is an
        # AccessError (-> DEVERR). See SPEC-ISSUES.md entry 24.
        self.ram = SparseMem()
        if dev_base is not None:
            ram_len = min(ram_len, dev_base)
        self.ram_regions = [(0, ram_len)]
        self.dev_base = dev_base
        self.devices = []
        self.devorder = devorder            # None = off; else queue depth
        self.queue = []                     # [(pa, bytes)] oldest first

    def add_device(self, dev):
        self.devices.append(dev)

    def device_at(self, pa):
        for d in self.devices:
            if d.base <= pa < d.base + d.size:
                return d
        return None

    def in_ram(self, pa, n):
        for base, ln in self.ram_regions:
            if base <= pa and pa + n <= base + ln:
                return True
        return False

    # -- raw access, loader/device-table use (no queue, no faults) --------
    def write_raw(self, pa, data):
        self.ram.write(pa, data)

    def read_raw(self, pa, n):
        return self.ram.read(pa, n)

    # -- CPU access path --------------------------------------------------
    def load(self, pa, n):
        """Returns (value:int, device_or_None). Raises AccessError."""
        dev = self.device_at(pa)
        if dev is not None:
            if pa + n > dev.base + dev.size:
                raise AccessError(pa)
            return dev.load(pa - dev.base, n), dev
        if not self.in_ram(pa, n):
            raise AccessError(pa)
        data = bytearray(self.ram.read(pa, n))
        # snoop the weak-store queue, oldest to newest
        for qpa, qdata in self.queue:
            lo = max(pa, qpa)
            hi = min(pa + n, qpa + len(qdata))
            if lo < hi:
                data[lo - pa:hi - pa] = qdata[lo - qpa:hi - qpa]
        return int.from_bytes(data, "little"), None

    def store(self, pa, n, val):
        """Returns device_or_None. Raises AccessError."""
        data = (val & ((1 << (8 * n)) - 1)).to_bytes(n, "little")
        dev = self.device_at(pa)
        if dev is not None:
            if pa + n > dev.base + dev.size:
                raise AccessError(pa)
            self.drain()                    # release fence: rule 9.2(1)
            dev.store(pa - dev.base, n, val)
            return dev
        if not self.in_ram(pa, n):
            raise AccessError(pa)
        if self.devorder is None:
            self.ram.write(pa, data)
        else:
            self.queue.append((pa, data))
            while len(self.queue) > self.devorder:
                cpa, cdata = self.queue.pop(0)
                self.ram.write(cpa, cdata)
        return None

    def drain(self):
        for cpa, cdata in self.queue:
            self.ram.write(cpa, cdata)
        self.queue.clear()

    def any_device_pending(self):
        return any(d.pending() for d in self.devices)
