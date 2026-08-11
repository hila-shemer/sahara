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

/* RNG register offsets (rng.md 2; fault catalog rng.md 8). */
enum {
    RNG_DATA = 0,
    RNG_STATUS = 8,
    RNG_CTRL = 16,
    RNG_SEED = 24,
};

/* CTRL bit assignments (rng.md 2): everything above bit 1 is reserved
 * and write-rejected (E5), so future bits stay opt-in. */
#define RNG_CTRL_MODE 1ull /* 0 = QUEUE, 1 = PRNG */
#define RNG_CTRL_IE 2ull
#define RNG_CTRL_RESERVED (~3ull)

/* SplitMix64, normative in rng.md 5.1. One call = one PRNG-mode DATA
 * pop; the state advance and the output are inseparable by design. */
static uint64_t rng_splitmix64(uint64_t *state)
{
    *state += 0x9E3779B97F4A7C15ull;
    uint64_t z = *state;
    z ^= z >> 30;
    z *= 0xBF58476D1CE4E5B9ull;
    z ^= z >> 27;
    z *= 0x94D049BB133111EBull;
    z ^= z >> 31;
    return z;
}

void SeDev_reset(SeDev *d)
{
    memset(d, 0, sizeof *d);
    d->disp_width = DISP_REF_WIDTH;
    d->disp_height = DISP_REF_HEIGHT;
    d->disp_stride = DISP_REF_STRIDE;
}

/* Expose the RX queue head: write exactly len bytes to the RX buffer
 * (nic.md 2.3 -- bytes beyond len keep their prior contents) and
 * publish RX_LEN. Device-internal writes: no trace records (nic.md
 * 7.2); the frame's only trace footprint is its EVENT record. */
static void nic_expose_head(SeDev *d, SeMem *m)
{
    const SeNicRxQ *q = &d->nic_rxq;
    RWC_ASSERT(q->count != 0u);
    uint16_t len = q->len[q->head];
    for (uint16_t i = 0; i < len; i++)
        SeMem_write(m, SE_PLAT_NIC_RXBUF + i, 1u, q->frame[q->head][i]);
    d->nic_rx_len = len;
}

bool SeDev_inject_nic(SeDev *d, SeMem *m, const uint8_t *frame,
                      uint16_t len)
{
    RWC_ASSERT(m != NULL && m == d->mem);
    RWC_ASSERT(len >= SE_NIC_FRAME_MIN && len <= SE_NIC_FRAME_MAX);
    SeNicRxQ *q = &d->nic_rxq;
    if (q->count == SE_NIC_QDEPTH)
        return true; /* discarded before admission (nic.md 4.3): no
                        event, no record, no guest-visible effect */
    uint32_t slot = (q->head + q->count) % SE_NIC_QDEPTH;
    memcpy(q->frame[slot], frame, len);
    q->len[slot] = len;
    q->count += 1u;
    if (d->nic_rx_len == 0u) {
        /* Mailbox empty implies the queue was too (a pop always
         * exposes the next head immediately), so the new frame IS the
         * head. */
        RWC_ASSERT(q->count == 1u);
        nic_expose_head(d, m);
    }
    return false;
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
        case DISP_WIDTH: return acc_val(d->disp_width);
        case DISP_HEIGHT: return acc_val(d->disp_height);
        case DISP_STRIDE: return acc_val(d->disp_stride);
        case DISP_FORMAT: return acc_val(DISP_REF_FORMAT);
        case DISP_IRQ_STATUS: return acc_val(d->display_irq_status);
        default:
            if (off >= DISP_RESERVED)
                return acc_val(0); /* extension window (display.md 2 r5) */
            return acc_fault(); /* PRESENT/IRQ_ACK are write-only (D-03) */
        }
    case SE_SPACE_KBD:
    case SE_SPACE_MOUSE: {
        SeInputQ *q = sp == SE_SPACE_KBD ? &d->kbd : &d->mouse;
        switch (off) {
        case INPUT_DATA: {
            if (q->count == 0u)
                return acc_val(~0ull); /* empty sentinel, no effect
                                          (input.md rule 4) */
            uint64_t w = q->ev[q->head];
            q->head = (q->head + 1u) % SE_INPUT_QDEPTH;
            q->count -= 1u;
            return acc_val(w); /* pop the oldest (FIFO, input.md 4.3) */
        }
        case INPUT_STATUS:
            return acc_val(q->count); /* queue depth */
        default:
            return acc_fault(); /* unlisted offset (input.md rule 3) */
        }
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
    case SE_SPACE_RNG:
        switch (off) {
        case RNG_DATA:
            if (d->rng_ctrl & RNG_CTRL_MODE)
                /* PRNG mode: the queue is untouched (rng.md 5.2). */
                return acc_val(rng_splitmix64(&d->rng_prng_state));
            if (d->rng_count == 0u)
                return acc_fault(); /* E6: no sentinel exists -- every
                                       u64 is a legal entropy word
                                       (rng.md 4.1 rule 4) */
            {
                uint64_t w = d->rng_q[d->rng_head];
                d->rng_head = (d->rng_head + 1u) % SE_RNG_QDEPTH;
                d->rng_count -= 1u;
                return acc_val(w); /* pop the oldest (FIFO, rng.md 4.1) */
            }
        case RNG_STATUS:
            return acc_val(d->rng_count); /* mode-independent depth */
        case RNG_CTRL:
            return acc_val(d->rng_ctrl);
        default:
            return acc_fault(); /* SEED is write-only (E2); the rest
                                   is unlisted (E1) */
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
            /* Present a frame; the stored value is ignored (D-14).
             * Headless the frame's only footprint is the DEVW record
             * the caller traces -- which is what checks/c7_dev.py's
             * D-13 snapshot diff quantifies over. The pending flag is
             * the GUI's repaint hook and nothing else reads it. */
            d->present_pending = true;
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
            if (val < SE_NIC_FRAME_MIN || val > SE_NIC_FRAME_MAX)
                return acc_fault(); /* E5; transmits nothing */
            /* Transmit TX buffer bytes [0, val): the hook captures
             * synchronously (nic.md 2.2 -- the guest cannot run until
             * this store completes) and runs the GUI's translator.
             * NULL headless: replay sources RX frames from the trace
             * alone (nic.md 7.3), so the frame is dropped with no
             * reply and its only footprint is the caller's DEVW. */
            if (d->tx_doorbell != NULL)
                d->tx_doorbell(d->tx_ctx, (uint32_t)val);
            return acc_val(0);
        case NIC_RX_POP: {
            if (d->nic_rx_len == 0u)
                return acc_fault(); /* E6: empty pop is a DEVERR */
            SeNicRxQ *q = &d->nic_rxq;
            RWC_ASSERT(q->count != 0u); /* exposed implies held */
            q->head = (q->head + 1u) % SE_NIC_QDEPTH;
            q->count -= 1u;
            if (q->count != 0u) {
                /* Expose the next frame immediately: the very next
                 * instruction observes the new RX_LEN and bytes
                 * (nic.md 2.4). */
                RWC_ASSERT(d->mem != NULL); /* wired at setup */
                nic_expose_head(d, d->mem);
            } else {
                d->nic_rx_len = 0u;
            }
            return acc_val(0);
        }
        default:
            return acc_fault(); /* read-only (E4) or unlisted (E2) */
        }
    case SE_SPACE_RNG:
        switch (off) {
        case RNG_CTRL:
            if (val & RNG_CTRL_RESERVED)
                return acc_fault(); /* E5: reserved bits stay opt-in
                                       (rng.md 9), no state change */
            d->rng_ctrl = val;
            return acc_val(0);
        case RNG_SEED:
            /* state = value, stream restarts (rng.md 5.1); legal in
             * either mode, replay-safe because this store is DEVW-
             * traced like any other (rng.md 5.3). */
            d->rng_prng_state = val;
            return acc_val(0);
        default:
            return acc_fault(); /* DATA/STATUS read-only (E2); the
                                   rest unlisted (E1) */
        }
    default:
        RWC_ASSERT(0);
        return acc_fault();
    }
}

