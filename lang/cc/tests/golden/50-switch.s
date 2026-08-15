# 50-switch.c - CC-M1 compiled output (lang/cc/cc.py; spec lang/cc/cc-m1.md)
        .align 16
# cc: func classify frame=32 calls=0
classify:
        add sp, sp, -32
        st.64 [sp + 0], r0
        li r8, 0
        st.64 [sp + 16], r8
        lds.64 r8, [sp + 0]
        cmpeq.64 p1, r8, 0
        (p1) b classify.L1
        cmpeq.64 p1, r8, 1
        (p1) b classify.L2
        cmpeq.64 p1, r8, 2
        (p1) b classify.L3
        cmpeq.64 p1, r8, 3
        (p1) b classify.L4
        cmpeq.64 p1, r8, 4
        (p1) b classify.L5
        cmpeq.64 p1, r8, 5
        (p1) b classify.L6
        b classify.L7
classify.L1:
        li r8, 100
        st.64 [sp + 16], r8
        b classify.L8
classify.L2:
classify.L3:
        li r8, 200
        st.64 [sp + 16], r8
        b classify.L8
classify.L4:
        li r8, 300
        st.64 [sp + 16], r8
classify.L5:
        lds.64 r8, [sp + 16]
        li r9, 400
        add.64 r8, r8, r9
        st.64 [sp + 16], r8
        b classify.L8
classify.L6:
        lds.64 r8, [sp + 0]
        li r9, 2
        mul.64 r8, r8, r9
        cmpeq.64 p1, r8, 10
        (p1) b classify.L9
        b classify.L10
classify.L9:
        li r8, 510
        st.64 [sp + 16], r8
        b classify.L11
classify.L10:
        li r8, 599
        st.64 [sp + 16], r8
classify.L11:
        b classify.L8
classify.L7:
        li r8, 999
        st.64 [sp + 16], r8
classify.L8:
        lds.64 r8, [sp + 16]
        mov r0, r8
        b classify.Lret
        li r0, 0
classify.Lret:
        add sp, sp, 32
        ret
# cc: func main frame=96 calls=1
main:
        add sp, sp, -96
        st128 [sp + 80], ra
        li r8, 0
        st.64 [sp + 0], r8
        li r8, 0
        st.64 [sp + 16], r8
main.L1:
        lds.64 r8, [sp + 16]
        li r9, 8
        cmplt.64 p1, r8, r9
        (!p1) b main.L2
        lds.64 r8, [sp + 0]
        li r9, 10
        mul.64 r8, r8, r9
        lds.64 r9, [sp + 16]
        st128 [sp + 32], r8
        st128 [sp + 48], r9
        ld128 r0, [sp + 48]
        jal classify
        mov r9, r0
        ld128 r8, [sp + 32]
        li r10, 100
        sdiv.64 r9, r9, r10
        add.64 r8, r8, r9
        st.64 [sp + 0], r8
        lds.64 r8, [sp + 16]
        li r9, 1
        add.64 r8, r8, r9
        st.64 [sp + 16], r8
        b main.L1
main.L2:
        lds.64 r8, [sp + 0]
        mov r0, r8
        b main.Lret
        li r0, 0
main.Lret:
        ld128 ra, [sp + 80]
        add sp, sp, 96
        ret
        .align 16
__etext:
        .align 16
__erodata:
        .align 16
__edata:
        .align 16
_end:
