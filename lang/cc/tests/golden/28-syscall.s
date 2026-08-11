# 28-syscall.c - CC-M1 compiled output (lang/cc/cc.py; spec lang/cc/cc-m1.md)
        .align 16
# cc: func slen frame=32 calls=0
slen:
        add sp, sp, -32
        st128 [sp + 0], r0
        li r8, 0
        st.64 [sp + 16], r8
slen.L1:
        ld128 r8, [sp + 0]
        lds.64 r9, [sp + 16]
        add r8, r8, r9
        ldz.8 r8, [r8 + 0]
        cmpeq.64 p1, r8, 0
        (p1) b slen.L2
        lds.64 r8, [sp + 16]
        li r9, 1
        add.64 r8, r8, r9
        st.64 [sp + 16], r8
        b slen.L1
slen.L2:
        lds.64 r8, [sp + 16]
        mov r0, r8
        b slen.Lret
        li r0, 0
slen.Lret:
        add sp, sp, 32
        ret
# cc: func main frame=96 calls=1
main:
        add sp, sp, -96
        st128 [sp + 80], ra
        la r8, cc.str.0
        st128 [sp + 0], r8
        li r8, 0
        ld128 r9, [sp + 0]
        ld128 r10, [sp + 0]
        st128 [sp + 32], r8
        st128 [sp + 48], r9
        st128 [sp + 64], r10
        ld128 r0, [sp + 64]
        jal slen
        mov r10, r0
        ld128 r8, [sp + 32]
        ld128 r9, [sp + 48]
        st128 [sp + 32], r8
        st128 [sp + 48], r9
        st128 [sp + 64], r10
        ld128 r0, [sp + 32]
        ld128 r1, [sp + 48]
        ld128 r2, [sp + 64]
        jal sys_write
        mov r8, r0
        st.64 [sp + 16], r8
        li r8, 112
        lds.64 r9, [sp + 16]
        add.64 r8, r8, r9
        li r9, 6
        sub.64 r8, r8, r9
        li r9, 7
        add.64 r8, r8, r9
        st128 [sp + 32], r8
        ld128 r0, [sp + 32]
        jal sys_exit
        mov r8, r0
        li r8, 0
        mov r0, r8
        b main.Lret
        li r0, 0
main.Lret:
        ld128 ra, [sp + 80]
        add sp, sp, 96
        ret
        .align 16
__etext:
cc.str.0:
        .asciiz "hi cc\n"
        .align 16
__erodata:
        .align 16
__edata:
        .align 16
_end:
