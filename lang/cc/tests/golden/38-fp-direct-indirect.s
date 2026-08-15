# 38-fp-direct-indirect.c - CC-M1 compiled output (lang/cc/cc.py; spec lang/cc/cc-m1.md)
        .align 16
# cc: func sq frame=16 calls=0
sq:
        add sp, sp, -16
        st.64 [sp + 0], r0
        lds.64 r8, [sp + 0]
        lds.64 r9, [sp + 0]
        mul.64 r8, r8, r9
        mov r0, r8
        b sq.Lret
        li r0, 0
sq.Lret:
        add sp, sp, 16
        ret
# cc: func main frame=144 calls=1
main:
        add sp, sp, -144
        st128 [sp + 128], ra
        la r8, sq
        st128 [sp + 0], r8
        li r8, 9
        st128 [sp + 80], r8
        ld128 r0, [sp + 80]
        jal sq
        mov r8, r0
        st.64 [sp + 16], r8
        ld128 r8, [sp + 0]
        li r9, 9
        st128 [sp + 80], r8
        st128 [sp + 96], r9
        ld128 r0, [sp + 96]
        ld128 r8, [sp + 80]
        jalr ra, r8, 0
        mov r8, r0
        st.64 [sp + 32], r8
        ld128 r8, [sp + 0]
        li r9, 4
        st128 [sp + 80], r8
        st128 [sp + 96], r9
        ld128 r0, [sp + 96]
        ld128 r8, [sp + 80]
        jalr ra, r8, 0
        mov r8, r0
        st.64 [sp + 48], r8
        la r8, sq
        st128 [sp + 64], r8
        lds.64 r8, [sp + 16]
        li r9, 1000000
        mul.64 r8, r8, r9
        lds.64 r9, [sp + 32]
        li r10, 1000
        mul.64 r9, r9, r10
        add.64 r8, r8, r9
        lds.64 r9, [sp + 48]
        add.64 r8, r8, r9
        ld128 r9, [sp + 0]
        ld128 r10, [sp + 64]
        cmpeq p1, r9, r10
        li r9, 1
        (!p1) li r9, 0
        add.64 r8, r8, r9
        mov r0, r8
        b main.Lret
        li r0, 0
main.Lret:
        ld128 ra, [sp + 128]
        add sp, sp, 144
        ret
        .align 16
__etext:
        .align 16
__erodata:
        .align 16
__edata:
        .align 16
_end:
