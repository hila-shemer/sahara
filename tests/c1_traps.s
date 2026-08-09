# c1_traps — CONFORMANCE.md group C1: traps, nesting, privilege.
# Assembled after tests/defs.s (run-tests.sh prepends it).
# Conventions per tests/README.md: r24 = FAIL_ADDR, r27 = test ID.
#
# Expected values derived by hand from ISA-SPEC 7.1 (cause table, epc
# semantics per cause class), 7.2 (trap levels and banks), 7.3 (TL
# lowering), 7.4 (IRET), 7.5 (interrupts), 7.6 (WFI), 2.3/2.4
# (privilege), 3.2 (predication cannot fault), 4 (cycle counting).
#
# Bounded coverage — deliberately NOT here (no silent gaps):
# - Triple fault is its own image (c1_triplefault.s + expect= in
#   MANIFEST) because it ends the machine.
# - EXTINT delivery/masking needs device input events (--replay); lands
#   with C7. IE masking is exercised with the timer here.
# - Page-fault flavors of "handler faults" / TL-lowering: the spec's
#   example is a nested *page* fault; C1 runs MMU-off and uses
#   UNALIGNED as the legitimate nested fault (same delivery machinery);
#   C2 redoes the pattern with a real PF.
# - False-predicated load to an *unmapped* address is C2 (needs MMU);
#   here squash covers unaligned/illegal/syscall/priv cases.
# - "Verify no sreg was modified" after triple fault is bounded to what
#   a trace can show (checks/c1_triplefault.sh); sregs are not trace
#   records.
# - MFSR cycle read timing: value excludes the reading instruction's
#   own increment (SPEC-ISSUES entry 16); the cycle-delta checks here
#   depend on it.
#
# Register use: r24 FAIL_ADDR, r27 test ID, r19-r23 scratch,
# r26 handler scratch (phase U), k0 handler bootstrap.

        .org 0x1000
start:
        li r24, FAIL_ADDR

# ==== phase A: single-level faults, supervisor, IE=0 (reset state) ====
# Faults must deliver regardless of IE=0 (ISA-SPEC 7.5) — the whole
# phase runs with interrupts disabled, so every delivery below is also
# an IE=0 fault-delivery check.

        la.abs r21, h_rec
        mtsr vbase, r21

        # -- A1: ILLEGAL raw word: cause, epc, no baddr contract; -------
        #    TL=1 + S=1 inside the handler, TL=0 after IRET
        li r27, 1
a1_site:
        .quad RAW_ILLEGAL         # traps ILLEGAL; h_rec records + skips
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_ILLEGAL
        (!p1) b fail
        li r27, 2
        lds.64 r22, [r24 + TRAP_EPC_SLOT - FAIL_ADDR]
        la.abs r20, a1_site
        cmpeq p1, r22, r20
        (!p1) b fail
        li r27, 3                 # status seen by handler: S=1, TL=1
        lds.64 r22, [r24 + TRAP_STATUS_SLOT - FAIL_ADDR]
        li r20, STATUS_S + STATUS_TL_UNIT
        and r22, r22, STATUS_S + STATUS_TL_MASK
        cmpeq p1, r22, r20
        (!p1) b fail
        li r27, 4                 # after IRET: TL back to 0, S=1
        mfsr r22, status
        and r22, r22, STATUS_S + STATUS_TL_MASK
        cmpeq p1, r22, STATUS_S
        (!p1) b fail

        # -- A2: UNALIGNED load: baddr = ea ----------------------------
        li r27, 5
a2_site:
        lds.64 r19, [r24 + SENTINEL_BOX + 1 - FAIL_ADDR]   # ea 0x719
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_UNALIGNED
        (!p1) b fail
        li r27, 6
        lds.64 r22, [r24 + TRAP_BADDR_SLOT - FAIL_ADDR]
        cmpeq p1, r22, SENTINEL_BOX + 1
        (!p1) b fail
        li r27, 7
        lds.64 r22, [r24 + TRAP_EPC_SLOT - FAIL_ADDR]
        la.abs r20, a2_site
        cmpeq p1, r22, r20
        (!p1) b fail

        # -- A3: UNALIGNED store (4-byte at +2) ------------------------
        li r27, 8
        st.32 [r24 + SENTINEL_BOX + 2 - FAIL_ADDR], r19    # ea 0x71a
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_UNALIGNED
        (!p1) b fail
        li r27, 9
        lds.64 r22, [r24 + TRAP_BADDR_SLOT - FAIL_ADDR]
        cmpeq p1, r22, SENTINEL_BOX + 2
        (!p1) b fail

        # -- A4: SYSCALL from supervisor: epc = the SYSCALL itself -----
        li r27, 10
