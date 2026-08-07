"""Sahara CPU core — spec-shaped Python. ISA-SPEC.md is the text this file
tries to read like.

All encoding data (fields, opcodes, sregs, causes, MMU constants) comes
from encoding.py; nothing is hardcoded here.
"""

import encoding as E
import mem
import softfloat as sf
import trc

MASK128 = (1 << 128) - 1
IMM_MASK = (1 << E.IMM_BITS) - 1

# execute() returns this as `predw` when the whole predicate file was
# written in place (PWR), as opposed to True/False for a single-bit write.
PRED_FILE_WRITE = object()

# opcode-value -> (name, iform, family, operands), like the C header table
OPTABLE = {}
for _name, (_val, _fam, _ops) in E.OPCODES.items():
    OPTABLE[_val] = (_name, 0, _fam, _ops)
    if E.FAMILIES[_fam]["iflag"]:
        OPTABLE[_val + 1] = (_name, 1, _fam, _ops)

_ST = E.STATUS_BITS
_SREG_NAME = {v: k for k, v in E.SREGS.items()}


def sext(v, bits):
    """Two's-complement sign extension of the low `bits` of v, as a
    python int (may be negative)."""
    v &= (1 << bits) - 1
    if v & (1 << (bits - 1)):
        v -= 1 << bits
    return v


def canon(v, w):
    """Canonical form (ISA-SPEC 3.4): low w bits sign-extended to 128,
    including for unsigned operations. Width 128 is native."""
    v &= (1 << w) - 1
    if w < 128 and v & (1 << (w - 1)):
        v |= MASK128 ^ ((1 << w) - 1)
    return v


class Trap(Exception):
    def __init__(self, cause, baddr=0, epc=None):
        super().__init__(cause)
        self.cause = cause          # name, key of E.CAUSES
        self.baddr = baddr
        self.epc = epc              # None = faulting instruction pc


class CheckFail(Exception):
    """A check-mode assertion (--check-invtp / --check-devorder)."""


class _WalkFault(Exception):
    """Internal: page-table walk failed (no valid mapping / malformed)."""


class Machine:
    def __init__(self, phys, tracer=None, check_invtp=False, events=()):
        self.phys = phys
        self.trace = tracer
        self.regs = [0] * 32
        self.preds = [0] * 8
        self.preds[0] = 1                      # p0 hardwired
        self.sregs = [0] * len(E.SREGS)
        self.sregs[E.SREGS["status"]] = 1 << _ST["S"]   # reset: S=1 (ISA 11)
        self.pc = E.RESET_PC
        self.cycle = 0
        self.halted = False
        self.triple_fault = False
        self.check_invtp = check_invtp
        self.invtp_cache = {}                  # (asid, vpn) -> (frame, perms)
        self.events = sorted(events)           # [(cycle, device_idx, bytes)]

    # ------------------------------------------------------------- state
    def rreg(self, i):
        return 0 if i == 31 else self.regs[i]

    def wreg(self, i, v):
        if i == 31:
            return False                        # writes discarded
        self.regs[i] = v & MASK128
        return True

    def wpred(self, i, v):
        i &= 7
        if i == 0:
            return False                        # p0 immutable
        self.preds[i] = 1 if v else 0
        return True

    @property
    def status(self):
        return self.sregs[E.SREGS["status"]]

    @status.setter
    def status(self, v):
        self.sregs[E.SREGS["status"]] = v & 0x7F   # defined bits only

    def stbit(self, name):
        return (self.status >> _ST[name]) & 1

    def set_stbit(self, name, v):
        b = 1 << _ST[name]
        self.status = (self.status & ~b) | (b if v else 0)

    @property
    def tl(self):
        return (self.status >> _ST["TL_LSB"]) & ((1 << E.TL_BITS) - 1)

    @tl.setter
    def tl(self, v):
        m = ((1 << E.TL_BITS) - 1) << _ST["TL_LSB"]
        self.status = (self.status & ~m) | ((v << _ST["TL_LSB"]) & m)

    def sreg_read(self, idx):
        if idx == E.SREGS["cycle"]:
            return self.cycle
        return self.sregs[idx]

    def sreg_write(self, idx, v):
        if idx == E.SREGS["status"]:
            self.status = v
        elif idx == E.SREGS["fcsr"]:
            self.sregs[idx] = v & 0xFF          # flags 4:0 + rm 7:5
        else:
            self.sregs[idx] = v & MASK128

    # ----------------------------------------------------------- events
    def process_events(self):
        while self.events and self.events[0][0] <= self.cycle:
            ecycle, dev_idx, payload = self.events.pop(0)
            if dev_idx >= len(self.phys.devices):
                raise RuntimeError(
                    f"event for nonexistent device {dev_idx} at cycle "
                    f"{ecycle}")
            if self.trace:
                self.trace.event(ecycle, dev_idx, payload)
            self.phys.devices[dev_idx].event(payload)

    def pending_interrupt(self):
        """Fixed priority: timer, then external (ISA-SPEC 7.5)."""
        timecmp = self.sregs[E.SREGS["timecmp"]]
        if timecmp != 0 and self.cycle >= timecmp:
            return "TIMER"
        if self.phys.any_device_pending():
            return "EXTINT"
        return None

    # ------------------------------------------------------ trap machinery
    def deliver(self, cause, epc, baddr):
        """ISA-SPEC 7.2. Consumes one cycle. TL>=2 -> triple fault: the
        machine halts, no state is written (and no TRAP record: nothing
        was delivered — see SPEC-ISSUES.md)."""
        if self.tl >= 2:
            self.halted = True
            self.triple_fault = True
            return
        new_tl = self.tl + 1
        bank = new_tl - 1
        names = ("epc0", "cause0", "baddr0") if bank == 0 else \
                ("epc1", "cause1", "baddr1")
        self.sregs[E.SREGS[names[0]]] = epc & MASK128
        self.sregs[E.SREGS[names[1]]] = E.CAUSES[cause]
        self.sregs[E.SREGS[names[2]]] = baddr & MASK128
        self.set_stbit("PIE", self.stbit("IE"))
        self.set_stbit("IE", 0)
        self.set_stbit("PS", self.stbit("S"))
        self.set_stbit("S", 1)
        self.tl = new_tl
        self.pc = self.sregs[E.SREGS["vbase" if new_tl == 1 else "dfbase"]]
        if self.trace:
            self.trace.trap(self.cycle, E.CAUSES[cause], epc, baddr, new_tl)
        self.cycle += 1

    def require_supervisor(self):
        if not self.stbit("S"):
            raise Trap("PRIV")

    # ------------------------------------------------------------- MMU
    def translate(self, va, acc):
        """acc in 'X' 'R' 'W'. Returns physical address. ISA-SPEC 8."""
        if not self.stbit("MMU_EN"):
            return va
        vpn = va >> E.PAGE_BITS
        key = (self.sregs[E.SREGS["asid"]], vpn)
        pf = {"X": "PF_FETCH", "R": "PF_LOAD", "W": "PF_STORE"}[acc]
        perm = {"X": "PERM_FETCH", "R": "PERM_LOAD", "W": "PERM_STORE"}[acc]
        try:
            frame, perms = self.walk(vpn)
        except _WalkFault:
            if self.check_invtp and key in self.invtp_cache:
                raise CheckFail(
                    f"stale translation served for va=0x{va:x} "
                    f"(cached mapping exists, walk now faults; missing "
                    f"INVTP?)") from None
            raise Trap(pf, baddr=va) from None
        if self.check_invtp:
            cached = self.invtp_cache.get(key)
            if cached is not None and cached != (frame, perms):
                raise CheckFail(
                    f"stale translation served for va=0x{va:x} "
                    f"(cached {cached} != walked {(frame, perms)}; "
                    f"missing INVTP?)")
            self.invtp_cache[key] = (frame, perms)
        r, w, x, u = perms
        need = {"X": x, "R": r, "W": w}[acc]
        if not need:
            raise Trap(perm, baddr=va)
        if not self.stbit("S") and not u:
            raise Trap(perm, baddr=va)
        return frame | (va & ((1 << E.PAGE_BITS) - 1))

    def _walk_read(self, pa, n):
        """Table reads come from plain RAM; anything else is malformed."""
        if self.phys.device_at(pa) is not None or not self.phys.in_ram(pa, n):
            raise _WalkFault()
        val, _dev = self.phys.load(pa, n)
        return val

    def walk(self, vpn):
        """ISA-SPEC 8.2/8.3. Returns (frame, (r, w, x, u))."""
        node = self.sregs[E.SREGS["ptbase"]]
        for _depth in range((E.VPN_BITS // E.CHUNK_BITS) + 1):
            if node & (E.NODE_ALIGN - 1):
                raise _WalkFault()
            shift = self._walk_read(node, 8)
            prefix = self._walk_read(node + 8, 16)
            prefix_mask = self._walk_read(node + 24, 16)
            reserved = self._walk_read(node + 40, E.NODE_HEADER_BYTES - 40)
            if reserved != 0:
                raise _WalkFault()
            if shift % E.CHUNK_BITS != 0 or shift > E.VPN_BITS - E.CHUNK_BITS:
                raise _WalkFault()
            if (vpn & prefix_mask) != prefix:
                raise _WalkFault()
            idx = (vpn >> shift) & (E.NODE_ENTRIES - 1)
            entry = self._walk_read(
                node + E.NODE_HEADER_BYTES + idx * E.NODE_ENTRY_BYTES,
                E.NODE_ENTRY_BYTES)
            etype = entry & 3
            if etype == E.PTE_TYPE_TABLE:
                node = entry & ~0x3F & MASK128
                continue
            if etype == E.PTE_TYPE_LEAF:
                if shift != 0:
                    raise _WalkFault()
                if (entry >> 6) & 0x3FF:        # bits 15:6 reserved
                    raise _WalkFault()
                perms = tuple((entry >> E.PTE_BITS[b]) & 1
                              for b in ("R", "W", "X", "U"))
                frame = entry & ~((1 << E.PAGE_BITS) - 1) & MASK128
                return frame, perms
            raise _WalkFault()                  # invalid or reserved type
        raise _WalkFault()                      # walk too deep: cyclic table

    # ------------------------------------------------------------ fetch
    def fetch(self):
        if self.pc & (E.INSN_BYTES - 1):
            raise Trap("UNALIGNED", baddr=self.pc)
        pa = self.translate(self.pc, "X")
        if self.phys.device_at(pa) is not None:
            raise Trap("DEVERR", baddr=self.pc)
        try:
            val, _dev = self.phys.load(pa, E.INSN_BYTES)
        except mem.AccessError:
            raise Trap("DEVERR", baddr=self.pc) from None
        return val

    # ------------------------------------------------------------- step
    def step(self):
        """One unit of forward progress: an event batch + either an
        interrupt delivery or one instruction."""
        if self.halted:
            return
        self.process_events()
        if self.stbit("IE"):
            cause = self.pending_interrupt()
            if cause is not None:
                # epc = next instruction to execute (ISA-SPEC 7.1)
                self.deliver(cause, epc=self.pc, baddr=0)
                return
        pc = self.pc
        try:
            insn = self.fetch()
        except Trap as t:
            self.deliver(t.cause, pc if t.epc is None else t.epc, t.baddr)
            return

        f = {name: (insn >> lsb) & ((1 << width) - 1)
             for name, (lsb, width) in E.FIELDS.items()}

        # predication first: a false-predicated instruction retires with
        # no effect and cannot fault — even an illegal opcode (ISA 3.2)
        pol, pidx = f["pred"] & 1, (f["pred"] >> 1) & 7
        if (self.preds[pidx] ^ pol) != 1:
            if self.trace:
                self.trace.exec_(self.cycle, pc, insn, 0, trc.F_SQUASHED, 0)
            self.cycle += 1
            self.pc = (pc + E.INSN_BYTES) & MASK128
            return

        try:
            wb, predw, next_pc, wfi_stall = self.execute(insn, f)
        except Trap as t:
            self.deliver(t.cause, pc if t.epc is None else t.epc, t.baddr)
            return

        flags = 0
        wb_val = 0
        pred_wb = 0
        if wb is not None:
            wrote = self.wreg(f["dst"], wb)
            if wrote:
                flags |= trc.F_WROTE_DST
                wb_val = wb & MASK128
        if predw is not None:
            # PWR has already written the file; compares write one bit here.
            wrote = True if predw is PRED_FILE_WRITE \
                else self.wpred(f["dst"], predw)
            if wrote:
                # pred_wb carries the full predicate file after the write
                # (bit i = P[i]) -- the toolchain's SPEC-ISSUES reading 1,
                # which trace-q's `reg pN` reconstruction depends on.
                flags |= trc.F_WROTE_PRED
                pred_wb = sum(self.preds[i] << i for i in range(8))
        if self.trace:
            self.trace.exec_(self.cycle, pc, insn, wb_val, flags, pred_wb)
        self.cycle += 1
        self.pc = ((pc + E.INSN_BYTES) if next_pc is None else next_pc) \
            & MASK128
        if wfi_stall:
            self.wfi_stall()

    # --------------------------------------------------------- execute
    def execute(self, insn, f):
        """Returns (wb, predw, next_pc, wfi_stall). Raises Trap. Must not
        write any state before its last possible Trap (all checks precede
        all writes, ISA-SPEC 4)."""
        info = OPTABLE.get(f["opcode"])
        if info is None:
            raise Trap("ILLEGAL")
        name, iform, fam, _ops = info
        pc = self.pc

        if fam in ("ALU", "CMP"):
            w = E.FAMILIES[fam]["widths"][f["width"]]
            if w is None:
                raise Trap("ILLEGAL")
            b = (sext(f["imm"], E.IMM_BITS) & MASK128) if iform \
                else self.apply_mod(self.rreg(f["src2"]), f["mod"])
            return self.exec_int(name, fam, w, f, b)

        if fam in ("MEM", "MEM128"):
            return self.exec_mem(name, f)

        if fam == "ATOMIC":
            return self.exec_atomic(name, f)

        if fam == "CTRL":
            disp = sext(f["imm"], E.IMM_BITS)
            if name == "B":
                return None, None, pc + disp * E.INSN_BYTES, False
            if name == "JAL":
                return (pc + E.INSN_BYTES, None,
                        pc + disp * E.INSN_BYTES, False)
            # JALR: byte target, must be 8-aligned
            target = (self.rreg(f["src1"]) + disp) & MASK128
            if target & (E.INSN_BYTES - 1):
                raise Trap("UNALIGNED", baddr=target)
            return pc + E.INSN_BYTES, None, target, False

        if fam == "CONST":
            if name == "LDI":
                return sext(f["imm"], E.IMM_BITS) & MASK128, None, None, False
            if name == "SHORI":
                return ((self.rreg(f["src1"]) << E.IMM_BITS)
                        | f["imm"]) & MASK128, None, None, False
            # LAP
            return (pc + sext(f["imm"], E.IMM_BITS)) & MASK128, None, None, \
                False

        if fam == "PREDF":
            if name == "PRD":
                v = sum(self.preds[i] << i for i in range(8))
                return v, None, None, False
            # PWR: p0 immutable; bits 1..7 taken from src1
            src = self.rreg(f["src1"])
            for i in range(1, 8):
                self.preds[i] = (src >> i) & 1
            return None, PRED_FILE_WRITE, None, False

        if fam == "FP":
            return self.exec_fp(name, f)

        if fam == "FCVT":
            return self.exec_fcvt(name, f)

        # SYS
        return self.exec_sys(name, f)

    def apply_mod(self, v, mod):
        """src2 modifier, ISA-SPEC 3.3."""
        kind, amount = mod & 3, mod >> 2
        if kind == 0:
            if amount != 0:
                raise Trap("ILLEGAL")   # "amount must be 0"; see SPEC-ISSUES
            return v
        if kind == 1:                   # shl
            return (v << amount) & MASK128
        if amount == 0:                 # sxt/zxt amount 0 = no-op
            return v
        if kind == 2:                   # sxt from low `amount` bits
            return sext(v, amount) & MASK128
        return v & ((1 << amount) - 1)  # zxt

    # ---------------------------------------------------- integer ops
    def exec_int(self, name, fam, w, f, b):
        wmask = (1 << w) - 1
        a = self.rreg(f["src1"]) & wmask
        b &= wmask

        def s(v):                       # signed interpretation at width w
            return v - (1 << w) if v & (1 << (w - 1)) else v

        if fam == "CMP":
            res = {
                "CMPEQ": a == b,
                "CMPLT": s(a) < s(b),
                "CMPLTU": a < b,
                "CMPLE": s(a) <= s(b),
                "CMPLEU": a <= b,
            }[name]
            return None, res, None, False

        if name == "ADD":
            r = a + b
        elif name == "SUB":
            r = a - b
        elif name == "AND":
            r = a & b
        elif name == "OR":
            r = a | b
        elif name == "XOR":
            r = a ^ b
        elif name == "SHL":
            r = a << (b % w)
        elif name == "SHR":
            r = a >> (b % w)
        elif name == "SAR":
            r = s(a) >> (b % w)
        elif name == "MUL":
            r = a * b
        elif name == "MULH":
            r = (s(a) * s(b)) >> w
        elif name == "MULHU":
            r = (a * b) >> w
        elif name == "MADD":
            r = a * b + (self.rreg(f["src3"]) & wmask)
        elif name in ("UDIV", "SDIV", "UREM", "SREM"):
            r = self.divide(name, w, a, b, s)
        else:
            raise AssertionError(name)
        return canon(r, w), None, None, False

    @staticmethod
    def divide(name, w, a, b, s):
        """ISA-SPEC 5.1: div-by-zero -> all-ones / dividend; signed
        overflow MIN_w/-1 -> MIN_w / 0. Signed division truncates toward
        zero (see SPEC-ISSUES)."""
        if b == 0:
            return (1 << w) - 1 if name in ("UDIV", "SDIV") else a
        if name == "UDIV":
            return a // b
        if name == "UREM":
            return a % b
        sa, sb = s(a), s(b)
        if sa == -(1 << (w - 1)) and sb == -1:
            return sa if name == "SDIV" else 0
        q = abs(sa) // abs(sb)
        if (sa < 0) != (sb < 0):
            q = -q
        return q if name == "SDIV" else sa - q * sb

    # --------------------------------------------------------- memory
    def data_ea(self, f, with_mod=True):
        ea = self.rreg(f["src1"]) + sext(f["imm"], E.IMM_BITS)
        if with_mod:
            ea += self.apply_mod(self.rreg(f["src2"]), f["mod"])
        return ea & MASK128

    def exec_mem(self, name, f):
        nbytes = 16 if name in ("LD128", "ST128") else \
            E.FAMILIES["MEM"]["widths"][f["width"]] // 8
        ea = self.data_ea(f)
        if ea & (nbytes - 1):
            raise Trap("UNALIGNED", baddr=ea)
        if name in ("LDS", "LDZ", "LD128"):
            pa = self.translate(ea, "R")
            try:
                val, dev = self.phys.load(pa, nbytes)
            except mem.AccessError:
                raise Trap("DEVERR", baddr=ea) from None
            if self.trace:
                self.trace.memr(self.cycle, ea, nbytes, val)
            if name == "LDS":
                val = canon(val, nbytes * 8)
            return val, None, None, False
        # ST / ST128
        val = self.rreg(f["src3"]) & ((1 << (nbytes * 8)) - 1)
        pa = self.translate(ea, "W")
        try:
            dev = self.phys.store(pa, nbytes, val)
        except mem.AccessError:
            raise Trap("DEVERR", baddr=ea) from None
        if self.trace:
            if dev is not None:
                self.trace.devw(self.cycle, ea, nbytes, val)
            else:
                self.trace.memw(self.cycle, ea, nbytes, val)
        return None, None, None, False

    def exec_atomic(self, name, f):
        w = E.FAMILIES["ATOMIC"]["widths"][f["width"]]
        if w is None:
            raise Trap("ILLEGAL")
        nbytes = w // 8
        wmask = (1 << w) - 1
        ea = self.data_ea(f, with_mod=False)    # ea = R[src1] + sext(imm22)
        if ea & (nbytes - 1):
            raise Trap("UNALIGNED", baddr=ea)
        # both R and W required; first failing check in the order R then W
        pa = self.translate(ea, "R")
        self.translate(ea, "W")
        if self.phys.device_at(pa) is not None:
            raise Trap("DEVERR", baddr=ea)
        try:
            old, _dev = self.phys.load(pa, nbytes)
        except mem.AccessError:
            raise Trap("DEVERR", baddr=ea) from None
        if self.trace:
            self.trace.memr(self.cycle, ea, nbytes, old)

        def s(v):
            return v - (1 << w) if v & (1 << (w - 1)) else v

        b = self.rreg(f["src2"]) & wmask
        store = None
        if name == "CAS":
            if old == b:                        # low w bits compared
                store = self.rreg(f["src3"]) & wmask
        else:
            store = {
                "AMOADD": (old + b) & wmask,
                "AMOAND": old & b,
                "AMOOR": old | b,
                "AMOXOR": old ^ b,
                "AMOSWAP": b,
                "AMOMIN": min(s(old), s(b)) & wmask,
                "AMOMAX": max(s(old), s(b)) & wmask,
                "AMOMINU": min(old, b),
                "AMOMAXU": max(old, b),
            }[name]
        if store is not None:
            self.phys.store(pa, nbytes, store)
            if self.trace:
                self.trace.memw(self.cycle, ea, nbytes, store)
        return canon(old, w), None, None, False

    # ------------------------------------------------------------- FP
    def fp_rm(self):
        fcsr = self.sregs[E.SREGS["fcsr"]]
        rm = (fcsr >> E.FCSR_RM_LSB) & ((1 << E.FCSR_RM_BITS) - 1)
        if rm not in E.ROUNDING.values():
            raise Trap("ILLEGAL")       # reserved rm traps at next rounding op
        return rm

    def fp_accum(self, flags):
        self.sregs[E.SREGS["fcsr"]] |= flags & 0x1F

    def exec_fp(self, name, f):
        fmt = sf.BY_WIDTH.get(f["width"])
        if fmt is None:
            raise Trap("ILLEGAL")
        fmask = (1 << fmt.bits) - 1
        a = self.rreg(f["src1"]) & fmask
        b = self.rreg(f["src2"]) & fmask
        if name in ("FCMPEQ", "FCMPLT", "FCMPLE"):
            op = {"FCMPEQ": "eq", "FCMPLT": "lt", "FCMPLE": "le"}[name]
            res, flags = sf.fcmp(fmt, op, a, b)
            self.fp_accum(flags)
            return None, res, None, False
        if name in ("FMIN", "FMAX"):
            bits, flags = sf.fminmax(fmt, a, b, name == "FMAX")
        else:
            rm = self.fp_rm()           # these all round
            if name == "FADD":
                bits, flags = sf.fadd(fmt, a, b, rm)
            elif name == "FSUB":
                bits, flags = sf.fsub(fmt, a, b, rm)
            elif name == "FMUL":
                bits, flags = sf.fmul(fmt, a, b, rm)
            elif name == "FDIV":
                bits, flags = sf.fdiv(fmt, a, b, rm)
            elif name == "FSQRT":
                bits, flags = sf.fsqrt(fmt, a, rm)
            elif name == "FMADD":
                c = self.rreg(f["src3"]) & fmask
                bits, flags = sf.fmadd(fmt, a, b, c, rm)
            else:
                raise AssertionError(name)
        self.fp_accum(flags)
        return canon(bits, fmt.bits), None, None, False

    def exec_fcvt(self, name, f):
        """ISA-SPEC 10.4: width = dest format, mod bits 1:0 = source
        format, mod bits 7:2 must be zero. Codes: 0=32, 1=64, 2=128
        (integer only)."""
        if f["mod"] & ~3:
            raise Trap("ILLEGAL")
        sfc, dfc = f["mod"] & 3, f["width"]
        if name in ("FCVTFI", "FCVTFIU"):
            fmt = sf.BY_WIDTH.get(sfc)
            iw = {0: 32, 1: 64, 2: 128}.get(dfc)
            if fmt is None or iw is None:
                raise Trap("ILLEGAL")
            a = self.rreg(f["src1"]) & ((1 << fmt.bits) - 1)
            val, flags = sf.f_to_int(fmt, a, iw, signed=(name == "FCVTFI"))
            self.fp_accum(flags)
            return canon(val, iw), None, None, False
        if name in ("FCVTIF", "FCVTUIF"):
            iw = {0: 32, 1: 64, 2: 128}.get(sfc)
            fmt = sf.BY_WIDTH.get(dfc)
            if iw is None or fmt is None:
                raise Trap("ILLEGAL")
            rm = self.fp_rm()
            raw = self.rreg(f["src1"]) & ((1 << iw) - 1)
            v = sext(raw, iw) if name == "FCVTIF" else raw
            bits, flags = sf.int_to_f(fmt, v, rm)
            self.fp_accum(flags)
            return canon(bits, fmt.bits), None, None, False
        # FCVTFF: FP -> FP, 32 <-> 64 only (see SPEC-ISSUES on same-format)
        sfmt, dfmt = sf.BY_WIDTH.get(sfc), sf.BY_WIDTH.get(dfc)
        if sfmt is None or dfmt is None or sfc == dfc:
            raise Trap("ILLEGAL")
        rm = self.fp_rm()
        a = self.rreg(f["src1"]) & ((1 << sfmt.bits) - 1)
        bits, flags = sf.f_to_f(sfmt, dfmt, a, rm)
        self.fp_accum(flags)
        return canon(bits, dfmt.bits), None, None, False

    # ------------------------------------------------------------ system
    def exec_sys(self, name, f):
        if name == "ILLEGAL":
            raise Trap("ILLEGAL")
        if name == "SYSCALL":
            raise Trap("SYSCALL", epc=self.pc)
        if name == "IFENCE":
            self.phys.drain()           # no icache yet: ordering only
            return None, None, None, False
        if name == "MFSR":
            idx = sext(f["imm"], E.IMM_BITS)
            if idx not in _SREG_NAME:
                raise Trap("ILLEGAL")
            if not self.stbit("S") and \
                    "r" not in E.SREG_USER_OK.get(_SREG_NAME[idx], ""):
                raise Trap("PRIV")
            return self.sreg_read(idx), None, None, False
        if name == "MTSR":
            idx = sext(f["imm"], E.IMM_BITS)
            if idx not in _SREG_NAME:
                raise Trap("ILLEGAL")
            if idx == E.SREGS["cycle"]:
                raise Trap("PRIV")      # writes trap PRIV from any mode
            if not self.stbit("S") and \
                    "w" not in E.SREG_USER_OK.get(_SREG_NAME[idx], ""):
                raise Trap("PRIV")
            self.sreg_write(idx, self.rreg(f["src1"]))
            return None, None, None, False
        # remaining are supervisor-only
        self.require_supervisor()
        if name == "IRET":
            bank = 1 if self.tl >= 2 else 0
            new_pc = self.sregs[E.SREGS["epc1" if bank else "epc0"]]
            self.set_stbit("IE", self.stbit("PIE"))
            self.set_stbit("S", self.stbit("PS"))
            self.tl = max(self.tl - 1, 0)
            return None, None, new_pc, False
        if name == "INVTP":
            if f["imm"] != 0:
                raise Trap("ILLEGAL")   # "other values reserved"
            self.invtp_cache.clear()
            return None, None, None, False
        if name == "WFI":
            return None, None, None, True
        if name == "HALT":
            self.phys.drain()
            self.halted = True
            return None, None, None, False
        raise AssertionError(name)

    def wfi_stall(self):
        """ISA-SPEC 7.6 with the freeze from root SPEC-ISSUES 20: from
        WFI's own cycle c, virtual time jumps to T — the first cycle
        >= c at which an interrupt can become pending — and WFI's
        retire increment lands after the jump, so execution resumes at
        cycle T+1. step() already added the retire increment before
        calling here (cycle == c+1), so we compute T from c and land on
        T+1 directly. If no future cycle can make an interrupt pending,
        halt (deadlock is loud)."""
        c = self.cycle - 1               # WFI's own cycle
        candidates = []
        timecmp = self.sregs[E.SREGS["timecmp"]]
        if timecmp != 0:
            candidates.append(max(timecmp, c))
        if self.phys.any_device_pending():
            candidates.append(c)
        for ecycle, _d, _p in self.events:
            candidates.append(max(ecycle, c))
            break                        # events sorted; first is enough
        if not candidates:
            self.halted = True           # WFI deadlock: machine halts
            return
        self.cycle = min(candidates) + 1
        self.process_events()

    # -------------------------------------------------------------- run
    def run(self, maxcycles=None):
        """Returns 'halt' or 'maxcycles'."""
        while not self.halted:
            if maxcycles is not None and self.cycle >= maxcycles:
                return "maxcycles"
            self.step()
        return "halt"
