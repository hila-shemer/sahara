# c7_kbd_ovf.s — C7 keyboard queue overflow, the input.md 8.5
# scenario (INPUT-18), via the EVENT-fed --replay path. Feed:
# tests/events/c7_kbd_ovf.py; trace assertions:
# checks/c7_kbd_ovf.py — the three files mirror each other, change
# them together.
#
# 257 events arrive at one cycle: 128 press/release pairs of key A
# fill the exactly-256 queue (input.md 4.1), the 257th is dropped-
# newest. Guest-visible: STATUS jumps 0 -> 256 (never 257), the 256
# pops return the strict press/release alternation with STATUS
# decrementing 255..0 at each step (INPUT-02), the dropped press is
# absent, and pop 257 returns the all-ones sentinel. The drop itself
# is trace-visible (flags bit 0 on EVENT record 257) — asserted by
# the checker, and by replay byte-identity recomputing the drop
# (trace.md 5.4).
#
# Bounded coverage, deliberate: INPUT-19 (the generation state
# advancing past a dropped event) constrains live-mode generation,
# which a feed cannot exercise (SPEC-ISSUES 31). NOT
# emulator-verified yet: expectations hand-derived from input.md.

        .org 0x1000
start:
        li r24, FAIL_ADDR
        li r26, DEV_KBD_BASE

        # test 1: STATUS == 0 before cycle 5000 (INPUT-21)
        li r27, 1
        ldz.64 r19, [r26 + 8]
        cmpeq p1, r19, 0
        (!p1) b fail

        # test 2: poll until the batch lands; the first nonzero
        # STATUS must be exactly 256 (whole batch at one boundary,
        # 257th dropped — INPUT-18)
        li r27, 2
owait:
        ldz.64 r19, [r26 + 8]
        cmpeq p1, r19, 0
        (p1) b owait
        cmpeq p1, r19, 256
        (!p1) b fail

        # test 3: 256 pops, strict alternation press/release of A
        # (even index: press 0x1_00000004, odd: release 0x4), STATUS
        # reading 255 - i after pop i
        li r27, 3
        li r23, 0                      # pop index i
        li r20, 0x0000000100000004     # press word (KV-01)
        li r22, 0x0000000000000004     # release word (KV-02)
poploop:
        ldz.64 r19, [r26]              # pop i
        and r17, r23, 1
        cmpeq p2, r17, 0               # p2 <- (i even)
        (p2) cmpeq p1, r19, r20        # even: expect press
        (!p2) cmpeq p1, r19, r22       # odd: expect release
        (!p1) b fail
        ldz.64 r19, [r26 + 8]          # STATUS == 255 - i
        li r17, 255
        sub r17, r17, r23
        cmpeq p1, r19, r17
        (!p1) b fail
        add r23, r23, 1
        cmpeq p1, r23, 256
        (!p1) b poploop

        # test 4: pop 257 is the sentinel — the dropped press never
        # entered the queue (8.5 steps 2/4)
        li r27, 4
        ldz.64 r19, [r26]
        li r22, 0xffffffffffffffff
        cmpeq p1, r19, r22
        (!p1) b fail

pass:
        li r0, PASS_MAGIC
        halt
fail:
        st.64 [r24], r27
        mov r0, r27
        halt
