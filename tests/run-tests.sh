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
# MANIFEST line: NAME SRC [level=N] [expect=<32 lowercase hex>] [flags]
# expect= overrides the required HALT r0 value for tests that cannot
# reach the 0x600D path (e.g. the triple-fault halt, SPEC-ISSUES 12).
# expect=checkfail marks a test whose CORRECT outcome is a check-mode
# assertion: exit 3, stdout first word CHECKFAIL. Only the class is
# compared — the reason text is implementation-worded (SPEC-ISSUES 23).

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

pass=0 fail=0 ran=0
fail_names=""

run_one() {
    local name="$1" src="$2" level="$3" expect="$4"; shift 4
    local flags=("$@")
    local img="$OUT/$name.img" sym="$OUT/$name.sym"
    ran=$((ran+1))

    if ! python3 "$ASM" -o "$img" "$TESTS/defs.s" "$TESTS/$src" 2>"$OUT/$name.asm.err"; then
        echo "FAIL $name: assembly failed:"
        sed 's/^/    /' "$OUT/$name.asm.err"
        return 1
    fi

    local trc rc out
    for run in a b; do
        trc="$OUT/$name.$run.trc"
        # HARNESS_EXPECT_R0 is not part of the CLI contract; real
        # emulators ignore it. Only the selftest stub reads it (so the
        # expect= plumbing is testable without an emulator).
        out=$(HARNESS_EXPECT_R0="$expect" \
              "$EMU" "$img" --trace "$trc" --trace-level "$level" \
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
    flags=()
    for tok in $rest; do
        case "$tok" in
            level=*) level="${tok#level=}";;
            expect=*) expect="${tok#expect=}"
                      [[ "$expect" =~ ^([0-9a-f]{32}|checkfail)$ ]] \
                          || die "$name: expect= must be 32 lowercase hex digits or 'checkfail'";;
            *) flags+=("$tok");;
        esac
    done
    if run_one "$name" "$src" "$level" "$expect" ${flags[@]+"${flags[@]}"}; then
        pass=$((pass+1))
    else
        fail=$((fail+1)); fail_names="$fail_names $name"
    fi
done < "$TESTS/MANIFEST"

[ $ran -gt 0 ] || die "no tests matched"
echo
echo "run-tests: $pass passed, $fail failed (of $ran)"
[ $fail -eq 0 ] || { echo "failed:$fail_names"; exit 1; }
