# Running log: semantics invented beyond the frozen decisions

Kept as required by section 3 of the brief. Each entry: what was unspecified,
what I chose, why. "Arbitrary" is stated where true. This feeds CONSTRAINTS.md
section 2.

1. **Predicate register file size: 8, p0 hardwired true.** Frozen text says
   "separate predicate registers" with a selector + polarity bit but not how
   many. 4-bit pred field = 3-bit selector + 1 polarity → 8 regs. p0 reads as
   always-true so an unpredicated instruction is (p0, positive) = pred field 0;
   writes to p0 are ignored. Arbitrary but forced to a power of 2 by the field.

2. **Register roles.** Frozen: 32 regs, ~16 caller / 12 callee / 4 special.
   Chose: r0-r15 caller-saved (arguments passed in r0-r15, return in r0),
   r16-r27 callee-saved, specials = sp(r28), ra(r29), k0 kernel scratch(r30),
   zero(r31). zero-as-GPR chosen because a hardwired zero source makes mov/nop/
   single-operand patterns free in a single-format ISA. ra is a GPR so JAL just
   writes it (dst field), not a hidden special. Arbitrary numbering.

3. **I-flag in opcode LSB.** "One format" fixes field positions but not how an
   instruction says "src2 is the immediate". Chose: opcode LSB = I-flag, so
   every major op has a register form and an imm form at adjacent opcodes.
   Decode stays shifts-and-masks; compiler has one rule, not per-op tables.

4. **mod field layout: 2-bit kind (none/shl/sxt/zxt) + amount.** Amount is a
   shift count for shl, a bit-width for sxt/zxt. With MOD_BITS=8 the amount is
   6 bits (shifts 0-63). Shifts >=64 must use the SHL instruction proper.

5. **Special registers via MFSR/MTSR with the sreg index in imm.** status,
   epc, cause, baddr, vbase, ptbase, cycle, timecmp, scratch0/1.

6. **Two kernel scratch sregs (scratch0/1) + k0.** A trap handler cannot save
   any GPR without first having a free GPR. One reserved GPR (k0) plus two
   MTSR-reachable scratch sregs is the minimum that felt workable. This is a
   real discovery candidate for the doc.

7. **Trap model (invented wholesale).** On trap/interrupt: epc <- pc of the
   faulting/next instruction, cause <- code, baddr <- faulting VA (faults
   only), status.PIE <- status.IE, status.IE <- 0, pc <- vbase (single vector,
   software dispatches on cause). IRET: pc <- epc, IE <- PIE. One instruction
   return. Interrupts are checked between instructions only (they are precise
   by construction).

8. **Cause codes.** timer=0 kbd=1 pf_load=2 pf_store=3 pf_fetch=4 illegal=5
   unaligned=6. Arbitrary.

9. **Alignment: natural alignment required, unaligned access traps.** The
   frozen list is silent. Trapping chosen because it is the smallest emulator
   and surfaces compiler bugs loudly.

10. **Branch displacement counts instructions (8-byte units), sign-extended;
    JALR target is a byte address in a register and must be 8-aligned (else
    illegal trap).** Frozen text fixed the units for displacement only.

11. **CMP* writes a predicate register selected by the low 3 bits of the dst
    field.** The dst field is reused as a predicate index; no pred-to-GPR move
    exists (not needed by the slice; noted as an open question).

12. **Loads: sized load with explicit zero/sign extension to 128 bits
    (LD8U/8S/.../LD128); addr = src1 + mod(src2) + imm.** Stores take data in
    src3 (this is what three sources buy for stores) with the same addressing.

13. **LDI/SHORI constant synthesis.** LDI dst=sext(imm); SHORI dst=(src1 <<
    IMM_BITS) | zext(imm). SHORI's shift tracks the configured immediate
    width, so constant-synthesis sequence length depends on the encoding
    config (measured in the experiments).

14. **STATUS bits: IE=bit0, PIE=bit1, MMU_EN=bit2.** No user/kernel mode in
    the slice at all; everything runs privileged. Real design needs a mode
    bit and mode-switch semantics — flagged in the doc.

15. **Page-table build is "firmware".** The emulator builds the radix tree in
    physical memory from --map va:pa:len flags before boot, sets ptbase, and
    boot code enables MMU_EN then issues INVTP. Runtime remap is not
    exercised by the slice (noted honestly in the doc).

16. **1 instruction = 1 cycle of virtual time**; page-walk memory accesses are
    counted in stats but do not add cycles. Determinism only needs a
    monotonic cycle count; costs are not the spike's question.

17. **Memory ops use src2(mod) AND imm simultaneously; their I-flag is
    ignored.** addr = src1 + mod(src2) + sext(imm). The I-flag convention
    ("imm replaces src2") breaks down for loads/stores, which want both an
    index and a displacement. Real spec should define I=0 for memory ops.

18. **Divide by zero returns all-ones (unsigned) / leaves dividend (rem);
    no trap.** Arbitrary, RISC-V-style. Avoids inventing another trap cause.

19. **int (64-bit) values live sign-extended in 128-bit registers; ld64s
    keeps them canonical; the compiler never re-canonicalizes after
    arithmetic.** Latent-overflow bug class accepted for the slice; a real
    compiler needs a stated canonical form rule.

20. **Predicate registers cannot be saved or restored** — there is no
    pred->GPR path in the ISA as built. The trap handler simply clobbers p7
    and hopes. This is a real hole; see CONSTRAINTS.md.

21. **Weak-store experiment semantics** (emulator-only, not proposed
    architecture): normal stores delayed 64 cycles in a FIFO; loads drain the
    FIFO; MMIO store either drains first (mode 1) or bypasses (mode 2).
    Exists solely to make the MMIO-ordering question observable.
