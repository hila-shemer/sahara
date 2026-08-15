# Work order: mini-libc — the first Sahara C library (SABI v0.2 + lib/c)

Branch: `libc` (worktree of this repo, off a green main at c071c11 or
later). Read first, in this order; they govern: `os/abi/sabi-v0.md`
(ALL of it — §4.6 heap direction, §7's deferral list where "the libc
surface" sits, the amendment rules at the end, and the v0.1 amendment
as the worked precedent for what you are about to do), `lang/cc/cc-m1.md`
(ALL of it — the language you are writing in; you are its toughest
customer on purpose), `lang/cc/rt/crt0.s` and `lang/cc/rt/sys.s` (the
runtime you build on, untouched), root SPEC-ISSUES.md entry 38
(single-owner boundary labels — why two cc outputs cannot concatenate),
`os/oasis/doc/syscalls.md` (the numbers the shim already speaks), and
`lang/cc/tests/run-tests.sh` + `abicheck.py` (the harness pattern to
imitate, NOT to modify).

The design below is FINAL — decisions marked binding are not yours to
reopen; ambiguities you *discover* go to SPEC-ISSUES.md per house
protocol, they do not license improvisation. This stream has a second,
deliberate product besides the library: the cc-m1 friction list. Every
place the subset makes you route around something is a SPEC-ISSUES.md
entry feeding cc-m2 — recorded, not resented.

Two deliverables of equal rank, in dependency order:

1. **SABI amendment v0.2 — the libc surface** — drafted and appended
   to `os/abi/sabi-v0.md` FIRST, flagged DRAFT for owner sign-off,
   exactly as v0.1 was. Per amendment rule 2, the library may be
   developed against the draft only on this branch; nothing merges to
   main until the owner flips the flag.
2. **`lib/c/`** — the library itself: mem*/str*/allocator/conversion/
   output primitives in cc-m1 C, the developer-facing build recipe,
   and the headless test suite on both emulators.

The amendment proves itself by having a conforming implementation; the
library proves itself by tests two emulators and a host oracle accept.
Divergence between amendment and library is a bug in one of them,
never something to paper over.

## Why this exists

The machine is proven, the toolchain is landed, SABI v0 and CC-M1 are
signed off, and cc.py compiles real programs — which today can call
nothing but their own functions and two raw syscall wrappers. The
mini-libc is the middle rung of the DOOM-port ladder set at cc
sign-off: cc (done) → **mini-libc (this stream)** → the Linux-ish
DOOM/LVGL shim (later, on top of these exact routines). The mission:
primitives that (a) bare test images and kernel-mode code can use
today, and (b) the DOOM shim sits on later, without renaming anything.

Dogfood clause, binding: the library is written in cc-m1 C wherever
the subset allows — libc becomes the compiler's biggest consumer, and
that is the point. Assembly is permitted only where the subset
genuinely cannot express the operation, one justification per file,
recorded in the file header and in SPEC-ISSUES.md.

## What already exists — build on it, do not rebuild it

- **SABI v0 + v0.1** (`os/abi/sabi-v0.md`): §4.6 freezes heap
  direction (up from `_end`); the v0.1 draft caps the kernel heap at
  UBASE = 0x0200_0000 (A.2) and keeps the *user* heap deferred (A.8).
  The amendment rules at the end of the file are the process you
  follow; v0.1 is the shape to imitate, section for section.
- **CC-M1** (`lang/cc/cc-m1.md`, signed off): no varargs, no function
  pointers, no struct by-value, one TU per invocation, no preprocessor
  in cc.py — but the owner sanctioned EXTERNAL cpp preprocessing at
  sign-off (§9 item 7). i128/u128 are native. `extern` prototypes are
  the C↔asm interop surface. The tiered change policy means cc.py is
  frozen for you: tier-1 surface is signed, and this stream owns none
  of the tiers.
- **The runtime pair** (`lang/cc/rt/crt0.s`, `sys.s`): device-table
  boot, sp from the table, vectors, `jal main`, HALT; `sys_write`/
  `sys_exit` wrappers speaking Oasis's numbers (0 write, 1 read,
  2 exit — `os/oasis/doc/syscalls.md`). The library talks to the
  world ONLY through these extern wrappers — that is its whole OS
  surface, and why it is OS-neutral.
- **SPEC-ISSUES 38**: the last file on the assembler command line owns
  rodata/data/bss and the four seam labels. Two cc.py outputs cannot
  concatenate. This single fact drives the linkage decision below.
- **The cc test harness** (`lang/cc/tests/run-tests.sh`): exit
  contract, abicheck, determinism double-compile/double-run, trace-q
  gates, capture-buffer assertions, host-gcc oracle, emu-py leg. Copy
  the pattern into `lib/c/tests/`; invoke `lang/cc/tests/abicheck.py`
  by path (read-only reuse); modify nothing under `lang/cc/`.

## Binding decisions

1. **Amendment v0.2 first — the process constraint, non-negotiable.**
   Before any library code, append `## Amendment v0.2 — the libc
   surface (DRAFT — awaiting owner sign-off)` to `os/abi/sabi-v0.md`,
   filling the "libc surface, string/memory routine names" deferral of
   §7. Contents, all normative:

   - **The m1 function list** — exact names, exact semantics, the
     decision-2 signatures. Names are frozen; the C-level parameter
     types are recorded as *m1-subset renderings* (`u8*` standing in
     for `void*`, `u64` for `size_t`), and what is frozen at ABI level
     is the register contract (pointer args in r0/r1, count in r2,
     result in r0, all per SABI §1). The cc-m2 re-rendering to
     `void*`/`size_t` is pre-authorized in the amendment text as a
     source-level retyping with bit-identical ABI — no re-amendment.
   - **Environments served**: kernel/bare now — the heap is SABI
     §4.6's KERNEL-side heap. User-mode programs get this libc only
     when the user heap deferral (v0.1 A.8) is amended; until then a
     user-mode caller of `malloc` is out of scope by definition.
     State this in one paragraph.
   - **Allocator contract**: heap = [`_end` rounded up to 16, ceiling
     0x0200_0000), growing up (§4.6). The ceiling is UBASE's value,
     stated as a v0.2 constant in its own right so it binds whether or
     not v0.1 is signed — when v0.1 lands they coincide by
     construction. Alignment: every returned pointer 16-byte aligned
     (SABI's slot/LD128 granule). OOM: return 0/NULL, never trap,
     never halt. Determinism: same program, same allocation sequence,
     same addresses, every run — trivially true on this machine (no
     entropy, no ASLR), and the amendment says so out loud because
     ports will ask.
   - **The printf deferral**: fixed-arity output helpers only, over
     the write syscall. printf/sprintf are explicitly deferred WITH
     the committed path: cc-m2 delivers varargs (cc-m1.md roadmap),
     then libc m2 adds printf over them as a v0.x amendment. No
     varargs emulation in the meantime — stated as a ban.
   - **Consumer registry**: add `mini-libc — lib/c/` to the registry
     (the one-line sanctioned edit, same as cc did).

   DRAFT flag and sign-off gate exactly like v0.1: develop on this
   branch against the draft; the owner's flag-flip is what licenses
   the merge. Do not start `lib/c/` source files before the amendment
   text exists in the tree — spec first is the house pattern (SABI
   before Oasis, cc-m1.md before cc.py) and this stream keeps it.

2. **The m1 surface — this list, no more.** Everything below is
   expressible in cc-m1 (i128/u128 are native; byte work is `u8`
   loops; multi-level pointers exist). Per function, one line of
   semantics in the amendment; the binding corners are here:

   - **mem\***: `u8 *memcpy(u8 *dst, u8 *src, u64 n)` (returns dst;
     copies forward byte-by-byte ALWAYS — overlap is deterministic
     forward copy, defined, documented: this platform has no UB
     culture and the libc doesn't import one), `u8 *memmove(...)`
     (order chosen by comparison, correct for all overlap),
     `u8 *memset(u8 *dst, u64 c, u64 n)` (c mod 256),
     `i64 memcmp(u8 *a, u8 *b, u64 n)` — returns
     `(i64)a[i] − (i64)b[i]` at the first differing byte, else 0.
     Stronger than C's sign-only contract, deterministic, and the
     differential leg compares signs so the host still oracles it.
   - **str\*** (the minimal honest set): `u64 strlen(u8 *s)`,
     `i64 strcmp(u8 *a, u8 *b)`, `i64 strncmp(u8 *a, u8 *b, u64 n)`
     (both with the memcmp difference convention),
     `u8 *strcpy(u8 *dst, u8 *src)` (returns dst),
     `u8 *strchr(u8 *s, u64 c)` (c mod 256; finds NUL when c = 0;
     returns 0 when absent — pointer-vs-literal-0 compare is in the
     subset). DEFERRED, named in the amendment: `strcat`, `strncpy`,
     `strstr`, `strcasecmp` — the DOOM shim amendment adds them when
     the port's real symbol list is measured, not guessed. Adding a
     name later is a v0.x amendment; that is cheap and honest.
   - **allocator**: `u8 *malloc(u64 n)`, `void free(u8 *p)`,
     `u8 *realloc(u8 *p, u64 n)`. realloc IS in: it costs ~30 lines
     given malloc/memcpy/free (grow = allocate-copy-free; shrink may
     be in-place), the DOOM-era consumers want it, and freezing the
     surface once beats re-amending for one name. No calloc (memset
     exists; one fewer name to freeze). Pinned corners, all defined:
     `malloc(0)` → 0; `free(0)` → no-op; `realloc(0, n)` ≡
     `malloc(n)`; `realloc(p, 0)` ≡ `free(p)`, returns 0; double-free
     is self-sabotage the platform does not detect (same stance as
     writing rodata, cc-m1.md §5.4). Internals: recommended shape is
     a K&R-style address-ordered first-fit free list with a 16-byte
     header (size, next) and coalescing on free — but the binding
     contract is observable: alignment 16, OOM = 0 at the ceiling,
     and the reuse stress test of decision 6 must pass (a
     malloc/free loop of big blocks must NOT creep to OOM — that
     test is what makes free-list reuse and coalescing mandatory in
     practice without freezing the data structure).
   - **conversion** (buffer-filling, fixed arity): to text —
     `u64 u64_to_dec(u8 *buf, u64 v)`, `u64 i64_to_dec(u8 *buf,
     i64 v)`, `u64 u64_to_hex(u8 *buf, u64 v)`, `u64 u128_to_dec(u8
     *buf, u128 v)`, `u64 u128_to_hex(u8 *buf, u128 v)` — each writes
     minimal digits (no leading zeros, "0" for zero, lowercase hex,
     no 0x prefix, leading `-` for negative i64), NUL-terminates,
     returns the length excluding the NUL. Caller buffer minimums,
     stated per function in the amendment: 21 / 21 / 17 / 40 / 33.
     From text — `u64 dec_to_u64(u8 *s, u8 **end)`,
     `i64 dec_to_i64(u8 *s, u8 **end)` (one optional leading `-`),
     `u128 dec_to_u128(u8 *s, u8 **end)`, `u64 hex_to_u64(u8 *s,
     u8 **end)`, `u128 hex_to_u128(u8 *s, u8 **end)` — strict: no
     whitespace skip, no 0x prefix, digits until the first non-digit;
     `*end` = first unconsumed byte (when `end` ≠ 0); no digits
     consumed ⇒ result 0 and `*end == s` (the caller's error check);
     overflow wraps mod 2^width — the language's own arithmetic
     semantics (cc-m1.md §5.3), defined and documented.
   - **output** (fixed-arity, over the write syscall — NO printf,
     decision 1): `i64 print_str(u8 *s)`, `i64 print_u64(u64 v)`,
     `i64 print_i64(i64 v)`, `i64 print_hex(u64 v)`,
     `i64 print_u128_hex(u128 v)`. Each formats into a local buffer
     (conversion routines above) and passes the `sys_write(0, buf,
     len)` result through — the return value is the syscall's,
     errno-negative and all. fd is 0 always: capture buffer under
     the bare runtime, console under an Oasis that adopts the
     library later. The libc never issues SYSCALL itself; it calls
     the extern `sys_write`/`sys_exit` wrappers (decision 3).

   Name check: none of these collide with the asm reserved-name set
   (cc-m1.md §2 — the dot-free mnemonics and register names); the
   compiler would reject a collision loudly anyway, which is the
   backstop.

3. **Linkage: source concatenation — one TU, no label problem
   (binding, and the honest choice).** The two candidates, evaluated:

   - *(a) precompiled `.s`*: build libc.c once with cc.py, strip the
     section seams and boundary labels, prefix internals, place it
     mid-command-line as a text-only file. Rejected: cc.py output
     always owns all four sections and the seam labels (cc-m1.md
     §8.3), so this requires a post-processing stripper; worse, the
     allocator has real mutable state (heap pointer, free list) and
     the conversion helpers want rodata — an earlier command-line
     file must be TEXT ONLY (cc-m1.md §1.3), so state gets embedded
     in text the way sys.s embeds its capture buffer, which for a
     LIBRARY means hand-managed asm data blobs behind C code, a
     stripper script that can silently corrupt, and a second copy of
     SPEC-ISSUES 38's cost. That is a linker grown in a jar.
   - *(b) source concatenation*: the program and the library are
     preprocessed into ONE translation unit by external cpp
     (owner-sanctioned) and compiled together. Truly single-TU —
     cc-m1's native model; the seam labels have exactly one owner
     because there is exactly one unit; allocator state is ordinary
     bss globals; string tables are ordinary rodata. Cost: every
     program recompiles the library. At this scale — cc.py compiles
     the whole suite in seconds, libc is under a thousand lines —
     that cost is FINE, and paying it openly is more honest than
     hiding a proto-linker. **Chosen: (b).** When compile times
     actually hurt, the ladder already has the answer (cc-m1.md §11
     roadmap: multi-input cc.py in m2) — this decision composes with
     it instead of preempting it.

   **The developer-facing recipe, exact.** A libc-using program
   begins with one line:

       #include "libc.c"

   and is built by `lib/c/ccbuild.sh prog.c -o prog.img`, which does
   precisely:

       cpp -P -nostdinc -I lib/c prog.c -o out/prog.tu.c
       python3 lang/cc/cc.py out/prog.tu.c -o out/prog.s
       python3 asm/asm.py -o prog.img lang/cc/rt/crt0.s \
               lang/cc/rt/sys.s out/prog.s

   `lib/c/libc.c` is the aggregator: it `#include`s `libc.h` (the
   declarations, include-guarded — programs may also include it
   directly for readability) and then the per-area sources (decision
   4). cpp is used for `#include` and include guards ONLY in libc
   sources — the language stays cc-m1, the preprocessing stays the
   build's business, exactly the owner's sign-off note. `-P` strips
   linemarkers (cc.py has no `#line`); the resulting friction —
   diagnostics point into the combined TU, not the user's file — is a
   SPEC-ISSUES entry and cc-m2 input, not something to hack around.

   This recipe serves both required consumers today: a **bare image**
   (the command above — crt0 boots, main runs, HALT r0 = result) and
   an **Oasis-hosted kernel-mode consumer** (the same TU compiled the
   same way, placed last on whatever Oasis-image command line a
   LATER Oasis milestone defines; the libc's only external needs are
   the `sys_write`/`sys_exit` labels and the `_end` label, all
   resolved by asm.py concatenation against whichever runtime is on
   the line — that is the whole adoption story, and it is Oasis's to
   execute, not yours).

   Namespace rule: public names are the decision-2 list; libc
   internals are `__libc_*` (m1 has no `static`, so internals are
   globals — the prefix is the containment, documented in libc.h).
   A program defining a libc name collides at compile time (duplicate
   definition, loud) — documented as the reservation mechanism.

4. **Directory: `lib/c/` — outside `lang/cc/` (the compiler doesn't
   own the library) and outside `os/` (the library is OS-neutral; its
   entire world interface is the SABI syscall mechanism via the
   sys_*-shim externs).** Layout:

       lib/c/
         libc.h            # declarations, include-guarded — mirrors v0.2
         libc.c            # aggregator: includes libc.h + src/*.c
         src/mem.c         # memcpy/memmove/memset/memcmp
         src/str.c         # strlen/strcmp/strncmp/strcpy/strchr
         src/alloc.c       # malloc/free/realloc over [_end, 0x0200_0000)
         src/conv.c        # *_to_dec/_to_hex and back
         src/io.c          # print_* over sys_write
         ccbuild.sh        # the decision-3 recipe, ~60 lines
         README.md         # three paragraphs: what works, the exact
                           # build command, pointer to the amendment
         .gitignore        # tests/out/, droppings
         tests/            # decision 6

   Heap base in C: `extern u8 _end;` then `(u64)&_end` — the extern
   emits nothing (cc-m1.md §7), the reference resolves to the unit's
   own seam label at assembly. **If** cc.py rejects or mishandles a
   user extern named `_end` (untested territory — the boundary labels
   are compiler-emitted), the sanctioned fallback is the ONE
   permitted assembly file: `lib/c/heap.s`, a text-only frameless
   leaf `__libc_heap_base: la r0, _end / ret`, placed between sys.s
   and the unit, declared `extern u8 *__libc_heap_base();`. Either
   way, which reading held is a SPEC-ISSUES.md entry. No other
   assembly is expected anywhere in this stream; each additional .s
   needs its own recorded justification.

5. **Everything else in C, and the friction list is a deliverable.**
   No cc.py changes of any kind. When the subset blocks something,
   route around it in C (or the decision-4 asm escape hatch) and
   record the friction in SPEC-ISSUES.md as explicit cc-m2 input.
   Known candidates you will likely hit, to record not to fix:
   no `static` (namespace pollution → `__libc_` prefix), no `void*`
   (u8* renderings + m2 retyping pre-authorization), no `const`
   (rodata reachable only via string literals), cpp `-P` losing line
   info in diagnostics, `extern u8 _end` (decision 4), and whatever
   else the library surfaces. This stream is deliberately cc-m1's
   toughest customer; a rich, precise friction list is success, not
   failure.

6. **Test strategy — headless, both emulators, in `lib/c/tests/`,
   NEVER under root `tests/` or `trace-q/` (toolchain-owned).**
   `lib/c/tests/run-tests.sh`, shaped like `lang/cc/tests/
   run-tests.sh` (same header-comment case metadata: `// expect:`,
   `// oracle:`, `// maxcycles:`, `// capture:`, `// syscalls:`);
   cases are `lib/c/tests/cases/*.c`, each beginning with
   `#include "libc.c"`, built by the decision-3 recipe, outputs under
   `lib/c/tests/out/` (gitignored). Assertion layers:

   1. **Exit contract**: stdout exactly `HALT r0=<32 hex of expect>`,
      exit 0, `--maxcycles` backstop. Expects are per-test computed
      values in this suite's own space — never 0x700/r24, never
      0x600D, never cc's 0xCCBAD codes.
   2. **abicheck**: `python3 lang/cc/tests/abicheck.py` invoked by
      path on every compiled TU (read-only reuse — the tool already
      verifies every emitted function; the libc rides along).
   3. **Determinism**: compile twice → `cmp` the `.s`; run twice →
      `cmp` the traces. Both in the default run. Plus the allocator
      determinism case: two runs of an alloc/free pattern that
      RETURNS a checksum of the addresses it got — byte-identical
      HALT lines are the no-address-randomization proof.
   4. **trace-q gates**: zero ILLEGAL/UNALIGNED/DEVERR/PRIV/PF/PERM,
      no double fault, on every case (UNALIGNED is the canary for a
      malloc that mis-aligns — a 16-byte-header bug surfaces as an
      LD128 trap, loudly).
   5. **Differential leg (host oracle)** where feasible: pure
      mem*/str* cases build on the host with the cc-suite prelude
      pattern PLUS one trick — the oracle prelude pre-defines
      libc.c's include guard, so `#include "libc.c"` becomes a no-op
      and the case's `memcmp`/`strcmp`/`strlen` calls resolve to the
      HOST's libc: a genuine two-implementation differential on
      identical inputs. Cases clamp comparison results to −1/0/1
      themselves so both implementations agree exactly. Conversion,
      allocator, and print cases are `// oracle: no` (the host has
      no `u64_to_dec`, addresses differ, capture is ours) — their
      truth is expect-values plus round-trip identities
      (`parse(format(x)) == x` over a corner table: 0, 1, 9, 10,
      2^64−1, i64 MIN/MAX, 2^128−1, 0xFFFF… canonical-form
      lookalikes). `CC_ORACLE=0` disables with a loud SKIP.
   6. **Allocator stress**: (i) alignment — every returned pointer
      `& 15 == 0`, asserted in-program across mixed sizes; (ii)
      reuse — loop 100 × {malloc(1 MB); free(p)}: must never return
      0 (forces real free-list reuse); (iii) OOM at the ceiling —
      malloc 1 MB blocks until 0, assert the failure IS 0 (not a
      trap) and the count lands in the computed range for
      [_end→0x0200_0000), then free all and allocate once more
      successfully (coalescing works); (iv) realloc grow/shrink with
      content verification via memcmp. Cycle budget: stress cases
      allocate big and touch little (headers, first/last bytes) —
      never memset megabytes — so every case stays under ~200k
      cycles and the emu-py leg stays under a minute.
   7. **Capture assertions** for the print_* family: `// capture:`
      against the sys_cap buffer via .sym + trace-q last-write,
      exactly the cc-suite mechanism, plus `// syscalls: N`.
   8. **emu-py leg** (`EMU_PY=1`): the FULL case set re-run on
      emu-py asserting the same HALT lines.

   ~25–35 cases: per-function units (each amendment corner above is
   a case — memcpy overlap-forward, memmove both directions, strchr
   of NUL, strcmp difference convention, wrap-on-overflow parses,
   minimal-digit formatting, malloc(0)/free(0)/realloc corners), the
   allocator stress quartet, the determinism checksum case, and one
   end-to-end: format a computed u128 in hex, print_str it, assert
   the capture bytes and the exit value — the whole library in one
   image.

7. **Scope walls (binding).** No `cc.py` changes — friction is a
   SPEC-ISSUES entry plus a C/asm route-around, never a patch. No
   `asm/asm.py`, root `tests/`, `trace-q/`, `emu-c/`, `emu-py/`
   changes, no frozen-spec edits beyond the sanctioned v0.2 appendix
   + registry line. No printf and NO varargs emulation hacks (no
   arg-array pseudo-printf — fixed arity is the m1 shape, cc-m2 is
   the path). No Oasis changes: Oasis ADOPTS the library in a later
   Oasis milestone by putting the compiled TU on its own image
   command line — note it in the README, do not do it. No user-mode
   heap and no user-mode anything (v0.1 A.8 stands). No `lang/cc/`
   edits of any kind — the harness and abicheck are imitated and
   invoked, never modified.

## Deliverables

1. `os/abi/sabi-v0.md` — Amendment v0.2 appended (DRAFT flag, decision
   1 contents), consumer-registry line `mini-libc — lib/c/`.
2. `lib/c/libc.h`, `lib/c/libc.c`, `lib/c/src/{mem,str,alloc,conv,
   io}.c` — the library, cc-m1 C throughout (decision-4 `heap.s`
   only if the `_end` extern fails, with its justification header).
3. `lib/c/ccbuild.sh` — the decision-3 recipe, exact.
4. `lib/c/tests/` — `run-tests.sh`, `cases/*.c` (~25–35 incl. every
   named corner), the oracle prelude with the include-guard trick,
   `lib/c/.gitignore`.
5. SPEC-ISSUES.md entries — the cc-m2 friction list (decision 5), one
   entry per route-around, plus the `_end`-extern reading.
6. `lib/c/README.md` — three paragraphs: what works, the exact
   build-a-program command line, pointer to the amendment; one line
   on the later Oasis adoption path.

## Definition of done

Every gate green, from the worktree root:

    # reference emulator present (rebuild after pulling main — stale
    # bazel-bin binaries have burned us before)
    (cd emu-c && ./build.sh)

    # the libc suite, primary leg: cpp -> cc -> asm -> run -> assert,
    # abicheck, oracle differential, allocator stress, determinism
    EMU=$PWD/emu-c/bazel-bin/sahara-emu lib/c/tests/run-tests.sh

    # emu-py leg: full case set, same HALT assertions
    EMU=$PWD/emu-c/bazel-bin/sahara-emu EMU_PY=1 lib/c/tests/run-tests.sh

    # consumers of the amended document stay green, untouched
    EMU=$PWD/emu-c/bazel-bin/sahara-emu lang/cc/tests/run-tests.sh
    os/oasis/tests/run-tests.sh

    # root harness contract: untouched and green
    ./run_tests.sh

    # tree discipline: nothing outside lib/c/ except the sabi-v0.md
    # appendix + registry line and SPEC-ISSUES.md entries
    git status --porcelain

- Amendment v0.2 present, DRAFT-flagged, self-consistent with libc.h
  (spot-check: every public name in libc.h appears in the amendment
  with identical signature rendering, and vice versa).
- Every decision-2 corner is a passing test, not just a sentence.
- The oracle leg actually resolves to the HOST's mem*/str* (verify
  once by breaking our memcmp locally and watching the differential
  catch it — then revert; a differential that can't fail is
  decoration).
- The allocator stress quartet passes on both emulators; the
  determinism checksum case is byte-identical across runs.
- `lang/cc/`, root `tests/`, `trace-q/`, `os/oasis/` (beyond zero
  files), `emu-c/`, `emu-py/`, `asm/`: zero diffs.
- Every route-around has its SPEC-ISSUES.md entry. Commit in small
  green steps; `hila-voice` skill for commit messages. The branch
  does not merge until the owner signs v0.2.

## Risks (mitigate, don't relitigate)

1. **Canonical-form bugs in byte loops** — u8 promotes to u64
   (cc-m1.md §5.1), and 0xFF-heavy buffers are the classic trap for
   the memcmp difference convention. The corner cases + the host
   differential are the mitigation; write the 0xFF/0x00 boundary
   cases first.
2. **`extern u8 _end`** — untested compiler territory (decision 4).
   Probe it in the first hour; the asm fallback is pre-authorized and
   two lines, so this can't stall the stream either way.
3. **Allocator dishonesty** — a bump allocator with a no-op free
   passes naive tests. The reuse-loop and coalescing tests exist
   precisely to make that impossible; they go in BEFORE the
   allocator, red first.
4. **Oracle false confidence** — if the include-guard trick silently
   fails and the host builds OUR sources, the differential compares
   us to us. The break-it-once check in the DoD is the guard.
5. **emu-py cycle blowups** — 50 KIPS meets megabyte memsets. Stress
   cases allocate big, touch little; every case under ~200k cycles;
   `// maxcycles:` is a backstop, not a budget.
6. **Surface creep** — strcat "while we're here", a sprintf "just
   for tests", calloc "it's trivial". The amendment IS the surface;
   a name not in it does not get written. Additions wait for the
   DOOM-shim amendment with measured need.
7. **cpp creep** — the sanction is #include + guards in the build,
   not a macro layer. Libc sources using cpp conditionals or macros
   would fork the language by stealth; don't.
8. **Amendment drift** — libc.h and v0.2 disagreeing after a rename.
   The DoD spot-check is manual but mandatory; keep the two in one
   commit whenever either moves.

Sizing expectation: amendment ~150–200 lines; library ~700–1,000
lines of cc-m1 C across the five src files; ccbuild.sh ~60 lines;
tests ~30 cases plus ~350 lines of harness (mostly lifted patterns).
One branch, one milestone, merge gated on the owner's v0.2 signature.
If you find yourself far outside this envelope — or patching any
frozen tool — stop and reread the scope walls before writing more
code.
