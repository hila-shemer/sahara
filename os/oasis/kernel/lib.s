# lib.s - tiny leaf helpers (frameless per SABI 2.5; temps r8-r15).
# No libc, and none is owed - SABI defers the whole surface.

lib_strlen:                            # r0 = asciiz -> r0 = length
        mov     r8, r0
ls_loop:
        ldz.8   r9, [r8]
        cmpeq   p1, r9, zero
        (p1) b  ls_done
        add     r8, r8, 1
        b       ls_loop
ls_done:
        sub     r0, r8, r0
        ret

lib_streq:                             # (r0 a, r1 b) -> r0 = 1 if equal
        mov     r8, r0
        mov     r9, r1
le_loop:
        ldz.8   r10, [r8]
        ldz.8   r11, [r9]
        cmpeq   p1, r10, r11
        (!p1) b le_ne
        cmpeq   p1, r10, zero          # equal so far; both ended?
        (p1) b  le_eq
        add     r8, r8, 1
        add     r9, r9, 1
        b       le_loop
le_eq:
        li      r0, 1
        ret
le_ne:
        li      r0, 0
        ret

lib_prefix:                            # (r0 str, r1 prefix) -> r0 = 1
        mov     r8, r0                 # if str starts with prefix
        mov     r9, r1
lp_loop:
        ldz.8   r11, [r9]
        cmpeq   p1, r11, zero          # prefix exhausted: match
        (p1) b  le_eq
        ldz.8   r10, [r8]
        cmpeq   p1, r10, r11
        (!p1) b le_ne
        add     r8, r8, 1
        add     r9, r9, 1
        b       lp_loop

lib_append:                            # (r0 dst, r1 src asciiz) -> r0 =
        mov     r8, r1                 # dst end (no terminator written)
la_loop:
        ldz.8   r9, [r8]
        cmpeq   p1, r9, zero
        (p1) b  la_done
        st.8    [r0], r9
        add     r0, r0, 1
        add     r8, r8, 1
        b       la_loop
la_done:
        ret

lib_u64hex:                            # (r0 buf, r1 value) -> r0 = end;
        cmpeq   p1, r1, zero           # lowercase, no leading zeros
        (!p1) b lh_digits
        li      r8, 0x30
        st.8    [r0], r8
        add     r0, r0, 1
        ret
lh_digits:
        mov     r8, r0                 # nibbles reversed, then reuse
lh_loop:                               # u64dec's in-place reverse
        cmpeq   p1, r1, zero
        (p1) b  lu_rev
        and     r9, r1, 15
        cmpltu  p1, r9, 10
        add     r9, r9, 0x30
        (!p1) add r9, r9, 0x27         # 'a' - '0' - 10
        st.8    [r8], r9
        add     r8, r8, 1
        shr     r1, r1, 4
        b       lh_loop

lib_u64dec:                            # (r0 buf, r1 value) -> r0 = end;
        cmpeq   p1, r1, zero           # unsigned decimal, no leading 0s
        (!p1) b lu_digits
        li      r8, 0x30               # "0"
        st.8    [r0], r8
        add     r0, r0, 1
        ret
lu_digits:
        mov     r8, r0                 # write digits reversed...
lu_loop:
        cmpeq   p1, r1, zero
        (p1) b  lu_rev
        urem.64 r9, r1, 10
        add     r9, r9, 0x30
        st.8    [r8], r9
        add     r8, r8, 1
        udiv.64 r1, r1, 10
        b       lu_loop
lu_rev:                                # ...then reverse in place
        mov     r9, r0
        sub     r10, r8, 1
lr_loop:
        cmpltu  p1, r9, r10
        (!p1) b lr_done
        ldz.8   r11, [r9]
        ldz.8   r12, [r10]
        st.8    [r9], r12
        st.8    [r10], r11
        add     r9, r9, 1
        sub     r10, r10, 1
        b       lr_loop
lr_done:
        mov     r0, r8
        ret

        # end of text (SABI 6.3: sections are referenced only via
        # these labels; rodata - the generated font - follows)
        .align 16
__etext:
