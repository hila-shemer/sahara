# SPEC-ISSUES — emu-c

Ambiguities and gaps found while implementing, with the reading chosen
(emu-common-prompt.md: do not silently pick). Entries marked **[divergence
risk]** are places where the Python implementation can legitimately read
the spec differently and the record-by-record trace diff will flag it;
they need a spec ruling more urgently than the rest.

1. **ISA-SPEC 8.2 — page-table node header field offsets.** The header
   lists `shift` (u64), `prefix` (u128), `prefix_mask` (u128) but gives no
   offsets. Packed layout (0/8/24, reserved [40,64)) vs natural alignment
   (0/16/32, reserved [48,64)) both fit in 64 bytes. Chose **packed**, by
   analogy with PLATFORM-SPEC's device entry, which explicitly places a
   u128 at offset 8. **[divergence risk]** — C2 will diverge if the other
   implementation chose natural alignment.

2. **ISA-SPEC 8.2/8.3 — what exactly is a "malformed node"?** Chose to
   fault PF_* on: node or ptbase not 64-byte aligned; node not fully
   inside RAM; header reserved bytes [40,64) nonzero; `shift` > 104 or not
   a multiple of 8; leaf at shift != 0; entry type 3; leaf reserved bits
   15:6 nonzero; walk deeper than 15 nodes (cycle/degenerate-table bound —
   14 chunks cover the 112-bit VPN, so an honest table never needs more).
   The depth bound and the reserved-header check are the debatable ones.

3. **ISA-SPEC (7.1, 9.2) — physical access outside RAM and outside every
   device window** (reachable with MMU off, or via a leaf mapping a frame
   beyond ram_len, or a walk to a node beyond RAM). No cause is specified
   for "no such physical address". Chose **DEVERR with baddr = the
   virtual address** for data/fetch accesses, and PF_* when it happens
   inside a page-table walk (folded into "malformed node"). **[divergence
   risk]**

4. **ISA-SPEC 3/5.5 — fetch from a misaligned PC.** JALR checks its
   target, but IRET (arbitrary epc via MTSR) and trap vectors can set
   pc to a non-8-aligned value; section 3 only says instructions "must be
   8-byte aligned". Chose: fetch of a misaligned pc traps UNALIGNED with
   epc = baddr = pc.

5. **ISA-SPEC 3.3 — mod kind 0 with nonzero amount.** "amount must be 0"
   with no consequence stated. Chose ILLEGAL trap (loud-failure policy),
   checked only when the mod field is actually applied (unused fields are
   "ignored by hardware" per section 3).

6. **ISA-SPEC 5.8 — INVTP with imm != 0.** "other values reserved". Chose
   ILLEGAL trap, consistent with reserved opcodes/widths.

7. **ISA-SPEC 2.3 — writes of nonzero "unused high bits" to an sreg.**
   "must be written as zero" with no consequence stated. Chose
   mask-and-ignore: status keeps bits 6:0, fcsr keeps bits 7:0, no trap.
   The alternative (ILLEGAL) is defensible under loud-failure; masking
   matches "read as zero".

8. **ISA-SPEC 7.1 vs 9 — UNALIGNED vs translation-fault priority.** An
   access can be both misaligned and unmapped. Chose alignment first (it
   needs no walk). **[divergence risk]** in trap-cause tests.

9. **TOOLING-SPEC 3.2 — does a faulting instruction emit EXEC? does it
   consume a cycle?** ISA 4 says cycle increments per *retired*
   instruction and per delivery; a faulting instruction has no
   architectural effect, so: chose **no EXEC record and no cycle for the
   faulting instruction itself; the TRAP delivery consumes the one
   cycle**. SYSCALL is treated the same way (TRAP record only, no EXEC).
   **[divergence risk]** — this shapes every trace containing a trap.

10. **TOOLING-SPEC 3.2 — pred_wb semantics.** u8 field, but PWR writes
    seven predicates at once. Chose: when flags bit 2 (wrote-pred) is
    set, pred_wb = the whole predicate file P7..P0 *after* the write
    (works uniformly for CMP and PWR). **[divergence risk]**

11. **TOOLING-SPEC 3.2 — writes discarded by hardware (r31 dst, p0
    pred).** Chose: discarded writes set no wrote-dst/wrote-pred flag,
    wb/pred_wb stay 0 (the architectural effect is nil).

12. **TOOLING-SPEC 3.2 — intra-cycle record order.** Not pinned. Chose:
    MEMR record(s), then MEMW, then EXEC, all carrying the same cycle;
    TRAP stands alone. **[divergence risk]** for byte-identical diffs.

13. **TOOLING-SPEC 3.2 — META payload format.** "key/value text (image
    path+hash, encoding version, mode flags)": no key names, no hash
    algorithm, no text framing given. Chose newline-separated
    `key=value` lines, image *basename* (a full path would make traces
    differ across working directories), FNV-1a-64 as the hash. Needs
    pinning before cross-implementation byte comparison can include
    META. **[divergence risk]**

14. **TOOLING-SPEC 3.2 — MEMR `val` for a sign-extending load.** Chose
    the raw memory bytes zero-extended (what memory returned), not the
    sign-extended writeback (which EXEC's wb already records).

15. **TOOLING-SPEC 3.2 — are page-table-walk reads traced as MEMR?**
    Chose no: MEMR records architectural data accesses of instructions;
    walk reads are a hardware mechanism. **[divergence risk]** at trace
    level 2.

16. **TOOLING-SPEC 1 vs ISA-SPEC 11 — image `entry` vs reset PC.**
    TOOLING says the loader "then start[s] at entry"; ISA and PLATFORM
    fix reset at PA 0x1000 and call entry "convention". Chose: execution
    always starts at 0x1000; entry is validated (8-aligned) and
    otherwise ignored by the emulator.

17. **CLI contract — hex digit case of `HALT r0=`.** "32 hex digits" is
    byte-compared by the harness; chose lowercase. **[divergence risk]**
    (trivial to fix, but must be pinned).

18. **CLI contract — triple fault and WFI deadlock.** Both "halt the
    machine" (ISA 7.2, 7.6) but are not the HALT instruction, and the
    CLI defines output only for HALT/MAXCYCLES/CHECKFAIL. Chose: both
    print the normal `HALT r0=...` line and exit 0, plus a diagnostic
    note on stderr (stdout contract untouched, failure still loud).
    **[divergence risk]**

19. **ISA-SPEC 7.5 — timer compare width.** `cycle >= timecmp` compared
    at full 128-bit sreg width here; the trace's EXEC/TRAP cycle field is
    u64, so a >2^64-cycle run would wrap in the *trace* only. Harmless
    in practice; noting the width mismatch between ISA (128-bit sregs)
    and TOOLING (u64 cycle fields).

20. **ISA-SPEC 5.4 — CAS comparison width.** "low w of old == low w of
    R[src2]": src2 is compared truncated, not canonicalized — high
    garbage in the expected-value register is ignored at w=32 (this is
    what C3's "width-33 garbage" test wants). Implemented exactly that;
    noting because 3.4's canonical-form rule might tempt a stricter
    reading.

21. **ISA-SPEC 10.3 / emu-c-prompt — RMM has no C99 fenv equivalent.**
    fcsr rounding mode 4 (RMM, ties away from zero) cannot be set via
    `fesetround` (C99 defines only RNE/RTZ/RDN/RUP), so the prompt's
    "host float/double + fesetround + fetestexcept" recipe cannot
    implement the full fcsr contract. Deviation: FP is implemented as
    an integer softfloat (fp.c) — exact mantissa arithmetic in a
    128-bit window, one software rounding per operation, all five
    modes, flags computed exactly. No host-FP dependence at all, which
    also strengthens the determinism guarantee. Verified against an
    independent exact-rational oracle (test/fp_oracle.py, itself
    checked against host-hardware IEEE doubles at RNE).

22. **ISA-SPEC 10.3 — which ops are "the next FP operation that
    rounds"?** First chose "the ops that consult fcsr" (exempting
    FCVTFI/FCVTFIU, which truncate regardless of fcsr); root
    SPEC-ISSUES 19 (toolchain) rules the other way — *all* FCVT forms
    round, FMIN/FMAX/FCMP* must not trap — with "emulators must
    match". Adopted the toolchain ruling; risk resolved unless the
    spec is edited to disagree.

23. **ISA-SPEC 10.4 — FCVTFF with source format == destination
    format.** "FP -> FP (32 <-> 64)" plus "illegal format combinations
    trap ILLEGAL". Chose: same-format FCVTFF traps ILLEGAL (the spec
    names only the two cross conversions); the permissive reading is a
    canonicalization no-op. **Resolved by the shared suite:** c4_fp.s
    test 920 asserts the raw same-format word traps ILLEGAL.

24. **ISA-SPEC 10.3 — underflow flag definition.** 754 leaves tininess
    detection (before vs after rounding) to the implementation and the
    spec is silent. Chose **tininess after rounding**, UF raised only
    when the result is also inexact (the x86-SSE convention; RISC-V
    uses the same pair). **[divergence risk]** — a before-rounding
    implementation differs on results that round up to the smallest
    normal. c4_fp.s deliberately keeps its UF vectors off that edge
    until root SPEC-ISSUES 13 is frozen, so the risk stays untested.

