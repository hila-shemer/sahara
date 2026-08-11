# c7_rng_irq.s — C7 RNG IE-qualified level interrupt (devspec/rng.md
# 6: RNG-20, RNG-21). Feed: tests/events/c7_rng_irq.py; trace
# assertions: checks/c7_rng_irq.py — the three files mirror each
# other, change them together.
#
# Coverage: depth > 0 with CTRL.IE = 0 delivers nothing even with
# status.IE = 1 (reset-off keeps the device invisible to old
# kernels); setting CTRL.IE with depth > 0 delivers EXTINT before the
# next instruction; the handler drains STATUS-then-pop (rng.md 3) and
# the level deasserts at depth 0 with no ack register; a WFI with
# CTRL.IE back off still wakes at EXACTLY the feed event's cycle (the
# record itself is the wake source, IE-independent) and no delivery
# happens.
#
# Census: exactly one EXTINT. NOT emulator-verified when written:
# expectations hand-derived from rng.md 6 and the 11.6 S-3 script.

        .org 0x1000
start:
        li r24, FAIL_ADDR
        li r25, DEV_RNG_BASE
        li r16, EVT_SLOTS          # handler drain cursor
        li r17, DEV_RNG_BASE       # handler window base
        li r18, 0                  # handler drain count
        la.abs r19, h_ext
        mtsr vbase, r19
        li r19, STATUS_S + STATUS_IE
        mtsr status, r19           # machine-level IE on from the start

        # test 1: nothing visible before cycle 5000
        li r27, 1
        ldz.64 r19, [r25 + 8]
        cmpeq p1, r19, 0
        (!p1) b fail

        # wait for the 2-word batch; status.IE is ON the whole time,
        # CTRL.IE is 0 — if depth alone asserted EXTINT we would trap
        # into the handler and EVT_COUNT would show it
        li r27, 2
iwait:
        ldz.64 r19, [r25 + 8]
        cmpeq p1, r19, 0
        (p1) b iwait
        cmpeq p1, r19, 2
        (!p1) b fail

        # test 3: still no delivery after the wait loop's many
        # boundaries (RNG-20 negative half)
        li r27, 3
        lds.64 r19, [r24 + EVT_COUNT - FAIL_ADDR]
        cmpeq p1, r19, 0
        (!p1) b fail

        # test 4: CTRL.IE = 1 with depth 2 -> EXTINT delivers HERE,
        # before the next instruction; the handler drains both words
        li r27, 4
        li r22, 2
        st.64 [r25 + 16], r22      # CTRL = IE, QUEUE mode
        lds.64 r19, [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR]
        cmpeq p1, r19, CAUSE_EXTINT
        (!p1) b fail
        lds.64 r19, [r24 + EVT_COUNT - FAIL_ADDR]
        cmpeq p1, r19, 1           # exactly one delivery
        (!p1) b fail
        cmpeq p1, r18, 2           # handler popped exactly depth
        (!p1) b fail

        # test 5: the drained words, in arrival order
        li r27, 5
        ldz.64 r19, [r24 + EVT_SLOTS - FAIL_ADDR]
        li r22, 0x1BAD5EED00000001
        cmpeq p1, r19, r22
        (!p1) b fail
        ldz.64 r19, [r24 + EVT_SLOTS + 8 - FAIL_ADDR]
        li r22, 0x1BAD5EED00000002
        cmpeq p1, r19, r22
        (!p1) b fail

        # test 6: level deasserted by the drain (depth 0, IE still 1,
        # status.IE still 1): we are executing, and no second delivery
        # has bumped the count
        li r27, 6
        ldz.64 r19, [r25 + 8]
        cmpeq p1, r19, 0
        (!p1) b fail
        lds.64 r19, [r24 + EVT_COUNT - FAIL_ADDR]
        cmpeq p1, r19, 1
        (!p1) b fail

        # test 7: CTRL.IE back off, then WFI: the cycle-30000 feed
        # record is the only wake source and lands at EXACTLY 30000
        # (RNG-21) — with IE off it wakes but does not deliver
        li r27, 7
        st.64 [r25 + 16], zero     # CTRL = 0
        wfi
        mfsr r19, cycle
        li r22, 30000
        cmpeq p1, r19, r22
        (!p1) b fail
        ldz.64 r19, [r25 + 8]      # the word is already visible
        cmpeq p1, r19, 1
        (!p1) b fail
        lds.64 r19, [r24 + EVT_COUNT - FAIL_ADDR]
        cmpeq p1, r19, 1           # no delivery on the IE-off wake
        (!p1) b fail

        # test 8: pop it (STATUS said 1), then IE on with depth 0:
        # nothing pends, nothing delivers (RNG-20 deassert half)
        li r27, 8
        ldz.64 r19, [r25]
        li r22, 0x1BAD5EED00000003
        cmpeq p1, r19, r22
        (!p1) b fail
        li r22, 2
        st.64 [r25 + 16], r22      # IE on, well empty
        lds.64 r19, [r24 + EVT_COUNT - FAIL_ADDR]
        cmpeq p1, r19, 1
        (!p1) b fail

pass:
        li r0, PASS_MAGIC
        halt
fail:
        st.64 [r24], r27
        mov r0, r27
        halt

        # EXTINT handler: record cause, count deliveries, drain the
        # rng queue STATUS-then-pop (rng.md 3 — the well has no
        # sentinel, so the count IS the loop bound), words to
        # [r16], count in r18.
h_ext:
        mfsr k0, cause0
        st.64 [r24 + TRAP_CAUSE_SLOT - FAIL_ADDR], k0
        lds.64 k0, [r24 + EVT_COUNT - FAIL_ADDR]
        add k0, k0, 1
        st.64 [r24 + EVT_COUNT - FAIL_ADDR], k0
        ldz.64 k0, [r17 + 8]       # STATUS: the pop budget
he_loop:
        cmpeq p3, k0, 0
        (p3) b he_done
        lds.64 r26, [r17]          # DATA pop (r26 = handler scratch)
        st.64 [r16], r26
        add r16, r16, 8
        add r18, r18, 1
        sub k0, k0, 1
        b he_loop
he_done:
        iret
