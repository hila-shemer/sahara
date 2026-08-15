# SBP/1 — the Sahara Boot Protocol

**Status:** normative for the netboot ROM and the `sahara-gui` image
server. This is SOFTWARE documentation — the protocol between two
programs (the ROM, a tiny OS that uses the NIC, and a local-plane
service in the front end), exactly as `os/oasis/doc/syscalls.md` is OS
personality. It defines nothing about the NIC device; devspec/nic.md
owns the hardware contract and is not amended by this document. The
classification-tree carve-out that routes 10.0.2.2:69 to this service
is recorded in SPEC-ISSUES.md as a proposal for a future nic.md
amendment.

Style follows nic.md: numbered conformance-ish rules, byte-exact test
vectors, hex dumps 16 bytes per line, whitespace not part of the data.

---

## 1. Overview

SBP/1 fetches "the image" — one file, no name, no listing — over
stop-and-wait UDP from the gateway virtual host:

| constant | value |
|---|---|
| server endpoint | 10.0.2.2:69/udp (the gateway serves boot, the classic BOOTP/TFTP shape; reuses an existing virtual host — no new neighbor, no ARP change) |
| client endpoint | 10.0.2.15:45063 (0xB007), fixed — a deterministic constant, not an ephemeral pick |
| block size | 1024 bytes (v1 server; power of two for the ROM's shift arithmetic) |
| byte order | all SBP integers little-endian, like everything guest-side |

Determinism rides for free: every DATA block enters the guest as a
recorded RX EVENT, so a netboot session's trace *contains the
downloaded image*, and `sahara-emu <rom.img> --replay session.trc`
reproduces the whole boot on a machine with no network and no server.
All replies are synthesized sans-IO in gui/nic.c; backends never see
SBP traffic, which is why `--nic fake` covers the entire path in CI.

*Trace growth note:* a level-0 netboot trace carries the image in
EVENTs plus one EXEC per polled instruction. Cheap at fake-clock
pacing; a multi-MB image at `--hz 0` live writes a big trace.
Accepted — never hack the trace format around it.

*Untethered note:* `--untethered` (SPEC-ISSUES 44) composes with
netboot — the embedded ROM still materializes and boots, but with no
trace for the file to sit next to it falls back to
`untethered-<epoch>.rom.img`. The trace-contains-the-image property
above is forfeited with the rest of replayability; that is the
opt-out working as ruled, not a netboot special case.

## 2. Packet formats

Every SBP packet is one UDP datagram beginning:

| offset | size | field |
|-------:|-----:|-------|
| 0 | 4 | magic: the bytes `53 42 50 31` ("SBP1") |
| 4 | 4 | opcode, u32 LE |
| 8 | 4 | argument, u32 LE |

| opcode | name | argument | payload after offset 12 |
|-------:|------|----------|--------------------------|
| 1 | REQ  | max_block (the ROM sends 1024) | none — exactly 12 bytes |
| 2 | DATA | block number, 1-based | the block's bytes, ≤ block size |
| 3 | ACK  | block number being acknowledged | none — exactly 12 bytes |
| 4 | ERR  | error code (section 6) | none |

REQ and ACK are both exactly 12 payload bytes — deliberately, so the
ROM's two TX frames have identical fixed-size IP headers and the IP
checksum (0x62B5) is an assemble-time constant. The ROM computes no
checksums at runtime: guest UDP checksum 0 is legal (nic.md 6.2
step 5).

`max_block` is the one forward-compatibility hook: a future server
may serve smaller blocks, never larger. The v1 pair is pinned at 1024
on both sides (rule S4).

## 3. Server rules (stateless response function)

The server holds zero session state. Its entire behavior is one pure
function of (blob, request):

- **S1.** A datagram to 10.0.2.2:69 whose payload is not exactly 12
  bytes, lacks the magic, or carries an opcode other than REQ/ACK is
  dropped silently (the classification norm for malformed traffic).
- **S2.** REQ with no image configured → ERR 1. ACK likewise. Loud by
  policy: a serverless plane fails the guest in one round trip, never
  a mystery timeout.
- **S3.** REQ with max_block < 1024 → ERR 2. A stateless server has
  nowhere to keep a smaller negotiated size across ACKs.
- **S4.** REQ (max_block ≥ 1024) → DATA(1). ACK(n), n ≥ 1 →
  DATA(n+1). ACK(0) is malformed → drop.
- **S5.** DATA(k) carries blob bytes [(k−1)·1024, min(k·1024, len)).
  If (k−1)·1024 > len, no such block exists → drop. A DATA payload
  shorter than 1024 — zero-length included, for exact multiples — is
  the final block.
- **S6.** Replies go to the request's source (10.0.2.15, source
  port); every reply carries the nic.md 6.1 translator constants
  (TTL 64, IP ID 0, UDP checksum 0), like every synthesized frame.
- **S7.** Byte-identical requests produce byte-identical replies —
  duplicate REQ/ACK re-elicit identical DATA (vectors below; the
  test_nic dup-ACK case pins it).

## 4. Client (ROM) rules

- **C1.** The client sends REQ {max_block 1024} from 10.0.2.15:45063
  and expects DATA(1); after DATA(n) with a full 1024-byte payload it
  sends ACK(n) and expects DATA(n+1); a DATA payload shorter than
  1024 completes the transfer.
- **C2.** DATA whose block number is not the expected one is popped
  and ignored (a duplicate re-elicits nothing; unreachable on the
  lossless plane — the timer is the backstop).
- **C3.** Retransmit by timer COUNT: the ROM records COUNT at each
  send; after TIMEOUT_CYCLES (8,000,000) with no reply it re-sends
  the last REQ/ACK; after RETRY_MAX (5) total sends of the same
  packet it fails terminally with 0xBAD4. On the lossless local plane
  this is a liveness backstop only — it fires when there is no
  translator at all (`--nic off`).
- **C4.** ERR is terminal immediately (0xBAD5), no retries.
- **C5.** No DHCP, no ARP, no DNS: classification accepts src
  10.0.2.15 unconditionally and the peer MAC 52:55:0A:00:02:02 is
  normative (nic.md 6.1), so both TX frames are fixed 60-byte
  templates. The source MAC is patched from the device table's NIC
  params[0] at boot (a table value, never a constant).

## 5. The ROM around the protocol

Fetch lands in a staging window derived entirely from the device
table (netboot.s, work order decision 4):

    stage_cap  = (region0.len / 2) & ~0xFFFF
    stage_base = (region0.top − 64 KB − stage_cap) & ~0xFFFF

with the extra floor `stage_base ≥ 0x10000` (keeps staging
structurally clear of the ROM; build.sh asserts the image ends below
64 KB). Payload territory is [0x1000, stage_base) — at least half of
RAM by construction. The top 64 KB of region 0 is the SABI 4.5 boot
stack window; the relocated copy-down loop and parsed segment table
live at its base during hand-off.

In-guest SAHIMG01 validation (the first in-guest consumer of
TOOLING-SPEC 1): magic; entry u128 (high half 0, 8-aligned, inside
[0x1000, stage_base)); nsegs in [1, 64]; per segment file_off +
file_len inside the download, mem_len ≥ file_len, no u64 wraps,
target [load_pa, load_pa + mem_len) inside [0x1000, stage_base).
NOT checked, deliberately: segment-vs-segment overlap (the ROM is not
a linker; the host assembler refuses overlap, and a hand-hostile
image gets last-writer-wins in table order) and the reserved flags
word. SPEC-ISSUES records the validation-subset reading.

**Hand-off state.** The copy-down ends reset-like: r0–r30 and p1–p7
zero, pc = entry, S = 1, IE = 0, MMU off. Deltas from a cold reset a
payload must not trip over: `cycle`, the NIC mailbox/pop state, and
the timer are NOT reset (a netbooted payload must not assume cycle
0); `epc0` = entry and `status.PS` = 1 (the jump is epc0 + IRET, so
every GPR can be zero at entry — a jalr would leak the entry address
in a register).

**Oasis note:** Oasis is a valid payload once it fits stage_cap —
`sahara-gui --serve-image <oasis.img>` with no image argument is the
manual smoke finale, not a CI gate.

## 6. Error codes

ERR argument values (server → client):

| code | meaning |
|-----:|---------|
| 1 | no image configured (`--serve-image` absent) |
| 2 | REQ max_block below the server's block size |

ROM terminal HALT codes (frozen; the malformed-image CI legs assert
them; netboot.s carries the same table):

| r0 | class | screen color |
|---:|-------|--------------|
| 0xBAD1 | device-table validation (incl. u128 high halves) | maroon |
| 0xBAD2 | no NIC (type 4) in the table | orange-brown |
| 0xBAD3 | no timer (type 5) in the table | olive |
| 0xBAD4 | fetch timeout, retries exhausted | navy |
| 0xBAD5 | server ERR (any code) | purple |
| 0xBAD6 | image bad magic / entry / nsegs | teal |
| 0xBAD7 | segment truncated or out of bounds | green |
| 0xBAD8 | staging overflow / image too big / RAM too small | gray |

Every terminal path paints the screen (when a display record exists),
renders a human-readable message in the ROM's 8x16 font, PRESENTs,
and HALTs with the code — loud, never a hang. Headless CI asserts the
codes; the run-gui-tests screencheck leg decodes the rendered text
from a level-1 trace.

## 7. Test vectors

Conventions as nic.md 9: complete frames, 16 hex bytes per line;
guest MAC 52:54:00:12:34:56 (the reference table's params[0], patched
into the templates at boot). Expected replies match byte-exactly,
padding included. These four vectors are embedded verbatim in
emu-c/test_nic.c.

### SBP-TV-1 — REQ, G→N, doorbell = 60

The ROM's first TX frame: 10.0.2.15:45063 → 10.0.2.2:69, max_block
1024, padded from 54 to 60.

```
52550a00020252540012345608004500
002800000000401162b50a00020f0a00
0202b007004500140000534250310100
000000040000000000000000
```

### SBP-TV-2 — DATA(1), N→G, RX_LEN = 70

Reply to TV-1 with the 16-byte image "SBP1-TEST-BLOB!!" configured:
one short (hence final) block.

```
52540012345652550a00020208004500
003800000000401162a50a0002020a00
020f0045b00700240000534250310200
000001000000534250312d544553542d
424c4f422121
```

### SBP-TV-3 — ACK(1), G→N, doorbell = 60

Byte-identical to TV-1 except opcode 3 and argument 1. Elicits
DATA(2) — the final-block walk continues; against the TV-2 image
(only one block) it elicits nothing.

```
52550a00020252540012345608004500
002800000000401162b50a00020f0a00
0202b007004500140000534250310300
000001000000000000000000
```

### SBP-TV-4 — ERR 1, N→G, RX_LEN = 60

Reply to TV-1 with no image configured; padded from 54 to 60.

```
52540012345652550a00020208004500
002800000000401162b50a0002020a00
020f0045b00700140000534250310400
000001000000000000000000
```

Programmatic vectors (test_nic.c, not dumped here): the 1024+200
ACK walk, duplicate-ACK byte identity, the exact-multiple
zero-length final DATA, ERR 2 for max_block 512, and the
malformed/misaddressed drop set.
