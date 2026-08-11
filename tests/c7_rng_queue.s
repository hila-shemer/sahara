# c7_rng_queue.s — C7 RNG queue pops WITH CONTENT via the EVENT-fed
# --replay path. Feed: tests/events/c7_rng_queue.py; trace assertions:
# checks/c7_rng_queue.py — the three files mirror each other, change
# them together.
#
# Coverage (devspec/rng.md): RNG-18 boundary visibility (STATUS reads
# 0 before cycle 5000, and the two same-cycle records land as one
# 0 -> 4 jump), RNG-02 FIFO order + STATUS decrement, RNG-03 STATUS
# has no side effect, RNG-10 predicated-false pop pops nothing,
# RNG-21 WFI wake at EXACTLY the event cycle with CTRL.IE = 0 (the
# mfsr-cycle compare is the cycle-exact assertion), and the rng.md 3
# STATUS-then-pop consumer contract throughout — no pop here ever
# races the count, and no E6 can fire.
#
# IE stays off at both levels (status.IE and CTRL.IE): the trap
# census is empty. NOT emulator-verified when written: expectations
# hand-derived from rng.md 4 and the 11.2 S-1 script.

        .org 0x1000
start:
        li r24, FAIL_ADDR
        li r26, DEV_RNG_BASE

        # test 1: STATUS == 0 before cycle 5000 (RNG-18: events with a
        # future cycle are invisible; we run at cycle < 200 here)
        li r27, 1
        ldz.64 r19, [r26 + 8]
        cmpeq p1, r19, 0
        (!p1) b fail

        # test 2: CTRL reads 0 (QUEUE mode) — and stays 0 all test
        li r27, 2
        ldz.64 r19, [r26 + 16]
        cmpeq p1, r19, 0
        (!p1) b fail

        # wait for batch A: both records share cycle 5000, so the
        # first nonzero STATUS read must already be 4 (rng.md 4.3 —
        # one boundary, no intermediate depth)
        li r27, 3
qwait:
        ldz.64 r19, [r26 + 8]
        cmpeq p1, r19, 0
        (p1) b qwait
        cmpeq p1, r19, 4
        (!p1) b fail

        # test 4: STATUS load has no side effect (RNG-03): still 4
        li r27, 4
        ldz.64 r19, [r26 + 8]
        cmpeq p1, r19, 4
        (!p1) b fail

        # test 5: predicated-false DATA load pops nothing (RNG-10)
        li r27, 5
        cmpeq p2, zero, 1          # p2 <- false
        (p2) ldz.64 r19, [r26]     # squashed: no device access
        ldz.64 r19, [r26 + 8]
        cmpeq p1, r19, 4
        (!p1) b fail

        # tests 6-9: FIFO pops in arrival order (RNG-02), STATUS
        # decrementing 4 -> 3 -> 2 -> 1 -> 0 after each pop
        li r27, 6
        ldz.64 r19, [r26]          # pop 1
        li r22, 0xD1CE00000000A001
        cmpeq p1, r19, r22
        (!p1) b fail
        ldz.64 r19, [r26 + 8]
        cmpeq p1, r19, 3
        (!p1) b fail

        li r27, 7
        ldz.64 r19, [r26]          # pop 2
        li r22, 0xD1CE00000000A002
        cmpeq p1, r19, r22
        (!p1) b fail
        ldz.64 r19, [r26 + 8]
        cmpeq p1, r19, 2
        (!p1) b fail

        li r27, 8
        ldz.64 r19, [r26]          # pop 3
        li r22, 0xD1CE00000000A003
        cmpeq p1, r19, r22
        (!p1) b fail
        ldz.64 r19, [r26 + 8]
        cmpeq p1, r19, 1
        (!p1) b fail

        li r27, 9
        ldz.64 r19, [r26]          # pop 4
        li r22, 0xD1CE00000000A004
        cmpeq p1, r19, r22
        (!p1) b fail
        ldz.64 r19, [r26 + 8]      # drained — and we STOP popping:
        cmpeq p1, r19, 0           # a fifth pop would be E6 by design
        (!p1) b fail

        # test 10: WFI with no timer and IE off everywhere — the
        # cycle-20000 feed record is the only wake source, and the
        # wake lands at EXACTLY its cycle (RNG-21, frozen rule)
        li r27, 10
        wfi
        mfsr r19, cycle
        li r22, 20000
        cmpeq p1, r19, r22
        (!p1) b fail
        ldz.64 r19, [r26 + 8]      # applied at the woken boundary
        cmpeq p1, r19, 2
        (!p1) b fail

        # tests 11-12: batch B pops in order
        li r27, 11
        ldz.64 r19, [r26]
        li r22, 0xD1CE00000000B001
        cmpeq p1, r19, r22
        (!p1) b fail

        li r27, 12
        ldz.64 r19, [r26]
        li r22, 0xD1CE00000000B002
        cmpeq p1, r19, r22
        (!p1) b fail
        ldz.64 r19, [r26 + 8]
        cmpeq p1, r19, 0
        (!p1) b fail

pass:
        li r0, PASS_MAGIC
        halt
fail:
        st.64 [r24], r27
        mov r0, r27
        halt
