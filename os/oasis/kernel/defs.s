# defs.s - Oasis constants. First file on the assembler command line;
# .equ only, emits nothing. Machine facts come from the frozen specs;
# the only hardcodable address is the device table's 0x0800
# (devspec/boot.md 2.3). Everything else is derived at boot.

        .equ DT_BASE,        0x800
        .equ DT_MAGIC,       0x5450415241484153   # "SAHARAPT"
        .equ DT_VERSION,     1
        .equ DT_WINDOW,      2048

        # status bits (ISA-SPEC 2.3)
        .equ STATUS_IE,      1
        .equ STATUS_PIE,     2
        .equ STATUS_MMU_EN,  4
        .equ STATUS_S,       8
        .equ STATUS_PS,      16

        # page-table geometry (ISA-SPEC 8.2): 64 KB pages, 4160-byte
        # nodes (64-byte header + 256 x 16-byte entries), leaf flag bits
        .equ PAGE_SIZE,      0x10000
        .equ NODE_SIZE,      4160
        .equ PTE_TABLE,      1
        .equ PTE_LEAF,       2
        .equ PTE_R,          4
        .equ PTE_W,          8
        .equ PTE_X,          16
        .equ PTE_U,          32

        # user window (SABI v0.1 amendment A.2): one VPN chunk, 16 MB
        .equ UBASE,          0x02000000
        .equ USIZE,          0x01000000
        .equ USTACK_PAGE,    0x02FF0000
        .equ UTOP,           0x03000000

        # causes we dispatch on (ISA-SPEC 7.1)
        .equ CAUSE_TIMER,    0
        .equ CAUSE_EXTINT,   1
        .equ CAUSE_SYSCALL,  10

        # display control regs (devspec/display.md 2)
        .equ DISP_PRESENT,   0x00
        .equ DISP_WIDTH,     0x08
        .equ DISP_HEIGHT,    0x10
        .equ DISP_STRIDE,    0x18
        .equ DISP_FORMAT,    0x20
        .equ DISP_IRQSTAT,   0x28
        .equ DISP_IRQACK,    0x30

        # input device regs (devspec/input.md 1)
        .equ INPUT_DATA,     0
        .equ INPUT_STATUS,   8

        # HID shift modifiers (devspec/input.md 2.2)
        .equ HID_LSHIFT,     0xE1
        .equ HID_RSHIFT,     0xE5

        # timer period, cycles. Re-armed in the handler; keeps WFI
        # always-wakeable (ISA 7.6 deadlock is loud, we never risk it).
        .equ TICK,           100000

        # syscall numbers (doc/syscalls.md) and SABI v0 errnos
        .equ SYS_WRITE,      0
        .equ SYS_READ,       1
        .equ SYS_EXIT,       2
        .equ EINVAL,         1
        .equ ENOSYS,         2
        .equ EFAULT,         3

        # console
        .equ WHITE,          0x00FFFFFF            # XRGB8888
        .equ EXIT_PASS,      0x600D

        # boot-stage codes stored to dbg_status (README). M2 renumber:
        # mmu-on slots in as stage 3, everything after shifts by one.
        .equ DBG_TABLE_OK,   1
        .equ DBG_VECTORS_ON, 2
        .equ DBG_MMU_ON,     3
        .equ DBG_IRQ_ON,     4
        .equ DBG_SHELL_READY, 5

        # loud halt codes, r0 at HALT (README; our value space, distinct
        # per failure class, never the conformance suite's idioms)
        .equ HALT_BADMAGIC,  0x0BAD0001
        .equ HALT_BADVER,    0x0BAD0002
        .equ HALT_BADSIZE,   0x0BAD0003
        .equ HALT_U128,      0x0BAD0004
        .equ HALT_NODISP,    0x0BAD0005
        .equ HALT_NOKBD,     0x0BAD0006
        .equ HALT_BADFMT,    0x0BAD0007
        .equ HALT_BADTRAP,   0x0BAD000F
        .equ HALT_PTPOOL,    0x0BAD0008
        .equ HALT_PTREACH,   0x0BAD0009
        .equ HALT_UBLOW,     0x0BAD000A
        .equ HALT_UBHIGH,    0x0BAD000B
        .equ HALT_DF,        0x0DF0DF0

        # kernel globals block offsets (gp = r27 -> kglobals, SABI 1.2)
        .equ G_DISP,         0    # display control window base
        .equ G_PIXBUF,       8    # pixel buffer PA (params[0])
        .equ G_PIXSZ,        16   # pixel buffer window size (params[1])
        .equ G_KBD,          24   # keyboard window base
        .equ G_MOUSE,        32   # mouse window base (0 = absent)
        .equ G_RAMTOP,       40   # RAM region 0 top = boot sp
        .equ G_WIDTH,        48
        .equ G_HEIGHT,       56
        .equ G_STRIDE,       64
        .equ G_COLS,         72
        .equ G_ROWS,         80
        .equ G_CURCOL,       88
        .equ G_CURROW,       96
        .equ G_TICKS,        104  # timer tick counter
        .equ G_SHIFT,        112  # shift-held mask: bit0 L, bit1 R
        .equ G_RHEAD,        120  # ASCII ring head (monotonic u64)
        .equ G_RTAIL,        128  # ASCII ring tail (monotonic u64)
        .equ G_PTNEXT,       136  # page-table node bump allocator

        .equ RING_SIZE,      256
        .equ LINE_MAX,       120

        # per-process structure offsets (uproc.s instance; the trap
        # paths reach it only through cur_proc - SABI v0.1 A.4). sp
        # and gp slots are 16-byte st128 slots; the rest are u64.
        .equ P_KSTK,         0    # kernel trap-stack pointer (top)
        .equ P_USP,          16   # interrupted user sp - data, never a stack
        .equ P_UGP,          32   # user r27 across a syscall (SABI 3.6)
        .equ P_KSP,          48   # caller's kernel sp across run_user
        .equ P_STATE,        64   # PSTATE_*
        .equ P_EXIT,         72   # exit(code) argument
        .equ P_CAUSE,        80   # kill diagnostics for the shell line
        .equ P_EPC,          88
        .equ P_BADDR,        96
        .equ P_SIZE,         112

        .equ PSTATE_IDLE,    0
        .equ PSTATE_RUN,     1
        .equ PSTATE_EXITED,  2
        .equ PSTATE_KILLED,  3

        .equ KSTK_SIZE,      16384  # reference trap-stack size (v0.1 A.4)
