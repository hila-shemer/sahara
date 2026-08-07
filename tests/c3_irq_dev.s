# c3_irq_dev — CONFORMANCE.md group C3, the two bullets that needed
# scaffolding c3_atomics.s does not have: atomicity under interrupts
# (timer armed to land near an AMO; the trace must never show a
# delivery between the AMO's read and its write — checks/c3_irq_dev.sh
# asserts it from the level-2 trace, which is why this test carries
# level=2 in MANIFEST) and AMO/CAS to device address space trapping
# DEVERR (ISA-SPEC 5.4/9.2; window addresses from PLATFORM-SPEC 1 via
# defs.s — the trap is the core's address-classification seam and needs
# no device internals, so it is NOT devspec-gated).
#
# Phase 1 arms timecmp at eight offsets (cycle+2 .. cycle+9) and runs a
# burst of four back-to-back amoadd.64 each time, so deliveries land at
# swept points around the bursts; the handler counts and disarms, the
# main flow spins until the count arrives (a lost delivery is a loud
# MAXCYCLES). checks/c3_irq_dev.sh then asserts, from the trace: 32
# paired MEMR/MEMW at ATOMIC_BOX with nothing foreign-cycled between
# them, exactly 8 TIMER deliveries, at least 2 of them inside the AMO
# span (non-vacuity), and zero accesses in device space (the DEVERR'd
# atomics of phase 2 must leave no footprint — SPEC-ISSUES 17).
#
# Bounded coverage: successful device-register accesses (reads/writes
# that do NOT trap) are devspec-gated and live with C7's device-order
# work; here only the always-trapping cases appear.
#
# Register use per tests/README.md: r24 FAIL_ADDR, r27 test ID,
# r19-r23 scratch, r25 box pointer, r26+k0 handler-only. The timer
# handler is predicate-free: delivery can land between a cmpeq and its
# consuming branch, so the handler must not touch any predicate.

        .org 0x1000
start:
        li r24, FAIL_ADDR
        li r21, h_timer
        mtsr vbase, r21
        li r25, ATOMIC_BOX
        st128 [r25], zero
        st.64 [r24 + TIMER_COUNT_SLOT - FAIL_ADDR], zero
        st.64 [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR], zero
        li r23, 1                 # AMO addend
        li r21, STATUS_S + STATUS_IE
        mtsr status, r21          # interrupts on

# ==== phase 1: eight arm-burst-spin iterations ========================
# Each: arm timecmp = cycle + d, run 4 amoadds, spin until the handler
# has counted the delivery, check the recorded cause. d sweeps 2..9 so
# the delivery point walks across the burst.

        # -- iteration 1 (d=2) --
        li r27, 1
        mfsr r19, cycle
        add r19, r19, 2
        mtsr timecmp, r19
        amoadd.64 r20, [r25], r23
        amoadd.64 r20, [r25], r23
        amoadd.64 r20, [r25], r23
        amoadd.64 r20, [r25], r23
w1:
        lds.64 r22, [r24 + TIMER_COUNT_SLOT - FAIL_ADDR]
        cmpeq p1, r22, 1
        (!p1) b w1
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_TIMER
        (!p1) b fail

        # -- iteration 2 (d=3) --
        li r27, 2
        mfsr r19, cycle
        add r19, r19, 3
        mtsr timecmp, r19
        amoadd.64 r20, [r25], r23
        amoadd.64 r20, [r25], r23
        amoadd.64 r20, [r25], r23
        amoadd.64 r20, [r25], r23
w2:
        lds.64 r22, [r24 + TIMER_COUNT_SLOT - FAIL_ADDR]
        cmpeq p1, r22, 2
        (!p1) b w2
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_TIMER
        (!p1) b fail

        # -- iteration 3 (d=4) --
        li r27, 3
        mfsr r19, cycle
        add r19, r19, 4
        mtsr timecmp, r19
        amoadd.64 r20, [r25], r23
        amoadd.64 r20, [r25], r23
        amoadd.64 r20, [r25], r23
        amoadd.64 r20, [r25], r23
w3:
        lds.64 r22, [r24 + TIMER_COUNT_SLOT - FAIL_ADDR]
        cmpeq p1, r22, 3
        (!p1) b w3
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_TIMER
        (!p1) b fail

        # -- iteration 4 (d=5) --
        li r27, 4
        mfsr r19, cycle
        add r19, r19, 5
        mtsr timecmp, r19
        amoadd.64 r20, [r25], r23
        amoadd.64 r20, [r25], r23
        amoadd.64 r20, [r25], r23
        amoadd.64 r20, [r25], r23
w4:
        lds.64 r22, [r24 + TIMER_COUNT_SLOT - FAIL_ADDR]
        cmpeq p1, r22, 4
        (!p1) b w4
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_TIMER
        (!p1) b fail

        # -- iteration 5 (d=6) --
        li r27, 5
        mfsr r19, cycle
        add r19, r19, 6
        mtsr timecmp, r19
        amoadd.64 r20, [r25], r23
        amoadd.64 r20, [r25], r23
        amoadd.64 r20, [r25], r23
        amoadd.64 r20, [r25], r23
w5:
        lds.64 r22, [r24 + TIMER_COUNT_SLOT - FAIL_ADDR]
        cmpeq p1, r22, 5
        (!p1) b w5
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_TIMER
        (!p1) b fail

        # -- iteration 6 (d=7) --
        li r27, 6
        mfsr r19, cycle
        add r19, r19, 7
        mtsr timecmp, r19
        amoadd.64 r20, [r25], r23
        amoadd.64 r20, [r25], r23
        amoadd.64 r20, [r25], r23
        amoadd.64 r20, [r25], r23
w6:
        lds.64 r22, [r24 + TIMER_COUNT_SLOT - FAIL_ADDR]
        cmpeq p1, r22, 6
        (!p1) b w6
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_TIMER
        (!p1) b fail

        # -- iteration 7 (d=8) --
        li r27, 7
        mfsr r19, cycle
        add r19, r19, 8
        mtsr timecmp, r19
        amoadd.64 r20, [r25], r23
        amoadd.64 r20, [r25], r23
        amoadd.64 r20, [r25], r23
        amoadd.64 r20, [r25], r23
w7:
        lds.64 r22, [r24 + TIMER_COUNT_SLOT - FAIL_ADDR]
        cmpeq p1, r22, 7
        (!p1) b w7
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_TIMER
        (!p1) b fail

        # -- iteration 8 (d=9) --
        li r27, 8
        mfsr r19, cycle
        add r19, r19, 9
        mtsr timecmp, r19
        amoadd.64 r20, [r25], r23
        amoadd.64 r20, [r25], r23
        amoadd.64 r20, [r25], r23
        amoadd.64 r20, [r25], r23
w8:
        lds.64 r22, [r24 + TIMER_COUNT_SLOT - FAIL_ADDR]
        cmpeq p1, r22, 8
        (!p1) b w8
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_TIMER
        (!p1) b fail

        # -- 9: every add landed exactly once: box = 8 bursts * 4 -----
        li r27, 9
        lds.64 r22, [r25]         # the check's one expected unpaired
        cmpeq p1, r22, 32         # MEMR at ATOMIC_BOX
        (!p1) b fail

# ==== phase 2: atomics to device space trap DEVERR ====================
# IE stays on but timecmp is 0 (disarmed by the 8th delivery); the
# recording handler pattern from c1 takes over. Each faulting atomic is
# skipped (epc+8) and must leave dst untouched and no MEM record.

        li r21, h_rec
        mtsr vbase, r21

        # -- 10: amoadd.32 on a device register: cause --------------
        li r27, 10
        li r21, DEV_KBD_BASE
        li r20, 0x5AFE            # dst sentinel: must survive the trap
c3d_site:
        amoadd.32 r20, [r21], r23
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_DEVERR
        (!p1) b fail
        li r27, 11                # baddr = ea
        lds.64 r22, [r24 + TRAP_BADDR_SLOT - FAIL_ADDR]
        cmpeq p1, r22, r21
        (!p1) b fail
        li r27, 12                # epc = the atomic itself
        lds.64 r22, [r24 + TRAP_EPC_SLOT - FAIL_ADDR]
        li r19, c3d_site
        cmpeq p1, r22, r19
        (!p1) b fail
        li r27, 13                # dst not written by a faulting AMO
        cmpeq p1, r20, 0x5AFE
        (!p1) b fail

        # -- 14: amoadd.64, offset ea inside the window ---------------
        li r27, 14
        amoadd.64 r20, [r21 + 8], r23
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_DEVERR
        (!p1) b fail
        li r27, 15
        lds.64 r22, [r24 + TRAP_BADDR_SLOT - FAIL_ADDR]
        add r19, r21, 8
        cmpeq p1, r22, r19
        (!p1) b fail

        # -- 16: width-128 AMO (16-aligned so DEVERR, not UNALIGNED) --
        li r27, 16
        amoswap r20, [r21 + 16], r23
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_DEVERR
        (!p1) b fail

        # -- 17: CAS at 64 and 128 ------------------------------------
        li r27, 17
        cas.64 r20, [r21], r22, r23
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_DEVERR
        (!p1) b fail
        li r27, 18
        cas r20, [r21], r22, r23
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_DEVERR
        (!p1) b fail

        # -- 19: the display pixel buffer is device space too ---------
        # ("behave as memory" for size/side effects, but still device
        # space in the ISA 9.2 sense — atomics must trap)
        li r27, 19
        li r21, 0x10000000        # pixel buffer PA (PLATFORM-SPEC 1)
        amoadd.64 r20, [r21], r23
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_DEVERR
        (!p1) b fail

        # -- 20: display control window -------------------------------
        li r27, 20
        li r21, DEV_DISPLAY_BASE
        amomax.64 r20, [r21], r23
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_DEVERR
        (!p1) b fail

pass:
        li r0, PASS_MAGIC
        halt
fail:
        st.64 [r24], r27
        mov r0, r27
        halt

# ==== handlers ========================================================

        # timer: count + disarm + resume. PREDICATE-FREE on purpose: a
        # delivery can land between any cmpeq and its consuming branch
        # in the main flow, so touching p1 here would corrupt the
        # interrupted computation. The cause goes to TRAP_CAUSE_SLOT
        # for the main flow to check after the spin.
h_timer:
        mfsr k0, cause0
        li r26, TRAP_CAUSE_SLOT
        st.64 [r26], k0
        li r26, TIMER_COUNT_SLOT
        lds.64 k0, [r26]
        add k0, k0, 1
        st.64 [r26], k0
        mtsr timecmp, zero        # disarm: 0 never pends
        iret                      # epc untouched: resume where deferred

        # record cause/baddr/epc/status, skip the faulting instruction
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
