#!/usr/bin/env bash
# Sahara cross-implementation diff harness. Usage:
#   tests/difftest.sh path/to/emu-A path/to/emu-B [test names...]
#
# Runs the full conformance suite on both emulators at trace level 1
# (per toolchain-prompt) and reports the first trace divergence per
# test via `trace-q diverge` (which excludes the run-variant META keys
# per devspec/trace.md 6.5.6). Every divergence is either a bug in one
# implementation or a spec ambiguity — this output is the project's
# product, treat it accordingly.
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
PASS_HEX="0000000000000000000000000000600d"
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
    # HARNESS_EXPECT_R0: selftest-stub backchannel only; real emulators
    # ignore it (not part of the CLI contract).
    run_out=$(HARNESS_EXPECT_R0="$expect" \
              "$emu" "$img" --trace "$trc" --trace-level 1 \
              --maxcycles "$MAXCYCLES" --check-invtp "$@" 2>"$errf")
    run_rc=$?
}

while read -r name src rest; do
    case "$name" in ""|\#*) continue;; esac
    [ $want_all -eq 1 ] || [ -n "${want[$name]:-}" ] || continue
    flags=()
    expect="$PASS_HEX"
    for tok in $rest; do
        case "$tok" in
            level=*) ;;
            expect=*) expect="${tok#expect=}";;
            *) flags+=("$tok");;
        esac
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

    if [ "$expect" = "checkfail" ]; then
        # Expected-CHECKFAIL class (SPEC-ISSUES 22/23): compare only the
        # outcome class — exit 3 + first stdout word CHECKFAIL. Reason
        # text is implementation-worded and traces near the assertion
        # point are not comparison-stable, so neither is diffed.
        cf_a=0; cf_b=0
        [ $rc_a -eq 3 ] && case "$out_a" in CHECKFAIL\ *|CHECKFAIL) cf_a=1;; esac
        [ $rc_b -eq 3 ] && case "$out_b" in CHECKFAIL\ *|CHECKFAIL) cf_b=1;; esac
        if [ $cf_a -ne $cf_b ]; then
            echo "DIVERGE $name (checkfail class):"
            echo "    A rc=$rc_a '$out_a' | B rc=$rc_b '$out_b'"
            diverged=$((diverged+1))
        elif [ $cf_a -eq 0 ]; then
            echo "SHARED-FAIL $name: neither emulator CHECKFAILed" \
                 "(A rc=$rc_a '$out_a' | B rc=$rc_b '$out_b')"
            shared_fail=$((shared_fail+1))
        else
            echo "IDENTICAL $name (checkfail class; reasons not compared)"
            identical=$((identical+1))
        fi
        continue
    fi

    if [ ! -f "$OUT/$name.A.trc" ] || [ ! -f "$OUT/$name.B.trc" ]; then
        echo "BROKEN $name: missing trace (rc_a=$rc_a rc_b=$rc_b)"
        broken=$((broken+1))
        continue
    fi

    # trace-q diverge exit codes (devspec/trace.md 6.2): 1 = identical,
    # 0 = first divergence printed, 2 = malformed/unreadable trace.
    dv=$(python3 "$TRACEQ" diverge \
         "$OUT/$name.A.trc" "$OUT/$name.B.trc" 2>"$OUT/$name.dv.err")
    dv_rc=$?
    if [ $dv_rc -gt 1 ]; then
        echo "BROKEN $name: trace-q diverge failed:"
        sed 's/^/    /' "$OUT/$name.dv.err"
        broken=$((broken+1))
        continue
    fi
    if [ $dv_rc -eq 0 ] || [ "$out_a" != "$out_b" ] \
        || [ "$rc_a" != "$rc_b" ]; then
        echo "DIVERGE $name:"
        [ "$out_a" != "$out_b" ] || [ "$rc_a" != "$rc_b" ] && \
            echo "    stdout/rc: A rc=$rc_a '$out_a' | B rc=$rc_b '$out_b'"
        [ $dv_rc -eq 0 ] && echo "$dv" | sed 's/^/    /'
        diverged=$((diverged+1))
        continue
    fi
    if [ $rc_a -ne 0 ] || [ "$out_a" != "HALT r0=$expect" ]; then
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
