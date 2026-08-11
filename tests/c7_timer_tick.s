# c7_timer_tick — devspec/timer.md TMR-02/03/05/06/08/16/17: the
# periodic tick end to end. Arm N=100 at a guest-computed W (the COUNT
# read returns its own cycle, so the very-next-instruction arming store
# has W = COUNT+1 — timer.md 4.1/4.2); the EXTINT handler stores COUNT
# to TMR_TICK_SLOT and ACKs, so every fire's cycle is observable as
# F+1 in RAM and in the trace.
#
# Six fires: 1-3 on time at exactly W+100m (handler latency 8 cycles,
# ACK k=1); fire 4 after an IE-masked gap of >2 periods — ONE delivery
# for the whole gap (TMR-17), landing right after IE re-enables; fire 5
# back on the W+100m grid, proving ACK's k>1 collapse is phase-locked
# and drift-free (TMR-08; the guest recomputes the grid point with
# udiv from A4 = tick4+5, mirroring h_ext's ACK position); fire 6 after
# an arm-1000-then-rewrite-40 pair, proving rewrite re-arms fresh from
# the new W (TMR-06). Expectations are pure cycle arithmetic from
# timer.md — 1 cycle per retired instruction, 1 per delivery — never
# from an emulator run. checks/c7_timer_tick.py re-derives the same
# grid from the trace's DEVW stamps (level=2 in MANIFEST: it reads the
# COUNT MEMRs).
#
# Register use per tests/README.md: r24 FAIL_ADDR, r27 test ID,
# r19-r23 scratch, r25 timer base, r16-r18 W/x/tick4, k0 handler-only.
# The handler is predicate-free: a delivery can land between any cmpeq
# and its consuming branch in the main flow.

        .org 0x1000
start:
        li r24, FAIL_ADDR
        la.abs r21, h_ext
        mtsr vbase, r21
        li r25, DEV_TIMER_BASE
        li r23, 1                 # ACK value / count increment
        li r20, 100               # N
        st.64 [r24 + TIMER_COUNT_SLOT - FAIL_ADDR], zero
        st.64 [r24 + TMR_TICK_SLOT - FAIL_ADDR], zero
        li r21, STATUS_S + STATUS_IE
        mtsr status, r21          # interrupts on

        # -- 0: TMR-02 equivalence: COUNT is the same counter MFSR
        # sreg-8 reads — adjacent reads differ by exactly the 1-cycle
        # delta between the two instructions (timer.md 4.1)
        li r27, 0
        mfsr r19, cycle           # x (= this insn's cycle)
        lds.64 r22, [r25]         # COUNT at x+1
        sub.64 r22, r22, r19
        cmpeq p1, r22, 1
        (!p1) b fail

        # -- 1: arm N=100; W = COUNT + 1 (arming store is the very
        # next instruction after the COUNT load); PERIOD reads back
        li r27, 1
        lds.64 r16, [r25]         # COUNT -> c (= this load's cycle)
        st.64 [r25 + 8], r20      # arm: W = c+1, next_fire = W+100
        add r16, r16, 1           # r16 = W
        lds.64 r19, [r25 + 8]
        cmpeq p1, r19, 100        # TMR-05: last-written readback
        (!p1) b fail

        # -- 2..4: three on-time fires; handler's COUNT store must
        # read exactly W+100m+1 (delivery at W+100m, COUNT load is the
        # first handler instruction)
        li r27, 2
w1:
        lds.64 r22, [r24 + TIMER_COUNT_SLOT - FAIL_ADDR]
        cmpeq p1, r22, 1
        (!p1) b w1
        lds.64 r22, [r24 + TMR_TICK_SLOT - FAIL_ADDR]
        add r19, r16, 101
        cmpeq p1, r22, r19
        (!p1) b fail
        li r27, 3
w2:
        lds.64 r22, [r24 + TIMER_COUNT_SLOT - FAIL_ADDR]
        cmpeq p1, r22, 2
        (!p1) b w2
        lds.64 r22, [r24 + TMR_TICK_SLOT - FAIL_ADDR]
        add r19, r16, 201
        cmpeq p1, r22, r19
        (!p1) b fail
        li r27, 4
w3:
        lds.64 r22, [r24 + TIMER_COUNT_SLOT - FAIL_ADDR]
        cmpeq p1, r22, 3
        (!p1) b w3
        lds.64 r22, [r24 + TMR_TICK_SLOT - FAIL_ADDR]
        add r19, r16, 301
        cmpeq p1, r22, r19
        (!p1) b fail

        # -- 5: mask IE, let >2 periods elapse (fires 4 and 5 of the
        # grid go by), unmask: the level delivers exactly ONCE, at the
        # first boundary after the IE-setting mtsr (x = COUNT read
        # right before it, so F4 = x+2 and tick4 = x+3)
        li r27, 5
        li r21, STATUS_S
        mtsr status, r21          # IE off; pending holds level-high
        li r19, 80
