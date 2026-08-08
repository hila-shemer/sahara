#include "dev.h"

#include <string.h>

#include "rwc/status.h"

/* Display register offsets (PLATFORM-SPEC 4; devspec/display.md 2). */
enum {
    DISP_PRESENT = 0,
    DISP_WIDTH = 8,
    DISP_HEIGHT = 16,
    DISP_STRIDE = 24,
    DISP_FORMAT = 32,
    DISP_IRQ_STATUS = 40,
    DISP_IRQ_ACK = 48,
    DISP_RESERVED = 56, /* 56.. end of window: reads 0, writes ignored */
};

/* The reference initial mode, fixed before reset and identical between
 * a recording run and its replay (devspec/display.md 1). */
enum {
    DISP_REF_WIDTH = 640,
    DISP_REF_HEIGHT = 480,
    DISP_REF_STRIDE = 2560,
    DISP_REF_FORMAT = 1, /* XRGB8888, the only v1.0 format */
};

/* Keyboard/mouse register offsets (PLATFORM-SPEC 5-6). */
enum {
    INPUT_DATA = 0,
    INPUT_STATUS = 8,
};

/* NIC register offsets (PLATFORM-SPEC 7; fault catalog nic.md 5.1). */
enum {
    NIC_TX_DOORBELL = 0,
    NIC_TX_STATUS = 8,
    NIC_RX_LEN = 16,
    NIC_RX_POP = 24,
    NIC_MAC = 32,
};

void SeDev_reset(SeDev *d)
{
    memset(d, 0, sizeof *d);
}

static SeDevAcc acc_fault(void)
{
    return (SeDevAcc){ .fault = true, .val = 0 };
}

static SeDevAcc acc_val(uint64_t v)
{
    return (SeDevAcc){ .fault = false, .val = v };
}

SeDevAcc SeDev_reg_read(SeDev *d, SePlatSpace sp, uint64_t off)
{
    switch (sp) {
    case SE_SPACE_DISPLAY:
        switch (off) {
        case DISP_WIDTH: return acc_val(DISP_REF_WIDTH);
        case DISP_HEIGHT: return acc_val(DISP_REF_HEIGHT);
        case DISP_STRIDE: return acc_val(DISP_REF_STRIDE);
        case DISP_FORMAT: return acc_val(DISP_REF_FORMAT);
        case DISP_IRQ_STATUS: return acc_val(d->display_irq_status);
        default:
            if (off >= DISP_RESERVED)
                return acc_val(0); /* extension window (display.md 2 r5) */
            return acc_fault(); /* PRESENT/IRQ_ACK are write-only (D-03) */
        }
    case SE_SPACE_KBD:
    case SE_SPACE_MOUSE:
        switch (off) {
        case INPUT_DATA:
            /* Pop the oldest event; the queues are empty until EVENT
             * injection lands, so this is always the all-ones empty
             * sentinel (input.md rule 4), idempotently. */
            return acc_val(~0ull);
        case INPUT_STATUS:
            return acc_val(0); /* queue depth */
        default:
            return acc_fault(); /* unlisted offset (input.md rule 3) */
        }
    case SE_SPACE_NIC:
        switch (off) {
        case NIC_TX_STATUS: return acc_val(0); /* always 0 in v1.0 */
        case NIC_RX_LEN: return acc_val(d->nic_rx_len);
        case NIC_MAC: return acc_val(SE_PLAT_MAC);
        default:
            /* TX_DOORBELL/RX_POP are write-only (E3); the rest of the
             * register region is unlisted (E2). */
            return acc_fault();
        }
    default:
        RWC_ASSERT(0); /* only register windows reach here */
        return acc_fault();
    }
}

SeDevAcc SeDev_reg_write(SeDev *d, SePlatSpace sp, uint64_t off,
                         uint64_t val)
{
    switch (sp) {
    case SE_SPACE_DISPLAY:
        switch (off) {
        case DISP_PRESENT:
            /* Present a frame; the stored value is ignored (D-14). The
             * headless front end has no output surface, so the frame's
             * only footprint is the DEVW record the caller traces --
             * which is what checks/c7_dev.py's D-13 snapshot diff
             * quantifies over. */
            return acc_val(0);
        case DISP_IRQ_ACK:
            if ((val & ~1ull) != 0u)
                return acc_fault(); /* bits 63:1 set: DEVERR, clears
                                       nothing (display.md 2 reg map) */
            d->display_irq_status &= ~(val & 1ull);
            return acc_val(0);
        default:
            if (off >= DISP_RESERVED)
                return acc_val(0); /* writes ignored, no fault */
            return acc_fault(); /* read-only registers (D-04) */
        }
    case SE_SPACE_KBD:
    case SE_SPACE_MOUSE:
        /* Both registers are read-only; every store anywhere in the
         * window traps (input.md rule 2). */
        return acc_fault();
    case SE_SPACE_NIC:
        switch (off) {
        case NIC_TX_DOORBELL:
            if (val < 60u || val > 1514u)
                return acc_fault(); /* E5; transmits nothing */
            /* Transmit TX buffer bytes [0, val): synchronous and
             * silent in v1.0 (TX_STATUS stays 0). The nic.md 6
             * translator is not implemented -- headless replay sources
             * RX frames from the trace alone, so every live-mode frame
             * is dropped with no reply (SPEC-ISSUES.md entry 35). */
            return acc_val(0);
        case NIC_RX_POP:
            if (d->nic_rx_len == 0u)
                return acc_fault(); /* E6: empty pop is a DEVERR */
            d->nic_rx_len = 0u; /* nothing queued behind it headless */
            return acc_val(0);
        default:
            return acc_fault(); /* read-only (E4) or unlisted (E2) */
        }
    default:
        RWC_ASSERT(0);
        return acc_fault();
    }
}

bool SeDev_ext_pending(const SeDev *d)
{
    /* Keyboard/mouse queue non-empty would OR in here; the queues do
     * not exist yet (always empty), so only the display and NIC
     * conditions are live (PLATFORM-SPEC 3). */
    return d->display_irq_status != 0u || d->nic_rx_len != 0u;
}

/* ---------------------------------------------------- device table */

#define DEVTAB_PA 0x800u
#define DEVTAB_MAGIC 0x5450415241484153ull /* "SAHARAPT" little-endian */

/* One device record (devspec/boot.md 3.5), 64 bytes at *off. */
static void devtab_record(SeMem *m, uint64_t *off, uint64_t type,
                          se_u128 base, uint64_t size,
                          const uint64_t params[4])
{
    SeMem_write(m, *off + 0u, 8u, type);
    SeMem_write(m, *off + 8u, 16u, base);
    SeMem_write(m, *off + 24u, 8u, size);
    for (unsigned i = 0; i < 4u; i++)
        SeMem_write(m, *off + 32u + 8u * i, 8u, params[i]);
    *off += 64u;
}

void se_plat_write_devtable(SeMem *m, uint64_t ram_region_len)
{
    /* Structural rules of boot.md 3.4 for the one-region reference
     * table; main.c derives ram_region_len to satisfy them. */
    RWC_ASSERT(ram_region_len % 0x10000u == 0u);
    RWC_ASSERT(ram_region_len > 0u &&
              (se_u128)ram_region_len <= SE_PLAT_RAM_MAX);

    uint64_t off = DEVTAB_PA;
    SeMem_write(m, off + 0u, 8u, DEVTAB_MAGIC);
    SeMem_write(m, off + 8u, 8u, 1u);  /* version */
    SeMem_write(m, off + 16u, 8u, 1u); /* cpu_count */
    SeMem_write(m, off + 24u, 8u, 1u); /* ram_region_count */
    SeMem_write(m, off + 32u, 8u, 4u); /* device_count */
    off += 40u;
    SeMem_write(m, off + 0u, 16u, 0u); /* region 0 base */
    SeMem_write(m, off + 16u, 16u, (se_u128)ram_region_len);
    off += 32u;

    const uint64_t disp_params[4] = { se_lo64(SE_PLAT_PIXBUF_BASE),
                                      se_lo64(SE_PLAT_PIXBUF_SIZE), 0u,
                                      0u };
    const uint64_t no_params[4] = { 0u, 0u, 0u, 0u };
    const uint64_t nic_params[4] = { SE_PLAT_MAC, 0u, 0u, 0u };
    devtab_record(m, &off, 1u, SE_PLAT_DISPLAY_BASE, 0x10000u,
                  disp_params);
    devtab_record(m, &off, 2u, SE_PLAT_KBD_BASE, 0x10000u, no_params);
    devtab_record(m, &off, 3u, SE_PLAT_MOUSE_BASE, 0x10000u, no_params);
    devtab_record(m, &off, 4u, SE_PLAT_NIC_BASE, 0x30000u, nic_params);
    /* Window bytes past the encoded table stay 0: sparse memory reads
     * zero untouched, and the loader rejects segments overlapping
     * [0x800, 0x1000) (boot.md BOOT-4, image.c). */
}
