# c7_timer_wfi — devspec/timer.md TMR-18 (WFI wakes at exactly
# next_fire) and TMR-16 (level re-trap without ACK before IRET).
#
# Phase A runs with IE=0 so the wake cycles are naked in the EXEC
# stream: arm N=50 at a guest-computed W (COUNT+1 trick, timer.md
# 4.1), WFI, and the first post-WFI COUNT read must return exactly
# W+50 — the event-style landing rule, NOT timecmp's T+1 (timer.md
# 4.5; the frozen ISA 7.6 "advances directly to the next cycle at
# which one becomes pending"). ACK (k=1) and a second WFI pin W+100:
# two consecutive periods, zero drift. Expectations are hand-derived
# cycle arithmetic; checks/c7_timer_wfi.py re-derives them from the
# trace's DEVW stamp of the arming store (level=2: it reads the COUNT
# MEMRs).
#
# Phase B: consume the held level, enable IE, and take the next fire
# with a handler that IRETs once WITHOUT acking — the level must
# re-deliver at the boundary after the IRET; the second entry ACKs
# and disarms. Delivery count lands on exactly 2.
#
# Register use per tests/README.md: r24 FAIL_ADDR, r27 test ID,
# r19-r23 scratch, r25 timer base, r16 = W, r26+k0 handler-only. The
# handler touches only p2; the main flow spins on p1.

        .org 0x1000
start:
        li r24, FAIL_ADDR
        la.abs r21, h_lvl
        mtsr vbase, r21
        li r25, DEV_TIMER_BASE
        li r23, 1
        li r20, 50                # N
        st.64 [r24 + TIMER_COUNT_SLOT - FAIL_ADDR], zero

        # -- 1: arm N=50; WFI (IE=0); wake lands at exactly next_fire
        li r27, 1
        lds.64 r16, [r25]         # COUNT -> c (= this load's cycle)
        st.64 [r25 + 8], r20      # arm: W = c+1, next_fire = W+50
        add r16, r16, 1           # r16 = W
        wfi                       # at c+3 < W+50: stalls
        lds.64 r19, [r25]         # first post-WFI insn: cycle W+50
        add r22, r16, 50
        cmpeq p1, r19, r22
        (!p1) b fail
        # -- 2: the level held across the wake (IE=0 defers delivery)
        li r27, 2
        lds.64 r19, [r25 + 0x10]
        cmpeq p1, r19, 1
        (!p1) b fail
        # -- 3: ACK (k=1 -> next grid point W+100); second WFI period
        li r27, 3
        st.64 [r25 + 0x18], r23   # A = W+59 < W+100: k = 1
        wfi
        lds.64 r19, [r25]         # wakes at exactly W+100
        add r22, r16, 100
        cmpeq p1, r19, r22
        (!p1) b fail

        # -- 4: re-trap without ACK before IRET (TMR-16): drain the
        # held level, then take fire 3 (W+150) with IE=1. h_lvl's
        # first entry IRETs without acking -> immediate re-delivery;
        # its second entry ACKs and disarms. Count must reach exactly 2.
        li r27, 4
        st.64 [r25 + 0x18], r23   # ack fire 2: next_fire = W+150
        li r21, STATUS_S + STATUS_IE
        mtsr status, r21
w1:
        lds.64 r22, [r24 + TIMER_COUNT_SLOT - FAIL_ADDR]
        cmpeq p1, r22, 2
        (!p1) b w1
        # -- 5: drained and disarmed; no straggler delivery
        li r27, 5
        lds.64 r19, [r25 + 0x10]
        cmpeq p1, r19, zero
        (!p1) b fail
        lds.64 r19, [r25 + 8]
        cmpeq p1, r19, zero
        (!p1) b fail
        li r19, 30
settle:
        sub.64 r19, r19, 1
        cmpeq p1, r19, zero
        (!p1) b settle
        lds.64 r22, [r24 + TIMER_COUNT_SLOT - FAIL_ADDR]
        cmpeq p1, r22, 2
        (!p1) b fail

pass:
        li r0, PASS_MAGIC
        halt
fail:
        st.64 [r24], r27
        mov r0, r27
        halt

# ==== handler ========================================================
# Level handler, 7 instructions to its first-entry IRET — the checker
# pins the re-trap at first-TRAP-cycle + 7 (change together). Touches
# only p2 and k0/r26; first entry (count 1) returns WITHOUT ack, the
# re-delivery's entry (count 2) ACKs and disarms.
h_lvl:
        li r26, TIMER_COUNT_SLOT
        lds.64 k0, [r26]
        add k0, k0, 1
        st.64 [r26], k0
        cmpeq p2, k0, 1
        (p2) iret                 # no ACK: the level re-traps
        st.64 [r25 + 0x18], r23   # ACK
        st.64 [r25 + 8], zero     # disarm
        iret
