# Contract C1: Single-4090 >=1B Feasibility

Status: ENGINEERING_BASELINE_SURFACE_READY for `single_4090_ge_1b_foundation_ceiling`; full family completion still requires representative full-1B multi-layer long-run throughput evidence and dual-repo verifier PASS.

## Uncheatable Form

Build or run Ember 1B+ active/trainable-parameter training artifact `X_4090_1B` that reaches frozen capability target `Z_days_to_capability` within days-scale threshold `T` on one RTX 4090-class 24GB GPU, against strongest sourced theoretical/comparator ruler `Y_4090_1B` implemented as the engineering baseline surface in `engineering/4090-1b/`, preserving one-GPU compute, memory, optimizer, activation, precision, quantization, source/data, evaluation, energy, and replay constraints `C`, under compute budget `B`, verified by `baseline/scripts/validate_4090_ceiling.py`, `baseline/scripts/verify_completion.py`, and family receipts `V`, producing PASS, FAIL, or INVALID-RUN.

## Locked Defaults

- Days-scale default: <=14 calendar days.
- Hardware: one RTX 4090-class 24GB GPU.
- Parameter accounting: active trainable parameters must be >=1B; inactive sparse capacity and frozen parameters are reported separately.
- Compute estimate: `training_flops ~= 6 * active_parameters * trained_tokens`.
- Token-budget tiers: 5B, 10B, 20B, 30B, 50B tokens.
- Required sustained throughput for <=14 days: 24.80, 49.60, 99.21, 148.81, and 248.02 TFLOP/s respectively.
- From-scratch and pretraining-equivalent claims are separate lanes and cannot be interchanged.
- PyTorch is a reproducible reference path, not the automatic ceiling; native C++/CUDA/Triton/custom-kernel paths must be bounded, measured, or explicitly falsified before C1 can complete.

## Native C++/CUDA/Triton Ceiling

PyTorch is a reproducible reference path, not the automatic ceiling. C1 completion requires a native/lower-level ceiling analysis for one RTX 4090-class GPU: CUDA C++/CUTLASS-style kernels, Triton kernels, fused optimizer/loss/attention paths, or a measured explanation that the selected PyTorch path already reaches the relevant lower-level kernels for forward+backward+optimizer.

A C1 PASS cannot use framework overhead as the field ceiling. If Ember beats only the current PyTorch harness while a plausible native C++/CUDA/Triton path remains unbounded, the result is local progress, not the final 4090 ceiling baseline.

## Required Evidence

A valid run against this baseline must include:

## Engineering Implementation Surface

The theory map is implemented by:

- `engineering/4090-1b/environment.json`
- `engineering/4090-1b/configs/from_scratch_1b_4090.json`
- `engineering/4090-1b/configs/pretraining_equivalent_1b_4090.json`
- `engineering/4090-1b/train_1b_4090.py`
- `engineering/4090-1b/parse_receipts.py`
- `engineering/4090-1b/native_kernel_probe_4090.py`
- `engineering/4090-1b/README.md`

Dry-run evidence currently proves the surface is runnable and config-complete:

- `receipts/4090-engineering-from-scratch-dry-run.json`
- `receipts/4090-engineering-from-scratch-parse.json`
- `receipts/4090-engineering-pretraining-equivalent-dry-run.json`
- `receipts/4090-engineering-pretraining-equivalent-parse.json`

These receipts are not an Ember win and not overall `/baseline` completion. They prove that the theoretical ceiling has been converted into an inspectable engineering baseline with >=1B active/trainable parameter accounting, memory plan, throughput requirement, stop rule, and parser verdict.

Bounded governed GPU probe evidence also exists:

- `receipts/4090-governed-probe-from-scratch.json` and `receipts/4090-governed-probe-from-scratch-parse.json`.
- `receipts/4090-governed-probe-pretraining-equivalent.json` and `receipts/4090-governed-probe-pretraining-equivalent-parse.json`.

The governed probes execute real forward/backward optimizer steps on the local RTX 4090 at bounded probe shape and record telemetry, but they are not representative full-1B long-run throughput and cannot complete the family by themselves.

Full-config memory feasibility probes also exist:

- `receipts/4090-full-memory-probe-from-scratch.json` and `receipts/4090-full-memory-probe-from-scratch-parse.json`.
- `receipts/4090-full-memory-probe-pretraining-equivalent.json` and `receipts/4090-full-memory-probe-pretraining-equivalent-parse.json`.

The memory probes allocate the planned 1.027B-parameter bf16 weights, bf16 gradients, 8-bit optimizer-state estimate, activation-checkpoint estimate, and 2GB temporary/fragmentation margin on the local RTX 4090. Peak reserved memory was 11.6875GB against 23.9878GB device memory. This proves the C1 memory plan is allocation-feasible on the observed 4090, but it is still not representative full forward/backward throughput.

Full-shape block throughput probes also exist:

- `receipts/4090-full-shape-block-probe-from-scratch.json` and `receipts/4090-full-shape-block-probe-from-scratch-parse.json`.
- `receipts/4090-full-shape-block-probe-pretraining-equivalent.json` and `receipts/4090-full-shape-block-probe-pretraining-equivalent-parse.json`.

The block probes run a decoder block at the locked C1 shape: sequence length 2048, hidden size 2048, 16 heads, bf16, SDPA causal attention, forward/backward optimizer steps. Observed lower-bound block throughput was 7.32-7.73 TFLOP/s. This is representative block telemetry, not full 19-layer 1B long-run throughput.


Full-stack step probes also exist:

- `receipts/4090-full-stack-step-probe-from-scratch.json` and `receipts/4090-full-stack-step-probe-from-scratch-parse.json`.
- `receipts/4090-full-stack-step-probe-pretraining-equivalent.json` and `receipts/4090-full-stack-step-probe-pretraining-equivalent-parse.json`.

The full-stack probes execute all 19 configured transformer layers at sequence length 2048, hidden size 2048, 16 heads, bf16, activation checkpointing, SDPA causal attention, forward/backward, and AdamW optimizer step. They use a hidden-state surrogate loss, observed 27.98-28.48 lower-bound TFLOP/s, and reserve about 10.49GB. This is full-stack bounded telemetry, not a long-run language-model training receipt and not family completion.

Native kernel probe evidence also exists:

- `receipts/4090-native-kernel-probe-from-scratch.json` and `receipts/4090-native-kernel-probe-from-scratch-parse.json`.

The native probe records CUDA/Triton toolchain availability and compares PyTorch tuned matmul with a simple Triton GEMM at C1 transformer-relevant shapes. PyTorch measured about 138-155 TFLOP/s; simple Triton measured about 45-49 TFLOP/s with relative BF16 error below 0.5%. This bounds a native GEMM microbench only; it does not exhaust fused attention, backward, optimizer, or CUDA C++ paths.

A bounded native training-stack probe also exists: `receipts/4090-native-training-stack-probe-pretraining-equivalent.json` and `receipts/4090-native-training-stack-validation-2026-06-30.json`. It measures PyTorch/CUDA SDPA attention forward/backward, CUDA cross-entropy, and fused AdamW API behavior at C1-like shapes; it does not exhaust the full native transformer, Triton fused attention backward, residual/norm fusion, full 19-layer native long-run, or thermal/power stability surfaces.

## Required Evidence

- exact >=1B architecture/config and active/trainable/frozen parameter accounting;
- token budget, data mix, dedupe/contamination policy, and capability target frozen before execution;
- memory receipt for weights, gradients, optimizer/master state, activations, temporary buffers, dataloader staging, fragmentation margin, and evaluation overhead; current full-config allocation receipt covers weights, gradients, optimizer estimate, activation estimate, and margin, while dataloader/evaluation overhead still requires governed long-run receipt;
- throughput receipt at representative model shape, not only tiny sanity probes; current full-shape block receipts cover the locked block shape, while full multi-layer long-run throughput remains required;
- precision, quantization/QAT, activation checkpointing, optimizer compression/offload, kernel, sequence packing, compile/fusion settings, and native C++/CUDA/Triton ceiling analysis;
- wall-clock accounting for data prep, training, eval, checkpoint/restart, recovery, and packaging;
- energy accounting or explicit estimation method;
- PASS/FAIL/INVALID-RUN parser output.

## Falsifiers

The claim is invalid if:

- the model has fewer than 1B active/trainable parameters;
- days-scale is claimed from FLOP math without representative sustained throughput and memory receipts;
- a pretraining-equivalent result is reported as from-scratch training;
- inference-only, forward-only, draft-model, or distributed-infrastructure results are transferred to training without same-axis receipts;
- capability target or comparator threshold is chosen after seeing results;
- memory fit excludes activations, optimizer state, temporary buffers, or fragmentation margin;
- long-job compute is launched without stop rule, checkpoint/resume plan, expected information gain, and no-recompute justification;
- a PyTorch prototype result is treated as the absolute 4090 ceiling while native C++/CUDA/Triton/custom-kernel paths remain unbounded.

## Current Verdict

ENGINEERING_BASELINE_SURFACE_READY. The dry-run surface counts 1,027,764,224 active trainable parameters and parser PASS receipts exist for from-scratch and pretraining-equivalent lanes. This is still not a governed non-dry-run result, not an Ember win, and not overall `/baseline` completion.

Representative LM-loss probe evidence also exists:

- `receipts/4090-full-stack-lm-loss-probe-from-scratch.json` and `receipts/4090-full-stack-lm-loss-probe-from-scratch-parse.json`.
- `receipts/4090-full-stack-lm-loss-probe-pretraining-equivalent.json` and `receipts/4090-full-stack-lm-loss-probe-pretraining-equivalent-parse.json`.

These receipts execute the locked C1 full stack with token input, tied LM head, cross-entropy, backward, and AdamW. They remove the surrogate-loss limitation for bounded step telemetry, but still do not supply real training data, dedupe/contamination receipts, multi-step stability, checkpoint/resume behavior, or days-scale long-run throughput.

C1 throughput-gap validation now exists: `receipts/4090-training-throughput-gap-validation-2026-06-30.json`. The best current full-stack LM-loss measurement is below the locked <=14-day requirement, so C1 cannot complete until a replacement measured full-stack long-run or stronger native/lower-level ceiling receipt closes that gap without weakening the data, memory, evaluation, and replay constraints.

C1 real-data LM-loss probe evidence now exists: `receipts/4090-real-data-lm-loss-probe-from-scratch.json`, `receipts/4090-real-data-lm-loss-probe-pretraining-equivalent.json`, and `receipts/4090-real-data-lm-loss-validation-2026-06-30.json`. This closes only the random-token limitation for bounded LM-loss telemetry; it does not close multi-step stability, checkpoint/resume, dedupe/contamination, or long-run throughput.

C1 bounded checkpoint/resume evidence now exists: `receipts/4090-real-data-checkpoint-resume-probe-pretraining-equivalent.json` and `receipts/4090-checkpoint-resume-validation-2026-06-30.json`. This validates save/hash/reload/post-resume mechanics for a model+optimizer checkpoint only; long-run checkpoint cadence, recovery accounting, and days-scale throughput remain required.

C1 bounded checkpoint-cadence evidence now exists: `receipts/4090-real-data-checkpoint-cadence-probe-pretraining-equivalent.json` and `receipts/4090-checkpoint-cadence-validation-2026-06-30.json`. This validates repeated checkpoint save/hash/reload/delete mechanics with streamed real-token steps only; long-run checkpoint policy, recovery accounting, external evaluation, and days-scale throughput remain required.

C1 bounded eval-accounting evidence now exists: `receipts/4090-real-data-eval-accounting-probe-pretraining-equivalent.json` and `receipts/4090-eval-accounting-validation-2026-06-30.json`. This validates no-grad tied-LM-head eval timing/loss on streamed real-token windows only; full external evaluation, recovery accounting, data-hygiene PASS, and days-scale throughput remain required.

C1 bounded recovery-accounting evidence now exists: `receipts/4090-real-data-recovery-accounting-probe-pretraining-equivalent.json` and `receipts/4090-recovery-accounting-validation-2026-06-30.json`. This validates checkpoint recovery plus post-recovery streamed train/eval accounting only; long-run recovery policy, full external evaluation, data-hygiene PASS, and days-scale throughput remain required.

C1 bounded integrated policy evidence now exists: `receipts/4090-integrated-policy-probe-pretraining-equivalent.json` and `receipts/4090-integrated-policy-validation-2026-06-30.json`. This combines streamed real-token training, checkpoint cadence, eval accounting, and recovery accounting in one receipt; it preserves the throughput-overhead gap and remains below days-scale completion requirements.

C1 bounded multi-step stability evidence now exists: `receipts/4090-real-data-multistep-stability-probe-pretraining-equivalent.json` and `receipts/4090-multistep-stability-validation-2026-06-30.json`. This validates finite same-window real-token optimizer behavior only; full-data coverage, convergence, long-run throughput, and external eval remain required.

C1 bounded steady-state throughput evidence now exists: `receipts/4090-real-data-steady-state-throughput-probe-pretraining-equivalent.json` and `receipts/4090-steady-state-throughput-validation-2026-06-30.json`. This clears the locked TFLOP/s threshold only for a same-window 16-step probe; varied-data long-run throughput, dataloader overhead, checkpoint cadence, recovery, and evaluation accounting remain required.

C1 bounded varied-window throughput evidence now exists: `receipts/4090-real-data-varied-window-throughput-probe-pretraining-equivalent.json` and `receipts/4090-varied-window-throughput-validation-2026-06-30.json`. This clears the locked TFLOP/s threshold for 16 unique real-token shard windows only; dataloader-inclusive long-run throughput, checkpoint cadence, recovery, external evaluation, and hygiene PASS receipts remain required.

C1 bounded streamed-window throughput evidence now exists: `receipts/4090-real-data-streamed-window-throughput-probe-pretraining-equivalent.json` and `receipts/4090-streamed-window-throughput-validation-2026-06-30.json`. A longer 128-window streamed evidence packet now also exists at `receipts/4090-real-data-streamed-128-window-throughput-probe-pretraining-equivalent.json`, validated by `receipts/4090-streamed-128-window-throughput-validation-2026-06-30.json`: it executes 128 unique real-token windows at the full 1B stack shape with per-step loader timing included, records 25.009s elapsed, and measures a 64.638 TFLOP/s lower bound against the 50.980 TFLOP/s requirement. This strengthens dataloader-inclusive throughput evidence only; full-shard long-run throughput, checkpoint cadence, recovery, external evaluation, and hygiene PASS receipts remain required.

