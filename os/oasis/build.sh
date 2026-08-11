#!/usr/bin/env bash
# Build build/oasis.img + .sym. The assembler CLI order below IS the
# section layout (SABI v0 section 6): text | rodata | data | bss, then
# the user program LAST - it opens the .org UBASE segment itself
# (SABI v0.1 A.7). Optional args: user program source, output image.
# Default: user/echo.s -> build/oasis.img; the test suite builds
# build/oasis-<name>.img variants from user/crash_*.s etc.
# Deterministic: generators and asm.py are both byte-stable, so two
# runs produce identical images (the test suite checks this).
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
K="$HERE/kernel"
B="$HERE/build"
mkdir -p "$B"

USER_SRC="${1:-$HERE/user/echo.s}"
OUT_IMG="${2:-$B/oasis.img}"

python3 "$HERE/gen/genfont.py"   "$B/font.s"
python3 "$HERE/gen/genkeymap.py" "$B/keymap.s"

python3 "$ROOT/asm/asm.py" -o "$OUT_IMG" \
    "$K/defs.s" "$K/boot.s" "$K/trap.s" "$K/mmu.s" "$K/kbd.s" "$K/con.s" \
    "$K/shell.s" "$K/sys.s" "$K/lib.s" \
    "$B/font.s" "$B/keymap.s" "$K/rodata.s" \
    "$K/data.s" "$K/bss.s" \
    "$USER_SRC"
echo "built $OUT_IMG"
