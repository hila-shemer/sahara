#include "gui/nic.h"

#include <string.h>

#include "platform.h"
#include "rwc/status.h"

/* nic.md 6.1 network constants. IPs are held in host byte order and
 * converted at the frame edge (be32/put32). */
enum {
    NIC_GUEST_IP = 0x0A00020F, /* 10.0.2.15 */
    NIC_GW_IP = 0x0A000202,    /* 10.0.2.2 (gateway, DHCP server) */
    NIC_DNS_IP = 0x0A000203,   /* 10.0.2.3 */
    NIC_SUBNET = 0x0A000200,   /* 10.0.2.0/24 */
    NIC_BCAST_IP = 0x0A0002FF, /* 10.0.2.255 */
};

#define NIC_LEASE_SECS 86400u

/* The single peer MAC: gateway, DNS, DHCP and every NAT-ed remote. */
static const uint8_t nic_peer_mac[6] = { 0x52, 0x55, 0x0A,
                                         0x00, 0x02, 0x02 };
static const uint8_t nic_bcast_mac[6] = { 0xFF, 0xFF, 0xFF,
                                          0xFF, 0xFF, 0xFF };

/* Guest MAC wire bytes from the platform packing (boot.md 3.6: wire
 * octets little-endian into bits 47:0). */
static void nic_guest_mac(uint8_t out[6])
{
    for (unsigned i = 0; i < 6u; i++)
        out[i] = (uint8_t)(SE_PLAT_MAC >> (8u * i));
}

static uint16_t be16(const uint8_t *p)
{
    return (uint16_t)((uint16_t)p[0] << 8 | p[1]);
}

static uint32_t be32(const uint8_t *p)
{
    return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 |
           (uint32_t)p[2] << 8 | p[3];
}

static void put16(uint8_t *p, uint16_t v)
{
    p[0] = (uint8_t)(v >> 8);
    p[1] = (uint8_t)v;
}

static void put32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)(v >> 24);
    p[1] = (uint8_t)(v >> 16);
    p[2] = (uint8_t)(v >> 8);
    p[3] = (uint8_t)v;
}

/* Internet checksum, incremental: fold at the end. An odd trailing
 * byte pads with zero per RFC 1071. */
static uint32_t csum_add(uint32_t sum, const uint8_t *p, uint32_t len)
{
    for (uint32_t i = 0; i + 1u < len; i += 2u)
        sum += (uint32_t)be16(p + i);
    if (len & 1u)
        sum += (uint32_t)p[len - 1u] << 8;
    return sum;
}

static uint16_t csum_fin(uint32_t sum)
{
    while (sum >> 16)
        sum = (sum & 0xFFFFu) + (sum >> 16);
    return (uint16_t)~sum;
}

/* Pseudo-header sum for UDP/TCP (RFC 768/793). */
static uint32_t csum_pseudo(uint32_t src, uint32_t dst, uint8_t proto,
                            uint16_t l4len)
{
    return (src >> 16) + (src & 0xFFFFu) + (dst >> 16) + (dst & 0xFFFFu) +
           proto + l4len;
}

/* Zero-pad to the 60-byte exposure minimum (nic.md 3.3) and hand the
 * finished frame to the front end. */
static void nic_emit(SeNic *n, uint16_t len)
{
    RWC_ASSERT(len <= SE_NIC_FRAME_MAX);
    if (len < SE_NIC_FRAME_MIN) {
        memset(n->scratch + len, 0, SE_NIC_FRAME_MIN - len);
        len = SE_NIC_FRAME_MIN;
    }
    n->deliver(n->deliver_ctx, n->scratch, len);
}

/* Begin an IPv4 frame in scratch with the 6.1 translator constants
 * (TTL 64, ID 0, DF 0, offset 0); returns the L4 area. The caller
 * fills l4len bytes there (checksummed per protocol) and calls
 * nic_ip_emit, which completes lengths and the header checksum. */
static uint8_t *nic_ip_begin(SeNic *n, const uint8_t *dst_mac,
                             uint8_t proto, uint32_t src_ip,
                             uint32_t dst_ip)
{
    uint8_t *f = n->scratch;
    memcpy(f, dst_mac, 6u);
    memcpy(f + 6u, nic_peer_mac, 6u);
    put16(f + 12u, 0x0800u);
    uint8_t *ip = f + 14u;
    ip[0] = 0x45u;
    ip[1] = 0;
    /* total length at +2: nic_ip_emit */
    put16(ip + 4u, 0); /* ID 0 */
    put16(ip + 6u, 0); /* no flags, offset 0 */
    ip[8] = 64u;       /* TTL */
    ip[9] = proto;
    put16(ip + 10u, 0); /* header checksum: nic_ip_emit */
    put32(ip + 12u, src_ip);
    put32(ip + 16u, dst_ip);
    return ip + 20u;
}

static void nic_ip_emit(SeNic *n, uint16_t l4len)
{
    uint8_t *ip = n->scratch + 14u;
    put16(ip + 2u, (uint16_t)(20u + l4len));
    put16(ip + 10u, csum_fin(csum_add(0, ip, 20u)));
    nic_emit(n, (uint16_t)(14u + 20u + l4len));
}

/* ------------------------------------------------------------- ARP */

static void nic_arp(SeNic *n, const uint8_t *f)
{
    const uint8_t *a = f + 14u;
    /* Ethernet/IPv4 ARP only (6.3): htype 1, ptype 0x0800, hlen 6,
     * plen 4; requests only -- replies, gratuitous-for-self and
     * off-subnet probes all fall out of the checks below. */
    if (be16(a) != 1u || be16(a + 2u) != 0x0800u || a[4] != 6u ||
        a[5] != 4u)
        return;
    if (be16(a + 6u) != 1u)
        return;
    uint32_t tip = be32(a + 24u);
    if ((tip & 0xFFFFFF00u) != NIC_SUBNET)
        return;
    if (tip == NIC_GUEST_IP || tip == NIC_BCAST_IP)
        return;
    /* Proxy-answer the whole subnet with the one peer MAC, unicast to
     * the requester's sender pair. */
    uint8_t *r = n->scratch;
    memcpy(r, a + 8u, 6u); /* requester's sender MAC */
    memcpy(r + 6u, nic_peer_mac, 6u);
    put16(r + 12u, 0x0806u);
    uint8_t *ra = r + 14u;
    put16(ra, 1u);
    put16(ra + 2u, 0x0800u);
    ra[4] = 6u;
    ra[5] = 4u;
    put16(ra + 6u, 2u); /* reply */
    memcpy(ra + 8u, nic_peer_mac, 6u);
    put32(ra + 14u, tip);
    memcpy(ra + 18u, a + 8u, 10u); /* target = sender MAC + IP */
    nic_emit(n, 42u);
}

/* ------------------------------------------------------------ DHCP */

/* One parsed option scan over the BOOTP options region. Truncated or
 * malformed encodings terminate the scan; whatever parsed before the
 * damage stands (drop then follows from a missing option 53). */
typedef struct DhcpOpts {
    uint8_t msg;      /* option 53 value; 0 = absent */
    bool have_reqip;  /* option 50 */
    uint32_t reqip;
    bool have_server; /* option 54 */
    uint32_t server;
} DhcpOpts;

static DhcpOpts dhcp_scan(const uint8_t *bp, uint16_t blen)
{
    DhcpOpts o = { 0, false, 0, false, 0 };
    uint32_t i = 240u;
    while (i < blen) {
        uint8_t code = bp[i];
        if (code == 0u) {
            i += 1u;
            continue;
        }
        if (code == 255u)
            break;
        if (i + 1u >= blen)
            break;
        uint8_t olen = bp[i + 1u];
        if (i + 2u + olen > blen)
            break;
        if (code == 53u && olen >= 1u)
            o.msg = bp[i + 2u];
        else if (code == 50u && olen == 4u) {
            o.have_reqip = true;
            o.reqip = be32(bp + i + 2u);
        } else if (code == 54u && olen == 4u) {
            o.have_server = true;
            o.server = be32(bp + i + 2u);
        }
        i += 2u + olen;
    }
    return o;
}

enum { DHCP_OFFER = 2, DHCP_ACK = 5, DHCP_NAK = 6 };

/* Build and emit one reply per the fixed 6.4 construction: xid/flags/
 * chaddr echoed, everything else constant, BOOTP padded to exactly
 * 300 bytes, options in the normative order. ciaddr is always 0 --
 * 6.4's construction list omits it and 0 is the deterministic reading
 * (SPEC-ISSUES entry). inform selects the ACK-without-51 option set. */
static void nic_dhcp_reply(SeNic *n, const uint8_t *req, uint8_t kind,
                           bool inform)
{
    bool nak = kind == DHCP_NAK;
    uint32_t yiaddr = (nak || inform) ? 0u : NIC_GUEST_IP;
    uint32_t siaddr = nak ? 0u : NIC_GW_IP;
    uint16_t flags = be16(req + 10u);
    /* Broadcast if the request asked for it or yiaddr is 0 (6.4 --
     * the yiaddr-0 leg covers NAK and, by its letter, INFORM). */
    bool bcast = (flags & 0x8000u) != 0u || yiaddr == 0u;
    uint8_t *l4 = nic_ip_begin(n, bcast ? nic_bcast_mac : req + 28u, 17u,
                               NIC_GW_IP,
                               bcast ? 0xFFFFFFFFu : yiaddr);
    put16(l4, 67u);
    put16(l4 + 2u, 68u);
    put16(l4 + 4u, 8u + 300u);
    put16(l4 + 6u, 0); /* UDP checksum absent (6.1) */
    uint8_t *bp = l4 + 8u;
    memset(bp, 0, 300u);
    bp[0] = 2u; /* BOOTREPLY */
    bp[1] = 1u;
    bp[2] = 6u;
    memcpy(bp + 4u, req + 4u, 4u); /* xid */
    put16(bp + 10u, flags);
    put32(bp + 16u, yiaddr);
    put32(bp + 20u, siaddr);
    memcpy(bp + 28u, req + 28u, 16u); /* chaddr, all 16 bytes */
    uint8_t *o = bp + 236u;
    *o++ = 0x63u;
    *o++ = 0x82u;
    *o++ = 0x53u;
    *o++ = 0x63u;
    *o++ = 53u;
    *o++ = 1u;
    *o++ = kind;
    *o++ = 54u;
    *o++ = 4u;
    put32(o, NIC_GW_IP);
    o += 4u;
    if (!nak) {
        if (!inform) {
            *o++ = 51u;
            *o++ = 4u;
            put32(o, NIC_LEASE_SECS);
            o += 4u;
        }
        *o++ = 1u;
        *o++ = 4u;
        put32(o, 0xFFFFFF00u);
        o += 4u;
        *o++ = 3u;
        *o++ = 4u;
        put32(o, NIC_GW_IP);
        o += 4u;
        *o++ = 6u;
        *o++ = 4u;
        put32(o, NIC_DNS_IP);
        o += 4u;
    }
    *o = 255u;
    nic_ip_emit(n, 8u + 300u);
}

static void nic_dhcp(SeNic *n, const uint8_t *bp, uint16_t blen)
{
    /* >= 236 bytes of BOOTP with the cookie and an option 53; plain
     * BOOTP is not served, nor non-Ethernet htype/hlen (6.4). */
    if (blen < 240u)
        return;
    if (bp[1] != 1u || bp[2] != 6u)
        return;
    static const uint8_t cookie[4] = { 0x63, 0x82, 0x53, 0x63 };
    if (memcmp(bp + 236u, cookie, 4u) != 0)
        return;
    DhcpOpts o = dhcp_scan(bp, blen);
    switch (o.msg) {
    case 1: /* DISCOVER: the offer is always 10.0.2.15 */
        nic_dhcp_reply(n, bp, DHCP_OFFER, false);
        return;
    case 3: { /* REQUEST */
        if (o.have_server && o.server != NIC_GW_IP)
            return; /* the guest chose another server; there is none */
        uint32_t req = o.have_reqip ? o.reqip : be32(bp + 12u); /* ciaddr */
        nic_dhcp_reply(n, bp, req == NIC_GUEST_IP ? DHCP_ACK : DHCP_NAK,
                       false);
        return;
    }
    case 8: /* INFORM */
        nic_dhcp_reply(n, bp, DHCP_ACK, true);
        return;
    default: /* DECLINE/RELEASE consumed silently; the rest dropped */
        return;
    }
}

/* ------------------------------------------------------------ ICMP */

static void nic_icmp(SeNic *n, const uint8_t *pl, uint16_t ipl,
                     uint32_t dst)
{
    if (ipl < 8u)
        return;
    if (pl[0] != 8u || pl[1] != 0u)
        return; /* only echo requests are ever answered (6.8) */
    if (dst != NIC_GW_IP && dst != NIC_DNS_IP)
        return; /* outside subnet: never forwarded in milestone 1;
                   broadcast/other 10.0.2.x: drop -- all one leaf */
    uint8_t gmac[6];
    nic_guest_mac(gmac);
    uint8_t *icmp = nic_ip_begin(n, gmac, 1u, dst, NIC_GUEST_IP);
    memcpy(icmp, pl, ipl);
    icmp[0] = 0; /* echo reply */
    put16(icmp + 2u, 0);
    put16(icmp + 2u, csum_fin(csum_add(0, icmp, ipl)));
    nic_ip_emit(n, ipl);
}

/* ------------------------------------------------------------- TCP */

/* Milestone 1 has no connection table, so every valid TCP segment
 * takes a 6.7.6 leaf: a SYN gets the refused-SYN RST|ACK (the 6.7.1
 * "host connect fails" observable -- connection refused, not a dead
 * wire), anything else the no-matching-connection form. A guest RST
 * is never answered (6.7.5; RFC 793 never RSTs an RST). */
static void nic_tcp(SeNic *n, const uint8_t *pl, uint16_t ipl,
                    uint32_t dst)
{
    if (ipl < 20u)
        return;
    uint16_t doff = (uint16_t)((pl[12] >> 4) * 4u);
    if (doff < 20u || doff > ipl)
        return; /* truncated (6.2 step 5) */
    uint32_t sum = csum_pseudo(NIC_GUEST_IP, dst, 6u, ipl);
    if (csum_fin(csum_add(sum, pl, ipl)) != 0u)
        return; /* invalid TCP checksum */
    uint8_t flags = pl[13];
    if ((flags & 0x04u) != 0u)
        return; /* guest RST */
    uint32_t seq = be32(pl + 4u), ack = be32(pl + 8u);
    uint32_t rseq, rack;
    uint8_t rflags;
    if ((flags & 0x12u) == 0x02u) {
        /* SYN, no ACK: refused (6.7.6 first form). */
        rseq = 0u;
        rack = seq + 1u;
        rflags = 0x14u; /* RST|ACK */
    } else if ((flags & 0x10u) != 0u) {
        rseq = ack;
        rack = 0u;
        rflags = 0x04u; /* RST, no ACK */
    } else {
        uint32_t seglen = (uint32_t)(ipl - doff) +
                          ((flags & 0x02u) ? 1u : 0u) +
                          ((flags & 0x01u) ? 1u : 0u);
        rseq = 0u;
        rack = seq + seglen;
        rflags = 0x14u; /* RST|ACK */
    }
    uint8_t gmac[6];
    nic_guest_mac(gmac);
    uint8_t *t = nic_ip_begin(n, gmac, 6u, dst, NIC_GUEST_IP);
    put16(t, be16(pl + 2u));     /* src = the refused destination port */
    put16(t + 2u, be16(pl));     /* dst = guest port */
    put32(t + 4u, rseq);
    put32(t + 8u, rack);
    t[12] = 0x50u; /* data offset 5 */
    t[13] = rflags;
    put16(t + 14u, 0); /* window 0 (6.7.6) */
    put16(t + 16u, 0);
    put16(t + 18u, 0); /* urgent */
    uint32_t rsum = csum_pseudo(dst, NIC_GUEST_IP, 6u, 20u);
    put16(t + 16u, csum_fin(csum_add(rsum, t, 20u)));
    nic_ip_emit(n, 20u);
}

/* ------------------------------------------------------------- UDP */

static void nic_udp_flow(SeNic *n, uint16_t sport, uint32_t dst,
                         uint16_t dport, bool dns, const uint8_t *data,
                         uint16_t dlen)
{
    /* Flow key (6.5): (guest source port, remote IP, remote port).
     * Linear scan; slots are appended and never freed, so the index
     * doubles as the backend's socket key and the deterministic
     * sweep order. */
    for (uint32_t i = 0; i < n->flow_count; i++) {
        SeNicFlow *fl = &n->flows[i];
        if (fl->gport == sport && fl->rip == dst && fl->rport == dport) {
            n->send(n->send_ctx, i, fl->dns, dst, dport, data, dlen);
            return;
        }
    }
    if (n->flow_count == SE_NIC_UDP_FLOWS)
        return; /* 64 flows exist: drop the first datagram (6.5) */
    uint32_t i = n->flow_count;
    n->flow_count += 1u;
    n->flows[i] = (SeNicFlow){ .used = true,
                               .dns = dns,
                               .gport = sport,
                               .rip = dst,
                               .rport = dport };
    n->send(n->send_ctx, i, dns, dst, dport, data, dlen);
}

/* ------------------------------------------------------ SBP/1 boot */

/* The boot-image server on 10.0.2.2:69 (rom/netboot/sbp.md): one more
 * local-plane service beside DHCP, fully synthesized and backend-free,
 * so netboot is guest-visibly identical under --nic fake and host.
 * Stateless by design: DATA(k) is a pure function of (blob, k), so a
 * duplicate REQ/ACK re-elicits identical bytes and the server needs no
 * session table. All SBP integers are little-endian (guest-side
 * convention), unlike everything else in a frame. */

enum {
    SBP_OP_REQ = 1,
    SBP_OP_DATA = 2,
    SBP_OP_ACK = 3,
    SBP_OP_ERR = 4,
};

enum {
    SBP_ERR_NO_IMAGE = 1,  /* no image configured (--serve-image) */
    SBP_ERR_MAX_BLOCK = 2, /* REQ max_block below the served size */
};

static const uint8_t sbp_magic[4] = { 'S', 'B', 'P', '1' };

static uint32_t sbp_le32(const uint8_t *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 |
           (uint32_t)p[3] << 24;
}

static void sbp_put32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16);
    p[3] = (uint8_t)(v >> 24);
}

/* Reply to the request's source port: the ROM's 45063 is a client
 * constant, not a server assumption. */
static void nic_sbp_reply(SeNic *n, uint16_t dport, uint32_t op,
                          uint32_t arg, const uint8_t *data,
                          uint16_t dlen)
{
    uint8_t gmac[6];
    nic_guest_mac(gmac);
    uint8_t *u = nic_ip_begin(n, gmac, 17u, NIC_GW_IP, NIC_GUEST_IP);
    put16(u, 69u);
    put16(u + 2u, dport);
    put16(u + 4u, (uint16_t)(8u + 12u + dlen));
    put16(u + 6u, 0); /* UDP checksum absent (6.1) */
    memcpy(u + 8u, sbp_magic, 4u);
    sbp_put32(u + 12u, op);
    sbp_put32(u + 16u, arg);
    if (dlen != 0u)
        memcpy(u + 20u, data, dlen);
    nic_ip_emit(n, (uint16_t)(8u + 12u + dlen));
}

/* REQ and ACK are exactly 12 payload bytes; anything else -- wrong
 * size, wrong magic, opcodes only the server sends -- drops like any
 * classification miss. ERR when unconfigured is deliberate loudness:
 * a guest netbooting against a serverless plane fails in one round
 * trip instead of timing out (SPEC-ISSUES entry). */
static void nic_sbp(SeNic *n, uint16_t sport, const uint8_t *d,
                    uint16_t dlen)
{
    if (dlen != 12u || memcmp(d, sbp_magic, 4u) != 0)
        return;
    uint32_t op = sbp_le32(d + 4u), arg = sbp_le32(d + 8u), block;
    if (op == SBP_OP_REQ) {
        if (!n->sbp_configured) {
            nic_sbp_reply(n, sport, SBP_OP_ERR, SBP_ERR_NO_IMAGE, NULL,
                          0);
            return;
        }
        if (arg < SE_NIC_SBP_BLOCK) {
            /* A stateless server cannot hold a smaller negotiated
             * block across ACKs; loud refusal beats a broken walk. */
            nic_sbp_reply(n, sport, SBP_OP_ERR, SBP_ERR_MAX_BLOCK, NULL,
                          0);
            return;
        }
        block = 1u;
    } else if (op == SBP_OP_ACK) {
        if (!n->sbp_configured) {
            nic_sbp_reply(n, sport, SBP_OP_ERR, SBP_ERR_NO_IMAGE, NULL,
                          0);
            return;
        }
        if (arg == 0u)
            return; /* blocks are 1-based; ACK(0) is malformed */
        block = arg + 1u;
    } else {
        return;
    }
    uint64_t off = (uint64_t)(block - 1u) * SE_NIC_SBP_BLOCK;
    if (off > n->sbp_len)
        return; /* past the final block: no such DATA exists */
    uint32_t dl = n->sbp_len - (uint32_t)off;
    if (dl > SE_NIC_SBP_BLOCK)
        dl = SE_NIC_SBP_BLOCK;
    /* dl < SE_NIC_SBP_BLOCK marks the final block; an exact-multiple
     * blob ends with a zero-length DATA (off == sbp_len). */
    nic_sbp_reply(n, sport, SBP_OP_DATA, block,
                  dl != 0u ? n->sbp_blob + off : NULL, (uint16_t)dl);
}

static void nic_udp(SeNic *n, const uint8_t *pl, uint16_t ipl,
                    uint32_t src, uint32_t dst)
{
    if (ipl < 8u)
        return;
    uint16_t ulen = be16(pl + 4u);
    if (ulen < 8u || ulen > ipl)
        return; /* truncated relative to the IP total length */
    if (be16(pl + 6u) != 0u) {
        /* Checksum present: verify against the pseudo-header; 0 was
         * accepted without verification (6.2 step 5). */
        uint32_t sum = csum_pseudo(src, dst, 17u, ulen);
        if (csum_fin(csum_add(sum, pl, ulen)) != 0u)
            return;
    }
    uint16_t sport = be16(pl), dport = be16(pl + 2u);
    const uint8_t *data = pl + 8u;
    uint16_t dlen = (uint16_t)(ulen - 8u);
    if (dport == 67u && (dst == 0xFFFFFFFFu || dst == NIC_GW_IP)) {
        nic_dhcp(n, data, dlen);
        return;
    }
    if (dst == NIC_DNS_IP && dport == 53u) {
        nic_udp_flow(n, sport, dst, dport, true, data, dlen);
        return;
    }
    if (dst == NIC_GW_IP && dport == 69u) {
        /* SBP/1 boot service: the one (host, port) pair carved out of
         * the 6.2 subnet drop, gui-only (SPEC-ISSUES entry). */
        nic_sbp(n, sport, data, dlen);
        return;
    }
    if (dst == 0xFFFFFFFFu)
        return; /* limited broadcast other than DHCP: drop (6.2) */
    if ((dst & 0xFFFFFF00u) == NIC_SUBNET)
        return; /* anything else on 10.0.2.0/24: drop */
    nic_udp_flow(n, sport, dst, dport, false, data, dlen);
}

/* ------------------------------------------------------ public API */

void SeNic_reset(SeNic *n, SeNicDeliver deliver, void *deliver_ctx,
                 SeNicSend send, void *send_ctx)
{
    memset(n, 0, sizeof *n);
    n->deliver = deliver;
    n->deliver_ctx = deliver_ctx;
    n->send = send;
    n->send_ctx = send_ctx;
}

void SeNic_tx(SeNic *n, const uint8_t *frame, uint16_t len)
{
    RWC_ASSERT(len >= SE_NIC_FRAME_MIN && len <= SE_NIC_FRAME_MAX);
    /* 6.2 step 1: destination MAC. The source MAC is never checked. */
    if (memcmp(frame, nic_peer_mac, 6u) != 0 &&
        memcmp(frame, nic_bcast_mac, 6u) != 0)
        return;
    uint16_t et = be16(frame + 12u);
    if (et == 0x0806u) {
        nic_arp(n, frame); /* len >= 60 covers the 28 ARP bytes */
        return;
    }
    if (et != 0x0800u)
        return; /* step 2: everything else (0x86DD included) drops */
    /* Step 3: IPv4 sanity. */
    const uint8_t *ip = frame + 14u;
    if (ip[0] != 0x45u)
        return; /* version != 4 or IHL != 5 (options unsupported) */
    uint16_t total = be16(ip + 2u);
    if (total < 20u || total > (uint16_t)(len - 14u))
        return;
    if (csum_fin(csum_add(0, ip, 20u)) != 0u)
        return;
    if ((be16(ip + 6u) & 0x3FFFu) != 0u)
        return; /* MF set or fragment offset != 0 */
    uint32_t src = be32(ip + 12u), dst = be32(ip + 16u);
    uint8_t proto = ip[9];
    const uint8_t *pl = ip + 20u;
    uint16_t ipl = (uint16_t)(total - 20u);
    /* Step 4: source IP -- 10.0.2.15, or 0.0.0.0 for DHCP. */
    if (src != NIC_GUEST_IP &&
        !(src == 0u && proto == 17u && ipl >= 8u && be16(pl + 2u) == 67u))
        return;
    switch (proto) {
    case 17u:
        nic_udp(n, pl, ipl, src, dst);
        return;
    case 6u:
        nic_tcp(n, pl, ipl, dst);
        return;
    case 1u:
        nic_icmp(n, pl, ipl, dst);
        return;
    default:
        return; /* any other IP protocol: drop */
    }
}

void SeNic_serve_image(SeNic *n, const uint8_t *blob, uint32_t len,
                       bool configured)
{
    RWC_ASSERT(!configured || blob != NULL || len == 0u);
    n->sbp_blob = blob;
    n->sbp_len = len;
    n->sbp_configured = configured;
}

void SeNic_datagram(SeNic *n, uint32_t flow, const uint8_t *payload,
                    uint16_t len)
{
    RWC_ASSERT(flow < SE_NIC_UDP_FLOWS && n->flows[flow].used);
    if (len > SE_NIC_UDP_MAX)
        return; /* frame would exceed 1514 bytes (6.5) */
    const SeNicFlow *fl = &n->flows[flow];
    uint8_t gmac[6];
    nic_guest_mac(gmac);
    uint8_t *u = nic_ip_begin(n, gmac, 17u, fl->rip, NIC_GUEST_IP);
    put16(u, fl->rport);
    put16(u + 2u, fl->gport);
    put16(u + 4u, (uint16_t)(8u + len));
    put16(u + 6u, 0); /* checksum absent (6.1) */
    memcpy(u + 8u, payload, len);
    nic_ip_emit(n, (uint16_t)(8u + len));
}
