#!/usr/bin/env bash
# Sahara conformance harness. Usage:
#   EMU=path/to/emulator tests/run-tests.sh [test names...]
#
# Relies only on the frozen CLI contract in emu-common-prompt.md:
#   <emulator> IMAGE [--replay f] [--trace f --trace-level N]
#              [--maxcycles N] [--ram BYTES] [--check-invtp]
#              [--check-devorder N]
#   HALT -> "HALT r0=<32 hex digits>" on stdout, exit 0
#   MAXCYCLES -> exit 2; CHECKFAIL -> exit 3.
#
# Every test runs twice and the two traces must be byte-identical
# (determinism is checked here, for free, for both emulators).
# All harness errors are fatal and named. Warnings do not exist.
#
# MANIFEST line: NAME SRC [level=N] [expect=<32 lowercase hex>]
#                [events=GEN.py] [flags]
# expect= overrides the required HALT r0 value for tests that cannot
# reach the 0x600D path (e.g. the triple-fault halt, SPEC-ISSUES 12).
# expect=checkfail marks a test whose CORRECT outcome is a check-mode
# assertion: exit 3, stdout first word CHECKFAIL. Only the class is
# compared — the reason text is implementation-worded (SPEC-ISSUES 23).
# events= marks an EVENT-fed test: tests/events/GEN.py is run with
# the assembled image to emit a feed trace (META + EVENT records,
# trace.md 4/5.1) that every run of the test consumes via --replay —
# the CLI's only headless event-injection path. Such tests need the
# emulator to implement --replay, so they are SKIPPED (loudly,
# counted) unless REPLAY=1.

set -u

die() { echo "run-tests: FATAL: $*" >&2; exit 2; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TESTS="$ROOT/tests"
ASM="$ROOT/asm/asm.py"
TRACEQ="$ROOT/trace-q/trace-q"
OUT="$TESTS/out"
PASS_HEX="0000000000000000000000000000600d"
MAXCYCLES="${MAXCYCLES:-10000000}"

[ -n "${EMU:-}" ] || die "set EMU=path/to/emulator"
command -v "$EMU" >/dev/null 2>&1 || [ -x "$EMU" ] \
    || die "EMU '$EMU' is not executable"
[ -f "$TESTS/MANIFEST" ] || die "missing $TESTS/MANIFEST"
mkdir -p "$OUT" || die "cannot create $OUT"

want_all=1
declare -A want
for t in "$@"; do want_all=0; want[$t]=1; done

pass=0 fail=0 skip=0 ran=0
fail_names=""

run_one() {
    local name="$1" src="$2" level="$3" expect="$4" events="$5"; shift 5
    local flags=("$@")
    local img="$OUT/$name.img" sym="$OUT/$name.sym"
    ran=$((ran+1))

    if ! python3 "$ASM" -o "$img" "$TESTS/defs.s" "$TESTS/$src" 2>"$OUT/$name.asm.err"; then
        echo "FAIL $name: assembly failed:"
        sed 's/^/    /' "$OUT/$name.asm.err"
        return 1
    fi

    # EVENT-fed test: generate the feed trace from the image (the
    # generator writes the image's real sha256 into META so the
    # replayer's trace.md 5.1 validation passes), then every run
    # below consumes it via --replay.
    local replay_args=()
    if [ -n "$events" ]; then
        local evtrc="$OUT/$name.events.trc"
        if ! python3 "$TESTS/events/$events" "$img" "$evtrc" \
                2>"$OUT/$name.ev.err"; then
            echo "FAIL $name: event-feed generation failed:"
            sed 's/^/    /' "$OUT/$name.ev.err"
            return 1
        fi
        replay_args=(--replay "$evtrc")
    fi

    local trc rc out
    for run in a b; do
        trc="$OUT/$name.$run.trc"
        # HARNESS_EXPECT_R0 is not part of the CLI contract; real
        # emulators ignore it. Only the selftest stub reads it (so the
        # expect= plumbing is testable without an emulator).
        out=$(HARNESS_EXPECT_R0="$expect" \
              "$EMU" "$img" ${replay_args[@]+"${replay_args[@]}"} \
              --trace "$trc" --trace-level "$level" \
              --maxcycles "$MAXCYCLES" --check-invtp "${flags[@]}" \
              2>"$OUT/$name.$run.err")
        rc=$?
        ok=1
        if [ "$expect" = "checkfail" ]; then
            # Correct outcome is the check-mode assertion: exit 3 and a
            # stdout line whose first word is CHECKFAIL. The reason text
            # is implementation-worded and NOT compared (SPEC-ISSUES 23).
            [ $rc -eq 3 ] && case "$out" in CHECKFAIL\ *|CHECKFAIL) ;; \
                *) ok=0;; esac || ok=0
        else
            [ $rc -eq 0 ] && [ "$out" = "HALT r0=$expect" ] || ok=0
        fi
        if [ $ok -ne 1 ]; then
            echo "FAIL $name (run $run): rc=$rc stdout='$out'"
            [ -s "$OUT/$name.$run.err" ] && sed 's/^/    stderr: /' \
                "$OUT/$name.$run.err"
            if [ -f "$trc" ]; then
                echo "    failing test ID (last write to 0x700):"
                python3 "$TRACEQ" last-write 0x700 "$trc" 2>/dev/null \
                    | sed 's/^/    /'
                echo "    traps:"
                python3 "$TRACEQ" trapdump "$trc" --sym "$sym" \
                    2>/dev/null | tail -5 | sed 's/^/    /'
            fi
            return 1
        fi
    done

    if ! cmp -s "$OUT/$name.a.trc" "$OUT/$name.b.trc"; then
        echo "FAIL $name: NONDETERMINISM - the two runs' traces differ:"
        python3 "$TRACEQ" diverge "$OUT/$name.a.trc" "$OUT/$name.b.trc" \
            | sed 's/^/    /'
        return 1
    fi

    # Reference-implementation replay check (CONFORMANCE.md: "bit-exact
    # replay of every test's trace"), REPLAY=1-gated so emulators that
    # have not built --replay yet still get the rest of the harness.
    # Per devspec/trace.md 5.1 the --replay input is the recorded
    # trace itself (the replayer consumes its EVENT records and
    # validates META); the replay must reproduce stdout and, per
    # trace.md 5.2/5.3, every post-META record byte-identically —
    # which `diverge` checks (its META comparison already excludes the
    # run-variant mode/image keys). checkfail runs are not replayed:
    # what --replay does after an assertion is nobody's contract.
    if [ "${REPLAY:-0}" = "1" ] && [ "$expect" != "checkfail" ]; then
        local rtrc="$OUT/$name.r.trc"
        out=$(HARNESS_EXPECT_R0="$expect" \
              "$EMU" "$img" --replay "$OUT/$name.a.trc" --trace "$rtrc" \
              --trace-level "$level" --maxcycles "$MAXCYCLES" \
              --check-invtp "${flags[@]}" 2>"$OUT/$name.r.err")
        rc=$?
        if [ $rc -ne 0 ] || [ "$out" != "HALT r0=$expect" ]; then
            echo "FAIL $name (replay): rc=$rc stdout='$out'"
            [ -s "$OUT/$name.r.err" ] && sed 's/^/    stderr: /' \
                "$OUT/$name.r.err"
            return 1
        fi
        # trace-q diverge exit codes (trace.md 6.2): 1 = identical,
        # 0 = divergence found, 2 = malformed/unreadable trace.
        dv=$(python3 "$TRACEQ" diverge "$OUT/$name.a.trc" "$rtrc" \
             2>"$OUT/$name.dv.err")
        dv_rc=$?
        if [ $dv_rc -eq 0 ]; then
            echo "FAIL $name: REPLAY DIVERGENCE from the recorded run:"
            echo "$dv" | sed 's/^/    /'
            return 1
        elif [ $dv_rc -ne 1 ]; then
            echo "FAIL $name: trace-q diverge errored on the replay pair:"
            sed 's/^/    /' "$OUT/$name.dv.err"
            return 1
        fi
    fi

    if [ -x "$TESTS/checks/$name.sh" ]; then
        if ! "$TESTS/checks/$name.sh" "$OUT/$name.a.trc" "$sym" "$img"; then
            echo "FAIL $name: trace-level check checks/$name.sh failed"
            return 1
        fi
    fi
    echo "PASS $name"
    return 0
}

while read -r name src rest; do
    case "$name" in ""|\#*) continue;; esac
    [ $want_all -eq 1 ] || [ -n "${want[$name]:-}" ] || continue
    level=1
    expect="$PASS_HEX"
    events=""
    flags=()
    for tok in $rest; do
        case "$tok" in
            level=*) level="${tok#level=}";;
            expect=*) expect="${tok#expect=}"
                      [[ "$expect" =~ ^([0-9a-f]{32}|checkfail)$ ]] \
                          || die "$name: expect= must be 32 lowercase hex digits or 'checkfail'";;
            events=*) events="${tok#events=}"
                      [ -f "$TESTS/events/$events" ] \
                          || die "$name: events generator tests/events/$events does not exist";;
            *) flags+=("$tok");;
        esac
    done
    if [ -n "$events" ] && [ "${REPLAY:-0}" != "1" ]; then
        # EVENT-fed tests require the emulator to implement --replay;
        # REPLAY=1 is the harness's declaration that it does. Loud,
        # counted, never silent.
        ran=$((ran+1)); skip=$((skip+1))
        echo "SKIP $name: EVENT-fed (needs --replay; set REPLAY=1)"
        continue
    fi
    if run_one "$name" "$src" "$level" "$expect" "$events" \
            ${flags[@]+"${flags[@]}"}; then
        pass=$((pass+1))
    else
        fail=$((fail+1)); fail_names="$fail_names $name"
    fi
done < "$TESTS/MANIFEST"

[ $ran -gt 0 ] || die "no tests matched"
echo
echo "run-tests: $pass passed, $fail failed, $skip skipped (of $ran)"
[ $fail -eq 0 ] || { echo "failed:$fail_names"; exit 1; }
