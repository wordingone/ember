#!/usr/bin/env bash
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
# tools/ember-cli/scripts/tsc-newerror-gate.sh
#
# Local pre-PR gate for ember-cli TypeScript type-debt (class-fix, PR #980
# manifest-typing + mock-typing reduction: 61 -> 25 `error TS` lines).
# Counts the CURRENT `tsc --noEmit` error count and compares it against a
# frozen baseline recorded in tools/ember-cli/.tsc-baseline. Exits 1 (RED)
# if the count has grown -- i.e. the class silently regrew -- exits 0
# (GREEN) otherwise. LOCAL gate only: no GitHub Actions workflow, no CI
# billing surface; run this by hand or from a pre-PR checklist.
#
# Usage: tools/ember-cli/scripts/tsc-newerror-gate.sh   (from anywhere)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLI_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SRC_DIR="$CLI_ROOT/src"
BASELINE_FILE="$CLI_ROOT/.tsc-baseline"

if [ ! -f "$BASELINE_FILE" ]; then
  echo "tsc-newerror-gate: no baseline at $BASELINE_FILE -- refusing to run ungated." >&2
  exit 1
fi

# Baseline file carries a goal-binding header (# comment lines) above the bare
# integer -- strip comment/blank lines, then take the last remaining line.
baseline="$(grep -vE '^\s*#' "$BASELINE_FILE" | grep -vE '^\s*$' | tail -n1 | tr -d '[:space:]')"
if ! [[ "$baseline" =~ ^[0-9]+$ ]]; then
  echo "tsc-newerror-gate: baseline file does not contain a plain integer: '$baseline'" >&2
  exit 1
fi

cd "$SRC_DIR"

# Fail-closed run-proof (oburst-0926 2026-07-21): the old form
# `bun run typecheck 2>&1 | grep -c 'error TS' || true` cannot distinguish
# "tsc ran, 0 errors" from "tsc never ran" (bun absent -> 127, spawn failure,
# crash before emitting any output) -- both produce current=0 and the `|| true`
# swallowed the pipeline's failure, so a dead/missing tsc binary reported
# GREEN over an uncompiled tree. Capture bun's own exit status separately
# from the grep count and require a positive proof of a real run before
# trusting a low error count.
set +e
typecheck_output="$(bun run typecheck 2>&1)"
bun_status=$?
set -e

current="$(printf '%s\n' "$typecheck_output" | grep -c 'error TS' || true)"

if [ "$bun_status" -eq 127 ]; then
  echo "RED: tsc did not run -- bun/tsc command not found (exit 127). Refusing to certify." >&2
  echo "$typecheck_output" >&2
  exit 1
fi

if [ "$bun_status" -ne 0 ] && [ "$current" -eq 0 ]; then
  echo "RED: tsc did not run -- bun exited $bun_status with no 'error TS' output (spawn/crash, not a completed typecheck). Refusing to certify." >&2
  echo "$typecheck_output" >&2
  exit 1
fi

if [ "$current" -gt "$baseline" ]; then
  echo "RED: tsc error count grew: baseline=$baseline current=$current (+$((current - baseline)))" >&2
  exit 1
fi

echo "GREEN: tsc error count $current <= baseline $baseline (bun exit $bun_status)"
exit 0
