"""CLI contract, determinism double-runs, decoder fuzz."""

import io
import random

import encoding as E
import image
import trc
from helpers import (alui, asm, b, cmpi, halt, iret, ldi, lds, li128, mfsr,
                     mtsr, pred, run_cli, run_words, st, syscall,
                     vbase_setup, wbytes)


def write_img(tmp_path, name, segments, entry=E.RESET_PC):
    p = tmp_path / name
    p.write_bytes(image.build_image(segments, entry))
    return p


def test_halt_line_exact(tmp_path):
    magic = 0xDEADBEEF_CAFEF00D_01234567_89ABCDEF
    prog = li128(0, magic) + [halt()]
    img = write_img(tmp_path, "t.img", [(E.RESET_PC, wbytes(prog))])
    r = run_cli(img)
    assert r.returncode == 0, r.stderr
    assert r.stdout == f"HALT r0={magic:032x}\n".encode()
    assert r.stderr == b""


def test_maxcycles_exit(tmp_path):
    img = write_img(tmp_path, "spin.img", [(E.RESET_PC, wbytes([b(0)]))])
    r = run_cli(img, "--maxcycles", "1000")
    assert r.returncode == 2
    assert r.stdout == b"MAXCYCLES\n"


def _busy_program():
    """Traps, memory traffic, FP flags, a loop — determinism fodder."""
    handler = [mfsr(12, "epc0"), alui("ADD", 12, 12, 8),
               mtsr("epc0", 12), iret()]
    prog = (vbase_setup()
            + [ldi(1, 0x8000), ldi(2, 0)]
            # loop: st r2; ld r3; r2 += 1; cmplt p1, r2, 20; (p1) b loop
            + [st(2, 1, 0, w=64), lds(3, 1, 0, w=64),
               alui("ADD", 2, 2, 1),
               cmpi("CMPLT", 1, 2, 20, w=64),
               b(-4, p=pred(1))]
            + [syscall()]
            + li128(4, 0x3FF0000000000000)     # 1.0
            + li128(5, 0)
            + [asm("FDIV", dst=6, src1=4, src2=5, width=1)]   # DZ flag
            + li128(0, 0x600D600D)
            + [halt()])
    return prog, handler


def test_determinism_double_run(tmp_path):
    prog, handler = _busy_program()
    img = write_img(tmp_path, "busy.img",
                    [(E.RESET_PC, wbytes(prog)), (0x2000, wbytes(handler))])
    outs = []
    for i in range(2):
        t = tmp_path / f"run{i}.trc"
        r = run_cli(img, "--trace", str(t), "--trace-level", "2",
                    "--check-invtp")
        assert r.returncode == 0, r.stderr
        outs.append((r.stdout, t.read_bytes()))
    assert outs[0][0] == outs[1][0]
    assert outs[0][1] == outs[1][1]           # byte-identical traces
    assert len(outs[0][1]) > 100


def test_trace_structure(tmp_path):
    prog, handler = _busy_program()
    img = write_img(tmp_path, "busy2.img",
                    [(E.RESET_PC, wbytes(prog)), (0x2000, wbytes(handler))])
    t = tmp_path / "out.trc"
    r = run_cli(img, "--trace", str(t), "--trace-level", "1")
    assert r.returncode == 0, r.stderr
    recs = list(trc.read_records(io.BytesIO(t.read_bytes())))
    assert recs[0][0] == trc.T_META
    types = {typ for typ, _ in recs}
    assert trc.T_EXEC in types
    assert trc.T_TRAP in types
    assert trc.T_MEMW in types
    assert trc.T_MEMR not in types            # level 1 excludes MEMR
    # EXEC records carry strictly increasing cycles
    cycles = [int.from_bytes(p[0:8], "little")
              for typ, p in recs if typ == trc.T_EXEC]
    assert cycles == sorted(cycles)
    assert len(set(cycles)) == len(cycles)


def test_fuzz_decoder_inprocess():
    """Random 64-bit words must never crash: execute or trap ILLEGAL.
    Any Python exception escaping the emulator fails this test."""
    rng = random.Random(0x5A11A7A)
    for _ in range(300):
        word = rng.getrandbits(64)
        _m, out = run_words([word], maxcycles=200)
        assert out in ("halt", "maxcycles")
    for _ in range(60):
        words = [rng.getrandbits(64) for _ in range(20)]
        _m, out = run_words(words, maxcycles=500)
        assert out in ("halt", "maxcycles")


def test_fuzz_decoder_cli(tmp_path):
    rng = random.Random(42)
    for i in range(15):
        word = rng.getrandbits(64)
        img = write_img(tmp_path, f"fuzz{i}.img",
                        [(E.RESET_PC, wbytes([word]))])
        r = run_cli(img, "--maxcycles", "300")
        assert r.returncode in (0, 2), (word, r.stderr)


def test_ram_flag(tmp_path):
    # a store beyond --ram traps DEVERR -> vbase 0 -> triple fault halt
    prog = [ldi(1, 1 << 20), ldi(2, 1), st(2, 1, 0, w=64), halt()]
    img = write_img(tmp_path, "ram.img", [(E.RESET_PC, wbytes(prog))])
    r = run_cli(img, "--ram", str(1 << 20), "--maxcycles", "100")
    assert r.returncode == 0                  # triple fault halts
    r2 = run_cli(img, "--maxcycles", "100")   # default 256 MB: fine
    assert r2.returncode == 0
    assert r2.stdout.startswith(b"HALT r0=")
