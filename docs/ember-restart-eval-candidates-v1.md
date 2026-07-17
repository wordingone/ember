<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02C -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->
# Ember Restart External Evaluation Candidates v1

This is a source-identity inventory, not an executable scorecard. A candidate
becomes a frozen suite only after its dataset split, prompt/tool protocol,
scoring code, resource budget, and local receipt are pinned in the
checkpoint-bound manifest.

| Required family | Candidate source | Resolved source commit | Why it is included | Still required before scoring |
| --- | --- | --- | --- | --- |
| Terminal/file work | `harbor-framework/terminal-bench-2` | `2fd12b88aafdd04a52c298e3940bcb189f9766d6` | Source custody and strict freezer; current cache is 89/0/0 (records/digest-pinned images/offline-eligible tasks) | digest-pinned task images, `allow_internet=false`, and a bounded Harbor run receipt |
| Browser/UI | `ServiceNow/BrowserGym` | `9e779f087de9a65668b6974d11f9ce9816026e96` | Source identity plus repeatable read-only custody audit; no local runtime or frozen MiniWoB task bundle is claimed | environment snapshot, frozen task bundle, browser action protocol, and a bounded receipt |
| Audio | `THENIROCK/audiobench` | `0fc7fef2709c00ac1e2eb2b372ec4c56362bb8c6` | Source/procedural custody and bound scorer; arbitrary closed runs are refused | licensed local split, exact closed-run artifact hash, and checkpoint-bound predictions |
| Image/reasoning | `MMMU-Benchmark/MMMU` | `bc168a9119d986d7cdf1e07b1eeb96ed3e8f92fa` | Validation/image-input custody and deterministic scorer; no checkpoint-bound image score | permitted split, image preprocessing hash, answer normalization, and checkpoint predictions |
| SQL | `taoyds/spider` | `b7b5b8c890cd30e35427348bb9eb8c6d1350ca7c` | Source/split custody and deterministic scorer; no frozen database execution artifact | database snapshot hashes, execution sandbox, exact-match/execution scorer, and checkpoint predictions |
| Code | `evalplus/evalplus` | `26d6d00bb1fd0fa37f39c99d5290da67891d1c5e` | Frozen HumanEval+/MBPP+ task assets and deterministic SELFTEST adapter; no claim-bearing score | immutable code-sandbox runtime and checkpoint-generated code predictions |
| Mathematics | `HuggingFaceH4/MATH-500` | `2cd6fe926f1203a15d19f73c9a329cbe62b806fd` | Frozen 500-row split and deterministic scorer; CPU-only next local adapter, still PREFLIGHT_ONLY | checkpoint-generated predictions and a central-contract evidence receipt |

## Existing pinned text/code/math surface

The inherited frozen v1 suite remains the text/code anchor, with its harness
at `97a5e2c710e2b56b9dd48f367bb6fe87bbb2c176`. Its exact split hashes are in
`manifests/ember-restart-eval-precheckpoint-v1.json`. Its contamination
exclusions still apply. EvalPlus and MATH-500 are the next locally runnable
deterministic adapters, but their outputs remain SELFTEST/PREFLIGHT_ONLY until
real checkpoint inference and the central evidence gate bind them.

## Admission and execution

1. Niko supplies the owned checkpoint's immutable lineage manifest.
2. Vera resolves each candidate's final task/split and protocol hashes, then
   records a resource budget before materialization.
3. Each materialization and run is invoked through `disk_budget_runner.py`
   with C and B caps plus a receipt.
4. The contract validator must admit the checkpoint-bound manifest before any
   target score or comparator gap is reported.
