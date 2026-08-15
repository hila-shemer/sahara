# Work order: cc — milestone 2 (the C89 core: function pointers, the full integer model, aggregates)

Branch: `cc-m2` (worktree of this repo, off a green main). Read first,
in this order; they govern: `lang/cc/cc-m1.md` (ALL of it — SIGNED
OFF 2026-08-12; its §12 roadmap is this milestone's frame, its tiered
change policy is the amendment mechanism you will use, and its §9
promoted FUNCTION POINTERS to m2's first item at sign-off),
`lang/cc/cc.py` (the implementation you are growing — the
(size, signedness) type model, the ring temp allocator, the
LOADS/STORES/suffix tables are the extension points this order names),
`os/abi/sabi-v0.md` §1–3 (the convention function pointers ride on —
JALR indirect calls are already inside it; you amend NOTHING there),
ISA-SPEC.md §3–5 and §12 (width field, narrow-ALU semantics at
w ∈ {32, 64}, the `sxt`/`zxt` mods, LDS/LDZ/ST at 8/16/32/64),
devspec/asm.md §4 (expression value kinds — data directives take
label expressions in pass 2, which is what makes address initializers
expressible without touching the assembler; also `.half`/`.word`),
root SPEC-ISSUES.md 37–38 plus ANY cc-tagged friction entries the
parallel mini-libc stream has filed by the time you start (that
stream's work order makes a cc-m2 friction list one of its
deliverables — sweep it now and again before your DoD),
`mini-libc-prompt.md` decision 3 (why multi-input is the committed
relief path) — and `lang/cc/tests/run-tests.sh` + `abicheck.py`, the
harness you extend in place.

The design below is FINAL — decisions marked binding are not yours to
reopen; ambiguities you *discover* go to SPEC-ISSUES.md per house
protocol, they do not license improvisation.

Two deliverables of equal rank, in dependency order:

1. **The M2 amendment to `lang/cc/cc-m1.md`** — written FIRST, per
   that document's own change policy (decision 2 below fixes the
   form). Tables grow rows, the grammar grows productions, every
   change carries a dated change-log entry, and the whole delta is
   flagged for owner sign-off exactly as m1 was.
2. **`lang/cc/cc.py` grown to implement it**, plus the extended test
   suite: abicheck through function-pointer calls, the
   signedness × width × operation host-oracle matrix, the
   struct-by-value aliasing suite, multi-input cases, and one
   DOOM-shaped integration case run on both emulators.

Divergence between spec and compiler is a bug in one of them, never
something to paper over.

## Why this exists

CC-M1 is signed off and cc.py compiles real programs. The strategic
frame, owner-set and binding: the project is walking toward a DOOM
port (via doomgeneric — real C89), milestone by milestone. What
doomgeneric actually uses is the m2 shopping list: structs by value,
unions, enums, switch/for/do/goto, ++/compound-assign/ternary,
8/16/32-bit signed and unsigned integers, global initializers full of
arrays and structs of constants, sizeof, casts, function pointers
everywhere, and varargs for the printf family. m2 is ONE honest
milestone cut from that list; everything not in it is named in the
cc-m3 scope of decision 12 so nothing is silently dropped. The
mini-libc stream runs in parallel and is cc-m1's toughest customer;
m2's multi-input compilation is its committed relief path.

## What already exists — build on it, do not rebuild it

- **cc.py (~1,200 lines)**: scalar types are `('int', bits, signed)`
  tuples — the m1 spec's whole bet was that sub-widths become table
  rows. The tables that must grow: `TYPE_KW`, `LOADS`/`STORES`
  (currently {8, 64}), `suffix()` (currently ".64"/""),
  `DATA_DIRECTIVE` (currently {1, 8, 16}), `promote()` (currently u8
  only), `convert()` (the 64/128 matrix), `index_to_128()` (u64
  only). The bet mostly holds; decision 4 says exactly where it
  doesn't.
- **SABI v0 §1**: JALR writes ra like JAL; an indirect call is
  convention-identical to a direct one. Nothing to amend.
- **The assembler, frozen**: `.byte/.half/.word/.quad/.oct` all
  exist; data-directive values are pass-2 expressions that accept
  labels and ADDR ± CONST (asm.md §4.2/4.4) — address initializers
  are `.oct funcname`, no relocation story needed. ALU mods
  `sxt N`/`zxt N` (amount ≤ 63) give one-instruction sub-width
  sign/zero extension. You change NOTHING in asm.py.
- **The m1 test suite**: 37 cases, abicheck, ~5 goldens, host-gcc
  oracle with prelude/wrapper, determinism double-compile and
  double-run, trace-q gates, emu-py full leg. It is the regression
  net under every m1-surface refactor you make: m1 programs must
  compile to byte-identical output unless a golden is deliberately
  re-blessed with a reason.
- **SPEC-ISSUES 38**: the compiled unit owns the section seams —
  which is why multi-input lands inside cc.py (one emitter) and not
  as any linker-shaped thing.

## Binding decisions

1. **The m2 cut.** IN, in implementation order (each phase leaves the
   suite green):

   1. **Function pointers** — owner-fixed first item.
   2. **The general declarator parser** — the same rewrite carries
      multi-dimensional arrays and parenthesized declarators; do it
      once, under function pointers.
   3. **Sub-128 integer types**: `i8 i16 i32 u16 u32` first-class.
   4. **Control flow**: `switch` (compare-chain lowering), `for`,
      `do`-`while`, `goto`/labels.
   5. **Operator sugar**: `++ --` (pre/post), compound assignment
      (all ten binary ops), `?:` (branch-lowered like `&&`), `~`,
      unary `+`, the comma operator (DOOM `for`-headers use it).
   6. **enums, unions, `void*`, `sizeof expr`, cast completion,
      struct self-reference through pointers** (`struct S *next;`
      inside `S`, and forward `struct S;` — DOOM's thinker lists).
   7. **`typedef`, `static`, `const`, `volatile`** bookkeeping.
   8. **Struct/union by value**: assignment, initialization,
      parameters, returns.
   9. **Global initializers, full**: nested brace lists for
      arrays/structs, string-literal initializers, address
      initializers (`&global`, array names, function names — DOOM's
      state tables are exactly this).
   10. **Multi-input single-output compilation**.

   Ruled IN or OUT, with the reasons the owner asked for:

   - **Multi-input** — IN. Not mere ergonomics: cpp concatenation
     (the libc path that works today) cannot survive doomgeneric's
     per-file `static`s — same-named file-scope statics in different
     .c files collide in one concatenated TU, so multi-input plus
     static mangling is the *correctness* path to multi-file C89,
     and the mini-libc order names it as the committed relief for
     its recompile-everything cost. Honest cost: a Unit refactor
     (per-TU namespaces, cross-TU symbol unification) and harness
     growth — decision 8 pays it last, when the language work is
     done.
   - **Sub-width integers** — IN. DOOM is unportable without them,
     and they are the riskiest correctness area in the milestone
     (decision 4 and the §test-matrix are shaped around that).
   - **Control flow + sugar** — IN. Front-end productions per
     cc-m1.md §9; DOOM uses every one of them pervasively; none
     touches the back end.
   - **enums, unions** — IN. Representation decisions are one line
     each (decision 6); DOOM uses both.
   - **sizeof/casts completion, `void*`** — IN. Small, and every
     DOOM file needs them.
   - **Struct by value** — IN. DOOM passes and returns small structs
     (and assigns them constantly); decision 7 picks the copy
     mechanism that keeps the libc wall standing.
   - **static/const/typedef/volatile** — IN. Bookkeeping, but
     load-bearing bookkeeping: `static` is what makes multi-input
     correct, `const` is what routes DOOM's tables to rodata,
     `typedef` is the port-compatibility hook (`typedef i32 int;` is
     legal — `int` is not a cc keyword — and is how the future shim
     maps C89 names onto cc types).
   - **Global initializers** — IN. DOOM is one-third initialized
     tables by weight; asm.md §4.2 makes address initializers
     expressible today (verified above), so this is compiler work
     only.
   - **varargs** — OUT, to cc-m3, named there. Weighed honestly: the
     SABI 16-byte-slot design makes the mechanism cheap, but it
     drags a second callee prologue shape (spill all eight argument
     registers), a third abicheck shape, and a `va_*` builtin
     surface into a milestone that is already twice m1's size — and
     its only consumer (printf, in libc-m2) cannot start until
     cc-m2 lands regardless, so sequencing it first buys nothing.
     NOTE: this contradicts the mini-libc work order's phrasing
     ("cc-m2 delivers varargs, then libc m2 adds printf") — that
     conflict is flagged for the owner in this order's final section
     and must be resolved at sign-off of the m2 amendment, not
     unilaterally.
   - **FP** — OUT, stays deferred with SABI §7; the port targets are
     fixed-point (cc-m1.md §12). Not on any critical path.
   - **bitfields, designated initializers, jump-table switch, object
     format/linker** — OUT, named in decision 12.

2. **Spec process: amend `lang/cc/cc-m1.md` in place — no separate
   cc-m2.md.** Justification, since the house has two patterns: SABI
   amendments *append* because they fill self-contained deferrals
   (v0.1 is new sections). m2's changes are row and production
   extensions of existing normative tables — the type table, the
   conversion table, the operator table, the statement grammar. A
   second document overlaying row-diffs on frozen tables would fork
   the single source of truth; the honest form is the one cc-m1.md's
   own change policy already prescribes: tier-1 *additions* land in
   the live sections with a dated change-log entry in the same
   change. So: grow the tables and grammar in situ; append one
   `## M2 — amendment summary` section listing every addition with
   its change-log date (the SABI-style audit trail); the file keeps
   its name exactly as `sabi-v0.md` kept its name while carrying
   v0.1 — the filename marks the founding milestone and every
   cross-reference in the tree survives. The summary section carries
   the banner `M2 AMENDMENT — FLAGGED FOR OWNER SIGN-OFF`; the
   branch does not merge until the owner signs, and nothing already
   frozen in m1 changes meaning (additions only; the u8→u64
   promotion, the pinned m1 lowerings, and all m1 deviations stand).

3. **Function pointers — type model and lowering (the owner-fixed
   first item).** The back end is trivial and stays trivial; the
   work is the front end, exactly as the sign-off note said.

   - **Type representation**: one new constructor,
     `('func', ret, (param-types…))`. It appears ONLY as a pointee:
     `ret (*p)(A, B)` is `('ptr', ('func', ret, (A, B)))`. A
     function *designator* (a name of declared function type) is not
     a value: it decays immediately to pointer-to-function (`la rX,
     name`), the same move array decay already makes. `is_scalar`
     stays false for `('func', …)`; `t_size`/`t_align`/`sizeof` on a
     function type is a loud error; pointer-to-function is 128 bits
     like every pointer.
   - **Declarators**: replace the m1 ad-hoc `type * name [N]` parse
     with the standard two-stage C declarator parser (base type +
     recursive declarator with postfix `[]`/`()` and prefix `*`,
     parentheses for precedence). This is the one real piece of new
     machinery in the item, and it must reproduce the m1 AST exactly
     for m1 syntax — the golden set is the proof.
   - **Calls**: the call node takes a callee *expression*. A bare
     identifier naming a declared function keeps the m1 `jal NAME`
     path (goldens undisturbed); anything else evaluates the callee
     onto the temp stack like any operand — strict left-to-right:
     callee first, then arguments — and the call site emits
     `jalr ra, rC, 0` where the m1 sequence emitted `jal NAME`.
     Everything around it (spill-all-live, argument staging, r0
     capture, reload) is unchanged; that is the whole point of
     riding the existing convention.
   - **Semantics**: assignment/comparison of function pointers of
     identical type; `== !=` against literal `0`; explicit casts
     between function-pointer types and to/from
     `u64/i64/u128/i128` (defined — no-UB culture; calling through
     a wrong-type or garbage pointer is self-sabotage the platform
     may or may not trap, same stance as writing rodata).
     Implicit conversion: exact type match only. `void*` ↔ function
     pointer: explicit cast only (documented deviation; C89 says
     nothing portable here either). `&f` and plain `f` are the same
     pointer; `(*p)(x)` and `p(x)` both call.
   - **abicheck**: `jalr` joins `jal` as a call site — marker
     `calls=1`, ra discipline identical, and the checker verifies
     `jalr` is always the `ra, rX, 0` form. This is the only
     abicheck semantic change in m2 (plus the new-mnemonic
     allowlist rows of decision 4).

4. **Sub-128 integers — what the width-discipline design really
   touches (verified against cc.py).** The claim "new types are
   table rows" is TRUE for: `TYPE_KW`, `t_size`/`t_align` (already
   `bits // 8`), struct layout (already natural-alignment-general),
   constant folding (`sext`/`to_val` already parameterized by bits),
   `DATA_DIRECTIVE` (+{2: `.half`, 4: `.word`} — both exist in
   asm.py), and `suffix()` (+".32"). It is NOT purely rows in four
   places, and those four are where the bugs will live: `promote()`,
   the `convert()` matrix, `LOADS`/`STORES` keying, and the
   pointer-index path (`index_to_128`). Pinned design:

   - **Two-tier width model, following the ISA.** The ALU has no 8-
     or 16-bit form (ISA §3.4: narrow ALU widths are {32, 64}), so
     8- and 16-bit types PROMOTE in every expression, exactly like
     m1's u8: `i8, i16 → i64`; `u8, u16 → u64` (u8's row is frozen
     m1 surface; the new rows follow its pattern). 32-bit types are
     FIRST-CLASS at width 32: `.32` ALU/compare suffix, unsigned
     variants (`cmpltu.32`, `udiv.32`, `urem.32`, `shr.32`) by
     signedness, canonical form = sign-extension from bit 31 — for
     i32 AND u32 alike, exactly as u64 lives sign-extended from bit
     63. `u32 op u32` therefore wraps at 32 bits like C; `i32`
     overflow wraps too (defined, the ISA's semantics — the m1
     deviation family).
   - **Loads/stores** (LOADS/STORES become keyed by (bits, signed)):
     `i8: lds.8`, `i16: lds.16` (sign-extension IS the promoted i64
     canonical image); `u8: ldz.8`, `u16: ldz.16` (zero-extension is
     the promoted u64 image — bit 15 < 63 so it is canonical);
     `i32 AND u32: lds.32` (sign-extension from bit 31 IS the
     32-bit canonical form — the u64/lds.64 argument one octave
     down). Stores: `st.8/st.16/st.32` truncate from any wider
     canonical image.
   - **Conversions — the new pinned lowerings** (the m1 rows are
     untouched; new rows use the ISA mods, one instruction each):
     - anything → `i8`: `or.64 rd, zero, rs sxt 8`; → `i16`:
       `… sxt 16` (result = the promoted i64 image).
     - anything → `u16`: `or.64 rd, zero, rs zxt 16`; → `u8` keeps
       m1's `and.64 rd, rs, 0xff` (frozen row, don't churn it).
     - anything wider → `i32`/`u32`: `or.32 rd, rs, 0`
       (re-canonicalize at 32 — the same trick as m1's 128→64
       `or.64 rd, rs, 0`).
     - `i32` → 64/128-bit: none (the canonical-32 image already IS
       the sign-extension — value-correct for i64 and i128).
     - `u32` → 64/128-bit: `or.64 rd, zero, rs zxt 32` (the mod
       amount fits — only the 64→128 case needs m1's shl/shr pair,
       because zxt caps at 63).
   - **The zero-extension discipline (the milestone's riskiest
     line).** Every place a value participates at a WIDER width than
     its type, an unsigned sub-width value must be zero-extended
     from its own width first, because its canonical image is
     sign-extended and reads negative when bit (w−1) is set. The
     audited list, each with a pinned lowering and a test: pointer
     indexing/arithmetic (`index_to_128` grows: u32 index →
     `zxt 32`, u64 → the shl/shr pair; i32 index needs NOTHING, its
     canonical image is the correct 128-bit value; promoted
     u8/u16 are non-negative already), balancing to a larger common
     type, explicit widening casts, `return` widening, argument
     widening, and shift counts. Nothing else in the compiler may
     widen a value.
   - **Promotion/balancing deviations from C, documented in the
     spec**: sub-32 types promote to 64-bit (C promotes to 32-bit
     int) — same family as the frozen u8 rule; where C would
     overflow `int` (UB), cc computes the defined 64-bit result.
     Consequence for the oracle: decision 9's matrix generator
     emits, for the gcc leg, only expressions whose C89 and cc
     semantics provably coincide (operands pre-cast to a common
     ≥32-bit type, no signed overflow, in-range shift counts); the
     deviation corners run as expect-value cases on the two
     emulators instead.
   - **Literals**: the m1 typing rule stands unchanged (first of
     i64/u64/i128/u128) — sub-width literals do not exist, exactly
     as C's do not.

5. **switch, and the rest of control flow.** `switch` lowers to a
   **linear compare chain** (evaluate the controlling expression
   once into a temp slot; one `cmpeq` + branch per `case` in source
   order; `default` last), NOT a jump table — binding, with the
   reason on the record: a jump table is an optimization, and the
   no-optimizer stance is m1 policy this milestone keeps; the chain
   is deterministic, abicheck-transparent (branches stay
   in-function), and needs no label-address table machinery. DOOM's
   switches are tens of cases, not thousands; when profiling on real
   ports ever demands tables, that is optimizer-stream work over the
   already-running determinism gate (named in decision 12).
   Semantics: controlling expression any integer type, promoted;
   case labels are constant expressions, converted to the promoted
   controlling type, duplicates a loud error; fallthrough is C's;
   `break` binds to the nearest enclosing loop-or-switch,
   `continue` to the nearest loop only. `for` and `do`-`while` are
   productions over the existing loop machinery (empty `for`
   clauses legal). `goto`: labels are function-scoped, defined once,
   forward references resolved at function end; a `goto` into a
   scope is legal C89 and legal here (locals have frame slots for
   the whole function — no lifetime machinery to violate).
   Constant-expression evaluation (case labels, array sizes, enum
   values, global initializers) grows to the C89 constant-expression
   grammar including `?:`, comparisons, `&& || !` and casts among
   integer types — that is front-end necessity, not optimization,
   and it stays literal-only with `/` and `%` still never folded at
   runtime (the m1 rule; in constant expressions they ARE evaluated,
   with the ISA's division semantics, because `.space` and case
   labels need values — state this distinction in the spec).

6. **enums and unions — representations.**
   - **enum**: a named or anonymous enum type is `i32`. Rationale:
     m2 makes 32-bit types real, `i32` matches C89 `int` layout so
     DOOM structs with enum members keep their expected shapes, and
     enum-typed values ride the entire existing i32 row (loads,
     compares, switch) for free. Enumerators are compile-time `i32`
     constants (value = previous + 1, `= const-expr` resets, wrap at
     32 loud-errors instead — values must fit i32), live in the
     ordinary identifier namespace, usable in constant expressions
     and case labels. `sizeof(enum E)` = 4.
   - **union**: all members at offset 0; size = max member size
     rounded up to alignment; alignment = max member alignment.
     Reading a member other than the one last written is DEFINED:
     the bytes reinterpret little-endian at the reading member's
     type (the no-UB culture — DOOM's fixed/angle punning just
     works, and the spec says so in one sentence). Unions follow
     structs everywhere grammatically (members, by-value copy,
     globals); a union global initializer takes a single brace
     initializer for its FIRST member (C89's rule).

7. **Struct/union by value — the copy mechanism and the call
   convention (the libc wall holds).**
   - **Copy mechanism: inline, compiler-emitted — never a call to
     memcpy.** Binding, with the reasons: (a) dependency-free — m1's
     property that compiled output references only symbols the
     source declared is worth keeping, and it is what makes "no
     coupling to the parallel mini-libc stream" true rather than
     aspirational; (b) an emitted `jal memcpy` would invent a hidden
     runtime contract that neither SABI (libc surface deferred, §7)
     nor the unsigned v0.2 draft licenses; (c) bare no-libc programs
     keep working. Shape: copies go through a temp-stack address
     pair in units of the aggregate's alignment (16 → ld128/st128,
     8 → lds.64/st.64, 4/2/1 likewise), straight-line up to a small
     pinned count, an emitted loop above it. The unit choice is
     semantics (alignment-safe by construction); the
     unroll threshold is tier-2 codegen and may be re-blessed.
   - **Assignment/initialization**: `a = b` on same-type
     structs/unions; evaluation order lvalue-address then
     rvalue-address, then the copy; the assignment expression's
     value is the lvalue (usable, though rarely used). Overlap
     (self-assignment, aliased pointers) is defined: forward copy,
     documented — and tested.
   - **Parameters**: at each call site the caller copies the
     aggregate argument into a fresh staging slot in its own frame
     and passes the ADDRESS in the ordinary argument position
     (register or 16-byte stack slot). The callee uses the staging
     copy directly as the parameter object — no second copy; it may
     write it (the copy is call-lifetime, caller-dead). C semantics
     hold because every call makes a fresh copy; `&param` is legal
     and points at the staging copy.
   - **Returns**: functions returning an aggregate take a hidden
     result pointer as argument 0 (r0); explicit arguments shift
     right by one. The callee copies the return value through that
     pointer before `.Lret` and returns the pointer in r0. The
     caller allocates the result slot in its frame.
   - **Layering, stated in the spec and in SPEC-ISSUES**: this is
     cc's mapping of aggregates ONTO SABI v0 — every actual register
     and stack slot still carries a scalar or pointer, so SABI is
     untouched and abicheck's frame rules hold unchanged. The
     convention is frozen in the cc spec (it is interop surface:
     hand-written .s can now be called with and call with
     aggregates); a SPEC-ISSUES entry records that a future SABI
     revision may want to bless it platform-wide.

8. **`static`/`const`/`typedef`/`volatile`, and multi-input — the
   two are one design.**
   - **typedef**: scoped name → type aliases, one table per scope;
     a typedef-name is a type-specifier token thereafter. This is
     deliberately the port-compat hook (`typedef i32 int;` — legal
     because cc never reserved `int`).
   - **const**: tracked as a type qualifier for exactly two effects:
     assignment through a const lvalue is a compile error, and a
     `const` GLOBAL with an initializer is emitted to RODATA instead
     of data (DOOM's tables land read-only, as they should). No
     other semantic weight — there is no optimizer to inform.
   - **volatile**: accepted, recorded, and semantically already
     satisfied — the spec states in one sentence that with no
     optimizer every source access is a real access, so volatile's
     contract holds for every object (the m1 §9 note graduates from
     "why absent" to "why trivially honored").
   - **static** file-scope: internal linkage, rendered as label
     `cc.static.<k>.<name>` where `<k>` is the input file's 0-based
     CLI index — dots make collision with user symbols impossible
     (the `cc.str.<n>` precedent). static locals:
     `cc.static.<k>.<func>.<name>`, constant initializers only
     (C89's own rule), emitted to data/bss like a global.
   - **Multi-input single-output**: `python3 lang/cc/cc.py a.c b.c …
     -o out.s`. Each input is a real translation unit: its own
     struct/typedef/enum namespaces and its own statics; functions,
     extern objects, and non-static globals unify across units by
     exact-signature/type agreement (the m1 duplicate rules extend
     across files; mismatch is a loud error naming both files);
     exactly one `main` across the set. One merged emission —
     single text section in (file, source) order, one shared
     deduplicated string pool, one set of seam labels — SPEC-ISSUES
     38's single-owner rule satisfied by construction. Diagnostics
     carry the RIGHT file's name and line (this is the fix for the
     libc stream's `cpp -P` friction). Determinism: the header
     comment lists input basenames in CLI order; single-input
     invocations stay byte-identical to m1 output (golden-verified).

9. **Global initializers, full.** Brace initializers for arrays and
   structs, nested (inner braces optional per C89's
   fill-in-order rule is NOT adopted — braces are required at each
   aggregate level, a documented simplification; DOOM's tables are
   fully braced); scalar members take constant expressions; partial
   initialization zero-fills the remainder; string literals
   initialize `u8` arrays (bytes + NUL, size-checked) and `u8*`
   scalars (pointer to the pooled rodata object); ADDRESS
   initializers — `&global`, `array_name`, `array_name + k`,
   `function_name` — emit as `.oct label` / `.oct label + off`
   (16-byte pointers; asm.md §4.2 ADDR ± CONST, pass-2 resolution;
   the label may live in any input unit or in an earlier .s on the
   assembler line). A function-pointer table global — DOOM's
   states[] shape — is therefore an ordinary initialized global.
   Sub-width array data emits via `.half`/`.word` rows in the
   existing chunked style.

10. **Test strategy — everything m1 had, scaled, plus four new
    instruments.** All seven m1 layers stay on by default for every
    case (exit contract, abicheck, goldens, host oracle, trace-q
    gates, double-compile/double-run determinism, emu-py full leg).
    Growth:

    - **abicheck** (extended in place, it is cc-owned): `jalr` as a
      call site per decision 3; allowlist rows for
      `lds.16/lds.32/ldz.16/st.16/st.32` and mod-suffixed operands
      (`… sxt 8`); nothing else loosens.
    - **The signedness × width × operation matrix** — the sub-width
      insurance. A checked-in generator
      (`lang/cc/tests/gen-matrix.py`) emits matrix case files over
      {i8,u8,i16,u16,i32,u32,i64,u64} × {+ − * / % << >> < <= == &
      | ^ ~, unary −, widening and narrowing casts} × a corner
      vector (0, 1, ±1 images, MIN, MAX, 0x80…, 0xFF…,
      mixed-signedness pairs), folded into running checksums. Two
      families: `matrix-oracle-*.c` — restricted to forms where C89
      and cc semantics coincide (decision 4), so gcc is a true
      second implementation; `matrix-corners-*.c` — the deviation
      semantics (promotion divergence, wrap, shift-mod-width,
      division corners at 8/16/32 bits), `// oracle: no`, expects
      computed by the generator from the spec's own semantics
      (a third implementation of the semantics, in the generator —
      disagreement between generator, compiler, and emulators is
      the alarm). Generated cases are CHECKED IN (determinism;
      regeneration is `gen-matrix.py --update` + review). Each file
      sized under ~200k cycles so the emu-py leg keeps affording
      the full set.
    - **Struct-by-value aliasing/corner suite**: self-assignment;
      assignment through two pointers to the same object; odd-size
      align-1 structs (u8[7]) and nested aggregates; by-value param
      mutation invisible to the caller; `&param`; an aggregate
      argument in the >8-arg stack-slot region; struct return into
      an expression (call argument position); recursion with struct
      params; function-pointer call returning a struct (the two
      features composed).
    - **Function-pointer suite**: direct-vs-indirect same-function
      agreement; dispatch through a table in a struct field; fnptr
      as argument and return value; extern .s function called
      through a pointer (fixture — interop both ways); >8 args
      through a pointer; null-compare and cast round-trip. abicheck
      runs on all of it — that is "abicheck on every function
      including through function-pointer calls".
    - **Multi-input cases**: the harness grows a multi-file case
      form (per-case extra-input header key, same style as
      `// fixture:`); positive: statics with the same name in two
      files, cross-file extern global + function use, struct-by-name
      defined identically in both files; negative: conflicting
      signatures across files (diagnostic names the right file),
      duplicate non-static definition, two mains.
    - **One DOOM-shaped integration case** (the milestone's honest
      exit exam): a const lookup table in rodata, a global
      address-initialized dispatch table of `{i32 tag; i64
      (*fn)(i32);}` records, and a switch-driven state machine over
      u16/i32 state, run for a few thousand ticks, folding a
      checksum returned through main — compiled from TWO input
      files, assertion by expect value, abicheck, determinism, and
      both emulators (the emu-py leg already reruns everything;
      keep it under ~200k cycles).
    - **Goldens**: ~5 new (indirect call, switch chain, struct
      copy in/out, sub-width conversion cluster, a two-input
      compile), m1 goldens byte-stable except deliberate,
      change-logged re-blessings.

11. **Scope boundaries (binding).** No `asm/asm.py` changes — a gap
    is a SPEC-ISSUES entry plus a compiler-side workaround. Root
    `tests/` and `trace-q/` are toolchain-owned: never touched. No
    optimizer work beyond what correctness forces (constant
    expressions per decision 5 are front-end necessity; nothing else
    — no jump tables, no CSE, no allocation). `os/`, `emu-c/`,
    `emu-py/`, frozen specs: zero diffs; SABI untouched (the
    aggregate convention is cc-level, decision 7). The mini-libc
    stream runs in parallel: no coupling in either direction beyond
    what decision 7 already settled (inline copies mean cc never
    calls libc; libc's later re-typing to `void*`/`size_t` is
    pre-authorized in its own amendment and needs nothing from you
    beyond `void*` existing). Sweep SPEC-ISSUES for cc-tagged libc
    friction at start and before DoD; friction you can now retire is
    retired by the feature landing, not by editing their entries.

12. **The remainder — cc-m3, named now so nothing is silently
    dropped.** Append to cc-m1.md §12 in the same amendment:
    - **varargs + the `va_*` surface** — m3's first item, the printf
      enabler, over SABI's uniform 16-byte slots (spill-r0–r7
      callee prologue variant + abicheck's third shape); libc-m2's
      printf follows it.
    - **The port-compat layer**: the C89-names header
      (`typedef`s + cpp defines mapping char/short/int/long,
      `register`-away, etc.) — property of the DOOM-shim stream,
      enabled by m2's typedef.
    - **bitfields** — still no measured consumer; if the port
      surfaces one, it arrives with the measurement.
    - **Designated initializers / other C99-isms** — doomgeneric is
      C89; only measured need admits them.
    - **Jump-table switch and all optimization** — optimizer-stream
      work over the determinism gate.
    - **Object format + linker** — unchanged ladder position: after
      multi-input stops scaling, behind a SABI amendment.
    - **FP** — with SABI §7, off the critical path.

## Deliverables

1. `lang/cc/cc-m1.md` — amended in place per decision 2: grown
   tables/grammar, dated change-log entries, `## M2 — amendment
   summary` section with the sign-off banner, §12 roadmap updated
   with the named cc-m3 scope.
2. `lang/cc/cc.py` — the grown compiler (multi-input CLI of
   decision 8; single-input output byte-stable).
3. `lang/cc/tests/` — extended `run-tests.sh` (multi-file case
   form), extended `abicheck.py`, `gen-matrix.py` + checked-in
   matrix cases, ~60–70 new cases including every named suite of
   decision 10, ~5 new goldens.
4. SPEC-ISSUES.md entries: the aggregate-convention SABI-blessing
   note (decision 7), any assembler/spec gap discovered, plus
   dispositions for the libc stream's cc-tagged friction list.
5. `lang/cc/README.md` refreshed (multi-input build line, one
   paragraph on what m2 added).

## Definition of done

Every gate green, from the worktree root:

    # reference emulator present (rebuild after pulling main — stale
    # bazel-bin binaries have burned us before)
    (cd emu-c && ./build.sh)

    # the cc suite, primary leg: full m1 net + every m2 suite —
    # abicheck (incl. jalr call sites), goldens, oracle + matrix,
    # trace-q gates, double-compile/double-run determinism
    EMU=$PWD/emu-c/bazel-bin/sahara-emu lang/cc/tests/run-tests.sh

    # emu-py leg: the FULL case set, same HALT assertions
    EMU=$PWD/emu-c/bazel-bin/sahara-emu EMU_PY=1 lang/cc/tests/run-tests.sh

    # matrix regeneration is a no-op against the checked-in cases
    python3 lang/cc/tests/gen-matrix.py --check

    # root harness contract: untouched and green
    ./run_tests.sh

    # tree discipline: nothing outside lang/cc/ except SPEC-ISSUES.md
    git status --porcelain

- The amendment is complete and self-consistent BEFORE the feature
  it licenses lands (spec-first per house pattern, phase by phase is
  fine, spec-and-code in one commit is fine; code-before-spec is
  not).
- Every m1 case passes unmodified; every golden diff is a deliberate
  re-blessing with its reason in the commit message.
- The DOOM-shaped integration case passes on both emulators.
- abicheck passes on every function of every case, indirect calls
  included.
- The oracle matrix leg demonstrably CAN fail: break one conversion
  lowering locally, watch the matrix catch it, revert (a
  differential that can't fail is decoration).
- Every ambiguity met is a SPEC-ISSUES entry. Commit in small green
  steps, phase order of decision 1; `hila-voice` skill for commit
  messages. The branch merges only after the owner signs the M2
  amendment — and the varargs question below is answered.

## Risks (mitigate, don't relitigate)

1. **Unsigned sub-width canonical-form bugs** — u32's register image
   is negative-looking whenever bit 31 is set; a missed
   zero-extension at a widening site (pointer index, balance, cast)
   "works" until 0x80000000 arrives. The audited widening-site list
   (decision 4), the pinned mod lowerings, and the matrix are the
   defense; write the 0xFFFF…/0x8000… matrix rows first.
2. **Oracle false confidence** — gcc promotes u16 to int32; cc to
   u64. If the generator leaks a divergent form into the oracle
   family, the differential goes green while testing nothing. The
   coincide-by-construction restriction plus the break-it-once DoD
   check guard it.
3. **Declarator-rewrite regression** — the new parser must be
   AST-identical over m1 syntax. The full m1 suite + byte-stable
   goldens are the net; land the rewrite as its own green commit
   before function-pointer semantics.
4. **Aggregate-convention interop drift** — hand-written .s authors
   must know arguments shift when a struct is returned. It is
   spec'd interop surface (decision 7), and the interop fixture
   test covers both directions; the SPEC-ISSUES note keeps the
   SABI-blessing question alive instead of buried.
5. **Milestone bloat** — this is deliberately ~2× m1; the pressure
   valve is decision 12's named m3 list, never silent dropping. If
   the envelope blows, the pre-agreed spill order is: comma
   operator, `goto`, multi-dimensional arrays — small, separable,
   DOOM-light items — and each spill is an owner-visible roadmap
   edit, not a quiet omission. Multi-input and the aggregate work
   are NOT spillable; they are the milestone's point.
6. **Nondeterminism creep via multi-input** — per-file dicts, path
   strings, or set iteration reaching the emitter. Basename-only
   extends to all inputs; the double-compile gate already runs on
   every case including multi-file ones.
7. **Golden churn** — new lowerings must not perturb m1 rows (u8
   keeps its and-mask; 64/128 conversions keep their m1 shapes).
   Any golden that moves without a spec change-log entry is a bug.
8. **emu-py cycle blowups** — compare chains inside hot loops
   multiply; every case, matrix files included, stays under ~200k
   cycles; `// maxcycles:` is a backstop, not a budget.

## For the owner (must be answered at amendment sign-off)

**varargs sequencing.** This order cuts varargs OUT of m2 (decision
1's weighing) — but the mini-libc work order's v0.2 amendment text
commits "cc-m2 delivers varargs, then libc m2 adds printf." Accepting
this cut means printf's enabler moves to cc-m3 and the v0.2 wording
is amended to match; the alternative is trading multi-input or the
aggregate work out of m2 to make room, which this order recommends
against (both are DOOM-critical and libc-critical respectively).
Owner picks; the amendment text records the pick.

**RESOLVED at owner review (2026-08-15): varargs moves to cc-m3, still
gating DOOM's printf family; the libc v0.2 amendment names the
capability (varargs), not a milestone number, as printf's trigger.
Implementation sketch ratified for m3: callers never change (variadic
and normal calls are indistinguishable — SABI's uniform 16-byte slots
at [sp+0] for args 8+); a varargs callee gains one new prologue shape
that unconditionally spills incoming r0-r7 into frame slots contiguous
with the caller's stack-arg slots, making all arguments one memory
run; va_list is a pointer, va_arg is load-and-advance-16. abicheck
learns the third prologue shape then, not now.**

Sizing expectation: cc.py grows ~1,200–1,800 lines (to ~2,500–3,000);
spec delta ~450–600 lines; tests ~60–70 new cases plus the generator
(~250 lines) and ~150 lines of harness/abicheck growth. One branch,
one milestone. If you find yourself far outside this envelope, stop
and reread decision 12 and risk 5 before writing more code. (Sizing
envelope approved at owner review, 2026-08-15.)
