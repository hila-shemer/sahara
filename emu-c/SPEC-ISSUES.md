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
   *devspec (landed on main) pins the same reading: boot.md 3.4/BOOT-15
   and devspec/SPEC-ISSUES.md 19 — data or fetch in a hole traps DEVERR
   with baddr = the accessed address, predicated-false exempt. Still
   flagged there as new normative surface for Hila; risk retired unless
   she rules against it.*

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
   *Pinned by devspec/trace.md 3.3 and T-06 (same reading; recorded there
   as devspec SPEC-ISSUES 17 for Hila). Risk retired unless overruled.*

10. **TOOLING-SPEC 3.2 — pred_wb semantics.** u8 field, but PWR writes
    seven predicates at once. Chose: when flags bit 2 (wrote-pred) is
    set, pred_wb = the whole predicate file P7..P0 *after* the write
    (works uniformly for CMP and PWR). **[divergence risk]**
    *Pinned by devspec/trace.md 2.3.1, verbatim. Risk retired.*

11. **TOOLING-SPEC 3.2 — writes discarded by hardware (r31 dst, p0
    pred).** Chose: discarded writes set no wrote-dst/wrote-pred flag,
    wb/pred_wb stay 0 (the architectural effect is nil).
    *Pinned by devspec/trace.md 2.3.1 rules (r31 case stated verbatim).*

12. **TOOLING-SPEC 3.2 — intra-cycle record order.** Not pinned. Chose:
    MEMR record(s), then MEMW, then EXEC, all carrying the same cycle;
    TRAP stands alone. **[divergence risk]** for byte-identical diffs.
    *Pinned by devspec/trace.md 3.3/T-08: access records before their
    EXEC, atomic MEMR before MEMW, failed CAS emits MEMR only — the
    implemented order. Risk retired.*

13. **TOOLING-SPEC 3.2 — META payload format.** "key/value text (image
    path+hash, encoding version, mode flags)": no key names, no hash
    algorithm, no text framing given. Chose newline-separated
    `key=value` lines, image *basename* (a full path would make traces
    differ across working directories), FNV-1a-64 as the hash. Needs
    pinning before cross-implementation byte comparison can include
    META. **[divergence risk]**
    *Superseded: devspec/trace.md 2.3.7 pins the v1 catalog (trace,
    encoding, level, mode, image, image_sha256, platform — exactly, in
    order) and 5.3 excludes the run-variant keys (mode, image) from
    comparison, which answers the working-directory concern the basename
    choice was solving; the hash is SHA-256. Adopted wholesale
    (emu-c/sha256.c, main.c meta_record), image= now the exact CLI
    argument, and --replay validates trace/encoding/image_sha256 per
    5.1. The harness now byte-compares a full run against trace.md TV-2,
    META included. Risk retired.*

