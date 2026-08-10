#ifndef SE_GUI_BLIT_H
#define SE_GUI_BLIT_H

#include <stdint.h>

#include "mem.h"

/* v1 frame blit: page-walking row copy of the current frame snapshot
 * (display.md 3.3) from the sparse pixel window into a host staging
 * buffer of 4*width*height bytes. Guest XRGB8888-LE bytes (B, G, R, X)
 * are byte-identical to SDL ARGB8888 memory order, so rows copy
 * verbatim and the X byte rides along ignored. Unallocated pages read
 * as zeros without being touched. No contiguity optimization -- the
 * ~1.2 MB reference frame is trivial at 60 Hz. */
void SeGuiBlit_frame(const SeMem *m, uint64_t width, uint64_t height,
                     uint64_t stride, uint8_t *dst);

#endif /* SE_GUI_BLIT_H */