C1 bounded power-sampled throughput evidence now exists: `receipts/4090-real-data-streamed-128-window-power-sampled-probe-pretraining-equivalent.json`, `receipts/4090-power-sampled-128-window-throughput-2026-06-30.json`, and `receipts/4090-power-sampled-128-window-validation-2026-06-30.json`. It executes 128 unique real-token windows at the full 1B stack with per-step loader timing and nvidia-smi power sampling, measures a 64.551 TFLOP/s lower bound against the 50.980 TFLOP/s requirement, and estimates 9,898.822 joules / 2.750 Wh for the bounded child-wall-clock probe. This is not days-scale long-run training, not full-run energy accounting for data prep/eval/recovery/packaging, and not family completion.

C1 policy-amortized train/checkpoint/eval/recovery/power evidence now exists: `receipts/4090-policy-amortized-256-window-probe-pretraining-equivalent.json`, `receipts/4090-policy-amortized-256-window-power-2026-06-30.json`, and `receipts/4090-policy-amortized-256-window-validation-2026-06-30.json`. It executes 256 streamed real-token train windows, two checkpoint-cadence events at 128-step intervals, four eval windows, one recovery cycle, and nvidia-smi power sampling. It measures 36.084 TFLOP/s lower bound against the 50.980 TFLOP/s requirement and 21,311.846 joules / 5.920 Wh around the child wall clock. This is stronger policy-overhead evidence, but it is explicitly below the locked days-scale requirement and therefore preserves the C1 non-completion gate.

C1 policy-optimized train/checkpoint/eval/recovery/power evidence now exists: `receipts/4090-policy-optimized-1024-window-probe-pretraining-equivalent.json`, `receipts/4090-policy-optimized-1024-window-power-2026-06-30.json`, and `receipts/4090-policy-optimized-1024-window-validation-2026-06-30.json`. It executes 1024 streamed real-token train windows, one checkpoint-cadence event at the 1024-step boundary, four eval windows, one recovery cycle, and nvidia-smi power sampling. It measures 57.390 TFLOP/s lower bound against the 50.980 TFLOP/s requirement and 80,386.935 joules / 22.330 Wh around the child wall clock. This closes the bounded policy-overhead throughput gap for this 1024-window pretraining-equivalent probe only; it is still not days-scale long-run training, not full-run energy accounting, not a data-hygiene PASS, and not family completion.

C1 data-governance evidence also exists: `receipts/4090-data-governance-2026-06-30.json` and `receipts/4090-data-governance-validation-2026-06-30.json`. The receipt records a pinned 6.973B-content-token substrate, tokenizer/shard hashes, C1 vocab compatibility, pretraining-equivalent token-floor readiness, and a from-scratch 10B-token shortfall. It keeps dedupe, contamination, dataloader-inclusive long-run throughput, checkpoint cadence, and recovery/evaluation accounting as explicit gaps.

C1 data-hygiene audit evidence also exists: `receipts/4090-data-hygiene-audit-2026-06-30.json` and `receipts/4090-data-hygiene-validation-2026-06-30.json`. The audit accepts only a blocking-gap verdict until corpus-wide exact dedupe, near-duplicate/MinHash dedupe, eval contamination, and threshold-policy PASS receipts replace it.

Exact token-document dedupe now has PASS evidence via `receipts/4090-exact-dedupe-scan-2026-06-30.json` and `receipts/4090-exact-dedupe-validation-2026-06-30.json`: 4,236,458 documents scanned, zero exact duplicate documents. Near-duplicate/MinHash and eval contamination receipts remain required.

Data-hygiene threshold policy is locked in `receipts/4090-data-hygiene-policy-thresholds-2026-06-30.json` with validation receipt `receipts/4090-data-hygiene-policy-validation-2026-06-30.json`. The policy does not replace the near-duplicate or eval contamination scans.

Local heldout exact 32-token and 16-token contamination now have PASS evidence via `receipts/4090-local-heldout-contamination-scan-2026-06-30.json`, `receipts/4090-local-heldout-contamination-validation-2026-06-30.json`, `receipts/4090-local-heldout-16gram-contamination-scan-2026-06-30.json`, and `receipts/4090-local-heldout-16gram-contamination-validation-2026-06-30.json`. Available eval-text normalized-span evidence also exists via `receipts/4090-eval-text-inventory-normalized-span-scan-2026-06-30.json` and `receipts/4090-eval-text-inventory-validation-2026-06-30.json`: it scans 17,912 normalized 200-character local heldout windows against checked-in local training JSONL with zero hits and records imported external benchmark receipts as metadata-only raw-text gaps. C1 post-filter near-duplicate challenge evidence now exists: `receipts/4090-targeted-filtered-near-duplicate-sample-2026-06-30.json`, validated by `receipts/4090-targeted-filtered-near-duplicate-sample-validation-2026-06-30.json`. It rescans all 4,236,458 pinned documents, applies all 1,668 targeted exclusions before sampling, draws a deterministic 50,000-document challenge sample from the remaining 4,234,790-document view, and still finds 25 above-threshold crossing pairs with max exact Jaccard 0.955778. Deterministic challenge remediation now exists at `receipts/4090-targeted-filtered-challenge-remediation-2026-06-30.json`, validated by `receipts/4090-targeted-filtered-challenge-remediation-validation-2026-06-30.json`: it clusters those 25 crossing pairs into 14 components, identifies 25 additional challenge-sample exclusions covering 38,244 tokens, and verifies zero overlap with the existing 1,668-document targeted manifest. This proves the targeted filtered view is not enough for a C1 near-duplicate PASS; all-pairs/full-corpus remediation and pass validation remain required.

