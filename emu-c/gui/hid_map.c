#include "gui/hid_map.h"

bool se_hid_in_subset(uint32_t usage)
{
    if (usage >= 0xE0u && usage <= 0xE7u)
        return true; /* the eight modifiers */
    if (usage < 0x04u || usage > 0x63u)
        return false; /* 0x00-0x03 rollover codes; 0x64+ all excluded */
    return usage != 0x32u; /* the one hole: Non-US # */
}
