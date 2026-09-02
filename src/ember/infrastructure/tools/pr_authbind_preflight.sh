#!/usr/bin/env bash
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
#
# Pre-handoff authority-binding preflight.
#
# Predicts the PUBLIC verdict for a PR by reproducing the CI steps against the
# exact ref CI actually evaluates.
#
# The `pull_request` job checks out `refs/pull/<N>/merge` — the GitHub-computed
# merge of the PR head into the current base tip — never the bare PR head. A
# two-dot diff of a local head against origin/master (the old approach) can
# include/omit unrelated upstream changes whenever the branch is behind or has
# diverged, and never proves the local tree even equals the public PR head.
# This script instead:
#   1. resolves the PUBLIC PR head OID via `gh api` and REJECTS if the local
#      ref does not match it exactly (no silent proceed on a stale/wrong ref),
#   2. requires the PR's PUBLIC base to be `master`, and AUTHENTICATES the
#      base by comparing the freshly fetched `origin/master` tip against the
#      API's own `.base.sha` — a locally-fetched `origin/master` is never
#      trusted as "the public base" until it is proven equal to what the API
#      itself reports as the PR's base at query time,
#   3. reads `.mergeable`/`.mergeable_state` and gates on them: false exits
#      2 immediately; unknown (still computing) is retried a few times, and
#      still-unknown after retries exits 2 — synthetic merge construction is
#      only ever a fallback for a true mergeable PR whose merge ref happens
#      to be momentarily unavailable, never a way to paper over a real
#      conflict or an unresolved GitHub computation,
#   4. fetches the guarded merge ref (`refs/pull/<N>/merge`), verifying its
#      parents are exactly {authenticated base SHA, public head OID} —
#      falling back to constructing the same merge deterministically only
#      if the merge ref is unavailable, and failing loud if that merge does
#      not apply cleanly,
#   5. runs both CI steps inside a clean temporary worktree checked out at
#      that merge commit, against the authenticated base,
#   6. pulls the LIVE PR body via `gh api` (CI's github.event.pull_request.body
#      is a webhook-payload SNAPSHOT; `gh run rerun` replays it, so a body
#      edit only lands via a fresh event — this script always reads the
#      current body) and refuses to proceed on any API failure or an empty
#      body — never a silent pass-through.
#
# Usage:
#   bash src/ember/infrastructure/tools/pr_authbind_preflight.sh <PR_NUMBER> [<LOCAL_HEAD_REF>]
# Exit 0 only if ALL of Step A (repo-guard structural kernel), Step B (PR-body +
# changed-artifact authority binding), and Step C (the live PR policy: labels,
# milestone, title grammar, template marker, required body sections, the
# label/milestone vocabulary, and the closing-linkage check against the real
# fetched closingIssuesReferences) pass against the merge ref.
# Exit 2 on any preflight-validity failure (head mismatch, non-master base,
# unauthenticated/stale base, mergeable=false or persistently unknown,
# unresolvable/stale merge ref, non-clean merge, API failure, empty body) —
# these are never guard verdicts; they mean the preflight cannot yet speak
# for the public job, and it never proceeds past one to find out anyway.
#
# Step C exists because A and B alone were not the whole public verdict. A PR
# could pass both and still fail ci-pr, guard, and python together, all three
# reporting labels:*-cardinality and milestone:required-or-exception — rules
# neither earlier step looks at. Step C delegates to the same
# validate_live_pull_request() the CI gate calls, via
# scripts/github/pr_intent_policy.py, so the contract is not restated here. To
# check a PR that does not exist yet, use src/ember/infrastructure/tools/pr_intent_preflight.sh.

set -u
ROOT="$(git rev-parse --show-toplevel)" || { echo "not in a git repo"; exit 2; }
cd "$ROOT"

PR="${1:?usage: pr_authbind_preflight.sh <PR_NUMBER> [<HEAD_REF>]}"
HEAD_REF="${2:-HEAD}"
MERGEABLE_RETRIES="${PR_AUTHBIND_PREFLIGHT_MERGEABLE_RETRIES:-3}"
MERGEABLE_RETRY_SLEEP="${PR_AUTHBIND_PREFLIGHT_MERGEABLE_RETRY_SLEEP:-2}"

command -v gh >/dev/null 2>&1 || { echo "FAIL: gh CLI not available"; exit 2; }

# owner/repo from origin
SLUG="$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null)"
[ -z "$SLUG" ] && { echo "FAIL: cannot resolve owner/repo from gh"; exit 2; }

echo "== preflight: PR #$PR  head=$HEAD_REF  repo=$SLUG =="

# -- (1) public PR head/base/mergeable, retrying while mergeable is unknown --
fetch_pr_info() {
  gh api "repos/${SLUG}/pulls/${PR}" \
    --jq '[.head.sha, .base.ref, .base.sha, (.mergeable|tostring), (.mergeable_state // "unknown")] | @tsv' \
    2>/dev/null
}

PR_INFO="$(fetch_pr_info)" || { echo "FAIL: gh api pulls/$PR"; exit 2; }
[ -z "$PR_INFO" ] && { echo "FAIL: gh api pulls/$PR returned no data"; exit 2; }
IFS=$'\t' read -r PUBLIC_HEAD BASE_REF PUBLIC_BASE_SHA MERGEABLE MERGEABLE_STATE <<<"$PR_INFO"

ATTEMPT=0
while [ "$MERGEABLE" = "null" ] && [ "$ATTEMPT" -lt "$MERGEABLE_RETRIES" ]; do
  ATTEMPT=$((ATTEMPT + 1))
  echo "   mergeable still computing (attempt $ATTEMPT/$MERGEABLE_RETRIES) — retrying after ${MERGEABLE_RETRY_SLEEP}s"
  sleep "$MERGEABLE_RETRY_SLEEP"
  PR_INFO="$(fetch_pr_info)" || { echo "FAIL: gh api pulls/$PR (retry $ATTEMPT)"; exit 2; }
  [ -z "$PR_INFO" ] && { echo "FAIL: gh api pulls/$PR returned no data (retry $ATTEMPT)"; exit 2; }
  IFS=$'\t' read -r PUBLIC_HEAD BASE_REF PUBLIC_BASE_SHA MERGEABLE MERGEABLE_STATE <<<"$PR_INFO"
done

[ -z "$PUBLIC_HEAD" ] && { echo "FAIL: could not resolve public head OID for PR #$PR"; exit 2; }
echo "   public PR #$PR: head=$PUBLIC_HEAD base=$BASE_REF($PUBLIC_BASE_SHA) mergeable=$MERGEABLE ($MERGEABLE_STATE)"

if [ "$BASE_REF" != "master" ]; then
  echo "FAIL: PR #$PR base branch is '$BASE_REF', not master — this preflight only predicts the master repo-guard job"
  exit 2
fi

if [ "$MERGEABLE" = "false" ]; then
  echo "FAIL: PR #$PR mergeable=false — GitHub cannot merge the head into the base cleanly; fix the conflict upstream, don't preflight around it"
  exit 2
fi
if [ "$MERGEABLE" != "true" ]; then
  echo "FAIL: PR #$PR mergeable is still '$MERGEABLE' after $MERGEABLE_RETRIES retries (state=$MERGEABLE_STATE) — cannot predict a verdict for an unresolved merge computation"
  exit 2
fi

# -- (2) local head must be the exact public head, no silent proceed --------
LOCAL_HEAD_OID="$(git rev-parse "${HEAD_REF}^{commit}" 2>/dev/null)" \
  || { echo "FAIL: cannot resolve local ref '$HEAD_REF' to a commit"; exit 2; }
if [ "$LOCAL_HEAD_OID" != "$PUBLIC_HEAD" ]; then
  echo "FAIL: local head ($HEAD_REF = $LOCAL_HEAD_OID) != public PR #$PR head ($PUBLIC_HEAD)"
  echo "      the preflight only predicts the verdict for the ref that is ACTUALLY the PR head"
  exit 2
fi
echo "   local head confirmed == public PR head ($PUBLIC_HEAD)"

# -- (3) authenticate the base: a fetched origin/master is only trustworthy
#        once proven equal to the API's own .base.sha at query time ---------
echo "-- fetching fresh origin/master"
git fetch --quiet origin master || { echo "FAIL: git fetch origin master"; exit 2; }
MASTER_TIP="$(git rev-parse origin/master)"
if [ "$MASTER_TIP" != "$PUBLIC_BASE_SHA" ]; then
  echo "FAIL: fetched origin/master ($MASTER_TIP) != public PR #$PR base sha ($PUBLIC_BASE_SHA)"
  echo "      local base is stale or has diverged from the public base since the API was queried — refetch and retry, never assume they match"
  exit 2
fi
AUTH_BASE_SHA="$MASTER_TIP"
echo "   fetched origin/master confirmed == public base sha ($AUTH_BASE_SHA)"

# -- (4) resolve the guarded merge ref, falling back to constructing it ------
TMPWT="$(mktemp -d)"
WORK_C="$(mktemp -d -t pr_policy_c.XXXXXX)"
BODY_FILE=""
cleanup() {
  git worktree remove --force "$TMPWT" >/dev/null 2>&1
  rm -rf "$TMPWT" "$WORK_C"
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
  EXPECTED_SORTED="$(printf '%s\n' "$AUTH_BASE_SHA" "$PUBLIC_HEAD" | sort)"
  if [ "$ACTUAL_SORTED" != "$EXPECTED_SORTED" ]; then
    echo "FAIL: stale refs/pull/${PR}/merge — parents ($ACTUAL_SORTED) != expected (authenticated base + public head: $EXPECTED_SORTED)"
    echo "      GitHub has not recomputed the merge ref against the current base; do not trust it yet"
    exit 2
  fi
  echo "   using guarded merge ref refs/pull/${PR}/merge ($CANDIDATE), parents verified"
  MERGE_OID="$CANDIDATE"
else
  echo "   refs/pull/${PR}/merge unavailable — constructing the merge deterministically"
  git worktree add --detach --quiet "$TMPWT" "$AUTH_BASE_SHA" || { echo "FAIL: worktree add at authenticated base"; exit 2; }
  WORKTREE_MADE=1
  if ! git -C "$TMPWT" merge --no-ff --no-commit "$PUBLIC_HEAD" >/dev/null 2>&1; then
    echo "FAIL: PR #$PR head ($PUBLIC_HEAD) does not merge cleanly onto the authenticated base ($AUTH_BASE_SHA)"
    echo "      (this contradicts mergeable=true from the API — fail loud rather than guess)"
    exit 2
  fi
  git -C "$TMPWT" commit --no-edit -m "preflight: synthetic merge PR #$PR ($PUBLIC_HEAD) into base ($AUTH_BASE_SHA)" >/dev/null \
    || { echo "FAIL: could not commit constructed merge"; exit 2; }
  MERGE_OID="$(git -C "$TMPWT" rev-parse HEAD)"
  echo "   constructed merge commit $MERGE_OID (parents: $AUTH_BASE_SHA $PUBLIC_HEAD)"
fi

# If the merge-ref path was taken (worktree not yet materialized), check it out now.
if [ "$WORKTREE_MADE" -eq 0 ]; then
  git worktree add --detach --quiet "$TMPWT" "$MERGE_OID" || { echo "FAIL: worktree add at merge ref $MERGE_OID"; exit 2; }
fi

# -- (5) LIVE body (never the event snapshot); fail closed on any API hiccup
#        or an empty body — never a silent proceed --------------------------
BODY_FILE="$(mktemp -t pr_body.XXXXXX)"
gh api "repos/${SLUG}/pulls/${PR}" --jq '.body // ""' > "$BODY_FILE" 2>/dev/null \
  || { echo "FAIL: gh api pulls/$PR (body)"; exit 2; }
if ! grep -q '[^[:space:]]' "$BODY_FILE"; then
  echo "FAIL: live PR body for #$PR is empty — cannot bind authority against an empty body, refusing to proceed"
  exit 2
fi
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
echo "== Step C: live PR policy incl. labels, milestone, title, body sections =="
# Steps A and B reproduce the repo-guard and authority-binding jobs. They do not
# look at labels, milestone, or title, so a PR could pass both and still fail
# ci-pr, guard, and python on labels:*-cardinality and milestone:required-or-exception.
# This step runs the same policy CI runs, plus the vocabulary check that only
# matters before GitHub has accepted the metadata.
step_c() {
  gh api "repos/${SLUG}/pulls/${PR}" > "$WORK_C/pr.json" 2>/dev/null || return 2
  gh api --paginate --slurp "repos/${SLUG}/pulls/${PR}/files?per_page=100" \
    > "$WORK_C/files.json" 2>/dev/null || return 2
  gh api "repos/${SLUG}/labels?per_page=100" --paginate --slurp \
    > "$WORK_C/labels.json" 2>/dev/null || return 2
  gh api "repos/${SLUG}/milestones?state=all&per_page=100" --paginate --slurp \
    > "$WORK_C/milestones.json" 2>/dev/null || return 2
  # A live PR already has a real closingIssuesReferences computed by GitHub;
  # fetch it rather than guessing, so Step C can actually predict the
  # closing-linkage check instead of being structurally blind to it.
  gh api graphql \
    -f query='query($owner:String!,$repo:String!,$number:Int!){repository(owner:$owner,name:$repo){pullRequest(number:$number){closingIssuesReferences(first:50){nodes{number}}}}}' \
    -F owner="${SLUG%%/*}" -F repo="${SLUG#*/}" -F number="${PR}" \
    --jq '[.data.repository.pullRequest.closingIssuesReferences.nodes[].number]' \
    > "$WORK_C/closing-issues.json" 2>/dev/null || return 2
  (
    cd "$TMPWT" || exit 2
    PR_C_DIR="$WORK_C" PR_C_BASE="$AUTH_BASE_SHA" PR_C_HEAD="$PUBLIC_HEAD" python -c '
import json, os, pathlib
from scripts.github.live_pr_policy import build_snapshot
from scripts.github.pr_intent_policy import DERIVED_FIELDS
work = pathlib.Path(os.environ["PR_C_DIR"])
snapshot = build_snapshot(
    json.loads((work / "pr.json").read_text(encoding="utf-8")),
    json.loads((work / "files.json").read_text(encoding="utf-8")),
    event_base_sha=os.environ["PR_C_BASE"],
    event_head_sha=os.environ["PR_C_HEAD"],
    closing_issue_numbers=json.loads((work / "closing-issues.json").read_text(encoding="utf-8")),
)
intent = {k: v for k, v in snapshot.items() if k not in DERIVED_FIELDS}
(work / "intent.json").write_text(json.dumps(intent), encoding="utf-8")
' || exit 2
    python -m scripts.github.pr_intent_policy \
      --root . \
      --intent-json "$WORK_C/intent.json" \
      --labels-json "$WORK_C/labels.json" \
      --milestones-json "$WORK_C/milestones.json"
  )
}

step_c
STEP_C_RC=$?
if [ "$STEP_C_RC" -eq 0 ]; then
  echo "Step C: PASS"
elif [ "$STEP_C_RC" -eq 2 ]; then
  echo "Step C: FAIL (could not acquire live metadata or the label/milestone vocabulary)"
  RC=1
else
  echo "Step C: FAIL"
  RC=1
fi

echo
if [ "$RC" -eq 0 ]; then
  echo "PREFLIGHT: PASS — predicts public repo-guard AND live-PR-policy GREEN for PR #$PR (merge ref $MERGE_OID)"
  echo "   (if the public job is nonetheless RED, CI used a STALE body snapshot:"
  echo "    push a fresh event — empty commit or close/reopen — never 'gh run rerun'.)"
else
  echo "PREFLIGHT: FAIL — a public job would be RED for PR #$PR (see Step A/B/C above)"
fi
exit "$RC"
