# 13 — Runbook

Practical commands, reproduced from real sessions working this repository
(not aspirational — every command below was actually run against this tree
while authoring this anatomy set and the C-PROC/C-TALLY fixes that preceded
it).

## Create a worktree for a scoped fix

```bash
python src/ember/governance/scripts/worktree_lifecycle.py create \
  --path <local-worktree-root>/<name> \
  --branch fix/<name> \
  --owner <you> \
  --purpose "<one-line purpose>" \
  --expires <YYYY-MM-DD> \
  --start-point origin/master
```
`<local-worktree-root>` is an operator-chosen local directory outside the
main checkout and outside `.claude/` — never a path this doc hardcodes. Run
from the main checkout, after `git fetch origin` if master may have moved.
Never `git worktree add` directly — see 02_REPO_TOPOLOGY.md.

## Run a single totality-board condition probe

```bash
python scripts/ember_totality/test_c_proc.py
python scripts/ember_totality/test_c_anat.py
```
Each probe prints exactly one `RED <reason>` / `GREEN <reason>` /
`UNEVALUABLE <reason>` line and exits 0.

## Validate a new receipt before committing it

```bash
python src/ember/governance/scripts/receipt_check.py --file receipts/<subdir>/<name>.json
```
Fails closed (non-zero exit) on any schema-floor violation — fix before
committing, per 10_RECEIPTS_PROVENANCE.md.

## Verify authority conservation

```bash
python scripts/verify_authority_conservation.py --root .
```
Prints `EMBER_AUTHORITY_CONSERVATION PASS` or `FAIL <leg> <finding>`. Also
runs automatically inside the repo-guard commit/push hooks.

## Commit, push, open a PR

```bash
git add <files>
git commit -m "..."          # repo-guard runs here; fails closed
git push -u origin fix/<name>  # repo-guard runs again here
gh pr create --repo wordingone/ember --title "..." --body-file <file>
```
If `git commit` fails with `UNMANAGED_WORKTREE: <path>`, that is repo-guard
detecting a stray, non-lifecycle-managed worktree SOMEWHERE in the repo
(not necessarily yours) — do not touch another contributor's live worktree;
wait for its owner to retire it, or escalate.

## Set live-PR-policy metadata on an open PR

```bash
gh pr edit <n> --repo wordingone/ember \
  --add-label "affects:EMBER-02" --add-label "area:<x>" \
  --add-label "kind:<x>" --add-label "needs:review" \
  --add-label "priority:p1" --add-label "review:self-only" \
  --add-label "state:review" \
  --milestone "EMBER-02 — Three-billion-parameter foundation birth"
gh pr edit <n> --repo wordingone/ember --body-file <file>
gh pr checks <n> --repo wordingone/ember
```
Every label FAMILY (`affects:`/`area:`/`kind:`/`needs:`/`priority:`/
`review:`/`state:`) needs exactly one label; the PR body needs every
required section filled (see `docs/charter/probe-authoring-contract.md`-adjacent PR
template conventions) with real content, `Exact base SHA` matching the LIVE
`origin/master` tip at check-run time (not the branch's git merge-base if
master has since moved), and `Affected milestones` containing the milestone
title verbatim.

## Current gaps — honestly stated

This runbook covers the workflow this doc set's own authoring session
actually exercised. It is not a complete operator manual — training-launch,
GPU-window, and eval-harness runbooks live in their own docs
(`docs/domains/governance/ember-restart/ember-restart-3b-governed-runner-v1.md` and similar) and are not
duplicated here.
