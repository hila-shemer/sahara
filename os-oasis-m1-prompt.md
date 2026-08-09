# Work order: SABI v0 + Oasis — OS milestone 1

Branch: `os` (worktree of this repo). Read the frozen root specs
(ISA-SPEC.md, PLATFORM-SPEC.md, TOOLING-SPEC.md, CONFORMANCE.md,
CONSTRAINTS.md) and devspec/boot.md, display.md, input.md, trace.md first;
they govern. The design below is FINAL — decisions marked binding are not
yours to reopen; ambiguities you *discover* go to SPEC-ISSUES.md per house
protocol, they do not license improvisation.

This milestone has two deliverables of equal rank, in dependency order:

1. **`os/abi/sabi-v0.md`** — the machine-wide software conventions spec.
   No ABI of any kind exists in this repo today. Every future Sahara OS,
   library, loader, and compiler builds against this document; the kernel
   below is merely its first conforming client. Write it FIRST.
2. **Oasis** (`os/oasis/`) — the first kernel: boots per devspec/boot.md,
   runs a text console + keyboard shell over SYSCALL, tested headlessly.

The spec proves itself by having a conforming client; the kernel proves
itself by obeying the spec. Divergence between the two is a bug in one of
them, never something to paper over.

## Why this exists

Two emulators are conformant and byte-identical under difftest; the
toolchain (asm, trace-q, EVENT replay) is landed. The machine works but
nothing runs on it, and nothing CAN be written for it repeatably because
no calling convention, stack discipline, syscall mechanism, or image
layout convention exists anywhere. The owner's directives: the OS stream
is orthogonal to the (separate) interactive front-end stream; the OS must
be fully testable headless — event feeds in, trace assertions out — and
must never know whether a window exists. Milestone 1 is hand-written
Sahara assembly; compilers are future work.

## Which emulator (binding)

Test against **both, asymmetrically**:

- **emu-c is the primary harness.** `emu-c/build.sh` produces
  `emu-c/bazel-bin/sahara-emu`; it is the reference implementation, has
  the full `--replay` device phase, and is fast enough to run every OS
  test with determinism double-runs. `EMU` in your test script defaults
  to it.
- **emu-py runs a smoke leg only** (`emu-py/sahara-emu-py`, ~50 KIPS).
  One boot-to-shell-to-halt feed, gated behind `EMU_PY=1` in the full
  run. Keep boot under ~2M cycles so this leg stays under a minute.

Rationale: the emulators are already proven equivalent under the
conformance difftest; the OS gains nothing from running its whole suite
twice, but a cross-emulator smoke test catches "works only on emu-c's
interpretation" drift for free. Do not read either emulator's sources to
learn machine behavior — the specs govern; if an emulator disagrees with
a spec, that is a SPEC-ISSUES.md entry, not a workaround.

## Facts you build on (spec references, not prose — go read them)

Boot hand-off (devspec/boot.md §2):
- Reset: pc = 0x1000 physical, S=1, IE=PIE=MMU_EN=PS=0, TL=0, all other
  sregs and r0–r30 zero, vbase = dfbase = 0, timecmp = 0 (timer never
  pending). Pre-vector faults triple-fault loudly (boot.md §2.2).
- Device table at PA 0x0800, window [0x0800, 0x1000): magic
  0x5450_4152_4148_4153 ("SAHARAPT"), version 1, header 40 B, RAM region
  records 32 B, device records 64 B; parse by counts (boot.md §3.3–3.5).
  Validate magic/version/size; each failure is terminal — halt loud with
  a distinct code (boot.md §3.3).
- u128 table fields are only 8-aligned: read them as paired `ldz.64`
  (low, high), never LD128 (boot.md §3.2 — LD128 there traps UNALIGNED).
- Derive EVERYTHING from the table: RAM size/top, device bases, pixel
  buffer PA (display record params[0]) and size (params[1]). The only
  hardcodable address is 0x0800 itself (boot.md §2.3). Type codes:
  1 display, 2 keyboard, 3 mouse, 4 nic; use the first record of a type,
  skip unknown types whole (boot.md §3.5, §4.2).

Traps and interrupts (ISA-SPEC §7):
- Causes you handle: 0 TIMER, 1 EXTINT, 10 SYSCALL (§7.1). Delivery:
  TL += 1, bank TL−1 gets epc/cause/baddr, PIE←IE, IE←0, PS←S, S←1,
  pc ← vbase (TL=1) or dfbase (TL=2); costs one cycle (§7.2).
- SYSCALL resumes via epc += 8 then IRET (§7.1, §7.4).
- Timer pending while cycle ≥ timecmp and timecmp ≠ 0; EXTINT is the
  level-triggered OR of all device queues being non-empty; priority
  timer-then-external (§7.5).
- WFI: stalls and jumps `cycle` to the next pending-interrupt cycle; if
  no future event can pend, the machine HALTS — deadlock is loud (§7.6).
- Trap-entry contract: r30 (k0) plus scratch0/scratch1 (sregs 10/11) are
  the free-register bootstrap; PRD/PWR save/restore the predicate file;
  bank-0 sregs and status go to memory before TL is lowered (§12, §7.3).

Input MMIO (devspec/input.md):
- Keyboard type 2, mouse type 3; identical windows: DATA (offset 0, read
  pops, all-ones sentinel when empty), STATUS (offset 8, depth 0–256).
  64-bit loads ONLY; any store, other offset, other size, or atomic in
  the window traps DEVERR (§1). Canonical drain loop in §5 (lds.64 /
  cmpeq p, −1 / (p) b done — lds sign-extends the sentinel to −1).
- Event word: bits 31:0 = HID usage ID (closed 103-ID set, §2.2), bit 32
  = 1 press / 0 release, bits 63:33 zero (§2.1). Modifiers are ordinary
  press/release keys — track shift yourself (§2.3). No auto-repeat in
  hardware (§2.4). Queue depth 256, overflow drops newest, press/release
  alternation still holds per key (§4.2, §2.6).

Display MMIO (devspec/display.md):
- Control window (64-bit regs, exact-size access, wrong direction/size/
  offset traps DEVERR — §2): 0x00 PRESENT (W), 0x08 WIDTH (R), 0x10
  HEIGHT (R), 0x18 STRIDE (R), 0x28 IRQ_STATUS (R), 0x30 IRQ_ACK (W).
- pixel_pa(x,y) = pixbuf_base + y·STRIDE + 4·x, XRGB8888 little-endian
  (§3.2–3.3). READ the stride; never assume 2560. Frame becomes visible
  only on PRESENT (§5). Resize sets IRQ_STATUS bit 0; ack via IRQ_ACK
  bit 0, then re-read W/H/S (§6).

Trace, replay, toolchain:
- Keyboard EVENT payload trace.md §4.1 (9 bytes), resize §4.4 (32 bytes);
  replay semantics §5; pixel-buffer stores appear as DEVW records at
  trace level 1 (§2.3.6) — your framebuffer checker depends on that.
- Emulator CLI (frozen, tests/run-tests.sh header): `<emu> IMAGE
  [--replay f] [--trace f --trace-level N] [--maxcycles N] [--ram BYTES]
  [--check-invtp]`; HALT prints `HALT r0=<32 hex digits>`, exit 0.
- Assembler: `python3 asm/asm.py -o OUT.img IN1.s IN2.s ...` — no linker,
  files concatenate in CLI order, `.sym` sidecar emitted alongside
  (TOOLING-SPEC §1–2). Directives: .byte/.quad/.ascii/.asciiz/.space/
  .align. NO .incbin, NO macros, NO .include; expressions are + − * only.

## SABI v0 — deliverable 1 (binding content)

One shared doc at `os/abi/sabi-v0.md`, outside any OS directory: register
roles, stack discipline, section order, and the syscall *mechanism* are
properties of the machine, not of one OS. Per-OS personality (the syscall
number table) lives in `os/<name>/doc/syscalls.md`. Forks are explicit
(`os/abi/sabi-v1-<name>.md`); silent divergence is banned. Flag the doc
for owner sign-off before any second consumer builds on it.

