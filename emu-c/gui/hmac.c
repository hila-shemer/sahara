/* HMAC-SHA256 and a constant-time compare (gui/hmac.h). */
#include "gui/hmac.h"

#include <string.h>

#include "rwc/status.h"
#include "sha256.h"

/* A wipe the compiler may not drop as a dead store (memset may be). */
static void wipe(uint8_t *p, uint64_t n)
{
    volatile uint8_t *v = p;
    for (uint64_t i = 0; i < n; i++)
        v[i] = 0u;
}

void SeHmac_sha256(const uint8_t *key, uint64_t klen, const uint8_t *msg,
                   uint32_t mlen, uint8_t out[SE_HMAC_BYTES])
{
    RWC_ASSERT(mlen <= SE_HMAC_MSG_MAX);
    /* K0: the key, hashed if longer than a block, zero-padded. */
    uint8_t k0[SE_HMAC_BLOCK] = { 0 };
    if (klen > SE_HMAC_BLOCK)
        se_sha256(key, klen, k0);
    else if (klen != 0u)
        memcpy(k0, key, (size_t)klen);

    /* inner = H((K0 ^ ipad) || msg); out = H((K0 ^ opad) || inner). */
    uint8_t buf[SE_HMAC_BLOCK + SE_HMAC_MSG_MAX];
    for (unsigned i = 0; i < SE_HMAC_BLOCK; i++)
        buf[i] = k0[i] ^ 0x36u;
    if (mlen != 0u)
        memcpy(buf + SE_HMAC_BLOCK, msg, mlen);
    uint8_t inner[SE_HMAC_BYTES];
    se_sha256(buf, SE_HMAC_BLOCK + (uint64_t)mlen, inner);
    for (unsigned i = 0; i < SE_HMAC_BLOCK; i++)
        buf[i] = k0[i] ^ 0x5cu;
    memcpy(buf + SE_HMAC_BLOCK, inner, SE_HMAC_BYTES);
    se_sha256(buf, SE_HMAC_BLOCK + SE_HMAC_BYTES, out);
    /* The padded key is secret material: do not leave it on the stack
     * for the next frame to read back. */
    wipe(k0, sizeof k0);
    wipe(buf, sizeof buf);
    wipe(inner, sizeof inner);
}

bool SeHmac_equal(const uint8_t *a, const uint8_t *b, uint32_t n)
{
    /* volatile: the fold must not become an early-exit byte compare. */
    volatile uint8_t acc = 0;
    for (uint32_t i = 0; i < n; i++)
        acc = (uint8_t)(acc | (a[i] ^ b[i]));
    return acc == 0u;
}
