# c7_rng_prng.s — C7 RNG PRNG mode (devspec/rng.md 5: RNG-13..17).
# No events= line: this is a pure register-model test, so it runs in
# the difftest gate and needs no --replay. Self-checking; no trace
# checker.
#
# The expected outputs are the rng.md 11.3 SplitMix64 tables,
# hand-derived from the spec's algorithm by an independent one-off
# script (python bigints, masked to 64 bits per step) — NEVER from
# either emulator. Seed 0 first outputs: E220A8397B1DCDAF,
# 6E789E6AA1B965F4, 06C45D188009454F, F88BB8A8724C81EC,
# 1B39896A51A8749B, 53CB9F0C747EA2EA, 2C829ABE1F4532E1,
# C584133AC916AB3C. Seed 123456789ABCDEF0: 161922C645CE50E8,
# AD760CAFA1697B60.
#
# Replay-safety is structural (rng.md 5.3): every MODE/SEED change
# below is a DEVW-traced store in this instruction stream — there is
# nothing else that could switch modes, which is the point.

        .org 0x1000
start:
        li r24, FAIL_ADDR
        li r26, DEV_RNG_BASE

        # test 1: reset — QUEUE mode, IE off, empty well
        li r27, 1
        ldz.64 r19, [r26 + 16]
        cmpeq p1, r19, 0
        (!p1) b fail
        ldz.64 r19, [r26 + 8]
        cmpeq p1, r19, 0
        (!p1) b fail

        # test 2: SEED written in QUEUE mode, then MODE=1: the stream
        # starts from that seed (RNG-14) — first pop is P1
        li r27, 2
        st.64 [r26 + 24], zero     # SEED = 0
        li r22, 1
        st.64 [r26 + 16], r22      # CTRL = 1: PRNG mode
        ldz.64 r19, [r26 + 16]
        cmpeq p1, r19, 1
        (!p1) b fail
        ldz.64 r19, [r26]          # PRNG pop 1 — depth is 0 and this
        li r22, 0xE220A8397B1DCDAF # does NOT trap (no E6 in PRNG mode)
        cmpeq p1, r19, r22
        (!p1) b fail

        # test 3: outputs 2 and 3
        li r27, 3
        ldz.64 r19, [r26]
        li r22, 0x6E789E6AA1B965F4
        cmpeq p1, r19, r22
        (!p1) b fail
        ldz.64 r19, [r26]
        li r22, 0x06C45D188009454F
        cmpeq p1, r19, r22
        (!p1) b fail

        # test 4: STATUS untouched by PRNG pops (RNG-16)
        li r27, 4
        ldz.64 r19, [r26 + 8]
        cmpeq p1, r19, 0
        (!p1) b fail

        # test 5: a squashed PRNG pop advances nothing — the next real
        # pop is still output 4 (rng.md 2 rule 6)
        li r27, 5
        cmpeq p2, zero, 1          # p2 <- false
        (p2) ldz.64 r19, [r26]     # squashed: no state advance
        ldz.64 r19, [r26]
        li r22, 0xF88BB8A8724C81EC
        cmpeq p1, r19, r22
        (!p1) b fail

        # test 6: MODE flips both ways lose nothing (RNG-15): after
        # 1 -> 0 -> 1 the stream continues at output 5
        li r27, 6
        st.64 [r26 + 16], zero     # back to QUEUE mode
        ldz.64 r19, [r26 + 16]
        cmpeq p1, r19, 0
        (!p1) b fail
        li r22, 1
        st.64 [r26 + 16], r22      # and back to PRNG
        ldz.64 r19, [r26]
        li r22, 0x1B39896A51A8749B
        cmpeq p1, r19, r22
        (!p1) b fail

        # test 7: outputs 6..8 round out the table
        li r27, 7
        ldz.64 r19, [r26]
        li r22, 0x53CB9F0C747EA2EA
        cmpeq p1, r19, r22
        (!p1) b fail
        ldz.64 r19, [r26]
        li r22, 0x2C829ABE1F4532E1
        cmpeq p1, r19, r22
        (!p1) b fail
        ldz.64 r19, [r26]
        li r22, 0xC584133AC916AB3C
        cmpeq p1, r19, r22
        (!p1) b fail

        # test 8: reseed restarts with the new seed's stream
        li r27, 8
        li r22, 0x123456789ABCDEF0
        st.64 [r26 + 24], r22
        ldz.64 r19, [r26]
        li r22, 0x161922C645CE50E8
        cmpeq p1, r19, r22
        (!p1) b fail
        ldz.64 r19, [r26]
        li r22, 0xAD760CAFA1697B60
        cmpeq p1, r19, r22
        (!p1) b fail

        # test 9: reseeding 0 restarts the seed-0 stream (RNG-13)
        li r27, 9
        st.64 [r26 + 24], zero
        ldz.64 r19, [r26]
        li r22, 0xE220A8397B1DCDAF
        cmpeq p1, r19, r22
        (!p1) b fail

        # test 10: IE is a plain read-write bit alongside MODE
        li r27, 10
        li r22, 3
        st.64 [r26 + 16], r22      # PRNG + IE; depth 0, so no EXTINT
        ldz.64 r19, [r26 + 16]     # contribution exists even were
        cmpeq p1, r19, 3           # status.IE on (it is not)
        (!p1) b fail
        li r22, 2
        st.64 [r26 + 16], r22
        ldz.64 r19, [r26 + 16]
        cmpeq p1, r19, 2
        (!p1) b fail
        st.64 [r26 + 16], zero
        ldz.64 r19, [r26 + 16]
        cmpeq p1, r19, 0
        (!p1) b fail

pass:
        li r0, PASS_MAGIC
        halt
fail:
        st.64 [r24], r27
        mov r0, r27
        halt
