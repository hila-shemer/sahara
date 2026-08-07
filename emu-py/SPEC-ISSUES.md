# emu-py SPEC-ISSUES

Ambiguities found while implementing, and the readings chosen. Format:
file:section — the ambiguity — the chosen reading. Entries marked
**[cross-impl]** are places where the two implementations could silently
diverge byte-for-byte in traces or observable behavior; those want a spec
ruling most urgently.

1. **ISA-SPEC 4 / 7.2 — does a faulting instruction consume a cycle of its
   own?** §4 says cycle increments "for every retired instruction … and by
   1 for every trap delivery". A faulting instruction has no architectural
   effect, so I read it as *not retired*: only the delivery increments
   cycle (a fault costs exactly 1 cycle total). Same reading applied to
   SYSCALL (its trap delivery is its only cycle). **[cross-impl]**

2. **ISA-SPEC 11 vs TOOLING-SPEC 1 — start pc.** TOOLING's loader
   semantics say "then start at entry"; ISA-SPEC 11 says reset pc =
   0x1000 and TOOLING itself notes "entry is convention, reset PC is
   architecture; images place a jump at 0x1000 when entry differs".
   Chosen: the machine always starts at 0x1000; `entry` is metadata. If
   the other implementation jumps directly to entry, traces diverge on
   the trampoline EXEC record. **[cross-impl]**

3. **TOOLING-SPEC 3.2 — META record content is unspecified** ("key/value
   text"), yet traces are compared byte-for-byte across implementations.
   Chosen: `key=value\n` lines: image (basename), sha256 (image file),
   encoding (SPEC_VERSION), level, modes. The cross-impl differ must skip
   META, or the spec must pin the exact content. **[cross-impl]**

4. **TOOLING-SPEC 3.2 — cycle stamping of records.** Chosen: EXEC/TRAP
   records carry the cycle value *before* that unit's increment (an
   instruction executing "at cycle N" is stamped N; delivery stamped with
   the cycle at which it begins). MEMW/MEMR carry the executing
   instruction's cycle. **[cross-impl]**

5. **TOOLING-SPEC 3.2 — wb/flags for discarded writes.** Writes to r31
   and predicate writes to p0 are architecturally discarded. Chosen:
   flags wrote-dst / wrote-pred are 0 and wb/pred_wb are 0 for them.
   ~~Also: wrote-pred + pred_wb are used only for compare/FCMP predicate
   writes; PWR (which writes p1–p7 wholesale) sets neither.~~
   *Revised (iteration 2):* superseded by the toolchain's SPEC-ISSUES
   reading 1, marked "emulators must match": `pred_wb` is the **full
   8-bit predicate file after the write** (bit i = P[i], so bit 0 is
   always 1), valid whenever flags bit 2 is set — and PWR sets bit 2
   with the new file. trace-q's `reg pN` reconstruction depends on this.
   The p0-discard part stands: a compare targeting p0 writes nothing,
   sets no flag. **[cross-impl]**

6. **ISA-SPEC 7.2 — trace record on triple fault.** "No state is
   written"; chosen: the triple fault emits no TRAP record (nothing was
   delivered) — the machine just halts. **[cross-impl]**

7. **ISA-SPEC 7.6 / CLI contract — WFI deadlock "halts", triple fault
   "halts".** Chosen: both terminate exactly like HALT: print
   `HALT r0=…`, exit 0. If they should be distinguishable at the CLI, the
   contract needs a word for it. **[cross-impl]**

8. **PLATFORM-SPEC 1 — physical access outside RAM and every device
   window.** Unspecified. Chosen: trap DEVERR with baddr = the effective
   (virtual) address, for loads, stores, atomics, and fetch (loud
   failure, and DEVERR's "offending address" wording fits best).
   Alternatives (reads-as-zero, PF) would diverge. **[cross-impl]**

9. **ISA-SPEC 3.3 — mod kind 0 with nonzero amount.** "none (amount must
   be 0)" — behavior on violation unspecified. Chosen: trap ILLEGAL.
   **[cross-impl]** (only for deliberately malformed words / fuzz).

10. **ISA-SPEC 5.1 — signed division rounding.** Not stated. Chosen:
    truncation toward zero, remainder takes the dividend's sign (C /
    RISC-V convention); consistent with "MIN_w / -1" being the only
    listed overflow.