a4_site:
        syscall                   # h_rec records, epc+8 resumes past it
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_SYSCALL
        (!p1) b fail
        li r27, 11
        lds.64 r22, [r24 + TRAP_EPC_SLOT - FAIL_ADDR]
        la.abs r20, a4_site
        cmpeq p1, r22, r20
        (!p1) b fail

        # -- A5: write to cycle traps PRIV from any mode ---------------
        li r27, 12
        li r19, 5
        mtsr cycle, r19           # supervisor, still PRIV (ISA-SPEC 2.3)
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_PRIV
        (!p1) b fail

        # -- A6: MFSR of an unlisted sreg index traps ILLEGAL ----------
        li r27, 13
        .quad RAW_MFSR_SREG16
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_ILLEGAL
        (!p1) b fail

# ==== phase B: double fault, banks, TL writability ====================

        # -- B1: fault in handler prologue -> double fault -------------
        #    bank 1 = second fault, bank 0 intact with the first;
        #    IRET at TL=2 selects bank 1
        li r27, 14
        la.abs r21, h_bad             # handler that faults immediately
        mtsr vbase, r21
        la.abs r21, h_df
        mtsr dfbase, r21
b1_site:
        lds.64 r19, [r24 + SENTINEL_BOX + 1 - FAIL_ADDR]   # first fault
        # h_bad raises ILLEGAL at TL=1 -> h_df checks both banks, sets
        # epc1 = b1_cont, IRETs (bank 1) -> here at TL=1
b1_cont:
        li r27, 15                # IRET from TL=2 landed us at TL=1
        mfsr r22, status
        shr r22, r22, STATUS_TL_LSB
        and r22, r22, 3
        cmpeq p1, r22, 1
        (!p1) b fail
        li r21, STATUS_S          # repair: TL<-0 (TL is MTSR-writable)
        mtsr status, r21

        # -- B2: SYSCALL at TL=1 double-faults (spec consequence) ------
        li r27, 16
        la.abs r21, h_rec
        mtsr vbase, r21           # must NOT be used by this delivery
        la.abs r21, h_df2
        mtsr dfbase, r21
        li r21, STATUS_S + STATUS_TL_UNIT
        mtsr status, r21          # claim TL=1 by software consent
b2_site:
        syscall                   # delivery at TL=1 -> dfbase, bank 1
        # h_df2 checks cause1/epc1, sets epc1=b2_cont, IRETs -> TL=1
b2_cont:
        li r21, STATUS_S
        mtsr status, r21          # TL<-0

        # -- B3: TL-lowering pattern (ISA-SPEC 7.3) --------------------
        #    handler saves bank 0 + status, TL<-0, takes a legitimate
        #    nested fault, restores, IRETs twice
        li r27, 17
        la.abs r21, h_tl
        mtsr vbase, r21
b3_site:
        lds.64 r19, [r24 + SENTINEL_BOX + 1 - FAIL_ADDR]   # outer fault
        # h_tl: nested UNALIGNED handled by h_rec at TL=1, then h_tl
        # restores bank 0 + status and IRETs back here (skipping b3_site)
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_UNALIGNED     # nested fault was recorded
        (!p1) b fail
        li r27, 18
        lds.64 r22, [r24 + TRAP_BADDR_SLOT - FAIL_ADDR]
        cmpeq p1, r22, SENTINEL_BOX + 3    # nested ea, distinct from outer
        (!p1) b fail
        li r27, 19                # outer bank-0 values were restored and
        lds.64 r22, [r24 + TLSAVE_CAUSE - FAIL_ADDR]   # saved correctly
        cmpeq p1, r22, CAUSE_UNALIGNED
        (!p1) b fail
        li r27, 20
        lds.64 r22, [r24 + TLSAVE_EPC - FAIL_ADDR]
        la.abs r20, b3_site
        cmpeq p1, r22, r20
        (!p1) b fail

