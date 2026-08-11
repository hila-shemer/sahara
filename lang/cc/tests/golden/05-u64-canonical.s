# 05-u64-canonical.c - CC-M1 compiled output (lang/cc/cc.py; spec lang/cc/cc-m1.md)
        .align 16
# cc: func main frame=48 calls=0
main:
        add sp, sp, -48
        li r8, 18446744073709551615
        st.64 [sp + 0], r8
        li r8, 0
        st.64 [sp + 16], r8
        lds.64 r8, [sp + 0]
        li r9, 1000
        cmpleu.64 p1, r8, r9
        (p1) b main.L1
        lds.64 r8, [sp + 16]
        li r9, 1
        add.64 r8, r8, r9
        st.64 [sp + 16], r8
main.L1:
        lds.64 r8, [sp + 0]
        li r9, 3
        udiv.64 r8, r8, r9
        li r9, 6148914691236517205
        cmpeq.64 p1, r8, r9
        (!p1) b main.L2
        lds.64 r8, [sp + 16]
        li r9, 2
        add.64 r8, r8, r9
        st.64 [sp + 16], r8
main.L2:
        lds.64 r8, [sp + 0]
        li r9, 10
        urem.64 r8, r8, r9
        li r9, 5
        cmpeq.64 p1, r8, r9
        (!p1) b main.L3
        lds.64 r8, [sp + 16]
        li r9, 4
        add.64 r8, r8, r9
        st.64 [sp + 16], r8
main.L3:
        li r8, 9223372036854775808
        st.64 [sp + 32], r8
        lds.64 r8, [sp + 32]
        li r9, 9223372036854775807
        cmpleu.64 p1, r8, r9
        (p1) b main.L4
        lds.64 r8, [sp + 16]
        li r9, 8
        add.64 r8, r8, r9
        st.64 [sp + 16], r8
main.L4:
        lds.64 r8, [sp + 32]
        li r9, 1
        shr.64 r8, r8, r9
        li r9, 4611686018427387904
        cmpeq.64 p1, r8, r9
        (!p1) b main.L5
        lds.64 r8, [sp + 16]
        li r9, 16
        add.64 r8, r8, r9
        st.64 [sp + 16], r8
main.L5:
        lds.64 r8, [sp + 32]
        li r9, 0
        cmplt.64 p1, r8, r9
        (!p1) b main.L6
        lds.64 r8, [sp + 16]
        li r9, 32
        add.64 r8, r8, r9
        st.64 [sp + 16], r8
main.L6:
        lds.64 r8, [sp + 16]
        mov r0, r8
        b main.Lret
        li r0, 0
main.Lret:
        add sp, sp, 48
        ret
        .align 16
__etext:
        .align 16
__erodata:
        .align 16
__edata:
        .align 16
_end:
