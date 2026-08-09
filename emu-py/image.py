"""Sahara image (.img) loader and device-table writer.

Image format per TOOLING-SPEC section 1; device table per PLATFORM-SPEC
section 2. The machine starts at the architectural reset PC (0x1000);
the image's entry field is convention only (see SPEC-ISSUES.md).
"""

import struct

import encoding as E

MAGIC = b"SAHIMG01"
HEADER_LEN = 32
SEG_LEN = 48

DEVTAB_PA = 0x0800
DEVTAB_LEN = 0x0800                     # 2 KB
DEVTAB_MAGIC = int.from_bytes(b"SAHARAPT", "little")

# PLATFORM-SPEC 1: "everything at 0x0F00_0000 and above in this map is
# device space in the sense of ISA-SPEC section 9.2". Classification is
# by address, independent of which devices the table instantiates (the
# atomics-trap-DEVERR rule needs no device internals; SPEC-ISSUES 24).
DEV_SPACE_BASE = 0x0F000000


class ImageError(Exception):
    pass


def load_image(phys, data):
    """Loads segments into physical RAM. Returns entry (informational)."""
    if len(data) < HEADER_LEN:
        raise ImageError("image shorter than header")
    if data[0:8] != MAGIC:
        raise ImageError("bad image magic")
    entry = int.from_bytes(data[8:24], "little")
    nsegs = int.from_bytes(data[24:32], "little")
    if entry % E.INSN_BYTES:
        raise ImageError("entry not 8-aligned")
    segs = []
    for i in range(nsegs):
        off = HEADER_LEN + i * SEG_LEN
        d = data[off:off + SEG_LEN]
        if len(d) < SEG_LEN:
            raise ImageError("truncated segment descriptor")
        load_pa = int.from_bytes(d[0:16], "little")
        file_off = int.from_bytes(d[16:24], "little")
        file_len = int.from_bytes(d[24:32], "little")
        mem_len = int.from_bytes(d[32:40], "little")
        flags = int.from_bytes(d[40:48], "little")
        if flags != 0:
            raise ImageError(f"segment {i}: nonzero flags")
        if mem_len < file_len:
            raise ImageError(f"segment {i}: mem_len < file_len")
        if file_off + file_len > len(data):
            raise ImageError(f"segment {i}: file range out of bounds")
        segs.append((load_pa, file_off, file_len, mem_len))
    # overlap checks: segments against each other and the device table
    ranges = [(s[0], s[0] + s[3]) for s in segs if s[3] > 0]
    ranges.append((DEVTAB_PA, DEVTAB_PA + DEVTAB_LEN))
    for i, (a0, a1) in enumerate(ranges):
        for b0, b1 in ranges[i + 1:]:
            if a0 < b1 and b0 < a1:
                raise ImageError("segments overlap (or hit the device table)")
    for load_pa, file_off, file_len, mem_len in segs:
        phys.write_raw(load_pa, data[file_off:file_off + file_len])
        if mem_len > file_len:
            phys.write_raw(load_pa + file_len, bytes(mem_len - file_len))
    return entry


def build_image(segments, entry=E.RESET_PC):
    """segments: [(load_pa, bytes)] or [(load_pa, bytes, mem_len)].
    Test/bootstrap helper until asm/ lands on the toolchain branch."""
    body = b""
    descs = []
    file_off = HEADER_LEN + SEG_LEN * len(segments)
    for seg in segments:
        load_pa, data = seg[0], seg[1]
        mem_len = seg[2] if len(seg) > 2 else len(data)
        descs.append(
            (load_pa & (1 << 128) - 1).to_bytes(16, "little")
            + struct.pack("<QQQQ", file_off, len(data), mem_len, 0))
        body += data
        file_off += len(data)
    return (MAGIC + (entry & (1 << 128) - 1).to_bytes(16, "little")
            + struct.pack("<Q", len(segments)) + b"".join(descs) + body)


def write_device_table(phys, ram_len, devices=()):
    """PLATFORM-SPEC section 2: written by the emulator before reset.
    v1.0 headless: one RAM region, no devices yet (device phase gated)."""
    tab = struct.pack("<QQQQQ", DEVTAB_MAGIC, 1, 1, 1, len(devices))
    tab += (0).to_bytes(16, "little") + ram_len.to_bytes(16, "little")
    for dev in devices:
        typ, base, size, params = dev
        tab += struct.pack("<Q", typ) + base.to_bytes(16, "little")
        tab += struct.pack("<Q", size)
        tab += struct.pack("<QQQQ", *params)
    if len(tab) > DEVTAB_LEN:
        raise ImageError("device table exceeds 2 KB")
    phys.write_raw(DEVTAB_PA, tab)
