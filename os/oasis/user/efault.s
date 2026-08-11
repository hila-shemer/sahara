# efault.s - passes a kernel address to write() and expects -EFAULT
# back (v0.1 A.5, the errno's first real use). Reports what it saw and
# exits 0 only on the exact expected errno; any other outcome exits 1
# and fails the test's frozen report line.
        .org UBASE
        li      r0, 0
        li      r1, 0x1000             # kernel text: must be rejected
        li      r2, 16
        li      r6, 0
        li      r7, SYS_WRITE
        syscall
        cmpeq   p1, r0, -EFAULT
        (!p1) b e_bad
        li      r0, 0
        la      r1, e_msg
        add     r2, zero, e_msg_end - e_msg
        li      r6, 0
        li      r7, SYS_WRITE
        syscall
        li      r0, 0
        li      r6, 0
        li      r7, SYS_EXIT
        syscall
e_bad:
        li      r0, 1
        li      r6, 0
        li      r7, SYS_EXIT
        syscall

e_msg:
        .ascii "efault observed\n"
e_msg_end:
        .align 16
__uend:
