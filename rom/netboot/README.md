# The Sahara netboot ROM

A resident tiny OS, not a hardware feature: it owns the machine from
reset, uses the NIC, and its whole v1 job is "the network is the
storage layer" — `sahara-gui` with no image argument boots this ROM,
which fetches a boot image over SBP/1 (sbp.md) and runs it. It boots
ANY OS the server hands it; future versions may carry an OS or
diagnostic environment written INTO the ROM — a fallback shell or
monitor when no server answers. That resident payload does not exist
yet, but the modules are cut so it can reuse them: the console
(font.s + the paint/render section of netboot.s) and the fetch client
are separable pieces behind the boot scan.

Files:

| file | role |
|---|---|
| netboot.s | the ROM: boot scan, SBP client, SAHIMG01 parse + copy-down, error console |
| font.s | 8x16 console font (generated once from the Oasis art, owned here) |
| sbp.md | the SBP/1 protocol — normative, with byte-exact vectors |
| build.sh | assemble + refresh artifacts; `--check` is CI's reproducibility gate |
| netboot.img / .sym | the committed artifact the GUI embeds and materializes |
| VERSION / CHANGELOG.md | version number + artifact sha256; one line per version |
| test/ | CI fixtures: payload.s, mkpayload.py, netboot.script, screencheck.py |

Versioning is cheap hygiene, not ceremony: bump VERSION and add a
CHANGELOG line when the bytes change (build.sh --check catches you if
you forget), so a recorded trace's `image_sha256` always names a ROM
that exists as a file. Replay anchors on the materialized
`<trace>.rom.img` next to the trace, so old sessions replay
regardless of what this directory contains today.
