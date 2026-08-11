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

/* DMA register offsets (devspec/dma.md 2). No CTRL, no DESC_PA
 * readback -- resolved and dropped by the work order. */
enum {
    DMA_CAPS = 0x00,
    DMA_STATUS = 0x08,
    DMA_DOORBELL = 0x10,
    DMA_IRQ_ACK = 0x18,
    DMA_COMP_CYCLE = 0x20,
};

/* Descriptor field offsets (dma.md 4). */
enum {
    DMA_DESC_OP = 0,
    DMA_DESC_SRC = 8,
    DMA_DESC_DST = 16,
    DMA_DESC_LEN = 24,
    DMA_DESC_NEXT = 32,
    DMA_DESC_BYTES = 64,
};

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
    case SE_SPACE_DMA:
        switch (off) {
        case DMA_CAPS: return acc_val(SE_DMA_CAPS);
        case DMA_STATUS: return acc_val(d->dma_status);
        case DMA_COMP_CYCLE: return acc_val(d->dma_comp_cycle);
        default:
            /* DOORBELL/IRQ_ACK are write-only (dma.md E3); unlisted
             * offsets fault in BOTH directions (E2 -- no inert
             * reserved window; root SPEC-ISSUES 40). */
            return acc_fault();
        }
    default:
        RWC_ASSERT(0); /* only register windows reach here */
        return acc_fault();
    }
}

/* [base, base+len) wholly inside declared RAM (region 0)? u128 sums:
 * a guest-supplied base near 2^64 must overflow into BAD_RANGE, not
 * wrap into legality (dma.md 5.3 "range arithmetic is exact"). */
static bool dma_range_in_ram(const SeMem *m, uint64_t base, uint64_t len)
{
    return (se_u128)base + len <= (se_u128)m->ram_len;
}

/* The doorbell store's synchronous half (dma.md 5.2 steps 2-5): the
 * access checks E5-E7 passed in the caller; latch the 64 descriptor
 * bytes -- a device-internal read, no MEMR records (dma.md 7.2) --
 * validate content in the fixed order, and arm or terminate. Every
 * outcome here retires the store; content badness is never a trap. */
static void dma_doorbell(SeDev *d, SeMem *m, uint64_t pa, uint64_t cycle)
{
    uint64_t op = se_lo64(SeMem_read(m, pa + DMA_DESC_OP, 8u));
    uint64_t src = se_lo64(SeMem_read(m, pa + DMA_DESC_SRC, 8u));
    uint64_t dst = se_lo64(SeMem_read(m, pa + DMA_DESC_DST, 8u));
    uint64_t len = se_lo64(SeMem_read(m, pa + DMA_DESC_LEN, 8u));
    uint64_t next = se_lo64(SeMem_read(m, pa + DMA_DESC_NEXT, 8u));
    uint64_t resv = se_lo64(SeMem_read(m, pa + 40u, 8u)) |
                    se_lo64(SeMem_read(m, pa + 48u, 8u)) |
                    se_lo64(SeMem_read(m, pa + 56u, 8u));
    uint64_t opcode = op & 0xFFu;
    bool copy = opcode == 1u;

    uint64_t status;
    if (opcode != 1u && opcode != 2u)
        status = SE_DMA_ST_BAD_OP; /* 0 included: zeroed-RAM guard */
    else if ((op >> 9) != 0u || next != 0u || resv != 0u)
        status = SE_DMA_ST_BAD_FORMAT;
    else if ((copy && (src & 7u) != 0u) || (dst & 7u) != 0u ||
             (len & 7u) != 0u)
        status = SE_DMA_ST_BAD_ALIGN; /* FILL: src is a pattern */
    else if (len == 0u || len > SE_DMA_LEN_MAX ||
             (copy && !dma_range_in_ram(m, src, len)) ||
             !dma_range_in_ram(m, dst, len))
        status = SE_DMA_ST_BAD_RANGE;
    else
        status = SE_DMA_ST_BUSY;

    d->dma_status = status;
    if (status != SE_DMA_ST_BUSY) {
        /* Terminal at the doorbell itself: no BUSY window, nothing
         * written, one wait-path for software -- pending rises here
         * iff the latched OP asked for it (dma.md 5.2 step 4). */
        d->dma_comp_cycle = cycle;
        if ((op >> 8) & 1u)
            d->dma_irq_pending = true;
        return;
    }
    d->dma_op = op;
    d->dma_src = src;
    d->dma_dst = dst;
    d->dma_len = len;
    d->dma_comp_cycle = cycle + SE_DMA_K + len / SE_DMA_W;
}

SeDevAcc SeDev_reg_write(SeDev *d, SePlatSpace sp, uint64_t off,
                         uint64_t val, uint64_t cycle)
{
    (void)cycle; /* consumed by the DMA doorbell case only */
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
    case SE_SPACE_DMA:
        switch (off) {
        case DMA_DOORBELL:
            /* Access-class checks, fixed order E5 -> E6 -> E7
             * (dma.md 2.1): all trap DEVERR with zero device effect;
             * an in-flight job is untouched by a rejected doorbell. */
            if (d->dma_status == SE_DMA_ST_BUSY)
                return acc_fault(); /* E5 */
            if ((val & 63u) != 0u)
                return acc_fault(); /* E6 */
            RWC_ASSERT(d->mem != NULL); /* wired at setup */
            if (!dma_range_in_ram(d->mem, val, DMA_DESC_BYTES))
                return acc_fault(); /* E7 */
            dma_doorbell(d, d->mem, val, cycle);
            return acc_val(0);
        case DMA_IRQ_ACK:
            if (val != 1u)
                return acc_fault(); /* dma.md E8: even 0 is loud */
            d->dma_irq_pending = false; /* no-op if clear: race-free */
            return acc_val(0);
        default:
            return acc_fault(); /* read-only (E4) or unlisted (E2) */
        }
    default:
        RWC_ASSERT(0);
        return acc_fault();
    }
}

void SeDev_dma_advance(SeDev *d, SeMem *m, uint64_t cycle)
{
    if (d->dma_status != SE_DMA_ST_BUSY || cycle < d->dma_comp_cycle)
        return;
    RWC_ASSERT(m != NULL && m == d->mem);
    /* The whole transfer at one boundary, as if through an
     * intermediate buffer (dma.md 5.4): sources are live RAM -- never
     * a doorbell-time stash -- so stores made since the doorbell are
     * copied. Overlap: chunk-wise memmove; addresses are 8-aligned and
     * len a multiple of 8 (validated at the doorbell), so u64 chunks
     * with a direction pick are exact. Device-internal accesses: no
     * trace records anywhere here (dma.md 7.2). */
    uint64_t len = d->dma_len;
    if ((d->dma_op & 0xFFu) == 1u) {
        uint64_t src = d->dma_src, dst = d->dma_dst;
        if (dst <= src) {
            for (uint64_t i = 0; i < len; i += 8u)
                SeMem_write(m, dst + i, 8u, SeMem_read(m, src + i, 8u));
        } else {
            for (uint64_t i = len; i != 0u; i -= 8u)
                SeMem_write(m, dst + i - 8u, 8u,
                            SeMem_read(m, src + i - 8u, 8u));
        }
    } else {
        for (uint64_t i = 0; i < len; i += 8u)
            SeMem_write(m, d->dma_dst + i, 8u, d->dma_src);
    }
    d->dma_status = SE_DMA_ST_DONE;
    if ((d->dma_op >> 8) & 1u)
        d->dma_irq_pending = true; /* the ONLY completion-path flip */
}

bool SeDev_dma_wake(const SeDev *d, uint64_t *cycle_out)
{
    if (d->dma_status != SE_DMA_ST_BUSY || ((d->dma_op >> 8) & 1u) == 0u)
        return false; /* bit-8-clear: cannot raise, cannot wake */
    *cycle_out = d->dma_comp_cycle;
    return true;
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
     * nonzero, NIC frame exposed, DMA terminal-state IRQ. The DMA term
     * is the STORED flag only -- the flip happens in the doorbell /
     * boundary advance, never here, so the predicate stays cycle-free
     * and the two emulators cannot disagree on WHEN pending becomes
     * visible (dma work order risk 1). */
    return d->kbd.count != 0u || d->mouse.count != 0u ||
           d->display_irq_status != 0u || d->nic_rx_len != 0u ||
           d->dma_irq_pending;
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
    /* Type 6, all params zero: DMA limits are spec-pinned and surfaced
     * in CAPS, not the table (dma.md 1; boot.md V10 pins the bytes). */
    devtab_record(m, &off, 6u, SE_PLAT_DMA_BASE, 0x10000u, no_params);
    /* Window bytes past the encoded table stay 0: sparse memory reads
     * zero untouched, and the loader rejects segments overlapping
     * [0x800, 0x1000) (boot.md BOOT-4, image.c). */
}
