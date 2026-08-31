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
#   3. committed src/ember/infrastructure/tools/repo-guard-denylist.sha256 (one sha256-per-lowercase-name;
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

# ---- 1a. cockpit state must never reside inside the certified tree -------
# The completion verifier certifies this tree by TOTALITY -- it censuses and fingerprints
# every file, tracked AND untracked -- so a resident cockpit writer produces list-vs-hash
# contradictions and reds the run (run15). The cure was to move the writer out, not to
# exclude paths from the census: an exclusion would be a standing blind spot where
# contamination hides while the certificate silently promises less. Issue #1330 relocated
# all cockpit-mutable state to an external root; this check is what keeps the class from
# silently returning. Non-EMPTY is the bar, not absence -- an empty leftover directory
# writes nothing and the launcher sweeps it.
# Any SHAPE is refused, not just a populated directory: a symlink or junction pointing at
# the external root is the dangerous one, because the census walks through it and hashes
# live external state, so a "compatibility shim" would reintroduce the contamination. Only
# a genuinely empty real directory passes -- it writes nothing and the launcher sweeps it.
COCKPIT_STATE_DIR="$SUBJECT_ROOT/.ember"
if [ -L "$COCKPIT_STATE_DIR" ]; then
  fail "cockpit-state" "'.ember' is a symlink/junction in the tree; the census walks through it and hashes live cockpit state. Remove it — a shim is not an acceptable migration"
elif [ -e "$COCKPIT_STATE_DIR" ] && [ ! -d "$COCKPIT_STATE_DIR" ]; then
  fail "cockpit-state" "'.ember' exists in the tree as a file; cockpit state must live outside it (see EMBER_STATE_ROOT)"
elif [ -d "$COCKPIT_STATE_DIR" ] && [ -n "$(ls -A "$COCKPIT_STATE_DIR" 2>/dev/null)" ]; then
  fail "cockpit-state" "'.ember/' is resident in the tree; cockpit state must live outside it (see EMBER_STATE_ROOT). Launch tools/launchers/Ember.cmd once to migrate it, or move/delete the directory"
  ls -A "$COCKPIT_STATE_DIR" | sed 's/^/      /' | head -10
else
  ok "cockpit-state" "no resident cockpit state in the tree"
fi

# ---- 1b. tracked text files must be LF-only ------------------------------
if bash "$KERNEL_ROOT/tools/run-python-hidden.sh" "$KERNEL_ROOT/tools/check_line_endings.py" "$SUBJECT_ROOT"; then
  :
else
  FAIL=1
fi

# ---- 1c. tracked text must be strict UTF-8, no UTF-16/32 BOM -------------
# Use trusted kernel bytes against the subject checkout. Git's -I heuristic
# skips NUL-heavy content, so every Git text-attributed subject blob must pass
# this explicit byte-level check before the names/path scans below.
if bash "$KERNEL_ROOT/tools/run-python-hidden.sh" "$KERNEL_ROOT/tools/check_text_encoding.py" "$SUBJECT_ROOT"; then
  :
else
  FAIL=1
fi

# ---- 1d. redaction tokens must never become executable formatting syntax --
# Frozen receipts/prose may truthfully mention placeholders. The trusted
# checker rejects only the runtime-crashing boundary: a redacted token used as
# a percent-format or str.format operand (issue #502).
if bash "$KERNEL_ROOT/tools/run-python-hidden.sh" "$KERNEL_ROOT/tools/check_executable_redaction_placeholders.py" "$SUBJECT_ROOT"; then
  :
else
  FAIL=1
fi

# ---- 2. no absolute local filesystem paths in tracked text ---------------
# Matches drive-rooted private directories, temporary Windows locations, local
# mount roots, and similar forms. Separator is one-OR-MORE slash characters
# (not exactly one): serialized or repr-encoded paths may double separators, and a single-
# separator class silently misses that doubled form (issue #456 -- six such
# occurrences shipped in #455 before this fix, hand-redacted, never caught by
# this check). Windows+Temp is scoped to require the Temp segment specifically
# so a universal, non-identifying path like C:\Windows\System32\cmd.exe never
# false-positives here.
PATHPAT='([A-Za-z]:[/\\]+(Users|M|Downloads))|([A-Za-z]:[/\\]+[Ww][Ii][Nn][Dd][Oo][Ww][Ss][/\\]+[Tt][Ee][Mm][Pp])|(/mnt/[a-z]/)'
# Files that intentionally embed a leaked-path-shaped literal as adversarial
# test input (proving the app's own sanitization/redaction/clipping logic
# strips exactly this shape) -- these are the fixture, not a leak, and must
# keep the literal string to stay meaningful. See docs/authority/REDACTIONS.md (issue #456).
#
# Class 2 (issue #537, C2-restore ruling 2026-07-09): HASH-PINNED FROZEN
# ARTIFACTS. Byte-exact sha256 is load-bearing (C2 CHK frozen-rows hash-match
# + frozen-before law): redaction breaks the pin, re-pinning breaks
# frozen-before. Enumerated individually -- NEVER directory globs. Each entry
# has a docs/authority/REDACTIONS.md row. The operator-name checks still cover these files
# in full (this exclusion applies ONLY to the paths grep).
#
# Class 3 (issue #1401, 2026-08-04): the EMBER-02 LAUNCH-AUTHORITY DECLARATION
# and its run-spec. Same load-bearing-bytes reason as class 2: the
# certificate's sha256 is its identity, cited by declaration-ledger.jsonl and
# run-spec.json, so redacting the two path strings it carries would produce a
# document that is not the certificate that was declared. The run-spec's
# requested_scope is compared literally against the certificate's
# execution_scope, so redacting one and not the other would make a consistent
# pair read as a mismatch. Landed standalone (this file + docs/authority/REDACTIONS.md only)
# so the entries exist at the PR BASE the #1401 evidence-pack PR is judged
# against -- CI pins repo-guard.sh at the base kernel, and a PR that both
# introduces class-3 receipts AND edits this file to exempt them can never
# self-exclude (surface_bytes_match requires kernel == subject bytes).
PATHPAT_FIXTURE_EXCLUDE_ARGS=(
  ':(exclude)src/ember/governance/scripts/test_w1b_continuation.py'
  ':(exclude)tools/ember-cli/src/core/monitor-render.test.ts'
  ':(exclude)tools/ember-cli/src/components/homescreen-mock1-parity.test.ts'
  ':(exclude)tools/ember-cli/src/components/logo-homescreen.test.ts'
  ':(exclude)receipts/ember-d3-native-loop/d3-gym-fresh-rows-offset20-len12-20260708T221652Z.json'
  ':(exclude)receipts/ember-d3-native-loop/d3-broader-multifamily-fresh-rows-reconstructed.json'
  ':(exclude)receipts/ember-02-launch-authority/certificate.json'
  ':(exclude)receipts/ember-02-launch-authority/run-spec.json'
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
# Detect private mount fragments that carry developer-local context.
# Byte source under REPO_GUARD_SCOPE=staged is the git INDEX, not the
# working tree -- `git grep --cached`, mirroring the emberd-legacy and
# names checks. Non-staged scope is unchanged.
PRIVATE_MOUNT_FRAGMENT='M/avir'
PATHFRAG="(/mnt/[^/]*/${PRIVATE_MOUNT_FRAGMENT}/)|(/${PRIVATE_MOUNT_FRAGMENT})"
PATHFRAG_SELF_EXCLUDE_ARGS=()
for relative in \
  'tools/repo-guard.sh' \
  'tools/check_names_hashed.py' \
  'src/ember/infrastructure/tools/repo-guard-denylist.sha256'
do
  if surface_bytes_match "$relative"; then
    PATHFRAG_SELF_EXCLUDE_ARGS+=(":(exclude)$relative")
  fi
done
if [ "${REPO_GUARD_SCOPE:-}" = "staged" ]; then
  PATHFRAG_HITS="$(git grep --cached -nIE "$PATHFRAG" -- . "${PATHFRAG_SELF_EXCLUDE_ARGS[@]}" 2>/dev/null || true)"
else
  PATHFRAG_HITS="$(git grep -nIE "$PATHFRAG" -- . "${PATHFRAG_SELF_EXCLUDE_ARGS[@]}" 2>/dev/null || true)"
fi
if [ -n "$PATHFRAG_HITS" ]; then
  fail "path-frags" "local WSL/mount path fragments in tracked files"
  printf '%s\n' "$PATHFRAG_HITS" | sed 's/^/      /' | head -20
else
  ok "path-frags" "no local path fragments"
fi

# ---- 3. no operator names in tracked text (denylist supplied at runtime) --
# Priority: REPO_GUARD_NAMES env > local plaintext tools/.repo-guard-denylist >
# committed hashed src/ember/infrastructure/tools/repo-guard-denylist.sha256 (via check_names_hashed.py) >
# unusable (CI fail-closed / local skip).
#
# tools/repo-guard-names-exclude.cfg lists path-prefixes (one per line) that
# the names scan skips entirely — machine-generated vocab/data artifacts only
# (e.g. domains/model/tokenizer/), never prose. Both modes read it.
# SKIP all NAME checks if backup exemption is applied (exact-match private mirror only)
if [ "$BACKUP_EXEMPTION_APPLIED" -eq 0 ]; then
  NAMES_EXCLUDE_ARGS=()
  NAMES_EXCLUDE_FILE="$KERNEL_ROOT/tools/repo-guard-names-exclude.cfg"
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
    # Byte source under REPO_GUARD_SCOPE=staged (what .githooks/pre-commit
    # actually runs with) is the git INDEX, not the working tree -- `git
    # grep --cached` here, mirroring the emberd-legacy check above. This is
    # the operator-name denylist: a name staged then removed from the
    # working tree before commit would previously grep clean while the
    # commit that lands still carries it. Non-staged scope is unchanged.
    if [ "${REPO_GUARD_SCOPE:-}" = "staged" ]; then
      NAMES_HIT="$(git grep --cached -nIiE "\b(${NAMES})\b" -- . "${NAMES_SELF_EXCLUDE_ARGS[@]}" "${NAMES_EXCLUDE_ARGS[@]}" 2>/dev/null || true)"
    else
      NAMES_HIT="$(git grep -nIiE "\b(${NAMES})\b" -- . "${NAMES_SELF_EXCLUDE_ARGS[@]}" "${NAMES_EXCLUDE_ARGS[@]}" 2>/dev/null || true)"
    fi
    if [ -n "$NAMES_HIT" ]; then
      fail "names" "operator names in tracked files"
      printf '%s\n' "$NAMES_HIT" | sed 's/^/      /' | head -20
    else
      ok "names" "none found"
    fi
  elif [ -f "$KERNEL_ROOT/src/ember/infrastructure/tools/repo-guard-denylist.sha256" ]; then
    HASHED_SELF_ARGS=()
    if [ "$KERNEL_ROOT" != "$SUBJECT_ROOT" ]; then
      HASHED_SELF_ARGS+=(--scan-guard-surfaces)
    fi
    HASHED_OUT="$(
      bash "$KERNEL_ROOT/tools/run-python-hidden.sh" "$KERNEL_ROOT/tools/check_names_hashed.py" \
        --root "$SUBJECT_ROOT" \
        --denylist "$KERNEL_ROOT/src/ember/infrastructure/tools/repo-guard-denylist.sha256" \
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
           printf 'FAIL [names] hashed denylist present but unusable (src/ember/infrastructure/tools/repo-guard-denylist.sha256); aborting\n'
           exit 2
         else
           printf 'skip [names] hashed denylist unusable (local run) — structural checks still enforced\n'
         fi
         ;;
    esac
  else
    if [ -n "${CI:-}" ] || [ -n "${GITHUB_ACTIONS:-}" ]; then
      printf 'FAIL [names] denylist required in protected context (set REPO_GUARD_NAMES secret, tools/.repo-guard-denylist, or commit src/ember/infrastructure/tools/repo-guard-denylist.sha256); aborting\n'
      exit 2
    else
      printf 'skip [names] no denylist (local run) — structural checks still enforced\n'
    fi
  fi
else
  ok "names" "SKIPPED (backup-remote exemption)"
fi

# ---- 3b. emberd legacy-name: content-addressed exceptions only -----------
# Separate from the [names] check above and from its path-prefix
# tools/repo-guard-names-exclude.cfg, which is left exactly as-is. A tracked
# path matching the legacy name passes ONLY if it is enumerated in
# tools/emberd-legacy-exceptions.json AND its current content's sha256 equals
# the digest recorded there — path alone is never sufficient (anyone can
# rename a file into an exempted prefix; they cannot forge its digest).
# Policy validity is unconditional: the exceptions file is parsed and
# schema-validated on EVERY run, including a zero-hit tree — a missing,
# empty, malformed, or unparseable exceptions file is a hard FAIL always,
# never a silent pass, regardless of whether there is a legacy-name match to
# adjudicate this run. Only the per-path adjudication is conditional on a
# match existing; a clean tree with no legacy name anywhere still requires a
# valid policy to pass.
# Boundary is alnum-delimited, not \b: plain \b treats "_" as a word
# character, so "emberd_schedule" (a real key in the receipt exception below)
# would silently never match at all — invisible to the guard rather than
# adjudicated. "(^|[^A-Za-z0-9])emberd([^A-Za-z0-9]|$)" still excludes the
# two confirmed false positives ($EmberDir, toolsToEmberDefs — "emberd" as an
# accidental mid-identifier substring, alnum on both sides) while catching
# snake_case occurrences where "emberd" is its own semantic token.
# See state/specs/ember-lab-absorption-contract-2026-07-25.md Part 4.
# Byte source under REPO_GUARD_SCOPE=staged (what .githooks/pre-commit
# actually runs with) is the git INDEX, not the working tree -- `git grep
# --cached` here, and check_emberd_legacy_exceptions.py independently reads
# `git show :path` for every matched-path digest and for the exceptions file
# itself under the same scope. Reading working-tree bytes while committing
# staged bytes was a real bypass: stage divergent content, restore the
# working tree to the enumerated original, and a working-tree read never
# sees what actually lands in the commit. Non-staged scope (default local/CI
# run) is unchanged: working-tree bytes via plain `git grep`.
if [ "${REPO_GUARD_SCOPE:-}" = "staged" ]; then
  EMBERD_HITS="$(git grep --cached -nIiE '(^|[^A-Za-z0-9])emberd([^A-Za-z0-9]|$)' -- . ':(exclude)tools/repo-guard.sh' ':(exclude)tools/emberd-legacy-exceptions.json' ':(exclude)tools/check_emberd_legacy_exceptions.py' 2>/dev/null || true)"
else
  EMBERD_HITS="$(git grep -nIiE '(^|[^A-Za-z0-9])emberd([^A-Za-z0-9]|$)' -- . ':(exclude)tools/repo-guard.sh' ':(exclude)tools/emberd-legacy-exceptions.json' ':(exclude)tools/check_emberd_legacy_exceptions.py' 2>/dev/null || true)"
fi
if [ -z "$EMBERD_HITS" ]; then
  EMBERD_PATHS=""
else
  EMBERD_PATHS="$(printf '%s\n' "$EMBERD_HITS" | cut -d: -f1 | sort -u)"
fi
EMBERD_CHECK_OUT="$(EMBERD_PATHS="$EMBERD_PATHS" bash "$KERNEL_ROOT/tools/run-python-hidden.sh" "$KERNEL_ROOT/tools/check_emberd_legacy_exceptions.py" 2>&1)"
EMBERD_CHECK_RC=$?
if [ "$EMBERD_CHECK_RC" -eq 0 ]; then
  if [ -z "$EMBERD_HITS" ]; then
    ok "emberd-legacy" "no tracked content matches the legacy name; exceptions policy validated"
  else
    ok "emberd-legacy" "$(printf '%s' "$EMBERD_CHECK_OUT" | head -1)"
  fi
else
  if [ -z "$EMBERD_HITS" ]; then
    fail "emberd-legacy" "committed exceptions policy is invalid (zero-hit tree)"
  else
    fail "emberd-legacy" "legacy name present outside the content-addressed exceptions"
  fi
  printf '%s\n' "$EMBERD_CHECK_OUT" | sed 's/^/      /'
fi

# ---- 3c. governed-entry: no launcher-shaped script outside the sanctioned homes ----
# A governed training run is born through the sanctioned entry homes and nowhere
# else. A tracked script outside those homes that reaches for the training-segment
# API is launcher-shaped, and a standalone launcher is exactly the class this
# check keeps out of the tree.
#
# Adjudication is by (path, sha256) PAIR via tools/check_governed_entry_exceptions.py,
# never by path alone -- a file can be renamed into an exempted prefix, but its
# digest cannot be forged, and editing an enumerated file un-exempts it so the new
# behaviour is re-adjudicated rather than inherited.
#
# Test paths are excluded by construction: a test that references the training
# entry is asserting something about it, not starting a run. The sanctioned homes
# are excluded because that is where a launcher belongs.
#
# Byte source follows REPO_GUARD_SCOPE exactly as the check above does: the git
# INDEX under staged scope, the working tree otherwise. Reading working-tree bytes
# while committing staged bytes adjudicates content that never lands.
GOVERNED_ENTRY_RE='run_pretraining_segment|run_selection_pretraining_segment|run_manifest_bound_semantic_segment|run_vertical_slice'
GOVERNED_ENTRY_PATHSPEC=(
  -- '*.py' '*.sh'
  ':(exclude)runtime/ember-lab'
  ':(exclude)tools/ember-cli'
  ':(exclude)tools/ember-restart-3b'
  ':(exclude)tools/check_governed_entry_exceptions.py'
  ':(exclude)tools/repo-guard.sh'
  ':(exclude)tests'
  ':(exclude)scripts/tests'
  ':(exclude)*/tests/*'
  ':(exclude)*test_*'
)
if [ "${REPO_GUARD_SCOPE:-}" = "staged" ]; then
  GOVERNED_ENTRY_PATHS="$(git grep --cached -lIE "$GOVERNED_ENTRY_RE" "${GOVERNED_ENTRY_PATHSPEC[@]}" 2>/dev/null || true)"
else
  GOVERNED_ENTRY_PATHS="$(git grep -lIE "$GOVERNED_ENTRY_RE" "${GOVERNED_ENTRY_PATHSPEC[@]}" 2>/dev/null || true)"
fi
GOVERNED_ENTRY_OUT="$(GOVERNED_ENTRY_PATHS="$GOVERNED_ENTRY_PATHS" bash "$KERNEL_ROOT/tools/run-python-hidden.sh" "$KERNEL_ROOT/tools/check_governed_entry_exceptions.py" 2>&1)"
GOVERNED_ENTRY_RC=$?
if [ "$GOVERNED_ENTRY_RC" -eq 0 ]; then
  ok "governed-entry" "$(printf '%s' "$GOVERNED_ENTRY_OUT" | head -1)"
else
  fail "governed-entry" "launcher-shaped script outside the sanctioned entry homes"
  printf '%s\n' "$GOVERNED_ENTRY_OUT" | sed 's/^/      /'
fi

# ---- 3d. launcher-shape: nothing outside the daemon starts a run ---------
# The check above is about NAMING the training entry, which is deliberately
# broad and catches prose and manifests as well as code. This one is about
# BEING a launcher: a tracked script outside runtime/ember-lab and
# tools/ember-cli that is directly runnable AND creates a child process for a
# run. That conjunction is the standalone dispatcher issue 898 removes -- the
# thing a person runs by hand instead of running the daemon.
#
# Sanctioned homes are narrower here than for governed-entry, and deliberately
# so. governed-entry admits tools/ember-restart-3b because analysis code there
# legitimately refers to the training entry; launcher-shape does not, because a
# hand-runnable launcher living in the toolkit is precisely the offence. The run
# bodies the daemon dispatches DO match the shape (they re-exec their own
# workers) and are enumerated by digest rather than exempted by prefix, so a
# change to how they create children is re-adjudicated.
#
# Two arms, unioned:
#   A. directly runnable AND spawns a training entrypoint by name. This is the
#      precise arm; it is what catches the certified-launch dispatcher.
#   B. named as a launcher AND directly runnable AND creates any child. A name
#      alone proves nothing, which is why both other conditions are required --
#      without them the arm matches every analysis script under a directory
#      that happens to be called prelaunch.
# Arm B can only ADD coverage; it can never exempt anything arm A matched.
#
# Byte source follows REPO_GUARD_SCOPE, same as every check above.
LAUNCHER_MAIN_RE='^if __name__ == .__main__.:'
LAUNCHER_TRAINER_RE='(Popen|subprocess\.(run|check_call|check_output)|exec[vl]p?)\('
LAUNCHER_TRAINER_CHILD_RE='run_vertical_slice|certified_train|run_pretraining|torchrun|train\.py|pretrain\.py'
LAUNCHER_CHILD_RE='(subprocess\.(Popen|run|check_call)|os\.exec[vl]p?|Command::new)'
LAUNCHER_PS_CHILD_RE='(Start-(Process|Job)([[:space:]]|$)|Invoke-Expression([[:space:]]|$)|(^|[[:space:];|])&[[:space:]]+|^[[:space:]]*(([^[:space:]]*[\\/])?(python([0-9]+(\.[0-9]+)?)?|py|node|bun|cargo|rustc|dotnet|cmd|powershell|pwsh|bash|wsl|torchrun|ember(-lab)?)(\.exe)?|[^[:space:]]+\.(exe|com|bat|cmd))([[:space:]]|$))'
LAUNCHER_SHAPE_PATHSPEC=(
  -- '*.py' '*.sh'
  ':(exclude)runtime/ember-lab'
  ':(exclude)tools/ember-cli'
  ':(exclude)tools/check_governed_entry_exceptions.py'
  ':(exclude)tools/repo-guard.sh'
)
LAUNCHER_NAMED_PATHSPEC=(
  -- '*launch*.py' '*launch*.sh' '*launcher*'
  ':(exclude)runtime/ember-lab'
  ':(exclude)tools/ember-cli'
  ':(exclude)tools/powershell-launcher-shape-guard.ps1'
)
LAUNCHER_PS_SHAPE_PATHSPEC=(
  -- '*.ps1'
  ':(exclude)runtime/ember-lab'
  ':(exclude)tools/ember-cli'
  ':(exclude)tools/powershell-launcher-shape-guard.ps1'
)
LAUNCHER_PS_NAMED_PATHSPEC=(
  -- '*launch*.ps1' '*launcher*.ps1'
  ':(exclude)runtime/ember-lab'
  ':(exclude)tools/ember-cli'
)
if [ "${REPO_GUARD_SCOPE:-}" = "staged" ]; then
  LAUNCHER_GREP=(git grep --cached)
else
  LAUNCHER_GREP=(git grep)
fi
# Arm A: the spawn call and its child name may sit on different lines, so the
# child name is matched inside a two-line window before or after the call and
# the path is recovered from grep's own prefix (which uses '-' as the separator
# on context lines and ':' on match lines). Context options must precede the
# pattern: anything after `--` is a pathspec and silently provides no window.
LAUNCHER_SPAWN_PATHS="$(
  "${LAUNCHER_GREP[@]}" -nIE -B2 -A2 "$LAUNCHER_TRAINER_RE" "${LAUNCHER_SHAPE_PATHSPEC[@]}" 2>/dev/null \
    | grep -iE "$LAUNCHER_TRAINER_CHILD_RE" \
    | sed -E 's/^(.*\.(py|sh))[-:][0-9]+[-:].*/\1/' | sort -u || true
)"
LAUNCHER_MAIN_PATHS="$("${LAUNCHER_GREP[@]}" -lIE "$LAUNCHER_MAIN_RE" "${LAUNCHER_SHAPE_PATHSPEC[@]}" 2>/dev/null | sort -u || true)"
LAUNCHER_ARM_A="$(comm -12 <(printf '%s\n' "$LAUNCHER_SPAWN_PATHS") <(printf '%s\n' "$LAUNCHER_MAIN_PATHS"))"
# Arm B: named as a launcher, directly runnable, and creates a child.
LAUNCHER_NAMED_MAIN="$("${LAUNCHER_GREP[@]}" -lIE "$LAUNCHER_MAIN_RE" "${LAUNCHER_NAMED_PATHSPEC[@]}" 2>/dev/null | sort -u || true)"
LAUNCHER_NAMED_CHILD="$("${LAUNCHER_GREP[@]}" -lIE "$LAUNCHER_CHILD_RE" "${LAUNCHER_NAMED_PATHSPEC[@]}" 2>/dev/null | sort -u || true)"
LAUNCHER_ARM_B="$(comm -12 <(printf '%s\n' "$LAUNCHER_NAMED_MAIN") <(printf '%s\n' "$LAUNCHER_NAMED_CHILD"))"
LAUNCHER_PS_PATHS="$(
  "${LAUNCHER_GREP[@]}" -lIE '.' "${LAUNCHER_PS_SHAPE_PATHSPEC[@]}" 2>/dev/null \
    | sort -u || true
)"
LAUNCHER_PS_AST_OUT=""
LAUNCHER_PS_AST_RC=0
if [ -n "$LAUNCHER_PS_PATHS" ]; then
  # This override can only make the guard stricter.  It exists so the
  # load-bearing no-engine refusal is exercised by the hermetic selftest
  # instead of remaining an untested host contingency.
  if [ "${REPO_GUARD_DISABLE_POWERSHELL_AST_ENGINE:-}" = "1" ]; then
    LAUNCHER_PS_AST_OUT=$'tools/powershell-launcher-shape-guard.ps1\tREFUSED: no PowerShell AST engine is available'
    LAUNCHER_PS_AST_RC=1
  elif command -v pwsh >/dev/null 2>&1; then
    LAUNCHER_PS_ENGINE=(pwsh -NoLogo -NoProfile -NonInteractive -File)
  elif command -v powershell.exe >/dev/null 2>&1; then
    LAUNCHER_PS_ENGINE=(powershell.exe -NoLogo -NoProfile -NonInteractive -File)
  else
    LAUNCHER_PS_AST_OUT=$'tools/powershell-launcher-shape-guard.ps1\tREFUSED: no PowerShell AST engine is available'
    LAUNCHER_PS_AST_RC=1
  fi
  if [ "$LAUNCHER_PS_AST_RC" -eq 0 ]; then
    mapfile -t LAUNCHER_PS_PATH_ARRAY <<<"$LAUNCHER_PS_PATHS"
    LAUNCHER_PS_SCOPE="worktree"
    [ "${REPO_GUARD_SCOPE:-}" = "staged" ] && LAUNCHER_PS_SCOPE="staged"
    LAUNCHER_PS_AST_OUT="$(
      "${LAUNCHER_PS_ENGINE[@]}" "$KERNEL_ROOT/tools/powershell-launcher-shape-guard.ps1" \
        -Scope "$LAUNCHER_PS_SCOPE" "${LAUNCHER_PS_PATH_ARRAY[@]}" 2>&1
    )"
    LAUNCHER_PS_AST_RC=$?
  fi
