#!/usr/bin/env python3
"""Event feed for tests/c7_rng_overflow.s — the truncate-to-fit rule
(rng.md 4.2) driven past the 256-word queue.

Four records, all at cycle 5000, against an empty queue:

  A: 128 words  -> accepted in full          (depth 128)
  B: 120 words  -> accepted in full          (depth 248)
  C:  16 words  -> accepted 8, 8 discarded   (depth 256)
  D:   8 words  -> accepted 0 at depth 256   -> records NOTHING

The recorded trace therefore has THREE rng EVENT records, C's payload
truncated to its first 8 words — recorded = accepted prefix, not the
raw feed (checks/c7_rng_overflow.py asserts the bytes). The REPLAY=1
leg replays the RECORDING, whose 256 words fit exactly: the fixed
point the truncation rule buys (rng.md 7.3; SPEC-ISSUES 40).

Accepted words follow w(i) = 0xC0FFEE0000000000 + i, i = 0..255, so
the .s recomputes them with one add per pop. D's words use a marker
pattern that must never be observable.

Mirrors tests/c7_rng_overflow.s and checks/c7_rng_overflow.py — change
all three together.
"""

import evlib as V

BASE = 0xC0FFEE0000000000
STREAM = [BASE + i for i in range(264)]          # A + B + C words
DROPPED = [0xDEADDEADDEAD0000 + i for i in range(8)]  # D: never seen

EVENTS = [
    (5000, V.RNG_DEV_INDEX, V.rng_words(STREAM[:128])),
    (5000, V.RNG_DEV_INDEX, V.rng_words(STREAM[128:248])),
    (5000, V.RNG_DEV_INDEX, V.rng_words(STREAM[248:264])),
    (5000, V.RNG_DEV_INDEX, V.rng_words(DROPPED)),
]

# What a conforming emulator must RECORD (the accepted prefixes; the
# zero-accepted D record is absent). The checker compares against
# this, not against EVENTS.
ACCEPTED = [
    (5000, V.RNG_DEV_INDEX, V.rng_words(STREAM[:128])),
    (5000, V.RNG_DEV_INDEX, V.rng_words(STREAM[128:248])),
    (5000, V.RNG_DEV_INDEX, V.rng_words(STREAM[248:256])),
]

if __name__ == "__main__":
    img, out = V.main_two_args()
    V.write_feed(img, out, EVENTS)
