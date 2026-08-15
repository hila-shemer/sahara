# lib/c — the Sahara mini-libc

The first C library on the platform, written in cc-m1 C (the compiler's
biggest consumer, on purpose). Surface: `mem*` (memcpy/memmove/memset/
memcmp), the minimal `str*` set (strlen/strcmp/strncmp/strcpy/strchr),
a malloc/free/realloc over the kernel heap [`_end` rounded to 16,
0x0200_0000) with 16-aligned results and OOM = 0, dec/hex conversions
for u64/i64/u128 in both directions, and the fixed-arity `print_*`
family over the write syscall. No printf until the compiler delivers
varargs (cc-m3 as currently cut); no strcat/strncpy/strstr until the
DOOM shim's measured symbol list asks for them. The normative contract
is SABI Amendment v0.2 (`os/abi/sabi-v0.md`, DRAFT pending owner
sign-off) — this directory is its first conforming implementation, and
`libc.h` mirrors it name for name.

Building a program: start it with `#include "libc.c"`, then from the
repo root run

    lib/c/ccbuild.sh prog.c -o prog.img

which is exactly `cpp -P -nostdinc -I lib/c` → `lang/cc/cc.py` →
`asm/asm.py` with the cc runtime (`crt0.s`, `sys.s`) in front. The
program and the library become ONE translation unit — concatenation is
the linkage, there is no library binary, and every program recompiles
the ~1000 libc lines (seconds; the honest cost of not growing a
proto-linker — multi-input cc.py on the m2 roadmap is the real fix).
Tests: `EMU=$PWD/emu-c/bazel-bin/sahara-emu lib/c/tests/run-tests.sh`,
plus `EMU_PY=1` for the emu-py leg; the host-gcc differential oracle
runs by default (`CC_ORACLE=0` skips loudly).

The library's entire OS surface is the extern `sys_write`/`sys_exit`
wrappers and the `_end` label, all resolved by assembler concatenation
against whichever runtime is on the command line — so a later Oasis
milestone adopts it by placing the same compiled TU on its own image
command line, no libc changes involved.
