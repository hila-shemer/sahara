# basic ALU + predication + memory, MMU off
.org 0x1000
start:
    ldi r1, 5
    ldi r2, 7
    add r3, r1, r2            # 12
    madd r4, r1, r2, r3       # 5*7+12 = 47
    sub r5, r4, 40            # 7
    shl r6, r1, 3             # 40
    add r7, r1, r2<<4         # 5 + 7*16 = 117
    li  r8, 0x123456789abcdef0123
    cmplt p1, r1, r2          # 5<7 -> true
    (p1) add r9, zero, 111
    (!p1) add r9, zero, 222   # squashed
    cmpeq p2, r1, r2          # false
    (p2) add r10, zero, 333   # squashed
    ldi r11, 0x2000
    st64 [r11 + 8], r4
    ld64u r12, [r11 + 8]      # 47
    ld32s r13, [r11 + 8]      # 47
    # unsigned 128 div
    li r14, 0x10000000000000000   # 2^64
    udiv r15, r14, r1         # 2^64/5
    # result check: r0 = 0 if all good
    ldi r0, 0
    cmpeq p3, r3, 12
    (!p3) ldi r0, 1
    cmpeq p3, r4, 47
    (!p3) ldi r0, 2
    cmpeq p3, r5, 7
    (!p3) ldi r0, 3
    cmpeq p3, r7, 117
    (!p3) ldi r0, 4
    cmpeq p3, r9, 111
    (!p3) ldi r0, 5
    cmpeq p3, r10, zero
    (!p3) ldi r0, 6
    cmpeq p3, r12, 47
    (!p3) ldi r0, 7
    # loop test: sum 1..10 in r20
    ldi r20, 0
    ldi r21, 1
loop:
    add r20, r20, r21
    add r21, r21, 1
    cmple p4, r21, 10
    (p4) b loop
    cmpeq p3, r20, 55
    (!p3) ldi r0, 8
    # call/return
    jal ra, func
    cmpeq p3, r22, 99
    (!p3) ldi r0, 9
    halt
func:
    ldi r22, 99
    jalr zero, ra, 0
.entry start
