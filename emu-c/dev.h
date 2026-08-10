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
 * input queues and the live display geometry. The NIC RX queue is the
 * one still-missing model (SPEC-ISSUES 35); main.c rejects NIC EVENT
 * records loudly until it exists. */

/* 0-based positions among the reference device table's device records
 * (boot.md V1 order, written by se_plat_write_devtable). EVENT records
 * name their device by this index (devspec/trace.md 2.3.5). */
enum {
    SE_DEVIDX_DISPLAY = 0,
    SE_DEVIDX_KBD = 1,
    SE_DEVIDX_MOUSE = 2,
    SE_DEVIDX_NIC = 3,
    SE_DEVIDX_COUNT = 4,
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

typedef struct SeDev {
    /* Live display geometry (display.md 6): reference mode at reset,
     * rewritten atomically by resize events. FORMAT never changes. */
    uint64_t disp_width;
    uint64_t disp_height;
    uint64_t disp_stride;
    uint64_t display_irq_status; /* bit 0: mode changed (resize) */
    SeInputQ kbd, mouse;
    uint64_t nic_rx_len; /* exposed RX frame length; 0 = none */
    /* Set by a PRESENT store, cleared by the GUI's render pump (its
     * coalescing hook: repaint iff a frame was presented since the
     * last tick). Pure front-end state -- never read headless, no
     * guest-visible effect, not in any trace record. */
    bool present_pending;
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

/* Result of a 64-bit register access: fault = DEVERR (wrong direction,
 * unlisted offset, bad doorbell value, empty-pop -- the caller supplies
 * baddr and delivers). A faulting access has no device effect. */
typedef struct SeDevAcc {
    bool fault;
    uint64_t val;
} SeDevAcc;

/* sp names which register window (SE_SPACE_DISPLAY/KBD/MOUSE/NIC); off
 * is the byte offset inside it, 8-aligned (the caller has already
 * checked alignment and the 64-bit-only size rule). Reads may have side
 * effects (queue pop). */
RWC_WARN_UNUSED SeDevAcc SeDev_reg_read(SeDev *d, SePlatSpace sp,
                                       uint64_t off);
RWC_WARN_UNUSED SeDevAcc SeDev_reg_write(SeDev *d, SePlatSpace sp,
                                        uint64_t off, uint64_t val);

/* EXTINT is the OR of every device pending condition (PLATFORM-SPEC 3). */
RWC_WARN_UNUSED bool SeDev_ext_pending(const SeDev *d);

/* Write the device table at PA 0x0800 before reset (devspec/boot.md 3,
 * 5): header, one RAM region of ram_region_len bytes, and the four
 * reference device records. With ram_region_len = 0x0F00_0000 the bytes
 * equal boot.md vector V1 exactly (asserted by test_dev.c). */
void se_plat_write_devtable(SeMem *m, uint64_t ram_region_len);

#endif /* SE_DEV_H */
