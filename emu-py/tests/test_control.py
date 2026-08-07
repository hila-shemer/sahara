"""C6-shaped smoke tests: control flow, predication, PRD/PWR."""

import encoding as E
from helpers import (alui, asm, b, cmpi, halt, jal, jalr, ldi, nop, pred,
                     run_words)


def test_branch_loop():
    # r1 = 3; loop: r1 -= 1; r0 += 10; cmpeq p1, r1, 0; (!p1) b loop
    prog = [
        ldi(1, 3),
        alui("SUB", 1, 1, 1),
        alui("ADD", 0, 0, 10),
        cmpi("CMPEQ", 1, 1, 0),
        b(-3, p=pred(1, negate=True)),
        halt(),
    ]
    m, out = run_words(prog)
    assert out == "halt"
    assert m.regs[0] == 30
    assert m.regs[1] == 0


def test_branch_displacement_counts_instructions():
    prog = [b(2), halt(), alui("ADD", 0, 31, 7), halt()]
    m, _ = run_words(prog)
    assert m.regs[0] == 7


def test_jal_writes_link():
    prog = [jal(5, 2), halt(), alui("ADD", 0, 31, 1), halt()]
    m, _ = run_words(prog)
    assert m.regs[0] == 1
    assert m.regs[5] == E.RESET_PC + 8       # pc + 8


def test_jalr_byte_target_and_link():
    target = E.RESET_PC + 3 * 8
    prog = [ldi(1, target), jalr(5, 1), halt(),
            alui("ADD", 0, 31, 9), halt()]
    m, _ = run_words(prog)
    assert m.regs[0] == 9
    assert m.regs[5] == E.RESET_PC + 16


def test_predication_polarity_and_squash_cycle():
    prog = [
        cmpi("CMPEQ", 1, 31, 0),                       # p1 = 1
        alui("ADD", 0, 31, 1, p=pred(1)),              # executes
        alui("ADD", 0, 0, 10, p=pred(1, negate=True)),  # squashed
        alui("ADD", 2, 31, 5, p=pred(0)),              # p0: always
        halt(),
    ]
    m, _ = run_words(prog)
    assert m.regs[0] == 1
    assert m.regs[2] == 5
    assert m.cycle == 5                       # squashed insn still 1 cycle


def test_predicated_false_branch_falls_through():
    prog = [b(2, p=pred(3)), alui("ADD", 0, 31, 4), halt(), halt()]
    m, _ = run_words(prog)                    # p3 = 0 at reset
    assert m.regs[0] == 4


def test_prd_pwr_roundtrip():
    prog = [
        cmpi("CMPEQ", 1, 31, 0),              # p1 = 1
        cmpi("CMPEQ", 5, 31, 0),              # p5 = 1
        asm("PRD", dst=2),                    # r2 = predicate file
        ldi(3, 0b10001000),                   # p3, p7 (bit0 ignored)
        asm("PWR", src1=3),
        asm("PRD", dst=4),
        halt(),
    ]
    m, _ = run_words(prog)
    assert m.regs[2] == 0b00100011            # p0, p1, p5
    assert m.regs[4] == 0b10001001            # p0 forced 1; p3, p7
    assert m.preds[1] == 0                    # PWR cleared it


def test_pwr_p0_immutable():
    prog = [ldi(1, 0), asm("PWR", src1=1), asm("PRD", dst=0), halt()]
    m, _ = run_words(prog)
    assert m.regs[0] & 1 == 1
