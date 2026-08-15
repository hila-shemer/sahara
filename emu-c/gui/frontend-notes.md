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
the point.

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
