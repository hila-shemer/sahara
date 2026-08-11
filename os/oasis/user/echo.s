# echo.s - the demo user program (SABI v0.1 A.3/A.7: first byte at
# UBASE is the entry, no header; enters with all GPRs zero except sp).
# Writes a banner, burns a few hundred k cycles so timer preemption
# provably lands with epc in the user window (the u_echo test asserts
# it), then loops read -> write one byte at a time; a line whose first
# char is 'q' exits(0) after echoing its newline.
#
# Re-runnable per A.7: the image loads once, so ALL state is
# re-initialized from code - registers only, plus u_chbuf which is
# written before every read. Line state lives in callee-saved r16-r18:
# the kernel preserves those across syscalls (SABI 3.6) and this
# program leans on that on purpose.

        .org UBASE
u_entry:
        li      r0, 0
        la      r1, u_banner
        add     r2, zero, u_banner_end - u_banner  # li can't take labels (asm.md 4.4)
        li      r6, 0
        li      r7, SYS_WRITE
        syscall

        li      r8, 90000              # ~3 cycles/iter: >2 timer ticks
u_burn:                                # land while S=0
        sub     r8, r8, 1
        cmpeq   p1, r8, zero
        (!p1) b u_burn

        li      r16, 0                 # position in the current line
        li      r17, 0                 # the line's first char
u_loop:
        li      r0, 0
        la      r1, u_chbuf
        li      r2, 1
        li      r6, 0
        li      r7, SYS_READ
        syscall
        la      r9, u_chbuf
        ldz.8   r9, [r9]
        cmpeq   p1, r16, zero
        (p1) mov r17, r9
        add     r16, r16, 1
        li      r18, 0                 # 0 continue, 1 line end, 2 quit
        cmpeq   p1, r9, 0x0A
        (!p1) b u_echo
        li      r18, 1
        cmpeq   p1, r17, 0x71          # line started with 'q'
        (p1) li r18, 2
u_echo:
        li      r0, 0
        la      r1, u_chbuf
        li      r2, 1
        li      r6, 0
        li      r7, SYS_WRITE
        syscall
        cmpeq   p1, r18, zero
        (p1) b  u_loop
        li      r16, 0                 # line consumed: reset
        li      r17, 0
        cmpeq   p1, r18, 2
        (!p1) b u_loop
        li      r0, 0
        li      r6, 0
        li      r7, SYS_EXIT
        syscall

u_banner:
        .ascii "user echo: q<enter> quits\n"
u_banner_end:
u_chbuf:
        .space 16
        .align 16
__uend:                                # image extent for the kernel's
                                       # user-window map (v0.1 A.2)
