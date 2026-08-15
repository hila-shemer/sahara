# fnlib.s - function-pointer interop fixture (text-only, like
# asmlib.s). Both directions of the M2 indirect-call surface:
#   C -> asm through a pointer: fn_double is a plain SABI leaf whose
#       address the C side takes via an extern prototype and calls
#       through a function-pointer variable.
#   asm jalr's a C function: fn_dispatch(f, x) receives a C function
#       pointer in r0 and calls it with x - the hand-written side of
#       the same jalr convention abicheck holds compiled code to.

fn_double:                             # (r0 x) -> r0 = 2x; frameless leaf
        add     r0, r0, r0
        ret

fn_dispatch:                           # (r0 f, r1 x) -> r0 = f(x)
        add     sp, sp, -16
        st128   [sp + 0], ra
        mov     r8, r0
        mov     r0, r1
        jalr    ra, r8, 0
        ld128   ra, [sp + 0]
        add     sp, sp, 16
        ret
