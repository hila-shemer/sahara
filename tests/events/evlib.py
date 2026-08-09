"""Shared builder for event-feed traces (the --replay input of
event-fed conformance tests).

A feed is a minimal valid .trc: one META record (image_sha256 computed
from the actual .img so the replayer's trace.md 5.1 validation passes)
followed by EVENT records only, cycles non-decreasing. Payload
encodings per devspec/trace.md 4.1 (keyboard), 4.2 (mouse), 4.4
(display resize). Device indices are 0-based positions among the
reference device table's device entries (boot.md V1): 0 display,
1 keyboard, 2 mouse, 3 nic.

META notes: replay validates only image_sha256 / encoding / trace
(trace.md 5.1). `level` has no defined meaning for an events-only feed
(SPEC-ISSUES 31); we write 0. `mode` is `live` — the feed stands in
for a recorded live run's event stream.

Deterministic: byte-identical output for identical image bytes
(selftest regenerates and compares).
"""

import hashlib
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "trace-q"))
sys.path.insert(0, ROOT)
import tracefile as T  # noqa: E402
import encoding as E  # noqa: E402

DEV_DISPLAY, DEV_KBD, DEV_MOUSE, DEV_NIC = 0, 1, 2, 3


def kbd_event(usage, press, dropped=False):
    """trace.md 4.1: event u64 (bits 31:0 usage, bit 32 press) + flags."""
    word = (usage & 0xFFFFFFFF) | ((1 << 32) if press else 0)
    return struct.pack("<Q", word) + bytes([1 if dropped else 0])


def mouse_event(x, y, buttons, dropped=False):
    """trace.md 4.2: event u64 (15:0 x, 31:16 y, 39:32 buttons) + flags.
    x/y/buttons are the POST-clamp state: replay applies the recorded
    word verbatim, it never re-clamps (input.md 3.3 is live-generation
    behavior — a feed cannot exercise it; see the test headers)."""
    word = (x & 0xFFFF) | ((y & 0xFFFF) << 16) | ((buttons & 0xFF) << 32)
    return struct.pack("<Q", word) + bytes([1 if dropped else 0])


def resize_event(width, height, stride, fmt=1):
    """trace.md 4.4: four u64s — width, height, stride, format."""
    return struct.pack("<QQQQ", width, height, stride, fmt)


def write_feed(img_path, out_path, events):
    """events: iterable of (cycle, device_index, payload_bytes),
    cycles non-decreasing (asserted — a feed violating trace.md 3.1
    would be rejected by every conforming reader)."""
    with open(img_path, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    last = None
    with open(out_path, "wb") as f:
        T.write_record(f, T.T_META, T.meta_payload(T.meta_text(
            0, mode="live", image=img_path, image_sha256=sha,
            encoding_version=E.SPEC_VERSION)))
        for cycle, device, payload in events:
            assert last is None or cycle >= last, \
                f"feed cycles decrease: {last} -> {cycle}"
            last = cycle
            T.write_record(f, T.T_EVENT,
                           T.event_payload(cycle, device, payload))


def main_two_args():
    if len(sys.argv) != 3:
        sys.exit(f"usage: {sys.argv[0]} IMAGE OUT_TRC")
    return sys.argv[1], sys.argv[2]
