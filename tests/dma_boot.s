# dma_boot.s — device-table discovery of the DMA engine (devspec/
# boot.md V10, devspec/dma.md 1): parse by counts, locate the type-6
# record by TYPE-CODE SCAN, and pin every field of that record —
# base 0x0F07_0000 (u128 read as two u64 loads, boot.md 3.2), size
# 0x1_0000, params[0..3] all zero. Deliberately NOT pinned: the
# record's position and device_count — both are merge-variant on this
# branch (the wave-final table reorders; boot.md V10's superseded-at-
# integration marker). Unknown-type skip itself is already covered by
# boot.md V2 / the existing suite and is not re-tested here. Finally
# ties the table to the live device: CAPS at the discovered base
# reads the dma.md 3.1 constant. DMA-C-01 (CAPS via discovery) and
# boot.md BOOT-11 instances.
#
# Cycle-driven, no events= line: runs under difftest today.
# Expectations hand-derived from boot.md/dma.md; NOT from an emulator
# run. No trace checker: everything here is guest-visible.

        .org 0x1000
start:
        li r24, FAIL_ADDR
        li r1, 0x800

        # test 1: header sanity — magic and version (boot.md 3.3)
        li r27, 1
        ldz.64 r2, [r1]
        li r3, 0x5450415241484153
        cmpeq.64 p1, r2, r3
        (!p1) b fail
        ldz.64 r2, [r1 + 8]
        cmpeq.64 p1, r2, 1
        (!p1) b fail

        # ---- scan device records for type 6, by the counts ----
        li r27, 2
        ldz.64 r2, [r1 + 24]           # ram_region_count
        ldz.64 r3, [r1 + 32]           # device_count
        add r4, r1, 40
        shl.64 r2, r2, 5
        add r4, r4, r2                 # first device record
scan:
        cmpeq.64 p1, r3, 0
        (p1) b fail                    # no type-6 record
        ldz.64 r5, [r4]
        cmpeq.64 p1, r5, 6
        (p1) b found
        add r4, r4, 64
        sub.64 r3, r3, 1
        b scan
found:

        # test 3: base == 0x0F07_0000, high half 0 (u128 field read as
        # two u64 loads — LD128 on it would trap UNALIGNED, boot.md V6)
        li r27, 3
        ldz.64 r19, [r4 + 8]
        li r20, DEV_DMA_BASE
        cmpeq.64 p1, r19, r20
        (!p1) b fail
        ldz.64 r19, [r4 + 16]
        cmpeq.64 p1, r19, 0
        (!p1) b fail

        # test 4: size == 0x1_0000
        li r27, 4
        ldz.64 r19, [r4 + 24]
        li r20, 0x10000
        cmpeq.64 p1, r19, r20
        (!p1) b fail

        # test 5: params[0..3] all zero — limits live in CAPS, not the
        # table (dma.md 1; boot.md 4.4: zero means exactly v1 behavior)
        li r27, 5
        ldz.64 r19, [r4 + 32]
        cmpeq.64 p1, r19, 0
        (!p1) b fail
        ldz.64 r19, [r4 + 40]
        cmpeq.64 p1, r19, 0
        (!p1) b fail
        ldz.64 r19, [r4 + 48]
        cmpeq.64 p1, r19, 0
        (!p1) b fail
        ldz.64 r19, [r4 + 56]
        cmpeq.64 p1, r19, 0
        (!p1) b fail

        # test 6: the discovered window answers — CAPS reads the
        # dma.md 3.1 constant (version 1, log2 W 3, K 8, log2 LEN_MAX
        # 24), STATUS reads IDLE
        li r27, 6
        ldz.64 r21, [r4 + 8]           # base, from the table
        ldz.64 r19, [r21]
        li r20, 0x18080301
        cmpeq.64 p1, r19, r20
        (!p1) b fail
        ldz.64 r19, [r21 + 8]
        cmpeq.64 p1, r19, 0
        (!p1) b fail

pass:
        li r0, PASS_MAGIC
        halt
fail:
        st.64 [r24], r27
        mov r0, r27
        halt
