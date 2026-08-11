#!/usr/bin/env bash
# Harness self-test — no emulator required. Validates:
#   0. component unit tests (assembler, trace-q, trace.md 8 vectors)
#   1. every MANIFEST source assembles (with tests/defs.s prepended)
#   2. committed generated files match their generators byte-for-byte
#   3. run-tests.sh passes against the stub, and FAILS when the stub
#      breaks the contract (bad rc, uppercase hex)
#   4. difftest.sh reports identical stubs as identical and a wb
#      difference as DIVERGE
# The stub executes nothing; semantic expectations are first exercised
# when a real emulator arrives.
set -u
# selftest drives both REPLAY modes itself (step 3); an inherited
# REPLAY=1 would leak into the plain run and break its summary check
unset REPLAY

die() { echo "selftest: FATAL: $*" >&2; exit 1; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TESTS="$ROOT/tests"
TMP=$(mktemp -d) || die mktemp
trap 'rm -rf "$TMP"' EXIT

echo "== 0. component unit tests =="
for t in asm/test_asm.py asm/test_asmmd.py trace-q/test_traceq.py \
         trace-q/test_vectors.py; do
    python3 "$ROOT/$t" > "$TMP/unit.out" 2>&1 \
        || { cat "$TMP/unit.out"; die "$t failed"; }
    echo "ok: $t"
done

echo "== 1. assembly of every manifest source =="
while read -r name src rest; do
    case "$name" in ""|\#*) continue;; esac
    python3 "$ROOT/asm/asm.py" -o "$TMP/$name.img" "$TESTS/defs.s" \
        "$TESTS/$src" || die "assembly of $src failed"
    echo "ok: $src"
done < "$TESTS/MANIFEST"

echo "== 1b. event feeds generate, parse, and are deterministic =="
while read -r name src rest; do
    case "$name" in ""|\#*) continue;; esac
    ev=""
    for tok in $rest; do
        case "$tok" in events=*) ev="${tok#events=}";; esac
    done
    [ -n "$ev" ] || continue
    python3 "$TESTS/events/$ev" "$TMP/$name.img" "$TMP/$name.ev1.trc" \
        || die "event feed $ev failed"
    python3 "$TESTS/events/$ev" "$TMP/$name.img" "$TMP/$name.ev2.trc" \
        || die "event feed $ev failed (second run)"
    cmp -s "$TMP/$name.ev1.trc" "$TMP/$name.ev2.trc" \
        || die "event feed $ev is nondeterministic"
    echo "ok: $ev"
done < "$TESTS/MANIFEST"

echo "== 2. generated files match generators =="
for pair in "gen_c5.py c5_base.s" "gen_c3.py c3_atomics.s" \
            "gen_c2.py c2_mmu.s" "gen_c2.py c2_noinvtp_remap.s" \
            "gen_c2.py c2_noinvtp_ptbase.s" "gen_c4.py c4_fp.s" \
            "gen_c7.py c7_mem.s" "gen_defs.py defs.s"; do
    set -- $pair
    cp "$TESTS/$2" "$TMP/$2.committed"
    python3 "$TESTS/$1" >/dev/null || die "$1 failed"
    cmp -s "$TESTS/$2" "$TMP/$2.committed" \
        || die "$2 is stale: rerun tests/$1 and commit"
    echo "ok: $2"
done

# fpvec.dat is host-C-generated (committed); rebuild and compare when a
# compiler is present. IEEE + fesetround makes this host-independent
# for the committed vectors (fpvec.c header); a mismatch means either a
# stale .dat or a host that disagrees with IEEE — both fatal.
if command -v cc >/dev/null 2>&1; then
    cc -std=c11 -O0 -frounding-math -o "$TMP/fpvec" \
        "$TESTS/fpvec/fpvec.c" -lm || die "fpvec.c does not compile"
    "$TMP/fpvec" > "$TMP/fpvec.dat" || die "fpvec run failed"
    cmp -s "$TMP/fpvec.dat" "$TESTS/fpvec/fpvec.dat" \
        || die "fpvec.dat is stale or host FP disagrees: rebuild and diff"
    echo "ok: fpvec.dat"
else
    die "no C compiler: cannot verify fpvec.dat (needed for C4)"
fi

FAKE="$TMP/fake-emu"
printf '#!/usr/bin/env bash\nexec python3 "%s" "$@"\n' \
    "$TESTS/harness-selftest/fake-emu.py" > "$FAKE"
chmod +x "$FAKE"

