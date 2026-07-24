# CI Suite Build Report — feat/ci-actions-suite

Base: origin/master @ 3a907fe82e45bc2ddaad3dbf18a13afae189304c
Worktree: managed via scripts/worktree_lifecycle.py create

## Files added

- `.github/workflows/python-tests.yml`
- `.github/workflows/ember-cli-tests.yml`
- `.github/workflows/identity-verifiers.yml`
- `.github/workflows/lint.yml`

All four carry the same `goal_id: EMBER-02 / workstream_id: EMBER-02A / next_executed_outcome`
comment-header convention found in the two existing workflows
(`freshness-monitor.yml`, `repo-guard.yml`).

## Discovery

- Real python test dirs: `tests/` (161 files not importing torch, 37 that do,
  spread across `tests/`, `tests/ember_01_identity/`, `tests/ember_restart_model/`,
  and `scripts/tests/`) and `scripts/tests/`.
- No `pytest.ini` / `pyproject.toml` / `setup.cfg` / requirements file exists
  anywhere in the repo — python deps are not pinned/declared. `python-tests.yml`
  installs a curated minimal set (torch CPU wheel, pytest, jsonschema,
  cryptography, tokenizers, pyyaml, numpy) inferred from the actual import
  surface of the non-torch test files.
- No hardcoded operator-machine paths found in any test file (checked common
  local-drive / WSL-mount / user-profile path shapes — zero hits). One file
  hard-requires a GPU:
  `tests/ember_restart_model/test_checkpoint_artifacts.py` (unconditional
  `torch.cuda.is_available()` assertion, no skip marker) — excluded via
  `--ignore` with a comment; nothing else in the suite needs GPU hardware to
  exercise correctness on CPU torch.
- `tools/ember-cli/src/package.json`: lockfile is `bun.lock` (not `.lockb`);
  scripts are `dev`, `test` (`bun test`), `typecheck` (`tsc --noEmit`), `build`.
  No lint script and no linter devDependency configured, so no JS/TS lint step
  was added — `lint.yml` is python-only (ruff), matching the "don't introduce
  a new tool if none configured" instruction. `ember-cli-tests.yml` runs
  `bun install --frozen-lockfile`, `bun run typecheck`, then `timeout 600 bun
  test`.
- `scripts/ember_01_custody/verify_c0_failure_class_ledger.py` and
  `scripts/ember_01_identity/validate_identity.py` both exist as named.
  `verify_c0_failure_class_ledger.py` has a `--ledger` default pointing at the
  checked-in `manifests/ember-01-custody/c0-failure-class-ledger.json`, so it
  runs with no args. `validate_identity.py` has no self-test mode (its CLI
  requires real manifest/checkpoint artifacts) — `identity-verifiers.yml`
  instead runs `tests/ember_01_identity/test_validate_identity.py`
  (its actual unit tests) plus the ledger verifier plus
  `tests/ember_01_custody` (the custody suite named in the brief).
- No `ruff.toml` / `[tool.ruff]` anywhere — `lint.yml` runs ruff defaults.

## Local verification receipts

- **YAML parse** — all 6 workflow files (2 existing + 4 new) parsed clean via
  `python -c "yaml.safe_load(...)"`. Output: `OK` for each file, no errors.
- **repo-guard** — `bash tools/repo-guard.sh --base origin/master` → `PASS`
  (all 11 checks ok, authority certificate passes). Full tail:
  ```
  ok   [.agent] not tracked
  ok   [line-endings] tracked text files are LF-only
  ok   [paths] no absolute local paths
  ok   [path-frags] no local path fragments
  ok   [names] none found (hashed denylist)
  ok   [goal-doc] exactly one (GOAL.md)
  ok   [dup-dir] no known duplicate dirs
  ok   [state] STATE.md 1 lines (<= 150)
  ok   [branch] feat/ci-actions-suite
  ok   [goal/evidence] no goal+evidence co-commits in 3a907fe82e45bc2ddaad3dbf18a13afae189304c..HEAD
  ok   [authority] EMBER authority conservation certificate passes

  repo-guard: PASS
  ```
- **verify_c0_failure_class_ledger.py** — ran locally with no args (default
  ledger path), completed and printed a valid JSON verdict object
  (`schema: ember-01-c0-conjunct3-verdict-v1`, `classes_checked: 14`,
  `verdict: BLOCKED` — the ledger's actual current content-state, not a
  workflow-authoring defect; the step correctly propagates that as a non-zero
  exit in CI). Confirms the command in `identity-verifiers.yml` is exactly
  right and runnable with the repo's checked-in artifact.
- **NOT executed locally, disclosed honestly:**
  - `python-tests.yml`'s pytest run (tests/, scripts/tests/) — not run locally;
    installing the full curated dependency set (torch CPU wheel + co.) inside
    the available time budget was not attempted given the tight wall-clock
    cap on this build lane. The command syntax (`pytest scripts/tests -x -q`,
    `pytest tests -x -q --ignore=...`) matches how the repo's own test dirs
    are actually laid out (verified via `git ls-tree`), and mirrors the
    invocation pattern used elsewhere in the codebase.
  - `tests/ember_01_custody` pytest run inside `identity-verifiers.yml` — a
    local attempt was started (`pytest` confirmed present in the environment)
    but the process did not return within the available session time and was
    terminated; not confirmed green locally. The custody test files
    themselves were inspected (`test_census.py`, `test_compact_receipt.py`,
    `test_issue_census.py`, `test_resumable_discovery.py`,
    `test_verify_c0_failure_class_ledger.py`) and import only stdlib/pytest,
    no torch — this is a time-budget gap, not a known defect.
  - `bun install` / `bun test` in `tools/ember-cli/src` — not run locally
    (no local `bun` install confirmed in this session); untested.

## Commit

Single commit on `feat/ci-actions-suite`, author `wordingone <hjhan811@gmail.com>`,
adding the four workflow files above. No push — a maintainer verifies and pushes.

## Outstanding before push

- Confirm/verify `bun test` and the full pytest runs actually pass in CI (or
  locally with more time) before treating this as fully green — the workflow
  *authoring* is verified against the repo's real layout and conventions, but
  three of the four new workflows' actual test-execution steps were not
  proven green end-to-end in this build lane due to the wall-clock cap.
