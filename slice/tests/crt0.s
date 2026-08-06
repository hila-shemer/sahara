# runtime for compiled programs: stack, vectors, MMU+IE on, call main, halt.
# kbd handler stores the key to mailbox 0x3018 (mb[3] for int* mb = 0x3000).
.org 0x1000
_start:
    la r1, handler
    mtsr vbase, r1
    li sp, 0x1FF00
    mfsr r1, status
    or r1, r1, 5              # MMU_EN | IE
    mtsr status, r1
    invtp
    jal ra, main
    halt
handler:
    mtsr scratch0, r1
    mtsr scratch1, r2
    mfsr r1, cause
    cmpeq p7, r1, 1           # kbd?
    (!p7) b h_bad
    li r2, 0x1F010000
    ld64u r1, [r2]            # MMIO pop key
    ldi r2, 0x3000
    st64 [r2 + 24], r1
    mfsr r2, scratch1
    mfsr r1, scratch0
    iret
h_bad:
    halt
.entry _start
