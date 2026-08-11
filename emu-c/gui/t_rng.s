# t_rng.s — seam-driver guest for the rng scenario (run-gui-tests):
# the entropy-consuming session behind the record->replay proof. The
# driver feeds an 8-word batch while we poll, then a 4-word batch while
# we idle in WFI with CTRL.IE = 0 — the feed record itself is the wake
# source and lands at exactly its cycle (rng.md RNG-21). Each batch's
# words XOR to zero by driver construction, so the fold check needs no
# shared table. STATUS-then-pop throughout (rng.md 3): an empty pop
# here would be DEVERR, and passing proves we never made one.

        .equ DEV_RNG_BASE, 0x0F080000
        .equ PASS_MAGIC, 0x600D

        .org 0x1000
start:
        li r26, DEV_RNG_BASE
wait8:
        ldz.64 r19, [r26 + 8]      # STATUS
        cmpeq p1, r19, 8
        (!p1) b wait8
        li r18, 8                  # pop exactly the depth we counted
        li r20, 0
drain1:
        ldz.64 r19, [r26]          # DATA pop
        xor r20, r20, r19
        sub r18, r18, 1
        cmpeq p1, r18, 0
        (!p1) b drain1
        cmpeq p1, r20, 0           # batch XOR-folds to zero
        (!p1) b fail
        ldz.64 r19, [r26 + 8]      # drained: STATUS back to 0
        cmpeq p1, r19, 0
        (!p1) b fail

        wfi                        # no timer, IE off: the next feed
                                   # record is the only wake source
        ldz.64 r19, [r26 + 8]      # woke AT the event cycle: visible
        cmpeq p1, r19, 4
        (!p1) b fail
        li r18, 4
        li r20, 0
drain2:
        ldz.64 r19, [r26]
        xor r20, r20, r19
        sub r18, r18, 1
        cmpeq p1, r18, 0
        (!p1) b drain2
        cmpeq p1, r20, 0
        (!p1) b fail

        li r0, PASS_MAGIC
        halt
fail:
        li r0, 0xBAD
        halt
