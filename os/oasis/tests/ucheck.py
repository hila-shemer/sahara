#!/usr/bin/env python3
"""User-mode trace proofs for the Oasis M2 suite.

There is no mode bit in the trace (trace.md): U-mode occupancy is
proven by pc/epc geometry against the user window, and the SABI v0.1
A.4 stack discipline by MEMW geometry against the .sym-resolved
process kernel-trap-stack region. Options, each an independent gate:

  --dbg-user L        ordered MEMW value sequence on dbg_user == L
                      (comma list, e.g. 1,2 or 1,3 or 1,2,1,2)
  --enter-pc          >= 1 EXEC record with pc == UBASE (the S->U
                      transition happened)
  --user-syscalls N   TRAP cause-10 count with epc in the user window
                      == N (every user syscall crosses from U; the
                      shell's syscalls have kernel epcs)
  --kstack-write      >= 1 MEMW inside [uproc0_kstack,
                      uproc0_kstack_top) - the rule-2 stack switch
                      actually landed kernel pushes there
  --no-user-stack-write  zero MEMW inside the user stack page: no
                      kernel path treated a user sp as a stack (the
                      test programs never touch their own stacks)
  --min-timer-user N  >= N TRAP cause-0 with epc in the user window
                      (U-mode preemption is real and survivable)
  --fault CAUSE       exactly one fault-class TRAP (cause in {2..9,
                      11, 12}) in the trace, with this cause code and
                      tl_after == 1
  --fault-epc-in LO HI   that trap's epc in [LO, HI)
  --fault-epc HEX        ... or exactly HEX
  --fault-baddr HEX      that trap's baddr == HEX
  --no-fault          zero fault-class TRAPs anywhere
  --no-memr LO HI     zero MEMR with ea in [LO, HI) (EFAULT rejection
                      means the kernel never touched the buffer)

Window constants are platform/ABI knowledge the checker may hold,
like fbcheck's display constants: UBASE/UTOP per SABI v0.1 A.2.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, "trace-q"))
import tracefile as T          # noqa: E402

UBASE, UTOP = 0x02000000, 0x03000000
USTACK_PAGE = 0x02FF0000
FAULT_CAUSES = set(range(2, 10)) | {11, 12}


def fail(msg):
    print(f"ucheck: FAIL: {msg}")
    sys.exit(1)


def sym_addr(sym, name):
    with open(sym) as fh:
        for line in fh:
            addr, kind, nm = line.split()
            if nm == name:
                return int(addr, 16)
    fail(f"symbol {name} not in {sym}")


def main():
    args = sys.argv[1:]
    trace = sym = None
    dbg_user = None
    enter_pc = kstack = no_ustack = no_fault = False
    user_syscalls = min_timer_user = None
    fault = fault_epc = fault_baddr = None
    fault_epc_in = None
    no_memr = None
    it = iter(args)
    for a in it:
        if a == "--dbg-user":
            dbg_user = [int(x) for x in next(it).split(",")]
        elif a == "--enter-pc":
            enter_pc = True
        elif a == "--user-syscalls":
            user_syscalls = int(next(it))
        elif a == "--kstack-write":
            kstack = True
        elif a == "--no-user-stack-write":
            no_ustack = True
        elif a == "--min-timer-user":
            min_timer_user = int(next(it))
        elif a == "--fault":
            fault = int(next(it), 0)
        elif a == "--fault-epc-in":
            fault_epc_in = (int(next(it), 0), int(next(it), 0))
        elif a == "--fault-epc":
            fault_epc = int(next(it), 0)
        elif a == "--fault-baddr":
            fault_baddr = int(next(it), 0)
        elif a == "--no-fault":
            no_fault = True
        elif a == "--no-memr":
            no_memr = (int(next(it), 0), int(next(it), 0))
        elif trace is None:
            trace = a
        elif sym is None:
            sym = a
        else:
            fail(f"unknown arg {a}")
    if trace is None or sym is None:
        fail("usage: ucheck.py TRACE SYM [gates...]")

    recs = T.read_records(trace)

    dbg_addr = sym_addr(sym, "dbg_user")
    ks_lo = sym_addr(sym, "uproc0_kstack")
    ks_hi = sym_addr(sym, "uproc0_kstack_top")

    dbg_vals = []
    kstack_writes = 0
    ustack_writes = 0
    usys = 0
    utimer = 0
    faults = []
    memr_hits = 0
    for r in recs:
        if r.type == T.T_MEMW:
            ea = r.fields["ea"]
            if ea == dbg_addr:
                dbg_vals.append(r.fields["val"])
            if ks_lo <= ea < ks_hi:
                kstack_writes += 1
            if USTACK_PAGE <= ea < UTOP:
                ustack_writes += 1
        elif r.type == T.T_MEMR and no_memr:
            if no_memr[0] <= r.fields["ea"] < no_memr[1]:
                memr_hits += 1
        elif r.type == T.T_TRAP:
            c, epc = r.fields["cause"], r.fields["epc"]
            if c == 10 and UBASE <= epc < UTOP:
                usys += 1
            if c == 0 and UBASE <= epc < UTOP:
                utimer += 1
            if c in FAULT_CAUSES:
                faults.append(r.fields)

    if dbg_user is not None and dbg_vals != dbg_user:
        fail(f"dbg_user sequence {dbg_vals} != expected {dbg_user}")
    if enter_pc:
        if not any(r.type == T.T_EXEC and r.fields["pc"] == UBASE
                   for r in recs):
            fail("no EXEC record with pc == UBASE (never entered U)")
    if user_syscalls is not None and usys != user_syscalls:
        fail(f"user-window syscall TRAPs {usys} != expected {user_syscalls}")
    if kstack and kstack_writes == 0:
        fail("no MEMW inside the process kernel trap stack "
             "(rule-2 switch never landed a push there)")
    if no_ustack and ustack_writes != 0:
        fail(f"{ustack_writes} MEMW inside the user stack page "
             "(kernel used a user sp as a stack?)")
    if min_timer_user is not None and utimer < min_timer_user:
        fail(f"TIMER traps with user-window epc: {utimer} < "
             f"{min_timer_user} (no U-mode preemption proven)")
    if no_fault and faults:
        fail(f"unexpected fault trap: {faults[0]}")
    if fault is not None:
        if len(faults) != 1:
            fail(f"expected exactly 1 fault trap, saw {len(faults)}")
        f = faults[0]
        if f["cause"] != fault:
            fail(f"fault cause {f['cause']} != expected {fault}")
        if f["tl_after"] != 1:
            fail(f"fault tl_after {f['tl_after']} != 1 (double fault?)")
        if fault_epc is not None and f["epc"] != fault_epc:
            fail(f"fault epc 0x{f['epc']:x} != 0x{fault_epc:x}")
        if fault_epc_in is not None and not (
                fault_epc_in[0] <= f["epc"] < fault_epc_in[1]):
            fail(f"fault epc 0x{f['epc']:x} outside "
                 f"[0x{fault_epc_in[0]:x}, 0x{fault_epc_in[1]:x})")
        if fault_baddr is not None and f["baddr"] != fault_baddr:
            fail(f"fault baddr 0x{f['baddr']:x} != 0x{fault_baddr:x}")
    if no_memr and memr_hits:
        fail(f"{memr_hits} MEMR inside the rejected buffer range")
    print("ucheck: ok")


if __name__ == "__main__":
    main()
