"""Test helpers: assemble instruction words programmatically from
encoding.py (the sanctioned bootstrap until asm/ lands on the toolchain
branch), and run programs in-process or via the CLI."""

import os
import subprocess
import sys

import encoding as E
import machine
import mem as mem_

MASK128 = (1 << 128) - 1
EMU = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "sahara-emu-py")

W = {32: 0, 64: 1, 128: 2}          # ALU/CMP/ATOMIC width codes
MW = {8: 0, 16: 1, 32: 2, 64: 3}    # LDS/LDZ/ST width codes


def field(name, val):
    lsb, width = E.FIELDS[name]
    v = val & ((1 << width) - 1)
    return v << lsb


def asm(name, dst=0, src1=0, src2=0, src3=0, mod=0, width=0, imm=0,
        pred=0, iform=False):
    opcode, fam, _ops = E.OPCODES[name]
    if iform:
        assert E.FAMILIES[fam]["iflag"], name
        opcode += 1
    word = (field("opcode", opcode) | field("pred", pred) | field("dst", dst)
            | field("src1", src1) | field("src2", src2) | field("src3", src3)
            | field("mod", mod) | field("width", width) | field("imm", imm))
    return word


def pred(idx, negate=False):
    """pred-field encoding: bit 0 polarity, bits 3:1 index."""
    return (idx << 1) | (1 if negate else 0)


def mod_shl(n):
    return (n << 2) | 1


def mod_sxt(n):
    return (n << 2) | 2


def mod_zxt(n):
    return (n << 2) | 3


# ---------------------------------------------------------- mnemonics
def alui(name, dst, src1, imm, w=128, p=0):
    return asm(name, dst=dst, src1=src1, imm=imm, width=W[w], pred=p,
               iform=True)


def alur(name, dst, src1, src2, w=128, mod=0, p=0, src3=0):
    return asm(name, dst=dst, src1=src1, src2=src2, src3=src3, width=W[w],
               mod=mod, pred=p)


def cmpi(name, pd, src1, imm, w=128, p=0):
    return asm(name, dst=pd, src1=src1, imm=imm, width=W[w], pred=p,
               iform=True)


def cmpr(name, pd, src1, src2, w=128, mod=0, p=0):
    return asm(name, dst=pd, src1=src1, src2=src2, width=W[w], mod=mod,
               pred=p)


def ldi(dst, imm, p=0):
    return asm("LDI", dst=dst, imm=imm, pred=p)


def shori(dst, src1, imm, p=0):
    return asm("SHORI", dst=dst, src1=src1, imm=imm, pred=p)


def li128(dst, value):
    """LDI + 5x SHORI: exact 128-bit constant (ISA-SPEC 5.6)."""
    value &= MASK128
    chunks = [(value >> (22 * i)) & 0x3FFFFF for i in range(5, -1, -1)]
    words = [ldi(dst, chunks[0])]
    for c in chunks[1:]:
        words.append(shori(dst, dst, c))
    return words


def lds(dst, base, imm=0, w=64, src2=0, mod=0, p=0):
    return asm("LDS", dst=dst, src1=base, src2=src2, mod=mod, imm=imm,
               width=MW[w], pred=p)


def ldz(dst, base, imm=0, w=64, src2=0, mod=0, p=0):
    return asm("LDZ", dst=dst, src1=base, src2=src2, mod=mod, imm=imm,
               width=MW[w], pred=p)


def ld128(dst, base, imm=0, src2=0, mod=0, p=0):
    return asm("LD128", dst=dst, src1=base, src2=src2, mod=mod, imm=imm,
               pred=p)


def st(src3, base, imm=0, w=64, src2=0, mod=0, p=0):
    return asm("ST", src3=src3, src1=base, src2=src2, mod=mod, imm=imm,
               width=MW[w], pred=p)


def st128(src3, base, imm=0, src2=0, mod=0, p=0):
    return asm("ST128", src3=src3, src1=base, src2=src2, mod=mod, imm=imm,
               pred=p)


def b(disp, p=0):
    return asm("B", imm=disp, pred=p)


def jal(dst, disp, p=0):
    return asm("JAL", dst=dst, imm=disp, pred=p)


def jalr(dst, src1, imm=0, p=0):
    return asm("JALR", dst=dst, src1=src1, imm=imm, pred=p)


def mfsr(dst, name, p=0):
    return asm("MFSR", dst=dst, imm=E.SREGS[name], pred=p)


def mtsr(name, src1, p=0):
    return asm("MTSR", src1=src1, imm=E.SREGS[name], pred=p)


def syscall(p=0):
    return asm("SYSCALL", pred=p)


def iret(p=0):
    return asm("IRET", pred=p)


def halt(p=0):
    return asm("HALT", pred=p)


def nop():
    return asm("OR", dst=31, src1=31, src2=31, width=W[128])


