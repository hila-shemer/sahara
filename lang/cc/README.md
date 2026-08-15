# cc — the Sahara C compiler (m1 + the M2 amendment)

CC is a freestanding C variant for Sahara. m1 gave it `i64 u64 i128
u128 u8`, typed 128-bit pointers, structs, the operator core, and
defined behavior everywhere C has UB (the ISA's semantics, adopted
wholesale). **M2** (DRAFT, flagged for owner sign-off in `cc-m1.md`)
makes it the C89 core DOOM needs: the full integer model (`i8 i16 u16`
promoting to 64, `i32 u32` first-class at `.32`), function pointers
(`jalr` call sites), `switch`/`for`/`do`/`goto`, `++ -- op= ?: ~ ,`,
enums (= `i32`), unions with defined punning, `void*`, `sizeof expr`,
`typedef static const volatile`, struct/union by value (inline
compiler-emitted copies — no memcpy contract), full global
initializers (nested braces, strings, address initializers — DOOM's
`states[]` is an ordinary global), and **multi-input compilation**:

    python3 lang/cc/cc.py a.c b.c ... -o prog.s
    python3 asm/asm.py -o prog.img lang/cc/rt/crt0.s lang/cc/rt/sys.s [extra .s ...] prog.s
    emu-c/bazel-bin/sahara-emu prog.img

Each input is a real translation unit (own tags/typedefs/statics —
statics mangle to `cc.static.<k>.<name>`); symbols unify across units
structurally with both-files diagnostics; the output is one merged
`.s` (the compiled unit goes LAST — it owns the section seams and the
`__etext/__erodata/__edata/_end` labels). Single-input output is
byte-identical to m1.

The program boots through `rt/crt0.s`, runs `main`, and HALTs with
r0 = its return value; `sys_write`/`sys_exit` speak the SABI §3
syscall mechanism with the Oasis numbers. The language specification
is `cc-m1.md` (m1 signed off; the M2 amendment summary carries its
own sign-off banner). The test suite is `tests/run-tests.sh`: exit
contract, abicheck (`# cc: func` markers, jal AND jalr call sites),
golden `.s`, gcc differential oracle, the generated
signedness×width×operation matrix (`tests/gen-matrix.py` — oracle
family where C89 provably coincides, corners family from the spec's
own semantics), trace-q gates, determinism double-compile/double-run,
multi-file `// input:` cases, and an `EMU_PY=1` leg over the full
case set.
