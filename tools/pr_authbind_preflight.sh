#!/usr/bin/env bash
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
#
# Pre-handoff authority-binding preflight.
#
# Predicts the PUBLIC repo-guard verdict for a PR by reproducing BOTH CI steps
# locally, with the two corrections that make the local read match the server:
#   (1) fetch a FRESH origin/master (CI uses fetch-depth:0 — the true public tip),
#   (2) pull the LIVE PR body via `gh api` (CI's github.event.pull_request.body is
#       a webhook-payload SNAPSHOT; `gh run rerun` replays it, so a body edit only
#       lands via a fresh event — this script always reads the current body).
#
# Usage:
#   bash tools/pr_authbind_preflight.sh <PR_NUMBER> [<LOCAL_HEAD_REF>]
# Exit 0 only if BOTH Step A (repo-guard structural kernel) and Step B
# (PR-body + changed-artifact authority binding) pass.

set -u
ROOT="$(git rev-parse --show-toplevel)" || { echo "not in a git repo"; exit 2; }
cd "$ROOT"

PR="${1:?usage: pr_authbind_preflight.sh <PR_NUMBER> [<HEAD_REF>]}"
HEAD_REF="${2:-HEAD}"

command -v gh >/dev/null 2>&1 || { echo "FAIL: gh CLI not available"; exit 2; }

# owner/repo from origin
SLUG="$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null)"
[ -z "$SLUG" ] && { echo "FAIL: cannot resolve owner/repo from gh"; exit 2; }

echo "== preflight: PR #$PR  head=$HEAD_REF  repo=$SLUG =="

# (1) fresh public tip
echo "-- fetching fresh origin/master"
git fetch --quiet origin master || { echo "FAIL: git fetch origin master"; exit 2; }
RANGE="origin/master..${HEAD_REF}"
echo "   range: $RANGE"
echo "   merge-base: $(git merge-base origin/master "$HEAD_REF" 2>/dev/null || echo '<none>')"

# (2) LIVE body (never the event snapshot)
BODY_FILE="$(mktemp -t pr_body.XXXXXX)"
trap 'rm -f "$BODY_FILE"' EXIT
gh api "repos/${SLUG}/pulls/${PR}" --jq '.body // ""' > "$BODY_FILE" 2>/dev/null \
  || { echo "FAIL: gh api pulls/$PR"; exit 2; }
echo "   live body: $(wc -l < "$BODY_FILE") lines"

RC=0

# Step A — structural kernel against the fresh public tip
echo
echo "== Step A: repo-guard.sh --base origin/master =="
if bash tools/repo-guard.sh --base origin/master; then
  echo "Step A: PASS"
else
  echo "Step A: FAIL"; RC=1
fi

# Step B — PR-body + changed-artifact authority binding (live body, fresh range)
echo
echo "== Step B: check_pr_authority_binding.py (live body) =="
if python scripts/check_pr_authority_binding.py --body-file "$BODY_FILE" --changed-range "$RANGE"; then
  echo "Step B: PASS"
else
  echo "Step B: FAIL"; RC=1
fi

echo
if [ "$RC" -eq 0 ]; then
  echo "PREFLIGHT: PASS — predicts public repo-guard GREEN for PR #$PR"
  echo "   (if the public job is nonetheless RED, CI used a STALE body snapshot:"
  echo "    push a fresh event — empty commit or close/reopen — never 'gh run rerun'.)"
else
  echo "PREFLIGHT: FAIL — public repo-guard would be RED for PR #$PR (see Step A/B above)"
fi
exit "$RC"
