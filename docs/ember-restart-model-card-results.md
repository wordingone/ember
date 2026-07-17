<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02C -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->
# Ember Restart Model-Card Result Boundary

## Current checkpoint input

The available corrected checkpoint input is the shared-route v3 manifest
`bf20f05018991eb611b0623edd50a00ec30639da2f8ccae646f6962f152a2a2b`.
It records 3,839,161,856 allocated/unique/trainable/served parameters,
1,020,589,568 active shared-route parameters, global step 2, and 2,048
observed shared-text tokens.

This is structural bootstrap-mechanics evidence only. A
`VERIFIED_NON_CLAIM_RAW_FORWARD` for `ember-step2-raw-forward/1` generated one
token decoded as `lev`; it is execution-path evidence, not a frozen-suite
result. There is no frozen-suite score, admission, or sufficient-pretraining
finding, and that raw forward has no benchmark score or capability credit.
Image, audio, reasoning, and structured-tool specialists are untrained.

## Evaluation coverage disclosure

Text, image, audio, reasoning, code, mathematics, SQL, files, browser/UI,
Terminal-Bench, and structured-tools all have public protocol or custody
records. Their current dispositions are explicit rather than silently
omitted. In particular, Terminal-Bench has no eligible locally pinned
image/network-safe task subset; BrowserGym MiniWoB, BFCL, and SWE-bench Lite
have no locally pinned runtime; BFCL has only a private frozen static task set, which remains `PREFLIGHT_ONLY`. They therefore
have no target score.

The authoritative renderer-facing record is
[`ember-restart-evaluation-results.md`](ember-restart-evaluation-results.md). MMLU-Pro
strict custody is bound to scorer bytes, the pinned license-card artifact, and a
derived protocol, but remains preflight-only until canonical checkpoint
predictions exist. HellaSwag has a deterministic scorer but its frozen labels are
withheld; ARC-Challenge and GSM8K are likewise preflight-only. No score is
inferred from these descriptors.
The MATH-500 revision `2cd6fe926f1203a15d19f73c9a329cbe62b806fd` is custody-materialized as a 500-row MIT-licensed frozen suite (card SHA-256 `561724c0c751b31828bf8c2f5c7ffc20dc92deb804657c86d9f07a99e8100fd9`) with disposition `FROZEN_MATH500_TASKS_NO_CHECKPOINT_BOUND_PREDICTIONS`. BrowserGym source commit/tree/license is custody-bound, but its runtime and frozen MiniWoB task set remain absent. MMMU validation now also has a 900-row same-byte image-input digest artifact with disposition `FROZEN_MMMU_IMAGE_INPUTS_NO_CHECKPOINT_BOUND_PREDICTIONS`. None has checkpoint-bound predictions or a capability score.
