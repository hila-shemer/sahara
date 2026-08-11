# dma_fill.s — FILL pattern replication (devspec/dma.md 4.2) and the
# cost formula at a different LEN than dma_copy: 32 KB -> C_done =
# C_doorbell + 8 + 4096 (dma.md V3 second row). The SRC field is the
# 8-byte pattern itself — an ODD value here, proving FILL's SRC
# carries no alignment constraint (BAD_ALIGN is DST/LEN-only for
# FILL, dma.md 5.3). Checksum identity: 4096 identical words sum to
# pattern << 12 mod 2^64. DMA-C-13/18 instances.
#
# Cycle-driven, no events= line: runs under difftest today.
# Expectations hand-derived from dma.md; NOT from an emulator run.
#
# checks/dma_fill.py: exactly one doorbell DEVW, zero MEMW/DEVW inside
# [DST, DST+LEN), zero traps. Constants mirror this file — change
# together: DESC 0x100000, DST 0x300000, LEN 32768.

        .org 0x1000
start:
        li r24, FAIL_ADDR
        li r21, DEV_DMA_BASE
        li r14, 0x0123456789ABCDEF     # the pattern (odd on purpose)

        # ---- descriptor: FILL, no IRQ ----
        li r10, 0x100000
        li r22, 2                      # OP = FILL, bit 8 clear
        st.64 [r10], r22
        st.64 [r10 + 8], r14           # SRC = the pattern itself
        li r22, 0x300000               # DST
        st.64 [r10 + 16], r22
        li r22, 32768                  # LEN
        st.64 [r10 + 24], r22
        st.64 [r10 + 32], zero
        st.64 [r10 + 40], zero
        st.64 [r10 + 48], zero
        st.64 [r10 + 56], zero

        # test 1: doorbell; BUSY on the very next read
        li r27, 1
        mfsr r5, cycle
        st.64 [r21 + 16], r10
        ldz.64 r19, [r21 + 8]
        cmpeq.64 p1, r19, 1
        (!p1) b fail

        # test 2: COMP_CYCLE == (r5+1) + 8 + 32768/8 == r5 + 4105
        li r27, 2
        add r6, r5, 4105
        ldz.64 r19, [r21 + 32]
        cmpeq.64 p1, r19, r6
        (!p1) b fail

        # poll to DONE
        li r27, 3
poll:
        ldz.64 r19, [r21 + 8]
        cmpeq.64 p1, r19, 2
        (!p1) b poll

        # test 4: first, middle, and last destination words are the
        # pattern exactly
        li r27, 4
        li r12, 0x300000
        ldz.64 r19, [r12]
        cmpeq.64 p1, r19, r14
        (!p1) b fail
        ldz.64 r19, [r12 + 16384]
        cmpeq.64 p1, r19, r14
        (!p1) b fail
        ldz.64 r19, [r12 + 32760]
        cmpeq.64 p1, r19, r14
        (!p1) b fail

        # test 5: checksum — 4096 * pattern == pattern << 12 (mod 2^64)
        li r27, 5
        li r13, 0
        li r17, 0
fsum:
        ldz.64 r16, [r12]
        add.64 r17, r17, r16
        add r12, r12, 8
        add r13, r13, 1
        cmpltu.64 p1, r13, 4096
        (p1) b fsum
        shl.64 r20, r14, 12
        cmpeq.64 p1, r17, r20
        (!p1) b fail

        # test 6: guard words untouched on both sides
        li r27, 6
        li r12, 0x300000
        ldz.64 r19, [r12 + 32768]
        cmpeq.64 p1, r19, 0
        (!p1) b fail
        li r12, 0x300000 - 8
        ldz.64 r19, [r12]
        cmpeq.64 p1, r19, 0
        (!p1) b fail

        # test 7: COMP_CYCLE unchanged after completion
        li r27, 7
        ldz.64 r19, [r21 + 32]
        cmpeq.64 p1, r19, r6
        (!p1) b fail

pass:
        li r0, PASS_MAGIC
        halt
fail:
        st.64 [r24], r27
        mov r0, r27
        halt
