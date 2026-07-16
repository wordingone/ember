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
| Terminal | `harbor-framework/terminal-bench-2` | `2fd12b88aafdd04a52c298e3940bcb189f9766d6` | Real command-line task outcomes | no eligible pinned image/network-safe local task; fixture-only validator remains non-admissible |
| Code | `evalplus/evalplus` | `26d6d00bb1fd0fa37f39c99d5290da67891d1c5e` | HumanEval+ and MBPP+ task outcomes | digest-pinned offline code sandbox; the mutable upstream Docker tag is forbidden |
| Mathematics | frozen local MATH-500 exact scorer | `local-v1` | Deterministic exact-answer reasoning check | canonical checkpoint predictions on the frozen split |
| SQL | `taoyds/spider` | `b7b5b8c890cd30e35427348bb9eb8c6d1350ca7c` | Executable text-to-SQL evaluation | database snapshot hashes and canonical checkpoint predictions |
| Files | `SWE-bench/SWE-bench` | not materialized | Repository/file repair tasks | licensed pinned SWE-bench Lite release, offline runtime, image digest, canonical patches |
| Browser/UI | `ServiceNow/BrowserGym` | `9e779f087de9a65668b6974d11f9ce9816026e96` | Reproducible browser task environment | no local pinned runtime or frozen MiniWoB tasks; fixture validator is non-admissible |
| Structured tools | `ShishirPatil/gorilla` BFCL | `6ea57973c7a6097fd7c5915698c54c17c5b1b6c8` | Local function-call correctness | private frozen static tasks plus a canonical-prediction scorer are `PREFLIGHT_ONLY`; no local pinned BFCL runtime |
| Audio | `audiollms/audiobench` | `85dcdb88c41e6ebb2bcb3ce19b15d061dfef9dba` | Audio-language evaluation families | licensed local splits, raw-audio preprocessing hash, deterministic scorer |
| Image/reasoning | `MMMU-Benchmark/MMMU` | `bc168a9119d986d7cdf1e07b1eeb96ed3e8f92fa` | Expert multimodal understanding and reasoning | permitted split, image preprocessing hash, answer normalization |

## Existing pinned text/code surface

The inherited frozen v1 suite remains the text/code anchor, with its harness
at `97a5e2c710e2b56b9dd48f367bb6fe87bbb2c176`. Its exact split hashes are in
`manifests/ember-restart-eval-precheckpoint-v1.json`. Its contamination
exclusions still apply; it cannot substitute for the missing native families.

## Admission and execution

1. Vera selects an immutable completed owned checkpoint manifest and anchors its declared shards before evaluation.
2. Vera resolves each candidate's final task/split and protocol hashes, then
   records a resource budget before materialization.
3. Each materialization and run is invoked through `disk_budget_runner.py`
   with C and B caps plus a receipt.
4. The contract validator must admit the checkpoint-bound manifest before any
   target score or comparator gap is reported.
