# 76-struct-return.c - CC-M1 compiled output (lang/cc/cc.py; spec lang/cc/cc-m1.md)
        .align 16
# cc: func mk frame=64 calls=0
mk:
        add sp, sp, -64
        st128 [sp + 32], r0
        st.64 [sp + 0], r1
        st.64 [sp + 16], r2
        add r8, sp, 48
        lds.64 r9, [sp + 0]
        st.64 [r8 + 0], r9
        mov r8, r9
        add r8, sp, 48
        add r8, r8, 8
        lds.64 r9, [sp + 16]
        st.64 [r8 + 0], r9
        mov r8, r9
        add r8, sp, 48
        ld128 r9, [sp + 32]
        lds.64 r10, [r8 + 0]
        st.64 [r9 + 0], r10
        lds.64 r10, [r8 + 8]
        st.64 [r9 + 8], r10
        mov r0, r9
        b mk.Lret
        ld128 r0, [sp + 32]
mk.Lret:
        add sp, sp, 64
        ret
# cc: func flip frame=48 calls=0
flip:
        add sp, sp, -48
        st128 [sp + 16], r0
        st128 [sp + 0], r1
        add r8, sp, 32
        ld128 r9, [sp + 0]
        add r9, r9, 8
        lds.64 r9, [r9 + 0]
        st.64 [r8 + 0], r9
        mov r8, r9
        add r8, sp, 32
        add r8, r8, 8
        ld128 r9, [sp + 0]
        lds.64 r9, [r9 + 0]
        st.64 [r8 + 0], r9
        mov r8, r9
        add r8, sp, 32
        ld128 r9, [sp + 16]
        lds.64 r10, [r8 + 0]
        st.64 [r9 + 0], r10
        lds.64 r10, [r8 + 8]
        st.64 [r9 + 8], r10
        mov r0, r9
        b flip.Lret
        ld128 r0, [sp + 16]
flip.Lret:
        add sp, sp, 48
        ret
# cc: func dot frame=32 calls=0
dot:
        add sp, sp, -32
        st128 [sp + 0], r0
        st128 [sp + 16], r1
        ld128 r8, [sp + 0]
        lds.64 r8, [r8 + 0]
        ld128 r9, [sp + 16]
        lds.64 r9, [r9 + 0]
        mul.64 r8, r8, r9
        ld128 r9, [sp + 0]
        add r9, r9, 8
        lds.64 r9, [r9 + 0]
        ld128 r10, [sp + 16]
        add r10, r10, 8
        lds.64 r10, [r10 + 0]
        mul.64 r9, r9, r10
        add.64 r8, r8, r9
        mov r0, r8
        b dot.Lret
        li r0, 0
dot.Lret:
        add sp, sp, 32
        ret
# cc: func main frame=400 calls=1
main:
        add sp, sp, -400
        st128 [sp + 384], ra
        li r8, 3
        li r9, 4
        st128 [sp + 64], r8
        st128 [sp + 80], r9
        ld128 r1, [sp + 64]
        ld128 r2, [sp + 80]
        add r0, sp, 144
        jal mk
        mov r8, r0
        add r9, sp, 0
        lds.64 r10, [r8 + 0]
        st.64 [r9 + 0], r10
        lds.64 r10, [r8 + 8]
        st.64 [r9 + 8], r10
        add r8, sp, 16
        add r9, sp, 0
        add r10, sp, 176
        lds.64 r11, [r9 + 0]
        st.64 [r10 + 0], r11
        lds.64 r11, [r9 + 8]
        st.64 [r10 + 8], r11
        mov r9, r10
        st128 [sp + 64], r8
        st128 [sp + 80], r9
        ld128 r1, [sp + 80]
        add r0, sp, 160
        jal flip
        mov r9, r0
        ld128 r8, [sp + 64]
        lds.64 r10, [r9 + 0]
        st.64 [r8 + 0], r10
        lds.64 r10, [r9 + 8]
        st.64 [r8 + 8], r10
        add r8, sp, 0
        add r9, sp, 192
        lds.64 r10, [r8 + 0]
        st.64 [r9 + 0], r10
        lds.64 r10, [r8 + 8]
        st.64 [r9 + 8], r10
        mov r8, r9
        add r9, sp, 16
        add r10, sp, 208
        lds.64 r11, [r9 + 0]
        st.64 [r10 + 0], r11
        lds.64 r11, [r9 + 8]
        st.64 [r10 + 8], r11
        mov r9, r10
        st128 [sp + 64], r8
        st128 [sp + 80], r9
        ld128 r0, [sp + 64]
        ld128 r1, [sp + 80]
        jal dot
        mov r8, r0
        st.64 [sp + 32], r8
        lds.64 r8, [sp + 32]
        li r9, 1000
        mul.64 r8, r8, r9
        li r9, 1
        li r10, 2
        st128 [sp + 64], r8
        st128 [sp + 80], r9
        st128 [sp + 96], r10
        ld128 r1, [sp + 80]
        ld128 r2, [sp + 96]
        add r0, sp, 224
        jal mk
        mov r9, r0
        ld128 r8, [sp + 64]
        add r10, sp, 240
        lds.64 r11, [r9 + 0]
        st.64 [r10 + 0], r11
        lds.64 r11, [r9 + 8]
        st.64 [r10 + 8], r11
        mov r9, r10
        li r10, 3
        li r11, 4
        st128 [sp + 64], r8
        st128 [sp + 80], r9
        st128 [sp + 96], r10
        st128 [sp + 112], r11
        ld128 r1, [sp + 96]
        ld128 r2, [sp + 112]
        add r0, sp, 272
        jal mk
        mov r10, r0
        ld128 r8, [sp + 64]
        ld128 r9, [sp + 80]
        add r11, sp, 288
        lds.64 r12, [r10 + 0]
        st.64 [r11 + 0], r12
        lds.64 r12, [r10 + 8]
        st.64 [r11 + 8], r12
        mov r10, r11
        st128 [sp + 64], r8
        st128 [sp + 80], r9
        st128 [sp + 96], r10
        ld128 r1, [sp + 96]
        add r0, sp, 256
        jal flip
        mov r10, r0
        ld128 r8, [sp + 64]
        ld128 r9, [sp + 80]
        add r11, sp, 304
        lds.64 r12, [r10 + 0]
        st.64 [r11 + 0], r12
        lds.64 r12, [r10 + 8]
        st.64 [r11 + 8], r12
        mov r10, r11
        st128 [sp + 64], r8
        st128 [sp + 80], r9
        st128 [sp + 96], r10
        ld128 r0, [sp + 80]
        ld128 r1, [sp + 96]
        jal dot
        mov r9, r0
        ld128 r8, [sp + 64]
        add.64 r8, r8, r9
        st.64 [sp + 32], r8
        add r8, sp, 0
        add r9, sp, 352
        lds.64 r10, [r8 + 0]
        st.64 [r9 + 0], r10
        lds.64 r10, [r8 + 8]
        st.64 [r9 + 8], r10
        mov r8, r9
        st128 [sp + 64], r8
        ld128 r1, [sp + 64]
        add r0, sp, 336
        jal flip
        mov r8, r0
        add r9, sp, 368
        lds.64 r10, [r8 + 0]
        st.64 [r9 + 0], r10
        lds.64 r10, [r8 + 8]
        st.64 [r9 + 8], r10
        mov r8, r9
        st128 [sp + 64], r8
        ld128 r1, [sp + 64]
        add r0, sp, 320
        jal flip
        mov r8, r0
        add r9, sp, 48
        lds.64 r10, [r8 + 0]
        st.64 [r9 + 0], r10
        lds.64 r10, [r8 + 8]
        st.64 [r9 + 8], r10
        lds.64 r8, [sp + 32]
        li r9, 1000
        mul.64 r8, r8, r9
        add r9, sp, 48
        lds.64 r9, [r9 + 0]
        li r10, 10
        mul.64 r9, r9, r10
        add.64 r8, r8, r9
        add r9, sp, 48
        add r9, r9, 8
        lds.64 r9, [r9 + 0]
        add.64 r8, r8, r9
        st.64 [sp + 32], r8
        lds.64 r8, [sp + 32]
        mov r0, r8
        b main.Lret
        li r0, 0
main.Lret:
        ld128 ra, [sp + 384]
        add sp, sp, 400
        ret
        .align 16
__etext:
        .align 16
__erodata:
        .align 16
__edata:
        .align 16
_end:
