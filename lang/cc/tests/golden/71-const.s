# 71-const.c - CC-M1 compiled output (lang/cc/cc.py; spec lang/cc/cc-m1.md)
        .align 16
# cc: func sum frame=64 calls=0
sum:
        add sp, sp, -64
        st128 [sp + 0], r0
        st.64 [sp + 16], r1
        li r8, 0
        st.64 [sp + 32], r8
        li r8, 0
        st.64 [sp + 48], r8
sum.L1:
        lds.64 r8, [sp + 48]
        lds.64 r9, [sp + 16]
        cmplt.64 p1, r8, r9
        (!p1) b sum.L3
        add r8, sp, 32
        lds.64 r9, [r8 + 0]
        ld128 r10, [sp + 0]
        lds.64 r11, [sp + 48]
        shl r11, r11, 3
        add r10, r10, r11
        lds.64 r10, [r10 + 0]
        add.64 r9, r9, r10
        st.64 [r8 + 0], r9
        mov r8, r9
sum.L2:
        add r8, sp, 48
        lds.64 r9, [r8 + 0]
        mov r10, r9
        add.64 r10, r10, 1
        st.64 [r8 + 0], r10
        mov r8, r9
        b sum.L1
sum.L3:
        lds.64 r8, [sp + 32]
        mov r0, r8
        b sum.Lret
        li r0, 0
sum.Lret:
        add sp, sp, 64
        ret
# cc: func main frame=112 calls=1
main:
        add sp, sp, -112
        st128 [sp + 96], ra
        li r8, 25
        st.64 [sp + 0], r8
        la r8, factors
        li r9, 4
        st128 [sp + 48], r8
        st128 [sp + 64], r9
        ld128 r0, [sp + 48]
        ld128 r1, [sp + 64]
        jal sum
        mov r8, r0
        lds.64 r9, [sp + 0]
        add.64 r8, r8, r9
        st.64 [sp + 16], r8
        lds.64 r8, [sp + 16]
        li r9, 100000
        mul.64 r8, r8, r9
        la r9, magic
        lds.32 r9, [r9 + 0]
        or.64 r9, zero, r9 zxt 32
        add.64 r8, r8, r9
        st.64 [sp + 16], r8
        lds.64 r8, [sp + 16]
        li r9, 1000
        mul.64 r8, r8, r9
        la r9, msg
        li r10, 1
        add r9, r9, r10
        ldz.8 r9, [r9 + 0]
        add.64 r8, r8, r9
        st.64 [sp + 16], r8
        la r8, msg
        st128 [sp + 32], r8
        lds.64 r8, [sp + 16]
        li r9, 1000
        mul.64 r8, r8, r9
        ld128 r9, [sp + 32]
        li r10, 4
        add r9, r9, r10
        ldz.8 r9, [r9 + 0]
        add.64 r8, r8, r9
        st.64 [sp + 16], r8
        lds.64 r8, [sp + 16]
        mov r0, r8
        b main.Lret
        li r0, 0
main.Lret:
        ld128 ra, [sp + 96]
        add sp, sp, 112
        ret
        .align 16
__etext:
        .align 8
factors:
        .quad 0x2, 0x3, 0x5, 0x7
        .align 4
magic:
        .word 0xc0de
msg:
        .byte 0x68, 0x65, 0x6c, 0x6c, 0x6f, 0x0
        .align 16
__erodata:
        .align 16
__edata:
        .align 16
_end:
