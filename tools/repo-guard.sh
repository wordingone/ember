#!/usr/bin/env bash
# repo-guard — the structural-invariant kernel for this repository.
#
# One script, run identically by (1) the local pre-commit/pre-push hook,
# (2) the GitHub Actions required status check, and (3) the scheduled
# freshness monitor. Every invariant the repo must never violate is asserted
# here. If this exits non-zero, the offending change does not land.
#
# This file is PUBLIC. It must contain no operator names and no absolute local
# paths. The operator-name denylist is supplied at runtime, never committed:
#   - env var  REPO_GUARD_NAMES   = pipe-separated names (CI injects from a secret), or
#   - local file tools/.repo-guard-denylist (one name per line; git-ignored).
# If neither is present, the name check is SKIPPED with a notice; all other
# (structural) checks still run.
#
# Usage:
#   tools/repo-guard.sh                 # check the tracked tree (default)
#   tools/repo-guard.sh --range A..B    # also check commits in range A..B
#   tools/repo-guard.sh --base master   # range = merge-base(master,HEAD)..HEAD
#
# Tunables (env): MAX_STATE_LINES (default 150), MAX_BRANCHES (default 25).

set -u
cd "$(git rev-parse --show-toplevel)" || { echo "repo-guard: not in a git repo"; exit 2; }

FAIL=0
note() { printf '  - %s\n' "$1"; }
fail() { printf 'FAIL [%s] %s\n' "$1" "$2"; FAIL=1; }
ok()   { printf 'ok   [%s] %s\n' "$1" "$2"; }

MAX_STATE_LINES="${MAX_STATE_LINES:-150}"
MAX_BRANCHES="${MAX_BRANCHES:-25}"

# ---- 1. agent-harness machinery must never be tracked --------------------
if [ -n "$(git ls-files .agent 2>/dev/null | head -1)" ]; then
  fail ".agent" "agent-harness machinery is tracked; it must be git-ignored"
  git ls-files .agent | sed 's/^/      /' | head -10
else
  ok ".agent" "not tracked"
fi

# ---- 1b. tracked text files must be LF-only ------------------------------
if python tools/check_line_endings.py; then
  :
else
  FAIL=1
fi

# ---- 2. no absolute local filesystem paths in tracked text ---------------
# Matches <local-workspace-root>, <local-workspace-root>, <local-user-home>, <local-user-home>, <local> <local-mount>/ and similar.
PATHPAT='([A-Za-z]:[/\\](Users|M|Downloads))|(/mnt/[a-z]/)'
if git grep -nIE "$PATHPAT" -- . ':(exclude)tools/repo-guard.sh' >/tmp/rg_paths 2>/dev/null && [ -s /tmp/rg_paths ]; then
  fail "paths" "absolute local filesystem paths in tracked files"
  sed 's/^/      /' /tmp/rg_paths | head -20
else
  ok "paths" "no absolute local paths"
fi

# ---- 3. no operator names in tracked text (denylist supplied at runtime) --
NAMES=""
if [ -n "${REPO_GUARD_NAMES:-}" ]; then
  NAMES="$REPO_GUARD_NAMES"
elif [ -f tools/.repo-guard-denylist ]; then
  NAMES="$(grep -vE '^\s*(#|$)' tools/.repo-guard-denylist | paste -sd '|' -)"
fi
if [ -z "$NAMES" ]; then
  printf 'skip [names] no denylist supplied; structural checks still enforced\n'
else
  if git grep -nIiE "\b(${NAMES})\b" -- . ':(exclude)tools/repo-guard.sh' ':(exclude)tools/.repo-guard-denylist' >/tmp/rg_names 2>/dev/null && [ -s /tmp/rg_names ]; then
    fail "names" "operator names in tracked files"
    sed 's/^/      /' /tmp/rg_names | head -20
  else
    ok "names" "none found"
  fi
fi

# ---- 4. exactly one root goal document -----------------------------------
GOALN="$(git ls-files | grep -cE '^GOAL[^/]*\.md$')"
if [ "$GOALN" -eq 1 ]; then
  ok "goal-doc" "exactly one (GOAL.md)"
else
  fail "goal-doc" "found $GOALN root GOAL*.md files; exactly one canonical GOAL.md is allowed"
  git ls-files | grep -E '^GOAL[^/]*\.md$' | sed 's/^/      /'
fi

# ---- 5. no duplicate/overlapping top-level directories -------------------
check_dup() {
  local a="$1" b="$2"
  if [ -n "$(git ls-files "$a" | head -1)" ] && [ -n "$(git ls-files "$b" | head -1)" ]; then
    fail "dup-dir" "both '$a' and '$b' are tracked; merge into one"
  fi
}
check_dup config configs
check_dup receipts ledger
DUPOK=$?
[ "$FAIL" -eq 0 ] && ok "dup-dir" "no known duplicate dirs"

# ---- 6. STATE.md is a bounded position ledger, not an append log ---------
if git ls-files --error-unmatch STATE.md >/dev/null 2>&1; then
  SL="$(git show ":STATE.md" 2>/dev/null | wc -l | tr -d ' ')"
  [ -z "$SL" ] && SL="$(wc -l < STATE.md | tr -d ' ')"
  if [ "$SL" -le "$MAX_STATE_LINES" ]; then
    ok "state" "STATE.md $SL lines (<= $MAX_STATE_LINES)"
  else
    fail "state" "STATE.md $SL lines exceeds $MAX_STATE_LINES — it is a position ledger, not an append log"
  fi
fi

# ---- 7. branch name follows the single scheme ----------------------------
BR="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
case "$BR" in
  master|HEAD) ok "branch" "$BR" ;;
  feat/*|fix/*|exp/*|chore/*|docs/*|codex/*) ok "branch" "$BR" ;;
  *) fail "branch" "branch '$BR' must match <type>/<slug> where type in feat|fix|exp|chore|docs, or codex/* for short-lived agent staging" ;;
esac

# ---- 8. range checks: goal edits and evidence edits never co-commit ------
RANGE=""
if [ "${1:-}" = "--range" ] && [ -n "${2:-}" ]; then
  RANGE="$2"
elif [ "${1:-}" = "--base" ] && [ -n "${2:-}" ]; then
  RANGE="$(git merge-base "$2" HEAD)..HEAD"
fi
if [ -n "$RANGE" ]; then
  BAD=""
  for c in $(git rev-list "$RANGE" 2>/dev/null); do
    files="$(git show --name-only --format= "$c")"
    if echo "$files" | grep -qE '^GOAL[^/]*\.md$' && echo "$files" | grep -qE '^receipts/'; then
      BAD="$BAD $c"
    fi
  done
  if [ -n "$BAD" ]; then
    fail "goal/evidence" "commit(s) edit both GOAL.md and receipts/ in one change:$BAD"
  else
    ok "goal/evidence" "no goal+evidence co-commits in $RANGE"
  fi
fi

echo
if [ "$FAIL" -eq 0 ]; then echo "repo-guard: PASS"; else echo "repo-guard: FAIL"; fi
exit "$FAIL"
