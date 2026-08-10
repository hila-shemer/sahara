# Oasis syscall table — milestone 1

Personality document for the Oasis kernel, per SABI v0 section 3 (which
owns the *mechanism*: SYSCALL instruction, number in r7, args r0–r5, r6
reserved-zero, result-or-negated-errno in r0, clobbers = function call).
This document owns only the numbers and semantics below.

Errno values (SABI v0): 1 `EINVAL`, 2 `ENOSYS`, 3 `EFAULT`. Any number
not in this table returns `-ENOSYS`.

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
- Returns `len`. `buf` is not validated in M1 (kernel-only machine, MMU
  off; EFAULT is reserved for the milestone that adds user memory).

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
  handler is what fills the ring). Idle is WFI, never polling.

## 2 — exit(code)

- Halts the machine with r0 = `code`: the emulator prints
  `HALT r0=<code as 32 hex digits>` and exits 0.
- The shell's `halt` builtin calls `exit(0x600D)` — the suite's PASS
  idiom, in Oasis's own value space.