fi
LAUNCHER_PS_REFUSALS="$(printf '%s\n' "$LAUNCHER_PS_AST_OUT" | grep $'\tREFUSED:' || true)"
LAUNCHER_PS_AST_PATHS="$(
  printf '%s\n' "$LAUNCHER_PS_AST_OUT" | grep -v $'\tREFUSED:' | cut -f1 | sed '/^$/d' | sort -u
)"
LAUNCHER_SHAPE_PATHS="$(printf '%s\n%s\n%s\n' \
  "$LAUNCHER_ARM_A" "$LAUNCHER_ARM_B" "$LAUNCHER_PS_AST_PATHS" \
  | sed '/^$/d' | sort -u)"
LAUNCHER_SHAPE_OUT="$(LAUNCHER_SHAPE_PATHS="$LAUNCHER_SHAPE_PATHS" bash "$KERNEL_ROOT/tools/run-python-hidden.sh" "$KERNEL_ROOT/tools/check_governed_entry_exceptions.py" launcher-shape 2>&1)"
LAUNCHER_SHAPE_RC=$?
if [ "$LAUNCHER_PS_AST_RC" -ne 0 ] && [ -n "$LAUNCHER_PS_REFUSALS" ]; then
  fail "launcher-shape" "PowerShell source could not be safely parsed for launcher shape"
  printf '%s\n' "$LAUNCHER_PS_REFUSALS" | sed 's/^/      /'
