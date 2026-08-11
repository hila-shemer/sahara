# SABI v0 — Sahara Software ABI and Conventions

**Version 0. FLAGGED FOR OWNER SIGN-OFF — no second consumer may build
against this document until the owner has signed off.** First (and so far
only) conforming client: the Oasis kernel (`os/oasis/`).
Reviewing. Once we fix this spec, we can continue with multiple clients of it.

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
| r30     | `k0`. Reserved to the kernel at all times. |
This worries me - what if an application mangles it by mistake? The kernel should never depend on userspace behavior for its correctness.
Technically, once we go to userspace the app can do whatever it wants - internally it doesn't have to follow the calling convention
if it doesn't want to.
It just makes debugging that app kinda difficult. Kernel-based debugging features can depend on this SABI but must fail cleanly when its violated

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
This is fine, right? Most OSs do this - the kernel uses the extra stack the userspace isn't using. It doesn't assume any previous data there so it can't be mangled, and the memory is available so it won't double trap.
Also this is for program traps, right? An interrupt from HW would send us to a kernel context? In this case a double trap inside the program's handler can just kill the program
(i.e. - you caused a signal but didn't leave enough stack? OK you get kill-9ed instead, handler doesn't mind :))


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
Oh, so user can't mangle it - the user can't depend on it because a trap may modify it.
This changes my earlier objections - I'm okay with telling user 'never use r30 or your program breaks' as that's not the same as 'dont touch r30 or the kernel will crash'


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

**Sign-off status: FLAGGED FOR OWNER SIGN-OFF.** Until the flag is
removed by the owner, exactly one consumer (Oasis) may track this
document, and every change here must be reflected there in the same
change.
I'm replacing this flag by whatever you think the flag should be replaced weith :D
