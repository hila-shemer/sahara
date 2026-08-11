# crt0.s - CC-M1 program entry (lang/cc/cc-m1.md section 10).
# First file on the assembler command line: owns .org 0x1000 and
# .entry. Everything here is derived from the device table - the only
# hardcodable address is the table's own 0x0800 (SABI 4 / boot.md 2.3).
# u128 table fields are 8-aligned only: paired ldz.64, never LD128
# (boot.md 3.2 - an LD128 there traps UNALIGNED).

        .org 0x1000
        .entry _start
_start:
        li      r1, 0x800
        ldz.64  r2, [r1 + 0]           # magic
        li      r3, 0x5450415241484153 # "SAHARAPT"
        cmpeq   p1, r2, r3
        (!p1) b crt_fail_magic
        ldz.64  r2, [r1 + 8]           # version
        cmpeq   p1, r2, 1
        (!p1) b crt_fail_ver
        ldz.64  r2, [r1 + 24]          # ram_region_count >= 1
        cmpltu  p1, zero, r2
        (!p1) b crt_fail_nram

        # sp = RAM region 0 base + len (SABI 4.5); regions above 2^64
        # are beyond this runtime - fail loudly, never wrap.
        ldz.64  r4, [r1 + 40]          # base lo
        ldz.64  r5, [r1 + 48]          # base hi
        ldz.64  r6, [r1 + 56]          # len lo
        ldz.64  r7, [r1 + 64]          # len hi
        or      r5, r5, r7
        cmpeq   p1, r5, zero
        (!p1) b crt_fail_u128
        add     sp, r4, r6

        # vectors before main - a fault in compiled code lands in
        # cc_trap and halts with a distinct code instead of wandering.
        la      r2, cc_trap
        mtsr    vbase, r2
        la      r2, cc_df
        mtsr    dfbase, r2

        jal     main
        halt                           # r0 = main's return value

# ---- loud terminal failures, one code each (cc-m1.md section 10)
crt_fail_magic:
        li      r0, 0xCCBAD001
        halt
crt_fail_ver:
        li      r0, 0xCCBAD002
        halt
crt_fail_nram:
        li      r0, 0xCCBAD003
        halt
crt_fail_u128:
        li      r0, 0xCCBAD004
        halt
