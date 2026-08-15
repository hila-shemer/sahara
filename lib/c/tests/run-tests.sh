#!/usr/bin/env bash
# lib/c test suite - headless, both emulators, shaped like
# lang/cc/tests/run-tests.sh (imitated, never modified). Usage:
#   [EMU=path] [EMU_PY=1] [CC_ORACLE=0] lib/c/tests/run-tests.sh [names...]
#
# Assertion layers per case (work-order decision 6):
#   1. exit contract - stdout exactly "HALT r0=<32 hex of expect>",
#      exit 0, --maxcycles backstop
#   2. abicheck      - lang/cc/tests/abicheck.py invoked by path on the
#      compiled TU (read-only reuse); the whole libc rides along in
#      every case
#   3. determinism   - compile twice + cmp .s; run twice + cmp traces
#   4. trace-q gates - zero ILLEGAL/UNALIGNED/DEVERR/PRIV/PF/PERM, no
#      double fault (UNALIGNED is the mis-aligned-malloc canary)
#   5. host oracle   - the include-guard trick: the prelude pre-defines
#      LIBC_C so #include "libc.c" vanishes and mem*/str* resolve to
#      the HOST's libc. CC_ORACLE=0 disables with a loud SKIP.
#   6. capture       - // capture: + // syscalls: against sys_cap via
#      .sym + trace-q last-write, the cc-suite mechanism
#   7. emu-py leg    - EMU_PY=1 reruns the full set, same HALT lines
#
# Case headers (comments in cases/NAME.c):
#   // expect: VALUE     required (any python int literal)
#   // oracle: no        skip the host leg (allocator/conv/print cases)
#   // maxcycles: N      default 2000000 (backstop, not budget)
#   // syscalls: N       assert exactly N TRAP cause-10 records
#   // capture: TEXT     assert the capture buffer holds TEXT (\n ok)
#
# Boundary: root tests/ and trace-q/ are TOOLCHAIN-OWNED; lang/cc/ is
# the cc stream's. This suite reads them, patches nothing.

set -u

die() { echo "libc-tests: FATAL: $*" >&2; exit 2; }

HERE="$(cd "$(dirname "$0")" && pwd)"
LIBC="$(cd "$HERE/.." && pwd)"
ROOT="$(cd "$LIBC/../.." && pwd)"
EMU="${EMU:-$ROOT/emu-c/bazel-bin/sahara-emu}"
EMU_PY_BIN="$ROOT/emu-py/sahara-emu-py"
TRACEQ="$ROOT/trace-q/trace-q"
CCPY="$ROOT/lang/cc/cc.py"
ABICHECK="$ROOT/lang/cc/tests/abicheck.py"
WRAPPER="$ROOT/lang/cc/tests/oracle/wrapper.c"
OUT="$HERE/out"
CASES="$HERE/cases"
ORACLE="$HERE/oracle"

[ -x "$EMU" ] || die "EMU '$EMU' is not executable (cd emu-c && ./build.sh)"
mkdir -p "$OUT" || die "cannot create $OUT"

want_all=1
declare -A want
for t in "$@"; do want_all=0; want[$t]=1; done
wanted() { [ $want_all -eq 1 ] || [ -n "${want[$1]:-}" ]; }

pass=0 fail=0 skip_notes=0
fail_names=""
note_fail() { fail=$((fail+1)); fail_names="$fail_names $1"; }

hex32() { python3 -c "import sys; print(format(int(sys.argv[1],0)%(1<<128),'032x'))" "$1"; }

hdr() {  # hdr FILE KEY -> value or empty
    sed -n "s|^// $2: *||p" "$1" | head -1
}

check_tq_gates() {  # trace [nsyscalls]
    local trc="$1" nsys="${2:-}" dump got
    dump=$(python3 "$TRACEQ" trapdump "$trc" 2>/dev/null) || dump=""
    if grep -qE 'cause=(ILLEGAL|DEVERR|UNALIGNED|PRIV|PF_|PERM_)' <<<"$dump"; then
        echo "    forbidden trap:"
        grep -E 'cause=(ILLEGAL|DEVERR|UNALIGNED|PRIV|PF_|PERM_)' <<<"$dump" \
            | head -3 | sed 's/^/      /'
        return 1
    fi
    if grep -qE 'tl=[23]' <<<"$dump"; then
        echo "    double/triple fault in trapdump"
        return 1
    fi
    if [ -n "$nsys" ]; then
        got=$(grep -c 'cause=SYSCALL' <<<"$dump" || true)
        if [ "$got" != "$nsys" ]; then
            echo "    syscall count: want $nsys, got $got"
            return 1
        fi
    fi
    return 0
}