# ==== phase T: timer interrupt masking, delivery point, WFI ===========

        # -- T1: IE=0 defers the timer ---------------------------------
        li r27, 21
        la.abs r21, h_rec
        mtsr vbase, r21
        li r19, 12345
        st.64 [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR], r19  # sentinel
        li r21, 1
        mtsr timecmp, r21         # cycle >= 1 already: pending, masked
        nop
        nop
        nop
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, r19        # sentinel untouched: nothing delivered
        (!p1) b fail

        # -- T2: enabling IE delivers; epc = next instruction ----------
        li r27, 22
        la.abs r21, h_timer
        mtsr vbase, r21
        li r21, STATUS_S + STATUS_IE
        mtsr status, r21          # IE=1; pending timer delivers at the
t2_next:                          # next boundary; epc = t2_next
        nop                       # h_timer: record, timecmp<-0, IRET
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_TIMER
        (!p1) b fail
        li r27, 23
        lds.64 r22, [r24 + TRAP_EPC_SLOT - FAIL_ADDR]
        la.abs r20, t2_next
        cmpeq p1, r22, r20
        (!p1) b fail
        li r21, STATUS_S          # IE<-0 again for what follows
        mtsr status, r21

        # -- T3: WFI with IE=0: time jumps, execution continues --------
        li r27, 24
        mfsr r19, cycle
        add r20, r19, 200
        mtsr timecmp, r20
        wfi                       # stalls; cycle jumps to >= timecmp;
        mfsr r22, cycle           # IE=0 -> continue at next instruction
        cmpltu p1, r22, r20       # cycle >= timecmp now (exact value is
        (p1) b fail               # SPEC-ISSUES entry 20; only >= asserted)
        li r21, 0
        mtsr timecmp, r21

        # -- T4: WFI with IE=1: delivery, epc = instruction after WFI --
        li r27, 25
        la.abs r21, h_timer
        mtsr vbase, r21
        mfsr r19, cycle
        add r20, r19, 200
        mtsr timecmp, r20
        li r21, STATUS_S + STATUS_IE
        mtsr status, r21          # not yet pending: cycle < timecmp
        wfi                       # stalls, then delivers; epc = t4_next
t4_next:
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_TIMER
        (!p1) b fail
        li r27, 26
        lds.64 r22, [r24 + TRAP_EPC_SLOT - FAIL_ADDR]
        la.abs r20, t4_next
        cmpeq p1, r22, r20
        (!p1) b fail
        li r21, STATUS_S
        mtsr status, r21          # IE<-0

# ==== phase S: predicated-false instructions cannot fault =============
# ISA-SPEC 3.2: no effect, no trap, retires, one cycle each.
# The cycle-delta check doubles as the no-delivery check (a delivery
# would add a cycle). IE=0, timecmp=0: nothing else can interfere.

        li r27, 27
        la.abs r21, h_rec
        mtsr vbase, r21
        li r19, 12345
        st.64 [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR], r19  # sentinel again
        li r21, 7
        cmpeq p2, r21, 8          # p2 = 0 for the squash block
        mfsr r19, cycle
        .quad RAW_ILLEGAL_P2      # (p2) ILLEGAL      — squashed
        (p2) lds.64 r22, [r24 + SENTINEL_BOX + 1 - FAIL_ADDR]  # unaligned
        (p2) st.64 [r24 + SENTINEL_BOX + 1 - FAIL_ADDR], r22   # unaligned
        (p2) syscall              #                   — squashed
        (p2) mtsr cycle, r21      # would be PRIV     — squashed
        mfsr r20, cycle
        sub r21, r20, r19         # 5 squashed + the first mfsr = 6
        cmpeq p1, r21, 6
        (!p1) b fail
        li r27, 28
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        li r19, 12345
        cmpeq p1, r22, r19        # no trap was recorded
        (!p1) b fail

