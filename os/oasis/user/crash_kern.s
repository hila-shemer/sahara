# crash_kern.s - loads from kernel text at 0x1000. The page is mapped
# S-RWX with U=0, so the mapping exists and the U check is what fires:
# PERM_LOAD, baddr = 0x1000. Proves the U bit actually separates the
# privilege domains. The exit(1) tail must be unreachable.
        .org UBASE
        li      r1, 0x1000
        ldz.64  r2, [r1]
        li      r0, 1
        li      r6, 0
        li      r7, SYS_EXIT
        syscall
        .align 16
__uend:
