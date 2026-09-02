# Issue 1964 Spider Terminal Evaluator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the aggregate-only Spider adapter with a hash-bound, row-complete exact/execution evaluator that emits a self-hashed terminal receipt and fails closed on every frozen negative.

**Architecture:** Keep `scripts/ember_restart_eval_spider.py` as the single CLI boundary, but split its logic into pure manifest/identity validation, disposable-database row execution, authoritative scorer invocation, and canonical receipt publication functions. A closed-schema input manifest binds the two upstream scorer trees, dataset bytes, ordered rows, prediction/inference lineage, checkpoint identities, timeout, and source commit. Tests use real pinned upstream scorer bytes for a minimal Spider-shaped database and synthetic fixtures only for deliberate refusal classes.

**Tech Stack:** Python 3.10 standard library, SQLite, pinned Spider and test-suite-sql-eval Python sources, pytest.

**Spec:** untracked design receipt SHA-256 `791e6532902c452bca2656bd38eb01d3e543137330b7d1a9fe2fab1bf85b91de`

## Global Constraints

- Preserve EMBER-02 / EMBER-02C authority headers.
- All filesystem identities are SHA-256 bound before scorer import or SQL execution.
- Prediction row IDs equal the complete ordered frozen row set exactly.
- Every database execution uses a fresh disposable copy; canonical databases are never writable.
- Output is new-path-only canonical JSON with `self_sha256`; pre-existing output refuses.
- No capability threshold or `criterion_result` is emitted.
- Errors, timeouts, and invalid SQL stay in the denominator as named row classes.

---

### Task 1: Closed manifest and identity boundary

**Files:**
- Modify: `scripts/ember_restart_eval_spider.py`
- Create: `tests/test_ember_restart_eval_spider_terminal.py`

**Interfaces:**
- Consumes: `--manifest`, `--score-output`, and a closed JSON manifest with the exact fields frozen in the design receipt.
- Produces: `load_manifest(path: Path) -> dict`, `canonical(value: object) -> bytes`, `sha256_file(path: Path) -> str`, and validated ordered row/prediction records.

- [ ] Write failing tests for unknown/missing manifest keys, evaluator drift, database-tree drift, prediction/inference/checkpoint substitution, duplicate/missing/extra/reordered row IDs, empty SQL, and pre-existing output.
- [ ] Run the focused tests and confirm every new test fails for the intended missing validation.
- [ ] Implement strict schema, safe-path, hash, row-identity, lineage, and no-overwrite validation without scorer import.
- [ ] Run focused tests and confirm all identity/refusal tests pass.
- [ ] Commit the identity boundary and tests.

### Task 2: Authoritative exact and execution scoring

**Files:**
- Modify: `scripts/ember_restart_eval_spider.py`
- Modify: `tests/test_ember_restart_eval_spider_terminal.py`

**Interfaces:**
- Consumes: validated rows plus hash-verified exact-match and execution-match scorer roots.
- Produces: `score_row(row, custody, timeout_seconds) -> RowResult` and ordered exact/execution row results.

- [ ] Write a failing real pinned-scorer smoke using one minimal Spider-shaped SQLite database and exact upstream bytes.
- [ ] Add failing planted cases for wrong gold, missing database, changed schema, syntax/runtime failure, mutating SQL, and finite timeout.
- [ ] Invoke the pinned exact scorer and pinned execution scorer only after byte verification; create a fresh disposable database copy for each row; classify every failure without dropping denominator rows.
- [ ] Run the real smoke and all planted scorer negatives to green.
- [ ] Commit scorer execution and tests.

### Task 3: Canonical terminal receipt and cleanup evidence

**Files:**
- Modify: `scripts/ember_restart_eval_spider.py`
- Modify: `tests/test_ember_restart_eval_spider_terminal.py`
- Modify: `tests/domain-governance/test_ember_restart_eval_spider.py`
- Modify: `tests/domain-governance/test_ember_restart_eval_spider_json_predictions.py`

**Interfaces:**
- Consumes: ordered row results and all validated input hashes.
- Produces: one `ember-issue1964-spider-terminal-evaluator-v1` receipt with ordered-row-result hash, scorer stream hashes, resource receipt hash, cleanup status, and self-hash.

- [ ] Write failing tests that independently recompute ordered-row-result and terminal self-hashes, require both metric denominators, and prove no `criterion_result` exists.
- [ ] Implement canonical terminal publication with `open('xb')`, exact counts/metrics/classes, cleanup verification, and claim boundary.
- [ ] Convert the two legacy aggregate tests to the manifest-bound terminal contract or delete only assertions superseded by stricter terminal behavior.
- [ ] Run all Spider tests, diff check, and repository guard.
- [ ] Commit the terminal receipt implementation and compatibility updates.

### Task 4: #1581 admission boundary

**Files:**
- Modify: `scripts/ember_restart_eval_spider.py`
- Modify: `tests/test_ember_restart_eval_spider_terminal.py`

**Interfaces:**
- Consumes: exact closed-manifest hashes for the #1581 Spider admission receipt, catalog fragment, and Apache-2.0 license sidecar.
- Produces: either a validated `ADMITTED_FOR_PROTECTED_EVALUATION` binding or a row-complete terminal `NOT_COVERED` receipt whose sole row class is `MISSING_1581_ADMISSION_BINDING_FOR_SPIDER`.

- [x] Write RED tests for missing, malformed, and identity-substituted admission bytes plus one closed synthetic valid fixture.
- [x] Implement closed receipt/sidecar schemas, self-hash verification, exact raw-byte identities, catalog protected-eval/object/consumer edges, and frozen evaluator identity equality.
- [x] Prove invalid admission produces a full-denominator structural `NOT_COVERED` receipt without scorer execution.
- [x] Run focused and broad Spider tests to green.
- [ ] Rebind to the concrete successor bytes minted after the #1581 consumer-kind carrier merges, then run the first genuinely COVERED terminal.
