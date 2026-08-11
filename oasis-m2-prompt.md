# Work order: Oasis M2 — user mode

Branch: `oasis-m2` (worktree of this repo). Read the frozen root specs
(ISA-SPEC.md — especially §7 traps, §8 MMU, §12 ABI; PLATFORM-SPEC.md;
CONSTRAINTS.md) and devspec/boot.md first; they govern. Then read
**os/abi/sabi-v0.md in full** — it is SIGNED OFF and normative,
especially §1.4 (kernel/user trust boundary), §4 (memory layout,
identity axiom), §5 (trap-entry contract), §7 (deferrals), and the
amendment rules at its end. Then read the Oasis M1 kernel
(os/oasis/kernel/*.s, tests/run-tests.sh) — you are extending it, not
rewriting it.

The design below is FINAL — decisions marked binding are not yours to
reopen; ambiguities you *discover* go to SPEC-ISSUES.md per house
protocol, they do not license improvisation.

This milestone has two deliverables of equal rank, in dependency order:

1. **The SABI v0.1 user-mode amendment**, appended to
   `os/abi/sabi-v0.md` per its own amendment rules, flagged
   **DRAFT — awaiting owner sign-off**. SABI §7 defers every user-mode
   convention; rule 2 of the amendment rules says a deferral is filled
   by a v0.x amendment signed BEFORE consumers build on it. Draft it
   FIRST — it is commit 1 on the branch.
2. **Oasis M2** — MMU on with a kernel identity map, an S/U split, one
   user program embedded in the flat image and entered in U mode,
   syscalls crossing the boundary from U, and clean containment of
   user faults: a faulting user program is killed with a console
   diagnostic and the kernel survives.

## The ordering contract (binding, process)

- Commit 1 on `oasis-m2` is the v0.1 amendment draft. Every kernel
  commit after it develops against the draft *on this branch*.
- The branch **cannot be promoted to main until the owner signs the
  amendment**. The DRAFT flag stays in the document text; flipping it
  to signed, updating the change log, and merging are the owner's
  moves, not yours. Say this in the final commit message and in your
  hand-off summary.
- SABI §1–6 are frozen. You change not one character of them. The
  amendment is appended after the change log as its own section. If
  implementation teaches you the draft is wrong, amend the draft in a
  visible commit — never fork the conventions silently in code.

M2 is the first real test of SABI §1.4 — it is now normative, not
aspirational. Rule 1 (write-before-read k0/scratch) and rule 2 (a trap
arriving with status.PS = 0 must reach a kernel-owned stack/save area
before its first push) are load-bearing in everything below.

## Why this exists

M1 proved the machine runs a kernel: boot, timer, keyboard, console,
SYSCALL shell — all headless, deterministic, replay-identical. But
everything runs in S mode with the MMU off; nothing has ever executed
with status.S = 0, no PERM_* fault has ever fired outside the
conformance suite, and SABI §1.4's trust boundary has no client. M2
makes the privilege boundary real, on the smallest surface that
exercises all of it: one user program, the existing three syscalls,
and fault containment. Processes, scheduling, and per-program address
spaces are M3; the compiler (cc) and NIC streams are parallel and
must not be depended on — the user program is hand-written assembly.

## Which emulator (binding)

Same asymmetric strategy as M1: **emu-c is the primary harness**
(`emu-c/bazel-bin/sahara-emu`; rebuild it in your worktree before
trusting any replay-identity result — a stale binary produces phantom
drift NOTEs); **emu-py runs one smoke leg** gated behind `EMU_PY=1`
(boot → shell → `run` → user echo → exit → halt, kept small).

Do not read either emulator's sources to learn machine behavior. The
specs govern. The MMU implementations have been conformance-tested but
M2 is their first OS client: **if the emulators disagree with ISA §8
or with each other, that is a SPEC-ISSUES.md entry and a full stop for
the affected test — never a workaround, never an emulator patch.**

## Facts you build on (spec references, not prose — go read them)

- ISA §8: 64 KB pages, VPN = VA[127:16]; radix nodes of 4160 bytes,
  64-byte aligned: header (shift u64, prefix u128, prefix_mask u128,
  reserved zero) + 256 × 16-byte entries; leaf legal only at shift 0;
  leaf bits R=4, W=8, X=16, U=32. Walk checks
  `(VPN & prefix_mask) == prefix` then indexes by `(VPN>>shift)&0xFF`.
  Supervisor ignores U but honors R/W/X (no SMAP); user access to a
  U=0 page faults PERM_*.
- ISA §8.6–8.7: the walk never consults asid; INVTP after page-table
  stores and before the first dependent access is mandatory even on
  cache-less implementations (boot.md §6, BOOT-17; the harness runs
  `--check-invtp`).
- ISA §2.4/§7.1: user mode traps PRIV on MFSR/MTSR (except cycle,
  fcsr reads per the sreg table), IRET, INVTP, WFI, HALT. SYSCALL and
  IFENCE are legal from U. Cause 11 = PRIV.
- ISA §7.2: delivery does NOT switch stacks — it only sets PS←S, S←1.
  The PS bit at handler entry is the only record of where the trap
  came from. status bits: IE=1, PIE=2, MMU_EN=4, S=8, PS=16, TL=0x60.
- ISA §7.4: IRET does S←PS, IE←PIE, pc←epc[bank], TL←max(TL−1,0).
  Entering U mode IS an IRET with PS=0 — there is no other door.
- boot.md §6: page tables built, `mtsr ptbase`, `invtp`, then MMU_EN,
  in that order. The identity map makes the transition seamless
  (fetch after the status write translates to the same PA).
- SABI §4.4 (identity axiom): kernel VA = PA whether or not
  translation is on. M2 is the milestone this axiom was written for:
  conforming M1 kernel code needs zero changes when MMU_EN is set.
- SABI §4.5: kernel stack = top 64 KB of RAM region 0, from the table.
- TOOLING-SPEC §1 + devspec/asm.md §7.1: `.org PA` opens a new image
  segment with load_pa = PA; the emulator's loader places every
  segment before reset; segments must not overlap (E042). `la` is
  position-independent within ±4 MB (E028); `la.abs` forces an
  absolute chain — cross-segment references use `la.abs` or `.equ`
  constants.
- Trace: TRAP records carry cause/epc/baddr/tl_after; EXEC carries
  pc. There is no mode bit in the trace — U-mode occupancy is proven
  by pc/epc lying in the user window, via trace-q + the .sym sidecar.

## SABI v0.1 amendment — deliverable 1 (binding content)

Appended to `os/abi/sabi-v0.md` after the change log, as
`## Amendment v0.1 — user-mode conventions (DRAFT — awaiting owner
sign-off)`. It fills the "user-mode conventions" deferral of §7 —
partially, and says exactly which parts. Content, all binding:

1. **Address-space model: one address space, U-bit split.** User code
   runs in the same identity-mapped space as the kernel; the user
   window is user VA = PA; privilege separation is entirely the U bit.
   Kernel pages have U=0 — user loads/stores/fetches of kernel memory
   fault PERM_*. Rationale (state it): one program at a time needs no
   asid, no ptbase switching, no second set of mappings; per-program
   address spaces arrive with processes in a later amendment, and
   nothing in this one obstructs them. `asid` stays 0 throughout.
2. **User window: [0x0200_0000, 0x0300_0000) — UBASE, 16 MB.**
   Exactly one 8-bit VPN chunk (VPN 512–767): one shift-0 node, one
   root entry. Layout inside the window: program image pages from
   UBASE upward, mapped U+R+W+X (no W^X in v0.1 — deferred); the top
   64 KB page [0x02FF_0000, 0x0300_0000) is the user stack, U+R+W;
   every page between image end and stack is UNMAPPED — a wild user
   pointer faults PF_*, loudly. Boot checks (loud halt codes): UBASE ≥
   `_end` rounded up, UBASE + 16 MB ≤ RAM top from the table. The
   kernel heap (§4.6) is now capped at UBASE — direction unchanged,
   ceiling noted; the allocator amendment revisits.
3. **Entry contract.** pc = UBASE (a user program's first byte is its
   entry — no header); sp = 0x0300_0000 (top of stack, 16-aligned);
   r0–r30 = 0, p1–p7 = 0, fcsr = 0 — deterministic entry, no kernel
   state leaks into U mode. **No entry arguments in v0.1** (r0–r7 are
   zero by the rule above); argument passing is defined with
   processes, later. Entered via IRET with PS=0, PIE=1: user code
   runs at TL=0 with interrupts enabled — the timer keeps ticking and
   the keyboard keeps draining while user code runs.
4. **Kernel trap stacks are per-process (OWNER-DECIDED 2026-08-11 —
   state it as such in the draft, not as an open question).** Every
   user program/process has its own kernel-owned trap stack. The
   per-process structure holds its kernel stack pointer; a trap
   arriving with status.PS = 0 loads sp from the *current process's*
   structure before its first push (this mechanizes SABI §1.4 rule
   2), and the interrupted user sp is saved into that structure as
   data. Reference kernel-trap-stack size: 16 KB. M2 instantiates
   exactly one such structure; M3 changes a count, not a design. The
   shared boot/shell kernel stack of §4.5 is NOT a trap stack for
   user-mode traps.
5. **Syscalls from U mode.** Mechanism unchanged (§3). New rule: a
   pointer+length argument passed from user mode must lie entirely
   within the user window, else the syscall returns −EFAULT — the
   errno's first real use. Kernel-mode callers are exempt (trusted).
   Handlers that consume sp (the syscall path) perform the rule-4
   stack switch; handlers that are sp-free (the M1 interrupt path
   with its static save areas) need no switch and must stay sp-free.
6. **User faults.** Any trap with PS=0 and cause ∈ {2..9, 11, 12}
   terminates the user program. What termination means (diagnostic,
   return-to-shell, exit status) is per-OS policy; signal-like
   upcalls remain deferred. Consequences worth spelling out: HALT and
   WFI from user mode are PRIV traps — a user program cannot stop,
   halt, or sleep the machine.
7. **Image embedding.** A user program enters the flat image as an
   additional `.org UBASE` segment of the same assembly unit — the
   user source file(s) go last on the assembler command line and open
   the segment themselves. The loader (TOOLING-SPEC §1) places it
   before reset; there is still no runtime loader (deferral stands).
   One user program per image in v0.1. The image is loaded once at
   reset: re-entering the program does not re-initialize its data —
   re-runnable programs initialize their own state from code; reload
   semantics are deferred with the loader.
8. **Still deferred** (explicit list in the amendment): processes and
   scheduling, per-program address spaces and asid discipline, entry
   arguments, signal-like upcalls, user heap/allocator, W^X.

## Oasis M2 kernel — deliverable 2 (binding scope)

Page tables and MMU (new `kernel/mmu.s`):
- Static node pool in bss: `.align 64`, 18 nodes × 4160 B (~75 KB) —
  1 root (shift 8, prefix 0, prefix_mask = all VPN bits ≥ 16) + up to
  17 shift-0 nodes. Reference-platform contents: chunks 0–14 identity
  RAM S-RWX (U=0); chunk 15 maps only the device-table-derived
  control windows S-RW (display, keyboard, mouse, nic), the
  [0x0F06_0000, 0x1000_0000) hole stays unmapped; chunk 16 maps the
  pixel buffer S-RW from the display record's params. Everything is
  derived from the device table at boot — the loops map what the
  table declares; if the table needs more chunks than the pool holds,
  halt loud with a new distinct code. Chunk 2 is the user window:
  program pages U+R+W+X (image extent from a `__uend` label the user
  segment defines, rounded up to 64 KB), stack page U+R+W, the rest
  invalid.
- Choreography, in boot.s between vectors-on and irq-on: build nodes
  → `mtsr ptbase` → `invtp` → set status.MMU_EN → store the new boot
  stage. Renumber dbg_status stages: 1 table-ok, 2 vectors-on,
  3 mmu-on, 4 irq-on, 5 shell-ready (tests are os-owned; update
  them). No page-table stores after MMU_EN in M2 — the map is
  immutable post-boot, so boot's single INVTP is the only one needed.

Trap path (trap.s changes):
- Dispatch becomes PS-aware. Fault causes {2..9, 11, 12}: PS=1 →
  h_fatal exactly as M1 (a kernel fault is still a loud halt); PS=0 →
  the kill path. SYSCALL: PS=0 → save user sp into the process
  structure, load sp from its kernel-trap-stack pointer, dispatch;
  PS=1 → straight to dispatch on the caller's kernel stack, as M1.
  `sys_ret` re-checks PS and restores the user sp before IRET on the
  user path. The h_irq interrupt path stays static-save-area,
  sp-free — write that as a comment invariant; it is why it needs no
  switch.
- Kill path: record cause/epc/baddr for the diagnostic, set
  status.PS to 1 and epc0 to the kernel resume label, IRET — landing
  in `run_user`'s epilogue in S mode with interrupts live.
- sys_write/sys_read: when the saved PS says the caller was user,
  validate [buf, buf+len) ⊆ user window; −EFAULT otherwise.
- sys_exit: caller PS=1 (the shell's `halt`) → HALT as M1, the
  0x600D contract is untouched. Caller PS=0 → terminate the user
  program with its exit code; the machine does not stop.

Process structure and entry (new `kernel/uproc.s`):
- One per-process structure in bss (offsets in defs.s, `P_` prefix):
  kernel-trap-stack pointer, saved user sp, caller (shell) sp, state,
  exit/kill cause + epc + baddr. One 16 KB kernel trap stack in bss,
  16-aligned. Shaped per-process per the owner ruling: the trap path
  reaches everything through "the current process's structure" (one
  global pointer in M2), never through a global bare stack symbol.
- `run_user`: ordinary SABI frame; saves its sp into the structure;
  zeroes the entry register state per the contract; sets epc0=UBASE,
  PS=0, PIE=1; IRET. The resume label restores sp from the structure
  and returns to the shell with the termination report.
- Shell builtin `run`: enters the embedded user program; on return
  prints one line for a clean exit (includes the exit code) or one
  diagnostic line for a kill (includes at least cause and epc; exact
  text is yours, frozen verbatim in the tests). Store a `dbg_user`
  bss word: 1 written before entry, 2 on clean exit, 3 on kill — the
  tests assert the MEMW sequence via the .sym sidecar.

User programs (new `os/oasis/user/`, assembly only, SABI-conforming):
- `echo.s` — the demo: writes a banner via write(0,…), then loops
  read → write (echo); a line starting with `q` exits(0).
  Re-runnable: initializes all its state from code.
- Test programs, one per containment class: `crash_load.s` (load
  from an unmapped mid-window address → PF_LOAD), `crash_kern.s`
  (load from 0x1000 → PERM_LOAD), `crash_jump.s` (jump out of the
  window → PF_FETCH), `crash_priv.s` (executes HALT → PRIV — proves
  a user program cannot stop the machine), `hostile_sp.s` (sets sp
  to a garbage unaligned value, then makes a write syscall with a
  valid buffer, prints proof it returned, exits — SABI §1.4 rule 2's
  litmus test), `efault.s` (write with buf=0x1000 → expects −EFAULT,
  reports, exits 0).
- build.sh grows an optional argument: user program source and
  output image name; default `user/echo.s` → `build/oasis.img`. The
  suite builds `build/oasis-<name>.img` variants for the crash
  programs. Link order: M1's order, then the user file last (it
  opens the `.org UBASE` segment). Kernel bss stays the kernel
  segment's tail so the trailing-zero trim still applies per segment.

NOT in scope: scheduler, processes beyond the single per-process-
shaped structure, per-program page tables, asid ≠ 0, W^X, user heap,
signal upcalls, loader, allocator, libc, cc output, NIC, any emulator
or toolchain change, any edit to SABI §1–6.

## Test strategy (mandatory, headless, extends os/oasis/tests)

Same harness pattern as M1: mkfeed.py-built EVENT feeds (every feed
ends with enough input to reach `halt\n` at the shell — WFI never
deadlocks), `--trace-level 1 --check-invtp`, every test run twice
with byte-identical traces, record→replay identity, `EMU_PY=1` smoke
leg. All M1 tests stay green (updated only for the 5-stage dbg
sequence and boot-margin timing). New tests, each with the full
assertion stack (exit contract, dbg words, fbcheck text-decode,
trace-q gates, determinism):

1. **u_enter** — boot → `run` → banner → `q` → exit(0) → shell
   prompt → `halt`. Trace proofs: an EXEC record with pc = UBASE
   exists (trace-q `find --pc`, the S→U transition); every user
   syscall is a TRAP cause 10 with epc inside [UBASE, UBASE+16MB);
   dbg_user sequence 1 then 2; **kernel-stack-switch proof**: ≥1 MEMW
   with ea inside the process kernel-trap-stack region (resolved from
   .sym) during the user syscall window, and none to the user stack
   page from kernel code paths.
2. **u_echo** — keystrokes fed while the user program runs;
   read/write round-trip shown by fbcheck; plus ≥1 TRAP cause 0
   (timer) with epc in the user window — preemption of U mode works
   and execution resumes seamlessly.
3. **u_kill_load / u_kill_kern / u_kill_jump / u_kill_priv** — the
   four crash images: TRAP with the expected cause and epc/baddr in
   the expected window, tl_after = 1, dbg_user 1 then 3, the
   diagnostic line on the console, **then the shell prompt returns
   and a subsequent `echo ok` works** (the kernel-survives keystone),
   then `halt` → 0x600D. Zero double-faults, zero kernel h_fatal
   halts, anywhere.
4. **u_hostile_sp** — hostile-sp image: syscall completes correctly,
   no UNALIGNED/DEVERR/double-fault, clean exit. If this test fails,
   the SABI §1.4 rule-2 implementation is wrong — stop and fix, do
   not weaken the test.
5. **u_efault** — efault image reports −EFAULT observed; trace shows
   no kernel MEMR of the rejected buffer range servicing that call.
6. **u_rerun** — `run`, exit, `run` again in one session: second
   entry works (re-runnable program contract), dbg_user 1,2,1,2.
7. **m1_regression** — the full M1 suite semantics under MMU_EN=1:
   the identity axiom made this a no-op for conforming code; prove
   it, don't assume it.

trace-q gates across all tests: zero ILLEGAL/DEVERR/double-fault in
kernel context (PS=1), TRAP cause counts match feed expectations,
INVTP check clean (`--check-invtp` on every run).

## Definition of done

All from the worktree root, branch `oasis-m2`, every gate green:

    rg -n "Amendment v0.1" os/abi/sabi-v0.md
    # present, contains "DRAFT — awaiting owner sign-off" and the
    # OWNER-DECIDED per-process trap-stack item; git log shows it
    # as commit 1 of the branch; zero diffs inside SABI sections 1-6.

    (cd emu-c && ./build.sh)          # fresh binary — stale bazel-bin
                                      # binaries fake replay drift
    os/oasis/build.sh && os/oasis/build.sh
    # deterministic: suite's build test byte-compares two builds

    EMU="$PWD/emu-c/bazel-bin/sahara-emu" os/oasis/tests/run-tests.sh
    # green end to end: M1 tests + u_enter u_echo u_kill_* 
    # u_hostile_sp u_efault u_rerun m1_regression, double-run
    # determinism, record->replay identity

    EMU_PY=1 EMU="$PWD/emu-c/bazel-bin/sahara-emu" \
        os/oasis/tests/run-tests.sh   # emu-py smoke leg green

    ./run_tests.sh                    # root harness untouched, green

    git status --porcelain
    # changes ONLY under os/ plus SPEC-ISSUES.md entries (root or
    # devspec/, per their conventions); zero changes under tests/,
    # trace-q/, asm/, emu-c/, emu-py/, root frozen specs

- doc updates: os/oasis/doc/syscalls.md (EFAULT rules, exit-from-user
  semantics, `run`), os/oasis/README.md (user dir, new halt codes,
  5-stage dbg word, build.sh argument).
- Every ambiguity encountered is a SPEC-ISSUES.md entry, not an
  inline workaround. Every emulator/spec MMU disagreement is a
  SPEC-ISSUES entry AND a stop for the affected test.
- Commit in small green steps; `hila-voice` skill for commit
  messages. Final commit message and hand-off both state: branch
  awaits owner sign-off of SABI v0.1 before promotion to main.

## Scope boundaries

- `tests/` and `trace-q/` at the repo root are TOOLCHAIN-OWNED; never
  modify them. New checks live in os/oasis/tests/. If a tool bug
  blocks you, SPEC-ISSUES.md and a loud SKIP — never a patch there.
- No emulator changes of any kind, either emulator. The MMU is
  spec'd; implementations either conform or get a SPEC-ISSUES entry.
- No toolchain changes. If asm.py lacks something, route around it
  with a generator emitting `.s` (the M1 idiom) and record the gap.
- SABI §1–6 frozen; the amendment is append-only; the DRAFT flag is
  not yours to remove.
- No dependence on the cc or nic streams; user programs are
  hand-written assembly.
- The front-end stream stays orthogonal: everything here is headless
  under `$EMU`; the kernel never references a window.

## Risks (mitigate, don't relitigate)

1. First real MMU client — emulator disagreement is the top schedule
   risk. Mitigation: the m1_regression test lands immediately after
   the MMU-on commit, before any user-mode work, so translation bugs
   surface against known-good behavior.
2. PS-aware dispatch touches M1's hottest path. Mitigation: keep the
   interrupt path byte-for-byte sp-free; the only new instructions on
   the PS=1 syscall path are the PS test.
3. Boot margin — page-table build adds ~20k cycles before
   shell-ready. mkfeed boot margins are per-feed constants; bump them
   once, don't shave.
4. The user window sits in the heap's growth path. No allocator
   exists; the amendment documents the UBASE ceiling and the
   allocator amendment owns the real answer.
5. Kill-path IRET juggling (PS rewrite + epc0 rewrite) is subtle and
   trace-visible. The u_kill_* tests assert tl_after and the resume
   pc; get them in early.
6. Copy-paste drift of the trap-frame blocks — unchanged M1 blocks
   stay marker-commented and untouched; `rg` the markers before the
   final commit.

Sizing expectation: ~150 lines amendment text, ~700 lines new/changed
hand-written assembly (mmu.s, uproc.s, trap.s deltas, defs/boot/shell
deltas), ~250 lines user programs, ~450 lines test additions. One
branch, one milestone. If you find yourself far outside this
envelope, stop and reread the scope boundaries before writing more
code.
