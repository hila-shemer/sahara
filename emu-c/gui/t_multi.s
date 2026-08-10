# t_multi.s — seam-driver guest for same-cycle multi-event ordering:
# the driver feeds keyboard + mouse + resize at one boundary with IE
# on, so the trace must show EVENT, EVENT, EVENT then the EXTINT TRAP,
# all at one cycle (T-09), and replay must reproduce it byte-for-byte.
# The handler drains both queues and acks the display IRQ (nothing may
# stay pending across IRET or EXTINT redelivers forever), then the
# main loop verifies the resize took.

        .equ DEV_DISPLAY_BASE, 0x0F000000
        .equ DEV_KBD_BASE, 0x0F010000
        .equ DEV_MOUSE_BASE, 0x0F020000
        .equ PASS_MAGIC, 0x600D

        .org 0x1000
start:
        la.abs r19, h_ext
        mtsr vbase, r19
        li r21, 0              # handler-done flag
        li r19, 9              # STATUS_S | STATUS_IE
        mtsr status, r19
spin:
        cmpeq p1, r21, 1
        (!p1) b spin
        li r9, DEV_DISPLAY_BASE
        ldz.64 r19, [r9 + 8]   # WIDTH after the resize event
        cmpeq p1, r19, 800
        (!p1) b fail
        li r0, PASS_MAGIC
        halt
fail:
        mov r0, r19
        halt

h_ext:
        li r17, DEV_KBD_BASE
k1:
        lds.64 k0, [r17]
        cmpeq p3, k0, -1
        (!p3) b k1             # pop until the sentinel
        li r17, DEV_MOUSE_BASE
m1:
        lds.64 k0, [r17]
        cmpeq p3, k0, -1
        (!p3) b m1
        li r17, DEV_DISPLAY_BASE
        li k0, 1
        st.64 [r17 + 48], k0   # IRQ_ACK: clear the resize flag
        li r21, 1
        iret
