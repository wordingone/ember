# External Reference Ocean V0

Status: DISCOVERY DRAFT.

## Purpose

Ember already contains a large scattered ocean of external projects, papers, systems, and benchmark names. The baseline packet must treat that ocean as source material to absorb, pin, classify, and prune. A name that only makes sense with outside knowledge is a candidate baseline fragment until proven irrelevant.

## Current Public Scan

A narrowed machine scan of `<public-ember-local-mirror>` produced `fragments/external-refs-public-v0.jsonl` and `fragments/external-refs-public-summary-v0.json` with 12,877 rows after skipping receipts/checkpoints and files over 1 MiB.

High-volume or high-signal references include Qwen, MTP, GRPO, SFT, D3-Gym, Muon, FP8, QAT, ScienceAgentBench, BitNet, iGRPO, Kaggle, RLM, LoRA, Gemma, torchao, MLE-bench, Triton, Hugging Face, FineWeb, Codex, OpenAI, Hermes, and many GitHub-like project references. Public narrowed agent-loop counts include Codex 34, OpenAI 15, and Hermes 9 known-term hits.

This scan is intentionally over-inclusive. It contains false positives, generated artifacts, and repeated references. Its function is not to prove anything; its function is to prevent baseline amnesia.

## Required Classification

Each external reference promoted into `/baseline` must be classified as one of:

- direct external comparator;
- sample-efficiency comparator;
- training-efficiency comparator;
- architecture or kernel comparator;
- self-improvement or agent-loop comparator;
- local-control or proxy-only baseline;
- source-only context;
- false positive / excluded.

## Current Private Scan

The first broad scan of `<private-ember-local-checkout>` timed out before producing output because private dirty receipts and checkpoints are much larger. That has been converted into a solved scan-shape problem: the narrowed private scan produced `fragments/external-refs-private-v0.jsonl` and `fragments/external-refs-private-summary-v0.json` with 35,356 rows after skipping receipts/checkpoints and files over 1 MiB.

Private narrowed agent-loop counts include Anthropic 266, Codex 81, OpenAI 79, Claude Code 73, ClaudeCode 15, and Hermes 13 known-term hits. This confirms the private repo carries more dense agent/CLI baseline material and must not be treated as interchangeable with the public clean repo.

## Agent-Loop Addition

Codex, Claude Code, and Hermes-class systems are now explicit first-class baseline candidates. They belong to the self-improvement, goal-mode, ember-cli, and research-operator claim families. Any Ember claim in those families must either compare against them, cite why a same-budget comparison is impossible/unnecessary, or mark the claim incomplete.

## Current Verdict

NOT COMPLETE. The reference ocean is indexed enough to show that `/baseline` must include an absorption pipeline. It is not yet classified, sourced, or promoted into the public/private `/baseline` directories.