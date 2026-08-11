#ifndef SE_DEV_H
#define SE_DEV_H

#include <stdbool.h>
#include <stdint.h>

#include "mem.h"
#include "platform.h"
#include "rwc/attrs.h"

/* The reference platform's devices, headless (PLATFORM-SPEC 4-7 as
 * elaborated by devspec/display.md, input.md, nic.md; the device table
 * by devspec/boot.md). This is the register surface, the fault matrix,
 * and the EVENT-injection targets of --replay (devspec/trace.md 4-5):
 * input queues, the live display geometry, and the NIC RX queue
 * (nic.md 4 -- the model that closed SPEC-ISSUES 35's gap). The
 * translator that authors NIC events lives in the GUI front end
 * (gui/nic.c); headless, frames arrive only through SeDev_inject_nic
 * from the replay feed. */

/* 0-based positions among the reference device table's device records
 * (boot.md V1 order, written by se_plat_write_devtable). EVENT records
 * name their device by this index (devspec/trace.md 2.3.5). */
enum {
    SE_DEVIDX_DISPLAY = 0,
    SE_DEVIDX_KBD = 1,
    SE_DEVIDX_MOUSE = 2,
    SE_DEVIDX_NIC = 3,
    /* This branch's table position only (boot.md V10) -- the wave-final
     * table reorders records by base at integration. Nothing may key on
     * this value: the DMA engine is not EVENT-fed, so no trace record
     * ever names it, and the EVENT indices 0-3 above stay frozen. */
    SE_DEVIDX_DMA = 4,
    SE_DEVIDX_COUNT = 5,
};

/* Input event FIFO (input.md 4.1): depth exactly 256 on the reference
 * platform, so overflow behavior is deterministic and STATUS reads
 * 0-256. */
#define SE_INPUT_QDEPTH 256u

typedef struct SeInputQ {
    uint64_t ev[SE_INPUT_QDEPTH];
    uint32_t head;  /* index of the oldest event */
    uint32_t count; /* 0..SE_INPUT_QDEPTH */
} SeInputQ;

/* Ethernet II frame length bounds at the NIC interface, FCS-less
 * (nic.md 3.1): doorbell values, exposed RX_LEN, and EVENT inner
 * payloads all live in this range. */
#define SE_NIC_FRAME_MIN 60u
#define SE_NIC_FRAME_MAX 1514u

/* NIC RX frame store (nic.md 4.1): capacity 64 admitted frames total,
 * 1 exposed + up to 63 queued, fixed FIFO ring, no allocation. The
 * exposed frame is the ring head; its bytes were copied to the RX
 * buffer at exposure, so the ring keeps only what RX_POP still needs. */
#define SE_NIC_QDEPTH 64u

/* DMA engine (devspec/dma.md): STATUS codes (3.2) and the spec-pinned
 * constants of the cost model (6), all mirrored in CAPS (3.1). */
enum {
    SE_DMA_ST_IDLE = 0,
    SE_DMA_ST_BUSY = 1,
    SE_DMA_ST_DONE = 2,
    SE_DMA_ST_BAD_OP = 3,
    SE_DMA_ST_BAD_FORMAT = 4,
    SE_DMA_ST_BAD_ALIGN = 5,
    SE_DMA_ST_BAD_RANGE = 6,
};

#define SE_DMA_K 8u                       /* fixed job overhead, cycles */
#define SE_DMA_W 8u                       /* bytes per cycle */
#define SE_DMA_LEN_MAX (1ull << 24)       /* 16 MB */
#define SE_DMA_CAPS 0x18080301ull         /* dma.md 3.1 encoding */

typedef struct SeNicRxQ {
    uint8_t frame[SE_NIC_QDEPTH][SE_NIC_FRAME_MAX];
    uint16_t len[SE_NIC_QDEPTH];
    uint32_t head;  /* index of the exposed frame when count > 0 */
    uint32_t count; /* 0..SE_NIC_QDEPTH, exposed frame included */
} SeNicRxQ;

typedef struct SeDev {
    /* Live display geometry (display.md 6): reference mode at reset,
     * rewritten atomically by resize events. FORMAT never changes. */
    uint64_t disp_width;
    uint64_t disp_height;
    uint64_t disp_stride;
    uint64_t display_irq_status; /* bit 0: mode changed (resize) */
    SeInputQ kbd, mouse;
    uint64_t nic_rx_len; /* exposed RX frame length; 0 = none */
    SeNicRxQ nic_rxq;
    /* Guest memory, wired at setup by every front end (dev = mem = one
     * machine): RX exposure writes frame bytes into the RX buffer
     * window, both at admission and at RX_POP -- device-internal
     * writes, never trace records (nic.md 7.2). */
    SeMem *mem;
    /* TX consumer hook: called after E5 validation with the doorbell
     * length; the hook captures TX buffer bytes [0, len) synchronously
     * (nic.md 2.2) and runs the GUI's translator. NULL headless --
     * byte-for-byte the pre-translator drop, and the structural half
     * of the replay isolation guarantee (nic.md 7.3). */
    void (*tx_doorbell)(void *ctx, uint32_t len);
    void *tx_ctx;
    /* Set by a PRESENT store, cleared by the GUI's render pump (its
     * coalescing hook: repaint iff a frame was presented since the
     * last tick). Pure front-end state -- never read headless, no
     * guest-visible effect, not in any trace record. */
    bool present_pending;
    /* DMA engine (devspec/dma.md 3, 5). No inject fn and no EVENT
     * path: a job is a pure function of (descriptor latched at the
     * doorbell, RAM at the completion boundary, doorbell cycle).
     * dma_comp_cycle is written at the doorbell (dma.md 3.5 / root
     * SPEC-ISSUES 41), so a BUSY-time COMP_CYCLE read returns the
     * schedule. dma_irq_pending flips ONLY at a terminal state --
     * content errors at the doorbell, completion in the boundary
     * advance -- never inside SeDev_ext_pending, which stays
     * cycle-free by design. FILL keeps its pattern in dma_src. */
    uint64_t dma_status;      /* SE_DMA_ST_* */
    uint64_t dma_comp_cycle;
    bool dma_irq_pending;
    uint64_t dma_op, dma_src, dma_dst, dma_len; /* latched at doorbell */
} SeDev;

void SeDev_reset(SeDev *d);

/* Apply one input event word (input.md 2.1/3.1) arriving at a boundary.
 * A full queue drops the NEW event (drop-newest, input.md 4.2): returns
 * true so the caller records the recomputed dropped-on-arrival flag
 * (trace.md 5.4); the queue is untouched. */
RWC_WARN_UNUSED bool SeDev_inject_input(SeDev *d, bool kbd, uint64_t word);

/* Apply one resize event (display.md 6.2): WIDTH/HEIGHT/STRIDE update
 * together and IRQ_STATUS bit 0 sets, one atomic action at the
 * boundary. The caller has validated the geometry (display.md 3.4). */
void SeDev_inject_resize(SeDev *d, uint64_t width, uint64_t height,
                         uint64_t stride);

/* Apply one NIC arrival event (nic.md 4.2) at a boundary: admit the
 * frame -- expose it immediately if the mailbox is empty, else queue
 * it -- or discard it when 64 frames are already held. Returns true
 * for the overflow discard, and the caller then records NO event
 * (nic.md 4.3): the one asymmetry against input's flagged-record drop,
 * kept explicit at the apply_events call site. m must be the wired
 * d->mem (passed for symmetry with the setup contract). */
RWC_WARN_UNUSED bool SeDev_inject_nic(SeDev *d, SeMem *m,
                                      const uint8_t *frame, uint16_t len);

/* Result of a 64-bit register access: fault = DEVERR (wrong direction,
 * unlisted offset, bad doorbell value, empty-pop -- the caller supplies
 * baddr and delivers). A faulting access has no device effect. */
typedef struct SeDevAcc {
    bool fault;
    uint64_t val;
} SeDevAcc;

/* sp names which register window (SE_SPACE_DISPLAY/KBD/MOUSE/NIC/DMA);
 * off is the byte offset inside it, 8-aligned (the caller has already
 * checked alignment and the 64-bit-only size rule). Reads may have side
 * effects (queue pop). Writes take the executing instruction's cycle --
 * the value stamped on the store's DEVW record -- because the DMA
 * doorbell's C_done and error-path COMP_CYCLE are arithmetic on it
 * (dma.md 5.2, 6); every other device ignores it. */
RWC_WARN_UNUSED SeDevAcc SeDev_reg_read(SeDev *d, SePlatSpace sp,
                                       uint64_t off);
RWC_WARN_UNUSED SeDevAcc SeDev_reg_write(SeDev *d, SePlatSpace sp,
                                        uint64_t off, uint64_t val,
                                        uint64_t cycle);

/* The boundary device phase's DMA completion step (dma.md 5.5): when a
 * job is in flight and cycle has reached its C_done, perform the whole
 * transfer -- memmove-exact, straight into guest memory, zero trace
 * records (dma.md 7.2) -- and flip STATUS/pending. Runs after EVENT
 * apply, before interrupt recognition; the caller asserts the weak-
 * store queue is already drained (it never re-flushes). */
void SeDev_dma_advance(SeDev *d, SeMem *m, uint64_t cycle);

/* Is an in-flight job a WFI wake source, and at what cycle? True iff
 * BUSY with latched OP bit 8 set -- a bit-8-clear job cannot make an
 * interrupt pending and so cannot end a WFI stall (dma.md 7.5, root
 * SPEC-ISSUES 42). */
RWC_WARN_UNUSED bool SeDev_dma_wake(const SeDev *d, uint64_t *cycle_out);

/* EXTINT is the OR of every device pending condition (PLATFORM-SPEC 3). */
RWC_WARN_UNUSED bool SeDev_ext_pending(const SeDev *d);

/* Write the device table at PA 0x0800 before reset (devspec/boot.md 3,
 * 5): header, one RAM region of ram_region_len bytes, and the four
 * reference device records. With ram_region_len = 0x0F00_0000 the bytes
 * equal boot.md vector V1 exactly (asserted by test_dev.c). */
void se_plat_write_devtable(SeMem *m, uint64_t ram_region_len);

#endif /* SE_DEV_H */
