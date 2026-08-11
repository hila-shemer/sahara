# CC-M1 — the Sahara C-variant, milestone 1

**Status: FLAGGED FOR OWNER SIGN-OFF.** Written before the compiler,
exactly as SABI v0 was written before Oasis; `lang/cc/cc.py` is its
first conforming implementation and proves it implementable, but no m2
work may start before this document is signed. Divergence between this
document and the compiler is a bug in one of them, never something to
paper over.

CC-M1 is a freestanding C variant: one `.c` translation unit in, one
SABI-v0-conformant `.s` out, assembled by the untouched `asm/asm.py`
against the untouched toolchain. It targets **SABI v0**
(`os/abi/sabi-v0.md`, signed off) and is listed in that document's
consumer registry. Authority order on any discrepancy: ISA-SPEC.md,
PLATFORM-SPEC.md, TOOLING-SPEC.md and the devspec documents, then SABI
v0, then this document.

Non-normative rationale appears in indented *Note:* lines. Everything
else is normative.

---

## 1. Program contract

1. **Invocation**: `python3 lang/cc/cc.py IN.c -o OUT.s`. One
   translation unit, one output, no other flags in m1. On any error:
   one diagnostic line `FILE:LINE: error: message` on stderr, exit 1,
   no output file. There are no warnings (house loud-failure policy).
2. **Determinism**: identical input produces byte-identical output,
   every run, every host. The output header comment carries the
   input's basename only — no absolute paths, no timestamps, no
   tool-version strings.
3. **A program** is exactly this assembler command line (CLI order IS
   section order, SABI §6):

       python3 asm/asm.py -o prog.img lang/cc/rt/crt0.s lang/cc/rt/sys.s [extra .s ...] prog.s

   `crt0.s` first (it owns `.org 0x1000` and `.entry`); optional
   hand-written support files in between, **text only** (instructions
   and text-embedded constants; no section seams, no `.org`); the
   compiled unit **last** — it owns the section layout and defines the
   SABI §6 boundary labels `__etext __erodata __edata _end`.
4. **Freestanding**: no libc, no preprocessor, no linker. Multi-`.c`
   programs are out of scope in m1 (two units would interleave
   sections and break §6 concatenation layout); see the roadmap.
5. **Entry**: the unit must define `i64 main()` or `u64 main()` with
   no parameters. crt0 calls it and executes HALT with r0 = its return
   value (canonical form), so every program's observable result is the
   emulator's `HALT r0=<32 hex digits>` line. A program may instead
   exit via `sys_exit(code)` (section 10).

## 2. Lexical structure

Input is ASCII. Whitespace separates tokens. Comments: `//` to end of
line and `/* ... */` (non-nesting); both are whitespace.

| token | rule |
|-------|------|
| identifier | `[A-Za-z_][A-Za-z0-9_]*`, case-sensitive; keywords excluded |
| keyword | `u8 i64 u64 i128 u128 void struct extern if else while break continue return sizeof` |
| integer literal | decimal `[0-9]+` or hex `0x[0-9A-Fa-f]+`; value < 2^128, else error. No suffixes, no octal (a leading 0 is decimal). |
| char literal | `'c'` or `'\e'`, value 0–255; one byte exactly |
| string literal | `"..."`; operand of nothing but expressions |
| punctuation | `( ) [ ] { } ; , . -> = == != < > <= >= + - * / % & \| ^ << >> && \|\| !` |

Escapes in char and string literals, exactly the asm.md 2.2 set:
`\n \t \r \b \f \0 \\ \" \'` and `\xHH` (exactly two hex digits).
Anything else is an error.

**Reserved-name rejection.** Every symbol the compiler would emit as a
global label (function names, global variable names, `extern` names)
is checked case-insensitively against the assembler's reserved-name
set (asm.md §2.3). A collision is a compile error naming the
identifier. Since C identifiers cannot contain `.`, only the dot-free
reserved names can collide: `r0`–`r31`, `sp`, `ra`, `k0`, `zero`,
`p0`–`p7`, the sreg names, the bare mnemonics, the pseudo-mnemonics
(`li la mov nop not neg ret` — `la.abs` is unreachable), and
`shl sxt zxt f32 f64 i32 i64 i128`. This is a **documented deviation**
from C: `i64 add(...)` is a legal C program and a CC-M1 compile error.

## 3. Types

Scalar types, described by the pair **(size, signedness)** — the type
descriptor the whole compiler runs on, so that m2's `i8 i16 u16 i32
u32` are new table rows, not a redesign:

| type | size (bits) | signedness | in registers |
|------|------------:|------------|--------------|
| `u8`   | 8   | unsigned | promoted to `u64` in every expression (section 5.1) |
| `i64`  | 64  | signed   | canonical (sign-extended from bit 63) |
| `u64`  | 64  | unsigned | canonical (sign-extended from bit 63 — unsigned too, ISA §3.4) |
| `i128` | 128 | signed   | native |
| `u128` | 128 | unsigned | native |
| `T*`   | 128 | unsigned | native; typed, multi-level |

Derived types: pointers to any type, fixed-size one-dimensional arrays
`T name[N]` (N a constant expression > 0; element scalar, pointer, or
struct), and named structs. `void` is a function-return type and the
target of no pointer (`void*` is m2).

**Canonical form (the width-discipline firewall).** Every value in a
register is kept in the ISA §3.4 canonical form of its type's width:
sign-extended from bit (width−1) to 128 bits, for signed AND unsigned
types alike. This is maintained *by construction*: every arithmetic,
logical, shift, and compare instruction is emitted at the width of its
operand type (`.64` suffix for 64-bit types, bare/128 for 128-bit
types), with the unsigned variants (`cmpltu`, `cmpleu`, `udiv`,
`urem`, `shr`) selected by signedness. No emitted instruction relies
on a value being "small enough" for a wider width to coincide.

**Memory representation**: little-endian, at the type's natural size —
`u8` 1 byte, `i64`/`u64` 8 bytes, `i128`/`u128`/pointers 16 bytes.
Loads and stores per type:

| type | load | store |
|------|------|-------|
| `u8` | `ldz.8` (zero-extend = canonical, bit 7 < 63) | `st.8` |
| `i64` | `lds.64` | `st.64` |
| `u64` | `lds.64` (sign-extension from bit 63 IS the canonical form) | `st.64` |
| `i128`, `u128`, `T*` | `ld128` | `st128` |

**Struct layout, frozen now so future ports never re-layout.**
C-style: fields in declaration order, each at its natural alignment
(`u8` 1, `i64`/`u64` 8, `i128`/`u128`/pointer 16, array = element
alignment, struct = max member alignment), total size rounded up to
the struct's alignment (= max member alignment, minimum 1). No
packing, no reordering. `sizeof` reports exactly this size.

## 4. Conversions

All conversions are value → value at compile-known types. The
lowerings below are pinned; a conforming compiler emits exactly these
shapes (modulo register names).

| from → to | code emitted |
|-----------|--------------|
| 64-bit → 64-bit (any signedness mix) | none (same canonical image) |
| 128-bit or pointer → 64-bit | `or.64 rd, rs, 0` (truncate + re-canonicalize) |
| anything → `u8` | `and.64 rd, rs, 0xff` (result is the promoted `u64` value) |
| `i64` → 128-bit or pointer | none (the canonical image already is the sign-extension) |
| `u64` → 128-bit or pointer | `shl rd, rs, 64` then `shr rd, rd, 64` |
| 128-bit ↔ 128-bit / pointer ↔ pointer | none (bit-identical) |

*Note: the `u64` → 128 zero-extension cannot use the `zxt` mod (its
amount field caps at 63, ISA §3.3); the `shl 64; shr 64` pair at width
128 is the pinned lowering — chosen over an AND mask, which would cost
a 3-instruction `li` for the constant.*

Pointer conversions are **explicit-cast only**: pointer ↔ `u64`,
`u128`, `i64`, `i128`, and pointer ↔ pointer of any type. `u64` →
pointer zero-extends (addresses are unsigned); `i64` → pointer takes
the canonical 128-bit image as the address (defined, if rarely
useful). Integer ↔ pointer without a cast is a compile error — a
deliberate tightening of C.

Implicit conversions (assignment, initialization, argument passing,
`return`) are permitted among integer scalar types only, with the
table above. Pointer types must match exactly (no implicit
qualification games exist — there are no qualifiers).

## 5. Expressions

### 5.1 Promotion and balancing

- A `u8` rvalue promotes to `u64` immediately, in every context.
  **Documented deviation from C**, which promotes to signed `int`:
  `(u8)1 - (u8)2` is a huge positive `u64` here, `-1` in C. (The
  binding subset decision; it keeps exactly one promotion row.)
- Binary arithmetic, bitwise, and comparison operands are balanced to
  the **common type**: the larger-size operand's type wins; at equal
  size, unsigned wins. (This coincides with C's usual arithmetic
  conversions on this type set: `u64 op i128` → `i128`, since `i128`
  represents every `u64` value.)
- Shift results have the promoted **left** operand's type; the count
  is converted to `u64`.
- Unary `-` and `!` operate on the promoted operand.

### 5.2 Operators, precedence highest to lowest

| level | operators | associativity |
|------:|-----------|---------------|
| 1 | calls `f(...)`, indexing `a[i]`, `.`, `->` | left |
| 2 | unary `- ! * &`, cast `(type)e`, `sizeof(type)` | right |
| 3 | `* / %` | left |
| 4 | `+ -` | left |
| 5 | `<< >>` | left |
| 6 | `< > <= >=` | left |
| 7 | `== !=` | left |
| 8 | `&` | left |
| 9 | `^` | left |
| 10 | `\|` | left |
| 11 | `&&` | left |
| 12 | `\|\|` | left |
| 13 | `=` | right |

This is C's precedence exactly (with C's relational-below-shift,
bitwise-below-equality ordering), so a host C compiler is a valid
differential oracle over the shared subset.

### 5.3 Semantics

**Every operation's behavior is defined** — CC-M1 has no undefined
behavior anywhere. Where C says UB, CC-M1 adopts the ISA's semantics:

- **Overflow**: two's-complement wrap at the operation width, signed
  and unsigned alike.
- **Shifts**: count taken modulo the operation width (ISA §3.4/5.1).
  `>>` is arithmetic (`sar`) for signed types, logical (`shr`) for
  unsigned.
- **Division by zero**: quotient = all-ones at width (i.e. −1 signed,
  MAX unsigned), remainder = dividend. `MIN / −1`: quotient = MIN,
  remainder = 0 (ISA §5.1). No traps.
- **Evaluation order**: strict left-to-right, depth-first, everywhere
  — binary operands, call arguments, and assignment (lvalue address
  before the right-hand side). Side effects happen in exactly that
  order.

Operator notes:

- `/ %` select `sdiv/srem` vs `udiv/urem`, `< <= > >=` select
  `cmplt/cmple` vs `cmpltu/cmpleu`, by the common type's signedness,
  at its width. Comparisons and `! && ||` yield `i64` 0 or 1.
- `&& ||` short-circuit and are branch-lowered (no if-conversion in
  m1): the right operand's side effects do not happen when the left
  operand decides. Operands may be any scalar (integer or pointer);
  the test is ≠ 0 at the operand's width.
- `!e` is `e == 0` at `e`'s width; `e` any scalar.
- Unary `&` yields `T*` from any lvalue; unary `*` requires a pointer.
  `a[i]` is `*(a + i)`; `s.f` requires a struct lvalue, `p->f` a
  struct pointer.
- **Pointer arithmetic**: `p + n`, `n + p`, `p - n` scale `n` by
  `sizeof(*p)` at width 128; `p - q` (same pointee type) yields the
  element difference as `i128` (byte difference `sdiv` element size).
  Pointers compare with pointers of the same type (unsigned, width
  128), or with the literal `0`.
- **Assignment is an expression** (right-associative); its value is
  the stored value, of the lvalue's type (promoted if `u8`). Arrays
  and structs are not assignable.
- An array rvalue decays to a pointer to its first element.

### 5.4 Literals

- Integer literal typing rule (pinned): the first of `i64`, `u64`,
  `i128`, `u128` whose range holds the value.
- Char literals are `i64` (value 0–255).
- String literals have type `u8*` and evaluate to the address of a
  NUL-terminated read-only object in rodata. Identical byte sequences
  within one unit share one object (deduplication is by exact bytes,
  first-occurrence order). Modifying one is self-sabotage, not an
  error the platform detects (MMU off).
- `sizeof(type-name)` is a `u64` constant; type-name is any scalar,
  pointer, or `struct` type.

### 5.5 Constant folding

The only optimization in m1: an operation whose operands are integer
literals is folded at compile time, at the operation's type and width,
under exactly the section 5.3 semantics — except `/` and `%`, which
are never folded (they are emitted and computed by the machine, so the
ISA's division corners have exactly one implementation). Nothing else
is optimized: no CSE, no register allocation, no reordering — every
source-level memory access is a real access (this is where `volatile`
would be, and why it is absent).

## 6. Statements

    block:      { statement* }
    statement:  block | declaration | expression ;
              | if (expr) statement [else statement]
              | while (expr) statement
              | break ;  | continue ;
              | return [expr] ;  |  ;

- Declarations may appear anywhere in a block (C99 placement — a
  documented convenience deviation from C89). Scope is from the
  declaration to the end of the block; shadowing outer names is legal.
- `if`/`while` conditions are any scalar, tested ≠ 0 at their width.
- `break`/`continue` bind to the nearest enclosing `while`; outside
  one they are errors.
- `return e` converts `e` to the function's return type; plain
  `return` is only legal in `void` functions. Control reaching the end
  of a non-`void` function returns 0 (defined; documented deviation
  from C's UB).
- Local declarations: `type name [N]? [= expr]? ;`. Initializers are
  a plain assignment (arrays and structs cannot be initialized in m1;
  initializer lists are m2).
- Reading an uninitialized local yields the prior contents of its
  frame slot: deterministic for any whole-program run (the machine
  is), but no particular value is promised and programs must not rely
  on one. Uninitialized globals are zero (section 7).

## 7. Declarations and program structure

    program:    (struct-def | function-def | function-proto | global-decl)*
    struct-def: struct NAME { (type name ([N])? ;)* } ;
    function:   type NAME ( params? ) (block | ;)
    params:     void | type name (, type name)*
    global:     [extern] type NAME ([N])? [= ginit] ;
    ginit:      const-expr | { const-expr (, const-expr)* }

- **Structs** are declared at file scope, before first use; members
  may be scalars, pointers, arrays, and previously declared structs
  (no forward references, so no recursion except through pointers to
  already-declared structs — `struct S *` inside `S` itself is m2).
- **Functions**: a definition or a prototype (`;` body). `extern` on a
  prototype is accepted and means nothing extra (functions have no
  storage). All declarations of one name must agree exactly in return
  and parameter types. Calls to names never declared in the unit are
  errors (no implicit int). A function defined later in the unit may
  be called earlier without a prototype (the compiler collects all
  signatures first). Parameters are scalars and pointers only — no
  arrays (use pointers), no structs by value (m2).
- **Prototypes are the interop surface**: an `extern` prototype is how
  C calls hand-written `.s`, and a C function's verbatim label is how
  `.s` calls C. Both sides speak SABI v0 (section 8).
- **Globals**: file-scope variables of any m1 type.
  - With an initializer (scalars: one constant expression; arrays of
    scalars: a brace list of ≤ N constant expressions, remainder
    zero): emitted to **data**, value stored mod 2^width.
  - Without: emitted to **bss** (`.space`), zero at boot by the loader
    contract (TOOLING-SPEC §1 zero-fill).
  - `extern type name;` declares without emitting — definition comes
    from another `.s` on the command line; asm.py's E030/E031 are the
    link errors (concatenation IS linkage).
  - String-literal and address initializers are out (m1 has no
    relocation story for data); pointer globals are bss-only.
  - Constant expressions: integer/char literals, `sizeof`, and the
    foldable operators of 5.5 over them.
- Duplicate definitions within the unit are compile errors; duplicates
  across units on the assembler command line are asm.py E031.

## 8. SABI v0 mapping

The compiler emits SABI-v0-conformant code **by construction**, and a
mechanical checker (`lang/cc/tests/abicheck.py`) verifies every
emitted function. To make the check mechanical, every function is
preceded by one structured marker:

    # cc: func NAME frame=N calls=0|1

### 8.1 Frame shape — one shape, no alternatives

Non-leaf or stack-using function (`frame=N`, N > 0):

    NAME:
            add     sp, sp, -N          # N a multiple of 16, N <= 2^20
            st128   [sp + N-16], ra     # iff calls=1
            ... entry spills, body ...
    NAME.Lret:
            ld128   ra, [sp + N-16]     # iff calls=1
            add     sp, sp, N
            ret

- Every `return` in the body branches to `NAME.Lret`; the `ret` after
  the epilogue is the only `ret` in the function.
- N ≤ 2^20 bytes; a frame beyond that is a **loud compile error**
  (documented m1 limit — keeps `add sp, sp, ±N` comfortably inside
  imm22 and the prologue shape unique for the checker).
- A function with no parameters, no locals, no calls, and expression
  depth ≤ 8 is frameless (`frame=0`, SABI §2.5): no `sp` writes at
  all, body then `NAME.Lret:` then `ret`.
- `calls=1` implies N ≥ 16 (the ra slot).

Frame layout, low to high (all region sizes multiples of 16, so every
slot offset is a multiple of 16 and every `st128`/`ld128` is 16-byte
aligned by construction — SABI §2.3, never by luck):

    [sp + 0            .. OUT)    outgoing >8-argument slots, 16·max(0, maxargs−8)
    [sp + OUT          .. +L)     locals and parameter homes
    [sp + OUT+L        .. +S)     expression-temp spill region
    [sp + N−16         .. N)      ra (iff calls=1)

### 8.2 Register plan

- **Arguments arrive in r0–r7** and are stored to their frame homes at
  entry (typed stores, section 3); arguments 8+ are read from
  [sp + N + 16·(i−8)] and copied to their homes. Locals and parameters
  are memory-resident for their whole lifetime — the no-optimizer
  stance, not a bug.
- **Expressions evaluate on a temp stack mapped onto r8–r15**: value
  stack slot k lives in register r(8 + k mod 8); pushing slot k ≥ 8
  first spills slot k−8 to its spill-region home
  [sp + SPILLBASE + 16·(k−8)], popping back past k reloads it. The top
  8 slots are always register-resident, so every operation's operands
  are in registers. Compilation is TOTAL — there is no "expression too
  complex" failure, only frame growth.
- **Calls**: before `jal`, every live temp-stack slot is spilled to
  its home; argument values are then loaded to r0–r7 (`ld128`) and
  stack-slot arguments stored to [sp + 0 + 16·(i−8)] (`st128` via r8
  as scratch); after return, r0 is captured into the result slot and
  the surviving register-resident slots are reloaded. Return value in
  r0 only (every m1 type fits one register; the r0:r1 pair form stays
  unused).
- **The compiler never touches r16–r27** (no callee-saved code to get
  wrong; r27's kernel-gp role costs user code nothing and not
  allocating it is free insurance), **never r30/k0**. `sp` is written
  by prologue/epilogue only.
- **Predicates**: the compiler writes only `p1`, never live across a
  call or between statements (caller-saved per SABI §1).

### 8.3 Sections and symbols

- Output order: text, rodata, data, bss; each seam is
  `.align 16` + boundary label: `__etext`, `__erodata`, `__edata`,
  `_end` (heap base, SABI §4.6). bss content is `.space`/`.align`
  only. The unit must be last on the assembler command line.
- C identifiers pass through **verbatim** as labels (readable `.sym`,
  plain interop), after the section-2 reserved-name check. Internal
  labels are `NAME.L<n>` with n per-function, source-order derived
  (a leading dot is NOT a legal label start in this assembler).
  String-literal labels are `cc.str.<k>` in first-use order — `.` is
  legal in asm identifiers and impossible in C ones, so they cannot
  collide with user symbols.

### 8.4 Width discipline in emitted code

For 64-bit types every ALU/compare instruction carries `.64`; for
128-bit types and pointers the bare (128) form; `u8` participates as
`u64` (5.1). Literal operands are materialized with `li` into a temp
slot (the assembler picks the minimal `LDI`/`SHORI` chain); constants
are emitted as **signed** values of their canonical 128-bit image, so
e.g. `u64` 0xFFFFFFFFFFFFFFFF emits `li rX, -1` (one instruction).

## 9. Deviations from C — the frozen list

Everything in this section is deliberate and frozen for m1:

1. Reserved-name rejection (section 2) — assembler namespace is shared.
2. `u8` promotes to `u64`, not `int` (5.1).
3. Default integer width is 64/128-bit; there is no `int` (name your
   width).
4. Two's-complement wrap, shift-mod-width, defined division corners,
   strict left-to-right evaluation (5.3) — C's UB becomes the ISA's
   defined semantics.
5. Integer ↔ pointer conversion requires an explicit cast (section 4).
6. Declarations anywhere in a block; end-of-function falls out as
   `return 0` (section 6).
7. No preprocessor at all: no `#include`, no macros. The language is
   .c-file-in, .s-file-out.
8. `main` takes no arguments (freestanding; there is no environment).

Out of m1, each with its reason (see also the roadmap):

- **Floating point** — SABI defers the FP ABI (§7); the flagship port
  targets are deliberately fixed-point. Not on the critical path.
- **varargs** — SABI's 16-byte stack slots leave an obvious future
  path (spill r0–r7 to slots and walk memory); noted, not built.
- **struct by-value / assignment / return** — needs a copy routine
  and there is no libc to hold one.
- **unions, enums, `switch`/`for`/`do`/`goto`** — expressible with
  what is in; table rows and productions for m2, not architecture.
- **`++ --`, compound assignment, ternary, `~`, unary `+`** — sugar;
  m2 productions.
- **function pointers** — need typed indirect calls (`jalr`); the
  calling convention already supports them, the front end defers them.
- **`typedef`, `static`, `const`, `volatile`** — no optimizer means
  every access is a real access, which is all m1 code could want from
  `volatile`; the rest is m2 bookkeeping.
- **bitfields, multi-dimensional arrays** — layout complexity with no
  m1 consumer.
- **`void*`** — needs implicit-conversion rules worth doing properly
  once, in m2.

## 10. Runtime contract (`lang/cc/rt/`)

Two hand-written, SABI-conformant, marker-commented files.

**`crt0.s`** — owns `.org 0x1000` and `.entry _start`:

1. Validates the device table per devspec/boot.md §3: magic
   `"SAHARAPT"`, version 1, `ram_region_count` ≥ 1 — each failure
   halts loud with a distinct code (below). u128 table fields are read
   as paired `ldz.64` (they are only 8-aligned; `LD128` would trap).
2. Sets `sp` = RAM region 0 `base + len` from the table — never a
   hardcoded constant (SABI §4.5). A region above 2^64 halts loud.
3. Installs `vbase` → `cc_trap` and `dfbase` → `cc_df` (both in
   sys.s).
4. `jal main`, then HALT — r0 at the halt is main's return value.

**`sys.s`** — the syscall surface and the trap handler. Numbers and
semantics deliberately match `os/oasis/doc/syscalls.md` (0 = write,
2 = exit), so a compiled program is already Oasis-shaped the day an OS
can host one; m1 compiled code does NOT run under Oasis (no loader, no
user mode — both SABI §7 deferrals). The shim exercises the identical
SABI §3 mechanism with the identical numbers; that is the honest
claim.

C-callable wrappers (ordinary SABI functions, frameless leaves):

- `sys_write(fd, buf, len)` — number 0 in r7, args already in r0–r2,
  r6 = 0, `syscall`, result in r0. Kernel side: fd ≠ 0 → −EINVAL;
  len = 0 → 0; else appends the bytes to the capture buffer and
  returns len.
- `sys_exit(code)` — number 2; does not return (the handler halts with
  r0 = code).

The `cc_trap` handler (SABI §5: a SYSCALL handler needs no trap-frame
block; this one touches only r8–r15, p1, k0 and sregs, and never
lowers TL):

- cause 10 (SYSCALL): dispatch on r7. 0 = write into the capture
  buffer `sys_cap` (4096 bytes) at `sys_cap_len`, bumping the length;
  overflow halts loud. 2 = exit: HALT with r0 = code. 1 (`read` in the
  Oasis table) is known but unhosted here: −ENOSYS. Anything else:
  −ENOSYS. Resume is `epc0 += 8` then `iret` (ISA §7.1).
- any other cause: HALT with r0 = 0xCCBADC00 + cause (loud, distinct).
- double fault (`cc_df`): HALT r0 = 0xCCBADDF0.

Halt codes (cc's own value space — never the conformance suite's
0x700/r24 idiom, never Oasis's 0x600D): 0xCCBAD001 bad table magic,
0xCCBAD002 bad version, 0xCCBAD003 no RAM region, 0xCCBAD004 u128
field above 2^64, 0xCCBADCAF capture-buffer overflow, 0xCCBADC00+cause
unexpected trap, 0xCCBADDF0 double fault.

*Note: the capture buffer lives inside sys.s, positionally in the text
region — the compiled unit owns all four sections and their seams, so
runtime state cannot live in the real bss. With the MMU off this is
byte-equivalent; recorded as a SPEC-ISSUES observation on
boundary-label ownership.*

## 11. Limits (m1, all loud errors)

- Frame size ≤ 2^20 bytes.
- Integer literals < 2^128.
- String literals ≤ 4096 bytes (the runtime capture buffer bounds the
  useful size anyway; not a language limit, a diagnostic courtesy —
  the emitted `.asciiz` would be legal).
- One translation unit per invocation.

## 12. Roadmap — the ladder this milestone must not saw off

m1 is this document. Nothing in m1's design — the (size, signedness)
type model, canonical-form handling, frozen struct layout, or the
calling-convention mapping — may make the following a redesign; they
must land as table entries and new productions:

- **m2 — the full C89 integer model**: `i8 u16 i16 u32 i32` as
  first-class types (new rows in the width tables: load/store insns,
  `.32` ALU suffix for 32-bit types, promotion rules), unions, enums,
  `switch`/`for`/`do`-`while`, function pointers (typed `jalr` calls),
  struct assignment and by-value passing (compiler-emitted copy
  loops), `static`/`const`, initializer lists, `typedef`, `void*`,
  the missing operator sugar (`~ ++ -- += ?:` …), string-literal and
  address initializers for globals.
- **Multi-unit compilation**: a future cc.py accepting several `.c`
  files in one invocation, emitting one interleaved `.s` (the honest
  path to multi-unit under §6 concatenation — there is no linker and
  none is wanted).
- **varargs**: over SABI's uniform 16-byte stack slots.
- **FP**: stays deferred with SABI §7. The flagship port targets
  (DOOM/LVGL-class: freestanding C89/C99, fixed-point, framebuffer +
  input) are deliberately fixed-point, so FP is NOT on the critical
  path of anything.
- **The mini-libc + Linux-ish shim** (fb + input + malloc) those ports
  need is a SEPARATE future stream that consumes cc's output; m1's
  only nod to it is this section and the non-blocking type model.
- Optimization of any kind — with the determinism gate (compile-twice
  byte-compare) already in place to keep it honest.

---

**Sign-off status: FLAGGED FOR OWNER SIGN-OFF** (not yet signed).
Consumers: `lang/cc/cc.py` (reference implementation, this branch).
Amendments before sign-off may be made freely by the cc stream;
after sign-off, SABI-style rules apply (dated change log, consumer
updates in the same change).
