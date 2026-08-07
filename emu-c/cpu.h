#ifndef SE_CPU_H
#define SE_CPU_H

#include <stdbool.h>
#include <stdint.h>

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

typedef struct SeCpu {
    se_u128 r[32];    /* r31 kept zero */
    uint8_t p[8];     /* 0/1; p[0] kept 1 */
    se_u128 sreg[16]; /* sreg[SREG_CYCLE] unused; cycle below is live */
    se_u128 pc;
    se_u128 cycle;
    SeMem *mem;
    SeTrace *tr;
    bool check_invtp;
    SeInvtpCache invtp;
    uint64_t devorder_depth; /* --check-devorder N; mechanics arrive with
                                the device phase (CONFORMANCE C7) */
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
/* Exposed for unit tests: translate va for an access kind under the
 * current MMU state (ISA-SPEC section 8). */
SeXlate SeCpu_translate(SeCpu *c, se_u128 va, int acc);

#endif /* SE_CPU_H */
