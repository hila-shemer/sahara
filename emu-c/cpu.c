#include "cpu.h"

#include <stdio.h>
#include <string.h>

#include "fp.h"
#include "gen/sahara_isa.h"
#include "hostmem.h"
#include "platform.h"
#include "rwc/status.h"

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
        /* Triple fault: the machine halts; no architectural state is
         * written (7.2), but the trace records it loudly -- a final
         * diagnostic TRAP carrying the cause/epc/baddr the third trap
         * WOULD have delivered, tl_after = 3, then the trace ends
         * (devspec/trace.md 2.3.4). Root SPEC-ISSUES 17 originally
         * pinned the opposite (no record); the toolchain's devspec
         * reconciliation overturned it and checks/c1_triplefault.sh
         * now asserts exactly three records (emu-c/SPEC-ISSUES 33,
         * resolved). No cycle is consumed: nothing was delivered. */
        SeTrace_trap(c->tr, se_lo64(c->cycle), cause, epc, baddr, 3u);
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

/* ------------------------------------- --check-devorder store queue */

/* Ordinary-store FIFO of depth N (ISA-SPEC 9.2). Pushing into a full
 * queue retires the oldest store to memory; device accesses and atomics
 * drain everything (rules 1-2). Loads read memory and then overlay the
 * queued bytes oldest-to-newest -- exact store-to-load forwarding, so
 * the mode is semantics-neutral by construction on one CPU. Trace
 * records are emitted at execution time, never at drain, so traces are
 * byte-identical with the mode off. */

static void ordq_flush(SeCpu *c)
{
    for (uint64_t i = 0; i < c->ordq_count; i++) {
        const SeOrdEnt *e =
            &c->ordq[(c->ordq_head + i) % c->devorder_depth];
        SeMem_write(c->mem, e->pa, e->size, e->val);
    }
    c->ordq_head = 0;
    c->ordq_count = 0;
}

static void ordq_store(SeCpu *c, se_u128 pa, unsigned size, se_u128 val)
{
    if (c->devorder_depth == 0u) {
        SeMem_write(c->mem, pa, size, val);
        return;
    }
    if (c->ordq_count == c->devorder_depth) {
        const SeOrdEnt *e = &c->ordq[c->ordq_head];
        SeMem_write(c->mem, e->pa, e->size, e->val);
        c->ordq_head = (c->ordq_head + 1u) % c->devorder_depth;
        c->ordq_count--;
    }
    uint64_t idx = (c->ordq_head + c->ordq_count) % c->devorder_depth;
    c->ordq[idx] =
        (SeOrdEnt){ .pa = pa, .val = val, .size = (uint8_t)size };
    c->ordq_count++;
}

/* Read that sees queued stores: fetches, page-table walks, and data
 * loads all come through here so no consumer can observe a stale byte. */
static se_u128 mem_read_fwd(SeCpu *c, se_u128 pa, unsigned size)
{
    se_u128 v = SeMem_read(c->mem, pa, size);
    if (c->ordq_count == 0u)
        return v;
    uint8_t b[16];
    for (unsigned i = 0; i < size; i++)
        b[i] = (uint8_t)se_lo64(v >> (8u * i));
    for (uint64_t j = 0; j < c->ordq_count; j++) {
        const SeOrdEnt *e =
            &c->ordq[(c->ordq_head + j) % c->devorder_depth];
        for (unsigned i = 0; i < size; i++) {
            se_u128 ad = pa + i;
            if (ad >= e->pa && ad < e->pa + e->size)
                b[i] = (uint8_t)se_lo64(e->val >> (8u * (unsigned)(ad - e->pa)));
        }
    }
    v = 0;
    for (unsigned i = 0; i < size; i++)
        v |= (se_u128)b[i] << (8u * i);
    return v;
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
    /* A page-table node inside device space is not RAM: the walk
     * treats it as malformed, same as a node beyond region 0. */
    if (se_plat_classify(pa) != SE_SPACE_RAM ||
        !SeMem_in_ram(c->mem, pa, size))
        return false;
    *out = mem_read_fwd(c, pa, size);
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

/* Load or store of size bytes at va, dispatched by physical space:
 * RAM (through the devorder queue when armed), memory-like device
 * buffers (NIC TX/RX, pixel window -- all sizes, DEVW/MEMR traced),
 * register windows (64-bit only, per-device semantics in dev.c), and
 * holes (DEVERR, boot.md BOOT-15). Alignment outranks every DEVERR
 * class (display.md 2 rule 4, nic.md 5.2): it is checked first. A
 * faulting access has no device effect and leaves no access record. */
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
    a.fault = true; /* every non-returning path below is DEVERR */
    a.cause = CAUSE_DEVERR;
    a.baddr = va;
    SePlatSpace sp = se_plat_classify(x.pa);
    if (sp == SE_SPACE_RAM) {
        if (!SeMem_in_ram(c->mem, x.pa, size))
            return a; /* outside region 0 */
        a.fault = false;
        if (acc == SE_ACC_STORE) {
            SeTrace_memw(c->tr, se_lo64(c->cycle), va, (uint8_t)size, wval);
            ordq_store(c, x.pa, size, wval);
        } else {
            a.val = mem_read_fwd(c, x.pa, size);
            SeTrace_memr(c->tr, se_lo64(c->cycle), va, (uint8_t)size, a.val);
        }
        return a;
    }
    if (sp == SE_SPACE_HOLE)
        return a;
    /* Any device access orders the store queue (ISA 9.2 rules 1-2). */
    if (c->ordq_count != 0u)
        ordq_flush(c);
    if (sp == SE_SPACE_BUF) {
        a.fault = false;
        if (acc == SE_ACC_STORE) {
            SeTrace_devw(c->tr, se_lo64(c->cycle), va, (uint8_t)size, wval);
            SeMem_write(c->mem, x.pa, size, wval);
        } else {
            a.val = SeMem_read(c->mem, x.pa, size);
            SeTrace_memr(c->tr, se_lo64(c->cycle), va, (uint8_t)size, a.val);
        }
        return a;
    }
    /* Register window: 64-bit accesses only (PLATFORM-SPEC 1), and no
     * device backs the windows in unit tests (dev == NULL). */
    if (size != 8u || c->dev == NULL)
        return a;
    uint64_t off = se_lo64(x.pa & 0xFFFFu);
    if (acc == SE_ACC_STORE) {
        SeDevAcc r = SeDev_reg_write(c->dev, sp, off, se_lo64(wval));
        if (r.fault)
            return a;
        SeTrace_devw(c->tr, se_lo64(c->cycle), va, 8u, wval);
    } else {
        SeDevAcc r = SeDev_reg_read(c->dev, sp, off);
        if (r.fault)
            return a;
        a.val = r.val;
        SeTrace_memr(c->tr, se_lo64(c->cycle), va, 8u, a.val);
    }
    a.fault = false;
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
        RWC_ASSERT(0);
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
        RWC_ASSERT(0);
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
    /* Level-triggered OR of every device pending condition
     * (PLATFORM-SPEC 3); no sources exist while the event queues stay
     * headless-empty, so this still never fires in the suite. */
    return c->dev != NULL && SeDev_ext_pending(c->dev);
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

/* WFI (7.6) under the root SPEC-ISSUES 20 freeze: from WFI's own cycle
 * c0, virtual time jumps to T -- the first cycle >= c0 at which an
 * interrupt can become pending -- and the retire increment lands after
 * the jump, so execution resumes at T + 1. Our caller already applied
 * the retire increment (cycle == c0 + 1 on entry), so every exit sets
 * cycle = T + 1 explicitly. Halts when no such T exists. */
static void wfi_wait(SeCpu *c)
{
    se_u128 c0 = c->cycle - 1u;
    c->cycle = c0; /* pending conditions are evaluated at c0 */
    if (timer_pending(c) || ext_pending(c)) {
        c->cycle = c0 + 1u; /* T = c0 */
        return;
    }
    se_u128 tc = c->sreg[SREG_TIMECMP];
    bool have = false;
    se_u128 wake = 0; /* the boundary cycle execution resumes at */
    if (tc != 0u && tc > c0) {
        wake = tc + 1u; /* T = tc, retire lands after the jump (root 20) */
        have = true;
    }
    /* The device timer follows the event-style rule, not timecmp's
     * T+1: pending derives at boundaries, so the wake lands at exactly
     * next_fire (timer.md 4.5, ISA 7.6 "advances directly to the next
     * cycle at which one becomes pending"). Armed and not already
     * pending at c0 (the early return above used the cached bit from
     * this boundary's tick) implies next_fire > c0. */
    if (c->dev != NULL && c->dev->tmr_period != 0u) {
        se_u128 tn = c->dev->tmr_next;
        if (!have || tn < wake) {
            wake = tn;
            have = true;
        }
    }
    /* A feed event wakes WFI at a boundary stamped exactly its cycle:
     * the recorded EVENT then equals the feed record byte-for-byte,
     * which is what makes replaying a recording idempotent across a
     * WFI stall -- a wake at ec+1 would re-stamp the event one cycle
     * later on every replay generation (SPEC-ISSUES 36; root
     * SPEC-ISSUES 32 anticipated the drift). The woken boundary
     * applies the event, and it always leaves EXTINT pending: a
     * drop-newest can only happen with a full queue, which was pending
     * already -- so the wake never resumes execution early. */
    if (c->ev_next < c->ev_count) {
        se_u128 ec = (se_u128)c->ev[c->ev_next].cycle;
        if (ec <= c0) {
            c->cycle = c0 + 1u; /* applies at the imminent boundary */
            return;
        }
        if (!have || ec < wake) {
            wake = ec;
            have = true;
        }
    }
    if (!have) {
        RWC_ASSERT(!c->live_yield); /* exec yields before a dead WFI retires */
        c->cycle = c0 + 1u;
        c->state = SE_RUN_HALT;
        c->halt_note = "WFI deadlock: no future event can raise an interrupt";
        return;
    }
    c->cycle = wake;
}

/* Would wfi_wait find a wake source if the WFI retired now? Evaluated
 * at the WFI's own cycle, which is the same value wfi_wait's c0 sees
 * after the retire increment -- the two must agree or a live WFI could
 * yield with a wake pending (or retire into the deadlock assert). */
static bool wfi_wake_exists(const SeCpu *c)
{
    if (timer_pending(c) || ext_pending(c))
        return true;
    se_u128 tc = c->sreg[SREG_TIMECMP];
    if (tc != 0u && tc > c->cycle)
        return true;
    if (c->dev != NULL && c->dev->tmr_period != 0u)
        return true; /* an armed timer always fires (timer.md 4.5) */
    return c->ev_next < c->ev_count;
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
        /* Device space traps DEVERR for atomics (5.4, nic.md E7) --
         * registers, buffers, and holes alike; out-of-RAM takes the
         * same path (SPEC-ISSUES.md entry 3). Checked before the read
         * so a DEVERR'd atomic leaves no MEMR footprint in the trace. */
        if (se_plat_classify(xl.pa) != SE_SPACE_RAM ||
            !SeMem_in_ram(c->mem, xl.pa, size)) {
            deliver(c, CAUSE_DEVERR, pc, ea);
            return;
        }
        /* An atomic is ordered on both sides: drain the devorder queue
         * and operate on memory directly. */
        if (c->ordq_count != 0u)
            ordq_flush(c);
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
            RWC_ASSERT(0);
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
            if (c->live_yield && !wfi_wake_exists(c)) {
                /* Live idle: nothing can wake this WFI yet, and the
                 * headless deadlock halt is wrong when the event feed
                 * is still open. Yield with nothing retired and no
                 * records emitted; the WFI re-executes -- same cycle,
                 * same records -- once input is fed (SPEC-ISSUES 36). */
                c->wfi_idle = true;
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
    case FAM_FP: {
        unsigned w = sahara_width[FAM_FP][wf];
        if (w == 0u) {
            deliver(c, CAUSE_ILLEGAL, pc, 0u); /* reserved width (3.4) */
            return;
        }
        unsigned rm = (unsigned)((se_lo64(c->sreg[SREG_FCSR])
                                  >> FCSR_RM_LSB) & 7u);
        bool is_cmp = (opcode == OPC_FCMPEQ || opcode == OPC_FCMPLT ||
                       opcode == OPC_FCMPLE);
        bool consults_rm = !is_cmp && opcode != OPC_FMIN &&
                           opcode != OPC_FMAX;
        if (consults_rm && rm > RM_RMM) {
            /* reserved rounding mode traps at the next op that rounds,
             * not at the MTSR that wrote it (10.3) */
            deliver(c, CAUSE_ILLEGAL, pc, 0u);
            return;
        }
        uint8_t fl = 0;
        if (is_cmp) {
            bool t = se_fp_cmp((uint8_t)opcode, SeFpFmtW_t_of(w),
                               se_lo64(c->r[src1]),
                               se_lo64(c->r[src2]), &fl);
            wr_pred(c, (unsigned)(dst & 7u), t, &o);
        } else {
            SeFpRes fr = se_fp_arith((uint8_t)opcode, SeFpFmtW_t_of(w),
                                     se_lo64(c->r[src1]),
                                     se_lo64(c->r[src2]),
                                     se_lo64(c->r[src3]),
                                     SeFpRm_t_of(rm));
            fl = fr.flags;
            wr_reg(c, dst, se_canon(fr.bits, w), &o);
        }
        c->sreg[SREG_FCSR] |= fl; /* flags are sticky (10.3) */
        break;
    }
    case FAM_FCVT: {
        unsigned rm = (unsigned)((se_lo64(c->sreg[SREG_FCSR])
                                  >> FCSR_RM_LSB) & 7u);
        unsigned sfmt = (unsigned)(mod & 3u);
        /* mod bits 7:2 must be zero; format codes 0/1/2 = 32/64/128,
         * 128-bit FP does not exist (10.4) */
        bool ok = (mod >> 2) == 0u;
        unsigned srcw = 32u << sfmt, dstw = 32u << wf;
        switch (opcode) {
        case OPC_FCVTFI:
        case OPC_FCVTFIU:
            /* FP (32/64) -> int (32/64/128); truncates regardless of
             * fcsr, but still "rounds" for the reserved-rm trap (root
             * SPEC-ISSUES 19: all FCVT forms round) */
            ok = ok && sfmt <= 1u && wf <= 2u;
            break;
        case OPC_FCVTIF:
        case OPC_FCVTUIF:
            ok = ok && sfmt <= 2u && wf <= 1u;
            break;
        default: /* OPC_FCVTFF: 32 <-> 64 only (SPEC-ISSUES.md) */
            ok = ok && sfmt <= 1u && wf <= 1u && sfmt != wf;
            break;
        }
        if (!ok || rm > RM_RMM) {
            deliver(c, CAUSE_ILLEGAL, pc, 0u);
            return;
        }
        uint8_t fl;
        if (opcode == OPC_FCVTFI || opcode == OPC_FCVTFIU) {
            SeFpInt ir = se_fp_to_int(SeFpFmtW_t_of(srcw),
                                      se_lo64(c->r[src1]),
                                      SeIntW_t_of(dstw),
                                      opcode == OPC_FCVTFIU);
            fl = ir.flags;
            wr_reg(c, dst, ir.val, &o);
        } else {
            SeFpRes fr;
            if (opcode == OPC_FCVTFF)
                fr = se_fp_to_fp(SeFpFmtW_t_of(srcw),
                                 se_lo64(c->r[src1]),
                                 SeFpFmtW_t_of(dstw), SeFpRm_t_of(rm));
            else
                fr = se_fp_from_int(c->r[src1], SeIntW_t_of(srcw),
                                    opcode == OPC_FCVTUIF,
                                    SeFpFmtW_t_of(dstw), SeFpRm_t_of(rm));
            fl = fr.flags;
            wr_reg(c, dst, se_canon(fr.bits, dstw), &o);
        }
        c->sreg[SREG_FCSR] |= fl;
        break;
    }
    default:
        RWC_ASSERT(0); /* every valid family is handled above */
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

static uint64_t ev_u64(const uint8_t *b)
{
    uint64_t v = 0;
    for (unsigned i = 0; i < 8u; i++)
        v |= (uint64_t)b[i] << (8u * i);
    return v;
}

/* The device phase (trace.md 3.3 rule 1, 5.2), shared by --replay and
 * the live feed: at this boundary, apply every feed event whose cycle
 * has been reached, in record order, to its device model, and record
 * each as an EVENT stamped with the boundary's cycle -- before
 * interrupt recognition, so a delivery the events cause shares their
 * cycle and follows them in the trace. The input drop flag is
 * recomputed by the model, never copied from the feed (trace.md 5.4). */
static void apply_events(SeCpu *c)
{
    while (c->ev_next < c->ev_count &&
           (se_u128)c->ev[c->ev_next].cycle <= c->cycle) {
        const SeEvRec *e = &c->ev[c->ev_next];
        c->ev_next += 1u;
        RWC_ASSERT(c->dev != NULL); /* main.c wires both or neither */
        const uint8_t *rec = e->payload;
        uint8_t inbuf[9];
        uint16_t rec_len = e->len;
        bool record = true;
        switch (e->device) {
        case SE_DEVIDX_DISPLAY:
            SeDev_inject_resize(c->dev, ev_u64(e->payload),
                                ev_u64(e->payload + 8u),
                                ev_u64(e->payload + 16u));
            break;
        case SE_DEVIDX_KBD:
        case SE_DEVIDX_MOUSE: {
            /* Input's overflow drop IS recorded, flagged (trace.md
             * 4.1/5.4)... */
            bool dropped = SeDev_inject_input(
                c->dev, e->device == SE_DEVIDX_KBD, ev_u64(e->payload));
            memcpy(inbuf, e->payload, sizeof inbuf);
            inbuf[8] = dropped ? 1u : 0u;
            rec = inbuf;
            break;
        }
        case SE_DEVIDX_NIC:
            /* ...but the NIC's overflow discard is NOT (nic.md 4.3):
             * an unadmitted frame never enters the trace, so replay
             * cannot double-apply it. A genuine --replay trace holds
             * only admitted frames and replays into the same queue
             * occupancy, so a discard under replay means the trace was
             * tampered with -- die loudly. */
            if (SeDev_inject_nic(c->dev, c->mem, e->payload, e->len)) {
                RWC_ASSERT(c->ev == c->feed);
                record = false;
            }
            break;
        case SE_DEVIDX_RNG: {
            /* Truncate-to-fit, recorded = accepted prefix (rng.md
             * 4.2, trace.md 4.6): the model recomputes acceptance on
             * every apply -- live and replay alike, so an overflowing
             * feed truncates deterministically instead of dying, and
             * the trace diff is the loud replay check (SPEC-ISSUES
             * 40). The recorded bytes are the payload prefix: word
             * boundaries are byte boundaries, no re-encoding needed. */
            uint64_t w[SE_RNG_EV_WORDS_MAX];
            uint32_t n = e->len / 8u;
            RWC_ASSERT(n >= 1u && n <= SE_RNG_EV_WORDS_MAX);
            for (uint32_t i = 0; i < n; i++)
                w[i] = ev_u64(e->payload + 8u * i);
            uint32_t took = SeDev_inject_rng(c->dev, w, n);
            if (took == 0u)
                record = false; /* zero accepted: no EVENT record */
            rec_len = (uint16_t)(8u * took);
            break;
        }
        default:
            RWC_ASSERT(0); /* both feeders admit only the five above */
        }
        if (record)
            SeTrace_event(c->tr, se_lo64(c->cycle), e->device, rec,
                          rec_len);
    }
}

void SeCpu_feed(SeCpu *c, uint8_t device, const uint8_t *payload,
                uint16_t len, uint64_t earliest_cycle)
{
    RWC_ASSERT(len <= sizeof c->feed[0].payload);
    RWC_ASSERT(c->ev == NULL || c->ev == c->feed); /* never mix with --replay */
    if (c->ev_next == c->ev_count) {
        /* Everything queued so far was applied: reuse the array from
         * the start instead of growing without bound over a session. */
        c->ev_next = 0;
        c->ev_count = 0;
    }
    if (c->ev_count == c->feed_cap) {
        uint64_t ncap = c->feed_cap ? c->feed_cap * 2u : 64u;
        SeEvRec *nf = se_host_alloc(ncap * sizeof *nf);
        if (c->feed_cap) {
            memcpy(nf, c->feed, c->ev_count * sizeof *nf);
            se_host_free(c->feed, c->feed_cap * sizeof *c->feed);
        }
        c->feed = nf;
        c->feed_cap = ncap;
    }
    uint64_t cyc = earliest_cycle;
    if (cyc < se_lo64(c->cycle))
        cyc = se_lo64(c->cycle); /* record what happens, never the past */
    if (c->ev_count != 0u && c->feed[c->ev_count - 1u].cycle > cyc)
        cyc = c->feed[c->ev_count - 1u].cycle; /* keep the feed sorted */
    SeEvRec *e = &c->feed[c->ev_count];
    c->ev_count += 1u;
    e->cycle = cyc;
    e->device = device;
    e->len = len;
    memcpy(e->payload, payload, len);
    c->ev = c->feed;
    c->wfi_idle = false; /* feeding is the wake */
}

void SeCpu_step(SeCpu *c)
{
    RWC_ASSERT(c->state == SE_RUN_RUNNING);
    /* Boundary order (trace.md 3.3): events first, then the device
     * phase, then interrupt recognition, then the next instruction.
     * The timer tick caches this boundary's cycle and recomputes the
     * derived pending bit (timer.md 4.3); register accesses by the
     * instruction below read the cache as their C/W/A, which equals
     * the cycle their own records carry -- the whole byte-match
     * contract with emu-py rides on this one call site. */
    apply_events(c);
    if (c->dev != NULL)
        SeDev_timer_tick(c->dev, c->cycle);
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
    /* Fetch from device space or a hole: DEVERR (boot.md BOOT-15; the
     * device-window case is the conservative reading of nic.md 5.2,
     * SPEC-ISSUES.md entries 3 and 32). */
    if (se_plat_classify(f.pa) != SE_SPACE_RAM ||
        !SeMem_in_ram(c->mem, f.pa, 8u)) {
        deliver(c, CAUSE_DEVERR, c->pc, c->pc);
        return;
    }
    uint64_t insn = se_lo64(mem_read_fwd(c, f.pa, 8u));
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
