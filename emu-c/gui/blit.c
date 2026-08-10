#include "gui/blit.h"

#include <string.h>

#include "platform.h"
#include "rwc/status.h"

void SeGuiBlit_frame(const SeMem *m, uint64_t width, uint64_t height,
                     uint64_t stride, uint8_t *dst)
{
    /* Published geometry always satisfies display.md 3.4; a violation
     * here is emulator state corruption, not guest input. */
    uint64_t row = 4u * width;
    RWC_ASSERT(width >= 1u && height >= 1u && stride >= row);
    RWC_ASSERT(height * stride <= se_lo64(SE_PLAT_PIXBUF_SIZE));
    uint64_t base = se_lo64(SE_PLAT_PIXBUF_BASE);
    for (uint64_t y = 0; y < height; y++) {
        uint64_t pa = base + y * stride;
        uint8_t *d = dst + y * row;
        uint64_t left = row;
        while (left != 0u) {
            uint64_t off = pa & (SE_PAGE_BYTES - 1u);
            uint64_t chunk = SE_PAGE_BYTES - off;
            if (chunk > left)
                chunk = left;
            const uint8_t *blk = SeMem_page_peek(m, pa >> SE_PAGE_SHIFT);
            if (blk)
                memcpy(d, blk + off, chunk);
            else
                memset(d, 0, chunk); /* never-written page reads 0 */
            pa += chunk;
            d += chunk;
            left -= chunk;
        }
    }
}
