# Architecture Growth Keystone SOTA Contract V1

Status: BASELINE_COMPLETE for the `architecture_growth_keystone_sota` family only.
Claim family: `architecture_growth_keystone_sota`.
Access date: 2026-06-29.

This contract locks the architecture/growth/keystone comparator surface for Ember. It does not claim Ember has beaten the ruler, and it does not complete the overall `/baseline`.

## Uncheatable Form

Build or run Ember artifact `X` that beats fixed-size, scratch, random-growth, iso-FLOP, and same-axis external architecture/kernel comparator `Y` on capability, loss, efficiency, preserved-functionality, or deletion-test metric `Z` by threshold `T`, while preserving budget, data, hardware, evaluation, transfer-scope, and ablation constraints `C`, under declared budget `B`, verified by command/protocol `V`, producing verdict `PASS`, `FAIL`, or `INVALID-RUN`.

## Locked Comparator Lanes Y

The baseline has four lanes. A future Ember result must name the lane before execution and may not transfer evidence across lanes without a separate same-axis receipt.

### Lane AG-GROWTH-DELETION

Comparator: fixed-size, scratch, random-growth, and iso-FLOP controls.

Controls: Ember keystone, delayed saturation, function-preserving growth, and growth-law claims.

Threshold: Ember must beat all matched controls on the locked capability/loss/efficiency metric and must lose the claimed gain when the mechanism is deleted or randomized. If deletion does not remove the gain, the architecture claim is invalid even if the main run improved.

### Lane AG-ATTENTION-MEMORY-RETRIEVAL

Comparator: same-axis attention, memory, retrieval, and sub-quadratic mechanisms relevant to Ember's claimed bottleneck.

Controls: claims that an attention, memory, retrieval, or state mechanism improves training quality, throughput, memory, or long-context behavior.

Threshold: Ember must beat the same-task baseline at equal data/compute/hardware while preserving quality. Inference-only or forward-only wins are not accepted for training claims unless a forward+backward receipt on the selected model path proves the transfer.

### Lane AG-DEEPSEEK-INFERENCE-TRANSFER

Comparator: `deepseek-deepspec-dspark` and `deepseek-open-infra-index` source rows.

Controls: DSpark/DeepSpec speculative-decoding/draft-model work plus DeepSeek open infrastructure candidates such as DeepGEMM, DeepEP, FlashMLA, DualPipe, 3FS, TileKernels, and related serving/data-pipeline systems.

Threshold: Ember may cite these as external architecture/kernel context, sampler/draft-model baselines, or rejection thresholds only on the same published axis. They cannot prove training speed, sample efficiency, 4090 >=1B feasibility, or keystone growth without same-axis measurement.

### Lane AG-LOWBIT-KERNEL-TRAINING

Comparator: `bitnet` source row and any stronger current low-bit/quantized-training successor discovered before final overall completion.

Controls: low-bit architecture, QAT, optimizer/state compression, precision-path, and kernel claims that might affect local training feasibility.

Threshold: Ember must show preserved quality at equal or better training compute/memory on the selected task. A memory-only, inference-only, or model-format-only result is insufficient unless it includes full training-step or pretraining-equivalent evidence.

## Metric Z

A valid architecture/growth run must report the lane-specific bundle:

- model/config and component enabled/disabled;
- matched fixed-size/scratch/random-growth/iso-FLOP controls where growth is claimed;
- deletion or randomization arm for the claimed mechanism;
- loss/capability score, throughput, memory, wall-clock, and token budget;
- hardware, precision, optimizer, sequence length, batch/global batch, and data manifest;
- whether the measured path is inference-only, forward-only, forward+backward, optimizer-only, draft-model training, or full foundation-model train step;
- parser command and receipt path.

## Constraints C

A valid architecture/growth claim must preserve:

- equal budget, data, hardware, and evaluation across arms;
- source pins and access dates;
- deletion-test causality for the claimed mechanism;
- no inference-to-training transfer without same-axis measurement;
- no forward-only kernel claim for full training speed;
- no distributed/MoE/storage claim for the single-4090 dense baseline unless it removes a measured local bottleneck without hidden hardware;
- no smoke-only, static-only, source-ledger-only, or docs-only completion;
- LF-only tracked baseline files;
- parser-readable PASS, FAIL, or INVALID-RUN receipt;
- public/private `/baseline` parity before any overall completion claim.

## Budget B

Short jobs may validate parser shape, source rows, local kernel availability, ablation plumbing, line endings, and receipt generation.

A long architecture/growth comparison must have a compute-spend packet before launch, naming lane, expected information gain, maximum GPU/CPU hours, stop rule, checkpoint/resume plan, deletion/randomization arms, energy/power method where claimed, and post-run parser. External inference/kernels are cited instead of recomputed unless same-axis normalization or local bottleneck proof requires measurement.

## Verifier V

Family verifier:

```powershell
python baseline\scripts\validate_architecture_growth.py --root baseline --out baseline\receipts\architecture-growth-validation-2026-06-29.json
```

Overall verifier remains:

```powershell
python baseline\scripts\verify_completion.py --root baseline --pretty
```

The family verifier passes only when this contract, transfer protocol, source ledger, and completion lock agree on all lanes, scope limits, deletion-test rules, transfer rejection, budget, verifier, and falsifiers.

## Falsifiers

The architecture/growth claim is downgraded or invalid if:

- deletion or randomization does not remove the claimed gain;
- fixed-size, scratch, random-growth, or iso-FLOP controls match or beat Ember;
- the result transfers an inference, serving, forward-only, or distributed-system win into a training/growth claim without same-axis evidence;
- low-bit or kernel evidence preserves memory but loses quality or lacks full training-step measurement;
- threshold or selected metric changes after seeing results;
- parser cannot reproduce the verdict from receipts;
- hidden compute, untracked data, or post-hoc threshold changes are found.

## Completion Boundary For This File

This family is complete when `baseline/scripts/validate_architecture_growth.py` emits `ARCHITECTURE_GROWTH_BASELINE_COMPLETE` and `completion-lock.json` references that receipt for `architecture_growth_keystone_sota`.

This file's completion does not complete the overall baseline.