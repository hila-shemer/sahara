# c7_dev.s — C7 device registers, read side effects, and ordering
# (CONFORMANCE.md C7, instantiated per devspec: display.md D-01..05/
# D-07/D-08/D-13, input.md pop/sentinel/DEVERR rules, nic.md E1-E6 +
# check precedence, ISA-SPEC 9.2 rules 1-2). Runs twice from MANIFEST:
# as c7_dev (plain) and as c7_dev_ordq under --check-devorder 4 — the
# store-queue check mode must be semantics-neutral on a single CPU
# (self-loads forward, device stores drain, ISA 9.1/9.2), so the same
# image must pass identically under it.
#
# Expected register values are the devspec-pinned reference defaults
# (normative per devspec SPEC-ISSUES #12): initial mode 640x480x2560
# format 1, MAC 52:54:00:12:34:56 packed little-endian into bits 47:0
# (boot.md 3.6) = 0x0000563412005452, empty-queue DATA sentinel
# all-ones (PLATFORM-SPEC 5).
#
# Bounded coverage, deliberate: no keyboard/mouse/NIC/resize EVENTs
# (headless suite generates none — queue pop with content, drop-newest
# overflow, and the NIC translator decision tree need the device-phase
# EVENT injection fixtures); no frame-output check (PRESENT snapshots
# are asserted trace-side in checks/c7_dev.py per D-13, not against
# rendered output). NOT emulator-verified yet — expectations are
# hand-derived from the specs above.
#
# checks/c7_dev.py asserts the trace side: MEMW/DEVW classification,
# register-read MEMR values, D-13 ordering around the LAST PRESENT,
# and the trap-cause census (3 UNALIGNED + 10 DEVERR — change the
# fault section and the checker together).

        .org 0x1000
start:
        li r24, FAIL_ADDR
        li r21, DEV_DISPLAY_BASE
        li r25, DEV_PIXBUF_BASE

        # ---- 1. display registers: the reference initial mode ----
        # test 1: WIDTH == 640
        li r27, 1
        ldz.64 r19, [r21 + 8]
        cmpeq p1, r19, 640
        (!p1) b fail

        # test 2: HEIGHT == 480
        li r27, 2
        ldz.64 r19, [r21 + 16]
        cmpeq p1, r19, 480
        (!p1) b fail

        # test 3: STRIDE == 2560
        li r27, 3
        ldz.64 r19, [r21 + 24]
        cmpeq p1, r19, 2560
        (!p1) b fail

        # test 4: FORMAT == 1 (XRGB8888, the only v1.0 format; D-01)
        li r27, 4
        ldz.64 r19, [r21 + 32]
        cmpeq p1, r19, 1
        (!p1) b fail

        # test 5: IRQ_STATUS == 0 (no resize has happened)
        li r27, 5
        ldz.64 r19, [r21 + 40]
        cmpeq p1, r19, 0
        (!p1) b fail

        # test 6: reserved offset 56 reads 0 (D-05)
        li r27, 6
        ldz.64 r19, [r21 + 56]
        cmpeq p1, r19, 0
        (!p1) b fail

        # test 7: 64-bit store to the reserved offset is ignored —
        # no fault, still reads 0 (D-05, never-repurpose rule)
        li r27, 7
        li r22, 0xDEAD
        st.64 [r21 + 56], r22
        ldz.64 r19, [r21 + 56]
        cmpeq p1, r19, 0
        (!p1) b fail

        # test 8: IRQ_ACK write with nothing pending is benign;
        # IRQ_STATUS stays 0
        li r27, 8
        li r22, 1
        st.64 [r21 + 48], r22
        ldz.64 r19, [r21 + 40]
        cmpeq p1, r19, 0
        (!p1) b fail

        # ---- 2. keyboard/mouse: empty-queue pop semantics ----
        li r26, DEV_KBD_BASE

        # test 9: kbd STATUS == 0 (empty queue)
        li r27, 9
        ldz.64 r19, [r26 + 8]
        cmpeq p1, r19, 0
        (!p1) b fail

        # test 10: kbd DATA pops nothing, returns the all-ones
        # sentinel (PLATFORM-SPEC 5, input.md empty-read rule)
        li r27, 10
        ldz.64 r19, [r26]
        li r20, 0xffffffffffffffff
        cmpeq p1, r19, r20
        (!p1) b fail

        # test 11: the empty pop is idempotent — DATA again all-ones
        li r27, 11
        ldz.64 r19, [r26]
        cmpeq p1, r19, r20
        (!p1) b fail

        # test 12: ...and STATUS still 0
        li r27, 12
        ldz.64 r19, [r26 + 8]
        cmpeq p1, r19, 0
        (!p1) b fail

        li r26, DEV_MOUSE_BASE
        # test 13: mouse STATUS == 0
        li r27, 13
        ldz.64 r19, [r26 + 8]
        cmpeq p1, r19, 0
        (!p1) b fail

        # test 14: mouse DATA all-ones sentinel
        li r27, 14
        ldz.64 r19, [r26]
        li r20, 0xffffffffffffffff
        cmpeq p1, r19, r20
        (!p1) b fail

        # ---- 3. NIC registers ----
        li r26, DEV_NIC_BASE

        # test 15: TX_STATUS == 0 (always, v1.0)
        li r27, 15
        ldz.64 r19, [r26 + 8]
        cmpeq p1, r19, 0
        (!p1) b fail

        # test 16: RX_LEN == 0 (nothing received)
        li r27, 16
        ldz.64 r19, [r26 + 16]
        cmpeq p1, r19, 0
        (!p1) b fail

        # test 17: MAC == table MAC, wire octets 52:54:00:12:34:56
        # little-endian into bits 47:0 (boot.md 3.6 owns the packing)
        li r27, 17
        ldz.64 r19, [r26 + 32]
        li r20, 0x0000563412005452
        cmpeq p1, r19, r20
        (!p1) b fail

        # ---- 4. buffers are memory-like at every size (device
        #         space for ordering only; PLATFORM-SPEC 1, D-07/08) --
        # test 18: pixel byte reads 0 before its first store (D-08)
        li r27, 18
        ldz.8 r19, [r25 + 16]
        cmpeq p1, r19, 0
        (!p1) b fail

        # test 19: st128 to the pixel buffer, u64 slice readback
        li r27, 19
        li r22, 0x112233445566778899aabbccddeeff00
        st128 [r25 + 16], r22
        ldz.64 r19, [r25 + 24]
        li r20, 0x1122334455667788
        cmpeq p1, r19, r20
        (!p1) b fail

        # test 20: byte store at an odd pixel offset, byte readback
        li r27, 20
        li r22, 0xC7
        st.8 [r25 + 17], r22
        ldz.8 r19, [r25 + 17]
        cmpeq p1, r19, 0xC7
        (!p1) b fail

        # test 21: ...merged byte-exact into the surrounding u64
        li r27, 21
        ldz.64 r19, [r25 + 16]
        li r20, 0x99aabbccddeec700
        cmpeq p1, r19, r20
        (!p1) b fail

        # test 22: NIC TX buffer memory-like readback
        li r27, 22
        li r26, DEV_NIC_TXBUF
        li r22, 0x0123456789abcdef
        st.64 [r26 + 128], r22
        ldz.64 r19, [r26 + 128]
        cmpeq p1, r19, r22
        (!p1) b fail

        # test 23: NIC RX buffer is guest-writable and memory-like
        # (NIC-C-14 presupposes guest pre-fills of the RX tail)
        li r27, 23
        li r26, DEV_NIC_RXBUF
        li r22, 0x5a5a5a5a5a5a5a5a
        st.64 [r26 + 256], r22
        ldz.64 r19, [r26 + 256]
        cmpeq p1, r19, r22
        (!p1) b fail

        # ---- 5. faults: precedence and direction/offset/value
        #         DEVERRs. Census: 3 UNALIGNED + 10 DEVERR (the
        #         checker counts them — change both together). -------
        li r26, h_rec
        mtsr vbase, r26
        li r26, DEV_KBD_BASE

        # test 24: misaligned 4-byte load on a register window traps
        # UNALIGNED, not DEVERR — alignment ranks first (display.md 1
        # rule 4, nic.md 5.2, SPEC-ISSUES 25); baddr = ea
        li r27, 24
        lds.32 r19, [r26 + 2]
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_UNALIGNED
        (!p1) b fail
        lds.64 r19, [r24 + TRAP_BADDR_SLOT - FAIL_ADDR]
        li r20, DEV_KBD_BASE + 2
        cmpeq p1, r19, r20
        (!p1) b fail

        # test 25: misaligned store: UNALIGNED outranks the
        # stores-always-DEVERR input rule too
        li r27, 25
        li r22, 1
        st.32 [r26 + 6], r22
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_UNALIGNED
        (!p1) b fail

        # test 26: misaligned 64-bit load on the display window:
        # UNALIGNED outranks the 64-bit-only size rule
        li r27, 26
        lds.64 r19, [r21 + 12]
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_UNALIGNED
        (!p1) b fail
        lds.64 r19, [r24 + TRAP_BADDR_SLOT - FAIL_ADDR]
        li r20, DEV_DISPLAY_BASE + 12
        cmpeq p1, r19, r20
        (!p1) b fail

        # test 27: aligned 64-bit load at an unlisted kbd offset
        # traps DEVERR, baddr = ea (input.md rule 3)
        li r27, 27
        ldz.64 r19, [r26 + 16]
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_DEVERR
        (!p1) b fail
        lds.64 r19, [r24 + TRAP_BADDR_SLOT - FAIL_ADDR]
        li r20, DEV_KBD_BASE + 16
        cmpeq p1, r19, r20
        (!p1) b fail

        # test 28: every store to the keyboard window traps DEVERR
        # (input.md rule 2 — both registers are read-only)
        li r27, 28
        li r22, 1
        st.64 [r26], r22
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_DEVERR
        (!p1) b fail

        # test 29: same for the mouse window
        li r27, 29
        li r26, DEV_MOUSE_BASE
        st.64 [r26 + 8], r22
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_DEVERR
        (!p1) b fail

        # test 30: reading the write-only PRESENT traps DEVERR (D-03)
        li r27, 30
        ldz.64 r19, [r21]
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_DEVERR
        (!p1) b fail

        # test 31: writing the read-only WIDTH traps DEVERR (D-04)...
        li r27, 31
        li r22, 123
        st.64 [r21 + 8], r22
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_DEVERR
        (!p1) b fail

        # test 32: ...and WIDTH is unchanged afterwards
        li r27, 32
        ldz.64 r19, [r21 + 8]
        cmpeq p1, r19, 640
        (!p1) b fail

        li r26, DEV_NIC_BASE
        # test 33: reading the write-only TX_DOORBELL traps DEVERR (E3)
        li r27, 33
        ldz.64 r19, [r26]
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_DEVERR
        (!p1) b fail

        # test 34: RX_POP while RX_LEN == 0 traps DEVERR (E6),
        # pops nothing
        li r27, 34
        li r22, 1
        st.64 [r26 + 24], r22
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_DEVERR
        (!p1) b fail
        ldz.64 r19, [r26 + 16]     # RX_LEN still 0
        cmpeq p1, r19, 0
        (!p1) b fail

        # test 35: aligned 64-bit load at an unlisted NIC register
        # offset traps DEVERR (E2)
        li r27, 35
        ldz.64 r19, [r26 + 40]
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_DEVERR
        (!p1) b fail

        # test 36: TX_DOORBELL value below 60 traps DEVERR (E5),
        # baddr = the doorbell address, nothing transmitted
        li r27, 36
        li r22, 59
        st.64 [r26], r22
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_DEVERR
        (!p1) b fail
        lds.64 r19, [r24 + TRAP_BADDR_SLOT - FAIL_ADDR]
        li r20, DEV_NIC_BASE
        cmpeq p1, r19, r20
        (!p1) b fail

        # test 37: TX_DOORBELL value above 1514 traps DEVERR (E5)
        li r27, 37
        li r22, 1515
        st.64 [r26], r22
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_DEVERR
        (!p1) b fail

        # ---- 6. a valid doorbell: synchronous, silent transmit ----
        # Zero the first 64 TX bytes explicitly (do not rely on reset
        # state), doorbell a minimum-length frame. The all-zero frame
        # matches nothing in the translator decision tree (nic.md 6):
        # dropped, no reply, no fault. TX_STATUS stays 0 (synchronous
        # transmit, PLATFORM-SPEC 7), RX_LEN stays 0.
        li r27, 38
        li r26, DEV_NIC_TXBUF
        st.64 [r26], zero
        st.64 [r26 + 8], zero
        st.64 [r26 + 16], zero
        st.64 [r26 + 24], zero
        st.64 [r26 + 32], zero
        st.64 [r26 + 40], zero
        st.64 [r26 + 48], zero
        st.64 [r26 + 56], zero
        li r26, DEV_NIC_BASE
        li r22, 60
        st.64 [r26], r22           # transmit; no trap expected
        ldz.64 r19, [r26 + 8]      # TX_STATUS == 0
        cmpeq p1, r19, 0
        (!p1) b fail
        ldz.64 r19, [r26 + 16]     # RX_LEN == 0: no reply to garbage
        cmpeq p1, r19, 0
        (!p1) b fail

        # ---- 7. ordering: store queue forwarding + drain ----------
        # Six RAM stores (deeper than the ordq run's queue of 4),
        # each read back immediately: ISA 9.1 program order w.r.t.
        # the processor itself — a store queue must forward. Then a
        # device store (PRESENT) drains per ISA 9.2 rule 1 and the
        # values must still read back.
        li r27, 39
        li r26, ORDQ_SLOTS
        li r22, 0x1111
        st.64 [r26], r22
        ldz.64 r19, [r26]
        cmpeq p1, r19, r22
        (!p1) b fail
        li r22, 0x2222
        st.64 [r26 + 8], r22
        li r22, 0x3333
        st.64 [r26 + 16], r22
        li r22, 0x4444
        st.64 [r26 + 24], r22
        li r22, 0x5555
        st.64 [r26 + 32], r22
        li r22, 0x6666
        st.64 [r26 + 40], r22
        ldz.64 r19, [r26 + 8]      # forward from a full queue
        cmpeq p1, r19, 0x2222
        (!p1) b fail
        st.64 [r21], zero          # PRESENT: drains the queue
        ldz.64 r19, [r26 + 40]
        cmpeq p1, r19, 0x6666
        (!p1) b fail
        ldz.64 r19, [r26]
        cmpeq p1, r19, 0x1111
        (!p1) b fail

        # ---- 8. D-13: pixel stores before PRESENT, one after ------
        # This is the LAST touch of the pixel window in the program;
        # checks/c7_dev.py splits the trace at the LAST PRESENT DEVW
        # and asserts the pre/post write sets. Values are XRGB pixels
        # (byte 0 = B, 1 = G, 2 = R, 3 = X).
        li r27, 40
        li r22, 0x00FF0000         # red pixel at (0,0)
        st.32 [r25], r22
        li r22, 0x0000FF00         # green pixel at (0,1)
        st.32 [r25 + 4], r22
        st.64 [r21], zero          # PRESENT (value ignored, D-14)
        li r22, 0x000000FF         # blue pixel AFTER the present
        st.32 [r25 + 8], r22
        ldz.64 r19, [r25]          # readback survives the present
        li r20, 0x0000FF0000FF0000
        cmpeq p1, r19, r20
        (!p1) b fail

pass:
        li r0, PASS_MAGIC
        halt
fail:
        st.64 [r24], r27
        mov r0, r27
        halt

        # record cause/baddr/epc/status, skip the faulter
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
