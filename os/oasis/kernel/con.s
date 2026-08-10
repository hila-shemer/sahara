# con.s - 80x30 text console over the pixel buffer. XRGB8888, stride
# always read from the register (never assumed 2560), st128 writes 4
# pixels per store via a boot-built nibble table (font bit-quad ->
# 128-bit pixel quad). Scroll is one big forward copy, not a redraw.
#
# ABI functions (SABI v0 frames; called from boot and the syscall
# path, NEVER from interrupt handlers - they clobber r0-r7):
#   con_init            derive geometry, build the nibble table
#   con_putc(r0=ch)     draw one byte: printable / 0x0A NL / 0x08 BS
#   con_puts(r0=asciiz) putc loop + present
#   con_write(r0,r1)    buf,len putc loop + present
#   con_present         PRESENT (one DEVW; frame becomes visible)

con_init:
        ldz.64  r8, [r27 + G_DISP]
        ldz.64  r9, [r8 + DISP_FORMAT]
        cmpeq   p1, r9, 1
        (!p1) b ci_badfmt              # unusable display: loud, no guessing
        ldz.64  r9, [r8 + DISP_WIDTH]
        st.64   [r27 + G_WIDTH], r9
        shr     r10, r9, 3
        st.64   [r27 + G_COLS], r10
        ldz.64  r9, [r8 + DISP_HEIGHT]
        st.64   [r27 + G_HEIGHT], r9
        shr     r10, r9, 4
        st.64   [r27 + G_ROWS], r10
        ldz.64  r9, [r8 + DISP_STRIDE]
        st.64   [r27 + G_STRIDE], r9
        st.64   [r27 + G_CURCOL], zero
        st.64   [r27 + G_CURROW], zero
        # nibble table: entry n = 4 pixels, leftmost = n's bit 3,
        # leftmost pixel at the LOWEST byte address (bits 31:0)
        la      r8, con_nibtab
        li      r9, WHITE
        mov     r10, zero              # n
ci_n:
        mov     r11, zero              # v
        li      r12, 1                 # mask walks 1,2,4,8 = pixels 3..0
ci_m:
        shl     r11, r11, 32
        and     r13, r10, r12
        cmpeq   p1, r13, zero
        (!p1) or r11, r11, r9
        shl     r12, r12, 1
        cmpltu  p1, r12, 16
        (p1) b  ci_m
        st128   [r8], r11
        add     r8, r8, 16
        add     r10, r10, 1
        cmpltu  p1, r10, 16
        (p1) b  ci_n
        ret
ci_badfmt:
        li      r0, HALT_BADFMT
        halt

# draw glyph r0 at the cursor (leaf; no cursor movement)
con_draw:
        sub     r8, r0, 0x20
        shl     r8, r8, 4
        la      r9, font8x16
        add     r8, r8, r9             # glyph rows
        ldz.64  r9, [r27 + G_CURROW]
        shl     r9, r9, 4              # pixel row = currow*16
        ldz.64  r10, [r27 + G_STRIDE]
        mul     r9, r9, r10
        ldz.64  r11, [r27 + G_CURCOL]
        shl     r11, r11, 5            # byte col = curcol*32
        add     r9, r9, r11
        ldz.64  r11, [r27 + G_PIXBUF]
        add     r9, r9, r11            # pixel address of cell top-left
        la      r11, con_nibtab
        li      r12, 16
cd_row:
        ldz.8   r13, [r8]
        shr     r14, r13, 4
        shl     r14, r14, 4
        add     r14, r14, r11
        ld128   r14, [r14]
        st128   [r9], r14              # left 4 pixels
        and     r14, r13, 15
        shl     r14, r14, 4
        add     r14, r14, r11
        ld128   r14, [r14]
        st128   [r9 + 16], r14         # right 4 pixels
        add     r8, r8, 1
        add     r9, r9, r10
        sub     r12, r12, 1
        cmpeq   p1, r12, zero
        (!p1) b cd_row
        ret

con_putc:
        add     sp, sp, -16
        st128   [sp + 0], r29          # ra: top slot (SABI 2.4)
        cmpeq   p1, r0, 0x0A
        (p1) b  cp_nl
        cmpeq   p1, r0, 0x08
        (p1) b  cp_bs
        cmpltu  p1, r0, 0x20           # everything else non-printable:
        (p1) b  cp_out                 # ignored (syscalls.md write)
        cmpltu  p1, r0, 0x7F
        (!p1) b cp_out
        jal     con_draw
        ldz.64  r8, [r27 + G_CURCOL]
        add     r8, r8, 1
        st.64   [r27 + G_CURCOL], r8
        ldz.64  r9, [r27 + G_COLS]
        cmpltu  p1, r8, r9
        (p1) b  cp_out                 # no wrap
