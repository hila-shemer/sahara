#include "cpu.h"

#include <stdio.h>
#include <string.h>

#include "gen/sahara_isa.h"
#include "hostmem.h"
#include "rw/status.h"

/* ------------------------------------------------------------- status */

static uint64_t status_bits(const SeCpu *c)
{
    return se_lo64(c->sreg[SREG_STATUS]);
}

static void set_status(SeCpu *c, uint64_t v)
{
    /* Defined bits only (ISA-SPEC 2.3: unused bits read as zero). */
    c->sreg[SREG_STATUS] = v & 0x7Fu;
}

static unsigned get_tl(const SeCpu *c)
{
    return (unsigned)((status_bits(c) >> STATUS_TL_LSB) & 3u);
}

static bool is_sup(const SeCpu *c)
{
    return (status_bits(c) & STATUS_S) != 0u;
}

/* ------------------------------------------------------------- reset */

void SeCpu_reset(SeCpu *c, SeMem *m, SeTrace *t)
{
    memset(c, 0, sizeof *c);
    c->mem = m;
    c->tr = t;
    c->pc = SAHARA_RESET_PC;
    c->p[0] = 1u; /* p0 hardwired 1 */
    set_status(c, STATUS_S); /* supervisor, MMU off, IE off, TL 0 */
    c->state = SE_RUN_RUNNING;
}

/* ------------------------------------------------------ trap delivery */

static void deliver(SeCpu *c, uint64_t cause, se_u128 epc, se_u128 baddr)
{
    unsigned tl = get_tl(c);
    if (tl == 2u) {
        /* Triple fault: the machine halts; no state is written (7.2). */
        c->state = SE_RUN_HALT;
        c->halt_note = "triple fault";
        return;
    }
    tl += 1u;
    if (tl == 1u) {
        c->sreg[SREG_EPC0] = epc;
        c->sreg[SREG_CAUSE0] = cause;
        c->sreg[SREG_BADDR0] = baddr;
    } else {
        c->sreg[SREG_EPC1] = epc;
        c->sreg[SREG_CAUSE1] = cause;
        c->sreg[SREG_BADDR1] = baddr;
    }
    uint64_t st = status_bits(c);
    st = (st & ~(uint64_t)STATUS_PIE) | ((st & STATUS_IE) ? STATUS_PIE : 0u);
    st &= ~(uint64_t)STATUS_IE;
    st = (st & ~(uint64_t)STATUS_PS) | ((st & STATUS_S) ? STATUS_PS : 0u);
    st |= STATUS_S;
    st = (st & ~(3ull << STATUS_TL_LSB)) | ((uint64_t)tl << STATUS_TL_LSB);
    set_status(c, st);
    c->pc = (tl == 1u) ? c->sreg[SREG_VBASE] : c->sreg[SREG_DFBASE];
    SeTrace_trap(c->tr, se_lo64(c->cycle), cause, epc, baddr, (uint8_t)tl);
    c->cycle += 1u; /* delivery consumes one cycle (4) */
}

/* --------------------------------------------------- phantom TLB check */

static uint64_t invtp_hash(se_u128 asid, se_u128 vpn)
{
    uint64_t x = se_lo64(asid) ^ se_hi64(asid) ^ (se_lo64(vpn) * 0x9e3779b97f4a7c15ull) ^ se_hi64(vpn);
    x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9ull;
    x = (x ^ (x >> 27)) * 0x94d049bb133111ebull;
    return x ^ (x >> 31);
}

static void invtp_grow(SeInvtpCache *ic)
{
    uint64_t ncap = ic->cap ? ic->cap * 2u : 256u;
    SeInvtpEnt *ne = se_host_alloc(ncap * sizeof *ne);
    for (uint64_t i = 0; i < ic->cap; i++) {
        if (!ic->ents[i].used)
            continue;
        uint64_t j = invtp_hash(ic->ents[i].asid, ic->ents[i].vpn) & (ncap - 1u);
        while (ne[j].used)
            j = (j + 1u) & (ncap - 1u);
        ne[j] = ic->ents[i];
    }
    if (ic->cap)
        se_host_free(ic->ents, ic->cap * sizeof *ic->ents);
    ic->cap = ncap;
    ic->ents = ne;
}

static SeInvtpEnt *invtp_find(SeInvtpCache *ic, se_u128 asid, se_u128 vpn)
{
    if (ic->cap == 0)
        return NULL;
    uint64_t i = invtp_hash(asid, vpn) & (ic->cap - 1u);
    while (ic->ents[i].used) {
        if (ic->ents[i].asid == asid && ic->ents[i].vpn == vpn)
            return &ic->ents[i];
        i = (i + 1u) & (ic->cap - 1u);
    }
    return NULL;
}

static void invtp_insert(SeInvtpCache *ic, se_u128 asid, se_u128 vpn,
                         se_u128 frame, uint8_t perms)
{
    if (ic->cap == 0 || (ic->count + 1u) * 10u >= ic->cap * 7u)
        invtp_grow(ic);
    uint64_t i = invtp_hash(asid, vpn) & (ic->cap - 1u);
    while (ic->ents[i].used)
        i = (i + 1u) & (ic->cap - 1u);
    ic->ents[i] = (SeInvtpEnt){ .used = true, .asid = asid, .vpn = vpn,
                                .frame = frame, .perms = perms };
    ic->count++;
}

static void invtp_clear(SeInvtpCache *ic)
{
    for (uint64_t i = 0; i < ic->cap; i++)
        ic->ents[i].used = false;
    ic->count = 0;
}

/* --------------------------------------------------------- MMU walk */

/* Local permission bit encoding for walk results. */
enum { WP_R = 1u, WP_W = 2u, WP_X = 4u, WP_U = 8u };

typedef struct WalkR {
    bool fault;
    se_u128 frame;
    uint8_t perms;
} WalkR;

static bool ram_read(SeCpu *c, se_u128 pa, unsigned size, se_u128 *out)
{
    if (!SeMem_in_ram(c->mem, pa, size))
        return false;
    *out = SeMem_read(c->mem, pa, size);
    return true;
}

/* One page-table walk (ISA-SPEC 8.2-8.3). Any malformation faults PF_*.
 * Node header layout: shift u64 at +0, prefix u128 at +8, prefix_mask
 * u128 at +24, reserved-zero to +64 (packed offsets, matching the
 * PLATFORM-SPEC table style; see SPEC-ISSUES.md). The depth bound makes
 * a cyclic or degenerate table a fault instead of a hang: 14 chunks
 * cover the whole 112-bit VPN, so an honest table never needs more. */
static WalkR mmu_walk(SeCpu *c, se_u128 va)
{
    WalkR r = { .fault = true, .frame = 0, .perms = 0 };
    se_u128 vpn = va >> PAGE_BITS;
    se_u128 node = c->sreg[SREG_PTBASE];
    for (unsigned depth = 0; depth < 15u; depth++) {
        se_u128 shift128, prefix, pmask, resv0, resv1;
        if ((node & (NODE_ALIGN - 1u)) != 0u)
            return r;
        if (!ram_read(c, node, 8u, &shift128) ||
            !ram_read(c, node + 8u, 16u, &prefix) ||
            !ram_read(c, node + 24u, 16u, &pmask) ||
            !ram_read(c, node + 40u, 8u, &resv0) ||
            !ram_read(c, node + 48u, 16u, &resv1))
            return r;
        if (resv0 != 0u || resv1 != 0u)
            return r;
        if (shift128 > 104u || (se_lo64(shift128) % 8u) != 0u)
            return r;
        unsigned shift = (unsigned)se_lo64(shift128);
        if ((vpn & pmask) != prefix)
            return r;
        uint64_t idx = se_lo64((vpn >> shift) & 0xFFu);
        se_u128 ent;
        if (!ram_read(c, node + NODE_HEADER_BYTES + (se_u128)idx * 16u, 16u,
                      &ent))
            return r;
        unsigned type = (unsigned)(ent & 3u);
        if (type == PTE_LEAF) {
            if (shift != 0u)
                return r; /* leaf legal only at shift 0 (8.2) */
            if ((ent & 0xFFC0u) != 0u)
                return r; /* bits 15:6 reserved, must be zero */
            r.fault = false;
            r.frame = ent & ~(se_u128)0xFFFFu;
            r.perms = (uint8_t)((se_lo64(ent) >> 2) & 0xFu);
            return r;
        }
        if (type != PTE_TABLE)
            return r; /* invalid or reserved type 3 */
        node = ent & ~(se_u128)(NODE_ALIGN - 1u);
    }
    return r; /* deeper than any well-formed table: malformed */
}

static const uint64_t pf_cause[3] = { CAUSE_PF_FETCH, CAUSE_PF_LOAD,
                                      CAUSE_PF_STORE };
static const uint64_t perm_cause[3] = { CAUSE_PERM_FETCH, CAUSE_PERM_LOAD,
                                        CAUSE_PERM_STORE };

static void checkfail(SeCpu *c, const char *fmt, se_u128 va)
{
    (void)snprintf(c->checkfail, sizeof c->checkfail, "%s va=0x%016llx%016llx",
                   fmt, (unsigned long long)se_hi64(va),
                   (unsigned long long)se_lo64(va));
    c->state = SE_RUN_CHECKFAIL;
}

SeXlate SeCpu_translate(SeCpu *c, se_u128 va, int acc)
{
    SeXlate x = { .fault = false, .cause = 0, .baddr = 0, .pa = va };
    if ((status_bits(c) & STATUS_MMU_EN) == 0u)
        return x; /* identity, no permission checks (8.1) */
    WalkR w = mmu_walk(c, va);
    if (c->check_invtp) {
        se_u128 vpn = va >> PAGE_BITS;
        se_u128 asid = c->sreg[SREG_ASID];
        SeInvtpEnt *e = invtp_find(&c->invtp, asid, vpn);
        if (e) {
            if (w.fault || e->frame != w.frame || e->perms != w.perms) {
                checkfail(c, "stale translation would have been served "
                             "(page tables changed without INVTP)", va);
                return x;
            }
        } else if (!w.fault) {
            invtp_insert(&c->invtp, asid, vpn, w.frame, w.perms);
        }
    }
    if (w.fault) {
        x.fault = true;
        x.cause = pf_cause[acc];
        x.baddr = va;
        return x;
    }
    unsigned need = (acc == SE_ACC_FETCH) ? WP_X
                  : (acc == SE_ACC_LOAD) ? WP_R : WP_W;
    bool ok = (w.perms & need) != 0u;
    if (ok && !is_sup(c) && (w.perms & WP_U) == 0u)
        ok = false; /* U gates user access; supervisor ignores U (8.4) */
    if (!ok) {
        x.fault = true;
        x.cause = perm_cause[acc];
        x.baddr = va;
        return x;
    }
    x.pa = w.frame | (va & 0xFFFFu);
    return x;
}

/* ------------------------------------------------------ data access */

typedef struct AccR {
    bool fault;
    uint64_t cause;
    se_u128 baddr;
    se_u128 val;
} AccR;

/* Load or store of size bytes at va. Device windows are not populated
 * yet (device phase, CONFORMANCE C7); the dispatch seam is the branch
 * below. A physical address outside RAM (and outside every device
 * window) raises DEVERR with baddr = va (see SPEC-ISSUES.md). */
static AccR data_access(SeCpu *c, se_u128 va, unsigned size, int acc,
                        se_u128 wval)
{
    AccR a = { .fault = false, .cause = 0, .baddr = 0, .val = 0 };
    if ((va & (size - 1u)) != 0u) {
        a.fault = true;
        a.cause = CAUSE_UNALIGNED;
        a.baddr = va;
        return a;
    }
    SeXlate x = SeCpu_translate(c, va, acc);
    if (c->state != SE_RUN_RUNNING)
        return a; /* check mode fired mid-translate */
    if (x.fault) {
        a.fault = true;
        a.cause = x.cause;
        a.baddr = x.baddr;
        return a;
    }
    /* MMIO dispatch seam: device windows get checked here before RAM. */
    if (!SeMem_in_ram(c->mem, x.pa, size)) {
        a.fault = true;
        a.cause = CAUSE_DEVERR;
        a.baddr = va;
        return a;
    }
    if (acc == SE_ACC_STORE) {
        SeTrace_memw(c->tr, se_lo64(c->cycle), va, (uint8_t)size, wval);
        SeMem_write(c->mem, x.pa, size, wval);
    } else {
        a.val = SeMem_read(c->mem, x.pa, size);
        SeTrace_memr(c->tr, se_lo64(c->cycle), va, (uint8_t)size, a.val);
    }
    return a;
}

/* --------------------------------------------------------- ALU core */

static se_u128 alu_compute(uint8_t op, se_u128 a, se_u128 b, se_u128 s3,
                           unsigned w)
{
    se_u128 za = se_zext(a, w), zb = se_zext(b, w);
    se_u128 sa = se_sext(a, w), sb = se_sext(b, w);
    unsigned cnt = (unsigned)(se_lo64(b) & (w - 1u)); /* shifts mod w (3.4) */
    se_u128 minw = (se_u128)1 << (w - 1u); /* MIN_w as a w-bit pattern */
    switch (op) {
    case OPC_ADD: return se_canon(a + b, w);
    case OPC_SUB: return se_canon(a - b, w);
    case OPC_AND: return se_canon(a & b, w);
    case OPC_OR:  return se_canon(a | b, w);
    case OPC_XOR: return se_canon(a ^ b, w);
    case OPC_SHL: return se_canon(za << cnt, w);
    case OPC_SHR: return se_canon(za >> cnt, w);
    case OPC_SAR: return se_canon((se_u128)((se_s128)sa >> cnt), w);
    case OPC_MUL: return se_canon(za * zb, w);
    case OPC_MULH:
        if (w == 128u)
            return se_mulhs128(a, b);
        return se_canon((se_u128)(((se_s128)sa * (se_s128)sb) >> w), w);
    case OPC_MULHU:
        if (w == 128u)
            return se_mulhu128(a, b);
        return se_canon((za * zb) >> w, w);
    case OPC_MADD: return se_canon(za * zb + s3, w);
    case OPC_UDIV:
        if (zb == 0u)
            return se_canon(~(se_u128)0, w); /* div by zero: all ones (5.1) */
        return se_canon(za / zb, w);
    case OPC_SDIV:
        if (zb == 0u)
            return se_canon(~(se_u128)0, w);
        if (se_zext(sa, w) == minw && sb == ~(se_u128)0)
            return se_canon(minw, w); /* MIN_w / -1 overflow (5.1) */
        return se_canon((se_u128)((se_s128)sa / (se_s128)sb), w);
    case OPC_UREM:
        if (zb == 0u)
            return se_canon(za, w); /* remainder = dividend */
        return se_canon(za % zb, w);
    case OPC_SREM:
        if (zb == 0u)
            return se_canon(sa, w);
        if (se_zext(sa, w) == minw && sb == ~(se_u128)0)
            return 0u; /* MIN_w / -1: remainder 0 */
        return se_canon((se_u128)((se_s128)sa % (se_s128)sb), w);
    default:
        RW_ASSERT(0);
        return 0u;
    }
}

static bool cmp_compute(uint8_t op, se_u128 a, se_u128 b, unsigned w)
{
    se_u128 za = se_zext(a, w), zb = se_zext(b, w);
    se_s128 sa = (se_s128)se_sext(a, w), sb = (se_s128)se_sext(b, w);
    switch (op) {
    case OPC_CMPEQ:  return za == zb;
    case OPC_CMPLT:  return sa < sb;
    case OPC_CMPLTU: return za < zb;
    case OPC_CMPLE:  return sa <= sb;
    case OPC_CMPLEU: return za <= zb;
    default:
        RW_ASSERT(0);
        return false;
    }
}

/* ------------------------------------------------------- step logic */

static bool timer_pending(const SeCpu *c)
{
    se_u128 tc = c->sreg[SREG_TIMECMP];
    return tc != 0u && c->cycle >= tc; /* 7.5 */
}

static bool ext_pending(const SeCpu *c)
{
    (void)c; /* device seam: no device sources until the device phase */
    return false;
}