C1 cumulative near-duplicate v2 evidence now exists: `fragments/c1-near-duplicate-cumulative-exclusions-v2-2026-06-30.jsonl`, `receipts/4090-near-duplicate-cumulative-exclusion-manifest-v2-2026-06-30.json`, `receipts/4090-cumulative-filtered-corpus-view-v2-2026-06-30.json`, and `receipts/4090-cumulative-filtered-near-duplicate-sample-v2-2026-06-30.json`, with validation receipts for each. It combines the 1,668 targeted-cluster exclusions with the 25 validated post-filter challenge exclusions into 1,693 excluded documents covering a 2,988,224-token floor, materializes a replayable v2 filtered view with 4,234,765 remaining documents / 6,974,880,534 token floor, then reruns the deterministic 50,000-document challenge sample. The v2 challenge still finds 25 above-threshold crossing pairs with max exact Jaccard 0.927525, so it is stronger problem-finding evidence, not a C1 near-duplicate PASS; all-pairs/full-corpus remediation and pass validation remain required.

C1 cumulative near-duplicate v3 evidence now also exists: `fragments/c1-near-duplicate-cumulative-exclusions-v3-2026-06-30.jsonl`, `receipts/4090-cumulative-filtered-challenge-remediation-v3-2026-06-30.json`, `receipts/4090-near-duplicate-cumulative-exclusion-manifest-v3-2026-06-30.json`, `receipts/4090-cumulative-filtered-corpus-view-v3-2026-06-30.json`, and `receipts/4090-cumulative-filtered-near-duplicate-sample-v3-2026-06-30.json`, with validation receipts for each. It adds 16 exclusions from the v2 challenge crossings to the prior 1,693-document cumulative manifest, yielding 1,709 exclusions covering a 3,012,037-token floor, and materializes a replayable v3 filtered view with 4,234,749 remaining documents / 6,974,856,721 token floor. The v3 deterministic 50,000-document challenge still finds 10 above-threshold crossing pairs with max exact Jaccard 0.912172. This is measurable remediation progress, not a C1 near-duplicate PASS; all-pairs/full-corpus remediation and pass validation remain required.

C1 cumulative near-duplicate v4 evidence now exists: `fragments/c1-near-duplicate-cumulative-exclusions-v4-2026-06-30.jsonl`, `receipts/4090-cumulative-filtered-challenge-remediation-v4-2026-06-30.json`, `receipts/4090-near-duplicate-cumulative-exclusion-manifest-v4-2026-06-30.json`, `receipts/4090-cumulative-filtered-corpus-view-v4-2026-06-30.json`, and `receipts/4090-cumulative-filtered-near-duplicate-sample-v4-2026-06-30.json`, with validation receipts for each. It adds 10 exclusions from the v3 challenge crossings to the prior 1,709-document cumulative manifest, yielding 1,719 exclusions covering a 3,026,203-token floor, and materializes a replayable v4 filtered view with 4,234,739 remaining documents / 6,974,842,555 token floor. The v4 deterministic 50,000-document challenge sample found zero above-threshold crossing pairs and max exact Jaccard 0.799711. This clears this bounded challenge sample only; it is still not an all-pairs/full-corpus near-duplicate PASS, and full-corpus remediation/pass validation remain required.
C1 cumulative near-duplicate v4 full-document LSH bucket-census evidence now also exists: `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-2026-06-30.json` and `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-validation-2026-06-30.json`. It scans all 3,806,884 eligible v4-filtered documents for selected MinHash band 0, records 3,723,151 buckets, 28,337 collision buckets, 112,070 collision document memberships, and a max bucket size of 2,994. This is corpus-scale collision-pressure evidence for one of 16 bands only; it is still not full-band coverage, not exact all-pairs Jaccard adjudication, not a C1 near-duplicate PASS, and not overall baseline completion.
C1 cumulative near-duplicate v4 full-document LSH bucket-census coverage has expanded to bands 0, 4, and 8: `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-2026-06-30.json`, `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band4-2026-06-30.json`, and `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band8-2026-06-30.json`, with validation receipts for each. Each scanned all 3,806,884 eligible v4-filtered documents. Band 4 records 3,726,985 buckets / 28,392 collision buckets / max bucket size 2,290; band 8 records 3,724,494 buckets / 28,593 collision buckets / max bucket size 1,296. Together this is 3 of 16 selected-band collision-pressure coverage only; it is still not full-band coverage, not exact all-pairs Jaccard adjudication, not a C1 near-duplicate PASS, and not overall baseline completion.
C1 cumulative near-duplicate v4 full-document LSH bucket-census coverage has expanded again to bands 0, 4, 8, 12, 16, and 20. The new receipts are `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band12-2026-06-30.json`, `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band16-2026-06-30.json`, and `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band20-2026-06-30.json`, with validation receipts for each. Each scanned all 3,806,884 eligible v4-filtered documents. Band 12 records 3,718,516 buckets / 28,324 collision buckets / max bucket size 3,766; band 16 records 3,722,972 buckets / 28,684 collision buckets / max bucket size 2,142; band 20 records 3,716,406 buckets / 29,149 collision buckets / max bucket size 2,392. Together this is 6 of 16 selected-band collision-pressure coverage only; it is still not full-band coverage, not exact all-pairs Jaccard adjudication, not a C1 near-duplicate PASS, and not overall baseline completion.
C1 cumulative near-duplicate v4 full-document LSH bucket-census coverage has expanded to 9 of 16 bands: 0, 4, 8, 12, 16, 20, 24, 28, and 32. The new receipts are `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band24-2026-06-30.json`, `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band28-2026-06-30.json`, and `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band32-2026-06-30.json`, with validation receipts for each. Each scanned all 3,806,884 eligible v4-filtered documents. Band 24 records 3,728,419 buckets / 28,292 collision buckets / max bucket size 1,761; band 28 records 3,725,146 buckets / 28,764 collision buckets / max bucket size 2,147; band 32 records 3,722,249 buckets / 28,691 collision buckets / max bucket size 2,856. Together this is 9 of 16 selected-band collision-pressure coverage only; it is still not full-band coverage, not exact all-pairs Jaccard adjudication, not a C1 near-duplicate PASS, and not overall baseline completion.
C1 cumulative near-duplicate v4 full-document LSH bucket-census coverage now spans all 16 selected bands: 0, 4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48, 52, 56, and 60. The final-band receipts are `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band36-2026-06-30.json`, `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band40-2026-06-30.json`, `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band44-2026-06-30.json`, `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band48-2026-06-30.json`, `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band52-2026-06-30.json`, `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band56-2026-06-30.json`, and `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band60-2026-06-30.json`, with validation receipts for each. Each scanned all 3,806,884 eligible v4-filtered documents. Bands 36/40/44/48/52/56/60 respectively record 28,850 / 29,705 / 29,276 / 28,289 / 28,356 / 29,178 / 29,320 collision buckets and max bucket sizes 1,318 / 4,898 / 630 / 5,741 / 1,019 / 2,389 / 907. Across all 16 selected bands this records 460,200 observed collision buckets and max observed bucket size 5,741. This completes selected-band LSH census coverage only; exact candidate/Jaccard adjudication, remediation as needed, a replacement C1 near-duplicate PASS, and overall baseline completion remain open.
C1 cumulative near-duplicate v4 exact-adjudication preparation has begun with a materialized band-48 LSH collision-candidate index: `fragments/c1-cumulative-filtered-lsh-candidate-index-v4-band48-2026-07-01.jsonl`, receipt `receipts/4090-cumulative-filtered-lsh-candidate-index-v4-band48-2026-07-01.json`, and validation `receipts/4090-cumulative-filtered-lsh-candidate-index-v4-band48-validation-2026-07-01.json`. It covers all 3,806,884 eligible v4-filtered documents for selected band 48 and writes 28,289 collision buckets / 113,574 document memberships / 20,991,666 candidate-pair upper bound before deduplication, with max bucket size 5,741. This is a concrete candidate surface for exact Jaccard adjudication; it is not exact adjudication, not full 16-band candidate-index coverage, not a C1 near-duplicate PASS, and not overall baseline completion.





This does not replace the full external eval-suite contamination scan or token-shard/full-corpus normalized-span scan.

C1 bounded near-duplicate/MinHash sample evidence now exists: `receipts/4090-near-duplicate-minhash-sample-2026-06-30.json` and `receipts/4090-near-duplicate-minhash-sample-validation-2026-06-30.json`. The deterministic 50,000-document sample was drawn from 3,808,603 eligible documents across the full 4,236,458-document pinned shard stream, found 25 above-threshold crossing pairs at the 0.80 Jaccard policy threshold, and observed max exact Jaccard 0.914169. This is problem-finding evidence, not a pass: full-corpus near-duplicate remediation and a corpus-wide PASS receipt remain required.

