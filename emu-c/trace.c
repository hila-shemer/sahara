#include "trace.h"

#include "rwc/status.h"

/* Record header (3.2): u8 type, u8 reserved, u16 reserved, u32 payload
 * length. Payload field widths are normative; sizes below are the sums. */
#define HDR_BYTES 8u
#define EXEC_PAYLOAD 50u   /* u64 + u128 + u64 + u128 + u8 + u8 */
#define MEM_PAYLOAD 41u    /* u64 + u128 + u8 + u128 */
#define TRAP_PAYLOAD 49u   /* u64 + u64 + u128 + u128 + u8 */
#define EVENT_FIXED 20u    /* u64 + u64 + u32 */

static size_t put_u8(uint8_t *b, size_t o, uint8_t v)
{
    b[o] = v;
    return o + 1u;
}

static size_t put_u16(uint8_t *b, size_t o, uint16_t v)
{
    b[o] = (uint8_t)v;
    b[o + 1u] = (uint8_t)(v >> 8);
    return o + 2u;
}

static size_t put_u32(uint8_t *b, size_t o, uint32_t v)
{
    for (unsigned i = 0; i < 4u; i++)
        b[o + i] = (uint8_t)(v >> (8u * i));
    return o + 4u;
}

static size_t put_u64(uint8_t *b, size_t o, uint64_t v)
{
    for (unsigned i = 0; i < 8u; i++)
        b[o + i] = (uint8_t)(v >> (8u * i));
    return o + 8u;
}

static size_t put_u128(uint8_t *b, size_t o, se_u128 v)
{
    for (unsigned i = 0; i < 16u; i++)
        b[o + i] = (uint8_t)(v >> (8u * i));
    return o + 16u;
}

static size_t put_hdr(uint8_t *b, uint8_t type, uint32_t payload_len)
{
    size_t o = put_u8(b, 0, type);
    o = put_u8(b, o, 0);
    o = put_u16(b, o, 0);
    return put_u32(b, o, payload_len);
}

static void emit(SeTrace *t, const uint8_t *b, size_t n)
{
    size_t w = fwrite(b, 1u, n, t->f);
    /* A failed trace write means the run is unreproducible: fail loud. */
    RWC_ASSERT(w == n);
}

void SeTrace_meta(SeTrace *t, const char *text, uint32_t len)
{
    if (!t->f)
        return;
    uint8_t b[HDR_BYTES];
    (void)put_hdr(b, SE_TR_META, len);
    emit(t, b, HDR_BYTES);
    emit(t, (const uint8_t *)text, len);
}

void SeTrace_exec(SeTrace *t, uint64_t cycle, se_u128 pc, uint64_t insn,
                  se_u128 wb, uint8_t flags, uint8_t pred_wb)
{
    if (!t->f)
        return;
    uint8_t b[HDR_BYTES + EXEC_PAYLOAD];
    size_t o = put_hdr(b, SE_TR_EXEC, EXEC_PAYLOAD);
    o = put_u64(b, o, cycle);
    o = put_u128(b, o, pc);
    o = put_u64(b, o, insn);
    o = put_u128(b, o, wb);
    o = put_u8(b, o, flags);
    o = put_u8(b, o, pred_wb);
    emit(t, b, o);
}

static void mem_record(SeTrace *t, uint8_t type, uint64_t cycle, se_u128 ea,
                       uint8_t size, se_u128 val)
{
    uint8_t b[HDR_BYTES + MEM_PAYLOAD];
    size_t o = put_hdr(b, type, MEM_PAYLOAD);
    o = put_u64(b, o, cycle);
    o = put_u128(b, o, ea);
    o = put_u8(b, o, size);
    o = put_u128(b, o, val);
    emit(t, b, o);
}

void SeTrace_memw(SeTrace *t, uint64_t cycle, se_u128 ea, uint8_t size,
                  se_u128 val)
{
    if (!t->f || t->level < 1)
        return;
    mem_record(t, SE_TR_MEMW, cycle, ea, size, val);
}

void SeTrace_memr(SeTrace *t, uint64_t cycle, se_u128 ea, uint8_t size,
                  se_u128 val)
{
    if (!t->f || t->level < 2)
        return;
    mem_record(t, SE_TR_MEMR, cycle, ea, size, val);
}

void SeTrace_devw(SeTrace *t, uint64_t cycle, se_u128 ea, uint8_t size,
                  se_u128 val)
{
    if (!t->f || t->level < 1)
        return;
    mem_record(t, SE_TR_DEVW, cycle, ea, size, val);
}

void SeTrace_trap(SeTrace *t, uint64_t cycle, uint64_t cause, se_u128 epc,
                  se_u128 baddr, uint8_t tl_after)
{
    if (!t->f)
        return;
    uint8_t b[HDR_BYTES + TRAP_PAYLOAD];
    size_t o = put_hdr(b, SE_TR_TRAP, TRAP_PAYLOAD);
    o = put_u64(b, o, cycle);
    o = put_u64(b, o, cause);
    o = put_u128(b, o, epc);
    o = put_u128(b, o, baddr);
    o = put_u8(b, o, tl_after);
    emit(t, b, o);
}

void SeTrace_event(SeTrace *t, uint64_t cycle, uint64_t device,
                   const uint8_t *payload, uint32_t payload_len)
{
    if (!t->f)
        return;
    uint8_t b[HDR_BYTES + EVENT_FIXED];
    size_t o = put_hdr(b, SE_TR_EVENT, EVENT_FIXED + payload_len);
    o = put_u64(b, o, cycle);
    o = put_u64(b, o, device);
    o = put_u32(b, o, payload_len);
    emit(t, b, o);
    if (payload_len)
        emit(t, payload, payload_len);
}
