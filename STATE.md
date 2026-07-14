# Ember identity and artifact state

This file resolves object identity. It does not establish model birth,
capability, lineage admissibility, or goal completion. `GOAL.md` is the highest
amendable authority; `CONTINUITY.md` records the current work cursor.

An object is **current and addressable** only when it has a row below. Every
other legacy config, receipt, checkpoint copy, branch artifact, or benchmark
payload is historical evidence by default and has no execution or capability
authority. Adding a current object requires an authority-conservation update
with an exact identity, `goal_id`, and `next_executed_outcome`.

## Exact terminology

- **Ember** is the conserved totality: creation primitive, sovereign foundation
  intelligence, organism, body, and general local AI laboratory. It does not
  mean whichever backend happens to answer through ember-cli.
- **Ember model** is a sufficiently trained, clean-lineage milestone containing
  at least 3,000,000,000 total unique learned parameters and native text,
  image, audio, reasoning, and structured tool use. No current checkpoint is an
  Ember model under this definition.
- **Research candidate** is an authorized at-least-3B network that already
  satisfies the required native architecture/capability surface but has not yet
  earned milestone evidence. EMBER-02 permits a candidate only through the
  executable `ember-owned-rung-v1` contract; architecture or allocation alone
  earns no model or capability credit.
- **Historical artifact** is preserved evidence with execution denied. It may
  inform research but cannot become a model milestone or target-lineage seed.
- **Borrowed reference** is an external learned model or result admitted only
  to an explicit frozen comparison seat. It receives no Ember capability or
  lineage credit.
- **Parameter count** means total unique learned parameters. State-dict sums,
  trainable parameters, and episode-active parameters are reported separately
  when relevant and never substituted for total unique learned parameters.
- **Trained capacity** is parameter state demonstrably updated by an admissible
  training run with exact token, data, optimizer, and checkpoint bindings.
  Allocated, copied, widened, or untrained parameters are not trained capacity.
- **Active capacity** is the exact parameter subset participating in an
  episode. It does not reduce the model's total-parameter identity.
- **Checkpoint** is immutable model bytes plus architecture, tokenizer, data,
  token-count, optimizer, parentage, and hash bindings. A path or model label
  alone is not a checkpoint identity.
- **Backend** is the process and protocol serving a bound checkpoint. Backend,
  body, and model identities are separate.
- **Benchmark result** is an executed score bound to exact task data, harness,
  checkpoint or non-model object, and comparator. A download, freeze, smoke,
  selftest, or harness is not a benchmark result.
- **Body** is ember-cli and its tool, observation, interruption, memory, and
  operator-control surface. Harness capability is not model capability.
- **Organism** is the bound model-body-memory-tool-learning system whose state
  transitions are inspectable and causal.
- **Laboratory** is the local system that creates, studies, evaluates, evolves,
  and operates clean-genesis intelligences without permanent hosted cognition.

## Current identity resolver

All capability-credit cells are `none`: these rows classify evidence and do
not promote any current artifact into an Ember model.

