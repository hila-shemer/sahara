# Work order: cc — the first Sahara compiler, milestone 1 (C subset → SABI)

Branch: `cc` (worktree of this repo). Read first, in this order; they
govern: `os/abi/sabi-v0.md` (ALL of it — you are its second consumer),
ISA-SPEC.md §3–5 and §12, TOOLING-SPEC.md §4 + devspec/asm.md (the
assembler you emit for, including its reserved-name and label rules),
devspec/boot.md §2–3 (crt0 needs the device table), and the idiom of
`os/oasis/kernel/*.s`. Prior art: `slice/cc.py` and
`slice/DECISIONS-LOG.md` — read them for what subset proved sufficient
and which invented semantics later became spec; the code is DISPOSABLE,
it targets the pre-v1 ISA and resurrects nothing.

The design below is FINAL — decisions marked binding are not yours to
reopen; ambiguities you *discover* go to SPEC-ISSUES.md per house
protocol, they do not license improvisation.

Two deliverables of equal rank, in dependency order:

1. **`lang/cc/cc-m1.md`** — the CC-M1 language specification: subset
   grammar, semantics, deviations from C, the SABI mapping, and the
   roadmap. Written FIRST, exactly as SABI was written before Oasis.
2. **`lang/cc/cc.py`** — the compiler: one `.c` in, one SABI-conformant
   `.s` out, assembled by the untouched `asm/asm.py`, plus the tiny
   runtime (`crt0.s`, `sys.s`) and the headless test suite.

The spec proves itself by having a conforming implementation; the
compiler proves itself by emitting code a mechanical checker and two
emulators accept. Divergence between spec and compiler is a bug in one
of them, never something to paper over.

## Why this exists

The machine is proven (two byte-identical emulators), the toolchain is
landed (asm.py, trace-q, replay), SABI v0 is SIGNED OFF (owner review
2026-08-11, commit cfff4aa), and Oasis demonstrates the ABI by hand.
Nothing can yet be written for Sahara except by hand. The owner's
direction: "easiest is to compile a variant of C" — milestone 1 is a
working compiler for a C subset, in Python (the house prototyping
language), freestanding only (no libc; SABI §7 defers that surface).

Stretch destination, set by the owner and binding on the *shape* of m1
though not its scope: eventually compile and run real Linux-world
framebuffer software — DOOM/LVGL class: freestanding C89/C99,
fixed-point, framebuffer + input + mini-libc — on Sahara via the source
route. m1 does not climb that ladder; m1 must not saw off its rungs.

## What already exists — build on it, do not rebuild it

- **SABI v0** (`os/abi/sabi-v0.md`, signed off): register roles and
  calling convention (§1, incl. the §1.4 trust boundary), frames (§2 —
  16-byte slots, st128/ld128, ra top slot), syscall mechanism (§3),
  memory layout (§4), section conventions and boundary labels (§6).
  The compiler conforms totally; add yourself to the consumer registry
  (one line — that is the sanctioned amendment).
- **asm/asm.py** — narrow assembler, frozen: no linker, no macros, no
  includes; `python3 asm/asm.py -o out.img in1.s in2.s` and CLI order
  IS section order (SABI §6). Pseudos `li`/`la`/`mov`/`ret`, width
  suffixes, closed E-code catalog. You change NOTHING in it.
- **Emulators**: `emu-c/bazel-bin/sahara-emu` (reference, fast) and
  `emu-py/sahara-emu-py` (~50 KIPS). Frozen CLI; `HALT r0=<32 hex>`,
  exit 0. trace-q for trace assertions.
- **Idiom**: `os/oasis/kernel/*.s` is what conforming hand-written
  Sahara code looks like (frameless leaves, r8–r15 temps, ldz.8 byte
  loops); `os/oasis/tests/run-tests.sh` is the harness shape to copy.
- **slice/cc.py** — proved a C subset of this size compiles in ~600
  lines of Python with a temp-stack codegen model. Lessons, not code.

## Binding decisions

1. **Spec first: `lang/cc/cc-m1.md`.** Contents, all normative: the
   grammar (EBNF over the token set), the type model and width
   discipline, expression/statement semantics, the frozen deviations
   from C (below), the SABI mapping (how each construct lands on §1/§2
   /§3/§6), the freestanding program contract (crt0, `main`, exit),
   and a **roadmap section** stating the ladder explicitly: m1 = this
   subset; named future milestones add the full C89 integer model
   (i8/u8/i16/u16/i32/u32 as first-class types), unions, enums,
   switch/for/do-while, function pointers, struct assignment and
   by-value passing, static/const, initializer lists — enough C89 for
   ports. Nothing in m1's design — the (size, signedness)-parameterized
   type model, canonical-form handling, struct layout, or the calling
   convention mapping — may make sub-128-bit types, structs, unions, or
   function pointers a redesign later; they must be table entries and
   new productions, not surgery. The roadmap also notes: the FP ABI
   stays deferred (SABI §7) and the flagship port targets are
   deliberately fixed-point, so FP is NOT on the critical path. The
   spec carries a "flagged for owner sign-off" banner exactly as SABI
   did; m2 work may not start before it is signed.

2. **The m1 subset.** IN:
   - Types: `i64 u64 i128 u128 u8`, pointers (128-bit, typed, multi
     level), fixed-size one-dimensional arrays (of scalars, pointers,
     structs), named structs (declaration, `.`, `->`, arrays of,
     pointers to). `void` for functions. `u8` is in because freestanding
     code is byte buffers and strings and the ISA has ldz.8/st.8; it
     costs one row in the width tables and buys the whole string-test
     surface. Wider-narrow types (i8/u16/i16/u32/i32) are m2 — but the
     type model is written for them now (decision 3).
   - Expressions: full binary set `+ - * / % & | ^ << >>`, comparisons,
     `&& || !` (short-circuit, branch-lowered — no if-conversion in
     m1), unary `- & *`, indexing, `.`/`->`, calls, assignment (as in
     C: an expression), explicit casts among scalars and
     pointer↔`u128`/`u64`, `sizeof(type)`, integer/char/string
     literals (string literals → deduplicated rodata `.asciiz`, type
     `u8*`). Literal typing rule pinned in the spec (fits i64 → i64,
     else u64, else i128, else u128).
   - Statements: blocks, declarations with optional initializer, `if`
     /`else`, `while`, `break`, `continue`, `return`, expression
     statements.
   - Functions: definitions and `extern` prototypes (that is how C
     calls hand-written `.s` and vice versa); up to and BEYOND 8
     arguments — the >8 stack-slot mechanism of ISA §12 is implemented,
     not capped away. Return in r0 only (every m1 type fits one
     128-bit register; the r0:r1 pair form stays unused).
   - Globals: scalars and arrays with constant integer initializers
     (→ data), uninitialized (→ bss, zero by the loader contract);
     `extern` globals. String-literal and address initializers are OUT.
   - Comments `//` and `/* */`, decimal/hex literals, char literals.

   OUT (say so in the spec, each with one line of why): floating point
   (SABI defers the FP ABI; ports are fixed-point), varargs (SABI's
   16-byte stack slots leave an obvious future path; note it), struct
   by-value/assignment/return (needs a copy routine; no libc), unions,
   enums, `switch`/`for`/`do`/`goto`, `++ -- += …`, ternary, function
   pointers, `typedef`, `static`/`const`/`volatile` qualifiers (no
   optimizer ⇒ every source access is a real access — state this in
   the spec where volatile would be), bitfields, multi-dimensional
   arrays, preprocessor (no `#include`, no macros — the language is
   .c-file-in, .s-file-out).

3. **Type model and width discipline (the canonical-form firewall).**
   Every value in a register is kept in ISA §3.4 canonical form
   (sign-extended from its width, signed AND unsigned alike) — by
   construction: every arithmetic/compare op is emitted at the width of
   its type (`.64` for 64-bit types, bare/128 for 128-bit), unsigned
   variants (`cmpltu`, `udiv`, `urem`, `shr`) selected by signedness.
   `u8` follows C: it promotes to `u64` in every expression (`ldz.8` on
   load — already canonical since bit 7 < 63) and truncates on store
   (`st.8`). Conversions are explicit lowerings pinned in the spec —
   note the known trap: zero-extending 64→128 cannot use the `zxt` mod
   (amount ≤ 63); it is the `shl 64; shr 64` pair or an AND mask, spec
   picks one. The compiler's type descriptor is (size, signedness) —
   this is exactly what makes m2's i8..u32 table entries, and it is
   the reason canonical-form handling never gets redesigned. Struct
   layout is fixed now, C-style: fields in declaration order, each at
   its natural alignment (u8:1, i64/u64:8, u128/i128/pointers:16,
   struct: max member), size rounded up to alignment. Frozen in the
   spec so future ports never re-layout.

4. **Codegen contract: SABI-conformant by construction, checkable by
   machine.** One frame shape, no alternatives:
   - Non-leaf or stack-using function: prologue exactly
     `add sp, sp, -N`, N a multiple of 16; `ra` saved `st128
     [sp + N-16], r29` iff the function makes calls; epilogue is the
     mirror image at a single `<name>.Lret` label that every `return`
     branches to. Leaf functions with no locals are frameless
     (SABI §2.5).
   - Register plan, m1: arguments arrive r0–r7 and are spilled to
     their frame slots at entry (locals are memory-resident — this is
     the no-optimizer stance, not a bug); expressions evaluate on a
     temp stack r8–r15 with automatic spill to a reserved frame region
     when depth exceeds 8 — compilation is TOTAL, no "expression too
     complex" failures. The compiler NEVER touches r16–r27 (so there
     is no callee-save code to get wrong), never r30/k0, never r27 —
     r27's kernel-gp role (SABI §1.2) costs user code nothing, and not
     allocating it is free insurance. Predicates p1–p7, never live
     across a call (caller-saved per SABI §1).
   - Every save slot 16 bytes via st128/ld128; every slot offset a
     multiple of 16; arguments past 8 stored at [sp+0] slots and read
     at [sp + framesize + 16·i] — alignment holds by construction,
     never by luck (SABI §2.3).
   - Frame size limit: N ≤ 2^20 bytes, loud compile error beyond
     (keeps `add sp, sp, ±N` inside imm22 and keeps the prologue shape
     unique for the checker). Documented m1 limit.
   - Symbol policy: C identifiers pass through verbatim as labels (the
     `.sym` sidecar stays readable, interop stays plain); the compiler
     REJECTS, with a clear error, any identifier that collides
     case-insensitively with the assembler's reserved-name set
     (asm.md §2.3 — a C function named `add` or `ret` would otherwise
     die inside asm.py). Internal labels are `<func>.L<n>` (legal:
     labels must start with a letter/underscore — a leading dot is
     NOT valid in this assembler, whatever slice did). Duplicate
     user symbols across the program are left to asm.py's E031 —
     concatenation IS linkage and its errors are the link errors.
   - Semantics deviations, frozen in the spec (C's UB becomes defined
     behavior, always by adopting the ISA's semantics): two's-
     complement wrap on overflow; shift counts mod width; division by
     zero yields all-ones quotient / dividend remainder, MIN/−1 wraps
     (ISA §5.1); strict left-to-right evaluation of operands and
     arguments. No behavior is "undefined" anywhere in CC-M1.

5. **Deterministic output.** Same input → byte-identical `.s`, every
   run. Concretely: no iteration over unordered containers reaches the
   emitter; label counters are per-function and derived from source
   order; the output header comment carries the input's BASENAME only —
   no absolute paths, no timestamps, no Python-version strings. The
   suite enforces this with a compile-twice `cmp` gate on every case.
   No optimizer beyond the trivial: constant folding of literal
   subexpressions is permitted (it keeps `li` chains short), nothing
   else — no CSE, no register allocation, no reordering. Optimization
   is a future milestone with the determinism gate already in place.

6. **Entry contract and image layout.** `python3 lang/cc/cc.py in.c
   -o out.s` — one translation unit in, one `.s` out, no other flags
   in m1. The emitted file is internally ordered text → rodata → data
   → bss, each section introduced by `.align 16`, bss as
   `.space`/`.align` only, and it DEFINES the SABI §6 boundary labels
   `__etext __erodata __edata _end` at its seams. Consequence, stated
   in the spec: the compiler's output is the LAST file on the
   assembler command line, and a program is exactly

       python3 asm/asm.py -o prog.img lang/cc/rt/crt0.s lang/cc/rt/sys.s [extra .s text files...] prog.s

   crt0 first (it owns `.org 0x1000` and `.entry`), hand-written
   text-only support files in between, compiled unit last. Multi-`.c`
   programs are OUT in m1 (two units would interleave text and data
   and break §6's concatenation layout); the honest path to multi-unit
   is a future `cc.py` that accepts several `.c` files in one
   invocation and emits one interleaved `.s` — note it in the roadmap,
   do not build it.

7. **Runtime: two hand-written files under `lang/cc/rt/`, SABI-
   conformant, marker-commented.**
   - `crt0.s`: `.org 0x1000`, `.entry`; parse the device table per
     boot.md §3 (magic/version check, halt loud on failure; paired
     ldz.64 for u128 fields — never LD128 there); sp = RAM region 0
     `base + len` from the table (never hardcoded — SABI §4.5);
     install `vbase` → the sys.s handler; call `main`; HALT with
     r0 = main's return value. That makes every compiled test a bare
     image that halts with its result — the integration form.
   - `sys.s`: the SYSCALL surface compiled code can call. Two C-
     callable wrappers `sys_write(fd, buf, len)` and `sys_exit(code)`
     that place the number in r7, args r0–r5, r6 = 0, and issue
     `syscall` (SABI §3 exactly); plus the vbase handler: dispatch on
     cause, SYSCALL → epc += 8 then IRET, number 0 `write` appends the
     bytes into a labeled bss capture buffer (`sys_cap`/`sys_cap_len`)
     and returns len, number 2 `exit` → HALT r0 = code, unknown →
     −ENOSYS; any non-SYSCALL trap halts loud with a distinct code.
     Numbers and semantics deliberately match
     `os/oasis/doc/syscalls.md` (0 write, 2 exit) so a compiled
     program is already Oasis-shaped the day an OS can host one.
     Per SABI §5, a SYSCALL handler needs no trap-frame block; the
     handler uses only r8–r15/k0 and stays trivially conformant.

8. **Integration proof — the cheapest honest form (binding).** The
   bare image IS the integration: every test compiles → assembles →
   boots through crt0 → runs real compiled code → HALTs with its
   result. On top of that, ONE dedicated syscall test: a C program
   that `sys_write`s a string and `sys_exit`s a computed value; the
   suite asserts the exit value, the TRAP-cause-10 count via trace-q,
   and the capture-buffer bytes via the `.sym` sidecar + trace-q
   MEMW/last-write. Compiled code does NOT run under Oasis in m1 —
   there is no loader and no user mode (both explicitly deferred,
   SABI §7), and `os/oasis/` belongs to the OS stream; linking C into
   its image would entangle two branches for a demo. The sys.s shim
   exercises the identical SABI §3 mechanism with the identical
   numbers; that is the honest claim, state it in the spec.

9. **Test strategy — headless, both emulators, in `lang/cc/tests/`,
   NEVER under root `tests/` or `trace-q/` (toolchain-owned).**
   Driver `lang/cc/tests/run-tests.sh`, shaped like the Oasis suite
   (`EMU` defaults to `emu-c/bazel-bin/sahara-emu`; `EMU_PY=1` adds
   the emu-py leg). Cases are `lang/cc/tests/cases/*.c`, each carrying
   its expectation in a header comment (`// expect: 0x2a`); outputs
   under `lang/cc/tests/out/` (gitignored via `lang/cc/.gitignore`).
   Assertion layers — each catches a distinct failure class:
   1. **Exit contract**: stdout exactly `HALT r0=<32 hex of expect>`,
      exit 0, `--maxcycles` backstop. Expected values are per-test
      computed results in cc's own value space — never the conformance
      suite's 0x700/r24 sentinel idiom, never Oasis's 0x600D.
   2. **abicheck**: `lang/cc/tests/abicheck.py` statically verifies
      every emitted function against the decision-4 contract. cc.py
      emits one structured marker per function
      (`# cc: func <name> frame=N calls=0|1`) to make the check
      mechanical: prologue/epilogue shape and pairing, N % 16 == 0,
      ra at [sp+N−16] iff calls=1, every st128/ld128 offset % 16 == 0,
      no r16–r27/r30 writes, no naked `ret` off the epilogue path.
      Runs on every case — this is "provably SABI-conformant".
   3. **Golden `.s`**: ~5 checked-in expected outputs, byte-compared
      (`UPDATE_GOLDEN=1` regenerates; small set, catches silent
      codegen churn without freezing all output).
   4. **Host oracle (differential)**: pure-computation cases (marked;
      pointer-width- and MMIO-dependent cases opt out) also build with
      the host C compiler via a 10-line prelude (`typedef unsigned
      long long u64; typedef __uint128_t u128; …`) and a wrapper that
      prints `main()`'s value; result must equal `expect` — two
      independent implementations agreeing on the same source.
      `CC_ORACLE=0` disables with a loud SKIP line, never silently.
   5. **trace-q gates**: every run traced (level 1); zero ILLEGAL /
      UNALIGNED / DEVERR / double-fault anywhere (UNALIGNED is the
      canary for frame-alignment bugs); the syscall test's cause-10
      count and capture-buffer content.
   6. **Determinism**: every case compiled twice → `cmp` on `.s`;
      assembled once; run twice → `cmp` on traces. Both gates in the
      default run, not opt-in.
   7. **emu-py leg** (`EMU_PY=1`): the FULL case set re-run on
      `emu-py/sahara-emu-py` asserting the same HALT lines — the
      programs are microscopic, so unlike Oasis this "smoke leg"
      affords everything; keep each case under ~200k cycles so the
      leg stays under a minute.

   Named hard cases (each is a test, most feed the oracle too):
   recursion (frames + ra discipline); a 10-argument call (>8-arg
   slots, both caller and callee sides); i128/u128 multiply/divide
   (native, no helper routines — verify against the oracle's
   __int128); the u64→u128 zero-extension lowering; unsigned compare
   and divide on u64 values whose canonical form is negative-looking
   (0xFFFF… — the classic canonical-form bug); pointer arithmetic
   with a non-power-of-two struct size; `.`/`->`/array-of-struct
   access; a strlen-in-C over a string literal (u8 promotion);
   division-by-zero and shift-count-mod-width defined semantics;
   globals — initialized data readback and bss-is-zero; C-calls-asm
   and asm-calls-C interop (one extra `.s` fixture); one
   deliberately deep expression that forces temp spilling;
   `break`/`continue` nesting; `&&`/`||` short-circuit (side effects
   on the RHS must not happen).

10. **Scope boundaries (binding).** No `asm/asm.py` changes of any
    kind — a missing directive, pseudo, or expression power is a
    SPEC-ISSUES.md observation plus a compiler-side workaround, never
    a patch. No linker and no object format — SABI §6 concatenation IS
    linkage. No optimizer beyond decision-5's constant folding. No
    edits under root `tests/`, `trace-q/`, `os/`, `emu-c/`, `emu-py/`,
    frozen specs. No FP, no varargs, no preprocessor. No mini-libc:
    the mini-libc + Linux-ish shim (fb + input + malloc) that the
    DOOM/LVGL stretch needs is a SEPARATE future stream that consumes
    cc's output; m1's only nod to it is the roadmap section and the
    non-blocking type model.

## Deliverables

1. `lang/cc/cc-m1.md` — the spec, written first, sign-off banner.
2. `lang/cc/cc.py` — the compiler (entry contract of decision 6).
3. `lang/cc/rt/crt0.s`, `lang/cc/rt/sys.s` — the runtime pair.
4. `lang/cc/tests/` — `run-tests.sh`, `abicheck.py`, `cases/*.c`
   (~30–40 incl. every named hard case), `golden/*.s`, the oracle
   prelude/wrapper, `lang/cc/.gitignore` for `tests/out/` and build
   droppings.
5. SABI consumer-registry line: `cc compiler — lang/cc/` (the one
   sanctioned edit outside `lang/cc/`, alongside SPEC-ISSUES).
6. SPEC-ISSUES.md entries for every assembler/spec gap or invented
   reading encountered (candidates you will likely hit: reserved-name
   collision policy surfacing in a compiler, boundary-label ownership
   when several tools emit sections).
7. `lang/cc/README.md` — three paragraphs: what works, the exact
   build-a-program command line, pointer to the spec.

## Definition of done

Every gate green, from the worktree root:

    # reference emulator present (rebuild after pulling main — stale
    # bazel-bin binaries have burned us before)
    (cd emu-c && ./build.sh)

    # the cc suite, primary leg: compile → assemble → run → assert,
    # abicheck, golden, oracle, trace-q gates, double-compile and
    # double-run determinism
    EMU=$PWD/emu-c/bazel-bin/sahara-emu lang/cc/tests/run-tests.sh

    # emu-py leg: full case set, same HALT assertions
    EMU=$PWD/emu-c/bazel-bin/sahara-emu EMU_PY=1 lang/cc/tests/run-tests.sh

    # root harness contract: untouched and green
    ./run_tests.sh

    # tree discipline: nothing outside lang/cc/ except SPEC-ISSUES.md
    # and the one-line SABI consumer-registry entry
    git status --porcelain

- `cc-m1.md` complete and self-consistent, roadmap + deviations
  sections present, flagged for owner sign-off; `cc.py` demonstrably
  implements it (spot-check: width discipline, frame shape, >8 args,
  boundary labels, reserved-name rejection).
- abicheck passes on every emitted function of every case.
- The syscall test's trace shows exactly the expected TRAP-cause-10
  count and capture-buffer bytes.
- Root `tests/`, `trace-q/`, `os/`, `emu-c/`, `emu-py/`, `asm/`, and
  all frozen specs: zero diffs.
- Every ambiguity encountered is a SPEC-ISSUES.md entry, not an inline
  workaround. Commit in small green steps; `hila-voice` skill for
  commit messages.

## Risks (mitigate, don't relitigate)

1. **Canonical-form bugs** — u64 values live sign-extended (ISA §3.4);
   an unsuffixed compare or divide silently goes 128-bit and "works"
   until 0xFFFF… arrives. Mitigation: the width-discipline rule (every
   op at its type's width), plus the dedicated hard cases, plus the
   oracle.
2. **Reserved-name collisions** — a C function named `add`, `not`, or
   `ret` is a legal C program and an assembler error. Front-end
   rejection with a clear message, documented deviation in the spec.
3. **Nondeterminism creep** — dict iteration, paths, or version
   strings reaching the emitter. The double-compile `cmp` gate runs on
   every case from day one.
4. **Frame/immediate range** — big local arrays can exceed imm22. The
   2^20 loud-error limit keeps one prologue shape and one checker.
5. **Golden-file brittleness** — keep the golden set small (~5);
   correctness lives in execution + oracle, the goldens only catch
   silent churn.
6. **Ladder-blocking shortcuts** — hardcoding 128-bit everywhere,
   punting struct layout, or capping args at 8 would each force an m2
   redesign. The (size, signedness) type model, frozen layout rules,
   and implemented >8-arg path are the insurance; the stretch goal
   (DOOM/LVGL-class ports, fixed-point, via a future mini-libc + shim
   stream) is why the insurance is worth its ~100 lines.
7. **Idiom squatting** — the conformance suite owns 0x700/r24/0x600D
   conventions; cc tests assert their own computed values and their
   own labeled bss words.
8. **Scope creep** — no optimizer, no multi-unit, no libc, no FP. When
   in doubt, the roadmap section is where an idea goes to wait.

Sizing expectation: `cc.py` ~1,200–1,700 lines of Python (slice did a
comparable subset in ~600 against a friendlier ISA — canonical form,
spilling, and globals are the growth); spec ~500 lines; runtime ~150
lines of assembly; tests ~35 cases plus ~450 lines of harness/checker.
One branch, one milestone. If you find yourself far outside this
envelope, stop and reread the scope boundaries before writing more
code.
