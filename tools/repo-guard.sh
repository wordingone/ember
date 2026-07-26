#!/usr/bin/env bash
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
# repo-guard — the structural-invariant kernel for this repository.
#
# One script, run identically by (1) the local pre-commit/pre-push hook,
# (2) the GitHub Actions required status check, and (3) the scheduled
# freshness monitor. Every invariant the repo must never violate is asserted
# here. If this exits non-zero, the offending change does not land.
#
# This file is PUBLIC. It must contain no operator names and no absolute local
# paths. The operator-name denylist is supplied at runtime, never committed as
# plaintext; three modes, checked in this priority order:
#   1. env var  REPO_GUARD_NAMES        = pipe-separated names (CI injects from a secret), or
#   2. local file tools/.repo-guard-denylist (one name per line; git-ignored), or
#   3. committed tools/repo-guard-denylist.sha256 (one sha256-per-lowercase-name;
#      contains no reversible names, safe to commit) via tools/check_names_hashed.py.
# Modes 1/2 take precedence when present (exact string match on the real names).
# Mode 3 lets CI enforce the same invariant with no secret at all. If none of the
# three is usable, the name check is SKIPPED with a notice; all other (structural)
# checks still run — except in a CI context, where an unusable name check is a
# hard failure (see step 3 below).
#
# Usage:
#   tools/repo-guard.sh                 # check the tracked tree (default)
#   tools/repo-guard.sh --range A..B    # also check commits in range A..B
#   tools/repo-guard.sh --base master   # range = merge-base(master,HEAD)..HEAD
#
# Tunables (env): MAX_STATE_LINES (default 150), MAX_BRANCHES (default 25).

set -u
SUBJECT_ROOT="${REPO_GUARD_SUBJECT_ROOT:-}"
if [ -z "$SUBJECT_ROOT" ]; then
  SUBJECT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
    echo "repo-guard: not in a git repo"
    exit 2
  }
fi
KERNEL_ROOT="${REPO_GUARD_KERNEL_ROOT:-$SUBJECT_ROOT}"
SUBJECT_ROOT="$(cd "$SUBJECT_ROOT" 2>/dev/null && pwd -P)" || {
  echo "repo-guard: subject root is unavailable"
  exit 2
}
KERNEL_ROOT="$(cd "$KERNEL_ROOT" 2>/dev/null && pwd -P)" || {
  echo "repo-guard: kernel root is unavailable"
  exit 2
}
git -C "$SUBJECT_ROOT" rev-parse --show-toplevel >/dev/null 2>&1 || {
  echo "repo-guard: subject root is not a git repository"
  exit 2
}
cd "$SUBJECT_ROOT" || exit 2

FAIL=0
note() { printf '  - %s\n' "$1"; }
fail() { printf 'FAIL [%s] %s\n' "$1" "$2"; FAIL=1; }
ok()   { printf 'ok   [%s] %s\n' "$1" "$2"; }

surface_bytes_match() {
  local relative="$1"
  local kernel_surface="$KERNEL_ROOT/$relative"
  local subject_surface="$SUBJECT_ROOT/$relative"
  [ -f "$kernel_surface" ] &&
    [ ! -L "$kernel_surface" ] &&
    [ -f "$subject_surface" ] &&
    [ ! -L "$subject_surface" ] &&
    cmp -s "$kernel_surface" "$subject_surface"
}

[ -f "$SUBJECT_ROOT/tools/repo-guard.sh" ] && [ ! -L "$SUBJECT_ROOT/tools/repo-guard.sh" ] ||
  fail "guard-kernel" "subject guard surface is missing"

MAX_STATE_LINES="${MAX_STATE_LINES:-150}"
MAX_BRANCHES="${MAX_BRANCHES:-25}"
PUSH_REMOTE_URL="${PUSH_REMOTE_URL:-}"
GATE_LOG="${GATE_LOG:-tools/.leak-gate.log}"

# Canonical backup URL — exact-match allowlist (tracked, reviewed via PR only)
CANONICAL_BACKUP_URL="https://github.com/wordingone/ember-backup.git"

