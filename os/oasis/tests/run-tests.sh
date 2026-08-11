#!/usr/bin/env bash
# Oasis M1 test suite - headless, front-end-free. Usage:
#   [EMU=path] [EMU_PY=1] os/oasis/tests/run-tests.sh [test names...]
#
# EMU defaults to emu-c/bazel-bin/sahara-emu (the primary harness).
# EMU_PY=1 adds the emu-py smoke leg (one boot-to-shell-to-halt feed,
# kept small - emu-py runs ~50 KIPS).
#
# Assertion layers per test (each catches a distinct failure class):
#   1. exit contract   - stdout exactly "HALT r0=<32 hex>", exit 0
#   2. dbg_status      - ordered boot-stage MEMW sequence, each stage
#                        exactly once, via the .sym sidecar + trace-q
#   3. framebuffer     - fbcheck.py text-decodes the glyph grid from
#                        the trace's pixbuf DEVW records (+ one golden
#                        PPM byte-compare on the smoke test)
#   4. trace-q gates   - zero ILLEGAL/DEVERR/double-fault anywhere;
#                        EXTINT >= per-feed bound; TRAP cause 10 count
#                        == the feed's expected syscall count
#   5. determinism     - every run twice, traces byte-identical (cmp);
#                        record->replay identity (the produced trace
#                        re-replays byte-identically, trace.md 5.2)
#
# Boundary: tests/ and trace-q/ at the repo root are TOOLCHAIN-OWNED.
# This suite never modifies them - if a tool bug blocks a test, it is
# a SPEC-ISSUES.md entry and a loud SKIP here, never a patch there.

set -u

die() { echo "oasis-tests: FATAL: $*" >&2; exit 2; }

HERE="$(cd "$(dirname "$0")" && pwd)"
OASIS="$(cd "$HERE/.." && pwd)"
ROOT="$(cd "$OASIS/../.." && pwd)"
EMU="${EMU:-$ROOT/emu-c/bazel-bin/sahara-emu}"
EMU_PY_BIN="$ROOT/emu-py/sahara-emu-py"
TRACEQ="$ROOT/trace-q/trace-q"
ASM="$ROOT/asm/asm.py"
OUT="$HERE/out"
FEEDS="$HERE/feeds"
IMG="$OASIS/build/oasis.img"
SYM="$OASIS/build/oasis.sym"
MAXCYCLES="${MAXCYCLES:-20000000}"
PASS_HEX="0000000000000000000000000000600d"

[ -x "$EMU" ] || command -v "$EMU" >/dev/null 2>&1 \
    || die "EMU '$EMU' is not executable (build emu-c first)"
mkdir -p "$OUT" "$FEEDS" || die "cannot create work dirs"

want_all=1
declare -A want
for t in "$@"; do want_all=0; want[$t]=1; done
wanted() { [ $want_all -eq 1 ] || [ -n "${want[$1]:-}" ]; }

pass=0 fail=0 drift_notes=0
fail_names=""
note_fail() { fail=$((fail+1)); fail_names="$fail_names $1"; }

# ---- build, twice: images must be byte-identical (deterministic
# toolchain + deterministic generators)
if wanted build; then
    "$OASIS/build.sh" >/dev/null || die "build failed"
    cp "$IMG" "$OUT/oasis.first.img"
    "$OASIS/build.sh" >/dev/null || die "rebuild failed"
    if cmp -s "$IMG" "$OUT/oasis.first.img"; then
        echo "PASS build (two builds byte-identical)"
        pass=$((pass+1))
    else
        echo "FAIL build: two builds differ"
        note_fail build
    fi
else
    [ -f "$IMG" ] || "$OASIS/build.sh" >/dev/null || die "build failed"
fi

# ---- helpers ---------------------------------------------------------

run_emu() {  # rc in $?, stdout echoed; args: img out.trc extra...
    local img="$1" trc="$2"; shift 2
    "$EMU" "$img" --trace "$trc" --trace-level 1 --check-invtp \
        --maxcycles "$MAXCYCLES" "$@" 2>"$trc.err"
}

check_dbg_status() {  # trace sym -> asserts stage sequence 1..5 (M2:
    # 1 table-ok, 2 vectors-on, 3 mmu-on, 4 irq-on, 5 shell-ready)
    local trc="$1" sym="$2" addr from line cycle val want wanthex
    addr=$(awk '$2=="D" && $3=="dbg_status"{print $1}' "$sym")
    [ -n "$addr" ] || { echo "    dbg_status missing from .sym"; return 1; }
    from=0
    for want in 1 2 3 4 5; do
        line=$(python3 "$TRACEQ" find --touched "0x$addr" --from "$from" \
               "$trc") || { echo "    dbg_status: stage $want missing"; return 1; }
        cycle=$(sed 's/.*cycle=\([0-9]*\).*/\1/' <<<"$line")
        val=$(sed 's/.*val=0x\([0-9a-f]*\).*/\1/' <<<"$line")
        wanthex=$(printf "%032x" "$want")
        if [ "$val" != "$wanthex" ]; then
            echo "    dbg_status: stage $want saw val=$val"
            return 1
        fi
        from=$((cycle+1))
    done
    if python3 "$TRACEQ" find --touched "0x$addr" --from "$from" "$trc" \
            >/dev/null 2>&1; then
        echo "    dbg_status: unexpected 6th write"
        return 1
    fi
    return 0
}

check_tq_gates() {  # trace -> zero ILLEGAL/DEVERR/double-fault
    local trc="$1" dump
    dump=$(python3 "$TRACEQ" trapdump "$trc" 2>/dev/null) || true
    if grep -qE 'cause=(ILLEGAL|DEVERR|UNALIGNED|PRIV|PF_|PERM_)' <<<"$dump"; then
        echo "    forbidden trap in trapdump:"
        grep -E 'cause=(ILLEGAL|DEVERR|UNALIGNED|PRIV|PF_|PERM_)' <<<"$dump" \
            | head -3 | sed 's/^/      /'
        return 1
    fi
    if grep -qE 'tl=[23]' <<<"$dump"; then
        echo "    double/triple fault in trapdump"
        return 1
    fi
    return 0
}

# run_feed_test NAME EXPECT_HEX fbcheck-args...
run_feed_test() {
    local name="$1" expect="$2"; shift 2
    wanted "$name" || return 0
    local feed="$FEEDS/$name.trc" meta syscalls minext out rc run trc

    meta=$(python3 "$HERE/mkfeed.py" "$name" "$IMG" "$feed") \
        || { echo "FAIL $name: mkfeed"; note_fail "$name"; return; }
    syscalls=$(sed -n 's/^SYSCALLS=//p' <<<"$meta")
    minext=$(sed -n 's/^MIN_EXTINT=//p' <<<"$meta")

    for run in a b; do
        trc="$OUT/$name.$run.trc"
        out=$(run_emu "$IMG" "$trc" --replay "$feed"); rc=$?
        if [ $rc -ne 0 ] || [ "$out" != "HALT r0=$expect" ]; then
            echo "FAIL $name (run $run): rc=$rc stdout='$out'"
            [ -s "$trc.err" ] && sed 's/^/    stderr: /' "$trc.err" | head -5
            python3 "$TRACEQ" trapdump "$trc" --sym "$SYM" 2>/dev/null \
                | tail -5 | sed 's/^/    /'
            note_fail "$name"; return
        fi
    done

    if ! cmp -s "$OUT/$name.a.trc" "$OUT/$name.b.trc"; then
        echo "FAIL $name: NONDETERMINISM between identical runs:"
        python3 "$TRACEQ" diverge "$OUT/$name.a.trc" "$OUT/$name.b.trc" \
            | sed 's/^/    /'
        note_fail "$name"; return
    fi

    # record->replay identity (trace.md 5.2/5.3). replaycmp.py accepts
    # exactly one divergence shape: the WFI-stall EVENT restamp drift
    # of root SPEC-ISSUES 35 (an emulator bug this branch may not fix;
    # emu-c/emu-py are out of scope). Everything else fails. Once 35
    # is resolved the drift path dies and this becomes byte-identity.
    out=$(run_emu "$IMG" "$OUT/$name.r.trc" --replay "$OUT/$name.a.trc"); rc=$?
    if [ $rc -ne 0 ] || [ "$out" != "HALT r0=$expect" ]; then
        echo "FAIL $name (replay): rc=$rc stdout='$out'"
        note_fail "$name"; return
    fi
    python3 "$HERE/replaycmp.py" "$OUT/$name.a.trc" "$OUT/$name.r.trc" \
        >"$OUT/$name.dv" 2>&1
    case $? in
        0) ;;
        3) echo "NOTE $name: replay identity degraded to known-drift" \
                "(root SPEC-ISSUES 35)"
           drift_notes=$((drift_notes+1));;
        *) echo "FAIL $name: record->replay divergence:"
           sed 's/^/    /' "$OUT/$name.dv" | head -5
           note_fail "$name"; return;;
    esac

    if ! check_dbg_status "$OUT/$name.a.trc" "$SYM"; then
        echo "FAIL $name: dbg_status sequence"
        note_fail "$name"; return
    fi
    if ! check_tq_gates "$OUT/$name.a.trc"; then
        echo "FAIL $name: trace-q gates"
        note_fail "$name"; return
    fi
    if ! python3 "$HERE/fbcheck.py" "$OUT/$name.a.trc" \
            --syscalls "$syscalls" --min-extint "$minext" --min-timer 1 \
            "$@" >"$OUT/$name.fb" 2>&1; then
        echo "FAIL $name: fbcheck:"
        sed 's/^/    /' "$OUT/$name.fb" | tail -40
        note_fail "$name"; return
    fi
    echo "PASS $name"
    pass=$((pass+1))
}

