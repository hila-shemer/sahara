# Oasis — the first Sahara kernel (milestone 1)

Oasis boots per devspec/boot.md, runs an 80×30 text console and a
keyboard line-edit shell over SYSCALL, and is tested fully headless:
event feeds in, trace assertions out. It is the first conforming client
of SABI v0 (`os/abi/sabi-v0.md`); its syscall numbers live in
`doc/syscalls.md`. It never references, detects, or depends on a window.

## Layout

    doc/syscalls.md      syscall personality (numbers + semantics)
    kernel/*.s           hand-written Sahara assembly (link order below)
    gen/genfont.py       emits build/font.s (8x16 font, ASCII 0x20-0x7E)
    gen/genkeymap.py     emits build/keymap.s (HID->ASCII tables)
    build/               generated .s + oasis.img/.sym (gitignored)
    tests/               run-tests.sh, mkfeed.py, fbcheck.py, feeds/, golden/
    build.sh             builds build/oasis.img + .sym
    run.sh               headless demo run under $EMU

## Build

    ./build.sh          # needs python3; uses ../../asm/asm.py

Link order is the section convention (SABI v0 section 6) — there is no
linker, the assembler CLI order IS the layout:

    text:   defs.s boot.s trap.s kbd.s con.s shell.s sys.s lib.s
    rodata: build/font.s build/keymap.s rodata.s
    data:   data.s
    bss:    bss.s

Symbols are global across the whole unit; each file prefixes its labels
(`con_`, `kbd_`, `sys_`, `sh_`, `lib_`, …) to dodge collisions.

## Test

    EMU=../../emu-c/bazel-bin/sahara-emu tests/run-tests.sh   # (default)
    EMU_PY=1 tests/run-tests.sh                               # adds the emu-py smoke leg

Every feed ends with `halt\n`, so WFI never deadlocks after the last
event; `--maxcycles` is only a backstop. See tests/run-tests.sh header
for the assertion layers and the toolchain-ownership boundary.

## Shell

Prompt `$ `. Line editing: printables, Backspace, Enter. Builtins:

    help            list builtins
    echo <text>     print <text>
    uptime          timer ticks + current cycle (proves the timer runs)
    halt            exit(0x600D) -> HALT r0=...600d

Unknown commands print an error line.

## Boot-stage debug word

Boot stores ordered u64 stage codes to the bss word `dbg_status`:
1 table-ok, 2 vectors-on, 3 mmu-on, 4 irq-on, 5 shell-ready. The tests
resolve
`dbg_status` from the `.sym` sidecar and assert the ordered MEMW
sequence via trace-q, each stage exactly once.

Boot-failure halts are loud and distinct (r0 values, kernel/defs.s):
0x0BAD0001 bad magic, 0x0BAD0002 unknown table version, 0x0BAD0003
table too big for its window, 0x0BAD0004 u128 table field above 2^64,
0x0BAD0005 no display record, 0x0BAD0006 no keyboard record,
0x0BAD0007 unusable display FORMAT, 0x0BAD000F unexpected trap cause;
0x0DF0DF0 double fault (dfbase stub stores both banks to dbg_df* and
halts).
