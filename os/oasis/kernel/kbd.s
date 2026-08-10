# kbd.s - EXTINT-side input draining. Called from h_irq only, between
# the canonical save/restore blocks: r8-r15 + r29 + k0 are the entire
# register budget here (r0-r7 are the interrupted code's, untouched).
#
# Keyboard: pop until the all-ones sentinel (input.md 5 canonical
# loop), translate PRESS events through the generated tables (shift
# tracked from the modifier press/release stream, input.md 2.3), push
# ASCII into the 256-byte ring. Ring full -> drop newest, silently
# (mirrors the device's own overflow discipline).
# Mouse: drain and DISCARD - EXTINT is level-triggered, an undrained
# queue holds the line asserted forever.
# Display: ack-first then re-read geometry (display.md 6.4 race-free
# pattern), best-effort re-layout.

kbd_drain:
        ldz.64  r8, [r27 + G_KBD]
        la      r9, keymap_plain
        la      r10, keymap_shift
kd_loop:
        lds.64  r11, [r8 + INPUT_DATA] # pop (sign-extends the sentinel)
        cmpeq   p1, r11, -1
        (p1) b  kd_done
        shr     r12, r11, 32           # bit 32 -> press flag (63:33 are 0)
        or      r13, zero, r11 zxt 32  # usage ID
        and     r13, r13, 255          # table index bound (in-set IDs fit)
        cmpeq   p2, r13, HID_LSHIFT
        (p2) b  kd_lshift
        cmpeq   p2, r13, HID_RSHIFT
        (p2) b  kd_rshift
        cmpeq   p2, r12, 1             # press events only
        (!p2) b kd_loop
        ldz.64  r14, [r27 + G_SHIFT]
        cmpeq   p2, r14, zero
        mov     r15, r10               # shifted table...
        (p2) mov r15, r9               # ...unless no shift held
        add     r15, r15, r13
        ldz.8   r14, [r15]             # ASCII (0 = no translation)
        cmpeq   p2, r14, zero
        (p2) b  kd_loop
        # push into the ring unless full (head/tail are monotonic u64;
        # the handler owns head, sys_read owns tail - no lock needed on
        # one CPU with program-ordered memory)
        ldz.64  r15, [r27 + G_RHEAD]
        ldz.64  r12, [r27 + G_RTAIL]
        sub     r12, r15, r12
        cmpltu  p2, r12, RING_SIZE
        (!p2) b kd_loop                # full: drop newest
        and     r12, r15, RING_SIZE - 1
        la      r13, kbd_ring
        add     r13, r13, r12
        st.8    [r13], r14
        add     r15, r15, 1
        st.64   [r27 + G_RHEAD], r15
        b       kd_loop
kd_lshift:
        ldz.64  r14, [r27 + G_SHIFT]
        cmpeq   p2, r12, 1
        (p2) or r14, r14, 1
        (!p2) and r14, r14, -2
        st.64   [r27 + G_SHIFT], r14
        b       kd_loop
kd_rshift:
        ldz.64  r14, [r27 + G_SHIFT]
        cmpeq   p2, r12, 1
        (p2) or r14, r14, 2
        (!p2) and r14, r14, -3
        st.64   [r27 + G_SHIFT], r14
        b       kd_loop
kd_done:
        ret

mouse_drain:
        ldz.64  r8, [r27 + G_MOUSE]
        cmpeq   p1, r8, zero           # tolerate a mouse-less table
        (p1) b  md_done
md_loop:
        lds.64  r9, [r8 + INPUT_DATA]
        cmpeq   p1, r9, -1
        (!p1) b md_loop                # discard event, keep draining
md_done:
        ret

disp_check:
        ldz.64  r8, [r27 + G_DISP]
        ldz.64  r9, [r8 + DISP_IRQSTAT]
        and     r9, r9, 1
        cmpeq   p1, r9, zero
        (p1) b  dc_out
        li      r9, 1
        st.64   [r8 + DISP_IRQACK], r9 # ack FIRST (display.md 6.4)
        ldz.64  r9, [r8 + DISP_WIDTH]  # then read: never miss the final mode
        st.64   [r27 + G_WIDTH], r9
        shr     r10, r9, 3
        st.64   [r27 + G_COLS], r10
        ldz.64  r9, [r8 + DISP_HEIGHT]
        st.64   [r27 + G_HEIGHT], r9
        shr     r11, r9, 4
        st.64   [r27 + G_ROWS], r11
        ldz.64  r9, [r8 + DISP_STRIDE]
        st.64   [r27 + G_STRIDE], r9
        # best-effort re-layout: clamp the cursor into the new grid;
        # existing pixels are left as-is (stride change garbles old
        # rows - cosmetic, next full lines draw clean)
        ldz.64  r9, [r27 + G_CURCOL]
        cmpltu  p1, r9, r10
        (p1) b  dc_row
        sub     r9, r10, 1
        st.64   [r27 + G_CURCOL], r9
dc_row:
        ldz.64  r9, [r27 + G_CURROW]
        cmpltu  p1, r9, r11
        (p1) b  dc_out
        sub     r9, r11, 1
        st.64   [r27 + G_CURROW], r9
dc_out:
        ret