# run_boot_fail NAME EXPECT_HEX TABLE_S_BODY
# Boot-failure tests: the kernel validates a device table copy placed
# at 0x20000 by a build variant (DT_BASE moved). The real table at
# 0x800 is untouched; only the validation paths differ.
run_boot_fail() {
    local name="$1" expect="$2" body="$3"
    wanted "$name" || return 0
    local img="$OUT/$name.img" out rc run trc
    sed 's/DT_BASE, *0x800$/DT_BASE,        0x20000/' \
        "$OASIS/kernel/defs.s" > "$OUT/$name.defs.s" \
        || die "defs variant generation"
    grep -q 0x20000 "$OUT/$name.defs.s" || die "$name: DT_BASE sed missed"
    printf '%s\n' "$body" > "$OUT/$name.table.s"
    python3 "$ASM" -o "$img" \
        "$OUT/$name.defs.s" "$OASIS/kernel/boot.s" "$OASIS/kernel/trap.s" \
        "$OASIS/kernel/mmu.s" \
        "$OASIS/kernel/kbd.s" "$OASIS/kernel/con.s" "$OASIS/kernel/shell.s" \
        "$OASIS/kernel/sys.s" "$OASIS/kernel/lib.s" \
        "$OASIS/build/font.s" "$OASIS/build/keymap.s" \
        "$OASIS/kernel/rodata.s" "$OASIS/kernel/data.s" \
        "$OASIS/kernel/bss.s" "$OASIS/user/echo.s" "$OUT/$name.table.s" \
        2>"$OUT/$name.asm.err" \
        || { echo "FAIL $name: assembly:"; sed 's/^/    /' \
             "$OUT/$name.asm.err"; note_fail "$name"; return; }
    for run in a b; do
        trc="$OUT/$name.$run.trc"
        out=$(run_emu "$img" "$trc"); rc=$?
        if [ $rc -ne 0 ] || [ "$out" != "HALT r0=$expect" ]; then
            echo "FAIL $name (run $run): rc=$rc stdout='$out'"
            note_fail "$name"; return
        fi
    done
    cmp -s "$OUT/$name.a.trc" "$OUT/$name.b.trc" \
        || { echo "FAIL $name: NONDETERMINISM"; note_fail "$name"; return; }
    echo "PASS $name"
    pass=$((pass+1))
}

# ---- the suite -------------------------------------------------------

A78=$(printf 'A%.0s' $(seq 78))
A32=$(printf 'A%.0s' $(seq 32))

run_feed_test boot_shell "$PASS_HEX" \
    --expect "Oasis 0.1" --expect '$ echo hi' --expect "hi" \
    --expect '$ halt' --min-presents 5 \
    --golden "$HERE/golden/boot_shell.ppm"

run_feed_test help_uptime "$PASS_HEX" \
    --expect '$ help' --expect "builtins: help echo uptime halt" \
    --expect '$ uptime' --expect-sub "uptime: " --expect-sub " cycles" \
    --expect '$ frob' --expect "unknown command" --expect '$ halt'

run_feed_test edit "$PASS_HEX" \
    --expect '$ echo ok' --expect "ok" --expect '$ halt'

run_feed_test predphase "$PASS_HEX" \
    --expect '$ echo abcdefghijklmnopqrstuvwxyz' \
    --expect "abcdefghijklmnopqrstuvwxyz" --expect '$ halt'

run_feed_test ovf_shift "$PASS_HEX" \
    --expect "\$ $A78" --expect "${A32}x" \
    --expect "unknown command" --expect '$ halt'

run_feed_test scroll "$PASS_HEX" \
    --absent "Oasis 0.1" --expect '$ echo bottom' --expect "bottom" \
    --expect '$ halt'

run_feed_test resize "$PASS_HEX" \
    --expect-sub "echo hi" --expect "hi" --expect '$ halt'

run_feed_test m1_regression "$PASS_HEX" \
    --expect '$ help' --expect "builtins: help echo uptime halt" \
    --expect '$ echo ok' --expect "ok" \
    --expect-sub "uptime: " --expect-sub " cycles" \
    --expect '$ frob' --expect "unknown command" --expect '$ halt'

HALT_BADMAGIC=$(printf "%032x" $((0x0BAD0001)))
HALT_BADVER=$(printf "%032x" $((0x0BAD0002)))

run_boot_fail badtable_magic "$HALT_BADMAGIC" '        .org 0x20000
        .quad 0x5450415241484154   # SAHARAPT with the top byte off-by-1
        .quad 1
        .quad 1
        .quad 1
        .quad 0
        .oct 0
        .oct 0x0F000000'

run_boot_fail badtable_version "$HALT_BADVER" '        .org 0x20000
        .quad 0x5450415241484153
        .quad 2                    # a version this guest was not written for
        .quad 1
        .quad 1
        .quad 0
        .oct 0
        .oct 0x0F000000'

# ---- emu-py smoke leg (gated: slow emulator, one feed only) ----------
if [ "${EMU_PY:-0}" = "1" ] && wanted emu_py_smoke; then
    name=emu_py_smoke
    feed="$FEEDS/boot_shell.trc"
    [ -f "$feed" ] || python3 "$HERE/mkfeed.py" boot_shell "$IMG" "$feed" \
        >/dev/null
    [ -f "$OUT/boot_shell.a.trc" ] \
        || run_emu "$IMG" "$OUT/boot_shell.a.trc" --replay "$feed" >/dev/null
    trc="$OUT/$name.trc"
    out=$("$EMU_PY_BIN" "$IMG" --replay "$feed" --trace "$trc" \
          --trace-level 1 --check-invtp --maxcycles "$MAXCYCLES" \
          2>"$trc.err"); rc=$?
    if [ $rc -ne 0 ] || [ "$out" != "HALT r0=$PASS_HEX" ]; then
        echo "FAIL $name: rc=$rc stdout='$out'"
        [ -s "$trc.err" ] && sed 's/^/    stderr: /' "$trc.err" | head -5
        note_fail "$name"
    else
        # cross-emulator: the same feed drives both, so the traces
        # must be byte-identical - except the two emulators today
        # disagree on the EVENT stamp of a WFI-stall arrival (emu-py
        # stamps the visibility cycle T, emu-c stamps T+1; root
        # SPEC-ISSUES 35). replaycmp --cross tolerates exactly that
        # pair shape and holds every other record to byte-identity,
        # which is what catches "works only on emu-c" drift.
        python3 "$HERE/replaycmp.py" --cross "$OUT/boot_shell.a.trc" \
            "$trc" >"$OUT/$name.dv" 2>&1
        case $? in
            0) echo "PASS $name"; pass=$((pass+1));;
            3) echo "NOTE $name: cross-emulator EVENT-stamp drift" \
                    "(root SPEC-ISSUES 35)"
               drift_notes=$((drift_notes+1))
               echo "PASS $name"; pass=$((pass+1));;
            *) echo "FAIL $name: emu-py trace differs from emu-c:"
               sed 's/^/    /' "$OUT/$name.dv" | head -5
               note_fail "$name";;
        esac
    fi
fi

echo
echo "oasis-tests: $pass passed, $fail failed" \
     "($drift_notes replay-identity known-drift notes, SPEC-ISSUES 35)"
[ $fail -eq 0 ] || { echo "failed:$fail_names"; exit 1; }
