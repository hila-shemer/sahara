/* The SVP backend of the live session (gui/live.h): sahara-serve, the
 * same live session as sahara-gui with its window replaced by one TCP
 * viewer speaking SVP/1 (gui/svp.h). This TU is the socket carve-out,
 * on nic_host.c's pattern: allow_banned, out of the source audits,
 * never linked into sahara-emu. It only moves bytes -- every protocol
 * decision is in gui/svp.c.
 *
 *   sahara-serve [live options] --listen HOST:PORT
 *
 * One viewer owns input; a second connection gets BUSY and is closed.
 * A viewer disconnecting is a capture loss (every held key and button
 * released) and the session keeps running; the next viewer gets HELLO
 * and a full frame. Frames coalesce: while the previous FRAME is still
 * draining, only the newest snapshot is kept, so a slow link never
 * queues stale frames (display.md 5: the host may drop frames). */
#define _GNU_SOURCE /* accept4, SOCK_NONBLOCK/SOCK_CLOEXEC */
#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#include "gui/live.h"
#include "gui/svp.h"
#include "hostmem.h"

const char *const se_live_prog = "sahara-serve";

enum { RX_CAP = 4096 }; /* input messages only; a frame-sized one is bad */

static const char *listen_arg;
static bool scripted;
static int lfd = -1, cfd = -1;
static uint32_t fw, fh;
static uint8_t *last;      /* newest snapshot, 4*fw*fh */
static bool have_last;     /* the guest has PRESENTed at least once */
static bool frame_dirty;   /* last not yet queued to this viewer */
static bool lost_pending;  /* viewer dropped outside poll: release keys */
static uint32_t *enc_prev; /* XRLE reference for this viewer */
static SeSvpEnc enc;
static uint8_t *out;       /* pending bytes to the viewer */
static uint64_t out_len, out_off, out_cap;
static uint8_t rxbuf[RX_CAP];
static SeSvpRx rx;

static void die(const char *msg)
{
    fprintf(stderr, "sahara-serve: %s\n", msg);
    exit(1);
}

int SeLiveBe_option(int argc, char **argv, int i)
{
    if (strcmp(argv[i], "--listen") == 0 && i + 1 < argc) {
        listen_arg = argv[i + 1];
        return 2;
    }
    return 0;
}

static void open_listener(void)
{
    char host[64];
    const char *colon = strrchr(listen_arg, ':');
    if (!colon || (size_t)(colon - listen_arg) >= sizeof host)
        die("--listen must be HOST:PORT (an IPv4 address)");
    memcpy(host, listen_arg, (size_t)(colon - listen_arg));
    host[colon - listen_arg] = '\0';
    char *end = NULL;
    unsigned long port = strtoul(colon + 1, &end, 10);
    if (!end || *end != '\0' || port == 0u || port > 65535u)
        die("--listen port must be 1..65535");
    struct sockaddr_in sa;
    memset(&sa, 0, sizeof sa);
    sa.sin_family = AF_INET;
    sa.sin_port = htons((uint16_t)port);
    if (inet_pton(AF_INET, host, &sa.sin_addr) != 1)
        die("--listen host must be a dotted IPv4 address");
    lfd = socket(AF_INET, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
    if (lfd < 0)
        die("socket failed");
    int one = 1;
    (void)setsockopt(lfd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
    if (bind(lfd, (const struct sockaddr *)&sa, sizeof sa) != 0)
        die("bind failed (address in use, or not this host's address?)");
    if (listen(lfd, 2) != 0)
        die("listen failed");
    fprintf(stderr, "sahara-serve: listening on %s\n", listen_arg);
}

void SeLiveBe_init(SeLive *lv, uint64_t w, uint64_t h, bool is_scripted)
{
    (void)lv;
    scripted = is_scripted;
    fw = (uint32_t)w;
    fh = (uint32_t)h;
    if (scripted)
        return; /* --script owns input and the clock: no network */
    if (!listen_arg)
        die("--listen HOST:PORT is required (bind a specific address)");
    last = se_host_alloc(4u * w * h);
    enc_prev = se_host_alloc(4u * w * h);
    out_cap = SeSvp_frame_msg_max(fw, fh) + 64u;
    out = se_host_alloc(out_cap);
    open_listener();
}

void SeLiveBe_fini(void)
{
    if (cfd >= 0)
        close(cfd);
    if (lfd >= 0)
        close(lfd);
}

uint64_t SeLiveBe_now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000u + (uint64_t)ts.tv_nsec / 1000000u;
}

static void drop_viewer(SeLive *lv)
{
    close(cfd);
    cfd = -1;
    out_len = out_off = 0;
    /* The guest must never see keys stuck down by a vanished viewer
     * (input.md 2.6): a disconnect is a capture loss. */
    if (lv)
        SeLive_host_capture_lost(lv);
    else
        lost_pending = true; /* dropped from present: no session handle */
    fprintf(stderr, "sahara-serve: viewer disconnected\n");
}

/* Push pending bytes; false if the viewer is gone. */
static bool flush(void)
{
    while (out_off < out_len) {
        ssize_t n = send(cfd, out + out_off, out_len - out_off,
                         MSG_NOSIGNAL | MSG_DONTWAIT);
        if (n < 0)
            return errno == EAGAIN || errno == EWOULDBLOCK;
        out_off += (uint64_t)n;
    }
    out_len = out_off = 0;
    return true;
}

/* Queue the newest frame if nothing is draining; coalesce otherwise. */
static bool pump_frame(void)
{
    if (!flush())
        return false;
    if (frame_dirty && out_len == 0u && have_last) {
        out_len = SeSvpEnc_frame(&enc, last, fw, fh, out);
        frame_dirty = false;
        return flush();
    }
    return true;
}

static void queue_small(const uint8_t *msg, uint32_t n)
{
    /* Small replies ride behind whatever is draining; out_cap leaves
     * 64 bytes of room past the largest frame for exactly this. */
    if (out_len + n > out_cap)
        return; /* cannot happen with one frame in flight; drop */
    memcpy(out + out_len, msg, n);
    out_len += n;
}

static void accept_viewer(void)
{
    int fd = accept4(lfd, NULL, NULL, SOCK_NONBLOCK | SOCK_CLOEXEC);
    if (fd < 0)
        return;
    int one = 1;
    (void)setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
    uint8_t msg[32];
    if (cfd >= 0) {
        uint32_t n = SeSvp_empty(msg, SE_SVP_BUSY);
        (void)send(fd, msg, n, MSG_NOSIGNAL | MSG_DONTWAIT);
        close(fd);
        return;
    }
    cfd = fd;
    SeSvpRx_reset(&rx, rxbuf, sizeof rxbuf);
    SeSvpEnc_reset(&enc, enc_prev, (uint64_t)fw * fh);
    out_len = out_off = 0;
    queue_small(msg, SeSvp_hello(msg, fw, fh));
    frame_dirty = have_last; /* full frame against a zero reference */
    fprintf(stderr, "sahara-serve: viewer connected\n");
}

static void handle(SeLive *lv, const SeSvpMsg *m)
{
    uint32_t usage;
    bool press, repeat;
    int32_t x, y;
    uint8_t btn;
    uint64_t token;
    uint8_t reply[32];
    switch (m->type) {
    case SE_SVP_KEY:
        if (SeSvp_parse_key(m, &usage, &press, &repeat))
            SeLive_host_key(lv, usage, press, repeat);
        return;
    case SE_SVP_MOUSE:
        if (SeSvp_parse_mouse(m, &x, &y, &btn))
            SeLive_host_mouse(lv, x, y, btn);
        return;
    case SE_SVP_FOCUSLOST:
        SeLive_host_capture_lost(lv);
        return;
    case SE_SVP_PING:
        if (SeSvp_parse_ping(m, &token))
            queue_small(reply, SeSvp_ping(reply, SE_SVP_PONG, token));
        return;
    case SE_SVP_CLOSE:
        SeLive_host_quit(lv);
        return;
    default:
        return; /* unknown types from a newer viewer are ignored */
    }
}

void SeLiveBe_poll(SeLive *lv)
{
    if (scripted)
        return;
    if (lost_pending) {
        lost_pending = false;
        SeLive_host_capture_lost(lv);
    }
    accept_viewer();
    if (cfd < 0)
        return;
    for (;;) {
        uint64_t room;
        uint8_t *dst = SeSvpRx_space(&rx, &room);
        ssize_t n = recv(cfd, dst, room, MSG_DONTWAIT);
        if (n == 0 || (n < 0 && errno != EAGAIN && errno != EWOULDBLOCK)) {
            drop_viewer(lv);
            return;
        }
        if (n < 0)
            break;
        SeSvpRx_commit(&rx, (uint64_t)n);
        SeSvpMsg m;
        while (SeSvpRx_next(&rx, &m))
            handle(lv, &m);
        if (rx.bad) {
            fprintf(stderr, "sahara-serve: malformed stream\n");
            drop_viewer(lv);
            return;
        }
    }
    if (!pump_frame())
        drop_viewer(lv);
}

void SeLiveBe_present(const uint8_t *frame, uint64_t w, uint64_t h)
{
    if (scripted)
        return; /* frames are output only; the scripted gate has none */
    if (w != fw || h != fh)
        return; /* v1 display never resizes (frontend-notes.md); HELLO's
                   geometry is the only one this viewer can take */
    memcpy(last, frame, 4u * w * h);
    have_last = true;
    frame_dirty = true;
    if (cfd >= 0 && !pump_frame())
        drop_viewer(NULL); /* capture loss runs at the next poll */
}

/* Sleep up to ms, waking early on viewer traffic or a new connection
 * (the next poll handles it) or when a draining frame can move. */
static void wait_fds(int ms)
{
    struct pollfd p[2];
    nfds_t n = 0;
    if (lfd >= 0)
        p[n++] = (struct pollfd){ .fd = lfd, .events = POLLIN };
    if (cfd >= 0)
        p[n++] = (struct pollfd){
            .fd = cfd,
            .events = (short)(POLLIN | (out_len > out_off ? POLLOUT : 0)),
        };
    if (n == 0u) {
        struct timespec ts = { ms / 1000, (long)(ms % 1000) * 1000000L };
        nanosleep(&ts, NULL);
        return;
    }
    (void)poll(p, n, ms);
}

void SeLiveBe_wait_input(int timeout_ms)
{
    wait_fds(timeout_ms);
}

void SeLiveBe_delay(uint64_t ms)
{
    wait_fds((int)ms);
}

void SeLiveBe_release_capture(void)
{
    /* The pointer grab lives in the viewer; nothing to release here. */
}
