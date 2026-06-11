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
  --json number,title --limit 100)

# closed-without-merged-PR check (violation) — per-issue query.
# NOTE: must use GraphQL directly — `gh issue view --json` FLATTENS the
# closing-PR refs and drops the `merged` field (every closure looked like a
# violation; bug surfaced by Kai checkpoint 14424 S1-C follow-up 2026-06-10).
OWNER=$(gh repo view --json owner --jq .owner.login)
NAME=$(gh repo view --json name --jq .name)
VIOLATIONS="["
first=1
for n in $(echo "$CLOSED_JSON" | grep -o '"number":[0-9]*' | grep -o '[0-9]*' || true); do
  prs=$(gh api graphql -f query="query{repository(owner:\"$OWNER\",name:\"$NAME\"){issue(number:$n){closedByPullRequestsReferences(first:20){nodes{merged}}}}}" \
        --jq '[.data.repository.issue.closedByPullRequestsReferences.nodes[] | select(.merged==true)] | length' \
        2>/dev/null || echo "QUERY_FAIL")
  if [ "$prs" = "0" ] || [ "$prs" = "QUERY_FAIL" ]; then
    [ $first -eq 0 ] && VIOLATIONS="$VIOLATIONS,"
    VIOLATIONS="$VIOLATIONS{\"issue\":$n,\"merged_closing_prs\":\"$prs\"}"
    first=0
  fi
done
VIOLATIONS="$VIOLATIONS]"

OPEN_N=$(echo "$OPEN_JSON" | { grep -o '"number":[0-9]*' || true; } | wc -l | tr -d ' ')
CLOSED_N=$(echo "$CLOSED_JSON" | { grep -o '"number":[0-9]*' || true; } | wc -l | tr -d ' ')

mkdir -p receipts
cat > "receipts/eng-sync-$TS.json" <<EOF
{"ticket":"ENG-SYNC","ts":"$TS","open":$OPEN_N,"closed":$CLOSED_N,
"closed_without_merged_pr":$VIOLATIONS,
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
