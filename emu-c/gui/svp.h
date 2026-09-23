#ifndef SE_GUI_SVP_H
#define SE_GUI_SVP_H

#include <stdbool.h>
#include <stdint.h>

#include "rwc/attrs.h"

/* SVP/2, the Sahara view protocol: one TCP stream between sahara-serve
 * (the live session on the host that runs the machine) and sahara-view
 * (a window somewhere else). Software, not hardware: it lives beside
 * rom/netboot/sbp.md, never in devspec, and nothing guest-visible
 * depends on it -- frames are outside the deterministic boundary
 * (display.md 7) and input arrives as raw host facts that the server
 * translates and feeds exactly as a local window would (gui/live.h).
 *
 * Every message is an 8-byte header -- u8 type, three zero bytes, u32
 * payload length, little-endian -- followed by the payload.
 *
 *   server -> view
 *     CHALLENGE {u32 version=2, u8 nonce[32]}   first, on every connect
 *     DENIED {}                       wrong answer; the server closes
 *     HELLO  {u32 version=2, u32 width, u32 height}
 *     FRAME  {u32 seq, u8 codec, 3 zero, u32 width, u32 height, data}
 *     PONG   {u64 token}              (answer to PING, same token)
 *     BUSY   {}                       (another view owns the session)
 *   view -> server
 *     AUTH   {u8 mac[32]}             answer to CHALLENGE, sent once
 *     KEY    {u32 usage, u8 press, u8 repeat, 2 zero}   page-7 usage
 *     MOUSE  {i32 x, i32 y, u8 buttons, 3 zero}  guest pixels, mask
 *                                                 bit0 L, bit1 R, bit2 M
 *     FOCUSLOST {}                    capture lost: release all
 *     PING   {u64 token}              latency probe, echoed as PONG
 *     CLOSE  {}                       this view is leaving (detach)
 *
 * Authentication (new in version 2; VNC's shape, with HMAC in place of
 * DES): both ends hold a shared secret token (a file, never argv).
 * The server's first message is CHALLENGE with 32 fresh random bytes;
 * the view answers AUTH with mac = HMAC-SHA256(token, "SVP/2 AUTH" ||
 * nonce), so the token itself never crosses the wire and a recorded
 * answer is useless against the next nonce. The server compares in
 * constant time and allows one attempt: any first message other than
 * a right AUTH, or none within SE_SVP_AUTH_DEADLINE_MS, gets DENIED (or
 * just a close) and the connection ends. Until then the server sends
 * nothing else and reads no input; an unauthenticated connection never
 * holds or contends for the viewer slot. After a right AUTH the reply
 * is HELLO when the slot is free, BUSY when another authenticated view
 * owns it. The view does not authenticate the server (one-way, as in
 * VNC): the tailnet already authenticates the host.
 *
 * CLOSE, like a dropped connection, detaches only that view: the
 * session keeps running and the slot frees for the next one. Nothing
 * a view sends ends the session.
 *
 * Codecs: RAW is the frame snapshot itself (4*w*h bytes, XRGB8888-LE
 * rows, display.md 3.3). XRLE XORs the snapshot, as u32 words, against
 * the previous frame on this connection (zeros before the first) and
 * run-length codes the result as repeated {u32 zero_words, u32 n, n
 * literal words} until w*h words are covered: a console redraw that
 * touches one glyph costs a few hundred bytes instead of 1.2 MB. */

enum {
    SE_SVP_HDR_BYTES = 8,
    SE_SVP_VERSION = 2,
    SE_SVP_NONCE_BYTES = 32,
    SE_SVP_MAC_BYTES = 32,
    SE_SVP_AUTH_DEADLINE_MS = 5000, /* connect to AUTH, server side */
    /* Token bounds, after trailing whitespace is trimmed: 16 bytes is
     * the least worth calling a secret (the suggested one is 32 random
     * bytes, 44 in base64); the cap bounds a file read. */
    SE_SVP_TOKEN_MIN = 16,
    SE_SVP_TOKEN_MAX = 1024,
    /* Reference display is 640x480; the pixel window bounds any mode
     * at 16 MB (display.md 1), so no legal frame exceeds this. */
    SE_SVP_FRAME_MAX_BYTES = 16u * 1024u * 1024u,
    SE_SVP_PAYLOAD_MAX = 16u + SE_SVP_FRAME_MAX_BYTES + 8u,
};

typedef enum SeSvpType {
    SE_SVP_HELLO = 1,
    SE_SVP_FRAME = 2,
    SE_SVP_PONG = 3,
    SE_SVP_BUSY = 4,
    SE_SVP_CHALLENGE = 5,
    SE_SVP_DENIED = 6,
    SE_SVP_KEY = 16,
    SE_SVP_MOUSE = 17,
    SE_SVP_FOCUSLOST = 18,
    SE_SVP_PING = 19,
    SE_SVP_CLOSE = 20,
    SE_SVP_AUTH = 21,
} SeSvpType;

typedef enum SeSvpCodec {
    SE_SVP_RAW = 0,
    SE_SVP_XRLE = 1,
} SeSvpCodec;

/* ---------------------------------------------------------- encoding */

/* Fixed-size messages into out (room for SE_SVP_HDR_BYTES + 40);
 * each returns the byte count written. */
RWC_WARN_UNUSED uint32_t SeSvp_hello(uint8_t *out, uint32_t w, uint32_t h);
RWC_WARN_UNUSED uint32_t SeSvp_key(uint8_t *out, uint32_t usage, bool press,
                                   bool repeat);
RWC_WARN_UNUSED uint32_t SeSvp_mouse(uint8_t *out, int32_t x, int32_t y,
                                     uint8_t buttons);
RWC_WARN_UNUSED uint32_t SeSvp_ping(uint8_t *out, SeSvpType type,
                                    uint64_t token); /* PING or PONG */
RWC_WARN_UNUSED uint32_t SeSvp_empty(uint8_t *out, SeSvpType type);
RWC_WARN_UNUSED uint32_t SeSvp_challenge(
    uint8_t *out, const uint8_t nonce[SE_SVP_NONCE_BYTES]);
/* AUTH answering nonce with token (tlen bytes, SE_SVP_TOKEN_MIN..MAX). */
RWC_WARN_UNUSED uint32_t SeSvp_auth(uint8_t *out, const uint8_t *token,
                                    uint32_t tlen,
                                    const uint8_t nonce[SE_SVP_NONCE_BYTES]);

/* Frame encoder: owns the previous-frame reference for XRLE. */
typedef struct SeSvpEnc {
    uint32_t *prev; /* w*h words; caller-provided, zeroed at reset */
    uint64_t words; /* w*h */
    uint32_t seq;
} SeSvpEnc;

void SeSvpEnc_reset(SeSvpEnc *e, uint32_t *prev_words, uint64_t words);

/* Encode frame (4*w*h bytes) as one FRAME message into out, which must
 * hold SE_SVP_HDR_BYTES + 16 + 4*w*h + 8*(w*h+1) bytes (XRLE's worst
 * case is bounded; RAW is chosen whenever it is not larger). Updates
 * the reference to this frame. Returns the message length. */
RWC_WARN_UNUSED uint64_t SeSvpEnc_frame(SeSvpEnc *e, const uint8_t *frame,
                                        uint32_t w, uint32_t h, uint8_t *out);

/* Worst-case FRAME message size for w x h, for sizing out. */
RWC_WARN_UNUSED uint64_t SeSvp_frame_msg_max(uint32_t w, uint32_t h);

/* ---------------------------------------------------------- decoding */

/* Incremental receiver: bytes in (any split), whole messages out. */
typedef struct SeSvpRx {
    uint8_t *buf; /* caller-provided, cap bytes */
    uint64_t cap;
    uint64_t len; /* bytes held */
    uint64_t off; /* start of the unconsumed region */
    bool bad;     /* malformed stream: header garbage or oversize */
} SeSvpRx;

typedef struct SeSvpMsg {
    SeSvpType type;
    const uint8_t *p; /* payload, valid until the next SeSvpRx_* call */
    uint32_t len;
} SeSvpMsg;

/* ---------------------------------------------------- authentication */

/* The server's verdict on a connection's first message: true only for
 * a well-formed AUTH whose MAC matches token and nonce (compared with
 * SeHmac_equal, constant time). Anything else -- another type, a wrong
 * length, a wrong MAC -- is a refusal; there is no second attempt. */
RWC_WARN_UNUSED bool SeSvp_auth_ok(const SeSvpMsg *m, const uint8_t *token,
                                   uint32_t tlen,
                                   const uint8_t nonce[SE_SVP_NONCE_BYTES]);

/* A token file's bytes to the token: trailing whitespace (the newline
 * `base64 > file` writes) is dropped; the rest must be
 * SE_SVP_TOKEN_MIN..SE_SVP_TOKEN_MAX bytes with no NUL. False
 * otherwise. *tlen gets the token's length. */
RWC_WARN_UNUSED bool SeSvp_token_trim(const uint8_t *buf, uint64_t len,
                                      uint32_t *tlen);

/* Whether a token file may be trusted, from its fstat facts: a regular
 * file, owned by the user reading it, no group or other permission
 * bits (0600, 0400 or stricter). The same rule on both ends. */
typedef enum SeSvpTokenPerm {
    SE_SVP_TOKEN_PERM_OK = 0,
    SE_SVP_TOKEN_NOT_REGULAR,
    SE_SVP_TOKEN_WRONG_OWNER,
    SE_SVP_TOKEN_TOO_OPEN,
} SeSvpTokenPerm;

RWC_WARN_UNUSED SeSvpTokenPerm SeSvp_token_perm(bool regular, uint32_t mode,
                                                uint32_t owner_uid,
                                                uint32_t my_uid);

/* cap bounds the largest acceptable message: a view needs
 * SE_SVP_HDR_BYTES + SeSvp_frame_msg_max(w, h), a server only room for
 * input messages. */
void SeSvpRx_reset(SeSvpRx *r, uint8_t *buf, uint64_t cap);
/* Room for the next push; compacts consumed bytes first. */
RWC_WARN_UNUSED uint8_t *SeSvpRx_space(SeSvpRx *r, uint64_t *room);
void SeSvpRx_commit(SeSvpRx *r, uint64_t n);
/* Next complete message, or false (need more bytes, or r->bad). */
RWC_WARN_UNUSED bool SeSvpRx_next(SeSvpRx *r, SeSvpMsg *m);
/* True when SeSvpRx_next has something to say without more bytes: a
 * whole message is buffered, or the buffered header is malformed. A
 * consumer that stops early (a per-poll budget) must not sleep on its
 * socket while this holds -- the bytes are already here. */
RWC_WARN_UNUSED bool SeSvpRx_ready(const SeSvpRx *r);

/* Input rate limit: a token bucket on the wall clock, sans-IO (the
 * caller passes now_ms). The per-poll budget alone bounds one poll,
 * not the polls per second; a viewer that streams input without pause
 * would otherwise be served as fast as the server can loop, and every
 * accepted KEY or MOUSE grows the session trace. When the bucket is
 * empty the server stops reading and TCP pushes back on the viewer. */
typedef struct SeSvpRate {
    uint64_t milli;   /* tokens held, in thousandths */
    uint64_t cap;     /* burst, in thousandths */
    uint32_t per_s;   /* refill, tokens per second */
    uint64_t last_ms; /* clock at the last refill */
} SeSvpRate;

/* Full bucket of burst tokens at now_ms. per_s must be nonzero. */
void SeSvpRate_reset(SeSvpRate *r, uint32_t burst, uint32_t per_s,
                     uint64_t now_ms);
/* Refill up to now_ms; the whole tokens available. A clock that steps
 * backwards refills nothing. */
RWC_WARN_UNUSED uint32_t SeSvpRate_refill(SeSvpRate *r, uint64_t now_ms);
/* Spend n tokens, n at most what the last refill returned. */
void SeSvpRate_spend(SeSvpRate *r, uint32_t n);
/* Milliseconds until one whole token is available (0: one is now). */
RWC_WARN_UNUSED uint64_t SeSvpRate_wait_ms(const SeSvpRate *r);

/* Field readers for fixed payloads; false if the payload is short. */
RWC_WARN_UNUSED bool SeSvp_parse_hello(const SeSvpMsg *m, uint32_t *w,
                                       uint32_t *h);
RWC_WARN_UNUSED bool SeSvp_parse_key(const SeSvpMsg *m, uint32_t *usage,
                                     bool *press, bool *repeat);
RWC_WARN_UNUSED bool SeSvp_parse_mouse(const SeSvpMsg *m, int32_t *x,
                                       int32_t *y, uint8_t *buttons);
RWC_WARN_UNUSED bool SeSvp_parse_ping(const SeSvpMsg *m, uint64_t *token);
/* CHALLENGE of this protocol version: its nonce. A CHALLENGE of any
 * other version is false, and so is a HELLO (an SVP/1 server, which
 * has no authentication). */
RWC_WARN_UNUSED bool SeSvp_parse_challenge(
    const SeSvpMsg *m, uint8_t nonce[SE_SVP_NONCE_BYTES]);

/* Apply a FRAME payload to fb (4*w*h bytes, holding the previous frame
 * for XRLE). False, fb possibly partly written, on any malformation:
 * wrong geometry, unknown codec, runs past the end, trailing bytes. */
RWC_WARN_UNUSED bool SeSvp_apply_frame(const SeSvpMsg *m, uint32_t w,
                                       uint32_t h, uint8_t *fb,
                                       uint32_t *seq);

#endif /* SE_GUI_SVP_H */
