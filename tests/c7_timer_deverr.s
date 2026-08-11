# c7_timer_deverr — devspec/timer.md TMR-10..15: the full E1-E5 fault
# matrix, the UNALIGNED-precedence case, and a predicated-false
# squashed access. IE stays 0 throughout (faults deliver regardless,
# ISA 7.5); the recording handler h_rec (the c1 pattern) stores
# cause/baddr/epc and skips. After each fault the guest re-reads
# STATUS and PERIOD to pin the no-effect rule (ISA 4: a faulting
# access changes no device state).
#
# Exact trap census, mirrored by checks/c7_timer_deverr.py (change
# together): 18 DEVERR (3x E2, 3x E1, 5x E3, 3x E4, 3x E5-disarmed,
# 1x E5-while-pending) + 2 UNALIGNED. The squashed access at the end
# contributes nothing to the census and no record to the trace — that
# absence, under an exact census, IS the TMR-15 squash check.
#
# Register use per tests/README.md: r24 FAIL_ADDR, r27 test ID,
# r19-r23 scratch, r25 timer base, r26+k0 handler-only.

        .org 0x1000
start:
        li r24, FAIL_ADDR
        la.abs r21, h_rec
        mtsr vbase, r21
        li r25, DEV_TIMER_BASE
        li r23, 1

# ==== E2: wrong direction on listed offsets ==========================
        # -- 1: load from ACK (write-only)
        li r27, 1
        lds.64 r19, [r25 + 0x18]
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_DEVERR
        (!p1) b fail
        li r27, 2                 # baddr = ea
        lds.64 r22, [r24 + TRAP_BADDR_SLOT - FAIL_ADDR]
        add r19, r25, 0x18
        cmpeq p1, r22, r19
        (!p1) b fail
        # -- 3: store to COUNT (read-only)
        li r27, 3
        st.64 [r25], r23
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_DEVERR
        (!p1) b fail
        # -- 4: store to STATUS (read-only)
        li r27, 4
        st.64 [r25 + 0x10], zero
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_DEVERR
        (!p1) b fail

# ==== E1: unlisted offsets (no read-0 window here, timer.md 6) =======
        # -- 5: load 0x20; -- 6: store 0x20; -- 7: load 0xFFF8
        li r27, 5
        lds.64 r19, [r25 + 0x20]
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_DEVERR
        (!p1) b fail
        li r27, 6
        st.64 [r25 + 0x20], r23
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_DEVERR
        (!p1) b fail
        li r27, 7
        lds.64 r19, [r25 + 0xFFF8]
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_DEVERR
        (!p1) b fail
        li r27, 8                 # baddr for the top-of-window case
        lds.64 r22, [r24 + TRAP_BADDR_SLOT - FAIL_ADDR]
        add r19, r25, 0xFFF8
        cmpeq p1, r22, r19
        (!p1) b fail

# ==== E3: size != 8, aligned (so DEVERR, not UNALIGNED) ==============
        # -- 9..13: 4/2/1/16-byte loads at COUNT, 4-byte store to PERIOD
        li r27, 9
        lds.32 r19, [r25]
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_DEVERR
        (!p1) b fail
        li r27, 10
        lds.16 r19, [r25]
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_DEVERR
        (!p1) b fail
        li r27, 11
        lds.8 r19, [r25]
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_DEVERR
        (!p1) b fail
        li r27, 12
        ld128 r19, [r25]          # base is 64 KB-aligned: 16-aligned
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_DEVERR
        (!p1) b fail
        li r27, 13
        st.32 [r25 + 8], r23
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_DEVERR
        (!p1) b fail

# ==== UNALIGNED outranks every DEVERR class (timer.md 2.2) ===========
        # -- 14: misaligned 8-byte; -- 15: misaligned 2-byte
        li r27, 14
        lds.64 r19, [r25 + 4]
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_UNALIGNED
        (!p1) b fail
        lds.64 r22, [r24 + TRAP_BADDR_SLOT - FAIL_ADDR]
        add r19, r25, 4
        cmpeq p1, r22, r19
        (!p1) b fail
        li r27, 15
        lds.16 r19, [r25 + 1]
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_UNALIGNED
        (!p1) b fail

# ==== E4: atomics anywhere in the window =============================
        # -- 16..18: amoadd.64, cas.64, width-128 amoswap (16-aligned)
        li r27, 16
        amoadd.64 r19, [r25], r23
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_DEVERR
        (!p1) b fail
        li r27, 17
        cas.64 r19, [r25 + 8], r22, r23
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_DEVERR
        (!p1) b fail
        li r27, 18
        amoswap r19, [r25 + 16], r23
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_DEVERR
        (!p1) b fail

# ==== E5: ACK value != 1, disarmed (state stays reset) ===============
        # -- 19..21: values 0, 2, and a high-bit pattern
        li r27, 19
        st.64 [r25 + 0x18], zero
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_DEVERR
        (!p1) b fail
        li r27, 20
        li r22, 2
        st.64 [r25 + 0x18], r22
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_DEVERR
        (!p1) b fail
        li r27, 21
        li r22, 0x8000000000000001
        st.64 [r25 + 0x18], r22
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_DEVERR
        (!p1) b fail
        # -- 22: all that faulting left the device in reset state
        li r27, 22
        lds.64 r19, [r25 + 8]
        cmpeq p1, r19, zero
        (!p1) b fail
        lds.64 r19, [r25 + 0x10]
        cmpeq p1, r19, zero
        (!p1) b fail

# ==== E5 while pending: DEVERR'd ACK changes no state ================
        # -- 23: arm N=1 (pending from the next boundary on, IE=0
        # defers delivery); a bad ACK faults and STATUS/PERIOD are
        # untouched; a good ACK then still works; disarm ends it
        li r27, 23
        st.64 [r25 + 8], r23      # arm N=1: next_fire = W+1
        lds.64 r19, [r25 + 0x10]  # at W+1: pending
        cmpeq p1, r19, 1
        (!p1) b fail
        li r22, 2
        st.64 [r25 + 0x18], r22   # E5: DEVERR
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, CAUSE_DEVERR
        (!p1) b fail
        li r27, 24
        lds.64 r19, [r25 + 0x10]  # still pending: no state change
        cmpeq p1, r19, 1
        (!p1) b fail
        lds.64 r19, [r25 + 8]     # PERIOD still 1
        cmpeq p1, r19, r23
        (!p1) b fail
        li r27, 25
        st.64 [r25 + 0x18], r23   # the strict value works (TMR-08/09)
        st.64 [r25 + 8], zero     # disarm: pending drops (TMR-04)
        lds.64 r19, [r25 + 0x10]
        cmpeq p1, r19, zero
        (!p1) b fail
        lds.64 r19, [r25 + 8]
        cmpeq p1, r19, zero
        (!p1) b fail

# ==== predicated-false: no trap, no record, one cycle ================
        # -- 26: p2 = 0 at reset; the bad-value ACK is squashed and
        # must not reach the device (TMR-15). Sentinel proves h_rec
        # never ran; the checker's exact census proves no trap; the
        # trace's record absence is checked there too.
        li r27, 26
        li r19, 999
        st.64 [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR], r19
        li r22, 7
        (p2) st.64 [r25 + 0x18], r22
        lds.64 r22, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r22, 999
        (!p1) b fail

pass:
        li r0, PASS_MAGIC
        halt
fail:
        st.64 [r24], r27
        mov r0, r27
        halt

# ==== handler ========================================================
        # record cause/baddr/epc/status, skip the faulting instruction
        # (the c1/c3 recording pattern; every fault site is a single
        # 8-byte instruction, so epc+8 lands on the next one)
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
