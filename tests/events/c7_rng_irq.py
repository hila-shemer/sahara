#!/usr/bin/env python3
"""Event feed for tests/c7_rng_irq.s — the IE-qualified level
interrupt (rng.md 6: RNG-20/21).

Two words at cycle 5000 sit in the queue while CTRL.IE = 0 — depth
alone must NOT assert EXTINT (reset-off keeps the device invisible to
type-7-unaware kernels). The guest then sets IE and takes exactly one
level-triggered delivery, draining STATUS-then-pop. One word at cycle
30000 wakes a WFI with IE back off: the feed record is the wake
source and lands at exactly 30000, no delivery.

Mirrors tests/c7_rng_irq.s and checks/c7_rng_irq.py — change all
three together.
"""

import evlib as V

WORDS_A = [0x1BAD5EED00000001, 0x1BAD5EED00000002]
WORD_B = [0x1BAD5EED00000003]

EVENTS = [
    (5000, V.RNG_DEV_INDEX, V.rng_words(WORDS_A)),
    (30000, V.RNG_DEV_INDEX, V.rng_words(WORD_B)),
]

if __name__ == "__main__":
    img, out = V.main_two_args()
    V.write_feed(img, out, EVENTS)