25. **ISA-SPEC 10.2 — signaling NaN vs FCMPEQ.** "FCMPLT and FCMPLE
    with a NaN operand raise NV, FCMPEQ does not" — read literally:
    FCMPEQ never raises NV, *even for an sNaN operand*, diverging from
    754's compareQuietEqual (which signals on sNaN). Implemented the
    literal spec. Everywhere else any sNaN operand raises NV (FMIN/
    FMAX included, per 754-2019 minimum/maximum). **[divergence risk]**
    — c4_fp.s only feeds FCMPEQ a qNaN, never an sNaN, so the shared
    suite does not arbitrate this.

26. **ISA-SPEC 10.2 — FMADD of (0, inf, c).** 754-2008/2019 makes NV
    for fusedMultiplyAdd(0, inf, qNaN) implementation-defined. Chose:
    0 x inf raises NV and returns the canonical qNaN regardless of c
    (the RISC-V choice). **[divergence risk]** — c4_fp.s covers
    FMADD(inf, 0, 1.0), where NV is forced under either reading; the
    c=qNaN case that separates them is untested.

27. **ISA-SPEC 10.4 — NX on inexact conversions.** 10.4 mentions only
    NV (saturation) explicitly; standard 754 also raises NX on inexact
    F->I truncation and inexact I->F / F->F rounding. Implemented the
    standard behavior: NX accumulates for inexact conversions, and is
    *not* raised alongside a saturating NV. **Resolved by the shared
    suite:** c4_fp.s asserts flags=NX on 21 inexact-conversion vectors
    and NV alone on the saturating ones.

28. **ISA-SPEC 10.3 — exact overflow raises NX.** A result exactly
    representable at an out-of-range exponent (e.g. maxfin + maxfin at
    RNE has no fraction bits lost) still raises OF|NX per 754's
    overflow definition. Noting because "flags = what was lost" would
    suggest OF alone.

29. **ISA-SPEC 10.2 — zero-result sign rules.** Not spelled out in the
    spec; implemented 754-2019: exact cancellation x + (-x) gives +0
    except -0 under RDN; sums of like-signed zeros keep the sign;
    FMADD applies the same rule between the product sign and the
    addend; FMIN/FMAX order -0 < +0.

30. **ISA-SPEC 7.6 — exact cycle value after a WFI stall** (root
    SPEC-ISSUES 20). Implemented: WFI retires normally (EXEC record at
    cycle N, cycle -> N+1), then virtual time jumps so that
    post-stall `cycle` equals **exactly the pending event's cycle**
    (timecmp); no extra +1. The root entry recommends freezing the
    other reading (jump, then +1 for the retire). c1 only asserts
    `cycle >= timecmp`, so both pass today; the TRAP record's cycle
    field will differ in the cross-diff until Hila freezes one.
    **[divergence risk]**

31. **tests/gen_c2.py — test bug: ROOT2's code-page leaf drops the U
    bit, so the ptbase/asid switch window CHECKFAILs under root
    SPEC-ISSUES 21's own definition.** The generator's comment (and
    root entry 21) promise the two fetches between `mtsr ptbase` and
    `mtsr asid` in test [32] "translate identically under either
    table" — but ROOT maps VPN0 `leaf(0, R,W,X,U)` = 0x3e while ROOT2
    maps it `leaf(0, R,W,X)` = 0x1e. Frames match; the U permission
    does not. Entry 21 pins stale = "frame and permissions differ from
    a fresh walk", so a conforming checker MUST fire on the fetch at
    0x17e0 (VPN0, cached under asid A from ROOT, fresh-walked under
    ROOT2). The bug is in the test, not the spec and not this
    emulator: one character in gen_c2.py (add "U" to ROOT2's entry 0)
    fixes it. Verified both ways on emu-c: the committed image runs to
    HALT 0x600D with the check off; a patched copy (0x1e -> 0x3e at
    ROOT2 entry[0], nothing else) runs to HALT 0x600D twice with
    --check-invtp on and byte-identical level-2 traces. Until the
    toolchain fixes the generator, c2_mmu fails on any emulator that
    implements entry 21 faithfully — arguably on both. **(toolchain
    fix needed; test unchanged here per the no-edits rule)**
    *Resolved: toolchain 8f31564 adds exactly that U bit (c2_mmu.s
    entry[0] 0x1e -> 0x3e, matching the patched copy verified above)
    plus the two assertion-side images root entry 22 owed; after the
    merge the shared suite is 10/10 green here, c2_mmu included.*
