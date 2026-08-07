# c1_wfihang — the reference-implementation check "WFI deadlock halts"
# (CONFORMANCE.md last section; ISA-SPEC 7.6: if no future event exists
# that could make an interrupt pending, the machine halts — deadlock is
# loud). At reset IE=0 and timecmp=0 (0 never pends, ISA-SPEC 7.5), and
# the headless suite has no device that could ever assert EXTINT, so
# this WFI can never wake: the only conforming outcome is an
# architectural halt, which prints the contract line with current r0
# (SPEC-ISSUES 12) — MANIFEST carries expect=...57a11 ("stall").
#
# The two wrong behaviors both fail loudly: treating WFI as a nop falls
# through to a HALT with r0=0xbad (expect mismatch); spinning forever
# is a MAXCYCLES exit 2.

        .org 0x1000
start:
        li r0, 0x57A11
        wfi                       # nothing pending, nothing armed:
                                  # must halt the machine here
        li r0, 0xbad              # reached only if WFI fell through
        halt