/* The src2 modifier (3.3). kind 0 with nonzero amount is malformed:
 * ILLEGAL by the loud-failure reading (SPEC-ISSUES.md). */
static bool apply_mod(uint64_t mod, se_u128 v, se_u128 *out)
{
    unsigned kind = (unsigned)(mod & 3u);
    unsigned amt = (unsigned)(mod >> 2);
    switch (kind) {
    case 0u:
        if (amt != 0u)
            return false;
        *out = v;
        return true;
    case 1u:
        *out = v << amt;
        return true;
    case 2u:
        *out = amt ? se_sext(v, amt) : v;
        return true;
    default:
        *out = amt ? se_zext(v, amt) : v;
        return true;
    }
}

/* Per-instruction writeback bookkeeping for the EXEC trace record. */
typedef struct Wb {
    se_u128 wb;
    uint8_t flags;
    uint8_t pred_wb;
} Wb;

static void wr_reg(SeCpu *c, uint64_t rd, se_u128 v, Wb *o)
{
    if (rd == 31u)
        return; /* r31 hardwired zero: write discarded (2.1) */
    c->r[rd] = v;
    o->wb = v;
    o->flags |= SE_TRF_WROTE_DST;
}

static uint8_t pred_file(const SeCpu *c)
{
    uint8_t v = 0;
    for (unsigned i = 0; i < 8u; i++)
        v |= (uint8_t)(c->p[i] << i);
    return v;
}

static void wr_pred(SeCpu *c, unsigned pi, bool val, Wb *o)
{
    if (pi == 0u)
        return; /* p0 hardwired 1: write discarded (2.2) */
    c->p[pi] = val ? 1u : 0u;
    o->flags |= SE_TRF_WROTE_PRED;
    o->pred_wb = pred_file(c);
}

/* WFI (7.6): called after the WFI instruction has retired. Advances
 * cycle straight to the next point an interrupt can become pending, or
 * halts when no such point exists. */
static void wfi_wait(SeCpu *c)
{
    if (timer_pending(c) || ext_pending(c))
        return;
    se_u128 tc = c->sreg[SREG_TIMECMP];
    bool have = false;
    se_u128 next = 0;
    if (tc != 0u && tc > c->cycle) {
        next = tc;
        have = true;
    }
    /* Device seam: the event queue contributes candidate cycles here
     * once devices exist. */
    if (!have) {
        c->state = SE_RUN_HALT;
        c->halt_note = "WFI deadlock: no future event can raise an interrupt";
        return;
    }
    c->cycle = next;
}

static void exec_insn(SeCpu *c, uint64_t insn)
{
    uint64_t opcode = F_OPCODE(insn);
    const sahara_opc_info *info = &sahara_opc[opcode];
    se_u128 pc = c->pc;
    if (!info->valid) {
        deliver(c, CAUSE_ILLEGAL, pc, 0u);
        return;
    }
    uint64_t dst = F_DST(insn), src1 = F_SRC1(insn), src2 = F_SRC2(insn),
             src3 = F_SRC3(insn), mod = F_MOD(insn), wf = F_WIDTH(insn);
    se_u128 simm = se_sext(F_IMM(insn), SAHARA_IMM_BITS);
    Wb o = { .wb = 0, .flags = 0, .pred_wb = 0 };
    se_u128 next_pc = pc + 8u;
    bool do_halt = false, do_wfi = false;
    uint8_t base_op = (uint8_t)(info->iflag_form ? opcode - 1u : opcode);

    switch (info->family) {
    case FAM_ALU:
    case FAM_CMP: {
        unsigned w = sahara_width[info->family][wf];
        if (w == 0u) {
            deliver(c, CAUSE_ILLEGAL, pc, 0u); /* reserved width (3.4) */
            return;
        }
        se_u128 b;
        if (info->iflag_form) {
            b = simm;
        } else if (!apply_mod(mod, c->r[src2], &b)) {
            deliver(c, CAUSE_ILLEGAL, pc, 0u);
            return;
        }
        if (info->family == FAM_ALU)
            wr_reg(c, dst, alu_compute(base_op, c->r[src1], b, c->r[src3], w),
                   &o);
        else
            wr_pred(c, (unsigned)(dst & 7u),
                    cmp_compute(base_op, c->r[src1], b, w), &o);
        break;
    }
    case FAM_MEM:
    case FAM_MEM128: {
        unsigned size;
        if (info->family == FAM_MEM128)
            size = 16u;
        else
            size = sahara_width[FAM_MEM][wf] / 8u; /* 1/2/4/8 bytes */
        se_u128 idxv;
        if (!apply_mod(mod, c->r[src2], &idxv)) {
            deliver(c, CAUSE_ILLEGAL, pc, 0u);
            return;
        }
        se_u128 ea = c->r[src1] + idxv + simm; /* 5.3 */
        bool is_store = (opcode == OPC_ST || opcode == OPC_ST128);
        se_u128 wval = 0;
        if (is_store)
            wval = se_zext(c->r[src3], size * 8u);
        AccR a = data_access(c, ea, size, is_store ? SE_ACC_STORE : SE_ACC_LOAD,
                             wval);
        if (c->state != SE_RUN_RUNNING)
            return;
        if (a.fault) {
            deliver(c, a.cause, pc, a.baddr);
            return;
        }
        if (!is_store) {
            se_u128 v = a.val;
            if (opcode == OPC_LDS)
                v = se_sext(v, size * 8u);
            /* LDZ raw value is already zero-extended; LD128 is full. */
            wr_reg(c, dst, v, &o);
        }
        break;
    }
    case FAM_ATOMIC: {
        unsigned w = sahara_width[FAM_ATOMIC][wf];
        if (w == 0u) {
            deliver(c, CAUSE_ILLEGAL, pc, 0u);
            return;
        }
        unsigned size = w / 8u;
        se_u128 ea = c->r[src1] + simm; /* 5.4 */
        if ((ea & (size - 1u)) != 0u) {
            deliver(c, CAUSE_UNALIGNED, pc, ea);
            return;
        }
        /* R then W, so the first failing check is reported (7.1). */
        SeXlate xl = SeCpu_translate(c, ea, SE_ACC_LOAD);
        if (c->state != SE_RUN_RUNNING)
            return;
        if (!xl.fault) {
            SeXlate xs = SeCpu_translate(c, ea, SE_ACC_STORE);
            if (c->state != SE_RUN_RUNNING)
                return;
            if (xs.fault)
                xl = xs;
        }
        if (xl.fault) {
            deliver(c, xl.cause, pc, xl.baddr);
            return;
        }
        /* Device space traps DEVERR for atomics (5.4); with no device
         * windows yet, out-of-RAM is the same DEVERR path. */
        if (!SeMem_in_ram(c->mem, xl.pa, size)) {
            deliver(c, CAUSE_DEVERR, pc, ea);
            return;
        }
        se_u128 old = SeMem_read(c->mem, xl.pa, size);
        SeTrace_memr(c->tr, se_lo64(c->cycle), ea, (uint8_t)size, old);
        se_u128 zold = se_zext(old, w);
        se_u128 rs2 = c->r[src2];
        bool do_write = true;
        se_u128 newv = 0;
        switch (opcode) {
        case OPC_CAS:
            if (zold == se_zext(rs2, w))
                newv = se_zext(c->r[src3], w);
            else
                do_write = false;
            break;
        case OPC_AMOADD:  newv = se_zext(zold + rs2, w); break;
        case OPC_AMOAND:  newv = se_zext(zold & rs2, w); break;
        case OPC_AMOOR:   newv = se_zext(zold | rs2, w); break;
        case OPC_AMOXOR:  newv = se_zext(zold ^ rs2, w); break;
        case OPC_AMOSWAP: newv = se_zext(rs2, w); break;
        case OPC_AMOMIN:
            newv = ((se_s128)se_sext(old, w) < (se_s128)se_sext(rs2, w))
                       ? zold : se_zext(rs2, w);
            break;
        case OPC_AMOMAX:
            newv = ((se_s128)se_sext(old, w) > (se_s128)se_sext(rs2, w))
                       ? zold : se_zext(rs2, w);
            break;
        case OPC_AMOMINU:
            newv = (zold < se_zext(rs2, w)) ? zold : se_zext(rs2, w);
            break;
        case OPC_AMOMAXU:
            newv = (zold > se_zext(rs2, w)) ? zold : se_zext(rs2, w);
            break;
        default:
            RW_ASSERT(0);
        }
        if (do_write) {
            SeTrace_memw(c->tr, se_lo64(c->cycle), ea, (uint8_t)size, newv);
            SeMem_write(c->mem, xl.pa, size, newv);
        }
        wr_reg(c, dst, se_canon(old, w), &o);
        break;
    }
    case FAM_CTRL:
        switch (opcode) {
        case OPC_B:
            next_pc = pc + (simm << 3); /* displacement in instructions */
            break;
        case OPC_JAL:
            wr_reg(c, dst, pc + 8u, &o);
            next_pc = pc + (simm << 3);
            break;
        default: { /* JALR */
            se_u128 target = c->r[src1] + simm;
            if ((target & 7u) != 0u) {
                deliver(c, CAUSE_UNALIGNED, pc, target);
                return;
            }
            wr_reg(c, dst, pc + 8u, &o);
            next_pc = target;
            break;
        }
        }
        break;
    case FAM_CONST:
        switch (opcode) {
        case OPC_LDI:
            wr_reg(c, dst, simm, &o);
            break;
        case OPC_SHORI:
            wr_reg(c, dst, (c->r[src1] << SAHARA_IMM_BITS) | F_IMM(insn), &o);
            break;
        default: /* LAP */
            wr_reg(c, dst, pc + simm, &o);
            break;
        }
        break;
    case FAM_PREDF:
        if (opcode == OPC_PRD) {
            wr_reg(c, dst, pred_file(c), &o);
        } else { /* PWR: p0 immutable (5.7) */
            uint64_t v = se_lo64(c->r[src1]);
            for (unsigned i = 1; i < 8u; i++)
                c->p[i] = (uint8_t)((v >> i) & 1u);
            o.flags |= SE_TRF_WROTE_PRED;
            o.pred_wb = pred_file(c);
        }
        break;
    case FAM_SYS:
        switch (opcode) {
        case OPC_ILLEGAL:
            deliver(c, CAUSE_ILLEGAL, pc, 0u);
            return;
        case OPC_MFSR:
        case OPC_MTSR: {
            if (simm > 15u) { /* unlisted index (2.3); negative wraps huge */
                deliver(c, CAUSE_ILLEGAL, pc, 0u);
                return;
            }
            unsigned idx = (unsigned)se_lo64(simm);
            bool rd = (opcode == OPC_MFSR);
            if (idx == SREG_CYCLE && !rd) {
                deliver(c, CAUSE_PRIV, pc, 0u); /* cycle write: any mode */
                return;
            }
            if (!is_sup(c)) {
                bool ok = (idx == SREG_FCSR) || (idx == SREG_CYCLE && rd);
                if (!ok) {
                    deliver(c, CAUSE_PRIV, pc, 0u);
                    return;
                }
            }
            if (rd) {
                se_u128 v = (idx == SREG_CYCLE) ? c->cycle : c->sreg[idx];
                wr_reg(c, dst, v, &o);
            } else {
                se_u128 v = c->r[src1];
                if (idx == SREG_STATUS)
                    set_status(c, se_lo64(v));
                else if (idx == SREG_FCSR)
                    c->sreg[idx] = v & 0xFFu;
                else
                    c->sreg[idx] = v;
            }
            break;
        }
        case OPC_SYSCALL:
            deliver(c, CAUSE_SYSCALL, pc, 0u); /* epc = the SYSCALL (5.8) */
            return;
        case OPC_IRET: {
            if (!is_sup(c)) {
                deliver(c, CAUSE_PRIV, pc, 0u);
                return;
            }
            unsigned tl = get_tl(c);
            next_pc = (tl == 2u) ? c->sreg[SREG_EPC1] : c->sreg[SREG_EPC0];
            uint64_t st = status_bits(c);
            st = (st & ~(uint64_t)STATUS_IE) |
                 ((st & STATUS_PIE) ? STATUS_IE : 0u);
            st = (st & ~(uint64_t)STATUS_S) |
                 ((st & STATUS_PS) ? STATUS_S : 0u);
            unsigned ntl = tl ? tl - 1u : 0u; /* saturates at 0 (7.4) */
            st = (st & ~(3ull << STATUS_TL_LSB)) |
                 ((uint64_t)ntl << STATUS_TL_LSB);
            set_status(c, st);
            break;
        }
        case OPC_INVTP:
            if (!is_sup(c)) {
                deliver(c, CAUSE_PRIV, pc, 0u);
                return;
            }
            if (F_IMM(insn) != 0u) { /* imm = 0; others reserved (5.8) */
                deliver(c, CAUSE_ILLEGAL, pc, 0u);
                return;
            }
            invtp_clear(&c->invtp);
            break;
        case OPC_IFENCE:
            break; /* architectural no-op until instruction caching (9.3) */
        case OPC_WFI:
            if (!is_sup(c)) {
                deliver(c, CAUSE_PRIV, pc, 0u);
                return;
            }
            do_wfi = true;
            break;
        default: /* OPC_HALT */
            if (!is_sup(c)) {
                deliver(c, CAUSE_PRIV, pc, 0u);
                return;
            }
            do_halt = true;
            break;
        }
        break;
    default:
        /* FAM_FP / FAM_FCVT: TODO(build-order step 4) -- FP per ISA-SPEC
         * section 10. Until implemented, FP opcodes trap ILLEGAL so the
         * decoder-fuzz contract (execute or trap, never crash) holds;
         * CONFORMANCE C4 fails until this lands. */
        deliver(c, CAUSE_ILLEGAL, pc, 0u);
        return;
    }

    SeTrace_exec(c->tr, se_lo64(c->cycle), pc, insn, o.wb, o.flags, o.pred_wb);
    c->cycle += 1u;
    c->pc = next_pc;
    if (do_halt)
        c->state = SE_RUN_HALT;
    else if (do_wfi)
        wfi_wait(c);
}

