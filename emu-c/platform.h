#ifndef SE_PLATFORM_H
#define SE_PLATFORM_H

#include <stdbool.h>

#include "rw/attrs.h"
#include "u128.h"

/* Reference-platform physical map, PLATFORM-SPEC section 1. The four
 * fixed device-register windows are contiguous: display control (64 KB),
 * keyboard (64 KB), mouse (64 KB), NIC (192 KB). They sit numerically
 * inside the default 256 MB RAM span, and the spec's "everything at
 * 0x0F00_0000 and above in this map is device space" makes them a
 * carve-out: device-space classification wins over RAM backing
 * (SPEC-ISSUES.md entry 32).
 *
 * The display pixel buffer (PA 0x1000_0000, size per device table) is
 * NOT classified here: no display device exists yet, its window has no
 * table-defined size, and under the default RAM length its base is
 * out-of-RAM, which already takes the DEVERR path. Entry 32 records the
 * --ram > 256 MB gap this leaves until the device phase. */

#define SE_PLAT_DEV_BASE ((se_u128)0x0F000000u)
#define SE_PLAT_DEV_END ((se_u128)0x0F060000u)

/* Does [pa, pa+size) overlap the device-register windows? Physical
 * addresses only (classification happens after translation). A pa near
 * the top of the address space wraps pa+size to a small value and
 * returns false; such an access then fails the caller's RAM check. */
RW_WARN_UNUSED static inline bool se_plat_in_dev_window(se_u128 pa,
                                                        unsigned size)
{
    return pa < SE_PLAT_DEV_END && pa + size > SE_PLAT_DEV_BASE;
}

#endif /* SE_PLATFORM_H */
