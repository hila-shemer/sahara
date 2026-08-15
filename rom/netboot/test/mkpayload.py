#!/usr/bin/env python3
"""Build the netboot CI fixtures (run-gui-tests netboot legs).

Repacks the assembled payload.s core into the 3-segment SAHIMG01 the
payload's own checks expect (see payload.s for the layout and why it
proves the copy-down), then derives the malformed variants the ROM's
error legs assert on:

  payload.img       the good image (multi-block, short final block)
  bad-magic.img     header magic corrupted            -> HALT 0xBAD6
  truncated.img     seg-1 file_len past the download  -> HALT 0xBAD7
  low-seg.img       seg-1 aimed at the device table   -> HALT 0xBAD7
  too-big.img       > 64 KB, for the small --ram leg  -> HALT 0xBAD8

Also asserts the good image's segments cover the ROM's entire
footprint (read from --rom netboot.img) - without that, the
self-overwrite proof would ship latent.

usage: mkpayload.py --core CORE.img --rom NETBOOT.img --outdir DIR
"""

import argparse
import os
import struct

PAT_LO, PAT_HI = 0x2000, 0x4000       # keep in sync with payload.s
ZP_BASE, ZP_FILE, ZP_END = 0x4000, 16, 0x5000
PAT, ZPAT = 0xA5, 0xC3
CODE_LEN = 0x1000

HDR = 32                              # magic u64, entry u128, nsegs u64
DESC = 48


def read_img(path):
    d = open(path, "rb").read()
    assert d[:8] == b"SAHIMG01", path
    entry = int.from_bytes(d[8:24], "little")
    nsegs = int.from_bytes(d[24:32], "little")
    segs = []
    for i in range(nsegs):
        o = HDR + i * DESC
        pa = int.from_bytes(d[o:o + 16], "little")
        fo, fl, ml, fg = struct.unpack_from("<4Q", d, o + 16)
        segs.append((pa, fo, fl, ml, fg))
    return d, entry, segs


def pack(entry, segs, blobs):
    """segs: (pa, file_len, mem_len) per blob; file bytes packed
    densely after the descriptor table."""
    out = bytearray()
    out += b"SAHIMG01" + entry.to_bytes(16, "little")
    out += struct.pack("<Q", len(segs))
    fo = HDR + DESC * len(segs)
    for (pa, fl, ml), blob in zip(segs, blobs):
        assert len(blob) == fl
        out += pa.to_bytes(16, "little") + struct.pack("<4Q", fo, fl, ml, 0)
        fo += fl
    for blob in blobs:
        out += blob
    return bytes(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", required=True)
    ap.add_argument("--rom", required=True)
    ap.add_argument("--outdir", required=True)
    a = ap.parse_args()

    core, entry, csegs = read_img(a.core)
    assert entry == 0x1000 and len(csegs) == 1, "payload.s shape changed"
    pa, fo, fl, ml, _ = csegs[0]
    assert pa == 0x1000 and fl <= CODE_LEN, "code segment outgrew 0x1000"
    code = core[fo:fo + fl] + bytes([PAT]) * (CODE_LEN - fl)

    good = pack(0x1000,
                [(0x1000, CODE_LEN, CODE_LEN),
                 (PAT_LO, PAT_HI + 0x1000 - PAT_LO, PAT_HI + 0x1000 - PAT_LO),
                 (ZP_BASE, ZP_FILE, ZP_END - ZP_BASE)],
                [code,
                 bytes([PAT]) * (PAT_HI + 0x1000 - PAT_LO),
                 bytes([ZPAT]) * ZP_FILE])

    # The union [0x1000, ZP_END) must cover every ROM byte, or the
    # copy-down self-overwrite proof is vacuous.
    _, _, rsegs = read_img(a.rom)
    rom_end = max(pa + ml for pa, _, _, ml, _ in rsegs)
    assert rom_end <= ZP_END, (
        f"ROM footprint {rom_end:#x} outgrew the payload's coverage "
        f"[0x1000, {ZP_END:#x}) - widen the payload layout")

    def emit(name, data):
        with open(os.path.join(a.outdir, name), "wb") as f:
            f.write(data)

    emit("payload.img", good)

    bad = bytearray(good)
    bad[0] ^= 0xFF
    emit("bad-magic.img", bad)

    trunc = bytearray(good)
    # seg 1 descriptor: file_len at HDR + DESC + 24
    struct.pack_into("<Q", trunc, HDR + DESC + 24, 1 << 20)
    emit("truncated.img", trunc)

    low = bytearray(good)
    # seg 1 load_pa -> 0x800: the device table, below the reset PC
    low[HDR + DESC:HDR + DESC + 16] = (0x800).to_bytes(16, "little")
    emit("low-seg.img", low)

    # Anything > 64 KB overflows the --ram 0x30000 staging window
    # (stage_cap = 0x10000) while downloading, before any parsing.
    emit("too-big.img", good + bytes(0x11000 - (len(good) & 0x3FF)))

    nblocks = (len(good) + 1023) // 1024 + 1
    print(f"payload.img: {len(good)} bytes, {nblocks} DATA blocks "
          f"(final short), ROM footprint {rom_end:#x} covered")


if __name__ == "__main__":
    main()