check_capture() {  # trace sym expected-text(with \n escapes)
    local trc="$1" sym="$2" text="$3" cap len i n addr line val want
    cap=$(awk '$3=="sys_cap"{print $1}' "$sym")
    len=$(awk '$3=="sys_cap_len"{print $1}' "$sym")
    [ -n "$cap" ] && [ -n "$len" ] || { echo "    sys_cap not in .sym"; return 1; }
    n=$(printf '%b' "$text" | wc -c)
    line=$(python3 "$TRACEQ" last-write "0x$len" "$trc") \
        || { echo "    sys_cap_len never written"; return 1; }
    val=$(sed 's/.*val=0x\([0-9a-f]*\).*/\1/' <<<"$line")
    want=$(printf '%032x' "$n")
    [ "$val" = "$want" ] || { echo "    sys_cap_len=$val want=$want"; return 1; }
    i=0
    while [ $i -lt $n ]; do
        addr=$(python3 -c "print(format(int('$cap',16)+$i,'032x'))")
        line=$(python3 "$TRACEQ" last-write "0x$addr" "$trc") \
            || { echo "    capture byte $i never written"; return 1; }
        val=$(sed 's/.*val=0x\([0-9a-f]*\).*/\1/' <<<"$line")
        want=$(printf '%b' "$text" | od -An -v -tx1 | tr -d ' \n' \
               | cut -c$((2*i+1))-$((2*i+2)))
        if [ "${val: -2}" != "$want" ]; then
            echo "    capture byte $i: got ${val: -2}, want $want"
            return 1
        fi
        i=$((i+1))
    done
    return 0
}

