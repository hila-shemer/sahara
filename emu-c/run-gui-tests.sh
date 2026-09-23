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

bazel build //:sahara-emu //:sahara-gui //:sahara-serve //:sahara-view \
    //:gui-seam-driver //:test_gui //:test_svp
bazel test //:test_gui //:test_svp

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

echo "untethered session gate (--untethered)"
# untethered-mode-prompt.md decisions 2/3: the recorder is never
# attached, so a fresh cwd stays empty (not even the session-*.trc
# default), stderr carries the banner exactly twice (startup + exit),
# and stdout has the guest result but no replay command - there is
# nothing to replay.
ROOT="$PWD"
UDIR="$OUT/untethered.d"
rm -rf "$UDIR"
mkdir "$UDIR"
(cd "$UDIR" && SDL_VIDEODRIVER=dummy "$ROOT/bazel-bin/sahara-gui" \
    "$ROOT/$OUT/demo.img" --script "$ROOT/gui/session.script" \
    --untethered > untethered.out 2> untethered.err)
grep -qx "$PASS_LINE" "$UDIR/untethered.out"
test "$(grep -cx 'untethered session: not recorded, not replayable' \
    "$UDIR/untethered.err")" = 2
if grep -q '^sahara-emu ' "$UDIR/untethered.out"; then
    echo "ERROR: untethered session printed a replay command"; exit 1
fi
if ls "$UDIR"/*.trc >/dev/null 2>&1; then
    echo "ERROR: untethered session left a trace file"; exit 1
fi

# Recording and not-recording at once is a contradiction the user
# resolves: loud startup error, never a silent override (decision 2).
for extra in "--trace $OUT/conflict.trc" "--trace-level 1"; do
    if SDL_VIDEODRIVER=dummy bazel-bin/sahara-gui "$OUT/demo.img" \
        --script gui/session.script --untethered $extra \
        > /dev/null 2> "$OUT/conflict.err"; then
        echo "ERROR: --untethered $extra was accepted"; exit 1
    fi
    grep -q 'untethered never records' "$OUT/conflict.err"
done
if [ -e "$OUT/conflict.trc" ]; then
    echo "ERROR: the conflict error still opened a trace file"; exit 1
fi

echo "recorded-mode regression vs merge base"
# The untethered wiring must leave recorded mode untouched: the same
# scripted session through the merge-base sahara-gui produces a
# byte-identical trace, whole file - --script owns the clock, so two
# binaries with identical behavior cannot drift by a byte.
BASE_SHA="$(git merge-base main HEAD)"
if [ "$BASE_SHA" = "$(git rev-parse HEAD)" ]; then
    echo "  HEAD is the merge base: nothing to compare"
else
    # The throwaway worktree must sit beside this checkout, not in
    # /tmp: the build resolves rightwayc as ../../rightwayc, and only
    # our parent directory has that sibling (checkout or worktree
    # layout alike).
    BASE_WT="$(cd ../.. && pwd)/sahara-gui-base-$BASE_SHA"
    [ -d "$BASE_WT" ] || git worktree add --detach "$BASE_WT" "$BASE_SHA"
    (cd "$BASE_WT/emu-c" && bazel build //:sahara-gui)
    SDL_VIDEODRIVER=dummy "$BASE_WT/emu-c/bazel-bin/sahara-gui" \
        "$OUT/demo.img" --script gui/session.script \
        --trace "$OUT/session-base.trc" > /dev/null
    cmp "$OUT/session.trc" "$OUT/session-base.trc"
fi

echo "netboot ROM reproducibility gate"
# Committed netboot.img, the generated netboot_rom.c TU, and VERSION's
# sha256 must all reproduce from a fresh asm.py rebuild - the two
# in-tree copies of the ROM bytes stay honest.
../rom/netboot/build.sh --check

echo "netboot fixtures"
NBROM=../rom/netboot/netboot.img
NBSCRIPT=../rom/netboot/test/netboot.script
python3 "$ASM" -o "$OUT/nb-core.img" ../rom/netboot/test/payload.s
python3 ../rom/netboot/test/mkpayload.py --core "$OUT/nb-core.img" \
    --rom "$NBROM" --outdir "$OUT"

echo "netboot headline gate (no IMAGE, --nic fake, --serve-image)"
# The vision made test: no image argument - the embedded ROM
# materializes next to the trace, fetches the multi-block payload over
# SBP, copy-downs it over its own footprint (zero-fill tail included),
# and the payload HALTs 600d. Then the same double-run and
# printed-command replay idioms as the sessions above: the image came
# over the network and the frozen headless binary reproduces the boot
# offline from the trace alone.
SDL_VIDEODRIVER=dummy bazel-bin/sahara-gui --script "$NBSCRIPT" \
    --nic fake --serve-image "$OUT/payload.img" --hz 0 \
    --maxcycles 3000000 --trace "$OUT/netboot.trc" > "$OUT/netboot.out"
grep -qx "$PASS_LINE" "$OUT/netboot.out"
cmp "$OUT/netboot.rom.img" "$NBROM"
cp "$OUT/netboot.trc" "$OUT/netboot.first.trc"
SDL_VIDEODRIVER=dummy bazel-bin/sahara-gui --script "$NBSCRIPT" \
    --nic fake --serve-image "$OUT/payload.img" --hz 0 \
    --maxcycles 3000000 --trace "$OUT/netboot.trc" > /dev/null
cmp "$OUT/netboot.first.trc" "$OUT/netboot.trc"
CMD="$(grep '^sahara-emu ' "$OUT/netboot.out")"
PATH="$PWD/bazel-bin:$PATH" sh -c "$CMD" > "$OUT/netboot-replay.out"
grep -qx "$PASS_LINE" "$OUT/netboot-replay.out"
cmp_post_meta "$OUT/netboot.trc" "$OUT/netboot.trc.replay.trc"

echo "netboot loud-failure legs"
# Each malformed image is one scripted run asserting its frozen HALT
# code (the codes are the CI contract; the on-screen text is for
# humans). Traces go to /dev/null - failure legs prove codes, not
# replay, and the timeout leg alone would write a ~2 GB level-0 trace.
nb_fail() { # nb_fail CODE extra-args...
    local code=$1; shift
    SDL_VIDEODRIVER=dummy bazel-bin/sahara-gui --rom "$NBROM" \
        --script "$NBSCRIPT" --hz 0 --maxcycles 50000000 \
        --trace /dev/null "$@" \
        | grep -qx "HALT r0=0000000000000000000000000000$code"
}
nb_fail bad6 --nic fake --serve-image "$OUT/bad-magic.img"
nb_fail bad7 --nic fake --serve-image "$OUT/truncated.img"
nb_fail bad7 --nic fake --serve-image "$OUT/low-seg.img"
# Image bigger than stage_cap under a small --ram: overflows the
# staging window mid-download (192 KB RAM -> 64 KB cap).
nb_fail bad8 --nic fake --serve-image "$OUT/too-big.img" --ram 0x30000
# No translator at all: the timer-COUNT retransmit path, 5 sends x 8M
# cycles, then 0xBAD4 - the only leg where the timeout budget runs.
nb_fail bad4 --nic off

echo "netboot no-server leg + error-screen decode"
# No --serve-image: the service answers ERR 1 in one round trip ->
# 0xBAD5. Runs at level 1 through the embedded-ROM path so the same
# trace also feeds the fbcheck-style decode: the human-readable
# message really rendered (font parsed from the ROM's own font.s).
SDL_VIDEODRIVER=dummy bazel-bin/sahara-gui --script "$NBSCRIPT" \
    --nic fake --hz 0 --maxcycles 3000000 --trace-level 1 \
    --trace "$OUT/nb-noserve.trc" > "$OUT/nb-noserve.out"
grep -qx "HALT r0=0000000000000000000000000000bad5" "$OUT/nb-noserve.out"
python3 ../rom/netboot/test/screencheck.py "$OUT/nb-noserve.trc" \
    --expect-sub "no boot image configured"

echo "sahara-serve: scripted session is sahara-gui's, byte for byte"
# The two binaries share gui/live_main.c; under --script the backend is
# never consulted for input or time, so the traces must be identical,
# whole file. This is what makes a served session trustworthy.
bazel-bin/sahara-serve "$OUT/demo.img" --script gui/session.script \
    --trace "$OUT/serve-script.trc" > /dev/null
cmp "$OUT/session.trc" "$OUT/serve-script.trc"

echo "sahara-serve + sahara-view: live loopback session replays"
# A real remote session: serve on a loopback port, view connects under
# the offscreen SDL driver, --probe types a/Backspace, --end-session
# ends it. The server's trace must hold the viewer's keys as keyboard
# EVENTs and replay byte-identically through the printed command.
PORT="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')"
bazel-bin/sahara-serve "$OUT/demo.img" --nic off --listen "127.0.0.1:$PORT" \
    --trace "$OUT/serve-live.trc" > "$OUT/serve-live.out" 2> "$OUT/serve-live.err" &
SERVE_PID=$!
for _ in $(seq 50); do
    grep -q 'listening on' "$OUT/serve-live.err" 2>/dev/null && break
    sleep 0.1
done
SDL_VIDEODRIVER=offscreen timeout 60 bazel-bin/sahara-view \
    "127.0.0.1:$PORT" --probe 10 --end-session > "$OUT/view-probe.out"
wait "$SERVE_PID"
grep -q '^input-to-present: n=10 ' "$OUT/view-probe.out"
python3 - "$OUT/serve-live.trc" <<'PYEOF'
import sys
sys.path.insert(0, "../trace-q")
import tracefile as T
kbd = sum(1 for r in T.read_records(sys.argv[1])
          if r.name == "EVENT" and r.fields["device"] == 1)
# 10 keys, press + release each; the demo guest needs no others.
assert kbd == 20, f"expected 20 keyboard EVENTs from the viewer, got {kbd}"
PYEOF
CMD="$(grep '^sahara-emu ' "$OUT/serve-live.out")"
PATH="$PWD/bazel-bin:$PATH" sh -c "$CMD" > "$OUT/serve-live-replay.out" || true
cmp_post_meta "$OUT/serve-live.trc" "$OUT/serve-live.trc.replay.trc"

echo "run-gui-tests: all green"
