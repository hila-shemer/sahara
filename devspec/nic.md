# Sahara NIC — Detailed Device Specification

**Version 1.0-draft.** Companion to PLATFORM-SPEC.md §7, which is frozen and
authoritative for the register offsets, window layout, and everything else it
states. This document elaborates the NIC to full implementability: frame
rules, the mailbox protocol, error conditions, the guest-visible behavior of
the network translator, and the determinism contract. Where this document
restates a frozen fact it is marked *informative*; everything else here is
normative for the reference platform NIC.

Interfaces owned elsewhere and only referenced here:

- Device register offsets/widths — PLATFORM-SPEC §7 (frozen).
- EVENT record payload encoding — devspec/trace.md §4.3 (see §10).
- Device table layout — devspec/boot.md §3.5/§3.6; the NIC entry is type 4
  with params[0] holding the MAC in the packing of boot.md §3.6, which
  §2.5 of this document restates.
- Virtual-time rules — ISA-SPEC §4 and PLATFORM-SPEC §8 (frozen); §7 of this
  document elaborates within them.

---

## 1. Overview

The NIC is a single-frame mailbox device. The guest transmits by writing
frame bytes into a 64 KB TX buffer and ringing a doorbell; it receives by
reading one exposed frame at a time from a 64 KB RX buffer and popping it.
The emulator terminates and translates guest Ethernet traffic onto the host
network, slirp-style (PLATFORM-SPEC §7); the guest sees a private IPv4
network and never sees the host's link layer.

Terms used throughout:

- **frame** — an Ethernet II frame *without* FCS (§3.2).
- **mailbox** — the RX-side exposure mechanism: the RX buffer plus RX_LEN.
- **admitted frame** — a received frame the emulator has accepted into the
  RX queue and recorded as an event (§7.1). Only admitted frames ever become
  guest-visible.
- **translator** — the emulator component that converts between guest
  Ethernet frames and host network operations (§6).
- **virtual hosts** — the translator-implemented endpoints 10.0.2.2
  (gateway) and 10.0.2.3 (DNS).

## 2. Interface

### 2.1 Window layout (informative restatement of PLATFORM-SPEC §7)

The NIC window is 192 KB at the base given by the device table (reference
platform default PA 0x0F03_0000):

| window offset | region |
|---:|---|
| 0x0_0000 – 0x0_FFFF | registers |
| 0x1_0000 – 0x1_FFFF | TX buffer, 64 KB |
| 0x2_0000 – 0x2_FFFF | RX buffer, 64 KB |

Registers (64-bit, naturally aligned, 64-bit access only):

| off | reg | access |
|---:|---|---|
| 0  | TX_DOORBELL | W |
| 8  | TX_STATUS | R |
| 16 | RX_LEN | R |
| 24 | RX_POP | W |
| 32 | MAC | R |

The whole 192 KB window is device space in the sense of ISA-SPEC §9.2:
stores are release fences, loads/stores are mutually program-ordered, and
atomics trap DEVERR.

### 2.2 TX_DOORBELL (offset 0, write-only)

Writing value N transmits TX buffer bytes [0, N) as one frame. N must be in
[60, 1514]; any other value traps DEVERR and transmits nothing (§5).

Transmission is **synchronous**: when the doorbell store completes, the
frame bytes have been captured from the TX buffer. The instruction after the
doorbell store may overwrite the TX buffer freely without affecting the
transmitted frame. The release-fence rule (ISA-SPEC §9.2 rule 1) plus the
mutual ordering of device stores (rule 2 — the TX buffer is device space)
guarantee every prior buffer store is visible to the capture.

The captured frame is processed by the translator (§6). "Transmitted" never
implies delivery: the translator may deterministically drop the frame per
its rules. TX has no completion interrupt and no error reporting beyond the
doorbell-value DEVERR; TX_STATUS reads 0 always in v1.0.

Reading TX_DOORBELL traps DEVERR.

### 2.3 RX_LEN (offset 16, read-only) and the RX buffer

RX_LEN reads the length in bytes of the currently exposed frame, or 0 if
none. While a frame is exposed:

- RX buffer bytes [0, RX_LEN) hold the frame, byte 0 = first byte on the
  wire (destination MAC byte 0).
- RX buffer bytes [RX_LEN, 0x1_0000) are **unchanged** from before the
  exposure (the emulator writes exactly RX_LEN bytes at exposure time).
- Repeated reads of RX_LEN return the same value; the buffer contents are
  stable until RX_POP.

RX_LEN of an exposed frame is always in [60, 1514] (§3.3). Writing RX_LEN
traps DEVERR.

The guest may write the RX buffer (it behaves as memory); such writes only
affect subsequent guest reads and are overwritten byte-for-byte when the
next frame is exposed. This is legal but pointless.

### 2.4 RX_POP (offset 24, write-only)

Writing any value (the value is ignored) when RX_LEN != 0 consumes the
exposed frame. If the internal RX queue is non-empty, the next frame is
exposed immediately: the very next instruction observes the new RX_LEN and
buffer contents. If the queue is empty, RX_LEN becomes 0.

Writing RX_POP when RX_LEN == 0 traps DEVERR (loud-failure policy; there is
no legitimate reason to pop an empty mailbox). Reading RX_POP traps DEVERR.

### 2.5 MAC (offset 32, read-only) and the MAC encoding

MAC reads the device's 48-bit MAC address in bits 47:0; bits 63:48 read 0.

**Encoding (normative; identical by construction to the device-table
packing owned by devspec/boot.md §3.6):** for MAC address m0:m1:m2:m3:m4:m5
(m0 = first byte on the wire, i.e. the leftmost byte in conventional
notation), the register value is

    value = m0 | m1<<8 | m2<<16 | m3<<24 | m4<<32 | m5<<40

i.e. the six wire bytes little-endian into the low 48 bits. Example:
MAC 52:54:00:12:34:56 reads as 0x0000_5634_1200_5452. The device-table NIC
entry params[0] (PLATFORM-SPEC §2) uses the identical encoding and always
equals the MAC register value.

### 2.6 TX and RX buffers

Both buffers accept all access sizes (1/2/4/8/16 bytes) subject to natural
alignment (ISA-SPEC §5.3), behave as memory (reads return last written,
reads have no side effects), and are device space for ordering purposes
only. Buffer contents at reset are all zero.

## 3. Frames

### 3.1 Format and validity

All frames crossing the interface are Ethernet II: 6-byte destination MAC,
6-byte source MAC, 2-byte EtherType (big-endian on the wire, as in all
network byte order fields inside frames), payload. There is no 802.1Q tag
support, no 802.3 length-field frames, no jumbo frames. Frame length is
always in [60, 1514] bytes in both directions (1514 = 14-byte header +
1500-byte MTU).

The doorbell length is the only structural validity check applied at TX
time. Frames with any content — malformed EtherType, garbage payload — are
accepted by the doorbell and passed to the translator, which classifies and
possibly drops them (§6.2). Classification never traps; DEVERR is reserved
for interface misuse (§5), not for frame content.

### 3.2 FCS policy

**The guest never sees, computes, or checks an FCS.** The 4-byte Ethernet
CRC does not exist at this interface: TX frames are given to the doorbell
without FCS, RX frames are exposed without FCS, and the length limits
[60, 1514] are FCS-less lengths (wire minimum 64 and maximum 1518 minus 4).
The emulator neither validates nor synthesizes CRCs anywhere the guest can
observe. A guest that appends 4 CRC bytes has simply transmitted a frame
with 4 bytes of trailing garbage.

### 3.3 Padding

- **TX:** the guest is responsible for padding. A logical frame shorter than
  60 bytes must be zero-padded by the guest to reach the doorbell minimum;
  the doorbell traps DEVERR below 60 rather than padding silently.
- **RX:** every frame the emulator exposes is at least 60 bytes. When the
  translator synthesizes a frame shorter than 60 bytes, it zero-pads to
  exactly 60 and RX_LEN reads 60.

### 3.4 Trailing bytes

The translator parses guest IPv4 frames using the IPv4 total-length field;
bytes between the end of the IP datagram and the doorbell length (i.e.
padding) are ignored and never interpreted. Likewise ARP frames are parsed
as exactly 28 payload bytes; the rest is ignored.

## 4. Mailbox protocol

### 4.1 State machine

NIC RX state is (exposed frame or none, internal FIFO queue of admitted
frames). Capacity: **64 admitted frames total** — 1 exposed + up to 63
queued.

| state | RX_LEN | event: frame admitted | event: RX_POP written |
|---|---|---|---|
| EMPTY (no exposed, queue empty) | 0 | expose it → EXPOSED | DEVERR |
| EXPOSED, queue empty | len | enqueue → EXPOSED+Q | → EMPTY |
| EXPOSED, queue non-empty (EXPOSED+Q) | len | enqueue (or overflow-drop, §4.3) | expose queue head → EXPOSED or EXPOSED+Q |

TX_DOORBELL is not an input to this state machine: transmission is legal
and unchanged in every state (§4.5).

### 4.2 Admission and exposure

A frame is **admitted** at the virtual cycle assigned to its arrival event
(§7.1). At that cycle boundary:

- state EMPTY: the frame's bytes are written to RX buffer [0, len), RX_LEN
  becomes len. The first instruction executing at or after that cycle
  observes the frame.
- otherwise: the frame joins the tail of the FIFO queue with no
  guest-visible effect (EXTINT is already pending).

Exposure via RX_POP (§2.4) is not a new event and consumes no extra cycle;
the frame's only event is its admission.

Frames are exposed in exactly admission (event) order — FIFO, no exceptions.

### 4.3 Overflow

An arrival while 64 frames are already held is **discarded before
admission**: it produces no event, no trace record, and no guest-visible
effect, and the translator state that produced it is unaffected (e.g. a TCP
segment lost this way is *not* retransmitted — the connection's data is
truncated; the guest end will see a protocol-level stall. Guests must drain
the mailbox promptly). Because unadmitted frames never enter the event
trace, replay (§7.3) is trivially exact: overflow cannot occur in replay.

*Note: 64 frames is ample — EXTINT is level-triggered and pending the whole
time, so only a guest ignoring the NIC for a long stretch can overflow.*

### 4.4 EXTINT

The NIC's contribution to EXTINT (PLATFORM-SPEC §3) is: **pending iff
RX_LEN != 0**. Queued-but-unexposed frames do not add anything (RX_LEN is
already non-zero whenever the queue is non-empty). Draining to RX_LEN == 0
clears the NIC's contribution. There is no interrupt-enable register on the
NIC; masking is done with status.IE (ISA-SPEC §7.5).

### 4.5 TX path

On doorbell write with valid N: capture bytes, run the translator
classification (§6.2) synchronously in virtual time. Any reply frames the
translator synthesizes locally (ARP reply, DHCP, RST, echo reply from a
virtual host) are admitted as arrival events at a cycle strictly greater
than the doorbell store's cycle (§7.1). Frames NAT-ed to the host network
are handed to the host asynchronously; the wall-clock send time is
invisible to the guest.

### 4.6 TX during pending RX

TX and RX are fully independent (full duplex). TX_DOORBELL while RX_LEN !=
0 is legal, transmits normally, and does not disturb the exposed frame, the
queue, or RX_LEN. Reply frames triggered by such a TX join the tail of the
RX queue like any other arrival. RX_POP never affects TX state.

## 5. Error conditions

### 5.1 DEVERR catalog

All of the following trap DEVERR (cause 12) with baddr = the offending
virtual address (for the doorbell-value case, the address of TX_DOORBELL):

| # | condition | source |
|--:|---|---|
| E1 | access to the register region (window offsets 0x0_0000–0x0_FFFF) with size != 8 bytes | PLATFORM-SPEC §1 (frozen) |
| E2 | 8-byte aligned access to a register-region offset not in {0, 8, 16, 24, 32} | this spec (loud-failure) |
| E3 | read of TX_DOORBELL or RX_POP | this spec |
| E4 | write to TX_STATUS, RX_LEN, or MAC | this spec |
| E5 | TX_DOORBELL write with value < 60 or > 1514 | PLATFORM-SPEC §7 (frozen) |
| E6 | RX_POP write while RX_LEN == 0 | this spec |
| E7 | any atomic (CAS/AMO) anywhere in the 192 KB window, buffers included | ISA-SPEC §5.4 (frozen) |

A faulting access has no architectural or device effect (ISA-SPEC §4): E5
transmits nothing, E6 pops nothing.

### 5.2 Check precedence

For an access to the NIC window, checks apply in this order (first failure
wins): predication (a predicated-false access does nothing and cannot fault,
ISA-SPEC §3.2) → translation and permission (PF_*/PERM_*) → natural
alignment (UNALIGNED) → atomic-to-device (E7) → register-region size (E1) →
register offset/direction (E2–E4) → value checks (E5, E6). In particular a
misaligned 4-byte access to the register region traps UNALIGNED, not
DEVERR.

Instruction fetch from the NIC window is not defined by PLATFORM-SPEC; the
conservative reading used here is that it traps DEVERR at the fetch (flagged
as a spec issue — see the report accompanying this document).

## 6. Translator

### 6.1 Network model and constants

| constant | value |
|---|---|
| guest IP | 10.0.2.15/24 (the only accepted guest source address, §6.2) |
| gateway (virtual) | 10.0.2.2 |
| DNS (virtual) | 10.0.2.3 |
| translator MAC ("peer MAC") | **52:55:0A:00:02:02** — source MAC of every frame the emulator delivers to the guest, and the MAC answering all ARP |
| guest MAC | device table params[0] (§2.5) |
| DHCP lease | 86400 seconds, fixed |
| translator IPv4 TTL | 64 on every synthesized datagram |
| translator IPv4 ID | 0 on every synthesized datagram; DF = 0, fragment offset = 0 |
| translator UDP checksum | 0 (checksum absent, legal per RFC 768) on every synthesized UDP datagram |
| TCP: translator ISS | 0 for every connection |
| TCP: translator window | 0xFFFF, fixed, in every segment |
| TCP: MSS | 1460 advertised in SYN-ACK; guest data segmented to min(guest MSS, 1460) |
| TCP connection limit | 32 simultaneous (all non-free states count) |
| UDP flow limit | 64 simultaneous; flows never expire in v1.0 |

The single peer MAC plays gateway, DNS server, DHCP server, and every
NAT-ed remote: the guest's ARP table only ever contains one neighbor.

IPv4/TCP/ICMP checksums in synthesized frames are always valid. Only the
UDP checksum is elided (set to 0).

### 6.2 Classification of guest TX frames (normative decision tree)

Applied in order to every doorbell-captured frame; "drop" means silently
and deterministically discarded, with no reply, no trap, no event:

1. Destination MAC not 52:55:0A:00:02:02 and not ff:ff:ff:ff:ff:ff → drop.
   (Source MAC is never checked.)
2. EtherType 0x0806 → ARP handling (§6.3). EtherType 0x0800 → step 3.
   Any other EtherType (including 0x86DD IPv6) → drop.
3. IPv4 sanity: version != 4, IHL != 5 (options unsupported), total length
   > captured length − 14 or < 20, or header checksum invalid → drop.
   Fragmented (MF set or fragment offset != 0) → drop.
4. Source IP: must be 10.0.2.15, or 0.0.0.0 for DHCP (protocol 17, dst port
   67). Anything else → drop.
5. TCP or UDP payload truncated relative to the IP total length, or a UDP
   checksum present (non-zero) but invalid, or a TCP checksum invalid →
   drop. (UDP checksum 0 is accepted without verification.)
6. By protocol:
   - **UDP to dst port 67** (dst IP 255.255.255.255 or 10.0.2.2) → DHCP
     responder (§6.4).
   - **UDP to 10.0.2.3:53** → DNS forwarding (§6.6).
   - **UDP to any IP outside 10.0.2.0/24** → UDP translation (§6.5).
   - **UDP to anything else in 10.0.2.0/24** (including 10.0.2.2, other
     10.0.2.x, 10.0.2.255 broadcast, 255.255.255.255 other than DHCP) →
     drop.
   - **TCP to any IP outside 10.0.2.0/24** → TCP translation (§6.7).
   - **TCP to any IP inside 10.0.2.0/24** (virtual hosts included — no TCP
     services exist in v1.0, not even DNS-over-TCP) → RST per §6.7.6.
   - **ICMP echo request (type 8, code 0)** → §6.8. Any other ICMP → drop.
   - Any other IP protocol → drop.

### 6.3 ARP

The translator parses Ethernet/IPv4 ARP (htype 1, ptype 0x0800, hlen 6,
plen 4); anything else → drop.

- **Request (oper 1)** with target IP in 10.0.2.0/24, excluding 10.0.2.15
  and 10.0.2.255: reply with oper 2, sender = (52:55:0A:00:02:02, target
  IP), target = the requester's sender pair, unicast to the requester's
  MAC. The translator proxy-answers the *entire* subnet with its one MAC,
  whether or not anything answers at that IP.
- Request for 10.0.2.15 or 10.0.2.255, gratuitous ARP, ARP replies from the
  guest, ARP probes for other subnets → drop (consumed without effect).

The translator never sends unsolicited ARP and never ARPs the guest: frames
to the guest always use the guest MAC from the device table.

### 6.4 DHCP responder, message by message

Runs on UDP port 67. The BOOTP payload must be ≥ 236 bytes with the magic
cookie 63.82.53.63 and an option 53 (message type); otherwise → drop (plain
BOOTP is not served). Requests with htype != 1 or hlen != 6 → drop.

| guest message (option 53) | responder action |
|---|---|
| 1 DHCPDISCOVER | send DHCPOFFER: yiaddr 10.0.2.15, siaddr 10.0.2.2, options exactly, in order: 53=2, 54=10.0.2.2, 51=86400, 1=255.255.255.0, 3=10.0.2.2, 6=10.0.2.3, end. Any requested-IP option in the DISCOVER is ignored — the offer is always 10.0.2.15. |
| 3 DHCPREQUEST | if the requested IP (option 50 if present, else ciaddr) is 10.0.2.15 → DHCPACK (identical option set to OFFER but 53=5, same yiaddr/siaddr). Otherwise → DHCPNAK: yiaddr 0, siaddr 0, options 53=6, 54=10.0.2.2, end. An option-54 server ID naming any server other than 10.0.2.2 → drop (the guest chose another server; there is none, so it will retry). Renewal REQUESTs (ciaddr = 10.0.2.15) → ACK, always; the lease is effectively eternal. |
| 8 DHCPINFORM | DHCPACK with yiaddr 0 and the same configuration options (54, 1, 3, 6). |
| 4 DHCPDECLINE, 7 DHCPRELEASE | consumed, no reply, no state change (the responder is stateless; 10.0.2.15 is offered unconditionally forever). |
| anything else | drop |

Reply construction, fixed for determinism: op 2, htype 1, hlen 6, hops 0,
xid echoed, secs 0, flags echoed, giaddr 0, chaddr echoed, sname and file
all-zero, option 55 (parameter request list) ignored — the option set and
order above is emitted regardless. The BOOTP payload is zero-padded to
exactly 300 bytes. Delivery: if the broadcast flag (0x8000) was set or
yiaddr is 0 (NAK), the reply goes to Ethernet broadcast / IP
255.255.255.255; otherwise unicast to chaddr / yiaddr. UDP 67 → 68. The
responder is fully deterministic: byte-identical requests produce
byte-identical replies (§9 vectors TV-3…TV-7).

### 6.5 UDP translation

Flow key: (guest source port, remote IP, remote port). On the first
datagram of a new flow: if 64 flows exist → drop; else create the flow
(one host-side socket) and forward. Subsequent datagrams with the same key
reuse the flow. Flows never expire or close in v1.0.

- Outbound: the UDP payload is re-originated from the host stack to the
  remote endpoint. The guest's IP TTL/ID/DSCP are not propagated.
- Inbound: a datagram arriving on a flow's host socket **from the flow's
  remote endpoint** (others are ignored — address-restricted NAT) is
  synthesized to the guest: src = remote IP:port, dst = 10.0.2.15:guest
  port, translator constants of §6.1. If the synthesized frame would
  exceed 1514 bytes (payload > 1472) → drop.

### 6.6 DNS forwarding

UDP datagrams to 10.0.2.3:53 are a special UDP flow (key: guest port →
10.0.2.3:53; counts against the 64-flow limit): the DNS message bytes are
forwarded verbatim to the host's configured resolver, and each response's
bytes are returned verbatim as a datagram from 10.0.2.3:53. The translator
does not parse, validate, cache, or modify DNS content; truncation (TC)
handling is the guest's problem. There is no DNS-over-TCP in v1.0 (TCP to
10.0.2.3 is refused, §6.2), so guests must cope with truncated answers.

### 6.7 TCP translation

One translator connection object per 4-tuple (10.0.2.15:gport, remote
IP:rport). At most 32 exist at once. The guest-facing side is a full TCP
peer implemented by the translator; the remote side is a host-stack socket.
The virtual link is lossless and ordered, so the translator never
retransmits and needs no reassembly.

**6.7.1 Open.** Guest SYN for a new 4-tuple with dst outside 10.0.2.0/24:
if 32 connections exist → reply RST (per §6.7.6) and create nothing.
Otherwise create the connection in state CONNECTING and begin a host
connect. No immediate reply. Guest MSS option is recorded (absent → 536);
all other guest TCP options are ignored, in the SYN and everywhere else.
Retransmitted identical SYNs while CONNECTING → drop.

- Host connect succeeds → send SYN-ACK: seq = 0 (ISS), ack = guest ISS + 1,
  window 0xFFFF, single option MSS 1460 (padded with NOP+EOL to 4 bytes:
  02 04 05 B4), state ESTABLISHED-pending-ACK.
- Host connect fails or errors → send RST (seq 0, ack guest ISS + 1,
  RST|ACK) and free the connection.

The guest's ACK completing the handshake carries no reply. Data arriving
from the host before the guest's handshake ACK is delivered after it (the
translator holds it; on the lossless link the ACK arrives promptly).

**6.7.2 Guest → host data.** A data segment with seq == rcv_next: payload
is written to the host socket in order; rcv_next += len; reply one ACK
segment (no data, ack = rcv_next, window 0xFFFF). A segment with seq !=
rcv_next (a retransmission — the only possibility on a lossless link):
drop the payload, reply a duplicate ACK with the current rcv_next. Data
beyond the guest's advertised... (not applicable: the translator's 0xFFFF
window is a promise it keeps by buffering host-bound data in the emulator).
URG flag and urgent pointer are ignored.

**6.7.3 Host → guest data.** Bytes read from the host socket are segmented
into segments of at most min(guest MSS, 1460) payload bytes, each with
PSH|ACK set, seq continuing from the last, ack = current rcv_next, window
0xFFFF. Each segment is one admitted frame (one event). The translator
respects the guest's advertised receive window: it never has more than that
many unacknowledged bytes outstanding, buffering the excess.

**6.7.4 Close.** Guest FIN (at rcv_next): ACK it (rcv_next += 1), shut down
the host socket's write side; guest-closed. Host EOF: after all pending
data is sent, send FIN|ACK; host-closed; the guest's ACK of the FIN
completes that side. When both sides are closed and acknowledged, the
connection is freed immediately — no TIME_WAIT (ISS is always 0; the
determinism story makes TIME_WAIT pointless). The 4-tuple is immediately
reusable by a new SYN.

**6.7.5 Reset.** Guest RST (in-window): abort the host socket, free the
connection, no reply. Host-side hard error (reset, unreachable): send RST
(seq = next send seq, ACK set, ack = rcv_next) and free.

**6.7.6 RST generation for refused/unknown traffic.** For a SYN that is
refused (policy §6.2, table full, host connect failure): RST|ACK, seq 0,
ack = SYN seq + 1, window 0. For a non-SYN segment matching no connection:
if it has ACK set → RST, seq = the segment's ack value, no ACK flag, window
0; else → RST|ACK, seq 0, ack = segment seq + segment length (counting
SYN/FIN flags), window 0. (RFC 793 reset rules, fixed here for
determinism.)

### 6.8 ICMP

- **Echo request to 10.0.2.2 or 10.0.2.3**: the translator itself replies —
  type 0, code 0, identifier, sequence, and payload echoed verbatim,
  translator IP constants of §6.1. Fully deterministic (vector TV-8/9).
- **Echo request to an address outside 10.0.2.0/24**: forwarded via the
  host *if the host permits* (unprivileged ICMP); otherwise silently
  dropped. Availability is host-dependent and explicitly not guaranteed;
  any reply is delivered with the guest's identifier/sequence/payload
  restored, and is an admitted event like all arrivals, so replay is exact
  either way.
- Echo to 10.0.2.255, 255.255.255.255, or other 10.0.2.x → drop.
- All other ICMP types from the guest → drop. The translator never
  generates ICMP errors: no destination-unreachable, no time-exceeded, no
  fragmentation-needed. (Consequence: traceroute does not work, and UDP to
  a dead port simply times out at the application.)

### 6.9 What does not work in v1.0 (normative exclusions)

1. **No inbound listen.** There is no port forwarding and no way for any
   host-side peer to initiate contact with the guest. Every frame the guest
   ever receives is a response to guest activity (ARP/DHCP/DNS replies,
   NAT-flow return traffic, TCP segments of guest-opened connections, echo
   replies). A guest `listen()` succeeds locally and then never sees a SYN.
2. No IPv6 (EtherType 0x86DD dropped).
3. No IP fragmentation in either direction (fragments dropped; oversize
   inbound UDP/ICMP dropped; TCP is segmented so never fragments).
4. No IP options (IHL != 5 dropped).
5. No non-echo ICMP; no ICMP error generation.
6. No multicast, no IGMP, no broadcast services other than ARP and DHCP.
7. No TCP services on the virtual hosts (no DNS-over-TCP).
8. No 802.1Q, LLDP, STP, or any non-IP/ARP protocol.

## 7. Determinism

### 7.1 Arrival events and cycle assignment

Elaborating within ISA-SPEC §4 and PLATFORM-SPEC §8 (frozen): every
admitted RX frame — NAT return traffic and locally synthesized replies
alike — is one event (cycle, device = NIC device-table index, payload = the
exact frame bytes as exposed, i.e. after §3.3 padding).

Rules for the assigned cycle C:

1. **Boundary effect.** The event takes effect at an instruction boundary:
   its consequences (admission, exposure if the mailbox is empty, EXTINT
   pending) are visible to the first instruction that begins with
   `cycle >= C`, and invisible before. Events never take effect mid-
   instruction (atomics stay atomic; ISA-SPEC C3 relies on this).
2. **Monotonicity.** Assigned cycles are non-decreasing in admission order
   across all devices; equal cycles are ordered by their order in the
   trace, and frames sharing a cycle are admitted in that order.
3. **Causality.** A frame synthesized in response to a guest action (ARP
   reply, DHCP reply, RST, SYN-ACK, virtual-host echo reply, ACKs) is
   assigned C strictly greater than the cycle at which the triggering
   doorbell store retired.
4. **Live mode.** For genuinely external arrivals (host network traffic)
   the emulator chooses C as the current cycle at whatever inter-
   instruction boundary it polls the host — implementation-chosen, hence
   live runs differ; the trace records whatever was chosen. During WFI the
   emulator may assign C within the stall window; WFI then advances cycle
   to C per ISA-SPEC §7.6.
5. **Headless determinism.** In any mode with no external input source
   (conformance runs, replay), cycle assignment must be a pure function of
   the guest's execution history, so identical runs produce byte-identical
   traces (TOOLING-SPEC §3.1). The reference policy for synthesized local
   replies is C = trigger cycle + 1; conformance tests must not assume the
   +1, only rules 1–3, and should poll RX_LEN or use WFI.

### 7.2 EVENT payload

The encoding of the EVENT record payload for a NIC arrival is owned by the
trace specification: **per devspec/trace.md §4.3** (payload = exactly the
frame bytes, `payload_len` = the RX_LEN value). This document constrains
only its information content: the payload must carry exactly the frame
bytes as exposed to the guest (length = the RX_LEN value, padding
included), such that replay can reproduce the RX buffer and RX_LEN without
consulting the translator. The emulator's own writes into the RX buffer do
**not** appear as trace records: trace.md §2.3.2–§2.3.6 define
MEMW/MEMR/DEVW as per-instruction data accesses, so the frame enters the
trace solely as its EVENT record (confirmed at integration).

### 7.3 Replay isolation guarantee

In replay mode (TOOLING-SPEC §3.2): the host network is **never touched** —
no sockets, no DNS resolution, no ICMP, nothing; the translator is not
invoked at all. RX frames come solely from EVENT records, applied at their
recorded cycles per §7.1 rule 1; TX doorbell writes are validated (E5) and
their frames discarded. Guest-visible NIC behavior — RX_LEN, buffer
contents, EXTINT, all register semantics, all DEVERR conditions — is
bit-identical to the recorded run, and the replayed trace's non-EVENT
records match the original byte-for-byte. Replay of a trace therefore works
on a machine with no network at all.

## 8. Conformance requirements

Numbered, testable; each names the vector(s) (§9) or the check it implies.
"trap DEVERR" always also asserts the ISA no-effect rule (device and
register state unchanged by the faulting access).

**Registers and errors**

- NIC-C-01: 64-bit aligned reads of TX_STATUS, RX_LEN, MAC succeed;
  TX_STATUS reads 0; after reset RX_LEN reads 0.
- NIC-C-02: MAC reads the device-table params[0] value; for MAC
  52:54:00:12:34:56 the value is 0x0000_5634_1200_5452 (TV-R1).
- NIC-C-03: register-region access with size 1, 2, 4, or 16 traps DEVERR
  (E1) at any offset, including offsets 0–7 of a defined register.
- NIC-C-04: 8-byte aligned access at register-region offsets 40 and 0xFFF8
  traps DEVERR (E2).
- NIC-C-05: reading TX_DOORBELL or RX_POP traps DEVERR (E3).
- NIC-C-06: writing TX_STATUS, RX_LEN, or MAC traps DEVERR (E4).
- NIC-C-07: TX_DOORBELL values 59 and 1515 trap DEVERR; 60 and 1514
  transmit (E5, TV-R2).
- NIC-C-08: RX_POP written while RX_LEN == 0 traps DEVERR (E6).
- NIC-C-09: every atomic opcode targeting any window offset (register, TX
  buffer, RX buffer) traps DEVERR (E7).
- NIC-C-10: a misaligned access to the window traps UNALIGNED, not DEVERR
  (precedence §5.2); a predicated-false doorbell/pop with an invalid value
  retires with no trap and no effect.
- NIC-C-11: TX and RX buffers accept all sizes 1–16 aligned, read back
  last-written, and read 0 after reset.

**Frames and mailbox**

- NIC-C-12: no exposed frame ever has RX_LEN < 60 or > 1514; no frame in
  either direction carries an FCS (§3.2 — checked structurally: TV replies
  are FCS-less).
- NIC-C-13: translator-synthesized frames shorter than 60 bytes are
  zero-padded to exactly 60 and expose RX_LEN == 60 (TV-2, TV-9, TV-11).
- NIC-C-14: at exposure the emulator writes exactly RX_LEN bytes; RX buffer
  bytes beyond RX_LEN retain their prior contents (test: pre-fill buffer
  tail via guest writes, receive a short frame, verify tail).
- NIC-C-15: TX_DOORBELL captures synchronously: overwriting TX buffer byte
  0 in the instruction after the doorbell does not alter the transmitted
  frame (observable via the reply to a TV-1-style ARP whose buffer is
  scribbled post-doorbell).
- NIC-C-16: frames are exposed in admission order (FIFO): two back-to-back
  echo requests yield replies exposed in request order.
- NIC-C-17: RX_POP with a non-empty queue exposes the next frame such that
  the next instruction reads the new RX_LEN and new buffer bytes; RX_POP
  with an empty queue makes the next instruction read RX_LEN == 0.
- NIC-C-18: the 65th admitted-candidate arrival while 64 frames are held is
  discarded: no EVENT record, no state change; the first 64 are delivered
  intact.
- NIC-C-19: EXTINT is pending iff RX_LEN != 0 (with status.IE = 1 and no
  other device pending): asserts on exposure, holds while queued frames
  remain, clears at the pop that empties the mailbox.
- NIC-C-20: TX_DOORBELL while RX_LEN != 0 transmits normally and leaves the
  exposed frame, RX_LEN, and queue order unchanged; the reply joins the
  queue tail.

**Translator**

- NIC-C-21: ARP request for 10.0.2.2 (TV-1) yields exactly the TV-2 reply;
  ARP requests for 10.0.2.15 and for 192.168.1.1 (off-subnet) yield no
  reply.
- NIC-C-22: DHCP DISCOVER (TV-3) yields exactly the TV-4 OFFER; REQUEST
  (TV-5) yields exactly the TV-6 ACK; REQUEST for 10.0.2.99 yields exactly
  the TV-7 NAK; DECLINE and RELEASE yield no reply.
- NIC-C-23: DHCP replies are byte-deterministic: repeating TV-3 yields a
  byte-identical OFFER each time.
- NIC-C-24: ICMP echo to 10.0.2.2 (TV-8) yields exactly the TV-9 reply;
  echo id, sequence, and payload are echoed verbatim for other id/seq/
  payload choices too.
- NIC-C-25: TCP SYN to 10.0.2.3:80 (TV-10) yields exactly the TV-11 RST;
  TCP SYN to 10.0.2.2 and to 10.0.2.99 likewise yields RST per §6.7.6.
- NIC-C-26: with 32 TCP connections open, a 33rd SYN receives RST and
  creates no connection; after one connection is freed, a new SYN
  succeeds.
- NIC-C-27: every translator-synthesized IPv4 datagram has TTL 64, ID 0,
  offset 0, valid header checksum; synthesized UDP checksum is 0;
  synthesized TCP and ICMP checksums are valid; translator TCP ISS is 0
  and window is 0xFFFF (asserted over TV-4, TV-6, TV-7, TV-9, TV-11).
- NIC-C-28: frames dropped by classification (§6.2) produce no reply, no
  trap, and no event: dst MAC 00:11:22:33:44:55; EtherType 0x86DD; bad IP
  header checksum; MF-flagged fragment; src IP 10.0.2.16 — each transmitted
  via doorbell, each silently consumed.
- NIC-C-29: doorbell padding beyond the IP total length is ignored: TV-8
  (50 content bytes, doorbell 60) parses identically to the same datagram
  sent with doorbell 64 and extra trailing garbage.
- NIC-C-30: in an idle live-mode run with no guest TX, no NIC EVENT records
  appear (no unsolicited inbound — §6.9.1).

**Determinism**

- NIC-C-31: every guest-exposed frame has exactly one EVENT record whose
  payload equals the exposed bytes (per devspec/trace.md §4.3), RX_LEN
  bytes long.
- NIC-C-32: a synthesized reply's event cycle is strictly greater than the
  triggering doorbell store's cycle; event cycles are non-decreasing in
  trace order.
- NIC-C-33: an event's effects are visible to the first instruction
  beginning at cycle >= C and invisible to earlier ones; no event takes
  effect between an atomic's read and write (trace-checked per
  CONFORMANCE.md C3).
- NIC-C-34: two identical headless runs of any NIC conformance test produce
  byte-identical traces (TOOLING-SPEC §3.1).
- NIC-C-35: replaying a recorded NIC session with host networking disabled
  reproduces all non-EVENT trace records byte-identically and performs no
  host network access (asserted by instrumentation/sandbox in the reference
  implementation's test suite).
- NIC-C-36: WFI with IE=1 and a pending-only-in-the-future NIC event wakes
  exactly at the event's cycle with EXTINT delivered (epc = instruction
  after WFI).

## 9. Test vectors

Conventions: hex dumps are the complete frame, 16 bytes per line, offset =
line number × 16; whitespace and newlines are not part of the data. All
vectors use guest MAC **52:54:00:12:34:56** (device table params[0] =
0x0000_5634_1200_5452) and the constants of §6.1. "G→N" frames are written
to the TX buffer at offset 0 and doorbelled with the stated value; "N→G"
frames are the expected exposed RX contents with RX_LEN = stated length.
Expected replies must match **byte-exactly**, padding included.

### TV-R1 — MAC register (data)

| step | action | expected |
|---|---|---|
| 1 | 64-bit load, window offset 32 | value 0x0000563412005452 |

### TV-R2 — doorbell bounds (data)

TX buffer pre-filled with the TV-1 frame (extended with zeros as needed).

| step | doorbell value | expected |
|---|---|---|
| 1 | 59 | trap DEVERR |
| 2 | 1515 | trap DEVERR |
| 3 | 0 | trap DEVERR |
| 4 | 60 | no trap (transmits) |
| 5 | 1514 | no trap (transmits) |

### TV-1 — ARP request, G→N, doorbell = 60

Who-has 10.0.2.2, tell 10.0.2.15. Guest-padded from 42 to 60 bytes.

```
ffffffffffff52540012345608060001
0800060400015254001234560a00020f
0000000000000a000202000000000000
000000000000000000000000
```

### TV-2 — ARP reply, N→G, RX_LEN = 60 (expected reply to TV-1)

10.0.2.2 is-at 52:55:0a:00:02:02. Translator-padded from 42 to 60.

```
52540012345652550a00020208060001
08000604000252550a0002020a000202
5254001234560a00020f000000000000
000000000000000000000000
```

### TV-3 — DHCP DISCOVER, G→N, doorbell = 342

xid 0x3903f326, broadcast flag set, options: 53=1, end; BOOTP padded to
300. UDP checksum 0. Field map (frame offsets): 0 dstMAC, 6 srcMAC,
12 ethertype, 14 IP header (checksum at 24), 34 UDP header, 42 BOOTP
(42 op, 46 xid, 52 flags, 54 ciaddr, 58 yiaddr, 62 siaddr, 66 giaddr,
70 chaddr, 86 sname, 150 file, 278 cookie, 282 options), 342 end.

```
ffffffffffff52540012345608004500
014800000000401179a600000000ffff
ffff0044004301340000010106003903
f3260000800000000000000000000000
00000000000052540012345600000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000063825363350101ff0000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
000000000000
```

### TV-4 — DHCP OFFER, N→G, RX_LEN = 342 (expected reply to TV-3)

yiaddr 10.0.2.15, siaddr 10.0.2.2, options in the normative §6.4 order
(53=2, 54, 51, 1, 3, 6, end), same field map as TV-3.

```
ffffffffffff52550a00020208004500
01480000000040116da40a000202ffff
ffff0043004401340000020106003903
f32600008000000000000a00020f0a00
02020000000052540012345600000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
0000000000006382536335010236040a
0002023304000151800104ffffff0003
040a00020206040a000203ff00000000
00000000000000000000000000000000
000000000000
```

### TV-5 — DHCP REQUEST, G→N, doorbell = 342

Options: 53=3, 50=10.0.2.15, 54=10.0.2.2, end.

```
ffffffffffff52540012345608004500
014800000000401179a600000000ffff
ffff0044004301340000010106003903
f3260000800000000000000000000000
00000000000052540012345600000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
0000000000006382536335010332040a
00020f36040a000202ff000000000000
00000000000000000000000000000000
00000000000000000000000000000000
000000000000
```

### TV-6 — DHCP ACK, N→G, RX_LEN = 342 (expected reply to TV-5)

Byte-identical to TV-4 except the option-53 value: byte at frame offset
284 is 05 instead of 02.

```
ffffffffffff52550a00020208004500
01480000000040116da40a000202ffff
ffff0043004401340000020106003903
f32600008000000000000a00020f0a00
02020000000052540012345600000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
0000000000006382536335010536040a
0002023304000151800104ffffff0003
040a00020206040a000203ff00000000
00000000000000000000000000000000
000000000000
```

### TV-7 — DHCP NAK, N→G, RX_LEN = 342

Expected reply to a TV-5-shaped REQUEST whose option 50 is 10.0.2.99
(frame offsets 287–290 = 0a 00 02 63 in the request; offset 285 is the
option code 0x32, 286 its length 4). Options: 53=6,
54=10.0.2.2, end; yiaddr 0, siaddr 0.

```
ffffffffffff52550a00020208004500
01480000000040116da40a000202ffff
ffff0043004401340000020106003903
f3260000800000000000000000000000
00000000000052540012345600000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
0000000000006382536335010636040a
000202ff000000000000000000000000
00000000000000000000000000000000
00000000000000000000000000000000
000000000000
```

### TV-8 — ICMP echo request, G→N, doorbell = 60

10.0.2.15 → 10.0.2.2, id 1, seq 1, payload "SAHARA!!" (8 bytes), IP ID
0x0001 (guest's choice), guest-padded from 50 to 60 bytes.

```
52550a00020252540012345608004500
002400010000400162c80a00020f0a00
02020800e91800010001534148415241
212100000000000000000000
```

### TV-9 — ICMP echo reply, N→G, RX_LEN = 60 (expected reply to TV-8)

id/seq/payload echoed; translator constants (TTL 64, IP ID 0); padded to
60.

```
52540012345652550a00020208004500
002400000000400162c90a0002020a00
020f0000f11800010001534148415241
212100000000000000000000
```

### TV-10 — TCP SYN to a refused destination, G→N, doorbell = 60

10.0.2.15:49152 → 10.0.2.3:80, seq 0x12345678, no options, window 0xFFFF,
guest-padded from 54 to 60.

```
52550a00020252540012345608004500
002800000000400662bf0a00020f0a00
0203c000005012345678000000005002
ffff6ed40000000000000000
```

### TV-11 — TCP RST, N→G, RX_LEN = 60 (expected reply to TV-10)

RST|ACK per §6.7.6: seq 0, ack 0x12345679, window 0; padded to 60.

```
52540012345652550a00020208004500
002800000000400662bf0a0002030a00
020f0050c00000000000123456795014
00006ec10000000000000000
```

### TV-S1 — DHCP handshake sequence (script)

The end-to-end fixture tying TV-3…TV-6 together:

| step | action | expected |
|--:|---|---|
| 1 | read RX_LEN | 0 |
| 2 | copy TV-3 to TX buffer; doorbell 342 | no trap |
| 3 | poll RX_LEN until non-zero (or WFI with timer backstop) | becomes 342 |
| 4 | read RX buffer [0, 342) | == TV-4 exactly |
| 5 | write RX_POP | RX_LEN reads 0 |
| 6 | copy TV-5 to TX buffer; doorbell 342 | no trap |
| 7 | poll RX_LEN until non-zero | becomes 342 |
| 8 | read RX buffer [0, 342) | == TV-6 exactly |
| 9 | write RX_POP | RX_LEN reads 0 |

Trace assertions for the same run: exactly two NIC EVENT records, payloads
== TV-4 and TV-6, cycles strictly greater than their trigger doorbells'
cycles (NIC-C-31/32).

## 10. Cross-document dependencies

| dependency | resolution (integration pass) |
|---|---|
| devspec/trace.md §4.3 | NIC arrival payload = raw frame bytes, `payload_len` = RX_LEN — matches §7.2; device-internal RX-buffer writes produce no trace records (trace.md §2.3.2–§2.3.6: access records are per-instruction) |
| devspec/boot.md §3.6 | device table NIC entry (type 4); params[0] carries the MAC in the boot.md §3.6 packing, identical to §2.5 (value 0x0000_5634_1200_5452 for the reference MAC, both documents) |

Register offsets/widths and window layout are frozen in PLATFORM-SPEC §7;
virtual-time rules are frozen in ISA-SPEC §4 and PLATFORM-SPEC §8. This
document defines nothing owned by another devspec document.
