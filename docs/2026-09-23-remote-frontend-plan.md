# Remote frontend plan (2026-09-23)

Design: `docs/2026-09-23-remote-frontend-design.md` (A-native: `sahara-serve` on
flatpot, `sahara-view` on mercury, spark NVENC for H.264).

## Phase 1 - Sahara locally on mercury (DONE 2026-09-23)

No code change. Built on flatpot (Ubuntu 26.04, SDL2 2.32 dev, bazel 9.2)
from main d5770be, and copied to `mercury:~/sahara/`: `sahara-gui`,
`sahara-emu`, `oasis.img` (Oasis m2 with the echo user program), `demo.trc`.

Verified:
- Oasis suite on flatpot: 20 passed, 0 failed.
- On mercury, headless: `./sahara-emu oasis.img --replay demo.trc` ends
  `HALT ...600d`.
- On mercury, the GUI under `SDL_VIDEODRIVER=offscreen` with a scripted
  keypress: the session trace replays through the printed `sahara-emu
  --replay` command (exit 2 MAXCYCLES, as documented for a closed session).
  `os/oasis/tests/replaycmp.py` finds it identical. Negative control: the same
  trace against `demo.trc` reports "REAL divergence", exit 1.

Run it (on mercury): `cd ~/sahara && ./sahara-gui oasis.img`.

## Phase 2 - Sahara on flatpot, view and control from mercury

Each step ends green on the existing gates: `emu-c/build.sh`, the Oasis
suite, and `run-gui-tests.sh`, unchanged.

1. **Core loop out of `sdl_main.c`.** Split pacing + feed + present-pump
   into a frontend-neutral `gui/live.c`, with SDL as one backend. This is a
   pure refactor: sahara-gui must behave byte-identically (the run-gui-tests
   `--script` legs and replay identity are the gate).
2. **Wire protocol `SVP/1`** (a software doc beside `rom/netboot/sbp.md`,
   not a devspec). One TCP connection. Server->client: `HELLO{w,h,stride}`,
   `FRAME{seq,codec,len,bytes}` on PRESENT, coalesced to the newest frame
   when the client is behind (frames are outside determinism, so dropping is
   legal). Client->server: `INPUT{kbd|mouse, word}`, carrying the exact
   words `hid_map`/`translate` produce today, and `CLOSE`. Codecs: `raw`,
   `lz4`, later `h264`.
3. **`sahara-serve`** = the live core + an SVP server backend. One client
   owns input; a second connection is refused, with no spectators (owner
   answer 2). It records a trace by default, exactly like sahara-gui, and
   prints the replay line on exit. Binds only the address it is given.
4. **`sahara-view`** = SDL2 window + SVP client, reusing `hid_map`/capture
   UX, `raw`/`lz4` first. Gate: a `sahara-view`-driven session on flatpot
   replays byte-identically; this is the new e2e leg, run over loopback in CI.
5. **LAN bring-up**: `sahara-serve` on flatpot bound to its tailnet IP on a
   port checked free (`ss -ltn` AND `tailscale serve status`: 8453/8454 were
   freed today, and 8450-8452 are serve's). Tailnet input is already accepted
   on flatpot, so there is no firewall change. mercury runs `sahara-view`.
   Measure: frames/s delivered, Mbit/s, input-to-photon, by eye.
6. **spark bridge (H.264)**: `sahara-serve --bridge spark` streams
   raw/LZ4 frames out to a bridge on spark (`h264_nvenc`, CBR, `-tune ull`).
   The bridge relays H.264 to `sahara-view --codec h264` (libavcodec decode)
   and relays INPUT back. Needs:
   - flatpot: libavcodec-dev to build sahara-view's decoder. That is an
     apt install as root, so a **deploy button**.
   - spark: one listener for the bridge (ufw is inactive there; it binds the
     tailnet/LAN address only). Running a new service on spark is Hila's
     call, so a **button**.
   - mercury: nothing new (libavcodec 62 and libva 2 runtimes present).
   Measure the same three numbers, on the LAN and from the 80 Mbit site.

## Out of scope

Guest-visible resize (owner answer 3 unanswered, default keep 640x480, the
view scales); multiple viewers; audio (Sahara has no audio device).

## Status 2026-09-23

- Steps 1-5 DONE (branch design-remote-frontend, 8fb6e27..7a67278):
  live session split; SVP/1; sahara-serve; sahara-view; tailnet
  bring-up. Acceptance from mercury over the tailnet: input-to-present
  p50 12.6 ms, p95 15.2 ms, max 17.6 ms, over 100 keys; the session
  replayed byte-identically (200 keyboard EVENTs). All gates green.
- Step 6 (spark H.264) NOT started, deliberately. See the handoff: for
  the Oasis console XRLE is a few hundred bytes per key, and H.264
  would add encode + decode + a hop, making text slower. It pays only
  for full-motion guests (the DOOM lane), which do not exist yet.
