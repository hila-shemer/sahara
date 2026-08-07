#ifndef SE_MEM_H
#define SE_MEM_H

#include <stdbool.h>
#include <stdint.h>

#include "u128.h"

/* Sparse guest physical memory: page-number -> 64 KB block, allocated on
 * first write; reads of untouched pages return zeros without allocating.
 * No flat allocation and no RAM ceiling baked into the core
 * (emu-common-prompt.md); ram_len is configuration. The same sparse
 * store backs RAM region 0 and the memory-like device windows (NIC
 * TX/RX, pixel buffer) at their physical addresses; SeMem_in_ram is the
 * region-0 bounds check, and which spaces an access may touch is the
 * caller's classification (platform.h). */

#define SE_PAGE_SHIFT 16u
#define SE_PAGE_BYTES (1u << SE_PAGE_SHIFT)

typedef struct SeMem {
    uint64_t ram_len;   /* bytes of guest RAM (region 0 at PA 0) */
    uint64_t cap;       /* hash capacity, power of two; 0 = empty */
    uint64_t count;
    uint64_t *keys;     /* page_no + 1; 0 = empty slot */
    uint8_t **blocks;
} SeMem;

void SeMem_init(SeMem *m, uint64_t ram_len);
/* Is [pa, pa+size) inside RAM region 0? */
bool SeMem_in_ram(const SeMem *m, se_u128 pa, unsigned size);
/* Access of size bytes (1..16), little-endian value. The caller has
 * checked that the address is RAM or a memory-like device window and
 * natural alignment, so an access never crosses a 64 KB page. */
se_u128 SeMem_read(SeMem *m, se_u128 pa, unsigned size);
void SeMem_write(SeMem *m, se_u128 pa, unsigned size, se_u128 val);

#endif /* SE_MEM_H */
