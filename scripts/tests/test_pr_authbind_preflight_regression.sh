#!/usr/bin/env bash
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
#
# Regression test for tools/pr_authbind_preflight.sh.
#
# Proves two things against a throwaway scratch repo (never the live tree):
#
#   1. The OLD two-dot-tip approach (`git diff origin/master..HEAD_REF`) gives
#      a DIFFERENT changed-file set than the merge-ref approach once the base
#      has advanced after the PR branched — the exact class of divergence
#      (#938/#952) the preflight repair exists to close. Two-dot notation for
#      `git diff` (unlike `git log`) is a straight two-tree comparison with no
#      merge-base logic, so it picks up the base's post-branch advance as a
#      spurious (reversed) change; the merge-ref tree does not.
#   2. The repaired `tools/pr_authbind_preflight.sh` REJECTS with exit 2 when
#      the local head ref does not match the public PR head OID, rather than
#      silently proceeding against the wrong commit.
#
# Usage: bash scripts/tests/test_pr_authbind_preflight_regression.sh
# Exit 0 on all assertions passing, non-zero + message on the first failure.

set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PREFLIGHT="$REPO_ROOT/tools/pr_authbind_preflight.sh"

FAIL=0
assert_eq() {
  local desc="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    echo "ok   $desc"
  else
    echo "FAIL $desc: expected [$expected] got [$actual]"
    FAIL=1
  fi
}
assert_contains() {
  local desc="$1" haystack="$2" needle="$3"
  if printf '%s' "$haystack" | grep -qF -- "$needle"; then
    echo "ok   $desc"
  else
    echo "FAIL $desc: expected to find [$needle]"
    FAIL=1
  fi
}
assert_not_contains() {
  local desc="$1" haystack="$2" needle="$3"
  if printf '%s' "$haystack" | grep -qF -- "$needle"; then
    echo "FAIL $desc: did not expect to find [$needle]"
    FAIL=1
  else
    echo "ok   $desc"
  fi
}

SCRATCH="$(mktemp -d)"
cleanup() { rm -rf "$SCRATCH"; }
trap cleanup EXIT

# ---------------------------------------------------------------------------
# Part 1: two-dot-tip vs merge-ref changed-file set, after a base advance.
# ---------------------------------------------------------------------------
BARE="$SCRATCH/origin.git"
WORK="$SCRATCH/work"
git init --quiet --bare "$BARE"
git init --quiet "$WORK"
git -C "$WORK" config user.email "test@example.invalid"
git -C "$WORK" config user.name "test"
git -C "$WORK" remote add origin "$BARE"
git -C "$WORK" checkout --quiet -b master

echo base >"$WORK/base.txt"
git -C "$WORK" add base.txt
git -C "$WORK" commit --quiet -m "base"
BASE_SHA="$(git -C "$WORK" rev-parse HEAD)"
git -C "$WORK" push --quiet origin master

# PR branch off the pre-advance base.
git -C "$WORK" checkout --quiet -b prbranch "$BASE_SHA"
echo pr >"$WORK/pr_file.txt"
git -C "$WORK" add pr_file.txt
git -C "$WORK" commit --quiet -m "pr change"
PR_HEAD_SHA="$(git -C "$WORK" rev-parse HEAD)"

# Base advances AFTER the PR branched (the class this repairs).
git -C "$WORK" checkout --quiet master
echo master_only >"$WORK/master_only.txt"
git -C "$WORK" add master_only.txt
git -C "$WORK" commit --quiet -m "unrelated base advance"
git -C "$WORK" push --quiet origin master
git -C "$WORK" fetch --quiet origin master
MASTER_TIP_SHA="$(git -C "$WORK" rev-parse origin/master)"

# OLD approach: straight two-tree diff, no merge-base logic.
OLD_CHANGED="$(git -C "$WORK" diff --name-only origin/master.."$PR_HEAD_SHA" | sort | tr '\n' ' ')"

# NEW approach: diff against the actual merge-ref tree.
MERGEWT="$SCRATCH/mergewt"
git -C "$WORK" worktree add --detach --quiet "$MERGEWT" origin/master
git -C "$MERGEWT" merge --no-ff --no-commit "$PR_HEAD_SHA" >/dev/null 2>&1
git -C "$MERGEWT" commit --quiet --no-edit -m "test merge"
NEW_CHANGED="$(git -C "$MERGEWT" diff --name-only origin/master..HEAD | sort | tr '\n' ' ')"

assert_contains "old two-dot-tip diff wrongly flags the base's own post-branch file as changed" \
  "$OLD_CHANGED" "master_only.txt"
assert_not_contains "merge-ref diff correctly excludes the base's own unrelated file" \
  "$NEW_CHANGED" "master_only.txt"
assert_contains "both approaches see the PR's actual added file" "$OLD_CHANGED" "pr_file.txt"
assert_contains "both approaches see the PR's actual added file" "$NEW_CHANGED" "pr_file.txt"
if [ "$OLD_CHANGED" = "$NEW_CHANGED" ]; then
  echo "FAIL old and new changed-file sets are identical — the scratch repo failed to reproduce the divergence"
  FAIL=1
else
  echo "ok   old ([$OLD_CHANGED]) and new ([$NEW_CHANGED]) changed-file sets diverge as predicted"
fi

git -C "$WORK" worktree remove --force "$MERGEWT" >/dev/null 2>&1

# ---------------------------------------------------------------------------
# Part 2: preflight rejects a local head that doesn't match the public PR head.
# ---------------------------------------------------------------------------
FAKEBIN="$SCRATCH/fakebin"
mkdir -p "$FAKEBIN"
cat >"$FAKEBIN/gh" <<'FAKEGH'
#!/usr/bin/env bash
set -u
if [ "$1" = "repo" ] && [ "$2" = "view" ]; then
  echo "scratch/repo"
  exit 0
fi
if [ "$1" = "api" ]; then
  jq_arg=""
  prev=""
  for a in "$@"; do
    if [ "$prev" = "--jq" ]; then jq_arg="$a"; fi
    prev="$a"
  done
  case "$jq_arg" in
    *head.sha*)
      printf '%s\t%s\t%s\t%s\n' "${FAKE_PR_HEAD:?}" "master" "true" "clean"
      ;;
    '.body // ""')
      printf '%s\n' "${FAKE_PR_BODY:-}"
      ;;
    *)
      echo ""
      ;;
  esac
  exit 0
fi
echo "fake gh: unhandled args: $*" >&2
exit 1
FAKEGH
chmod +x "$FAKEBIN/gh"

# Public PR head = the real PR branch tip; local ref under test = master
# (deliberately the WRONG commit) — must be rejected, never silently diffed.
OUT="$(cd "$WORK" && PATH="$FAKEBIN:$PATH" FAKE_PR_HEAD="$PR_HEAD_SHA" \
  bash "$PREFLIGHT" 999 master 2>&1)"
RC=$?
assert_eq "mismatched local head exits non-zero (preflight-validity failure, not a guard verdict)" "2" "$RC"
assert_contains "mismatch message names both the local and public head" "$OUT" "!= public PR #999 head"

# Sanity: the matching head should get past the head-check (may still fail
# later steps in this minimal scratch repo — that's fine, this only proves
# the head-equality gate itself does not falsely reject a true match).
OUT2="$(cd "$WORK" && PATH="$FAKEBIN:$PATH" FAKE_PR_HEAD="$PR_HEAD_SHA" \
  bash "$PREFLIGHT" 999 "$PR_HEAD_SHA" 2>&1)"
assert_contains "matching local head passes the head-equality gate" "$OUT2" "local head confirmed == public PR head"

if [ "$FAIL" -eq 0 ]; then
  echo
  echo "ALL REGRESSION ASSERTIONS PASSED"
  exit 0
else
  echo
  echo "REGRESSION TEST FAILED — see FAIL lines above"
  exit 1
fi
