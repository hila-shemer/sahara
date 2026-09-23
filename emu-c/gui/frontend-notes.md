# sahara-gui front-end notes

**Phase amendment:** the GUI phase started at commit "Core seam for
the GUI phase" — the phase gate of emu-c-prompt.md was satisfied (the
shared suite green headless for both emulators) before the first GUI
line landed.

## Two live sessions never match — by design

A live session's EVENT cycles come from human timing quantized by the
pacing loop; two interactive runs of the same image are therefore
never byte-identical, and nothing should try to "fix" that. The
contract is different: any *one* session's trace replays bit-exactly
through `sahara-emu --replay` (the command printed on exit), and two
runs of the same `--script` session ARE byte-identical because the
script owns the clock. run-gui-tests.sh asserts both.

## What the exit line means

On any exit (halt, window close, --maxcycles) the GUI prints one
`sahara-emu ...` line: the exact headless invocation that reproduces
the session. `--maxcycles <end>` pins the endpoint so a session ended
by window close terminates under replay (exit 2/MAXCYCLES, trace
prefix identical); a halted session halts on its own before the cap.

## Untethered mode (--untethered): the sanctioned opt-out

Owner ruling 2026-08-15 (untethered-mode-prompt.md, SPEC-ISSUES 44):
sessions that retire instructions in bulk - DOOM-class workloads now,
the GPU later - may opt out of the always-record rule. `--untethered`
never attaches the recorder: no trace file, no META, no record
emission on the hot path, no replay command at exit. What it forfeits
is exactly the platform's headline guarantee - the session is not
reproducible, full stop - so it is loud twice: `untethered session:
not recorded, not replayable` on stderr at startup AND exit. Combining
it with `--trace`/`--trace-level` is a startup error, never a silent
override. It composes with `--nic`/`--hz`/`--script`; pair with
`--hz 0` for throughput work - free-run with the recorder detached is
the point. It also composes with netboot (no IMAGE): the embedded ROM
still materializes and boots, but with no trace to name the file
after it falls back to `untethered-<epoch>.rom.img` - the replay
guarantee the (trace, rom) pair anchors is forfeited anyway.

Recorded mode stays the default and the only mode any gate runs;
`sahara-emu` is untouched (headless without `--trace` was already
untethered).

**Results-only test convention** (the ruling's other half, for FUTURE
heavy suites - nothing existing converts): a suite whose sessions
retire instructions in bulk may judge outcomes - the exit contract
(HALT magic / exit code), memory, framebuffer state - and skip
byte-identity. Every existing gate keeps the byte-exact replay
contract.

## Capture UX (input.md Appendix A)

Keyboard follows window focus. Mouse is click-to-capture (pointer
hidden + confined; the capturing click is delivered); left Ctrl+Alt
releases; focus loss or release synthesizes release events for every
held key and button, so the guest never sees stuck keys. Uncaptured
motion is invisible to the guest. `--script` events bypass the
capture gate — the script *is* the fake host.

## --script grammar (test-only)

One command per line, `#` comments: `wait MS`, `keydown U`,
`keyup U`, `keyrepeat U`, `mouse X Y BTN`, `focuslost`, `close`.
U is a page-7 usage (= SDL scancode), BTN the packed sahara mask
(bit 0 left, 1 right, 2 middle). The clock is fake and only `wait`
advances it; a `wait` is a deterministic burst of `MS * hz / 1000`
cycles, so the live-mode slew heuristic is disabled under --script.

## v2 resize recipe (deliberately NOT implemented)

v1 is fixed 640x480, non-resizable: META carries no display mode, so
replay leans on the fixed reset default (display.md 1). When v2 makes
the window resizable:

- coalesce host resize drags; emit one resize event per settled size;
- legal geometry chosen at a boundary: STRIDE = 4*W rounded up to 16,
  bounds checked against the pixel window (display.md 3.4), FORMAT 1;
- inject through SeCpu_feed (device 0, trace.md 4.4 payload) so it is
  traced and replays — never poke SeDev directly;
- letterbox the stale frame until the guest's next PRESENT
  (display.md 6.5: cosmetic, outside determinism);
- recreate the SDL texture at the new mode on the next repaint;
- mouse clamping already tracks dev->disp_* at the injection
  boundary, so it follows resize for free (input.md 3.3 rule 1).

## Manual smoke checklist (work order; run with a real window)

    ./bazel-bin/sahara-gui gui/out/demo.img

- window opens 640x480, gradient band on first PRESENT; no PRESENT
  means the last frame persists
- typing paints one block per key press (held key = one block: no
  auto-repeat); press+release pairs in the trace
