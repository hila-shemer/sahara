# Oasis syscall table — milestone 2

Personality document for the Oasis kernel, per SABI v0 section 3 (which
owns the *mechanism*: SYSCALL instruction, number in r7, args r0–r5, r6
reserved-zero, result-or-negated-errno in r0, clobbers = function call).
This document owns only the numbers and semantics below.

Errno values (SABI v0): 1 `EINVAL`, 2 `ENOSYS`, 3 `EFAULT`. Any number
not in this table returns `-ENOSYS`.

M2: all three syscalls are callable from user mode (`status.PS` = 0 at
handler entry). Two caller-mode rules, per SABI v0.1 amendment A.5/A.6:

- **Pointer validation.** A `buf`/`len` pair from a user-mode caller
  must lie entirely inside the user window `[0x0200_0000, 0x0300_0000)`
  or the syscall returns `-EFAULT` before touching the buffer.
  Kernel-mode callers are trusted and unchecked.
- **Stack discipline.** A user-mode syscall runs on the current
  process's kernel trap stack (v0.1 A.4); the caller's sp is saved and
  restored bit-for-bit as data — a user program may make syscalls with
  any garbage in sp and they still work.

| # | name | args | returns |
|--:|------|------|---------|
| 0 | `write` | r0 fd, r1 buf, r2 len | bytes written (= len), or −EINVAL |
| 1 | `read`  | r0 fd, r1 buf, r2 len | bytes read, ≥ 1; blocks; or −EINVAL |
| 2 | `exit`  | r0 code | does not return |

## 0 — write(fd, buf, len)

- `fd` 0 is the console; any other fd returns −EINVAL.
- Writes `len` bytes from `buf` to the text console. Byte semantics are
  the console's: printables 0x20–0x7E render; 0x0A is newline; 0x08 is
  backspace-erase; every other byte is ignored. One PRESENT is issued at
  the end of the write (after the last byte's effect), not per byte.
- `len` = 0 returns 0 without touching the display (no PRESENT).
- Returns `len`. From user mode, `[buf, buf+len)` outside the user
  window returns `-EFAULT` (the check caps `len` at the window size
  first, so `buf+len` cannot wrap).

## 1 — read(fd, buf, len)

- `fd` 0 is the console keyboard stream; any other fd returns −EINVAL.
- `len` = 0 returns −EINVAL (a successful read returns ≥ 1 by contract,
  so a zero-length buffer cannot succeed).
- **Blocks** until at least one byte is available in the kernel's ASCII
  ring, then copies up to `len` available bytes to `buf` and returns the
  count (≥ 1, ≤ len). No line editing here — the ring carries raw ASCII
  (printables, 0x0A from Enter, 0x08 from Backspace); line editing lives
  in the shell.
- Blocking is the SABI/ISA 7.3 pattern: the handler saves bank-0 sregs
  and status to its stack frame, lowers TL to 0, sets IE, and idles in
  WFI; the timer and EXTINT handlers run normally meanwhile (the EXTINT
  handler is what fills the ring). Idle is WFI, never polling. For a
  user-mode caller the frame lives on the process kernel trap stack —
  nesting-safe by the same construction.
- From user mode, the buffer is validated (`-EFAULT`) **before**
  blocking: a bad pointer fails fast, it never sleeps first.

## 2 — exit(code)

- **Kernel-mode caller** (the shell's `halt`): halts the machine with
  r0 = `code`: the emulator prints `HALT r0=<code as 32 hex digits>`
  and exits 0. The shell's `halt` builtin calls `exit(0x600D)` — the
  suite's PASS idiom, in Oasis's own value space.
- **User-mode caller**: terminates the user program with `code`; the
  machine does not stop (v0.1 A.6 — a user program cannot halt the
  machine; `HALT`/`WFI` from user mode are PRIV traps and kill it).
  Control returns to the shell, which prints `user: exit <code>`.

## The `run` builtin (not a syscall — shell surface)

`run` enters the user program embedded in the image at UBASE per the
v0.1 A.3 entry contract (all registers zero, sp = window top, IRET
with PS=0/PIE=1). On termination the shell prints exactly one line:
`user: exit <code>` for a clean exit, or
`user: killed cause=<c> epc=0x<hex>` when a fault/PRIV trap killed it
(cause codes are ISA 7.1's). Re-running is legal; the image is loaded
once, so programs re-initialize their own state from code (A.7).