# Check if this push is to the backup remote (exact match only, no patterns, fail-closed)
BACKUP_EXEMPTION_APPLIED=0
if [ -n "$PUSH_REMOTE_URL" ] && [ "$PUSH_REMOTE_URL" = "$CANONICAL_BACKUP_URL" ]; then
  BACKUP_EXEMPTION_APPLIED=1
  # Log the exemption
  mkdir -p "$(dirname "$GATE_LOG")"
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) backup-remote exemption applied" >> "$GATE_LOG" 2>/dev/null || true
  ok "backup-exemption" "NAME/leak scans SKIPPED for backup remote"
fi

# ---- 1. agent-harness machinery must never be tracked --------------------
if [ -n "$(git ls-files .agent 2>/dev/null | head -1)" ]; then
  fail ".agent" "agent-harness machinery is tracked; it must be git-ignored"
  git ls-files .agent | sed 's/^/      /' | head -10
else
  ok ".agent" "not tracked"
fi

# ---- 1b. tracked text files must be LF-only ------------------------------
if python "$KERNEL_ROOT/tools/check_line_endings.py" "$SUBJECT_ROOT"; then
  :
else
  FAIL=1
fi

# ---- 2. no absolute local filesystem paths in tracked text ---------------
# Matches B:/M, B:\M, C:/Users, C:\Users, C:\Windows\Temp, <local> /mnt/c/ and
# similar. Separator is one-OR-MORE / or \ (not exactly one): a real path
# embedded via json.dumps() or Python repr() has every backslash doubled
# (B:\M on disk becomes literal B:\\M in the tracked text), and a single-
# separator class silently misses that doubled form (issue #456 -- six such
# occurrences shipped in #455 before this fix, hand-redacted, never caught by
# this check). Windows+Temp is scoped to require the Temp segment specifically
# so a universal, non-identifying path like C:\Windows\System32\cmd.exe never
# false-positives here.
PATHPAT='([A-Za-z]:[/\\]+(Users|M|Downloads))|([A-Za-z]:[/\\]+[Ww][Ii][Nn][Dd][Oo][Ww][Ss][/\\]+[Tt][Ee][Mm][Pp])|(/mnt/[a-z]/)'
# Files that intentionally embed a leaked-path-shaped literal as adversarial
# test input (proving the app's own sanitization/redaction/clipping logic
# strips exactly this shape) -- these are the fixture, not a leak, and must
# keep the literal string to stay meaningful. See REDACTIONS.md (issue #456).
#
# Class 2 (issue #537, C2-restore ruling 2026-07-09): HASH-PINNED FROZEN
# ARTIFACTS. Byte-exact sha256 is load-bearing (C2 CHK frozen-rows hash-match
# + frozen-before law): redaction breaks the pin, re-pinning breaks
# frozen-before. Enumerated individually -- NEVER directory globs. Each entry
# has a REDACTIONS.md row. The operator-name checks still cover these files
# in full (this exclusion applies ONLY to the paths grep).
PATHPAT_FIXTURE_EXCLUDE_ARGS=(
  ':(exclude)scripts/test_w1b_continuation.py'
  ':(exclude)tools/ember-cli/src/core/monitor-render.test.ts'
  ':(exclude)tools/ember-cli/src/components/homescreen-mock1-parity.test.ts'
  ':(exclude)tools/ember-cli/src/components/logo-homescreen.test.ts'
  ':(exclude)receipts/ember-d3-native-loop/d3-gym-fresh-rows-offset20-len12-20260708T221652Z.json'
  ':(exclude)receipts/ember-d3-native-loop/d3-broader-multifamily-fresh-rows-reconstructed.json'
)
PATHPAT_SELF_EXCLUDE_ARGS=()
if surface_bytes_match 'tools/repo-guard.sh'; then
  PATHPAT_SELF_EXCLUDE_ARGS=(':(exclude)tools/repo-guard.sh')
