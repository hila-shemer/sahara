# t_burst.s — seam-driver guest for the overflow scenario: the driver
# feeds >256 keyboard events at one boundary, the queue keeps 256 and
# drops the rest with the flag recomputed by the model (INPUT-18/19,
# trace.md 5.4). Polling only, IE stays off: visibility is by cycle,
# delivery is not needed. Halts with the pass magic iff exactly 256
# events pop before the sentinel.

        .equ DEV_KBD_BASE, 0x0F010000
        .equ PASS_MAGIC, 0x600D

        .org 0x1000
start:
        li r26, DEV_KBD_BASE
w256:
        ldz.64 r19, [r26 + 8]  # STATUS
        cmpeq p1, r19, 256
        (!p1) b w256
        li r18, 0
drain:
        lds.64 r19, [r26]
        cmpeq p1, r19, -1
        (p1) b done
        add r18, r18, 1
        b drain
done:
        cmpeq p1, r18, 256
        (!p1) b fail
        li r0, PASS_MAGIC
        halt
fail:
        mov r0, r18
        halt
