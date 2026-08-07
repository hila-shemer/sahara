# Issues raised against the frozen specs

Collected by the integration pass from the six devspec writers plus one
issue found during integration. Format per issue: frozen file + section,
the problem, and the conservative reading the devspec documents use. **No
frozen file was modified**; these are for Hila to resolve. Where a frozen
spec is later amended, the conservative readings below are the devspec
behavior to reconcile against.

## PLATFORM-SPEC.md

1. **§1 (memory map) — RAM region 0 vs device windows.** "0x0 .. ram_len,
   default 256 MB" would span [0, 0x1000_0000) and overlap the device
   windows at 0x0F00_0000–0x0F06_0000.
   *Conservative reading (boot.md §3.4/§5):* declared RAM never overlaps
   device space; the reference table declares region 0 as
   [0, 0x0F00_0000) (240 MB), "256 MB" read as the address budget below
   the pixel buffer; [0x0F06_0000, 0x1000_0000) is an undeclared hole.

2. **§1/§7 — instruction fetch from device space undefined.** Nothing
   states what a fetch from a device window does (platform-wide, raised
   from the NIC side).
   *Conservative (loud) reading (nic.md §5.2):* fetch from the NIC window
   traps DEVERR. Needs a platform-level ruling covering all windows.

3. **§2 (device table) — "naturally aligned" unsatisfiable for u128
   fields.** The first RAM region's `base` is at table offset 40 and a
   device record's `base` at record offset 8 — 8-aligned, not 16-aligned,
   so LD128 on them traps UNALIGNED.
   *Conservative reading (boot.md §3.2, BOOT-8, vector V6):* the stated
   offsets are normative and exact; u128 fields are guaranteed only
   8-byte alignment; guests read them as two u64 loads.

4. **§2/§7 — MAC byte order unspecified.** Neither the NIC MAC register
   value nor device-table params[0] has a defined byte order.
   *Conservative reading (boot.md §3.6, owner; nic.md §2.5 restates):*
   the six wire-order octets little-endian into bits 47:0
   (52:54:00:12:34:56 → 0x0000_5634_1200_5452).

5. **§4 (display) — the buffer bound is stated over the wrong product.**
   "WIDTH*STRIDE never exceeds the window size" — but a frame occupies
   HEIGHT*STRIDE bytes (row start = buffer + y*STRIDE), so the stated
   product does not bound the buffer.
   *Conservative reading (display.md §3.4, D-10, vector V6):* require
   BOTH WIDTH*STRIDE ≤ window AND HEIGHT*STRIDE ≤ window.

6. **§5 (keyboard) — queue depth "at least 256" is guest-observable.**
   The overflow point (STATUS ceiling, which event gets dropped) is
   implementation-defined under "at least", breaking cross-implementation
   determinism.
   *Conservative reading (input.md §4.1):* reference platform depth fixed
   at exactly 256 for both devices.

7. **§5/§6 — stores to the keyboard/mouse windows and loads from offsets
   other than 0 and 8 unspecified.**
   *Conservative (loud) reading (input.md §1 rules 2–3):* all such
   accesses trap DEVERR with baddr = the accessed address.

8. **§5 — overflow drops must be "recorded in the event trace" but no
   mechanism is given.**
   *Conservative reading (trace.md §4.1/§4.2, as EVENT-payload owner):* a
   dropped-on-arrival flag byte in keyboard/mouse EVENT payloads,
   recomputed and cross-checked at replay.

9. **§6 (mouse) — 16-bit x/y fields vs unbounded display modes.** Nothing
   bounds display modes to 65535 pixels, so clamping "within the current
   display mode" is unrepresentable for larger modes.
   *Conservative reading (input.md §3.3):* clamp additionally to 65535;
   display.md deliberately bounds mode dimensions only to 32 bits (D-10),
   so the 65535 clamp is load-bearing.

## TOOLING-SPEC.md

