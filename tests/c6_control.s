# c6_control — CONFORMANCE.md group C6: control flow and predication.
# Assembled after tests/defs.s (run-tests.sh prepends it).
# Conventions per tests/README.md: r24 = FAIL_ADDR, r27 = test ID.
# Runs at trace level 2; checks/c6_control.sh asserts from the trace
# that SQUASH_BOX (0x710) is never touched — the "no memory access on
# squash" half of the predication tests lives there, not here.
#
# Expected values are derived by hand from ISA-SPEC 5.5 (branch
# displacement in instructions, JAL/JALR link = pc + 8), 3.2
# (predication), 7.1/7.2 (UNALIGNED trap fields), 5.7 (PRD/PWR).

        .org 0x1000
start:
        li r24, FAIL_ADDR

        # -- C6.1 backward and forward B displacement ------------------
        li r27, 1
        li r19, 0
        b fwd1
        b fail                    # skipped
back1:
        add r19, r19, 100
        b join1
fwd1:
        add r19, r19, 1
        b back1
        b fail                    # skipped
join1:
        li r20, 101
        cmpeq p1, r19, r20
        (!p1) b fail

        # -- C6.2 JAL: link register = address of next instruction -----
        li r27, 2
        jal r5, jt1
after_jal:
        b fail                    # jumped over by jal's target path
jt1:
        li r20, after_jal
        cmpeq p1, r5, r20
        (!p1) b fail

        # bare jal links ra
        li r27, 3
        jal jt2
after_jal2:
        b fail
jt2:
        li r20, after_jal2
        cmpeq p1, ra, r20
        (!p1) b fail

        # -- C6.3 JALR: byte target, imm added, link written -----------
        li r27, 4
        li r21, jt3
        jalr r5, r21, 0
after_jalr:
        b fail
jt3:
        li r20, after_jalr
        cmpeq p1, r5, r20
        (!p1) b fail

        li r27, 5
        li r21, jt4 - 16          # nonzero displacement path
        jalr zero, r21, 16
        b fail
jt4:

        # ret = jalr zero, ra, 0
        li r27, 6
        li r19, 0
        jal func1
        cmpeq p1, r19, 7
        (!p1) b fail
        b c6_4
func1:
        li r19, 7
        ret

        # -- C6.4 JALR misalignment: UNALIGNED, baddr = target, --------
        #    epc = the jalr, no link write on the faulting path
c6_4:
        li r27, 7
        li r21, handler
        mtsr vbase, r21
        li r5, 1234               # must survive the faulting jalr
        li r21, jt5 + 4           # 8-byte alignment violated
jalr_site:
        jalr r5, r21, 0           # traps; handler records and skips
