# uproc.s - the single M2 user process: entry, clean exit, kill, and
# the per-process kernel trap stack (SABI v0.1 A.3/A.4/A.6). One
# instance today, but every trap-side path reaches it through the
# cur_proc pointer, never a bare stack symbol - M3 changes a count and
# adds a scheduler, not this file's shape.

# ---- run_user() -> r0 = PSTATE_EXITED or PSTATE_KILLED.
# An ordinary SABI function to its caller (the shell): preserves the
# callee-saved set by parking ALL of it in the frame, because the A.3
# entry contract zeroes every register before the IRET - deterministic
# entry, no kernel state leaking into user mode.
run_user:
        add     sp, sp, -224
        st128   [sp + 208], r29
        st128   [sp + 192], r27
        st128   [sp + 176], r26
        st128   [sp + 160], r25
        st128   [sp + 144], r24
        st128   [sp + 128], r23
        st128   [sp + 112], r22
        st128   [sp + 96],  r21
        st128   [sp + 80],  r20
        st128   [sp + 64],  r19
        st128   [sp + 48],  r18
        st128   [sp + 32],  r17
        st128   [sp + 16],  r16

        la      r8, uproc0
        la      r9, uproc0_kstack_top
        st128   [r8 + P_KSTK], r9
        li      r9, PSTATE_RUN
        st.64   [r8 + P_STATE], r9
        st128   [r8 + P_KSP], sp
        la      r9, cur_proc
        st.64   [r9], r8
        la      r9, dbg_user           # 1: entering user mode
        li      r10, 1
        st.64   [r9], r10

        # A.3 entry contract. IE off first, so nothing can overwrite
        # epc0 between here and the IRET; PIE=1 hands the user
        # interrupts-enabled execution (the timer keeps ticking).
        li      r8, STATUS_S + STATUS_MMU_EN + STATUS_PIE
        mtsr    status, r8
        li      r8, UBASE
        mtsr    epc0, r8
        mtsr    fcsr, zero
        pwr     zero                   # p1-p7 = 0
        li      sp, UTOP               # top of the user stack page
        mov     r0, zero
        mov     r1, zero
        mov     r2, zero
        mov     r3, zero
        mov     r4, zero
        mov     r5, zero
        mov     r6, zero
        mov     r7, zero
        mov     r8, zero
        mov     r9, zero
        mov     r10, zero
        mov     r11, zero
        mov     r12, zero
        mov     r13, zero
        mov     r14, zero
        mov     r15, zero
        mov     r16, zero
        mov     r17, zero
        mov     r18, zero
        mov     r19, zero
        mov     r20, zero
        mov     r21, zero
        mov     r22, zero
        mov     r23, zero
        mov     r24, zero
        mov     r25, zero
        mov     r26, zero
        mov     r27, zero
        mov     r29, zero
        mov     r30, zero
        iret                           # the one door into user mode

# ---- termination. uproc_exit arrives from sys_exit (user caller, on
# the process kernel trap stack); uproc_kill arrives from h_fault with
# PS=0 and MUST NOT push - sp is the dying user's garbage (SABI 1.4
# rule 2). Neither path returns; both leave through the terminate IRET
# into run_user's epilogue. k0 is reloaded, not trusted (1.4 rule 1).
uproc_exit:
        la      k0, cur_proc
        ldz.64  k0, [k0]
        st.64   [k0 + P_EXIT], r0
        li      r8, PSTATE_EXITED
        st.64   [k0 + P_STATE], r8
        b       uproc_terminate

uproc_kill:
        la      k0, cur_proc
        ldz.64  k0, [k0]
        mfsr    r8, cause0             # bank 0 is intact: IE=0 since
        st.64   [k0 + P_CAUSE], r8     # delivery, nothing nested
        mfsr    r8, epc0
        st.64   [k0 + P_EPC], r8
        mfsr    r8, baddr0
        st.64   [k0 + P_BADDR], r8
        li      r8, PSTATE_KILLED
        st.64   [k0 + P_STATE], r8

uproc_terminate:
        ldz.64  r8, [k0 + P_STATE]     # dbg_user: 2 exit / 3 kill
        la      r9, dbg_user
        st.64   [r9], r8
        # Land in run_user's epilogue in S mode with interrupts live:
        # epc0 <- resume label, PS <- 1, and IRET (S<-PS, IE<-PIE=1,
        # TL<-0). The user program had IE=1 by A.3, so PIE is 1 here.
        la      r8, uproc_resume
        mtsr    epc0, r8
        mfsr    r8, status
        or      r8, r8, STATUS_PS
        mtsr    status, r8
        iret

uproc_resume:
        # Back in S mode, interrupts on, but every register is trap
        # debris - reload the caller's sp from the structure first,
        # then the callee-saved set from the frame it points at.
        la      r8, uproc0
        ld128   sp, [r8 + P_KSP]
        ldz.64  r0, [r8 + P_STATE]     # the return value
        la      r9, cur_proc
        st.64   [r9], zero
        ld128   r16, [sp + 16]
        ld128   r17, [sp + 32]
        ld128   r18, [sp + 48]
        ld128   r19, [sp + 64]
        ld128   r20, [sp + 80]
        ld128   r21, [sp + 96]
        ld128   r22, [sp + 112]
        ld128   r23, [sp + 128]
        ld128   r24, [sp + 144]
        ld128   r25, [sp + 160]
        ld128   r26, [sp + 176]
        ld128   r27, [sp + 192]
        ld128   r29, [sp + 208]
        add     sp, sp, 224
        ret
