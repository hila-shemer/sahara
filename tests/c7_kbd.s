# c7_kbd.s — C7 input-queue pop WITH CONTENT, via the EVENT-fed
# --replay path (the CLI's only headless event source). Feed:
# tests/events/c7_kbd.py; trace assertions: checks/c7_kbd.py — the
# three files mirror each other, change them together.
#
# Coverage (input.md): INPUT-21 boundary visibility (STATUS reads 0
# before the events' cycle), INPUT-02 FIFO order + STATUS decrement,
# INPUT-03 STATUS has no side effect, INPUT-08 predicated-false pop
# pops nothing, the 8.2 Shift+A pop sequence (KV-06/01/02/07) ending
# in the all-ones sentinel, queue independence (mouse untouched by kbd
# pops), INPUT-20 EXTINT level delivery + drain-to-deassert using the
# input.md section 5 canonical lds.64/cmpeq -1 drain loop, and the 8.3
# MV-01/MV-02 mouse words.
#
# Bounded coverage, deliberate: live-mode generation rules (INPUT-10..
# 12/16/19 alternation-and-dedup, INPUT-15 clamping) are host-input
# translation behavior — a replay feed carries finished event words
# verbatim and cannot exercise them (SPEC-ISSUES 31). NOT
# emulator-verified yet: expectations hand-derived from input.md /
# trace.md.
#
# Cycle math (1 cycle per retired instruction, ISA-SPEC 4): the early
# checks run at cycle < 200 << 5000 (first kbd event); the mouse batch
# at 10000 is polled for after the kbd phase (~cycle 5100).

        .org 0x1000
start:
        li r24, FAIL_ADDR
        li r26, DEV_KBD_BASE
        li r25, DEV_MOUSE_BASE
        li r20, 0xffffffffffffffff     # ldz.64 sentinel image

        # test 1: kbd STATUS == 0 before cycle 5000 (INPUT-21:
        # events with a future cycle are invisible)
        li r27, 1
        ldz.64 r19, [r26 + 8]
        cmpeq p1, r19, 0
        (!p1) b fail

        # test 2: mouse STATUS == 0 too (its batch is at 10000)
        li r27, 2
        ldz.64 r19, [r25 + 8]
        cmpeq p1, r19, 0
        (!p1) b fail

        # test 3: ...and an empty-queue pop returns the sentinel
        # without disturbing anything (INPUT-01; also gives the trace
        # a mouse-DATA sentinel read BEFORE the mouse events exist)
        li r27, 3
        ldz.64 r19, [r25]
        cmpeq p1, r19, r20
        (!p1) b fail

        # wait for the kbd batch: poll until all 4 events (cycles
        # 5000..5002) are visible. STATUS can only grow to 4.
        li r27, 4
kwait:
        ldz.64 r19, [r26 + 8]
        cmpeq p1, r19, 4
        (!p1) b kwait

        # test 5: STATUS load has no side effect (INPUT-03): still 4
        li r27, 5
        ldz.64 r19, [r26 + 8]
        cmpeq p1, r19, 4
        (!p1) b fail

        # test 6: predicated-false DATA load pops nothing (INPUT-08,
        # FV-12): STATUS still 4 afterwards
        li r27, 6
        cmpeq p2, zero, 1              # p2 <- false
        (p2) ldz.64 r19, [r26]         # squashed: no device access
        ldz.64 r19, [r26 + 8]
        cmpeq p1, r19, 4
        (!p1) b fail

        # tests 7-10: the 8.2 Shift+A sequence pops in generation
        # order (INPUT-02), STATUS decrementing 4->3->2->1->0
        li r27, 7
        ldz.64 r19, [r26]              # pop 1: LShift press (KV-06)
        li r22, 0x00000001000000E1
        cmpeq p1, r19, r22
        (!p1) b fail
        ldz.64 r19, [r26 + 8]
        cmpeq p1, r19, 3
        (!p1) b fail

        li r27, 8
        ldz.64 r19, [r26]              # pop 2: A press (KV-01)
        li r22, 0x0000000100000004
        cmpeq p1, r19, r22
        (!p1) b fail

        li r27, 9
        ldz.64 r19, [r26]              # pop 3: A release (KV-02)
        li r22, 0x0000000000000004
        cmpeq p1, r19, r22
        (!p1) b fail

        li r27, 10
        ldz.64 r19, [r26]              # pop 4: LShift release (KV-07)
        li r22, 0x00000000000000E1
        cmpeq p1, r19, r22
        (!p1) b fail
        ldz.64 r19, [r26 + 8]          # queue drained
        cmpeq p1, r19, 0
        (!p1) b fail

        # test 11: pop 5 hits the sentinel (8.2 row 5)
        li r27, 11
        ldz.64 r19, [r26]
        cmpeq p1, r19, r20
        (!p1) b fail

        # wait for the mouse batch: both MV-01/MV-02 share cycle
        # 10000, so STATUS jumps 0 -> 2 atomically (input.md 4.3)
        li r27, 12
