/* Short-tier unit tests for SVP/1 (gui/svp.h): fixed-message layout,
 * the incremental receiver under every split, the RAW/XRLE frame codec
 * round trip across successive frames, and rejection of every
 * malformation the decoder guards -- the socket shims above these are
 * too thin to unit-test; run-gui-tests.sh's serve/view leg covers the
 * assembled pipeline. */
#include <stdio.h>
#include <string.h>

#include "gui/svp.h"
#include "hostmem.h"
#include "rwc/status.h"

enum { W = 64, H = 48 };

static void fill(uint8_t *fb, uint32_t seed)
{
    for (uint32_t i = 0; i < 4u * W * H; i++)
        fb[i] = (uint8_t)((i * 2654435761u) >> 24 ^ seed);
}

/* Feed msg into a fresh receiver n bytes at a time. */
static bool rx_one(SeSvpRx *r, const uint8_t *msg, uint64_t len, uint64_t step,
                   SeSvpMsg *out)
{
    uint64_t at = 0;
    while (at < len) {
        uint64_t room;
        uint8_t *dst = SeSvpRx_space(r, &room);
        uint64_t n = len - at < step ? len - at : step;
        RWC_ASSERT(n <= room);
        memcpy(dst, msg + at, n);
        SeSvpRx_commit(r, n);
        at += n;
        if (at < len)
            RWC_ASSERT(!SeSvpRx_next(r, out)); /* never early */
    }
    return SeSvpRx_next(r, out);
}

static void test_fixed_messages(void)
{
    static uint8_t rxbuf[4096];
    SeSvpRx r;
    SeSvpMsg m;
    uint8_t b[64];

    SeSvpRx_reset(&r, rxbuf, sizeof rxbuf);
    uint32_t n = SeSvp_hello(b, 640u, 480u);
    RWC_ASSERT(n == 20u && b[0] == SE_SVP_HELLO && b[4] == 12u);
    RWC_ASSERT(rx_one(&r, b, n, 1u, &m));
    uint32_t w, h;
    RWC_ASSERT(SeSvp_parse_hello(&m, &w, &h) && w == 640u && h == 480u);

    n = SeSvp_key(b, 0x04u, true, false);
    RWC_ASSERT(rx_one(&r, b, n, 3u, &m));
    uint32_t usage;
    bool press, repeat;
    RWC_ASSERT(SeSvp_parse_key(&m, &usage, &press, &repeat));
    RWC_ASSERT(usage == 0x04u && press && !repeat);
    RWC_ASSERT(!SeSvp_parse_mouse(&m, &(int32_t){0}, &(int32_t){0},
                                  &(uint8_t){0})); /* type-checked */

    n = SeSvp_mouse(b, -5, 700, 0xFFu);
    RWC_ASSERT(rx_one(&r, b, n, 5u, &m));
    int32_t x, y;
    uint8_t btn;
    RWC_ASSERT(SeSvp_parse_mouse(&m, &x, &y, &btn));
    RWC_ASSERT(x == -5 && y == 700 && btn == 7u); /* mask to 3 bits */

    n = SeSvp_ping(b, SE_SVP_PING, 0x1122334455667788ull);
    RWC_ASSERT(rx_one(&r, b, n, 8u, &m));
    uint64_t tok;
    RWC_ASSERT(SeSvp_parse_ping(&m, &tok) && tok == 0x1122334455667788ull);

    n = SeSvp_empty(b, SE_SVP_CLOSE);
    RWC_ASSERT(n == 8u && rx_one(&r, b, n, 2u, &m));
    RWC_ASSERT(m.type == SE_SVP_CLOSE && m.len == 0u);

    /* Two messages in one push come out in order. */
    n = SeSvp_empty(b, SE_SVP_FOCUSLOST);
    n += SeSvp_empty(b + n, SE_SVP_BUSY);
    uint64_t room;
    uint8_t *dst = SeSvpRx_space(&r, &room);
    memcpy(dst, b, n);
    SeSvpRx_commit(&r, n);
    RWC_ASSERT(SeSvpRx_next(&r, &m) && m.type == SE_SVP_FOCUSLOST);
    RWC_ASSERT(SeSvpRx_next(&r, &m) && m.type == SE_SVP_BUSY);
    RWC_ASSERT(!SeSvpRx_next(&r, &m));
}

static void test_rx_rejects(void)
{
    static uint8_t rxbuf[256];
    SeSvpRx r;
    SeSvpMsg m;
    uint8_t b[16] = { SE_SVP_KEY, 1, 0, 0, 0, 0, 0, 0 }; /* nonzero pad */
    SeSvpRx_reset(&r, rxbuf, sizeof rxbuf);
    RWC_ASSERT(!rx_one(&r, b, 8u, 8u, &m) && r.bad);
    /* Sticky: a good message after garbage is not parsed. */
    uint32_t n = SeSvp_empty(b, SE_SVP_CLOSE);
    uint64_t room;
    uint8_t *dst = SeSvpRx_space(&r, &room);
    memcpy(dst, b, n);
    SeSvpRx_commit(&r, n);
    RWC_ASSERT(!SeSvpRx_next(&r, &m));

    /* Oversize for this buffer: a server's input buffer refuses a
     * frame-sized message instead of waiting forever. */
    SeSvpRx_reset(&r, rxbuf, sizeof rxbuf);
    uint8_t big[8] = { SE_SVP_FRAME, 0, 0, 0, 0x00, 0x10, 0, 0 }; /* 4 KB */
    RWC_ASSERT(!rx_one(&r, big, 8u, 8u, &m) && r.bad);

    /* Wrong payload sizes fail the typed parsers. */
    SeSvpRx_reset(&r, rxbuf, sizeof rxbuf);
    uint8_t shortkey[12] = { SE_SVP_KEY, 0, 0, 0, 4, 0, 0, 0 };
    RWC_ASSERT(rx_one(&r, shortkey, 12u, 12u, &m));
    RWC_ASSERT(!SeSvp_parse_key(&m, &(uint32_t){0}, &(bool){0},
                                &(bool){0}));
    uint8_t hello_v2[20];
    RWC_ASSERT(SeSvp_hello(hello_v2, 640u, 480u) == 20u);
    hello_v2[8] = 2u; /* version 2 */
    RWC_ASSERT(rx_one(&r, hello_v2, 20u, 20u, &m));
    RWC_ASSERT(!SeSvp_parse_hello(&m, &(uint32_t){0}, &(uint32_t){0}));
}

static void test_frame_codec(void)
{
    uint64_t max = SeSvp_frame_msg_max(W, H);
    uint8_t *msg = se_host_alloc(max);
    uint8_t *rxbuf = se_host_alloc(max + 64u);
    uint32_t *prev = se_host_alloc(4u * W * H);
    static uint8_t cur[4 * W * H], fb[4 * W * H];
    SeSvpEnc e;
    SeSvpRx r;
    SeSvpMsg m;
    uint32_t seq;
    SeSvpEnc_reset(&e, prev, (uint64_t)W * H);
    SeSvpRx_reset(&r, rxbuf, max + 64u);
    memset(fb, 0, sizeof fb);

    /* Frame 0: noise, so XRLE is larger than RAW and RAW is chosen. */
    fill(cur, 0x5Au);
    uint64_t n = SeSvpEnc_frame(&e, cur, W, H, msg);
    RWC_ASSERT(msg[SE_SVP_HDR_BYTES + 4u] == SE_SVP_RAW);
    RWC_ASSERT(rx_one(&r, msg, n, 997u, &m));
    RWC_ASSERT(SeSvp_apply_frame(&m, W, H, fb, &seq) && seq == 0u);
    RWC_ASSERT(memcmp(fb, cur, sizeof cur) == 0);

    /* Frame 1: one "glyph" changes -- XRLE, tiny, exact. */
    for (uint32_t y = 10; y < 26; y++)
        for (uint32_t x = 20; x < 28; x++)
            cur[4u * (y * W + x)] ^= 0xFFu;
    n = SeSvpEnc_frame(&e, cur, W, H, msg);
    RWC_ASSERT(msg[SE_SVP_HDR_BYTES + 4u] == SE_SVP_XRLE);
    RWC_ASSERT(n < 16u * 8u * 12u + 64u); /* 16 runs of 8 words */
    RWC_ASSERT(rx_one(&r, msg, n, 1u, &m));
    RWC_ASSERT(SeSvp_apply_frame(&m, W, H, fb, &seq) && seq == 1u);
    RWC_ASSERT(memcmp(fb, cur, sizeof cur) == 0);

    /* Frame 2: identical -- one all-zero run. */
    n = SeSvpEnc_frame(&e, cur, W, H, msg);
    RWC_ASSERT(n == SE_SVP_HDR_BYTES + 16u + 8u);
    RWC_ASSERT(rx_one(&r, msg, n, 4096u, &m));
    RWC_ASSERT(SeSvp_apply_frame(&m, W, H, fb, &seq) && seq == 2u);
    RWC_ASSERT(memcmp(fb, cur, sizeof cur) == 0);

    /* Frame 3: last word only, then first word only (run edges). */
    cur[4u * W * H - 1u] ^= 1u;
    n = SeSvpEnc_frame(&e, cur, W, H, msg);
    RWC_ASSERT(rx_one(&r, msg, n, 64u, &m));
    RWC_ASSERT(SeSvp_apply_frame(&m, W, H, fb, &seq));
    RWC_ASSERT(memcmp(fb, cur, sizeof cur) == 0);
    cur[0] ^= 1u;
    n = SeSvpEnc_frame(&e, cur, W, H, msg);
    RWC_ASSERT(rx_one(&r, msg, n, 64u, &m));
    RWC_ASSERT(SeSvp_apply_frame(&m, W, H, fb, &seq));
    RWC_ASSERT(memcmp(fb, cur, sizeof cur) == 0);

    /* Rejections, each on a pristine copy of the last XRLE message. */
    uint8_t good[64];
    RWC_ASSERT(n <= sizeof good);
    memcpy(good, msg, n);
    SeSvpMsg bad = { SE_SVP_FRAME, good + SE_SVP_HDR_BYTES,
                     (uint32_t)(n - SE_SVP_HDR_BYTES) };
    RWC_ASSERT(!SeSvp_apply_frame(&bad, W + 1u, H, fb, &seq)); /* geometry */
    good[SE_SVP_HDR_BYTES + 4u] = 9u;                        /* codec */
    RWC_ASSERT(!SeSvp_apply_frame(&bad, W, H, fb, &seq));
    memcpy(good, msg, n);
    bad.len -= 4u;                                     /* truncated */
    RWC_ASSERT(!SeSvp_apply_frame(&bad, W, H, fb, &seq));
    bad.len += 4u;
    good[SE_SVP_HDR_BYTES + 16u] = 0xFFu;              /* zeros past end */
    good[SE_SVP_HDR_BYTES + 19u] = 0x7Fu;
    RWC_ASSERT(!SeSvp_apply_frame(&bad, W, H, fb, &seq));
    memcpy(good, msg, n);
    /* A (0,0) run followed by a run that would otherwise complete the
     * frame: only the no-progress guard rejects this (truncation does
     * not), so the guard is what this line tests. */
    uint8_t zz[SE_SVP_HDR_BYTES + 16u + 16u];
    memcpy(zz, msg, SE_SVP_HDR_BYTES + 16u);
    memset(zz + SE_SVP_HDR_BYTES + 16u, 0, 16u);
    zz[SE_SVP_HDR_BYTES + 24u] = (uint8_t)(W * H);
    zz[SE_SVP_HDR_BYTES + 25u] = (uint8_t)((W * H) >> 8);
    SeSvpMsg z = { SE_SVP_FRAME, zz + SE_SVP_HDR_BYTES, 32u };
    RWC_ASSERT(!SeSvp_apply_frame(&z, W, H, fb, &seq));
    zz[SE_SVP_HDR_BYTES + 16u] = 1u; /* control: (1,0),(W*H,0) overruns */
    RWC_ASSERT(!SeSvp_apply_frame(&z, W, H, fb, &seq));
    zz[SE_SVP_HDR_BYTES + 16u] = 0u;
    memmove(zz + SE_SVP_HDR_BYTES + 16u, zz + SE_SVP_HDR_BYTES + 24u, 8u);
    z.len = 24u; /* control: the lone (W*H,0) run is a valid frame */
    RWC_ASSERT(SeSvp_apply_frame(&z, W, H, fb, &seq));
    /* RAW with the wrong byte count. */
    z.len = 32u;
    zz[SE_SVP_HDR_BYTES + 4u] = SE_SVP_RAW;
    RWC_ASSERT(!SeSvp_apply_frame(&z, W, H, fb, &seq));
}

int main(void)
{
    test_fixed_messages();
    test_rx_rejects();
    test_frame_codec();
    printf("test_svp: ok\n");
    return 0;
}
