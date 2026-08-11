# dma_boundary.s — the latch/sample split and completion atomicity
# (devspec/dma.md 4, 5.4, 5.5):
#   - exact boundary visibility: with LEN=8, a STATUS load retiring at
#     C_done-1 reads BUSY and one retiring at C_done reads DONE
#     (cycle-counted filler instructions, no polling) — the
#     boundary-visibility rule instantiated for the DMA engine
#     (deliberate instantiation, CONFORMANCE-DELTA.md);
#   - descriptor overwrite after the doorbell is ignored (latched);
#   - a store into SRC after the doorbell, before C_done, IS copied
#     (sources sampled at completion);
#   - overlapping COPY gives the exact memmove result, both directions;
#   - DOORBELL while BUSY traps DEVERR with zero effect on the
#     in-flight job (the test's only trap);
#   - re-arm from DONE; the device table is a legal COPY source.
# DMA-C-08/12/14/15/16/17/18 instances.
#
# Cycle-driven, no events= line: runs under difftest today.
# Expectations hand-derived from dma.md V3/V4; NOT from an emulator
# run.
#
# checks/dma_boundary.py: exactly 7 doorbell DEVWs (the BUSY-rejected
# one faults and leaves NO record), trap census exactly {DEVERR: 1}.
# Change file and checker together.

        .org 0x1000
start:
        li r24, FAIL_ADDR
        li r21, DEV_DMA_BASE
        li r10, 0x100000               # descriptor PA
        la.abs r26, h_rec
        mtsr vbase, r26

        # ---- leg 0: exact completion boundary, cycle-counted ----
        # LEN=8: C_done = C_doorbell + 9. After the doorbell (cycle
        # X = r5+1) come exactly 7 fillers (X+1..X+7), then the BUSY
        # read at X+8 = C_done-1 and the DONE read at X+9 = C_done.
        li r27, 1
        li r23, 0xB0B                  # source word (desc_small owns r22)
        li r12, 0x200000
        st.64 [r12], r23
        jal desc_small
        mfsr r5, cycle
        st.64 [r21 + 16], r10          # doorbell at X = r5+1
        mov r6, r6                     # X+1
        mov r6, r6                     # X+2
        mov r6, r6                     # X+3
        mov r6, r6                     # X+4
        mov r6, r6                     # X+5
        mov r6, r6                     # X+6
        mov r6, r6                     # X+7
        ldz.64 r19, [r21 + 8]          # X+8 = C_done-1: BUSY
        ldz.64 r20, [r21 + 8]          # X+9 = C_done:   DONE
        cmpeq.64 p1, r19, 1
        (!p1) b fail
        cmpeq.64 p1, r20, 2
        (!p1) b fail
        li r12, 0x300000
        ldz.64 r19, [r12]
        cmpeq.64 p1, r19, r23
        (!p1) b fail

        # ---- leg 1: descriptor bytes are LATCHED at the doorbell ----
        # Overwrite the whole descriptor right after ringing it: the
        # in-flight job must finish as submitted, STATUS ends DONE,
        # never BAD_OP, and the smashed LEN/DST change nothing.
        li r27, 2
        li r12, 0x210000               # A: 8 known source words
        li r13, 0
l1fill:
        add r16, r13, 0x41
        st.64 [r12], r16
        add r12, r12, 8
        add r13, r13, 1
        cmpltu.64 p1, r13, 8
        (p1) b l1fill
        li r22, 1
        st.64 [r10], r22               # OP = COPY
        li r22, 0x210000
        st.64 [r10 + 8], r22           # SRC = A
        li r22, 0x310000
        st.64 [r10 + 16], r22          # DST = B
        li r22, 64
        st.64 [r10 + 24], r22
        st.64 [r10 + 32], zero
        st.64 [r10 + 40], zero
        st.64 [r10 + 48], zero
        st.64 [r10 + 56], zero
        st.64 [r21 + 16], r10          # doorbell
        st.64 [r10], zero              # smash OP (would be BAD_OP)
        li r22, 0x7000000
        st.64 [r10 + 24], r22          # smash LEN (would be BAD_RANGE)
        li r22, 0x320000
        st.64 [r10 + 16], r22          # smash DST
l1poll:
        ldz.64 r19, [r21 + 8]
        cmpeq.64 p1, r19, 2            # DONE — the latch held
        (!p1) b l1poll
        li r12, 0x310000
        li r13, 0
l1chk:
        add r16, r13, 0x41
        ldz.64 r19, [r12]
        cmpeq.64 p1, r19, r16
        (!p1) b fail
        add r12, r12, 8
        add r13, r13, 1
        cmpltu.64 p1, r13, 8
        (p1) b l1chk
        li r12, 0x320000               # the smashed DST: untouched
        ldz.64 r19, [r12]
        cmpeq.64 p1, r19, 0
        (!p1) b fail

        # ---- leg 2: sources are SAMPLED at completion ----
        # 4 KB COPY is in flight for 520 cycles; stores into SRC right
        # after the doorbell land before C_done and MUST be copied.
        li r27, 3
        li r12, 0x220000               # C: words 0..511 = index
        li r13, 0
l2fill:
        st.64 [r12], r13
        add r12, r12, 8
        add r13, r13, 1
        cmpltu.64 p1, r13, 512
        (p1) b l2fill
        li r22, 1
        st.64 [r10], r22
        li r22, 0x220000
        st.64 [r10 + 8], r22
        li r22, 0x330000               # D
        st.64 [r10 + 16], r22
        li r22, 4096
        st.64 [r10 + 24], r22
        st.64 [r10 + 32], zero
        st.64 [r10 + 40], zero
        st.64 [r10 + 48], zero
        st.64 [r10 + 56], zero
        st.64 [r21 + 16], r10          # doorbell; C_done 520 away
        li r12, 0x220000
        li r22, 0xFEED0001
        st.64 [r12], r22               # into SRC word 0, before C_done
        li r23, 0xFEED0002
        st.64 [r12 + 8], r23           # into SRC word 1
l2poll:
        ldz.64 r19, [r21 + 8]
        cmpeq.64 p1, r19, 2
        (!p1) b l2poll
        li r12, 0x330000
        ldz.64 r19, [r12]
        cmpeq.64 p1, r19, r22          # the post-doorbell value
        (!p1) b fail
        ldz.64 r19, [r12 + 8]
        cmpeq.64 p1, r19, r23
        (!p1) b fail
        ldz.64 r19, [r12 + 16]
        cmpeq.64 p1, r19, 2            # untouched words: originals
        (!p1) b fail
        ldz.64 r19, [r12 + 4088]
        cmpeq.64 p1, r19, 511
        (!p1) b fail

        # ---- leg 3: forward overlap is memmove, not a smear ----
        # E: 64 words f(i) = 0x1000+i; COPY E -> E+8, LEN 512. Word
        # E[1+j] must be f(j) for every j and E[0] stays f(0). A
        # forward in-place byte copy would replicate f(0) everywhere.
        li r27, 4
        li r12, 0x230000
        li r13, 0
l3fill:
        add r16, r13, 0x1000
        st.64 [r12], r16
        add r12, r12, 8
        add r13, r13, 1
        cmpltu.64 p1, r13, 64
        (p1) b l3fill
        li r22, 1
        st.64 [r10], r22
        li r22, 0x230000
        st.64 [r10 + 8], r22
        li r22, 0x230008
        st.64 [r10 + 16], r22
        li r22, 512
        st.64 [r10 + 24], r22
        st.64 [r10 + 32], zero
        st.64 [r10 + 40], zero
        st.64 [r10 + 48], zero
        st.64 [r10 + 56], zero
        st.64 [r21 + 16], r10
l3poll:
        ldz.64 r19, [r21 + 8]
        cmpeq.64 p1, r19, 2
        (!p1) b l3poll
        li r12, 0x230000
        ldz.64 r19, [r12]
        li r16, 0x1000
        cmpeq.64 p1, r19, r16          # E[0] untouched
        (!p1) b fail
        li r13, 0
l3chk:
        add r16, r13, 0x1000           # E[1+j] == f(j)
        ldz.64 r19, [r12 + 8]
        cmpeq.64 p1, r19, r16
        (!p1) b fail
        add r12, r12, 8
        add r13, r13, 1
        cmpltu.64 p1, r13, 64
        (p1) b l3chk

        # ---- leg 4: backward overlap is memmove too ----
        # F: 65 words g(i) = 0x2000+i; COPY F+8 -> F, LEN 512. Word
        # F[j] must become g(j+1); the word past the copy, F[64],
        # stays g(64).
        li r27, 5
        li r12, 0x240000
        li r13, 0
l4fill:
        add r16, r13, 0x2000
        st.64 [r12], r16
        add r12, r12, 8
        add r13, r13, 1
        cmpltu.64 p1, r13, 65
        (p1) b l4fill
        li r22, 1
        st.64 [r10], r22
        li r22, 0x240008
        st.64 [r10 + 8], r22
        li r22, 0x240000
        st.64 [r10 + 16], r22
        li r22, 512
        st.64 [r10 + 24], r22
        st.64 [r10 + 32], zero
        st.64 [r10 + 40], zero
        st.64 [r10 + 48], zero
        st.64 [r10 + 56], zero
        st.64 [r21 + 16], r10
