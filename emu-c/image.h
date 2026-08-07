#ifndef SE_IMAGE_H
#define SE_IMAGE_H

#include <stdint.h>

#include "mem.h"
#include "u128.h"

/* Load a .img file (TOOLING-SPEC section 1) into guest RAM.
 * Returns NULL on success, else a static error string (caller prints it
 * to stderr and exits nonzero -- image problems are host-side errors,
 * not guest traps). entry_out is validated 8-aligned; execution still
 * starts at the architectural reset PC (ISA-SPEC section 11).
 * sha256_out gets the SHA-256 of the file bytes for the trace META
 * record's image_sha256 key and for --replay validation
 * (devspec/trace.md 2.3.7, 5.1). */
const char *se_image_load(SeMem *m, const char *path, se_u128 *entry_out,
                          uint8_t sha256_out[32]);

#endif /* SE_IMAGE_H */
