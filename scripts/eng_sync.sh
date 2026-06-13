#!/usr/bin/env bash
# eng_sync.sh — engineering-tracker enforcement (runs from the cron tick).
#
# Contract being enforced (issues #1-#10, label `eng`):
#   1. Every eng item is a GitHub issue; the CC tasklist mirrors it in-session.
#   2. An eng issue may be CLOSED only by a merged PR ("Closes #<n>").
#      Closed-without-PR = gate violation -> flagged here, reopen + investigate.
#   3. An open issue whose closing PR already merged = stale -> flagged.
#   4. Tick duty: if nothing gates and the GPU is busy, advance exactly ONE
#      open eng issue: branch eng/<n>-<slug>, implement, PR "Closes #<n>",
#      merge on green. (The tick reads this script's output to pick it.)
#
# Local-only by design: GitHub Actions/workflows are not used (requires
# sign-off per project rules). Receipt: receipts/eng-sync-<ts>.json
set -euo pipefail
cd "$(dirname "$0")/.."

TS=$(date -u +%Y%m%dT%H%M%SZ)
OPEN_JSON=$(gh issue list --label eng --state open \
  --json number,title,updatedAt --limit 100)
CLOSED_JSON=$(gh issue list --label eng --state closed \
  --json number,title,stateReason --limit 100)

# closed-without-merged-PR check (violation) — per-issue query.
# NOTE: must use GraphQL directly — `gh issue view --json` FLATTENS the
# closing-PR refs and drops the `merged` field (every closure looked like a
# violation; bug surfaced by Kai checkpoint 14424 S1-C follow-up 2026-06-10).
# NOTE 2 (#323): closedByPullRequestsReferences is ALSO empty when GitHub
# closes the issue via the squash-commit message keyword ("Closes #N" in the
# squash title) — the common path here. Fallback: the CLOSED_EVENT closer.
# Closer = Commit (oid recorded) or merged PullRequest -> legitimate;
# closer null / query failure -> genuine violation (manual button-close).
OWNER=$(gh repo view --json owner --jq .owner.login)
NAME=$(gh repo view --json name --jq .name)
VIOLATIONS="["
COMMIT_CLOSED="["
first=1
cfirst=1
# NOTE 3 (#369, 2026-06-13): stateReason==NOT_PLANNED is an INTENTIONAL closure
# (duplicate / won't-do), not a silent drop of completed work. The violation we
# hunt is COMPLETED-without-merged-PR. Exempt NOT_PLANNED from the loop so a
# legitimate dup-close (e.g. #369 = dup of #368) does not false-flag every tick.
# NOTE 4 (#373, 2026-06-13): issues whose deliverable landed via a merged PR that
# did NOT use a "Closes #N" keyword (so GitHub recorded no closing-PR link and the
# issue shows a manual button-close, closer=null). Leo-verified complete against
# the named merged PR. Format "issue:pr" space-separated. #373's compile patch
# landed via merged PR #380 (titled "eng-353…", no Closes-keyword for 373).
VERIFIED_VIA_PR="373:380"
for n in $(echo "$CLOSED_JSON" | jq -r '.[] | select(.stateReason != "NOT_PLANNED") | .number' || true); do
  vpr=$(echo "$VERIFIED_VIA_PR" | tr ' ' '\n' | awk -F: -v i="$n" '$1==i{print $2}')
  if [ -n "$vpr" ]; then
    [ $cfirst -eq 0 ] && COMMIT_CLOSED="$COMMIT_CLOSED,"
    COMMIT_CLOSED="$COMMIT_CLOSED{\"issue\":$n,\"closed_by\":\"verified-pr:$vpr\"}"
    cfirst=0
    continue
  fi
  prs=$(gh api graphql -f query="query{repository(owner:\"$OWNER\",name:\"$NAME\"){issue(number:$n){closedByPullRequestsReferences(first:20){nodes{merged}}}}}" \
        --jq '[.data.repository.issue.closedByPullRequestsReferences.nodes[] | select(.merged==true)] | length' \
        2>/dev/null || echo "QUERY_FAIL")
  if [ "$prs" = "0" ] || [ "$prs" = "QUERY_FAIL" ]; then
    closer=$(gh api graphql -f query="query{repository(owner:\"$OWNER\",name:\"$NAME\"){issue(number:$n){timelineItems(itemTypes:CLOSED_EVENT,last:1){nodes{... on ClosedEvent{closer{__typename ... on Commit{oid} ... on PullRequest{number merged}}}}}}}}" \
        --jq '.data.repository.issue.timelineItems.nodes[0].closer | if .==null then "null" elif .__typename=="Commit" then "commit:"+.oid elif (.__typename=="PullRequest" and .merged==true) then "pr:"+(.number|tostring) else "other" end' \
        2>/dev/null || echo "QUERY_FAIL")
    case "$closer" in
      commit:*|pr:*)
        [ $cfirst -eq 0 ] && COMMIT_CLOSED="$COMMIT_CLOSED,"
        COMMIT_CLOSED="$COMMIT_CLOSED{\"issue\":$n,\"closed_by\":\"$closer\"}"
        cfirst=0
        ;;
      *)
        [ $first -eq 0 ] && VIOLATIONS="$VIOLATIONS,"
        VIOLATIONS="$VIOLATIONS{\"issue\":$n,\"merged_closing_prs\":\"$prs\",\"closer\":\"$closer\"}"
        first=0
        ;;
    esac
  fi
done
VIOLATIONS="$VIOLATIONS]"
COMMIT_CLOSED="$COMMIT_CLOSED]"

OPEN_N=$(echo "$OPEN_JSON" | { grep -o '"number":[0-9]*' || true; } | wc -l | tr -d ' ')
CLOSED_N=$(echo "$CLOSED_JSON" | { grep -o '"number":[0-9]*' || true; } | wc -l | tr -d ' ')

mkdir -p receipts
cat > "receipts/eng-sync-$TS.json" <<EOF
{"ticket":"ENG-SYNC","ts":"$TS","open":$OPEN_N,"closed":$CLOSED_N,
"closed_without_merged_pr":$VIOLATIONS,
"closed_by_commit":$COMMIT_CLOSED,
"open_issues":$OPEN_JSON}
EOF

echo "ENG-SYNC $TS — open:$OPEN_N closed:$CLOSED_N"
if [ "$VIOLATIONS" != "[]" ]; then
  echo "GATE-VIOLATION closed-without-merged-PR: $VIOLATIONS"
  echo "ACTION: reopen the issue(s), investigate the closure, restore tracking."
fi
echo "$OPEN_JSON" | python -c "
import json,sys
rows=json.load(sys.stdin)
for r in sorted(rows,key=lambda x:x['number']):
    print(f'  open #{r[\"number\"]}: {r[\"title\"]}')" 2>/dev/null || true

# Receipt-schema sweep (report-only; fail-closed lives at write time via checked_write)
echo "--- receipt_check sweep (report-only) ---"
python scripts/receipt_check.py --all receipts 2>&1 || true
echo "--- end receipt_check sweep ---"

echo "ENG_SYNC_DONE (receipt: receipts/eng-sync-$TS.json)"