- click captures (cursor hides), motion draws white dots, left
  Ctrl+Alt releases capture
- alt-tab away mid-keypress: the trace shows the synthesized release
- idle guest (WFI) wakes on input; close prints the replay command
  and running it reproduces the session byte-identically

## Remote: sahara-serve + sahara-view (2026-09-23)

`sahara-serve` is this live session with an SVP/1 socket backend
(gui/be_svp.c) instead of the window; `sahara-view` is the window,
anywhere on the network (gui/view_main.c). Protocol: SVP/2, gui/svp.h.

    sahara-serve IMAGE --listen 100.123.236.10:8453 [--token-file PATH] [live options]
    sahara-view flatpot.tail0b59ad.ts.net:8453 [--token-file PATH] [--probe N]

Both ends need the same secret token, in a private file (setup below).

- The view sends raw host facts; the server translates and feeds them
  through the same path as SDL, so a served session replays under
  `sahara-emu --replay` (run-gui-tests: scripted serve == gui, whole
  file; live loopback serve+view replays byte-identically).
- One authenticated viewer owns input; a second authenticated one gets
  BUSY. Closing the view sends CLOSE and disconnects (a capture loss:
  all keys and buttons released); the session keeps running and the
  next view gets HELLO and a full frame. A dropped connection is the
  same. **Nothing a view sends ends the session**: the guest halting,
  `--maxcycles`, or SIGINT/SIGTERM to sahara-serve do, and each prints
  the replay line (SIGTERM is what `systemctl --user stop` sends). The
  two are taken whether the guest sleeps or spins: a busy guest at
  `--hz 0` never waits in the server's ppoll, so each poll also takes a
  pending one without waiting. The
  old `sahara-view --end-session` is gone and says so.
- A view that dies without closing (laptop suspended) is reaped by TCP
  keepalive + `TCP_USER_TIMEOUT` on the server's socket in about 20 s;
  until then the slot is still taken. sahara-view retries BUSY,
  "connection refused" and a close before CHALLENGE (a full pending
  table, below) for up to 60 s (one line on stderr), so a view
  started right after a resume gets in once the dead one is gone. A
  server that accepts but never sends HELLO fails the view in 5 s.
  Any other connect failure (no route, no IPv6, no fds) fails at once.
  Linux applies `TCP_USER_TIMEOUT` to zero-window probing too: a live
  view that stops reading for 20 s with a frame waiting (Ctrl-Z, a
  blocked event loop) is dropped the same way -- a capture loss.
- Input is budgeted and rate-limited: at most 256 messages per server
  poll, and a token bucket of 256 then 1000 messages a second across
  polls; the rest waits in the socket (TCP pushes back on the view),
  in order. The per-poll cap alone kept the core's feed queue bounded
  but not the rate: a loopback flood was served at ~21k keys/s and
  grew the trace by ~40 MB/s. Capped, a flood costs about 2-3 MB/s
  of trace on the demo image (~1.9 KB of guest work per key; the
  gate's 6000-key flood session is a 16 MB trace). The view sends pointer motion once per event batch, not per
  SDL motion event, so a 1 kHz mouse stays well under the cap.
  run-gui-tests: 6000 keys in one burst, checked in order and taking
  at least the rate's time.
- `--listen HOST:0` binds a free port and prints the real one on the
  `listening on` line (the test gate uses this).
- Frames: RAW or XRLE (XOR vs previous frame, run-length), whichever
  is smaller -- a glyph echo is a few hundred bytes. Frames coalesce to
  the newest while one is draining.
- Build `-c opt` for real use: the XRLE encode is 3 ms optimized and
  20 ms at fastbuild's -O0.
- Recording is on (level 0): a served Oasis session grows its trace at
  ~65 KB/s (see Open decisions). Keep traces on tmpfs, and restart the
  session to reset.

### Authentication (owner decision 2026-09-23: "much like other remote-view servers")

Shared-token challenge-response, VNC's shape with HMAC-SHA256 in place
of DES (gui/svp.h has the wire detail):

- sahara-serve reads the token from `--token-file PATH`, default
  `${XDG_CONFIG_HOME:-~/.config}/sahara/serve-token`. It refuses to
  start, before writing anything (no trace file), if the file is
  missing, not a regular file, not owned by the serving user, has any
  group/other permission bit (0600 or 0400 only), or does not hold
  16..1024 bytes after the trailing newline is trimmed. The message
  names the file and the one command that fixes it. This applies under
  `--script` too: one rule, no mode-dependent exception.
- sahara-view takes the token from `--token-file PATH`, else from the
  environment variable `SAHARA_VIEW_TOKEN`, else from the same default
  path on its own machine; a token file there is held to the same rule
  (the view refuses too, so both ends behave alike). The token is never
  accepted on argv on either end (ps would show it).
- On connect the server sends `CHALLENGE{version 2, 32 random bytes
  from getrandom}`; the view answers `AUTH{HMAC-SHA256(token, "SVP/2
  AUTH" || nonce)}`. The token never crosses the wire, and an answer is
  useless against the next nonce. The server compares in constant time
  (`SeHmac_equal`; run-gui-tests checks it is the only compare) and
  allows one attempt: a wrong MAC, any other first message, or input
  sent instead gets `DENIED` and a close; silence is closed after 5 s.
  The view prints `sahara-view: authentication failed (wrong token for
  this server)` and exits 1 without retrying.
- Before AUTH checks, a connection gets nothing but CHALLENGE: no
  HELLO, no FRAME, not even whether the slot is taken, and none of its
  bytes are read as input. It waits in a separate pending table (4
  entries) and never holds or contends for the viewer slot, so it can
  neither push out nor block an authenticated view. BUSY is only ever
  said to an authenticated view. A connection that finds all 4 entries
  taken is closed unanswered; the view treats that close as retryable.
  Residual: a tailnet peer without the token can keep the 4 pending
  entries full (5 s each) and so hold new views off (each gives up
  after 60 s); it can never reach the session.
- One-way, as in VNC: the view does not authenticate the server (the
  tailnet already authenticates the host). SHA-256 is the core's
  FIPS 180-4 one (sha256.c, unchanged); HMAC is gui/hmac.c. test_svp
  checks FIPS 180-4 and all seven RFC 4231 vectors.
- An SVP/1 view against this server fails on the CHALLENGE ("bad
  HELLO"); this view against an SVP/1 server says to upgrade the server.

Setup (flatpot serves, mercury views):

    # on flatpot, as the user that runs sahara-serve
    umask 077; mkdir -p ~/.config/sahara && head -c 32 /dev/urandom | base64 > ~/.config/sahara/serve-token
    # copy it to mercury without widening its mode
    ssh mercury 'umask 077; mkdir -p ~/.config/sahara'
    scp -p ~/.config/sahara/serve-token mercury:.config/sahara/serve-token
    ssh mercury 'chmod 600 ~/.config/sahara/serve-token'

run-gui-tests covers: a missing, default-path-missing, 0644, 0640 and
too-short token file each stop the server with no trace written, and
the view refuses a 0640 file; a wrong-token AUTH (with KEYs pipelined
behind it), input instead of AUTH, and a silent peer are each refused
with no FRAME, the server keeps running, and its trace has 0 keyboard
EVENTs; the real view with a wrong token prints the message above,
exits 1, and never retries; view 1 probes 10 keys and CLOSEs, the
session keeps running, view 2 (token from the environment) attaches
while an unauthenticated peer (confirmed holding its CHALLENGE) sits
in the door and probes 4 more, and the one trace (28 keyboard EVENTs)
replays byte-identically after SIGTERM; with 4 peers filling the
pending table the real view says so once, retries, and attaches when
they leave; and a guest that spins at `--hz 0` without ever sleeping
still ends on SIGTERM with the replay line.

**Open decision (owner's call, not implemented):**
- *Trace retention.* The live session trace grows about 65 KB/s
  (measured: 194 MB in 50 minutes) and lives under ~/.cache, which on
  flatpot is RAM. Nothing caps or rotates it; a session left running
  for a day costs ~5.6 GB of RAM. A viewer flooding input at the rate
  cap adds about 2-3 MB/s (~150 MB a minute) on top; since auth only a
  token holder can. Cap, rotate, drop
  to untethered for long-lived serves, or leave as is: open.

Latency (`sahara-view --probe`, key sent -> frame presented by the view,
compositor and scanout excluded), Oasis, --hz 2 MHz, -c opt:

| path | p50 | p95 | max |
|---|---|---|---|
| loopback on flatpot | 10.2 ms | 11.4 ms | 16.7 ms |
| mercury -> flatpot, tailnet on the home LAN | 12.6 ms | 15.2 ms | 17.6 ms |

Two live-only pacing rules in live_main.c exist for this; --script
never takes them:

- When input lands and the guest is ahead of the pacing clock, which it
  is after any WFI because WFI jumps the cycle to timecmp (ISA 7.6),
  re-anchor pacing at the guest's cycle with one chunk of budget.
  Without this, every key waited up to one timer period (50 ms at
  Oasis's 100k-cycle tick and 2 MHz).
- A PRESENT ends the step chunk, so the frame is handed over at once,
  not up to CHUNK_MS later.
