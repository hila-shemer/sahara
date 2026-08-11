# crash_priv.s - executes HALT in user mode: PRIV trap (ISA 2.4), the
# program dies, the machine does not stop. This is amendment A.6's
# sharpest consequence - a user program cannot halt, stop, or sleep
# the machine. The exit(1) tail must be unreachable.
        .org UBASE
        halt
        li      r0, 1
        li      r6, 0
        li      r7, SYS_EXIT
        syscall
        .align 16
__uend:
