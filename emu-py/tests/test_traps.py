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
    prog = [ldi(1, 50), mtsr("timecmp", 1), asm("WFI"), halt()]
    m, out = run_words(prog)
    assert out == "halt"
    assert m.cycle == 51                      # jump to 50, HALT retires


def test_wfi_deadlock_halts():
    m, out = run_words([asm("WFI"), halt()])
    assert out == "halt"
    assert m.cycle == 1                       # nothing after the WFI retire


def test_wfi_in_user_mode_privs():
    prog = vbase_setup() + [ldi(1, 0), mtsr("status", 1), asm("WFI"),
                            halt()]
    m, _ = run_words(prog, data=[(HANDLER_PA, wbytes(cause_handler()))])
    assert m.regs[10] == E.CAUSES["PRIV"]