# ==== phase U: user mode and PRIV =====================================

        # -- U1: enter user mode: IRET at TL=0 (saturation) with PS=0 --
        li r27, 29
        la.abs r21, h_user
        mtsr vbase, r21
        li r19, 0
        st.64 [r24 + PRIV_COUNT_SLOT - FAIL_ADDR], r19
        la.abs r21, user_entry
        mtsr epc0, r21
        li r21, STATUS_S          # PS=0, PIE=0, TL=0
        mtsr status, r21
        iret                      # TL stays 0 (saturates); S<-PS=0
user_entry:
        # user mode from here. MMU off: memory fully accessible; only
        # privilege is being tested. h_user counts PRIV traps and skips.
        # Every supervisor-only operation from ISA-SPEC 2.4 + cycle write:
        mfsr r19, status          # PRIV 1 (S-only sreg read)
        mtsr scratch0, r19        # PRIV 2 (S-only sreg write, benign)
        iret                      # PRIV 3
        invtp                     # PRIV 4
        wfi                       # PRIV 5
        halt                      # PRIV 6 (if wrongly executed: loud
                                  #         non-600D HALT line)
        mtsr cycle, r19           # PRIV 7 (cycle write, any mode)
        # user-permitted accesses must NOT trap:
        mfsr r19, cycle           # ok (S+U read)
        mfsr r20, fcsr            # ok
        li r21, 0
        mtsr fcsr, r21            # ok (fcsr is S+U rw)
        # squashed supervisor-only ops cannot fault, in user mode too:
        li r21, 7
        cmpeq p2, r21, 8          # p2 = 0
        (p2) halt
        (p2) iret
        # exactly 7 PRIV traps so far:
        lds.64 r22, [r24 + PRIV_COUNT_SLOT - FAIL_ADDR]
        cmpeq p1, r22, 7
        (!p1) b fail
        li r27, 30
u_sys_site:
        syscall                   # h_user: record epc+status, exit to
        b fail                    # supervisor continuation (not here)
u_cont:
        # -- U2: supervisor again; syscall-from-user bookkeeping -------
        li r27, 31
        lds.64 r22, [r24 + USER_EPC_SLOT - FAIL_ADDR]
        la.abs r20, u_sys_site        # epc = the SYSCALL instruction itself
        cmpeq p1, r22, r20
        (!p1) b fail
        li r27, 32                # status at delivery: S=1, PS=0 (came
        lds.64 r22, [r24 + USER_STATUS_SLOT - FAIL_ADDR]  # from user)
        and r22, r22, STATUS_S + STATUS_PS
        cmpeq p1, r22, STATUS_S
        (!p1) b fail

pass:
        li r0, PASS_MAGIC
        halt
fail:
        st.64 [r24], r27
        mov r0, r27
        halt

# ==== handlers ========================================================

        # record bank-0 fields + status, skip the faulting instruction
h_rec:
        mfsr k0, cause0
        st.64 [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR], k0
        mfsr k0, baddr0
        st.64 [r24 + TRAP_BADDR_SLOT - FAIL_ADDR], k0
        mfsr k0, epc0
        st.64 [r24 + TRAP_EPC_SLOT - FAIL_ADDR], k0
        mfsr k0, status
        st.64 [r24 + TRAP_STATUS_SLOT - FAIL_ADDR], k0
        mfsr k0, epc0
        add k0, k0, 8
        mtsr epc0, k0
        iret

        # timer handler: record cause/epc, disarm, return
h_timer:
        mfsr k0, cause0
        st.64 [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR], k0
        mfsr k0, epc0
        st.64 [r24 + TRAP_EPC_SLOT - FAIL_ADDR], k0
        mtsr timecmp, zero        # disarm: timecmp = 0 never pends
        iret                      # epc unchanged: resume where deferred

        # "bad" handler: faults in its prologue before saving anything.
        # Its first (and only) instruction is the second fault's site.
h_bad:
        .quad RAW_ILLEGAL

        # double-fault handler for B1: verify TL=2, bank 1 = ILLEGAL at
        # h_bad, bank 0 intact with the original UNALIGNED; then IRET
        # via bank 1 back into the main flow.
