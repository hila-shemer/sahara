# crash_jump.s - jumps clean out of the mapped world (0xF0000000 is a
# chunk no table record declares). The fetch at the target faults:
# PF_FETCH with epc = baddr = the jump target. The exit(1) tail must
# be unreachable.
        .org UBASE
        li      r1, 0xF0000000
        jalr    zero, r1, 0
        li      r0, 1
        li      r6, 0
        li      r7, SYS_EXIT
        syscall
        .align 16
__uend:
