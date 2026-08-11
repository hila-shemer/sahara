#include "gui/nic_fake.h"

#include <string.h>

#include "rwc/status.h"

void SeNicFake_reset(SeNicFake *f)
{
    memset(f, 0, sizeof *f);
}

void SeNicFake_send(void *ctx, uint32_t flow, bool dns, uint32_t ip,
                    uint16_t port, const uint8_t *payload, uint16_t len)
{
    (void)dns; /* the echo peer plays resolver too */
    (void)ip;
    (void)port;
    SeNicFake *f = ctx;
    RWC_ASSERT(len <= SE_NIC_UDP_MAX);
    if (f->count == SE_NIC_FAKE_QDEPTH)
        return; /* drop-newest, deterministically */
    SeNicFakeDgram *d = &f->q[(f->head + f->count) % SE_NIC_FAKE_QDEPTH];
    f->count += 1u;
    d->flow = flow;
    d->len = len;
    memcpy(d->data, payload, len);
}

void SeNicFake_pump(SeNicFake *f, SeNic *n)
{
    while (f->count != 0u) {
        const SeNicFakeDgram *d = &f->q[f->head];
        f->head = (f->head + 1u) % SE_NIC_FAKE_QDEPTH;
        f->count -= 1u;
        SeNic_datagram(n, d->flow, d->data, d->len);
    }
}
