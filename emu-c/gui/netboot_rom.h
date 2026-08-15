#ifndef SE_GUI_NETBOOT_ROM_H
#define SE_GUI_NETBOOT_ROM_H

#include <stdint.h>

/* The embedded netboot ROM (rom/netboot/): the SAHIMG01 bytes of
 * netboot.img, verbatim. sdl_main materializes them next to the trace
 * and loads the file through the ordinary image loader, so META
 * image_sha256 and --replay work with zero image argument. The .c is
 * generated and drift-gated by rom/netboot/build.sh --check. */
extern const uint8_t se_netboot_rom[];
extern const uint32_t se_netboot_rom_len;
extern const char se_netboot_rom_version[];

#endif /* SE_GUI_NETBOOT_ROM_H */