l4poll:
        ldz.64 r19, [r21 + 8]
        cmpeq.64 p1, r19, 2
        (!p1) b l4poll
        li r12, 0x240000
        li r13, 0
l4chk:
        add r16, r13, 0x2001           # F[j] == g(j+1)
        ldz.64 r19, [r12]
        cmpeq.64 p1, r19, r16
        (!p1) b fail
        add r12, r12, 8
        add r13, r13, 1
        cmpltu.64 p1, r13, 64
        (p1) b l4chk
        ldz.64 r19, [r12]              # F[64] == g(64)
        li r16, 0x2040
        cmpeq.64 p1, r19, r16
        (!p1) b fail

        # ---- leg 5: DOORBELL while BUSY is DEVERR, zero effect ----
        # 64 KB COPY holds BUSY for 8200 cycles; the second doorbell
        # traps (the test's ONLY trap) and the in-flight job's
        # COMP_CYCLE and data are unharmed.
        li r27, 6
        li r22, 1
        st.64 [r10], r22
        li r22, 0x250000
        st.64 [r10 + 8], r22
        li r22, 0x340000
        st.64 [r10 + 16], r22
        li r22, 65536
        st.64 [r10 + 24], r22
        st.64 [r10 + 32], zero
        st.64 [r10 + 40], zero
        st.64 [r10 + 48], zero
        st.64 [r10 + 56], zero
        mfsr r5, cycle
        st.64 [r21 + 16], r10          # accepted at X = r5+1
        add r6, r5, 8201               # C_done = X + 8 + 8192
        st.64 [r21 + 16], r10          # rejected: E5, DEVERR
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq.64 p1, r19, CAUSE_DEVERR
        (!p1) b fail
        lds.64 r19, [r24 + TRAP_BADDR_SLOT - FAIL_ADDR]
        li r20, DEV_DMA_BASE + 16
        cmpeq.64 p1, r19, r20
        (!p1) b fail
        ldz.64 r19, [r21 + 8]          # still BUSY
        cmpeq.64 p1, r19, 1
        (!p1) b fail
        ldz.64 r19, [r21 + 32]         # schedule unharmed
        cmpeq.64 p1, r19, r6
        (!p1) b fail
l5poll:
        ldz.64 r19, [r21 + 8]
        cmpeq.64 p1, r19, 2
        (!p1) b l5poll
        ldz.64 r19, [r21 + 32]
        cmpeq.64 p1, r19, r6
        (!p1) b fail

        # ---- leg 6: the device table is ordinary RAM and a legal
        #      COPY source (dma.md 5.3); also proves re-arm from DONE
        li r27, 7
        li r22, 1
        st.64 [r10], r22
        li r22, 0x800                  # the device table itself
        st.64 [r10 + 8], r22
        li r22, 0x350000
        st.64 [r10 + 16], r22
        li r22, 64
        st.64 [r10 + 24], r22
        st.64 [r10 + 32], zero
        st.64 [r10 + 40], zero
        st.64 [r10 + 48], zero
        st.64 [r10 + 56], zero
        st.64 [r21 + 16], r10
l6poll:
        ldz.64 r19, [r21 + 8]
        cmpeq.64 p1, r19, 2
        (!p1) b l6poll
        li r12, 0x350000
        ldz.64 r19, [r12]              # header magic ("SAHARAPT")
        li r20, 0x5450415241484153
        cmpeq.64 p1, r19, r20
        (!p1) b fail
        ldz.64 r19, [r12 + 8]          # version 1 — and nothing about
        cmpeq.64 p1, r19, 1            # counts/positions: those are
        (!p1) b fail                   # merge-variant on this branch

pass:
        li r0, PASS_MAGIC
        halt
fail:
        st.64 [r24], r27
        mov r0, r27
        halt

        # minimal COPY descriptor for leg 0: SRC=0x200000,
        # DST=0x300000, LEN=8. Clobbers r22.
desc_small:
        li r22, 1
        st.64 [r10], r22
        li r22, 0x200000
        st.64 [r10 + 8], r22
        li r22, 0x300000
        st.64 [r10 + 16], r22
        li r22, 8
        st.64 [r10 + 24], r22
        st.64 [r10 + 32], zero
        st.64 [r10 + 40], zero
        st.64 [r10 + 48], zero
        st.64 [r10 + 56], zero
        ret

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