NTESTS=$(grep -cv '^\s*\(#\|$\)' "$TESTS/MANIFEST")
NEV=$(grep -v '^\s*\(#\|$\)' "$TESTS/MANIFEST" | grep -c 'events=')
# The c7_rng_* checkers demand real device content the stub has no
# furniture for (harness-selftest/fake-emu.py predates the rng branch,
# whose tests/ grant is additions-only), so the run-tests steps drive
# the stub over the pre-rng subset. difftest runs no checkers and
# keeps the full manifest. The rng tests' first real exercise is the
# two actual emulators — which is the point of the suite anyway.
STUB_TESTS=$(grep -v '^\s*\(#\|$\)' "$TESTS/MANIFEST" | awk '{print $1}' \
    | grep -v '^c7_rng_')
NSTUB=$(echo "$STUB_TESTS" | grep -c .)
NSTUBEV=$(grep -v '^\s*\(#\|$\)' "$TESTS/MANIFEST" | grep 'events=' \
    | awk '{print $1}' | grep -cv '^c7_rng_')

echo "== 3. run-tests.sh against the stub =="
# Without REPLAY=1 the event-fed tests must be SKIPPED (loudly,
# counted) — an emulator without --replay cannot run them.
# shellcheck disable=SC2086
EMU="$FAKE" "$TESTS/run-tests.sh" $STUB_TESTS > "$TMP/rt.out" 2>&1 \
    || { cat "$TMP/rt.out"; die "run-tests should pass with the stub"; }
grep -q "$((NSTUB - NSTUBEV)) passed, 0 failed, $NSTUBEV skipped" "$TMP/rt.out" \
    || { cat "$TMP/rt.out"; die "unexpected run-tests summary"; }
grep -q "SKIP c7_kbd:" "$TMP/rt.out" \
    || { cat "$TMP/rt.out"; die "event-fed skip must be printed"; }
echo "ok: stub passes ($((NSTUB - NSTUBEV)) tests, $NSTUBEV event-fed skipped)"

# With REPLAY=1 the (stub-capable) suite runs, event-fed tests
# included: the stub echoes the feed's EVENT records and emits
# check-satisfying furniture, so everything must pass with zero skips.
# shellcheck disable=SC2086
REPLAY=1 EMU="$FAKE" "$TESTS/run-tests.sh" $STUB_TESTS > "$TMP/rt-ev.out" 2>&1 \
    || { cat "$TMP/rt-ev.out"; die "REPLAY=1 full suite should pass"; }
grep -q "$NSTUB passed, 0 failed, 0 skipped" "$TMP/rt-ev.out" \
    || { cat "$TMP/rt-ev.out"; die "unexpected REPLAY=1 summary"; }
echo "ok: REPLAY=1 stub passes all $NSTUB (event-fed included)"

# A stub that loses an EVENT record must fail the test — via the
# replay-divergence check or the feed-vs-trace byte equality in
# checks/c7_kbd.py, whichever trips first. Both are loud.
printf '#!/usr/bin/env bash\nFAKE_DROP_EVENT=1 exec python3 "%s" "$@"\n' \
    "$TESTS/harness-selftest/fake-emu.py" > "$TMP/fake-noev"
chmod +x "$TMP/fake-noev"
REPLAY=1 EMU="$TMP/fake-noev" "$TESTS/run-tests.sh" c7_kbd \
    > "$TMP/rt-ev2.out" 2>&1 \
    && { cat "$TMP/rt-ev2.out"; die "a dropped EVENT record must fail the check"; }
echo "ok: missing EVENT record caught"

printf '#!/usr/bin/env bash\nFAKE_RC=7 exec python3 "%s" "$@"\n' \
    "$TESTS/harness-selftest/fake-emu.py" > "$TMP/fake-rc"
chmod +x "$TMP/fake-rc"
EMU="$TMP/fake-rc" "$TESTS/run-tests.sh" c0_smoke > "$TMP/rt2.out" 2>&1 \
    && { cat "$TMP/rt2.out"; die "run-tests must fail on nonzero rc"; }
echo "ok: nonzero rc detected"

printf '#!/usr/bin/env bash\nFAKE_CASE=upper exec python3 "%s" "$@"\n' \
    "$TESTS/harness-selftest/fake-emu.py" > "$TMP/fake-case"
chmod +x "$TMP/fake-case"
EMU="$TMP/fake-case" "$TESTS/run-tests.sh" c0_smoke > "$TMP/rt3.out" 2>&1 \
    && { cat "$TMP/rt3.out"; die "run-tests must reject uppercase hex"; }
echo "ok: uppercase HALT line rejected"

# expect= enforcement: FAKE_R0 overrides the stub's HALT value even for
# tests carrying expect=; a wrong r0 must fail the test.
printf '#!/usr/bin/env bash\nFAKE_R0=badbad exec python3 "%s" "$@"\n' \
    "$TESTS/harness-selftest/fake-emu.py" > "$TMP/fake-r0"
chmod +x "$TMP/fake-r0"
EMU="$TMP/fake-r0" "$TESTS/run-tests.sh" c1_triplefault > "$TMP/rt4.out" 2>&1 \
    && { cat "$TMP/rt4.out"; die "run-tests must enforce expect="; }
echo "ok: expect= mismatch detected"

# expect=checkfail enforcement: a HALTing run (FAKE_R0 forces the stub
# onto the HALT path) must FAIL a test whose correct outcome is the
# check-mode assertion (exit 3 + CHECKFAIL — SPEC-ISSUES 22/23).
EMU="$TMP/fake-r0" "$TESTS/run-tests.sh" c2_noinvtp_remap \
    > "$TMP/rt5.out" 2>&1 \
    && { cat "$TMP/rt5.out"; die "run-tests must reject HALT where CHECKFAIL expected"; }
echo "ok: expect=checkfail rejects a HALTing run"

# REPLAY=1: --replay re-run (fed the recorded trace, trace.md 5.1) +
# diverge. The stub has
# no EVENT records (0-event replay is still a meaningful determinism
# re-run) and reproduces its trace, so this must pass...
REPLAY=1 EMU="$FAKE" "$TESTS/run-tests.sh" c0_smoke > "$TMP/rt6.out" 2>&1 \
    || { cat "$TMP/rt6.out"; die "REPLAY=1 should pass with the stub"; }
echo "ok: replay round-trip passes"
# ...and a stub that emits a different wb only under --replay must be
# caught as a replay divergence.
printf '#!/usr/bin/env bash\nFAKE_REPLAY_WB=9 exec python3 "%s" "$@"\n' \
    "$TESTS/harness-selftest/fake-emu.py" > "$TMP/fake-rwb"
chmod +x "$TMP/fake-rwb"
REPLAY=1 EMU="$TMP/fake-rwb" "$TESTS/run-tests.sh" c0_smoke \
    > "$TMP/rt7.out" 2>&1 \
    && { cat "$TMP/rt7.out"; die "replay divergence must fail the test"; }
grep -q "REPLAY DIVERGENCE" "$TMP/rt7.out" \
    || { cat "$TMP/rt7.out"; die "no REPLAY DIVERGENCE in output"; }
echo "ok: replay divergence caught"

echo "== 4. difftest.sh =="
# Without REPLAY=1: event-fed tests skipped, everything else identical.
"$TESTS/difftest.sh" "$FAKE" "$FAKE" > "$TMP/dt.out" 2>&1 \
    || { cat "$TMP/dt.out"; die "difftest identical stubs should pass"; }
grep -q "$((NTESTS - NEV)) identical, 0 diverged" "$TMP/dt.out" \
    || { cat "$TMP/dt.out"; die "unexpected difftest summary"; }
grep -q "$NEV skipped" "$TMP/dt.out" \
    || { cat "$TMP/dt.out"; die "difftest must count event-fed skips"; }
echo "ok: identical stubs identical ($NEV event-fed skipped)"

# With REPLAY=1: event-fed tests run on both sides from one shared
# feed and must come out identical too.
REPLAY=1 "$TESTS/difftest.sh" "$FAKE" "$FAKE" > "$TMP/dt-ev.out" 2>&1 \
    || { cat "$TMP/dt-ev.out"; die "REPLAY=1 difftest should pass"; }
grep -q "$NTESTS identical, 0 diverged" "$TMP/dt-ev.out" \
    || { cat "$TMP/dt-ev.out"; die "unexpected REPLAY=1 difftest summary"; }
echo "ok: REPLAY=1 identical stubs identical (event-fed included)"

printf '#!/usr/bin/env bash\nFAKE_WB=5 exec python3 "%s" "$@"\n' \
    "$TESTS/harness-selftest/fake-emu.py" > "$TMP/fake-wb"
chmod +x "$TMP/fake-wb"
"$TESTS/difftest.sh" "$FAKE" "$TMP/fake-wb" > "$TMP/dt2.out" 2>&1 \
    && { cat "$TMP/dt2.out"; die "difftest must report the divergence"; }
grep -q "DIVERGE" "$TMP/dt2.out" \
    || { cat "$TMP/dt2.out"; die "no DIVERGE in difftest output"; }
echo "ok: wb divergence reported"

# checkfail-class divergence: A CHECKFAILs, B (FAKE_R0) HALTs — the
# class comparison, not the reason text, must flag it.
"$TESTS/difftest.sh" "$FAKE" "$TMP/fake-r0" c2_noinvtp_remap \
    > "$TMP/dt3.out" 2>&1 \
    && { cat "$TMP/dt3.out"; die "difftest must diverge on checkfail class"; }
grep -q "DIVERGE c2_noinvtp_remap (checkfail class)" "$TMP/dt3.out" \
    || { cat "$TMP/dt3.out"; die "no checkfail-class DIVERGE reported"; }
echo "ok: checkfail class divergence reported"

echo
echo "selftest: all harness checks passed"
