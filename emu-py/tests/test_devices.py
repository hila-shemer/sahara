"""Headless device register model: display, keyboard/mouse, NIC
(CURRENT_TASK.md deliverable 5). Exercises devices.py directly against
its load/store surface rather than through instruction sequences —
that surface *is* the register model devspec/display.md, input.md and
nic.md define.
"""

import pytest

import devices
import mem

MASK64 = (1 << 64) - 1


def devfault(fn):
    with pytest.raises(mem.AccessError):
        fn()


# ------------------------------------------------------------- display

def test_display_reference_initial_state():
    d = devices.Display()
    assert d.load(d.OFF_WIDTH, 8) == 640
    assert d.load(d.OFF_HEIGHT, 8) == 480
    assert d.load(d.OFF_STRIDE, 8) == 2560
    assert d.load(d.OFF_FORMAT, 8) == 1
    assert d.load(d.OFF_IRQ_STATUS, 8) == 0
    assert d.pending() is False


def test_display_write_only_regs_fault_on_load():
    d = devices.Display()
    devfault(lambda: d.load(d.OFF_PRESENT, 8))
    devfault(lambda: d.load(d.OFF_IRQ_ACK, 8))


def test_display_read_only_regs_fault_on_store():
    d = devices.Display()
    for off in (d.OFF_WIDTH, d.OFF_HEIGHT, d.OFF_STRIDE, d.OFF_FORMAT,
                d.OFF_IRQ_STATUS):
        devfault(lambda off=off: d.store(off, 8, 0))


def test_display_present_accepts_any_value_and_has_no_state_effect():
    d = devices.Display()
    d.store(d.OFF_PRESENT, 8, 0xFFFFFFFFFFFFFFFF)   # must not raise
    assert d.load(d.OFF_WIDTH, 8) == 640             # geometry unaffected


def test_display_irq_ack_clears_status_and_rejects_bad_bits():
    d = devices.Display()
    d.irq_status = 1
    d.store(d.OFF_IRQ_ACK, 8, 0)                     # no-op
    assert d.load(d.OFF_IRQ_STATUS, 8) == 1
    devfault(lambda: d.store(d.OFF_IRQ_ACK, 8, 2))    # bits 63:1 set -> DEVERR
    assert d.load(d.OFF_IRQ_STATUS, 8) == 1           # unchanged by the fault
    d.store(d.OFF_IRQ_ACK, 8, 1)
    assert d.load(d.OFF_IRQ_STATUS, 8) == 0


def test_display_non_64bit_access_faults_everywhere_in_window():
    d = devices.Display()
    for off in (d.OFF_WIDTH, d.OFF_PRESENT, d.OFF_RESERVED_START):
        devfault(lambda off=off: d.load(off, 4))
        devfault(lambda off=off: d.store(off, 4, 0))


def test_display_reserved_extension_reads_zero_ignores_writes_no_fault():
    d = devices.Display()
    assert d.load(d.OFF_RESERVED_START, 8) == 0
    assert d.load(d.size - 8, 8) == 0
    d.store(d.OFF_RESERVED_START, 8, 0xDEADBEEF)      # must not raise
    assert d.load(d.OFF_RESERVED_START, 8) == 0        # still reads 0


# --------------------------------------------------------------- input

def test_input_empty_queue_sentinel_and_status():
    kbd = devices.Input(devices.KBD_BASE, devices.KBD_SIZE)
    assert kbd.load(kbd.OFF_DATA, 8) == MASK64
    assert kbd.load(kbd.OFF_STATUS, 8) == 0
    assert kbd.pending() is False


def test_input_registers_are_read_only():
    kbd = devices.Input(devices.KBD_BASE, devices.KBD_SIZE)
    devfault(lambda: kbd.store(kbd.OFF_DATA, 8, 0))
    devfault(lambda: kbd.store(kbd.OFF_STATUS, 8, 0))


def test_input_unlisted_offset_faults():
    kbd = devices.Input(devices.KBD_BASE, devices.KBD_SIZE)
    devfault(lambda: kbd.load(0x10, 8))


def test_input_non_64bit_access_faults():
    kbd = devices.Input(devices.KBD_BASE, devices.KBD_SIZE)
    devfault(lambda: kbd.load(kbd.OFF_DATA, 4))
    devfault(lambda: kbd.load(kbd.OFF_DATA, 16))       # ld128 is not 64-bit


