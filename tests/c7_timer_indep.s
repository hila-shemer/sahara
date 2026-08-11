# c7_timer_indep — devspec/timer.md TMR-19: sreg timecmp (cause 0,
# TIMER) and the device timer (cause 1, EXTINT) are independent
# compare sources over the same counter, with ISA 7.5's fixed priority
# when both become pending at the same boundary.
#
# Both are armed for the same cycle T: timecmp = T directly, and the
# device with N = T - W where W is the arming store's cycle (counted
# by hand from the COUNT read: lds at c, so the store 5 instructions
# later has W = c+5 and N = 32-5 = 27; T = c+32). At T the TIMER
# delivers FIRST; its handler records the cause, snapshots the
# device's STATUS (still 1 — draining the sreg side leaves the device
# pending), disarms ONLY timecmp, and re-vectors to h_second; the
# EXTINT then delivers at the boundary after the IRET, records its
# cause, and disarms the device. Handler chaining by re-vectoring
# keeps both handlers predicate-free and branch-free.
#
# checks/c7_timer_indep.py re-derives T = W + N from the arming DEVW
# and pins: TIMER TRAP at exactly T, EXTINT strictly after it, one of
# each. Register use per tests/README.md: r24 FAIL_ADDR, r27 test ID,
# r19-r23 scratch, r25 timer base, r26 = h_second address (preloaded
# for the handler), k0 handler-only.

        .org 0x1000
start:
        li r24, FAIL_ADDR
        li r25, DEV_TIMER_BASE
        li r23, 1
        la.abs r21, h_first
        mtsr vbase, r21
        la.abs r26, h_second
        st.64 [r24 + TIMER_COUNT_SLOT - FAIL_ADDR], zero
        li r21, STATUS_S + STATUS_IE
        mtsr status, r21          # IE on; nothing pending yet

        # -- 1: arm BOTH compare sources for the same boundary T=c+32.
        # Instruction count from the COUNT load is load-bearing: the
        # arming store executes at c+5, so N = 32 - 5 keeps
        # next_fire = W + N = c + 32 = timecmp exactly.
        li r27, 1
        lds.64 r19, [r25]         # c (= this load's cycle)
        add r20, r19, 32          # T            @ c+1
        sub.64 r21, r20, r19      # 32           @ c+2
        sub.64 r21, r21, 5        # N = 27       @ c+3
        mtsr timecmp, r20         #              @ c+4
        st.64 [r25 + 8], r21      # W = c+5 -> next_fire = T
w1:
        lds.64 r22, [r24 + TIMER_COUNT_SLOT - FAIL_ADDR]
        cmpeq p1, r22, 2
        (!p1) b w1

        # -- 2: TIMER (cause 0) delivered first (ISA 7.5 priority)
        li r27, 2
        lds.64 r22, [r24 + TMR_TICK_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_TIMER
        (!p1) b fail
        # -- 3: the device was STILL pending inside the TIMER handler:
        # draining one source leaves the other (TMR-19)
        li r27, 3
        lds.64 r22, [r24 + TMR_W_SLOT - FAIL_ADDR]
        cmpeq p1, r22, 1
        (!p1) b fail
        # -- 4: EXTINT (cause 1) delivered second
        li r27, 4
        lds.64 r22, [r24 + TMR_AUX_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_EXTINT
        (!p1) b fail
        # -- 5: both sides drained by their own mechanism only
        li r27, 5
        lds.64 r19, [r25 + 0x10]
        cmpeq p1, r19, zero
        (!p1) b fail
        mfsr r19, timecmp
        cmpeq p1, r19, zero
        (!p1) b fail
        lds.64 r19, [r25 + 8]
        cmpeq p1, r19, zero
        (!p1) b fail

pass:
        li r0, PASS_MAGIC
        halt
fail:
        st.64 [r24], r27
        mov r0, r27
        halt

# ==== handlers =======================================================
# Both predicate-free and branch-free; chaining is by re-vectoring.

h_first:                          # the simultaneous boundary: TIMER
        mfsr k0, cause0
        st.64 [r24 + TMR_TICK_SLOT - FAIL_ADDR], k0
        lds.64 k0, [r25 + 0x10]   # device STATUS: must still be 1
        st.64 [r24 + TMR_W_SLOT - FAIL_ADDR], k0
        mtsr timecmp, zero        # drain ONLY the sreg timer
        lds.64 k0, [r24 + TIMER_COUNT_SLOT - FAIL_ADDR]
        add k0, k0, 1
        st.64 [r24 + TIMER_COUNT_SLOT - FAIL_ADDR], k0
        mtsr vbase, r26           # next delivery -> h_second
        iret                      # EXTINT still pending: delivers next

h_second:                         # the surviving level: EXTINT
        mfsr k0, cause0
        st.64 [r24 + TMR_AUX_SLOT - FAIL_ADDR], k0
        st.64 [r25 + 8], zero     # disarm the device: pending drops
        lds.64 k0, [r24 + TIMER_COUNT_SLOT - FAIL_ADDR]
        add k0, k0, 1
        st.64 [r24 + TIMER_COUNT_SLOT - FAIL_ADDR], k0
        iret