- **Register roles / calling convention: adopt ISA-SPEC §12 verbatim, by
  reference.** Add nothing silently. r28 sp (16-aligned, grows down),
  r29 ra, r30 k0, r31 zero; args r0–r7, return r0 (r0:r1 for pairs);
  r16–r27 callee-saved; predicates caller-saved; no frame pointer; args
  beyond 8 in 16-byte stack slots at [sp+0].
- **Frames.** Prologue `add sp, sp, -N` (N a multiple of 16), saves via
  `st.128` in 16-byte slots (ST128 needs 16-alignment; the slot rule
  guarantees it). ra in the TOP slot [sp+N−16], callee-saved registers
  downward; leaf functions may be frameless.
- **gp.** r27 = gp **inside kernel code only**, set once at boot to the
  kernel globals block (table-derived device bases, console state), so
  MMIO bases are one `ldz.64 rX, [gp+off]`. The user-facing ABI keeps
  r27 as plain callee-saved.
- **Syscall convention.** SYSCALL instruction, cause 10. Number in
  **r7**, arguments r0–r5, r6 reserved; return in r0: result ≥ 0 or
  negated errno in [−255,−1], canonical sign-extended 128-bit form
  (ISA §3.4). Errno v0: 1 EINVAL, 2 ENOSYS, 3 EFAULT; unknown number
  returns −ENOSYS. Clobbers = function call (r16–r28 preserved).
  Numbering is per-OS; the mechanism is SABI.
- **Trap-entry contract** restated from ISA §12, plus ONE canonical
  trap-frame save/restore block as normative reference text — there is
  no macro processor, so copy-paste instances must match it exactly.
- **Memory layout.** [0, 0x800) untouched (zero decodes ILLEGAL — a
  deliberate tripwire); [0x800, 0x1000) device table, read-only by
  convention; kernel loads flat at 0x1000. **Identity axiom: kernel VA =
  PA whether or not translation is enabled.** M1 runs MMU off; a later
  milestone enabling an identity map changes nothing for conforming
  code. Kernel/boot stack: top of RAM region 0 AS READ FROM THE TABLE
  (reference 0x0F00_0000, never hardcoded); top 64 KB reserved as kernel
  stack. Heap grows UP from `_end` (direction frozen; no allocator in
  M1).