C1 near-duplicate sample remediation evidence now exists: `receipts/4090-near-duplicate-sample-remediation-2026-06-30.json` and `receipts/4090-near-duplicate-sample-remediation-validation-2026-06-30.json`. The packet clusters the 25 above-threshold sample crossing pairs into 4 connected components, keeps the lowest deterministic document per component, and identifies 24 sample documents / 38,772 tokens for exclusion. This is sample remediation only; full-corpus MinHash scanning, full-corpus exclusion materialization, and post-remediation PASS validation remain required.

C1 targeted near-duplicate expansion evidence now exists: `receipts/4090-near-duplicate-targeted-expansion-2026-06-30.json` and `receipts/4090-near-duplicate-targeted-expansion-validation-2026-06-30.json`. The run rescanned all 4,236,458 pinned documents, compared 3,808,603 eligible documents to the 4 discovered cluster representatives, and materialized 1,668 exclusion documents covering at least 2,949,980 tokens. This expands the discovered clusters across the full corpus, but it is still not an all-pairs full-corpus near-duplicate PASS.

C1 targeted near-duplicate exclusion materialization now exists: `fragments/c1-near-duplicate-targeted-exclusions-2026-06-30.jsonl`, `receipts/4090-near-duplicate-targeted-exclusion-manifest-2026-06-30.json`, and `receipts/4090-near-duplicate-targeted-exclusion-manifest-validation-2026-06-30.json`. The manifest records 1,668 hash-addressed exclusions covering a 2,949,980-token floor for the discovered clusters only. A targeted filtered-corpus view now also exists at `receipts/4090-targeted-filtered-corpus-view-2026-06-30.json`, validated by `receipts/4090-targeted-filtered-corpus-view-validation-2026-06-30.json`: it applies those exclusions as a replayable view over the pinned document stream, leaving 4,234,790 documents and a 6,974,918,778-token floor. This is still not an all-pairs near-duplicate PASS and not a binary shard rewrite.

C1 cumulative near-duplicate v4 band-48 candidate-index exact adjudication has begun with `receipts/4090-cumulative-filtered-lsh-candidate-index-v4-band48-adjudication-partial25-2026-07-01.json`, validated by `receipts/4090-cumulative-filtered-lsh-candidate-index-v4-band48-adjudication-partial25-validation-2026-07-01.json`. The first 25 materialized band-48 collision buckets contain 75 candidate pairs, 74 exact Jaccard computations plus 1 size-pruned impossible crossing, 17 above-threshold crossing pairs, and max exact Jaccard 0.970803. A deterministic remediation packet `receipts/4090-cumulative-filtered-lsh-candidate-index-v4-band48-adjudication-partial25-remediation-2026-07-01.json` clusters those crossings into 12 components and 14 proposed exclusions with zero overlap against the existing v4 cumulative manifest. This is problem-finding and partial remediation evidence only; full band-48 adjudication, remaining candidate coverage, follow-up manifest materialization, reruns, C1 PASS receipts, and overall baseline completion remain open.

C1 cumulative near-duplicate v5 materialization now exists from the partial band-48 remediation: `fragments/c1-near-duplicate-cumulative-exclusions-v5-2026-07-01.jsonl`, `receipts/4090-near-duplicate-cumulative-exclusion-manifest-v5-2026-07-01.json`, `receipts/4090-near-duplicate-cumulative-exclusion-manifest-v5-validation-2026-07-01.json`, `receipts/4090-cumulative-filtered-corpus-view-v5-2026-07-01.json`, and `receipts/4090-cumulative-filtered-corpus-view-v5-validation-2026-07-01.json`. Required v5 totals are 1,733 cumulative exclusions / 3,039,393 excluded-token floor, leaving 4,234,725 documents / 6,974,829,365 content-token floor. This receipt family is required evidence for the current C1 surface but is not sufficient for completion: full band-48 adjudication, full 16-band exact adjudication, C1 near-duplicate PASS receipts, external eval-contamination PASS receipts, and overall baseline completion remain required.

C1 v5/v6 near-duplicate evidence is now required for the current single-4090 surface. The v5 band-48 candidate index and partial exact adjudication receipts show that applying v5 did not clear the high-pressure band: the first 25 v5 rows still contain 18 above-threshold crossing pairs, max exact Jaccard 0.975309. The v6 manifest/view applies 9 additional deterministic exclusions, yielding 1,742 cumulative exclusions and leaving 4,234,716 documents / 6,974,817,925 content-token floor. This remains a blocking-gap state: full band-48 adjudication, full 16-band exact adjudication, replacement near-duplicate PASS receipts, external eval-contamination PASS receipts, and overall verifier PASS remain required.

