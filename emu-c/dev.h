#ifndef SE_DEV_H
#define SE_DEV_H

#include <stdbool.h>
#include <stdint.h>

#include "mem.h"
#include "platform.h"
#include "rw/attrs.h"

/* The reference platform's devices, headless (PLATFORM-SPEC 4-7 as
 * elaborated by devspec/display.md, input.md, nic.md; the device table
 * by devspec/boot.md). This is the register surface and the fault
 * matrix; the input/NIC event queues are always empty until EVENT
 * injection lands (the headless suite generates no events), so the
 * state here is the little that headless registers can observe. */

typedef struct SeDev {
    uint64_t display_irq_status; /* bit 0: mode changed (resize) */
    uint64_t nic_rx_len;         /* exposed RX frame length; 0 = none */
} SeDev;

void SeDev_reset(SeDev *d);

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
RW_WARN_UNUSED SeDevAcc SeDev_reg_read(SeDev *d, SePlatSpace sp,
                                       uint64_t off);
RW_WARN_UNUSED SeDevAcc SeDev_reg_write(SeDev *d, SePlatSpace sp,
                                        uint64_t off, uint64_t val);

/* EXTINT is the OR of every device pending condition (PLATFORM-SPEC 3). */
RW_WARN_UNUSED bool SeDev_ext_pending(const SeDev *d);

/* Write the device table at PA 0x0800 before reset (devspec/boot.md 3,
 * 5): header, one RAM region of ram_region_len bytes, and the four
 * reference device records. With ram_region_len = 0x0F00_0000 the bytes
 * equal boot.md vector V1 exactly (asserted by test_dev.c). */
void se_plat_write_devtable(SeMem *m, uint64_t ram_region_len);

#endif /* SE_DEV_H */
