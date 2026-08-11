# sys.s - syscall bodies. Entered by branch from h_syscall (trap.s)
# with the SYSCALL register state live: r0-r5 args, return in r0, exit
# through sys_ret (epc+8, IRET). Everything here may clobber the
# caller-saved set; r16-r28 are preserved by ordinary frame discipline
# (SABI 3.6). We run on the interrupted thread's kernel stack - legal
# because there is no red zone (SABI 1.1).

sys_write:                             # write(fd, buf, len) -> len
        cmpeq   p1, r0, zero           # fd 0 = console
        (!p1) b sys_einval
        jal     sys_ubuf_check         # -EFAULT out for bad user bufs
        cmpeq   p1, r2, zero
        (p1) b  sys_ret0               # len 0: no bytes, no PRESENT
        add     sp, sp, -32
        st128   [sp + 16], r16
        mov     r16, r2                # keep len for the return value
        mov     r0, r1
        mov     r1, r2
        jal     con_write
        mov     r0, r16
        ld128   r16, [sp + 16]
        add     sp, sp, 32
        b       sys_ret

sys_read:                              # read(fd, buf, len) -> count >= 1
        cmpeq   p1, r0, zero
        (!p1) b sys_einval
        cmpeq   p1, r2, zero           # len 0 can never satisfy ">= 1"
        (p1) b  sys_einval
        jal     sys_ubuf_check         # validate BEFORE blocking
        # Block until the ring has a byte: ISA 7.3 software-consent
        # pattern per SABI 5 - bank-0 sregs + status to memory (our
        # stack frame: nesting-safe by construction), TL<-0, IE<-1,
        # then WFI-idle. The EXTINT handler fills the ring; the timer
        # guarantees WFI always has a future wake. Never polls.
        add     sp, sp, -64
        mfsr    r8, epc0
        st128   [sp + 0], r8
        mfsr    r8, cause0
        st128   [sp + 16], r8
        mfsr    r8, baddr0
        st128   [sp + 32], r8
        mfsr    r8, status
        st128   [sp + 48], r8
        li      r8, STATUS_S + STATUS_IE + STATUS_MMU_EN
        mtsr    status, r8             # TL=0, interrupts live, MMU stays on
sr_wait:
        ldz.64  r9, [r27 + G_RHEAD]
        ldz.64  r10, [r27 + G_RTAIL]
        cmpeq   p1, r9, r10
        (!p1) b sr_have
        wfi
        b       sr_wait
sr_have:
        sub     r11, r9, r10           # available
        cmpltu  p1, r2, r11
        (p1) mov r11, r2               # n = min(len, available)
        mov     r12, zero
        la      r13, kbd_ring
sr_copy:
        cmpltu  p1, r12, r11
        (!p1) b sr_copied
        and     r14, r10, RING_SIZE - 1
        add     r14, r14, r13
        ldz.8   r15, [r14]
        add     r14, r1, r12
        st.8    [r14], r15
        add     r10, r10, 1
        add     r12, r12, 1
        b       sr_copy
sr_copied:
        st.64   [r27 + G_RTAIL], r10    # publish after copying (handler
                                       # only ever writes head)
        ld128   r8, [sp + 48]
        mtsr    status, r8             # back to TL=1, IE=0, atomically
        ld128   r8, [sp + 0]
        mtsr    epc0, r8               # interrupts overwrote bank 0
        ld128   r8, [sp + 16]
        mtsr    cause0, r8
        ld128   r8, [sp + 32]
        mtsr    baddr0, r8
        add     sp, sp, 64
        mov     r0, r11
        b       sys_ret

sys_exit:                              # exit(code): who dies depends on
        mfsr    r8, status             # the caller (v0.1 A.6) - a user
        and     r8, r8, STATUS_PS      # program cannot stop the machine
        cmpeq   p1, r8, zero
        (p1) b  uproc_exit             # user: the program terminates
        halt                           # kernel (shell halt): M1 contract

# ---- user-pointer rule (v0.1 A.5): for a user-mode caller, [buf,
# buf+len) must lie inside the user window, else -EFAULT; the len cap
# comes first so buf+len cannot wrap. Kernel callers are trusted.
# Returns on pass; a failure abandons ra and leaves via sys_ret with
# the errno - nothing was pushed, so there is nothing to unwind.
sys_ubuf_check:
        mfsr    r8, status
        and     r8, r8, STATUS_PS
        cmpeq   p1, r8, zero
        (!p1) ret                      # kernel caller
        li      r8, USIZE
        cmpleu  p1, r2, r8
        (!p1) b sys_efault
        li      r8, UBASE
        cmpleu  p1, r8, r1
        (!p1) b sys_efault
        li      r9, UTOP
        add     r10, r1, r2
        cmpleu  p1, r10, r9
        (!p1) b sys_efault
        ret

sys_einval:
        li      r0, -EINVAL
        b       sys_ret
sys_efault:
        li      r0, -EFAULT
        b       sys_ret
sys_ret0:
        li      r0, 0
        b       sys_ret