burn:
        sub.64 r19, r19, 1
        cmpeq p1, r19, zero
        (!p1) b burn              # ~240 cycles: well past W+400
        li r21, STATUS_S + STATUS_IE
        lds.64 r17, [r25]         # x (= this load's cycle)
        mtsr status, r21          # IE on at x+1; delivery at x+2
w4:
        lds.64 r22, [r24 + TIMER_COUNT_SLOT - FAIL_ADDR]
        cmpeq p1, r22, 4
        (!p1) b w4
        add r19, r16, 400
        cmpltu p1, r17, r19       # vacuity guard: x must be >= W+400
        (p1) b fail
        li r27, 6
        lds.64 r18, [r24 + TMR_TICK_SLOT - FAIL_ADDR]
        add r19, r17, 3
        cmpeq p1, r18, r19        # tick4 = x+3: one late delivery
        (!p1) b fail

        # -- 7: fire 5 lands back on the W+100m grid: the late ACK at
        # A4 = tick4+5 collapsed k>1 periods to the first grid point
        # past A4 (TMR-08); recompute it exactly
        li r27, 7
        add r19, r18, 5           # A4 (ACK is 5 insns after COUNT in h_ext)
        sub.64 r19, r19, r16      # A4 - W
        udiv.64 r19, r19, r20     # (A4 - W) / 100
        add r19, r19, 1           # m5
        mul.64 r19, r19, r20
        add r19, r19, r16         # F5 = W + 100*m5
        add r18, r19, 1           # expected tick5
w5:
        lds.64 r22, [r24 + TIMER_COUNT_SLOT - FAIL_ADDR]
        cmpeq p1, r22, 5
        (!p1) b w5
        lds.64 r22, [r24 + TMR_TICK_SLOT - FAIL_ADDR]
        cmpeq p1, r22, r18
        (!p1) b fail

        # -- 8: disarm: pending drops with no ACK handshake (TMR-04),
        # PERIOD reads 0
        li r27, 8
        st.64 [r25 + 8], zero
        lds.64 r19, [r25 + 0x10]
        cmpeq p1, r19, zero
        (!p1) b fail
        lds.64 r19, [r25 + 8]
        cmpeq p1, r19, zero
        (!p1) b fail

        # -- 9: rewrite-while-armed re-arms fresh (TMR-06): arm 1000,
        # rewrite 40 on the very next instruction; the fire comes at
        # W3+40 (tick6 = c2+43), nowhere near W2+1000
        li r27, 9
        li r21, 1000
        li r22, 40
        lds.64 r17, [r25]         # c2 (= this load's cycle)
        st.64 [r25 + 8], r21      # W2 = c2+1
        st.64 [r25 + 8], r22      # W3 = c2+2 -> next_fire = c2+42
        add r17, r17, 43          # expected tick6
w6:
        lds.64 r22, [r24 + TIMER_COUNT_SLOT - FAIL_ADDR]
        cmpeq p1, r22, 6
        (!p1) b w6
        lds.64 r22, [r24 + TMR_TICK_SLOT - FAIL_ADDR]
        cmpeq p1, r22, r17
        (!p1) b fail
        st.64 [r25 + 8], zero     # disarm before the W3+80 grid point

        # -- 10: no straggler delivery after the disarm
        li r27, 10
        li r19, 40
settle:
        sub.64 r19, r19, 1
        cmpeq p1, r19, zero
        (!p1) b settle
        lds.64 r22, [r24 + TIMER_COUNT_SLOT - FAIL_ADDR]
        cmpeq p1, r22, 6
        (!p1) b fail

pass:
        li r0, PASS_MAGIC
        halt
fail:
        st.64 [r24], r27
        mov r0, r27
        halt

# ==== handler =========================================================
# PREDICATE-FREE on purpose (see header). Fixed shape the main flow's
# arithmetic mirrors: COUNT load first (value F+1), ACK 5 instructions
# later (A = F+6) — change the offsets in tests 6/7 if this changes.
h_ext:
        lds.64 k0, [r25]                                  # F+1
        st.64 [r24 + TMR_TICK_SLOT - FAIL_ADDR], k0       # F+2
        lds.64 k0, [r24 + TIMER_COUNT_SLOT - FAIL_ADDR]   # F+3
        add k0, k0, 1                                     # F+4
        st.64 [r24 + TIMER_COUNT_SLOT - FAIL_ADDR], k0    # F+5
        st.64 [r25 + 0x18], r23                           # ACK at F+6
        iret
