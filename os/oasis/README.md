# Oasis — the first Sahara kernel (milestone 2)

Oasis boots per devspec/boot.md, turns the MMU on behind an identity
map (SABI 4.4), runs an 80×30 text console and a keyboard line-edit
shell over SYSCALL, and executes one embedded user program in U mode
per the SABI v0.1 user-mode amendment (`os/abi/sabi-v0.md`, appended
after the change log — DRAFT until the owner signs it). Tested fully
headless: event feeds in, trace assertions out. Its syscall numbers
and the `run` builtin live in `doc/syscalls.md`. It never references,
detects, or depends on a window.

## Layout

    doc/syscalls.md      syscall personality (numbers + semantics + run)
    kernel/*.s           hand-written Sahara assembly (link order below)
    user/*.s             user programs: echo.s (default) + one image
                         per fault-containment test class
    gen/genfont.py       emits build/font.s (8x16 font, ASCII 0x20-0x7E)
    gen/genkeymap.py     emits build/keymap.s (HID->ASCII tables)
    build/               generated .s + oasis*.img/.sym (gitignored)
    tests/               run-tests.sh, mkfeed.py, fbcheck.py, ucheck.py,
                         replaycmp.py, feeds/, golden/
    build.sh             builds build/oasis.img + .sym
    run.sh               headless demo run under $EMU

## Build

    ./build.sh [USER_SRC] [OUT_IMG]   # needs python3; uses ../../asm/asm.py

Defaults: `user/echo.s` → `build/oasis.img`. The test suite builds
`build/oasis-<name>.img` variants from the other user programs.

Link order is the section convention (SABI v0 section 6) — there is no
linker, the assembler CLI order IS the layout — with the user program
LAST: it opens its own `.org UBASE` segment (SABI v0.1 A.7):

    text:   defs.s boot.s trap.s mmu.s uproc.s kbd.s con.s shell.s sys.s lib.s
    rodata: build/font.s build/keymap.s rodata.s
    data:   data.s
    bss:    bss.s
    user:   user/<prog>.s   (.org UBASE segment, ends at __uend)

Symbols are global across the whole unit; each file prefixes its labels
(`con_`, `kbd_`, `sys_`, `sh_`, `lib_`, `mmu_`, `uproc_`, `u_`, …) to
dodge collisions.

## Test

    EMU=../../emu-c/bazel-bin/sahara-emu tests/run-tests.sh   # (default)
    EMU_PY=1 tests/run-tests.sh                               # adds the emu-py smoke leg

Every feed ends with `halt\n`, so WFI never deadlocks after the last
event; `--maxcycles` is only a backstop. See tests/run-tests.sh header
for the assertion layers and the toolchain-ownership boundary.
ucheck.py holds the M2-specific trace proofs (U-mode entry, the
kernel-trap-stack switch, kill diagnostics) — there is no mode bit in
the trace, so user-mode facts are pc/epc/MEMW geometry.

## Shell

Prompt `$ `. Line editing: printables, Backspace, Enter. Builtins:

    help            list builtins
    echo <text>     print <text>
    uptime          timer ticks + current cycle (proves the timer runs)
    run             enter the embedded user program at UBASE; prints
                    "user: exit <code>" or "user: killed cause=<c>
                    epc=0x<hex>" when it terminates
    halt            exit(0x600D) -> HALT r0=...600d

Unknown commands print an error line.

## User mode (M2)

One user program per image, embedded at UBASE = 0x0200_0000 (16 MB
window, SABI v0.1 A.2): image pages U+RWX, top page U+RW as the user
stack, the gap unmapped so wild pointers fault loudly. Kernel pages
are U=0 — user access faults PERM_*. Any user fault (causes 2..9, 11,
12) kills the program with a shell diagnostic; the kernel survives.
User syscalls run on the per-process kernel trap stack (v0.1 A.4,
one instance in M2); the user sp is saved/restored as data, never
used as a stack (SABI 1.4 rule 2).

## Boot-stage debug word

Boot stores ordered u64 stage codes to the bss word `dbg_status`:
1 table-ok, 2 vectors-on, 3 mmu-on, 4 irq-on, 5 shell-ready. The
tests resolve `dbg_status` from the `.sym` sidecar and assert the
ordered MEMW sequence via trace-q, each stage exactly once. A second
word `dbg_user` tracks the user program: 1 entered, 2 clean exit,
3 killed.

Boot-failure halts are loud and distinct (r0 values, kernel/defs.s):
0x0BAD0001 bad magic, 0x0BAD0002 unknown table version, 0x0BAD0003
table too big for its window, 0x0BAD0004 u128 table field above 2^64,
0x0BAD0005 no display record, 0x0BAD0006 no keyboard record,
0x0BAD0007 unusable display FORMAT, 0x0BAD0008 device table needs
more page-table nodes than the pool holds, 0x0BAD0009 table window
beyond the map's 4 GB reach, 0x0BAD000A kernel image grew into UBASE,
0x0BAD000B user window off the end of RAM, 0x0BAD000F unexpected trap
cause; 0x0DF0DF0 double fault (dfbase stub stores both banks to
dbg_df* and halts).
