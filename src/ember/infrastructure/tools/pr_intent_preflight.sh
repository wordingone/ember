#!/usr/bin/env bash
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
#
# Pre-OPEN pull-request policy preflight.
#
# src/ember/infrastructure/tools/pr_authbind_preflight.sh answers "would repo-guard and the authority
# binding pass for a PR that already exists". It deliberately reproduces only
# those two CI steps, so a PR can pass it and still go red on ci-pr, guard, and
# python together, all reporting the same thing: the live PR policy also demands
# a complete label set, a milestone, a conforming title, and a body carrying the
# template marker and every required section. None of that is checkable by the
# authbind preflight, and none of it is visible until after `gh pr create`.
#
# This script closes that gap by validating the PR you are ABOUT to open. It
# gathers the mechanical facts (your login, the base tip, your head, the changed
# files) and the repository's live label and milestone vocabulary, combines them
# with the title, body, labels, and milestone you intend to use, and hands the
# result to src/ember/governance/scripts/github/pr_intent_policy.py -- which delegates every policy
# question to the same validate_live_pull_request() the CI gate calls. The rules
# are never restated here; only the inputs are assembled earlier.
#
# The two checks this adds beyond the gate are vocabulary checks: that each
# intended label and the intended milestone actually exist. The gate can assume
# they do, because GitHub rejects unknown ones at apply time -- but before the PR
# exists nothing has been applied, and `area:tooling` counts toward the `area:`
# family exactly as convincingly as `area:tools` does.
#
# Usage:
#   bash src/ember/infrastructure/tools/pr_intent_preflight.sh \
#     --title "fix(scope): summary" \
#     --body-file /path/to/body.md \
#     --label kind:defect --label area:tools --label state:review \
#     --label priority:p2 --label review:self-only \
#     --milestone "EMBER-02 — Three-billion-parameter foundation birth"
#
#   bash src/ember/infrastructure/tools/pr_intent_preflight.sh --intent-json /path/to/intent.json
#
# --base defaults to origin/master and --head to HEAD. Exit 0 only if the
# intended PR would satisfy the live policy; 1 on a policy verdict of FAIL; 2 on
# any preflight-validity failure (missing gh, unreadable body, no changed files),
# which is never a policy verdict -- it means the check could not speak at all.

set -u

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "FAIL: not in a git repo"; exit 2; }
cd "$ROOT" || { echo "FAIL: cannot enter repo root"; exit 2; }

TITLE=""
BODY_FILE=""
MILESTONE=""
INTENT_JSON=""
BASE_REF="origin/master"
HEAD_REF="HEAD"
LABELS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --title)       TITLE="${2:?--title needs a value}"; shift 2;;
    --body-file)   BODY_FILE="${2:?--body-file needs a value}"; shift 2;;
    --label)       LABELS+=("${2:?--label needs a value}"); shift 2;;
    --milestone)   MILESTONE="${2:?--milestone needs a value}"; shift 2;;
    --base)        BASE_REF="${2:?--base needs a value}"; shift 2;;
    --head)        HEAD_REF="${2:?--head needs a value}"; shift 2;;
    --intent-json) INTENT_JSON="${2:?--intent-json needs a value}"; shift 2;;
    -h|--help)     sed -n '6,45p' "$0"; exit 0;;
    *) echo "FAIL: unknown argument: $1"; exit 2;;
  esac
done

command -v gh >/dev/null 2>&1 || { echo "FAIL: gh CLI not available"; exit 2; }

SLUG="$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null)"
[ -z "$SLUG" ] && { echo "FAIL: cannot resolve owner/repo from gh"; exit 2; }

WORK="$(mktemp -d -t pr_intent.XXXXXX)" || { echo "FAIL: mktemp"; exit 2; }
trap 'rm -rf "$WORK"' EXIT

# -- vocabulary: required, never optional. A skipped vocabulary check is exactly
#    the failure mode this script exists to remove, so fetch failures are fatal.
gh api "repos/${SLUG}/labels?per_page=100" --paginate --slurp > "$WORK/labels.json" 2>/dev/null \
  || { echo "FAIL: gh api labels — cannot validate against an unknown vocabulary"; exit 2; }
gh api "repos/${SLUG}/milestones?state=all&per_page=100" --paginate --slurp > "$WORK/milestones.json" 2>/dev/null \
  || { echo "FAIL: gh api milestones — cannot validate against an unknown vocabulary"; exit 2; }

if [ -n "$INTENT_JSON" ]; then
  [ -r "$INTENT_JSON" ] || { echo "FAIL: cannot read --intent-json $INTENT_JSON"; exit 2; }
  cp "$INTENT_JSON" "$WORK/intent.json" || { echo "FAIL: cannot stage intent JSON"; exit 2; }
  echo "== pre-open preflight: intent from $INTENT_JSON  repo=$SLUG =="