jt5:
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_UNALIGNED
        (!p1) b fail
        li r27, 8
        lds.64 r22, [r24 + TRAP_BADDR_SLOT - FAIL_ADDR]
        li r20, jt5 + 4
        cmpeq p1, r22, r20
        (!p1) b fail
        li r27, 9
        lds.64 r22, [r24 + TRAP_EPC_SLOT - FAIL_ADDR]
        li r20, jalr_site
        cmpeq p1, r22, r20
        (!p1) b fail
        li r27, 10
        li r20, 1234              # faulting instruction wrote no link
        cmpeq p1, r5, r20
        (!p1) b fail

        # -- C6.5 predication: all 16 pred-field encodings -------------
        # PWR 0xAA sets p1,p3,p5,p7; p0 stays hardwired 1.
        li r27, 11
        li r21, 0xAA
        pwr r21
        prd r19
        li r20, 0xAB
        cmpeq p1, r19, r20
        (!p1) b fail

        # NOTE: p1 is set (1) by the pattern; keep using p1 for the
        # check compares only AFTER each block's own predicate test.
        li r27, 12                # (p0)  -> executes
        li r19, 0
        (p0) add r19, zero, 1
        cmpeq p1, r19, 1
        (!p1) b fail
        li r27, 13                # (!p0) -> never executes
        li r19, 0
        (!p0) add r19, zero, 1
        cmpeq p1, r19, 0
        (!p1) b fail
        li r27, 14                # (p1) set
        li r19, 0
        (p1) add r19, zero, 1
        cmpeq p1, r19, 1          # p1 still 1 (compare true)
        (!p1) b fail
        li r27, 15                # (!p1)
        li r19, 0
        (!p1) add r19, zero, 1
        cmpeq p1, r19, 0
        (!p1) b fail
        # re-establish the pattern (the checks above rewrote p1)
        li r21, 0xAA
        pwr r21
        li r27, 16                # (p2) clear
        li r19, 0
        (p2) add r19, zero, 1
        cmpeq p1, r19, 0
        (!p1) b fail
        li r27, 17                # (!p2)
        li r19, 0
        (!p2) add r19, zero, 1
        cmpeq p1, r19, 1
        (!p1) b fail
        li r27, 18                # (p3) set
        li r19, 0
        (p3) add r19, zero, 1
        cmpeq p1, r19, 1
        (!p1) b fail
        li r27, 19                # (!p3)
        li r19, 0
        (!p3) add r19, zero, 1
        cmpeq p1, r19, 0
        (!p1) b fail
        li r27, 20                # (p4) clear
        li r19, 0
        (p4) add r19, zero, 1
        cmpeq p1, r19, 0
        (!p1) b fail
        li r27, 21                # (!p4)
        li r19, 0
        (!p4) add r19, zero, 1
        cmpeq p1, r19, 1
        (!p1) b fail
        li r27, 22                # (p5) set
        li r19, 0
        (p5) add r19, zero, 1
        cmpeq p1, r19, 1
        (!p1) b fail
        li r27, 23                # (!p5)
        li r19, 0
        (!p5) add r19, zero, 1
        cmpeq p1, r19, 0
        (!p1) b fail
        li r27, 24                # (p6) clear
        li r19, 0
        (p6) add r19, zero, 1
        cmpeq p1, r19, 0
        (!p1) b fail
        li r27, 25                # (!p6)
        li r19, 0
        (!p6) add r19, zero, 1
        cmpeq p1, r19, 1
        (!p1) b fail
        li r27, 26                # (p7) set
        li r19, 0
        (p7) add r19, zero, 1
        cmpeq p1, r19, 1
        (!p1) b fail
        li r27, 27                # (!p7)
        li r19, 0
        (!p7) add r19, zero, 1
        cmpeq p1, r19, 0
        (!p1) b fail

        # -- C6.6 squash: no memory access, no link, no pred write, ----
        #    no control transfer. SQUASH_BOX untouched is asserted from
        #    the trace by checks/c6_control.sh.
        li r25, SQUASH_BOX
        li r27, 28
        li r21, 7
        cmpeq p2, r21, 8          # p2 = 0 for this whole section
        li r19, 55
        (p2) st.64 [r25], r21     # squashed store: no access
        (p2) st128 [r25], r21
        (p2) lds.64 r19, [r25]    # squashed load: r19 unchanged
        (p2) ld128 r19, [r25]
        cmpeq p1, r19, 55
        (!p1) b fail

        li r27, 29                # squashed CAS: no access, no dst write
        li r19, 66
        (p2) cas.64 r19, [r25], r21, r21
        (p2) amoadd.64 r19, [r25], r21
        cmpeq p1, r19, 66
        (!p1) b fail

        li r27, 30                # squashed branches fall through
        (p2) b fail
        (p2) jal r5, fail
        li r20, 1234              # r5 keeps the C6.4 value (squashed
        cmpeq p1, r5, r20         # jal wrote no link)
        (!p1) b fail

        li r27, 31                # squashed IRET: no control transfer
        (p2) iret
        li r19, 1                 # reached only if iret squashed
        cmpeq p1, r19, 1
        (!p1) b fail

        li r27, 32                # squashed compare: no predicate write
        li r21, 0xAA
        pwr r21                   # p3 = 1
        li r22, 5
        (p2) cmpeq p3, r22, 0     # would write p3=0; squashed
        li r19, 0
        (p3) add r19, zero, 1
        cmpeq p1, r19, 1
        (!p1) b fail

        # -- C6.7 PRD/PWR round-trip: ABI handler save/restore ---------
        li r27, 33
        li r21, 0x54              # p2,p4,p6 (bit0 clear)
        pwr r21
        prd r22                   # save (reads 0x55: bit0 forced 1)
        li r21, 0xAA
        pwr r21                   # clobber
        pwr r22                   # restore from saved copy
        prd r19
        li r20, 0x55
        cmpeq p1, r19, r20
        (!p1) b fail

pass:
        li r0, PASS_MAGIC
        halt
fail:
        st.64 [r24], r27
        mov r0, r27
        halt

        # -- trap handler: record bank-0 fields, skip the instruction --
handler:
        mfsr k0, cause0
        st.64 [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR], k0
        mfsr k0, baddr0
        st.64 [r24 + TRAP_BADDR_SLOT - FAIL_ADDR], k0
        mfsr k0, epc0
        st.64 [r24 + TRAP_EPC_SLOT - FAIL_ADDR], k0
        add k0, k0, 8
        mtsr epc0, k0
        iret
