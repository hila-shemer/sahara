# SABI v0 — Sahara Software ABI and Conventions

**Version 0 — SIGNED OFF** (owner review 2026-08-11, commit cfff4aa;
review comments integrated as section 1.4 and the section 1.1 scoping in
the same change). Multiple consumers may build against this document; the
consumer registry and amendment rules are at the end. First conforming
client: the Oasis kernel (`os/oasis/`).

This document defines the machine-wide software conventions of the Sahara
platform: register roles, calling convention, stack discipline, the
syscall *mechanism*, the trap-entry contract, the physical memory-layout
conventions, and the image/section conventions. These are properties of
the machine, shared by every OS, library, loader, and compiler — they live
here, outside any OS directory, on purpose.

What is **not** here: per-OS personality. The syscall *number table* and
per-syscall semantics of an OS live in `os/<name>/doc/syscalls.md` (for
Oasis: `os/oasis/doc/syscalls.md`).

Authority: ISA-SPEC.md, PLATFORM-SPEC.md, TOOLING-SPEC.md and the devspec
documents are frozen and win over this document on any discrepancy. Where
this document says "adopted by reference", the referenced text is the
normative content and nothing here modifies it.

**Forks are explicit.** A divergent ABI must be a new document
(`os/abi/sabi-v1-<name>.md`); silent divergence from this document is
banned. Conforming code states which SABI version it targets.

---

## 1. Register roles and calling convention

**Adopted verbatim, by reference: ISA-SPEC.md section 12.** All of it —
the register-role table, predicate save rules, stack-slot rules, the
canonical-form rule, and the trap-entry contract. Nothing is added to it
silently; every SABI addition is listed explicitly in 1.1–1.3 below.

Informative restatement of the ISA-SPEC 12 table (the ISA text governs):

| registers | role |
|-----------|------|
| r0–r7   | arguments 0–7 in order; return value in r0 (r0:r1 for a two-register return). Caller-saved. |
| r8–r15  | temporaries. Caller-saved. |
| r16–r27 | callee-saved: a function preserves exactly the ones it uses. |
| r28     | `sp`. 16-byte aligned at all times. Grows down. |
| r29     | `ra`. Written by JAL/JALR. Caller-saved. |
| r30     | `k0`. Reserved to the kernel at all times (violating it breaks only the violator — section 1.4). |
| r31     | `zero` (hardware). |

Predicate registers are caller-saved and not preserved across calls.
Arguments beyond 8 are passed in 16-byte stack slots at [sp + 0] of the
caller's frame at call time; the callee addresses them at
[sp + framesize + 16·i]. There is no frame pointer. All integer values are
kept in the canonical form of ISA-SPEC 3.4.

### 1.1 SABI addition: no red zone

Memory below `sp` is volatile. A trap or interrupt handler may use the
current stack (pushing its own frames below the interrupted `sp`), so no
code may keep live data at addresses below `sp`. There is no red zone of
any size.

The below-`sp` license is scoped: it applies when the interrupted context
is **kernel** code. Sahara hardware does not switch stacks on trap entry
(delivery only sets S=1 — ISA-SPEC 7.2); a handler entered from user mode
must not treat the user's `sp` as a stack at all (section 1.4, rule 2).

### 1.2 SABI addition: `gp` = r27, kernel-internal only

Inside kernel code — and only there — r27 is `gp`, the kernel globals
pointer. It is set exactly once, during boot, to the kernel's globals
block (the table-derived device bases, console state, and similar), so
that any global is one `ldz.64 rX, [gp + offset]` away. Kernel code never
writes r27 after boot.

The user-facing ABI is unchanged: to everything outside the kernel, r27
is a plain callee-saved register with no special role. This works because
r27 is callee-saved: any future user code preserves it across calls, and
the kernel's trap paths preserve it like every other callee-saved
register, so the kernel's `gp` survives every excursion.

### 1.3 SABI addition: `k0` and the scratch sregs are trap-path property

`k0` (r30) and the supervisor scratch sregs `scratch0`/`scratch1` (sregs
10/11) belong to the trap path (section 5). Their values are destroyed,
without notice, by any trap or interrupt — including SYSCALL. No code,
kernel or user, may keep a value in any of them across any instruction
that can be interrupted (that is: ever, outside the trap path itself).

### 1.4 SABI addition: the kernel/user trust boundary

Owner-review outcome (2026-08-11). The conventions in this document bind
user code only on pain of **its own** misbehavior. Normatively:

**Kernel correctness must never depend on user-mode adherence to this
document.** A user-mode violation of any SABI convention — register
roles, stack discipline, alignment, canonical form — must be containable
to the violating program. "Never use r30 or your program breaks" is a
conforming consequence; "don't touch r30 or the kernel crashes" is a
kernel bug. Two rules make the existing conventions satisfy this:

1. **`k0`/`scratch0`/`scratch1` are write-before-read in the trap path.**
   The kernel never consumes a value a less-privileged context could have
   placed in them; the canonical block of section 5 writes `k0` (`la k0,
   SAVE`) before its first read, and every conforming handler must do the
   same. User code that touches r30 loses its value at the next trap —
   which can be any instruction — so it harms only itself.
2. **User `sp` is data, never infrastructure.** On a trap whose saved
   status shows the interrupted context was user mode (`status.PS` = 0 at
   handler entry), the handler must load a kernel-owned stack pointer (or
   use a kernel-owned save area) before its first push; the interrupted
   `sp` is register state to be saved, not a stack to be used. The
   section 1.1 below-`sp` license never crosses the privilege boundary.
   (Milestone-1 corollary: with no user mode, every trap interrupts
   kernel code and the license always applies; Oasis's static save areas
   conform a fortiori.)

Kernel debugging and introspection features (stack walkers over section 2
frames, symbolization via section 6 labels, and similar) MAY interpret
SABI structure in user programs, and must **fail cleanly** when it is
violated: degraded or absent output for that program, never kernel
misbehavior. What a kernel does to a user program that wrecks itself
(kill it, signal it) is per-OS policy and, for signal-like upcalls, a
deferral of section 7.

## 2. Stack discipline and frames

1. `sp` is 16-byte aligned at all times — at function entry, at every
   call site, and at every SYSCALL.
2. A frame is allocated by the prologue `add sp, sp, -N` where **N is a
   multiple of 16**, and released by `add sp, sp, N`. The frame is the
   byte range [sp, sp + N) between those two points.
3. Every save slot in a frame is 16 bytes, and saves use `st128` /
   `ld128`. Because sp is 16-aligned and N and all slot offsets are
   multiples of 16, every slot is 16-byte aligned — ST128's alignment
   requirement (ISA-SPEC 5.3) is met by construction, never by luck.
4. Slot layout, top down:
   - `ra` (when the function makes calls) is saved in the **top** slot:
     `st128 [sp + N - 16], r29`.
   - Callee-saved registers the function uses go downward from there:
     [sp + N − 32], [sp + N − 48], … in decreasing register order.
   - Locals and outgoing >8-argument slots occupy the remainder; outgoing
     stack arguments are at [sp + 0], per ISA-SPEC 12.
5. Leaf functions (no calls, no stack use) may be frameless.
6. Nothing may be kept below `sp` (section 1.1).

Canonical shape (informative):

    func:                                # non-leaf, uses r16, r17
            add     sp, sp, -48
            st128   [sp + 32], r29       # ra: top slot
            st128   [sp + 16], r17       # callee-saved, downward
            st128   [sp + 0],  r16
            ...body...
            ld128   r16, [sp + 0]
            ld128   r17, [sp + 16]
            ld128   r29, [sp + 32]
            add     sp, sp, 48
            ret

## 3. Syscall mechanism

The mechanism below is SABI (machine-wide). The *numbering* — which
syscall has which number, and each one's semantics — is per-OS, in
`os/<name>/doc/syscalls.md`.

1. **Instruction.** A syscall is the `SYSCALL` instruction: trap cause 10,
   `epc` = the SYSCALL itself; the handler resumes past it via
   `epc += 8` then `IRET` (ISA-SPEC 7.1/7.4).
2. **Number** in **r7**.
3. **Arguments** in r0–r5, in order. **r6 is reserved**: callers set it
   to 0 in v0; kernels ignore it.
4. **Return value** in r0: a result ≥ 0, or a negated errno in
   [−255, −1]. Either way the value is in the canonical sign-extended
   128-bit form of ISA-SPEC 3.4. No other error channel exists.
5. **Errno values, v0:** 1 `EINVAL`, 2 `ENOSYS`, 3 `EFAULT`. An unknown
   syscall number returns −ENOSYS. (Per-OS documents may not renumber
   these three; they may extend beyond them only by a SABI revision.)
6. **Clobbers = function call.** A SYSCALL clobbers exactly what a
   function call may clobber: r0–r15, r29, and all predicate registers
   are caller-saved; r16–r28 are preserved by the kernel across the
   syscall; `k0` is destroyed (section 1.3). `sp` must be 16-aligned at
   the SYSCALL.
7. **fcsr** is caller-saved across calls and syscalls. (The rest of the
   FP ABI is deferred, section 7.)

## 4. Memory layout conventions

All addresses physical; everything device-shaped comes from the device
table per devspec/boot.md — the only hardcodable address is the table's
own 0x0800.

1. **[0, 0x0800) is untouched.** No code, no data, no stack, ever. Zeroed
   RAM decodes as opcode 0x00 = ILLEGAL, and vbase/dfbase are 0 at reset:
   this window is a deliberate tripwire (devspec/boot.md 2.2 — pre-vector
   faults triple-fault loudly). Software placing anything there defeats
   the tripwire and is non-conforming.
2. **[0x0800, 0x1000) is the device table, read-only by convention**
   (devspec/boot.md 2.1). Conforming software never stores to it.
3. **The kernel loads flat at 0x1000**, the reset PC. One contiguous
   region, sections ordered per section 6.
4. **Identity axiom: kernel VA = PA, whether or not translation is
   enabled.** Milestone-1 kernels run with the MMU off; a later milestone
   that enables translation must use an identity map for all kernel
   ranges. Conforming kernel code may therefore treat any kernel address
   as both a VA and a PA, and nothing changes for it when MMU_EN is set.
5. **Kernel/boot stack: the top of RAM region 0, as read from the
   table.** `sp` at boot = region 0's `base + len` (reference platform:
   0x0F00_0000 — a reference value, never hardcoded). The **top 64 KB**
   of RAM region 0 is reserved as the kernel stack; nothing else may be
   placed there.
6. **Heap grows UP from `_end`** (the section-end label of section 6),
   toward the stack. The growth direction is frozen in v0; no allocator
   is specified or implemented in milestone 1 (section 7).

## 5. Trap-entry contract and the canonical trap-frame block

Adopted by reference: ISA-SPEC 12's trap-handler entry contract and
ISA-SPEC 7.3's nested-fault pattern. Restated:

- At handler entry, `k0` plus `scratch0`/`scratch1` are the only free
  resources — the free-register bootstrap.
- The predicate file is preserved with PRD/PWR: a handler that can
  interrupt arbitrary code must save the whole predicate file before its
  first compare and restore it before IRET (an interrupt can land between
  a `cmpeq` and its consuming branch; clobbering that predicate corrupts
  the interrupted computation).
- Bank-0 sregs (`epc0`, `cause0`, `baddr0`) and `status` are saved to
  memory before `TL` is lowered (the ISA-SPEC 7.3 software-consent
  pattern). A handler that never lowers TL need not save them.

**Canonical trap-frame block.** There is no macro processor, so every
handler copy-pastes this block. The text below is the normative
reference: every instance must match it exactly — same instructions, same
order, same offsets — except for the single OS-chosen name of the save
area (`SAVE` below), which must be a 16-byte-aligned, ≥160-byte region of
kernel memory. Instances are bracketed by the marker comments shown, so
drift is greppable. The block preserves r8–r15, r29, and the predicate
file; a handler whose body touches only those registers (plus r30/k0 and
the sregs) is fully transparent to interrupted code.

Save (at handler entry, k0 free per the bootstrap):

    # SABI-TRAPFRAME-SAVE v0 -- begin (canonical block, sabi-v0.md section 5)
            la      k0, SAVE
            st128   [k0 + 0],   r8
            st128   [k0 + 16],  r9
            st128   [k0 + 32],  r10
            st128   [k0 + 48],  r11
            st128   [k0 + 64],  r12
            st128   [k0 + 80],  r13
            st128   [k0 + 96],  r14
            st128   [k0 + 112], r15
            st128   [k0 + 128], r29
            prd     r8
            st128   [k0 + 144], r8
    # SABI-TRAPFRAME-SAVE v0 -- end

Restore (immediately before IRET):

    # SABI-TRAPFRAME-RESTORE v0 -- begin (canonical block, sabi-v0.md section 5)
            la      k0, SAVE
            ld128   r8, [k0 + 144]
            pwr     r8
            ld128   r8,  [k0 + 0]
            ld128   r9,  [k0 + 16]
            ld128   r10, [k0 + 32]
            ld128   r11, [k0 + 48]
            ld128   r12, [k0 + 64]
            ld128   r13, [k0 + 80]
            ld128   r14, [k0 + 96]
            ld128   r15, [k0 + 112]
            ld128   r29, [k0 + 128]
    # SABI-TRAPFRAME-RESTORE v0 -- end
            iret

A static save area is sufficient exactly when the handler cannot nest
with itself (interrupt handlers run with IE = 0 and never lower TL). A
handler that lowers TL (e.g. a blocking syscall path) must keep its own
saved state somewhere nesting-safe — its stack frame — and must not
depend on the static area across the lowered-TL window.

SYSCALL handlers need no trap-frame block for r8–r15/r29/predicates:
those are caller-saved across a syscall (section 3.6). They must still
preserve r16–r28 by the ordinary function discipline of section 2.

## 6. Image and section conventions

1. **Physical format**: flat `SAHIMG01` image + `.sym` sidecar, exactly
   per TOOLING-SPEC 1–2. No new format.
2. **Logical section order is fixed by source concatenation** — there is
   no linker; the assembler command line IS the layout:

       text | rodata | data | bss

   Each section begins with `.align 16`. `bss` is `.space` (and `.align`)
   only — zero bytes at the image tail, which the assembler's
   trailing-zero trim keeps out of the file (asm.md 8.2).
3. **Boundary labels**, defined at the section seams, in this order:
   `__etext` (end of text = start of rodata), `__erodata` (end of rodata
   = start of data), `__edata` (end of data = start of bss), `_end` (end
   of bss = end of image). Programs reference section boundaries **only**
   via these labels — never via file names, hardcoded addresses, or
   arithmetic reconstructions of the layout.
4. The heap base is `_end` (section 4.6).

## 7. Frozen in v0, and explicit deferrals

**Frozen by this document**: everything in sections 1–6.

**Explicitly deferred — specified as deferred, implemented by nothing in
milestone 1.** A future SABI revision must define these before anything
uses them; until then any code needing one of them is out of scope by
definition:

- Object/executable format beyond the flat image, and any loader.
- Relocation, position-independent code conventions beyond what LAP
  gives for free, and dynamic linking of any kind.
- User-mode conventions: user/kernel memory split, user stack placement,
  argument passing at process entry, signal-like upcalls.
- Allocator API. (Heap direction is frozen — up from `_end` — the
  allocator over it is not.)
- FP ABI beyond "fcsr is caller-saved": FP argument passing beyond the
  integer rules, FP callee-saved set, NaN/rounding guarantees at call
  boundaries.
- The libc surface, string/memory routine names, anything resembling a
  runtime library contract.

---

**Sign-off status: SIGNED OFF** — owner review 2026-08-11 (commit
cfff4aa), comments integrated as section 1.4 and the section 1.1 scoping.

**Consumer registry.** Every consumer of this document is listed here;
adding a consumer is a one-line change to this list.

- Oasis kernel — `os/oasis/`
- cc compiler — `lang/cc/`

**Amendment rules, now that the document is live:**

1. Sections 1–6 are frozen. A change to frozen text requires owner
   approval, a dated entry in the change log below, and same-change
   updates to every registered consumer.
2. Filling in a section-7 deferral (user-mode conventions, allocator
   API, FP ABI, …) is the expected growth path: it is drafted as a
   `v0.x` amendment appended to this document, flagged for owner
   sign-off exactly as v0 was, and no consumer may build on it until
   signed. Deferrals bind before they are signed: code needing an
   unsigned deferral is out of scope, not creatively unblocked.
3. Incompatible changes fork: `os/abi/sabi-v1-<name>.md`, per the header.

**Change log:**

- 2026-08-11 — Amendment v0.1 (user-mode conventions) signed off after
  owner review: A.2 gains the window-growth note, A.4 the `cur_proc`
  reachability answer, A.6 the committed direction on user-space fault
  handling. Consumers: Oasis M2.

- 2026-08-11 — v0 signed off. Trust-boundary section 1.4 added and the
  section 1.1 below-`sp` license scoped to kernel-mode interruption, from
  owner review (cfff4aa). No consumer code change required: Oasis M1 has
  no user mode, and its handlers use static save areas with
  write-before-read `k0`.

---

## Amendment v0.1 — user-mode conventions (SIGNED OFF 2026-08-11)

Fills the "user-mode conventions" deferral of section 7 — partially.
Defined here: the address-space model, the user window and its layout,
the process-entry contract, kernel trap stacks, the user-mode syscall
pointer rule, and user-fault classification. Still deferred (A.8 lists
them): processes/scheduling, per-program address spaces, entry
arguments, signal upcalls, user heap, W^X. Sections 1–6 of this
document are unchanged by this amendment; where this amendment says
"user mode", it means `status.S = 0` (ISA-SPEC 2.4). First consumer:
Oasis milestone 2.

### A.1 Address-space model: one address space, split by the U bit

User code runs in the same identity-mapped address space as the
kernel. The user window (A.2) is user VA = PA, exactly like the kernel
ranges of section 4.4; privilege separation is entirely the page-table
U bit (ISA-SPEC 8.4). Kernel pages carry U = 0: a user-mode load,
store, or fetch of kernel memory faults `PERM_*`.

Rationale: one program at a time needs no `asid`, no `ptbase`
switching, and no second set of mappings. Per-program address spaces
arrive with processes in a later amendment, and nothing here obstructs
them — the window is a page-table property, not a linkage one. `asid`
stays 0 throughout.

### A.2 The user window: [0x0200_0000, 0x0300_0000) — UBASE, 16 MB

Exactly one 8-bit VPN chunk (VPN 512–767): one shift-0 node, one root
entry. Layout inside the window:

- **Program image pages** from UBASE upward, mapped U+R+W+X. (No W^X
  in v0.1 — deferred, A.8.) The image extent is rounded up to the
  64 KB page.
- **User stack**: the top 64 KB page [0x02FF_0000, 0x0300_0000),
  mapped U+R+W.
- **Everything between image end and stack page is UNMAPPED** — a
  wild user pointer faults `PF_*`, loudly, rather than silently
  reading zeros.

Boot-time checks, each a loud distinct halt code: UBASE ≥ `_end`
rounded up to a page, and UBASE + 16 MB ≤ RAM top from the device
table. The kernel heap of section 4.6 is hereby capped at UBASE —
growth direction unchanged, ceiling noted; the allocator amendment
revisits this.

Owner note at sign-off: 16 MB is a v0.1 value, not an architectural
bound — expect the window to grow considerably in later amendments.
It must grow (or move) before any allocator consumes the heap ceiling,
which is why the allocator amendment owns the revisit.

### A.3 Entry contract

- `pc` = UBASE. A user program's first byte is its entry point — no
  header, no metadata.
- `sp` (r28) = 0x0300_0000 — the top of the user stack, 16-aligned
  (the stack grows down into the mapped page).
- Every other GPR (r0–r27, r29, r30) = 0; p1–p7 = 0; `fcsr` = 0.
  Deterministic entry; no kernel state leaks into user mode.
- **No entry arguments in v0.1** — r0–r7 are zero by the rule above.
  Argument passing is defined together with processes, later (A.8).
- Entered via IRET with `status.PS` = 0 and `PIE` = 1 (ISA-SPEC 7.4 —
  entering user mode IS an IRET with PS = 0; there is no other door).
  User code therefore runs at TL = 0 with interrupts enabled: the
  timer keeps ticking and the keyboard keeps draining while user code
  runs.

### A.4 Kernel trap stacks are per-process

**OWNER-DECIDED 2026-08-11** — recorded here as a ruling, not an open
question. Every user program/process has its own kernel-owned trap
stack. The per-process structure holds its kernel trap-stack pointer;
a trap arriving with `status.PS` = 0 loads `sp` from the *current
process's* structure before its first push — this mechanizes section
1.4 rule 2 — and the interrupted user `sp` is saved into that
structure as data, never used as a stack. Reference kernel-trap-stack
size: 16 KB.

M2 instantiates exactly one such structure; M3 changes a count, not a
design. Trap paths reach the stack only through "the current process's
structure", never through a global bare stack symbol. Reachability
(owner question at sign-off, answered): the structure is found through
`cur_proc`, a kernel global in U = 0 memory whose address enters the
trap path as an instruction immediate from kernel text (`la k0,
cur_proc` — k0 is write-before-read per section 1.4 rule 1). No
register a user context can write participates; user code cannot store
to the pointer or the structure (PERM_*). On this single-CPU machine a
plain kernel global is the whole per-CPU mechanism; a context switch
updates `cur_proc` and nothing else changes. The shared
boot/shell kernel stack of section 4.5 is NOT a trap stack for
user-mode traps.

### A.5 Syscalls from user mode

Mechanism unchanged from section 3. One new rule: a pointer+length
argument passed **from user mode** must lie entirely within the user
window of A.2, else the syscall returns −`EFAULT` — the errno's first
real use. Kernel-mode callers are exempt (trusted; section 1.4 is a
boundary, not a straitjacket).

Handlers that consume `sp` (the syscall path) perform the A.4 stack
switch when `status.PS` = 0 at entry. Handlers that are `sp`-free (the
static-save-area interrupt path of section 5) need no switch — and
must stay `sp`-free: that property is what exempts them.

### A.6 User faults

Any trap with `status.PS` = 0 and cause ∈ {2..9, 11, 12} terminates
the user program. What termination means — diagnostic, return to
shell, exit status — is per-OS policy; signal-like upcalls remain
deferred (A.8).

Owner direction at sign-off (binding on future amendments):
user-space fault handling — a user-registered SIGSEGV-style handler
receiving the fault instead of unconditional termination — is a
COMMITTED future amendment, not a mere deferral. Managed memory makes
signals real (guard-page stacks, GC barriers, Smalltalk-style tricks
are anticipated consumers). v0.1's kill-on-fault is the placeholder
policy, and nothing in this amendment may be read as precluding
delivery of user faults to user handlers later.

Consequences worth spelling out: `HALT` and `WFI` from user mode are
`PRIV` traps (ISA-SPEC 2.4) — a user program cannot stop, halt, or
sleep the machine. `exit()` from user mode terminates the program, not
the machine; only a kernel-mode caller can take the machine down.

### A.7 Image embedding

A user program enters the flat image as an additional `.org UBASE`
segment of the same assembly unit: the user source file(s) go last on
the assembler command line and open the segment themselves. The loader
of TOOLING-SPEC 1 places the segment before reset; there is still no
runtime loader (that deferral stands). One user program per image in
v0.1.

The image is loaded once, at reset: re-entering the program does not
re-initialize its data. Re-runnable programs initialize their own
state from code; reload semantics are deferred with the loader.

### A.8 Still deferred

Explicitly not defined by this amendment; code needing any of these
remains out of scope per amendment rule 2:

- Processes and scheduling.
- Per-program address spaces and `asid` discipline.
- Entry arguments (argc/argv or any equivalent).
- Signal-like upcalls.
- User heap / allocator.
- W^X (the v0.1 image mapping is U+R+W+X).

**Amendment status: SIGNED OFF** — owner review 2026-08-11
(conversation review: items 1–7; window-growth note, `cur_proc`
reachability answer, and the user-fault-handling commitment integrated
at sign-off). Consumers may build against v0.1.