C1 v6/v7 near-duplicate evidence is now required for the current single-4090 surface. The v6 band-48 candidate index and partial exact adjudication receipts show the first 25 v6 rows still contain 3 above-threshold crossing pairs, max exact Jaccard 0.978495. The v7 manifest/view applies 3 additional deterministic exclusions, yielding 1,745 cumulative exclusions and leaving 4,234,713 documents / 6,974,813,421 content-token floor. This remains a blocking-gap state: full band-48 adjudication, full 16-band exact adjudication, replacement near-duplicate PASS receipts, external eval-contamination PASS receipts, and overall verifier PASS remain required.
C1 v7/v8 near-duplicate evidence is now required for the current single-4090 surface. The v7 band-48 candidate index and partial exact adjudication receipts show the first 25 v7 rows still contain 3 above-threshold crossing pairs, max exact Jaccard 0.952118. The v8 manifest/view applies 2 additional deterministic exclusions, yielding 1,747 cumulative exclusions and leaving 4,234,711 documents / 6,974,810,145 content-token floor. This remains a blocking-gap state: full band-48 adjudication, full 16-band exact adjudication, replacement near-duplicate PASS receipts, external eval-contamination PASS receipts, and overall verifier PASS remain required.

C1 v8/v9 near-duplicate evidence is now required for the current single-4090 surface. The v8 band-48 candidate index and windowed exact adjudication receipts cover candidate-index rows 0-49, finding 23 above-threshold crossing pairs with max exact Jaccard 0.985562. The v9 manifest/view applies 19 additional deterministic exclusions, yielding 1,766 cumulative exclusions and leaving 4,234,692 documents / 6,974,781,662 content-token floor. This remains a blocking-gap state: full band-48 adjudication, full 16-band exact adjudication, replacement near-duplicate PASS receipts, external eval-contamination PASS receipts, and overall verifier PASS remain required.

C1 v9/v10 near-duplicate evidence is now required for the current single-4090 surface. The v9 band-48 candidate index and windowed exact adjudication receipts cover candidate-index rows 0-99, finding 94 above-threshold crossing pairs across 30 connected components with max exact Jaccard 0.988074. The v10 manifest/view applies 48 additional deterministic exclusions, yielding 1,814 cumulative exclusions and leaving 4,234,644 documents / 6,974,712,860 content-token floor. This remains a blocking-gap state: full band-48 adjudication, full 16-band exact adjudication, replacement near-duplicate PASS receipts, external eval-contamination PASS receipts, and overall verifier PASS remain required.

C1 v10/v11 near-duplicate evidence is now required for the current single-4090 surface. The v10 band-48 candidate index and windowed exact adjudication receipts cover candidate-index rows 0-124, finding 59 above-threshold crossing pairs across 25 connected components with max exact Jaccard 0.997024. The v11 manifest/view applies 40 additional deterministic exclusions, yielding 1,854 cumulative exclusions and leaving 4,234,604 documents / 6,974,647,576 content-token floor. This remains a blocking-gap state: full band-48 adjudication, full 16-band exact adjudication, replacement near-duplicate PASS receipts, external eval-contamination PASS receipts, and overall verifier PASS remain required.

C1 v11/v12 near-duplicate evidence is now required for the current single-4090 surface. The v11 band-48 candidate index and windowed exact adjudication receipts cover refreshed candidate-index rows 0-149, finding 56 above-threshold crossing pairs across 33 connected components with max exact Jaccard 0.997024. The v12 manifest/view applies 38 additional deterministic exclusions, yielding 1,892 cumulative exclusions and leaving 4,234,566 documents / 6,974,618,184 content-token floor. This remains a blocking-gap state: full band-48 adjudication, full 16-band exact adjudication, replacement near-duplicate PASS receipts, external eval-contamination PASS receipts, and overall verifier PASS remain required.

C1 v12/v13 near-duplicate evidence is now required for the current single-4090 surface. The v12 band-48 candidate index and windowed exact adjudication receipts cover refreshed candidate-index rows 0-174, finding 36 above-threshold crossing pairs across 28 connected components with max exact Jaccard 0.979872. The v13 manifest/view applies 32 additional deterministic exclusions, yielding 1,924 cumulative exclusions and leaving 4,234,534 documents / 6,974,572,823 content-token floor. This remains a blocking-gap state: full band-48 adjudication, full 16-band exact adjudication, replacement near-duplicate PASS receipts, external eval-contamination PASS receipts, and overall verifier PASS remain required.

C1 v14/v15 near-duplicate evidence is now required for the current single-4090 surface. The v14 band-48 candidate index and windowed exact adjudication receipts cover refreshed candidate-index rows 0-224, finding 85 above-threshold crossing pairs across 18 connected components with max exact Jaccard 0.99239. The v15 manifest/view applies 26 additional deterministic exclusions, yielding 1,978 cumulative exclusions and leaving 4,234,480 documents / 6,974,504,671 content-token floor. This remains a blocking-gap state: full band-48 adjudication, full 16-band exact adjudication, replacement near-duplicate PASS receipts, external eval-contamination PASS receipts, and overall verifier PASS remain required.