fi
# Commit-time invocation (REPO_GUARD_SCOPE=staged, set by .githooks/pre-commit)
# scans only the ADDED lines of the staged diff, so a branch carrying
# pre-existing tracked residue with this shape does not block every commit
# regardless of what the commit actually introduces. The tree-wide scan
# (default, no env var) is unchanged and is what CI / the freshness monitor
# run. Same PATHPAT and conditional/fixture pathspecs, applied to the diff.
if [ "${REPO_GUARD_SCOPE:-}" = "staged" ]; then
  if git diff --cached -U0 --no-color -- . "${PATHPAT_SELF_EXCLUDE_ARGS[@]}" "${PATHPAT_FIXTURE_EXCLUDE_ARGS[@]}" | grep -E '^\+' | grep -vE '^\+\+\+' | grep -E "$PATHPAT" >/tmp/rg_paths 2>/dev/null && [ -s /tmp/rg_paths ]; then
    fail "paths" "absolute local filesystem paths in staged changes"
    sed 's/^/      /' /tmp/rg_paths | head -20
  else
    ok "paths" "no absolute local paths (staged scope)"
  fi
else
  if git grep -nIE "$PATHPAT" -- . "${PATHPAT_SELF_EXCLUDE_ARGS[@]}" "${PATHPAT_FIXTURE_EXCLUDE_ARGS[@]}" >/tmp/rg_paths 2>/dev/null && [ -s /tmp/rg_paths ]; then
    fail "paths" "absolute local filesystem paths in tracked files"
    sed 's/^/      /' /tmp/rg_paths | head -20
  else
    ok "paths" "no absolute local paths"
  fi
fi

# ---- 2b. no local path fragments in tracked text (avir/, /mnt refs) -------
# Detect patterns like /mnt/..../M/avir/ or /M/avir that carry developer-local context.
PATHFRAG='(/mnt/[^/]*/M/avir/)|(/M/avir)'
PATHFRAG_SELF_EXCLUDE_ARGS=()
for relative in \
  'tools/repo-guard.sh' \
  'tools/check_names_hashed.py' \
  'tools/repo-guard-denylist.sha256'
do
  if surface_bytes_match "$relative"; then
    PATHFRAG_SELF_EXCLUDE_ARGS+=(":(exclude)$relative")
  fi
done
if git grep -nIE "$PATHFRAG" -- . "${PATHFRAG_SELF_EXCLUDE_ARGS[@]}" >/tmp/rg_pathfrags 2>/dev/null && [ -s /tmp/rg_pathfrags ]; then
  fail "path-frags" "local WSL/mount path fragments in tracked files"
  sed 's/^/      /' /tmp/rg_pathfrags | head -20
else
  ok "path-frags" "no local path fragments"
fi

# ---- 3. no operator names in tracked text (denylist supplied at runtime) --
# Priority: REPO_GUARD_NAMES env > local plaintext tools/.repo-guard-denylist >
# committed hashed tools/repo-guard-denylist.sha256 (via check_names_hashed.py) >
# unusable (CI fail-closed / local skip).
#
# tools/repo-guard-names-exclude.txt lists path-prefixes (one per line) that
# the names scan skips entirely — machine-generated vocab/data artifacts only
# (e.g. tokenizer/), never prose. Both plaintext and hashed modes read it.
# SKIP all NAME checks if backup exemption is applied (exact-match private mirror only)
if [ "$BACKUP_EXEMPTION_APPLIED" -eq 0 ]; then
  NAMES_EXCLUDE_ARGS=()
  NAMES_EXCLUDE_FILE="$KERNEL_ROOT/tools/repo-guard-names-exclude.txt"
  if [ -f "$NAMES_EXCLUDE_FILE" ]; then
    while IFS= read -r prefix; do
      prefix="$(printf '%s' "$prefix" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
      [ -z "$prefix" ] && continue
      case "$prefix" in \#*) continue ;; esac
      NAMES_EXCLUDE_ARGS+=(":(exclude)${prefix}")
    done < "$NAMES_EXCLUDE_FILE"
  fi
  NAMES_SELF_EXCLUDE_ARGS=()
  if [ "$KERNEL_ROOT" = "$SUBJECT_ROOT" ]; then
    NAMES_SELF_EXCLUDE_ARGS=(
      ':(exclude)tools/repo-guard.sh'
      ':(exclude)tools/.repo-guard-denylist'
    )
  fi
  NAMES=""
  if [ -n "${REPO_GUARD_NAMES:-}" ]; then
    NAMES="$REPO_GUARD_NAMES"
  elif [ "$KERNEL_ROOT" = "$SUBJECT_ROOT" ] && [ -f tools/.repo-guard-denylist ]; then
    NAMES="$(grep -vE '^\s*(#|$)' tools/.repo-guard-denylist | paste -sd '|' -)"
  fi
  if [ -n "$NAMES" ]; then
    if git grep -nIiE "\b(${NAMES})\b" -- . "${NAMES_SELF_EXCLUDE_ARGS[@]}" "${NAMES_EXCLUDE_ARGS[@]}" >/tmp/rg_names 2>/dev/null && [ -s /tmp/rg_names ]; then
      fail "names" "operator names in tracked files"
      sed 's/^/      /' /tmp/rg_names | head -20
    else
      ok "names" "none found"
    fi
  elif [ -f "$KERNEL_ROOT/tools/repo-guard-denylist.sha256" ]; then
    HASHED_SELF_ARGS=()
    if [ "$KERNEL_ROOT" != "$SUBJECT_ROOT" ]; then
      HASHED_SELF_ARGS+=(--scan-guard-surfaces)
    fi
    HASHED_OUT="$(
      python "$KERNEL_ROOT/tools/check_names_hashed.py" \
        --root "$SUBJECT_ROOT" \
        --denylist "$KERNEL_ROOT/tools/repo-guard-denylist.sha256" \
        --names-exclude "$NAMES_EXCLUDE_FILE" "${HASHED_SELF_ARGS[@]}" 2>&1
    )"
    HASHED_RC=$?
    case "$HASHED_RC" in
      0) ok "names" "none found (hashed denylist)" ;;
      1) fail "names" "operator names in tracked files (hashed denylist match)"
         printf '%s\n' "$HASHED_OUT" | sed 's/^/      /' ;;
      *) # denylist file present but unusable (empty after comment-stripping) — same
         # unusable-denylist branch as if no file existed at all.
         if [ -n "${CI:-}" ] || [ -n "${GITHUB_ACTIONS:-}" ]; then
           printf 'FAIL [names] hashed denylist present but unusable (tools/repo-guard-denylist.sha256); aborting\n'
           exit 2
         else
           printf 'skip [names] hashed denylist unusable (local run) — structural checks still enforced\n'
         fi
         ;;
    esac
  else
    if [ -n "${CI:-}" ] || [ -n "${GITHUB_ACTIONS:-}" ]; then
      printf 'FAIL [names] denylist required in protected context (set REPO_GUARD_NAMES secret, tools/.repo-guard-denylist, or commit tools/repo-guard-denylist.sha256); aborting\n'
      exit 2
    else
      printf 'skip [names] no denylist (local run) — structural checks still enforced\n'
    fi
  fi
else
  ok "names" "SKIPPED (backup-remote exemption)"
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
  feat/*|fix/*|exp/*|chore/*|docs/*) ok "branch" "$BR" ;;
  *) fail "branch" "branch '$BR' must match <type>/<slug> where type in feat|fix|exp|chore|docs" ;;
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

# ---- 9. authority and totality conservation -----------------------------
if [ ! -f "$KERNEL_ROOT/scripts/verify_authority_conservation.py" ]; then
  fail "authority" "trusted scripts/verify_authority_conservation.py is missing"
else
  AUTHORITY_ARGS=(--root .)
  if [ "${REPO_GUARD_SCOPE:-}" = "staged" ]; then
    AUTHORITY_ARGS+=(--staged)
  elif [ -n "$RANGE" ]; then
    AUTHORITY_ARGS+=(--changed-range "$RANGE")
  fi
  AUTHORITY_OUT="$(python "$KERNEL_ROOT/scripts/verify_authority_conservation.py" "${AUTHORITY_ARGS[@]}" 2>&1)"
  AUTHORITY_RC=$?
  if [ "$AUTHORITY_RC" -eq 0 ]; then
    ok "authority" "EMBER authority conservation certificate passes"
  else
    fail "authority" "EMBER authority conservation certificate failed"
    printf '%s\n' "$AUTHORITY_OUT" | sed 's/^/      /' | head -30
  fi
fi

echo
if [ "$FAIL" -eq 0 ]; then echo "repo-guard: PASS"; else echo "repo-guard: FAIL"; fi
exit "$FAIL"
