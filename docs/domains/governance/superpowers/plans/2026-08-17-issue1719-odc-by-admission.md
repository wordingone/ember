# #1719 ODC-By Dataset-Card Admission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Canonicalize only the exact normalized (lowercased) Hugging Face dataset-card token `odc-by` to the already-admissible SPDX value `ODC-By-1.0`, while retaining the exact reopened README declaration gate.

**Architecture:** Extend the existing closed `_HF_DATASET_CARD_LICENSES` map by one entry. Reuse the existing connector, path, raw-hash, front-matter, and three-way license equality checks; add no new parser, evidence route, or receipt field.

**Tech Stack:** Python 3.12, `unittest`, existing `text_lab_corpus.py` authority adapter.

## Global Constraints

- Exact source base: `80b34e5ef5e87b17ef5f11e8a7a716f28896bd4b`.
- Production scope is one map entry in `tools/ember-restart-3b/text_lab_corpus.py`.
- Preserve the existing uniform lowercase-before-lookup rule for every closed-map entry; accept normalized `odc-by` but add no punctuation or alias normalization.
- The root `README.md` bytes, connector license, and evidence declaration must independently converge on `ODC-By-1.0`.
- Do not mint tranche4d or claim corpus admission, byte movement, training, sufficient pretraining, or issue closure.

---

### Task 1: Add the exact ODC-By dataset-card token

**Files:**
- Modify through canonical remint only: `data/ember-restart-3b/owned-text-lab-input-identity-v2.json`
- Modify through canonical remint only: `data/ember-restart-3b/text-lab-authority-index-v1.json`
- Modify: `tests/ember_restart_model/domain-governance/test_text_lab_corpus.py`
- Modify: `tools/ember-restart-3b/text_lab_corpus.py`

**Interfaces:**
- Consumes: `adapt_connector_receipt(receipt: dict, evidence: dict) -> dict` and the existing exact `hf_fetch` receipt/evidence contract.
- Produces: `_HF_DATASET_CARD_LICENSES["odc-by"] == "ODC-By-1.0"`; no new public function or schema.

- [ ] **Step 1: Write the positive failing test**

Add `ConnectorReceiptAdapterTests.test_adapts_exact_odc_by_hf_dataset_card_license`. Build a two-file `hf_fetch` receipt whose reopened `README.md` is exactly:

```python
card_bytes = b"---\nlicense: odc-by\n---\n\n# Dataset\n"
```

Set the connector license and `_hf_dataset_card_evidence(..., declared_spdx="ODC-By-1.0")` to `ODC-By-1.0`. Assert the returned row and L4 receipt both retain `ODC-By-1.0` and the exact evidence object.

- [ ] **Step 2: Write the independent-declaration negative regression**

Add `ConnectorReceiptAdapterTests.test_rejects_odc_by_claim_without_exact_readme_declaration`. For each README token `apache-2.0`, `odc_by`, and `odc-by-1.0`, build the same `hf_fetch` receipt with connector/evidence claims `ODC-By-1.0` and assert `adapt_connector_receipt` raises `ValueError` matching `dataset card`.

- [ ] **Step 3: Run RED**

Run:

```text
bash tools/run-python-hidden.sh tests/ember_restart_model/domain-governance/test_text_lab_corpus.py ConnectorReceiptAdapterTests.test_adapts_exact_odc_by_hf_dataset_card_license ConnectorReceiptAdapterTests.test_rejects_odc_by_claim_without_exact_readme_declaration
```

Expected: two tests run; the positive fails because `odc-by` is absent from the closed map, while the negative regression passes.

- [ ] **Step 4: Implement the minimal production change**

Add exactly this one entry to `_HF_DATASET_CARD_LICENSES`:

```python
"odc-by": "ODC-By-1.0",
```

- [ ] **Step 5: Canonically remint governed source-hash pins**

Run `tools/ember-restart-3b/remint_text_lab_input_identity.py --write`, which alone may update `data/ember-restart-3b/owned-text-lab-input-identity-v2.json` and the downstream pin in `data/ember-restart-3b/text-lab-authority-index-v1.json`. Hand-editing either governed JSON file is forbidden. Then run the same tool with `--check` and require exit 0 with all live code-file pins matching.

- [ ] **Step 6: Run GREEN and focused regressions**

Run the two selectors from Step 3, then the full `ConnectorReceiptAdapterTests` class, then the full `tests.ember_restart_model.test_text_lab_corpus` module. All must pass with no warnings or errors.

- [ ] **Step 7: Verify and freeze the packet**

Compile both Python files from source without writing bytecode, run `git diff --check`, run the repository authority guard, hash every changed path, and request independent exact-byte review. Commit only after that review passes.
