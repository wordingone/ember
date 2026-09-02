#!/usr/bin/env bash
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
# src/ember/infrastructure/tools/ember-cli/scripts/tsc-newerror-gate.test.sh
#
# Minimal self-contained bash test for tsc-newerror-gate.sh (oburst-0926
# 2026-07-21 false-green defect). Reproduces the false-GREEN (tsc/bun
# absent from PATH must no longer report GREEN) and asserts the real
# clean/at-baseline run still reports GREEN. Exits nonzero on any failure.
#
# Usage: src/ember/infrastructure/tools/ember-cli/scripts/tsc-newerror-gate.test.sh   (from anywhere)

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATE="$SCRIPT_DIR/tsc-newerror-gate.sh"
CLI_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

fail_count=0

check() {
  local name="$1"
  local expect_exit="$2"
  local actual_exit="$3"
  if [ "$actual_exit" -eq "$expect_exit" ]; then
    echo "PASS: $name (exit $actual_exit, expected $expect_exit)"
  else
    echo "FAIL: $name (exit $actual_exit, expected $expect_exit)" >&2
    fail_count=$((fail_count + 1))
  fi
}

echo "=== test 1: bun/tsc absent from PATH must fail-closed (RED), never GREEN ==="
out="$(env -i PATH="/usr/bin:/bin" bash "$GATE" 2>&1)"
status=$?
echo "$out"
check "bun-absent fails closed" 1 "$status"
if printf '%s' "$out" | grep -q '^GREEN'; then
  echo "FAIL: bun-absent run printed GREEN -- the false-green defect is present" >&2
  fail_count=$((fail_count + 1))
fi
if ! printf '%s' "$out" | grep -qi 'did not run'; then
  echo "FAIL: bun-absent run did not explain itself with a 'did not run' message" >&2
  fail_count=$((fail_count + 1))
fi

echo "=== test 2: bun present but underlying tsc binary missing (spawn/crash, no error TS lines) must fail-closed ==="
stubdir="$(mktemp -d)"
trap 'rm -rf "$stubdir"' EXIT
cat > "$stubdir/bun" <<'EOF'
#!/usr/bin/env bash
echo "$ tsc --noEmit"
echo "bun: command not found: tsc" >&2
exit 1
EOF
chmod +x "$stubdir/bun"
out2="$(env -i PATH="$stubdir:/usr/bin:/bin" bash "$GATE" 2>&1)"
status2=$?
echo "$out2"
check "stubbed-crash bun fails closed" 1 "$status2"
if printf '%s' "$out2" | grep -q '^GREEN'; then
  echo "FAIL: stubbed-crash run printed GREEN -- current<=baseline masked a dead tsc" >&2
  fail_count=$((fail_count + 1))
fi

echo "=== test 3: real clean/at-baseline run must still report GREEN ==="
if [ ! -d "$CLI_ROOT/src/node_modules" ]; then
  echo "SKIP: $CLI_ROOT/src/node_modules absent -- run 'bun install' in src/ember/infrastructure/tools/ember-cli/src first to exercise the real-run path" >&2
else
  out3="$(bash "$GATE" 2>&1)"
  status3=$?
  echo "$out3"
  check "real run still green at/under baseline" 0 "$status3"
  if ! printf '%s' "$out3" | grep -q '^GREEN'; then
    echo "FAIL: real run did not report GREEN" >&2
    fail_count=$((fail_count + 1))
  fi
fi

echo "=== test 4: real run detecting genuine growth must still report RED (baseline-compare path intact) ==="
if [ ! -d "$CLI_ROOT/src/node_modules" ]; then
  echo "SKIP: node_modules absent -- see test 3" >&2
else
  baseline_file="$CLI_ROOT/.tsc-baseline"
  backup="$(mktemp)"
  cp "$baseline_file" "$backup"
  printf '0\n' > "$baseline_file"
  out4="$(bash "$GATE" 2>&1)"
  status4=$?
  cp "$backup" "$baseline_file"
  rm -f "$backup"
  echo "$out4"
  check "forced-growth run reports RED" 1 "$status4"
  if printf '%s' "$out4" | grep -q '^GREEN'; then
    echo "FAIL: forced-growth run printed GREEN" >&2
    fail_count=$((fail_count + 1))
  fi
fi

echo "==="
if [ "$fail_count" -eq 0 ]; then
  echo "ALL PASS"
  exit 0
else
  echo "$fail_count check(s) FAILED"
  exit 1
fi
