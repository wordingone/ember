#!/bin/bash
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
# Two things at once:
#  A. unit-assert the PROTECTED_RE against the exact paths the required checks execute, plus the
#     product paths that must stay eligible. This is the arithmetic, done before the survey.
#  B. re-run the live dry run over the open backlog with the narrowed regex.
set -uo pipefail

# The regex is EXTRACTED FROM THE WORKFLOW, never restated here. A copy in the test is a second
# source of truth that drifts silently -- and it already did: a sed pass stripped the backslash
# escapes from a hand-copied version, so the battery was green against a regex the workflow did
# not contain. Reading it from the file means the test cannot pass against bytes that are not
# shipping.
WF=${WF:-$(dirname "$0")/workflows/auto-merge-enable.yml}
RE=$(sed -n "s/^ *PROTECTED_RE='\(.*\)'$/\1/p" "$WF" | head -1)
if [ -z "$RE" ]; then echo "FATAL: could not extract PROTECTED_RE from $WF"; exit 2; fi
echo "regex under test (read from the workflow):"
echo "  $RE"
echo
FAIL=0

must_block() { if grep -qE "$RE" <<<"$1"; then echo "  PASS  blocked: $1"; else echo "  FAIL  NOT blocked: $1"; FAIL=1; fi; }
must_allow() { if grep -qE "$RE" <<<"$1"; then echo "  FAIL  wrongly blocked: $1"; FAIL=1; else echo "  PASS  allowed: $1"; fi; }

echo "=== A. paths a required check EXECUTES or READS -> must block ==="
must_block "tools/repo-guard.sh"
must_block "tools/check_line_endings.py"
must_block "tools/check_names_hashed.py"
must_block "tools/check_no_temp.py"
must_block "tools/repo-guard-denylist.sha256"
must_block "tools/repo-guard-names-exclude.cfg"
must_block "tools/no_temp_allowlist"
must_block "scripts/check_pr_authority_binding.py"
must_block "tools/ember-cli/src/build-tools/lifecycle-smoke.test.ts"
must_block "tools/ember-cli/src/build-tools/lifecycle-smoke-driver.ts"
must_block ".github/workflows/repo-guard.yml"
must_block ".githooks/pre-commit"
echo "=== authority surfaces -> must block ==="
must_block "INVARIANT.md"
must_block "GOAL.md"
must_block "docs/authority/anything.md"
must_block "goals/ember/x/goal.md"
echo "=== ordinary product source -> must stay ELIGIBLE ==="
must_allow "tools/ember-cli/src/screens/repl.ts"
must_allow "tools/ember-cli/src/ink/braille-canvas.ts"
must_allow "tools/ember-restart-3b/launch_packet.py"
must_allow "scripts/ember_01_identity/validate_identity.py"
must_allow "data/ember-restart-3b/cond3-identity-manifest.json"
must_allow "docs/some-note.md"
must_allow "tests/ember_restart_model/test_launch_packet.py"

echo
echo "=== B. live dry run over the open backlog ==="
REPO=wordingone/ember
ENROLL=0; DRAFT=0; PROT=0; TRUNC=0; OTHER=0
for pr in $(gh pr list --repo "$REPO" --state open --limit 200 --json number --jq '.[].number'); do
  meta=$(gh pr view "$pr" --repo "$REPO" --json number,isDraft,baseRefName,files,changedFiles 2>/dev/null) || { OTHER=$((OTHER+1)); continue; }
  [ "$(jq -r .isDraft <<<"$meta")" = "true" ] && { DRAFT=$((DRAFT+1)); continue; }
  [ "$(jq -r .baseRefName <<<"$meta")" != "master" ] && { OTHER=$((OTHER+1)); continue; }
  paths=$(jq -er '.files[].path' <<<"$meta") || { OTHER=$((OTHER+1)); continue; }
  [ "$(jq -r '.files|length' <<<"$meta")" != "$(jq -r .changedFiles <<<"$meta")" ] && { TRUNC=$((TRUNC+1)); continue; }
  if grep -qE "$RE" <<<"$paths"; then PROT=$((PROT+1)); continue; fi
  ENROLL=$((ENROLL+1))
done
echo "  enroll=$ENROLL draft=$DRAFT protected=$PROT truncated=$TRUNC other=$OTHER"
echo
[ "$FAIL" = 0 ] && echo "=== REGEX BATTERY: ALL PASS ===" || echo "=== REGEX BATTERY: FAILURES ==="
exit $FAIL
