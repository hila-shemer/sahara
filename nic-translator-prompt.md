# Work order: NIC translator — real host networking for sahara-gui live mode

Branch: `nic` (worktree of the main repo, full spec access). Read
`emu-common-prompt.md`, `emu-c-prompt.md`, and
`emu-c-gui-frontend-prompt.md` first; they govern. Read
`devspec/nic.md` IN FULL — it is the contract this phase implements —
and `devspec/trace.md` §4.3/§5. This closes the gap the frontend work
order explicitly deferred ("No NIC bridging, translator, or live NIC
EVENTs") and that emu-c SPEC-ISSUES 35 documents as the dead wire.

The design below was settled in advance and is **binding**. Do not
relitigate the resolved decisions; where you must invent a reading,
the inventions are already enumerated and each one gets a
SPEC-ISSUES.md entry before merge, per house protocol.

## Why this exists

nic.md defines the whole device — mailbox, translator decision tree,
virtual hosts 10.0.2.2/10.0.2.3, byte-exact test vectors — and the
determinism doctrine that shapes it: **anything that enters the
machine from the real network does so only as a recorded EVENT
through the same live-feed path keyboard input uses**
(`SeCpu_feed` → `apply_events` → device model → `SeTrace_event`).
A live session with networking must replay byte-identically headless
with no network access at all (nic.md §7.3, NIC-C-35). TX is pure
output, like PRESENT: doorbell frames never appear in the trace as
input. Wall-clock arrival maps to cycles by the front end's existing
stamping rule (trace.md §5.4; frontend work order rules 3/8) — the
NIC invents no new time machinery.

The front end already authors keyboard/mouse/resize events this way
and proves replay identity in run-gui-tests.sh. This work order makes
the NIC the fourth event author and gives the guest a real network.

## What already exists — do not rebuild it

- **The feed/replay seam.** `SeCpu_feed` (cpu.c) appends to the live
  queue; the shared `apply_events` applies at boundaries, recomputes
  drop decisions in the model, records what was accepted; `wfi_wait`
  wakes at exactly a feed event's cycle (NIC-C-36 is already the
  frozen wake rule — root SPEC-ISSUES 32/35, emu-c entry 36). The NIC
  plugs into this; it does not get its own path.
- **The NIC register surface.** dev.c implements the full register
  fault matrix (E1–E7), doorbell length validation, RX_LEN/RX_POP/MAC.
  Missing: the RX queue model (SPEC-ISSUES 35 / dev.h header comment)
  and any TX consumer.
- **The TX drop site.** dev.c `NIC_TX_DOORBELL` case: validates E5,
  then returns without capturing — the comment marks it as the
  deliberate translator gap (SPEC-ISSUES 35; emu-py labels the same
  boundary DECISIONS.md D8). This is where the translator attaches.
- **The replay-loader rejection.** main.c `validate_event`, case
  `SE_DEVIDX_NIC`: dies loudly on NIC EVENT records, by design, until
  the RX model exists. This work order removes that die — that is the
  one sanctioned behavior change to `sahara-emu`.
- **The carve-out precedent.** BUILD.bazel: `sdl_main.c` is the
  `allow_banned` shim excluded from the source audits; all logic
  lives in `:gui_core` under full rwc doctrine. Host sockets follow
  the identical pattern.
- **The test pattern.** run-gui-tests.sh: seam-driver record→replay
  byte-identity, `--script` + `SDL_VIDEODRIVER=dummy` scripted
  sessions, double-run cmp, replay via the exact printed command.
  NIC tests are new legs of this script, same idioms.
- **The GUI pump.** sdl_main.c's throttled loop, `pump_earliest`
  stamping, WFI-idle blocking with the housekeeping tick. The NIC
  rides the existing pump; no threads, ever.

## Binding decisions

1. **Milestone-1 protocol scope: the whole deterministic local plane,
   plus UDP outbound; TCP NAT deferred.** In scope, byte-exact per
   nic.md: classification §6.2 in full, ARP §6.3, DHCP §6.4, ICMP
   echo to the virtual hosts §6.8, RST generation §6.7.6, and the
   guest-initiated outbound paths UDP translation §6.5 and DNS
   forwarding §6.6 (64-flow table, connected sockets = the
   address-restricted NAT). Deferred with spec-sanctioned observables:
   - **TCP translation §6.7 → milestone 2.** An outbound SYN is
     answered RST per §6.7.6 — guest-visibly the §6.7.1
     "host connect fails" leaf, i.e. connection-refused, not a dead
     wire. SPEC-ISSUES entry (the successor to entry 35's pattern:
     partial closure, loudly documented).
   - **Outbound ICMP echo forwarding is never attempted.** §6.8
     explicitly permits silent drop when the host doesn't provide
     unprivileged ICMP; "never" is the deterministic reading of
     host-dependent. Virtual-host echo works. SPEC-ISSUES entry.
   Rationale: the local plane + UDP/DNS is everything the frozen test
   vectors (TV-1…TV-9, TV-S1) and NIC-C-21…30 can bite on, is where
   determinism is provable today, and already carries the project's
   stated storage-over-NIC future; TCP is the largest stateful chunk
   and deserves its own order on top of a proven RX path.

2. **It lives inside sahara-gui, split sans-IO.** No separate
   process, no IPC: emu-c-prompt.md makes the GUI the only component
   allowed to touch real time and host IO, and a daemon would add a
   second clock and a second failure domain for zero determinism
   gain. Three TUs in `emu-c/gui/`:
   - `nic.c/h` (in `:gui_core`, full doctrine, SDL-free, socket-free):
     the translator — classification, ARP/DHCP/ICMP/RST synthesis,
     the UDP flow table. **Sans-IO:** input is TX frame bytes +
     inbound datagrams; output is synthesized RX frames + host-op
     requests (send payload P to remote R on flow F) expressed as
     data through a small backend vtable. This is what the TV-vector
     unit tests target.
   - `nic_host.c` (carve-out): the real backend — nonblocking UDP
     sockets, one `connect()`ed socket per flow, resolv.conf's first
     nameserver for §6.6 (none → DNS drops, documented). Compiled
     like sdl_main.c: `allow_banned`, listed in `sahara-gui` srcs,
     excluded from AUDIT_SRCS.
   - `nic_fake.c` (in `:gui_core`, doctrine-clean): the test backend —
     echoes every forwarded datagram back verbatim from its remote
     endpoint at the next pump. No sockets anywhere in it.
   Guest-visible equivalence of fake and real backends given the same
   payloads is **by construction**: frame synthesis is the shared
   sans-IO core; backends only source payload bytes.

3. **Frame flow, TX side.** `SeDev` grows a TX hook:
   `void (*tx_doorbell)(void *ctx, uint32_t len); void *tx_ctx;` —
   NULL headless, which is byte-for-byte today's drop. dev.c's
   doorbell case calls it after E5 validation; the GUI's hook copies
   TX buffer bytes `[0, len)` from SeMem at `SE_PLAT_NIC_TXBUF`
   synchronously (safe: the guest cannot run until the store
   completes — nic.md §2.2's synchronous capture for free) and runs
   the translator. TX frames are never traced as input; their only
   trace footprint is the DEVW records the store path already emits.

4. **Frame flow, RX side — the model owns everything.** Implement
   nic.md §4 in dev.c (mirroring emu-py's D12-complete arrival path):
   64-slot frame store (1 exposed + 63 queued, fixed arrays, no
   allocation), `SeDev_inject_nic(SeDev*, SeMem*, const uint8_t*,
   uint16_t len)` returning admitted/discarded, exposure writing
   exactly `len` bytes to `SE_PLAT_NIC_RXBUF` via `SeMem_write`
   (device-internal writes produce no trace records — nic.md §7.2,
   trace.md §2.3), RX_POP exposing the queue head. RX_POP needs
   memory access: `SeDev` gains a `SeMem *mem` wired at setup by
   every front end, RWC_ASSERTed when the RX path runs. EXTINT
   already ORs `nic_rx_len` — untouched. **The translator never
   drops for capacity: the 64-frame cap and the no-record-on-overflow
   rule (nic.md §4.3) are recomputed by the model at the boundary**,
   exactly as input drop flags are. In `apply_events`, a NIC event
   the model discards on overflow emits NO EVENT record (unlike
   input's flagged record — nic.md §4.3 vs trace.md §4.1); under
   `--replay` an overflow is impossible from a genuine trace, so it
   dies as malformed.

5. **EVENT plumbing grows to frame size.** `SeEvRec.payload` goes
   32 → 1514 bytes inline; `len` widens to `uint16_t` (touches
   `SeCpu_feed`'s signature and main.c's loader). Allocation-free and
   uniform; the cost is replay-array memory (~1.5 KB/event), which is
   fine at realistic event counts. Escape hatch if it measurably
   hurts: payload pointer into a loader/feed-owned arena — the feed
   remains the mechanism of record. main.c `validate_event` accepts
   `SE_DEVIDX_NIC` with inner length in [60, 1514] (anything else is
   a malformed trace — the model only ever admits padded legal
   frames) and drops the die; SPEC-ISSUES 35 gets its closing
   amendment.

6. **Cycle stamping — two cases, both existing rules.** Locally
   synthesized replies (ARP, DHCP, echo, RST) are fed from within the
   TX hook with `earliest = doorbell cycle + 1`: applied at the first
   boundary after the store retires, satisfying causality (nic.md
   §7.1 rule 3, NIC-C-32) and matching the reference "+1" policy
   (rule 5) under `--script`'s fake clock, where the whole session is
   deterministic. Socket return traffic is fed at the pump with the
   existing `pump_earliest` stamp — including the WFI-idle
   `max(target, cycle+1)` rule, so NIC arrivals wake WFI at exactly
   their cycle (NIC-C-36) with zero new code. Guest images must poll
   RX_LEN or WFI, never assume +1 (nic.md §7.1 rule 5).

7. **CLI: `--nic host|off|fake`, mode-dependent default.** Live
   default `host` (bridging is the point of the phase); `off` is
   exactly today's dead wire (hook NULL); `fake` is test-only. Under
   `--script` the default is `off` and `--nic host` is **rejected** —
   the scripted gate must be socket-free and deterministic by
   construction. `sahara-emu` gains no flags: the translator and
   backends never link into `:core` or the headless binary, so
   nic.md §7.3's replay isolation is structural — the existing
   `audit_banned_syms` on `sahara-emu` doubles as the NIC-C-35
   instrumentation (no socket symbols in the headless binary).

8. **Security posture (document in gui/nic-notes.md).** The
   translator originates only: UDP datagrams to endpoints the guest
   names (any host/port the host stack can reach), DNS queries to the
   host's configured resolver, and nothing else — no listening
   sockets, no port forwarding, no inbound-initiated anything
   (nic.md §6.9.1), no TCP in milestone 1, no raw sockets, no ICMP
   sockets. A hostile guest can therefore send UDP anywhere the
   host user can — the authority of any program the developer runs
   locally, which is the trust model of a dev tool whose guest
   images are hand-assembled by the owner. `--nic off` exists for
   running untrusted images. Owner ruling (2026-08-11): images are
   trusted by default and hardening is deferred deliberately —
   "security for now is a keyword for never." Do not add sandboxing,
   allow-lists, or confirmation prompts; do not let a reviewer talk
   you into them. State all of this explicitly in the notes file,
   including what changes when TCP NAT lands.

9. **Determinism proof — fake first, sockets never in CI.**
   The gates extend run-gui-tests.sh's exact idioms:
   - TV-vector unit tests against the sans-IO core (byte-exact
     TV-1→TV-2, TV-3→TV-4, TV-5→TV-6, NAK TV-7, TV-8→TV-9,
     TV-10→TV-11; the NIC-C-28 drop quintet; NIC-C-29 trailing-byte
     equivalence; NIC-C-27 constants asserted over every reply).
   - RX-model unit tests in test_dev.c (FIFO order, 64-cap overflow
     discard, expose-on-pop, tail-bytes-unchanged NIC-C-14, EXTINT
     iff RX_LEN != 0).
   - A `nic` seam-driver scenario: NIC frames through `SeCpu_feed`
     at fabricated boundaries (including during WFI idle and
     same-cycle with keyboard events), record → `sahara-emu --replay`
     → post-META byte identity. This is also the proof the loader
     now accepts NIC EVENTs.
   - The end-to-end scripted-session gate: `sahara-gui --nic fake
     --script` over `gui/t_nic.s` (DHCP handshake per TV-S1, ARP,
     virtual-host ping, one UDP echo flow through the fake backend;
     HALT 600d), run twice → whole-file cmp; replay via the exact
     printed command → post-META cmp.
   Real sockets are exercised only by the manual smoke checklist.

10. **Recording, pacing, WFI: unchanged.** Mandatory session
    recording, level-0 default, the printed replay command, the pump,
    the slew rule — all exactly as the frontend work order fixed
    them. The NIC adds event authors, not time policy. Socket polling
    is one nonblocking sweep per pump tick; during WFI idle the
    existing housekeeping tick (250 ms) bounds NIC arrival latency —
    acceptable, and noted in nic-notes.md.

## Deliverables

1. Core seam patch: `SeDev` TX hook + `mem` pointer, the nic.md §4
   RX model in dev.c, `SeEvRec`/`SeCpu_feed` payload growth, the
   `apply_events` NIC case with overflow-discard semantics, main.c
   NIC EVENT acceptance. All inert headless except the sanctioned
   loader change (decision 5) — hook NULL, RX model reachable only
   via injection.
2. `emu-c/gui/nic.c`, `nic.h`, `nic_fake.c` (in `:gui_core`, full
   doctrine), `nic_host.c` (carve-out), sdl_main.c wiring
   (`--nic` flag, TX hook registration, pump socket sweep, fake/host
   backend selection).
3. `BUILD.bazel`: `nic_host.c` into `sahara-gui` srcs + AUDIT_SRCS
   exclusion; `nic.c`/`nic_fake.c` into `:gui_core`; TV-vector tests
   into `test_gui` (or a sibling `test_nic` if it outgrows it —
   rwc_test, short tier); RX-model cases into `test_dev`.
4. run-gui-tests.sh: the `nic` seam scenario and the `--nic fake`
   scripted-session gate, both under the existing cmp helpers.
5. `emu-c/gui/t_nic.s` — hand-assembled guest test image (asm.py; no
   Oasis, no toolchain additions), polling RX_LEN / WFI per nic.md
   §7.1 rule 5, HALT 600d on success.
6. `emu-c/gui/nic-notes.md`: the security posture (decision 8), the
   fake-backend contract, the WFI-idle latency note, a "known future
   consumers" line — the planned netboot ROM will fetch boot images
   through this plane via an image-server service on a virtual host,
   so keep the local-plane service dispatch extensible and note that
   RX-recorded EVENT traces already make a netboot session replayable
   offline — and the
   milestone-2 recipe (TCP translation §6.7: connection table,
   window-respecting segmentation, the CONNECTING/RST leaves already
   built here; outbound ICMP if ever).
7. SPEC-ISSUES.md entries: 35's closing amendment (RX model + loader
   acceptance landed; translator scope now decision 1); TCP-deferred
   RST reading; ICMP-never-forwarded reading; `--nic` flag and
   defaults (the frozen headless CLI is untouched); the fake-backend
   test reading. Note the emu-py cross-check status: its D12 arrival
   path should replay NIC sessions — if a cross-diff shows drift,
   record it, do not touch emu-py.

## Definition of done

All from the worktree root unless noted; every gate green:

- `emu-c/build.sh` end to end (bazel build+test picks up the new
  targets; REPLAY=1 conformance leg stays green).
- `./run_tests.sh` (repo root; emu-py leg saw no fallout).
- `emu-c/run-gui-tests.sh` green, including the two new NIC legs,
  all headless, no real window, **no real sockets** (verify: the
  script runs with the network namespace unshared if available —
  `unshare -rn emu-c/run-gui-tests.sh` must pass identically; if
  unshare is unavailable in the environment, note it and rely on
  `--nic host` being rejected under `--script`).
- **Headless byte-identity** — the frozen binary's behavior on the
  suite is unchanged, verified, not assumed (same recipe as the
  frontend order):

      git worktree add /tmp/sahara-base "$(git merge-base main HEAD)"
      (cd /tmp/sahara-base/emu-c && bazel build //:sahara-emu)
      REPLAY=1 EMU=/tmp/sahara-base/emu-c/bazel-bin/sahara-emu \
          tests/run-tests.sh
      cp -r tests/out /tmp/sahara-base-out
      REPLAY=1 EMU="$PWD/emu-c/bazel-bin/sahara-emu" tests/run-tests.sh
      for f in tests/out/*.a.trc; do
          cmp "$f" "/tmp/sahara-base-out/$(basename "$f")" \
              || { echo "HEADLESS DRIFT: $f"; exit 1; }
      done

  Any DRIFT line is stop-the-line. (The suite contains no NIC EVENT
  traces, so the loader change is invisible here — by design.)
- The scripted NIC session's trace replays through the **unmodified**
  `sahara-emu --replay` invocation printed by the GUI, byte-identical
  post-META; two identical `--script --nic fake` invocations produce
  byte-identical `.trc` files in their entirety.
- `bazel test //:audit_banned_syms` (sahara-emu) green — the
  structural NIC-C-35 check: no socket symbols in the headless
  binary.
- SPEC-ISSUES entries committed; dev.h/dev.c/cpu.h comments that
  currently document the NIC gap updated to the new reality.

## Scope boundaries

- No edits under `tests/` or `trace-q/` — toolchain-owned. The NIC
  conformance clauses that need shared-suite coverage (NIC-C-21…30
  as suite tests) are toolchain work; this order proves them
  emu-c-side in test_gui/test_dev and run-gui-tests.sh only. If a
  suite bug blocks you, record it in SPEC-ISSUES.md and stop.
- No `sahara-emu` CLI or output changes; the only headless behavior
  change is `--replay` accepting NIC EVENT records (decision 5).
- No emu-py changes of any kind (cross-diff findings go to
  SPEC-ISSUES).
- No Oasis or `os/` changes; the guest test image is hand-assembled
  in `emu-c/gui/`.
- No TCP translation, no outbound ICMP forwarding, no port
  forwarding, no inbound listen — milestone 2 or never (nic.md
  §6.9).
- No threads, no async runtimes, no second process: one pump,
  nonblocking sockets, that's all.
- No new trace record types, levels, or META keys.

## Manual smoke checklist (with a real window and real sockets, not CI)

- `sahara-gui gui/out/t_nic.img` (default `--nic host`): the local
  plane behaves identically to the fake run — DHCP handshake
  completes, ping 10.0.2.2 answered, HALT 600d.
- A DNS smoke image (or t_nic.s variant) sends one A query for a
  real name to 10.0.2.3:53: RX_LEN goes nonzero with a plausible
  answer; on a machine with no resolv.conf nameserver, it times out
  quietly (documented drop).
- One UDP flow to a real host-side endpoint (e.g. `socat
  UDP-LISTEN:9999,fork EXEC:cat` on loopback): guest sends, echo
  comes back, frame exposed.
- `--nic off`: dead wire exactly as before this phase.
- Close the window mid-session with NIC traffic in the trace; run
  the printed replay command **with networking disabled** (`unshare
  -rn`, or airplane mode): byte-identical post-META, HALT/MAXCYCLES
  as printed — the doctrine's headline demo.
- Overflow sanity: a guest that never pops while the fake backend
  floods stays at 64 held frames and the trace holds exactly 64 NIC
  EVENTs (NIC-C-18).

## Risks

- **The SeEvRec growth touches every feeder.** main.c, seam driver,
  sdl_main, cpu.c — a missed `uint8_t len` truncates frames at 255
  bytes and the DHCP vectors (342 bytes) will catch it immediately;
  run the TV tests before anything else works.
- **Overflow's no-record rule is the one asymmetry** against
  keyboard's flagged-record drop. If apply_events records a
  discarded NIC event, replay double-applies and the seam test
  catches it — keep the two semantics side by side in one comment.
- **Socket readiness vs pump cadence.** A burst of return traffic
  arriving between ticks lands as multiple frames at one boundary —
  legal (nic.md §7.1 rule 2 equal-cycle ordering), but keep the
  sweep-order deterministic (flow-table order, not fd order).
- **resolv.conf variance** makes DNS smoke host-dependent — that is
  why it is manual-only; never let a DNS test near CI.
- **Doctrine drift in the carve-out**: nic_host.c will tempt logic
  in (parsing, flow lookup). Everything with a decision in it
  belongs in nic.c where the tests are; the carve-out only moves
  bytes between fds and the backend interface.
