#ifndef SE_GUI_NIC_H
#define SE_GUI_NIC_H

#include <stdbool.h>
#include <stdint.h>

#include "dev.h"
#include "rwc/attrs.h"

/* The network translator, sans-IO (nic.md 6). Input is guest TX frame
 * bytes (doorbell-captured) and inbound datagrams handed back by a
 * backend; output is synthesized RX frames through the deliver
 * callback and host-op requests through the send callback. No sockets,
 * no SDL, no clock, no allocation -- the byte-exact nic.md 9 test
 * vectors drive this TU directly, and the fake and host backends are
 * guest-visibly equivalent by construction: every frame the guest ever
 * sees is synthesized here, backends only source payload bytes.
 *
 * Milestone-1 scope (the NIC work order's decision 1): the whole
 * deterministic local plane -- classification 6.2, ARP 6.3, DHCP 6.4,
 * virtual-host ICMP echo 6.8, RST generation 6.7.6 -- plus the
 * guest-initiated outbound paths UDP translation 6.5 and DNS
 * forwarding 6.6. TCP translation (6.7) is milestone 2: with no
 * connection table, every TCP segment takes the matching 6.7.6 RST
 * leaf, so an outbound SYN is guest-visibly connection-refused, not a
 * dead wire. Outbound ICMP echo is never forwarded: 6.8 permits silent
 * drop when the host lacks unprivileged ICMP, and "never" is the
 * deterministic reading. Both readings are SPEC-ISSUES entries. */

/* nic.md 6.1: 64 simultaneous UDP flows, never expiring in v1.0. The
 * DNS flow (6.6) counts against the same limit. */
#define SE_NIC_UDP_FLOWS 64u

/* Largest UDP payload a synthesized RX frame can carry
 * (1514 - 14 eth - 20 ip - 8 udp); bigger inbound datagrams drop
 * (nic.md 6.5). */
#define SE_NIC_UDP_MAX 1472u

typedef struct SeNicFlow {
    bool used;
    bool dns;       /* 6.6 flow: backend sends to the host resolver */
    uint16_t gport; /* guest source port */
    uint32_t rip;   /* guest-visible remote IPv4, host byte order */
    uint16_t rport;
} SeNicFlow;

/* Deliver one synthesized RX frame (padded to >= 60, nic.md 3.3) to
 * the front end, which feeds it through SeCpu_feed. */
typedef void (*SeNicDeliver)(void *ctx, const uint8_t *frame,
                             uint16_t len);

/* Forward one UDP payload on a flow to its remote endpoint. ip/port
 * are the guest-visible remote; for a dns flow they read 10.0.2.3:53
 * and the backend substitutes the host's resolver (nic.md 6.6). The
 * backend owns the socket keyed by the flow index -- flows never
 * close, so indices are stable for the whole session. */
typedef void (*SeNicSend)(void *ctx, uint32_t flow, bool dns,
                          uint32_t ip, uint16_t port,
                          const uint8_t *payload, uint16_t len);

typedef struct SeNic {
    SeNicDeliver deliver;
    void *deliver_ctx;
    SeNicSend send;
    void *send_ctx;
    SeNicFlow flows[SE_NIC_UDP_FLOWS];
    uint32_t flow_count; /* flows are appended and never freed */
    uint8_t scratch[SE_NIC_FRAME_MAX]; /* frame composition buffer */
} SeNic;

void SeNic_reset(SeNic *n, SeNicDeliver deliver, void *deliver_ctx,
                 SeNicSend send, void *send_ctx);

/* Classify one doorbell-captured guest frame (nic.md 6.2 decision
 * tree, applied in order; every leaf is a deterministic reply, a
 * forward, or a silent drop). len is the doorbell value, [60, 1514];
 * trailing bytes beyond the IP total length / the 28 ARP payload bytes
 * are ignored (nic.md 3.4). */
void SeNic_tx(SeNic *n, const uint8_t *frame, uint16_t len);

/* One datagram arriving from flow's remote endpoint (backend-sourced;
 * address restriction is the backend's connected socket / the fake's
 * construction). Synthesizes the nic.md 6.5 inbound frame, or drops it
 * if the payload exceeds SE_NIC_UDP_MAX. */
void SeNic_datagram(SeNic *n, uint32_t flow, const uint8_t *payload,
                    uint16_t len);

#endif /* SE_GUI_NIC_H */
