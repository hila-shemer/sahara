#ifndef SE_HOSTMEM_H
#define SE_HOSTMEM_H

#include <stddef.h>

/* Host allocation for the emulator: mmap-backed, zero-filled. malloc is
 * doctrine-banned; the emulator's dynamic needs (sparse guest pages,
 * growable hash tables, image bytes) all come through here. Aborts on
 * host OOM: guest behavior must never depend on host memory pressure,
 * so there is no failure path to mishandle. */
void *se_host_alloc(size_t bytes);
void se_host_free(void *p, size_t bytes);

#endif /* SE_HOSTMEM_H */
