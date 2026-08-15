# Work order: netboot ROM — the network IS the storage layer

Branch: `netboot` (worktree of the main repo, full spec access). Read
`emu-common-prompt.md`, `emu-c-prompt.md`,
`emu-c-gui-frontend-prompt.md`, and `nic-translator-prompt.md` first;
they govern. Read `devspec/nic.md` §6/§7 (the local plane and the
determinism contract), `devspec/boot.md` IN FULL (device table, reset
hand-off — the ROM is a conforming guest of it), `devspec/timer.md`
§1–§4 (COUNT), `TOOLING-SPEC.md` §1 (SAHIMG01 — the ROM is its first
in-guest consumer) and §4 (the assembler the ROM is written in), and
`os/abi/sabi-v0.md` §4 (memory conventions the ROM must not violate).
`emu-c/gui/nic-notes.md` names this work order as the known future
consumer of the local plane — this is that order.

The design below was settled in advance and is **binding**. Do not
relitigate the resolved decisions; where you must invent a reading,
the inventions are already enumerated and each one gets a
SPEC-ISSUES.md entry before merge, per house protocol.

## Why this exists

The owner's vision, verbatim scope: **the network is the storage
layer.** `sahara-gui` run with no image argument boots an embedded
bootloader ROM which fetches a boot image over the NIC and runs it.
There is no disk device and none is planned; the platform's
no-storage-peripheral stance is deliberate.

Determinism rides for free. Network RX enters the guest ONLY as
recorded EVENT records through `SeCpu_feed` (nic.md §7.1–§7.3; the
translator work order built the whole path and proved it in CI). So a
netboot session's trace *contains the downloaded image* — every DATA
block is an RX EVENT — and the session replays byte-identically as
`sahara-emu <rom.img> --replay session.trc` on a machine with no
network and no image server. The boot image literally lives in the
trace. Nothing in this order adds time machinery, trace machinery, or
core seams: the ROM is a guest program, the image server is one more
local-plane responder beside DHCP, and the only host-side novelty is
two `sahara-gui` flags.

## What already exists — do not rebuild it

- **The whole NIC path.** dev.c's RX model + TX hook, gui/nic.c's
  sans-IO translator with the local plane (classification §6.2, DHCP,
  ARP, virtual hosts 10.0.2.2/.3), synthesized replies fed at doorbell
  cycle + 1, `--nic host|off|fake`, the fake backend, the loader
  accepting NIC EVENTs. The image server is a new leaf in `nic_udp`'s
  dispatch (nic.c ~line 440) — nic-notes.md explicitly reserved this
  extension point. No dev.c, cpu.c, trace.c, or main.c changes at all.
- **The service pattern.** `nic_dhcp` is the template: parse the
  datagram, synthesize the byte-exact reply into `n->scratch`, emit
  via `nic_ip_emit` → deliver → `SeCpu_feed`. The image server is the
  same shape with a file blob instead of constants. Local-plane
  services consume no flow slots and never touch a backend — which is
  exactly why the whole netboot path runs under `--nic fake` in CI.
- **The device-table scan idiom.** os/oasis/kernel/boot.s
  `boot_dev_loop`: walk by `device_count`, first-record-of-type wins,
  the unconditional +64 IS the unknown-type skip rule, u128 fields as
  two u64 loads with a loud high-half check. The ROM's scan is a
  reduction of that loop — cite it in a comment, don't diverge from
  its idioms.
- **The assembler and image format.** asm/asm.py emits `.img` + `.sym`
  (TOOLING-SPEC §1/§4). The ROM is one hand-assembled source like
  gui/t_nic.s, only bigger.
- **The timer.** devspec/timer.md type-5 device: COUNT (offset 0x00)
  is a free-running 64-bit read of the cycle counter. That is the
  ROM's entire timeout mechanism — no PERIOD, no interrupts, no WFI.
- **The test pattern.** emu-c/run-gui-tests.sh: `--script` +
  `SDL_VIDEODRIVER=dummy`, PASS_LINE `HALT r0=...600d`, double-run
  whole-file cmp, replay via the exact printed command, cmp_post_meta,
  the whole script green under `unshare -rn`. Netboot legs are new
  stanzas of this script, same idioms.

## Binding decisions

1. **The fetch protocol: SBP/1 ("Sahara Boot Protocol"), stop-and-wait
   UDP blocks from the gateway, 10.0.2.2:69.** Full normative text
   (packet layouts, byte-exact test vectors in the nic.md §9 style)
   goes in `rom/netboot/sbp.md`; the shape is fixed here:
   - Server endpoint 10.0.2.2:69/udp — the gateway serves boot, the
     classic BOOTP/TFTP shape, and it reuses an existing virtual host:
     no new neighbor, no ARP change (the proxy already answers the
     subnet). Client endpoint 10.0.2.15:45063 (0xB007), fixed — a
     deterministic constant, not an ephemeral pick.
   - Every packet: u32 magic `"SBP1"` (bytes 53 42 50 31), u32 opcode,
     little-endian like everything guest-side. Opcodes: 1 REQ
     {max_block u32 = 1024}, 2 DATA {block u32 (1-based), then the
     bytes}, 3 ACK {block u32}, 4 ERR {code u32}. REQ and ACK are both
     exactly 12 payload bytes — deliberately, so the ROM's two TX
     frames have identical fixed-size IP headers and the IP checksum
     is an assemble-time constant. The ROM computes no checksums at
     runtime (guest UDP checksum 0 is legal, nic.md §6.2 step 5).
   - **Single-file, no name.** REQ requests "the image"; the server
     serves the one file `--serve-image` named. Request-by-name buys
     nothing today (one flag, one file, one client) and costs string
     handling in ROM assembly forever — the ROM's bytes are frozen by
     the trace anchor, so speculative protocol surface is pure risk.
     `max_block` in REQ is the one forward-compatibility hook: a
     future server may serve smaller blocks, never larger.
   - Block size 1024. DATA payload ≤ 1024 + 12 header = 1036 ≤ 1472
     (SE_NIC_UDP_MAX), comfortably one frame; power of two for the
     ROM's shift arithmetic; ~1k EVENTs per MB of image is fine.
   - **Stop-and-wait, client-driven, stateless server.** REQ elicits
     DATA(1); ACK(n) elicits DATA(n+1); DATA(n) is a pure function of
     (blob, n), so duplicate REQ/ACK re-elicits identical bytes. A
     DATA payload shorter than 1024 (0 included, for exact multiples)
     is the final block. The server keeps zero session state.
   - **Retransmit by timer COUNT.** The ROM records COUNT at each
     send, polls RX_LEN and COUNT; after TIMEOUT_CYCLES (`.equ`,
     8_000_000) with no reply it re-sends the last REQ/ACK; after
     RETRY_MAX (`.equ`, 5) attempts it fails terminally. On the
     lossless local plane the timeout is a liveness backstop only
     (it fires when there is no translator at all — `--nic off`);
     say so in a comment so nobody "fixes" the unreachable dup-DATA
     paths into complexity.
   - **Terminal failure is loud, never a hang:** decision 5's error
     discipline. ERR from the server (code 1 = no image configured)
     is terminal immediately, no retries.

2. **The server is a sans-IO local-plane service — entirely inside
   gui/nic.c, backend-independent.** `SeNic` grows
   `SeNic_serve_image(SeNic *n, const uint8_t *blob, uint32_t len,
   bool configured)`; the classification tree grows one leaf in
   `nic_udp`, before the 10.0.2.0/24 drop: dst 10.0.2.2:69 → `nic_sbp`.
   The blob is read once at startup by sdl_main.c (the carve-out
   already owns file IO) and handed in as bytes; nic.c stays
   socket-free, file-free, allocation-free, full rwc doctrine, and the
   service therefore behaves byte-identically under `--nic fake` and
   `--nic host` **by construction** — backends never see SBP traffic
   at all, exactly as they never see DHCP. This is what lets CI cover
   the entire netboot path with zero real IO. When no `--serve-image`
   was given the service still exists and answers ERR 1 (loud, per
   house policy — a silent drop would present as a mystery timeout).
   This changes the guest-visible classification of one (host, port)
   pair that previously dropped → SPEC-ISSUES entry (see deliverable
   7); everything else in §6.2 is untouched.

3. **The ROM: one assembly source, checked-in bytes, versioned
   forever.** `rom/netboot/netboot.s`, assembled by asm/asm.py via
   `rom/netboot/build.sh`, artifact `rom/netboot/netboot.img` (+
   `.sym`) **checked into the repo**. The ROM's sha256 is the META
   `image_sha256` anchor of every recorded netboot session ever, and
   `--replay` validates it — so the bytes are append-only history:
   any change is a new ROM version. Mechanics:
   - `netboot.s` embeds `.ascii "SBROM v1"` near its head (greppable
     in the image and in memory dumps).
   - `rom/netboot/VERSION`: version number + the artifact's sha256,
     one fact per line. `rom/netboot/CHANGELOG.md`: one line per
     version, mandatory.
   - `build.sh` rebuilds and **byte-compares** against the checked-in
     artifact (`--check` mode used by CI); a mismatch is stop-the-line
     — either you forgot to bump the version or asm.py's output
     drifted, and both are serious.
   - build.sh also emits `emu-c/gui/netboot_rom.c` (a generated,
     checked-in TU: `const uint8_t se_netboot_rom[]`, its length, and
     the version string) — checked in because rom/ lives outside the
     emu-c bazel workspace, so a genrule cannot reach it; the `--check`
     gate is what keeps the two copies honest. This TU goes in
     `:gui_core` (it is pure data).
   Directory: flat — `rom/netboot/{netboot.s, build.sh, netboot.img,
   netboot.sym, VERSION, CHANGELOG.md, sbp.md, test/}`. One source
   file needs no `src/`; if the ROM ever grows a second TU, that is a
   new version anyway and the tree can move then.

4. **Boot sequence and the staging policy (derived, never
   hardcoded).** In order:
   1. Validate the device table header exactly as boot.md §3.3 / the
      Oasis idiom: magic, version 1, size fits the window; loud fail.
   2. Walk RAM regions; region 0 gives `top = base + len` (high u64
      half must be 0, else loud fail — the Oasis reduction). Walk
      devices by count: first type 4 (NIC) and first type 5 (timer)
      win; unknown types skip by +64; u128 base as two u64 loads.
      Display (type 1) is recorded if present, optional. Missing NIC
      or missing timer is terminal (distinct codes, decision 5).
   3. Stack: `sp = top` — the SABI §4.5 boot stack, top 64 KB of
      region 0 reserved. The ROM honors all of sabi-v0.md §4: nothing
      below 0x800, the table read-only, everything derived from the
      table (the only hardcoded address is 0x0800 itself).
   4. Staging window: `stage_cap = (region0.len / 2) & ~0xFFFF`;
      `stage_base = (top − 64 KB − stage_cap) & ~0xFFFF`. The download
      cursor starts at `stage_base` and grows up; overrunning
      `top − 64 KB` is terminal. Derived entirely from the table, so
      `--ram` just works; the payload's own territory is
      `[0x1000, stage_base)` — at least half of RAM by construction.
   5. Fetch per decision 1 into the staging window.
   6. Parse SAHIMG01 in-guest (TOOLING-SPEC §1, first in-guest
      consumer): magic; entry u128 (two u64 loads, high half 0,
      8-aligned); nsegs in [1, 64]; per segment: `file_off+file_len`
      within the downloaded bytes, `mem_len >= file_len`, no u64
      wraps, target `[load_pa, load_pa+mem_len)` inside
      `[0x1000, stage_base)` — which structurally protects the ROM's
      no-go zones ([0, 0x800) tripwire, the device table, the staging
      window, the stack) in one check. Any violation: terminal, its
      own code. Segment-vs-segment overlap is NOT checked (the ROM is
      not a linker; the host-side assembler already refuses overlap,
      and a hand-hostile image gets last-writer-wins, documented).
   7. **The two-stage copy-down.** The ROM runs at 0x1000 and the
      payload wants 0x1000, so the ROM copies a small position-
      independent copy loop plus the parsed segment table to
      `top − 64 KB` (the base of the reserved stack window — always
      RAM, never a payload target) and jumps to it; the relocated loop
      copies each segment's file bytes staging→load_pa, zero-fills
      [file_len, mem_len), zeroes r0–r30 and p1–p7 (reset-like
      hand-off; document that cycle, NIC pop-state, and timer are NOT
      reset — a netbooted payload must not assume cycle 0), and jumps
      to entry. The copy loop is the only ROM code that survives the
      overwrite; keep it under one cache-irrelevant page and test it
      with a payload whose segment covers the whole ROM footprint.
   No DHCP, no ARP, no DNS in the ROM: classification accepts src
   10.0.2.15 unconditionally and the peer MAC 52:55:0A:00:02:02 is a
   normative constant (nic.md §6.1), so the ROM builds its two fixed
   frames from constants. Fewer packets, fewer failure modes, fewer
   bytes under the sha256 anchor.

5. **Failure discipline: paint + HALT, never a silent hang.** Every
   terminal path ends in: if a display was found, fill the visible
   frame with a solid per-class color and PRESENT (no font, no
   console machinery — a color is loud enough and costs ~30
   instructions); then `HALT` with a distinct r0 code. Codes (frozen
   in sbp.md and a netboot.s comment table): 0xBAD1 device-table
   validation, 0xBAD2 no NIC, 0xBAD3 no timer, 0xBAD4 fetch timeout
   (retries exhausted), 0xBAD5 server ERR, 0xBAD6 image bad
   magic/entry, 0xBAD7 segment bounds/truncated, 0xBAD8 staging
   overflow / image too big. The emulators print `HALT r0=...`, so
   the console message exists in every mode including headless
   replay; the codes are what the malformed-image CI legs assert.

6. **CLI semantics — the scope wall.** `sahara-gui`'s IMAGE argument
   becomes optional: `sahara-gui [IMAGE] [--rom PATH]
   [--serve-image PATH] [...existing flags...]`. No IMAGE → boot the
   embedded ROM (`se_netboot_rom`); `--rom PATH` overrides with a
   file; IMAGE + `--rom` together is a usage error. Mechanism:
   **materialize-then-load** — when the embedded ROM is used, its
   bytes are written next to the trace as `<trace-basename>.rom.img`
   and loaded through the existing image loader, so META
   `image_sha256`, `--replay` validation, and the printed replay
   command (`sahara-emu <that path> --replay <trace>`) all work with
   zero image.c/trace.c changes and the replay artifact pair
   (trace + ROM) is self-contained on disk. **The frozen headless
   `sahara-emu` CLI is untouched byte-for-byte** — no default-ROM
   behavior, no new flags, no output changes; a recorded netboot
   session replays as `sahara-emu <rom.img> --replay session.trc`
   with the ROM path explicit. That asymmetry is the design, not an
   oversight: the headless binary stays the frozen conformance
   instrument, and only the front end grows product behavior.

7. **Tests: the whole netboot path in CI, zero real IO.** New legs in
   `emu-c/run-gui-tests.sh` (the run-gui-tests precedent — emu-c-owned
   script, never under `tests/`), fixtures under `rom/netboot/test/`
   (`mkpayload.py` builds the good and malformed images; a
   `netboot.script` drives the scripted session):
   - **ROM reproducibility gate:** `rom/netboot/build.sh --check`
     (rebuild, cmp netboot.img, cmp emu-c/gui/netboot_rom.c, sha256
     matches VERSION).
   - **SBP responder unit tests** in test_nic.c against the sans-IO
     core: byte-exact request→reply vectors from sbp.md (REQ→DATA(1),
     ACK walk, duplicate ACK re-elicits identical DATA, final short
     block, exact-multiple zero-length final block, ERR when
     unconfigured, NIC-C-27 constants over every reply, oversize/
     malformed SBP datagrams drop).
   - **The headline gate:** `sahara-gui --script --nic fake
     --serve-image payload.img` with NO image argument, under
     `SDL_VIDEODRIVER=dummy`. The payload is a multi-segment SAHIMG01
     built by mkpayload.py whose segments overwrite the ROM's own
     address range and include a mem_len > file_len tail (zero-fill
     proof) — it HALTs 600d (the PASS_LINE magic proves the payload
     ran). Assertions: PASS_LINE; double run → whole-file cmp; replay
     via the exact printed `sahara-emu <...rom.img> --replay` command
     → cmp_post_meta. That last cmp is the vision made test: the
     image came over the network and the frozen headless binary
     reproduced the boot offline from the trace alone.
   - **Malformed-image legs:** bad magic → HALT 0xBAD6; truncated
     segment (file_len past the download) → 0xBAD7; segment aimed at
     the device table / below 0x1000 → 0xBAD7; image bigger than
     stage_cap under a small `--ram` → 0xBAD8. Each is one scripted
     run asserting its HALT line.
   - **No-server / no-plane legs:** no `--serve-image` → 0xBAD5 (ERR
     path); `--nic off` → 0xBAD4 (the timer-driven timeout, retries
     exhausted, bounded by `--maxcycles` as a safety net).
   - The whole script must still pass under `unshare -rn`.
   Existing suites all stay green; `tests/` and `trace-q/` are
   toolchain-owned and untouched.

8. **SABI and doctrine posture.** The ROM is freestanding assembly,
   not an OS: no syscalls, no trap vectors beyond the reset default
   (pre-vector faults triple-fault loudly per boot.md §2.2 — that is
   the desired behavior for a ROM bug, don't install halt vectors
   that would soften it), MMU off, IE 0 throughout. It conforms to
   sabi-v0.md §4 as a *memory citizen* (decision 4) so any SABI
   payload finds the machine in the state Oasis expects. Add the
   netboot hand-off note to nic-notes.md's "known future consumers"
   section (it is now a present consumer) and a kernel-side note in
   sbp.md: Oasis itself is a valid payload once it fits stage_cap —
   booting Oasis over SBP is the manual smoke finale, not a CI gate.

## Deliverables

1. `rom/netboot/netboot.s` — the ROM per decisions 1/4/5, commented
   at the Oasis boot.s standard (the scan cites boot_dev_loop; the
   copy-down and the staging math each get a why-comment; the error
   code table in one place).
2. `rom/netboot/build.sh` (+ `--check`), `netboot.img`, `netboot.sym`,
   `VERSION`, `CHANGELOG.md` ("v1: initial ROM" line), and the
   generated `emu-c/gui/netboot_rom.c` — all committed.
3. `rom/netboot/sbp.md` — normative SBP/1: packet layouts, server
   state machine (stateless; the response function), client state
   machine, timeout/retry constants, the error-code table, byte-exact
   test vectors (SBP-TV-1…: REQ, DATA(1), ACK(1), final block, ERR),
   and the determinism note (all replies synthesized sans-IO; the
   downloaded image is the EVENT subsequence of the trace).
4. gui/nic.c + nic.h: `nic_sbp` responder + `SeNic_serve_image` +
   the one-leaf `nic_udp` dispatch change, full doctrine, in
   `:gui_core`.
5. sdl_main.c: optional IMAGE, `--rom`, `--serve-image`,
   materialize-then-load, blob load + `SeNic_serve_image` wiring;
   usage string updated. BUILD.bazel: `netboot_rom.c` into
   `:gui_core`; SBP vectors into `test_nic`.
6. run-gui-tests.sh netboot stanzas + `rom/netboot/test/`
   (mkpayload.py, netboot.script, malformed fixtures) per decision 7.
7. SPEC-ISSUES.md entries: (a) the classification-tree extension —
   UDP to 10.0.2.2:69 now reaches a local-plane service instead of
   the §6.2 subnet drop, gui-only, proposed for a future nic.md
   amendment; (b) the `sahara-gui` optional-IMAGE/`--rom`/
   `--serve-image` CLI reading (frozen headless CLI untouched);
   (c) the ERR-when-unconfigured reading; (d) the in-guest SAHIMG01
   validation subset (what the ROM checks vs what host loaders
   check — no overlap check, the [0x1000, stage_base) rule).
8. nic-notes.md: move netboot from "known future consumers" to a
   short present-tense section pointing at rom/netboot/sbp.md.

## Definition of done

All from the worktree root unless noted; every gate green:

- `rom/netboot/build.sh --check` — the committed ROM bytes, the
  generated TU, and VERSION's sha256 all agree with a fresh asm.py
  rebuild.
- `emu-c/build.sh` end to end (bazel picks up the new TU and the
  test_nic vectors; REPLAY=1 conformance leg stays green).
- `./run_tests.sh` (repo root; the emu-py leg saw no fallout).
- `emu-c/run-gui-tests.sh` green including every netboot leg, all
  headless, no real window, no real sockets; identically green under
  `unshare -rn` where the host allows user namespaces (if unavailable,
  note it — `--nic host` is still rejected under `--script`).
- **Headless byte-identity** — `sahara-emu` is untouched this order,
  so this gate is pure paranoia; run it anyway, verbatim:

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

  Any DRIFT line is stop-the-line.
- The netboot gate's trace replays through the **unmodified**
  `sahara-emu` invocation printed by the GUI, byte-identical
  post-META; two identical scripted netboot runs produce byte-
  identical `.trc` files in their entirety.
- `bazel test //:audit_banned_syms` (sahara-emu) green — still no
  socket symbols headless.
- SPEC-ISSUES entries, VERSION/CHANGELOG, sbp.md, and the nic-notes
  update committed.

## Scope boundaries

- **The scope wall: zero changes to `sahara-emu`** — no CLI, no
  output, no loader, no core (cpu.c/dev.c/mem.c/trace.c/image.c/
  main.c) edits of any kind. This order lives in gui/, rom/, and
  run-gui-tests.sh only.
- No edits under `tests/` or `trace-q/` — toolchain-owned. If a suite
  bug blocks you, record it in SPEC-ISSUES.md and stop.
- No emu-py changes; no Oasis/`os/` changes (booting Oasis over SBP
  is smoke, not scope); no lang/cc involvement — the ROM is assembly.
- No devspec edits: nic.md is not amended here; the classification
  extension rides as a SPEC-ISSUES proposal (deliverable 7a).
- No request-by-name, no multi-file serving, no listing, no resume,
  no compression, no image signing — SBP/2 material, each would
  freeze new ROM bytes.
- No DMA-assisted copy, no MMU use, no interrupts in the ROM — pure
  polled loops; the boot phase does not need them and every
  instruction is under the version anchor.
- No new trace record types, levels, or META keys; no core seam
  growth — if the ROM seems to need one, the design is wrong; stop
  and record the issue.

## Manual smoke checklist (real window and/or real sockets, not CI)

- `sahara-gui --serve-image rom/netboot/test/out/payload.img` (no
  image argument, default `--nic host`): window opens, brief
  netboot, payload HALTs 600d — identical guest-visible behavior to
  the fake run, because the server never touches a backend.
- `sahara-gui` with no arguments at all: ERR path — error paint +
  `HALT r0=...bad5` within a second or two. Loud, not a hang.
- `--nic off`, no image: timeout paint + 0xBAD4 after the retry
  budget (~20 s at default `--hz`).
- Serve a big image (a few MB): fetch completes, trace size is
  ~image size + overhead, replay of that trace under `unshare -rn`
  reproduces the whole boot offline — the headline demo; keep the
  `.trc` + `.rom.img` pair as the artifact.
- `--rom rom/netboot/netboot.img` behaves identically to the
  embedded default (same sha256 in META).
- Kill the GUI mid-download; the partial trace replays post-META
  clean (partial sessions are still valid traces).
- Finale: assemble/point `--serve-image` at an Oasis image and watch
  the OS come up with no image argument — the network as the storage
  layer, end to end.

## Risks

- **The ROM bytes are forever.** The sha256 anchors every recorded
  session; a "trivial cleanup" after merge is a new version and a
  changelog line, and CI's `--check` gate will catch you if you
  forget. Get the error-code table and the two TX frames right
  before first freeze — review netboot.s hardest of everything in
  this order.
- **The copy-down is the classic self-overwrite bug farm.** The
  relocated loop must be genuinely position-independent (asm.py `la`
  is PC-relative within ±2 MB — verify what the relocated copy does,
  or use pure register arithmetic), and the CI payload must really
  cover the ROM's whole footprint or the bug ships latent.
- **Staging math edge cases:** tiny `--ram` (stage_cap smaller than
  the payload → 0xBAD8, tested), region-0-only assumption (the ROM
  uses region 0 exactly like Oasis; multi-region RAM stages in
  region 0 — fine, document), and the 64 KB granularity of the table
  keeping all the `& ~0xFFFF` arithmetic exact.
- **Two copies of the ROM bytes in-tree** (netboot.img and
  netboot_rom.c) is a drift hazard by construction; the `--check`
  gate is the mitigation and it must run in CI, not just in build.sh
  folklore.
- **Trace growth**: a level-0 netboot trace carries the image in
  EVENTs plus one EXEC per polled instruction; the poll loop between
  blocks is cheap at fake-clock pacing but a multi-MB image at
  `--hz 0` live writes a big trace. Acceptable; note it in sbp.md,
  never hack the format.
- **Classification-tree touch**: the new leaf sits before the subnet
  drop — one misplaced condition and DHCP or DNS re-routes. The
  existing TV vectors in test_nic are the regression net; run them
  first after wiring the leaf.
