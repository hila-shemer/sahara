#ifndef SE_TRACE_H
#define SE_TRACE_H

#include <stdint.h>
#include <stdio.h>

#include "u128.h"

/* Execution trace writer, byte-exact per TOOLING-SPEC.md section 3.2.
 * Fields are serialized explicitly little-endian, one record per fwrite;
 * no struct punning, so host padding can never leak into the stream.
 * Levels (3.2): 0 = EXEC+TRAP+EVENT+META, 1 adds MEMW/DEVW, 2 adds MEMR;
 * the level gate lives here so callers just report what happened. */

enum {
    SE_TR_EXEC = 1,
    SE_TR_MEMW = 2,
    SE_TR_MEMR = 3,
    SE_TR_TRAP = 4,
    SE_TR_EVENT = 5,
    SE_TR_DEVW = 6,
    SE_TR_META = 7,
};

enum {
    SE_TRF_PREDFALSE = 1u << 0,
    SE_TRF_WROTE_DST = 1u << 1,
    SE_TRF_WROTE_PRED = 1u << 2,
};

typedef struct SeTrace {
    FILE *f;    /* NULL = tracing off */
    int level;  /* 0..2 */
} SeTrace;

void SeTrace_meta(SeTrace *t, const char *text, uint32_t len);
void SeTrace_exec(SeTrace *t, uint64_t cycle, se_u128 pc, uint64_t insn,
                  se_u128 wb, uint8_t flags, uint8_t pred_wb);
void SeTrace_memw(SeTrace *t, uint64_t cycle, se_u128 ea, uint8_t size,
                  se_u128 val);
void SeTrace_memr(SeTrace *t, uint64_t cycle, se_u128 ea, uint8_t size,
                  se_u128 val);
void SeTrace_devw(SeTrace *t, uint64_t cycle, se_u128 ea, uint8_t size,
                  se_u128 val);
void SeTrace_trap(SeTrace *t, uint64_t cycle, uint64_t cause, se_u128 epc,
                  se_u128 baddr, uint8_t tl_after);
void SeTrace_event(SeTrace *t, uint64_t cycle, uint64_t device,
                   const uint8_t *payload, uint32_t payload_len);

#endif /* SE_TRACE_H */
