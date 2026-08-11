#!/usr/bin/env bash
# CC-M1 test suite - headless, both emulators. Usage:
#   [EMU=path] [EMU_PY=1] [CC_ORACLE=0] [UPDATE_GOLDEN=1] \
#       lang/cc/tests/run-tests.sh [case names...]
#
# Assertion layers per case (work-order decision 9; each catches a
# distinct failure class):
#   1. exit contract - stdout exactly "HALT r0=<32 hex of expect>",
#      exit 0, --maxcycles backstop
#   2. abicheck      - every emitted function statically held to the
#      cc-m1.md section 8 frame/register contract
#   3. golden .s     - byte-compare where golden/NAME.s exists
#      (UPDATE_GOLDEN=1 regenerates)
#   4. host oracle   - pure-computation cases also run under gcc
#      (prelude + wrapper); the printed canonical value must equal
#      expect. CC_ORACLE=0 disables with a loud SKIP, never silently.
#   5. trace-q gates - zero ILLEGAL/UNALIGNED/DEVERR/PRIV/PF/PERM and
#      no double fault anywhere; optional per-case syscall count and
#      capture-buffer content
#   6. determinism   - compile twice + cmp .s; run twice + cmp traces
#   7. emu-py leg    - EMU_PY=1 reruns the FULL case set on emu-py
#      asserting the same HALT lines
#
# Case headers (comments in cases/NAME.c):
#   // expect: VALUE        required (any python int literal)
#   // oracle: no           skip the gcc leg (pointer-width/MMIO dep)
#   // fixture: FILE.s      extra text-only .s between sys.s and the unit
#   // maxcycles: N         default 2000000
#   // syscalls: N          assert exactly N TRAP cause-10 records
#   // capture: TEXT        assert the capture buffer holds TEXT (\n ok)
#   // cc-error             negative test: cc.py must reject the file
#
# Boundary: root tests/ and trace-q/ are TOOLCHAIN-OWNED; this suite
# never touches them. A tool gap is a SPEC-ISSUES.md entry and a loud
# SKIP here, never a patch there.

set -u

die() { echo "cc-tests: FATAL: $*" >&2; exit 2; }

HERE="$(cd "$(dirname "$0")" && pwd)"
CC="$(cd "$HERE/.." && pwd)"
ROOT="$(cd "$CC/../.." && pwd)"
EMU="${EMU:-$ROOT/emu-c/bazel-bin/sahara-emu}"
EMU_PY_BIN="$ROOT/emu-py/sahara-emu-py"
TRACEQ="$ROOT/trace-q/trace-q"
ASM="$ROOT/asm/asm.py"
CCPY="$CC/cc.py"
RT="$CC/rt"
OUT="$HERE/out"
CASES="$HERE/cases"
GOLDEN="$HERE/golden"
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
    local src="$1" name base expect oracle fixture maxcy nsys capture
    name="$(basename "$src" .c)"
    wanted "$name" || return 0

    expect=$(hdr "$src" expect | awk '{print $1}')
    oracle=$(hdr "$src" oracle | awk '{print $1}')
    fixture=$(hdr "$src" fixture)
    maxcy=$(hdr "$src" maxcycles); maxcy="${maxcy:-2000000}"
    nsys=$(hdr "$src" syscalls)
    capture=$(hdr "$src" capture)

    # ---- negative tests: cc.py must reject, no output file
    if grep -q '^// cc-error' "$src"; then
        rm -f "$OUT/$name.s"
        if python3 "$CCPY" "$src" -o "$OUT/$name.s" 2>"$OUT/$name.err"; then
            echo "FAIL $name: cc.py accepted a program it must reject"
            note_fail "$name"; return
        fi
        if [ -e "$OUT/$name.s" ]; then
            echo "FAIL $name: error exit but output file exists"
            note_fail "$name"; return
        fi
        grep -q "error:" "$OUT/$name.err" \
            || { echo "FAIL $name: no diagnostic on stderr"
                 note_fail "$name"; return; }
        echo "PASS $name (rejected: $(head -1 "$OUT/$name.err"))"
        pass=$((pass+1)); return
    fi

    [ -n "$expect" ] || { echo "FAIL $name: no // expect:"; note_fail "$name"; return; }
    local exphex; exphex=$(hex32 "$expect")

    # ---- layer 6a: compile twice, byte-identical
    python3 "$CCPY" "$src" -o "$OUT/$name.s" 2>"$OUT/$name.err" \
        || { echo "FAIL $name: cc.py:"; sed 's/^/    /' "$OUT/$name.err"
             note_fail "$name"; return; }
    python3 "$CCPY" "$src" -o "$OUT/$name.2.s" 2>/dev/null
    cmp -s "$OUT/$name.s" "$OUT/$name.2.s" \
        || { echo "FAIL $name: two compiles differ (nondeterminism)"
             note_fail "$name"; return; }

    # ---- layer 2: abicheck on every emitted function
    python3 "$HERE/abicheck.py" "$OUT/$name.s" >/dev/null 2>"$OUT/$name.abi" \
        || { echo "FAIL $name: abicheck:"; sed 's/^/    /' "$OUT/$name.abi"
             note_fail "$name"; return; }

    # ---- layer 3: golden .s
    if [ "${UPDATE_GOLDEN:-0}" = "1" ] && [ -e "$GOLDEN/$name.s" ]; then
        cp "$OUT/$name.s" "$GOLDEN/$name.s"
    fi
    if [ -e "$GOLDEN/$name.s" ]; then
        if ! cmp -s "$OUT/$name.s" "$GOLDEN/$name.s"; then
            echo "FAIL $name: golden .s drift (UPDATE_GOLDEN=1 to accept):"
            diff "$GOLDEN/$name.s" "$OUT/$name.s" | head -8 | sed 's/^/    /'
            note_fail "$name"; return
        fi
    fi

    # ---- assemble (fixture, if any, between sys.s and the unit)
    local fixt=()
    [ -n "$fixture" ] && fixt=("$HERE/fixtures/$fixture")
    python3 "$ASM" -o "$OUT/$name.img" "$RT/crt0.s" "$RT/sys.s" \
        ${fixt[@]+"${fixt[@]}"} "$OUT/$name.s" 2>"$OUT/$name.asmerr" \
        || { echo "FAIL $name: asm:"; sed 's/^/    /' "$OUT/$name.asmerr"
             note_fail "$name"; return; }

    # ---- layers 1+6b: run twice, exit contract, identical traces
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

    # ---- layer 5: trace gates (+ syscall count / capture if declared)
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

    # ---- layer 4: host differential oracle
    if [ "$oracle" != "no" ]; then
        if [ "${CC_ORACLE:-1}" = "0" ]; then
            echo "SKIP $name: oracle leg disabled (CC_ORACLE=0)"
            skip_notes=$((skip_notes+1))
        else
            # two steps: -Dmain=cc_main must not rename the wrapper's main
            { gcc -w -O0 -include "$ORACLE/prelude.h" -Dmain=cc_main \
                  -c "$src" -o "$OUT/$name.o" \
              && gcc -w -O0 "$OUT/$name.o" "$ORACLE/wrapper.c" \
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
        grep -q '^// cc-error' "$src" && continue
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
echo "cc-tests: $pass passed, $fail failed ($skip_notes oracle skips)"
[ $fail -eq 0 ] || { echo "failed:$fail_names"; exit 1; }
