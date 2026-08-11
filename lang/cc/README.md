# cc — the CC-M1 compiler

CC-M1 is a freestanding C variant for Sahara: `i64 u64 i128 u128 u8`,
typed 128-bit pointers, one-dimensional arrays, named structs, the full
binary operator set with short-circuit `&&`/`||`, `if`/`while`/`break`
/`continue`/`return`, functions past 8 arguments, globals in data/bss,
string literals, `extern` interop with hand-written assembly in both
directions, and defined behavior everywhere C has UB (the ISA's
semantics, adopted wholesale). The compiler is `cc.py` — one `.c` in,
one SABI-v0-conformant `.s` out, deterministic to the byte; every
emitted function carries a `# cc: func` marker that
`tests/abicheck.py` verifies mechanically against the frame and
register contract.

Building a program (the compiled unit goes LAST — it owns the section
seams and the `__etext/__erodata/__edata/_end` boundary labels):

    python3 lang/cc/cc.py prog.c -o prog.s
    python3 asm/asm.py -o prog.img lang/cc/rt/crt0.s lang/cc/rt/sys.s [extra .s ...] prog.s
    emu-c/bazel-bin/sahara-emu prog.img

The program boots through `rt/crt0.s` (device-table validation, stack
from RAM region 0, vectors), runs `main`, and HALTs with r0 = its
return value; `sys_write`/`sys_exit` go through the SABI §3 syscall
mechanism with the Oasis numbers. The language specification —
grammar, type model, conversions, deviations from C, the SABI mapping,
and the m2+ roadmap — is `cc-m1.md` (flagged for owner sign-off). The
test suite is `tests/run-tests.sh`: exit contract, abicheck, golden
`.s`, gcc differential oracle, trace-q gates, determinism double-runs,
and an `EMU_PY=1` leg over the full case set.