11. **ISA-SPEC 2.3 — "unused high bits … must be written as zero";
    behavior on nonzero write unspecified.** Chosen: hardware masks:
    status stores only its defined bits (6:0), fcsr bits 7:0; all other
    sregs store the full 128 bits written. No trap.

12. **ISA-SPEC 7.4 — IRET bank selection at TL=3.** TL=3 is reachable
    only by MTSR-writing status.TL. Spec says "bank 1 if TL = 2, else
    bank 0". Chosen: bank 1 if TL >= 2. Delivery at TL >= 2 (incl. 3)
    triple-faults.

13. **ISA-SPEC 8.2 — malformed-node checks performed.** Chosen: fault
    PF_* on: ptbase/child not 64-byte aligned; header reserved bytes
    (40..63) nonzero; shift not a multiple of 8 or > 104; leaf reserved
    bits 15:6 nonzero; type 3; leaf at shift != 0; node outside RAM or
    overlapping a device window; walk deeper than 15 nodes (cycle
    guard — the spec has no termination guarantee for cyclic tables).
    **[cross-impl]** (which checks run, and their order, affect which
    accesses fault).

14. **ISA-SPEC 3 — fetch of a misaligned pc** (reachable via IRET with a
    misaligned epc, or vbase/dfbase). Not specified. Chosen: UNALIGNED
    with baddr = pc, checked before translation. **[cross-impl]**

15. **ISA-SPEC 2.3 — user-mode MFSR/MTSR of an unlisted index:** ILLEGAL
    (unlisted) or PRIV (user)? Chosen: ILLEGAL wins — "access to
    unlisted indices traps ILLEGAL" is unconditional; the priv check
    applies to listed indices only.

16. **ISA-SPEC 10.4 — FCVTFF with equal source and dest formats.**
    "FP -> FP (32 <-> 64)" — same-format not listed. Chosen: trap
    ILLEGAL (an "illegal format combination").

17. **ISA-SPEC 10.3 — which operations "round" for the reserved-rm
    trap.** Chosen: the ops that consult fcsr's rounding mode: FADD,
    FSUB, FMUL, FDIV, FSQRT, FMADD, FCVTIF, FCVTUIF, FCVTFF. FCVTFI/
    FCVTFIU (always RTZ, fcsr-independent), FMIN/FMAX, and FCMP* do not
    trap on a reserved rm. **[cross-impl]**

18. **ISA-SPEC 10.4 — NX on inexact in-range FCVT F→I.** Spec only
    mentions NV. Chosen: IEEE behavior — in-range inexact conversions
    raise NX; saturating/NaN cases raise NV only.

19. **ISA-SPEC 10 — FP details the spec is silent on**, chosen per IEEE
    754-2019 + RISC-V conventions: NV on any sNaN operand; FMADD raises
    NV for 0×inf even when the addend is a quiet NaN; underflow flag
    uses tininess-after-rounding (result subnormal-or-zero and inexact);
    FCMPEQ never raises NV even for sNaN operands (spec's "FCMPEQ does
    not" read as unconditional).

20. **ISA-SPEC 9.2 / check-devorder — store-queue model details.**
    Chosen: ordinary stores enter a depth-N queue (oldest commits on
    overflow); a device store drains the whole queue first, then hits
    the device; IFENCE and HALT drain; the processor's own loads,
    fetches, atomics, and page-table walks read through the queue
    (snoop), preserving single-CPU program order. MEMW trace records are
    emitted at execution time, not commit time, so traces match
    non-check-mode runs. **[cross-impl]** (only in check mode).

21. **ISA-SPEC 7.6 — WFI cycle accounting.** Chosen: WFI retires
    normally (+1 cycle), then, if nothing is pending, cycle jumps
    directly to the earliest cycle at which an interrupt condition
    becomes true (timecmp value, or the next event's cycle). Delivery
    then costs its usual +1. **[cross-impl]**

22. **PLATFORM/TOOLING — replay event application point.** Chosen: an
    EVENT with cycle C is applied (device queue fed, EVENT record
    re-emitted with cycle C) at the first between-instruction point
    where machine cycle >= C, before interrupt recognition at that
    point. **[cross-impl]** (moot until devices exist).