def test_mouse_same_shape_as_keyboard_but_separate_instance():
    kbd = devices.Input(devices.KBD_BASE, devices.KBD_SIZE)
    mouse = devices.Input(devices.MOUSE_BASE, devices.MOUSE_SIZE)
    kbd.queue.append(0x0104)
    assert kbd.load(kbd.OFF_STATUS, 8) == 1
    assert mouse.load(mouse.OFF_STATUS, 8) == 0        # unaffected


# ----------------------------------------------------------------- nic

def _nic():
    mac = devices.pack_mac(devices.REFERENCE_MAC_OCTETS)
    return devices.Nic(devices.NIC_BASE, devices.NIC_REG_SIZE, mac)


def test_nic_reference_mac_and_status_defaults():
    nic = _nic()
    assert nic.load(nic.OFF_MAC, 8) == 0x0000_5634_1200_5452
    assert nic.load(nic.OFF_TX_STATUS, 8) == 0
    assert nic.load(nic.OFF_RX_LEN, 8) == 0
    assert nic.pending() is False


def test_nic_write_only_and_read_only_directions():
    nic = _nic()
    devfault(lambda: nic.load(nic.OFF_TX_DOORBELL, 8))    # E3
    devfault(lambda: nic.load(nic.OFF_RX_POP, 8))         # E3
    devfault(lambda: nic.store(nic.OFF_TX_STATUS, 8, 0))  # E4
    devfault(lambda: nic.store(nic.OFF_RX_LEN, 8, 0))     # E4
    devfault(lambda: nic.store(nic.OFF_MAC, 8, 0))        # E4


def test_nic_unlisted_register_offset_faults():
    nic = _nic()
    devfault(lambda: nic.load(0x28, 8))                    # E2


def test_nic_non_64bit_register_access_faults():
    nic = _nic()
    devfault(lambda: nic.load(nic.OFF_MAC, 4))             # E1
    devfault(lambda: nic.store(nic.OFF_TX_DOORBELL, 4, 60))  # E1


def test_nic_doorbell_length_bounds():
    nic = _nic()
    devfault(lambda: nic.store(nic.OFF_TX_DOORBELL, 8, 59))    # < 60, E5
    devfault(lambda: nic.store(nic.OFF_TX_DOORBELL, 8, 1515))  # > 1514, E5
    nic.store(nic.OFF_TX_DOORBELL, 8, 60)                       # in range
    nic.store(nic.OFF_TX_DOORBELL, 8, 1514)                     # in range
    assert nic.load(nic.OFF_TX_STATUS, 8) == 0                  # still 0


def test_nic_rx_pop_on_empty_queue_faults():
    nic = _nic()
    devfault(lambda: nic.store(nic.OFF_RX_POP, 8, 0))            # E6


# -------------------------------------------------------------- buffer

def test_buffer_reads_zero_before_first_store():
    buf = devices.Buffer(devices.PIXBUF_BASE, devices.PIXBUF_SIZE)
    assert buf.load(0, 4) == 0
    assert buf.load(0x100, 16) == 0


def test_buffer_memory_like_across_sizes():
    buf = devices.Buffer(devices.PIXBUF_BASE, devices.PIXBUF_SIZE)
    for size in (1, 2, 4, 8, 16):
        off = size * 32
        val = (0xA5 << (8 * (size - 1))) | 0x11 if size > 1 else 0xA5
        buf.store(off, size, val)
        assert buf.load(off, size) == val


def test_buffer_sub_word_merge_is_last_write_wins_per_byte():
    buf = devices.Buffer(devices.PIXBUF_BASE, devices.PIXBUF_SIZE)
    buf.store(0, 8, 0xFFFFFFFFFFFFFFFF)
    buf.store(0, 2, 0x0000)                # overwrite low 2 bytes only
    assert buf.load(0, 8) == 0xFFFFFFFFFFFF0000
    assert buf.load(0, 2) == 0
    assert buf.load(2, 2) == 0xFFFF


def test_nic_tx_rx_buffers_are_plain_buffer_windows():
    tx = devices.Buffer(devices.NIC_BASE + devices.NIC_TX_OFFSET, 0x10000)
    rx = devices.Buffer(devices.NIC_BASE + devices.NIC_RX_OFFSET, 0x10000)
    tx.store(0, 4, 0x11223344)
    assert tx.load(0, 4) == 0x11223344
    assert rx.load(0, 4) == 0                # separate backing store
