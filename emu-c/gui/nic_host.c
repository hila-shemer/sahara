/* Real UDP sockets for `--nic host`. This TU is the socket carve-out,
 * compiled like sdl_main.c: allow_banned, excluded from the source
 * audits, linked only into sahara-gui -- sahara-emu's banned-symbol
 * audit is the structural proof no socket call can reach headless
 * replay (nic.md 7.3 / NIC-C-35). Everything with a decision in it
 * lives in gui/nic.c where the vector tests are; this file only moves
 * bytes between fds and the backend interface. */
#include "gui/nic_host.h"

#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

#include "rwc/status.h"

/* First IPv4 `nameserver` line of /etc/resolv.conf, parsed just far
 * enough: an IPv6 resolver or no file at all both mean "none", and
 * DNS flows then drop their sends. */
static void resolve_conf(SeNicHost *h)
{
    h->resolver_ip = 0;
    h->resolver_port = 53u;
    FILE *f = fopen("/etc/resolv.conf", "r");
    if (!f)
        return;
    char line[256];
    while (fgets(line, sizeof line, f)) {
        unsigned a, b, c, d;
        if (sscanf(line, " nameserver %u.%u.%u.%u", &a, &b, &c, &d) == 4 &&
            a < 256u && b < 256u && c < 256u && d < 256u) {
            h->resolver_ip = a << 24 | b << 16 | c << 8 | d;
            break;
        }
    }
    fclose(f);
}

void SeNicHost_init(SeNicHost *h)
{
    for (uint32_t i = 0; i < SE_NIC_UDP_FLOWS; i++)
        h->fd[i] = -1;
    resolve_conf(h);
}

void SeNicHost_send(void *ctx, uint32_t flow, bool dns, uint32_t ip,
                    uint16_t port, const uint8_t *payload, uint16_t len)
{
    SeNicHost *h = ctx;
    RWC_ASSERT(flow < SE_NIC_UDP_FLOWS);
    if (dns) {
        if (h->resolver_ip == 0u)
            return; /* no resolver: DNS drops, documented */
        ip = h->resolver_ip;
        port = h->resolver_port;
    }
    if (h->fd[flow] < 0) {
        int fd = socket(AF_INET, SOCK_DGRAM | SOCK_NONBLOCK, 0);
        if (fd < 0)
            return;
        struct sockaddr_in sa;
        memset(&sa, 0, sizeof sa);
        sa.sin_family = AF_INET;
        sa.sin_port = htons(port);
        sa.sin_addr.s_addr = htonl(ip);
        if (connect(fd, (const struct sockaddr *)&sa, sizeof sa) != 0) {
            close(fd);
            return;
        }
        h->fd[flow] = fd;
    }
    (void)send(h->fd[flow], payload, len, 0);
}

void SeNicHost_pump(SeNicHost *h, SeNic *n)
{
    /* 1600 > 1514: any datagram that overflows the buffer is already
     * over the translator's 1472 cap and drops there -- recv may
     * truncate it, the length still lands above the cap. */
    uint8_t buf[1600];
    for (uint32_t i = 0; i < SE_NIC_UDP_FLOWS; i++) {
        if (h->fd[i] < 0)
            continue;
        for (;;) {
            ssize_t r = recv(h->fd[i], buf, sizeof buf, 0);
            if (r < 0)
                break; /* EAGAIN or a soft error: nothing to read */
            SeNic_datagram(n, i, buf, (uint16_t)r);
        }
    }
}