void SeCpu_step(SeCpu *c)
{
    RW_ASSERT(c->state == SE_RUN_RUNNING);
    /* Interrupts: between instructions only, IE = 1, timer first (7.5). */
    if (status_bits(c) & STATUS_IE) {
        if (timer_pending(c)) {
            deliver(c, CAUSE_TIMER, c->pc, 0u); /* epc = next insn (7.1) */
            return;
        }
        if (ext_pending(c)) {
            deliver(c, CAUSE_EXTINT, c->pc, 0u);
            return;
        }
    }
    /* Fetch. Instructions must be 8-aligned (3); a misaligned pc (via
     * IRET or a zero vbase) traps UNALIGNED with baddr = pc. */
    if ((c->pc & 7u) != 0u) {
        deliver(c, CAUSE_UNALIGNED, c->pc, c->pc);
        return;
    }
    SeXlate f = SeCpu_translate(c, c->pc, SE_ACC_FETCH);
    if (c->state != SE_RUN_RUNNING)
        return;
    if (f.fault) {
        deliver(c, f.cause, c->pc, f.baddr);
        return;
    }
    if (!SeMem_in_ram(c->mem, f.pa, 8u)) {
        deliver(c, CAUSE_DEVERR, c->pc, c->pc);
        return;
    }
    uint64_t insn = se_lo64(SeMem_read(c->mem, f.pa, 8u));
    /* Predication (3.2) is evaluated before any legality check: a
     * false-predicated instruction -- even an illegal opcode -- retires
     * with no architectural effect and cannot fault (C1). */
    uint64_t predf = F_PRED(insn);
    unsigned pidx = (unsigned)((predf >> 1) & 7u);
    unsigned pol = (unsigned)(predf & 1u);
    if ((c->p[pidx] ^ pol) != 1u) {
        SeTrace_exec(c->tr, se_lo64(c->cycle), c->pc, insn, 0u,
                     SE_TRF_PREDFALSE, 0u);
        c->cycle += 1u;
        c->pc += 8u;
        return;
    }
    exec_insn(c, insn);
}
