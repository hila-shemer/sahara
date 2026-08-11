#!/usr/bin/env python3
"""Event feed for tests/c7_rng_queue.s — entropy words with content.

Batch A at cycle 5000 arrives as TWO records sharing the cycle (1 word
+ 3 words): both apply at one boundary, so the guest's STATUS poll
jumps 0 -> 4 with no intermediate depth (rng.md 4.3). Batch B (2
words) at cycle 20000 is the WFI wake: the guest sleeps with IE off
and the feed record itself is the wake source, landing at exactly
20000 (RNG-21).

Cycle margins: the guest's pre-arrival checks run in the first few
hundred cycles, far below 5000, so RNG-18's invisible-before leg is
real. Nothing here overflows: recorded EVENTs must equal this feed
byte-for-byte.

Mirrors tests/c7_rng_queue.s and checks/c7_rng_queue.py — change all
three together.
"""

import evlib as V

WORDS_A = [0xD1CE00000000A001, 0xD1CE00000000A002,
           0xD1CE00000000A003, 0xD1CE00000000A004]
WORDS_B = [0xD1CE00000000B001, 0xD1CE00000000B002]

EVENTS = [
    (5000, V.RNG_DEV_INDEX, V.rng_words(WORDS_A[:1])),
    (5000, V.RNG_DEV_INDEX, V.rng_words(WORDS_A[1:])),
    (20000, V.RNG_DEV_INDEX, V.rng_words(WORDS_B)),
]

if __name__ == "__main__":
    img, out = V.main_two_args()
    V.write_feed(img, out, EVENTS)
