# 84-multi-basic.c, 84b.c - CC-M1 compiled output (lang/cc/cc.py; spec lang/cc/cc-m1.md)
        .align 16
# cc: func shift frame=16 calls=0
shift:
        add sp, sp, -16
        st128 [sp + 0], r0
        ld128 r8, [sp + 0]
        lds.64 r8, [r8 + 0]
        ld128 r9, [sp + 0]
        add r9, r9, 8
        lds.64 r9, [r9 + 0]
        add.64 r8, r8, r9
        la r9, shared_base
        lds.64 r9, [r9 + 0]
        add.64 r8, r8, r9
        mov r0, r8
        b shift.Lret
        li r0, 0
shift.Lret:
        add sp, sp, 16
        ret
# cc: func main frame=144 calls=1
main:
        add sp, sp, -144
        st128 [sp + 128], ra
        add r8, sp, 0
        li r9, 3
        st.64 [r8 + 0], r9
        mov r8, r9
        add r8, sp, 0
        add r8, r8, 8
        li r9, 4
        st.64 [r8 + 0], r9
        mov r8, r9
        add r8, sp, 0
        add r9, sp, 96
        lds.64 r10, [r8 + 0]
        st.64 [r9 + 0], r10
        lds.64 r10, [r8 + 8]
        st.64 [r9 + 8], r10
        mov r8, r9
        st128 [sp + 32], r8
        ld128 r0, [sp + 32]
        jal shift
        mov r8, r0
        st.64 [sp + 16], r8
        lds.64 r8, [sp + 16]
        li r9, 1000
        mul.64 r8, r8, r9
        add r9, sp, 0
        add r10, sp, 112
        lds.64 r11, [r9 + 0]
        st.64 [r10 + 0], r11
        lds.64 r11, [r9 + 8]
        st.64 [r10 + 8], r11
        mov r9, r10
        li r10, 5
        st128 [sp + 32], r8
        st128 [sp + 48], r9
        st128 [sp + 64], r10
        ld128 r0, [sp + 48]
        ld128 r1, [sp + 64]
        jal magnify
        mov r9, r0
        ld128 r8, [sp + 32]
        add.64 r8, r8, r9
        st.64 [sp + 16], r8
        lds.64 r8, [sp + 16]
        mov r0, r8
        b main.Lret
        li r0, 0
main.Lret:
        ld128 ra, [sp + 128]
        add sp, sp, 144
        ret
# cc: func magnify frame=32 calls=0
magnify:
        add sp, sp, -32
        st128 [sp + 0], r0
        st.64 [sp + 16], r1
        ld128 r8, [sp + 0]
        lds.64 r8, [r8 + 0]
        ld128 r9, [sp + 0]
        add r9, r9, 8
        lds.64 r9, [r9 + 0]
        add.64 r8, r8, r9
        lds.64 r9, [sp + 16]
        mul.64 r8, r8, r9
        mov r0, r8
        b magnify.Lret
        li r0, 0
magnify.Lret:
        add sp, sp, 32
        ret
        .align 16
__etext:
        .align 16
__erodata:
        .align 8
shared_base:
        .quad 0x64
        .align 16
__edata:
        .align 16
_end:
