#ifndef SE_GUI_SVP_H
#define SE_GUI_SVP_H

#include <stdbool.h>
#include <stdint.h>

#include "rwc/attrs.h"

/* SVP/1, the Sahara view protocol: one TCP stream between sahara-serve
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
 *     HELLO  {u32 version=1, u32 width, u32 height}
 *     FRAME  {u32 seq, u8 codec, 3 zero, u32 width, u32 height, data}
 *     PONG   {u64 token}              (answer to PING, same token)
 *     BUSY   {}                       (another view owns the session)
 *   view -> server
 *     KEY    {u32 usage, u8 press, u8 repeat, 2 zero}   page-7 usage
 *     MOUSE  {i32 x, i32 y, u8 buttons, 3 zero}  guest pixels, mask
 *                                                 bit0 L, bit1 R, bit2 M
 *     FOCUSLOST {}                    capture lost: release all
 *     PING   {u64 token}              latency probe, echoed as PONG
 *     CLOSE  {}                       end the session (window closed)
 *
 * Codecs: RAW is the frame snapshot itself (4*w*h bytes, XRGB8888-LE
 * rows, display.md 3.3). XRLE XORs the snapshot, as u32 words, against
 * the previous frame on this connection (zeros before the first) and
 * run-length codes the result as repeated {u32 zero_words, u32 n, n
 * literal words} until w*h words are covered: a console redraw that
 * touches one glyph costs a few hundred bytes instead of 1.2 MB. */

enum {
    SE_SVP_HDR_BYTES = 8,
    SE_SVP_VERSION = 1,
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
    SE_SVP_KEY = 16,
    SE_SVP_MOUSE = 17,
    SE_SVP_FOCUSLOST = 18,
    SE_SVP_PING = 19,
    SE_SVP_CLOSE = 20,
} SeSvpType;

typedef enum SeSvpCodec {
    SE_SVP_RAW = 0,
    SE_SVP_XRLE = 1,
} SeSvpCodec;

/* ---------------------------------------------------------- encoding */

/* Fixed-size messages into out (room for SE_SVP_HDR_BYTES + 16);
 * each returns the byte count written. */
RWC_WARN_UNUSED uint32_t SeSvp_hello(uint8_t *out, uint32_t w, uint32_t h);
RWC_WARN_UNUSED uint32_t SeSvp_key(uint8_t *out, uint32_t usage, bool press,
                                   bool repeat);
RWC_WARN_UNUSED uint32_t SeSvp_mouse(uint8_t *out, int32_t x, int32_t y,
                                     uint8_t buttons);
RWC_WARN_UNUSED uint32_t SeSvp_ping(uint8_t *out, SeSvpType type,
                                    uint64_t token); /* PING or PONG */
RWC_WARN_UNUSED uint32_t SeSvp_empty(uint8_t *out, SeSvpType type);

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

/* cap bounds the largest acceptable message: a view needs
 * SE_SVP_HDR_BYTES + SeSvp_frame_msg_max(w, h), a server only room for
 * input messages. */
void SeSvpRx_reset(SeSvpRx *r, uint8_t *buf, uint64_t cap);
/* Room for the next push; compacts consumed bytes first. */
RWC_WARN_UNUSED uint8_t *SeSvpRx_space(SeSvpRx *r, uint64_t *room);
void SeSvpRx_commit(SeSvpRx *r, uint64_t n);
/* Next complete message, or false (need more bytes, or r->bad). */
RWC_WARN_UNUSED bool SeSvpRx_next(SeSvpRx *r, SeSvpMsg *m);

/* Field readers for fixed payloads; false if the payload is short. */
RWC_WARN_UNUSED bool SeSvp_parse_hello(const SeSvpMsg *m, uint32_t *w,
                                       uint32_t *h);
RWC_WARN_UNUSED bool SeSvp_parse_key(const SeSvpMsg *m, uint32_t *usage,
                                     bool *press, bool *repeat);
RWC_WARN_UNUSED bool SeSvp_parse_mouse(const SeSvpMsg *m, int32_t *x,
                                       int32_t *y, uint8_t *buttons);
RWC_WARN_UNUSED bool SeSvp_parse_ping(const SeSvpMsg *m, uint64_t *token);

/* Apply a FRAME payload to fb (4*w*h bytes, holding the previous frame
 * for XRLE). False, fb possibly partly written, on any malformation:
 * wrong geometry, unknown codec, runs past the end, trailing bytes. */
RWC_WARN_UNUSED bool SeSvp_apply_frame(const SeSvpMsg *m, uint32_t w,
                                       uint32_t h, uint8_t *fb,
                                       uint32_t *seq);

#endif /* SE_GUI_SVP_H */