mwait:
        ldz.64 r19, [r25 + 8]
        cmpeq p1, r19, 0
        (p1) b mwait
        cmpeq p1, r19, 2               # never 1: one boundary, both in
        (!p1) b fail

        # test 13: EXTINT is pending (STATUS != 0, INPUT-20); enable
        # IE and it must deliver before the next instruction. The
        # handler drains the mouse queue (canonical input.md 5 loop)
        # into EVT_SLOTS and counts pops in r18.
        li r27, 13
        li r16, EVT_SLOTS
        li r17, DEV_MOUSE_BASE
        li r18, 0                      # drain count
        li r19, h_ext
        mtsr vbase, r19
        li r19, STATUS_S + STATUS_IE
        mtsr status, r19               # EXTINT delivers HERE
        # after iret: exactly one delivery, cause EXTINT
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_EXTINT
        (!p1) b fail

        # test 14: the handler drained exactly 2 events, in order:
        # MV-01 then MV-02 (input.md 8.3)
        li r27, 14
        cmpeq p1, r18, 2
        (!p1) b fail
        # (r16 advanced in the handler; read the slots r24-relative)
        ldz.64 r19, [r24 + EVT_SLOTS - FAIL_ADDR]
        li r22, 0x0000000100C80064     # MV-01 (100,200,left)
        cmpeq p1, r19, r22
        (!p1) b fail

        li r27, 15
        ldz.64 r19, [r24 + EVT_SLOTS + 8 - FAIL_ADDR]
        li r22, 0x0000000000C80064     # MV-02 (100,200,none)
        cmpeq p1, r19, r22
        (!p1) b fail

        # test 16: draining deasserted EXTINT (INPUT-20) — we are
        # running with IE=1 and no second delivery happened; both
        # queues read empty
        li r27, 16
        ldz.64 r19, [r25 + 8]
        cmpeq p1, r19, 0
        (!p1) b fail
        ldz.64 r19, [r26 + 8]
        cmpeq p1, r19, 0
        (!p1) b fail
        lds.64 r19, [r24 + EVT_COUNT - FAIL_ADDR]
        cmpeq p1, r19, 1               # exactly one EXTINT delivery
        (!p1) b fail

pass:
        li r0, PASS_MAGIC
        halt
fail:
        st.64 [r24], r27
        mov r0, r27
        halt

        # EXTINT handler: record cause, count deliveries, drain the
        # mouse queue with the input.md section 5 canonical loop
        # (lds.64 sign-extends the all-ones sentinel to -1), storing
        # popped words at [r16], advancing r16, counting in r18.
h_ext:
        mfsr k0, cause0
        st.64 [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR], k0
        lds.64 k0, [r24 + EVT_COUNT - FAIL_ADDR]
        add k0, k0, 1
        st.64 [r24 + EVT_COUNT - FAIL_ADDR], k0
hd_loop:
        lds.64 k0, [r17]               # DATA: pop
        cmpeq p3, k0, -1               # sentinel?
        (p3) b hd_done
        st.64 [r16], k0
        add r16, r16, 8
        add r18, r18, 1
        b hd_loop
hd_done:
        iret
