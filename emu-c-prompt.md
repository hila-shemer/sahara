# Sahara emulator — C implementation (emu-c/)

Read `emu-common-prompt.md` first; it governs. This file adds only what is
specific to the C implementation.

## Role

This is **the reference implementation**. Other implementations are diffed
against it; per CONFORMANCE.md, it additionally matches recorded trace
hashes, so its traces are the recorded baseline once tests stabilize.
Clarity over everything: C11, portable, no optimization flags beyond -O1.

## Language specifics

- Use rightwayc — `~/proj/rightwayc` — and the applicable skills
  (rw-c-scaffold for setup, rw-c-review before finishing).
- Core is a library with no GUI dependency; the headless front end
  `sahara-emu` implements the frozen CLI contract.
- Consume `sahara_isa.h` (regenerate + diff against committed in the build
  script; `crosscheck.py` in CI).
- 128-bit: `unsigned __int128` is available (gcc/clang). MULH at width 128
  needs a manual 128×128→256 high half — test it against Python bigints in
  CI.
- FP: host `float`/`double` arithmetic is IEEE-conformant for the specced
  operations; set rounding via `fesetround` per fcsr, compute flags via
  `fetestexcept`. FCVT per spec, not per C cast behavior.

## GUI front end (last phase, after the shared suite is green headless)

`sahara-gui`: SDL2 — display window, keyboard/mouse capture, NIC bridged
to host (slirp-style; a minimal DHCP+NAT UDP/TCP/ICMP-echo translator you
write is acceptable; document what subset works). Every GUI session
records its event trace; any session replays headless bit-exactly. The
GUI is the only component allowed to touch real time, and only to
*timestamp* events into virtual cycles. The Python implementation has no
GUI; this one is the platform's interactive face.