| id | object_type | canonical_identity | artifact_class | parameter_count | trained_tokens | backend | capability_credit | evidence |
|---|---|---|---|---:|---:|---|---|---|
| cbase-seed-step610 | checkpoint | sha256:1ec99451d0c1446441db76f2d86d9b9e3f866941ca6f5a1c72f74182d08f5bdb | historical_only | 466658304 | 9994240 | none | none | receipts/v0-live-20260623T105829Z.json and receipts/cbase-grow-rung/cbase-grow-measured-flops-20260710T005231Z.json |
| cbase-rung0-step730 | checkpoint | sha256:ac43445b15e22cdc733d78855a34a49b35a241ff32289d427a9668e309697f0d | historical_only | 718316544 | 11960320 | none | none | receipts/cbase-grow-rung/cbase-grow-measured-flops-20260710T005231Z.json |
| cbase-rung1-step730 | checkpoint | sha256:74a5b1d4c21b38fb4a8037bd079c2073516dee9a242849fc33fda191f4fa0f3b | historical_only | 1221633024 | 11960320 | none | none | receipts/cbase-grow-rung/cbase-grow-rung1-live-20260703T155711Z.json |
| cbase-rung1-step766 | checkpoint | sha256:58e8e98916823941381d9cf71cf3725148aa61cf106e8b46c4fa96e0c5e4659b | historical_only | 1221633024 | 12550144 | disconnected_owned_server | none | receipts/cbase-grow-rung/cbase-grow-rung1-live-20260703T155711Z.json |
| w1-dense-restart-step50 | checkpoint | sha256:8055a9f4b67711b8f1103dcf76228c5f303ba6d6170af17243b17b7c5289ea54 | historical_only | 1221633024 | 819200 | lm_eval_cpu | none | receipts/ember-c-scale/w1-baseline-replay-closure-20260711T025650Z-redacted-edition.json |
| cbase-rung2-transient | transient_growth_artifact | receipt-sha256:b8a424bb81a3576c5a3acc040cefa8d45cc34c32302122b22232a397c38c423d | historical_only | 2195497984 | 12550144 | none | none | receipts/grow-op-verify-20260708T060841Z.json; no stabilized post-grow checkpoint |
| unified-v0-source-prototype | architecture_prototype | source:scripts/ember_model_v0_multimodal.py | research_prototype | not_instantiated | 0 | none | none | scripts/ember_model_v0_multimodal.py and scripts/train_multimodal_v0.py; separate from trained cbase |
| ember-cli-body | body_runtime | source:tools/ember-cli | research_prototype | not_applicable | not_applicable | qwen_reference_default | none | tools/ember-cli; body capability is not neural capability |
| cbase-openai-backend | backend | source:scripts/serve_cbase_openai.py@rung1-step766 | historical_only | 1123329024 | 12550144 | inactive_port_8083 | none | scripts/serve_cbase_openai.py; MTP keys are dropped and the legacy cbase-2.2b label is inaccurate |
| qwen36-reference-backend | backend | model:qwen3.6-27b-q4_k_m:26895998464 | borrowed_reference | 26895998464 | unknown | llama_cpp_reference | none | tools/ember-cli/src/model-config.ts; explicit reference seat only |
| arc-owned-step50-result | benchmark_result | receipt-sha256:32852248a61f6fc3d705f18f2e8f1ceb88e976ef477aaac5eb2a2d8dc4142c07 | historical_only | 1221633024 | 819200 | lm_eval_cpu | none | ARC-Challenge 1172 samples, acc 0.222696; receipts/legb-scorer/legb-scorer-evaluator-run-arc-full-20260711T080900Z.json |
| hellaswag-owned-step50-result | benchmark_result | receipt-sha256:105c9f8ba1c089849e12e33a03e258c882fd06f206e0479ac1dd0bd7d667e46e | historical_only | 1221633024 | 819200 | lm_eval_cpu | none | HellaSwag 10042 samples, acc 0.260008, falsifier absent; receipts/legb-scorer/legb-scorer-evaluator-run-hella-full-20260711T095448Z.json |
| math500-qwen-reference-result | benchmark_result | receipt-sha256:137e3e4c3c8098ed496c9aac3603001fa01a8869b01dc940e241efff50f3f918 | borrowed_reference | 26895998464 | unknown | llama_cpp_reference | none | borrowed Qwen MATH-500 result; receipts/eval-reference/math500-proof/Qwen3.6-27B-Q4_K_M.gguf/results_2026-07-09T23-03-49.194110.json |
| kaggle-emotion-classifier-result | benchmark_result | receipt-sha256:9abba7c0dd0f832998e8de99159835680819cb072f44f8e9746c24b5a5c333d3 | historical_only | not_applicable | not_applicable | sklearn_naive_bayes | none | receipts/ember-mvp/trained-external-heldout-wheel-20260618/arm-c-trained-benchmark-20260618T152822Z.json; not an Ember-model result |
| d3-code-artifact-result | benchmark_result | receipt-sha256:ac3be7d4bb8064de9d1722335a41367d847d66919279c6a8b370014d0275f383 | historical_only | not_applicable | not_applicable | external_code_artifact_loop | none | representative D3-Gym A/B/C/Deleted program result; not owned-model capability |
| arcade-random-smoke-result | benchmark_result | receipt-sha256:931b3a608c6bf1911bb0ffaa56797014d8ea9a38be475297df9864d6c631a237 | historical_only | not_applicable | not_applicable | random_control | none | 25 games at 200 steps, zero wins; not the preregistered 1000-step floor |
| ember-target | model_target | uninstantiated:ember-owned-30-35b-unified-sparse | target | 30000000001 | 0 | owned | none | GOAL.md; target identity only, no model claim |
| ember-owned-rung-v1-contract | admission_contract | source:scripts/ember_restart/contract.py@8b0d684e9e289aa66a7c18217b71bfaecab1e642 | research_prototype | not_applicable | not_applicable | local_fail_closed_validator | none | docs/ember-restart/integration-contract-v1.md and scripts/ember_restart/contract.py; candidate/admission boundary only |

