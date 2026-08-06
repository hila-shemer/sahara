# MMU + traps + timer irq + kbd irq. Run with:
#   --map 0x0:0x0:0x10000 --map 0x0F010000:0x0F010000:0x10000 \
#   --map128 12345:6789abcdef000000:0x40000:0x10000 --kbd tests/t2.kbd
# mailbox at 0x3000: +0 fault cause, +8 fault baddr, +16 timer flag, +24 kbd key
.org 0x1000
start:
    la r1, handler
    mtsr vbase, r1
    mfsr r1, status
    or r1, r1, 4              # MMU_EN
    mtsr status, r1
    invtp
    # store/load through the huge sparse VA
    li r16, 0x123456789abcdef000000
    ldi r5, 4747
    st64 [r16], r5
    ld64u r6, [r16]
    # deliberate fault: unmapped VA (handler records + skips the load)
    li r4, 0x99990000
    ld64u r3, [r4]
    # timer: fire ~150 cycles from now, then enable interrupts
    mfsr r1, cycle
    add r1, r1, 150
    mtsr timecmp, r1
    mfsr r1, status
    or r1, r1, 1              # IE
    mtsr status, r1
    ldi r10, 0x3000
wait_timer:
    ld64u r11, [r10 + 16]
    cmpeq p1, r11, zero
    (p1) b wait_timer
wait_kbd:
    ld64u r11, [r10 + 24]
    cmpeq p1, r11, zero
    (p1) b wait_kbd
    # checks
    ldi r0, 0
    cmpeq p3, r6, 4747
    (!p3) ldi r0, 1
    ld64u r11, [r10]
    cmpeq p3, r11, 2          # CAUSE_PF_LOAD
    (!p3) ldi r0, 2
    ld64u r11, [r10 + 8]
    cmpeq p3, r11, r4
    (!p3) ldi r0, 3
    ld64u r11, [r10 + 24]
    cmpeq p3, r11, 42         # key from trace
    (!p3) ldi r0, 4
    halt

handler:
    mtsr scratch0, r1
    mtsr scratch1, r2
    mfsr r1, cause
    cmpeq p7, r1, 0
    (p7) b h_timer
    cmpeq p7, r1, 1
    (p7) b h_kbd
    # fault: record cause+baddr, skip the faulting instruction
    ldi r2, 0x3000
    st64 [r2], r1
    mfsr r1, baddr
    st64 [r2 + 8], r1
    mfsr r1, epc
    add r1, r1, 8
    mtsr epc, r1
    b h_out
h_timer:
    ldi r2, 0x3000
    ldi r1, 1
    st64 [r2 + 16], r1
    mtsr timecmp, zero
    b h_out
h_kbd:
    li r2, 0x0F010000
    ld64u r1, [r2]            # MMIO pop
    ldi r2, 0x3000
    st64 [r2 + 24], r1
h_out:
    mfsr r2, scratch1
    mfsr r1, scratch0
    iret
.entry start
