/* SVP/1 framing and frame codecs, sans-IO (gui/svp.h). The socket
 * shims (gui/be_svp.c, gui/view_main.c) only move bytes between fds
 * and these functions; every decision -- message layout, the XRLE
 * run coding, every bounds check on untrusted input -- is here, under
 * full doctrine and the unit tests in test_svp.c. */
#include "gui/svp.h"

#include <string.h>

#include "rwc/status.h"

static void wr32(uint8_t *p, uint32_t v)
{
    for (unsigned i = 0; i < 4u; i++)
        p[i] = (uint8_t)(v >> (8u * i));
}

static void wr64(uint8_t *p, uint64_t v)
{
    for (unsigned i = 0; i < 8u; i++)
        p[i] = (uint8_t)(v >> (8u * i));
}

static uint32_t rd32(const uint8_t *p)
{
    uint32_t v = 0;
    for (unsigned i = 0; i < 4u; i++)
        v |= (uint32_t)p[i] << (8u * i);
    return v;
}

static uint64_t rd64(const uint8_t *p)
{
    uint64_t v = 0;
    for (unsigned i = 0; i < 8u; i++)
        v |= (uint64_t)p[i] << (8u * i);
    return v;
}

static uint32_t header(uint8_t *out, SeSvpType type, uint32_t len)
{
    out[0] = (uint8_t)type;
    out[1] = out[2] = out[3] = 0u;
    wr32(out + 4u, len);
    return SE_SVP_HDR_BYTES;
}

uint32_t SeSvp_hello(uint8_t *out, uint32_t w, uint32_t h)
{
    uint32_t n = header(out, SE_SVP_HELLO, 12u);
    wr32(out + n, SE_SVP_VERSION);
    wr32(out + n + 4u, w);
    wr32(out + n + 8u, h);
    return n + 12u;
}

uint32_t SeSvp_key(uint8_t *out, uint32_t usage, bool press, bool repeat)
{
    uint32_t n = header(out, SE_SVP_KEY, 8u);
    wr32(out + n, usage);
    out[n + 4u] = press ? 1u : 0u;
    out[n + 5u] = repeat ? 1u : 0u;
    out[n + 6u] = out[n + 7u] = 0u;
    return n + 8u;
}

uint32_t SeSvp_mouse(uint8_t *out, int32_t x, int32_t y, uint8_t buttons)
{
    uint32_t n = header(out, SE_SVP_MOUSE, 12u);
    wr32(out + n, (uint32_t)x);
    wr32(out + n + 4u, (uint32_t)y);
    out[n + 8u] = buttons;
    out[n + 9u] = out[n + 10u] = out[n + 11u] = 0u;
    return n + 12u;
}

uint32_t SeSvp_ping(uint8_t *out, SeSvpType type, uint64_t token)
{
    RWC_ASSERT(type == SE_SVP_PING || type == SE_SVP_PONG);
    uint32_t n = header(out, type, 8u);
    wr64(out + n, token);
    return n + 8u;
}

uint32_t SeSvp_empty(uint8_t *out, SeSvpType type)
{
    return header(out, type, 0u);
}

/* ------------------------------------------------------------- frames */

enum { FRAME_FIXED = 16u }; /* seq, codec + 3 zero, width, height */

uint64_t SeSvp_frame_msg_max(uint32_t w, uint32_t h)
{
    uint64_t words = (uint64_t)w * h;
    /* XRLE's worst case: every other word differs, one 8-byte run
     * header per changed word. RAW is 4*words; take the larger. */
    return SE_SVP_HDR_BYTES + FRAME_FIXED + 4u * words + 8u * (words + 1u);
}

void SeSvpEnc_reset(SeSvpEnc *e, uint32_t *prev_words, uint64_t words)
{
    e->prev = prev_words;
    e->words = words;
    e->seq = 0;
    for (uint64_t i = 0; i < words; i++)
        prev_words[i] = 0u;
}

/* XRLE body of cur against e->prev into out; returns its byte length. */
static uint64_t xrle(const SeSvpEnc *e, const uint8_t *cur, uint8_t *out)
{
    uint64_t i = 0, o = 0;
    while (i < e->words) {
        uint32_t zeros = 0;
        while (i < e->words && (rd32(cur + 4u * i) ^ e->prev[i]) == 0u) {
            zeros++;
            i++;
        }
        uint64_t lit0 = i;
        while (i < e->words && (rd32(cur + 4u * i) ^ e->prev[i]) != 0u)
            i++;
        uint32_t n = (uint32_t)(i - lit0);
        wr32(out + o, zeros);
        wr32(out + o + 4u, n);
        o += 8u;
        for (uint64_t k = lit0; k < i; k++, o += 4u)
            wr32(out + o, rd32(cur + 4u * k) ^ e->prev[k]);
    }
    return o;
}

uint64_t SeSvpEnc_frame(SeSvpEnc *e, const uint8_t *frame, uint32_t w,
                        uint32_t h, uint8_t *out)
{
    uint64_t words = (uint64_t)w * h;
    RWC_ASSERT(words == e->words);
    uint8_t *body = out + SE_SVP_HDR_BYTES + FRAME_FIXED;
    uint64_t blen = xrle(e, frame, body);
    uint8_t codec = SE_SVP_XRLE;
    if (blen >= 4u * words) {
        memcpy(body, frame, 4u * words);
        blen = 4u * words;
        codec = SE_SVP_RAW;
    }
    for (uint64_t i = 0; i < words; i++)
        e->prev[i] = rd32(frame + 4u * i);
    uint64_t plen = FRAME_FIXED + blen;
    RWC_ASSERT(plen <= SE_SVP_PAYLOAD_MAX);
    uint32_t n = header(out, SE_SVP_FRAME, (uint32_t)plen);
    wr32(out + n, e->seq++);
    out[n + 4u] = codec;
    out[n + 5u] = out[n + 6u] = out[n + 7u] = 0u;
    wr32(out + n + 8u, w);
    wr32(out + n + 12u, h);
    return n + plen;
}

bool SeSvp_apply_frame(const SeSvpMsg *m, uint32_t w, uint32_t h,
                       uint8_t *fb, uint32_t *seq)
{
    if (m->type != SE_SVP_FRAME || m->len < FRAME_FIXED)
        return false;
    const uint8_t *p = m->p;
    if (rd32(p + 8u) != w || rd32(p + 12u) != h)
        return false;
    uint64_t words = (uint64_t)w * h;
    const uint8_t *b = p + FRAME_FIXED;
    uint64_t blen = m->len - FRAME_FIXED;
    *seq = rd32(p);
    if (p[4] == SE_SVP_RAW) {
        if (blen != 4u * words)
            return false;
        memcpy(fb, b, blen);
        return true;
    }
    if (p[4] != SE_SVP_XRLE)
        return false;
    uint64_t at = 0, o = 0;
    while (at < words) {
        if (blen - o < 8u)
            return false;
        uint64_t zeros = rd32(b + o), n = rd32(b + o + 4u);
        o += 8u;
        if (zeros > words - at || n > words - at - zeros)
            return false;
        if (zeros == 0u && n == 0u)
            return false; /* a no-progress run: never emitted */
        at += zeros;
        if ((blen - o) / 4u < n)
            return false;
        for (uint64_t k = 0; k < n; k++, at++, o += 4u)
            wr32(fb + 4u * at, rd32(fb + 4u * at) ^ rd32(b + o));
    }
    return o == blen;
}

/* ------------------------------------------------------------ receive */

void SeSvpRx_reset(SeSvpRx *r, uint8_t *buf, uint64_t cap)
{
    RWC_ASSERT(cap >= SE_SVP_HDR_BYTES + 64u);
    r->buf = buf;
    r->cap = cap;
    r->len = 0;
    r->off = 0;
    r->bad = false;
}

uint8_t *SeSvpRx_space(SeSvpRx *r, uint64_t *room)
{
    if (r->off != 0u) {
        memmove(r->buf, r->buf + r->off, r->len - r->off);
        r->len -= r->off;
        r->off = 0;
    }
    *room = r->cap - r->len;
    return r->buf + r->len;
}

void SeSvpRx_commit(SeSvpRx *r, uint64_t n)
{
    RWC_ASSERT(n <= r->cap - r->len);
    r->len += n;
}

/* A payload the buffer cannot hold is as fatal as garbage: a server's
 * small input buffer rejects a view that sends frames. */
static bool header_bad(const SeSvpRx *r, const uint8_t *h, uint32_t plen)
{
    return h[1] != 0u || h[2] != 0u || h[3] != 0u ||
           plen > SE_SVP_PAYLOAD_MAX ||
           SE_SVP_HDR_BYTES + (uint64_t)plen > r->cap;
}

bool SeSvpRx_ready(const SeSvpRx *r)
{
    if (r->bad)
        return false; /* already reported; nothing more will come */
    if (r->len - r->off < SE_SVP_HDR_BYTES)
        return false;
    const uint8_t *h = r->buf + r->off;
    uint32_t plen = rd32(h + 4u);
    return header_bad(r, h, plen) ||
           r->len - r->off >= SE_SVP_HDR_BYTES + (uint64_t)plen;
}

bool SeSvpRx_next(SeSvpRx *r, SeSvpMsg *m)
{
    if (r->bad || r->len - r->off < SE_SVP_HDR_BYTES)
        return false;
    const uint8_t *h = r->buf + r->off;
    uint32_t plen = rd32(h + 4u);
    if (header_bad(r, h, plen)) {
        r->bad = true;
        return false;
    }
    if (r->len - r->off < SE_SVP_HDR_BYTES + (uint64_t)plen)
        return false;
    m->type = (SeSvpType)h[0];
    m->p = h + SE_SVP_HDR_BYTES;
    m->len = plen;
    r->off += SE_SVP_HDR_BYTES + (uint64_t)plen;
    return true;
}

bool SeSvp_parse_hello(const SeSvpMsg *m, uint32_t *w, uint32_t *h)
{
    if (m->type != SE_SVP_HELLO || m->len != 12u ||
        rd32(m->p) != SE_SVP_VERSION)
        return false;
    *w = rd32(m->p + 4u);
    *h = rd32(m->p + 8u);
    return *w != 0u && *h != 0u &&
           (uint64_t)*w * *h * 4u <= SE_SVP_FRAME_MAX_BYTES;
}

bool SeSvp_parse_key(const SeSvpMsg *m, uint32_t *usage, bool *press,
                     bool *repeat)
{
    if (m->type != SE_SVP_KEY || m->len != 8u || m->p[4] > 1u ||
        m->p[5] > 1u)
        return false;
    *usage = rd32(m->p);
    *press = m->p[4] != 0u;
    *repeat = m->p[5] != 0u;
    return true;
}

bool SeSvp_parse_mouse(const SeSvpMsg *m, int32_t *x, int32_t *y,
                       uint8_t *buttons)
{
    if (m->type != SE_SVP_MOUSE || m->len != 12u)
        return false;
    *x = (int32_t)rd32(m->p);
    *y = (int32_t)rd32(m->p + 4u);
    *buttons = m->p[8] & 7u;
    return true;
}

bool SeSvp_parse_ping(const SeSvpMsg *m, uint64_t *token)
{
    if ((m->type != SE_SVP_PING && m->type != SE_SVP_PONG) || m->len != 8u)
        return false;
    *token = rd64(m->p);
    return true;
}
