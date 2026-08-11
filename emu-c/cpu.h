#ifndef SE_CPU_H
#define SE_CPU_H

#include <stdbool.h>
#include <stdint.h>

#include "dev.h"
#include "mem.h"
#include "trace.h"
#include "u128.h"

/* Machine state and the step loop: ISA-SPEC sections 2, 4, 5, 7, 8. */

typedef enum SeRun {
    SE_RUN_RUNNING = 0,
    SE_RUN_HALT,      /* HALT, triple fault, or WFI deadlock */
    SE_RUN_CHECKFAIL, /* a check mode fired; reason in checkfail[] */
} SeRun;

/* Phantom translation cache (--check-invtp): no architectural effect;
 * exists only to assert when a real translation cache would have served
 * a stale entry, i.e. software modified translations without INVTP
 * (ISA-SPEC 8.6-8.7, CONFORMANCE C2). */
typedef struct SeInvtpEnt {
    bool used;
    se_u128 asid, vpn, frame;
    uint8_t perms;
} SeInvtpEnt;

typedef struct SeInvtpCache {
    uint64_t cap; /* power of two; 0 = empty */
    uint64_t count;
    SeInvtpEnt *ents;
} SeInvtpCache;

/* One pending ordinary store in the --check-devorder queue. */
typedef struct SeOrdEnt {
    se_u128 pa;
    se_u128 val;
    uint8_t size;
} SeOrdEnt;

/* One replay-feed event: an EVENT record of the --replay trace, parsed
 * and validated by main.c (devspec/trace.md 4, 5.1), or a live front
 * end's feed entry. The inner payload is inline and sized for the
 * largest device payload -- a full NIC frame (trace.md 4.3); input is
 * 9 bytes, resize 32. ~1.5 KB per event is fine at realistic event
 * counts; an arena-backed payload is the escape hatch if it ever
 * measurably hurts. */
typedef struct SeEvRec {
    uint64_t cycle;
    uint8_t device; /* 0-based device-table index (SE_DEVIDX_*) */
    uint16_t len;
    uint8_t payload[SE_NIC_FRAME_MAX];
} SeEvRec;

typedef struct SeCpu {
    se_u128 r[32];    /* r31 kept zero */
    uint8_t p[8];     /* 0/1; p[0] kept 1 */
    se_u128 sreg[16]; /* sreg[SREG_CYCLE] unused; cycle below is live */
    se_u128 pc;
    se_u128 cycle;
    SeMem *mem;
    SeTrace *tr;
    SeDev *dev; /* NULL in unit tests: register windows then DEVERR */
    bool check_invtp;
    SeInvtpCache invtp;
    /* --check-devorder N (ISA-SPEC 9.2, CONFORMANCE C7): ordinary RAM
     * stores sit in a FIFO of depth N; loads forward from it byte-wise;
     * device accesses and atomics drain it. Semantics-neutral on this
     * single-CPU platform (SPEC-ISSUES 30 toolchain-side) -- the mode's
     * testable property, which c7_dev_ordq asserts. */
    uint64_t devorder_depth; /* 0 = mode off */
    SeOrdEnt *ordq;          /* ring of devorder_depth entries */
    uint64_t ordq_head, ordq_count;
    /* Event feed: events apply in record order at the first boundary
     * where cycle reaches theirs (trace.md 5.2). Two exclusive owners:
     * --replay (main.c points ev at the validated record array) or the
     * live front end (SeCpu_feed appends to the owned `feed` array and
     * aims ev at it) -- both are consumed by the same apply_events /
     * wfi_wait path, so live and replay cannot diverge. */
    const SeEvRec *ev; /* NULL when neither replaying nor live-fed */
    uint64_t ev_count;
    uint64_t ev_next; /* first not-yet-applied index */
    SeEvRec *feed;     /* SeCpu_feed's growable backing store */
    uint64_t feed_cap;
    /* Live-session WFI handling (GUI front end only; both false in
     * headless builds so the deadlock halt is unchanged): with
     * live_yield set, a WFI that would deadlock returns an idle
     * outcome instead -- pc still at the WFI, nothing retired, no
     * records emitted -- and wfi_idle tells the front end to block
     * for host input (SPEC-ISSUES 36). */
    bool live_yield;
    bool wfi_idle;
    SeRun state;
    char checkfail[160];
    const char *halt_note; /* stderr diagnostic for non-HALT halts */
} SeCpu;

/* Translation access kinds; also index the PF/PERM cause tables. */
enum { SE_ACC_FETCH = 0, SE_ACC_LOAD = 1, SE_ACC_STORE = 2 };

typedef struct SeXlate {
    bool fault;
    uint64_t cause;
    se_u128 baddr;
    se_u128 pa;
} SeXlate;

void SeCpu_reset(SeCpu *c, SeMem *m, SeTrace *t);
/* Execute one instruction or deliver one trap/interrupt. */
void SeCpu_step(SeCpu *c);
/* Live front end only: append one host event to the feed. It applies
 * at the first boundary whose cycle reaches its stamp, through the
 * unchanged replay path (apply_events recomputes the drop flag and
 * records what was accepted). The stamp is max(earliest_cycle, current
 * cycle, last queued stamp): never in the past, and the queue stays
 * sorted so wfi_wait's head peek is always the next wake. Feeding
 * clears wfi_idle. Must not be mixed with a --replay feed. */
void SeCpu_feed(SeCpu *c, uint8_t device, const uint8_t *payload,
                uint16_t len, uint64_t earliest_cycle);
/* Exposed for unit tests: translate va for an access kind under the
 * current MMU state (ISA-SPEC section 8). */
SeXlate SeCpu_translate(SeCpu *c, se_u128 va, int acc);

#endif /* SE_CPU_H */
