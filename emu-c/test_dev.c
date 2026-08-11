/* Short-tier unit tests for the device layer: the byte-exact reference
 * device table (devspec/boot.md vector V1 -- the 328-byte dump
 * transcribed below, plus zeros through the end of the window), the
 * MAC packing vector V5, the physical-space classifier's boundaries,
 * the register fault matrix at the SeDev level (direction, unlisted
 * offsets, doorbell range, empty pop; the trap plumbing above it is
 * exercised by the shared c7_dev image), and the NIC RX frame store
 * (nic.md 4: FIFO exposure, exact-length buffer writes, the 64-cap
 * overflow discard). */
#include <stdio.h>
#include <string.h>

#include "dev.h"
#include "mem.h"
#include "platform.h"
#include "rwc/status.h"
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
        RWC_ASSERT(se_lo64(SeMem_read(&m, 0x800u + i, 1u)) == v1_table[i]);
    for (unsigned a = 0x948u; a < 0x1000u; a++)
        RWC_ASSERT(SeMem_read(&m, a, 1u) == 0u); /* BOOT-2: window zeros */
}

static void test_mac_packing(void)
{
    /* boot.md V5: 52:54:00:12:34:56 -> 0x0000563412005452, in-memory
     * bytes 52 54 00 12 34 56 00 00 (checked byte-wise above at table
     * offset 0x128). */
    RWC_ASSERT(SE_PLAT_MAC == 0x0000563412005452ull);
}

static void test_classify(void)
{
    RWC_ASSERT(se_plat_classify(0u) == SE_SPACE_RAM);
    RWC_ASSERT(se_plat_classify(0x0EFFFFF8u) == SE_SPACE_RAM);
    RWC_ASSERT(se_plat_classify(0x0F000000u) == SE_SPACE_DISPLAY);
    RWC_ASSERT(se_plat_classify(0x0F00FFF8u) == SE_SPACE_DISPLAY);
    RWC_ASSERT(se_plat_classify(0x0F010000u) == SE_SPACE_KBD);
    RWC_ASSERT(se_plat_classify(0x0F020000u) == SE_SPACE_MOUSE);
    RWC_ASSERT(se_plat_classify(0x0F030000u) == SE_SPACE_NIC);
    RWC_ASSERT(se_plat_classify(0x0F040000u) == SE_SPACE_BUF); /* TX */
    RWC_ASSERT(se_plat_classify(0x0F050000u) == SE_SPACE_BUF); /* RX */
    RWC_ASSERT(se_plat_classify(0x0F060000u) == SE_SPACE_HOLE); /* V9 */
    RWC_ASSERT(se_plat_classify(0x0FFFFFF8u) == SE_SPACE_HOLE);
    RWC_ASSERT(se_plat_classify(0x10000000u) == SE_SPACE_BUF); /* pixels */
    RWC_ASSERT(se_plat_classify(0x10FFFFF8u) == SE_SPACE_BUF);
    RWC_ASSERT(se_plat_classify(0x11000000u) == SE_SPACE_HOLE);
    RWC_ASSERT(se_plat_classify(se_make128(1u, 0u)) == SE_SPACE_HOLE);
}

static void test_registers(void)
{
    SeDev d;
    SeDev_reset(&d);
    /* Display: reference mode reads; wrong-direction faults. */
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DISPLAY, 8u).val == 640u);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DISPLAY, 16u).val == 480u);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DISPLAY, 24u).val == 2560u);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DISPLAY, 32u).val == 1u);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DISPLAY, 40u).val == 0u);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DISPLAY, 0u).fault);   /* D-03 */
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DISPLAY, 48u).fault);  /* D-03 */
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DISPLAY, 56u).val == 0u);
    RWC_ASSERT(SeDev_reg_write(&d, SE_SPACE_DISPLAY, 8u, 1u).fault);
    RWC_ASSERT(!SeDev_reg_write(&d, SE_SPACE_DISPLAY, 0u, 77u).fault);
    RWC_ASSERT(!SeDev_reg_write(&d, SE_SPACE_DISPLAY, 48u, 1u).fault);
    RWC_ASSERT(SeDev_reg_write(&d, SE_SPACE_DISPLAY, 48u, 2u).fault);
    RWC_ASSERT(!SeDev_reg_write(&d, SE_SPACE_DISPLAY, 56u, 5u).fault);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DISPLAY, 56u).val == 0u);
    /* Input: empty pop sentinel, depth 0, everything else faults. */
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_KBD, 0u).val == ~0ull);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_KBD, 8u).val == 0u);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_KBD, 16u).fault);
    RWC_ASSERT(SeDev_reg_write(&d, SE_SPACE_KBD, 0u, 1u).fault);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_MOUSE, 0u).val == ~0ull);
    RWC_ASSERT(SeDev_reg_write(&d, SE_SPACE_MOUSE, 8u, 1u).fault);
    /* NIC: E2-E6. */
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_NIC, 8u).val == 0u);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_NIC, 16u).val == 0u);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_NIC, 32u).val == SE_PLAT_MAC);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_NIC, 0u).fault);  /* E3 */
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_NIC, 24u).fault); /* E3 */
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_NIC, 40u).fault); /* E2 */
    RWC_ASSERT(SeDev_reg_write(&d, SE_SPACE_NIC, 8u, 0u).fault);  /* E4 */
    RWC_ASSERT(SeDev_reg_write(&d, SE_SPACE_NIC, 0u, 59u).fault);   /* E5 */
    RWC_ASSERT(SeDev_reg_write(&d, SE_SPACE_NIC, 0u, 1515u).fault); /* E5 */
    RWC_ASSERT(!SeDev_reg_write(&d, SE_SPACE_NIC, 0u, 60u).fault);
    RWC_ASSERT(!SeDev_reg_write(&d, SE_SPACE_NIC, 0u, 1514u).fault);
    RWC_ASSERT(SeDev_reg_write(&d, SE_SPACE_NIC, 24u, 1u).fault); /* E6 */
    RWC_ASSERT(!SeDev_ext_pending(&d));
}

static void test_input_queue(void)
{
    SeDev d;
    SeDev_reset(&d);
    /* FIFO pop order and depth (input.md 4.3), kbd/mouse independent. */
    RWC_ASSERT(!SeDev_inject_input(&d, true, 0x100000004ull));
    RWC_ASSERT(!SeDev_inject_input(&d, true, 0x4ull));
    RWC_ASSERT(!SeDev_inject_input(&d, false, 0xC80064ull));
    RWC_ASSERT(SeDev_ext_pending(&d));
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_KBD, 8u).val == 2u);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_MOUSE, 8u).val == 1u);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_KBD, 0u).val == 0x100000004ull);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_KBD, 0u).val == 0x4ull);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_KBD, 0u).val == ~0ull);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_MOUSE, 0u).val == 0xC80064ull);
    RWC_ASSERT(!SeDev_ext_pending(&d));
    /* Overflow at exactly 256: the 257th is dropped-newest and the
     * queue keeps its 256 (input.md 8.5 shape). */
    for (unsigned i = 0; i < 256u; i++)
        RWC_ASSERT(!SeDev_inject_input(&d, true, i));
    RWC_ASSERT(SeDev_inject_input(&d, true, 999u));
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_KBD, 8u).val == 256u);
    for (unsigned i = 0; i < 256u; i++)
        RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_KBD, 0u).val == i);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_KBD, 0u).val == ~0ull);
}

static void test_nic_rx_model(void)
{
    SeMem m;
    SeMem_init(&m, 0x20000u); /* RXBUF is a device window, not RAM */
    SeDev d;
    SeDev_reset(&d);
    d.mem = &m;
    uint64_t rx = se_lo64(SE_PLAT_NIC_RXBUF);
    uint8_t f[SE_NIC_FRAME_MAX];

    /* Pre-fill buffer tail bytes, then expose a short frame: exactly
     * len bytes are written, the tail keeps its prior contents
     * (NIC-C-14). */
    SeMem_write(&m, rx + 60u, 1u, 0xAAu);
    SeMem_write(&m, rx + 61u, 1u, 0xBBu);
    for (unsigned i = 0; i < 60u; i++)
        f[i] = (uint8_t)(i + 1u);
    RWC_ASSERT(!SeDev_inject_nic(&d, &m, f, 60u));
    RWC_ASSERT(d.nic_rx_len == 60u);
    RWC_ASSERT(SeDev_ext_pending(&d)); /* NIC-C-19: pending iff exposed */
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_NIC, 16u).val == 60u);
    for (unsigned i = 0; i < 60u; i++)
        RWC_ASSERT(se_lo64(SeMem_read(&m, rx + i, 1u)) == i + 1u);
    RWC_ASSERT(se_lo64(SeMem_read(&m, rx + 60u, 1u)) == 0xAAu);
    RWC_ASSERT(se_lo64(SeMem_read(&m, rx + 61u, 1u)) == 0xBBu);

    /* A second frame queues with no guest-visible effect; a max-size
     * third proves the u16 length plumbing. Pop exposes each in FIFO
     * order immediately (NIC-C-16/17), and the final pop empties the
     * mailbox and clears EXTINT. */
    memset(f, 0x22u, sizeof f);
    RWC_ASSERT(!SeDev_inject_nic(&d, &m, f, 61u));
    memset(f, 0x33u, sizeof f);
    RWC_ASSERT(!SeDev_inject_nic(&d, &m, f, SE_NIC_FRAME_MAX));
    RWC_ASSERT(d.nic_rx_len == 60u); /* first frame still exposed */
    RWC_ASSERT(se_lo64(SeMem_read(&m, rx, 1u)) == 1u);
    RWC_ASSERT(!SeDev_reg_write(&d, SE_SPACE_NIC, 24u, 0u).fault);
    RWC_ASSERT(d.nic_rx_len == 61u);
    RWC_ASSERT(se_lo64(SeMem_read(&m, rx, 1u)) == 0x22u);
    RWC_ASSERT(!SeDev_reg_write(&d, SE_SPACE_NIC, 24u, 0u).fault);
    RWC_ASSERT(d.nic_rx_len == SE_NIC_FRAME_MAX);
    RWC_ASSERT(se_lo64(SeMem_read(&m, rx + 1513u, 1u)) == 0x33u);
    RWC_ASSERT(SeDev_ext_pending(&d));
    RWC_ASSERT(!SeDev_reg_write(&d, SE_SPACE_NIC, 24u, 0u).fault);
    RWC_ASSERT(d.nic_rx_len == 0u);
    RWC_ASSERT(!SeDev_ext_pending(&d));
    RWC_ASSERT(SeDev_reg_write(&d, SE_SPACE_NIC, 24u, 0u).fault); /* E6 */

    /* Overflow (NIC-C-18): the 65th arrival while 64 are held is
     * discarded -- inject reports it, the queue and its contents are
     * untouched -- and the first 64 drain intact in order. */
    for (unsigned i = 0; i < 64u; i++) {
        memset(f, (uint8_t)i, 60u);
        RWC_ASSERT(!SeDev_inject_nic(&d, &m, f, (uint16_t)(60u + i)));
    }
    memset(f, 0xEEu, 60u);
    RWC_ASSERT(SeDev_inject_nic(&d, &m, f, 60u)); /* discarded */
    for (unsigned i = 0; i < 64u; i++) {
        RWC_ASSERT(d.nic_rx_len == 60u + i);
        RWC_ASSERT(se_lo64(SeMem_read(&m, rx, 1u)) == i);
        RWC_ASSERT(!SeDev_reg_write(&d, SE_SPACE_NIC, 24u, 0u).fault);
    }
    RWC_ASSERT(d.nic_rx_len == 0u);
}

static void test_resize_inject(void)
{
    SeDev d;
    SeDev_reset(&d);
    /* Atomic register update + sticky IRQ bit; ack clears; a second
     * event re-asserts (display.md 6.2/6.4, V5 shape). */
    SeDev_inject_resize(&d, 800u, 600u, 3200u);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DISPLAY, 8u).val == 800u);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DISPLAY, 16u).val == 600u);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DISPLAY, 24u).val == 3200u);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DISPLAY, 40u).val == 1u);
    RWC_ASSERT(SeDev_ext_pending(&d));
    RWC_ASSERT(!SeDev_reg_write(&d, SE_SPACE_DISPLAY, 48u, 1u).fault);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DISPLAY, 40u).val == 0u);
    RWC_ASSERT(!SeDev_ext_pending(&d));
    SeDev_inject_resize(&d, 640u, 480u, 2560u);
    SeDev_inject_resize(&d, 640u, 480u, 2560u); /* idempotent IRQ bit */
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DISPLAY, 40u).val == 1u);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DISPLAY, 8u).val == 640u);
}

int main(void)
{
    test_devtable_v1();
    test_mac_packing();
    test_classify();
    test_registers();
    test_input_queue();
    test_nic_rx_model();
    test_resize_inject();
    printf("test_dev: all passed\n");
    return 0;
}