run_case() {
    local src="$1" name expect oracle maxcy nsys capture
    name="$(basename "$src" .c)"
    wanted "$name" || return 0

    expect=$(hdr "$src" expect | awk '{print $1}')
    oracle=$(hdr "$src" oracle | awk '{print $1}')
    maxcy=$(hdr "$src" maxcycles); maxcy="${maxcy:-2000000}"
    nsys=$(hdr "$src" syscalls)
    capture=$(hdr "$src" capture)

    [ -n "$expect" ] || { echo "FAIL $name: no // expect:"; note_fail "$name"; return; }
    local exphex; exphex=$(hex32 "$expect")

    # ---- build via the developer-facing recipe (ccbuild.sh IS the
    # product; the suite dogfoods it rather than inlining the steps)
    if ! "$LIBC/ccbuild.sh" "$src" -o "$OUT/$name.img" \
            >"$OUT/$name.builderr" 2>&1; then
        echo "FAIL $name: ccbuild:"; sed 's/^/    /' "$OUT/$name.builderr" | head -5
        note_fail "$name"; return
    fi

    # ---- layer 3a: second cpp+cc pass, byte-identical .s. Same TU
    # basename in a subdir - cc.py stamps the input basename into its
    # header comment, so the names must match for cmp to mean anything.
    mkdir -p "$OUT/det"
    cpp -P -nostdinc -I "$LIBC" "$src" -o "$OUT/det/$name.tu.c" 2>/dev/null
    python3 "$CCPY" "$OUT/det/$name.tu.c" -o "$OUT/det/$name.s" 2>/dev/null
    if ! cmp -s "$OUT/$name.s" "$OUT/det/$name.s"; then
        echo "FAIL $name: two compiles differ (nondeterminism)"
        note_fail "$name"; return
    fi

    # ---- layer 2: abicheck on every emitted function (libc included)
    python3 "$ABICHECK" "$OUT/$name.s" >/dev/null 2>"$OUT/$name.abi" \
        || { echo "FAIL $name: abicheck:"; sed 's/^/    /' "$OUT/$name.abi"
             note_fail "$name"; return; }

    # ---- layers 1+3b: run twice, exit contract, identical traces
    local out rc run
    for run in a b; do
        out=$("$EMU" "$OUT/$name.img" --trace "$OUT/$name.$run.trc" \
              --trace-level 1 --check-invtp --maxcycles "$maxcy" \
              2>"$OUT/$name.emuerr"); rc=$?
        if [ $rc -ne 0 ] || [ "$out" != "HALT r0=$exphex" ]; then
            echo "FAIL $name (run $run): rc=$rc stdout='$out'" \
                 "want 'HALT r0=$exphex'"
            [ -s "$OUT/$name.emuerr" ] \
                && sed 's/^/    stderr: /' "$OUT/$name.emuerr" | head -3
            python3 "$TRACEQ" trapdump "$OUT/$name.$run.trc" \
                --sym "$OUT/$name.sym" 2>/dev/null | tail -3 | sed 's/^/    /'
            note_fail "$name"; return
        fi
    done
    cmp -s "$OUT/$name.a.trc" "$OUT/$name.b.trc" \
        || { echo "FAIL $name: NONDETERMINISM between identical runs"
             note_fail "$name"; return; }

    # ---- layer 4: trace gates (+ syscall count / capture if declared)
    if ! check_tq_gates "$OUT/$name.a.trc" "$nsys"; then
        echo "FAIL $name: trace-q gates"
        note_fail "$name"; return
    fi
    if [ -n "$capture" ]; then
        if ! check_capture "$OUT/$name.a.trc" "$OUT/$name.sym" "$capture"; then
            echo "FAIL $name: capture buffer"
            note_fail "$name"; return
        fi
    fi

    # ---- layer 5: host differential oracle (include-guard trick)
    if [ "$oracle" != "no" ]; then
        if [ "${CC_ORACLE:-1}" = "0" ]; then
            echo "SKIP $name: oracle leg disabled (CC_ORACLE=0)"
            skip_notes=$((skip_notes+1))
        else
            { gcc -w -O0 -std=gnu11 -include "$ORACLE/prelude.h" \
                  -Dmain=cc_main -I "$LIBC" -c "$src" -o "$OUT/$name.o" \
              && gcc -w -O0 "$OUT/$name.o" "$WRAPPER" \
                  -o "$OUT/$name.host"; } 2>"$OUT/$name.gccerr" \
                || { echo "FAIL $name: oracle build:"
                     sed 's/^/    /' "$OUT/$name.gccerr" | head -5
                     note_fail "$name"; return; }
            local hostout
            hostout=$("$OUT/$name.host")
            if [ "$hostout" != "$exphex" ]; then
                echo "FAIL $name: oracle disagrees: host=$hostout" \
                     "sahara/expect=$exphex"
                note_fail "$name"; return
            fi
        fi
    fi

    echo "PASS $name"
    pass=$((pass+1))
}

for src in "$CASES"/*.c; do
    run_case "$src"
done

# ---- layer 7: emu-py leg - full case set, same HALT assertions
if [ "${EMU_PY:-0}" = "1" ]; then
    [ -x "$EMU_PY_BIN" ] || die "emu-py not found at $EMU_PY_BIN"
    for src in "$CASES"/*.c; do
        name="$(basename "$src" .c)"
        wanted "$name" || continue
        [ -f "$OUT/$name.img" ] || continue
        expect=$(hdr "$src" expect); exphex=$(hex32 "$expect")
        maxcy=$(hdr "$src" maxcycles); maxcy="${maxcy:-2000000}"
        out=$("$EMU_PY_BIN" "$OUT/$name.img" --maxcycles "$maxcy" \
              2>"$OUT/$name.pyerr"); rc=$?
        if [ $rc -ne 0 ] || [ "$out" != "HALT r0=$exphex" ]; then
            echo "FAIL emu_py_$name: rc=$rc stdout='$out'"
            [ -s "$OUT/$name.pyerr" ] \
                && sed 's/^/    stderr: /' "$OUT/$name.pyerr" | head -3
            note_fail "emu_py_$name"
        else
            echo "PASS emu_py_$name"
            pass=$((pass+1))
        fi
    done
fi

echo
echo "libc-tests: $pass passed, $fail failed ($skip_notes oracle skips)"
[ $fail -eq 0 ] || { echo "failed:$fail_names"; exit 1; }