cp_nl:
        st.64   [r27 + G_CURCOL], zero
        ldz.64  r8, [r27 + G_CURROW]
        add     r8, r8, 1
        ldz.64  r9, [r27 + G_ROWS]
        cmpltu  p1, r8, r9
        (p1) b  cp_setrow
        jal     con_scroll
        ldz.64  r9, [r27 + G_ROWS]      # reload: scroll clobbers temps
        sub     r8, r9, 1
cp_setrow:
        st.64   [r27 + G_CURROW], r8
        b       cp_out
cp_bs:
        ldz.64  r8, [r27 + G_CURCOL]
        cmpeq   p1, r8, zero
        (p1) b  cp_out                 # nothing to erase
        sub     r8, r8, 1
        st.64   [r27 + G_CURCOL], r8
        li      r0, 0x20
        jal     con_draw               # erase = draw space, cursor stays
cp_out:
        ld128   r29, [sp + 0]
        add     sp, sp, 16
        ret

# scroll one text row: forward copy of (rows*16-16)*stride bytes, then
# clear the last row band. ~75k DEVW at reference geometry - callers
# keep test sessions under one screen except the dedicated scroll test.
con_scroll:
        ldz.64  r8, [r27 + G_PIXBUF]
        ldz.64  r9, [r27 + G_STRIDE]
        ldz.64  r10, [r27 + G_ROWS]
        shl     r10, r10, 4
        sub     r10, r10, 16
        mul     r10, r10, r9           # bytes to move
        shl     r11, r9, 4
        add     r11, r11, r8           # src = pixbuf + 16*stride
        mov     r12, r8                # dst = pixbuf
        add     r13, r8, r10           # dst end
cs_copy4:                              # 64B chunks (stride%64 may be !=0,
        add     r14, r12, 64           # hence the 16B tail below)
        cmpleu  p1, r14, r13
        (!p1) b cs_copy1
        ld128   r14, [r11]
        st128   [r12], r14
        ld128   r14, [r11 + 16]
        st128   [r12 + 16], r14
        ld128   r14, [r11 + 32]
        st128   [r12 + 32], r14
        ld128   r14, [r11 + 48]
        st128   [r12 + 48], r14
        add     r11, r11, 64
        add     r12, r12, 64
        b       cs_copy4
cs_copy1:
        cmpltu  p1, r12, r13
        (!p1) b cs_clear
        ld128   r14, [r11]
        st128   [r12], r14
        add     r11, r11, 16
        add     r12, r12, 16
        b       cs_copy1
cs_clear:                              # last band: 16*stride zero bytes,
        shl     r14, r9, 4             # 16*stride % 64 == 0 (stride%16==0
        add     r13, r12, r14          # per display.md 3.4)
cc_loop:
        cmpltu  p1, r12, r13
        (!p1) b cs_done
        st128   [r12], zero
        st128   [r12 + 16], zero
        st128   [r12 + 32], zero
        st128   [r12 + 48], zero
        add     r12, r12, 64
        b       cc_loop
cs_done:
        ret

con_present:
        ldz.64  r8, [r27 + G_DISP]
        st.64   [r8 + DISP_PRESENT], zero
        ret

con_puts:
        add     sp, sp, -48
        st128   [sp + 32], r29
        st128   [sp + 16], r16
        mov     r16, r0
cps_loop:
        ldz.8   r0, [r16]
        cmpeq   p1, r0, zero
        (p1) b  cps_done
        jal     con_putc
        add     r16, r16, 1
        b       cps_loop
cps_done:
        jal     con_present
        ld128   r16, [sp + 16]
        ld128   r29, [sp + 32]
        add     sp, sp, 48
        ret

con_write:                             # r0 buf, r1 len (len >= 1)
        add     sp, sp, -48
        st128   [sp + 32], r29
        st128   [sp + 16], r17
        st128   [sp + 0], r16
        mov     r16, r0
        add     r17, r0, r1
cw_loop:
        cmpltu  p1, r16, r17
        (!p1) b cw_done
        ldz.8   r0, [r16]
        jal     con_putc
        add     r16, r16, 1
        b       cw_loop
cw_done:
        jal     con_present            # one PRESENT per write (syscalls.md)
        ld128   r16, [sp + 0]
        ld128   r17, [sp + 16]
        ld128   r29, [sp + 32]
        add     sp, sp, 48
        ret
