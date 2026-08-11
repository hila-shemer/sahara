#ifndef SE_GUI_NIC_HOST_H
#define SE_GUI_NIC_HOST_H

#include <stdint.h>

#include "gui/nic.h"

/* The real backend (`--nic host`): one nonblocking connect()ed UDP
 * socket per flow, created lazily at the flow's first send -- the
 * kernel's connected-socket filter IS the 6.5 address-restricted NAT.
 * DNS flows connect to the host's first resolv.conf nameserver; with
 * none configured, DNS sends drop silently (documented in
 * nic-notes.md). Implemented in nic_host.c, the socket carve-out
 * (allow_banned, out of the source audits, never linked into
 * sahara-emu); this header stays doctrine-clean. */

typedef struct SeNicHost {
    int fd[SE_NIC_UDP_FLOWS]; /* -1 = no socket yet */
    uint32_t resolver_ip;     /* host byte order; 0 = none */
    uint16_t resolver_port;   /* 53 when resolver_ip != 0 */
} SeNicHost;

void SeNicHost_init(SeNicHost *h);

/* The SeNicSend backend entry; ctx is the SeNicHost. Send failures
 * are silent: guest-visibly identical to datagram loss, which UDP
 * callers must survive anyway. */
void SeNicHost_send(void *ctx, uint32_t flow, bool dns, uint32_t ip,
                    uint16_t port, const uint8_t *payload, uint16_t len);

/* One nonblocking sweep over all flow sockets in flow order (the
 * deterministic sweep order the work order fixes): every readable
 * datagram goes back to the translator. Called once per pump tick. */
void SeNicHost_pump(SeNicHost *h, SeNic *n);

#endif /* SE_GUI_NIC_HOST_H */
