#ifndef SE_GUI_HID_MAP_H
#define SE_GUI_HID_MAP_H

#include <stdbool.h>
#include <stdint.h>

#include "rwc/attrs.h"

/* The platform keyboard's usage-ID subset (input.md 2.2): exactly 103
 * IDs from the USB HID Keyboard/Keypad page. SDL scancodes ARE page-7
 * usages, so the front end filters rather than maps; host keys whose
 * usage falls outside the table are silently discarded -- no event, no
 * queue entry, no trace record (INPUT-10). */
RWC_WARN_UNUSED bool se_hid_in_subset(uint32_t usage);

#endif /* SE_GUI_HID_MAP_H */