# ------------------------------------------------------- page tables
def pt_leaf(frame, r=1, w=1, x=0, u=0):
    return (frame | E.PTE_TYPE_LEAF | (r << E.PTE_BITS["R"])
            | (w << E.PTE_BITS["W"]) | (x << E.PTE_BITS["X"])
            | (u << E.PTE_BITS["U"]))


def pt_table(child_pa):
    return child_pa | E.PTE_TYPE_TABLE


def pt_node(shift, prefix, prefix_mask, entries):
    blob = bytearray(E.NODE_BYTES)
    blob[0:8] = shift.to_bytes(8, "little")
    blob[8:24] = prefix.to_bytes(16, "little")
    blob[24:40] = prefix_mask.to_bytes(16, "little")
    for idx, ent in entries.items():
        off = E.NODE_HEADER_BYTES + idx * E.NODE_ENTRY_BYTES
        blob[off:off + 16] = ent.to_bytes(16, "little")
    return bytes(blob)


# ----------------------------------------------------- ordered tracer
class OrderedTracer:
    """Records every trace record in stream order; enough tracer surface
    for Machine. Lets tests assert record *ordering* (e.g. no TRAP
    between an atomic's MEMR/MEMW pair)."""
    level = 2

    def __init__(self):
        self.recs = []

    def exec_(self, cycle, pc, insn, wb, flags, pred_wb):
        self.recs.append(("exec", cycle, pc, insn, wb, flags, pred_wb))

    def memw(self, cycle, ea, size, new):
        self.recs.append(("memw", cycle, ea, size, new))

    def memr(self, cycle, ea, size, val):
        self.recs.append(("memr", cycle, ea, size, val))

    def trap(self, cycle, cause, epc, baddr, tl_after):
        self.recs.append(("trap", cycle, cause, epc, baddr, tl_after))

    def event(self, cycle, device, payload):
        self.recs.append(("event", cycle, device, payload))

    def devw(self, cycle, ea, size, val):
        self.recs.append(("devw", cycle, ea, size, val))

    def kinds(self):
        return [r[0] for r in self.recs]


# ------------------------------------------------------ queue device
class QueueDevice(mem_.Device):
    """Minimal EXTINT source shaped like the reference input device
    (ISA-SPEC 7.5): level-triggered while its queue is non-empty, drained
    by a load. Stores are recorded (with a pre-store RAM peek so tests
    can observe the 9.2 release-drain ordering)."""

    def __init__(self, base, size=8, on_store=None):
        super().__init__(base, size)
        self.queue = []
        self.stores = []
        self.on_store = on_store        # callback(): sampled at store time

    def event(self, payload):
        self.queue.append(payload)
        return payload

    def pending(self):
        return bool(self.queue)

    def load(self, off, size):
        n = len(self.queue)
        self.queue.clear()
        return n

    def store(self, off, size, val):
        self.stores.append((off, size, val,
                            self.on_store() if self.on_store else None))


# ------------------------------------------------------- trap harness
HANDLER_PA = 0x2000
DF_PA = 0x3000


def wbytes(words):
    return b"".join(w.to_bytes(8, "little") for w in words)


def cause_handler():
    """Standard trap handler: r10=cause0, r11=baddr0, r12=epc0, halt."""
    return [mfsr(10, "cause0"), mfsr(11, "baddr0"), mfsr(12, "epc0"), halt()]


def vbase_setup(pa=HANDLER_PA):
    return [ldi(21, pa), mtsr("vbase", 21)]


def dfbase_setup(pa=DF_PA):
    return [ldi(22, pa), mtsr("dfbase", 22)]


# ------------------------------------------------------------ running
def make_machine(words, ram=1 << 24, data=None, check_invtp=False,
                 tracer=None, events=(), devorder=None, devices=(),
                 dev_base=None, event_devices=None, with_dma=False):
    phys = mem_.PhysMap(ram, devorder=devorder, dev_base=dev_base)
    for dev in devices:
        phys.add_device(dev)
    prog = b"".join(w.to_bytes(8, "little") for w in words)
    phys.write_raw(E.RESET_PC, prog)
    for pa, blob in (data or []):
        phys.write_raw(pa, blob)
    if event_devices is None:
        event_devices = devices
    dma = None
    if with_dma:
        # Dma needs the phys it transfers through, so the helper owns
        # construction; the test reaches it as m.dma.
        import devices as devices_mod
        dma = devices_mod.Dma(devices_mod.DMA_BASE, devices_mod.DMA_SIZE,
                              phys)
        phys.add_device(dma)
    return machine.Machine(phys, tracer=tracer, check_invtp=check_invtp,
                           events=events, event_devices=event_devices,
                           dma=dma)


def run_words(words, maxcycles=100_000, **kw):
    m = make_machine(words, **kw)
    outcome = m.run(maxcycles)
    return m, outcome


def run_cli(img_path, *extra, cwd=None):
    return subprocess.run([sys.executable, EMU, str(img_path), *extra],
                          capture_output=True, text=False, timeout=120,
                          cwd=cwd)
