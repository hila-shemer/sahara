# Conformance delta — new test obligations from the devspec documents

Companion to CONFORMANCE.md (frozen; not modified). Each devspec document
ends with a numbered Conformance-requirements section; the integration
pass verified all six are numbered, testable as stated, and — modulo the
deliberate per-device instantiations listed at the end — non-duplicative.
This file maps them onto CONFORMANCE.md's group structure: additions to
existing groups first, then proposed new groups for surfaces
CONFORMANCE.md does not cover (boot protocol, trace format/tools,
assembler).

## Additions to C7 — memory and devices

The C7 outline ("device ordering rules, device read side effects,
unsupported access size traps DEVERR") is instantiated per device:

| source | requirements | one-line scope |
|---|---|---|
| display.md §9 | D-01 … D-21 | register access matrix incl. wrong-direction/size DEVERR, pixel-buffer memory semantics, XRGB8888 extraction, PRESENT snapshot/ordering, resize/ack state machine, reserved-window inertness |
| input.md §7 | INPUT-01 … INPUT-21, INPUT-23 | DATA/STATUS pop semantics, empty-read sentinel, size/write/offset DEVERR, HID subset closure, alternation, no-repeat, mouse clamping/emission, 256-deep drop-newest overflow, EXTINT by draining, device-read ordering |
| nic.md §8 | NIC-C-01 … NIC-C-30 | register/DEVERR catalog E1–E7 with precedence, FCS/padding rules, mailbox FIFO + 64-frame overflow, TX-during-RX, and the full translator decision tree (ARP, DHCP, DNS, UDP/TCP NAT, ICMP, exclusions) against byte-exact vectors |
| rng.md §10 | RNG-01 … RNG-21 | register/DEVERR catalog E1–E6 with the nic.md precedence chain (empty pop E6 — no sentinel), 256-word FIFO with truncate-to-fit acceptance and boundary visibility, normative SplitMix64 PRNG mode (guest-selected, mode/seed/queue independence), IE-qualified EXTINT level, WFI wake at exactly the event cycle |

Existing C7 tests are unaffected; the store-queue check mode and
doorbell-after-stores tests gain concrete fixtures (nic.md NIC-C-15,
display.md D-13).

## Additions to Reference-implementation-only checks

Trace/replay obligations bind the reference emulator, not the ISA:

| source | requirements | scope |
|---|---|---|
| display.md | D-22, D-23 | replay reproduces register reads and (cycle, frame snapshot) sequence; geometry-invariants across resize |
| input.md | INPUT-22 | replay reproduces DATA/STATUS values with host input untouched |
| nic.md | NIC-C-31 … NIC-C-36 | one EVENT per exposed frame, causal cycle ordering, boundary-effect atomicity (ties into C3's interrupt-atomicity test), byte-identical headless runs, replay isolation from the host network, WFI wake at event cycle |
| rng.md | RNG-R1 … RNG-R4 | recorded EVENT payloads are exactly the accepted-word prefixes (zero-accepted records nothing); replay reproduces every DATA/STATUS/CTRL read and every EVENT record byte-identically with the host entropy source untouched, in either mode |
| boot.md | BOOT-16 | table bytes a pure function of emulator configuration |
| trace.md | T-17 … T-20 | byte-identical invocations, replay byte-identity at level, no host consultation, META validation refusal |

## New group C9-B — boot protocol and device table (proposed by boot.md)

BOOT-1 … BOOT-17 (boot.md §9), each tagged emulator (E), guest (G), or
both: reset-state exactness, one-time table write, loader overlap
rejection, table structural invariants, u128-field alignment behavior,
version/magic refusal, unknown-type skip, count-driven parsing, MAC
packing, hole-access DEVERR, INVTP-before-MMU_EN ordering (hooks into
C2's check mode). Vectors: boot.md V1–V9 (byte-exact reference table
included).

## New group C10-T — trace format, replay, and trace-q (trace.md)

T-01 … T-16 (format and stream invariants: META catalog, framing,
cycle stamping, emission order, EVENT payload correctness per device) and
T-21 … T-28 (reader/tool behavior: torn-tail tolerance, malformation
rejection, exit codes, output grammar, .sym resolution, reg
reconstruction, diverge, disassembly canonical form). Vectors: trace.md
TV-1 … TV-10, including a complete 449-byte level-1 trace and 12
byte-exact trace-q command/stdout/exit fixtures.

Note: T-05/T-06 encode the "trapping instruction does not retire" reading
recorded as SPEC-ISSUES.md #17; if Hila rules the other way, these two
tests and trace.md §3.2–§3.3 change together.

## New group C11-A — assembler (asm.md)

ASM-1 … ASM-22 (asm.md §11): 60 source↔hex encodings (T1, verified
against the frozen encoding.py at integration — sample re-verified
independently), li chain minimality (T2), la relaxation (T3), a complete
program → byte-exact .img/.sym (T4), the closed error catalog E001–E049
with per-code trigger vectors (T5), determinism, case rules, and
encoding.py-as-sole-source (ASM-19).

## Deliberate instantiations (not duplicates)

These appear in several documents because each instantiates a frozen rule
for its own device; the suite should implement them as one parameterized
test each where practical:

- **Atomics to device space trap DEVERR** (C3/C7 already): D-06,
  INPUT-07, NIC-C-09, RNG-08.
- **Predicated-false accesses cannot fault** (C1 already): D-15,
  INPUT-08, NIC-C-10 (second clause), BOOT-15 (predicated case),
  RNG-10 (which additionally pins "no PRNG-state advance").
- **Non-64-bit register access traps DEVERR** (C7 already): D-02,
  INPUT-04, NIC-C-03, RNG-05.
- **Event visibility at the first boundary with cycle ≥ C**: INPUT-21 and
  NIC-C-33 (same rule, two devices), RNG-18; trace-side T-04/T-09 check
  the record ordering it implies.
- **EXTINT level-triggering per device** (PLATFORM §3): D-19, INPUT-20,
  NIC-C-19, RNG-20 (the one IE-qualified instance: reset-off, so a
  type-7-unaware kernel never sees it).
