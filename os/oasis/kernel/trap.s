# trap.s - single trap entry, predicate-free dispatch, the interrupt
# paths wrapped in SABI's canonical trap-frame block, and the syscall
# spine. Interrupt handlers touch ONLY r8-r15/r29/k0 plus sregs (r0-r7
# belong to the interrupted code and are not in the trap frame); the
# syscall path is free to clobber the whole caller-saved set (SABI 3.6)
# but must preserve r16-r28 by ordinary function discipline.

# ---- entry: dispatch on cause without touching any predicate (a
# delivery can land between a cmpeq and its consuming branch; the
# interrupted predicate file must survive until the canonical block
# saves it). k0 + scratch0 are the ISA 12 bootstrap.
trap_entry:
        mtsr    scratch0, r8
        mfsr    r8, cause0
        shl     r8, r8, 3              # cause -> vector slot offset
        la      k0, trap_vec
        add     k0, k0, r8
        mfsr    r8, scratch0           # r8 back before any path runs
        jalr    zero, k0, 0

trap_vec:                              # one 8-byte slot per cause 0..12
        b       h_irq                  # 0  TIMER
        b       h_irq                  # 1  EXTINT
        b       h_fatal                # 2  PF_FETCH
        b       h_fatal                # 3  PF_LOAD
        b       h_fatal                # 4  PF_STORE
        b       h_fatal                # 5  PERM_FETCH
        b       h_fatal                # 6  PERM_LOAD
        b       h_fatal                # 7  PERM_STORE
        b       h_fatal                # 8  ILLEGAL
        b       h_fatal                # 9  UNALIGNED
        b       h_syscall              # 10 SYSCALL
        b       h_fatal                # 11 PRIV
        b       h_fatal                # 12 DEVERR

# ---- interrupts: transparent to the interrupted code. Static save
# area is safe: IE=0 for the whole handler and it never lowers TL, so
# this path cannot nest with itself (SABI 5).
h_irq:
# SABI-TRAPFRAME-SAVE v0 -- begin (canonical block, sabi-v0.md section 5)
        la      k0, trap_save
        st128   [k0 + 0],   r8
        st128   [k0 + 16],  r9
        st128   [k0 + 32],  r10
        st128   [k0 + 48],  r11
        st128   [k0 + 64],  r12
        st128   [k0 + 80],  r13
        st128   [k0 + 96],  r14
        st128   [k0 + 112], r15
        st128   [k0 + 128], r29
        prd     r8
        st128   [k0 + 144], r8
# SABI-TRAPFRAME-SAVE v0 -- end
        mfsr    r8, cause0
        cmpeq   p1, r8, CAUSE_TIMER
        (!p1) b h_extint

        # TIMER: count the tick, re-arm. Level condition clears because
        # timecmp moves into the future (ISA 7.5).
        ldz.64  r9, [r27 + G_TICKS]
        add     r9, r9, 1
        st.64   [r27 + G_TICKS], r9
        mfsr    r9, cycle
        add     r9, r9, TICK
        mtsr    timecmp, r9
        b       h_irq_out

h_extint:
        # EXTINT is the level-OR of every device (PLATFORM-SPEC 3):
        # clear every source or the line stays asserted forever. The
        # mouse drain is not a nicety - an undrained mouse queue is a
        # hang.
        jal     kbd_drain
        jal     mouse_drain
        jal     disp_check

h_irq_out:
# SABI-TRAPFRAME-RESTORE v0 -- begin (canonical block, sabi-v0.md section 5)
        la      k0, trap_save
        ld128   r8, [k0 + 144]
        pwr     r8
        ld128   r8,  [k0 + 0]
        ld128   r9,  [k0 + 16]
        ld128   r10, [k0 + 32]
        ld128   r11, [k0 + 48]
        ld128   r12, [k0 + 64]
        ld128   r13, [k0 + 80]
        ld128   r14, [k0 + 96]
        ld128   r15, [k0 + 112]
        ld128   r29, [k0 + 128]
# SABI-TRAPFRAME-RESTORE v0 -- end
        iret

# ---- syscall spine: number in r7 (SABI 3), resume past the SYSCALL
# via epc+8 then IRET (ISA 7.1). No trap-frame needed: everything the
# sys_* bodies clobber is caller-saved across a syscall.
h_syscall:
        cmpeq   p1, r7, SYS_WRITE
        (p1) b  sys_write
        cmpeq   p1, r7, SYS_READ
        (p1) b  sys_read
        cmpeq   p1, r7, SYS_EXIT
        (p1) b  sys_exit
        li      r0, -ENOSYS
        b       sys_ret

sys_ret:                               # shared syscall exit (sys.s jumps here)
        mfsr    k0, epc0
        add     k0, k0, 8
        mtsr    epc0, k0
        iret

# ---- unexpected cause: loud stop. The trace's TRAP record carries the
# cause; r0 marks the class.
h_fatal:
        li      r0, HALT_BADTRAP
        halt

# ---- double fault: store both banks + status for post-mortem, halt.
df_entry:
        la      k0, dbg_df
        mfsr    r8, epc0
        st.64   [k0 + 0], r8
        mfsr    r8, cause0
        st.64   [k0 + 8], r8
        mfsr    r8, baddr0
        st.64   [k0 + 16], r8
        mfsr    r8, epc1
        st.64   [k0 + 24], r8
        mfsr    r8, cause1
        st.64   [k0 + 32], r8
        mfsr    r8, baddr1
        st.64   [k0 + 40], r8
        mfsr    r8, status
        st.64   [k0 + 48], r8
        li      r0, HALT_DF
        halt
