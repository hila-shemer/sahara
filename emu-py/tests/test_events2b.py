"""EVENT/replay device model — CURRENT_TASK.md (phase 2b) deliverable 7.

Device-level unit coverage for `Device.event` on all four devices plus
`--replay` META validation (trace.md 5.1). The c7_kbd/c7_kbd_ovf/
c7_resize conformance tests already pin the machine-level behaviour
through instruction sequences; these tests pin the device/CLI seams
directly, including boundaries the conformance suite doesn't reach
(e.g. the 65th NIC RX arrival, a corrupt META key).
"""

import hashlib
import struct

import pytest

import devices
import encoding as E
import image
import mem
import trc
from helpers import halt, li128, run_cli, wbytes

MASK64 = (1 << 64) - 1


def _kbd_payload(word, flags=0):
    return word.to_bytes(8, "little") + bytes([flags])


# --------------------------------------------------------------- input

def test_input_queue_fills_to_256_without_drop():
    kbd = devices.Input(devices.KBD_BASE, devices.KBD_SIZE)
    for i in range(256):
        rec = kbd.event(_kbd_payload(i))
        assert rec[8] == 0
    assert kbd.load(kbd.OFF_STATUS, 8) == 256
    assert kbd.pending() is True


def test_input_257th_event_drops_newest():
    kbd = devices.Input(devices.KBD_BASE, devices.KBD_SIZE)
    for i in range(256):
        kbd.event(_kbd_payload(i))
    rec = kbd.event(_kbd_payload(999))
    assert rec[0:8] == (999).to_bytes(8, "little")   # word recorded verbatim
    assert rec[8] == 1                                 # own drop decision
    assert kbd.load(kbd.OFF_STATUS, 8) == 256           # depth unchanged


def test_input_flags_byte_flips_exactly_on_257th():
    kbd = devices.Input(devices.KBD_BASE, devices.KBD_SIZE)
    flags = [kbd.event(_kbd_payload(i))[8] for i in range(257)]
    assert flags[:256] == [0] * 256
    assert flags[256] == 1


def test_input_dropped_event_never_poppable_or_counted():
    kbd = devices.Input(devices.KBD_BASE, devices.KBD_SIZE)
    for i in range(256):
        kbd.event(_kbd_payload(i))
    kbd.event(_kbd_payload(0xDEAD))                     # dropped
    words = [kbd.load(kbd.OFF_DATA, 8) for _ in range(256)]
    assert words == list(range(256))                     # dropped press absent
    assert kbd.load(kbd.OFF_DATA, 8) == MASK64            # empty sentinel
    assert kbd.load(kbd.OFF_STATUS, 8) == 0
    assert kbd.pending() is False


def test_input_fifo_pop_order_and_status_depth_tracking():
    kbd = devices.Input(devices.KBD_BASE, devices.KBD_SIZE)
    for w in (0x10, 0x20, 0x30):
        kbd.event(_kbd_payload(w))
    assert kbd.load(kbd.OFF_STATUS, 8) == 3
    assert kbd.load(kbd.OFF_DATA, 8) == 0x10
    assert kbd.load(kbd.OFF_STATUS, 8) == 2
    assert kbd.load(kbd.OFF_DATA, 8) == 0x20
    assert kbd.load(kbd.OFF_DATA, 8) == 0x30
    assert kbd.load(kbd.OFF_STATUS, 8) == 0


def test_input_mouse_word_survives_verbatim_out_of_range_coords():
    # x=0xFFFF, y=0xFFFF, buttons=0xFF packed per trace.md 4 — nonsense
    # coordinates for any real geometry. event() must not decode, clamp
    # or validate them (INPUT-17): store and return the word verbatim.
    mouse = devices.Input(devices.MOUSE_BASE, devices.MOUSE_SIZE)
    word = 0xFF_FFFF_FFFF
    rec = mouse.event(_kbd_payload(word))
    assert rec[0:8] == word.to_bytes(8, "little")
    assert mouse.load(mouse.OFF_DATA, 8) == word


def test_input_event_bad_payload_length_rejected():
    kbd = devices.Input(devices.KBD_BASE, devices.KBD_SIZE)
    with pytest.raises(ValueError):
        kbd.event(b"short")
    with pytest.raises(ValueError):
        kbd.event(_kbd_payload(1) + b"\x00")


# ------------------------------------------------------------- display

def _resize_payload(width, height, stride, fmt=1):
    return struct.pack("<QQQQ", width, height, stride, fmt)


def test_display_resize_sets_geometry_atomically_and_irq():
    d = devices.Display()
    payload = _resize_payload(800, 600, 3200)
    rec = d.event(payload)
    assert rec == payload
    assert (d.width, d.height, d.stride) == (800, 600, 3200)
    assert d.load(d.OFF_IRQ_STATUS, 8) == 1
    assert d.load(d.OFF_FORMAT, 8) == 1                # untouched, still 1


def test_display_resize_leaves_pixel_buffer_and_format_untouched():
    d = devices.Display()
    pixbuf = devices.Buffer(devices.PIXBUF_BASE, devices.PIXBUF_SIZE)
    pixbuf.store(0, 8, 0x1122334455667788)
    d.event(_resize_payload(1024, 768, 4096))
    assert pixbuf.load(0, 8) == 0x1122334455667788      # separate window
    assert d.load(d.OFF_FORMAT, 8) == 1


def test_display_irq_status_sticky_and_ack_clears():
    d = devices.Display()
    d.event(_resize_payload(800, 600, 3200))
    assert d.load(d.OFF_IRQ_STATUS, 8) == 1
    d.event(_resize_payload(640, 480, 2560))             # idempotent set
    assert d.load(d.OFF_IRQ_STATUS, 8) == 1
    d.store(d.OFF_IRQ_ACK, 8, 1)
    assert d.load(d.OFF_IRQ_STATUS, 8) == 0


def test_display_ack_then_event_and_event_then_ack_orders():
    # ack-then-event: acking a stale IRQ first, then a resize raises it fresh.
    d = devices.Display()
    d.irq_status = 1
    d.store(d.OFF_IRQ_ACK, 8, 1)
    assert d.load(d.OFF_IRQ_STATUS, 8) == 0
    d.event(_resize_payload(800, 600, 3200))
    assert d.load(d.OFF_IRQ_STATUS, 8) == 1

    # event-then-ack: a pending resize IRQ survives until explicitly acked.
    d2 = devices.Display()
    d2.event(_resize_payload(640, 480, 2560))
    assert d2.load(d2.OFF_IRQ_STATUS, 8) == 1
    d2.store(d2.OFF_IRQ_ACK, 8, 1)
    assert d2.load(d2.OFF_IRQ_STATUS, 8) == 0


def test_display_resize_bad_format_rejected():
    d = devices.Display()
    with pytest.raises(ValueError):
        d.event(_resize_payload(800, 600, 3200, fmt=2))


def test_display_resize_bad_payload_length_rejected():
    d = devices.Display()
    with pytest.raises(ValueError):
        d.event(b"\x00" * 31)


# ----------------------------------------------------------------- nic

def _nic():
    mac = devices.pack_mac(devices.REFERENCE_MAC_OCTETS)
    rx = devices.Buffer(devices.NIC_BASE + devices.NIC_RX_OFFSET, 0x10000)
    return devices.Nic(devices.NIC_BASE, devices.NIC_REG_SIZE, mac, rx), rx


def _frame(tag, length=60):
    return bytes([tag & 0xFF]) * length


def test_nic_empty_arrival_exposes_immediately():
    nic, rx = _nic()
    frame = _frame(0xAA)
    rec = nic.event(frame)
    assert rec == frame
    assert nic.load(nic.OFF_RX_LEN, 8) == len(frame)
    assert bytes(rx.data[0:len(frame)]) == frame
    assert nic.pending() is True


def test_nic_second_arrival_queues_with_no_guest_visible_effect():
    nic, rx = _nic()
    first, second = _frame(0xAA), _frame(0xBB)
    nic.event(first)
    nic.event(second)
    assert nic.load(nic.OFF_RX_LEN, 8) == len(first)     # unchanged
    assert bytes(rx.data[0:len(first)]) == first


def test_nic_rx_pop_exposes_queue_head_in_admission_order():
    nic, rx = _nic()
    frames = [_frame(tag) for tag in (0xAA, 0xBB, 0xCC)]
    for f in frames:
        nic.event(f)
    for f in frames:
        assert nic.load(nic.OFF_RX_LEN, 8) == len(f)
        assert bytes(rx.data[0:len(f)]) == f
        nic.store(nic.OFF_RX_POP, 8, 0)
    assert nic.load(nic.OFF_RX_LEN, 8) == 0
    assert nic.pending() is False


def test_nic_rx_pop_on_empty_after_drain_faults():
    nic, rx = _nic()
    nic.event(_frame(0xAA))
    nic.store(nic.OFF_RX_POP, 8, 0)                       # drains to EMPTY
    with pytest.raises(mem.AccessError):
        nic.store(nic.OFF_RX_POP, 8, 0)


def test_nic_rx_capacity_cap_rejects_65th_arrival():
    nic, rx = _nic()
    for i in range(64):                                   # 1 exposed + 63 queued
        nic.event(_frame(i))
    with pytest.raises(ValueError):
        nic.event(_frame(0xFF))
    assert nic.load(nic.OFF_RX_LEN, 8) == len(_frame(0))  # unaffected by the reject


def test_nic_event_bad_frame_length_rejected():
    nic, rx = _nic()
    with pytest.raises(ValueError):
        nic.event(_frame(0xAA, length=59))
    with pytest.raises(ValueError):
        nic.event(_frame(0xAA, length=1515))
    assert nic.load(nic.OFF_RX_LEN, 8) == 0                # no partial effect


# --------------------------------------------------------- replay META

def _write_img(tmp_path, name="ev.img"):
    prog = li128(0, 0x600D) + [halt()]
    p = tmp_path / name
    p.write_bytes(image.build_image([(E.RESET_PC, wbytes(prog))],
                                    E.RESET_PC))
    return p


def _write_replay_trace(path, meta_kv):
    with open(path, "wb") as f:
        w = trc.TraceWriter(f, level=0)
        w.meta(meta_kv)
        w.close()


def _good_meta(img_path, sha256, **overrides):
    kv = {
        "trace": 1,
        "encoding": E.SPEC_VERSION,
        "level": 0,
        "mode": "live",
        "image": str(img_path),
        "image_sha256": sha256,
        "platform": "1.0-draft",
    }
    kv.update(overrides)
    return list(kv.items())


def test_replay_rejects_bad_image_sha256(tmp_path):
    img = _write_img(tmp_path)
    feed = tmp_path / "bad.trc"
    _write_replay_trace(feed, _good_meta(img, "0" * 64))
    r = run_cli(img, "--replay", str(feed))
    assert r.returncode != 0
    assert b"Traceback" not in r.stderr
    assert b"image_sha256" in r.stderr


def test_replay_rejects_bad_encoding(tmp_path):
    img = _write_img(tmp_path)
    sha = hashlib.sha256(img.read_bytes()).hexdigest()
    feed = tmp_path / "bad.trc"
    _write_replay_trace(feed, _good_meta(img, sha, encoding="not-a-version"))
    r = run_cli(img, "--replay", str(feed))
    assert r.returncode != 0
    assert b"Traceback" not in r.stderr
    assert b"encoding" in r.stderr


def test_replay_rejects_trace_not_one(tmp_path):
    img = _write_img(tmp_path)
    sha = hashlib.sha256(img.read_bytes()).hexdigest()
    feed = tmp_path / "bad.trc"
    _write_replay_trace(feed, _good_meta(img, sha, trace=0))
    r = run_cli(img, "--replay", str(feed))
    assert r.returncode != 0
    assert b"Traceback" not in r.stderr


def test_replay_accepts_feed_whose_level_and_mode_differ(tmp_path):
    img = _write_img(tmp_path)
    sha = hashlib.sha256(img.read_bytes()).hexdigest()
    feed = tmp_path / "ok.trc"
    _write_replay_trace(feed, _good_meta(
        img, sha, level=2, mode="live", image="/some/other/path.img"))
    r = run_cli(img, "--replay", str(feed))
    assert r.returncode == 0, r.stderr
