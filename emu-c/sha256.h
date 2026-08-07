#ifndef SE_SHA256_H
#define SE_SHA256_H

#include <stdint.h>

/* One-shot SHA-256 (FIPS 180-4) of a fully in-memory buffer. The only
 * consumer is the trace META record's image_sha256 key (devspec/trace.md
 * 2.3.7), which hashes the slurped .img bytes; no streaming interface is
 * needed. out gets the 32 digest bytes, big-endian word order per the
 * standard (so hex-printing the bytes in order gives the usual digest
 * string). */
void se_sha256(const uint8_t *data, uint64_t len, uint8_t out[32]);

#endif /* SE_SHA256_H */
