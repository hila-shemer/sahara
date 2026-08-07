#!/usr/bin/env bash
# Harness self-test — no emulator required. Validates:
#   1. every MANIFEST source assembles (with tests/defs.s prepended)
#   2. committed generated files match their generators byte-for-byte
#   3. run-tests.sh passes against the stub, and FAILS when the stub
#      breaks the contract (bad rc, uppercase hex)
#   4. difftest.sh reports identical stubs as identical and a wb
#      difference as DIVERGE
# The stub executes nothing; semantic expectations are first exercised
# when a real emulator arrives.
set -u

die() { echo "selftest: FATAL: $*" >&2; exit 1; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TESTS="$ROOT/tests"
TMP=$(mktemp -d) || die mktemp
trap 'rm -rf "$TMP"' EXIT

echo "== 1. assembly of every manifest source =="
while read -r name src rest; do
    case "$name" in ""|\#*) continue;; esac
    python3 "$ROOT/asm/asm.py" -o "$TMP/$name.img" "$TESTS/defs.s" \
        "$TESTS/$src" || die "assembly of $src failed"
    echo "ok: $src"
done < "$TESTS/MANIFEST"

echo "== 2. generated files match generators =="
for pair in "gen_c5.py c5_base.s" "gen_c3.py c3_atomics.s" "gen_defs.py defs.s"; do
    set -- $pair
    cp "$TESTS/$2" "$TMP/$2.committed"
    python3 "$TESTS/$1" >/dev/null || die "$1 failed"
    cmp -s "$TESTS/$2" "$TMP/$2.committed" \
        || die "$2 is stale: rerun tests/$1 and commit"
    echo "ok: $2"
done

FAKE="$TMP/fake-emu"
printf '#!/usr/bin/env bash\nexec python3 "%s" "$@"\n' \
    "$TESTS/harness-selftest/fake-emu.py" > "$FAKE"
chmod +x "$FAKE"

echo "== 3. run-tests.sh against the stub =="
EMU="$FAKE" "$TESTS/run-tests.sh" > "$TMP/rt.out" 2>&1 \
    || { cat "$TMP/rt.out"; die "run-tests should pass with the stub"; }
grep -q "4 passed, 0 failed" "$TMP/rt.out" \
    || { cat "$TMP/rt.out"; die "unexpected run-tests summary"; }
echo "ok: stub passes"

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

echo "== 4. difftest.sh =="
"$TESTS/difftest.sh" "$FAKE" "$FAKE" > "$TMP/dt.out" 2>&1 \
    || { cat "$TMP/dt.out"; die "difftest identical stubs should pass"; }
grep -q "4 identical, 0 diverged" "$TMP/dt.out" \
    || { cat "$TMP/dt.out"; die "unexpected difftest summary"; }
echo "ok: identical stubs identical"

printf '#!/usr/bin/env bash\nFAKE_WB=5 exec python3 "%s" "$@"\n' \
    "$TESTS/harness-selftest/fake-emu.py" > "$TMP/fake-wb"
chmod +x "$TMP/fake-wb"
"$TESTS/difftest.sh" "$FAKE" "$TMP/fake-wb" > "$TMP/dt2.out" 2>&1 \
    && { cat "$TMP/dt2.out"; die "difftest must report the divergence"; }
grep -q "DIVERGE" "$TMP/dt2.out" \
    || { cat "$TMP/dt2.out"; die "no DIVERGE in difftest output"; }
echo "ok: wb divergence reported"

echo
echo "selftest: all harness checks passed"
