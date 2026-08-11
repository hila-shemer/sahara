# c7_rng_err.s — C7 RNG register-model faults and reset state
# (devspec/rng.md: RNG-01, RNG-04..12, E1-E6 census, precedence).
# Headless, no feed: the empty well is a first-class state — every
# DEVERR here is provoked against a reset-fresh device. Trace
# assertions: checks/c7_rng_err.py.
#
# Census contract: exactly 2 UNALIGNED + 17 DEVERR traps, in program
# order below — the checker counts them (change this fault section and
# the checker's census dict TOGETHER).
#
# NOT emulator-verified when written: expectations hand-derived from
# devspec/rng.md sections 2, 8, 9 (access matrix V-A).

        .org 0x1000
start:
        li r24, FAIL_ADDR
        li r26, DEV_RNG_BASE
        la.abs r19, h_rec
        mtsr vbase, r19

        # ---- reset state (RNG-01) ----
        # test 1: STATUS == 0 — the well starts empty
        li r27, 1
        ldz.64 r19, [r26 + 8]
        cmpeq p1, r19, 0
        (!p1) b fail

        # test 2: CTRL == 0 — QUEUE mode, IE off
        li r27, 2
        ldz.64 r19, [r26 + 16]
        cmpeq p1, r19, 0
        (!p1) b fail

        # ---- precedence: UNALIGNED outranks every DEVERR class ----
        # test 3: misaligned 4-byte load: UNALIGNED (not E3), baddr = ea
        li r27, 3
        lds.32 r19, [r26 + 2]
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_UNALIGNED
        (!p1) b fail
        lds.64 r19, [r24 + TRAP_BADDR_SLOT - FAIL_ADDR]
        li r20, DEV_RNG_BASE + 2
        cmpeq p1, r19, r20
        (!p1) b fail

        # test 4: misaligned 64-bit load: UNALIGNED (not E1/E6)
        li r27, 4
        lds.64 r19, [r26 + 4]
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_UNALIGNED
        (!p1) b fail

        # ---- E3: size != 8 (aligned, so past the UNALIGNED check) --
        # test 5: 4-byte DATA load
        li r27, 5
        ldz.32 r19, [r26]
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_DEVERR
        (!p1) b fail
        lds.64 r19, [r24 + TRAP_BADDR_SLOT - FAIL_ADDR]
        li r20, DEV_RNG_BASE
        cmpeq p1, r19, r20
        (!p1) b fail

        # test 6: 1-byte STATUS load
        li r27, 6
        ldz.8 r19, [r26 + 8]
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_DEVERR
        (!p1) b fail

        # test 7: 4-byte CTRL store
        li r27, 7
        li r22, 1
        st.32 [r26 + 16], r22
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_DEVERR
        (!p1) b fail

        # test 8: LD128 at the (16-aligned) window base is not 64-bit
        li r27, 8
        ld128 r19, [r26]
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_DEVERR
        (!p1) b fail

        # ---- E4: atomics anywhere in the window ----
        # test 9: AMOADD on DATA
        li r27, 9
        li r22, 1
        amoadd.64 r19, [r26], r22
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_DEVERR
        (!p1) b fail

        # test 10: CAS on CTRL
        li r27, 10
        li r22, 0
        li r23, 1
        cas.64 r19, [r26 + 16], r22, r23
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_DEVERR
        (!p1) b fail

        # ---- E1: unlisted offsets ----
        # test 11: load at 0x20
        li r27, 11
        ldz.64 r19, [r26 + 32]
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_DEVERR
        (!p1) b fail
        lds.64 r19, [r24 + TRAP_BADDR_SLOT - FAIL_ADDR]
        li r20, DEV_RNG_BASE + 32
        cmpeq p1, r19, r20
        (!p1) b fail

        # test 12: store at 0x28
        li r27, 12
        li r22, 1
        st.64 [r26 + 40], r22
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_DEVERR
        (!p1) b fail

        # test 13: load at the top of the window (0xFFF8)
        li r27, 13
        ldz.64 r19, [r26 + 0xFFF8]
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_DEVERR
        (!p1) b fail

        # ---- E2: wrong direction ----
        # test 14: store to DATA
        li r27, 14
        li r22, 1
        st.64 [r26], r22
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_DEVERR
        (!p1) b fail

        # test 15: store to STATUS
        li r27, 15
        st.64 [r26 + 8], r22
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_DEVERR
        (!p1) b fail

        # test 16: load from SEED (write-only)
        li r27, 16
        ldz.64 r19, [r26 + 24]
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_DEVERR
        (!p1) b fail

        # ---- E6: the empty well is LOUD (rng.md 4.1 rule 4) ----
        # test 17: QUEUE-mode pop at depth 0 traps; no sentinel exists
        li r27, 17
        ldz.64 r19, [r26]
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_DEVERR
        (!p1) b fail
        lds.64 r19, [r24 + TRAP_BADDR_SLOT - FAIL_ADDR]
        li r20, DEV_RNG_BASE
        cmpeq p1, r19, r20
        (!p1) b fail
        ldz.64 r19, [r26 + 8]      # zero state change: still empty
        cmpeq p1, r19, 0
        (!p1) b fail

        # ---- E5: CTRL reserved bits (rng.md 9: opt-in forever) ----
        # test 18: bit 2 set
        li r27, 18
        li r22, 4
        st.64 [r26 + 16], r22
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_DEVERR
        (!p1) b fail
        ldz.64 r19, [r26 + 16]     # no state change
        cmpeq p1, r19, 0
        (!p1) b fail

        # test 19: bit 63 + a legal bit together still reject whole
        li r27, 19
        li r22, 0x8000000000000001
        st.64 [r26 + 16], r22
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_DEVERR
        (!p1) b fail
        ldz.64 r19, [r26 + 16]
        cmpeq p1, r19, 0
        (!p1) b fail

        # ---- the holes either side of the window (rng.md 1, W2) ----
        # test 20: 0x0F07_0000 is declared in no region: DEVERR
        li r27, 20
        li r21, 0x0F070000
        ldz.64 r19, [r21]
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_DEVERR
        (!p1) b fail

        # test 21: 0x0F09_0000 (just past the window): DEVERR
        li r27, 21
        li r21, 0x0F090000
        ldz.64 r19, [r21]
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_DEVERR
        (!p1) b fail

        # ---- predication: squashed accesses cannot fault (RNG-10) --
        # test 22: predicated-false empty pop is a no-fault no-op
        li r27, 22
        li r22, 0x5EA1
        st.64 [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR], r22
        cmpeq p2, zero, 1          # p2 <- false
        (p2) ldz.64 r19, [r26]     # squashed: no E6, no pop
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, r22         # sentinel untouched: no trap ran
        (!p1) b fail
        ldz.64 r19, [r26 + 8]
        cmpeq p1, r19, 0
        (!p1) b fail

        # test 23: predicated-false wrong-size access: no E3 either
        li r27, 23
        (p2) ldz.32 r19, [r26]
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, r22
        (!p1) b fail

        # ---- CTRL write/readback over the architected bits ----
        # test 24: 1, 3, 2, 0 each store and read back exactly
        # (RNG-11; the checker also sees exactly these four DEVWs)
        li r27, 24
        li r22, 1
        st.64 [r26 + 16], r22
        ldz.64 r19, [r26 + 16]
        cmpeq p1, r19, 1
        (!p1) b fail
        li r22, 3
        st.64 [r26 + 16], r22
        ldz.64 r19, [r26 + 16]
        cmpeq p1, r19, 3
        (!p1) b fail
        li r22, 2
        st.64 [r26 + 16], r22
        ldz.64 r19, [r26 + 16]
        cmpeq p1, r19, 2
        (!p1) b fail
        st.64 [r26 + 16], zero
        ldz.64 r19, [r26 + 16]
        cmpeq p1, r19, 0
        (!p1) b fail

pass:
        li r0, PASS_MAGIC
        halt
fail:
        st.64 [r24], r27
        mov r0, r27
        halt

        # record cause/baddr, skip the faulting instruction
h_rec:
        mfsr k0, cause0
        st.64 [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR], k0
        mfsr k0, baddr0
        st.64 [r24 + TRAP_BADDR_SLOT - FAIL_ADDR], k0
        mfsr k0, epc0
        add k0, k0, 8
        mtsr epc0, k0
        iret