- **Image conventions.** Physical format stays flat SAHIMG01 + `.sym`.
  Logical section order fixed by source concatenation: text | rodata |
  data | bss, each `.align 16`, bss as `.space` at the tail (the
  assembler's trailing-zero trim keeps images small). Boundary labels
  `__etext`, `__erodata`, `__edata`, `_end`; programs reference section
  boundaries only via these labels.
- **Frozen in v0:** everything above. **Explicitly deferred (specify the
  deferral, implement nothing):** object/executable format and loader,
  relocation/PIC, dynamic anything, user-mode conventions, allocator
  API, FP ABI beyond "fcsr caller-saved", the libc surface.

## Oasis M1 — deliverable 2 (binding scope)

Kernel behavior:
- Boot per boot.md: validate magic/version/size, halt loud with a
  distinct r0 code per failure class; parse by counts; paired ldz.64 for
  u128 fields; derive RAM top, device bases, pixbuf PA from the table.
- Set sp (RAM top) and gp (globals block); install vbase, and a dfbase
  stub that stores both banks and halts. Store ordered boot-stage codes
  (u64) to a labeled bss word `dbg_status` — table-ok → vectors-on →
  irq-on → shell-ready — the tests assert this sequence via the `.sym`
  sidecar and trace-q. Never squat on the conformance suite's 0x700
  idiom.
- Arm the periodic timer: TICK = 100,000 cycles, a named constant,
  re-armed in the handler (see tests/c3_irq_dev.s for the arm idiom),
  maintaining a tick counter. Enable IE.
- 80×30 text console: 8×16 font, XRGB8888, stride from the register;
  `st.128` writes 4 pixels per store; PRESENT after each visible update;
  scroll by copy, not full redraw.
- EXTINT handler: drain keyboard into a 256-byte ASCII ring (press
  events only; HID→ASCII via generated tables, shift tracked from
  modifier press/release), **drain and discard mouse** (level-triggered
  EXTINT: an undrained mouse queue holds the line asserted forever — a
  hang, not a nicety), ack display IRQ_STATUS then re-read W/H/S with
  best-effort re-layout. Handler is predicate-clean via PRD/PWR.
- Idle is WFI, never polling — polling would bloat every trace with
  millions of dead EXEC records; WFI jumps to the next EVENT cycle under
  replay. The always-armed timer guarantees WFI always has a future
  wake.
- Line-edit echo shell (printables, backspace, enter) with builtins
  `help`, `echo <text>`, `uptime` (tick count + `mfsr cycle` — proves
  the timer), `halt` → exit(0x600D) → `HALT r0=…600d` (the suite's PASS
  idiom, our own value space). Unknown commands print an error line.
- The shell calls its own kernel through SYSCALL — the contract is
  exercised from day one. Three syscalls, numbers in
  `os/oasis/doc/syscalls.md`: 0 `write(fd,buf,len)` (fd 0 = console),
  1 `read(fd,buf,len)` (blocks via WFI until ≥1 byte in the ring,
  returns count ≥ 1 — line editing stays in the shell), 2 `exit(code)`.

NOT in scope: MMU/page tables/user mode, processes/scheduler, NIC, mouse
semantics beyond drain-discard, storage/FS (none exists by design),
allocator, libc, cursor blink, auto-repeat, Unicode (ASCII 0x20–0x7E
only), and ANY reference to the front-end stream.

Embedded data — route around the assembler, never extend it:
- `os/oasis/gen/genfont.py`: public-domain 8×16 bitmap for ASCII
  0x20–0x7E as Python data, emits `font.s` (label `font8x16`,
  `.align 16`, 16 `.byte` rows per glyph). The module is IMPORTED by the
  test checker so renderer and checker share one truth.
- `os/oasis/gen/genkeymap.py`: emits `keymap.s`, two 256-byte HID→ASCII
  tables (plain, shifted), packed constants precomputed in Python,
  generator-tested against input.md §2.2's closed set.
- Build = fixed CLI concatenation order (that IS the section
  convention): `defs.s boot.s trap.s kbd.s con.s shell.s sys.s lib.s`
  (text), `font.s keymap.s rodata.s` (rodata), `data.s bss.s`. Symbols
  are global — prefix per file (`con_`, `kbd_`, `sys_`, …) to dodge E031
  collisions. Trap-frame blocks are copy-pasted from SABI's canonical
  block, marker-commented, one instance each.

Directory layout (binding):

    os/abi/sabi-v0.md
    os/oasis/README.md
    os/oasis/doc/syscalls.md
    os/oasis/kernel/*.s          (link order above)
    os/oasis/gen/genfont.py genkeymap.py
    os/oasis/build/              (generated .s + oasis.img/.sym; gitignored)
    os/oasis/tests/run-tests.sh mkfeed.py fbcheck.py feeds/ golden/
    os/oasis/build.sh  os/oasis/run.sh

## Test strategy (mandatory, headless, front-end-free)

All under `os/oasis/tests/`, driven by `os/oasis/tests/run-tests.sh`.
Feed builder `mkfeed.py` imports root `encoding.py` (encoding-as-data
rule), computes the image's sha256, writes META + EVENT `.trc` feeds
(device index of the keyboard record, 9-byte payloads, press + release
per character, ~10,000 cycles apart after a boot margin — echoing a glyph
costs ~32 st.128 + PRESENT plus handler overhead, so 1k-cycle spacing
risks overlap). **Every feed ends with `halt\n`** so WFI never deadlocks
after the last event; `--maxcycles` is the harness backstop.

Run shape: `$EMU build/oasis.img --replay feed.trc --trace out.trc
--trace-level 1 --check-invtp --maxcycles N`.

Assertion layers (all of them — each catches a distinct failure class):
1. Exit contract: stdout exactly `HALT r0=<…600d>`, exit 0; boot-failure
   tests assert their distinct halt codes.
2. Boot-stage word: resolve `dbg_status` from the `.sym` sidecar, use
   trace-q to assert the ordered MEMW sequence, each stage exactly once.
3. Framebuffer from the trace: `fbcheck.py` replays out.trc's
   pixbuf-window DEVW records into a shadow buffer, snapshots at each
   PRESENT (DEVW to control+0x00), text-decodes the glyph grid via the
   imported genfont tables and asserts expected lines (`$ echo hi` /
   `hi`) — primary check; plus ONE golden PPM byte-compare smoke test
   (CONSTRAINTS §5 snapshot-diff doctrine).
4. trace-q gates: zero ILLEGAL/DEVERR/double-fault everywhere; ≥1 TRAP
   cause 1 per keystroke burst; TRAP cause 10 count == expected syscall
   count.

Named hard cases: (a) predicate corruption — keystroke lands between a
cmpeq and its consuming branch (the c3_irq_dev heisenbug); (b) shift
state across a >256-event overflow burst; (c) one short dedicated scroll
test (scroll ≈ 75k DEVW records — every other session stays under one
screen).

Determinism gates: every test runs twice → `cmp` byte-identical traces;
record→replay identity (the produced out.trc re-replays byte-identically
— the live-mode conformance property proven headless before any GUI
exists); the smoke feed runs on both emulators.

## Definition of done

- `os/abi/sabi-v0.md` complete, self-consistent, marked "flagged for
  owner sign-off"; `os/oasis/doc/syscalls.md` written; kernel code
  demonstrably obeys both (spot-check: frame shape, r7 syscall number,
  section labels, no hardcoded device addresses).
- `os/oasis/build.sh` produces `build/oasis.img` + `.sym`
  deterministically (two builds, identical bytes).
- `EMU=emu-c/bazel-bin/sahara-emu os/oasis/tests/run-tests.sh` green end
  to end: exit contract, dbg_status sequence, fbcheck text-decode +
  golden PPM, trace-q gates, hard-case tests, double-run determinism,
  record→replay identity.
- `EMU_PY=1` leg green: the smoke feed on `emu-py/sahara-emu-py`.
- Root `./run_tests.sh` untouched and still green (it is the harness
  contract entry point; you change nothing it depends on).
- `git status` on branch `os` shows zero changes under `tests/`,
  `trace-q/`, root frozen specs, `asm/`, `emu-c/`, `emu-py/`.
- Every ambiguity encountered is a SPEC-ISSUES.md entry (root or
  devspec/, per its conventions), not an inline workaround.
- Commit in small green steps; `hila-voice` skill for commit messages.

## Scope boundaries

- `tests/` and `trace-q/` are TOOLCHAIN-OWNED. Never modify them. If a
  suite or tool bug blocks you, record it in SPEC-ISSUES.md and stop —
  do not patch around it. Put a negative bullet saying exactly this in
  your run-tests.sh header.
- No toolchain changes, period. If asm.py is missing something
  (.incbin, macros, expression power), route around it with a generator
  script that emits `.s` (the tests/gen_*.py idiom) and record the gap
  in SPEC-ISSUES.md as an observation, not a demand.
- No loader, no libc, no allocator in M1 — SABI specifies their
  deferral; nothing implements them.
- The front-end stream is orthogonal: `run.sh` runs headless under
  `$EMU`; the kernel never references, detects, or depends on a window.
- Do not consult emulator sources for machine semantics; specs govern.

## Risks (mitigate, don't relitigate)

1. Scroll trace bloat — copy-scroll, sub-screen test sessions, one
   dedicated scroll test.
2. WFI runaway vs deadlock — halt-terminated feeds, always-armed timer,
   `--maxcycles` backstop, TICK a named constant.
3. Keymap/shift edges — table-driven, generator-tested, overflow-burst
   test.
4. No-macro copy-paste drift — SABI canonical trap-frame block, one
   instance per site, marker comments, reviewed once.
5. SABI decisions harden fast — the sign-off flag is part of the
   deliverable; do not let a second consumer in before it.
6. Accidental toolchain edits — the negative bullet, plus the clean
   `git status` check in the definition of done.

Sizing expectation: ~1,300 lines hand-written assembly, ~1,900 generated
(font + keymap), ~600 lines Python (generators + mkfeed + fbcheck). One
branch, one milestone. If you find yourself far outside this envelope,
stop and reread the scope boundaries before writing more code.
