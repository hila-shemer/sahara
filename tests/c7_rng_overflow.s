# c7_rng_overflow.s — C7 RNG truncate-to-fit past the 256-word cap
# (devspec/rng.md 4.2: RNG-19, and the recorded-equals-accepted rule
# RNG-R2 asserted trace-side). Feed: tests/events/c7_rng_overflow.py;
# trace assertions: checks/c7_rng_overflow.py — the three files mirror
# each other, change them together.
#
# The feed delivers 264 words + an 8-word batch at depth 256, all at
# cycle 5000. The guest sees: STATUS capped at exactly 256 (never
# more, never an intermediate value — one boundary), then a full
# STATUS-then-pop drain returning EXACTLY the first 256 accepted words
# w(i) = 0xC0FFEE0000000000 + i, recomputed here with one add per
# iteration. The truncated tail and the zero-accepted batch must never
# be observable. No WFI anywhere: a zero-accepted arrival leaves no
# record, so it must never be a wake source (rng.md 7.3 note).
#
# The drain count lands at RNG_SCRATCH (0x7c0) as a u64 so the checker
# can cross-check 256 from the trace. IE off throughout: empty census.
#
# NOT emulator-verified when written: expectations hand-derived from
# rng.md 4.2 and vector V-B.

        .org 0x1000
start:
        li r24, FAIL_ADDR
        li r26, DEV_RNG_BASE

        # test 1: nothing visible before cycle 5000
        li r27, 1
        ldz.64 r19, [r26 + 8]
        cmpeq p1, r19, 0
        (!p1) b fail

        # wait for the batch: the whole 4-record pile applies at one
        # boundary, so the first nonzero STATUS read is already the
        # 256 cap (RNG-19: never 264, never a partial)
        li r27, 2
owait:
        ldz.64 r19, [r26 + 8]
        cmpeq p1, r19, 0
        (p1) b owait
        cmpeq p1, r19, 256
        (!p1) b fail

        # test 3: drain all 256, comparing each pop against the
        # recomputed accepted stream w(i) = BASE + i (FIFO order
        # proves acceptance was the PREFIX of each record)
        li r27, 3
        li r22, 0xC0FFEE0000000000 # expected word
        li r18, 0                  # drain count
dloop:
        ldz.64 r19, [r26]          # pop
        cmpeq p1, r19, r22
        (!p1) b fail
        add r22, r22, 1
        add r18, r18, 1
        cmpltu p1, r18, 256
        (p1) b dloop

        # test 4: exactly empty now — the discarded 8 + 8 words do not
        # exist anywhere (and we stop popping: E6 would be next)
        li r27, 4
        ldz.64 r19, [r26 + 8]
        cmpeq p1, r19, 0
        (!p1) b fail
        li r21, RNG_SCRATCH
        st.64 [r21], r18           # drain count for the checker: 256

pass:
        li r0, PASS_MAGIC
        halt
fail:
        st.64 [r24], r27
        mov r0, r27
        halt
