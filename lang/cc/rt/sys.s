# sys.s - the CC-M1 syscall surface (lang/cc/cc-m1.md section 10).
# Numbers and semantics match os/oasis/doc/syscalls.md (0 write,
# 2 exit) so compiled programs are Oasis-shaped; the handler here is
# the m1 stand-in for a kernel that does not host user code yet.
#
# The wrappers are ordinary SABI functions (frameless leaves, SABI
# 2.5); the handler is a SYSCALL-only path: no trap-frame block needed
# (r8-r15/r29/predicates are caller-saved across a syscall, SABI 5),
# touches nothing callee-saved, never lowers TL. Interrupts are never
# enabled in a cc m1 program, so cause 10 and outright faults are the
# only ways in - faults halt loud.

# ---- C-callable wrappers ------------------------------------------
# sys_write(fd, buf, len) -> len written or negated errno
sys_write:
        li      r7, 0                  # number (SABI 3.2)
        li      r6, 0                  # r6 reserved, callers set 0 (SABI 3.3)
        syscall
        ret

# sys_exit(code) - does not return (handler halts with r0 = code)
sys_exit:
        li      r7, 2
        li      r6, 0
        syscall
        ret                            # unreachable, kept for shape

# ---- trap entry ----------------------------------------------------
# k0 is write-before-read (SABI 1.4 rule 1). Clobbering p1 before the
# cause check is fine: non-SYSCALL causes never resume (they halt),
# and across a SYSCALL predicates are caller-saved.
cc_trap:
        mfsr    k0, cause0
        cmpeq   p1, k0, 10             # SYSCALL?
        (!p1) b cc_trap_bad

        cmpeq   p1, r7, 0
        (p1) b  cc_sys_write
        cmpeq   p1, r7, 2
        (p1) b  cc_sys_exit
        li      r0, -2                 # -ENOSYS (1 = read is known but
        b       cc_sys_ret             # unhosted here - same answer)

# write(fd, buf, len): fd 0 only; append to the capture buffer.
cc_sys_write:
        cmpeq   p1, r0, zero
        (!p1) b cc_sys_einval
        cmpeq   p1, r2, zero
        (p1) b  cc_sys_ret0
        la      r8, sys_cap_len
        ldz.64  r9, [r8]
        add     r10, r9, r2
        cmpleu  p1, r10, 4096
        (!p1) b cc_cap_ovf
        la      r11, sys_cap
        add     r11, r11, r9           # dst = cap + old len
        mov     r12, r1                # src
        mov     r13, r2                # remaining
cc_wcopy:
        cmpeq   p1, r13, zero
        (p1) b  cc_wdone
        ldz.8   r14, [r12]
        st.8    [r11], r14
        add     r12, r12, 1
        add     r11, r11, 1
        sub     r13, r13, 1
        b       cc_wcopy
cc_wdone:
        st.64   [r8], r10              # publish new length
        mov     r0, r2                 # return len
        b       cc_sys_ret

# exit(code): r0 already holds the code - the emulator prints it.
cc_sys_exit:
        halt

cc_sys_einval:
        li      r0, -1                 # -EINVAL
        b       cc_sys_ret
cc_sys_ret0:
        li      r0, 0
cc_sys_ret:
        mfsr    k0, epc0               # resume past the SYSCALL
        add     k0, k0, 8              # (ISA 7.1)
        mtsr    epc0, k0
        iret

# ---- loud stops ----------------------------------------------------
cc_cap_ovf:                            # capture buffer full: a test
        li      r0, 0xCCBADCAF         # bug, not a quiet truncation
        halt
cc_trap_bad:                           # non-SYSCALL trap: 0xCCBADC00
        li      r0, 0xCCBADC00         # + cause (k0 = cause0 from entry)
        add     r0, r0, k0
        halt
cc_df:                                 # double fault
        li      r0, 0xCCBADDF0
        halt

# ---- capture buffer ------------------------------------------------
# Positionally inside the text region: the compiled unit (last file)
# owns the four sections and their seam labels, so runtime state
# cannot live in the real bss. MMU off makes this byte-equivalent;
# recorded in SPEC-ISSUES (boundary-label ownership). Kept at the end
# of the file so no instruction follows unaligned.
        .align 16
sys_cap_len:
        .space 16
sys_cap:
        .space 4096