elif [ "$LAUNCHER_SHAPE_RC" -eq 0 ]; then
  ok "launcher-shape" "$(printf '%s' "$LAUNCHER_SHAPE_OUT" | head -1)"
else
  fail "launcher-shape" "a script outside the daemon can be run by hand to start a run"
  printf '%s\n' "$LAUNCHER_SHAPE_OUT" | sed 's/^/      /'
fi

# ---- 4. exactly one old-or-new authority document ------------------------
AUTHORITY_PATHS_OK=1
GOAL_REL=""
STATE_REL=""
for AUTHORITY_NAME in GOAL.md INVARIANT.md GOVERNANCE.md CONTINUITY.md REDACTIONS.md STATE.md; do
  OLD_REL="$AUTHORITY_NAME"
  NEW_REL="docs/authority/$AUTHORITY_NAME"
  DOMAIN_REL=""
  if [ "$AUTHORITY_NAME" = "GOAL.md" ] || [ "$AUTHORITY_NAME" = "STATE.md" ]; then
    DOMAIN_REL="docs/domains/governance/authority/$AUTHORITY_NAME"
  fi
  OLD_PRESENT=0
  NEW_PRESENT=0
  DOMAIN_PRESENT=0
  git ls-files --error-unmatch "$OLD_REL" >/dev/null 2>&1 && OLD_PRESENT=1
  git ls-files --error-unmatch "$NEW_REL" >/dev/null 2>&1 && NEW_PRESENT=1
  [ -n "$DOMAIN_REL" ] && git ls-files --error-unmatch "$DOMAIN_REL" >/dev/null 2>&1 && DOMAIN_PRESENT=1
  AUTHORITY_COUNT=$((OLD_PRESENT + NEW_PRESENT + DOMAIN_PRESENT))
  if [ "$AUTHORITY_COUNT" -ne 1 ]; then
    if [ -n "$DOMAIN_REL" ]; then
      fail "authority-paths" "$AUTHORITY_NAME must exist at exactly one of '$OLD_REL', '$NEW_REL', or '$DOMAIN_REL' (found $AUTHORITY_COUNT)"
    else
      fail "authority-paths" "$AUTHORITY_NAME must exist at exactly one of '$OLD_REL' or '$NEW_REL' (found $AUTHORITY_COUNT)"
    fi
    AUTHORITY_PATHS_OK=0
  elif [ "$OLD_PRESENT" -eq 1 ]; then
    [ "$AUTHORITY_NAME" = "GOAL.md" ] && GOAL_REL="$OLD_REL"
    [ "$AUTHORITY_NAME" = "STATE.md" ] && STATE_REL="$OLD_REL"
  elif [ "$NEW_PRESENT" -eq 1 ]; then
    [ "$AUTHORITY_NAME" = "GOAL.md" ] && GOAL_REL="$NEW_REL"
    [ "$AUTHORITY_NAME" = "STATE.md" ] && STATE_REL="$NEW_REL"
  else
    [ "$AUTHORITY_NAME" = "GOAL.md" ] && GOAL_REL="$DOMAIN_REL"
    [ "$AUTHORITY_NAME" = "STATE.md" ] && STATE_REL="$DOMAIN_REL"
  fi
