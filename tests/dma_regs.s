# dma_regs.s — DMA engine register surface (devspec/dma.md 2-3):
# reset values pinned (exact CAPS encoding, STATUS=0, COMP_CYCLE=0),
# the full DEVERR access matrix (size != 8, atomics, wrong direction,
# unlisted offsets both ways, IRQ_ACK != 1) with UNALIGNED precedence,
# predicated-false no-fault, and the benign race-free ack.
# DMA-C-01..07 instances; also the shared parameterized rules
# (atomics-DEVERR, non-64-bit DEVERR, predicated-false-no-fault)
# instantiated for the DMA window — deliberate instantiations, per
# devspec/CONFORMANCE-DELTA.md.
#
# Cycle-driven, no events= line: runs under difftest today.
# Expectations hand-derived from dma.md V1; NOT from an emulator run.
#
# checks/dma_regs.py (level-2 trace) asserts the MEMR values for the
# three readable registers, the trap census — exactly 18 DEVERR +
# 2 UNALIGNED, change this file and the checker together — and that
# the only DEVW in the window is the single benign ack.

        .org 0x1000
start:
        li r24, FAIL_ADDR
        li r21, DEV_DMA_BASE
        la.abs r26, h_rec
        mtsr vbase, r26

        # ---- 1. reset values (dma.md 3.6, V1 rows 1-3) ----
        # test 1: CAPS == 0x18080301 (version 1, log2 W 3, K 8,
        # log2 LEN_MAX 24; dma.md 3.1)
        li r27, 1
        ldz.64 r19, [r21]
        li r20, 0x18080301
        cmpeq.64 p1, r19, r20
        (!p1) b fail

        # test 2: STATUS == 0 (IDLE)
        li r27, 2
        ldz.64 r19, [r21 + 8]
        cmpeq.64 p1, r19, 0
        (!p1) b fail

        # test 3: COMP_CYCLE == 0
        li r27, 3
        ldz.64 r19, [r21 + 32]
        cmpeq.64 p1, r19, 0
        (!p1) b fail

        # ---- 2. size != 8 traps DEVERR everywhere (E1): 5 DEVERRs --
        # test 4: 4-byte load of CAPS
        li r27, 4
        ldz.32 r19, [r21]
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq.64 p1, r19, CAUSE_DEVERR
        (!p1) b fail
        lds.64 r19, [r24 + TRAP_BADDR_SLOT - FAIL_ADDR]
        li r20, DEV_DMA_BASE
        cmpeq.64 p1, r19, r20
        (!p1) b fail

        # test 5: 2-byte and 1-byte loads
        li r27, 5
        ldz.16 r19, [r21]
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq.64 p1, r19, CAUSE_DEVERR
        (!p1) b fail
        ldz.8 r19, [r21]
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq.64 p1, r19, CAUSE_DEVERR
        (!p1) b fail

        # test 6: 16-byte load, 4-byte store
        li r27, 6
        ld128 r19, [r21]
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq.64 p1, r19, CAUSE_DEVERR
        (!p1) b fail
        li r22, 1
        st.32 [r21 + 16], r22
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq.64 p1, r19, CAUSE_DEVERR
        (!p1) b fail

        # ---- 3. alignment outranks every DEVERR class: 2 UNALIGNED --
        # test 7: misaligned 64-bit load
        li r27, 7
        ldz.64 r19, [r21 + 4]
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq.64 p1, r19, CAUSE_UNALIGNED
        (!p1) b fail
        lds.64 r19, [r24 + TRAP_BADDR_SLOT - FAIL_ADDR]
        li r20, DEV_DMA_BASE + 4
        cmpeq.64 p1, r19, r20
        (!p1) b fail

        # test 8: misaligned 4-byte load (would be E1 if aligned)
        li r27, 8
        ldz.32 r19, [r21 + 2]
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq.64 p1, r19, CAUSE_UNALIGNED
        (!p1) b fail

        # ---- 4. atomics trap DEVERR (E9): 2 DEVERRs ----
        # test 9: AMOADD on CAPS, CAS on DOORBELL
        li r27, 9
        li r22, 1
        amoadd.64 r19, [r21], r22
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq.64 p1, r19, CAUSE_DEVERR
        (!p1) b fail
        li r23, 2
        cas.64 r19, [r21 + 16], r22, r23
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq.64 p1, r19, CAUSE_DEVERR
        (!p1) b fail

        # ---- 5. wrong direction (E3/E4): 5 DEVERRs ----
        # test 10: loads of the write-only DOORBELL and IRQ_ACK
        li r27, 10
        ldz.64 r19, [r21 + 16]
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq.64 p1, r19, CAUSE_DEVERR
        (!p1) b fail
        ldz.64 r19, [r21 + 24]
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq.64 p1, r19, CAUSE_DEVERR
        (!p1) b fail

        # test 11: stores to the read-only CAPS/STATUS/COMP_CYCLE
        li r27, 11
        li r22, 7
        st.64 [r21], r22
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq.64 p1, r19, CAUSE_DEVERR
        (!p1) b fail
        st.64 [r21 + 8], r22
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq.64 p1, r19, CAUSE_DEVERR
        (!p1) b fail
        st.64 [r21 + 32], r22
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq.64 p1, r19, CAUSE_DEVERR
        (!p1) b fail

        # ---- 6. unlisted offsets: DEVERR in BOTH directions (E2 —
        #         no inert reserved window; root SPEC-ISSUES 41):
        #         3 DEVERRs ----
        # test 12: load and store at 0x28, load at the last aligned
        # offset 0xFFF8
        li r27, 12
        ldz.64 r19, [r21 + 40]
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq.64 p1, r19, CAUSE_DEVERR
        (!p1) b fail
        st.64 [r21 + 40], r22
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq.64 p1, r19, CAUSE_DEVERR
        (!p1) b fail
        ldz.64 r19, [r21 + 0xFFF8]
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq.64 p1, r19, CAUSE_DEVERR
        (!p1) b fail

        # ---- 7. IRQ_ACK value rule (E8): only 1 is legal; even 0 is
        #         loud (dma.md 3.4): 3 DEVERRs ----
        # test 13: ack 0, ack 2, ack with a high bit set
        li r27, 13
        li r22, 0
        st.64 [r21 + 24], r22
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq.64 p1, r19, CAUSE_DEVERR
        (!p1) b fail
        li r22, 2
        st.64 [r21 + 24], r22
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq.64 p1, r19, CAUSE_DEVERR
        (!p1) b fail
        li r22, 0x8000000000000001
        st.64 [r21 + 24], r22
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq.64 p1, r19, CAUSE_DEVERR
        (!p1) b fail

        # ---- 8. predicated-false accesses cannot fault (ISA 3.2):
        #         plant a sentinel, fire squashed versions of every
        #         class, sentinel must survive ----
        # test 14
        li r27, 14
        li r22, 0x5E17
        st.64 [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR], r22
        cmpeq p2, zero, 1              # p2 <- false
        (p2) ldz.32 r19, [r21]         # squashed E1
        (p2) ldz.64 r19, [r21 + 16]    # squashed E3
        (p2) st.64 [r21], r22          # squashed E4
        (p2) amoadd.64 r19, [r21], r22 # squashed E9
        (p2) ldz.64 r19, [r21 + 4]     # squashed UNALIGNED
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq.64 p1, r19, r22
        (!p1) b fail

        # ---- 9. nothing above changed any register; benign ack ----
        # test 15: STATUS/COMP_CYCLE/CAPS unchanged after the matrix
        li r27, 15
        ldz.64 r19, [r21 + 8]
        cmpeq.64 p1, r19, 0
        (!p1) b fail
        ldz.64 r19, [r21 + 32]
        cmpeq.64 p1, r19, 0
        (!p1) b fail
        ldz.64 r19, [r21]
        li r20, 0x18080301
        cmpeq.64 p1, r19, r20
        (!p1) b fail

        # test 16: ack 1 with nothing pending is a race-free no-op
        # (dma.md 3.4) — no fault, STATUS untouched
        li r27, 16
        li r22, 1
        st.64 [r21 + 24], r22
        ldz.64 r19, [r21 + 8]
        cmpeq.64 p1, r19, 0
        (!p1) b fail

pass:
        li r0, PASS_MAGIC
        halt
fail:
        st.64 [r24], r27
        mov r0, r27
        halt

        # record cause/baddr, skip the faulter
h_rec:
        mfsr k0, cause0
        st.64 [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR], k0
        mfsr k0, baddr0
        st.64 [r24 + TRAP_BADDR_SLOT - FAIL_ADDR], k0
        mfsr k0, epc0
        add k0, k0, 8
        mtsr epc0, k0
        iret
