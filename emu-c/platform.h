#ifndef SE_PLATFORM_H
#define SE_PLATFORM_H

#include "rw/attrs.h"
#include "u128.h"

/* Reference-platform physical map, PLATFORM-SPEC section 1 as resolved
 * by devspec/boot.md: RAM region 0 is [0, 0x0F00_0000) -- 240 MB, ending
 * exactly where the device windows begin ("256 MB" is the address budget
 * below the pixel buffer, devspec SPEC-ISSUES 1); the four register
 * windows and the two NIC buffers are contiguous above it;
 * [0x0F06_0000, 0x1000_0000) is declared in no region and traps DEVERR
 * (boot.md BOOT-15), as does everything past the pixel buffer window.
 * SPEC-ISSUES.md entry 32 records the adoption history. */

#define SE_PLAT_RAM_MAX ((se_u128)0x0F000000u) /* region 0 length cap */
#define SE_PLAT_DISPLAY_BASE ((se_u128)0x0F000000u)
#define SE_PLAT_KBD_BASE ((se_u128)0x0F010000u)
#define SE_PLAT_MOUSE_BASE ((se_u128)0x0F020000u)
#define SE_PLAT_NIC_BASE ((se_u128)0x0F030000u)
#define SE_PLAT_NIC_TXBUF ((se_u128)0x0F040000u)
#define SE_PLAT_NIC_RXBUF ((se_u128)0x0F050000u)
#define SE_PLAT_DEV_END ((se_u128)0x0F060000u)
#define SE_PLAT_PIXBUF_BASE ((se_u128)0x10000000u)
#define SE_PLAT_PIXBUF_SIZE ((se_u128)0x01000000u) /* 16 MB, display.md 1 */

/* Reference MAC 52:54:00:12:34:56 packed per devspec/boot.md 3.6 (wire
 * octets little-endian into bits 47:0). The CLI contract has no MAC
 * flag, so this is a constant of the platform. */
#define SE_PLAT_MAC 0x0000563412005452ull

/* What backs a physical address (classification happens after
 * translation). Naturally-aligned accesses of at most 16 bytes cannot
 * cross the 64 KB window boundaries, so classifying the base address
 * classifies the whole access; callers check alignment first. */
typedef enum SePlatSpace {
    SE_SPACE_RAM = 0, /* below the windows: RAM if inside region 0 */
    SE_SPACE_DISPLAY, /* display control registers */
    SE_SPACE_KBD,     /* keyboard registers */
    SE_SPACE_MOUSE,   /* mouse registers */
    SE_SPACE_NIC,     /* NIC registers */
    SE_SPACE_BUF,     /* memory-like device space: NIC TX/RX, pixels */
    SE_SPACE_HOLE,    /* in no region and no window: always DEVERR */
} SePlatSpace;

RW_WARN_UNUSED static inline SePlatSpace se_plat_classify(se_u128 pa)
{
    if (pa < SE_PLAT_DISPLAY_BASE)
        return SE_SPACE_RAM;
    if (pa < SE_PLAT_KBD_BASE)
        return SE_SPACE_DISPLAY;
    if (pa < SE_PLAT_MOUSE_BASE)
        return SE_SPACE_KBD;
    if (pa < SE_PLAT_NIC_BASE)
        return SE_SPACE_MOUSE;
    if (pa < SE_PLAT_NIC_TXBUF)
        return SE_SPACE_NIC;
    if (pa < SE_PLAT_DEV_END)
        return SE_SPACE_BUF;
    if (pa >= SE_PLAT_PIXBUF_BASE &&
        pa < SE_PLAT_PIXBUF_BASE + SE_PLAT_PIXBUF_SIZE)
        return SE_SPACE_BUF;
    return SE_SPACE_HOLE;
}

#endif /* SE_PLATFORM_H */
