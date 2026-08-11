# bss.s - zero-initialized tail: .space/.align only, so the
# assembler's trailing-zero trim keeps all of it out of the image file
# (SABI 6.2). Reset guarantees RAM outside the image reads zero, and
# these bytes ARE in the image extent - loader zero-fill covers them.

        .align 16
kglobals:                              # gp block; offsets = defs.s G_*
        .space 160
        .align 16
con_nibtab:                            # 16 entries x 16B: nibble -> 4px
        .space 256
        .align 16
trap_save:                             # SABI 5 canonical block area
        .space 160
kbd_ring:                              # 256-byte ASCII ring
        .space 256
sh_line:                               # shell line buffer (LINE_MAX+pad)
        .space 128
sh_chbuf:                              # 1-byte read target
        .space 16
sh_ubuf:                               # uptime compose buffer
        .space 128
dbg_status:                            # boot-stage word (tests assert
        .space 8                       # the ordered MEMW sequence)
dbg_user:                              # user-program lifecycle word:
        .space 8                       # 1 entered, 2 exited, 3 killed
cur_proc:                              # THE current-process pointer
        .space 8                       # (v0.1 A.4): trap paths reach
                                       # the structure only through it
        .align 16
uproc0:                                # the one M2 process structure
        .space 112                     # (offsets: defs.s P_*)
        .align 16
uproc0_kstack:                         # its kernel trap stack, 16 KB
        .space 16384                   # (v0.1 A.4 reference size)
uproc0_kstack_top:
dbg_df:                                # double-fault post-mortem: epc0,
        .space 64                      # cause0, baddr0, epc1, cause1,
                                       # baddr1, status
        .align 64
mmu_nodes:                             # page-table pool (ISA 8.2 nodes,
        .space 74880                   # 64-aligned): 18 x 4160 B - root
mmu_nodes_end:                         # + one shift-0 node per chunk
        .align 16
_end:                                  # heap grows UP from here (SABI
                                       # 4.6, ceiling now UBASE per
                                       # v0.1 A.2); no allocator yet
