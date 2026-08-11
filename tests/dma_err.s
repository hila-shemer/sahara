# dma_err.s — descriptor CONTENT errors (devspec/dma.md 5.3, 8): one
# descriptor per STATUS code, the fixed check order BAD_OP ->
# BAD_FORMAT -> BAD_ALIGN -> BAD_RANGE (first failure wins), terminal
# immediately post-doorbell (STATUS read as the VERY NEXT instruction),
# COMP_CYCLE = the doorbell cycle, destination proven untouched by
# guest re-reads, and error-with-IRQ_ON_COMPLETE raising the pending
# level (one wait-path for software). None of these traps: the badness
# lives in RAM data, the doorbell store itself retires — DEVERR never
# fires in this test. DMA-C-10/11/16 instances.
#
# Cycle-driven, no events= line: runs under difftest today.
# Expectations hand-derived from dma.md V2; NOT from an emulator run.
#
# checks/dma_err.py: exactly 16 doorbell DEVWs + 1 ack DEVW, trap
# census exactly {EXTINT: 1}, and the only write in the destination
# page is the guest's own canary MEMW. Change file and checker
# together.

        .org 0x1000
start:
        li r24, FAIL_ADDR
        li r21, DEV_DMA_BASE
        li r10, 0x100000               # descriptor PA, 64-aligned
        la.abs r26, h_ext
        mtsr vbase, r26

        # canary at the would-be destination: every leg must leave it
        li r23, 0x600DCAFE
        li r12, 0x300000
        st.64 [r12], r23

        # test 1: opcode 0 — the zeroed-RAM guard — is BAD_OP (3)
        li r27, 1
        jal desc_valid
        st.64 [r10], zero
        mfsr r5, cycle
        st.64 [r21 + 16], r10
        ldz.64 r19, [r21 + 8]          # the very next instruction
        cmpeq.64 p1, r19, 3
        (!p1) b fail
        add r6, r5, 1
        ldz.64 r19, [r21 + 32]         # COMP_CYCLE = doorbell cycle
        cmpeq.64 p1, r19, r6
        (!p1) b fail

        # test 2: unassigned opcode 7 is BAD_OP
        li r27, 2
        jal desc_valid
        li r22, 7
        st.64 [r10], r22
        mfsr r5, cycle
        st.64 [r21 + 16], r10
        ldz.64 r19, [r21 + 8]
        cmpeq.64 p1, r19, 3
        (!p1) b fail

        # test 3: NEXT != 0 is BAD_FORMAT (4) — a v2 chaining
        # descriptor is rejected, never half-run (dma.md 4.1)
        li r27, 3
        jal desc_valid
        li r22, 1
        st.64 [r10 + 32], r22
        mfsr r5, cycle
        st.64 [r21 + 16], r10
        ldz.64 r19, [r21 + 8]
        cmpeq.64 p1, r19, 4
        (!p1) b fail
        add r6, r5, 1
        ldz.64 r19, [r21 + 32]
        cmpeq.64 p1, r19, r6
        (!p1) b fail

        # test 4: OP bit 9 set is BAD_FORMAT
        li r27, 4
        jal desc_valid
        li r22, 0x201
        st.64 [r10], r22
        mfsr r5, cycle
        st.64 [r21 + 16], r10
        ldz.64 r19, [r21 + 8]
        cmpeq.64 p1, r19, 4
        (!p1) b fail

        # test 5: reserved word at offset 56 nonzero is BAD_FORMAT
        li r27, 5
        jal desc_valid
        li r22, 1
        st.64 [r10 + 56], r22
        mfsr r5, cycle
        st.64 [r21 + 16], r10
        ldz.64 r19, [r21 + 8]
        cmpeq.64 p1, r19, 4
        (!p1) b fail

        # test 6: COPY with unaligned SRC is BAD_ALIGN (5)
        li r27, 6
        jal desc_valid
        li r22, 0x200001
        st.64 [r10 + 8], r22
        mfsr r5, cycle
        st.64 [r21 + 16], r10
        ldz.64 r19, [r21 + 8]
        cmpeq.64 p1, r19, 5
        (!p1) b fail

        # test 7: unaligned DST is BAD_ALIGN
        li r27, 7
        jal desc_valid
        li r22, 0x300004
        st.64 [r10 + 16], r22
        mfsr r5, cycle
        st.64 [r21 + 16], r10
        ldz.64 r19, [r21 + 8]
        cmpeq.64 p1, r19, 5
        (!p1) b fail

        # test 8: LEN not a multiple of 8 is BAD_ALIGN
        li r27, 8
        jal desc_valid
        li r22, 12
        st.64 [r10 + 24], r22
        mfsr r5, cycle
        st.64 [r21 + 16], r10
        ldz.64 r19, [r21 + 8]
        cmpeq.64 p1, r19, 5
        (!p1) b fail

        # test 9: LEN = 0 is BAD_RANGE (6) — loud, not a no-op
        li r27, 9
        jal desc_valid
        st.64 [r10 + 24], zero
        mfsr r5, cycle
        st.64 [r21 + 16], r10
        ldz.64 r19, [r21 + 8]
        cmpeq.64 p1, r19, 6
        (!p1) b fail
        add r6, r5, 1
        ldz.64 r19, [r21 + 32]
        cmpeq.64 p1, r19, r6
        (!p1) b fail

        # test 10: LEN > 2^24 is BAD_RANGE
        li r27, 10
        jal desc_valid
        li r22, 0x1000008
        st.64 [r10 + 24], r22
        mfsr r5, cycle
        st.64 [r21 + 16], r10
        ldz.64 r19, [r21 + 8]
        cmpeq.64 p1, r19, 6
        (!p1) b fail

        # test 11: DST in the pixel buffer is BAD_RANGE — the engine
        # touches ordinary RAM only; blit is a CAPS-gated v2 candidate
        li r27, 11
        jal desc_valid
        li r22, DEV_PIXBUF_BASE
        st.64 [r10 + 16], r22
        mfsr r5, cycle
        st.64 [r21 + 16], r10
        ldz.64 r19, [r21 + 8]
        cmpeq.64 p1, r19, 6
        (!p1) b fail

        # test 12: SRC range crossing the RAM top is BAD_RANGE
        # ([0x0EFF_F000, +0x2000) straddles 0x0F00_0000)
        li r27, 12
        jal desc_valid
        li r22, 0x0EFFF000
        st.64 [r10 + 8], r22
        li r22, 0x2000
        st.64 [r10 + 24], r22
        mfsr r5, cycle
        st.64 [r21 + 16], r10
        ldz.64 r19, [r21 + 8]
        cmpeq.64 p1, r19, 6
        (!p1) b fail

        # test 13: everything wrong at once — BAD_OP wins (first
        # failure in the fixed order)
        li r27, 13
        jal desc_valid
        li r22, 0x200                  # opcode 0, bit 9 junk
        st.64 [r10], r22
        li r22, 1
        st.64 [r10 + 32], r22
        li r22, 0x200001
        st.64 [r10 + 8], r22
        st.64 [r10 + 24], zero
        mfsr r5, cycle
        st.64 [r21 + 16], r10
        ldz.64 r19, [r21 + 8]
        cmpeq.64 p1, r19, 3
        (!p1) b fail

        # test 14: opcode good, format bad, align bad, range bad —
        # BAD_FORMAT wins
        li r27, 14
        jal desc_valid
        li r22, 0x201
        st.64 [r10], r22
        li r22, 0x200001
        st.64 [r10 + 8], r22
        st.64 [r10 + 24], zero
        mfsr r5, cycle
        st.64 [r21 + 16], r10
        ldz.64 r19, [r21 + 8]
        cmpeq.64 p1, r19, 4
        (!p1) b fail

        # test 15: opcode and format good, align bad, range bad —
        # BAD_ALIGN wins
        li r27, 15
        jal desc_valid
        li r22, 0x200001
        st.64 [r10 + 8], r22
        st.64 [r10 + 24], zero
        mfsr r5, cycle
        st.64 [r21 + 16], r10
        ldz.64 r19, [r21 + 8]
        cmpeq.64 p1, r19, 5
        (!p1) b fail

        # test 16: content error WITH IRQ_ON_COMPLETE — opcode 0 with
        # bit 8: BAD_OP, and the pending level rises at the doorbell
        # (dma.md 5.2 step 4: one wait-path for both outcomes)
        li r27, 16
        jal desc_valid
        li r22, 0x100
        st.64 [r10], r22
        mfsr r5, cycle
        st.64 [r21 + 16], r10
        ldz.64 r19, [r21 + 8]
        cmpeq.64 p1, r19, 3
        (!p1) b fail
        # unmask: exactly one EXTINT delivers; the handler counts and
        # acks (level drops, so exactly one)
        li r22, STATUS_S + STATUS_IE
        mtsr status, r22
        lds.64 r19, [r24 + DMA_COUNT_SLOT - FAIL_ADDR]
        cmpeq.64 p1, r19, 1
        (!p1) b fail

        # test 17: the ack dropped the level — IE is still 1 and no
        # second delivery happens
        li r27, 17
        mov r6, r6
        mov r6, r6
        lds.64 r19, [r24 + DMA_COUNT_SLOT - FAIL_ADDR]
        cmpeq.64 p1, r19, 1
        (!p1) b fail

        # test 18: sixteen failed doorbells later, the destination
        # canary is untouched (no BUSY window ever existed)
        li r27, 18
        ldz.64 r19, [r12]
        cmpeq.64 p1, r19, r23
        (!p1) b fail
        ldz.64 r19, [r12 + 8]
        cmpeq.64 p1, r19, 0
        (!p1) b fail

pass:
        li r0, PASS_MAGIC
        halt
fail:
        st.64 [r24], r27
        mov r0, r27
        halt

        # rebuild the canonical VALID COPY descriptor: OP=1,
        # SRC=0x200000, DST=0x300000, LEN=64, NEXT/reserved zero.
        # Legs patch fields after calling this. Clobbers r22.
desc_valid:
        li r22, 1
        st.64 [r10], r22
        li r22, 0x200000
        st.64 [r10 + 8], r22
        li r22, 0x300000
        st.64 [r10 + 16], r22
        li r22, 64
        st.64 [r10 + 24], r22
        st.64 [r10 + 32], zero
        st.64 [r10 + 40], zero
        st.64 [r10 + 48], zero
        st.64 [r10 + 56], zero
        ret

        # EXTINT handler: count the delivery, ack the DMA level, iret
h_ext:
        lds.64 k0, [r24 + DMA_COUNT_SLOT - FAIL_ADDR]
        add k0, k0, 1
        st.64 [r24 + DMA_COUNT_SLOT - FAIL_ADDR], k0
        li k0, 1
        st.64 [r21 + 24], k0           # IRQ_ACK <- 1
        iret
