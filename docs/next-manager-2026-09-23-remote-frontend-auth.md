# Next session: remote frontend hardened + auth (2026-09-23, sahara-RosyRobin)

Supersedes the "Running now" part of next-manager-2026-09-23-remote-frontend.md.

## State

Branch design-remote-frontend (this worktree):
- Local tip is **f63a0c5**. The fork has **7f31314**, the gated hardening.
- f63a0c5 is a clean fast-forward of main d5770be. main is NOT merged.

Commits on the branch:
- e3e97bb..7f31314, hardening:
  - input budget per poll plus a token bucket (burst 256, then 1000 msg/s)
  - keepalive/TCP_USER_TIMEOUT reaping of dead viewers, ~20 s (from settings, not measured end to end)
  - viewer retries BUSY/refused for 60 s, with a 5 s HELLO deadline
  - test script cleanup via an EXIT trap, and port-0 binds
- 7f31314..f63a0c5, SVP/2 (Hila decision 1 = (c)):
  - The server sends a 32-byte getrandom nonce. The viewer answers with HMAC-SHA256(token, "SVP/2 AUTH"||nonce), and
    the server checks it with a constant-time compare.
  - One attempt per connection and a 5 s auth deadline. Unauthenticated peers wait in a separate 4-slot door, and a
    viewer retries when the door is full.
  - The token lives in a 0600 file, `~/.config/sahara/serve-token` (or `--token-file`). The viewer can also take it
    from env `SAHARA_VIEW_TOKEN`. It is never on argv. Both ends refuse a file with a bad mode.
  - CLOSE detaches only the viewer, and the session keeps running. `--end-session` is removed. SIGINT/SIGTERM end the
    session, now even while the guest is busy.

Gates on f63a0c5, all run niced:
- build.sh 34/34
- bazel 10/10
- Oasis 20/20
- run-gui-tests all green, including the wrong-token negative control (0 EVENTs, no FRAME), reattach byte-identity,
  the flood and the busy-guest SIGTERM
- headless identity vs d5770be: 34 identical, checked at 7f31314

## Blocked on Hila

1. **Push f63a0c5 and merge main.** The auto-mode classifier refused both the fork push of f63a0c5 and the ff-merge
   ("Merge Without Review"). The commands:
   ```
   cd ~/proj/sahara
   GIT_SSH_COMMAND="ssh -i ~/.ssh/id_claude_agent -o IdentitiesOnly=yes" git push origin f63a0c5:refs/heads/design-remote-frontend
   git merge --ff-only f63a0c5 && GIT_SSH_COMMAND="ssh -i ~/.ssh/id_claude_agent -o IdentitiesOnly=yes" git push origin main
   ```
2. **Recording decision, A or B.** The spec does not define two modes today:
   - PLATFORM-SPEC §8 has one rule, that every interactive session records.
   - The non-recording mode is SPEC-ISSUES 44, an `--untethered` flag.
   - Choices: (A) amend §8 to define a recording VM and a non-recording VM (recommended), or (B) a code-default flip
     in sahara-serve.
   - Measured on loopback, Oasis, one pinned CPU, recording vs untethered:
     - CPU: +0.07 percentage points idle, about +4% under 20 keys/s (inside run-to-run noise)
     - input-to-present p50: 12.6 vs 11.8 ms (+0.8 ms)
     - trace growth: 61.5 KB/s idle (5.3 GB/day in RAM) and 783 KB/s while typing
   - So the cost is the trace volume, not CPU or latency.
3. **Deploy the new binaries.** This is a button, and the deploy-propose HOLD from the Manager applies. The live unit
   still runs the old SVP/1 build from ~/.local/lib/sahara, and a new sahara-view cannot talk to it. Steps:
   - Create the token on flatpot:
     `umask 077; mkdir -p ~/.config/sahara && head -c 32 /dev/urandom | base64 > ~/.config/sahara/serve-token`
   - Copy it to mercury (0600).
   - Copy the -c opt sahara-serve/sahara-emu into ~/.local/lib/sahara, and sahara-view to mercury:~/sahara/.
   - Restart the unit. Add `--untethered` if Hila picks non-recording for the live VM.
   - `bazel-bin` currently holds -c opt.

## Next milestone after landing

Oasis user-mode graphics:
- `fb_blit` and `input_read` syscalls, and a mouse ring in place of the discard in kbd.s. These are OS-owned syscalls,
  so no SABI sign-off is needed.
- An asm paint demo.
- A full-frame mode that doubles as the step-6 (40 Mbit/s) probe.

Full survey is in the result file:
~/.claude/claude-control/results/20260923-032315-sahara-RosyRobin.md.
