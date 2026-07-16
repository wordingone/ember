<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02C -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->
# Ember Restart Evaluation Results

This surface may render only the output of
`scripts/ember_restart_eval_result_surface.py`. That renderer labels an
evaluation as **MEASURED CAPABILITY** only after the central admission contract
has independently admitted the exact receipt; every other record is **NOT
CLAIM-BEARING**.

## Current disposition

A corrected v3 shared-route checkpoint input exists at manifest
`bf20f05018991eb611b0623edd50a00ec30639da2f8ccae646f6962f152a2a2b`:
3,839,161,856 allocated/unique/trainable/served parameters, 1,020,589,568
active parameters, global step 2, and 2,048 observed shared-text tokens. It is
structural bootstrap-mechanics evidence only. Specialists remain untrained;
there is no sufficient-pretraining, capability, or admission claim.

One exact execution-path record is now public: `VERIFIED_NON_CLAIM_RAW_FORWARD`
for `ember-step2-raw-forward/1` generated one greedy token decoded as `lev`
from this checkpoint. It is a bounded raw-forward record, not the frozen
local-text suite: it carries no benchmark score, capability, admission, or
sufficient-pretraining credit. No frozen-suite canonical prediction envelope or
score has been emitted. Historical v2 snapshots remain bootstrap/raw-forward
evidence only and are not corrected-rung capability evidence.

Frozen external reasoning protocols are ready but have no checkpoint-bound predictions:
ARC-Challenge and MMLU-Pro each have byte-bound parquet custody and deterministic
canonical-envelope scorers. Their outputs remain `PREFLIGHT_ONLY` with a failed
criterion until a conforming checkpoint prediction envelope is produced. HellaSwag
is explicitly held at `NOT_EXECUTABLE_NO_FROZEN_LABELS`; its frozen test split
withholds labels, so no score is inferred or fabricated.
The public MMLU-Pro descriptor additionally requires the exact scorer-adapter
bytes and a protocol derived from version, frozen references, license-card bytes,
and adapter identity; it remains `NOT_EXECUTABLE_LICENSE_CARD_HASH_MISSING` until
that exact license-card artifact is custody-bound.

MATH-500, MMLU-Pro, and static BFCL strict freeze manifests now derive protocol identity from exact scorer bytes plus frozen split/reference and license/version identity; valid-hex caller substitutions are rejected. These remain preflight-only and do not create checkpoint-bound scores.

## Frozen-matrix coverage and current limits

Every requested family is tracked below. A frozen source, scorer self-test, or
preflight record is not a checkpoint-bound score.

| Family | Frozen evaluation boundary | Current result state |
| --- | --- | --- |
| Text / reasoning | ARC-Challenge, MMLU-Pro, GSM8K, and MATH-500 byte-bound task custody and deterministic scoring | No canonical checkpoint predictions or score |
| Code | HumanEval+ and MBPP+ frozen tasks with EvalPlus adapter self-tests | No pinned code-sandbox runtime or checkpoint predictions |
| Terminal | Terminal-Bench 2 source pin | `PREFLIGHT_ONLY_NO_ELIGIBLE_OFFLINE_DIGEST_PINNED_TASK`: no digest-pinned, network-disabled task image is eligible |
| SQL | Spider source/split custody and deterministic scorer pin | No frozen gold/database execution artifact or checkpoint predictions |
| Files | SWE-bench source custody | No frozen repository execution environment or checkpoint predictions |
| Browser/UI | BrowserGym/MiniWoB source pin | No local pinned BrowserGym runtime or frozen MiniWoB task bundle |
| Image | MMMU validation custody and scorer pin | No checkpoint-bound multimodal predictions |
| Audio | AudioBench custody and bound scorer pin | No checkpoint-bound audio predictions |
| Structured tools | BFCL static task custody and preflight scorer | No pinned live tool harness or checkpoint predictions |

These visible failure and preflight states are intentionally non-admissible and
must not be summarized as native capability coverage.
## Required result record

Before adding any result, preserve the checkpoint manifest hash, evaluator
commit, benchmark version/split, harness and protocol hashes, raw predictions,
score artifact, resource receipt, variance, and comparator identity. The
completion-certificate validator rejects a record that omits honest unresolved
gaps or inflates a preflight into a measured result.
