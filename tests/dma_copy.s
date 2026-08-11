# dma_copy.s — one 4 KB COPY end to end (devspec/dma.md 5-7):
# sreg-cycle reads bracket the doorbell so the cost model is checked
# EXACTLY (C_done = C_doorbell + 8 + LEN/8, dma.md V3), COMP_CYCLE is
# readable during BUSY (holds the schedule, dma.md 3.5 / root
# SPEC-ISSUES 42), STATUS polls to DONE, and the guest checksums the
# destination against the sum it accumulated while writing the source.
# DMA-C-13/18 instances.
#
# Cycle-driven, no events= line: runs under difftest today.
# Expectations hand-derived from dma.md; NOT from an emulator run.
#
# checks/dma_copy.py enforces the no-records clause (DMA-C-22):
# exactly ONE doorbell DEVW, ZERO MEMW/DEVW records inside
# [DST, DST+LEN), zero traps. Constants mirror this file — change
# together: DESC 0x100000, SRC 0x200000, DST 0x300000, LEN 4096.

        .org 0x1000
start:
        li r24, FAIL_ADDR
        li r21, DEV_DMA_BASE

        # ---- fill the source: word i = i * 0x0101010101010101,
        #      summing as we go (r15, mod 2^64) ----
        li r12, 0x200000
        li r13, 0                      # i
        li r14, 0x0101010101010101
        li r15, 0                      # running sum
fill:
        mul.64 r16, r13, r14
        st.64 [r12], r16
        add.64 r15, r15, r16
        add r12, r12, 8
        add r13, r13, 1
        cmpltu.64 p1, r13, 512
        (p1) b fill

        # ---- build the descriptor (dma.md 4): COPY, no IRQ ----
        li r10, 0x100000               # 64-byte aligned, ordinary RAM
        li r22, 1                      # OP = COPY, bit 8 clear
        st.64 [r10], r22
        li r22, 0x200000               # SRC
        st.64 [r10 + 8], r22
        li r22, 0x300000               # DST
        st.64 [r10 + 16], r22
        li r22, 4096                   # LEN
        st.64 [r10 + 24], r22
        st.64 [r10 + 32], zero         # NEXT (MBZ)
        st.64 [r10 + 40], zero
        st.64 [r10 + 48], zero
        st.64 [r10 + 56], zero

        # ---- submit; the doorbell retires one cycle after the mfsr,
        #      so C_doorbell = r5 + 1 and C_done = r5 + 521 ----
        # test 1: STATUS reads BUSY right after the doorbell
        li r27, 1
        mfsr r5, cycle
        st.64 [r21 + 16], r10          # DOORBELL <- descriptor PA
        ldz.64 r19, [r21 + 8]
        cmpeq.64 p1, r19, 1
        (!p1) b fail

        # test 2: COMP_CYCLE already holds the schedule during BUSY
        li r27, 2
        add r6, r5, 521                # (r5+1) + 8 + 4096/8
        ldz.64 r19, [r21 + 32]
        cmpeq.64 p1, r19, r6
        (!p1) b fail

        # poll to DONE (bounded by construction: C_done is exact)
        li r27, 3
poll:
        ldz.64 r19, [r21 + 8]
        cmpeq.64 p1, r19, 2
        (!p1) b poll

        # test 4: COMP_CYCLE unchanged by completion
        li r27, 4
        ldz.64 r19, [r21 + 32]
        cmpeq.64 p1, r19, r6
        (!p1) b fail

        # ---- verify the destination ----
        # test 5: checksum over all 512 destination words == the sum
        # accumulated while writing the source
        li r27, 5
        li r12, 0x300000
        li r13, 0
        li r17, 0                      # destination sum
dsum:
        ldz.64 r16, [r12]
        add.64 r17, r17, r16
        add r12, r12, 8
        add r13, r13, 1
        cmpltu.64 p1, r13, 512
        (p1) b dsum
        cmpeq.64 p1, r17, r15
        (!p1) b fail

        # test 6: exact spot checks — first and last words
        li r27, 6
        li r12, 0x300000
        ldz.64 r19, [r12]
        cmpeq.64 p1, r19, 0
        (!p1) b fail
        li r13, 511
        mul.64 r16, r13, r14
        ldz.64 r19, [r12 + 4088]
        cmpeq.64 p1, r19, r16
        (!p1) b fail

        # test 7: exactly LEN bytes written — the guard words on both
        # sides of [DST, DST+4096) still read zero
        li r27, 7
        ldz.64 r19, [r12 + 4096]
        cmpeq.64 p1, r19, 0
        (!p1) b fail
        li r12, 0x300000 - 8
        ldz.64 r19, [r12]
        cmpeq.64 p1, r19, 0
        (!p1) b fail

pass:
        li r0, PASS_MAGIC
        halt
fail:
        st.64 [r24], r27
        mov r0, r27
        halt
