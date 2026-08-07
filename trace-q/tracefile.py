#!/usr/bin/env python3
"""Sahara execution-trace file IO — TOOLING-SPEC.md section 3.2 as
elaborated by devspec/trace.md sections 2-3.

Reader (strict, loud) and writer (used by tests to hand-build traces;
emulators write their own). Every record: u8 type, u8 0, u16 0,
u32 payload_len, then the payload. u128 = two little-endian u64s (lo, hi),
matching the image format.

Malformation policy (trace.md 2.4):
- torn tail (file ends mid-record): accepted; the complete-record prefix
  is returned and a diagnostic naming the offset of the incomplete
  record and the discarded byte count goes to stderr.
- everything else in trace.md's class-2 list raises TraceError (which
  trace-q maps to exit 2): nonzero reserved header bytes, type outside
  1-7, wrong fixed payload length, EVENT inner payload_len mismatch,
  EXEC flags bits 7:3 nonzero, META not record 0 / duplicated /
  grammar-violating / missing a mandatory key, decreasing cycle.
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

# trace.md 2.1: fixed payload lengths a reader must verify
FIXED_PAYLOAD_LEN = {T_EXEC: 50, T_MEMW: 41, T_MEMR: 41, T_TRAP: 49,
                     T_DEVW: 41}

# trace.md 2.3.7: the v1 META catalog, in catalog order
META_KEYS = ("trace", "encoding", "level", "mode", "image",
             "image_sha256", "platform")
# run-variant keys, excluded from trace comparison (trace.md 5.3, 6.5.6)
META_RUN_VARIANT = ("mode", "image")


class TraceError(Exception):
    pass


def pack_u128(v):
    return struct.pack("<QQ", v & (1 << 64) - 1, (v >> 64) & (1 << 64) - 1)


def unpack_u128(buf, off):
    lo, hi = struct.unpack_from("<QQ", buf, off)
    return lo | (hi << 64)


class Record:
    __slots__ = ("type", "payload", "fields", "index", "offset")

    def __init__(self, rtype, payload, fields, index, offset):
        self.type = rtype
        self.payload = payload
        self.fields = fields
        self.index = index
        self.offset = offset

    @property
    def name(self):
        return TYPE_NAMES.get(self.type, f"TYPE{self.type}")

    def __eq__(self, other):
        return (self.type, self.payload) == (other.type, other.payload)


def parse_meta_text(payload, where):
    """trace.md 2.3.7 line grammar -> dict. Raises TraceError loudly."""
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as e:
        raise TraceError(f"{where}: META payload is not UTF-8: {e}")
    kv = {}
    if text and not text.endswith("\n"):
        raise TraceError(f"{where}: META final line not LF-terminated")
    for line in text.split("\n")[:-1]:
        if "=" not in line:
            raise TraceError(f"{where}: META line without '=': {line!r}")
        key, val = line.split("=", 1)
        if not key or not all(c.islower() and c.isalnum() or c in "_0123456789"
                              for c in key):
            raise TraceError(f"{where}: META key violates [a-z0-9_]+: "
                             f"{key!r}")
        if "\x00" in val:
            raise TraceError(f"{where}: META value contains NUL: {key}")
        if key in kv:
            raise TraceError(f"{where}: duplicate META key {key}")
        kv[key] = val
    for k in META_KEYS:
        if k not in kv:
            raise TraceError(f"{where}: META missing mandatory key {k}")
    return kv


def parse_payload(rtype, payload, where="trace"):
    f = {}
    if rtype in FIXED_PAYLOAD_LEN and len(payload) != FIXED_PAYLOAD_LEN[rtype]:
        raise TraceError(
            f"{where}: {TYPE_NAMES[rtype]} payload is {len(payload)} "
            f"bytes, expected {FIXED_PAYLOAD_LEN[rtype]}")
    if rtype == T_EXEC:
        f["cycle"], = struct.unpack_from("<Q", payload, 0)
        f["pc"] = unpack_u128(payload, 8)
        f["insn"], = struct.unpack_from("<Q", payload, 24)
        f["wb"] = unpack_u128(payload, 32)
        f["flags"] = payload[48]
        f["pred_wb"] = payload[49]
        if f["flags"] & ~0x07:
            raise TraceError(f"{where}: EXEC flags bits 7:3 nonzero: "
                             f"0x{f['flags']:02x}")
    elif rtype in (T_MEMW, T_MEMR, T_DEVW):
        f["cycle"], = struct.unpack_from("<Q", payload, 0)
        f["ea"] = unpack_u128(payload, 8)
        f["size"] = payload[24]
        f["val"] = unpack_u128(payload, 25)
    elif rtype == T_TRAP:
        f["cycle"], f["cause"] = struct.unpack_from("<QQ", payload, 0)
        f["epc"] = unpack_u128(payload, 16)
        f["baddr"] = unpack_u128(payload, 32)
        f["tl_after"] = payload[48]
    elif rtype == T_EVENT:
        if len(payload) < 20:
            raise TraceError(f"{where}: EVENT payload too short: "
                             f"{len(payload)}")
        f["cycle"], f["device"], plen = struct.unpack_from("<QQI",
                                                           payload, 0)
        if plen != len(payload) - 20:
            raise TraceError(f"{where}: EVENT inner payload_len {plen} != "
                             f"{len(payload) - 20}")
        f["bytes"] = payload[20:]
    elif rtype == T_META:
        f["meta"] = parse_meta_text(payload, where)
    else:
        raise TraceError(f"{where}: record type {rtype} outside 1-7")
    return f


def read_records(path):
    """Read and validate a .trc per trace.md 2.4 / 3.1.

    Torn tail: the complete-record prefix is returned and a diagnostic
    goes to stderr. Class-2 malformations raise TraceError.
    """
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as e:
        raise TraceError(f"cannot read {path}: {e}")
    recs, i, idx = [], 0, 0
    last_cycle = None
    while i < len(data):
        if len(data) - i < HEADER.size:
            break  # torn tail: incomplete header
        rtype, r1, r2, plen = HEADER.unpack_from(data, i)
        if len(data) - i - HEADER.size < plen:
            break  # torn tail: incomplete payload
        if r1 or r2:
            raise TraceError(f"{path}: reserved header bytes nonzero at "
                             f"byte {i}")
        payload = data[i + HEADER.size:i + HEADER.size + plen]
        fields = parse_payload(rtype, payload, path)
        if idx == 0:
            if rtype != T_META:
                raise TraceError(f"{path}: first record is not META")
        elif rtype == T_META:
            raise TraceError(f"{path}: duplicate META at record {idx}")
        c = fields.get("cycle")
        if c is not None:
            if last_cycle is not None and c < last_cycle:
                raise TraceError(f"{path}: cycle decreases at record {idx} "
                                 f"({last_cycle} -> {c})")
            last_cycle = c
        recs.append(Record(rtype, payload, fields, idx, i))
        i += HEADER.size + plen
        idx += 1
    if i < len(data):
        print(f"trace-q: warning: {path}: torn tail: incomplete record at "
              f"offset {i}, {len(data) - i} bytes discarded",
              file=sys.stderr)
    if not recs:
        raise TraceError(f"{path}: no complete records (missing META)")
    return recs


# ------------------------------------------------------------------ writer


def write_record(fh, rtype, payload):
    fh.write(HEADER.pack(rtype, 0, 0, len(payload)))
    fh.write(payload)


def meta_payload(text):
    return text.encode("utf-8")


def meta_text(level, mode="live", image="test.img", image_sha256="0" * 64,
              encoding_version="1.0-draft", platform="1.0-draft"):
    """The mandatory 7-key v1 META text, in catalog order (trace.md
    2.3.7). Test writers use this so hand-built traces validate."""
    return (f"trace=1\nencoding={encoding_version}\nlevel={level}\n"
            f"mode={mode}\nimage={image}\nimage_sha256={image_sha256}\n"
            f"platform={platform}\n")


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
    """Address symbolization per trace.md 6.4: T/D kinds only, largest
    address <= target, same-address ties break to the lexicographically
    SMALLEST name, `name+0xoff` when inexact."""

    def __init__(self, syms):
        best = {}
        for a, k, n in syms:
            if k in ("T", "D") and (a not in best or n < best[a]):
                best[a] = n
        self.addr_syms = sorted(best.items())

    def lookup(self, addr):
        import bisect
        i = bisect.bisect_right(self.addr_syms, (addr, "\U0010ffff")) - 1
        if i < 0:
            return None
        base, name = self.addr_syms[i]
        off = addr - base
        return name if off == 0 else f"{name}+0x{off:x}"
