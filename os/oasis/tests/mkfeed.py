#!/usr/bin/env python3
"""Feed builder for the Oasis test suite.

Writes a minimal replay trace (META with the image's real sha256 +
EVENT records, trace.md 2/4/5.1) for a named feed, and prints the
expectations the runner consumes as KEY=VALUE lines:

    SYSCALLS=<exact TRAP-cause-10 count the run must show>
    MIN_EXTINT=<lower bound on TRAP-cause-1 deliveries>
    LAST_CYCLE=<cycle of the last event>

SYSCALLS comes from a tiny model of the shell's I/O discipline (one
read syscall per delivered char; one write per prompt, per accepted
echo, per command output; one exit) - the same rules doc/syscalls.md
and shell.s state. If the shell's I/O shape changes, this model and
that code change together.

Encoding-as-data: payloads via root encoding.py conventions and
trace-q/tracefile.py; char->key via gen/genkeymap.py (the table the
kernel itself is built from).
"""

import hashlib
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OASIS = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(OASIS))
sys.path.insert(0, os.path.join(ROOT, "trace-q"))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(OASIS, "gen"))
import tracefile as T          # noqa: E402
import encoding as E           # noqa: E402
import genkeymap as K          # noqa: E402

# 0-based device-table indices, reference order (boot.md 5)
DEV_DISPLAY, DEV_KBD, DEV_MOUSE, DEV_NIC = 0, 1, 2, 3

BOOT_MARGIN = 800000   # boot + page-table build + banner is ~200k
                       # cycles under M2's MMU bring-up; wide margin,
                       # bumped once (work-order risk 3), never shaved
GAP = 10000            # default inter-key spacing (echo is ~3k cycles)
RELGAP = 2000          # press -> release spacing

LINE_MAX = 120         # must match kernel defs.s


def kbd(usage, press, dropped=False):
    word = (usage & 0xFFFFFFFF) | ((1 << 32) if press else 0)
    return struct.pack("<Q", word) + bytes([1 if dropped else 0])


def resize(w, h, stride, fmt=1):
    return struct.pack("<QQQQ", w, h, stride, fmt)


class Feed:
    # user-program syscall models (mirror os/oasis/user/*.s; change
    # together): fixed syscalls at entry/exit plus per-delivered-char
    # (reads, writes) while the program runs. "fixed" includes failed
    # syscalls - a rejected write is still a TRAP cause 10.
    UM_ECHO = {"fixed": 2, "per_char": (1, 1)}   # banner + exit(0)
    UM_CRASH = {"fixed": 0, "per_char": (0, 0)}  # dies before syscall 1
    UM_3FIXED = {"fixed": 3, "per_char": (0, 0)} # hostile_sp / efault:
                                                 # 2 writes + exit

    def __init__(self):
        self.events = []   # (cycle, dev, payload)
        self.chars = []    # (char, goes_to_user) in delivery order
        self.shift = False
        self.user_model = self.UM_ECHO

    def at(self, t, dev, payload):
        self.events.append((t, dev, payload))

    def key(self, t, ch, gap=GAP, relgap=RELGAP, user=False):
        """Press+release (with shift transitions) for one char.
        Returns the next free cycle."""
        hid, need = K.char_to_key(ch)
        if need and not self.shift:
            self.at(t, DEV_KBD, kbd(K.HID_LSHIFT, True))
            t += relgap
            self.shift = True
        elif not need and self.shift:
            self.at(t, DEV_KBD, kbd(K.HID_LSHIFT, False))
            t += relgap
            self.shift = False
        self.at(t, DEV_KBD, kbd(hid, True))
        self.chars.append((ch, user))
        self.at(t + relgap, DEV_KBD, kbd(hid, False))
        return t + gap

    def text(self, t, s, gap=GAP, relgap=RELGAP, user=False):
        for ch in s:
            t = self.key(t, ch, gap, relgap, user=user)
        if self.shift:
            self.at(t, DEV_KBD, kbd(K.HID_LSHIFT, False))
            self.shift = False
            t += gap
        return t

    def utext(self, t, s, gap=GAP, relgap=RELGAP):
        """Chars consumed by the running user program, not the shell."""
        return self.text(t, s, gap, relgap, user=True)

    # -- the shell I/O model (mirrors shell.s; change together) --
    def expected_syscalls(self):
        reads = 0
        writes = 1                      # the first prompt
        exits = 0
        linelen = 0
        line = []
        halted = False
        for ch, to_user in self.chars:
            assert not halted, "chars after halt are never read"
            if to_user:
                r, w = self.user_model["per_char"]
                reads += r
                writes += w
                continue
            reads += 1                  # shell reads 1 byte per syscall
            if ch == '\n':
                writes += 1             # echo the newline
                cmd = "".join(line)
                if cmd == "halt":
                    halted = True
                    line, linelen = [], 0
                    continue            # exit(): no output, no prompt
                if cmd == "run":
                    # user program: its fixed syscalls, then the
                    # shell's report line; per-char I/O is counted by
                    # the to_user branch above
                    writes += self.user_model["fixed"]  # incl. exit -
                    writes += 1         # report line   # close enough:
                    exits += 0          # every fixed call IS a TRAP 10
                elif cmd:               # every other command: 1 write
                    writes += 1         # (help/echo/uptime/unknown)
                writes += 1             # next prompt
                line, linelen = [], 0
            elif ch == '\x08':
                if linelen > 0:
                    linelen -= 1
                    line.pop()
                    writes += 1         # echo the BS
            else:
                if linelen < LINE_MAX:
                    linelen += 1
                    line.append(ch)
                    writes += 1         # echo the char
        assert halted, "feed must end with halt\\n (WFI backstop rule)"
        return reads + writes + exits + 1   # + the shell's exit

    def user_syscalls(self):
        # TRAP-10s whose epc sits in the user window: the user model's
        # fixed calls per run plus its per-char I/O (ucheck asserts
        # the count; the shell's own syscalls have kernel epcs)
        runs = 0
        line = []
        per = 0
        for ch, to_user in self.chars:
            if to_user:
                per += sum(self.user_model["per_char"])
                continue
            if ch == '\n':
                if "".join(line) == "run":
                    runs += 1
                line = []
            elif ch == '\x08':
                if line:
                    line.pop()
            else:
                line.append(ch)
        return runs * self.user_model["fixed"] + per

    def min_extint(self):
        # an event arriving >= GAP/2 after its predecessor lands with
        # the previous one fully processed (echo is ~3k cycles), so it
        # asserts EXTINT anew; tighter-packed events may coalesce into
        # one delivery and never count toward the bound
        n, prev = 0, None
        for c, d, p in sorted(self.events):
            if prev is None or c - prev >= GAP // 2:
                n += 1
            prev = c
        return max(n, 1)


def feed_boot_shell(f):
    t = f.text(BOOT_MARGIN, "echo hi\n")
    f.text(t + GAP, "halt\n")


feed_demo = feed_boot_shell


def feed_help_uptime(f):
    t = f.text(BOOT_MARGIN, "help\n")
    t = f.text(t + GAP, "uptime\n")
    t = f.text(t + GAP, "frob\n")
    f.text(t + GAP, "halt\n")


def feed_edit(f):
    # two shifted X's typed by mistake, erased, line completed
    t = f.text(BOOT_MARGIN, "ecXX\x08\x08ho ok\n")
    f.text(t + GAP, "halt\n")


def feed_predphase(f):
    # the c3_irq_dev heisenbug shape: arrivals swept across the shell's
    # compute phase so deliveries land between cmpeq and consuming
    # branch at many distinct offsets. Gaps drift by a prime; tight
    # enough that events arrive mid-echo, loose enough not to overflow.
    t = BOOT_MARGIN
    for i, ch in enumerate("echo abcdefghijklmnopqrstuvwxyz\n"):
        t = f.key(t, ch, gap=1400 + 13 * i, relgap=701)
    f.text(t + GAP, "halt\n")


def feed_ovf_shift(f):
    # shift state across a >256-event overflow burst (input.md 4.2
    # drop-newest, whole-pair drops keep alternation clean).
    t = BOOT_MARGIN
    f.at(t, DEV_KBD, kbd(K.HID_LSHIFT, True))
    f.shift = True
    t += 2 * GAP
    # 280 events at ONE cycle: queue takes 256, drops 24 (12 aA pairs)
    for i in range(140):
        dropped = 2 * i >= 256
        f.at(t, DEV_KBD, kbd(0x04, True, dropped=dropped))
        if 2 * i < 256:
            f.chars.append(('A', False))   # 128 visible presses
        f.at(t, DEV_KBD, kbd(0x04, False, dropped=(2 * i + 1 >= 256)))
    t += 2 * GAP
    f.at(t, DEV_KBD, kbd(K.HID_LSHIFT, False))
    f.shift = False
    t += 2 * GAP
    t = f.text(t, "\x08" * 10)         # erase back below LINE_MAX
    t = f.text(t, "x\n")               # lowercase proves shift cleared
    f.text(t + GAP, "halt\n")


def feed_scroll(f):
    # push the prompt to the bottom row, then force scrolls. Sub-screen
    # sessions everywhere else; this is the ONE scroll test.
    t = BOOT_MARGIN
    for _ in range(28):
        t = f.key(t, '\n')
    t = f.text(t + GAP, "echo bottom\n")
    f.text(t + 2 * GAP, "halt\n")


def feed_u_enter(f):
    # S->U->S round trip: run, user banner, one echoed line, q quits,
    # report + prompt return, halt. Also the emu-py smoke leg's feed.
    t = f.text(BOOT_MARGIN, "run\n")
    t = f.utext(t + GAP, "hi\n")
    t = f.utext(t + GAP, "q\n")
    f.text(t + GAP, "halt\n")


def feed_u_echo(f):
    # keystrokes fed while the user program runs, several lines, then
    # quit; echo.s's burn loop guarantees TIMER traps with user epcs
    t = f.text(BOOT_MARGIN, "run\n")
    t = f.utext(t + GAP, "hello world\n")
    t = f.utext(t + GAP, "abc\n")
    t = f.utext(t + GAP, "q\n")
    f.text(t + GAP, "halt\n")


def feed_u_kill(f):
    # a crash image: run dies instantly; the keystone is the shell
    # coming back and WORKING - echo ok, then a clean halt
    f.user_model = Feed.UM_CRASH
    t = f.text(BOOT_MARGIN, "run\n")
    t = f.text(t + 2 * GAP, "echo ok\n")
    f.text(t + GAP, "halt\n")


def feed_u_3fixed(f):
    # hostile_sp / efault images: three fixed user syscalls, no user
    # input, then the same kernel-survives epilogue
    f.user_model = Feed.UM_3FIXED
    t = f.text(BOOT_MARGIN, "run\n")
    t = f.text(t + 2 * GAP, "echo ok\n")
    f.text(t + GAP, "halt\n")


def feed_u_rerun(f):
    # run, quit, run again: the image is loaded once (v0.1 A.7), so
    # the second entry proves echo.s re-initializes from code
    t = f.text(BOOT_MARGIN, "run\n")
    t = f.utext(t + GAP, "q\n")
    t = f.text(t + GAP, "run\n")
    t = f.utext(t + GAP, "q\n")
    f.text(t + GAP, "halt\n")


def feed_m1_regression(f):
    # the M1 suite semantics in one session, now under MMU_EN=1: the
    # identity axiom (SABI 4.4) says conforming kernel code needs zero
    # changes when translation goes on - this feed proves it instead
    # of assuming it (work-order risk 1).
    t = f.text(BOOT_MARGIN, "help\n")
    t = f.text(t + GAP, "ecXX\x08\x08ho ok\n")
    t = f.text(t + GAP, "uptime\n")
    t = f.text(t + GAP, "frob\n")
    f.text(t + GAP, "halt\n")


def feed_resize(f):
    # resize before typing: geometry re-read via ack-first, re-layout,
    # typing continues on the new stride
    f.at(BOOT_MARGIN, DEV_DISPLAY, resize(800, 600, 3200))
    t = f.text(BOOT_MARGIN + 5 * GAP, "echo hi\n")
    f.text(t + GAP, "halt\n")


FEEDS = {n[len("feed_"):]: fn for n, fn in list(globals().items())
         if n.startswith("feed_")}


def main():
    if len(sys.argv) != 4 or sys.argv[1] not in FEEDS:
        sys.exit(f"usage: {sys.argv[0]} {{{'|'.join(sorted(FEEDS))}}} "
                 f"IMAGE OUT_TRC")
    name, img, out = sys.argv[1:]
    f = Feed()
    FEEDS[name](f)
    f.events.sort(key=lambda e: e[0])
    with open(img, "rb") as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()
    with open(out, "wb") as fh:
        T.write_record(fh, T.T_META, T.meta_payload(T.meta_text(
            0, mode="live", image=img, image_sha256=sha,
            encoding_version=E.SPEC_VERSION)))
        for cycle, dev, payload in f.events:
            T.write_record(fh, T.T_EVENT,
                           T.event_payload(cycle, dev, payload))
    print(f"SYSCALLS={f.expected_syscalls()}")
    print(f"MIN_EXTINT={f.min_extint()}")
    print(f"LAST_CYCLE={f.events[-1][0]}")
    print(f"USER_SYSCALLS={f.user_syscalls()}")


if __name__ == "__main__":
    main()