else
  [ -n "$TITLE" ] || { echo "FAIL: --title is required (or use --intent-json)"; exit 2; }
  [ -n "$BODY_FILE" ] || { echo "FAIL: --body-file is required (or use --intent-json)"; exit 2; }
  [ -r "$BODY_FILE" ] || { echo "FAIL: cannot read --body-file $BODY_FILE"; exit 2; }

  git fetch origin master --quiet 2>/dev/null || true
  BASE_SHA="$(git rev-parse "$BASE_REF" 2>/dev/null)" || { echo "FAIL: cannot resolve --base $BASE_REF"; exit 2; }
  HEAD_SHA="$(git rev-parse "$HEAD_REF" 2>/dev/null)" || { echo "FAIL: cannot resolve --head $HEAD_REF"; exit 2; }
  ACTOR="$(gh api user --jq .login 2>/dev/null)"
  [ -z "$ACTOR" ] && { echo "FAIL: cannot resolve your GitHub login"; exit 2; }

  git diff --name-only "${BASE_SHA}..${HEAD_SHA}" > "$WORK/changed.txt" 2>/dev/null \
    || { echo "FAIL: cannot diff ${BASE_SHA}..${HEAD_SHA}"; exit 2; }
  if ! grep -q '[^[:space:]]' "$WORK/changed.txt"; then
    echo "FAIL: no changed files in ${BASE_REF}..${HEAD_REF} — nothing to open a PR for"
    exit 2
  fi

  echo "== pre-open preflight: $HEAD_REF ($HEAD_SHA) onto $BASE_REF ($BASE_SHA)  repo=$SLUG =="
  echo "   changed files: $(wc -l < "$WORK/changed.txt")"
  echo "   labels: ${LABELS[*]:-<none>}"
  echo "   milestone: ${MILESTONE:-<none>}"

  PR_INTENT_ACTOR="$ACTOR" \
  PR_INTENT_TITLE="$TITLE" \
  PR_INTENT_BODY_FILE="$BODY_FILE" \
  PR_INTENT_BASE_SHA="$BASE_SHA" \
  PR_INTENT_HEAD_SHA="$HEAD_SHA" \
  PR_INTENT_MILESTONE="$MILESTONE" \
  PR_INTENT_CHANGED_FILE="$WORK/changed.txt" \
  PR_INTENT_LABELS="$(printf '%s\n' ${LABELS[@]+"${LABELS[@]}"})" \
  python -c '
import json, os, pathlib
labels = [row for row in os.environ["PR_INTENT_LABELS"].splitlines() if row.strip()]
changed = [
    row.strip()
    for row in pathlib.Path(os.environ["PR_INTENT_CHANGED_FILE"]).read_text(encoding="utf-8").splitlines()
    if row.strip()
]
milestone = os.environ["PR_INTENT_MILESTONE"] or None
intent = {
    "actor_login": os.environ["PR_INTENT_ACTOR"],
    "title": os.environ["PR_INTENT_TITLE"],
    "body": pathlib.Path(os.environ["PR_INTENT_BODY_FILE"]).read_text(encoding="utf-8"),
    "base_sha": os.environ["PR_INTENT_BASE_SHA"],
    "head_sha": os.environ["PR_INTENT_HEAD_SHA"],
    "draft": False,
    "labels": labels,
    "milestone": milestone,
    "changed_files": changed,
    # No PR exists yet at pre-open time, so GitHub has computed zero closing
    # references -- this is the exact live value, not an approximation of it.
    "closing_issue_numbers": [],
}
print(json.dumps(intent))
' > "$WORK/intent.json" || { echo "FAIL: could not assemble the PR intent"; exit 2; }
fi

echo
echo "== live PR policy against the intended pull request =="
if python -m src.ember.governance.scripts.github.pr_intent_policy \
    --root . \
    --intent-json "$WORK/intent.json" \
    --labels-json "$WORK/labels.json" \
    --milestones-json "$WORK/milestones.json"; then
  echo
  echo "PRE-OPEN PREFLIGHT: PASS — this PR would satisfy the live policy at open time."
  echo "   Still run src/ember/infrastructure/tools/pr_authbind_preflight.sh <N> after opening: repo-guard and the"
  echo "   merge-ref authority binding are evaluated against the merge commit, which does"
  echo "   not exist until the PR does."
  exit 0
fi

echo
echo "PRE-OPEN PREFLIGHT: FAIL — fix the errors above BEFORE 'gh pr create'."
echo "   Each error is the exact string the public gate would print."
exit 1
