# hostile_sp.s - SABI 1.4 rule 2's litmus test. Wreck sp with an
# unaligned garbage value FIRST, then make syscalls with valid
# buffers. If any kernel path used our sp for its own pushes, the
# st128 would trap UNALIGNED in kernel context -> h_fatal -> the test
# dies on the halt code. Instead every syscall must complete on the
# process kernel trap stack (v0.1 A.4) and come back here - sp
# restored bit-for-bit as the data it is.
        .org UBASE
        li      sp, UBASE + 0x123457   # garbage: unaligned, mid-gap
        li      r0, 0
        la      r1, h_msg1
        add     r2, zero, h_msg1_end - h_msg1
        li      r6, 0
        li      r7, SYS_WRITE
        syscall
        li      r0, 0                  # the proof: we returned, sp is
        la      r1, h_msg2             # still ours, syscalls keep
        add     r2, zero, h_msg2_end - h_msg2  # working
        li      r6, 0
        li      r7, SYS_WRITE
        syscall
        li      r0, 0
        li      r6, 0
        li      r7, SYS_EXIT
        syscall

h_msg1:
        .ascii "hostile sp set\n"
h_msg1_end:
h_msg2:
        .ascii "syscall returned\n"
h_msg2_end:
        .align 16
__uend:
