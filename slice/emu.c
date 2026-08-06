/* Sahara slice emulator. Throwaway code; the deliverable is CONSTRAINTS.md. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "encoding.h"

typedef unsigned __int128 u128;
typedef __int128 s128;
typedef uint64_t u64;

/* ---------- sparse physical memory: hash page# -> 64KB block ---------- */
#define PAGE_BITS 16
#define PAGE_SIZE (1u << PAGE_BITS)
#define NBUCKETS 65536
typedef struct PhysPage { u128 pno; uint8_t *data; struct PhysPage *next; } PhysPage;
static PhysPage *buckets[NBUCKETS];
static u64 phys_pages_allocated;

static uint8_t *phys_page(u128 pno) {
    unsigned h = (unsigned)((u64)pno ^ ((u64)(pno >> 64))) % NBUCKETS;
    for (PhysPage *p = buckets[h]; p; p = p->next)
        if (p->pno == pno) return p->data;
    PhysPage *p = calloc(1, sizeof *p);
    p->pno = pno; p->data = calloc(1, PAGE_SIZE);
    p->next = buckets[h]; buckets[h] = p;
    phys_pages_allocated++;
    return p->data;
}
static u128 pread(u128 pa, int w) {
    u128 v = 0;
    for (int i = 0; i < w; i++)
        v |= (u128)phys_page((pa + i) >> PAGE_BITS)[(u64)(pa + i) & (PAGE_SIZE-1)] << (8*i);
    return v;
}
static void pwrite(u128 pa, int w, u128 v) {
    for (int i = 0; i < w; i++)
        phys_page((pa + i) >> PAGE_BITS)[(u64)(pa + i) & (PAGE_SIZE-1)] = (uint8_t)(v >> (8*i));
}

/* ---------- CPU state ---------- */
static u128 R[32];
static int P[8];             /* predicate regs; P[0] hardwired 1 */
static u128 SR[16];
static u128 pc;
static u64 cycle;
#define ST_IE  ((u128)1)
#define ST_PIE ((u128)2)
#define ST_MMU ((u128)4)

/* ---------- stats ---------- */
static u64 st_insns, st_walks, st_walk_accesses, st_walk_depth_max;
static u64 st_pt_nodes, st_pt_bytes, st_irqs, st_traps, st_pred_squashed,
           st_pred_carried, st_frames, st_invtp;

/* ---------- radix page table (built by "firmware", walked by CPU) ---------- */
static int IB = 8;                        /* index bits per level; --index-bits */
#define VPNBITS 112
static u128 pt_bump = 0x200000;           /* phys bump allocator for nodes */

static u128 vpn_mask_above(int k) {       /* mask of VPN bits [k, VPNBITS) */
    u128 all = (~(u128)0) >> (128 - VPNBITS);
    if (k >= VPNBITS) return 0;
    return all & ~((((u128)1) << k) - 1);
}
/* node: 64-byte header {u64 shift @0, u128 prefix @16, u128 mask @32}, then
   2^IB entries of 16 bytes. entry low 2 bits: 0 invalid, 1 table, 2 leaf. */
static u128 node_new(int shift, u128 vpn) {
    u128 n = pt_bump;
    pt_bump += 64 + ((u128)16 << IB);
    pt_bump = (pt_bump + 63) & ~(u128)63;
    u128 mask = vpn_mask_above(shift + IB);
    pwrite(n, 8, (u128)shift);
    pwrite(n + 16, 16, vpn & mask);
    pwrite(n + 32, 16, mask);
    st_pt_nodes++; st_pt_bytes += 64 + (16u << IB);
    return n;
}
static int highbit(u128 x) { int b = -1; while (x) { x >>= 1; b++; } return b; }

static void pt_insert(u128 va, u128 pa_frame) {
    u128 vpn = va >> PAGE_BITS;
    u128 ibmask = ((u128)1 << IB) - 1;
    if (!SR[SR_PTBASE]) SR[SR_PTBASE] = node_new(0, vpn);
    u128 cur = SR[SR_PTBASE], parent_entry = 0;
    for (;;) {
        int shift = (int)pread(cur, 8);
        u128 prefix = pread(cur + 16, 16), mask = pread(cur + 32, 16);
        if ((vpn & mask) != prefix) {           /* split above cur */
            int top = highbit((vpn & mask) ^ prefix);
            int ns = (top / IB) * IB;
            u128 nn = node_new(ns, vpn);
            u64 idx_old = (u64)((prefix >> ns) & ibmask);
            u64 idx_new = (u64)((vpn >> ns) & ibmask);
            pwrite(nn + 64 + idx_old*16, 16, cur | 1);
            u128 child = node_new(0, vpn);
            pwrite(nn + 64 + idx_new*16, 16, child | 1);
            if (parent_entry) pwrite(parent_entry, 16, nn | 1);
            else SR[SR_PTBASE] = nn;
            cur = child; continue;
        }
        u64 idx = (u64)((vpn >> shift) & ibmask);
        u128 eaddr = cur + 64 + idx*16;
        if (shift == 0) { pwrite(eaddr, 16, (pa_frame & ~(u128)(PAGE_SIZE-1)) | 2); return; }
        u128 e = pread(eaddr, 16);
        if ((e & 3) == 0) { u128 child = node_new(0, vpn); pwrite(eaddr, 16, child | 1); cur = child; }
        else { cur = e & ~(u128)3; }
        parent_entry = eaddr;
    }
}

static int mmu_walk(u128 va, u128 *pa) {        /* 0 = ok, 1 = fault */
    u128 vpn = va >> PAGE_BITS, cur = SR[SR_PTBASE];
    u128 ibmask = ((u128)1 << IB) - 1;
    if (!cur) return 1;
    st_walks++;
    u64 depth = 0;
    for (int guard = 0; guard < 64; guard++) {
        depth++;
        st_walk_accesses++;                     /* header */
        int shift = (int)pread(cur, 8);
        u128 prefix = pread(cur + 16, 16), mask = pread(cur + 32, 16);
        if ((vpn & mask) != prefix) goto out;
        st_walk_accesses++;                     /* entry */
        u128 e = pread(cur + 64 + ((u64)((vpn >> shift) & ibmask))*16, 16);
        if ((e & 3) == 0) goto out;
        if ((e & 3) == 2) {
            if (shift != 0) goto out;
            if (depth > st_walk_depth_max) st_walk_depth_max = depth;
            *pa = (e & ~(u128)3 & ~(u128)(PAGE_SIZE-1)) | (va & (PAGE_SIZE-1));
            return 0;
        }
        cur = e & ~(u128)3;
    }
out:
    if (depth > st_walk_depth_max) st_walk_depth_max = depth;
    return 1;
}

/* ---------- MMIO devices ---------- */
#define FB_PA      ((u128)0x10000000)
#define FB_W 320
#define FB_H 200
#define FB_BYTES   (FB_W*FB_H*4)
#define FBCTL_PA   ((u128)0x0F000000)   /* +0 doorbell(w), +8 framecnt(r) */
#define KBD_PA     ((u128)0x0F010000)   /* +0 data(r, pops), +8 status(r) */
static char *fbprefix = "out/frame";
static u64 kbd_queue[256]; static int kbd_head, kbd_tail;
struct KbdEv { u64 cycle, key; };
static struct KbdEv kbd_trace[4096]; static int kbd_ntrace, kbd_next;

static void fb_dump(void) {
    char path[256];
    snprintf(path, sizeof path, "%s_%llu.ppm", fbprefix, (unsigned long long)st_frames);
    FILE *f = fopen(path, "wb");
    if (!f) { perror(path); exit(1); }
    fprintf(f, "P6\n%d %d\n255\n", FB_W, FB_H);
    for (u64 i = 0; i < FB_BYTES; i += 4) {
        u128 px = pread(FB_PA + i, 4);
        fputc((int)(px & 0xff), f); fputc((int)((px>>8) & 0xff), f); fputc((int)((px>>16) & 0xff), f);
    }
    fclose(f);
    st_frames++;
}
static int is_mmio(u128 pa) {
    return (pa >= FBCTL_PA && pa < FBCTL_PA + 0x100) ||
           (pa >= KBD_PA && pa < KBD_PA + 0x100);
}
static u128 mmio_read(u128 pa) {
    if (pa == KBD_PA) {
        if (kbd_head == kbd_tail) return (u128)(s128)-1;
        return kbd_queue[kbd_head++ & 255];
    }
    if (pa == KBD_PA + 8) return kbd_head != kbd_tail;
    if (pa == FBCTL_PA + 8) return st_frames;
    return 0;
}
static void mmio_write(u128 pa, u128 v) {
    (void)v;
    if (pa == FBCTL_PA) fb_dump();
}

/* ---------- weak store buffer (for the MMIO-ordering experiment) ----------
   mode 0: strong (default, stores visible immediately)
   mode 1: normal stores delayed WEAK_DELAY cycles; MMIO store DRAINS first
   mode 2: same delay but MMIO store bypasses (models missing guarantee)   */
static int weak_mode = 0;
#define WEAK_DELAY 64
struct PendSt { u64 ready; u128 pa; int w; u128 v; };
static struct PendSt stq[1024]; static int stq_n;
static void stq_drain_all(void) {
    for (int i = 0; i < stq_n; i++) pwrite(stq[i].pa, stq[i].w, stq[i].v);
    stq_n = 0;
}
static void stq_drain_ready(void) {
    int j = 0;
    for (int i = 0; i < stq_n; i++) {
        if (stq[i].ready <= cycle) pwrite(stq[i].pa, stq[i].w, stq[i].v);
        else stq[j++] = stq[i];
    }
    stq_n = j;
}

/* ---------- trap plumbing ---------- */
static u128 vload_fault_va; static int pending_trap = -1;
static void raise_trap(int cause, u128 badva) {
    pending_trap = cause; vload_fault_va = badva;
}
static void deliver(int cause, u128 epc, u128 badva) {
    SR[SR_EPC] = epc; SR[SR_CAUSE] = (u128)cause; SR[SR_BADDR] = badva;
    SR[SR_STATUS] = (SR[SR_STATUS] & ~ST_PIE) | ((SR[SR_STATUS] & ST_IE) ? ST_PIE : 0);
    SR[SR_STATUS] &= ~ST_IE;
    pc = SR[SR_VBASE];
    st_traps++;
}

/* ---------- memory access from the CPU ---------- */
static int vaccess(u128 va, int w, int is_store, int is_fetch, u128 *pa_out) {
    if (w > 1 && (va & (w - 1))) { raise_trap(CAUSE_UNALIGNED, va); return -1; }
    u128 pa = va;
    if (SR[SR_STATUS] & ST_MMU) {
        if (mmu_walk(va, &pa)) {
            raise_trap(is_fetch ? CAUSE_PF_FETCH : is_store ? CAUSE_PF_STORE : CAUSE_PF_LOAD, va);
            return -1;
        }
    }
    *pa_out = pa;
    return 0;
}
static int vload(u128 va, int w, u128 *out) {
    u128 pa;
    if (vaccess(va, w, 0, 0, &pa)) return -1;
    if (weak_mode) stq_drain_all();          /* loads act as full flush; crude */
    *out = is_mmio(pa) ? mmio_read(pa) : pread(pa, w);
    return 0;
}
static int vstore(u128 va, int w, u128 v) {
    u128 pa;
    if (vaccess(va, w, 1, 0, &pa)) return -1;
    if (is_mmio(pa)) {
        if (weak_mode == 1) stq_drain_all();  /* the hardware ordering guarantee */
        mmio_write(pa, v);
    } else if (weak_mode) {
        if (stq_n == 1024) stq_drain_all();
        stq[stq_n++] = (struct PendSt){ cycle + WEAK_DELAY, pa, w, v };
    } else pwrite(pa, w, v);
    return 0;
}

/* ---------- helpers ---------- */
static u128 sext_imm(u64 raw) {
    return (u128)(s128)((int64_t)(raw << (64 - ENC_IMM_BITS)) >> (64 - ENC_IMM_BITS));
}
static u128 apply_mod(u128 v, unsigned mod) {
    unsigned kind = mod & 3, amt = mod >> 2;
    switch (kind) {
    case MOD_SHL: return v << amt;
    case MOD_SXT: if (!amt || amt >= 128) return v;
                  return (u128)((s128)(v << (128 - amt)) >> (128 - amt));
    case MOD_ZXT: if (!amt || amt >= 128) return v;
                  return v & ((((u128)1) << amt) - 1);
    default: return v;
    }
}
static void wreg(int r, u128 v) { if (r != 31) R[r] = v; }
static void hex128(char *buf, u128 v) {
    sprintf(buf, "%016llx%016llx", (unsigned long long)(v >> 64), (unsigned long long)v);
}

/* ---------- image loading ---------- */
static u128 load_image(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) { perror(path); exit(1); }
    char line[1 << 16]; u128 entry = 0;
    while (fgets(line, sizeof line, f)) {
        if (!strncmp(line, "ENTRY", 5)) { entry = strtoull(line + 6, 0, 0); continue; }
        if (line[0] != '@') continue;
        char *sp = strchr(line, ' ');
        *sp = 0;
        u128 addr = strtoull(line + 1, 0, 16);
        for (char *p = sp + 1; p[0] && p[1] && p[0] != '\n'; p += 2) {
            unsigned b; sscanf(p, "%2x", &b);
            pwrite(addr++, 1, b);
        }
    }
    fclose(f);
    return entry;
}

