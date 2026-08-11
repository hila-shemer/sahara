#ifndef SE_GUI_NIC_FAKE_H
#define SE_GUI_NIC_FAKE_H

#include <stdint.h>

#include "gui/nic.h"

/* The test backend (`--nic fake`): every forwarded datagram is echoed
 * back verbatim from its remote endpoint at the next pump tick. No
 * sockets anywhere in this TU -- it is what makes the scripted NIC
 * gate deterministic and CI-safe, and what the record->replay
 * byte-identity proof runs against. The pending queue is fixed at 64
 * and drop-newest on overflow: a scripted guest cannot outrun one
 * pump tick by more than that, and determinism only needs the drop
 * rule to be fixed. */

#define SE_NIC_FAKE_QDEPTH 64u

typedef struct SeNicFakeDgram {
    uint32_t flow;
    uint16_t len;
    uint8_t data[SE_NIC_UDP_MAX];
} SeNicFakeDgram;

typedef struct SeNicFake {
    SeNicFakeDgram q[SE_NIC_FAKE_QDEPTH];
    uint32_t head;
    uint32_t count;
} SeNicFake;

void SeNicFake_reset(SeNicFake *f);

/* The SeNicSend backend entry; ctx is the SeNicFake. */
void SeNicFake_send(void *ctx, uint32_t flow, bool dns, uint32_t ip,
                    uint16_t port, const uint8_t *payload, uint16_t len);

/* Hand every datagram queued since the last pump back to the
 * translator, FIFO, as if each arrived from its flow's remote. */
void SeNicFake_pump(SeNicFake *f, SeNic *n);

#endif /* SE_GUI_NIC_FAKE_H */