done
if [ "$AUTHORITY_PATHS_OK" -eq 1 ]; then
  ok "authority-paths" "each authority document has exactly one canonical old-or-new-or-domain path"
fi

GOALN="$(git ls-files | grep -cE '^(GOAL[^/]*\.md|docs/authority/GOAL[^/]*\.md|docs/domains/governance/authority/GOAL[^/]*\.md)$')"
if [ "$GOALN" -eq 1 ] && [ -n "$GOAL_REL" ]; then
  ok "goal-doc" "exactly one ($GOAL_REL)"
else
  fail "goal-doc" "found $GOALN GOAL*.md files across canonical authority locations; exactly one is allowed"
  git ls-files | grep -E '^(GOAL[^/]*\.md|docs/authority/GOAL[^/]*\.md|docs/domains/governance/authority/GOAL[^/]*\.md)$' | sed 's/^/      /'
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

# ---- 6. docs/domains/governance/authority/STATE.md is a bounded position ledger, not an append log ---------
if [ -n "$STATE_REL" ] && git ls-files --error-unmatch "$STATE_REL" >/dev/null 2>&1; then
  SL="$(git show ":$STATE_REL" 2>/dev/null | wc -l | tr -d ' ')"
  [ -z "$SL" ] && SL="$(wc -l < "$STATE_REL" | tr -d ' ')"
  if [ "$SL" -le "$MAX_STATE_LINES" ]; then
    ok "state" "$STATE_REL $SL lines (<= $MAX_STATE_LINES)"
  else
    fail "state" "docs/domains/governance/authority/STATE.md $SL lines exceeds $MAX_STATE_LINES — it is a position ledger, not an append log"
  fi
fi

# ---- 7. branch name follows the single scheme ----------------------------
BR="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
case "$BR" in
  master|HEAD) ok "branch" "$BR" ;;
  feat/*|fix/*|exp/*|chore/*|docs/*) ok "branch" "$BR" ;;
  *)
    if [ "${GITHUB_ACTIONS:-}" = "true" ] && [ "${GITHUB_EVENT_NAME:-}" = "pull_request" ] && [ -n "${GITHUB_HEAD_REF:-}" ] && [ "$GITHUB_HEAD_REF" = "$BR" ]; then
      ok "branch" "$BR is a pre-existing open-PR head; naming is advisory only—never rename the live ref"
    else
      fail "branch" "branch '$BR' must match <type>/<slug> where type in feat|fix|exp|chore|docs; never rename a branch that has an open pull request—detach HEAD and push to the existing ref"
    fi
    ;;
esac

# ---- 8. range checks: goal edits and evidence edits never co-commit ------
RANGE=""
if [ "${1:-}" = "--range" ] && [ -n "${2:-}" ]; then
  RANGE="$2"
elif [ "${1:-}" = "--base" ] && [ -n "${2:-}" ]; then
  if [ "${REPO_GUARD_PR_MERGE_SUBJECT:-}" = "true" ]; then
    # pull_request_target checks run against refs/pull/<n>/merge. Its first
    # parent is the live base actually used to construct that merge subject;
    # the event payload's base SHA can lag behind it. Scanning from the stale
    # payload base blames later PRs for squash commits already on the live base.
    LIVE_MERGE_PARENT="$(git rev-parse --verify HEAD^1 2>/dev/null || true)"
    MERGE_HEAD_PARENT="$(git rev-parse --verify HEAD^2 2>/dev/null || true)"
    if [ -z "$LIVE_MERGE_PARENT" ] || [ -z "$MERGE_HEAD_PARENT" ]; then
      fail "range" "PR merge subject is not a two-parent merge commit"
      RANGE="$2..HEAD"
    elif ! git merge-base --is-ancestor "$2" "$LIVE_MERGE_PARENT" 2>/dev/null; then
      fail "range" "event base is not reachable from the live PR merge parent"
      RANGE="$2..HEAD"
    else
      # Exclude the exact live first parent while retaining every
      # branch-authored commit reachable only through the second parent.
      RANGE="$LIVE_MERGE_PARENT..HEAD"
    fi
  else
    RANGE="$(git merge-base "$2" HEAD)..HEAD"
  fi
fi
# ---- 8b. every changed receipt must pass the fail-closed schema floor -----
# Historical debt remains visible to `receipt_check.py --all`, but it cannot
# justify landing another malformed or unstamped receipt. NUL-delimited Git
# paths preserve spaces and other valid filename bytes without shell splitting.
CHANGED_RECEIPT_SCOPE=0
CHANGED_RECEIPT_OUT=""
CHANGED_RECEIPT_RC=0
if [ ! -f "$KERNEL_ROOT/scripts/check_changed_receipts.py" ]; then
  fail "changed-receipts" "trusted scripts/check_changed_receipts.py is missing"
elif [ "${REPO_GUARD_SCOPE:-}" = "staged" ]; then
  CHANGED_RECEIPT_SCOPE=1
  CHANGED_RECEIPT_OUT="$(
    git diff --cached --name-only --diff-filter=ACMR -z -- receipts |
      bash "$KERNEL_ROOT/tools/run-python-hidden.sh" "$KERNEL_ROOT/scripts/check_changed_receipts.py" --root "$SUBJECT_ROOT" --null 2>&1
  )"
  CHANGED_RECEIPT_RC=$?
elif [ -n "$RANGE" ]; then
  CHANGED_RECEIPT_SCOPE=1
  CHANGED_RECEIPT_OUT="$(
    git diff --name-only --diff-filter=ACMR -z "$RANGE" -- receipts |
      bash "$KERNEL_ROOT/tools/run-python-hidden.sh" "$KERNEL_ROOT/scripts/check_changed_receipts.py" --root "$SUBJECT_ROOT" --null 2>&1
  )"
  CHANGED_RECEIPT_RC=$?
fi
if [ "$CHANGED_RECEIPT_SCOPE" -eq 1 ]; then
  if [ "$CHANGED_RECEIPT_RC" -eq 0 ]; then
    ok "changed-receipts" "$CHANGED_RECEIPT_OUT"
  else
    fail "changed-receipts" "changed receipt validation failed"
    printf '%s\n' "$CHANGED_RECEIPT_OUT" | sed 's/^/      /' | head -30
  fi
fi

if [ -n "$RANGE" ]; then
  BAD=""
  for c in $(git rev-list "$RANGE" 2>/dev/null); do
    files="$(git show --name-only --format= "$c")"
    if echo "$files" | grep -qE '^(GOAL\.md|docs/authority/GOAL\.md|docs/domains/governance/authority/GOAL\.md)$' && echo "$files" | grep -qE '^receipts/'; then
      BAD="$BAD $c"
    fi
  done
  if [ -n "$BAD" ]; then
    fail "goal/evidence" "commit(s) edit a canonical GOAL.md and receipts/ in one change:$BAD"
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
  AUTHORITY_OUT="$(bash "$KERNEL_ROOT/tools/run-python-hidden.sh" "$KERNEL_ROOT/scripts/verify_authority_conservation.py" "${AUTHORITY_ARGS[@]}" 2>&1)"
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
