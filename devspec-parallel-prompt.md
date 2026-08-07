# Sahara detailed hardware specs — parallel authoring prompt

You are the coordinator. The task is to expand the terse platform/tooling
specs into detailed, independently implementable specifications, using
parallel subagents. You write no spec content yourself; you dispatch,
integrate, and consistency-check.

## Inputs (read before dispatching; give every subagent all of them)

`ISA-SPEC.md`, `PLATFORM-SPEC.md`, `TOOLING-SPEC.md`, `CONFORMANCE.md`,
`encoding.py`. These are frozen and authoritative. A subagent that believes
one is wrong or self-contradictory records the issue (see Issues below) and
proceeds with the most conservative reading. No subagent may change them or
contradict them.

If the repo has a dispatched-subagent contract skill, subagents operate
under it.

## Dispatch — six subagents, fully parallel

Each produces one self-contained document under `devspec/`. The test for
"done" is: an agent given only that document plus ISA-SPEC.md could
implement the component with zero further questions. Every document ends
with two mandatory sections: **Conformance requirements** (numbered,
testable statements — these feed CONFORMANCE.md) and **Test vectors**
(concrete bytes/programs with expected results; see below).

1. **`devspec/display.md`** — pixel format precisely (byte order, X byte
   semantics), STRIDE constraints, PRESENT semantics relative to the
   release-fence rule, the resize state machine (event ordering, register
   update atomicity, pending/ack protocol, behavior when resizes outpace
   acks), letterbox/crop statement, the reserved dirty-rect extension
   window (which offsets, what a future version may put there and what it
   may never repurpose).
2. **`devspec/input.md`** — keyboard and mouse. The exact USB HID usage-ID
   subset the platform emits (full table), modifier and repeat policy
   (repeat is host-side or absent — decide and state), event encodings
   bit-precise, queue depth and the overflow-drop rule and its trace
   visibility, empty-read semantics, mouse coordinate clamping at resize
   boundaries, GUI capture/release conventions (non-normative appendix).
3. **`devspec/nic.md`** — frame validity rules, padding, FCS policy (guest
   never sees/computes FCS — state it), the mailbox protocol state machine,
   TX during pending RX, DEVERR conditions. The translator: exactly which
   traffic works — DHCP responder message-by-message, DNS forwarding, UDP
   translation, TCP translation (connection lifecycle, RST/FIN mapping,
   simultaneous-connection limit), ICMP echo; and what does not (no
   inbound listen in v1 — state it). Determinism: how live-mode arrivals
   are assigned cycles, what exactly goes in the EVENT payload (defer
   encoding to the trace owner, reference it), replay isolation guarantee.
4. **`devspec/boot.md`** — device table byte-exact layout with a worked
   hex-dump example, forward-compatibility rules (unknown types, unknown
   header versions, table growth), RAM region semantics (ordering,
   overlap prohibition), reset hand-off restated precisely, and a
   non-normative annotated example boot sequence in Sahara assembly
   (discovers table, sizes RAM, installs vectors, enables MMU).
5. **`devspec/trace.md`** — the binary format byte-exact (endianness,
   alignment, record framing edge cases, truncated-file semantics), META
   key/value catalog, **ownership of the EVENT payload encoding for every
   device** (keyboard, mouse, NIC frame, resize) — bit-precise, replay
   semantics (what is consumed, what must be reproduced, what "byte-
   identical" quantifies over at each trace level), and `trace-q`: exact
   output text format per query, exit codes, `.sym` resolution rules.
6. **`devspec/asm.md`** — full grammar (EBNF), token rules, expression
   evaluation (precedence, label arithmetic legality), every pseudo's
   expansion rules including `li` minimal-chain algorithm and `la`
   range/fallback decision, segment/`.org` semantics and overlap
   detection, the complete error catalog (numbered, with trigger
   conditions), and encoding worked examples: at least 20 instructions
   shown source → 64-bit hex, covering every operand shape, both I-forms,
   predication, mod kinds, each width family.

## Ownership matrix (prevents parallel divergence — include verbatim in
every subagent's instructions)

| shared semantic | owner | everyone else |
|---|---|---|
| EVENT payload encodings (all devices) | trace.md | reference, never define |
| device register offsets/widths | frozen in PLATFORM-SPEC | reference only |
| instruction encodings | frozen in encoding.py | asm.md shows worked examples, defines nothing |
| HID usage subset | input.md | reference |
| device table layout | boot.md | reference |
| virtual-time/cycle assignment rules | frozen in ISA-SPEC 4 + PLATFORM 8 | nic.md and trace.md elaborate within it |

A subagent needing a semantic it doesn't own and can't find: it writes a
**placeholder reference** ("per devspec/trace.md §EVENT") and lists the
dependency in its report — it does not invent a local version.

## Test vectors (mandatory, the highest-value output)

Concrete and checkable: boot.md ships a hex device table; trace.md ships a
hex trace fragment decoded field-by-field; asm.md ships source↔hex pairs;
input.md ships event words for named keys; nic.md ships a DHCP
request/reply byte exchange. These become executable fixtures in the
emulator's test suite — write them as data a test can consume, not prose.

## Integration pass (you, after all six return)

1. Cross-check every reference against its owner: addresses, offsets,
   encodings, names. Any mismatch: fix the *referencing* doc to match the
   owner.
2. Resolve placeholder references now that owners exist.
3. Verify each Conformance-requirements section is numbered, testable, and
   non-duplicative; assemble `devspec/CONFORMANCE-DELTA.md` listing new
   test obligations for the main suite, grouped by CONFORMANCE.md's C-
   groups.
4. Collect every issue raised against the frozen specs into
   `devspec/SPEC-ISSUES.md` — file, section, problem, the conservative
   reading the subagent used. Do not act on them; they are for Hila.
5. Write `devspec/INDEX.md`: one paragraph per document, the ownership
   matrix, and the dependency list.

## Rules

- Specs only. No implementation code anywhere (the boot-sequence assembly
  example and test-vector data are the only executable content).
- Loud-failure policy propagates: where a subagent must choose between
  silent tolerance and a defined error, it chooses the error.
- Determinism constraints propagate to every device behavior described.
- Never push to any remote without asking Hila interactively first, and
  then only to a newly created branch whose name she approved. Local
  commits: one per document plus one for the integration pass.
- Subagents receive: the five input files, their own section above, and
  the ownership matrix. They do not see each other's output; cross-
  references go through the matrix. (Fresh-context implementability is
  the acceptance test, so fresh-context authoring is the honest setup.)
