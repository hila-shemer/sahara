# c7_resize.s — C7 display resize via the EVENT-fed --replay path.
# Feed: tests/events/c7_resize.py; trace assertions:
# checks/c7_resize.py — the three files mirror each other, change
# them together.
#
# Coverage (display.md section 6 / V5, input.md 3.3 + 8.6): D-16
# atomic geometry update + IRQ_STATUS set, D-17 sticky flag readable
# without side effect, D-18 ack clears, 6.4 latest-wins when two
# resizes land before the guest looks (both share one cycle: applied
# in trace order), D-19 EXTINT level delivery with the 6.4 ack-first
# handler pattern (V5 steps 12-13), D-09 resizes touch no pixel, D-20
# FORMAT never changes, INPUT-17 a queued mouse event pops with its
# pre-shrink coordinates unmodified, and a post-shrink mouse word
# clamped to the new mode (8.6 E2 — the CLAMPING itself is live-mode
# behavior the feed cannot exercise, only the pop fidelity is tested;
# SPEC-ISSUES 31).
#
# NOT emulator-verified yet: expectations hand-derived from
# display.md / input.md / trace.md.
#
# Cycle math (1 cycle per retired instruction): early checks < 200,
# feed events at 5000/7000/10000/13000/15000; each wait loop starts
# thousands of cycles before its event; the pop-E1 block finishes
# near 10000, well before E2 at 13000.

        .org 0x1000
start:
        li r24, FAIL_ADDR
        li r21, DEV_DISPLAY_BASE
        li r25, DEV_MOUSE_BASE
        li r23, DEV_PIXBUF_BASE

        # test 1: IRQ_STATUS == 0 (no resize yet; V5 step 1)
        li r27, 1
        ldz.64 r19, [r21 + 40]
        cmpeq p1, r19, 0
        (!p1) b fail

        # D-09 marker: a red pixel, stored BEFORE any resize; must
        # survive every resize below untouched
        li r22, 0x00FF0000
        st.32 [r23], r22

        # wait for resize #1 (cycle 5000): poll the sticky flag
        li r27, 2
rwait1:
        ldz.64 r19, [r21 + 40]
        cmpeq p1, r19, 1
        (!p1) b rwait1

        # test 3: geometry is the event's, atomically (D-16, V5 step 4)
        li r27, 3
        ldz.64 r19, [r21 + 8]
        cmpeq p1, r19, 800
        (!p1) b fail
        ldz.64 r19, [r21 + 16]
        cmpeq p1, r19, 600
        (!p1) b fail
        ldz.64 r19, [r21 + 24]
        cmpeq p1, r19, 3200
        (!p1) b fail

        # test 4: FORMAT unchanged by resize (D-20)
        li r27, 4
        ldz.64 r19, [r21 + 32]
        cmpeq p1, r19, 1
        (!p1) b fail

        # test 5: ack clears the flag (D-18; V5 steps 5-6)
        li r27, 5
        li r22, 1
        st.64 [r21 + 48], r22
        ldz.64 r19, [r21 + 40]
        cmpeq p1, r19, 0
        (!p1) b fail

        # wait for mouse E1 (cycle 7000) — do NOT pop yet: INPUT-17
        # wants it popped after the shrink
        li r27, 6
mwait1:
        ldz.64 r19, [r25 + 8]
        cmpeq p1, r19, 1
        (!p1) b mwait1

        # wait for the double resize (both at cycle 10000)
        li r27, 7
rwait2:
        ldz.64 r19, [r21 + 40]
        cmpeq p1, r19, 1
        (!p1) b rwait2

        # test 8: latest wins — registers show 640x480x2560, the
        # SECOND same-cycle event (6.4; V5 steps 8-9); one sticky
        # flag, not two
        li r27, 8
        ldz.64 r19, [r21 + 8]
        cmpeq p1, r19, 640
        (!p1) b fail
        ldz.64 r19, [r21 + 16]
        cmpeq p1, r19, 480
        (!p1) b fail
        ldz.64 r19, [r21 + 24]
        cmpeq p1, r19, 2560
        (!p1) b fail
        li r22, 1
        st.64 [r21 + 48], r22          # ack
        ldz.64 r19, [r21 + 40]
        cmpeq p1, r19, 0
        (!p1) b fail

        # test 9: E1 pops with PRE-shrink coordinates unmodified
        # (INPUT-17): (790,590) exceeds the new 640x480 mode
        li r27, 9
        ldz.64 r19, [r25]
        li r22, 0x00000000024E0316
        cmpeq p1, r19, r22
        (!p1) b fail
        ldz.64 r19, [r25 + 8]          # queue empty again (< cycle
        cmpeq p1, r19, 0               # 13000 by construction)
        (!p1) b fail

        # wait for E2 (cycle 13000), pop: word already clamped to the
        # new mode (639,479,left) — pop fidelity only, the clamp is
        # live-mode behavior (SPEC-ISSUES 31)
        li r27, 10
