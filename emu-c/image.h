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
 * fnv64_out gets an FNV-1a-64 of the file bytes for the trace META
 * record. */
const char *se_image_load(SeMem *m, const char *path, se_u128 *entry_out,
                          uint64_t *fnv64_out);

#endif /* SE_IMAGE_H */
