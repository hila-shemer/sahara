"""Sahara execution trace writer/reader — TOOLING-SPEC section 3.2 exactly.

Every record: u8 type, u8 0, u16 0, u32 payload_len, then the payload.
Byte-identical output is the cross-implementation comparison medium; every
field width here is normative.
"""

import struct

T_EXEC, T_MEMW, T_MEMR, T_TRAP, T_EVENT, T_DEVW, T_META = 1, 2, 3, 4, 5, 6, 7

# EXEC flags
F_SQUASHED = 1 << 0     # predicated-false
F_WROTE_DST = 1 << 1
F_WROTE_PRED = 1 << 2


def _u64(v):
    return (v & (1 << 64) - 1).to_bytes(8, "little")


def _u128(v):
    return (v & (1 << 128) - 1).to_bytes(16, "little")


class TraceWriter:
    """level 0 = EXEC+TRAP+EVENT+META; 1 adds MEMW/DEVW; 2 adds MEMR."""

    def __init__(self, f, level=1):
        self.f = f
        self.level = level

    def _rec(self, typ, payload):
        self.f.write(struct.pack("<BBHI", typ, 0, 0, len(payload)))
        self.f.write(payload)

    def meta(self, kv):
        text = "".join(f"{k}={v}\n" for k, v in kv)
        self._rec(T_META, text.encode())

    def exec_(self, cycle, pc, insn, wb, flags, pred_wb):
        self._rec(T_EXEC, _u64(cycle) + _u128(pc) + _u64(insn) + _u128(wb)
                  + bytes([flags, pred_wb]))

    def memw(self, cycle, ea, size, new):
        if self.level >= 1:
            self._rec(T_MEMW, _u64(cycle) + _u128(ea) + bytes([size])
                      + _u128(new))

    def memr(self, cycle, ea, size, val):
        if self.level >= 2:
            self._rec(T_MEMR, _u64(cycle) + _u128(ea) + bytes([size])
                      + _u128(val))

    def trap(self, cycle, cause, epc, baddr, tl_after):
        self._rec(T_TRAP, _u64(cycle) + _u64(cause) + _u128(epc)
                  + _u128(baddr) + bytes([tl_after]))

    def event(self, cycle, device, payload):
        self._rec(T_EVENT, _u64(cycle) + _u64(device)
                  + struct.pack("<I", len(payload)) + payload)

    def devw(self, cycle, ea, size, val):
        if self.level >= 1:
            self._rec(T_DEVW, _u64(cycle) + _u128(ea) + bytes([size])
                      + _u128(val))

    def close(self):
        self.f.flush()


def read_records(f):
    """Yields (type, payload) from a .trc stream. For replay and tests."""
    while True:
        hdr = f.read(8)
        if not hdr:
            return
        if len(hdr) < 8:
            raise ValueError("truncated trace record header")
        typ, z1, z2, plen = struct.unpack("<BBHI", hdr)
        if z1 or z2:
            raise ValueError("nonzero reserved bytes in trace header")
        payload = f.read(plen)
        if len(payload) < plen:
            raise ValueError("truncated trace payload")
        yield typ, payload


def parse_event(payload):
    """EVENT payload -> (cycle, device, bytes)."""
    cycle = int.from_bytes(payload[0:8], "little")
    device = int.from_bytes(payload[8:16], "little")
    plen = int.from_bytes(payload[16:20], "little")
    data = payload[20:20 + plen]
    if len(data) != plen:
        raise ValueError("EVENT payload length mismatch")
    return cycle, device, data
