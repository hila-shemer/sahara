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
    /* On this branch the writer emits boot.md V10 (five records); V1
     * is superseded-at-integration but its bytes stay the reference
     * for everything except the count: the header (device_count u64
     * at table offset 0x20 excepted), the RAM region, and records 0-3
     * must still match V1 byte-for-byte. The new count and the
     * appended type-6 record are pinned by test_devtable_v10_dma. */
    SeMem m;
    SeMem_init(&m, se_lo64(SE_PLAT_RAM_MAX));
    se_plat_write_devtable(&m, se_lo64(SE_PLAT_RAM_MAX));
    for (unsigned i = 0; i < sizeof v1_table; i++) {
        if (i >= 0x20u && i < 0x28u)
            continue; /* device_count: 4 in V1, 5 on this branch */
        RWC_ASSERT(se_lo64(SeMem_read(&m, 0x800u + i, 1u)) == v1_table[i]);
    }
}

/* devspec/boot.md section 7, vector V10 (dev-dma branch): V1 with
 * device_count = 5 and this type-6 DMA record appended at 0x0948 --
 * base 0x0F07_0000, size 0x1_0000, params all zero (limits live in
 * CAPS, not the table). Encoded table now ends at 0x0988. Superseded
 * at integration by the wave-final table; the record BYTES carry
 * over, the position does not. */
static const uint8_t v10_dma_record[64] = {
    0x06, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x07, 0x0F,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00,
};

static void test_devtable_v10_dma(void)
{
    SeMem m;
    SeMem_init(&m, se_lo64(SE_PLAT_RAM_MAX));
    se_plat_write_devtable(&m, se_lo64(SE_PLAT_RAM_MAX));
    RWC_ASSERT(se_lo64(SeMem_read(&m, 0x820u, 8u)) == 5u);
    for (unsigned i = 0; i < sizeof v10_dma_record; i++)
        RWC_ASSERT(se_lo64(SeMem_read(&m, 0x948u + i, 1u)) ==
                   v10_dma_record[i]);
    for (unsigned a = 0x988u; a < 0x1000u; a++)
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
    RWC_ASSERT(se_plat_classify(0x0F06FFF8u) == SE_SPACE_HOLE);
    RWC_ASSERT(se_plat_classify(0x0F070000u) == SE_SPACE_DMA);
    RWC_ASSERT(se_plat_classify(0x0F07FFF8u) == SE_SPACE_DMA);
    RWC_ASSERT(se_plat_classify(0x0F080000u) == SE_SPACE_HOLE);
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
    RWC_ASSERT(SeDev_reg_write(&d, SE_SPACE_DISPLAY, 8u, 1u, 0u).fault);
    RWC_ASSERT(!SeDev_reg_write(&d, SE_SPACE_DISPLAY, 0u, 77u, 0u).fault);
    RWC_ASSERT(!SeDev_reg_write(&d, SE_SPACE_DISPLAY, 48u, 1u, 0u).fault);
    RWC_ASSERT(SeDev_reg_write(&d, SE_SPACE_DISPLAY, 48u, 2u, 0u).fault);
    RWC_ASSERT(!SeDev_reg_write(&d, SE_SPACE_DISPLAY, 56u, 5u, 0u).fault);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DISPLAY, 56u).val == 0u);
    /* Input: empty pop sentinel, depth 0, everything else faults. */
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_KBD, 0u).val == ~0ull);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_KBD, 8u).val == 0u);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_KBD, 16u).fault);
    RWC_ASSERT(SeDev_reg_write(&d, SE_SPACE_KBD, 0u, 1u, 0u).fault);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_MOUSE, 0u).val == ~0ull);
    RWC_ASSERT(SeDev_reg_write(&d, SE_SPACE_MOUSE, 8u, 1u, 0u).fault);
    /* NIC: E2-E6. */
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_NIC, 8u).val == 0u);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_NIC, 16u).val == 0u);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_NIC, 32u).val == SE_PLAT_MAC);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_NIC, 0u).fault);  /* E3 */
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_NIC, 24u).fault); /* E3 */
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_NIC, 40u).fault); /* E2 */
    RWC_ASSERT(SeDev_reg_write(&d, SE_SPACE_NIC, 8u, 0u, 0u).fault);  /* E4 */
    RWC_ASSERT(SeDev_reg_write(&d, SE_SPACE_NIC, 0u, 59u, 0u).fault);   /* E5 */
    RWC_ASSERT(SeDev_reg_write(&d, SE_SPACE_NIC, 0u, 1515u, 0u).fault); /* E5 */
    RWC_ASSERT(!SeDev_reg_write(&d, SE_SPACE_NIC, 0u, 60u, 0u).fault);
    RWC_ASSERT(!SeDev_reg_write(&d, SE_SPACE_NIC, 0u, 1514u, 0u).fault);
    RWC_ASSERT(SeDev_reg_write(&d, SE_SPACE_NIC, 24u, 1u, 0u).fault); /* E6 */
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
    RWC_ASSERT(!SeDev_reg_write(&d, SE_SPACE_NIC, 24u, 0u, 0u).fault);
    RWC_ASSERT(d.nic_rx_len == 61u);
    RWC_ASSERT(se_lo64(SeMem_read(&m, rx, 1u)) == 0x22u);
    RWC_ASSERT(!SeDev_reg_write(&d, SE_SPACE_NIC, 24u, 0u, 0u).fault);
    RWC_ASSERT(d.nic_rx_len == SE_NIC_FRAME_MAX);
    RWC_ASSERT(se_lo64(SeMem_read(&m, rx + 1513u, 1u)) == 0x33u);
    RWC_ASSERT(SeDev_ext_pending(&d));
    RWC_ASSERT(!SeDev_reg_write(&d, SE_SPACE_NIC, 24u, 0u, 0u).fault);
    RWC_ASSERT(d.nic_rx_len == 0u);
    RWC_ASSERT(!SeDev_ext_pending(&d));
    RWC_ASSERT(SeDev_reg_write(&d, SE_SPACE_NIC, 24u, 0u, 0u).fault); /* E6 */

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
        RWC_ASSERT(!SeDev_reg_write(&d, SE_SPACE_NIC, 24u, 0u, 0u).fault);
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
    RWC_ASSERT(!SeDev_reg_write(&d, SE_SPACE_DISPLAY, 48u, 1u, 0u).fault);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DISPLAY, 40u).val == 0u);
    RWC_ASSERT(!SeDev_ext_pending(&d));
    SeDev_inject_resize(&d, 640u, 480u, 2560u);
    SeDev_inject_resize(&d, 640u, 480u, 2560u); /* idempotent IRQ bit */
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DISPLAY, 40u).val == 1u);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DISPLAY, 8u).val == 640u);
}

/* DMA engine unit tests (devspec/dma.md). Registers and the DEVERR
 * matrix at the SeDev level; the doorbell's two error classes; the
 * cost model; latch-vs-sample; memmove overlap; the WFI wake gate.
 * The trap plumbing and boundary phase above SeDev are exercised by
 * the shared dma_* conformance images. */

#define DMA_DESC_PA 0x10000u
#define DMA_SRC_PA 0x20000u
#define DMA_DST_PA 0x30000u

static void dma_write_desc(SeMem *m, uint64_t op, uint64_t src,
                           uint64_t dst, uint64_t len)
{
    SeMem_write(m, DMA_DESC_PA + 0u, 8u, op);
    SeMem_write(m, DMA_DESC_PA + 8u, 8u, src);
    SeMem_write(m, DMA_DESC_PA + 16u, 8u, dst);
    SeMem_write(m, DMA_DESC_PA + 24u, 8u, len);
    SeMem_write(m, DMA_DESC_PA + 32u, 8u, 0u);
    SeMem_write(m, DMA_DESC_PA + 40u, 8u, 0u);
    SeMem_write(m, DMA_DESC_PA + 48u, 8u, 0u);
    SeMem_write(m, DMA_DESC_PA + 56u, 8u, 0u);
}

static void test_dma_registers(void)
{
    SeMem m;
    SeMem_init(&m, 0x100000u);
    SeDev d;
    SeDev_reset(&d);
    d.mem = &m;
    /* Reset values (dma.md 3.6, V1 rows 1-3). */
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DMA, 0x00u).val == SE_DMA_CAPS);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DMA, 0x08u).val == 0u);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DMA, 0x20u).val == 0u);
    /* Wrong direction (E3/E4), unlisted both ways (E2). */
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DMA, 0x10u).fault);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DMA, 0x18u).fault);
    RWC_ASSERT(SeDev_reg_write(&d, SE_SPACE_DMA, 0x00u, 0u, 0u).fault);
    RWC_ASSERT(SeDev_reg_write(&d, SE_SPACE_DMA, 0x08u, 0u, 0u).fault);
    RWC_ASSERT(SeDev_reg_write(&d, SE_SPACE_DMA, 0x20u, 0u, 0u).fault);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DMA, 0x28u).fault);
    RWC_ASSERT(SeDev_reg_write(&d, SE_SPACE_DMA, 0x28u, 0u, 0u).fault);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DMA, 0xFFF8u).fault);
    /* IRQ_ACK value rule (E8): only 1 is legal; 0 is loud too. */
    RWC_ASSERT(SeDev_reg_write(&d, SE_SPACE_DMA, 0x18u, 0u, 0u).fault);
    RWC_ASSERT(SeDev_reg_write(&d, SE_SPACE_DMA, 0x18u, 2u, 0u).fault);
    RWC_ASSERT(!SeDev_reg_write(&d, SE_SPACE_DMA, 0x18u, 1u, 0u).fault);
    RWC_ASSERT(!SeDev_ext_pending(&d));
    /* Doorbell access class (E6/E7): unaligned PA, PA range past RAM
     * top -- DEVERR, and STATUS/COMP_CYCLE untouched. */
    RWC_ASSERT(SeDev_reg_write(&d, SE_SPACE_DMA, 0x10u, 8u, 0u).fault);
    RWC_ASSERT(SeDev_reg_write(&d, SE_SPACE_DMA, 0x10u, 0x100000u,
                               0u).fault); /* E7: [ram_top, +64) */
    RWC_ASSERT(SeDev_reg_write(&d, SE_SPACE_DMA, 0x10u,
                               0xFFFFFFFFFFFFFFC0ull, 0u).fault);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DMA, 0x08u).val == 0u);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DMA, 0x20u).val == 0u);
}

static void test_dma_content_errors(void)
{
    SeMem m;
    SeMem_init(&m, 0x100000u);
    SeDev d;
    SeDev_reset(&d);
    d.mem = &m;
    /* Each row: doorbell at a known cycle, expect the STATUS code,
     * COMP_CYCLE = the doorbell cycle, nothing written (dma.md 5.3,
     * V2). Check order: first failure wins. */
    static const struct {
        uint64_t op, src, dst, len, want;
    } rows[] = {
        { 0u, DMA_SRC_PA, DMA_DST_PA, 64u, SE_DMA_ST_BAD_OP },
        { 7u, DMA_SRC_PA, DMA_DST_PA, 64u, SE_DMA_ST_BAD_OP },
        { 1u | (1u << 9), DMA_SRC_PA, DMA_DST_PA, 64u,
          SE_DMA_ST_BAD_FORMAT },
        { 1u, DMA_SRC_PA + 1u, DMA_DST_PA, 64u, SE_DMA_ST_BAD_ALIGN },
        { 1u, DMA_SRC_PA, DMA_DST_PA + 4u, 64u, SE_DMA_ST_BAD_ALIGN },
        { 1u, DMA_SRC_PA, DMA_DST_PA, 12u, SE_DMA_ST_BAD_ALIGN },
        /* FILL: src is a pattern, no align rule -- an odd src falls
         * through to the LEN=0 range check instead */
        { 2u, DMA_SRC_PA + 1u, DMA_DST_PA, 0u, SE_DMA_ST_BAD_RANGE },
        { 1u, DMA_SRC_PA, DMA_DST_PA, 0u, SE_DMA_ST_BAD_RANGE },
        { 1u, DMA_SRC_PA, DMA_DST_PA, SE_DMA_LEN_MAX + 8u,
          SE_DMA_ST_BAD_RANGE },
        { 1u, DMA_SRC_PA, 0x10000000u, 64u, /* pixel-buffer base */
          SE_DMA_ST_BAD_RANGE },
        /* precedence: opcode beats format beats align beats range */
        { 0u | (1u << 9), DMA_SRC_PA + 1u, DMA_DST_PA, 0u,
          SE_DMA_ST_BAD_OP },
        { 1u | (1u << 9), DMA_SRC_PA + 1u, DMA_DST_PA, 0u,
          SE_DMA_ST_BAD_FORMAT },
        { 1u, DMA_SRC_PA + 1u, DMA_DST_PA, 0u, SE_DMA_ST_BAD_ALIGN },
    };
    for (unsigned i = 0; i < sizeof rows / sizeof rows[0]; i++) {
        dma_write_desc(&m, rows[i].op, rows[i].src, rows[i].dst,
                       rows[i].len);
        uint64_t cyc = 1000u + i;
        RWC_ASSERT(!SeDev_reg_write(&d, SE_SPACE_DMA, 0x10u, DMA_DESC_PA,
                                    cyc).fault);
        RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DMA, 0x08u).val ==
                   rows[i].want);
        RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DMA, 0x20u).val == cyc);
        RWC_ASSERT(!d.dma_irq_pending); /* bit 8 clear everywhere here */
        RWC_ASSERT(SeMem_read(&m, DMA_DST_PA, 8u) == 0u); /* untouched */
    }
    /* NEXT != 0 is BAD_FORMAT; error-with-IRQ raises pending. */
    dma_write_desc(&m, 1u, DMA_SRC_PA, DMA_DST_PA, 64u);
    SeMem_write(&m, DMA_DESC_PA + 32u, 8u, 1u);
    RWC_ASSERT(!SeDev_reg_write(&d, SE_SPACE_DMA, 0x10u, DMA_DESC_PA,
                                2000u).fault);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DMA, 0x08u).val ==
               SE_DMA_ST_BAD_FORMAT);
    dma_write_desc(&m, 0x100u, DMA_SRC_PA, DMA_DST_PA, 64u); /* op 0+bit8 */
    RWC_ASSERT(!SeDev_reg_write(&d, SE_SPACE_DMA, 0x10u, DMA_DESC_PA,
                                2001u).fault);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DMA, 0x08u).val ==
               SE_DMA_ST_BAD_OP);
    RWC_ASSERT(d.dma_irq_pending);
    RWC_ASSERT(SeDev_ext_pending(&d));
    RWC_ASSERT(!SeDev_reg_write(&d, SE_SPACE_DMA, 0x18u, 1u, 0u).fault);
    RWC_ASSERT(!SeDev_ext_pending(&d));
}

static void test_dma_copy_fill(void)
{
    SeMem m;
    SeMem_init(&m, 0x100000u);
    SeDev d;
    SeDev_reset(&d);
    d.mem = &m;
    for (uint64_t i = 0; i < 512u; i++)
        SeMem_write(&m, DMA_SRC_PA + 8u * i, 8u, 0x0101010101010101ull * i);
    /* COPY 4 KB at cycle 1000: C_done = 1520 (dma.md V3), COMP_CYCLE
     * readable during BUSY, doorbell-while-BUSY is E5. */
    dma_write_desc(&m, 1u, DMA_SRC_PA, DMA_DST_PA, 4096u);
    RWC_ASSERT(!SeDev_reg_write(&d, SE_SPACE_DMA, 0x10u, DMA_DESC_PA,
                                1000u).fault);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DMA, 0x08u).val ==
               SE_DMA_ST_BUSY);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DMA, 0x20u).val == 1520u);
    RWC_ASSERT(SeDev_reg_write(&d, SE_SPACE_DMA, 0x10u, DMA_DESC_PA,
                               1001u).fault); /* E5 */
    /* Latch rule: corrupt the descriptor in RAM mid-flight. */
    SeMem_write(&m, DMA_DESC_PA, 8u, 0u);
    /* Sample rule: change source word 0 before C_done. */
    SeMem_write(&m, DMA_SRC_PA, 8u, 0xDEADBEEFDEADBEEFull);
    SeDev_dma_advance(&d, &m, 1519u); /* one early: nothing happens */
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DMA, 0x08u).val ==
               SE_DMA_ST_BUSY);
    RWC_ASSERT(SeMem_read(&m, DMA_DST_PA, 8u) == 0u);
    SeDev_dma_advance(&d, &m, 1520u);
    RWC_ASSERT(SeDev_reg_read(&d, SE_SPACE_DMA, 0x08u).val ==
               SE_DMA_ST_DONE);
    RWC_ASSERT(!d.dma_irq_pending); /* bit 8 was clear */
    RWC_ASSERT(SeMem_read(&m, DMA_DST_PA, 8u) == 0xDEADBEEFDEADBEEFull);
    for (uint64_t i = 1; i < 512u; i++)
        RWC_ASSERT(SeMem_read(&m, DMA_DST_PA + 8u * i, 8u) ==
                   (se_u128)(0x0101010101010101ull * i));
    RWC_ASSERT(SeMem_read(&m, DMA_DST_PA + 4096u, 8u) == 0u); /* fence */
    /* FILL with bit 8 from DONE: re-arm legal, wake gate on, pattern
     * replicated, pending flips only at the advance. */
    dma_write_desc(&m, 0x102u, 0xA5A5A5A5A5A5A5A5ull, DMA_DST_PA, 64u);
    RWC_ASSERT(!SeDev_reg_write(&d, SE_SPACE_DMA, 0x10u, DMA_DESC_PA,
                                2000u).fault);
    uint64_t wake = 0;
    RWC_ASSERT(SeDev_dma_wake(&d, &wake));
    RWC_ASSERT(wake == 2000u + 8u + 8u);
    RWC_ASSERT(!d.dma_irq_pending);
    SeDev_dma_advance(&d, &m, wake);
    RWC_ASSERT(d.dma_irq_pending);
    RWC_ASSERT(SeDev_dma_wake(&d, &wake) == false); /* DONE: no wake */
    for (uint64_t i = 0; i < 8u; i++)
        RWC_ASSERT(SeMem_read(&m, DMA_DST_PA + 8u * i, 8u) ==
                   0xA5A5A5A5A5A5A5A5ull);
    RWC_ASSERT(SeMem_read(&m, DMA_DST_PA + 64u, 8u) ==
               (se_u128)(0x0101010101010101ull * 8u)); /* fence held */
}

static void test_dma_overlap(void)
{
    SeMem m;
    SeMem_init(&m, 0x100000u);
    SeDev d;
    SeDev_reset(&d);
    d.mem = &m;
    /* Forward overlap (dst > src): memmove semantics, not a smear. */
    for (uint64_t i = 0; i < 64u; i++)
        SeMem_write(&m, DMA_SRC_PA + 8u * i, 8u, 100u + i);
    dma_write_desc(&m, 1u, DMA_SRC_PA, DMA_SRC_PA + 8u, 512u);
    RWC_ASSERT(!SeDev_reg_write(&d, SE_SPACE_DMA, 0x10u, DMA_DESC_PA,
                                0u).fault);
    SeDev_dma_advance(&d, &m, 100u);
    RWC_ASSERT(SeMem_read(&m, DMA_SRC_PA, 8u) == 100u); /* untouched */
    for (uint64_t i = 0; i < 64u; i++)
        RWC_ASSERT(SeMem_read(&m, DMA_SRC_PA + 8u * (i + 1u), 8u) ==
                   100u + i);
    /* Backward overlap (dst < src). */
    for (uint64_t i = 0; i < 65u; i++)
        SeMem_write(&m, DMA_DST_PA + 8u * i, 8u, 200u + i);
    dma_write_desc(&m, 1u, DMA_DST_PA + 8u, DMA_DST_PA, 512u);
    RWC_ASSERT(!SeDev_reg_write(&d, SE_SPACE_DMA, 0x10u, DMA_DESC_PA,
                                200u).fault);
    SeDev_dma_advance(&d, &m, 300u);
    for (uint64_t i = 0; i < 64u; i++)
        RWC_ASSERT(SeMem_read(&m, DMA_DST_PA + 8u * i, 8u) == 201u + i);
    RWC_ASSERT(SeMem_read(&m, DMA_DST_PA + 8u * 64u, 8u) == 264u);
}

int main(void)
{
    test_devtable_v1();
    test_devtable_v10_dma();
    test_dma_registers();
    test_dma_content_errors();
    test_dma_copy_fill();
    test_dma_overlap();
    test_mac_packing();
    test_classify();
    test_registers();
    test_input_queue();
    test_nic_rx_model();
    test_resize_inject();
    printf("test_dev: all passed\n");
    return 0;
}
