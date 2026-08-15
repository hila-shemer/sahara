# 49-subwidth-convert.c - CC-M1 compiled output (lang/cc/cc.py; spec lang/cc/cc-m1.md)
        .align 16
# cc: func main frame=192 calls=0
main:
        add sp, sp, -192
        li r8, 1311768467463790320
        st.64 [sp + 0], r8
        lds.64 r8, [sp + 0]
        or.64 r8, zero, r8 sxt 8
        or.64 r8, zero, r8 sxt 8
        st.8 [sp + 16], r8
        lds.64 r8, [sp + 0]
        and.64 r8, r8, 0xff
        and.64 r8, r8, 0xff
        st.8 [sp + 32], r8
        lds.64 r8, [sp + 0]
        or.64 r8, zero, r8 sxt 16
        or.64 r8, zero, r8 sxt 16
        st.16 [sp + 48], r8
        lds.64 r8, [sp + 0]
        or.64 r8, zero, r8 zxt 16
        or.64 r8, zero, r8 zxt 16
        st.16 [sp + 64], r8
        lds.64 r8, [sp + 0]
        or.32 r8, r8, 0
        st.32 [sp + 80], r8
        lds.64 r8, [sp + 0]
        or.32 r8, r8, 0
        st.32 [sp + 96], r8
        lds.32 r8, [sp + 96]
        or.64 r8, zero, r8 zxt 32
        st.64 [sp + 112], r8
        lds.32 r8, [sp + 80]
        st.64 [sp + 128], r8
        lds.64 r8, [sp + 112]
        shl r8, r8, 64
        shr r8, r8, 64
        st128 [sp + 144], r8
        lds.32 r8, [sp + 80]
        st128 [sp + 160], r8
        lds.8 r8, [sp + 16]
        ldz.8 r9, [sp + 32]
        add.64 r8, r8, r9
        lds.16 r9, [sp + 48]
        add.64 r8, r8, r9
        ldz.16 r9, [sp + 64]
        add.64 r8, r8, r9
        st.64 [sp + 176], r8
        lds.64 r8, [sp + 176]
        lds.32 r9, [sp + 80]
        add.64 r8, r8, r9
        lds.32 r9, [sp + 96]
        or.64 r9, zero, r9 zxt 32
        add.64 r8, r8, r9
        lds.64 r9, [sp + 112]
        add.64 r8, r8, r9
        lds.64 r9, [sp + 128]
        add.64 r8, r8, r9
        st.64 [sp + 176], r8
        lds.64 r8, [sp + 176]
        ld128 r9, [sp + 144]
        li r10, 1
        sar r9, r9, r10
        or.64 r9, r9, 0
        add.64 r8, r8, r9
        ld128 r9, [sp + 160]
        li r10, 255
        and r9, r9, r10
        or.64 r9, r9, 0
        add.64 r8, r8, r9
        st.64 [sp + 176], r8
        lds.64 r8, [sp + 176]
        mov r0, r8
        b main.Lret
        li r0, 0
main.Lret:
        add sp, sp, 192
        ret
        .align 16
__etext:
        .align 16
__erodata:
        .align 16
__edata:
        .align 16
_end:
