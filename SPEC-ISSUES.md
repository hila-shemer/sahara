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
   Originally chosen: `key=value` lines with `image`, `level` at
   minimum, plus a `diverge --ignore-meta` flag. *Superseded by
   devspec/trace.md 2.3.7 (entry 27): the closed 7-key v1 catalog is
   now enforced by the tracefile reader, and `diverge` always excludes
   exactly the run-variant keys `mode`/`image` (trace.md 6.5.6), so
   `--ignore-meta` was removed. The determinism double-run (same
   emulator twice) still compares whole files with `cmp`.*

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
   while the reverse-continue note says "taking the last match".
   Originally trace-q added a `--last` flag. *Superseded by
   devspec/trace.md 6.1/6.5.5 (entry 27), which pins the closed CLI
   without it: `find` prints the first match; reverse-continue is the
   caller narrowing `--to`. `--last` was removed.*

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
    record (whose epc points at it) is its only footprint —
    *confirmed by devspec/trace.md 3.3/T-06.* The original consequence
    drawn here for the triple fault (no third record) is **overturned**
    by trace.md 2.3.4: the triple fault emits a final DIAGNOSTIC TRAP
    record carrying the cause/epc/baddr the third trap would have
    delivered, `tl_after = 3`, corresponding to no sreg writes, and
    the trace ends. checks/c1_triplefault.sh now asserts exactly three
    TRAP records (tl 1, 2, 3). **(emulators must match)**

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
    *FROZEN 2026-08-09 as recommended: T = the first cycle >= the WFI's
    own cycle at which an interrupt can become pending; execution
    resumes at T + 1 (the retire increment lands after the jump). The
    predicted disagreement did surface: the first full emu-c/emu-py
    difftest diverged at c1_traps record 435 (post-WFI `mfsr cycle`
    read 595 vs 596). emu-py already implemented this reading; emu-c
    was aligned (cpu.c wfi_wait, which also mis-woke at c0+1 when
    timecmp landed exactly on the retire cycle). emu-c SPEC-ISSUES 30
    is superseded.*

21. **emu-common-prompt, INVTP check mode: what "served stale" means**
    — the phantom translation cache "assert[s] if a translation would
    have been served stale". Chosen: stale = the cached (asid, VA)
    entry's *result* (frame and permissions) differs from a fresh walk
    at use time; serving a cached entry whose result still matches is
    not an assertion, even if tables were touched or ptbase changed in
    between. c2's ptbase/asid switch relies on this: both roots map
    the code page identically, so the two fetches inside the switch
    window translate to the same frame under either table.
    **(emulators must match, or c2_mmu CHECKFAILs on one of them)**

22. **CONFORMANCE C2, the assertion-firing side of the INVTP check** —
    "change ptbase alone without INVTP (illegal — check-mode assertion
    fires)" describes a run that *ends* in CHECKFAIL exit 3 with an
    implementation-worded reason line; the current harness has no
    expected-CHECKFAIL test class, and difftest compares stdout
    byte-for-byte (reason lines will legitimately differ). Needs a
    manifest extension (e.g. `expect=checkfail`, comparing exit code +
    first word only) — planned, not yet built. Until then the
    assertion side of C2's INVTP contract is unexercised (bounded
    coverage, noted in gen_c2.py). *Resolved by entry 23's harness
    class; the assertion-side images are c2_noinvtp_remap.s and
    c2_noinvtp_ptbase.s.*

23. **Expected-CHECKFAIL harness class (`expect=checkfail`)** — the
    CLI contract fixes only `CHECKFAIL <one-line reason>` + exit 3;
    the reason wording is implementation-defined, and where exactly
    the trace ends relative to the asserting access is unspecified.
    Chosen: a MANIFEST line may carry `expect=checkfail`; run-tests
    then requires exit 3 and a stdout line whose FIRST WORD is
    CHECKFAIL (reason text ignored), still runs twice and requires
    byte-identical traces (one implementation's assertion point and
    reason must be deterministic); difftest compares only the outcome
    class for such tests and does not diff their traces or reasons
    (neither is comparison-stable across implementations).
    **(emulators must match the class: both must assert on the
    c2_noinvtp_* images, at the load marked in each file)**

24. **TOOLING-SPEC 3.2, record order within one instruction** — the
    format fixes per-record fields but not the order of one
    instruction's records relative to each other. *Resolved by
    devspec/trace.md 3.3/T-08 (entry 27), stricter than the original
    choice here: access records precede their EXEC and share its
    cycle; the EXEC is emitted LAST (the commit marker); an atomic's
    MEMR is IMMEDIATELY followed by its MEMW (no record of any kind
    between them); a failed CAS emits MEMR only; EVENTs applied at a
    boundary precede the TRAP/EXEC of the same cycle in application
    order. checks/c3_irq_dev.py asserts the atomic adjacency.*
    **(emulators must match)**

25. **PLATFORM-SPEC 1 vs ISA-SPEC 5.3, misaligned device access** —
    a misaligned non-64-bit access to a device register violates both
    the natural-alignment rule (UNALIGNED) and the register-size rule
    (DEVERR), and neither frozen document ranks them. *Resolved by
    devspec (entry 27), matching the recommendation here: UNALIGNED
    ranks first — display.md 1 rule 4 ("a misaligned access traps
    UNALIGNED before any device semantics apply"), nic.md 5's check
    precedence (alignment -> E7 -> E1 -> ...), NIC-C-10. The C7
    device tranche pins it with a misaligned device-window access
    expecting UNALIGNED.* **(emulators must match)**

26. **TOOLING-SPEC 3.2 replay mode, input file format** — "re-run
    from an image plus EVENT records alone" never says what the
    `--replay events.trc` file looks like. *Resolved by
    devspec/trace.md 5 (entry 27): the replay input is a recorded
    .trc — the replayer consumes only its EVENT records, validates
    META (`image_sha256`/`encoding`/`trace`, refusing on mismatch,
    T-20), and must reproduce every post-META record byte-identically
    at the same level (T-18). run-tests now feeds run a's own trace
    to `--replay` and compares with `diverge` (whose META comparison
    excludes the run-variant `mode`/`image` keys); the interim
    `trace-q events` extraction subcommand was removed. Still
    REPLAY=1-gated until both emulators implement --replay; a
    zero-EVENT trace remains a meaningful replay (a determinism
    re-run through the replay path).* **(emulators must match)**

27. **devspec/ landed on main (INDEX.md present) — toolchain
    reconciliation.** Per emu-common-prompt, devspec documents now
    govern their surfaces; trace.md owns the trace format, replay,
    EVENT payload encodings, and the trace-q CLI/output grammar.
    trace-q, tracefile.py, and the disassembler were conformed to
    trace.md 2-6 (exit codes 0/1/2; key=value line grammar; hex128
    widths; `-` placeholders; sym resolution with smallest-name
    tie-break and A-symbols excluded; canonical disassembly incl.
    signed-decimal branch displacements and bare `invalid`; torn-tail
    tolerance with stderr diagnostic; class-2 malformation rejection;
    the 7-key META catalog). trace.md 8's vectors TV-1/TV-2/TV-7..10
    are enforced byte-exactly by trace-q/test_vectors.py, including
    the 12 TV-8 command fixtures and the assembler reproducing TV-1's
    112 image bytes. Consequences for earlier entries: 1 and 16
    confirmed; 2, 9, 24, 25, 26 resolved as noted; 17's triple-fault
    consequence overturned (diagnostic tl=3 TRAP record).

28. **devspec/trace.md 2.3.1/2.3.4 payload offset tables are
    internally inconsistent** — EXEC lists insn at 24 then wb at 40 /
    flags at 56 (payload is 50 bytes; correct: wb 32, flags 48,
    pred_wb 49), and TRAP lists epc at 24 / baddr at 40 (payload is
    49 bytes; correct: epc 16, baddr 32, tl_after 48). The TV-2 hex
    dump and its field-by-field decode (record offsets, i.e. payload
    offset + 8) are consistent with TOOLING-SPEC 3.2's field order
    and payload lengths, so the toolchain follows the vectors; the
    two offset tables need a doc fix.

29. **TOOLING-SPEC 4.3 store operand order** — 4.3 shows load syntax
    only (`lds.32 rd, [ea]`) and never a store. The assembler
    originally accepted `st.W rs, [ea]`; devspec/asm.md 5.5 pins
    `st.W [ea], rs` (and trace.md 6.4's canonical disassembly plus
    TV-8's `st.64 [r2 + 0x4], r1` agree). The assembler and every
    test source/generator were flipped to `[ea], rs`; all 13 suite
    images were verified byte-identical before/after the flip
    (operand order is surface syntax only).

30. **emu-common-prompt `--check-devorder N` — nothing on this
    platform can fail it.** The mode models ISA 9.2's weak store
    order (a depth-N queue of ordinary stores, drained by device
    stores), but every device consumer on the reference platform
    reads device space only — the pixel buffer and NIC TX/RX buffers
    are device windows, and no device DMAs from RAM — while 9.1
    keeps single-CPU self-loads program-ordered (the queue must
    forward). So there is no guest-observable difference and no
    assertable staleness: the mode's only testable property today is
    semantics-neutrality, which is what c7_dev_ordq pins (the c7_dev
    image must pass identically under `--check-devorder 4`, forwarding
    out of a full queue included). The mode earns real assertions
    only when a RAM-reading device (DMA) or SMP arrives. Chosen: an
    emulator whose devorder mode perturbs nothing observable is
    conforming; a CHECKFAIL under c7_dev_ordq is a bug. **(emulators
    must match)**

31. **Replay feeds cannot exercise live-mode event *generation*
    rules; feed META `level` is meaningless.** The EVENT-fed tests
    (c7_kbd, c7_kbd_ovf, c7_resize — the `events=` MANIFEST class)
    inject hand-built EVENT records via `--replay`, per trace.md
    4/5.1: the only headless event source. A feed carries finished
    event words verbatim, so everything input.md specifies about
    *generating* them from host input — clamping (INPUT-15, MV-03/07,
    8.6's "generated by host pointer" leg), in-table-usage-only
    (INPUT-09/10), press/release alternation and no-repeat
    (INPUT-11/12), mouse dedup (INPUT-16), and generation-state
    advance past a drop (INPUT-19) — is untestable here and remains
    untested; the suite pins pop/visibility/overflow/interrupt
    behavior instead, plus the one replay-checkable generation fact:
    the emulator must RECOMPUTE the 8.5 drop decision and byte-match
    the feed's flags (trace.md 5.4, checks/c7_kbd_ovf.py). Testing
    generation needs a GUI/live harness — out of toolchain scope.
    Second reading in the same area: an events-only feed has no
    meaningful recording `level` (it records nothing), but META's
    seven keys are all mandatory (trace.md 2.3.7) and replay
    validates only sha/encoding/trace (5.1). Chosen: feeds write
    `level=0`, `mode=live`; replayers must not reject a feed for its
    `level`/`mode` values. **(emulators must match)**

32. **input.md/trace.md, recorded EVENT `cycle` vs feed `cycle`
    under replay.** trace.md 2.3.5/5.4 record the cycle "at which the
    event was applied", and 5.2 applies a feed event at the first
    boundary where `cycle >= C` — so a replayed emulator could
    legitimately record a LATER cycle than the feed's C if no
    boundary lands on C exactly. On this ISA every retired
    instruction advances `cycle` by exactly 1 (ISA-SPEC 4), so in a
    guest that never idles every cycle value is a boundary and
    application lands exactly on C. The event-fed tests' guests never
    execute WFI, and checks/evcheck.py therefore asserts recorded
    EVENT records equal the feed byte-for-byte, cycles included. If a
    future test WFIs across a feed cycle (the 7.6 jump can skip
    values), that equality no longer holds; revisit then. **(emulators
    must match)**

33. **asm.md 8.2's file_len trim parenthetical contradicts both T4
    and trace.md TV-1: instruction bytes are never trimmed.** 8.2
    says `file_len` = "mem_len minus the trailing run of zero bytes
    (i.e. index of the last non-zero byte + 1)". Applied literally to
    T4's first segment (which ends in `halt` = byte FE then seven
    zero bytes) that gives file_len 25 — but the normative T4 dump
    says 32 (whole halt word kept, image 162 bytes not 155), and
    trace.md's TV-1 reference image agrees (file_len = mem_len = 32
    for a code segment ending in halt; TV-1's sha256 is embedded in
    TV-2's META, so every emulator will re-derive it). The dump's
    second segment ("Hi\0" -> file_len 2, ASM-21) shows the trim IS
    real for data bytes. Chosen reading, implemented in asm.py and
    pinned byte-exactly by asm/test_asmmd.py (T4) and
    trace-q/test_vectors.py (TV-1): trim the trailing zero run but
    never into instruction-emitted bytes. Fix suggestion for asm.md
    8.2: "index of the last non-zero byte + 1, but not below the end
    of the segment's last emitted instruction". **(emulators
    unaffected; loaders reproduce either encoding)**

34. **asm.md ambiguities resolved while building the E-catalog
    conformance suite** (asm/test_asmmd.py pins each choice):
    (a) *Line attribution for whole-image errors* — ASM-11 demands
    "the correct 1-based line number" but E042/E045-E049 have no
    single triggering line. Chosen: E042 -> the later segment's
    `.org` line; E045 -> the empty segment's `.org` line;
    E046/E047/E048 -> the `.entry` line; E049 -> the first `.org`
    line. (b) *.equ cycles* — `.equ a, b` / `.equ b, a` is no
    catalog row; the catalog is "complete and closed", so the cycle
    reports E030 (the chain never resolves to a value). (c) *Bytes
    >= 0x80 in comments* — 2.1 makes them E001 "outside string and
    character literals", but comments are an ignored region; the
    assembler checks after comment stripping, so comments tolerate
    them. (d) *`la` with a CONST target* — 6.2 says "any ADDR-valued
    expression" but no error code covers a CONST one, and 5.7 branch
    targets explicitly allow both; `la` accepts both. (e) *sreg CONST
    bound* — 5.9/E026 say [0, 2^21-1] although the imm field is 22
    bits; enforced as written. (f) *Default output name* — "the first
    input's basename with the extension replaced" keeps the
    directory (splitext), not a path-stripping basename.

35. **trace.md 5.2/T-18 vs SPEC-ISSUES 20's WFI T+1 rule: EVENT
    records applied during a WFI stall cannot replay byte-identically**
    (found by the OS agent - Oasis is the first guest that idles in
    WFI with keyboard events in flight; the toolchain's own EVENT-fed
    c7 tests poll, so the interaction was never exercised). Observed
    on emu-c: a feed event at cycle C arriving during a WFI stall is
    applied and stamped at the post-wake boundary T+1 = C+1 (entry
    20's frozen "resume at T+1" reading), so record->replay re-stamps
    it C+2, and each replay generation drifts one more cycle - the
    execution suffix shifts with it, and where the guest reads `cycle`
    (Oasis `uptime`) the replay is a genuinely different run. This
    directly violates trace.md 5.2/T-18 ("replay reproduces every
    post-META record byte-identically, EVENT records included").
    Reading chosen for the Oasis suite, implemented in
    os/oasis/tests/replaycmp.py: the replay-identity gate accepts
    exactly the drift signature (EVENT pair, same device+payload,
    cycle+1) as a loud SKIP and fails anything else; it reverts to
    strict byte-identity the moment the emulators change.
    *Cross-emulator addendum, same session: the two emulators in fact
    DISAGREE on this stamp today - the Oasis smoke feed run on both
    produced traces whose only differences (25 of 14732 records) are
    EVENT stamps: emu-py writes the visibility cycle T (= the feed
    cycle), emu-c writes T+1. Every EXEC/TRAP/MEMW/DEVW record is
    byte-identical, i.e. both wake and execute identically per entry
    20; only the stamp differs. The conformance difftest never caught
    it because no toolchain EVENT-fed test idles in WFI. emu-py's
    reading is also the one under which T-18 replay identity is
    satisfiable and stable.* Suggested resolution (owner + emulator
    agents): freeze emu-py's reading - an event applied during a WFI
    stall is stamped with its visibility cycle T, not the post-retire
    boundary T+1; the T-09 "same cycle as the following TRAP/EXEC"
    phrasing then reads vacuously across a stall, and T-18 becomes
    satisfiable. **(emulators must match; trace.md may need a
    clarifying sentence in 3.3)**
