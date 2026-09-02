#!/usr/bin/env bash
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
#
# Regression test for src/ember/infrastructure/tools/pr_authbind_preflight.sh.
#
# Proves, against throwaway scratch repos (never the live tree):
#
#   1. The OLD two-dot-tip approach (`git diff origin/master..HEAD_REF`) gives
#      a DIFFERENT changed-file set than the merge-ref approach once the base
#      has advanced after the PR branched — the exact class of divergence
#      (#938/#952) the preflight repair exists to close.
#   2. The preflight REJECTS a local head that doesn't match the public head.
#   3. The preflight REJECTS a fetched origin/master that doesn't match the
#      API's own `.base.sha` (P1-A: the base must be authenticated, never
#      just assumed from whatever the local remote happens to have).
#   4. The preflight REJECTS a stale `refs/pull/<N>/merge` whose parents
#      don't match {authenticated base, public head}.
#   5. The preflight REJECTS mergeable=false, and mergeable=null/unknown that
#      persists through retries (P1-B: mergeable is gated, never ignored).
#   6. The preflight REJECTS a `gh api` failure and an empty live body —
#      fail-closed, never a silent proceed.
#   7. A FULL clean scenario (matching head, authenticated base, mergeable
#      true, no merge ref so the deterministic-construction fallback runs,
#      live body present) exits 0 and actually executes both Step A and
#      Step B inside the merge-ref worktree (proven by touch-file markers,
#      not just an exit code).
#
# Usage: bash src/ember/governance/scripts/tests/test_pr_authbind_preflight_regression.sh
# Exit 0 on all assertions passing, non-zero + message on the first failure.

set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PREFLIGHT="$REPO_ROOT/src/ember/infrastructure/tools/pr_authbind_preflight.sh"

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
# Fake `gh` — parameterized by env vars so every test below reuses the same
# binary. Speed knobs (retries/sleep) are read from the preflight's own env
# overrides so the unknown-mergeable retry test doesn't actually wait.
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
    *head.sha*base.sha*)
      if [ "${FAKE_API_FAIL:-0}" = "1" ]; then
        echo "fake gh: simulated api failure" >&2
        exit 1
      fi
      printf '%s\t%s\t%s\t%s\t%s\n' \
        "${FAKE_PR_HEAD:?}" \
        "${FAKE_PR_BASE_REF:-master}" \
        "${FAKE_PR_BASE_SHA:-0000000000000000000000000000000000000000}" \
        "${FAKE_MERGEABLE:-true}" \
        "${FAKE_MERGEABLE_STATE:-clean}"
      ;;
    '.body // ""')
      if [ "${FAKE_BODY_API_FAIL:-0}" = "1" ]; then
        echo "fake gh: simulated body api failure" >&2
        exit 1
      fi
      printf '%s\n' "${FAKE_PR_BODY-body}"
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

# Common fast-retry env for every invocation below (no real sleeping in CI).
FAST_RETRY_ENV=(PR_AUTHBIND_PREFLIGHT_MERGEABLE_RETRIES=2 PR_AUTHBIND_PREFLIGHT_MERGEABLE_RETRY_SLEEP=0)

# ---------------------------------------------------------------------------
# Part 2: preflight rejects a local head that doesn't match the public PR head.
# ---------------------------------------------------------------------------
# Public PR head = the real PR branch tip; local ref under test = master
# (deliberately the WRONG commit) — must be rejected, never silently diffed.
OUT="$(cd "$WORK" && PATH="$FAKEBIN:$PATH" env "${FAST_RETRY_ENV[@]}" \
  FAKE_PR_HEAD="$PR_HEAD_SHA" FAKE_PR_BASE_REF="master" FAKE_MERGEABLE="true" \
  bash "$PREFLIGHT" 999 master 2>&1)"
RC=$?
assert_eq "mismatched local head exits non-zero (preflight-validity failure, not a guard verdict)" "2" "$RC"
assert_contains "mismatch message names both the local and public head" "$OUT" "!= public PR #999 head"

# Sanity: the matching head should get past the head-check (may still fail
# later steps here — this only proves the head-equality gate itself does not
# falsely reject a true match).
OUT2="$(cd "$WORK" && PATH="$FAKEBIN:$PATH" env "${FAST_RETRY_ENV[@]}" \
  FAKE_PR_HEAD="$PR_HEAD_SHA" FAKE_PR_BASE_REF="master" FAKE_MERGEABLE="true" \
  bash "$PREFLIGHT" 999 "$PR_HEAD_SHA" 2>&1)"
assert_contains "matching local head passes the head-equality gate" "$OUT2" "local head confirmed == public PR head"

# ---------------------------------------------------------------------------
# Part 3 (P1-A): preflight rejects an unauthenticated/stale base — the API's
# .base.sha must match the freshly fetched origin/master, never assumed.
# ---------------------------------------------------------------------------
REAL_MASTER_TIP="$(git -C "$WORK" rev-parse origin/master)"
BOGUS_BASE_SHA="0123456789abcdef0123456789abcdef01234567"
OUT3="$(cd "$WORK" && PATH="$FAKEBIN:$PATH" env "${FAST_RETRY_ENV[@]}" \
  FAKE_PR_HEAD="$PR_HEAD_SHA" FAKE_PR_BASE_REF="master" FAKE_PR_BASE_SHA="$BOGUS_BASE_SHA" \
  FAKE_MERGEABLE="true" \
  bash "$PREFLIGHT" 999 "$PR_HEAD_SHA" 2>&1)"
RC3=$?
assert_eq "base-sha mismatch (API base.sha != fetched origin/master) exits non-zero" "2" "$RC3"
assert_contains "base-sha mismatch message names the fetched tip" "$OUT3" "$REAL_MASTER_TIP"
assert_contains "base-sha mismatch message names the public base sha" "$OUT3" "$BOGUS_BASE_SHA"

# Non-master base is rejected outright, before any base-sha comparison.
OUT3B="$(cd "$WORK" && PATH="$FAKEBIN:$PATH" env "${FAST_RETRY_ENV[@]}" \
  FAKE_PR_HEAD="$PR_HEAD_SHA" FAKE_PR_BASE_REF="develop" FAKE_PR_BASE_SHA="$REAL_MASTER_TIP" \
  FAKE_MERGEABLE="true" \
  bash "$PREFLIGHT" 999 "$PR_HEAD_SHA" 2>&1)"
RC3B=$?
assert_eq "non-master base ref exits non-zero" "2" "$RC3B"
assert_contains "non-master base message names the actual base branch" "$OUT3B" "base branch is 'develop'"

# ---------------------------------------------------------------------------
# Part 4: preflight rejects mergeable=false and persistently-unknown mergeable.
# ---------------------------------------------------------------------------
OUT4="$(cd "$WORK" && PATH="$FAKEBIN:$PATH" env "${FAST_RETRY_ENV[@]}" \
  FAKE_PR_HEAD="$PR_HEAD_SHA" FAKE_PR_BASE_REF="master" FAKE_PR_BASE_SHA="$REAL_MASTER_TIP" \
  FAKE_MERGEABLE="false" \
  bash "$PREFLIGHT" 999 "$PR_HEAD_SHA" 2>&1)"
RC4=$?
assert_eq "mergeable=false exits non-zero" "2" "$RC4"
assert_contains "mergeable=false message is explicit" "$OUT4" "mergeable=false"

OUT4B="$(cd "$WORK" && PATH="$FAKEBIN:$PATH" env "${FAST_RETRY_ENV[@]}" \
  FAKE_PR_HEAD="$PR_HEAD_SHA" FAKE_PR_BASE_REF="master" FAKE_PR_BASE_SHA="$REAL_MASTER_TIP" \
  FAKE_MERGEABLE="null" FAKE_MERGEABLE_STATE="unknown" \
  bash "$PREFLIGHT" 999 "$PR_HEAD_SHA" 2>&1)"
RC4B=$?
assert_eq "persistently-unknown mergeable exits non-zero after retries" "2" "$RC4B"
assert_contains "persistently-unknown message names the retry count" "$OUT4B" "after 2 retries"
assert_contains "persistently-unknown mergeable actually retried the API" "$OUT4B" "attempt 1/2"
assert_contains "persistently-unknown mergeable actually retried the API" "$OUT4B" "attempt 2/2"

# ---------------------------------------------------------------------------
# Part 5: preflight rejects a gh api failure and an empty live body — fail
# closed, never a silent proceed.
# ---------------------------------------------------------------------------
OUT5="$(cd "$WORK" && PATH="$FAKEBIN:$PATH" env "${FAST_RETRY_ENV[@]}" \
  FAKE_PR_HEAD="$PR_HEAD_SHA" FAKE_PR_BASE_REF="master" FAKE_PR_BASE_SHA="$REAL_MASTER_TIP" \
  FAKE_MERGEABLE="true" FAKE_API_FAIL="1" \
  bash "$PREFLIGHT" 999 "$PR_HEAD_SHA" 2>&1)"
RC5=$?
assert_eq "gh api failure (info query) exits non-zero" "2" "$RC5"
assert_contains "gh api failure message names the failed call" "$OUT5" "gh api pulls/999"

OUT5B="$(cd "$WORK" && PATH="$FAKEBIN:$PATH" env "${FAST_RETRY_ENV[@]}" \
  FAKE_PR_HEAD="$PR_HEAD_SHA" FAKE_PR_BASE_REF="master" FAKE_PR_BASE_SHA="$REAL_MASTER_TIP" \
  FAKE_MERGEABLE="true" FAKE_PR_BODY="" \
  bash "$PREFLIGHT" 999 "$PR_HEAD_SHA" 2>&1)"
RC5B=$?
assert_eq "empty live PR body exits non-zero" "2" "$RC5B"
assert_contains "empty body message is explicit" "$OUT5B" "live PR body for #999 is empty"

OUT5C="$(cd "$WORK" && PATH="$FAKEBIN:$PATH" env "${FAST_RETRY_ENV[@]}" \
  FAKE_PR_HEAD="$PR_HEAD_SHA" FAKE_PR_BASE_REF="master" FAKE_PR_BASE_SHA="$REAL_MASTER_TIP" \
  FAKE_MERGEABLE="true" FAKE_BODY_API_FAIL="1" \
  bash "$PREFLIGHT" 999 "$PR_HEAD_SHA" 2>&1)"
RC5C=$?
assert_eq "gh api failure (body query) exits non-zero" "2" "$RC5C"
assert_contains "body-query api failure message names the failed call" "$OUT5C" "gh api pulls/999 (body)"

# ---------------------------------------------------------------------------
# Part 6 (P1-A/P1-B negative continued): a stale refs/pull/<N>/merge — parents
# built against an OLD base — is rejected even though head/base/mergeable are
# all otherwise valid.
# ---------------------------------------------------------------------------
STALE_BARE="$SCRATCH/stale-origin.git"
STALE_WORK="$SCRATCH/stale-work"
git init --quiet --bare "$STALE_BARE"
git init --quiet "$STALE_WORK"
git -C "$STALE_WORK" config user.email "test@example.invalid"
git -C "$STALE_WORK" config user.name "test"
git -C "$STALE_WORK" remote add origin "$STALE_BARE"
git -C "$STALE_WORK" checkout --quiet -b master
echo base >"$STALE_WORK/base.txt"
git -C "$STALE_WORK" add base.txt
git -C "$STALE_WORK" commit --quiet -m "base"
STALE_BASE_SHA="$(git -C "$STALE_WORK" rev-parse HEAD)"
git -C "$STALE_WORK" push --quiet origin master

git -C "$STALE_WORK" checkout --quiet -b prbranch2 "$STALE_BASE_SHA"
echo pr2 >"$STALE_WORK/pr2_file.txt"
git -C "$STALE_WORK" add pr2_file.txt
git -C "$STALE_WORK" commit --quiet -m "pr2 change"
STALE_PR_HEAD="$(git -C "$STALE_WORK" rev-parse HEAD)"

# Construct a merge ref against the OLD base (before the advance below).
git -C "$STALE_WORK" checkout --quiet -b stalemerge_tmp "$STALE_BASE_SHA"
git -C "$STALE_WORK" merge --no-ff --no-commit "$STALE_PR_HEAD" >/dev/null 2>&1
git -C "$STALE_WORK" commit --quiet --no-edit -m "stale merge"
STALE_MERGE_SHA="$(git -C "$STALE_WORK" rev-parse HEAD)"
git -C "$STALE_WORK" push --quiet origin "${STALE_MERGE_SHA}:refs/pull/42/merge"
git -C "$STALE_WORK" checkout --quiet master
git -C "$STALE_WORK" branch -D stalemerge_tmp --quiet 2>/dev/null || git -C "$STALE_WORK" branch -D stalemerge_tmp

# Base advances AFTER the merge ref was computed — merge ref parents are now stale.
echo master_only2 >"$STALE_WORK/master_only2.txt"
git -C "$STALE_WORK" add master_only2.txt
git -C "$STALE_WORK" commit --quiet -m "base advance after merge ref computed"
git -C "$STALE_WORK" push --quiet origin master
git -C "$STALE_WORK" fetch --quiet origin master
STALE_NEW_MASTER_TIP="$(git -C "$STALE_WORK" rev-parse origin/master)"

OUT6="$(cd "$STALE_WORK" && PATH="$FAKEBIN:$PATH" env "${FAST_RETRY_ENV[@]}" \
  FAKE_PR_HEAD="$STALE_PR_HEAD" FAKE_PR_BASE_REF="master" FAKE_PR_BASE_SHA="$STALE_NEW_MASTER_TIP" \
  FAKE_MERGEABLE="true" \
  bash "$PREFLIGHT" 42 "$STALE_PR_HEAD" 2>&1)"
RC6=$?
assert_eq "stale merge-ref parents (built against an old base) exit non-zero" "2" "$RC6"
assert_contains "stale merge-ref message names the mechanism" "$OUT6" "stale refs/pull/42/merge"

# ---------------------------------------------------------------------------
# Part 7: full clean success path — everything authenticates, mergeable=true,
# no merge ref exists (fallback construction runs), live body present. Proves
# BOTH Step A and Step B actually execute inside the merge-ref worktree, via
# touch-file markers written by stub scripts (never the real repo-guard
# machinery — this is an execution-path proof, not a repo-guard content test).
# ---------------------------------------------------------------------------
E2E_BARE="$SCRATCH/e2e-origin.git"
E2E_WORK="$SCRATCH/e2e-work"
git init --quiet --bare "$E2E_BARE"
git init --quiet "$E2E_WORK"
git -C "$E2E_WORK" config user.email "test@example.invalid"
git -C "$E2E_WORK" config user.name "test"
git -C "$E2E_WORK" remote add origin "$E2E_BARE"
git -C "$E2E_WORK" checkout --quiet -b master

mkdir -p "$E2E_WORK/tools" "$E2E_WORK/scripts"
MARKER_A="$SCRATCH/marker_step_a"
MARKER_B="$SCRATCH/marker_step_b"
cat >"$E2E_WORK/tools/repo-guard.sh" <<EOF
#!/usr/bin/env bash
touch "$MARKER_A"
echo "stub repo-guard: ok"
exit 0
EOF
# check_pr_authority_binding.py runs under a NATIVE python (not MSYS bash), so
# the marker path must be a native Windows path when one is available (git
# bash's /tmp is an MSYS mount, invisible to native python on Windows) — fall
# back to the raw path unchanged on platforms without cygpath.
MARKER_B_FOR_PY="$MARKER_B"
command -v cygpath >/dev/null 2>&1 && MARKER_B_FOR_PY="$(cygpath -w "$MARKER_B")"
cat >"$E2E_WORK/src/ember/governance/scripts/check_pr_authority_binding.py" <<EOF
import pathlib
pathlib.Path(r"$MARKER_B_FOR_PY").touch()
print("stub check_pr_authority_binding: ok")
EOF
chmod +x "$E2E_WORK/tools/repo-guard.sh"
git -C "$E2E_WORK" add tools/repo-guard.sh src/ember/governance/scripts/check_pr_authority_binding.py
git -C "$E2E_WORK" commit --quiet -m "base with stub CI steps"
E2E_BASE_SHA="$(git -C "$E2E_WORK" rev-parse HEAD)"
git -C "$E2E_WORK" push --quiet origin master

git -C "$E2E_WORK" checkout --quiet -b prbranch3 "$E2E_BASE_SHA"
echo pr3 >"$E2E_WORK/pr3_file.txt"
git -C "$E2E_WORK" add pr3_file.txt
git -C "$E2E_WORK" commit --quiet -m "pr3 change"
E2E_PR_HEAD="$(git -C "$E2E_WORK" rev-parse HEAD)"
git -C "$E2E_WORK" fetch --quiet origin master
E2E_MASTER_TIP="$(git -C "$E2E_WORK" rev-parse origin/master)"

rm -f "$MARKER_A" "$MARKER_B"
OUT7="$(cd "$E2E_WORK" && PATH="$FAKEBIN:$PATH" env "${FAST_RETRY_ENV[@]}" \
  FAKE_PR_HEAD="$E2E_PR_HEAD" FAKE_PR_BASE_REF="master" FAKE_PR_BASE_SHA="$E2E_MASTER_TIP" \
  FAKE_MERGEABLE="true" FAKE_PR_BODY="goal_id: EMBER-02" \
  bash "$PREFLIGHT" 7 "$E2E_PR_HEAD" 2>&1)"
RC7=$?
assert_eq "full clean scenario exits 0" "0" "$RC7"
assert_contains "full clean scenario used the deterministic-construction fallback" "$OUT7" "unavailable — constructing the merge deterministically"
if [ -f "$MARKER_A" ]; then
  echo "ok   Step A (repo-guard.sh) actually executed inside the merge-ref worktree"
else
  echo "FAIL Step A marker not found — repo-guard.sh did not actually run"
  FAIL=1
fi
if [ -f "$MARKER_B" ]; then
  echo "ok   Step B (check_pr_authority_binding.py) actually executed inside the merge-ref worktree"
else
  echo "FAIL Step B marker not found — check_pr_authority_binding.py did not actually run"
  FAIL=1
fi

if [ "$FAIL" -eq 0 ]; then
  echo
  echo "ALL REGRESSION ASSERTIONS PASSED"
  exit 0
else
  echo
  echo "REGRESSION TEST FAILED — see FAIL lines above"
  exit 1
fi
