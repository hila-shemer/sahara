# devspec index

Six detailed device/tooling specifications expanding the frozen inputs
(ISA-SPEC.md, PLATFORM-SPEC.md, TOOLING-SPEC.md, CONFORMANCE.md,
encoding.py). Acceptance test per document: an agent given only that
document plus ISA-SPEC.md can implement the component with zero further
questions. All six documents are present and complete; every document
ends with numbered Conformance requirements and data-shaped Test vectors.
Integration companions: CONFORMANCE-DELTA.md (new test obligations mapped
to CONFORMANCE.md groups) and SPEC-ISSUES.md (19 issues against the
frozen specs, conservative readings recorded — for Hila, not acted on).

## Documents

**display.md** — The display device: XRGB8888 bit/byte-precise (byte
order B,G,R,X; X has no semantics and reads back as stored), memory-like
pixel-buffer semantics, STRIDE constraints, the frame-snapshot definition
and PRESENT semantics derived from ISA-SPEC 9.2's ordering rules (no
guest barrier needed), the full resize state machine (atomic register
update, sticky IRQ flag, latest-wins coalescing, ack-first handler
pattern), letterbox/crop declared cosmetic, and the reserved extension
window with never-repurpose rules. Fixes reference defaults: 16 MB pixel
window, initial mode 640×480×2560. D-01..D-23, vectors V1–V6.

**input.md** — Keyboard and mouse: the full 103-ID USB HID usage subset
(owner), modifiers as ordinary keys, no auto-repeat (host repeat
suppressed), lock keys unlatched, per-key press/release alternation with
synthesized releases on capture loss, mouse full-state events emitted on
clamped-state change, clamping to min(dim−1, 65535), queues exactly 256
deep with drop-newest overflow (drops traced via trace.md's flag byte),
all-ones empty-read sentinel, DEVERR on every store/wrong size/unlisted
offset. INPUT-01..23, vectors incl. event words, overflow, resize-clamp.

**nic.md** — The NIC and its translator: Ethernet II frames without FCS
in either direction, guest-pads-TX / translator-pads-RX to 60, mailbox
state machine (1 exposed + 63 queued, pre-admission overflow drop that
emits no EVENT), DEVERR catalog E1–E7 with check precedence, and the
translator as a normative decision tree with all constants pinned (peer
MAC 52:55:0a:00:02:02, TTL 64, IP ID 0, ISS 0, MSS 1460, 32 TCP / 64 UDP
flows): ARP proxy, DHCP message-by-message, DNS forwarding, UDP/TCP NAT
with full lifecycle and RFC-793-style RSTs, ICMP echo, and eight
normative exclusions (no inbound listen in v1). Cycle-assignment rules
and replay isolation. NIC-C-01..36, eleven byte-exact frame vectors plus
register and handshake scripts.

**boot.md** — Reset hand-off and the device table (owner of the table
layout and the MAC packing): emulator pre-reset obligations, exhaustive
reset-state table, byte-exact header/RAM-region/device-record layouts
with the u128-fields-are-only-8-aligned reading rule, forward
compatibility (refuse unknown version, skip unknown types, zero-means-v1
params growth), RAM-region canonicality rules, hole accesses trap DEVERR,
the normative reference table (region 0 = 240 MB), and a non-normative
annotated boot sequence in Sahara assembly. BOOT-1..17, vectors V1–V9
incl. the 328-byte reference table dump.

**trace.md** — The .trc format byte-exact (framing, fixed payload sizes,
torn-tail vs malformed), the closed 7-key META catalog, ownership of
every device's EVENT payload encoding (keyboard/mouse = event word +
dropped flag byte, NIC = raw frame bytes, resize = width/height/stride/
format u64×4; device = 0-based table index), cycle stamping and per-cycle
emission order (trapping instructions emit TRAP, no EXEC), replay
semantics and what byte-identical quantifies over per level, and trace-q:
CLI, exit codes, line grammar, .sym resolution, disassembly canonical
form. T-01..28, vectors TV-1..TV-10 incl. a complete decoded trace.

**rng.md** — The RNG device (accelerator wave, type 7): one 256-deep
FIFO of 64-bit entropy words fed exclusively by EVENT records
(truncate-to-fit acceptance, recorded = accepted prefix, zero-accepted
records nothing — payload bytes owned by trace.md §4.6), empty-pop
DEVERR (no sentinel — every u64 is a legal word), guest-selected
SplitMix64 PRNG mode as pure architectural state (DEVW-traced MODE/SEED,
no emulator fallback path), IE-qualified level pending into the EXTINT
OR (reset off — invisible to type-7-unaware kernels), DEVERR catalog
E1–E6 with the nic.md precedence chain. Window 0x0F08_0000/64 KB,
params all zero. RNG-01..21 + RNG-R1..R4, vectors incl. the SplitMix64
output table, the truncation byte vector, and the 5-record table dump.

**asm.md** — The assembler: CLI and determinism contract, lexical rules
and reserved names, full EBNF, 128-bit expression semantics with
CONST/ADDR kinds and label-arithmetic legality, per-family assembly rules
(I-form selection, mod syntax, src2=r31 for omitted index, store order
`st.W [ea], rs`), normative pseudo expansions (li minimal chain, la
sticky relaxation, la.abs fixed 6), segment/.org semantics with
device-table-window overlap detection, .img/.sym emission, and the closed
error catalog E001–E049. ASM-1..22, vectors T1 (60 source↔hex pairs)
through T5.

## Ownership matrix (as dispatched; held)

| shared semantic | owner | everyone else |
|---|---|---|
| EVENT payload encodings (all devices) | trace.md | reference, never define |
| RNG queue/PRNG/CTRL semantics, type-7 record defaults | rng.md | reference (payload bytes stay trace.md §4.6's) |
| device register offsets/widths | frozen in PLATFORM-SPEC | reference only |
| instruction encodings | frozen in encoding.py | asm.md shows worked examples, defines nothing |
| HID usage subset | input.md | reference |
| device table layout | boot.md | reference |
| virtual-time/cycle assignment rules | frozen in ISA-SPEC 4 + PLATFORM 8 | nic.md and trace.md elaborate within it |

## Cross-document dependencies (all resolved at integration)

- display.md → trace.md §4.4/§2.3.5/§3.3 (resize payload, device index,
  delivery interleaving); → boot.md §3.5 (type-1 entry).
- input.md → trace.md §4.1–§4.2/§3.3/§5 (payload framing, drop flag,
  same-cycle ordering); → boot.md §3.5 (types 2–3); → display.md
  (WIDTH/HEIGHT for clamping; display bounds dims to 32 bits, so
  input.md's 65535 clamp is load-bearing).
- nic.md → trace.md §4.3 (frame payload; emulator-internal RX writes
  produce no access records); → boot.md §3.6 (MAC packing, identical
  values verified).
- boot.md → asm.md §5.5 (store operand order in the example); → nic.md
  (MAC register reads back the table value); → display.md (pixel-window
  semantics behind params[0]/[1]).
- trace.md → input.md §2.2 (HID subset), → boot.md §5 (reference device
  order 0 display, 1 keyboard, 2 mouse, 3 nic), → nic.md §3/§6.1 (frame
  validity, peer MAC in TV-6), → asm.md §5 (disassembly surface —
  verified in agreement).
- asm.md → none (frozen inputs only).
- rng.md → trace.md §4.6/§3.3/§5.4 (payload bytes, boundary visibility,
  model-recomputed acceptance); → boot.md §3.5/§4.2/§4.3 (record layout,
  positional skip, params growth); → input.md §4 (the queue model it
  instantiates); → nic.md §5.2/§7.1/§7.3 (precedence chain, cycle rules,
  replay isolation).

## Integration fixes applied (referencing doc corrected to its owner)

1. **asm.md T4/§8.2**: image payload offset formula was "40 + 48·nsegs";
   TOOLING-SPEC §1's header is 32 bytes, so it is 32 + 48·nsegs. The T4
   descriptors' file_off bytes (0x88/0xA8 → 0x80/0xA0) now match the
   payload placement, which was already correct.
2. **boot.md §8**: example store syntax flipped to asm.md's pinned
   `st.W [ea], rs` order.
3. **display.md §1**: dropped the claim that the initial mode is recorded
   in trace META (trace.md's v1 catalog is closed and has no such key);
   replay consequence stated instead (see SPEC-ISSUES.md #12).
4. **trace.md TV-6**: rebuilt around nic.md's TV-2 ARP reply — the
   original used a wrong gateway MAC (52:55:00:00:02:02 vs nic.md's
   52:55:0a:00:02:02) and depicted an ARP request the translator never
   sends.
5. All "per devspec/X.md §EVENT/§META" placeholders resolved to concrete
   section numbers; nic.md's MAC-encoding claim now cites boot.md §3.6 as
   owner; nic.md's RX-buffer-writes-not-traced assumption confirmed
   against trace.md §2.3.

Verification performed at integration: encoding samples from asm.md T1/T4
and trace.md TV-1 re-derived from the frozen encoding.py (15/15 match;
encoding.py self-check passes); trace.md's image SHA-256 recomputed and
matching; boot.md V1 table dump field-decoded against §3.3–§3.5; the
rebuilt TV-6 record bytes generated independently. Full re-derivation of
every vector (all 60 T1 rows, NIC checksums, the 449-byte trace) was done
by the authoring scripts and spot-checked, not exhaustively repeated,
here.
