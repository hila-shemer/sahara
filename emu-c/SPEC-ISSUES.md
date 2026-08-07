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