bool SeDev_inject_input(SeDev *d, bool kbd, uint64_t word)
{
    SeInputQ *q = kbd ? &d->kbd : &d->mouse;
    if (q->count == SE_INPUT_QDEPTH)
        return true; /* drop-newest (input.md 4.2): never visible via
                        DATA/STATUS, never contributes to EXTINT */
    q->ev[(q->head + q->count) % SE_INPUT_QDEPTH] = word;
    q->count += 1u;
    return false;
}

uint32_t SeDev_inject_rng(SeDev *d, const uint64_t *words, uint32_t nwords)
{
    /* Truncate-to-fit (rng.md 4.2): accept the front, drop the rest.
     * The return value is the recording contract -- the caller traces
     * exactly the accepted prefix, or nothing when it is 0. */
    uint32_t space = SE_RNG_QDEPTH - d->rng_count;
    uint32_t take = nwords < space ? nwords : space;
    for (uint32_t i = 0; i < take; i++)
        d->rng_q[(d->rng_head + d->rng_count + i) % SE_RNG_QDEPTH] =
            words[i];
    d->rng_count += take;
    return take;
}

void SeDev_inject_resize(SeDev *d, uint64_t width, uint64_t height,
                         uint64_t stride)
{
    d->disp_width = width;
    d->disp_height = height;
    d->disp_stride = stride;
    d->display_irq_status |= 1u; /* idempotent if already set (6.2) */
}

bool SeDev_ext_pending(const SeDev *d)
{
    /* Level-triggered OR of every device pending condition
     * (PLATFORM-SPEC 3): input queue non-empty, display IRQ_STATUS
     * nonzero, NIC frame exposed, RNG depth behind its IE gate --
     * IE-qualified so the device stays invisible to type-7-unaware
     * kernels (rng.md 6). Pure state: no cycle plumbing anywhere. */
    return d->kbd.count != 0u || d->mouse.count != 0u ||
           d->display_irq_status != 0u || d->nic_rx_len != 0u ||
           ((d->rng_ctrl & RNG_CTRL_IE) != 0u && d->rng_count != 0u);
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
    SeMem_write(m, off + 32u, 8u, 5u); /* device_count */
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
    /* Type 7 rng, all params 0 ("0 = v1 behavior", rng.md 1; depth
     * 256 is spec-fixed, not a param). Fifth record on this branch --
     * SE_DEVIDX_RNG carries the wave-renumber note. */
    devtab_record(m, &off, 7u, SE_PLAT_RNG_BASE, 0x10000u, no_params);
    /* Window bytes past the encoded table stay 0: sparse memory reads
     * zero untouched, and the loader rejects segments overlapping
     * [0x800, 0x1000) (boot.md BOOT-4, image.c). */
}
