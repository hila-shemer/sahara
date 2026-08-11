# sahara-gui NIC notes

The translator phase closed emu-c SPEC-ISSUES 35's dead wire: the RX
model lives in dev.c (nic.md 4), the sans-IO translator in gui/nic.c
(nic.md 6, milestone-1 scope), and every frame the guest ever receives
enters the machine as a fed EVENT through the same boundary path as a
keystroke. A networked session's trace replays byte-identically under
`sahara-emu --replay` with no network — that is the doctrine's
headline demo, and the run-gui-tests nic legs prove it in CI with the
fake backend.

## Security posture (owner ruling, 2026-08-11 — binding)

The translator originates exactly three kinds of host traffic, all
guest-initiated:

- UDP datagrams to endpoints the guest names — any host/port the host
  stack can reach;
- DNS queries to the host's configured resolver (first IPv4
  `nameserver` in /etc/resolv.conf);
- nothing else. No listening sockets, no port forwarding, no
  inbound-initiated anything (nic.md 6.9.1), no TCP in milestone 1,
  no raw sockets, no ICMP sockets.

A hostile guest can therefore send UDP anywhere the host user can —
the authority of any program the developer runs locally, which is the
trust model of a dev tool whose guest images are hand-assembled by the
owner. Images are trusted by default and `--nic host` is the live
default; `--nic off` exists for running untrusted images. Hardening is
deferred deliberately ("security for now is a keyword for never"): no
sandboxing, no allow-lists, no confirmation prompts — do not let a
reviewer talk you into them. When TCP NAT lands (milestone 2) the
statement above widens to "TCP connections to endpoints the guest
names"; the no-inbound-listen line does not move.

## The fake backend contract (`--nic fake`, test-only)

nic_fake.c echoes every forwarded datagram back verbatim from its
flow's remote endpoint at the next pump tick. No sockets anywhere in
the TU, so the scripted gate runs identically with the network
namespace unshared. Guest-visible equivalence with the host backend is
by construction: frame synthesis is the shared sans-IO core; backends
only source payload bytes. The pending queue is 64 datagrams,
drop-newest — fixed, hence deterministic.

## WFI-idle latency (accepted)

Socket polling is one nonblocking sweep per pump tick, in flow-table
order (deterministic, not fd order). While the guest idles in WFI the
front end blocks on the SDL event queue with the existing 250 ms
housekeeping tick, so NIC return traffic can wait up to 250 ms before
being fed. Acceptable for a dev tool; the stamp is pump_earliest, so
determinism is untouched either way.

## Known future consumers

The planned netboot ROM will fetch boot images through this plane via
an image-server service on a virtual host — keep the local-plane
service dispatch (the `nic_udp` leaf that today serves only DHCP and
DNS) extensible for another virtual-host service. Because arrivals are
RX-recorded EVENTs, a netboot session's trace already replays offline
with no image server present.

## Milestone-2 recipe (TCP translation, nic.md 6.7)

- Connection table: 32 entries keyed by (gport, rip, rport), states
  CONNECTING / ESTABLISHED-pending-ACK / ESTABLISHED / half-closed —
  the RST leaves (6.7.6) and the connection-refused observable built
  here already carry the guest-visible failure semantics, so landing
  the table changes only the success paths.
- Backend grows a connect/read/write/shutdown surface on the same
  flow-index pattern; connect completion is polled in the pump sweep.
- Window-respecting segmentation (6.7.3): min(guest MSS, 1460) per
  segment, one admitted frame per segment, buffer the excess in the
  translator.
- Retransmitted SYNs while CONNECTING drop (6.7.1); guest RSTs abort;
  no TIME_WAIT (ISS 0 always).
- Outbound ICMP echo forwarding stays "never" unless a work order
  says otherwise — it is host-dependent by spec and deterministically
  absent here.

## Manual smoke checklist (real window, real sockets — never CI)

- `bazel-bin/sahara-gui gui/out/t_nic.img` (default `--nic host`):
  the local plane behaves identically to the fake run — DHCP
  handshake completes, ping 10.0.2.2 answered, HALT 600d. (The UDP
  leg times out unless something echoes on 1.2.3.4:9999; the local
  plane through TV-9 is the point.)
- DNS smoke: a t_nic.s variant sending one A query to 10.0.2.3:53 —
  RX_LEN goes nonzero with a plausible answer; no resolv.conf
  nameserver means a quiet timeout (documented drop).
- One UDP flow to a real endpoint: `socat UDP-LISTEN:9999,fork
  EXEC:cat` on loopback, guest sends, echo comes back exposed.
- `--nic off`: dead wire exactly as before this phase.
- Close the window mid-session with NIC traffic in the trace; run the
  printed replay command under `unshare -rn`: byte-identical
  post-META, HALT/MAXCYCLES as printed.
- Overflow sanity: a guest that never pops while the fake backend
  floods holds 64 frames and the trace holds exactly 64 NIC EVENTs
  (NIC-C-18; the nicseam seam scenario pins the same rule headlessly).
