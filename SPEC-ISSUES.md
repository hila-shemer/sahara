# SPEC-ISSUES — toolchain agent

Ambiguities and apparent gaps found while building `asm/`, `trace-q/`,
and `tests/`, with the reading chosen. Per the ambiguity protocol these
are decisions, not questions; each names the file:section it interprets.
Both emulator implementations must match the readings marked
**(emulators must match)** or the cross-diff will flag them.

1. **TOOLING-SPEC 3.2, EXEC `pred_wb`** — the field's meaning is not
   stated. A single-bit reading cannot represent PWR (writes p1-p7 at
   once), so `pred_wb` is read as **the full 8-bit predicate file after
   the write** (bit i = P[i]), valid when flags bit 2 is set.
   trace-q's `reg pN` reconstruction depends on it. **(emulators must
   match)**

2. **TOOLING-SPEC 3.2, META** — "key/value text" has no defined syntax.
   Chosen: UTF-8 text, one `key=value` per newline-terminated line; keys
   `image`, `level` at minimum. Two conforming emulators may still
   legitimately differ (image path, implementation tag), so
   `trace-q diverge` grew `--ignore-meta`, which difftest.sh uses. The
   determinism double-run (same emulator twice) compares META too.

3. **emu-common-prompt CLI contract, `HALT r0=<32 hex digits>`** — digit
   case is unspecified. The harness requires **lowercase**. Recommend
   freezing lowercase in the contract. **(emulators must match)**

4. **TOOLING-SPEC 4.4, `sub rd, imm, rs`** — listed under "the obvious
   one-instruction expansions", but no reverse-subtract exists and SUB's
   immediate form computes `src1 - imm`, not `imm - src1`. Only
   `imm = 0` (i.e. `neg`) is expressible in one instruction. The
   assembler accepts `sub rd, 0, rs` and rejects any other immediate
   with an error directing to `li` + `sub`.

5. **TOOLING-SPEC 4.4, `la` fallback** — "LAP + immediate `add`
   (position-independent within 2^22 * range)" does not say how the
   delta splits. Chosen: split across the two signed 22-bit fields
   (first saturates, second takes the remainder), reaching about +/-4 MB;
   beyond that is a loud error directing to `la.abs`. A forward-referenced
   `la` always reserves the two-instruction form (the second may be
   `add rd, rd, 0`) because sizes must be fixed in pass 1; same policy
   for forward-referenced `li` (full 6-word chain).

6. **TOOLING-SPEC 4.5, layout before `.org` / missing `.entry`** — no
   default load address or entry is specified. Chosen: content before the
   first `.org` lands at PA 0x1000 (the reset PC), and a missing `.entry`
   means entry = 0x1000.

7. **TOOLING-SPEC 4.3 / ISA-SPEC 10.4, FCVT assembly syntax** — only
   `fcvtfi.32 rd, rs1, f64` is shown; the spelling of integer source
   formats is not. Chosen: destination suffix `.32/.64/.128` (integer)
   or `.f32/.f64` (FP); trailing source-format operand `f32/f64` (FP) or
   `i32/i64/i128` (integer). `fcvtff` with equal source and destination
   formats is rejected (ISA-SPEC 10.4 "illegal format combinations trap"
   is read to include it). **(emulators must match** on the trap for the
   equal-format encoding**)**

8. **TOOLING-SPEC 2, symbol kinds** — how the assembler classifies T vs
   D is unspecified. Chosen: a label's kind is decided by the first
   content emitted after it (instruction -> T, data directive -> D,
   nothing -> D). `.equ` names are emitted as kind A with their value in
   the address column.

9. **TOOLING-SPEC 3.3, `find`** — the table says "first matching cycle"
   while the reverse-continue note says "taking the last match". trace-q
   prints the first match by default and adds `--last` so
   reverse-continue is a single invocation.

10. **TOOLING-SPEC 4.3, `lap` operand** — the primitive's assembly
    operand is unspecified. Chosen: a target *address* expression
    (imm = target - pc), consistent with `b`/`jal`; raw-offset use is
    what `li`+`add` or `.equ` arithmetic is for.

11. **CONFORMANCE.md, "well-known address" for the failing test ID** —
    not pinned to a value anywhere. Chosen (tests/README.md): failing
    test ID stored as u64 at **PA 0x700**, success magic **r0 = 0x600D**
    at HALT, failure HALTs with r0 = the failing test ID. Both below the
    device table so no image segment can collide.

12. **ISA-SPEC 7.2 / emu-common CLI contract, halts that are not the
    HALT instruction** — the contract defines stdout for "On HALT", but
    the machine also halts on triple fault (ISA-SPEC 7.2 step 1) and on
    WFI deadlock (7.6). Whether those print the `HALT r0=...` line and
    exit 0 is unspecified. Chosen reading: **yes — any architectural
    halt prints the same line (current r0) and exits 0**; C1's
    triple-fault test will set r0 to a marker and rely on it.
    **(emulators must match)**

13. **ISA-SPEC 10.3, UF (underflow) tininess detection** — IEEE 754
    allows detecting tininess before or after rounding and the spec does
    not choose; implementations on host FP (x86: after rounding) and
    softfloat defaults can disagree on the UF flag for results near the
    subnormal boundary. Recommend freezing **after rounding**. C4
    vectors will avoid the distinguishing edge until this is frozen.
    **(emulators must match)**

14. **ISA-SPEC 3.3 mod field with I=1** — 3.1 says `mod` is ignored when
    I=1 for ALU/compare. Assemblers must emit zero in unused fields, so
    the only way to exercise "ignored" is a hand-built word; c5 includes
    one via `.quad`. Note the tension with ISA-SPEC 3 "future revisions
    may assign meaning" to unused fields: a future revision could make
    that word illegal. The test documents this.

15. **ISA-SPEC 10.3 fcsr flag bit order vs encoding.py** — the spec
    sentence "Bits 4:0 accumulate exception flags NV, DZ, OF, UF, NX"
    reads naturally as NV = bit 4 (list written 4 down to 0), but
    encoding.py `FCSR_FLAG_BITS` assigns **NV = bit 0 .. NX = bit 4**.
    Encoding truth is encoding.py, so the toolchain and the C4 vectors
    use NV=0/DZ=1/OF=2/UF=3/NX=4. Recommend rewording the spec sentence
    to name the bits explicitly. **(emulators must match — via
    encoding.py, which they are required to consume)**

16. **ISA-SPEC 4 / 2.3, MFSR-of-cycle read timing** — `cycle`
    increments by 1 per retired instruction, but whether an MFSR that
    reads `cycle` sees the value before or after its own increment is
    unspecified. Chosen: **before** (the value counts instructions
    retired prior to the reading instruction, plus deliveries). c1's
    squash cycle-delta checks (two MFSRs N instructions apart differ by
    N+1) depend on it. **(emulators must match)**

17. **TOOLING-SPEC 3.2, records for non-retiring instructions** — EXEC
    is "emitted for every retired instruction", and a faulting
    instruction does not retire (ISA-SPEC 4: no architectural effect).
    Chosen: a faulting instruction emits **no EXEC record**; the TRAP
    record (whose epc points at it) is its only footprint. Consequence
    for the triple fault: delivery at TL=2 delivers nothing, so **no
    third TRAP record is written** — checks/c1_triplefault.sh asserts
    exactly two. **(emulators must match)**

18. **ISA-SPEC 10.4, FCVT `mod` bits 7:2 "must be zero"** — no
    consequence is stated for a violation. Chosen: traps ILLEGAL, like
    the other reserved-encoding rules in the same section; defs.s
    provides `RAW_FCVT_BADMOD` and C4 asserts it. **(emulators must
    match)**

19. **ISA-SPEC 10.3, "the next FP operation that rounds then traps"**
    (reserved rounding mode) — which operations "round" is not
    enumerated. Chosen: FADD/FSUB/FMUL/FDIV/FSQRT/FMADD and all FCVT
    forms round; FMIN/FMAX/FCMP* do not and must NOT trap on a
    reserved mode. C4 asserts the trap via FADD only; the FMIN/FCMP
    non-trap side is unasserted (bounded coverage). **(emulators must
    match)**

20. **ISA-SPEC 7.6, cycle value after a WFI stall** — "virtual time
    advances directly to the next cycle at which one becomes pending"
    does not pin whether WFI's own retire-increment lands before or
    after the jump, so the exact post-WFI cycle differs by ±1 between
    natural readings. c1 asserts only `cycle >= timecmp` after the
    stall. The value is observable in traces, so the cross-diff will
    surface any disagreement loudly. Recommend freezing: jump to
    exactly the pending cycle, then +1 for WFI's retire. **(emulators
    must match)**
