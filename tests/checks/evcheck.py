#!/usr/bin/env python3
"""Shared helpers for the event-fed tests' trace checks
(c7_kbd / c7_resize / c7_kbd_ovf). Import from checks/*.py; not a
standalone tool.

The one non-obvious assertion lives in check_events_match_feed: the
recorded trace's EVENT records must equal the feed byte-for-byte —
cycle, device index, payload (flags byte included). Cycle equality is
exact because these guests never idle (no WFI), so every cycle value
is an instruction boundary and an event with cycle C is applied and
recorded at exactly C (trace.md 5.2/5.4). A dropped-on-arrival flag
mismatch here means the emulator's overflow decision diverged from
the feed's (trace.md 5.4).
"""

import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "trace-q"))
sys.path.insert(0, ROOT)
import tracefile as T  # noqa: E402
import encoding as E  # noqa: E402

DEV_BASE = 0x0F000000
DISPLAY = 0x0F000000
KBD = 0x0F010000
MOUSE = 0x0F020000
SENTINEL = 0xFFFFFFFFFFFFFFFF


def fail(who, msg):
    print(f"checks/{who}: {msg}", file=sys.stderr)
    sys.exit(1)


def load_feed_events(name):
    """EVENTS list of tests/events/<name>.py — the single source of
    truth the .s, the feed, and the check all mirror."""
    evdir = os.path.join(ROOT, "tests", "events")
    sys.path.insert(0, evdir)
    spec = importlib.util.spec_from_file_location(
        f"feed_{name}", os.path.join(evdir, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.EVENTS


def check_events_match_feed(who, recs, name):
    feed = load_feed_events(name)
    got = [(r.fields["cycle"], r.fields["device"], r.fields["bytes"])
           for r in recs if r.type == T.T_EVENT]
    if len(got) != len(feed):
        fail(who, f"{len(got)} EVENT records, feed has {len(feed)}")
    for i, ((gc, gd, gp), (fc, fd, fp)) in enumerate(zip(got, feed)):
        if (gc, gd, bytes(gp)) != (fc, fd, bytes(fp)):
            fail(who, f"EVENT {i}: recorded (cycle={gc} dev={gd} "
                      f"payload={bytes(gp).hex()}) != feed (cycle={fc} "
                      f"dev={fd} payload={bytes(fp).hex()})")


def memr_vals(recs, ea):
    """Values of every MEMR at exactly ea, in record order."""
    return [r.fields["val"] for r in recs
            if r.type == T.T_MEMR and r.fields["ea"] == ea]


def devw_vals(recs, ea):
    return [r.fields["val"] for r in recs
            if r.type == T.T_DEVW and r.fields["ea"] == ea]


def trap_census(recs):
    causes = {}
    for r in recs:
        if r.type == T.T_TRAP:
            c = r.fields["cause"]
            causes[c] = causes.get(c, 0) + 1
    return causes


def check_classification(who, recs):
    """trace.md T-12: stores land in MEMW xor DEVW by physical target."""
    for i, r in enumerate(recs):
        if r.type == T.T_MEMW and r.fields["ea"] >= DEV_BASE:
            fail(who, f"record {i}: MEMW at device ea "
                      f"0x{r.fields['ea']:x} — must be DEVW (T-12)")
        if r.type == T.T_DEVW and r.fields["ea"] < DEV_BASE:
            fail(who, f"record {i}: DEVW at RAM ea 0x{r.fields['ea']:x}")


def check_seq(who, recs, ea, want, label):
    got = memr_vals(recs, ea)
    if got != want:
        fail(who, f"{label} read sequence at 0x{ea:x} is "
                  f"[{', '.join(f'0x{v:x}' for v in got)}], want "
                  f"[{', '.join(f'0x{v:x}' for v in want)}]")


def check_trap_census(who, recs, want):
    got = trap_census(recs)
    if got != want:
        names = {v: k for k, v in E.CAUSES.items()}
        fail(who, "trap census mismatch: got {"
             + ", ".join(f"{names.get(c, c)}: {n}"
                         for c, n in sorted(got.items()))
             + "}, want {"
             + ", ".join(f"{names.get(c, c)}: {n}"
                         for c, n in sorted(want.items())) + "}")