14. **TOOLING-SPEC 3.2 — MEMR `val` for a sign-extending load.** Chose
    the raw memory bytes zero-extended (what memory returned), not the
    sign-extended writeback (which EXEC's wb already records).
    *Pinned by devspec/trace.md 2.3.3 ("bytes above size zero").*

15. **TOOLING-SPEC 3.2 — are page-table-walk reads traced as MEMR?**
    Chose no: MEMR records architectural data accesses of instructions;
    walk reads are a hardware mechanism. **[divergence risk]** at trace
    level 2.
    *Pinned by devspec/trace.md 2.3.3/T-12: fetches and walk reads are
    never recorded. Risk retired.*

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
    *stdout/exit side confirmed by root SPEC-ISSUES 12 ("any
    architectural halt prints the same line and exits 0, emulators must
    match") and exercised by c1_triplefault/c1_wfihang. The triple
    fault's trace-side record is a live conflict — see entry 33.*

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
    SPEC-ISSUES 20). ~~Implemented: WFI retires normally (EXEC record at
    cycle N, cycle -> N+1), then virtual time jumps so that
    post-stall `cycle` equals **exactly the pending event's cycle**
    (timecmp); no extra +1. The root entry recommends freezing the
    other reading (jump, then +1 for the retire). c1 only asserts
    `cycle >= timecmp`, so both pass today; the TRAP record's cycle
    field will differ in the cross-diff until Hila freezes one.~~
    *RESOLVED 2026-08-09: the cross-diff surfaced the divergence
    (c1_traps record 435) and the root entry froze its recommended
    reading — jump to T, then +1 for the retire. wfi_wait now
    evaluates pending at WFI's own cycle c0 and resumes at T + 1;
    this also fixed a latent edge where timecmp == c0 + 1 woke at
    c0 + 1 instead of timecmp + 1.*

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

32. **PLATFORM-SPEC 1 — the device windows lie numerically inside the
    default 256 MB RAM region.** RAM region 0 spans `0x0 .. ram_len`
    (default 0x1000_0000) and the register windows sit at
    0x0F00_0000..0x0F05_FFFF, inside that span. Chose **carve-out**:
    "everything at 0x0F00_0000 and above in this map is device space"
    is normative classification, so device-space decode wins over RAM
    backing (emu-c/platform.h; checked before every RAM access: data,
    atomic, fetch, and page-table-node reads). Three sub-readings,
    each of which the other implementation could take differently:
    (a) plain loads/stores to the windows before the device phase trap
    DEVERR -- no device backs the address (device_count=0 in the table
    this emulator writes), extending entry 3's "no such physical
    address" reading; these accesses stop trapping per-device once
    devspec behavior lands, atomics keep trapping per ISA 5.4. (b) A
    page-table node inside a window is malformed (PF_*, entry 2), not
    DEVERR. (c) The display pixel buffer (0x1000_0000, size "per
    table") is NOT classified until a display table entry defines its
    length: under default RAM its base is already out-of-RAM (DEVERR
    via entry 3), but with `--ram` > 256 MB an atomic there would NOT
    trap yet -- and ram_len > 0x1000_0000 makes the spec's own map
    self-overlapping, which needs a ruling anyway. **[divergence
    risk]** (a) and (c) are observable in traces and exit paths.
    *devspec/boot.md (landed) resolves the map: RAM region 0 is
    [0, 0x0F00_0000) — 240 MB, ending where the windows begin ("256 MB"
    read as the address budget below the pixel buffer, devspec
    SPEC-ISSUES 1); [0x0F06_0000, 0x1000_0000) is an undeclared hole
    trapping DEVERR (BOOT-15, matching sub-reading (a)'s trap and
    entry 3); the pixel buffer is device space located by the display
    record's params, killing sub-reading (c)'s self-overlap. Sub-
    reading (b) — walk node in a window → PF — is not contradicted.
    ADOPTION DEFERRED: the current tree still decodes a 256 MB RAM span
    with the windows carved out and writes a device_count=0 table;
    switching to the 240 MB region + boot.md 5's byte-exact 4-device
    reference table (V1) + hole classification changes guest-visible
    table bytes and the [0x0F06_0000, 0x1000_0000) trap behavior, and
    belongs to the device phase (build order 6), which this run's
    dispatch keeps gated. The suite today probes RAM boundaries only
    below 0x0F00_0000 and above 0x0F06_0000, so it cannot distinguish
    hole-DEVERR from RAM there — the flip is invisible to it except
    through the table bytes.*
    *ADOPTED (iteration 10, with the C7 device tranche): platform.h now
    classifies the full boot.md map — RAM region 0 capped at
    0x0F00_0000, four register windows with dev.c behavior, NIC TX/RX
    and the pixel window as memory-like device space, holes at
    [0x0F06_0000, 0x1000_0000) and past the pixel window trapping
    DEVERR (BOOT-15) — and main.c writes the byte-exact boot.md V1
    four-device table (test_dev.c asserts all 328 bytes + window
    zeros). Sub-reading (b) (walk node in device space → PF) kept.*

33. **devspec/trace.md 2.3.4 vs root SPEC-ISSUES 17 — does a triple
    fault write a diagnostic TRAP record?** Root entry 17 (toolchain,
    "emulators must match"): delivery at TL=2 delivers nothing, no
    third TRAP record; checks/c1_triplefault.sh asserts exactly two.
    devspec/trace.md 2.3.4/3.3/T-07 (landed on main): the trace
    records the triple fault loudly — one final diagnostic TRAP with
    the cause/epc/baddr the third trap would have delivered and
    tl_after = 3, then the trace ends. Both readings are consistent
    with the frozen specs (ISA 7.2 and CONFORMANCE are silent about
    the trace; TOOLING 3.2 only ties EXEC to retirement). Verified
    empirically this iteration: emitting the devspec record turns
    c1_triplefault red (trace-q renders it fine; the check counts 3).
    Implemented **root 17** — the shared suite is the operative gate
    and its author pinned this contract explicitly; the devspec-side
    flip is one line in deliver() (see the comment there) plus the
    harness's triplefault-two-traps-no-diagnostic check. Needs either
    a c1_triplefault update (toolchain's trace.md reconciliation) or a
    trace.md amendment; flagged for Hila. **[divergence risk]** — the
    Python implementation may follow trace.md here.
    *RESOLVED (iteration 8): the toolchain's devspec reconciliation
    (root SPEC-ISSUES 27, revising 17) flipped checks/c1_triplefault.sh
    to assert exactly three TRAP records with the tl_after=3
    diagnostic. deliver() now emits it (the documented one-line flip;
    no cycle consumed, no sreg writes) and the harness check became
    triplefault-diagnostic-trap. Divergence risk retired — trace.md
    2.3.4 and the suite now agree. The 2.3.1/2.3.4 offset-column
    arithmetic slips found independently this iteration (EXEC wb/flags/
    pred_wb at 40/56/57, TRAP epc/baddr at 24/40 — inconsistent with
    the fixed lengths 50/49 and TV-2's packed layout) are root
    SPEC-ISSUES 28; the packed layout is what this emulator writes and
    what --replay's strict reader checks against.*

34. **PLATFORM-SPEC 1 / boot.md 5 — what does `--ram` mean now that
    "256 MB" is an address budget, and which values are legal?** boot.md
    reads the default 256 MB as the budget below the pixel buffer, so
    region 0 = [0, 0x0F00_0000) (240 MB); it also requires region
    base/len to be 64 KB-granular (3.4 rule 1) and says the emulator
    "recomputes the RAM region record(s)" for other sizes — plural,
    unspecified placement for the overflow. Chose: `--ram` ≤ 240 MB maps
    to a single region of exactly that length; 240 MB < `--ram` ≤ 256 MB
    is capped at 240 MB (the budget reading); `--ram` > 256 MB dies
    loudly (a second region needs a placement rule — above the pixel
    window? gap size? — that no spec pins); a `--ram` that is not a
    64 KB multiple dies loudly (boot.md V7 requires the generator to
    refuse, and rounding silently would violate byte-exact table
    determinism, BOOT-16). **[divergence risk]** the Python
    implementation may round, refuse the 240–256 MB band, or invent a
    second-region placement; visible in table bytes and exit paths only
    for non-default `--ram`.

35. **nic.md 6 vs headless live mode — the translator is not yet
    implemented; live TX frames are dropped with no reply.** nic.md's
    translator decision tree is normative (ARP probes get replies,
    DHCP answers, etc.), but replay mode sources every RX frame from
    the trace alone (PLATFORM-SPEC 7 determinism rule; nic.md replay
    isolation), so a headless replay run never consults the translator
    and this emulator is conformant there. In live headless mode
    TX_DOORBELL validates E5, drains the store queue, traces DEVW, and
    drops the frame — no reply is synthesized, diverging from the
    decision tree for any frame it would answer. c7_dev only transmits
    an all-zero frame the tree drops anyway. The translator belongs to
    the NIC-bridging GUI phase (emu-c-prompt.md); until it lands, a
    live-mode guest doing real networking sees a dead wire, loudly
    documented here rather than half-faked. Not a divergence risk for
    the suite: no shared test can reach live-mode RX (the harness
    injects no EVENTs and the tree's reply paths need real frames).

36. **PLATFORM-SPEC 8 / trace.md 5.4 / ISA 7.6 — what a live WFI does
    when the event feed is still open, and what cycle a WFI-woken
    event records.** Headless `wfi_wait` jumps to the next known
    event/timer cycle and halts on deadlock; live, "no future event"
    is only true once the session ends, so halting is wrong. Chose,
    per the GUI work order: with a front-end-set `live_yield` flag, a
    WFI with no wake source returns an idle outcome — pc still at the
    WFI, nothing retired, no records — and re-executes identically
    once input is fed; the flag is never set headless, so `--replay`
    and the deadlock halt are untouched. Second half, the stamp: the
    front end stamps a WFI-woken event E = max(wfi_cycle + 1,
    pacing target) and `wfi_wait` now wakes at a boundary of exactly
    E (the timer keeps its frozen T+1 landing, root SPEC-ISSUES 20).
    Root SPEC-ISSUES 32 anticipated this corner: a wake at E+1 would
    re-stamp the event one cycle later on *every* replay generation,
    so replay-of-a-recording could never be byte-identical across a
    WFI stall. Stamp-at-E is the only fixed point; the trace shape is
    EXEC(WFI)@C, EVENT@E, TRAP@E. **[divergence risk]** emu-py's
    wfi wake may land events at E+1; no shared test WFIs across a
    feed cycle today (root 32), so the cross-diff stays green until
    one does — revisit root 32's "revisit then" with this reading.

37. **trace.md 2.3.7 — the META `mode` value for interactive GUI
    sessions.** The v1 catalog is closed (`live` or `replay`, no new
    keys, no new values), and nothing says which one an interactive
    session writes. Chose: `mode=live` — the GUI session is exactly
    the "recording run" the live/replay pair anticipates, and the key
    is run-variant (excluded from comparison, 5.3), so replaying a GUI
    session with `mode=replay` in the copy compares clean. No new
    catalog value invented.

38. **Nothing anywhere pins the GUI's pacing rate.** Pacing is
    deliberately outside the specs (the wall<->cycle map never appears
    in semantics or the trace), but the binary still needs a default.
    Chose: 2,000,000 cycles/s (`--hz N`, `0` = free-run) — fast enough
    that the demo image feels instant, slow enough that a level-0
    trace stays ~100 bytes/instruction manageable. Changing the
    default re-times *future* recordings only; every existing trace
    replays unchanged.

39. **The GUI's default recording level.** Recording is mandatory
    (PLATFORM-SPEC 8: a session records as it runs), but no spec picks
    the level for a session nobody asked to trace. Chose: level 0 —
    the cheapest *legal* level (META+EXEC+TRAP+EVENT, trace.md 3.1
    rule 4). Deliberately did NOT invent an EVENT-only level; that is
    entry 40's proposal, and until it lands the format is what it is.

40. **Proposal: an events-only recording level.** Level 0 still costs
    one EXEC record per retired instruction — ~58 bytes * 2 MHz =
    over 100 MB/min of interactive session, all of it reconstructible
    from the image plus the EVENT records alone (replay consumes only
    EVENTs, trace.md 5.1). Proposed: a `level=e` (or similar) catalog
    value recording META+EVENT only, defined in trace.md 2.3.7/3.1 so
    both implementations and trace-q agree; the level-nesting rule
    (5.3) extends naturally (filtering any trace to EVENT records
    yields the events-only trace). Until then the GUI buffers writes
    (1 MB stdio buffer) and pays the disk. Not implemented — the
    format changes only by trace.md changing.