h_df:
        li r27, 40                # sub-IDs 40..45 pin which check died
        mfsr k0, status
        shr k0, k0, STATUS_TL_LSB
        and k0, k0, 3
        cmpeq p1, k0, 2
        (!p1) b fail
        li r27, 41
        mfsr k0, cause1
        cmpeq p1, k0, CAUSE_ILLEGAL
        (!p1) b fail
        li r27, 42
        mfsr k0, epc1
        la.abs r26, h_bad
        cmpeq p1, k0, r26
        (!p1) b fail
        li r27, 43
        mfsr k0, cause0           # bank 0 untouched by the double fault
        cmpeq p1, k0, CAUSE_UNALIGNED
        (!p1) b fail
        li r27, 44
        mfsr k0, baddr0
        cmpeq p1, k0, SENTINEL_BOX + 1
        (!p1) b fail
        li r27, 45
        mfsr k0, epc0
        la.abs r26, b1_site
        cmpeq p1, k0, r26
        (!p1) b fail
        la.abs r26, b1_cont
        mtsr epc1, r26            # IRET at TL=2 must use bank 1
        iret

        # double-fault handler for B2: SYSCALL delivered at TL=1
h_df2:
        li r27, 46
        mfsr k0, cause1
        cmpeq p1, k0, CAUSE_SYSCALL
        (!p1) b fail
        li r27, 47
        mfsr k0, epc1
        la.abs r26, b2_site
        cmpeq p1, k0, r26
        (!p1) b fail
        la.abs r26, b2_cont
        mtsr epc1, r26
        iret

        # TL-lowering handler (ISA-SPEC 7.3): save bank 0 + status,
        # TL<-0, deliberately fault (handled by h_rec), restore, IRET.
h_tl:
        mfsr k0, epc0
        st.64 [r24 + TLSAVE_EPC - FAIL_ADDR], k0
        mfsr k0, cause0
        st.64 [r24 + TLSAVE_CAUSE - FAIL_ADDR], k0
        mfsr k0, baddr0
        st.64 [r24 + TLSAVE_BADDR - FAIL_ADDR], k0
        mfsr k0, status
        st.64 [r24 + TLSAVE_STATUS - FAIL_ADDR], k0
        la.abs k0, h_rec
        mtsr vbase, k0
        li k0, STATUS_S           # TL<-0 by software consent
        mtsr status, k0
        lds.64 k0, [r24 + SENTINEL_BOX + 3 - FAIL_ADDR]  # legitimate
        # nested fault (ea 0x71b), delivered normally to h_rec, which
        # skips it and IRETs back here at TL=0
        lds.64 k0, [r24 + TLSAVE_STATUS - FAIL_ADDR]
        mtsr status, k0           # back to TL=1
        lds.64 k0, [r24 + TLSAVE_CAUSE - FAIL_ADDR]
        mtsr cause0, k0
        lds.64 k0, [r24 + TLSAVE_BADDR - FAIL_ADDR]
        mtsr baddr0, k0
        lds.64 k0, [r24 + TLSAVE_EPC - FAIL_ADDR]
        add k0, k0, 8             # skip the outer faulting instruction
        mtsr epc0, k0
        iret

        # user-phase handler: count PRIV, skip; on SYSCALL exit to
        # supervisor continuation. Anything else: fail loudly.
h_user:
        mfsr k0, cause0
        cmpeq p1, k0, CAUSE_SYSCALL
        (p1) b h_user_sys
        cmpeq p1, k0, CAUSE_PRIV
        (!p1) b fail
        li r26, PRIV_COUNT_SLOT
        lds.64 k0, [r26]
        add k0, k0, 1
        st.64 [r26], k0
        mfsr k0, epc0
        add k0, k0, 8
        mtsr epc0, k0
        iret
h_user_sys:
        mfsr k0, epc0
        st.64 [r24 + USER_EPC_SLOT - FAIL_ADDR], k0
        mfsr k0, status
        st.64 [r24 + USER_STATUS_SLOT - FAIL_ADDR], k0
        li k0, STATUS_S           # supervisor, TL=0, IE=0
        mtsr status, k0
        b u_cont
