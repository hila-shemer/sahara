#!/usr/bin/env python3
"""Trace-level assertions for c7_resize (level-2 trace). Mirrors
tests/c7_resize.s and tests/events/c7_resize.py — change together.

What the .s cannot see about itself:
1. EVENT records equal the feed byte-for-byte.
2. Geometry read sequences: W [800,640,800], H [600,480,600],
   S [3200,2560,3200] — the middle triple proves latest-wins for the
   same-cycle double event (display.md 6.4/V5), the last is the
   handler's post-ack read.
3. FORMAT read twice, both 1 (D-20); IRQ_STATUS reads only 0/1 and
   ends 0.
4. Exactly three IRQ_ACK stores, all value 1 (two main acks + the
   handler's) — and the ACK-FIRST pattern is real: the handler's ack
   (last DEVW at +0x30) precedes its geometry reads (last MEMR at
   WIDTH) in record order.
5. Exactly one pixel-window DEVW: the D-09 marker at pixbuf+0 — no
   resize touched a pixel.
6. Mouse pops: E1 then E2 exactly; one trap: EXTINT.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evcheck as C  # noqa: E402
import tracefile as T  # noqa: E402
import encoding as E  # noqa: E402

WHO = "c7_resize"
PIXBUF = 0x10000000
PIXBUF_END = PIXBUF + (16 << 20)


def main():
    if len(sys.argv) != 2:
        C.fail(WHO, "usage: c7_resize.py TRACE")
    recs = T.read_records(sys.argv[1])

    C.check_classification(WHO, recs)
    C.check_events_match_feed(WHO, recs, "c7_resize")
    C.check_seq(WHO, recs, C.DISPLAY + 0x08, [800, 640, 800], "WIDTH")
    C.check_seq(WHO, recs, C.DISPLAY + 0x10, [600, 480, 600], "HEIGHT")
    C.check_seq(WHO, recs, C.DISPLAY + 0x18, [3200, 2560, 3200],
                "STRIDE")
    C.check_seq(WHO, recs, C.DISPLAY + 0x20, [1, 1], "FORMAT")
    C.check_seq(WHO, recs, C.MOUSE + 0,
                [0x00000000024E0316, 0x0000000101DF027F], "mouse DATA")
    C.check_trap_census(WHO, recs, {E.CAUSES["EXTINT"]: 1})

    irq = C.memr_vals(recs, C.DISPLAY + 0x28)
    if any(v not in (0, 1) for v in irq) or not irq or irq[-1] != 0:
        C.fail(WHO, f"IRQ_STATUS read sequence wrong: "
                    f"[{', '.join(str(v) for v in irq)}]")
    acks = C.devw_vals(recs, C.DISPLAY + 0x30)
    if acks != [1, 1, 1]:
        C.fail(WHO, f"IRQ_ACK stores {acks}, want [1, 1, 1]")

    # ack-first (display.md 6.4): handler ack precedes handler reads
    last_ack = max(i for i, r in enumerate(recs)
                   if r.type == T.T_DEVW
                   and r.fields["ea"] == C.DISPLAY + 0x30)
    last_wread = max(i for i, r in enumerate(recs)
                     if r.type == T.T_MEMR
                     and r.fields["ea"] == C.DISPLAY + 0x08)
    if not last_ack < last_wread:
        C.fail(WHO, f"handler is not ack-first: last IRQ_ACK at record "
                    f"{last_ack}, last WIDTH read at {last_wread}")

    pix = [(r.fields["ea"], r.fields["size"], r.fields["val"])
           for r in recs if r.type == T.T_DEVW
           and PIXBUF <= r.fields["ea"] < PIXBUF_END]
    if pix != [(PIXBUF, 4, 0x00FF0000)]:
        C.fail(WHO, f"pixel-window DEVWs {pix}, want exactly the D-09 "
                    f"marker [(0x{PIXBUF:x}, 4, 0xff0000)]")
    sys.exit(0)


if __name__ == "__main__":
    main()
