# Next session: Sahara remote frontend (2026-09-23)

Branch `design-remote-frontend` (worktree ~/proj/sahara.worktrees/design-remote-frontend),
pushed to the fork, NOT on main. Plan + status: docs/2026-09-23-remote-frontend-plan.md.

Done: phase 1 (sahara-gui on mercury) and phase 2 steps 1-5. sahara-serve on flatpot,
sahara-view on mercury, SVP/1 with RAW/XRLE. Acceptance from mercury over the tailnet:
p50 12.6 ms input-to-present. Gates: run-gui-tests all green (new serve/view legs +
merge-base identity), bazel //... 10/10, Oasis 20/20.

Running now: user unit `sahara-serve` on flatpot (CPUQuota 100%, CPUWeight 20,
MemoryMax 2G), Oasis on 100.123.236.10:8453, traces in ~/.cache/sahara-sessions (tmpfs,
~60 KiB/s idle). Binaries: ~/.local/lib/sahara (-c opt). Stop:
`systemctl --user stop sahara-serve`. Start again with the systemd-run line in the result
file.

Hila on mercury: `~/sahara/sahara-view flatpot.tail0b59ad.ts.net:8453`. Local phase 1:
`cd ~/sahara && ./sahara-gui oasis.img`.

Open DECISION: step 6, H.264 via spark NVENC. It is deliberately not started. For the
text console it would be slower (encode + decode + a hop) with no bandwidth need; it
pays only for full-motion guests. When it is wanted: the libavcodec-dev button on flatpot,
and a spark bridge (Python + ffmpeg h264_nvenc, bridging SVP), which is a button for the
persistent service.

Traps learned: bazel-bin follows the LAST config built. The GUI gate rebuilds fastbuild,
so re-run `bazel build -c opt` before copying binaries anywhere (check the size: ~110 KB
opt vs ~165 KB fastbuild). The shared-loop pacing fixes are live-only; keep them away from
--script.