10. **§2 (.sym) — 'A absolute (non-address constant)' vs "every label
    appears" leaves .equ handling underspecified.** Labels are all
    addresses, so A must target .equ; but an address-valued .equ
    contradicts "non-address".
    *Conservative reading (asm.md §8.3):* labels emit T/D rows;
    CONST-kind .equ emits an A row with its value; ADDR-kind .equ emits
    no row.

11. **§3.2 (trace) — EXEC `pred_wb` u8 content unspecified.** A single
    written bit cannot carry PWR, which writes p1–p7 at once.
    *Conservative reading (trace.md §2.3.1):* pred_wb = the full 8-bit
    predicate file after the write; 0 when wrote-pred = 0.

12. **§3 (replay) — guest-visible emulator configuration is outside both
    the image and the trace.** Replay consumes image + EVENT records, but
    the device table bytes (RAM size, MAC, pixel-buffer window size) and
    the initial display mode are emulator configuration recorded nowhere;
    META's v1 catalog has no config keys. Two replays with different
    configuration would diverge before the first EVENT. *(Found at
    integration.)*
    *Conservative reading (boot.md §5, display.md §1):* the reference
    defaults are pinned normatively (240 MB region 0, MAC
    52:54:00:12:34:56, 16 MB pixel window, 640×480×2560 initial mode);
    replay requires the same configuration as the recording run; a future
    trace-format revision should carry the configuration in META.

13. **§4.4 — `sub rd, imm, rs` listed as an "obvious one-instruction
    expansion" but the ISA has no reverse-subtract.**
    *Conservative reading (asm.md §6.4, E036):* legal only when imm
    evaluates to 0 (alias of neg → `sub rd, zero, rs`); any other imm is
    a fatal error directing to an explicit two-instruction sequence.

14. **§4.4 — `la` fallback range "position-independent within 2^22 *
    range" ambiguous.**
    *Conservative reading (asm.md §6.2, E028):* LAP+ADD reaches exactly
    deltas expressible as the sum of two signed 22-bit immediates,
    [−2^22, 2^22−2] bytes; beyond that is fatal, directing to la.abs.

15. **§4.4 — `li` "minimal chain for the constant's actual width" is
    circular if the constant depends on a label** (chain length changes
    layout changes label values).
    *Conservative reading (asm.md §6.1, E029):* li's operand must be a
    label-free assembly-time constant; addresses use `la` (relaxed,
    sticky promotion to a unique fixed point) or `la.abs` (fixed 6).

16. **§4.5 — "labels only in contexts wide enough to hold them"
    ambiguous** (static context-width rule vs value fit).
    *Conservative reading (asm.md §4.2, E020/E035):* every expression
    result is range-checked against its consuming context; a label-valued
    result is legal wherever its value fits; a non-fitting value is
    fatal, never truncated.

## ISA-SPEC.md

17. **§4 + §7.1/§7.2 — whether a trapping instruction also retires
    (consuming a cycle) in addition to the trap-delivery cycle is not
    explicit.**
    *Conservative reading (trace.md §3.3):* a trapping instruction does
    not retire — only the delivery increments cycle; the trace emits a
    TRAP record and no EXEC record for it (consistent with TOOLING §3.2
    "EXEC for every retired instruction").

18. **§3.3 — mod kind 0 requires "amount must be 0" without stating the
    consequence of violation.**
    *Conservative (loud) reading (trace.md §6.4 rule 7):* such an
    encoding traps ILLEGAL, and trace-q disassembles it as `invalid`.

## Gap noted, not a contradiction

19. **No spec defines physical accesses that hit neither declared RAM nor
    any device window.**
    *Conservative (loud) reading (boot.md §3.4, BOOT-15, vector V9):*
    such accesses (data or fetch) trap DEVERR with baddr = the accessed
    address. This is new normative surface rather than elaboration of an
    existing sentence — flagged specifically for review.
