# c0_smoke — harness smoke test: the fail/pass protocol itself, basic
# ALU, memory readback, branching. Not a conformance group; exists so a
# broken harness or emulator CLI fails here, loudly, before C1-C7 run.
# Conventions: tests/README.md (r24 = 0x700, r27 = test ID).

        .org 0x1000
start:
        li r24, 0x700
        li r27, 1

        # 2 + 3 == 5, 32-bit
        add.32 r1, zero, 2
        add.32 r2, zero, 3
        add.32 r3, r1, r2
        li r4, 5
        cmpeq p1, r3, r4
        (!p1) b fail

        # store/readback through the sentinel box
        li r27, 2
        st.64 r3, [r24 + 0x18]
        lds.64 r5, [r24 + 0x18]
        cmpeq p1, r5, r4
        (!p1) b fail

        # backward branch actually taken: loop 3 times
        li r27, 3
        li r6, 3
        li r7, 0
loop:
        add r7, r7, 1
        sub r6, r6, 1
        cmpeq p1, r6, 0
        (!p1) b loop
        li r8, 3
        cmpeq p1, r7, r8
        (!p1) b fail

pass:
        li r0, 0x600D
        halt
fail:
        st.64 r27, [r24]
        mov r0, r27
        halt
