# t_nicseam.s — seam-driver guest for the NIC feed scenario
# (run-gui-tests): handler-driven, idles in WFI between deliveries.
# The driver feeds NIC frames at fabricated boundaries — one during
# WFI idle, two sharing a cycle with a keyboard press, then a
# 70-frame burst that overflows the 64-frame cap. The guest counts
# every frame it drains and halts with the pass magic at exactly 67
# (1 + 2 + 64): the six overflow discards are invisible here AND in
# the trace (nic.md 4.3 — no EVENT records), which the record→replay
# byte-identity leg then proves.

        .equ DEV_KBD_BASE, 0x0F010000
        .equ DEV_NIC_BASE, 0x0F030000
        .equ PASS_MAGIC, 0x600D
        .equ WANT, 67

        .org 0x1000
start:
        la.abs r19, h_ext
        mtsr vbase, r19
        li r20, 0              # frames drained so far
        li r19, 9              # STATUS_S | STATUS_IE
        mtsr status, r19
loop:
        wfi
        b loop

        # EXTINT handler: drain the keyboard (its words are ignored),
        # then pop every exposed NIC frame. RX_POP exposes the next
        # frame immediately, so the loop re-reads RX_LEN each pass.
h_ext:
        li r17, DEV_KBD_BASE
kd:
        lds.64 k0, [r17]       # DATA pop (sentinel sign-extends to -1)
        cmpeq p3, k0, -1
        (!p3) b kd
        li r17, DEV_NIC_BASE
nx:
        ldz.64 r16, [r17 + 16] # RX_LEN
        cmpeq p3, r16, 0
        (p3) b drained
        add r20, r20, 1
        st.64 [r17 + 24], zero # RX_POP (value ignored)
        b nx
drained:
        cmpeq p3, r20, WANT
        (p3) b halt_now
        iret
halt_now:
        li r0, PASS_MAGIC
        halt