int main(int argc, char **argv) {
    const char *img = 0, *statsf = 0, *tracef = 0;
    u64 maxcycles = 50000000;
    struct { u128 va, pa; u64 len; } maps[64]; int nmaps = 0;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--map")) {
            char *s = argv[++i];
            u64 va = strtoull(s, &s, 0); s++;
            u64 pa = strtoull(s, &s, 0); s++;
            u64 len = strtoull(s, &s, 0);
            maps[nmaps].va = va; maps[nmaps].pa = pa; maps[nmaps].len = len; nmaps++;
        }
        else if (!strcmp(argv[i], "--map128")) {   /* va_hi:va_lo:pa:len for huge VAs */
            char *s = argv[++i];
            u64 hi = strtoull(s, &s, 16); s++;
            u64 lo = strtoull(s, &s, 16); s++;
            u64 pa = strtoull(s, &s, 0); s++;
            u64 len = strtoull(s, &s, 0);
            maps[nmaps].va = ((u128)hi << 64) | lo; maps[nmaps].pa = pa; maps[nmaps].len = len; nmaps++;
        }
        else if (!strcmp(argv[i], "--kbd")) {
            FILE *f = fopen(argv[++i], "r");
            if (!f) { perror("kbd"); exit(1); }
            while (kbd_ntrace < 4096 &&
                   fscanf(f, "%llu %llu", (unsigned long long *)&kbd_trace[kbd_ntrace].cycle,
                          (unsigned long long *)&kbd_trace[kbd_ntrace].key) == 2) kbd_ntrace++;
            fclose(f);
        }
        else if (!strcmp(argv[i], "--index-bits")) IB = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--weak")) weak_mode = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--stats")) statsf = argv[++i];
        else if (!strcmp(argv[i], "--trace")) tracef = argv[++i];
        else if (!strcmp(argv[i], "--fbprefix")) fbprefix = argv[++i];
        else if (!strcmp(argv[i], "--maxcycles")) maxcycles = strtoull(argv[++i], 0, 0);
        else img = argv[i];
    }
    if (!img) { fprintf(stderr, "usage: emu image [--map va:pa:len ...]\n"); exit(2); }
    pc = load_image(img);
    for (int i = 0; i < nmaps; i++)
        for (u64 off = 0; off < maps[i].len; off += PAGE_SIZE)
            pt_insert(maps[i].va + off, maps[i].pa + off);
    /* firmware built the tables; don't bill it to the running system */
    u64 fw_accesses = st_walk_accesses; st_walk_accesses = 0; st_walks = 0;
    (void)fw_accesses;
    P[0] = 1;
    FILE *tf = tracef ? fopen(tracef, "w") : 0;

    for (;;) {
        if (cycle >= maxcycles) { fprintf(stderr, "MAXCYCLES hit at pc=%llx\n", (unsigned long long)pc); break; }
        if (weak_mode) stq_drain_ready();
        /* virtual-time event queue: keyboard trace + timer */
        while (kbd_next < kbd_ntrace && kbd_trace[kbd_next].cycle <= cycle)
            kbd_queue[kbd_tail++ & 255] = kbd_trace[kbd_next++].key;
        if (SR[SR_STATUS] & ST_IE) {
            if (SR[SR_TIMECMP] && cycle >= (u64)SR[SR_TIMECMP]) {
                deliver(CAUSE_TIMER, pc, 0); st_irqs++; continue;
            }
            if (kbd_head != kbd_tail) { deliver(CAUSE_KBD, pc, 0); st_irqs++; continue; }
        }
        /* fetch */
        u128 ipa;
        if (vaccess(pc, 8, 0, 1, &ipa)) { deliver(pending_trap, pc, vload_fault_va); pending_trap = -1; continue; }
        u64 insn = (u64)pread(ipa, 8);
        u64 op   = (insn >> F_OPCODE_OFF) & ((1ULL << F_OPCODE_W) - 1);
        unsigned pred = (insn >> F_PRED_OFF) & ((1ULL << F_PRED_W) - 1);
        unsigned rd   = (insn >> F_DST_OFF)  & 31;
        unsigned rs1  = (insn >> F_SRC1_OFF) & 31;
        unsigned rs2  = (insn >> F_SRC2_OFF) & 31;
        unsigned rs3  = (insn >> F_SRC3_OFF) & 31;
        unsigned mod  = (insn >> F_MOD_OFF)  & ((1ULL << F_MOD_W) - 1);
        u64 immraw    = (insn >> F_IMM_OFF)  & ((1ULL << F_IMM_W) - 1);
        unsigned major = op >> 1, I = op & 1;
        u128 imm = sext_imm(immraw);
        if (pred) st_pred_carried++;
        int psel = (pred >> 1) & 7, ppol = pred & 1;
        if (!(P[psel] ^ ppol)) { st_pred_squashed++; pc += 8; cycle++; st_insns++; continue; }

        u128 a = R[rs1];
        u128 b = I ? imm : apply_mod(R[rs2], mod);
        u128 c = R[rs3];
        u128 next_pc = pc + 8;
        int fault = 0;
        u128 v, ea;
        switch (major) {
        case OP_ADD:  wreg(rd, a + b); break;
        case OP_SUB:  wreg(rd, a - b); break;
        case OP_AND:  wreg(rd, a & b); break;
        case OP_OR:   wreg(rd, a | b); break;
        case OP_XOR:  wreg(rd, a ^ b); break;
        case OP_SHL:  wreg(rd, a << ((unsigned)b & 127)); break;
        case OP_SHR:  wreg(rd, a >> ((unsigned)b & 127)); break;
        case OP_SAR:  wreg(rd, (u128)((s128)a >> ((unsigned)b & 127))); break;
        case OP_MUL:  wreg(rd, a * b); break;
        case OP_MADD: wreg(rd, a * b + c); break;
        case OP_UDIV: wreg(rd, b ? a / b : ~(u128)0); break;
        case OP_SDIV: wreg(rd, b ? (u128)((s128)a / (s128)b) : ~(u128)0); break;
        case OP_UREM: wreg(rd, b ? a % b : a); break;
        case OP_SREM: wreg(rd, b ? (u128)((s128)a % (s128)b) : a); break;
        case OP_CMPEQ:  if ((rd&7)) P[rd&7] = a == b; break;
        case OP_CMPLT:  if ((rd&7)) P[rd&7] = (s128)a < (s128)b; break;
        case OP_CMPLTU: if ((rd&7)) P[rd&7] = a < b; break;
        case OP_CMPLE:  if ((rd&7)) P[rd&7] = (s128)a <= (s128)b; break;
        case OP_CMPLEU: if ((rd&7)) P[rd&7] = a <= b; break;
        case OP_LD8U: case OP_LD8S: case OP_LD16U: case OP_LD16S:
        case OP_LD32U: case OP_LD32S: case OP_LD64U: case OP_LD64S: case OP_LD128: {
            int w = major==OP_LD8U||major==OP_LD8S ? 1 : major==OP_LD16U||major==OP_LD16S ? 2 :
                    major==OP_LD32U||major==OP_LD32S ? 4 : major==OP_LD64U||major==OP_LD64S ? 8 : 16;
            int sx = major==OP_LD8S||major==OP_LD16S||major==OP_LD32S||major==OP_LD64S;
            ea = a + apply_mod(R[rs2], mod) + imm;      /* mem ops use src2 AND imm */
            if (vload(ea, w, &v)) { fault = 1; break; }
            if (sx && w < 16) v = (u128)((s128)(v << (128 - 8*w)) >> (128 - 8*w));
            wreg(rd, v); break;
        }
        case OP_ST8: case OP_ST16: case OP_ST32: case OP_ST64: case OP_ST128: {
            int w = major==OP_ST8 ? 1 : major==OP_ST16 ? 2 : major==OP_ST32 ? 4 : major==OP_ST64 ? 8 : 16;
            ea = a + apply_mod(R[rs2], mod) + imm;
            if (vstore(ea, w, c)) fault = 1;
            break;
        }
        case OP_B:    next_pc = pc + (u128)((s128)imm * 8); break;
        case OP_JAL:  wreg(rd, pc + 8); next_pc = pc + (u128)((s128)imm * 8); break;
        case OP_JALR: v = a + imm;
                      if (v & 7) { raise_trap(CAUSE_ILLEGAL, v); fault = 1; break; }
                      wreg(rd, pc + 8); next_pc = v; break;
        case OP_LDI:  wreg(rd, imm); break;
        case OP_SHORI: wreg(rd, (a << ENC_IMM_BITS) | immraw); break;
        case OP_MFSR: wreg(rd, SR[immraw & 15]); break;
        case OP_MTSR: SR[immraw & 15] = a; break;
        case OP_IRET: next_pc = SR[SR_EPC];
                      SR[SR_STATUS] = (SR[SR_STATUS] & ~ST_IE) | ((SR[SR_STATUS] & ST_PIE) ? ST_IE : 0);
                      break;
        case OP_INVTP: st_invtp++; break;   /* architecturally a nop, for now */
        case OP_HALT: goto halted;
        default: raise_trap(CAUSE_ILLEGAL, 0); fault = 1; break;
        }
        if (tf) {
            char hb[40]; hex128(hb, R[rd]);
            fprintf(tf, "%llu %llx op%u rd=%u %s\n", (unsigned long long)cycle,
                    (unsigned long long)pc, major, rd, hb);
        }
        st_insns++; cycle++;
        if (fault) { deliver(pending_trap, pc, vload_fault_va); pending_trap = -1; continue; }
        pc = next_pc;
    }
