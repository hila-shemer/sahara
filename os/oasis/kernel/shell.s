# shell.s - the line-edit echo shell. Runs at TL=0 with IE on and
# talks to its own kernel exclusively through SYSCALL - the contract
# is exercised from day one, nothing here calls con_* directly.
# Persistent state sits in callee-saved registers (safe across
# syscalls, SABI 3.6): r16 = line length. sh_main never returns, so it
# owns r16 without saving it.
#
# Builtins: help, echo <text>, uptime, halt. Unknown -> error line.
# Line editing: printables append + echo; 0x08 pops + echoes (console
# does the erase); 0x0A terminates. Full line swallows input silently.

sh_main:
sh_loop:
        la      r0, msg_prompt
        jal     sh_puts
        li      r16, 0                 # line length
sh_rdch:
        li      r0, 0                  # read(0, sh_chbuf, 1): blocks
        la      r1, sh_chbuf
        li      r2, 1
        li      r6, 0
        li      r7, SYS_READ
        syscall
        la      r9, sh_chbuf
        ldz.8   r8, [r9]
        cmpeq   p1, r8, 0x0A
        (p1) b  sh_eol
        cmpeq   p1, r8, 0x08
        (p1) b  sh_bs
        cmpltu  p1, r8, 0x20           # ring only carries NL/BS/printables,
        (p1) b  sh_rdch                # but stay defensive
        cmpltu  p1, r16, LINE_MAX
        (!p1) b sh_rdch                # line full: swallow
        la      r9, sh_line
        add     r9, r9, r16
        st.8    [r9], r8
        add     r16, r16, 1
        jal     sh_echo1
        b       sh_rdch
sh_bs:
        cmpeq   p1, r16, zero
        (p1) b  sh_rdch                # empty line: nothing to erase
        sub     r16, r16, 1
        jal     sh_echo1               # echo the BS; console erases
        b       sh_rdch
sh_eol:
        jal     sh_echo1               # echo the newline
        la      r9, sh_line
        add     r9, r9, r16
        st.8    [r9], zero             # terminate
        cmpeq   p1, r16, zero
        (p1) b  sh_loop
        la      r0, sh_line            # dispatch
        la      r1, cmd_help
        jal     lib_streq
        cmpeq   p1, r0, zero
        (!p1) b sh_do_help
        la      r0, sh_line
        la      r1, cmd_halt
        jal     lib_streq
        cmpeq   p1, r0, zero
        (!p1) b sh_do_halt
        la      r0, sh_line
        la      r1, cmd_uptime
        jal     lib_streq
        cmpeq   p1, r0, zero
        (!p1) b sh_do_uptime
        la      r0, sh_line
        la      r1, cmd_echo           # bare "echo": empty output line
        jal     lib_streq
        cmpeq   p1, r0, zero
        (!p1) b sh_do_echo0
        la      r0, sh_line
        la      r1, cmd_echosp         # "echo " prefix
        jal     lib_prefix
        cmpeq   p1, r0, zero
        (!p1) b sh_do_echo
        la      r0, msg_unknown
        jal     sh_puts
        b       sh_loop

sh_do_help:
        la      r0, msg_help
        jal     sh_puts
        b       sh_loop

sh_do_halt:
        li      r0, EXIT_PASS          # exit(0x600D): HALT r0=...600d
        li      r6, 0
        li      r7, SYS_EXIT
        syscall                        # does not return

sh_do_echo0:
        la      r0, msg_nl
        jal     sh_puts
        b       sh_loop

sh_do_echo:
        la      r9, sh_line            # replace the NUL with '\n' and
        add     r9, r9, r16            # write text+NL in one syscall
        li      r10, 0x0A
        st.8    [r9], r10
        la      r1, sh_line
        add     r1, r1, 5              # past "echo "
        sub     r2, r16, 4             # (len-5) text + 1 newline
        li      r0, 0
        li      r6, 0
        li      r7, SYS_WRITE
        syscall
        b       sh_loop

sh_do_uptime:
        la      r0, sh_ubuf            # "uptime: T ticks, C cycles\n"
        la      r1, str_uptime
        jal     lib_append
        ldz.64  r1, [r27 + G_TICKS]
        jal     lib_u64dec
        la      r1, str_ticks
        jal     lib_append
        mfsr    r1, cycle              # proves the timer/cycle plumbing
        jal     lib_u64dec
        la      r1, str_cycles
        jal     lib_append
        mov     r2, r0
        la      r1, sh_ubuf
        sub     r2, r2, r1
        li      r0, 0
        li      r6, 0
        li      r7, SYS_WRITE
        syscall
        b       sh_loop

# ---- syscall wrappers (functions: frames per SABI 2, ra in top slot)

sh_puts:                               # r0 = asciiz -> write(0, s, strlen)
        add     sp, sp, -32
        st128   [sp + 16], r29
        st128   [sp + 0], r17
        mov     r17, r0
        jal     lib_strlen
        mov     r2, r0
        mov     r1, r17
        li      r0, 0
        li      r6, 0
        li      r7, SYS_WRITE
        syscall
        ld128   r17, [sp + 0]
        ld128   r29, [sp + 16]
        add     sp, sp, 32
        ret

sh_echo1:                              # write(0, sh_chbuf, 1)
        add     sp, sp, -16
        st128   [sp + 0], r29
        li      r0, 0
        la      r1, sh_chbuf
        li      r2, 1
        li      r6, 0
        li      r7, SYS_WRITE
        syscall
        ld128   r29, [sp + 0]
        add     sp, sp, 16
        ret
