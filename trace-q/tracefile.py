#!/usr/bin/env python3
"""Sahara execution-trace file IO — TOOLING-SPEC.md section 3.2.

Reader (strict, loud) and writer (used by tests to hand-build traces;
emulators write their own). Every record: u8 type, u8 0, u16 0,
u32 payload_len, then the payload. u128 = two little-endian u64s (lo, hi),
matching the image format.
"""

import struct
import sys

HEADER = struct.Struct("<BBHI")

T_EXEC, T_MEMW, T_MEMR, T_TRAP, T_EVENT, T_DEVW, T_META = 1, 2, 3, 4, 5, 6, 7
TYPE_NAMES = {T_EXEC: "EXEC", T_MEMW: "MEMW", T_MEMR: "MEMR",
              T_TRAP: "TRAP", T_EVENT: "EVENT", T_DEVW: "DEVW",
              T_META: "META"}

# EXEC flags bits (TOOLING-SPEC 3.2)
FLAG_SQUASHED, FLAG_WROTE_DST, FLAG_WROTE_PRED = 1, 2, 4


class TraceError(Exception):
    pass


def pack_u128(v):
    return struct.pack("<QQ", v & (1 << 64) - 1, (v >> 64) & (1 << 64) - 1)


def unpack_u128(buf, off):
    lo, hi = struct.unpack_from("<QQ", buf, off)
    return lo | (hi << 64)


class Record:
    __slots__ = ("type", "payload", "fields", "index")

    def __init__(self, rtype, payload, fields, index):
        self.type = rtype
        self.payload = payload
        self.fields = fields
        self.index = index

    @property
    def name(self):
        return TYPE_NAMES.get(self.type, f"TYPE{self.type}")

    def __eq__(self, other):
        return (self.type, self.payload) == (other.type, other.payload)


def _need(payload, n, name):
    if len(payload) != n:
        raise TraceError(f"{name} payload is {len(payload)} bytes, "
                         f"expected {n}")


def parse_payload(rtype, payload):
    f = {}
    if rtype == T_EXEC:
        _need(payload, 50, "EXEC")
        f["cycle"], = struct.unpack_from("<Q", payload, 0)
        f["pc"] = unpack_u128(payload, 8)
        f["insn"], = struct.unpack_from("<Q", payload, 24)
        f["wb"] = unpack_u128(payload, 32)
        f["flags"] = payload[48]
        f["pred_wb"] = payload[49]
    elif rtype in (T_MEMW, T_MEMR, T_DEVW):
        _need(payload, 41, TYPE_NAMES[rtype])
        f["cycle"], = struct.unpack_from("<Q", payload, 0)
        f["ea"] = unpack_u128(payload, 8)
        f["size"] = payload[24]
        f["val"] = unpack_u128(payload, 25)
    elif rtype == T_TRAP:
        _need(payload, 49, "TRAP")
        f["cycle"], f["cause"] = struct.unpack_from("<QQ", payload, 0)
        f["epc"] = unpack_u128(payload, 16)
        f["baddr"] = unpack_u128(payload, 32)
        f["tl_after"] = payload[48]
    elif rtype == T_EVENT:
        if len(payload) < 20:
            raise TraceError(f"EVENT payload too short: {len(payload)}")
        f["cycle"], f["device"], plen = struct.unpack_from("<QQI",
                                                           payload, 0)
        if plen != len(payload) - 20:
            raise TraceError(f"EVENT inner payload_len {plen} != "
                             f"{len(payload) - 20}")
        f["bytes"] = payload[20:]
    elif rtype == T_META:
        f["text"] = payload.decode("utf-8", errors="replace")
    else:
        raise TraceError(f"unknown record type {rtype}")
    return f


def read_records(path, require_meta=True):
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as e:
        raise TraceError(f"cannot read {path}: {e}")
    recs, i, idx = [], 0, 0
    while i < len(data):
        if len(data) - i < HEADER.size:
            raise TraceError(f"{path}: truncated record header at byte {i}")
        rtype, r1, r2, plen = HEADER.unpack_from(data, i)
        if r1 or r2:
            raise TraceError(f"{path}: reserved header bytes nonzero at "
                             f"byte {i}")
        i += HEADER.size
        if len(data) - i < plen:
            raise TraceError(f"{path}: truncated payload at byte {i}")
        payload = data[i:i + plen]
        i += plen
        recs.append(Record(rtype, payload, parse_payload(rtype, payload),
                           idx))
        idx += 1
    if require_meta and (not recs or recs[0].type != T_META):
        raise TraceError(f"{path}: first record is not META")
    return recs


# ------------------------------------------------------------------ writer


def write_record(fh, rtype, payload):
    fh.write(HEADER.pack(rtype, 0, 0, len(payload)))
    fh.write(payload)


def meta_payload(text):
    return text.encode("utf-8")


def exec_payload(cycle, pc, insn, wb=0, flags=0, pred_wb=0):
    return (struct.pack("<Q", cycle) + pack_u128(pc)
            + struct.pack("<Q", insn) + pack_u128(wb)
            + bytes([flags, pred_wb]))


def mem_payload(cycle, ea, size, val):
    return struct.pack("<Q", cycle) + pack_u128(ea) + bytes([size]) \
        + pack_u128(val)


def trap_payload(cycle, cause, epc, baddr, tl_after):
    return struct.pack("<QQ", cycle, cause) + pack_u128(epc) \
        + pack_u128(baddr) + bytes([tl_after])


def event_payload(cycle, device, data):
    return struct.pack("<QQI", cycle, device, len(data)) + data


# ------------------------------------------------------------------- sym


def load_sym(path):
    """Parse a .sym sidecar (TOOLING-SPEC section 2)."""
    syms = []
    try:
        with open(path) as fh:
            for lineno, line in enumerate(fh, 1):
                parts = line.split()
                if len(parts) != 3:
                    raise TraceError(f"{path}:{lineno}: bad sym line")
                addr, kind, name = parts
                if len(addr) != 32 or kind not in ("T", "D", "A"):
                    raise TraceError(f"{path}:{lineno}: bad sym line")
                syms.append((int(addr, 16), kind, name))
    except OSError as e:
        raise TraceError(f"cannot read {path}: {e}")
    return syms


class Symtab:
    def __init__(self, syms):
        # only address symbols (T/D) participate in address lookup
        self.addr_syms = sorted((a, n) for a, k, n in syms
                                if k in ("T", "D"))

    def lookup(self, addr):
        import bisect
        i = bisect.bisect_right(self.addr_syms, (addr, "\xff")) - 1
        if i < 0:
            return None
        base, name = self.addr_syms[i]
        off = addr - base
        return name if off == 0 else f"{name}+0x{off:x}"
