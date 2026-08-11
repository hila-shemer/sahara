# dma_irq_wfi.s — IRQ_ON_COMPLETE + WFI (devspec/dma.md 5.6, 7.5):
# the engine is discovered by device-table TYPE-CODE SCAN (no
# interrupt controller exists, and the table position is
# merge-variant — boot.md 4.2's skip rule makes positional
# assumptions non-conforming); a bit-8 COPY is doorbelled and the
# guest WFIs; the stall ends with the boundary at EXACTLY C_done (the
# frozen event-wake rule, not timecmp's T+1): the handler's first
# instruction reads cycle == C_done + 1 (delivery consumed one).
# Single delivery; IRQ_ACK drops the level; masking with IE=0 defers
# but never loses the level (per-device EXTINT level-trigger rule —
# deliberate instantiation, CONFORMANCE-DELTA.md).
# DMA-C-20/21 instances.
#
# Cycle-driven, no events= line: runs under difftest today.
# Expectations hand-derived from dma.md V5; NOT from an emulator run.
#
# checks/dma_irq_wfi.py: exactly 2 doorbell DEVWs, exactly 2 EXTINT
# traps (nothing else), the FIRST trap's cycle == first doorbell DEVW
# cycle + 8 + 4096/8 exactly, 2 ack DEVWs. Change file and checker
# together.

        .org 0x1000
start:
        li r24, FAIL_ADDR

        # ---- discover the DMA engine: scan device records for
        #      type 6, parse by counts (boot.md 6) ----
        li r27, 1
        li r1, 0x800
        ldz.64 r2, [r1 + 24]           # ram_region_count
        ldz.64 r3, [r1 + 32]           # device_count
        add r4, r1, 40                 # first RAM region record
        shl.64 r2, r2, 5               # 32 bytes per region record
        add r4, r4, r2                 # first device record
scan:
        cmpeq.64 p1, r3, 0
        (p1) b fail                    # no type-6 record: fail loudly
        ldz.64 r5, [r4]
        cmpeq.64 p1, r5, 6
        (p1) b found
        add r4, r4, 64
        sub.64 r3, r3, 1
        b scan
found:
        ldz.64 r21, [r4 + 8]           # window base, low u64
        li r20, DEV_DMA_BASE           # spec-pinned reference base
        cmpeq.64 p1, r21, r20
        (!p1) b fail

        # ---- handler + descriptor: COPY, OP bit 8 set ----
        la.abs r26, h_ext
        mtsr vbase, r26
        li r10, 0x100000
        li r22, 0x101                  # OP = COPY | IRQ_ON_COMPLETE
        st.64 [r10], r22
        li r22, 0x200000
        st.64 [r10 + 8], r22
        li r22, 0x300000
        st.64 [r10 + 16], r22
        li r22, 4096
        st.64 [r10 + 24], r22
        st.64 [r10 + 32], zero
        st.64 [r10 + 40], zero
        st.64 [r10 + 48], zero
        st.64 [r10 + 56], zero
        li r22, STATUS_S + STATUS_IE
        mtsr status, r22               # unmask BEFORE the doorbell

        # ---- doorbell at X = r5+1, WFI at X+1; C_done = X+520 ----
        li r27, 2
        mfsr r5, cycle
        st.64 [r21 + 16], r10
        wfi
        # EXTINT delivered at C_done; epc = here. After the handler:
        # test 2: exactly one delivery so far
        lds.64 r19, [r24 + DMA_COUNT_SLOT - FAIL_ADDR]
        cmpeq.64 p1, r19, 1
        (!p1) b fail

        # test 3: the handler's first instruction saw cycle ==
        # C_done + 1 == (r5+1) + 520 + 1 (wake at EXACTLY C_done, then
        # one cycle for the delivery itself)
        li r27, 3
        add r6, r5, 522
        lds.64 r19, [r24 + DMA_CYCLE_SLOT - FAIL_ADDR]
        cmpeq.64 p1, r19, r6
        (!p1) b fail

        # test 4: it was an EXTINT, and the job finished: STATUS DONE,
        # COMP_CYCLE == C_done
        li r27, 4
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq.64 p1, r19, CAUSE_EXTINT
        (!p1) b fail
        ldz.64 r19, [r21 + 8]
        cmpeq.64 p1, r19, 2
        (!p1) b fail
        add r6, r5, 521
        ldz.64 r19, [r21 + 32]
        cmpeq.64 p1, r19, r6
        (!p1) b fail

        # test 5: the ack dropped the level — IE is still 1, no second
        # delivery arrives
        li r27, 5
        mov r6, r6
        mov r6, r6
        lds.64 r19, [r24 + DMA_COUNT_SLOT - FAIL_ADDR]
        cmpeq.64 p1, r19, 1
        (!p1) b fail

        # test 6: the copy actually happened
        li r27, 6
        li r12, 0x300000
        ldz.64 r19, [r12]
        cmpeq.64 p1, r19, 0            # source was zero-filled RAM
        (!p1) b fail

        # ---- leg 2: masking defers, never cancels (ISA 7.5) ----
        # test 7: bit-8 FILL with IE=0; poll to DONE; the level is
        # pending but masked — count still 1. Setting IE delivers it.
        li r27, 7
        li r22, STATUS_S
        mtsr status, r22               # mask
        li r22, 0x102                  # OP = FILL | IRQ_ON_COMPLETE
        st.64 [r10], r22
        li r22, 0xABCD
        st.64 [r10 + 8], r22           # pattern
        li r22, 0x310000
        st.64 [r10 + 16], r22
        li r22, 8
        st.64 [r10 + 24], r22
        st.64 [r21 + 16], r10
mpoll:
        ldz.64 r19, [r21 + 8]
        cmpeq.64 p1, r19, 2
        (!p1) b mpoll
        lds.64 r19, [r24 + DMA_COUNT_SLOT - FAIL_ADDR]
        cmpeq.64 p1, r19, 1            # masked: deferred, not lost
        (!p1) b fail
        li r22, STATUS_S + STATUS_IE
        mtsr status, r22               # unmask: delivers HERE
        lds.64 r19, [r24 + DMA_COUNT_SLOT - FAIL_ADDR]
        cmpeq.64 p1, r19, 2
        (!p1) b fail

        # test 8: and the fill happened
        li r27, 8
        li r12, 0x310000
        ldz.64 r19, [r12]
        li r20, 0xABCD
        cmpeq.64 p1, r19, r20
        (!p1) b fail

pass:
        li r0, PASS_MAGIC
        halt
fail:
        st.64 [r24], r27
        mov r0, r27
        halt

        # EXTINT handler: FIRST instruction samples the cycle sreg
        # (the wake-cycle pin depends on it being first), then cause,
        # count, ack, iret.
h_ext:
        mfsr k0, cycle
        st.64 [r24 + DMA_CYCLE_SLOT - FAIL_ADDR], k0
        mfsr k0, cause0
        st.64 [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR], k0
        lds.64 k0, [r24 + DMA_COUNT_SLOT - FAIL_ADDR]
        add k0, k0, 1
        st.64 [r24 + DMA_COUNT_SLOT - FAIL_ADDR], k0
        li k0, 1
        st.64 [r21 + 24], k0           # IRQ_ACK <- 1
        iret
