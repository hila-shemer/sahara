# 11-recursion.c - CC-M1 compiled output (lang/cc/cc.py; spec lang/cc/cc-m1.md)
        .align 16
# cc: func fib frame=80 calls=1
fib:
        add sp, sp, -80
        st128 [sp + 64], ra
        st.64 [sp + 0], r0
        lds.64 r8, [sp + 0]
        li r9, 2
        cmplt.64 p1, r8, r9
        (!p1) b fib.L1
        lds.64 r8, [sp + 0]
        mov r0, r8
        b fib.Lret
fib.L1:
        lds.64 r8, [sp + 0]
        li r9, 1
        sub.64 r8, r8, r9
        st128 [sp + 16], r8
        ld128 r0, [sp + 16]
        jal fib
        mov r8, r0
        lds.64 r9, [sp + 0]
        li r10, 2
        sub.64 r9, r9, r10
        st128 [sp + 16], r8
        st128 [sp + 32], r9
        ld128 r0, [sp + 32]
        jal fib
        mov r9, r0
        ld128 r8, [sp + 16]
        add.64 r8, r8, r9
        mov r0, r8
        b fib.Lret
        li r0, 0
fib.Lret:
        ld128 ra, [sp + 64]
        add sp, sp, 80
        ret
# cc: func fact frame=80 calls=1
fact:
        add sp, sp, -80
        st128 [sp + 64], ra
        st.64 [sp + 0], r0
        lds.64 r8, [sp + 0]
        li r9, 0
        cmpeq.64 p1, r8, r9
        (!p1) b fact.L1
        li r8, 1
        mov r0, r8
        b fact.Lret
fact.L1:
        lds.64 r8, [sp + 0]
        lds.64 r9, [sp + 0]
        li r10, 1
        sub.64 r9, r9, r10
        st128 [sp + 16], r8
        st128 [sp + 32], r9
        ld128 r0, [sp + 32]
        jal fact
        mov r9, r0
        ld128 r8, [sp + 16]
        mul.64 r8, r8, r9
        mov r0, r8
        b fact.Lret
        li r0, 0
fact.Lret:
        ld128 ra, [sp + 64]
        add sp, sp, 80
        ret
# cc: func main frame=64 calls=1
main:
        add sp, sp, -64
        st128 [sp + 48], ra
        li r8, 12
        st128 [sp + 0], r8
        ld128 r0, [sp + 0]
        jal fib
        mov r8, r0
        li r9, 1000000
        mul.64 r8, r8, r9
        li r9, 10
        st128 [sp + 0], r8
        st128 [sp + 16], r9
        ld128 r0, [sp + 16]
        jal fact
        mov r9, r0
        ld128 r8, [sp + 0]
        li r10, 1000000
        srem.64 r9, r9, r10
        add.64 r8, r8, r9
        mov r0, r8
        b main.Lret
        li r0, 0
main.Lret:
        ld128 ra, [sp + 48]
        add sp, sp, 64
        ret
        .align 16
__etext:
        .align 16
__erodata:
        .align 16
__edata:
        .align 16
_end:
