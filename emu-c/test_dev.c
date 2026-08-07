/* Short-tier unit tests for the device layer: the byte-exact reference
 * device table (devspec/boot.md vector V1 -- the 328-byte dump
 * transcribed below, plus zeros through the end of the window), the
 * MAC packing vector V5, the physical-space classifier's boundaries,
 * and the register fault matrix at the SeDev level (direction, unlisted
 * offsets, doorbell range, empty pop; the trap plumbing above it is
 * exercised by the shared c7_dev image). */
#include <stdio.h>

#include "dev.h"
#include "mem.h"
#include "platform.h"
#include "rw/status.h"
#include "u128.h"

/* devspec/boot.md section 7, vector V1: the emulator must produce
 * exactly these 328 bytes at [0x0800, 0x0948). */
static const uint8_t v1_table[328] = {
    0x53, 0x41, 0x48, 0x41, 0x52, 0x41, 0x50, 0x54, 0x01, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x04, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x0F,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x0F,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x10,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x01, 0x0F, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x03, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x02, 0x0F, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x04, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x03, 0x0F,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x03, 0x00, 0x00, 0x00, 0x00, 0x00, 0x52, 0x54, 0x00, 0x12,
    0x34, 0x56, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00,
};

static void test_devtable_v1(void)
{
    SeMem m;
    SeMem_init(&m, se_lo64(SE_PLAT_RAM_MAX));
    se_plat_write_devtable(&m, se_lo64(SE_PLAT_RAM_MAX));
    for (unsigned i = 0; i < sizeof v1_table; i++)
        RW_ASSERT(se_lo64(SeMem_read(&m, 0x800u + i, 1u)) == v1_table[i]);
    for (unsigned a = 0x948u; a < 0x1000u; a++)
        RW_ASSERT(SeMem_read(&m, a, 1u) == 0u); /* BOOT-2: window zeros */
}

static void test_mac_packing(void)
{
    /* boot.md V5: 52:54:00:12:34:56 -> 0x0000563412005452, in-memory
     * bytes 52 54 00 12 34 56 00 00 (checked byte-wise above at table
     * offset 0x128). */
    RW_ASSERT(SE_PLAT_MAC == 0x0000563412005452ull);
}

static void test_classify(void)
{
    RW_ASSERT(se_plat_classify(0u) == SE_SPACE_RAM);
    RW_ASSERT(se_plat_classify(0x0EFFFFF8u) == SE_SPACE_RAM);
    RW_ASSERT(se_plat_classify(0x0F000000u) == SE_SPACE_DISPLAY);
    RW_ASSERT(se_plat_classify(0x0F00FFF8u) == SE_SPACE_DISPLAY);
    RW_ASSERT(se_plat_classify(0x0F010000u) == SE_SPACE_KBD);
    RW_ASSERT(se_plat_classify(0x0F020000u) == SE_SPACE_MOUSE);
    RW_ASSERT(se_plat_classify(0x0F030000u) == SE_SPACE_NIC);
    RW_ASSERT(se_plat_classify(0x0F040000u) == SE_SPACE_BUF); /* TX */
    RW_ASSERT(se_plat_classify(0x0F050000u) == SE_SPACE_BUF); /* RX */
    RW_ASSERT(se_plat_classify(0x0F060000u) == SE_SPACE_HOLE); /* V9 */
    RW_ASSERT(se_plat_classify(0x0FFFFFF8u) == SE_SPACE_HOLE);
    RW_ASSERT(se_plat_classify(0x10000000u) == SE_SPACE_BUF); /* pixels */
    RW_ASSERT(se_plat_classify(0x10FFFFF8u) == SE_SPACE_BUF);
    RW_ASSERT(se_plat_classify(0x11000000u) == SE_SPACE_HOLE);
    RW_ASSERT(se_plat_classify(se_make128(1u, 0u)) == SE_SPACE_HOLE);
}

static void test_registers(void)
{
    SeDev d;
    SeDev_reset(&d);
    /* Display: reference mode reads; wrong-direction faults. */
    RW_ASSERT(SeDev_reg_read(&d, SE_SPACE_DISPLAY, 8u).val == 640u);
    RW_ASSERT(SeDev_reg_read(&d, SE_SPACE_DISPLAY, 16u).val == 480u);
    RW_ASSERT(SeDev_reg_read(&d, SE_SPACE_DISPLAY, 24u).val == 2560u);
    RW_ASSERT(SeDev_reg_read(&d, SE_SPACE_DISPLAY, 32u).val == 1u);
    RW_ASSERT(SeDev_reg_read(&d, SE_SPACE_DISPLAY, 40u).val == 0u);
    RW_ASSERT(SeDev_reg_read(&d, SE_SPACE_DISPLAY, 0u).fault);   /* D-03 */
    RW_ASSERT(SeDev_reg_read(&d, SE_SPACE_DISPLAY, 48u).fault);  /* D-03 */
    RW_ASSERT(SeDev_reg_read(&d, SE_SPACE_DISPLAY, 56u).val == 0u);
    RW_ASSERT(SeDev_reg_write(&d, SE_SPACE_DISPLAY, 8u, 1u).fault);
    RW_ASSERT(!SeDev_reg_write(&d, SE_SPACE_DISPLAY, 0u, 77u).fault);
    RW_ASSERT(!SeDev_reg_write(&d, SE_SPACE_DISPLAY, 48u, 1u).fault);
    RW_ASSERT(SeDev_reg_write(&d, SE_SPACE_DISPLAY, 48u, 2u).fault);
    RW_ASSERT(!SeDev_reg_write(&d, SE_SPACE_DISPLAY, 56u, 5u).fault);
    RW_ASSERT(SeDev_reg_read(&d, SE_SPACE_DISPLAY, 56u).val == 0u);
    /* Input: empty pop sentinel, depth 0, everything else faults. */
    RW_ASSERT(SeDev_reg_read(&d, SE_SPACE_KBD, 0u).val == ~0ull);
    RW_ASSERT(SeDev_reg_read(&d, SE_SPACE_KBD, 8u).val == 0u);
    RW_ASSERT(SeDev_reg_read(&d, SE_SPACE_KBD, 16u).fault);
    RW_ASSERT(SeDev_reg_write(&d, SE_SPACE_KBD, 0u, 1u).fault);
    RW_ASSERT(SeDev_reg_read(&d, SE_SPACE_MOUSE, 0u).val == ~0ull);
    RW_ASSERT(SeDev_reg_write(&d, SE_SPACE_MOUSE, 8u, 1u).fault);
    /* NIC: E2-E6. */
    RW_ASSERT(SeDev_reg_read(&d, SE_SPACE_NIC, 8u).val == 0u);
    RW_ASSERT(SeDev_reg_read(&d, SE_SPACE_NIC, 16u).val == 0u);
    RW_ASSERT(SeDev_reg_read(&d, SE_SPACE_NIC, 32u).val == SE_PLAT_MAC);
    RW_ASSERT(SeDev_reg_read(&d, SE_SPACE_NIC, 0u).fault);  /* E3 */
    RW_ASSERT(SeDev_reg_read(&d, SE_SPACE_NIC, 24u).fault); /* E3 */
    RW_ASSERT(SeDev_reg_read(&d, SE_SPACE_NIC, 40u).fault); /* E2 */
    RW_ASSERT(SeDev_reg_write(&d, SE_SPACE_NIC, 8u, 0u).fault);  /* E4 */
    RW_ASSERT(SeDev_reg_write(&d, SE_SPACE_NIC, 0u, 59u).fault);   /* E5 */
    RW_ASSERT(SeDev_reg_write(&d, SE_SPACE_NIC, 0u, 1515u).fault); /* E5 */
    RW_ASSERT(!SeDev_reg_write(&d, SE_SPACE_NIC, 0u, 60u).fault);
    RW_ASSERT(!SeDev_reg_write(&d, SE_SPACE_NIC, 0u, 1514u).fault);
    RW_ASSERT(SeDev_reg_write(&d, SE_SPACE_NIC, 24u, 1u).fault); /* E6 */
    RW_ASSERT(!SeDev_ext_pending(&d));
}

int main(void)
{
    test_devtable_v1();
    test_mac_packing();
    test_classify();
    test_registers();
    printf("test_dev: all passed\n");
    return 0;
}
