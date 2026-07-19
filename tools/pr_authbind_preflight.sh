#!/usr/bin/env bash
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
#
# Pre-handoff authority-binding preflight.
#
# Predicts the PUBLIC repo-guard verdict for a PR by reproducing BOTH CI steps
# against the exact ref CI actually evaluates.
#
# The `pull_request` job checks out `refs/pull/<N>/merge` — the GitHub-computed
# merge of the PR head into the current base tip — never the bare PR head. A
# two-dot diff of a local head against origin/master (the old approach) can
# include/omit unrelated upstream changes whenever the branch is behind or has
# diverged, and never proves the local tree even equals the public PR head.
# This script instead:
#   1. resolves the PUBLIC PR head OID via `gh api` and REJECTS if the local
#      ref does not match it exactly (no silent proceed on a stale/wrong ref),
#   2. fetches the guarded merge ref (`refs/pull/<N>/merge`), verifying its
#      parents are exactly {origin/master tip, public head OID} — falling
#      back to constructing the same merge deterministically only if the
#      merge ref is unavailable, and failing loud if that merge does not
#      apply cleanly (what GitHub means by mergeable=false/unknown),
#   3. runs both CI steps inside a clean temporary worktree checked out at
#      that merge commit, against a freshly fetched origin/master,
#   4. pulls the LIVE PR body via `gh api` (CI's github.event.pull_request.body
#      is a webhook-payload SNAPSHOT; `gh run rerun` replays it, so a body
#      edit only lands via a fresh event — this script always reads the
#      current body).
#
# Usage:
#   bash tools/pr_authbind_preflight.sh <PR_NUMBER> [<LOCAL_HEAD_REF>]
# Exit 0 only if BOTH Step A (repo-guard structural kernel) and Step B
# (PR-body + changed-artifact authority binding) pass against the merge ref.
# Exit 2 on any preflight-validity failure (head mismatch, unresolvable/stale
# merge ref, non-clean merge) — these are never guard verdicts; they mean the
# preflight cannot yet speak for the public job.

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

# -- (1) fresh public tip -----------------------------------------------------
echo "-- fetching fresh origin/master"
git fetch --quiet origin master || { echo "FAIL: git fetch origin master"; exit 2; }
MASTER_TIP="$(git rev-parse origin/master)"

# -- (2) public PR head OID; reject a local ref that doesn't match it --------
PR_INFO="$(gh api "repos/${SLUG}/pulls/${PR}" --jq '[.head.sha, .base.ref, (.mergeable|tostring), (.mergeable_state // "unknown")] | @tsv' 2>/dev/null)" \
  || { echo "FAIL: gh api pulls/$PR"; exit 2; }
IFS=$'\t' read -r PUBLIC_HEAD BASE_REF MERGEABLE MERGEABLE_STATE <<<"$PR_INFO"
[ -z "$PUBLIC_HEAD" ] && { echo "FAIL: could not resolve public head OID for PR #$PR"; exit 2; }
echo "   public PR #$PR: head=$PUBLIC_HEAD base=$BASE_REF mergeable=$MERGEABLE ($MERGEABLE_STATE)"

LOCAL_HEAD_OID="$(git rev-parse "${HEAD_REF}^{commit}" 2>/dev/null)" \
  || { echo "FAIL: cannot resolve local ref '$HEAD_REF' to a commit"; exit 2; }
if [ "$LOCAL_HEAD_OID" != "$PUBLIC_HEAD" ]; then
  echo "FAIL: local head ($HEAD_REF = $LOCAL_HEAD_OID) != public PR #$PR head ($PUBLIC_HEAD)"
  echo "      the preflight only predicts the verdict for the ref that is ACTUALLY the PR head"
  exit 2
fi
echo "   local head confirmed == public PR head ($PUBLIC_HEAD)"

# -- (3) resolve the guarded merge ref, falling back to constructing it ------
TMPWT="$(mktemp -d)"
BODY_FILE=""
cleanup() {
  git worktree remove --force "$TMPWT" >/dev/null 2>&1
  rm -rf "$TMPWT"
  [ -n "$BODY_FILE" ] && rm -f "$BODY_FILE"
}
trap cleanup EXIT

MERGE_OID=""
WORKTREE_MADE=0
if git fetch --quiet origin "refs/pull/${PR}/merge" 2>/dev/null; then
  CANDIDATE="$(git rev-parse FETCH_HEAD)"
  PARENTS="$(git rev-list --parents -n1 "$CANDIDATE" | cut -d' ' -f2-)"
  PARENT_COUNT="$(printf '%s\n' "$PARENTS" | tr ' ' '\n' | grep -c .)"
  if [ "$PARENT_COUNT" -ne 2 ]; then
    echo "FAIL: refs/pull/${PR}/merge ($CANDIDATE) is not a 2-parent merge commit"
    exit 2
  fi
  ACTUAL_SORTED="$(printf '%s\n' $PARENTS | sort)"
  EXPECTED_SORTED="$(printf '%s\n' "$MASTER_TIP" "$PUBLIC_HEAD" | sort)"
  if [ "$ACTUAL_SORTED" != "$EXPECTED_SORTED" ]; then
    echo "FAIL: stale refs/pull/${PR}/merge — parents ($ACTUAL_SORTED) != expected (origin/master tip + public head: $EXPECTED_SORTED)"
    echo "      GitHub has not recomputed the merge ref against the current base; do not trust it yet"
    exit 2
  fi
  echo "   using guarded merge ref refs/pull/${PR}/merge ($CANDIDATE), parents verified"
  MERGE_OID="$CANDIDATE"
else
  echo "   refs/pull/${PR}/merge unavailable — constructing the merge deterministically"
  git worktree add --detach --quiet "$TMPWT" "$MASTER_TIP" || { echo "FAIL: worktree add at origin/master tip"; exit 2; }
  WORKTREE_MADE=1
  if ! git -C "$TMPWT" merge --no-ff --no-commit "$PUBLIC_HEAD" >/dev/null 2>&1; then
    echo "FAIL: PR #$PR head ($PUBLIC_HEAD) does not merge cleanly onto origin/master ($MASTER_TIP)"
    echo "      (this is what GitHub means by mergeable=false/unknown — fix the conflict upstream, don't preflight around it)"
    exit 2
  fi
  git -C "$TMPWT" commit --no-edit -m "preflight: synthetic merge PR #$PR ($PUBLIC_HEAD) into origin/master ($MASTER_TIP)" >/dev/null \
    || { echo "FAIL: could not commit constructed merge"; exit 2; }
  MERGE_OID="$(git -C "$TMPWT" rev-parse HEAD)"
  echo "   constructed merge commit $MERGE_OID (parents: $MASTER_TIP $PUBLIC_HEAD)"
fi

# If the merge-ref path was taken (worktree not yet materialized), check it out now.
if [ "$WORKTREE_MADE" -eq 0 ]; then
  git worktree add --detach --quiet "$TMPWT" "$MERGE_OID" || { echo "FAIL: worktree add at merge ref $MERGE_OID"; exit 2; }
fi

# -- (4) LIVE body (never the event snapshot) --------------------------------
BODY_FILE="$(mktemp -t pr_body.XXXXXX)"
gh api "repos/${SLUG}/pulls/${PR}" --jq '.body // ""' > "$BODY_FILE" 2>/dev/null \
  || { echo "FAIL: gh api pulls/$PR (body)"; exit 2; }
echo "   live body: $(wc -l < "$BODY_FILE") lines"

RC=0

# -- Step A / Step B, executed inside the clean merge-ref worktree -----------
echo
echo "== Step A: repo-guard.sh --base origin/master (in merge-ref worktree $MERGE_OID) =="
if (cd "$TMPWT" && bash tools/repo-guard.sh --base origin/master); then
  echo "Step A: PASS"
else
  echo "Step A: FAIL"; RC=1
fi

echo
echo "== Step B: check_pr_authority_binding.py (live body, in merge-ref worktree) =="
if (cd "$TMPWT" && python scripts/check_pr_authority_binding.py --body-file "$BODY_FILE" --changed-range origin/master..HEAD); then
  echo "Step B: PASS"
else
  echo "Step B: FAIL"; RC=1
fi

echo
if [ "$RC" -eq 0 ]; then
  echo "PREFLIGHT: PASS — predicts public repo-guard GREEN for PR #$PR (merge ref $MERGE_OID)"
  echo "   (if the public job is nonetheless RED, CI used a STALE body snapshot:"
  echo "    push a fresh event — empty commit or close/reopen — never 'gh run rerun'.)"
else
  echo "PREFLIGHT: FAIL — public repo-guard would be RED for PR #$PR (see Step A/B above)"
fi
exit "$RC"
