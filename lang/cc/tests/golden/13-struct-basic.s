# 13-struct-basic.c - CC-M1 compiled output (lang/cc/cc.py; spec lang/cc/cc-m1.md)
        .align 16
# cc: func main frame=224 calls=0
main:
        add sp, sp, -224
        add r8, sp, 0
        li r9, 11
        st.64 [r8 + 0], r9
        mov r8, r9
        add r8, sp, 0
        add r8, r8, 8
        li r9, 22
        st.64 [r8 + 0], r9
        mov r8, r9
        add r8, sp, 0
        add r8, r8, 16
        li r9, 7
        and.64 r9, r9, 0xff
        and.64 r9, r9, 0xff
        st.8 [r8 + 0], r9
        mov r8, r9
        add r8, sp, 32
        li r9, 100
        st.64 [r8 + 0], r9
        mov r8, r9
        add r8, sp, 32
        add r8, r8, 24
        li r9, 2
        shl r9, r9, 3
        add r8, r8, r9
        li r9, 55
        st.64 [r8 + 0], r9
        mov r8, r9
        add r8, sp, 32
        add r8, r8, 48
        li r9, 200
        and.64 r9, r9, 0xff
        and.64 r9, r9, 0xff
        st.8 [r8 + 0], r9
        mov r8, r9
        add r8, sp, 96
        li r9, 3
        mul r9, r9, 24
        add r8, r8, r9
        li r9, 1000
        st.64 [r8 + 0], r9
        mov r8, r9
        add r8, sp, 0
        st128 [sp + 192], r8
        ld128 r8, [sp + 192]
        add r8, r8, 8
        li r9, 33
        st.64 [r8 + 0], r9
        mov r8, r9
        add r8, sp, 0
        lds.64 r8, [r8 + 0]
        add r9, sp, 0
        add r9, r9, 8
        lds.64 r9, [r9 + 0]
        add.64 r8, r8, r9
        add r9, sp, 0
        add r9, r9, 16
        ldz.8 r9, [r9 + 0]
        add.64 r8, r8, r9
        add r9, sp, 32
        lds.64 r9, [r9 + 0]
        add.64 r8, r8, r9
        add r9, sp, 32
        add r9, r9, 24
        li r10, 2
        shl r10, r10, 3
        add r9, r9, r10
        lds.64 r9, [r9 + 0]
        add.64 r8, r8, r9
        add r9, sp, 32
        add r9, r9, 48
        ldz.8 r9, [r9 + 0]
        add.64 r8, r8, r9
        add r9, sp, 96
        li r10, 3
        mul r10, r10, 24
        add r9, r9, r10
        lds.64 r9, [r9 + 0]
        add.64 r8, r8, r9
        st.64 [sp + 208], r8
        lds.64 r8, [sp + 208]
        li r9, 1000
        mul.64 r8, r8, r9
        li r9, 24
        add.64 r8, r8, r9
        li r9, 56
        add.64 r8, r8, r9
        mov r0, r8
        b main.Lret
        li r0, 0
main.Lret:
        add sp, sp, 224
        ret
        .align 16
__etext:
        .align 16
__erodata:
        .align 16
__edata:
        .align 16
_end:
