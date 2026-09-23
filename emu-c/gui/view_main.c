/* sahara-view: a window onto a sahara-serve session somewhere else,
 * speaking SVP/1 (gui/svp.h) over one TCP connection.
 *
 *   sahara-view HOST:PORT [--probe N] [--end-session]
 *
 * The view sends raw host facts -- page-7 usage + press/repeat, the
 * pointer in guest pixels with the button mask, capture loss -- and
 * the server translates and feeds them exactly as sahara-gui would, so
 * the session trace on the server replays under `sahara-emu --replay`.
 * Capture UX is sahara-gui's (frontend-notes.md, input.md Appendix A):
 * click to capture, left Ctrl+Alt or focus loss releases, and a release
 * tells the server to synthesize releases for everything held. Closing
 * the window disconnects; the session keeps running on the server.
 *
 * The window is resizable and scales the guest frame to fit (aspect
 * kept, SDL logical size); the guest display stays at its reset mode.
 *
 * --probe N (acceptance measurement): after one second of observing the
 * idle frame rate, alternately type `a` and Backspace N times, and for
 * each report the time from sending the key to presenting the first
 * frame that arrives after it -- input-to-photon as far as this
 * process can see it (compositor and scanout excluded). Also reports
 * PING round trips. Runs under SDL_VIDEODRIVER=offscreen.
 *
 * --end-session sends CLOSE on exit, ending the server's session (it
 * flushes its trace and prints the replay command). Off by default:
 * closing a view, or probing, never ends a session by accident.
 *
 * A BUSY answer or a refused connection is retried for up to a minute:
 * after a laptop resume the server may still hold the slot for the
 * view that died with the suspend, until its keepalive reaps it (about
 * 20 s), and a server being restarted refuses for a moment.
 *
 * This TU is an SDL + socket carve-out (allow_banned, out of the source
 * audits); every protocol decision lives in gui/svp.c. */
#define _GNU_SOURCE /* SOCK_CLOEXEC */
#include <SDL2/SDL.h>

#include <arpa/inet.h>
#include <errno.h>
#include <netdb.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#include "gui/svp.h"
#include "hostmem.h"

enum { USAGE_A = 0x04, USAGE_BACKSPACE = 0x2A, USAGE_LCTRL = 0xE0,
       USAGE_LALT = 0xE2, PROBE_MAX = 10000 };

#define HELLO_TIMEOUT_US 5000000u  /* connected, but no HELLO: give up */
#define RETRY_FOR_US 60000000u     /* BUSY / refused: keep trying */
#define RETRY_EVERY_S 1
#define USAGE "usage: sahara-view HOST:PORT [--probe N] [--end-session]"

/* Why a session could not be opened, when it is worth trying again. */
typedef enum OpenResult {
    OPEN_OK,
    OPEN_BUSY,    /* another view (maybe a dead one) owns the session */
    OPEN_REFUSED, /* nothing listening there right now */
} OpenResult;

static int fd = -1;
static SeSvpRx rx;
static uint32_t gw, gh;
static uint8_t *fb;
static SDL_Window *win;
static SDL_Renderer *ren;
static SDL_Texture *tex;
static bool captured, lctrl, lalt;
static uint8_t btn_mask;
static uint64_t frames; /* presented */
static uint64_t frame_rx_us; /* when the newest FRAME was parsed */
/* Bandwidth accounting for the step-6 trigger (remote-frontend plan):
 * FRAME bytes on the wire, and the busiest one-second window. */
static uint64_t frame_bytes, win_start_us, win_bytes, peak_win_bytes;

static void die(const char *msg)
{
    fprintf(stderr, "sahara-view: %s\n", msg);
    exit(1);
}

static uint64_t now_us(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000u + (uint64_t)ts.tv_nsec / 1000u;
}

static void send_all(const uint8_t *p, uint32_t n)
{
    while (n > 0u) {
        ssize_t w = send(fd, p, n, MSG_NOSIGNAL);
        if (w < 0) {
            if (errno == EINTR)
                continue;
            die("connection lost (send)");
        }
        p += w;
        n -= (uint32_t)w;
    }
}

/* False only when every address refused the connection (retryable);
 * any other failure is fatal. */
static bool connect_to(const char *hostport)
{
    char host[256];
    const char *colon = strrchr(hostport, ':');
    if (!colon || (size_t)(colon - hostport) >= sizeof host)
        die(USAGE);
    memcpy(host, hostport, (size_t)(colon - hostport));
    host[colon - hostport] = '\0';
    struct addrinfo hints, *res = NULL;
    memset(&hints, 0, sizeof hints);
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;
    if (getaddrinfo(host, colon + 1, &hints, &res) != 0 || !res)
        die("cannot resolve HOST:PORT");
    bool all_refused = true;
    for (struct addrinfo *a = res; a; a = a->ai_next) {
        fd = socket(a->ai_family, a->ai_socktype | SOCK_CLOEXEC,
                    a->ai_protocol);
        if (fd < 0)
            continue;
        if (connect(fd, a->ai_addr, a->ai_addrlen) == 0)
            break;
        if (errno != ECONNREFUSED)
            all_refused = false;
        close(fd);
        fd = -1;
    }
    freeaddrinfo(res);
    if (fd < 0) {
        if (all_refused)
            return false;
        die("cannot connect (is sahara-serve listening there?)");
    }
    int one = 1;
    (void)setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
    return true;
}

/* Read whatever is available within timeout_ms; false on EOF. A
 * timeout is not EOF: callers that need a message by a deadline keep
 * their own clock. */
static bool pull(int timeout_ms)
{
    struct pollfd p = { .fd = fd, .events = POLLIN };
    if (poll(&p, 1, timeout_ms) <= 0)
        return true;
    uint64_t room;
    uint8_t *dst = SeSvpRx_space(&rx, &room);
    ssize_t n = recv(fd, dst, room, MSG_DONTWAIT);
    if (n == 0)
        return false;
    if (n < 0)
        return errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR;
    SeSvpRx_commit(&rx, (uint64_t)n);
    return true;
}

/* Connect and read HELLO into rx (a small buffer: HELLO sizes the
 * rest). BUSY and refusal come back for the caller to retry; a
 * connection that stays silent for HELLO_TIMEOUT_US is fatal -- that
 * is not a sahara-serve, or it is wedged. */
static OpenResult open_session(const char *hostport, SeSvpMsg *hello)
{
    if (!connect_to(hostport))
        return OPEN_REFUSED;
    SeSvpRx_reset(&rx, rx.buf, rx.cap);
    uint64_t t0 = now_us();
    while (!SeSvpRx_next(&rx, hello)) {
        if (rx.bad)
            die("malformed stream from server (not an SVP/1 server?)");
        uint64_t spent = now_us() - t0;
        if (spent >= HELLO_TIMEOUT_US)
            die("no HELLO within 5 s (not a sahara-serve, or wedged?)");
        if (!pull((int)((HELLO_TIMEOUT_US - spent) / 1000u) + 1))
            die("server closed the connection before HELLO");
    }
    if (hello->type != SE_SVP_BUSY)
        return OPEN_OK;
    close(fd);
    fd = -1;
    return OPEN_BUSY;
}

static void present(void)
{
    (void)SDL_UpdateTexture(tex, NULL, fb, (int)(4u * gw));
    (void)SDL_RenderClear(ren);
    (void)SDL_RenderCopy(ren, tex, NULL, NULL);
    SDL_RenderPresent(ren);
    frames++;
}

/* Handle every complete message; returns the PONG token seen, or 0. */
static uint64_t drain(void)
{
    SeSvpMsg m;
    uint64_t pong = 0;
    while (SeSvpRx_next(&rx, &m)) {
        uint32_t seq;
        switch (m.type) {
        case SE_SVP_FRAME:
            frame_rx_us = now_us();
            frame_bytes += SE_SVP_HDR_BYTES + (uint64_t)m.len;
            if (frame_rx_us - win_start_us >= 1000000u) {
                win_start_us = frame_rx_us;
                win_bytes = 0;
            }
            win_bytes += SE_SVP_HDR_BYTES + (uint64_t)m.len;
            if (win_bytes > peak_win_bytes)
                peak_win_bytes = win_bytes;
            if (!SeSvp_apply_frame(&m, gw, gh, fb, &seq))
                die("malformed FRAME from server");
            present();
            break;
        case SE_SVP_PONG:
            if (!SeSvp_parse_ping(&m, &pong))
                die("malformed PONG from server");
            break;
        case SE_SVP_BUSY: /* only ever instead of HELLO */
            die("session busy: another viewer owns it");
        default:
            break;
        }
    }
    if (rx.bad)
        die("malformed stream from server");
    return pong;
}

static void release(void)
{
    uint8_t m[16];
    if (captured) {
        captured = false;
        SDL_SetWindowGrab(win, SDL_FALSE);
        SDL_ShowCursor(SDL_ENABLE);
    }
    btn_mask = 0;
    send_all(m, SeSvp_empty(m, SE_SVP_FOCUSLOST));
}

static uint8_t sdl_button_bit(uint8_t b)
{
    switch (b) {
    case SDL_BUTTON_LEFT: return 1u;
    case SDL_BUTTON_RIGHT: return 2u;
    case SDL_BUTTON_MIDDLE: return 4u;
    default: return 0u;
    }
}

static void send_key(uint32_t usage, bool press, bool repeat)
{
    uint8_t m[32];
    send_all(m, SeSvp_key(m, usage, press, repeat));
}

/* One SDL event; false when the window closed. */
static bool handle(const SDL_Event *e)
{
    uint8_t m[32];
    switch (e->type) {
    case SDL_QUIT:
        return false;
    case SDL_KEYDOWN:
    case SDL_KEYUP: {
        uint32_t usage = (uint32_t)e->key.keysym.scancode;
        bool down = e->type == SDL_KEYDOWN;
        if (usage == USAGE_LCTRL)
            lctrl = down;
        if (usage == USAGE_LALT)
            lalt = down;
        send_key(usage, down, e->key.repeat != 0);
        if (captured && lctrl && lalt) {
            lctrl = lalt = false;
            release(); /* left Ctrl+Alt: the server releases the chord */
        }
        return true;
    }
    case SDL_WINDOWEVENT:
        if (e->window.event == SDL_WINDOWEVENT_FOCUS_LOST) {
            lctrl = lalt = false;
            release();
        }
        return true;
    case SDL_MOUSEBUTTONDOWN:
        if (!captured) {
            captured = true;
            SDL_SetWindowGrab(win, SDL_TRUE);
            SDL_ShowCursor(SDL_DISABLE);
        }
        btn_mask |= sdl_button_bit(e->button.button);
        send_all(m, SeSvp_mouse(m, e->button.x, e->button.y, btn_mask));
        return true;
    case SDL_MOUSEBUTTONUP:
        if (!captured)
            return true;
        btn_mask &= (uint8_t)~sdl_button_bit(e->button.button);
        send_all(m, SeSvp_mouse(m, e->button.x, e->button.y, btn_mask));
        return true;
    case SDL_MOUSEMOTION:
        if (captured)
            send_all(m, SeSvp_mouse(m, e->motion.x, e->motion.y, btn_mask));
        return true;
    default:
        return true;
    }
}

static int cmp_u64(const void *a, const void *b)
{
    uint64_t x = *(const uint64_t *)a, y = *(const uint64_t *)b;
    return x < y ? -1 : x > y;
}

static void report(const char *what, uint64_t *v, uint32_t n)
{
    qsort(v, n, sizeof v[0], cmp_u64);
    printf("%s: n=%u min %.1f p50 %.1f p95 %.1f max %.1f ms\n", what, n,
           (double)v[0] / 1000.0, (double)v[n / 2] / 1000.0,
           (double)v[(n * 95u) / 100u] / 1000.0, (double)v[n - 1] / 1000.0);
}

static int probe(uint32_t n)
{
    static uint64_t lat[PROBE_MAX], rtt[PROBE_MAX], arr[PROBE_MAX],
        pres[PROBE_MAX];
    /* Idle frame rate: frames the guest presents with no input. If it
     * is not zero, "first frame after the key" may be a spontaneous
     * one, and the numbers below would understate latency. */
    /* The server sends a full frame on connect; that one is not idle
     * traffic, so start the idle window after it arrives. */
    uint64_t tw = now_us();
    while (frames == 0u) {
        if (!pull(100))
            die("server closed the connection");
        (void)drain();
        if (now_us() - tw > 5000000u)
            break; /* guest never presented: measure anyway */
    }
    uint64_t f0 = frames, t0 = now_us();
    while (now_us() - t0 < 1000000u) {
        if (!pull(50))
            die("server closed the connection");
        (void)drain();
    }
    uint64_t idle = frames - f0;
    printf("idle frames in 1 s: %llu%s\n", (unsigned long long)idle,
           idle ? " (WARNING: latency below may be understated)" : "");
    for (uint32_t i = 0; i < n; i++) {
        uint32_t usage = (i % 2u) ? USAGE_BACKSPACE : USAGE_A;
        uint64_t before = frames, ts = now_us();
        send_key(usage, true, false);
        send_key(usage, false, false);
        while (frames == before) {
            if (!pull(1000))
                die("server closed the connection");
            (void)drain();
            if (now_us() - ts > 5000000u)
                die("no frame within 5 s of a key press");
        }
        uint64_t done = now_us();
        lat[i] = done - ts;
        arr[i] = frame_rx_us - ts;   /* server + network */
        pres[i] = done - frame_rx_us; /* decode + present, this side */
        /* RTT: PING with the send time as token. */
        uint8_t m[32];
        uint64_t tp = now_us();
        send_all(m, SeSvp_ping(m, SE_SVP_PING, tp));
        uint64_t got = 0;
        while (got != tp) {
            if (!pull(1000))
                die("server closed the connection");
            got = drain();
            if (now_us() - tp > 5000000u)
                die("no PONG within 5 s");
        }
        rtt[i] = now_us() - tp;
        SDL_Delay(50u); /* let the guest settle between keys */
    }
    report("input-to-present", lat, n);
    report("  of which key->frame arrival", arr, n);
    report("  of which decode+present", pres, n);
    report("ping rtt", rtt, n);
    return 0;
}

int main(int argc, char **argv)
{
    const char *hostport = NULL;
    uint64_t probe_n = 0;
    bool end_session = false;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--probe") == 0 && i + 1 < argc) {
            probe_n = strtoull(argv[++i], NULL, 0);
            if (probe_n == 0u || probe_n > PROBE_MAX)
                die("--probe N must be 1..10000");
        } else if (strcmp(argv[i], "--end-session") == 0) {
            end_session = true;
        } else if (argv[i][0] == '-' || hostport) {
            die(USAGE);
        } else {
            hostport = argv[i];
        }
    }
    if (!hostport)
        die(USAGE);

    /* HELLO first: it sizes everything else. */
    uint64_t cap = 4096u;
    uint8_t *small = se_host_alloc(cap);
    SeSvpRx_reset(&rx, small, cap);
    SeSvpMsg m;
    uint64_t t_first = now_us();
    bool said = false;
    for (;;) {
        OpenResult r = open_session(hostport, &m);
        if (r == OPEN_OK)
            break;
        if (now_us() - t_first >= RETRY_FOR_US)
            die(r == OPEN_BUSY ? "session busy: another viewer owns it "
                                 "(gave up after 60 s)"
                               : "connection refused (gave up after 60 s; "
                                 "is sahara-serve listening there?)");
        if (!said) {
            fprintf(stderr, "sahara-view: %s; retrying for up to 60 s\n",
                    r == OPEN_BUSY ? "session busy (another viewer, or a "
                                     "dead one not reaped yet)"
                                   : "connection refused");
            said = true;
        }
        struct timespec ts = { RETRY_EVERY_S, 0 };
        nanosleep(&ts, NULL);
    }
    if (!SeSvp_parse_hello(&m, &gw, &gh))
        die("bad HELLO (not an SVP/1 server?)");
    /* Carry over anything that arrived behind HELLO. */
    uint64_t big = SeSvp_frame_msg_max(gw, gh) + 64u;
    uint8_t *rxbuf = se_host_alloc(big);
    uint64_t rest = rx.len - rx.off;
    memcpy(rxbuf, rx.buf + rx.off, rest);
    SeSvpRx_reset(&rx, rxbuf, big);
    SeSvpRx_commit(&rx, rest);
    fb = se_host_alloc(4u * gw * gh);

    if (SDL_Init(SDL_INIT_VIDEO) != 0)
        die("SDL_Init failed");
    win = SDL_CreateWindow("sahara (remote)", SDL_WINDOWPOS_UNDEFINED,
                           SDL_WINDOWPOS_UNDEFINED, (int)gw, (int)gh,
                           SDL_WINDOW_RESIZABLE);
    if (!win)
        die("SDL_CreateWindow failed");
    ren = SDL_CreateRenderer(win, -1, 0);
    if (!ren)
        die("SDL_CreateRenderer failed");
    /* Scale to the window, aspect kept; SDL maps pointer coordinates
     * back to logical (guest) pixels for us. */
    (void)SDL_RenderSetLogicalSize(ren, (int)gw, (int)gh);
    tex = SDL_CreateTexture(ren, SDL_PIXELFORMAT_ARGB8888,
                            SDL_TEXTUREACCESS_STREAMING, (int)gw, (int)gh);
    if (!tex)
        die("SDL_CreateTexture failed");
    fprintf(stderr, "sahara-view: connected, guest display %ux%u\n", gw,
            gh);

    int rc = 0;
    if (probe_n) {
        rc = probe((uint32_t)probe_n);
    } else {
        bool open = true;
        while (open) {
            SDL_Event e;
            while (open && SDL_PollEvent(&e))
                open = handle(&e);
            if (!pull(4)) /* bounds added input delay to 4 ms */
                die("server closed the connection");
            (void)drain();
        }
    }
    /* The number that decides the spark H.264 lane: build it when a
     * real guest's peak here stays above 40 Mbit/s, half the 80 Mbit/s
     * remote link (plan, step 6). */
    fprintf(stderr,
            "sahara-view: %llu frames, %llu bytes (%.0f per frame), "
            "peak 1 s %.2f Mbit/s\n",
            (unsigned long long)frames, (unsigned long long)frame_bytes,
            frames ? (double)frame_bytes / (double)frames : 0.0,
            (double)peak_win_bytes * 8.0 / 1e6);
    if (end_session) {
        uint8_t cm[16];
        send_all(cm, SeSvp_empty(cm, SE_SVP_CLOSE));
    }
    close(fd);
    SDL_DestroyTexture(tex);
    SDL_DestroyRenderer(ren);
    SDL_DestroyWindow(win);
    SDL_Quit();
    return rc;
}
