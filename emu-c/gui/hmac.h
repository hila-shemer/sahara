#ifndef SE_GUI_HMAC_H
#define SE_GUI_HMAC_H

#include <stdbool.h>
#include <stdint.h>

#include "rwc/attrs.h"

/* HMAC-SHA256 (RFC 2104 over FIPS 180-4, the core's se_sha256) and a
 * constant-time comparison, for SVP's challenge-response (gui/svp.h).
 * Messages are short and bounded -- the SVP auth input is a label plus
 * a nonce -- so this rides on the one-shot hash with a stack buffer
 * instead of adding a streaming SHA-256 to the frozen core. Verified
 * in test_svp.c against RFC 4231's test cases. */

enum {
    SE_HMAC_BYTES = 32,   /* SHA-256 digest */
    SE_HMAC_BLOCK = 64,   /* SHA-256 block */
    SE_HMAC_MSG_MAX = 256, /* bounds the stack buffer; RFC 4231 fits */
};

/* out = HMAC-SHA256(key, msg). Any key length (longer than a block is
 * hashed first, per RFC 2104); mlen at most SE_HMAC_MSG_MAX. */
void SeHmac_sha256(const uint8_t *key, uint64_t klen, const uint8_t *msg,
                   uint32_t mlen, uint8_t out[SE_HMAC_BYTES]);

/* a[0..n) == b[0..n), in time that depends only on n: every byte is
 * read and folded, no early exit, so a remote guesser learns nothing
 * from how long a wrong MAC takes to reject. */
RWC_WARN_UNUSED bool SeHmac_equal(const uint8_t *a, const uint8_t *b,
                                  uint32_t n);

#endif /* SE_GUI_HMAC_H */
