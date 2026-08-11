# asmlib.s - interop fixture (text-only: sits between sys.s and the
# compiled unit, so it may not open sections or define seam labels).
# Exercises both interop directions of cc-m1.md section 7:
#   C -> asm: asm_add3(a, b, c) - a plain SABI leaf the compiled code
#             calls through an extern prototype.
#   asm -> C: asm_call_c(x)     - saves ra, calls the C function
#             c_scale(x, 3) defined in the compiled unit (forward
#             reference across files; concatenation IS linkage).
# Also defines asm_seed, an extern global the C side reads.

asm_add3:                              # (r0, r1, r2) -> r0 sum; frameless leaf
        add     r0, r0, r1
        add     r0, r0, r2
        ret

asm_call_c:                            # (r0 x) -> r0 = c_scale(x, 3) + 1
        add     sp, sp, -16
        st128   [sp + 0], ra
        li      r1, 3
        jal     c_scale
        add     r0, r0, 1
        ld128   ra, [sp + 0]
        add     sp, sp, 16
        ret

        .align 16
asm_seed:                              # u64 the C side reads (extern)
        .quad   0x1155
