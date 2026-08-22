# A1 Lower-Bound-Only Supersession Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the append-only §4-A1 both-tiers-fail amendment that re-scopes A1 to a disclosed lower-bound-only arm without changing thresholds or creating a second authority.

**Architecture:** Add one closed JSON authority document bound to the frozen preregistration, thresholds, executed E8 receipts, and public adjudication. Add one independent contract test that reopens every in-repository binding and enforces the prohibited-claim booleans; no runtime consumer or threshold file changes.

**Tech Stack:** JSON, Python `unittest`, SHA-256, pytest.

**Spec:** `docs/spec/ember02-preregistration-v1.md` §4-A1 and §9.

## Global Constraints

- The frozen v1 preregistration is append-only and remains byte-unchanged.
- `docs/spec/ember02-preregistration-thresholds-v1.json` remains byte-unchanged.
- Trigger only on the executed both-tiers-fail R1-E8 evidence at source `24decc312c771ec0e9309882f24f2a3ba82ea156`.
- A1 receives no R2 funding and cannot carry dense-null, beaten-null, capability-credit, or result-credit claims.
- `NO_THRESHOLD_CHANGE` and `NO_NEW_PARALLEL_AUTHORITY` are explicit closed fields.

---

### Task 1: Freeze and test the superseding amendment

**Files:**
- Create: `tests/ember_restart_model/test_a1_lower_bound_amendment.py`
- Create: `docs/spec/ember02-a1-lower-bound-only-amendment-v2.json`

**Interfaces:**
- Consumes: raw SHA-256 of the frozen preregistration, thresholds, contract, liveness, parity, battery, and public closure comment identity.
- Produces: schema `ember02-a1-lower-bound-only-amendment/v2` with a closed decision envelope and no executable runtime authority.

- [ ] **Step 1: Write the failing contract test**

```python
def test_amendment_binds_frozen_authority_and_executed_trigger(self):
    amendment = json.loads(AMENDMENT.read_bytes())
    self.assertEqual(amendment["decision"]["arm_scope"], "LOWER_BOUND_ONLY")
    self.assertFalse(amendment["decision"]["r2_funding_allowed"])
    self.assertEqual(amendment["change_control"]["thresholds"], "NO_THRESHOLD_CHANGE")
```

- [ ] **Step 2: Run the focused test and verify RED**

Run through `scripts/owned_process.py` with `-p no:cacheprovider`.
Expected: FAIL because `docs/spec/ember02-a1-lower-bound-only-amendment-v2.json` does not exist.

- [ ] **Step 3: Add the minimal closed amendment JSON**

Include exact `supersedes`, `thresholds`, `trigger_evidence`, `decision`, `change_control`, `execution_boundary`, and `rollback` objects. Bind the preregistration pin `3d48d3870919bd04cec735f68d0fad45fcfae0b2` alongside raw SHA-256 `a671f81b02755178e67d0bcca5b0ec9c4d41650b6a1fd868f5e597b1aa3b3c51`.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `pytest -p no:cacheprovider tests/ember_restart_model/test_a1_lower_bound_amendment.py -q`
Expected: all assertions PASS.

- [ ] **Step 5: Run policy and whitespace verification**

Run the repository policy guard relevant to `docs/spec` plus `git diff --check`.
Expected: PASS with no generated identity change because the amendment is outside the training closure.

- [ ] **Step 6: Commit the frozen carrier**

```bash
git add docs/spec/ember02-a1-lower-bound-only-amendment-v2.json tests/ember_restart_model/test_a1_lower_bound_amendment.py docs/superpowers/plans/2026-08-22-a1-lower-bound-supersession.md
git commit -m "docs(ember-02): rescope failed A1 arm as lower bound"
```

### Task 2: Publish and gate the immutable carrier

**Files:**
- Create: `state/reports/issue1116-a1-lower-bound-pr-body.md` outside the committed carrier.

**Interfaces:**
- Consumes: Task 1 exact commit SHA and test receipt.
- Produces: draft PR linked non-closingly to #1116 for independent exact-head review.

- [ ] **Step 1: Build the PR body with exact claim boundaries**

State that the amendment records the preregistered result, changes no threshold, enables no runtime, grants no model/result/capability credit, and leaves #1116 open.

- [ ] **Step 2: Push the frozen branch and open a draft PR**

Use the safe Git/GitHub wrappers. Expected: draft PR whose base is public master `24decc312c771ec0e9309882f24f2a3ba82ea156`.

- [ ] **Step 3: Route exact head to the independent reviewer and wait for CI/review**

Do not amend the reviewed head without announcing the successor SHA. Merge only after independent PASS and all required checks are green.
