#!/usr/bin/env bash
# Sahara cross-implementation diff harness. Usage:
#   tests/difftest.sh path/to/emu-A path/to/emu-B [test names...]
#
# Runs the full conformance suite on both emulators at trace level 1
# (per toolchain-prompt) and reports the first trace divergence per
# test via `trace-q diverge --ignore-meta`. Every divergence is either
# a bug in one implementation or a spec ambiguity — this output is the
# project's product, treat it accordingly.
#
# stdout ("HALT r0=...") is compared too. A test failing *identically*
# on both is a shared failure, reported but distinct from a divergence.

set -u

die() { echo "difftest: FATAL: $*" >&2; exit 2; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TESTS="$ROOT/tests"
ASM="$ROOT/asm/asm.py"
TRACEQ="$ROOT/trace-q/trace-q"
OUT="$TESTS/out/diff"
PASS_LINE="HALT r0=0000000000000000000000000000600d"
MAXCYCLES="${MAXCYCLES:-10000000}"

[ $# -ge 2 ] || die "usage: difftest.sh EMU_A EMU_B [test names...]"
EMU_A="$1"; EMU_B="$2"; shift 2
for e in "$EMU_A" "$EMU_B"; do
    command -v "$e" >/dev/null 2>&1 || [ -x "$e" ] \
        || die "'$e' is not executable"
done
[ -f "$TESTS/MANIFEST" ] || die "missing $TESTS/MANIFEST"
mkdir -p "$OUT" || die "cannot create $OUT"

want_all=1
declare -A want
for t in "$@"; do want_all=0; want[$t]=1; done

identical=0 diverged=0 shared_fail=0 broken=0 ran=0

run_emu() {  # emu img trace flags... -> stdout to $run_out, rc in $run_rc
    local emu="$1" img="$2" trc="$3" errf="$4"; shift 4
    run_out=$("$emu" "$img" --trace "$trc" --trace-level 1 \
              --maxcycles "$MAXCYCLES" --check-invtp "$@" 2>"$errf")
    run_rc=$?
}

while read -r name src rest; do
    case "$name" in ""|\#*) continue;; esac
    [ $want_all -eq 1 ] || [ -n "${want[$name]:-}" ] || continue
    flags=()
    for tok in $rest; do
        case "$tok" in level=*) ;; *) flags+=("$tok");; esac
    done
    ran=$((ran+1))
    img="$OUT/$name.img"
    if ! python3 "$ASM" -o "$img" "$TESTS/defs.s" "$TESTS/$src" 2>"$OUT/$name.asm.err"; then
        echo "BROKEN $name: assembly failed:"
        sed 's/^/    /' "$OUT/$name.asm.err"
        broken=$((broken+1))
        continue
    fi
    run_emu "$EMU_A" "$img" "$OUT/$name.A.trc" "$OUT/$name.A.err" \
        ${flags[@]+"${flags[@]}"}
    out_a="$run_out" rc_a=$run_rc
    run_emu "$EMU_B" "$img" "$OUT/$name.B.trc" "$OUT/$name.B.err" \
        ${flags[@]+"${flags[@]}"}
    out_b="$run_out" rc_b=$run_rc

    if [ ! -f "$OUT/$name.A.trc" ] || [ ! -f "$OUT/$name.B.trc" ]; then
        echo "BROKEN $name: missing trace (rc_a=$rc_a rc_b=$rc_b)"
        broken=$((broken+1))
        continue
    fi

    dv=$(python3 "$TRACEQ" diverge --ignore-meta \
         "$OUT/$name.A.trc" "$OUT/$name.B.trc" --sym "$OUT/$name.sym" \
         2>"$OUT/$name.dv.err")
    dv_rc=$?
    if [ $dv_rc -gt 1 ]; then
        echo "BROKEN $name: trace-q diverge failed:"
        sed 's/^/    /' "$OUT/$name.dv.err"
        broken=$((broken+1))
        continue
    fi
    if [ $dv_rc -eq 1 ] || [ "$out_a" != "$out_b" ] \
        || [ "$rc_a" != "$rc_b" ]; then
        echo "DIVERGE $name:"
        [ "$out_a" != "$out_b" ] || [ "$rc_a" != "$rc_b" ] && \
            echo "    stdout/rc: A rc=$rc_a '$out_a' | B rc=$rc_b '$out_b'"
        [ $dv_rc -eq 1 ] && echo "$dv" | sed 's/^/    /'
        diverged=$((diverged+1))
        continue
    fi
    if [ $rc_a -ne 0 ] || [ "$out_a" != "$PASS_LINE" ]; then
        echo "SHARED-FAIL $name: both agree, both fail " \
             "(rc=$rc_a stdout='$out_a')"
        shared_fail=$((shared_fail+1))
        continue
    fi
    echo "IDENTICAL $name"
    identical=$((identical+1))
done < "$TESTS/MANIFEST"

[ $ran -gt 0 ] || die "no tests matched"
echo
echo "difftest: $identical identical, $diverged diverged," \
     "$shared_fail shared failures, $broken broken (of $ran)"
[ $((diverged + broken)) -eq 0 ] || exit 1
