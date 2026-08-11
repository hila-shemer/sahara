# boot.s - reset entry: validate the device table, derive everything
# from it (devspec/boot.md 6), install vectors, arm the timer, hand off
# to the shell. Boot-stage codes go to dbg_status (u64 stores) so the
# tests can assert the sequence from the trace.
#
# Register use: boot owns the machine, no ABI constraints until the
# first jal (sp is set before that). gp = r27 is live from right after
# the header checks and never written again (SABI 1.2).

        .org 0x1000
_reset:
        li      r1, DT_BASE

        # ---- header validation (boot.md 3.3): each failure terminal,
        # distinct halt code, never guess.
        ldz.64  r2, [r1 + 0]
        li      r3, DT_MAGIC
        cmpeq   p1, r2, r3
        (!p1) b boot_fail_magic
        ldz.64  r2, [r1 + 8]
        cmpeq   p1, r2, DT_VERSION
        (!p1) b boot_fail_ver
        ldz.64  r4, [r1 + 24]          # ram_region_count
        ldz.64  r5, [r1 + 32]          # device_count
        cmpltu  p1, zero, r4           # >= 1 region
        (!p1) b boot_fail_size
        mul     r6, r4, 32
        mul     r7, r5, 64
        add     r6, r6, r7
        add     r6, r6, 40             # encoded size
        cmpleu  p1, r6, DT_WINDOW
        (!p1) b boot_fail_size

        la      r27, kglobals          # gp live from here (SABI 1.2)

        # ---- RAM region 0: stack top comes from the table, never a
        # constant (SABI 4.5). u128 fields are 8-aligned only: paired
        # ldz.64, LD128 would trap UNALIGNED (boot.md 3.2).
        ldz.64  r8, [r1 + 40]          # base lo
        ldz.64  r9, [r1 + 48]          # base hi
        ldz.64  r10, [r1 + 56]         # len lo
        ldz.64  r11, [r1 + 64]         # len hi
        or      r9, r9, r11
        cmpeq   p1, r9, zero           # >2^64 is beyond this kernel:
        (!p1) b boot_fail_u128         # fail loudly, don't wrap
        add     r8, r8, r10
        st.64   [r27 + G_RAMTOP], r8

        # ---- device walk, by count (boot.md 3.5). First record of a
        # type wins; unknown types skip whole (the unconditional +64 IS
        # the skip rule, boot.md 4.2 - base/params of skipped records
        # are never touched).
        mul     r6, r4, 32
        add     r6, r6, 40
        add     r6, r6, r1             # r6 -> first device record
boot_dev_loop:
        cmpeq   p1, r5, zero
        (p1) b  boot_dev_done
        ldz.64  r7, [r6 + 0]           # type
        cmpeq   p2, r7, 1
        (p2) b  boot_dev_disp
        cmpeq   p2, r7, 2
        (p2) b  boot_dev_kbd
        cmpeq   p2, r7, 3
        (p2) b  boot_dev_mouse
        b       boot_dev_next
boot_dev_disp:
        ldz.64  r9, [r27 + G_DISP]
        cmpeq   p3, r9, zero
        (!p3) b boot_dev_next          # not the first of its type
        ldz.64  r9, [r6 + 8]           # base lo
        ldz.64  r10, [r6 + 16]         # base hi
        cmpeq   p3, r10, zero
        (!p3) b boot_fail_u128
        st.64   [r27 + G_DISP], r9
        ldz.64  r9, [r6 + 32]          # params[0]: pixel buffer PA
        st.64   [r27 + G_PIXBUF], r9
        ldz.64  r9, [r6 + 40]          # params[1]: pixel buffer size
        st.64   [r27 + G_PIXSZ], r9
        b       boot_dev_next
boot_dev_kbd:
        ldz.64  r9, [r27 + G_KBD]
        cmpeq   p3, r9, zero
        (!p3) b boot_dev_next
        ldz.64  r9, [r6 + 8]
        ldz.64  r10, [r6 + 16]
        cmpeq   p3, r10, zero
        (!p3) b boot_fail_u128
        st.64   [r27 + G_KBD], r9
        b       boot_dev_next
boot_dev_mouse:
        ldz.64  r9, [r27 + G_MOUSE]
        cmpeq   p3, r9, zero
        (!p3) b boot_dev_next
        ldz.64  r9, [r6 + 8]
        ldz.64  r10, [r6 + 16]
        cmpeq   p3, r10, zero
        (!p3) b boot_fail_u128
        st.64   [r27 + G_MOUSE], r9
        b       boot_dev_next
boot_dev_next:
        add     r6, r6, 64
        sub     r5, r5, 1
        b       boot_dev_loop
boot_dev_done:
        ldz.64  r9, [r27 + G_DISP]
        cmpeq   p1, r9, zero
        (p1) b  boot_fail_nodisp
        ldz.64  r9, [r27 + G_KBD]
        cmpeq   p1, r9, zero
        (p1) b  boot_fail_nokbd

        la      r8, dbg_status         # stage 1: table parsed + derived
        li      r9, DBG_TABLE_OK
        st.64   [r8], r9

        # ---- vectors before anything that may fault (boot.md 6)
        la      r8, trap_entry
        mtsr    vbase, r8
        la      r8, df_entry
        mtsr    dfbase, r8
        la      r8, dbg_status         # stage 2: vectors installed
        li      r9, DBG_VECTORS_ON
        st.64   [r8], r9

        # ---- stack at RAM region 0 top (SABI 4.5), then the MMU:
        # build the identity map from the table, then boot.md 6 step 5
        # in its exact order - ptbase, INVTP, MMU_EN. The single INVTP
        # is the only one the kernel needs: the map never changes after
        # this point. Identity axiom (SABI 4.4): the fetch after the
        # status write translates to the same PA, nothing moves.
        ldz.64  sp, [r27 + G_RAMTOP]
        jal     mmu_init               # r0 = root node PA (halts loud
        mtsr    ptbase, r0             # on pool/reach/window failures)
        invtp
        mfsr    r8, status
        or      r8, r8, STATUS_MMU_EN
        mtsr    status, r8
        la      r8, dbg_status         # stage 3: translation on
        li      r9, DBG_MMU_ON
        st.64   [r8], r9

        jal     con_init               # halts loud on FORMAT != 1
        la      r0, msg_banner
        jal     con_puts

        # ---- timer armed + IE on. timecmp is never left 0/armed-past:
        # the handler re-arms every TICK, so WFI always has a wake.
        mfsr    r8, cycle
        add     r8, r8, TICK
        mtsr    timecmp, r8
        li      r8, STATUS_S + STATUS_IE + STATUS_MMU_EN
        mtsr    status, r8
        la      r8, dbg_status         # stage 4: interrupts live
        li      r9, DBG_IRQ_ON
        st.64   [r8], r9

        la      r8, dbg_status         # stage 5: entering the shell
        li      r9, DBG_SHELL_READY
        st.64   [r8], r9
        b       sh_main

boot_fail_magic:
        li      r0, HALT_BADMAGIC
        halt
boot_fail_ver:
        li      r0, HALT_BADVER
        halt
boot_fail_size:
        li      r0, HALT_BADSIZE
        halt
boot_fail_u128:
        li      r0, HALT_U128
        halt
boot_fail_nodisp:
        li      r0, HALT_NODISP
        halt
boot_fail_nokbd:
        li      r0, HALT_NOKBD
        halt
