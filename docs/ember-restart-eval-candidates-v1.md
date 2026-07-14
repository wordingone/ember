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
| Terminal/file work | `harbor-framework/terminal-bench-2` | `2fd12b88aafdd04a52c298e3940bcb189f9766d6` | Real command-line task outcomes | task subset, Harbor protocol, container/image hashes, resource cap |
| Browser/UI | `ServiceNow/BrowserGym` | `9e779f087de9a65668b6974d11f9ce9816026e96` | Reproducible browser task environment | benchmark choice, environment snapshot, browser action protocol |
| Audio | `audiollms/audiobench` | `85dcdb88c41e6ebb2bcb3ce19b15d061dfef9dba` | Audio-language evaluation families | licensed local splits, raw-audio preprocessing hash, deterministic scorer |
| Image/reasoning | `MMMU-Benchmark/MMMU` | `bc168a9119d986d7cdf1e07b1eeb96ed3e8f92fa` | Expert multimodal understanding and reasoning | permitted split, image preprocessing hash, answer normalization |
| SQL | `taoyds/spider` | `b7b5b8c890cd30e35427348bb9eb8c6d1350ca7c` | Executable text-to-SQL evaluation | database snapshot hashes, execution sandbox, exact-match/execution scorer |

## Existing pinned text/code surface

The inherited frozen v1 suite remains the text/code anchor, with its harness
at `97a5e2c710e2b56b9dd48f367bb6fe87bbb2c176`. Its exact split hashes are in
`manifests/ember-restart-eval-precheckpoint-v1.json`. Its contamination
exclusions still apply; it cannot substitute for the missing native families.

## Admission and execution

1. Niko supplies the owned checkpoint's immutable lineage manifest.
2. Vera resolves each candidate's final task/split and protocol hashes, then
   records a resource budget before materialization.
3. Each materialization and run is invoked through `disk_budget_runner.py`
   with C and B caps plus a receipt.
4. The contract validator must admit the checkpoint-bound manifest before any
   target score or comparator gap is reported.
