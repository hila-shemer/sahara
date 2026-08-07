"""C1-shaped smoke tests: traps, nesting, privilege, interrupts, WFI."""

import encoding as E
from helpers import (DF_PA, HANDLER_PA, alui, asm, b, cause_handler, cmpi,
                     dfbase_setup, halt, iret, ldi, lds, li128, mfsr, mtsr,
                     nop, pred, run_words, syscall, vbase_setup, wbytes)

S = 1 << E.STATUS_BITS["S"]
IE = 1 << E.STATUS_BITS["IE"]
PS = 1 << E.STATUS_BITS["PS"]


def test_syscall_epc_and_resume():
    handler = [mfsr(12, "epc0"), alui("ADD", 12, 12, 8),
               mtsr("epc0", 12), iret()]
    prog = vbase_setup() + [alui("ADD", 0, 31, 1), syscall(),
                            alui("ADD", 0, 0, 2), halt()]
    m, out = run_words(prog, data=[(HANDLER_PA, wbytes(handler))])
    assert out == "halt"
    assert m.regs[0] == 3


def test_trap_state_and_cause():
    prog = vbase_setup() + [syscall(), halt()]
    m, _ = run_words(prog, data=[(HANDLER_PA, wbytes(cause_handler()))])
    assert m.regs[10] == E.CAUSES["SYSCALL"]
    assert m.regs[12] == E.RESET_PC + 2 * 8   # epc = the SYSCALL itself
    assert m.tl == 1
    assert m.stbit("S") == 1
    assert m.stbit("IE") == 0


def test_illegal_opcode_traps():
    prog = vbase_setup() + [0x00000000_00000000, halt()]  # opcode 0
    m, _ = run_words(prog, data=[(HANDLER_PA, wbytes(cause_handler()))])
    assert m.regs[10] == E.CAUSES["ILLEGAL"]


def test_double_fault_banks():
    # handler faults immediately (word 0 = ILLEGAL) -> dfbase, bank 1
    df = [mfsr(10, "cause0"), mfsr(11, "cause1"), mfsr(12, "epc0"),
          mfsr(13, "epc1"), halt()]
    prog = vbase_setup() + dfbase_setup() + [syscall(), halt()]
    m, out = run_words(prog, data=[(HANDLER_PA, wbytes([0])),
                                   (DF_PA, wbytes(df))])
    assert out == "halt"
    assert m.regs[10] == E.CAUSES["SYSCALL"]  # bank 0 intact
    assert m.regs[11] == E.CAUSES["ILLEGAL"]  # bank 1 = second fault
    assert m.regs[12] == E.RESET_PC + 4 * 8
    assert m.regs[13] == HANDLER_PA
    assert m.tl == 2


def test_triple_fault_halts():
    prog = vbase_setup() + dfbase_setup() + [syscall(), halt()]
    m, out = run_words(prog, data=[(HANDLER_PA, wbytes([0])),
                                   (DF_PA, wbytes([0]))])
    assert out == "halt"
    assert m.triple_fault
    # banks intact from the first two faults; nothing written by the third
    assert m.sregs[E.SREGS["cause0"]] == E.CAUSES["SYSCALL"]
    assert m.sregs[E.SREGS["cause1"]] == E.CAUSES["ILLEGAL"]
    assert m.tl == 2


def test_syscall_at_tl1_double_faults():
    df = [mfsr(11, "cause1"), halt()]
    handler = [syscall()]
    prog = vbase_setup() + dfbase_setup() + [syscall(), halt()]
    m, _ = run_words(prog, data=[(HANDLER_PA, wbytes(handler)),
                                 (DF_PA, wbytes(df))])
    assert m.regs[11] == E.CAUSES["SYSCALL"]
    assert m.tl == 2


def test_tl_lowering_pattern():
    """The ISA-SPEC 7.3 supervisor pattern in miniature: outer handler
    saves bank 0 + status, writes TL<-0, takes a legitimate nested
    SYSCALL (delivered normally), restores, IRETs twice."""
    inner = [mfsr(13, "epc0"), alui("ADD", 13, 13, 8),
             mtsr("epc0", 13), iret()]
    outer = [mfsr(14, "epc0"), alui("ADD", 14, 14, 8),   # resume point
             mfsr(15, "status"), mtsr("scratch0", 15),   # save status
             ldi(17, S), mtsr("status", 17),             # TL <- 0, stay S
             alui("ADD", 0, 0, 100),
             syscall(),                                  # nested, TL 0->1
             alui("ADD", 0, 0, 1000),
             mtsr("epc0", 14),                           # restore bank 0
             mfsr(18, "scratch0"), mtsr("status", 18),   # restore TL=1
             iret()]
    # vbase handler dispatches: r19 == 0 -> outer (sets r19=1), else inner
    handler = ([cmpi("CMPEQ", 1, 19, 0),
                alui("ADD", 19, 19, 1),
                b(1 + len(inner), p=pred(1))]            # to outer
               + inner + outer)
    prog = vbase_setup() + [syscall(), alui("ADD", 0, 0, 7), halt()]
    m, out = run_words(prog, data=[(HANDLER_PA, wbytes(handler))])
    assert out == "halt"
    assert m.regs[0] == 1107
    assert m.tl == 0
    assert m.stbit("S") == 1


def test_priv_supervisor_ops_from_user():
    # drop to user; HALT must trap PRIV
    prog = vbase_setup() + [ldi(1, 0), mtsr("status", 1), halt()]
    m, _ = run_words(prog, data=[(HANDLER_PA, wbytes(cause_handler()))])
    assert m.regs[10] == E.CAUSES["PRIV"]
    assert m.regs[12] == E.RESET_PC + 4 * 8


def test_user_cycle_read_ok_epc_read_priv():
    prog = vbase_setup() + [ldi(1, 0), mtsr("status", 1),
                            mfsr(5, "cycle"),          # allowed
                            mfsr(6, "epc0"),           # PRIV
                            halt()]
    m, _ = run_words(prog, data=[(HANDLER_PA, wbytes(cause_handler()))])
    assert m.regs[5] == 4                     # cycle when mfsr executed
    assert m.regs[10] == E.CAUSES["PRIV"]


def test_user_fcsr_rw_ok():
    prog = vbase_setup() + [ldi(1, 0), mtsr("status", 1),
                            ldi(2, 0x1F), mtsr("fcsr", 2),
                            mfsr(0, "fcsr"), halt()]
    m, _ = run_words(prog, data=[(HANDLER_PA, wbytes(cause_handler()))])
    # halt() traps PRIV from user, but fcsr write/read went through
    assert m.regs[0] == 0x1F
    assert m.regs[10] == E.CAUSES["PRIV"]


def test_cycle_write_priv_even_supervisor():
    prog = vbase_setup() + [ldi(1, 9), mtsr("cycle", 1), halt()]
    m, _ = run_words(prog, data=[(HANDLER_PA, wbytes(cause_handler()))])
    assert m.regs[10] == E.CAUSES["PRIV"]


def test_mfsr_unlisted_index_illegal():
    prog = vbase_setup() + [asm("MFSR", dst=1, imm=200), halt()]
    m, _ = run_words(prog, data=[(HANDLER_PA, wbytes(cause_handler()))])
    assert m.regs[10] == E.CAUSES["ILLEGAL"]


def test_timer_interrupt():
    loop_pc = E.RESET_PC + 7 * 8
    prog = (vbase_setup()
            + [ldi(1, 20), mtsr("timecmp", 1),
               ldi(1, S | IE), mtsr("status", 1),
               nop(),
               b(0)])                          # spin at loop_pc
    m, out = run_words(prog, data=[(HANDLER_PA, wbytes(cause_handler()))])
    assert out == "halt"
    assert m.regs[10] == E.CAUSES["TIMER"]
    assert m.regs[12] == loop_pc              # epc = next insn to execute
    assert m.cycle >= 20


def test_interrupt_masked_when_ie0():
    prog = (vbase_setup()
            + [ldi(1, 5), mtsr("timecmp", 1)]
            + [nop()] * 10 + [halt()])
    m, out = run_words(prog, data=[(HANDLER_PA, wbytes(cause_handler()))])
    assert out == "halt"                      # never delivered
    assert m.regs[10] == 0


def test_predicated_false_cannot_fault():
    npred = pred(1)                           # p1 == 0 at reset -> false
    squashed_illegal = 0 | (npred << 8)       # opcode 0, pred (p1)
    prog = li128(2, 1 << 90) + [
        syscall(p=npred),                     # squashed SYSCALL
        squashed_illegal,                     # squashed illegal opcode
        lds(3, 2, 0, w=64, p=npred),          # squashed unmapped load
        halt()]
    m, out = run_words(prog)
    assert out == "halt"
    assert not m.triple_fault
    assert m.cycle == 10                      # every squash retired 1 cycle
    assert m.regs[3] == 0


def test_iret_at_tl0_saturates():
    target = 0x4000
    prog = [ldi(1, S | PS), mtsr("status", 1),   # PS=1 so S survives IRET
            ldi(1, target), mtsr("epc0", 1), iret()]
    m, out = run_words(prog, data=[(target, wbytes([halt()]))])
    assert out == "halt"
    assert not m.triple_fault
    assert m.tl == 0


def test_wfi_timer_jump_and_delivery():
    prog = (vbase_setup()
            + [ldi(1, 1000), mtsr("timecmp", 1),
               ldi(1, S | IE), mtsr("status", 1),
               asm("WFI"),
               nop(), halt()])
    m, out = run_words(prog, data=[(HANDLER_PA, wbytes(cause_handler()))])
    assert out == "halt"
    assert m.regs[10] == E.CAUSES["TIMER"]
    wfi_pc = E.RESET_PC + 6 * 8
    assert m.regs[12] == wfi_pc + 8           # epc = insn after WFI
    assert m.cycle >= 1000


def test_wfi_ie0_continues_after_jump():
    # root SPEC-ISSUES 20 freeze: jump to timecmp (50), then +1 for
    # WFI's own retire -> resume at 51; HALT retires -> 52
    prog = [ldi(1, 50), mtsr("timecmp", 1), asm("WFI"), halt()]
    m, out = run_words(prog)
    assert out == "halt"
    assert m.cycle == 52


def test_wfi_deadlock_cycle_is_wfi_retire():
    m, out = run_words([asm("WFI"), halt()])
    assert out == "halt"
    assert m.cycle == 1                       # nothing after the WFI retire


def test_wfi_in_user_mode_privs():
    prog = vbase_setup() + [ldi(1, 0), mtsr("status", 1), asm("WFI"),
                            halt()]
    m, _ = run_words(prog, data=[(HANDLER_PA, wbytes(cause_handler()))])
    assert m.regs[10] == E.CAUSES["PRIV"]


# ------------------------------------------------- TL writability matrix
# ISA-SPEC 7.2/7.3/7.4: TL is MTSR-writable; delivery banks and IRET bank
# selection follow the *current* TL, however it got there.

def tl_bits(v):
    return v << E.STATUS_BITS["TL_LSB"]


def test_mtsr_tl2_then_fault_triple_faults():
    # software parks TL at 2: the very next fault is a triple fault --
    # machine halts, no sreg written
    prog = (vbase_setup() + dfbase_setup()
            + [ldi(1, S | tl_bits(2)), mtsr("status", 1),
               syscall(), halt()])
    m, out = run_words(prog, data=[(HANDLER_PA, wbytes(cause_handler())),
                                   (DF_PA, wbytes(cause_handler()))])
    assert out == "halt"
    assert m.triple_fault
    assert m.sregs[E.SREGS["cause0"]] == 0    # nothing was delivered
    assert m.sregs[E.SREGS["cause1"]] == 0
    assert m.tl == 2


def test_mtsr_tl1_next_fault_is_double():
    # TL=1 by MTSR, never trapped: the next fault delivers to bank 1 at
    # dfbase, bank 0 untouched
    df = [mfsr(10, "cause0"), mfsr(11, "cause1"), mfsr(13, "epc1"), halt()]
    prog = (vbase_setup() + dfbase_setup()
            + [ldi(1, S | tl_bits(1)), mtsr("status", 1),
               syscall(), halt()])
    m, out = run_words(prog, data=[(HANDLER_PA, wbytes([0])),
                                   (DF_PA, wbytes(df))])
    assert out == "halt"
    assert m.regs[10] == 0                    # bank 0 never written
    assert m.regs[11] == E.CAUSES["SYSCALL"]
    assert m.regs[13] == E.RESET_PC + 6 * 8   # the SYSCALL itself
    assert m.tl == 2


STAGE1_PA = 0x4000
STAGE2_PA = 0x5000


def test_iret_bank_selection_at_tl2():
    # TL=2 by MTSR: first IRET takes epc1 (bank 1) and drops to TL=1,
    # second takes epc0 (bank 0) and drops to TL=0
    stage1 = [alui("ADD", 5, 31, 1), iret()]
    stage2 = [alui("ADD", 6, 31, 2), halt()]
    prog = [ldi(1, STAGE1_PA), mtsr("epc1", 1),
            ldi(1, STAGE2_PA), mtsr("epc0", 1),
            ldi(1, S | PS | tl_bits(2)), mtsr("status", 1),
            iret()]
    m, out = run_words(prog, data=[(STAGE1_PA, wbytes(stage1)),
                                   (STAGE2_PA, wbytes(stage2))])
    assert out == "halt"
    assert m.regs[5] == 1
    assert m.regs[6] == 2
    assert m.tl == 0


def test_tl3_via_mtsr_iret_uses_bank1_delivery_triple_faults():
    # emu-py SPEC-ISSUES 12: TL=3 is reachable only by MTSR. IRET at TL=3
    # selects bank 1 (TL >= 2) and decrements to 2; a fault at TL=3
    # triple-faults. Pin both.
    stage1 = [alui("ADD", 5, 31, 1),
              syscall(),                       # TL now 2 -> triple fault
              halt()]
    prog = (vbase_setup() + dfbase_setup()
            + [ldi(1, STAGE1_PA), mtsr("epc1", 1),
               ldi(1, S | PS | tl_bits(3)), mtsr("status", 1),
               iret()])
    m, out = run_words(prog, data=[(STAGE1_PA, wbytes(stage1)),
                                   (HANDLER_PA, wbytes(cause_handler())),
                                   (DF_PA, wbytes(cause_handler()))])
    assert out == "halt"
    assert m.regs[5] == 1                     # bank-1 target reached
    assert m.triple_fault
    assert m.tl == 2


def test_double_fault_overwrites_pie_ps():
    # single copy of PIE/PS (ISA-SPEC 7.2): first trap saves IE=1 into
    # PIE; the handler faults with IE=0, overwriting PIE with 0
    df = [mfsr(15, "status"), halt()]
    prog = (vbase_setup() + dfbase_setup()
            + [ldi(1, S | IE), mtsr("status", 1),
               syscall(), halt()])
    m, out = run_words(prog, data=[(HANDLER_PA, wbytes([0])),
                                   (DF_PA, wbytes(df))])
    assert out == "halt"
    st = m.regs[15]
    assert (st >> E.STATUS_BITS["PIE"]) & 1 == 0   # 1 was overwritten
    assert (st >> E.STATUS_BITS["PS"]) & 1 == 1
    assert (st >> E.STATUS_BITS["IE"]) & 1 == 0


def test_priv_iret_from_user():
    prog = vbase_setup() + [ldi(1, 0), mtsr("status", 1), iret(), halt()]
    m, _ = run_words(prog, data=[(HANDLER_PA, wbytes(cause_handler()))])
    assert m.regs[10] == E.CAUSES["PRIV"]
    assert m.regs[12] == E.RESET_PC + 4 * 8


def test_priv_invtp_from_user():
    prog = (vbase_setup()
            + [ldi(1, 0), mtsr("status", 1), asm("INVTP"), halt()])
    m, _ = run_words(prog, data=[(HANDLER_PA, wbytes(cause_handler()))])
    assert m.regs[10] == E.CAUSES["PRIV"]
    assert m.regs[12] == E.RESET_PC + 4 * 8


# --------------------------------------- interrupt priority and WFI edges
DEVBASE = 0x100000


def test_timer_beats_extint_when_both_pending():
    """ISA-SPEC 7.5: fixed priority timer-then-external. Device pending
    from cycle 0, timer from cycle 1; at the first IE=1 boundary both are
    pending -- TIMER must be delivered first, EXTINT right after IRET."""
    from helpers import QueueDevice, alur
    dev = QueueDevice(DEVBASE)
    handler = [mfsr(9, "cause0"),
               cmpi("CMPEQ", 1, 13, 0, w=64),          # p1: first entry
               alur("OR", 10, 9, 31, p=pred(1)),       # r10 = first cause
               alur("OR", 11, 9, 31, p=pred(1, negate=True)),
               alui("ADD", 13, 13, 1, w=64),
               ldi(1, 0), mtsr("timecmp", 1),          # disarm timer
               cmpi("CMPEQ", 2, 13, 2, w=64),          # p2: both taken
               ldi(3, DEVBASE),
               lds(4, 3, 0, w=64, p=pred(2)),          # drain device
               halt(p=pred(2)),
               iret()]
    prog = (vbase_setup()
            + [ldi(1, 1), mtsr("timecmp", 1),
               ldi(1, S | IE), mtsr("status", 1),
               b(0)])
    m, out = run_words(prog, data=[(HANDLER_PA, wbytes(handler))],
                       devices=[dev], events=[(0, 0, b"k")])
    assert out == "halt"
    assert m.regs[10] == E.CAUSES["TIMER"]
    assert m.regs[11] == E.CAUSES["EXTINT"]
    assert not dev.queue                       # handler drained it


