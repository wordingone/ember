# Governance

This document defines how the `ember` repository is maintained. It exists to
prevent the failure modes this repo accumulated: an ownerless confluence of
parallel workstreams with no canonical state, no lifecycle, and no single
definition of done.

## 1. Ownership

The repository has **one integration owner** at any time. The owner is the only
party that merges to `master`, prunes branches, triages issues/PRs, and cuts
tags. Contributors open branches and PRs; they do not self-merge. Ownership is
recorded at the top of `STATE.md`. (Roles are referenced by function here, never
by personal name — see §7.)

## 2. Canonical state

- **`master` is the canonical branch.** It is the single source of truth for the
  project's current state. No long-lived parallel "real work lives elsewhere"
  branch is permitted. If `master` is stale, that is a defect to fix, not a
  condition to route around.
- **`STATE.md` is the single position ledger** — current state only, kept short.
  It is *not* an append-only narration log, and it is *not* duplicated by commit
  messages or by files under `receipts/`.
- **`GOAL.md` is the single goal document.** There is exactly one. Derived paste
  blocks or prompt snippets are not kept as separate tracked files.
- **`receipts/` holds evidence**, never status or goal text.

## 3. Branch lifecycle

- Branches are short-lived and single-purpose.
- A branch is **deleted immediately when merged** (or when abandoned). Merged
  branches are never retained — their commits live in `master`.
- The owner prunes merged/dead branches on a regular cadence. The steady-state
  branch count is small (active work only), not hundreds.

## 4. Pull requests & issues

- PRs are resolved **oldest-first**; an older open PR is never stranded behind a
  newer merge.
- Every open PR and issue has an owner and a next action; stale items (no
  movement in a defined window) are triaged — merged, closed, or explicitly
  re-scoped — never left to accumulate.
- A PR merges only on green CI against `master`.

## 5. Branch & ticket naming (one scheme)

A single naming scheme replaces the parallel taxonomies that accreted here.
Branches use `type/short-slug`:

| type        | meaning                                   |
|-------------|-------------------------------------------|
| `feat/`     | new capability                            |
| `fix/`      | bug or regression fix                     |
| `exp/`      | experiment / probe (expected to be short) |
| `chore/`    | hygiene, refactor, tooling                |
| `docs/`     | documentation only                        |

Issue/PR references use the GitHub number only. Private per-workstream ticket
prefixes are not used in branch names or commit subjects.

## 6. Commit messages

- The subject is a factual description of the change in the imperative mood.
- Commit messages are **not a status board**: no `DONE`/`FROZEN`/`ADVANCE`-style
  state verbs standing in for the position ledger. State lives in `STATE.md`.
- A commit changing the goal (`GOAL.md`) must **not** also change the evidence
  (`receipts/`) that grades against it. Goal edits and evidence edits are
  separate commits, so the target never moves in lockstep with its own proof.

## 7. Provenance & privacy

- **No personal or operator names, and no absolute local filesystem paths,**
  appear anywhere tracked in this (source-available) repository — not in code,
  docs, commit messages, branch names, issues, or PRs. Reference roles by
  function. Paths are repository-relative.
- Authorship in git history should distinguish real contributors rather than
  collapsing every commit under one identity, to the extent the workflow allows.

## 8. Releases

Meaningful milestones are marked with annotated tags (`vMAJOR.MINOR`). Tags are
the durable, human-readable record of "what state was real when" — distinct from
the moving branch tip.

---

*Deviations from this document are themselves defects. The point of the repo is
that its structure can always answer: what is the project, what is true now, and
who owns the next step.*
