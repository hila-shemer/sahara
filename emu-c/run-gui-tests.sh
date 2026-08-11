#!/usr/bin/env bash
# emu-c-owned GUI test gate (work-order deliverable 4; new checks live
# here, never under tests/):
#   1. translator/blit/HID/NIC-vector unit tests (the bazel short tier)
#   2. core-seam record->replay identity: gui-seam-driver feeds
#      scripted sequences through SeCpu_feed, then the frozen
#      `sahara-emu --replay` must reproduce every post-META record
#      byte-for-byte (WFI idle stamping, >256 burst drop recompute,
#      same-cycle multi-event ordering, NIC frames + the 64-cap
#      overflow's no-record rule)
#   3. the end-to-end scripted sessions through the real sahara-gui
#      binary under SDL_VIDEODRIVER=dummy, replayed via the exact
#      invocation the GUI printed (T-18) -- input (demo.s) and the
#      --nic fake NIC session (t_nic.s), both socket-free: this
#      script must pass identically under `unshare -rn` where the
#      host allows user namespaces
# Byte-identity is post-META because mode= differs between live and
# replay by design (trace.md 5.3).
set -euo pipefail
cd "$(dirname "$0")"

bazel build //:sahara-emu //:sahara-gui //:gui-seam-driver //:test_gui
bazel test //:test_gui

ASM=../asm/asm.py
OUT=gui/out
mkdir -p "$OUT"
PASS_LINE="HALT r0=0000000000000000000000000000600d"

cmp_post_meta() {
    python3 - "$1" "$2" <<'EOF'
import sys

def body(p):
    d = open(p, "rb").read()
    assert d[0] == 7, p + ": record 0 is not META"
    plen = int.from_bytes(d[4:8], "little")
    return d[8 + plen:]

a, b = body(sys.argv[1]), body(sys.argv[2])
if a != b:
    sys.exit("post-META divergence: %s vs %s (%d vs %d bytes)"
             % (sys.argv[1], sys.argv[2], len(a), len(b)))
print("  identical: %d post-META bytes" % len(a))
EOF
}

for sc in wfi burst multi nicseam rng; do
    echo "seam scenario: $sc"
    python3 "$ASM" -o "$OUT/t_$sc.img" "gui/t_$sc.s"
    bazel-bin/gui-seam-driver "$sc" "$OUT/t_$sc.img" "$OUT/t_$sc.trc"
    bazel-bin/sahara-emu "$OUT/t_$sc.img" --replay "$OUT/t_$sc.trc" \
        --trace "$OUT/t_$sc.replay.trc" --trace-level 1 \
        | grep -qx "$PASS_LINE"
    cmp_post_meta "$OUT/t_$sc.trc" "$OUT/t_$sc.replay.trc"
done

echo "scripted session gate"
python3 "$ASM" -o "$OUT/demo.img" gui/demo.s
SDL_VIDEODRIVER=dummy bazel-bin/sahara-gui "$OUT/demo.img" \
    --script gui/session.script --trace "$OUT/session.trc" \
    > "$OUT/session.out"
grep -qx "$PASS_LINE" "$OUT/session.out"

# Two identical scripted invocations must produce byte-identical .trc
# files in their entirety (T-17 for the live binary; also catches any
# wall-clock leakage into --script mode).
SDL_VIDEODRIVER=dummy bazel-bin/sahara-gui "$OUT/demo.img" \
    --script gui/session.script --trace "$OUT/session2.trc" \
    > /dev/null
cmp "$OUT/session.trc" "$OUT/session2.trc"

# Replay through the exact invocation the GUI printed; PATH resolves
# the unmodified command to the freshly built binary.
CMD="$(grep '^sahara-emu ' "$OUT/session.out")"
PATH="$PWD/bazel-bin:$PATH" sh -c "$CMD" > "$OUT/replay.out"
grep -qx "$PASS_LINE" "$OUT/replay.out"
cmp_post_meta "$OUT/session.trc" "$OUT/session.trc.replay.trc"

echo "scripted NIC session gate (--nic fake)"
# The whole nic.md local plane end to end through the real binary:
# TV-S1 DHCP handshake, ARP, virtual-host ping, one UDP flow echoed
# by the socket-free fake backend. Same idioms as above: double-run
# whole-file cmp, then replay via the printed command -- a networked
# session reproduced by the frozen headless binary with no network.
python3 "$ASM" -o "$OUT/t_nic.img" gui/t_nic.s
SDL_VIDEODRIVER=dummy bazel-bin/sahara-gui "$OUT/t_nic.img" \
    --script gui/t_nic.script --nic fake --trace "$OUT/nic.trc" \
    > "$OUT/nic.out"
grep -qx "$PASS_LINE" "$OUT/nic.out"
SDL_VIDEODRIVER=dummy bazel-bin/sahara-gui "$OUT/t_nic.img" \
    --script gui/t_nic.script --nic fake --trace "$OUT/nic2.trc" \
    > /dev/null
cmp "$OUT/nic.trc" "$OUT/nic2.trc"
CMD="$(grep '^sahara-emu ' "$OUT/nic.out")"
PATH="$PWD/bazel-bin:$PATH" sh -c "$CMD" > "$OUT/nic-replay.out"
grep -qx "$PASS_LINE" "$OUT/nic-replay.out"
cmp_post_meta "$OUT/nic.trc" "$OUT/nic.trc.replay.trc"

# --nic host must be refused under --script: the scripted gate stays
# socket-free by construction (work-order decision 7).
if SDL_VIDEODRIVER=dummy bazel-bin/sahara-gui "$OUT/t_nic.img" \
    --script gui/t_nic.script --nic host >/dev/null 2>&1; then
    echo "ERROR: --script --nic host was accepted"; exit 1
fi

echo "run-gui-tests: all green"