mwait2:
        ldz.64 r19, [r25 + 8]
        cmpeq p1, r19, 1
        (!p1) b mwait2
        ldz.64 r19, [r25]
        li r22, 0x0000000101DF027F
        cmpeq p1, r19, r22
        (!p1) b fail

        # test 11: resize #4 (cycle 15000) arrives with IE=1: EXTINT
        # delivers (D-19); the handler acks FIRST, then reads the
        # geometry (the 6.4 race-free pattern, V5 steps 12-13),
        # stores it in EVT_SLOTS, sets EVT_FLAG.
        li r27, 11
        la.abs r19, h_ext
        mtsr vbase, r19
        li r19, STATUS_S + STATUS_IE
        mtsr status, r19
fwait:
        lds.64 r19, [r24 + EVT_FLAG - FAIL_ADDR]
        cmpeq p1, r19, 0
        (p1) b fwait
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_EXTINT
        (!p1) b fail
        lds.64 r19, [r24 + EVT_COUNT - FAIL_ADDR]
        cmpeq p1, r19, 1               # exactly one delivery
        (!p1) b fail

        # test 12: the handler saw the new geometry (800x600x3200)
        li r27, 12
        ldz.64 r19, [r24 + EVT_SLOTS - FAIL_ADDR]
        cmpeq p1, r19, 800
        (!p1) b fail
        ldz.64 r19, [r24 + EVT_SLOTS + 8 - FAIL_ADDR]
        cmpeq p1, r19, 600
        (!p1) b fail
        ldz.64 r19, [r24 + EVT_SLOTS + 16 - FAIL_ADDR]
        cmpeq p1, r19, 3200
        (!p1) b fail

        # test 13: the handler's ack stuck: flag reads 0 with no
        # further event pending
        li r27, 13
        ldz.64 r19, [r21 + 40]
        cmpeq p1, r19, 0
        (!p1) b fail

        # test 14: FORMAT STILL 1 after everything (V5 step 14)
        li r27, 14
        ldz.64 r19, [r21 + 32]
        cmpeq p1, r19, 1
        (!p1) b fail

        # test 15: the pre-resize pixel is untouched (D-09)
        li r27, 15
        ldz.32 r19, [r23]
        li r22, 0x00FF0000
        cmpeq p1, r19, r22
        (!p1) b fail

pass:
        li r0, PASS_MAGIC
        halt
fail:
        st.64 [r24], r27
        mov r0, r27
        halt

        # EXTINT handler, ack-first (display.md 6.4): store IRQ_ACK=1,
        # THEN read the geometry — never the reverse.
h_ext:
        mfsr k0, cause0
        st.64 [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR], k0
        lds.64 k0, [r24 + EVT_COUNT - FAIL_ADDR]
        add k0, k0, 1
        st.64 [r24 + EVT_COUNT - FAIL_ADDR], k0
        li k0, 1
        st.64 [r21 + 48], k0           # ack FIRST
        ldz.64 k0, [r21 + 8]
        st.64 [r24 + EVT_SLOTS - FAIL_ADDR], k0
        ldz.64 k0, [r21 + 16]
        st.64 [r24 + EVT_SLOTS + 8 - FAIL_ADDR], k0
        ldz.64 k0, [r21 + 24]
        st.64 [r24 + EVT_SLOTS + 16 - FAIL_ADDR], k0
        li k0, 1
        st.64 [r24 + EVT_FLAG - FAIL_ADDR], k0
        iret
