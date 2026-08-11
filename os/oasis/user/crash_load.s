# crash_load.s - loads from an unmapped mid-window address. Expected
# death: PF_LOAD, baddr = UBASE+8MB (the A.2 gap between image end and
# stack page is invalid on purpose - wild pointers die loudly). The
# exit(1) tail must be unreachable: reaching it fails the test.
        .org UBASE
        li      r1, UBASE + 0x800000
        ldz.64  r2, [r1]
        li      r0, 1
        li      r6, 0
        li      r7, SYS_EXIT
        syscall
        .align 16
__uend:
