# payload.s - the netboot CI payload's code segment (run-gui-tests
# netboot gate). mkpayload.py repacks this into a 3-segment SAHIMG01
# whose layout proves the ROM's copy-down end to end:
#
#   seg 0  0x1000  this code, file bytes padded to exactly 0x1000
#   seg 1  0x2000  0x3000 bytes of PAT - covers the ROM's whole
#                  footprint (mkpayload asserts against netboot.img),
#                  so the relocated loop demonstrably survives the
#                  self-overwrite
#   seg 2  0x4000  16 bytes of ZPAT + mem_len 0x1000: the zero-fill
#                  tail lands on bytes seg 1 JUST painted, proving
#                  both the [file_len, mem_len) zeroing and the
#                  copy-order (last-writer-wins) rule
#
# The checks below fail loudly (HALT 0xBAD) on any byte that is not
# what the segment table promised; success is the run-gui-tests
# PASS_LINE magic 0x600D. The hand-off contract is exercised for
# free: this code starts with every GPR and p1-p7 zero.

        .equ PAT_LO, 0x2000
        .equ PAT_HI, 0x4000            # pattern survives up to here
        .equ ZP_BASE, 0x4000
        .equ ZP_FILE, 16
        .equ ZP_END, 0x5000
        .equ PAT, 0xA5
        .equ ZPAT, 0xC3

        .org 0x1000
        .entry start
start:
        li      r1, PAT_LO             # seg-1 bytes all PAT
        li      r2, PAT_HI
lp1:
        ldz.8   r3, [r1]
        cmpeq   p1, r3, PAT
        (!p1) b fail
        add     r1, r1, 1
        cmpltu  p1, r1, r2
        (p1) b  lp1

        li      r2, ZP_BASE + ZP_FILE  # seg-2 file bytes all ZPAT
lz1:
        ldz.8   r3, [r1]
        cmpeq   p1, r3, ZPAT
        (!p1) b fail
        add     r1, r1, 1
        cmpltu  p1, r1, r2
        (p1) b  lz1

        li      r2, ZP_END             # zero-fill overwrote seg-1 PAT
lz2:
        ldz.8   r3, [r1]
        cmpeq   p1, r3, 0
        (!p1) b fail
        add     r1, r1, 1
        cmpltu  p1, r1, r2
        (p1) b  lz2

        li      r0, 0x600D
        halt
fail:
        li      r0, 0xBAD
        halt
