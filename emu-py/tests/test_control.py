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


class _RecordingTracer:
    """Captures exec_ records; enough tracer surface for Machine."""
    level = 2

    def __init__(self):
        self.execs = []

    def exec_(self, cycle, pc, insn, wb, flags, pred_wb):
        self.execs.append((cycle, flags, pred_wb))

    def memw(self, *a):
        pass

    def memr(self, *a):
        pass

    def trap(self, *a):
        pass

    def event(self, *a):
        pass

    def devw(self, *a):
        pass


def test_pred_wb_traces_full_predicate_file():
    # Toolchain SPEC-ISSUES reading 1 (emulators must match): pred_wb is
    # the full 8-bit predicate file after the write, for compares AND PWR.
    import trc
    t = _RecordingTracer()
    prog = [
        cmpi("CMPEQ", 1, 31, 0),              # p1 := 1  -> file 0b00000011
        cmpi("CMPEQ", 2, 31, 1),              # p2 := 0  -> file 0b00000011
        ldi(3, 0b10101010),
        asm("PWR", src1=3),                   # file 0b10101011 (p0 stays 1)
        halt(),
    ]
    run_words(prog, tracer=t)
    predrecs = [(c, pw) for c, fl, pw in t.execs if fl & trc.F_WROTE_PRED]
    assert predrecs == [(0, 0b00000011), (1, 0b00000011), (3, 0b10101011)]


def test_pred_wb_compare_to_p0_discarded():
    import trc
    t = _RecordingTracer()
    prog = [cmpi("CMPEQ", 0, 31, 0), halt()]  # dst p0: write discarded
    run_words(prog, tracer=t)
    assert not any(fl & trc.F_WROTE_PRED for _, fl, _ in t.execs)


def test_all_16_pred_encodings():
    # C6: every (index, polarity) pair. File set to 0b10101011 via PWR,
    # then 16 predicated ADDs each contribute a distinct bit to r1;
    # exactly one of each +/- pair must fire, per polarity semantics.
    file = 0b10101010                          # p0 forced 1 -> 0b10101011
    prog = [ldi(3, file), asm("PWR", src1=3), ldi(1, 0)]
    for idx in range(8):
        prog.append(alui("ADD", 1, 1, 1 << (2 * idx), p=pred(idx)))
        prog.append(alui("ADD", 1, 1, 1 << (2 * idx + 1),
                         p=pred(idx, negate=True)))
    prog.append(halt())
    m, out = run_words(prog)
    assert out == "halt"
    want = 0
    effective = file | 1
    for idx in range(8):
        want |= 1 << (2 * idx) if (effective >> idx) & 1 \
            else 1 << (2 * idx + 1)
    assert m.regs[1] == want
