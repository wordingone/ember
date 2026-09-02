# Issue 1464 E8 Parity Plumbing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add identical dense pre-update gradient-norm telemetry, the ruled E7 v2 ratio-sigma composer, and a no-overwrite R1-E8 parity producer.

**Architecture:** A shared accumulator is called by the existing Tier-1 fused hook and the later Tier-2 hook. Two focused evidence producers reopen immutable inputs, derive Decimal-bound outputs, and publish durable closed-schema receipts; the validator stays unchanged.

**Tech Stack:** Python 3.10, PyTorch, pytest, JSON/JSONL, SHA-256, `Decimal`, Ember durable I/O.

**Spec:** `docs/domains/governance/superpowers/specs/2026-08-21-issue1464-e8-parity-plumbing-design.md`

## Global Constraints

- Start from public head `8846f5981bc01ee1a661de5e9a518a86dec57ab3` or a reviewed descendant.
- No production code is written before its named test fails for the missing behavior.
- `grad_norm` is the L2 norm over every registered parameter whose gradient is non-`None`, including 1-D parameters, before update or release.
- The E7 v2 estimator is seed-order invariant normalized pooled population sigma; no raw-key alias.
- `src/ember/governance/scripts/r1_e8_validator.py` remains unchanged.
- Every producer uses exclusive no-overwrite output creation and exact input hash reopening.
- The full local baseline may finish only with the exact same 20 named pre-existing failures and no additional or substituted failure.

---

### Task 1: Shared pre-update gradient norm and telemetry

**Files:**
- Modify: `src/ember/infrastructure/tools/ember-restart-3b/a1_optimizer.py`
- Modify: `tools/ember-restart-3b/a1_execution.py`
- Modify: `tests/ember_restart_model/domain-governance/test_a1_fused_backward.py`
- Modify: `tests/ember_restart_model/domain-governance/test_a1_execution_e8_telemetry.py`

**Interfaces:**
- Produces: `FullGradientNormAccumulator.accumulate(gradient: torch.Tensor) -> None`
- Produces: `FullGradientNormAccumulator.finish_step() -> float`
- Produces: `FullStateAdamWCPUOffload.finish_gradient_norm() -> float`
- Changes: `_train_step_envelope(..., grad_norm: float) -> dict[str, Any]`

- [ ] **Step 1: Write failing accumulator tests**

Add tests with hand-derived gradients `[3, 4]` and `[12]` expecting `13.0`, a 1-D inclusion test, empty/double-finish refusals, and a hook-order test whose update mutates the parameter after the expected norm is captured.

- [ ] **Step 2: Verify RED**

Run: `python -B -m pytest tests/ember_restart_model/domain-governance/test_a1_fused_backward.py -q`

Expected: FAIL because `FullGradientNormAccumulator` and `finish_gradient_norm` do not exist.

- [ ] **Step 3: Implement the minimum accumulator and hook integration**

Store an FP32 scalar sum of squares, refuse sparse/non-finite inputs, accumulate before `_apply_parameter_update`, reset only in `finish_step`, and expose it through the optimizer.

- [ ] **Step 4: Verify GREEN without optimizer-byte drift**

Run the Task 1 fused-backward file and retain its existing bit-identical Tier-1 assertions.

- [ ] **Step 5: Write and verify the telemetry RED test**

Call `_train_step_envelope(..., grad_norm=13.0)` and assert payload `grad_norm == "13.000000000000"`; run the telemetry test and observe the missing argument/field failure.

- [ ] **Step 6: Wire telemetry and verify GREEN**

Pass `optimizer.finish_gradient_norm()` after `optimizer.step()` and before the JSONL write. Run both Task 1 test files.

### Task 2: E7 v2 dimensionless sigma composer

**Files:**
- Create: `src/ember/governance/scripts/r1_e7_ratio_sigma.py`
- Create: `tests/domain-governance/test_r1_e7_ratio_sigma.py`
- Modify: `tests/test_r1_e8_validator.py`

**Interfaces:**
- Produces: `normalized_grad_norm_ratio_sigma(seed_series: dict[str, list[dict[str, Any]]]) -> dict[str, Any]`
- Produces: `compose_e7_v2(*, evidence_path: Path, v1_receipt_path: Path, telemetry_paths: tuple[Path, Path], thresholds_path: Path, output_dir: Path) -> tuple[Path, Path]`

- [ ] **Step 1: Write analytic RED tests**

Use two steps with literal seed pairs `(1, 3)` and `(2, 2)`. Normalized values are `(0.5, 1.5)` and `(1, 1)`, so pooled variance is `0.125` and sigma is `sqrt(0.125)`. Assert seed-order invariance, positive finite inputs, and the two-seed disclosure identity.

- [ ] **Step 2: Verify RED**

Run: `python -B -m pytest tests/domain-governance/test_r1_e7_ratio_sigma.py -q`

Expected: import failure because the composer does not exist.

- [ ] **Step 3: Implement estimator and closed v2 composer**

Reuse the battery telemetry parser and loss/raw-grad pooled sigma function. Reopen the v1 evidence, v1 receipt, threshold authority, and both telemetry hashes. Copy the v1 `prereg` block exactly; emit `loss`, ruled `grad_norm_ratio`, and record-only `grad_norm`; write v2 and composition receipts with exclusive durable creation.

- [ ] **Step 4: Verify GREEN and no-overwrite**

Run the new test file. Its second identical compose call must raise `FileExistsError` and leave first bytes unchanged.

- [ ] **Step 5: Pin validator refusal behavior**

In `tests/test_r1_e8_validator.py`, add a live-v1-shaped E7 fixture with only `{loss, grad_norm}` and assert `E7_SIGMA_MISSING`; retain the positive fixture with `{loss, grad_norm_ratio, grad_norm}`.

- [ ] **Step 6: Verify validator GREEN unchanged**

Run: `python -B -m pytest tests/test_r1_e8_validator.py -q`

Expected: PASS with no diff in `src/ember/governance/scripts/r1_e8_validator.py`.

### Task 3: No-overwrite parity producer

**Files:**
- Create: `tools/ember-restart-3b/a1_e8_parity.py`
- Create: `tests/ember_restart_model/domain-governance/test_a1_e8_parity.py`

**Interfaces:**
- Produces: `derive_parity_series(telemetry_path: Path, *, run_id: str, run_receipt_sha256: str, steps: int) -> dict[str, Any]`
- Produces: `mint_parity_receipt(*, packet_root: Path, candidate_run: Path, reference_run: Path, candidate_telemetry: Path, candidate_run_id: str, reference_telemetry: Path, reference_run_id: str, liveness_receipt: Path, thresholds_path: Path, e7_receipt: Path) -> Path`

- [ ] **Step 1: Write series RED tests**

Feed literal JSONL with steps 1..3 and assert the exact three-field sample rows. Add missing, duplicate, foreign-run, non-finite, and missing-grad-norm cases.

- [ ] **Step 2: Verify RED**

Run the new producer test file and observe the missing-module failure.

- [ ] **Step 3: Implement series extraction**

Parse real train-step envelopes, filter exact run ID, require contiguous `1..steps`, and serialize loss/norm through the existing 12-decimal convention.

- [ ] **Step 4: Write receipt RED tests**

Build complete literal candidate/reference/liveness/E7 fixtures. Assert exact Decimal metrics, SHA references, self digest, honest `PASS` and `FAIL`, identity refusal before output, and no-overwrite.

- [ ] **Step 5: Implement minimal receipt mint**

Reopen and validate all inputs, write both series first and the top-level receipt last through `atomic_create_durable`, and calculate exactly the validator's formulas.

- [ ] **Step 6: Verify producer and real validator GREEN**

Run the producer tests and `tests/test_r1_e8_validator.py` together, including feeding the producer output to the real validator.

### Task 4: Carrier verification, identity remint, and publication

**Files:**
- Modify: `data/ember-restart-3b/owned-text-lab-input-identity-v2.json`
- Modify: `manifests/training-dependency-closure.json`

**Interfaces:**
- Consumes: the three completed Task deliverables.
- Produces: one immutable Carrier P commit and draft PR.

- [ ] **Step 1: Run focused tests**

Run the Task 1-3 test files plus dense/offload, certified A1 route, energy, liveness, and R1-E8 validator tests.

- [ ] **Step 2: Remint source identity**

Run `tools/ember-restart-3b/remint_text_lab_input_identity.py --write`, then run its check mode and the training dependency closure guard.

- [ ] **Step 3: Prove exact-20 baseline invariance**

Run the same 262-test baseline command with a fresh C: TMP root. Compare the full node-ID failure set to the recorded 20; any added, removed, or substituted name is RED.

- [ ] **Step 4: Commit and publish draft**

Run `git diff --check`, repository guard, commit the exact paths, push through the safe Git wrapper, create the draft PR with five labels, milestone, and bare base/head pins, then send the immutable head and test evidence to the independent reviewer.
