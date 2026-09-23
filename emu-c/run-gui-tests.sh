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

# Background processes this script started (sahara-serve, test
# clients): killed on any exit, so a failing or timed-out leg under
# set -e never leaves a server behind.
BG_PIDS=()
cleanup() {
    for pid in ${BG_PIDS[@]+"${BG_PIDS[@]}"}; do
        kill "$pid" 2>/dev/null || true
    done
}
trap cleanup EXIT

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

echo "SVP auth: constant-time compare is the only MAC check"
# Structural: the MAC verdict goes through SeHmac_equal (volatile fold,
# no early exit), and neither auth TU has a memcmp to slip back to.
grep -q 'return SeHmac_equal(m->p, want, SE_SVP_MAC_BYTES);' gui/svp.c
if grep -n 'memcmp' gui/svp.c gui/hmac.c; then
    echo "ERROR: memcmp in the auth path"; exit 1
fi

# The shared token for every serve/view leg below: a private temp file,
# created the way frontend-notes.md tells a user to.
TOKDIR="$OUT/token.d"
rm -rf "$TOKDIR"
mkdir -m 700 "$TOKDIR"
TOKEN_FILE="$TOKDIR/serve-token"
(umask 077; head -c 32 /dev/urandom | base64 > "$TOKEN_FILE")
WRONG_TOKEN_FILE="$TOKDIR/wrong-token"
(umask 077; head -c 32 /dev/urandom | base64 > "$WRONG_TOKEN_FILE")

echo "sahara-serve: refuses to start without a private token file"
# Missing (explicit path, and the XDG default), 0644, and 0640: each a
# non-zero exit before anything is written, naming the fix.
refuse_serve() { # refuse_serve NAME EXPECTED-TEXT env/args...
    local name=$1 want=$2; shift 2
    if env "$@" --script gui/session.script \
        --trace "$OUT/$name.trc" > /dev/null 2> "$OUT/$name.err"; then
        echo "ERROR: sahara-serve started ($name)"; exit 1
    fi
    grep -qF -- "$want" "$OUT/$name.err" || {
        echo "ERROR: $name: expected '$want' in:"; cat "$OUT/$name.err"
        exit 1; }
    if [ -e "$OUT/$name.trc" ]; then
        echo "ERROR: refused start ($name) still wrote a trace"; exit 1
    fi
    echo "  $name: $(head -1 "$OUT/$name.err")"
}
rm -f "$OUT"/tok-*.trc
refuse_serve tok-missing 'head -c 32 /dev/urandom | base64 >' \
    bazel-bin/sahara-serve "$OUT/demo.img" --token-file "$TOKDIR/nope"
refuse_serve tok-default "$TOKDIR/xdg/sahara/serve-token" \
    XDG_CONFIG_HOME="$PWD/$TOKDIR/xdg" bazel-bin/sahara-serve "$OUT/demo.img"
cp "$TOKEN_FILE" "$TOKDIR/open-token"
chmod 644 "$TOKDIR/open-token"
refuse_serve tok-0644 'mode 0644, must be 0600 or stricter' \
    bazel-bin/sahara-serve "$OUT/demo.img" --token-file "$TOKDIR/open-token"
chmod 640 "$TOKDIR/open-token"
refuse_serve tok-0640 "chmod 600 '$TOKDIR/open-token'" \
    bazel-bin/sahara-serve "$OUT/demo.img" --token-file "$TOKDIR/open-token"
(umask 077; echo short > "$TOKDIR/short-token")
refuse_serve tok-short 'must hold 16..1024 bytes' \
    bazel-bin/sahara-serve "$OUT/demo.img" --token-file "$TOKDIR/short-token"
# The view applies the same rule to its own file, before connecting.
if bazel-bin/sahara-view 127.0.0.1:9 --token-file "$TOKDIR/open-token" \
    2> "$OUT/view-open-token.err"; then
    echo "ERROR: sahara-view accepted a 0640 token file"; exit 1
fi
grep -q 'must be 0600 or stricter' "$OUT/view-open-token.err"

echo "sahara-serve: scripted session is sahara-gui's, byte for byte"
# The two binaries share gui/live_main.c; under --script the backend is
# never consulted for input or time, so the traces must be identical,
# whole file. This is what makes a served session trustworthy.
bazel-bin/sahara-serve "$OUT/demo.img" --script gui/session.script \
    --token-file "$TOKEN_FILE" --trace "$OUT/serve-script.trc" > /dev/null
cmp "$OUT/session.trc" "$OUT/serve-script.trc"

# start_serve NAME: sahara-serve on the demo image, loopback port 0 (the
# kernel picks a free one, no pick-then-bind race); sets SERVE_PID and
# PORT from the "listening on" line.
start_serve() {
    local name=$1
    bazel-bin/sahara-serve "$OUT/demo.img" --nic off \
        --listen 127.0.0.1:0 --token-file "$TOKEN_FILE" \
        --trace "$OUT/$name.trc" \
        > "$OUT/$name.out" 2> "$OUT/$name.err" &
    SERVE_PID=$!
    BG_PIDS+=("$SERVE_PID")
    PORT=
    for _ in $(seq 50); do
        PORT="$(sed -n 's/^sahara-serve: listening on 127\.0\.0\.1:\([0-9]*\)$/\1/p' \
            "$OUT/$name.err")"
        [ -n "$PORT" ] && break
        sleep 0.1
    done
    [ -n "$PORT" ] || { echo "ERROR: sahara-serve never listened"; exit 1; }
}

# stop_serve: the operator's way to end a session now that no viewer
# can -- SIGTERM -- then the replay line must be there.
stop_serve() {
    kill -0 "$SERVE_PID" || { echo "ERROR: sahara-serve already gone"; exit 1; }
    kill -TERM "$SERVE_PID"
    wait "$SERVE_PID"
    BG_PIDS=()
}

# kbd_events TRACE: keyboard EVENT records in a session trace.
kbd_events() {
    python3 - "$1" <<'PYEOF'
import sys
sys.path.insert(0, "../trace-q")
import tracefile as T
print(sum(1 for r in T.read_records(sys.argv[1])
          if r.name == "EVENT" and r.fields["device"] == 1))
PYEOF
}

# svp_client.py: a raw SVP/2 peer for the legs a real view cannot play
# (wrong answers, input before auth, holding the slot, flooding).
cat > "$OUT/svp_client.py" <<'PYEOF'
import hashlib, hmac, socket, struct, sys

def recv_msg(s):
    hdr = b""
    while len(hdr) < 8:
        b = s.recv(8 - len(hdr))
        if not b:
            return None
        hdr += b
    t, n = hdr[0], struct.unpack_from("<I", hdr, 4)[0]
    body = b""
    while len(body) < n:
        b = s.recv(n - len(body))
        if not b:
            return None
        body += b
    return t, body

def token(path):
    return open(path, "rb").read().rstrip(b" \t\r\n")

def auth(s, tok):
    t, body = recv_msg(s)
    assert t == 5 and len(body) == 36, f"expected CHALLENGE, got {t}"
    assert struct.unpack_from("<I", body)[0] == 2, "not SVP/2"
    mac = hmac.new(tok, b"SVP/2 AUTH" + body[4:], hashlib.sha256).digest()
    s.sendall(struct.pack("<B3xI", 21, 32) + mac)

def key(usage, press):
    return struct.pack("<B3xIIBB2x", 16, 8, usage, press, 0)
PYEOF

echo "SVP auth negative controls: wrong token, input before auth, silence"
# Each is refused without a FRAME, feeds no EVENT, and the server keeps
# running; the session's trace is checked for zero keyboard EVENTs
# before any authenticated view has attached.
start_serve serve-auth
python3 - "$PORT" "$WRONG_TOKEN_FILE" <<'PYEOF'
import socket, sys, time
sys.path.insert(0, "gui/out")
from svp_client import *
port, wrong = int(sys.argv[1]), token(sys.argv[2])
# 1. Wrong token, with KEYs pipelined behind the AUTH: DENIED, close.
s = socket.create_connection(("127.0.0.1", port))
auth(s, wrong)
s.sendall(b"".join(key(4 + i, 1) + key(4 + i, 0) for i in range(8)))
seen = []
while (m := recv_msg(s)) is not None:
    seen.append(m[0])
assert seen == [6], f"wrong token: expected only DENIED, got {seen}"
print("  wrong token: DENIED, connection closed, no FRAME")
# 2. Input instead of AUTH: the first message is the one attempt.
s = socket.create_connection(("127.0.0.1", port))
t, _ = recv_msg(s)
assert t == 5
s.sendall(b"".join(key(4, p) for p in (1, 0)) * 8)
seen = []
while (m := recv_msg(s)) is not None:
    seen.append(m[0])
assert seen == [6], f"input before auth: expected only DENIED, got {seen}"
print("  input before auth: DENIED, no FRAME")
# 3. Silence: closed at the 5 s deadline, nothing sent but CHALLENGE.
s = socket.create_connection(("127.0.0.1", port))
t0 = time.monotonic()
t, _ = recv_msg(s)
assert t == 5
s.settimeout(15)
m = recv_msg(s)
dt = time.monotonic() - t0
assert m is None, f"silent peer got message {m[0]}"
assert 4.5 <= dt <= 8, f"auth deadline {dt:.2f} s, want ~5 s"
print(f"  silent peer: closed after {dt:.2f} s")
PYEOF
# The real view with the wrong token: the distinct message, exit 1, and
# no retry (one line, no "retrying").
if SDL_VIDEODRIVER=offscreen timeout 20 bazel-bin/sahara-view \
    "127.0.0.1:$PORT" --token-file "$WRONG_TOKEN_FILE" --probe 1 \
    > /dev/null 2> "$OUT/view-wrong.err"; then
    echo "ERROR: sahara-view with a wrong token succeeded"; exit 1
fi
grep -qx 'sahara-view: authentication failed (wrong token for this server)' \
    "$OUT/view-wrong.err"
if grep -q retrying "$OUT/view-wrong.err"; then
    echo "ERROR: sahara-view retried a refused token"; exit 1
fi
kill -0 "$SERVE_PID"
test "$(grep -c 'viewer authentication failed' "$OUT/serve-auth.err")" = 3
if grep -q 'viewer connected' "$OUT/serve-auth.err"; then
    echo "ERROR: an unauthenticated peer became the viewer"; exit 1
fi
stop_serve
test "$(kbd_events "$OUT/serve-auth.trc")" = 0
echo "  server kept running; 0 keyboard EVENTs in its trace"
CMD="$(grep '^sahara-emu ' "$OUT/serve-auth.out")"
PATH="$PWD/bazel-bin:$PATH" sh -c "$CMD" > "$OUT/serve-auth-replay.out" || true
cmp_post_meta "$OUT/serve-auth.trc" "$OUT/serve-auth.trc.replay.trc"

echo "sahara-serve + sahara-view: CLOSE detaches, a second view drives on"
# A real remote session over loopback: view 1 (token file) probes 10
# keys and leaves with CLOSE; the session keeps running; view 2 (token
# from the environment) attaches while an unauthenticated peer sits in
# the door, probes 4 more, leaves. SIGTERM then ends the session, and
# its one trace -- both viewers' keys -- replays byte-identically.
start_serve serve-live
SDL_VIDEODRIVER=offscreen timeout 60 bazel-bin/sahara-view \
    "127.0.0.1:$PORT" --token-file "$TOKEN_FILE" --probe 10 \
    > "$OUT/view-probe.out"
grep -q '^input-to-present: n=10 ' "$OUT/view-probe.out"
sleep 0.5
kill -0 "$SERVE_PID" || { echo "ERROR: CLOSE ended the session"; exit 1; }
grep -q 'viewer disconnected; session continues' "$OUT/serve-live.err"
if grep -q '^sahara-emu ' "$OUT/serve-live.out"; then
    echo "ERROR: the session ended when the view closed"; exit 1
fi
# An unauthenticated connection holds a door slot during view 2's
# whole attach: it must not take or block the viewer slot.
python3 -c "
import socket, sys, time
s = socket.create_connection(('127.0.0.1', int(sys.argv[1])))
time.sleep(6)" "$PORT" &
LURKER_PID=$!
BG_PIDS+=("$LURKER_PID")
sleep 0.2
SAHARA_VIEW_TOKEN="$(cat "$TOKEN_FILE")" SDL_VIDEODRIVER=offscreen \
    timeout 60 bazel-bin/sahara-view "127.0.0.1:$PORT" --probe 4 \
    > "$OUT/view-probe2.out" 2> "$OUT/view-probe2.err"
grep -q '^input-to-present: n=4 ' "$OUT/view-probe2.out"
if grep -q retrying "$OUT/view-probe2.err"; then
    echo "ERROR: view 2 was kept waiting by an unauthenticated peer"; exit 1
fi
wait "$LURKER_PID" || true
test "$(grep -c 'viewer connected' "$OUT/serve-live.err")" = 2
stop_serve
grep -q 'SIGTERM: ending the session' "$OUT/serve-live.err"
# 14 keys, press + release each; the demo guest needs no others.
test "$(kbd_events "$OUT/serve-live.trc")" = 28
echo "  two viewers, one session: 28 keyboard EVENTs"
CMD="$(grep '^sahara-emu ' "$OUT/serve-live.out")"
PATH="$PWD/bazel-bin:$PATH" sh -c "$CMD" > "$OUT/serve-live-replay.out" || true
cmp_post_meta "$OUT/serve-live.trc" "$OUT/serve-live.trc.replay.trc"

echo "sahara-serve: input flood is rate-limited and in order; BUSY view retries"
# An authenticated client holds the only slot and dumps 6000 KEY
# messages at once (press/release pairs over a..z), far more than one
# poll's budget and than the server's input rate (a burst of 256, then
# 1000 a second), so the server must take at least (6000-256)/1000 s
# over them -- longer than the holder's own 3 s stay, which is what the
# timing check sees. While it holds the slot a real sahara-view
# authenticates, gets BUSY and must retry rather than die; once the
# holder leaves, the view gets in, probes two keys and detaches. The
# trace must hold all 6000 flood keys in send order, spread over many
# poll stamps (the budget at work), then the view's 4, and the session
# must replay byte-identically.
FLOOD=6000
start_serve serve-flood
python3 - "$PORT" "$FLOOD" "$TOKEN_FILE" > "$OUT/flood-holder.out" <<'PYEOF' &
import socket, sys, time
sys.path.insert(0, "gui/out")
from svp_client import *
port, n = int(sys.argv[1]), int(sys.argv[2])
s = socket.create_connection(("127.0.0.1", port))
auth(s, token(sys.argv[3]))
t, _ = recv_msg(s)
assert t == 1, f"expected HELLO, got type {t}"
print("holding", flush=True)
t0 = time.monotonic()
s.sendall(b"".join(key(4 + (i // 2) % 26, 1 - i % 2) for i in range(n)))
time.sleep(3)  # keep the slot while the view knocks
# FIN, not RST: every flood byte must reach the server. Read until the
# server closes its side (it has consumed everything by then).
s.shutdown(socket.SHUT_WR)
while s.recv(65536):
    pass
s.close()
print(f"consumed in {time.monotonic() - t0:.2f} s", flush=True)
PYEOF
HOLDER_PID=$!
BG_PIDS+=("$HOLDER_PID")
for _ in $(seq 50); do
    grep -q holding "$OUT/flood-holder.out" 2>/dev/null && break
    sleep 0.1
done
SDL_VIDEODRIVER=offscreen timeout 60 bazel-bin/sahara-view \
    "127.0.0.1:$PORT" --token-file "$TOKEN_FILE" --probe 2 \
    > "$OUT/view-flood.out" 2> "$OUT/view-flood.err"
wait "$HOLDER_PID"
stop_serve
grep -q 'session busy.*retrying for up to 60 s' "$OUT/view-flood.err"
test "$(grep -c retrying "$OUT/view-flood.err")" = 1 # one line, not a spam
grep -q '^input-to-present: n=2 ' "$OUT/view-flood.out"
python3 - "$OUT/flood-holder.out" "$FLOOD" <<'PYEOF'
import re, sys
secs = float(re.search(r"consumed in ([0-9.]+) s", open(sys.argv[1]).read())[1])
n = int(sys.argv[2])
floor = (n - 256) / 1000 * 0.9
print(f"  {n} flood keys consumed in {secs:.2f} s (rate floor {floor:.2f} s)")
assert secs >= floor, "input was not rate-limited"
PYEOF
python3 - "$OUT/serve-flood.trc" "$FLOOD" <<'PYEOF'
import sys
sys.path.insert(0, "../trace-q")
import tracefile as T
n = int(sys.argv[2])
kbd = [r.fields for r in T.read_records(sys.argv[1])
       if r.name == "EVENT" and r.fields["device"] == 1]
assert len(kbd) == n + 4, f"expected {n + 4} keyboard EVENTs, got {len(kbd)}"
for i, f in enumerate(kbd[:n]):
    word = int.from_bytes(f["bytes"][:8], "little")
    want = (4 + (i // 2) % 26) | ((1 - i % 2) << 32)
    assert word == want, f"flood EVENT {i}: {word:#x}, want {want:#x}"
stamps = {}
for f in kbd[:n]:
    stamps[f["cycle"]] = stamps.get(f["cycle"], 0) + 1
biggest = max(stamps.values())
print(f"  {n} flood keys in order over {len(stamps)} stamps, "
      f"largest {biggest}")
# An unbudgeted drain takes whole socket reads per poll; the budget
# (256 per poll) must show up as many small batches.
assert len(stamps) >= n // 1024, "flood was not spread over polls"
PYEOF
CMD="$(grep '^sahara-emu ' "$OUT/serve-flood.out")"
PATH="$PWD/bazel-bin:$PATH" sh -c "$CMD" > "$OUT/serve-flood-replay.out" || true
cmp_post_meta "$OUT/serve-flood.trc" "$OUT/serve-flood.trc.replay.trc"

echo "run-gui-tests: all green"
