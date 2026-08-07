# c1_triplefault — CONFORMANCE.md C1: fault at TL=2 halts the machine.
# Own image: the halt ends the run, so the harness checks the HALT line
# against the marker below via `expect=` in MANIFEST (SPEC-ISSUES 12:
# any architectural halt prints `HALT r0=<r0>` and exits 0).
#
# Chain: UNALIGNED load -> vbase handler is itself an ILLEGAL word
# (double fault, TL=2) -> dfbase handler is also an ILLEGAL word ->
# delivery at TL=2 = triple fault: machine halts, no state written
# (ISA-SPEC 7.2 step 1).
#
# checks/c1_triplefault.sh asserts from the trace that exactly two TRAP
# records exist (tl_after 1 and 2) — the triple fault itself delivers
# nothing (SPEC-ISSUES 17). "No sreg was modified" is not directly
# observable post-halt (sregs are not trace records); the two-TRAP
# shape and the exact marker in r0 are the observable consequences.

        .equ TRIPLE_MARKER, 0x3F3F   # harness expects HALT r0=...3f3f

        .org 0x1000
start:
        li r21, h_bad
        mtsr vbase, r21
        li r21, h_dfbad
        mtsr dfbase, r21
        li r22, SENTINEL_BOX + 1
        li r0, TRIPLE_MARKER      # survives: triple fault writes nothing
        lds.64 r19, [r22]         # ea 0x719 -> UNALIGNED (fault 1)
        li r0, 0xDEAD             # must never execute
        halt

h_bad:
        .quad RAW_ILLEGAL         # fault 2: double fault -> dfbase
h_dfbad:
        .quad RAW_ILLEGAL         # fault 3 at TL=2: triple fault, halt