The seven-task frozen evaluation suite is custody, not seven results. Only the
ARC-Challenge and HellaSwag result rows above are located full owned-checkpoint
runs. MMLU-Pro, GSM8K, MATH-500, HumanEval+, and MBPP remain unexecuted or
blocked for the owned checkpoint at their required full boundaries. GPQA is
pin-blocked. Terminal-Bench and the broader image, audio, tool, agent, UI, and
world-model obligations remain outstanding; no missing result is converted
into completion by this resolver.

## Conserved benchmark obligation resolver

- **OPERATOR_MANDATE_2026-07-09:** SWE-Bench Pro; FrontierCode Diamond;
  GDPval-AA; GDPpdf; Blueprint-Bench 2; AutomationBench; OSWorld-Verified;
  Legal Agent Benchmark; Humanity's Last Exam; Terminal-Bench 2.1.
- **ADDITIONAL_DIRECT_RECOVERED:** ARC-AGI 1; ARC-AGI 2; ARC-AGI 3. These
  establish thirteen directly recovered names.
- **OPERATOR_RECOLLECTION_UNRESOLVED:** at least fifteen direct requests; at
  least two exact names remain unrecovered and outstanding, not guessed.
- **FROZEN_GENERAL_SUITE:** MMLU-Pro; GSM8K; MATH-500; ARC-Challenge;
  HumanEval+; MBPP; HellaSwag; GPQA-Diamond.
- **RESEARCH_AGENTIC_CUSTODY:** D3-Gym; ScienceAgentBench; RE-Bench;
  PaperBench; MLE-bench; MLAgentBench; CORE-Bench; AI-Scientist nanoGPT-lite.
- **WORLD_CODE_TRANSFER_CUSTODY:** LiveCodeBench; SWE-bench/SWE-Bench Pro;
  IFC/building-data; Atari; ARC-AGI 1/2/3.
- **TOOL_COMPUTER_USE_CUSTODY:** AutomationBench; Terminal-Bench 2.1;
  OSWorld-Verified; GAIA; WebArena; BFCL; ToolBench.
- **SPECIALIZED_AND_FALLBACK_CUSTODY:** FrontierCode Diamond; GDPval-AA;
  GDPpdf; Blueprint-Bench 2; Legal Agent Benchmark; Humanity's Last Exam;
  SciReplicate-Bench; ResearchBench.

This is a greater-than-thirty named universe with heterogeneous provenance;
it is not a claim that every name was directly requested. No member of the
ten-name mandate has a located admissible owned-model execution. Historical
ARC/Hella results, borrowed references, and harness/proxy work satisfy none of
those ten obligations.

## Hash-bound external classifications for protected controls

These files predate EMBER-00 and cannot safely carry an in-file authority
object: two are checksum manifests that must remain byte-identical, one is an
empty schedule array, and one is a legacy control-path object. The exact hashes
below deny their execution without mutating or reinterpreting their formats.
A byte change invalidates the classification.

| path | artifact_class | execution_authority | goal_id | next_executed_outcome | sha256 |
|---|---|---|---|---|---|
| configs/nck-baseline/nck-invariants.json | historical_only | denied | EMBER-00 | EMBER-01 clean 3B custody and identity spine | ba192cd69ab53fcf78d6903c097eee2a62d2ece072054eb1b05411eb81021519 |
| configs/nck-c10.json | historical_only | denied | EMBER-00 | EMBER-01 clean 3B custody and identity spine | a764f1a74e6ca695a584fef37e946f0b283969708821e440a74dc59d42e11b34 |
| configs/nck-invariants.json | historical_only | denied | EMBER-00 | EMBER-01 clean 3B custody and identity spine | ba192cd69ab53fcf78d6903c097eee2a62d2ece072054eb1b05411eb81021519 |
| configs/nck-schedule.json | historical_only | denied | EMBER-00 | EMBER-01 clean 3B custody and identity spine | 4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945 |

## State conclusion

The current truthful category is a fragmented research program, substantial
body/tooling system, historical sub-3B checkpoint lineages, separate
multimodal source prototype, explicit borrowed reference backend, and bounded
benchmark evidence. No row is an admissible Ember model, integrated organism,
or completed local AI laboratory. The next executable outcome is EMBER-02's
first sufficiently pretrained clean-genesis 3B Ember.
