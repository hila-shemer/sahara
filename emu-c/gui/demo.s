# demo.s — the GUI smoke image (work-order deliverable 5) and the
# scripted-session gate's guest. Paints a gradient band and PRESENTs,
# then idles in WFI; the EXTINT handler drains both input queues,
# plotting a colored block per key press (row 100, x by usage) and a
# white pixel per mouse event at its coordinates, and PRESENTs once
# per delivery. Escape (0x29) press halts with the pass magic — the
# deterministic end the scripted gate keys on. No auto-repeat, no
# timer: a held key paints exactly one block (INPUT-12 visible to the
# naked eye).

        .equ DEV_DISPLAY_BASE, 0x0F000000
        .equ DEV_KBD_BASE, 0x0F010000
        .equ DEV_MOUSE_BASE, 0x0F020000
        .equ PIXBUF, 0x10000000
        .equ ROW100, 0x1003E800        # PIXBUF + 100 * 2560
        .equ STRIDE, 2560
        .equ PASS_MAGIC, 0x600D

        .org 0x1000
start:
        # background: 16 rows whose pixel value is its own index —
        # a blue-green ramp, and proof the blit walks pages honestly
        li r10, PIXBUF
        li r11, 0
bg:
        st.32 [r10], r11
        add r10, r10, 4
        add r11, r11, 1
        cmpltu p1, r11, 10240
        (p1) b bg
        li r9, DEV_DISPLAY_BASE
        st.64 [r9], zero               # PRESENT the pattern
        la.abs r19, h_ext
        mtsr vbase, r19
        li r19, 9                      # STATUS_S | STATUS_IE
        mtsr status, r19
main:
        wfi                            # all further work is input-driven
        b main

        # EXTINT handler: drain keyboard, then mouse, then PRESENT.
h_ext:
        li r17, DEV_KBD_BASE
kd:
        lds.64 k0, [r17]
        cmpeq p3, k0, -1
        (p3) b md
        li r16, 1
        shl r16, r16, 32
        and r16, k0, r16
        cmpeq p3, r16, 0
        (p3) b kd                      # ignore releases
        li r16, 0xFFFFFFFF
        and r15, k0, r16               # usage ID
        cmpeq p3, r15, 0x29
        (p3) b bye                     # Escape ends the session
        # plot an 8-pixel block at (usage * 8, 100), color from usage
        li r14, ROW100
        li r13, 32
        mul r13, r15, r13
        add r14, r14, r13
        li r13, 0x010305
        mul r13, r15, r13              # usage-keyed RGB
        li r12, 8
kblk:
        st.32 [r14], r13
        add r14, r14, 4
        sub r12, r12, 1
        cmpeq p3, r12, 0
        (!p3) b kblk
        b kd
md:
        li r17, DEV_MOUSE_BASE
mloop:
        lds.64 k0, [r17]
        cmpeq p3, k0, -1
        (p3) b present
        li r16, 0xFFFF
        and r15, k0, r16               # x
        shr r14, k0, 16
        and r14, r14, r16              # y
        li r13, STRIDE
        mul r13, r14, r13
        li r12, PIXBUF
        add r13, r13, r12
        shl r15, r15, 2
        add r13, r13, r15
        li r12, 0xFFFFFF
        st.32 [r13], r12               # white dot at (x, y)
        b mloop
present:
        li r17, DEV_DISPLAY_BASE
        st.64 [r17], zero
        iret
bye:
        li r0, PASS_MAGIC
        halt
