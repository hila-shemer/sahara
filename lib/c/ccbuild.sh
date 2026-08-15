#!/usr/bin/env bash
# ccbuild.sh - build a libc-using program (the decision-3 recipe):
#
#   lib/c/ccbuild.sh PROG.c -o PROG.img
#
# does exactly:
#
#   cpp -P -nostdinc -I lib/c PROG.c -o OUT/PROG.tu.c
#   python3 lang/cc/cc.py OUT/PROG.tu.c -o OUT/PROG.s
#   python3 asm/asm.py -o PROG.img lang/cc/rt/crt0.s lang/cc/rt/sys.s \
#           OUT/PROG.s
#
# OUT is the directory of PROG.img; the intermediates stay there for
# abicheck and inspection (asm.py drops PROG.sym next to the image).
# cpp handles #include and guards ONLY - the language stays cc-m1
# (owner sign-off note, cc-m1.md 9.7). -P strips linemarkers because
# cc.py has no #line: diagnostics therefore point into the combined
# .tu.c, not the user's file - recorded in SPEC-ISSUES as cc-m2 input.
set -u

die() { echo "ccbuild: $*" >&2; exit 1; }

LIBC="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$LIBC/../.." && pwd)"

SRC="" IMG=""
while [ $# -gt 0 ]; do
    case "$1" in
        -o) [ $# -ge 2 ] || die "-o needs an argument"
            IMG="$2"; shift 2 ;;
        -*) die "unknown option '$1' (usage: ccbuild.sh PROG.c -o PROG.img)" ;;
        *)  [ -z "$SRC" ] || die "one input file only ('$SRC' and '$1')"
            SRC="$1"; shift ;;
    esac
done
[ -n "$SRC" ] && [ -n "$IMG" ] || die "usage: ccbuild.sh PROG.c -o PROG.img"
[ -f "$SRC" ] || die "no such file: $SRC"

OUT="$(dirname "$IMG")"
BASE="$(basename "$SRC" .c)"
mkdir -p "$OUT" || die "cannot create $OUT"

cpp -P -nostdinc -I "$LIBC" "$SRC" -o "$OUT/$BASE.tu.c" \
    || die "cpp failed on $SRC"
python3 "$ROOT/lang/cc/cc.py" "$OUT/$BASE.tu.c" -o "$OUT/$BASE.s" \
    || die "cc.py failed on $OUT/$BASE.tu.c"
python3 "$ROOT/asm/asm.py" -o "$IMG" \
    "$ROOT/lang/cc/rt/crt0.s" "$ROOT/lang/cc/rt/sys.s" "$OUT/$BASE.s" \
    || die "asm.py failed"
