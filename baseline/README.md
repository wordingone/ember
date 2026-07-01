# Ember Ultimate SOTA Baseline Packet

Status: OVERALL INCOMPLETE PENDING OPERATOR ACCEPTANCE. This directory is the active `/baseline` artifact, but the goal is not complete until the strict verifier and explicit operator acceptance gates pass.
Created: 2026-06-29.
Target publication path: top-level `baseline/` in both `wordingone/ember` and `wordingone/ember-backup`.

## Purpose

This packet builds the outside ruler Ember must face before any field-level claim is allowed. It is a cited, data-backed, recreatable `/baseline` directory committed to the shared Ember branch in both public and private remotes.

## Current Verdict

OVERALL INCOMPLETE PENDING OPERATOR ACCEPTANCE.

Reasons:

- the strict completion verifier still requires explicit post-artifact operator acceptance;
- no agent may create or infer that acceptance;
- Ember has not beaten these baselines yet;
- the publication surface is now separately validated, but overall goal completion remains locked by `completion-lock.json` and `scripts/verify_completion.py`.

## Layout

- `anchors.md`: external anchor inventory.
- `claim-map-v0.md`: current Ember claim families mapped to external comparators.
- `4090-ceiling-v0.md`: single-4090 >=1B feasibility ceiling.
- `self-improvement-baseline-v0.md`: autonomous ML loop baseline protocol.
- `cli-goal-mode-baseline-v0.md`: CLI and goal-mode baseline protocol.
- `compute-governance-v0.md`: short-job, long-job, and no-recompute rules.
- `contracts/`: uncheatable X/Y/Z/T/C/B/V contracts.
- `protocols/`: locked evaluation protocol.
- `schemas/`: receipt and verdict schemas.
- `scripts/`: deterministic verification helpers, 4090 ceiling calculator, bounded 4090 throughput probe, 4090 ceiling validator, publication-surface validator, family contract audit, training-efficiency validator, data-efficiency validator, architecture/growth validator, self-improvement validator, local-agentic research validator, CLI runtime validator, goal-mode control validator, field-level threshold validator, source-ledger validator, manifest generator, external-reference extractor, and promotion-readiness checker.
- `line-endings/`: CRLF/LF policy and verifier notes.
- `reports/`: publication packet draft and public/private parity report.

## Recreate Or Verify

```powershell
python baseline\scripts\validate_sources.py --sources baseline\sources.jsonl --pretty
python baseline\scripts\check_line_endings.py --root baseline --mode fail-mixed
python baseline\scripts\validate_publication_surface.py --root baseline --out baseline\receipts\publication-surface-validation-2026-06-29.json
python baseline\scripts\verify_completion.py --root baseline --pretty
```

## Non-Substitution Rule

A BabyLM, Modded-NanoGPT, smoke, mock, CLI, goal-mode, 4090 ceiling, or publication-surface result proves only its own contract. No result in this packet transfers to another Ember claim family without its own locked protocol and verdict.
Benchmark/data readiness is mechanically checked by `scripts/validate_benchmark_data_readiness.py` with receipt `receipts/benchmark-data-readiness-2026-06-30.json`: it verifies pinned benchmark/data substrate, records the MLAgentBench CLRS executable smoke plus upstream and deterministic patch comparators, and preserves remaining MLE-bench/auth and Ember governed-trial gaps without treating readiness as an Ember win.

Prior external benchmark/access receipts from prior Ember work are now imported and classified by `scripts/validate_external_benchmark_receipts.py` with receipt `receipts/external-benchmark-import-validation-2026-06-30.json`. The import records three executed external/public/heldout delta receipts and three blocked/access-gap receipts; it proves benchmark plumbing/history exists, not an Ember win.

Owned-engine candidate evidence is recorded in `receipts/owned-engine-tool-loop-2026-06-30.json`: a bounded owned-checkpoint tool-loop run failed to complete the task, preserving negative evidence without granting an Ember win.

Architecture/growth receipt import is recorded in `receipts/growth-refutation-import-2026-06-30.json`; it summarizes existing growth-law GPU evidence and marks the growth claim unsatisfied pending matched v4 controls and enough seeds.

Owned-engine SFT/tool-loop evidence is recorded in `receipts/owned-engine-sft-tool-loop-validation-2026-06-30.json`: bounded training moved tool-call behavior but the heldout task still failed.

Owned-engine SFT repair-attempt evidence is recorded in receipts/owned-engine-sft-repair-attempts-validation-2026-06-30.json: v2-v6 tested large-count generalization, turnwise next-action supervision, normalized copy-contract runtime, compositional target-path copying, and live-observation copying. v5/v6 reached the correct COUNT observation of 470, but WRITE still failed to copy that live observation, so the next attempt must replace short SFT patching with a more reliable observation-copy mechanism before longer GPU jobs.