def test_extint_level_triggered_until_drained():
    """ISA-SPEC 7.5: external is level-triggered. A handler that IRETs
    without draining the device is re-entered immediately; only the
    draining load stops delivery."""
    from helpers import QueueDevice
    dev = QueueDevice(DEVBASE)
    handler = [alui("ADD", 13, 13, 1, w=64),           # entry counter
               cmpi("CMPLT", 1, 13, 3, w=64),          # p1: fewer than 3
               iret(p=pred(1)),                        # bounce back undrained
               ldi(3, DEVBASE), lds(4, 3, 0, w=64),    # third entry: drain
               iret()]
    prog = (vbase_setup()
            + [ldi(1, S | IE), mtsr("status", 1),
               nop(), nop(), nop(), nop(), nop(),
               halt()])
    m, out = run_words(prog, data=[(HANDLER_PA, wbytes(handler))],
                       devices=[dev], events=[(0, 0, b"k")])
    assert out == "halt"
    assert not m.triple_fault
    assert m.regs[13] == 3                     # exactly 3 deliveries
    assert m.regs[4] == 1                      # drain saw 1 queued payload


def test_wfi_ie0_time_jumps_then_falls_through():
    """ISA-SPEC 7.6: with IE=0 the WFI still jumps virtual time to the
    pending point but delivers nothing; execution continues at the next
    instruction."""
    prog = [ldi(1, 500), mtsr("timecmp", 1),   # armed; IE stays 0 (reset)
            asm("WFI"),
            ldi(0, 0x77), halt()]
    m, out = run_words(prog)
    assert out == "halt"
    assert not m.triple_fault
    assert m.regs[0] == 0x77                   # fell through, no delivery
    assert m.cycle >= 500                      # time really jumped
    assert m.sregs[E.SREGS["cause0"]] == 0     # nothing was ever delivered


def test_wfi_deadlock_halts():
    """ISA-SPEC 7.6: no timer armed, no events, no device -> no future
    cycle can make an interrupt pending. WFI halts the machine (loudly),
    it does not spin."""
    prog = [ldi(0, 0x2BAD), asm("WFI"), ldi(0, 0), halt()]
    m, out = run_words(prog)
    assert out == "halt"
    assert not m.triple_fault
    assert m.regs[0] == 0x2BAD                 # never reached the ldi after


# ------------------------------------------- root SPEC-ISSUES 16 and 17

def test_mfsr_cycle_reads_before_own_increment():
    """Root SPEC-ISSUES 16: MFSR of cycle sees the count of instructions
    retired *before* it - its own increment lands after the read. The
    first instruction therefore reads 0, the second reads 1."""
    prog = [mfsr(0, "cycle"), mfsr(1, "cycle"), halt()]
    m, out = run_words(prog)
    assert out == "halt"
    assert m.regs[0] == 0
    assert m.regs[1] == 1


def test_faulting_insn_emits_no_exec_record():
    """Root SPEC-ISSUES 17: a faulting instruction does not retire, so it
    emits no EXEC record - the TRAP record (epc pointing at it) is its
    only trace footprint."""
    from helpers import OrderedTracer
    tr = OrderedTracer()
    prog = vbase_setup() + [asm("ILLEGAL"), halt()]
    m, out = run_words(prog, data=[(HANDLER_PA, wbytes(cause_handler()))],
                       tracer=tr)
    assert out == "halt"
    fault_pc = E.RESET_PC + 2 * 8
    assert m.regs[10] == E.CAUSES["ILLEGAL"]
    exec_pcs = [r[2] for r in tr.recs if r[0] == "exec"]
    assert fault_pc not in exec_pcs
    traps = [r for r in tr.recs if r[0] == "trap"]
    assert len(traps) == 1 and traps[0][3] == fault_pc   # epc = faulting pc
