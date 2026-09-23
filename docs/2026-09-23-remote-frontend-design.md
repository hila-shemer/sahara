# Remote frontend: Sahara on flatpot, pixels on mercury and the phone

2026-09-23. Design only, nothing built. Frozen once written (see the
workflow note on specs); what gets built goes in commit messages and code.

Hila's ask: "I want it running on flatpot eventually, we need to separate the
'VM' from the 'frontend'? or add a new output? recall Spark can encode video
very fast :)"

## What the spec already allows

Nothing below changes ISA-SPEC, PLATFORM-SPEC or any devspec.

- **PRESENT is pure output, outside the deterministic boundary**
  (devspec/display.md §5, §7). A frame is a deterministic function of the
  trace, the trace has no frame records, and "host-side rendering (vsync,
  frame dropping, window decoration) is outside the deterministic boundary".
  A new frame sink is therefore a host-side change only. Frames may be
  dropped, scaled or encoded lossily without touching replay.
- **Input already enters only as fed EVENTs** (`SeCpu_feed`, emu-c/cpu.h:120).
  The GUI's capture rules (frontend-notes.md, "Capture UX") produce page-7
  usages and packed mouse masks. A remote client that sends the same words
  lands them on the same path, so a remote session records and replays
  exactly like an SDL one.
- **The GUI is already a thin loop around the core.** `sdl_main.c` does three
  things: pace cycles against wall time (`--hz`, `live_yield` WFI idling),
  feed EVENTs, and on `present_pending` copy the frame snapshot
  (`SeGuiBlit_frame` → `staging`, 4·W·H bytes) into an SDL texture. That
  last step is the entire display output.

So the split Hila asked about is natural: **`sahara-serve`** = core + recorder
+ pacing + a network frontend in place of SDL. It emits frames on PRESENT
and takes input words in. It is the same binary shape as `sahara-gui`, with
the SDL calls swapped for a socket.

## Numbers

Measured 2026-09-23:

| what | value |
|---|---|
| flatpot → spark RTT | 0.14-1.0 ms (10GbE, via LAN) |
| spark NVENC, h264 low-latency (`-preset p1 -tune ull -zerolatency 1`, CBR 8M) | 120 frames of 640x480@60 in 0.60 s; 1920x1080@60 in 0.58 s, including process start and test-source generation. So ≥200 fps, i.e. an upper bound of ~5 ms/frame, not a per-frame latency |
| spark output bitrate at that setting | ~7.3 Mbit/s |
| spark GPU utilization right after | 3%; encode sessions 0 before and after (vLLM unaffected at this scale) |
| spark encoders available | `h264_nvenc`, `hevc_nvenc`, `av1_nvenc` in ffmpeg; no `nvh264enc` in its GStreamer |
| flatpot → mercury over tailnet (on the home LAN) | TCP rtt ~2-11 ms (ss, earlier today) |
| SPICE with lossy JPEG, Omarchy guest (a different workload, for scale) | 0-30 Mbit/s |

Computed, not measured:

| what | value |
|---|---|
| raw frame, Sahara default 640x480 XRGB | 1.23 MB; at 60 fps 74 MB/s = 590 Mbit/s |
| same over 10GbE | ~1 ms per frame on the wire |
| raw 1920x1080 (a future resizable display) | 8.3 MB/frame; 60 fps = 4 Gbit/s, 40% of the link |
| software x264 ultrafast, 640x480@60, on flatpot | estimate well under one core. **Not measured**: flatpot has no ffmpeg installed |

Frames flow only on PRESENT, so a text console (Oasis) that presents on
keystrokes costs close to nothing. The 590 Mbit/s figure is the ceiling for
a guest presenting every vsync.

## Options

All three share `sahara-serve` on flatpot. They differ in where encoding
happens and what the client is.

### A. Frame tap + spark NVENC + WebRTC (browser client)

flatpot `sahara-serve` opens one TCP connection **out** to spark. It sends
raw frames (optionally LZ4, which is very effective on console/UI frames)
and receives input words back on the same socket. On spark a small bridge
(ffmpeg `h264_nvenc`, or a GStreamer pipeline) encodes and publishes WebRTC.
It could use a WebRTC server such as mediamtx, or GStreamer `webrtcbin` built
with an ffmpeg encoder element. The input datachannel carries keyboard/mouse
back to the bridge, and from there down the same socket to flatpot, into
`SeCpu_feed`.

- Clients: any browser: mercury, the phone, anything on the tailnet. No install.
- Latency, estimated: copy <1 ms + wire ~1 ms + NVENC ≤5 ms + tailnet 2-11 ms
  on LAN (unmeasured from the 80 Mbit site) + browser decode/jitter buffer
  ~10-30 ms + display ≤16 ms. Roughly **30-60 ms on the LAN**. WebRTC's
  jitter buffer is the biggest term; low-latency settings trim it.
- Bandwidth to the client: 2-8 Mbit/s CBR, set at the bridge. It fits 80 Mbit/s
  many times over.
- Scaling: the bridge can upscale 640x480 to the client's size before encode
  (cosmetic, outside determinism), so no guest resize work is needed for
  "fullscreen on the phone".
- Firewall: flatpot→spark is outbound (flatpot output is policy accept for
  hila), so flatpot needs no new input rule. spark gets one listener, and the
  WebRTC port is exposed on the tailnet only. Both are system changes, so both
  are deploy buttons.

### B. Frame tap + spark NVENC + Moonlight (Sunshine on spark)

Same tap to spark. On spark, a headless Wayland compositor runs a tiny
"sahara-view" that paints the received frames and forwards its input to
flatpot. Sunshine captures that compositor with NVENC and serves Moonlight.

- Clients: Moonlight (already on mercury as a snap; Android and iOS apps
  exist). It has the most polished low-latency client, and gamepads work.
- Latency, estimated: Moonlight's pipeline is ~10-20 ms end to end on a LAN,
  plus one extra paint/capture hop on spark (~1 frame). Roughly **20-40 ms**.
- Cost: the most moving parts. Sunshine wants a desktop to capture, so we host
  a fake one to feed it. Input goes client → Sunshine → compositor →
  sahara-view → flatpot, three hops before it reaches `SeCpu_feed`.
- It works, but it is a desktop-streaming stack wrapped around a program that
  already has frames in hand.

### C. No spark: serve encodes, or the client decodes raw

`sahara-serve` speaks RFB (VNC) itself, e.g. via libvncserver, or ships
LZ4 frames to a native `sahara-view` (SDL2, reusing `gui/` code) on mercury.

- Latency: lowest on a LAN (~5-20 ms), with no encode hop.
- Bandwidth: fine for a console; poor for full-motion 640x480@60 at 80 Mbit/s
  (raw 590 Mbit/s, LZ4 helps only on flat frames). No phone story unless a VNC
  app is acceptable.
- Needs nothing new on spark or in the firewall beyond one tailnet port.

## Recommendation

**A, built in two steps, with C's viewer as step 1's test client.**

1. **`sahara-serve` + the frame/input socket protocol.** This is the actual
   "separate the VM from the frontend" work, and every option needs it.
   Deliverable: `sahara-serve IMAGE --out tcp:HOST:PORT` plus a native
   `sahara-view` that connects to it on the LAN. Gates: the existing
   run-gui-tests legs pass unchanged, and a `sahara-view`-driven session
   replays byte-identically through `sahara-emu --replay`, exactly the
   contract sahara-gui already has. Script mode (`--script`) keeps working
   server-side.
2. **spark bridge.** Consume the same socket, encode with `h264_nvenc`, and
   serve WebRTC with an input datachannel. That covers mercury and the phone
   with nothing installed.

Why A over B: frames are already in hand, so feeding them straight to the
encoder is one hop. B builds a desktop so that Sunshine can capture it. B stays
the fallback if browser latency disappoints. Swapping the bridge from WebRTC to
Sunshine does not touch step 1.

Why not C alone: no phone client, and full-motion content (the DOOM lane)
needs a real codec at 80 Mbit/s. As step 1's test client it costs nothing.

## Open questions for Hila

1. Is the phone a must-have? If yes, A (browser); if Moonlight is acceptable, B.
2. Should `sahara-serve` accept several viewers at once (read-only
   spectators), or exactly one client that owns input?
3. Resizable display (the v2 recipe in frontend-notes.md) now, or keep
   640x480 and let the bridge scale? Scaling is free and outside determinism;
   resize is guest-visible work.

## Not measured

End-to-end latency of any option; WebRTC jitter-buffer cost; NVENC
per-frame latency, as opposed to throughput; flatpot CPU encode; anything
from the 80 Mbit site.

## Owner answers (2026-09-23, same day, before any build)

Hila, relayed verbatim by the Manager: "phone? no, laptop! mercury, the laptop.
sahara runs on mercury or flatpot, and when on flatpot (phase 2 is running on
flatpot) I want remote view&control from mercury".

1. **Client = mercury, native.** No phone, so browser/WebRTC is not forced.
2. **One viewer, which owns input** (view and control). No spectators.
3. **Resize: unanswered.** Default is to keep 640x480; the view scales on the
   client (cosmetic, outside determinism).

**Re-pick: A-native.** The spark NVENC bridge as in A, but with a native
`sahara-view` on mercury instead of a browser: SDL2 (reusing `gui/`) plus
libavcodec H.264 decode (VA-API on mercury is optional). Input goes back over
the view's own connection.

- Why not WebRTC any more: its jitter buffer was the largest latency term
  (~10-30 ms) and existed only to reach a browser. A native decoder on a
  bounded TCP/UDP stream drops that term, which puts the estimate at roughly
  15-30 ms on the LAN.
- Why not B (Moonlight): still a fake desktop for Sunshine to capture, and
  input takes three hops. A native view is the same size of work with fewer
  hops.
- C's raw/LZ4 path stays inside `sahara-view` as a codec choice (`--codec raw`):
  zero encode, used for the phase-2 bring-up on the LAN and whenever spark is
  unavailable. H.264 via spark is the codec for full motion and the 80 Mbit site.

Phases:

- **Phase 1**: Sahara runs locally on mercury: the existing `sahara-gui`,
  built on flatpot (same Ubuntu 26.04 / SDL2 ABI) and copied over. No code
  change.
- **Phase 2**: `sahara-serve` on flatpot + `sahara-view` on mercury (raw
  first), then the spark NVENC bridge (H.264). Plan:
  `docs/2026-09-23-remote-frontend-plan.md`.
