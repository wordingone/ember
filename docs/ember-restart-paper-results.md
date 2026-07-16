<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02C -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->
# Ember Restart Paper Result Boundary

## Claim status

No empirical capability claim is available for the corrected 3B shared-route
checkpoint. The immutable v3 input at
`bf20f05018991eb611b0623edd50a00ec30639da2f8ccae646f6962f152a2a2b`
has only two shared-text optimizer steps (2,048 observed tokens). Its
structural parameter counts are not a substitute for held-out benchmark
evidence.

The public `VERIFIED_NON_CLAIM_RAW_FORWARD` for
`ember-step2-raw-forward/1` generated one token decoded as `lev`. This is
execution-path evidence only: it has no benchmark score, capability, admission,
or sufficient-pretraining credit.

## Reporting rule

Any paper-facing table must source a row from the central admitted evaluation
manifest and retain checkpoint, benchmark/split, harness, protocol,
predictions, score-artifact, and verifier identities. Preflight, SELFTEST,
PREFLIGHT_ONLY, or hardcoded-FAILED records may document evaluator readiness
or a negative boundary; they cannot be rendered as a measured capability
result.

## Present unresolved matrix

The public frozen-evaluation matrix includes explicit non-execution records
for Terminal-Bench, browser/UI, structured tools, and files, plus
non-admissible protocol/scorer paths for the other requested families. BrowserGym fixture outcomes are `SELFTEST_ONLY_FIXTURE_BROWSER_OUTCOMES`; BFCL runtime is `RUNTIME_HELD_UNPINNED_DEPENDENCY_AND_LIVE_TOOL_NETWORK`. The
result surface is [`ember-restart-evaluation-results.md`](ember-restart-evaluation-results.md).