halted:
    if (weak_mode) stq_drain_all();
    if (tf) fclose(tf);
    {
        char hb[40]; hex128(hb, R[0]);
        fprintf(stderr, "HALT cycle=%llu r0=%s\n", (unsigned long long)cycle, hb);
    }
    if (statsf) {
        FILE *f = fopen(statsf, "w");
        fprintf(f, "insns=%llu\ncycles=%llu\nwalks=%llu\nwalk_accesses=%llu\n"
                   "walk_depth_max=%llu\npt_nodes=%llu\npt_bytes=%llu\nphys_pages=%llu\n"
                   "irqs=%llu\ntraps=%llu\npred_carried=%llu\npred_squashed=%llu\n"
                   "frames=%llu\ninvtp=%llu\n",
                (unsigned long long)st_insns, (unsigned long long)cycle,
                (unsigned long long)st_walks, (unsigned long long)st_walk_accesses,
                (unsigned long long)st_walk_depth_max, (unsigned long long)st_pt_nodes,
                (unsigned long long)st_pt_bytes, (unsigned long long)phys_pages_allocated,
                (unsigned long long)st_irqs, (unsigned long long)st_traps,
                (unsigned long long)st_pred_carried, (unsigned long long)st_pred_squashed,
                (unsigned long long)st_frames, (unsigned long long)st_invtp);
        fclose(f);
    }
    return (int)(u64)R[0] & 0xff;
}
