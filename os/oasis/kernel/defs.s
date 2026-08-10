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
        .equ STATUS_S,       8

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

        # boot-stage codes stored to dbg_status (README)
        .equ DBG_TABLE_OK,   1
        .equ DBG_VECTORS_ON, 2
        .equ DBG_IRQ_ON,     3
        .equ DBG_SHELL_READY, 4

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

        .equ RING_SIZE,      256
        .equ LINE_MAX,       120
