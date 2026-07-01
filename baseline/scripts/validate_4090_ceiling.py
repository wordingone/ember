#!/usr/bin/env python3
"""Validate the single-RTX-4090 >=1B ceiling baseline family."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQUIRED_REPORT_TEXT = [
    "Status: ENGINEERING_BASELINE_SURFACE_READY for `single_4090_ge_1b_foundation_ceiling`",
    "5B-20B tokens",
    "30B tokens is the aggressive practical frontier",
    "50B-token run is an extreme best-case ceiling",
    "Memory Feasibility Stack",
    "Precision, Quantization, And Kernel Stack",
    "From-Scratch Path",
    "Pretraining-Equivalent Path",
    "Capability Target Floor",
    "ENGINEERING_BASELINE_SURFACE_READY",
    "not overall `/baseline` completion",
    "Native C++/CUDA/Triton Ceiling",
    "PyTorch is a reproducible reference path, not the automatic ceiling",
]

REQUIRED_CONTRACT_TEXT = [
    "Status: ENGINEERING_BASELINE_SURFACE_READY for `single_4090_ge_1b_foundation_ceiling`",
    "Build or run Ember 1B+ active/trainable-parameter training artifact",
    "Required sustained throughput for <=14 days",
    "From-scratch and pretraining-equivalent claims are separate lanes",
    "Required Evidence",
    "Falsifiers",
    "ENGINEERING_BASELINE_SURFACE_READY",
    "Native C++/CUDA/Triton Ceiling",
]

REQUIRED_SOURCES = {
    "nvidia-rtx-4090",
    "chinchilla",
    "mlcommons-algoperf",
    "pytorch-sdpa-flashattention",
    "pytorch-activation-checkpointing",
    "bitsandbytes-8bit-optimizers",
    "bitnet",
    "deepseek-deepspec-dspark",
    "deepseek-open-infra-index",
    "nvidia-cutlass",
    "triton-language",
}

REQUIRED_RECEIPTS = [
    "receipts/4090-ceiling-calculation-2026-06-29.json",
    "receipts/4090-throughput-probe-2026-06-29.json",
    "receipts/4090-engineering-from-scratch-dry-run.json",
    "receipts/4090-engineering-from-scratch-parse.json",
    "receipts/4090-engineering-pretraining-equivalent-dry-run.json",
    "receipts/4090-engineering-pretraining-equivalent-parse.json",
    "receipts/4090-governed-probe-from-scratch.json",
    "receipts/4090-governed-probe-from-scratch-parse.json",
    "receipts/4090-governed-probe-pretraining-equivalent.json",
    "receipts/4090-governed-probe-pretraining-equivalent-parse.json",
    "receipts/4090-full-memory-probe-from-scratch.json",
    "receipts/4090-full-memory-probe-from-scratch-parse.json",
    "receipts/4090-full-memory-probe-pretraining-equivalent.json",
    "receipts/4090-full-memory-probe-pretraining-equivalent-parse.json",
    "receipts/4090-full-shape-block-probe-from-scratch.json",
    "receipts/4090-full-shape-block-probe-from-scratch-parse.json",
    "receipts/4090-full-shape-block-probe-pretraining-equivalent.json",
    "receipts/4090-full-shape-block-probe-pretraining-equivalent-parse.json",
    "receipts/4090-full-stack-step-probe-from-scratch.json",
    "receipts/4090-full-stack-step-probe-from-scratch-parse.json",
    "receipts/4090-full-stack-step-probe-pretraining-equivalent.json",
    "receipts/4090-full-stack-step-probe-pretraining-equivalent-parse.json",
    "receipts/4090-full-stack-lm-loss-probe-from-scratch.json",
    "receipts/4090-full-stack-lm-loss-probe-from-scratch-parse.json",
    "receipts/4090-full-stack-lm-loss-probe-pretraining-equivalent.json",
    "receipts/4090-full-stack-lm-loss-probe-pretraining-equivalent-parse.json",
    "receipts/4090-training-throughput-gap-validation-2026-06-30.json",
    "receipts/4090-real-data-lm-loss-probe-from-scratch.json",
    "receipts/4090-real-data-lm-loss-probe-pretraining-equivalent.json",
    "receipts/4090-real-data-lm-loss-validation-2026-06-30.json",
    "receipts/4090-real-data-checkpoint-resume-probe-pretraining-equivalent.json",
    "receipts/4090-checkpoint-resume-validation-2026-06-30.json",
    "receipts/4090-real-data-multistep-stability-probe-pretraining-equivalent.json",
    "receipts/4090-multistep-stability-validation-2026-06-30.json",
    "receipts/4090-real-data-steady-state-throughput-probe-pretraining-equivalent.json",
    "receipts/4090-steady-state-throughput-validation-2026-06-30.json",
    "receipts/4090-real-data-varied-window-throughput-probe-pretraining-equivalent.json",
    "receipts/4090-varied-window-throughput-validation-2026-06-30.json",
    "receipts/4090-real-data-streamed-window-throughput-probe-pretraining-equivalent.json",
    "receipts/4090-streamed-window-throughput-validation-2026-06-30.json",
    "receipts/4090-real-data-streamed-128-window-throughput-probe-pretraining-equivalent.json",
    "receipts/4090-streamed-128-window-throughput-validation-2026-06-30.json",
    "receipts/4090-real-data-streamed-128-window-power-sampled-probe-pretraining-equivalent.json",
    "receipts/4090-power-sampled-128-window-throughput-2026-06-30.json",
    "receipts/4090-power-sampled-128-window-validation-2026-06-30.json",
    "receipts/4090-real-data-checkpoint-cadence-probe-pretraining-equivalent.json",
    "receipts/4090-checkpoint-cadence-validation-2026-06-30.json",
    "receipts/4090-real-data-eval-accounting-probe-pretraining-equivalent.json",
    "receipts/4090-eval-accounting-validation-2026-06-30.json",
    "receipts/4090-real-data-recovery-accounting-probe-pretraining-equivalent.json",
    "receipts/4090-recovery-accounting-validation-2026-06-30.json",
    "receipts/4090-integrated-policy-probe-pretraining-equivalent.json",
    "receipts/4090-integrated-policy-validation-2026-06-30.json",
    "receipts/4090-policy-amortized-256-window-probe-pretraining-equivalent.json",
    "receipts/4090-policy-amortized-256-window-power-2026-06-30.json",
    "receipts/4090-policy-amortized-256-window-validation-2026-06-30.json",
    "receipts/4090-policy-optimized-1024-window-probe-pretraining-equivalent.json",
    "receipts/4090-policy-optimized-1024-window-power-2026-06-30.json",
    "receipts/4090-policy-optimized-1024-window-validation-2026-06-30.json",
    "receipts/4090-native-kernel-probe-from-scratch.json",
    "receipts/4090-native-kernel-probe-from-scratch-parse.json",
    "receipts/4090-native-training-stack-probe-pretraining-equivalent.json",
    "receipts/4090-native-training-stack-validation-2026-06-30.json",
    "receipts/4090-data-governance-2026-06-30.json",
    "receipts/4090-data-governance-validation-2026-06-30.json",
    "receipts/4090-data-hygiene-audit-2026-06-30.json",
    "receipts/4090-data-hygiene-validation-2026-06-30.json",
    "receipts/4090-exact-dedupe-scan-2026-06-30.json",
    "receipts/4090-exact-dedupe-validation-2026-06-30.json",
    "receipts/4090-data-hygiene-policy-thresholds-2026-06-30.json",
    "receipts/4090-data-hygiene-policy-validation-2026-06-30.json",
    "receipts/4090-local-heldout-contamination-scan-2026-06-30.json",
    "receipts/4090-local-heldout-contamination-validation-2026-06-30.json",
    "receipts/4090-local-heldout-16gram-contamination-scan-2026-06-30.json",
    "receipts/4090-local-heldout-16gram-contamination-validation-2026-06-30.json",
    "receipts/4090-eval-text-inventory-normalized-span-scan-2026-06-30.json",
    "receipts/4090-eval-text-inventory-validation-2026-06-30.json",
    "receipts/4090-near-duplicate-minhash-sample-2026-06-30.json",
    "receipts/4090-near-duplicate-minhash-sample-validation-2026-06-30.json",
    "receipts/4090-near-duplicate-sample-remediation-2026-06-30.json",
    "receipts/4090-near-duplicate-sample-remediation-validation-2026-06-30.json",
    "receipts/4090-near-duplicate-targeted-expansion-2026-06-30.json",
    "receipts/4090-near-duplicate-targeted-expansion-validation-2026-06-30.json",
    "receipts/4090-near-duplicate-targeted-exclusion-manifest-2026-06-30.json",
    "receipts/4090-near-duplicate-targeted-exclusion-manifest-validation-2026-06-30.json",
    "receipts/4090-targeted-filtered-corpus-view-2026-06-30.json",
    "receipts/4090-targeted-filtered-corpus-view-validation-2026-06-30.json",
    "receipts/4090-targeted-filtered-near-duplicate-sample-2026-06-30.json",
    "receipts/4090-targeted-filtered-near-duplicate-sample-validation-2026-06-30.json",
    "receipts/4090-targeted-filtered-challenge-remediation-2026-06-30.json",
    "receipts/4090-targeted-filtered-challenge-remediation-validation-2026-06-30.json",
    "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v2-2026-06-30.json",
    "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v2-validation-2026-06-30.json",
    "receipts/4090-cumulative-filtered-corpus-view-v2-2026-06-30.json",
    "receipts/4090-cumulative-filtered-corpus-view-v2-validation-2026-06-30.json",
    "receipts/4090-cumulative-filtered-near-duplicate-sample-v2-2026-06-30.json",
    "receipts/4090-cumulative-filtered-near-duplicate-sample-v2-validation-2026-06-30.json",
    "receipts/4090-cumulative-filtered-challenge-remediation-v3-2026-06-30.json",
    "receipts/4090-cumulative-filtered-challenge-remediation-v3-validation-2026-06-30.json",
    "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v3-2026-06-30.json",
    "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v3-validation-2026-06-30.json",
    "receipts/4090-cumulative-filtered-corpus-view-v3-2026-06-30.json",
    "receipts/4090-cumulative-filtered-corpus-view-v3-validation-2026-06-30.json",
    "receipts/4090-cumulative-filtered-near-duplicate-sample-v3-2026-06-30.json",
    "receipts/4090-cumulative-filtered-near-duplicate-sample-v3-validation-2026-06-30.json",
    "receipts/4090-cumulative-filtered-challenge-remediation-v4-2026-06-30.json",
    "receipts/4090-cumulative-filtered-challenge-remediation-v4-validation-2026-06-30.json",
    "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v4-2026-06-30.json",
    "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v4-validation-2026-06-30.json",
    "receipts/4090-cumulative-filtered-corpus-view-v4-2026-06-30.json",
    "receipts/4090-cumulative-filtered-corpus-view-v4-validation-2026-06-30.json",
    "receipts/4090-cumulative-filtered-near-duplicate-sample-v4-2026-06-30.json",
    "receipts/4090-cumulative-filtered-near-duplicate-sample-v4-validation-2026-06-30.json",
    "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-2026-06-30.json",
    "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-validation-2026-06-30.json",
    "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band4-2026-06-30.json",
    "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band4-validation-2026-06-30.json",
    "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band8-2026-06-30.json",
    "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band8-validation-2026-06-30.json",
    "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band12-2026-06-30.json",
    "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band12-validation-2026-06-30.json",
    "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band16-2026-06-30.json",
    "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band16-validation-2026-06-30.json",
    "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band20-2026-06-30.json",
    "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band20-validation-2026-06-30.json",
    "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band24-2026-06-30.json",
    "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band24-validation-2026-06-30.json",
    "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band28-2026-06-30.json",
    "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band28-validation-2026-06-30.json",
    "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band32-2026-06-30.json",
    "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band32-validation-2026-06-30.json",
    "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band36-2026-06-30.json",
    "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band36-validation-2026-06-30.json",
    "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band40-2026-06-30.json",
    "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band40-validation-2026-06-30.json",
    "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band44-2026-06-30.json",
    "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band44-validation-2026-06-30.json",
    "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band48-2026-06-30.json",
    "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band48-validation-2026-06-30.json",
    "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band52-2026-06-30.json",
    "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band52-validation-2026-06-30.json",
    "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band56-2026-06-30.json",
    "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band56-validation-2026-06-30.json",
    "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band60-2026-06-30.json",
    "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band60-validation-2026-06-30.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v4-band48-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v4-band48-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v4-band48-adjudication-partial25-remediation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v4-band48-adjudication-partial25-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v4-band48-adjudication-partial25-2026-07-01.json",
    "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v5-2026-07-01.json",
    "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v5-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-corpus-view-v5-2026-07-01.json",
    "receipts/4090-cumulative-filtered-corpus-view-v5-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v5-band48-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v5-band48-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v5-band48-adjudication-partial25-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v5-band48-adjudication-partial25-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v5-band48-adjudication-partial25-remediation-2026-07-01.json",
    "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v6-2026-07-01.json",
    "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v6-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-corpus-view-v6-2026-07-01.json",
    "receipts/4090-cumulative-filtered-corpus-view-v6-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v6-band48-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v6-band48-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v6-band48-adjudication-partial25-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v6-band48-adjudication-partial25-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v6-band48-adjudication-partial25-remediation-2026-07-01.json",
    "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v7-2026-07-01.json",
    "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v7-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-corpus-view-v7-2026-07-01.json",
    "receipts/4090-cumulative-filtered-corpus-view-v7-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v7-band48-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v7-band48-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v7-band48-adjudication-partial25-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v7-band48-adjudication-partial25-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v7-band48-adjudication-partial25-remediation-2026-07-01.json",
    "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v8-2026-07-01.json",
    "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v8-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-corpus-view-v8-2026-07-01.json",
    "receipts/4090-cumulative-filtered-corpus-view-v8-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v8-band48-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v8-band48-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v8-band48-adjudication-partial25-skip0-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v8-band48-adjudication-partial25-skip0-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v8-band48-adjudication-partial25-skip25-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v8-band48-adjudication-partial25-skip25-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v8-band48-adjudication-window50-remediation-2026-07-01.json",
    "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v9-2026-07-01.json",
    "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v9-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-corpus-view-v9-2026-07-01.json",
    "receipts/4090-cumulative-filtered-corpus-view-v9-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v9-band48-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v9-band48-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v9-band48-adjudication-partial25-skip0-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v9-band48-adjudication-partial25-skip0-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v9-band48-adjudication-partial25-skip25-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v9-band48-adjudication-partial25-skip25-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v9-band48-adjudication-partial25-skip50-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v9-band48-adjudication-partial25-skip50-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v9-band48-adjudication-partial25-skip75-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v9-band48-adjudication-partial25-skip75-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v9-band48-adjudication-window100-remediation-2026-07-01.json",
    "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v10-2026-07-01.json",
    "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v10-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-corpus-view-v10-2026-07-01.json",
    "receipts/4090-cumulative-filtered-corpus-view-v10-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v10-band48-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v10-band48-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v10-band48-adjudication-partial25-skip0-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v10-band48-adjudication-partial25-skip0-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v10-band48-adjudication-partial25-skip25-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v10-band48-adjudication-partial25-skip25-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v10-band48-adjudication-partial25-skip50-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v10-band48-adjudication-partial25-skip50-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v10-band48-adjudication-partial25-skip75-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v10-band48-adjudication-partial25-skip75-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v10-band48-adjudication-partial25-skip100-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v10-band48-adjudication-partial25-skip100-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v10-band48-adjudication-window125-remediation-2026-07-01.json",
    "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v11-2026-07-01.json",
    "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v11-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-corpus-view-v11-2026-07-01.json",
    "receipts/4090-cumulative-filtered-corpus-view-v11-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v11-band48-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v11-band48-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v11-band48-adjudication-partial25-skip0-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v11-band48-adjudication-partial25-skip0-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v11-band48-adjudication-partial25-skip25-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v11-band48-adjudication-partial25-skip25-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v11-band48-adjudication-partial25-skip50-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v11-band48-adjudication-partial25-skip50-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v11-band48-adjudication-partial25-skip75-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v11-band48-adjudication-partial25-skip75-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v11-band48-adjudication-partial25-skip100-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v11-band48-adjudication-partial25-skip100-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v11-band48-adjudication-partial25-skip125-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v11-band48-adjudication-partial25-skip125-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v11-band48-adjudication-window150-remediation-2026-07-01.json",
    "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v12-2026-07-01.json",
    "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v12-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-corpus-view-v12-2026-07-01.json",
    "receipts/4090-cumulative-filtered-corpus-view-v12-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v12-band48-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v12-band48-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v12-band48-adjudication-partial25-skip0-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v12-band48-adjudication-partial25-skip0-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v12-band48-adjudication-partial25-skip25-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v12-band48-adjudication-partial25-skip25-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v12-band48-adjudication-partial25-skip50-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v12-band48-adjudication-partial25-skip50-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v12-band48-adjudication-partial25-skip75-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v12-band48-adjudication-partial25-skip75-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v12-band48-adjudication-partial25-skip100-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v12-band48-adjudication-partial25-skip100-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v12-band48-adjudication-partial25-skip125-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v12-band48-adjudication-partial25-skip125-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v12-band48-adjudication-partial25-skip150-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v12-band48-adjudication-partial25-skip150-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v12-band48-adjudication-window175-remediation-2026-07-01.json",
    "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v13-2026-07-01.json",
    "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v13-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-corpus-view-v13-2026-07-01.json",
    "receipts/4090-cumulative-filtered-corpus-view-v13-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v13-band48-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v13-band48-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-lsh-candidate-index-v13-band48-adjudication-window200-remediation-2026-07-01.json",
    "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v14-2026-07-01.json",
    "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v14-validation-2026-07-01.json",
    "receipts/4090-cumulative-filtered-corpus-view-v14-2026-07-01.json",
    "receipts/4090-cumulative-filtered-corpus-view-v14-validation-2026-07-01.json",
]

REQUIRED_ENGINEERING_ARTIFACTS = [
    "engineering/4090-1b/environment.json",
    "engineering/4090-1b/train_1b_4090.py",
    "engineering/4090-1b/configs/from_scratch_1b_4090.json",
    "engineering/4090-1b/configs/pretraining_equivalent_1b_4090.json",
    "engineering/4090-1b/parse_receipts.py",
    "engineering/4090-1b/governed_probe_4090.py",
    "engineering/4090-1b/full_memory_probe_4090.py",
    "engineering/4090-1b/full_shape_block_probe_4090.py",
    "engineering/4090-1b/full_stack_step_probe_4090.py",
    "engineering/4090-1b/full_stack_lm_loss_probe_4090.py",
    "engineering/4090-1b/native_kernel_probe_4090.py",
    "engineering/4090-1b/native_training_stack_probe_4090.py",
    "engineering/4090-1b/README.md",
    "scripts/validate_c1_training_throughput_gap.py",
    "scripts/validate_c1_real_data_lm_loss_probe.py",
    "scripts/validate_c1_checkpoint_resume_probe.py",
    "scripts/validate_c1_multistep_stability_probe.py",
    "scripts/validate_c1_steady_state_throughput_probe.py",
    "scripts/validate_c1_varied_window_throughput_probe.py",
    "scripts/validate_c1_streamed_window_throughput_probe.py",
    "scripts/validate_c1_streamed_long_window_probe.py",
    "scripts/run_c1_power_sampled_probe.py",
    "scripts/validate_c1_power_sampled_probe.py",
    "scripts/validate_c1_checkpoint_cadence_probe.py",
    "scripts/validate_c1_eval_accounting_probe.py",
    "scripts/validate_c1_recovery_accounting_probe.py",
    "scripts/validate_c1_integrated_policy_probe.py",
    "scripts/run_c1_policy_amortized_probe.py",
    "scripts/validate_c1_policy_amortized_probe.py",
    "scripts/run_c1_policy_optimized_probe.py",
    "scripts/validate_c1_policy_optimized_probe.py",
    "scripts/validate_c1_native_training_stack_probe.py",
    "scripts/validate_4090_data_governance.py",
    "protocols/4090-data-governance-v0.md",
    "scripts/validate_4090_data_hygiene.py",
    "protocols/4090-data-hygiene-v0.md",
    "scripts/scan_c1_exact_dedup.py",
    "scripts/validate_c1_exact_dedup.py",
    "scripts/validate_c1_data_hygiene_policy.py",
    "scripts/scan_c1_local_heldout_contamination.py",
    "scripts/validate_c1_local_heldout_contamination.py",
    "scripts/scan_c1_local_heldout_multingram_contamination.py",
    "scripts/validate_c1_local_heldout_16gram_contamination.py",
    "scripts/build_c1_eval_text_inventory.py",
    "scripts/validate_c1_eval_text_inventory.py",
    "scripts/scan_c1_near_duplicate_sample.py",
    "scripts/validate_c1_near_duplicate_sample.py",
    "scripts/remediate_c1_near_duplicate_sample.py",
    "scripts/validate_c1_near_duplicate_sample_remediation.py",
    "scripts/expand_c1_near_duplicate_targets.py",
    "scripts/validate_c1_near_duplicate_targeted_expansion.py",
    "scripts/materialize_c1_near_duplicate_exclusions.py",
    "scripts/validate_c1_near_duplicate_exclusion_manifest.py",
    "scripts/materialize_c1_targeted_filtered_corpus_view.py",
    "scripts/validate_c1_targeted_filtered_corpus_view.py",
    "scripts/scan_c1_targeted_filtered_near_duplicate_sample.py",
    "scripts/validate_c1_targeted_filtered_near_duplicate_sample.py",
    "scripts/remediate_c1_targeted_filtered_challenge_sample.py",
    "scripts/validate_c1_targeted_filtered_challenge_remediation.py",
    "scripts/materialize_c1_near_duplicate_cumulative_exclusions.py",
    "scripts/validate_c1_near_duplicate_cumulative_exclusions.py",
    "scripts/materialize_c1_cumulative_filtered_corpus_view.py",
    "scripts/validate_c1_cumulative_filtered_corpus_view.py",
    "scripts/scan_c1_cumulative_filtered_near_duplicate_sample.py",
    "scripts/validate_c1_cumulative_filtered_near_duplicate_sample.py",
    "fragments/c1-near-duplicate-targeted-exclusions-2026-06-30.jsonl",
    "fragments/c1-near-duplicate-cumulative-exclusions-v2-2026-06-30.jsonl",
    "scripts/remediate_c1_cumulative_filtered_challenge_sample_v3.py",
    "scripts/validate_c1_cumulative_filtered_challenge_remediation_v3.py",
    "scripts/materialize_c1_near_duplicate_cumulative_exclusions_v3.py",
    "scripts/validate_c1_near_duplicate_cumulative_exclusions_v3.py",
    "scripts/materialize_c1_cumulative_filtered_corpus_view_v3.py",
    "scripts/validate_c1_cumulative_filtered_corpus_view_v3.py",
    "scripts/scan_c1_cumulative_filtered_near_duplicate_sample_v3.py",
    "scripts/validate_c1_cumulative_filtered_near_duplicate_sample_v3.py",
    "fragments/c1-near-duplicate-cumulative-exclusions-v3-2026-06-30.jsonl",
    "scripts/remediate_c1_cumulative_filtered_challenge_sample_v4.py",
    "scripts/validate_c1_cumulative_filtered_challenge_remediation_v4.py",
    "scripts/materialize_c1_near_duplicate_cumulative_exclusions_v4.py",
    "scripts/validate_c1_near_duplicate_cumulative_exclusions_v4.py",
    "scripts/materialize_c1_cumulative_filtered_corpus_view_v4.py",
    "scripts/validate_c1_cumulative_filtered_corpus_view_v4.py",
    "scripts/scan_c1_cumulative_filtered_near_duplicate_sample_v4.py",
    "scripts/validate_c1_cumulative_filtered_near_duplicate_sample_v4.py",
    "scripts/scan_c1_cumulative_filtered_lsh_bucket_census_v4.py",
    "scripts/validate_c1_cumulative_filtered_lsh_bucket_census_v4.py",
    "fragments/c1-near-duplicate-cumulative-exclusions-v4-2026-06-30.jsonl",
    "scripts/materialize_c1_near_duplicate_cumulative_exclusions_v5.py",
    "scripts/validate_c1_near_duplicate_cumulative_exclusions_v5.py",
    "scripts/materialize_c1_cumulative_filtered_corpus_view_v5.py",
    "scripts/validate_c1_cumulative_filtered_corpus_view_v5.py",
    "fragments/c1-near-duplicate-cumulative-exclusions-v5-2026-07-01.jsonl",
    "scripts/materialize_c1_cumulative_filtered_lsh_candidate_index_v5.py",
    "scripts/validate_c1_cumulative_filtered_lsh_candidate_index_v5.py",
    "scripts/adjudicate_c1_cumulative_filtered_lsh_candidate_index_v5.py",
    "scripts/validate_c1_cumulative_filtered_lsh_candidate_index_adjudication_v5.py",
    "scripts/remediate_c1_lsh_candidate_adjudication_v5.py",
    "fragments/c1-cumulative-filtered-lsh-candidate-index-v5-band48-2026-07-01.jsonl",
    "scripts/materialize_c1_near_duplicate_cumulative_exclusions_v6.py",
    "scripts/validate_c1_near_duplicate_cumulative_exclusions_v6.py",
    "scripts/materialize_c1_cumulative_filtered_corpus_view_v6.py",
    "scripts/validate_c1_cumulative_filtered_corpus_view_v6.py",
    "fragments/c1-near-duplicate-cumulative-exclusions-v6-2026-07-01.jsonl",
    "scripts/materialize_c1_cumulative_filtered_lsh_candidate_index_v6.py",
    "scripts/validate_c1_cumulative_filtered_lsh_candidate_index_v6.py",
    "scripts/adjudicate_c1_cumulative_filtered_lsh_candidate_index_v6.py",
    "scripts/validate_c1_cumulative_filtered_lsh_candidate_index_adjudication_v6.py",
    "scripts/remediate_c1_lsh_candidate_adjudication_v6.py",
    "fragments/c1-cumulative-filtered-lsh-candidate-index-v6-band48-2026-07-01.jsonl",
    "scripts/materialize_c1_near_duplicate_cumulative_exclusions_v7.py",
    "scripts/validate_c1_near_duplicate_cumulative_exclusions_v7.py",
    "scripts/materialize_c1_cumulative_filtered_corpus_view_v7.py",
    "scripts/validate_c1_cumulative_filtered_corpus_view_v7.py",
    "fragments/c1-near-duplicate-cumulative-exclusions-v7-2026-07-01.jsonl",
    "scripts/materialize_c1_cumulative_filtered_lsh_candidate_index_v7.py",
    "scripts/validate_c1_cumulative_filtered_lsh_candidate_index_v7.py",
    "scripts/adjudicate_c1_cumulative_filtered_lsh_candidate_index_v7.py",
    "scripts/validate_c1_cumulative_filtered_lsh_candidate_index_adjudication_v7.py",
    "scripts/remediate_c1_lsh_candidate_adjudication_v7.py",
    "fragments/c1-cumulative-filtered-lsh-candidate-index-v7-band48-2026-07-01.jsonl",
    "scripts/materialize_c1_near_duplicate_cumulative_exclusions_v8.py",
    "scripts/validate_c1_near_duplicate_cumulative_exclusions_v8.py",
    "scripts/materialize_c1_cumulative_filtered_corpus_view_v8.py",
    "scripts/validate_c1_cumulative_filtered_corpus_view_v8.py",
    "fragments/c1-near-duplicate-cumulative-exclusions-v8-2026-07-01.jsonl",
    "scripts/materialize_c1_cumulative_filtered_lsh_candidate_index_v8.py",
    "scripts/validate_c1_cumulative_filtered_lsh_candidate_index_v8.py",
    "scripts/adjudicate_c1_cumulative_filtered_lsh_candidate_index_v8.py",
    "scripts/validate_c1_cumulative_filtered_lsh_candidate_index_adjudication_v8.py",
    "scripts/remediate_c1_lsh_candidate_adjudication_v8.py",
    "fragments/c1-cumulative-filtered-lsh-candidate-index-v8-band48-2026-07-01.jsonl",
    "scripts/materialize_c1_near_duplicate_cumulative_exclusions_v9.py",
    "scripts/validate_c1_near_duplicate_cumulative_exclusions_v9.py",
    "scripts/materialize_c1_cumulative_filtered_corpus_view_v9.py",
    "scripts/validate_c1_cumulative_filtered_corpus_view_v9.py",
    "fragments/c1-near-duplicate-cumulative-exclusions-v9-2026-07-01.jsonl",
    "scripts/materialize_c1_cumulative_filtered_lsh_candidate_index_v9.py",
    "scripts/validate_c1_cumulative_filtered_lsh_candidate_index_v9.py",
    "scripts/adjudicate_c1_cumulative_filtered_lsh_candidate_index_v9.py",
    "scripts/validate_c1_cumulative_filtered_lsh_candidate_index_adjudication_v9.py",
    "scripts/remediate_c1_lsh_candidate_adjudication_v9.py",
    "fragments/c1-cumulative-filtered-lsh-candidate-index-v9-band48-2026-07-01.jsonl",
    "scripts/materialize_c1_near_duplicate_cumulative_exclusions_v10.py",
    "scripts/validate_c1_near_duplicate_cumulative_exclusions_v10.py",
    "scripts/materialize_c1_cumulative_filtered_corpus_view_v10.py",
    "scripts/validate_c1_cumulative_filtered_corpus_view_v10.py",
    "fragments/c1-near-duplicate-cumulative-exclusions-v10-2026-07-01.jsonl",
    "scripts/materialize_c1_cumulative_filtered_lsh_candidate_index_v10.py",
    "scripts/validate_c1_cumulative_filtered_lsh_candidate_index_v10.py",
    "scripts/adjudicate_c1_cumulative_filtered_lsh_candidate_index_v10.py",
    "scripts/validate_c1_cumulative_filtered_lsh_candidate_index_adjudication_v10.py",
    "scripts/remediate_c1_lsh_candidate_adjudication_v10.py",
    "fragments/c1-cumulative-filtered-lsh-candidate-index-v10-band48-2026-07-01.jsonl",
    "scripts/materialize_c1_near_duplicate_cumulative_exclusions_v11.py",
    "scripts/validate_c1_near_duplicate_cumulative_exclusions_v11.py",
    "scripts/materialize_c1_cumulative_filtered_corpus_view_v11.py",
    "scripts/validate_c1_cumulative_filtered_corpus_view_v11.py",
    "fragments/c1-near-duplicate-cumulative-exclusions-v11-2026-07-01.jsonl",
    "scripts/materialize_c1_cumulative_filtered_lsh_candidate_index_v11.py",
    "scripts/validate_c1_cumulative_filtered_lsh_candidate_index_v11.py",
    "scripts/adjudicate_c1_cumulative_filtered_lsh_candidate_index_v11.py",
    "scripts/validate_c1_cumulative_filtered_lsh_candidate_index_adjudication_v11.py",
    "scripts/remediate_c1_lsh_candidate_adjudication_v11.py",
    "fragments/c1-cumulative-filtered-lsh-candidate-index-v11-band48-2026-07-01.jsonl",
    "scripts/materialize_c1_near_duplicate_cumulative_exclusions_v12.py",
    "scripts/validate_c1_near_duplicate_cumulative_exclusions_v12.py",
    "scripts/materialize_c1_cumulative_filtered_corpus_view_v12.py",
    "scripts/validate_c1_cumulative_filtered_corpus_view_v12.py",
    "fragments/c1-near-duplicate-cumulative-exclusions-v12-2026-07-01.jsonl",
    "scripts/materialize_c1_cumulative_filtered_lsh_candidate_index_v12.py",
    "scripts/validate_c1_cumulative_filtered_lsh_candidate_index_v12.py",
    "scripts/adjudicate_c1_cumulative_filtered_lsh_candidate_index_v12.py",
    "scripts/validate_c1_cumulative_filtered_lsh_candidate_index_adjudication_v12.py",
    "scripts/remediate_c1_lsh_candidate_adjudication_v12.py",
    "fragments/c1-cumulative-filtered-lsh-candidate-index-v12-band48-2026-07-01.jsonl",
    "scripts/materialize_c1_near_duplicate_cumulative_exclusions_v13.py",
    "scripts/validate_c1_near_duplicate_cumulative_exclusions_v13.py",
    "scripts/materialize_c1_cumulative_filtered_corpus_view_v13.py",
    "scripts/validate_c1_cumulative_filtered_corpus_view_v13.py",
    "scripts/materialize_c1_cumulative_filtered_lsh_candidate_index_v13.py",
    "scripts/validate_c1_cumulative_filtered_lsh_candidate_index_v13.py",
    "scripts/adjudicate_c1_cumulative_filtered_lsh_candidate_index_v13.py",
    "scripts/validate_c1_cumulative_filtered_lsh_candidate_index_adjudication_v13.py",
    "scripts/remediate_c1_lsh_candidate_adjudication_v13.py",
    "scripts/materialize_c1_near_duplicate_cumulative_exclusions_v14.py",
    "scripts/validate_c1_near_duplicate_cumulative_exclusions_v14.py",
    "scripts/materialize_c1_cumulative_filtered_corpus_view_v14.py",
    "scripts/validate_c1_cumulative_filtered_corpus_view_v14.py",
    "fragments/c1-near-duplicate-cumulative-exclusions-v13-2026-07-01.jsonl",
    "fragments/c1-cumulative-filtered-lsh-candidate-index-v13-band48-2026-07-01.jsonl",
    "fragments/c1-near-duplicate-cumulative-exclusions-v14-2026-07-01.jsonl",
    "fragments/c1-cumulative-filtered-lsh-candidate-index-v14-band48-2026-07-01.jsonl",
    "fragments/c1-near-duplicate-cumulative-exclusions-v15-2026-07-01.jsonl",
]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_sources(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8-sig") as fh:
        for line in fh:
            if line.strip():
                row = json.loads(line)
                rows[row["id"]] = row
    return rows


def require_text(path: Path, needles: list[str], failures: list[dict[str, Any]], label: str) -> None:
    if not path.exists():
        failures.append({"code": f"{label}_missing", "path": str(path)})
        return
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    forbidden = ["Status: INCOMPLETE", "Status: DRAFT", "Current Verdict\n\nINCOMPLETE", "NOT RUN"]
    for term in forbidden:
        if term in text:
            failures.append({"code": f"{label}_forbidden_incomplete_marker", "term": term})
    for needle in needles:
        if needle not in text:
            failures.append({"code": f"{label}_missing_required_text", "needle": needle})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    failures: list[dict[str, Any]] = []
    report_path = root / "4090-ceiling-v0.md"
    contract_path = root / "contracts" / "C1-4090-1B-feasibility.md"
    lock_path = root / "completion-lock.json"
    sources_path = root / "sources.jsonl"

    require_text(report_path, REQUIRED_REPORT_TEXT, failures, "report")
    require_text(contract_path, REQUIRED_CONTRACT_TEXT, failures, "contract")

    for rel in REQUIRED_RECEIPTS:
        path = root / rel
        if not path.exists():
            failures.append({"code": "required_receipt_missing", "path": rel})
        else:
            receipt = read_json(path)
            if not receipt.get("verdict"):
                failures.append({"code": "required_receipt_missing_verdict", "path": rel})
            if rel.endswith("-parse.json"):
                allowed_parse = {"ENGINEERING_DRY_RUN_PASS", "GOVERNED_PROBE_PARSE_PASS", "FULL_MEMORY_PROBE_PARSE_PASS", "FULL_SHAPE_BLOCK_PROBE_PARSE_PASS", "FULL_STACK_STEP_PROBE_PARSE_PASS", "NATIVE_KERNEL_PROBE_PARSE_PASS", "FULL_STACK_LM_LOSS_PROBE_PARSE_PASS", "C1_DATA_GOVERNANCE_VALIDATED"}
                if receipt.get("verdict") not in allowed_parse:
                    failures.append({"code": "engineering_parse_receipt_not_pass", "path": rel, "verdict": receipt.get("verdict")})
            if rel.endswith("-dry-run.json"):
                if receipt.get("verdict") != "DRY_RUN_ENGINEERING_BASELINE_READY":
                    failures.append({"code": "engineering_dry_run_not_ready", "path": rel, "verdict": receipt.get("verdict")})
                if receipt.get("active_trainable_parameters", 0) < 1000000000:
                    failures.append({"code": "engineering_dry_run_below_1b", "path": rel, "actual": receipt.get("active_trainable_parameters")})
            if "full-shape-block-probe" in rel and not rel.endswith("-parse.json"):
                if receipt.get("verdict") != "FULL_SHAPE_BLOCK_PROBE_NOT_COMPLETION":
                    failures.append({"code": "full_shape_block_probe_receipt_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                shape = receipt.get("probe_shape", {})
                if shape.get("seq_len") != 2048 or shape.get("hidden") != 2048 or shape.get("heads") != 16:
                    failures.append({"code": "full_shape_block_probe_shape_mismatch", "path": rel, "shape": shape})
            if "full-stack-step-probe" in rel and not rel.endswith("-parse.json"):
                if receipt.get("verdict") != "FULL_STACK_STEP_PROBE_NOT_COMPLETION":
                    failures.append({"code": "full_stack_step_probe_receipt_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                shape = receipt.get("probe_shape", {})
                if shape.get("seq_len") != 2048 or shape.get("hidden") != 2048 or shape.get("heads") != 16 or shape.get("layers_executed") != 19:
                    failures.append({"code": "full_stack_step_probe_shape_mismatch", "path": rel, "shape": shape})
                if receipt.get("uses_activation_checkpointing") is not True or receipt.get("uses_hidden_state_surrogate_loss") is not True:
                    failures.append({"code": "full_stack_step_probe_controls_missing", "path": rel})
            if rel == "receipts/4090-data-governance-2026-06-30.json":
                if receipt.get("verdict") != "C1_DATA_GOVERNANCE_EVIDENCE_READY_WITH_EXPLICIT_GAPS":
                    failures.append({"code": "data_governance_receipt_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                lanes = receipt.get("lane_readiness", {})
                if lanes.get("pretraining_equivalent", {}).get("status") != "TOKEN_FLOOR_READY_FOR_LOCKED_5B_PRETRAINING_EQUIVALENT_LANE":
                    failures.append({"code": "data_governance_pretraining_lane_not_ready", "path": rel, "lane": lanes.get("pretraining_equivalent")})
                if lanes.get("from_scratch", {}).get("status") != "TOKEN_SHORTFALL_FOR_LOCKED_10B_FROM_SCRATCH_LANE":
                    failures.append({"code": "data_governance_from_scratch_gap_missing", "path": rel, "lane": lanes.get("from_scratch")})
            if rel == "receipts/4090-data-governance-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_DATA_GOVERNANCE_VALIDATED":
                    failures.append({"code": "data_governance_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-data-hygiene-audit-2026-06-30.json":
                if receipt.get("verdict") != "C1_DATA_HYGIENE_AUDIT_READY_WITH_BLOCKING_GAPS":
                    failures.append({"code": "data_hygiene_audit_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                gaps = receipt.get("required_c1_hygiene_gaps", {})
                required_gaps = {
                    "corpus_wide_near_duplicate_or_minhash_scan",
                    "eval_suite_contamination_scan",
                }
                allowed_gap_values = {
                    "corpus_wide_near_duplicate_or_minhash_scan": {"MISSING_C1_RECEIPT", "BOUNDED_SAMPLE_FOUND_CANDIDATES_FULL_CORPUS_REMEDIATION_REQUIRED", "SAMPLE_REMEDIATION_READY_FULL_CORPUS_SCAN_AND_PASS_REQUIRED", "TARGETED_EXPANSION_READY_ALL_PAIRS_SCAN_AND_PASS_REQUIRED", "TARGETED_EXCLUSION_MANIFEST_READY_ALL_PAIRS_SCAN_AND_PASS_REQUIRED", "TARGETED_FILTERED_VIEW_READY_ALL_PAIRS_SCAN_AND_PASS_REQUIRED", "TARGETED_FILTERED_CHALLENGE_FOUND_CANDIDATES_ALL_PAIRS_PASS_REQUIRED", "TARGETED_FILTERED_CHALLENGE_REMEDIATION_READY_ALL_PAIRS_PASS_REQUIRED", "CUMULATIVE_FILTERED_V2_CHALLENGE_FOUND_CANDIDATES_ALL_PAIRS_PASS_REQUIRED", "CUMULATIVE_FILTERED_V3_CHALLENGE_FOUND_CANDIDATES_ALL_PAIRS_PASS_REQUIRED", "CUMULATIVE_FILTERED_V4_CHALLENGE_SAMPLE_NO_CROSSINGS_ALL_PAIRS_PASS_REQUIRED", "CUMULATIVE_FILTERED_V4_LSH_BAND0_CENSUS_READY_REMAINING_BANDS_AND_EXACT_ADJUDICATION_REQUIRED", "CUMULATIVE_FILTERED_V4_LSH_3_OF_16_BANDS_READY_REMAINING_BANDS_AND_EXACT_ADJUDICATION_REQUIRED", "CUMULATIVE_FILTERED_V4_LSH_6_OF_16_BANDS_READY_REMAINING_BANDS_AND_EXACT_ADJUDICATION_REQUIRED", "CUMULATIVE_FILTERED_V4_LSH_9_OF_16_BANDS_READY_REMAINING_BANDS_AND_EXACT_ADJUDICATION_REQUIRED", "CUMULATIVE_FILTERED_V4_LSH_16_OF_16_BANDS_READY_EXACT_ADJUDICATION_REQUIRED", "CUMULATIVE_FILTERED_V4_LSH_BAND48_CANDIDATE_INDEX_READY_EXACT_ADJUDICATION_REQUIRED", "CUMULATIVE_FILTERED_V4_LSH_BAND48_PARTIAL_ADJUDICATION_FOUND_CROSSINGS_REMEDIATION_REQUIRED", "CUMULATIVE_FILTERED_V5_PARTIAL_LSH_ADJUDICATION_REMEDIATED_FULL_ADJUDICATION_REQUIRED", "CUMULATIVE_FILTERED_V6_PARTIAL_LSH_ADJUDICATION_REMEDIATED_FULL_ADJUDICATION_REQUIRED", "CUMULATIVE_FILTERED_V7_PARTIAL_LSH_ADJUDICATION_REMEDIATED_FULL_ADJUDICATION_REQUIRED", "CUMULATIVE_FILTERED_V8_PARTIAL_LSH_ADJUDICATION_REMEDIATED_FULL_ADJUDICATION_REQUIRED", "CUMULATIVE_FILTERED_V9_WINDOW50_LSH_ADJUDICATION_REMEDIATED_FULL_ADJUDICATION_REQUIRED", "CUMULATIVE_FILTERED_V10_WINDOW100_LSH_ADJUDICATION_REMEDIATED_FULL_ADJUDICATION_REQUIRED", "CUMULATIVE_FILTERED_V11_WINDOW125_LSH_ADJUDICATION_REMEDIATED_FULL_ADJUDICATION_REQUIRED", "CUMULATIVE_FILTERED_V12_WINDOW150_LSH_ADJUDICATION_REMEDIATED_FULL_ADJUDICATION_REQUIRED", "CUMULATIVE_FILTERED_V13_WINDOW175_LSH_ADJUDICATION_REMEDIATED_FULL_ADJUDICATION_REQUIRED"},
                    "eval_suite_contamination_scan": {"MISSING_C1_RECEIPT", "MISSING_FULL_EVAL_SUITE_AND_NORMALIZED_SPAN_RECEIPT", "AVAILABLE_EVAL_TEXT_INVENTORY_READY_FULL_EXTERNAL_SUITE_AND_TOKEN_CORPUS_NORMALIZED_SCAN_REQUIRED"},
                }
                if set(gaps) != required_gaps or any(gaps.get(key) not in allowed for key, allowed in allowed_gap_values.items()):
                    failures.append({"code": "data_hygiene_required_gaps_not_preserved", "path": rel, "gaps": gaps})
                if receipt.get("c1_blocking_status") != "BLOCKS_C1_BASELINE_COMPLETE_UNTIL_REPLACED_BY_PASS_RECEIPTS":
                    failures.append({"code": "data_hygiene_blocking_status_missing", "path": rel, "actual": receipt.get("c1_blocking_status")})
            if rel == "receipts/4090-data-hygiene-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_DATA_HYGIENE_AUDIT_VALIDATED":
                    failures.append({"code": "data_hygiene_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-exact-dedupe-scan-2026-06-30.json":
                if receipt.get("verdict") != "C1_EXACT_DEDUPE_PASS" or receipt.get("duplicate_documents") != 0:
                    failures.append({"code": "exact_dedupe_scan_not_pass", "path": rel, "verdict": receipt.get("verdict"), "duplicate_documents": receipt.get("duplicate_documents")})
                if receipt.get("separator_tokens") != 4236458 or receipt.get("documents_seen") != 4236458:
                    failures.append({"code": "exact_dedupe_doc_count_mismatch", "path": rel, "documents_seen": receipt.get("documents_seen"), "separator_tokens": receipt.get("separator_tokens")})
            if rel == "receipts/4090-exact-dedupe-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_EXACT_DEDUPE_VALIDATED":
                    failures.append({"code": "exact_dedupe_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-data-hygiene-policy-thresholds-2026-06-30.json":
                if receipt.get("verdict") != "C1_DATA_HYGIENE_POLICY_THRESHOLDS_LOCKED":
                    failures.append({"code": "policy_thresholds_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                thresholds = receipt.get("thresholds", {})
                if thresholds.get("near_duplicate_minhash", {}).get("status") != "LOCKED_NOT_YET_SCANNED" or thresholds.get("eval_contamination", {}).get("status") != "LOCKED_NOT_YET_SCANNED":
                    failures.append({"code": "policy_thresholds_scan_status_not_locked_gap", "path": rel, "thresholds": thresholds})
            if rel == "receipts/4090-data-hygiene-policy-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_DATA_HYGIENE_POLICY_THRESHOLDS_VALIDATED":
                    failures.append({"code": "policy_thresholds_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-local-heldout-contamination-scan-2026-06-30.json":
                if receipt.get("verdict") != "C1_LOCAL_HELDOUT_EXACT_32GRAM_CONTAMINATION_PASS" or receipt.get("exact_32_token_hits") != 0:
                    failures.append({"code": "local_heldout_contamination_scan_not_pass", "path": rel, "verdict": receipt.get("verdict"), "hits": receipt.get("exact_32_token_hits")})
            if rel == "receipts/4090-local-heldout-contamination-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_LOCAL_HELDOUT_CONTAMINATION_VALIDATED":
                    failures.append({"code": "local_heldout_contamination_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-local-heldout-16gram-contamination-scan-2026-06-30.json":
                if receipt.get("verdict") != "C1_LOCAL_HELDOUT_MULTI_NGRAM_CONTAMINATION_PASS" or receipt.get("exact_hits_by_ngram", {}).get("16") != 0:
                    failures.append({"code": "local_heldout_16gram_scan_not_pass", "path": rel, "verdict": receipt.get("verdict"), "hits": receipt.get("exact_hits_by_ngram")})
            if rel == "receipts/4090-local-heldout-16gram-contamination-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_LOCAL_HELDOUT_16GRAM_CONTAMINATION_VALIDATED":
                    failures.append({"code": "local_heldout_16gram_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-eval-text-inventory-normalized-span-scan-2026-06-30.json":
                if receipt.get("verdict") != "C1_AVAILABLE_EVAL_TEXT_NORMALIZED_SPAN_LOCAL_SURFACE_SCAN_PASS_WITH_BLOCKING_FULL_SUITE_GAP" or receipt.get("exact_normalized_span_hits") != 0:
                    failures.append({"code": "eval_text_inventory_scan_bad_verdict", "path": rel, "verdict": receipt.get("verdict"), "hits": receipt.get("exact_normalized_span_hits")})
                if receipt.get("blocks_full_eval_suite_pass") is not True:
                    failures.append({"code": "eval_text_inventory_missing_blocking_gap", "path": rel})
            if rel == "receipts/4090-eval-text-inventory-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_EVAL_TEXT_INVENTORY_VALIDATED_WITH_BLOCKING_FULL_SUITE_GAP":
                    failures.append({"code": "eval_text_inventory_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-near-duplicate-minhash-sample-2026-06-30.json":
                if receipt.get("verdict") != "C1_NEAR_DUPLICATE_SAMPLE_CANDIDATES_FOUND":
                    failures.append({"code": "near_duplicate_sample_scan_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                if receipt.get("documents_seen") != 4236458 or receipt.get("sampled_documents", 0) < 50000:
                    failures.append({"code": "near_duplicate_sample_scope_mismatch", "path": rel, "documents_seen": receipt.get("documents_seen"), "sampled_documents": receipt.get("sampled_documents")})
                if receipt.get("crossing_pair_count", 0) < 1 or receipt.get("max_exact_jaccard_observed", 0) < 0.8:
                    failures.append({"code": "near_duplicate_sample_candidates_not_recorded", "path": rel, "crossing_pair_count": receipt.get("crossing_pair_count"), "max_exact_jaccard_observed": receipt.get("max_exact_jaccard_observed")})
            if rel == "receipts/4090-near-duplicate-minhash-sample-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_NEAR_DUPLICATE_SAMPLE_VALIDATED":
                    failures.append({"code": "near_duplicate_sample_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-near-duplicate-sample-remediation-2026-06-30.json":
                if receipt.get("verdict") != "C1_NEAR_DUPLICATE_SAMPLE_REMEDIATION_PACKET_READY":
                    failures.append({"code": "near_duplicate_sample_remediation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                if receipt.get("sample_exclusion_document_count", 0) < 1 or receipt.get("sample_exclusion_token_floor", 0) < 1:
                    failures.append({"code": "near_duplicate_sample_remediation_empty", "path": rel, "exclusions": receipt.get("sample_exclusion_document_count"), "token_floor": receipt.get("sample_exclusion_token_floor")})
            if rel == "receipts/4090-near-duplicate-sample-remediation-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_NEAR_DUPLICATE_SAMPLE_REMEDIATION_VALIDATED":
                    failures.append({"code": "near_duplicate_sample_remediation_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-near-duplicate-targeted-expansion-2026-06-30.json":
                if receipt.get("verdict") != "C1_NEAR_DUPLICATE_TARGETED_EXPANSION_READY":
                    failures.append({"code": "near_duplicate_targeted_expansion_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                if receipt.get("documents_seen") != 4236458 or receipt.get("expanded_exclusion_document_count", 0) < receipt.get("sample_exclusion_document_count", 0):
                    failures.append({"code": "near_duplicate_targeted_expansion_scope_mismatch", "path": rel, "documents_seen": receipt.get("documents_seen"), "expanded": receipt.get("expanded_exclusion_document_count"), "sample": receipt.get("sample_exclusion_document_count")})
            if rel == "receipts/4090-near-duplicate-targeted-expansion-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_NEAR_DUPLICATE_TARGETED_EXPANSION_VALIDATED":
                    failures.append({"code": "near_duplicate_targeted_expansion_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-near-duplicate-targeted-exclusion-manifest-2026-06-30.json":
                if receipt.get("verdict") != "C1_NEAR_DUPLICATE_TARGETED_EXCLUSION_MANIFEST_READY":
                    failures.append({"code": "near_duplicate_exclusion_manifest_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                manifest = receipt.get("manifest", {})
                if manifest.get("repo_path") != "fragments/c1-near-duplicate-targeted-exclusions-2026-06-30.jsonl" or manifest.get("line_count") != receipt.get("exclusion_document_count"):
                    failures.append({"code": "near_duplicate_exclusion_manifest_metadata_invalid", "path": rel, "manifest": manifest})
                if receipt.get("exclusion_document_count", 0) < 1 or receipt.get("exclusion_token_floor", 0) < 1:
                    failures.append({"code": "near_duplicate_exclusion_manifest_empty", "path": rel, "count": receipt.get("exclusion_document_count"), "token_floor": receipt.get("exclusion_token_floor")})
            if rel == "receipts/4090-near-duplicate-targeted-exclusion-manifest-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_NEAR_DUPLICATE_TARGETED_EXCLUSION_MANIFEST_VALIDATED":
                    failures.append({"code": "near_duplicate_exclusion_manifest_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-targeted-filtered-corpus-view-2026-06-30.json":
                filtered = receipt.get("targeted_filtered_view", {})
                if receipt.get("verdict") != "C1_TARGETED_FILTERED_CORPUS_VIEW_READY_NOT_COMPLETION":
                    failures.append({"code": "targeted_filtered_corpus_view_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                if filtered.get("excluded_document_count") != 1668 or filtered.get("excluded_token_floor") != 2949980 or filtered.get("binary_shards_rewritten") is not False:
                    failures.append({"code": "targeted_filtered_corpus_view_scope_invalid", "path": rel, "filtered": filtered})
                if "not an all-pairs near-duplicate PASS" not in str(receipt.get("completion_limit", "")):
                    failures.append({"code": "targeted_filtered_corpus_view_guard_missing", "path": rel})
            if rel == "receipts/4090-targeted-filtered-corpus-view-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_TARGETED_FILTERED_CORPUS_VIEW_VALIDATED":
                    failures.append({"code": "targeted_filtered_corpus_view_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-targeted-filtered-near-duplicate-sample-2026-06-30.json":
                if receipt.get("verdict") != "C1_TARGETED_FILTERED_NEAR_DUPLICATE_SAMPLE_CANDIDATES_FOUND":
                    failures.append({"code": "targeted_filtered_near_duplicate_sample_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                if receipt.get("documents_seen") != 4236458 or receipt.get("sampled_documents", 0) < 50000 or receipt.get("sampled_excluded_document_count") != 0:
                    failures.append({"code": "targeted_filtered_near_duplicate_sample_scope_invalid", "path": rel, "documents_seen": receipt.get("documents_seen"), "sampled_documents": receipt.get("sampled_documents"), "sampled_excluded": receipt.get("sampled_excluded_document_count")})
                if receipt.get("crossing_pair_count", 0) < 1 or receipt.get("max_exact_jaccard_observed", 0) < 0.8:
                    failures.append({"code": "targeted_filtered_near_duplicate_sample_candidates_not_recorded", "path": rel, "crossing_pair_count": receipt.get("crossing_pair_count"), "max_exact_jaccard_observed": receipt.get("max_exact_jaccard_observed")})
                if "not an all-pairs near-duplicate PASS" not in str(receipt.get("scope_limit", "")):
                    failures.append({"code": "targeted_filtered_near_duplicate_sample_guard_missing", "path": rel})
            if rel == "receipts/4090-targeted-filtered-near-duplicate-sample-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_TARGETED_FILTERED_NEAR_DUPLICATE_SAMPLE_VALIDATED":
                    failures.append({"code": "targeted_filtered_near_duplicate_sample_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-targeted-filtered-challenge-remediation-2026-06-30.json":
                if receipt.get("verdict") != "C1_TARGETED_FILTERED_CHALLENGE_REMEDIATION_PACKET_READY":
                    failures.append({"code": "targeted_filtered_challenge_remediation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                if receipt.get("input_crossing_pair_count") != 25 or receipt.get("challenge_exclusion_document_count", 0) < 1 or receipt.get("existing_targeted_manifest_overlap_count") != 0:
                    failures.append({"code": "targeted_filtered_challenge_remediation_scope_invalid", "path": rel, "input_crossing_pair_count": receipt.get("input_crossing_pair_count"), "exclusions": receipt.get("challenge_exclusion_document_count"), "overlap": receipt.get("existing_targeted_manifest_overlap_count")})
                if "all-pairs/full-corpus PASS remains required" not in str(receipt.get("completion_limit", "")):
                    failures.append({"code": "targeted_filtered_challenge_remediation_guard_missing", "path": rel})
            if rel == "receipts/4090-targeted-filtered-challenge-remediation-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_TARGETED_FILTERED_CHALLENGE_REMEDIATION_VALIDATED":
                    failures.append({"code": "targeted_filtered_challenge_remediation_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v2-2026-06-30.json":
                if receipt.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V2_READY":
                    failures.append({"code": "cumulative_exclusion_manifest_v2_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                if receipt.get("exclusion_document_count") != 1693 or receipt.get("exclusion_token_floor") != 2988224 or receipt.get("source_overlap_count") != 0:
                    failures.append({"code": "cumulative_exclusion_manifest_v2_scope_invalid", "path": rel, "count": receipt.get("exclusion_document_count"), "token_floor": receipt.get("exclusion_token_floor"), "overlap": receipt.get("source_overlap_count")})
            if rel == "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v2-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V2_VALIDATED":
                    failures.append({"code": "cumulative_exclusion_manifest_v2_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-cumulative-filtered-corpus-view-v2-2026-06-30.json":
                view = receipt.get("cumulative_filtered_view", {})
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V2_READY_NOT_COMPLETION":
                    failures.append({"code": "cumulative_filtered_view_v2_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                if view.get("excluded_document_count") != 1693 or view.get("remaining_document_count") != 4234765 or view.get("binary_shards_rewritten") is not False:
                    failures.append({"code": "cumulative_filtered_view_v2_scope_invalid", "path": rel, "view": view})
            if rel == "receipts/4090-cumulative-filtered-corpus-view-v2-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V2_VALIDATED":
                    failures.append({"code": "cumulative_filtered_view_v2_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-cumulative-filtered-near-duplicate-sample-v2-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_NEAR_DUPLICATE_SAMPLE_V2_CANDIDATES_FOUND":
                    failures.append({"code": "cumulative_filtered_near_duplicate_sample_v2_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                if receipt.get("sampled_documents", 0) < 50000 or receipt.get("sampled_excluded_document_count") != 0 or receipt.get("crossing_pair_count", 0) < 1:
                    failures.append({"code": "cumulative_filtered_near_duplicate_sample_v2_scope_invalid", "path": rel, "sampled": receipt.get("sampled_documents"), "sampled_excluded": receipt.get("sampled_excluded_document_count"), "crossing": receipt.get("crossing_pair_count")})
            if rel == "receipts/4090-cumulative-filtered-near-duplicate-sample-v2-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_NEAR_DUPLICATE_SAMPLE_V2_VALIDATED":
                    failures.append({"code": "cumulative_filtered_near_duplicate_sample_v2_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-cumulative-filtered-challenge-remediation-v3-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_CHALLENGE_REMEDIATION_V3_PACKET_READY":
                    failures.append({"code": "cumulative_filtered_challenge_remediation_v3_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                if receipt.get("input_crossing_pair_count") != 25 or receipt.get("challenge_exclusion_document_count") != 16 or receipt.get("existing_targeted_manifest_overlap_count") != 0:
                    failures.append({"code": "cumulative_filtered_challenge_remediation_v3_scope_invalid", "path": rel, "input_crossing_pair_count": receipt.get("input_crossing_pair_count"), "exclusions": receipt.get("challenge_exclusion_document_count"), "overlap": receipt.get("existing_targeted_manifest_overlap_count")})
                if "all-pairs/full-corpus PASS remains required" not in str(receipt.get("completion_limit", "")):
                    failures.append({"code": "cumulative_filtered_challenge_remediation_v3_guard_missing", "path": rel})
            if rel == "receipts/4090-cumulative-filtered-challenge-remediation-v3-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_CHALLENGE_REMEDIATION_V3_VALIDATED":
                    failures.append({"code": "cumulative_filtered_challenge_remediation_v3_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v3-2026-06-30.json":
                if receipt.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V3_READY":
                    failures.append({"code": "cumulative_exclusion_manifest_v3_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                if receipt.get("exclusion_document_count") != 1709 or receipt.get("exclusion_token_floor") != 3012037 or receipt.get("source_overlap_count") != 0:
                    failures.append({"code": "cumulative_exclusion_manifest_v3_scope_invalid", "path": rel, "doc_count": receipt.get("exclusion_document_count"), "tokens": receipt.get("exclusion_token_floor"), "overlap": receipt.get("source_overlap_count")})
            if rel == "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v3-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V3_VALIDATED":
                    failures.append({"code": "cumulative_exclusion_manifest_v3_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-cumulative-filtered-corpus-view-v3-2026-06-30.json":
                view = receipt.get("cumulative_filtered_view", {})
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V3_READY_NOT_COMPLETION":
                    failures.append({"code": "cumulative_filtered_view_v3_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                if view.get("excluded_document_count") != 1709 or view.get("remaining_document_count") != 4234749 or view.get("binary_shards_rewritten") is not False:
                    failures.append({"code": "cumulative_filtered_view_v3_scope_invalid", "path": rel, "view": view})
            if rel == "receipts/4090-cumulative-filtered-corpus-view-v3-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V3_VALIDATED":
                    failures.append({"code": "cumulative_filtered_view_v3_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-cumulative-filtered-near-duplicate-sample-v3-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_NEAR_DUPLICATE_SAMPLE_V3_CANDIDATES_FOUND":
                    failures.append({"code": "cumulative_filtered_near_duplicate_sample_v3_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                if receipt.get("sampled_documents", 0) < 50000 or receipt.get("sampled_excluded_document_count") != 0 or receipt.get("crossing_pair_count") != 10:
                    failures.append({"code": "cumulative_filtered_near_duplicate_sample_v3_scope_invalid", "path": rel, "sampled": receipt.get("sampled_documents"), "sampled_excluded": receipt.get("sampled_excluded_document_count"), "crossing": receipt.get("crossing_pair_count")})
            if rel == "receipts/4090-cumulative-filtered-near-duplicate-sample-v3-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_NEAR_DUPLICATE_SAMPLE_V3_VALIDATED":
                    failures.append({"code": "cumulative_filtered_near_duplicate_sample_v3_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-cumulative-filtered-challenge-remediation-v4-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_CHALLENGE_REMEDIATION_V4_PACKET_READY":
                    failures.append({"code": "cumulative_filtered_challenge_remediation_v4_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                if receipt.get("input_crossing_pair_count") != 10 or receipt.get("challenge_exclusion_document_count") != 10 or receipt.get("existing_targeted_manifest_overlap_count") != 0:
                    failures.append({"code": "cumulative_filtered_challenge_remediation_v4_scope_invalid", "path": rel, "input_crossing_pair_count": receipt.get("input_crossing_pair_count"), "exclusions": receipt.get("challenge_exclusion_document_count"), "overlap": receipt.get("existing_targeted_manifest_overlap_count")})
            if rel == "receipts/4090-cumulative-filtered-challenge-remediation-v4-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_CHALLENGE_REMEDIATION_V4_VALIDATED":
                    failures.append({"code": "cumulative_filtered_challenge_remediation_v4_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v4-2026-06-30.json":
                if receipt.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V4_READY":
                    failures.append({"code": "cumulative_exclusion_manifest_v4_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                if receipt.get("exclusion_document_count") != 1719 or receipt.get("exclusion_token_floor") != 3026203 or receipt.get("source_overlap_count") != 0:
                    failures.append({"code": "cumulative_exclusion_manifest_v4_scope_invalid", "path": rel, "doc_count": receipt.get("exclusion_document_count"), "tokens": receipt.get("exclusion_token_floor"), "overlap": receipt.get("source_overlap_count")})
            if rel == "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v4-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V4_VALIDATED":
                    failures.append({"code": "cumulative_exclusion_manifest_v4_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-cumulative-filtered-corpus-view-v4-2026-06-30.json":
                view = receipt.get("cumulative_filtered_view", {})
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V4_READY_NOT_COMPLETION":
                    failures.append({"code": "cumulative_filtered_view_v4_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                if view.get("excluded_document_count") != 1719 or view.get("remaining_document_count") != 4234739 or view.get("binary_shards_rewritten") is not False:
                    failures.append({"code": "cumulative_filtered_view_v4_scope_invalid", "path": rel, "view": view})
            if rel == "receipts/4090-cumulative-filtered-corpus-view-v4-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V4_VALIDATED":
                    failures.append({"code": "cumulative_filtered_view_v4_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-cumulative-filtered-near-duplicate-sample-v4-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_NEAR_DUPLICATE_SAMPLE_V4_NO_CROSSING_CANDIDATES":
                    failures.append({"code": "cumulative_filtered_near_duplicate_sample_v4_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                if receipt.get("sampled_documents", 0) < 50000 or receipt.get("sampled_excluded_document_count") != 0 or receipt.get("crossing_pair_count") != 0 or receipt.get("max_exact_jaccard_observed", 1) >= 0.8:
                    failures.append({"code": "cumulative_filtered_near_duplicate_sample_v4_scope_invalid", "path": rel, "sampled": receipt.get("sampled_documents"), "sampled_excluded": receipt.get("sampled_excluded_document_count"), "crossing": receipt.get("crossing_pair_count"), "max_jaccard": receipt.get("max_exact_jaccard_observed")})
            if rel == "receipts/4090-cumulative-filtered-near-duplicate-sample-v4-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_NEAR_DUPLICATE_SAMPLE_V4_VALIDATED":
                    failures.append({"code": "cumulative_filtered_near_duplicate_sample_v4_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_PARTIAL_NOT_COMPLETION":
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                if receipt.get("full_document_coverage") is not True or receipt.get("full_band_coverage") is not False:
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_coverage_invalid", "path": rel, "full_document": receipt.get("full_document_coverage"), "full_band": receipt.get("full_band_coverage")})
                if receipt.get("band_count_scanned") != 1 or receipt.get("band_starts_scanned") != [0]:
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band_scope_invalid", "path": rel, "band_count": receipt.get("band_count_scanned"), "band_starts": receipt.get("band_starts_scanned")})
                if receipt.get("documents_censused") != 3806884 or receipt.get("collision_bucket_count") != 28337 or receipt.get("max_bucket_size") != 2994:
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_counts_invalid", "path": rel, "documents_censused": receipt.get("documents_censused"), "collision_bucket_count": receipt.get("collision_bucket_count"), "max_bucket_size": receipt.get("max_bucket_size")})
                if "not an all-pairs near-duplicate PASS" not in str(receipt.get("scope_limit", "")):
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_completion_guard_missing", "path": rel})
            if rel == "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_VALIDATED":
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band4-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_PARTIAL_NOT_COMPLETION" or receipt.get("band_starts_scanned") != [4]:
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band4_bad_scope", "path": rel, "verdict": receipt.get("verdict"), "bands": receipt.get("band_starts_scanned")})
                if receipt.get("documents_censused") != 3806884 or receipt.get("collision_bucket_count") != 28392 or receipt.get("max_bucket_size") != 2290:
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band4_counts_invalid", "path": rel})
            if rel == "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band4-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_VALIDATED":
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band4_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band8-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_PARTIAL_NOT_COMPLETION" or receipt.get("band_starts_scanned") != [8]:
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band8_bad_scope", "path": rel, "verdict": receipt.get("verdict"), "bands": receipt.get("band_starts_scanned")})
                if receipt.get("documents_censused") != 3806884 or receipt.get("collision_bucket_count") != 28593 or receipt.get("max_bucket_size") != 1296:
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band8_counts_invalid", "path": rel})
            if rel == "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band8-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_VALIDATED":
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band8_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band12-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_PARTIAL_NOT_COMPLETION" or receipt.get("band_starts_scanned") != [12]:
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band12_bad_scope", "path": rel, "verdict": receipt.get("verdict"), "bands": receipt.get("band_starts_scanned")})
                if receipt.get("documents_censused") != 3806884 or receipt.get("collision_bucket_count") != 28324 or receipt.get("max_bucket_size") != 3766:
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band12_counts_invalid", "path": rel})
            if rel == "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band12-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_VALIDATED":
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band12_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band16-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_PARTIAL_NOT_COMPLETION" or receipt.get("band_starts_scanned") != [16]:
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band16_bad_scope", "path": rel, "verdict": receipt.get("verdict"), "bands": receipt.get("band_starts_scanned")})
                if receipt.get("documents_censused") != 3806884 or receipt.get("collision_bucket_count") != 28684 or receipt.get("max_bucket_size") != 2142:
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band16_counts_invalid", "path": rel})
            if rel == "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band16-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_VALIDATED":
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band16_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band20-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_PARTIAL_NOT_COMPLETION" or receipt.get("band_starts_scanned") != [20]:
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band20_bad_scope", "path": rel, "verdict": receipt.get("verdict"), "bands": receipt.get("band_starts_scanned")})
                if receipt.get("documents_censused") != 3806884 or receipt.get("collision_bucket_count") != 29149 or receipt.get("max_bucket_size") != 2392:
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band20_counts_invalid", "path": rel})
            if rel == "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band20-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_VALIDATED":
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band20_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band24-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_PARTIAL_NOT_COMPLETION" or receipt.get("band_starts_scanned") != [24]:
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band24_bad_scope", "path": rel, "verdict": receipt.get("verdict"), "bands": receipt.get("band_starts_scanned")})
                if receipt.get("documents_censused") != 3806884 or receipt.get("collision_bucket_count") != 28292 or receipt.get("max_bucket_size") != 1761:
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band24_counts_invalid", "path": rel})
            if rel == "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band24-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_VALIDATED":
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band24_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band28-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_PARTIAL_NOT_COMPLETION" or receipt.get("band_starts_scanned") != [28]:
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band28_bad_scope", "path": rel, "verdict": receipt.get("verdict"), "bands": receipt.get("band_starts_scanned")})
                if receipt.get("documents_censused") != 3806884 or receipt.get("collision_bucket_count") != 28764 or receipt.get("max_bucket_size") != 2147:
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band28_counts_invalid", "path": rel})
            if rel == "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band28-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_VALIDATED":
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band28_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band32-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_PARTIAL_NOT_COMPLETION" or receipt.get("band_starts_scanned") != [32]:
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band32_bad_scope", "path": rel, "verdict": receipt.get("verdict"), "bands": receipt.get("band_starts_scanned")})
                if receipt.get("documents_censused") != 3806884 or receipt.get("collision_bucket_count") != 28691 or receipt.get("max_bucket_size") != 2856:
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band32_counts_invalid", "path": rel})
            if rel == "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band32-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_VALIDATED":
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band32_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band36-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_PARTIAL_NOT_COMPLETION" or receipt.get("band_starts_scanned") != [36]:
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band36_bad_scope", "path": rel, "verdict": receipt.get("verdict"), "bands": receipt.get("band_starts_scanned")})
                if receipt.get("documents_censused") != 3806884 or receipt.get("collision_bucket_count") != 28850 or receipt.get("max_bucket_size") != 1318:
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band36_counts_invalid", "path": rel})
            if rel == "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band36-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_VALIDATED":
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band36_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band40-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_PARTIAL_NOT_COMPLETION" or receipt.get("band_starts_scanned") != [40]:
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band40_bad_scope", "path": rel, "verdict": receipt.get("verdict"), "bands": receipt.get("band_starts_scanned")})
                if receipt.get("documents_censused") != 3806884 or receipt.get("collision_bucket_count") != 29705 or receipt.get("max_bucket_size") != 4898:
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band40_counts_invalid", "path": rel})
            if rel == "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band40-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_VALIDATED":
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band40_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band44-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_PARTIAL_NOT_COMPLETION" or receipt.get("band_starts_scanned") != [44]:
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band44_bad_scope", "path": rel, "verdict": receipt.get("verdict"), "bands": receipt.get("band_starts_scanned")})
                if receipt.get("documents_censused") != 3806884 or receipt.get("collision_bucket_count") != 29276 or receipt.get("max_bucket_size") != 630:
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band44_counts_invalid", "path": rel})
            if rel == "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band44-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_VALIDATED":
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band44_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band48-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_PARTIAL_NOT_COMPLETION" or receipt.get("band_starts_scanned") != [48]:
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band48_bad_scope", "path": rel, "verdict": receipt.get("verdict"), "bands": receipt.get("band_starts_scanned")})
                if receipt.get("documents_censused") != 3806884 or receipt.get("collision_bucket_count") != 28289 or receipt.get("max_bucket_size") != 5741:
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band48_counts_invalid", "path": rel})
            if rel == "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band48-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_VALIDATED":
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band48_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band52-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_PARTIAL_NOT_COMPLETION" or receipt.get("band_starts_scanned") != [52]:
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band52_bad_scope", "path": rel, "verdict": receipt.get("verdict"), "bands": receipt.get("band_starts_scanned")})
                if receipt.get("documents_censused") != 3806884 or receipt.get("collision_bucket_count") != 28356 or receipt.get("max_bucket_size") != 1019:
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band52_counts_invalid", "path": rel})
            if rel == "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band52-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_VALIDATED":
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band52_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band56-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_PARTIAL_NOT_COMPLETION" or receipt.get("band_starts_scanned") != [56]:
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band56_bad_scope", "path": rel, "verdict": receipt.get("verdict"), "bands": receipt.get("band_starts_scanned")})
                if receipt.get("documents_censused") != 3806884 or receipt.get("collision_bucket_count") != 29178 or receipt.get("max_bucket_size") != 2389:
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band56_counts_invalid", "path": rel})
            if rel == "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band56-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_VALIDATED":
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band56_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band60-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_PARTIAL_NOT_COMPLETION" or receipt.get("band_starts_scanned") != [60]:
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band60_bad_scope", "path": rel, "verdict": receipt.get("verdict"), "bands": receipt.get("band_starts_scanned")})
                if receipt.get("documents_censused") != 3806884 or receipt.get("collision_bucket_count") != 29320 or receipt.get("max_bucket_size") != 907:
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band60_counts_invalid", "path": rel})
            if rel == "receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band60-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_BUCKET_CENSUS_V4_VALIDATED":
                    failures.append({"code": "cumulative_filtered_lsh_census_v4_band60_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-cumulative-filtered-lsh-candidate-index-v4-band48-2026-07-01.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V4_MATERIALIZED_NOT_COMPLETION" or receipt.get("band_starts_materialized") != [48]:
                    failures.append({"code": "cumulative_filtered_lsh_candidate_index_v4_band48_bad_scope", "path": rel, "verdict": receipt.get("verdict"), "bands": receipt.get("band_starts_materialized")})
                if receipt.get("collision_bucket_count") != 28289 or receipt.get("candidate_pair_upper_bound_before_deduplication") != 20991666 or receipt.get("max_bucket_size") != 5741:
                    failures.append({"code": "cumulative_filtered_lsh_candidate_index_v4_band48_counts_invalid", "path": rel})
                if "not exact Jaccard adjudication" not in str(receipt.get("scope_limit", "")):
                    failures.append({"code": "cumulative_filtered_lsh_candidate_index_v4_band48_completion_guard_missing", "path": rel})
            if rel == "receipts/4090-cumulative-filtered-lsh-candidate-index-v4-band48-validation-2026-07-01.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V4_VALIDATED":
                    failures.append({"code": "cumulative_filtered_lsh_candidate_index_v4_band48_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-cumulative-filtered-lsh-candidate-index-v4-band48-adjudication-partial25-2026-07-01.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V4_EXACT_ADJUDICATION_CROSSINGS_FOUND_NOT_COMPLETION" or receipt.get("partial_index_adjudication") is not True:
                    failures.append({"code": "cumulative_filtered_lsh_candidate_index_v4_band48_partial_adjudication_bad_scope", "path": rel, "verdict": receipt.get("verdict")})
                if receipt.get("index_rows_adjudicated") != 25 or receipt.get("crossing_pair_count") != 17 or receipt.get("max_exact_jaccard_observed") != 0.970803:
                    failures.append({"code": "cumulative_filtered_lsh_candidate_index_v4_band48_partial_adjudication_counts_invalid", "path": rel})
            if rel == "receipts/4090-cumulative-filtered-lsh-candidate-index-v4-band48-adjudication-partial25-validation-2026-07-01.json":
                if receipt.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V4_EXACT_ADJUDICATION_VALIDATED":
                    failures.append({"code": "cumulative_filtered_lsh_candidate_index_v4_band48_partial_adjudication_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-cumulative-filtered-lsh-candidate-index-v4-band48-adjudication-partial25-remediation-2026-07-01.json":
                if receipt.get("verdict") != "C1_LSH_CANDIDATE_ADJUDICATION_V4_REMEDIATION_PACKET_READY_NOT_COMPLETION":
                    failures.append({"code": "cumulative_filtered_lsh_candidate_index_v4_band48_partial_remediation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                if receipt.get("remediation_exclusion_document_count") != 14 or receipt.get("cluster_count") != 12 or receipt.get("existing_cumulative_manifest_overlap_count") != 0:
                    failures.append({"code": "cumulative_filtered_lsh_candidate_index_v4_band48_partial_remediation_counts_invalid", "path": rel})
            if "full-stack-lm-loss-probe" in rel and not rel.endswith("-parse.json"):
                if receipt.get("verdict") != "FULL_STACK_LM_LOSS_PROBE_NOT_COMPLETION":
                    failures.append({"code": "full_stack_lm_loss_probe_receipt_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                shape = receipt.get("probe_shape", {})
                if shape.get("seq_len") != 2048 or shape.get("vocab_size") != 32768 or shape.get("hidden") != 2048 or shape.get("layers_executed") != 19:
                    failures.append({"code": "full_stack_lm_loss_probe_shape_mismatch", "path": rel, "shape": shape})
                if receipt.get("uses_full_lm_head_loss") is not True or receipt.get("uses_hidden_state_surrogate_loss") is not False:
                    failures.append({"code": "full_stack_lm_loss_controls_missing", "path": rel})
            if rel == "receipts/4090-training-throughput-gap-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_TRAINING_THROUGHPUT_GAP_VALIDATED":
                    failures.append({"code": "training_throughput_gap_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                ratio = receipt.get("best_measured_to_required_ratio")
                if not isinstance(ratio, (int, float)) or ratio >= 1.0:
                    failures.append({"code": "training_throughput_gap_ratio_not_blocking", "path": rel, "ratio": ratio})
                if "cannot complete" not in str(receipt.get("c1_completion_gate", "")):
                    failures.append({"code": "training_throughput_completion_gate_missing", "path": rel})
            if "real-data-lm-loss-probe" in rel:
                if receipt.get("verdict") != "FULL_STACK_LM_LOSS_PROBE_NOT_COMPLETION":
                    failures.append({"code": "real_data_lm_loss_probe_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                if receipt.get("uses_real_token_data") is not True:
                    failures.append({"code": "real_data_lm_loss_probe_not_real_data", "path": rel})
                window = receipt.get("real_data_window") or {}
                if window.get("token_shard_receipt") != "receipts/token-shards-v0-20260611T170047Z.json" or window.get("separator_tokens_in_window") != 0:
                    failures.append({"code": "real_data_lm_loss_window_not_pinned_clean", "path": rel, "window": window})
            if rel == "receipts/4090-real-data-lm-loss-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_REAL_DATA_LM_LOSS_PROBE_VALIDATED":
                    failures.append({"code": "real_data_lm_loss_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-real-data-checkpoint-resume-probe-pretraining-equivalent.json":
                if receipt.get("verdict") != "FULL_STACK_LM_LOSS_PROBE_NOT_COMPLETION":
                    failures.append({"code": "checkpoint_resume_probe_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                ckpt = receipt.get("checkpoint_resume") or {}
                if ckpt.get("enabled") is not True or ckpt.get("checkpoint_contains_optimizer_state") is not True or ckpt.get("resumed_for_additional_steps") != 1:
                    failures.append({"code": "checkpoint_resume_probe_invalid", "path": rel, "checkpoint_resume": ckpt})
                if ckpt.get("checkpoint_path_recorded") is not False or ckpt.get("checkpoint_deleted_after_hash") is not True:
                    failures.append({"code": "checkpoint_resume_public_path_or_cleanup_invalid", "path": rel, "checkpoint_resume": ckpt})
            if rel == "receipts/4090-checkpoint-resume-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_CHECKPOINT_RESUME_PROBE_VALIDATED":
                    failures.append({"code": "checkpoint_resume_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-real-data-multistep-stability-probe-pretraining-equivalent.json":
                if receipt.get("verdict") != "FULL_STACK_LM_LOSS_PROBE_NOT_COMPLETION":
                    failures.append({"code": "multistep_stability_probe_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                if receipt.get("uses_real_token_data") is not True or receipt.get("steps_completed", 0) < 4 or receipt.get("loss_is_finite_all_steps") is not True:
                    failures.append({"code": "multistep_stability_probe_invalid", "path": rel, "steps_completed": receipt.get("steps_completed"), "finite": receipt.get("loss_is_finite_all_steps")})
                if receipt.get("estimated_stack_training_tflops_lower_bound", 0) >= receipt.get("full_config_required_sustained_tflops", 0):
                    failures.append({"code": "multistep_stability_probe_should_not_be_completion", "path": rel, "measured": receipt.get("estimated_stack_training_tflops_lower_bound"), "required": receipt.get("full_config_required_sustained_tflops")})
            if rel == "receipts/4090-multistep-stability-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_MULTISTEP_STABILITY_PROBE_VALIDATED":
                    failures.append({"code": "multistep_stability_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-real-data-steady-state-throughput-probe-pretraining-equivalent.json":
                if receipt.get("verdict") != "FULL_STACK_LM_LOSS_PROBE_NOT_COMPLETION":
                    failures.append({"code": "steady_state_throughput_probe_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                measured = receipt.get("estimated_stack_training_tflops_lower_bound")
                required = receipt.get("full_config_required_sustained_tflops")
                if receipt.get("uses_real_token_data") is not True or receipt.get("steps_completed", 0) < 16 or measured is None or required is None or measured < required:
                    failures.append({"code": "steady_state_throughput_probe_invalid", "path": rel, "steps_completed": receipt.get("steps_completed"), "measured": measured, "required": required})
                if "not long-run throughput" not in str(receipt.get("completion_limit", "")):
                    failures.append({"code": "steady_state_completion_guard_missing", "path": rel})
            if rel == "receipts/4090-steady-state-throughput-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_STEADY_STATE_THROUGHPUT_PROBE_VALIDATED":
                    failures.append({"code": "steady_state_throughput_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-real-data-varied-window-throughput-probe-pretraining-equivalent.json":
                if receipt.get("verdict") != "FULL_STACK_LM_LOSS_PROBE_NOT_COMPLETION":
                    failures.append({"code": "varied_window_throughput_probe_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                measured = receipt.get("estimated_stack_training_tflops_lower_bound")
                required = receipt.get("full_config_required_sustained_tflops")
                if (
                    receipt.get("uses_real_token_data") is not True
                    or receipt.get("uses_varied_real_token_windows") is not True
                    or receipt.get("steps_completed", 0) < 16
                    or receipt.get("real_data_unique_input_window_count") != receipt.get("steps_completed")
                    or measured is None
                    or required is None
                    or measured < required
                ):
                    failures.append({"code": "varied_window_throughput_probe_invalid", "path": rel, "steps_completed": receipt.get("steps_completed"), "unique_windows": receipt.get("real_data_unique_input_window_count"), "measured": measured, "required": required})
                if "not a real dataloader long-run" not in str(receipt.get("completion_limit", "")):
                    failures.append({"code": "varied_window_completion_guard_missing", "path": rel})
            if rel == "receipts/4090-varied-window-throughput-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_VARIED_WINDOW_THROUGHPUT_PROBE_VALIDATED":
                    failures.append({"code": "varied_window_throughput_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-real-data-streamed-window-throughput-probe-pretraining-equivalent.json":
                if receipt.get("verdict") != "FULL_STACK_LM_LOSS_PROBE_NOT_COMPLETION":
                    failures.append({"code": "streamed_window_throughput_probe_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                measured = receipt.get("estimated_stack_training_tflops_lower_bound")
                required = receipt.get("full_config_required_sustained_tflops")
                stream = receipt.get("real_data_stream") or {}
                if (
                    receipt.get("uses_real_token_data") is not True
                    or receipt.get("uses_varied_real_token_windows") is not True
                    or receipt.get("includes_dataloader_timing") is not True
                    or receipt.get("dataloader_window_loaded_inside_timed_step") is not True
                    or stream.get("window_search_and_tensor_source_inside_timed_step") is not True
                    or receipt.get("steps_completed", 0) < 16
                    or receipt.get("real_data_unique_input_window_count") != receipt.get("steps_completed")
                    or measured is None
                    or required is None
                    or measured < required
                ):
                    failures.append({"code": "streamed_window_throughput_probe_invalid", "path": rel, "steps_completed": receipt.get("steps_completed"), "unique_windows": receipt.get("real_data_unique_input_window_count"), "measured": measured, "required": required})
                if "not a long-run training receipt" not in str(receipt.get("completion_limit", "")):
                    failures.append({"code": "streamed_window_completion_guard_missing", "path": rel})
            if rel == "receipts/4090-streamed-window-throughput-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_STREAMED_WINDOW_THROUGHPUT_PROBE_VALIDATED":
                    failures.append({"code": "streamed_window_throughput_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-real-data-streamed-128-window-throughput-probe-pretraining-equivalent.json":
                if receipt.get("verdict") != "FULL_STACK_LM_LOSS_PROBE_NOT_COMPLETION":
                    failures.append({"code": "streamed_128_window_probe_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                measured = receipt.get("estimated_stack_training_tflops_lower_bound")
                required = receipt.get("full_config_required_sustained_tflops")
                if receipt.get("steps_completed", 0) < 128 or receipt.get("real_data_unique_input_window_count") != 128 or measured is None or required is None or measured < required:
                    failures.append({"code": "streamed_128_window_probe_invalid", "path": rel, "steps_completed": receipt.get("steps_completed"), "unique_windows": receipt.get("real_data_unique_input_window_count"), "measured": measured, "required": required})
                if "not a long-run training receipt" not in str(receipt.get("completion_limit", "")):
                    failures.append({"code": "streamed_128_window_completion_guard_missing", "path": rel})
            if rel == "receipts/4090-streamed-128-window-throughput-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_STREAMED_128_WINDOW_THROUGHPUT_VALIDATED":
                    failures.append({"code": "streamed_128_window_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-real-data-streamed-128-window-power-sampled-probe-pretraining-equivalent.json":
                if receipt.get("verdict") != "FULL_STACK_LM_LOSS_PROBE_NOT_COMPLETION":
                    failures.append({"code": "power_sampled_probe_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                measured = receipt.get("estimated_stack_training_tflops_lower_bound")
                required = receipt.get("full_config_required_sustained_tflops")
                if receipt.get("steps_completed", 0) < 128 or receipt.get("real_data_unique_input_window_count") != 128 or measured is None or required is None or measured < required:
                    failures.append({"code": "power_sampled_probe_invalid", "path": rel, "steps_completed": receipt.get("steps_completed"), "unique_windows": receipt.get("real_data_unique_input_window_count"), "measured": measured, "required": required})
            if rel == "receipts/4090-power-sampled-128-window-throughput-2026-06-30.json":
                sampling = receipt.get("power_sampling") or {}
                if receipt.get("verdict") != "C1_POWER_SAMPLED_128_WINDOW_THROUGHPUT_READY_NOT_COMPLETION":
                    failures.append({"code": "power_sampled_receipt_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                if receipt.get("child_returncode") != 0 or sampling.get("sample_count", 0) < 5 or sampling.get("energy_joules_trapezoid", 0) <= 0:
                    failures.append({"code": "power_sampled_receipt_invalid", "path": rel, "child_returncode": receipt.get("child_returncode"), "sampling": sampling})
                if "not full-run energy accounting" not in str(receipt.get("completion_limit", "")):
                    failures.append({"code": "power_sampled_completion_guard_missing", "path": rel})
            if rel == "receipts/4090-power-sampled-128-window-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_POWER_SAMPLED_128_WINDOW_THROUGHPUT_VALIDATED":
                    failures.append({"code": "power_sampled_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-real-data-checkpoint-cadence-probe-pretraining-equivalent.json":
                if receipt.get("verdict") != "FULL_STACK_LM_LOSS_PROBE_NOT_COMPLETION":
                    failures.append({"code": "checkpoint_cadence_probe_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                ckpt = receipt.get("checkpoint_cadence") or {}
                measured = receipt.get("estimated_stack_training_tflops_lower_bound")
                required = receipt.get("full_config_required_sustained_tflops")
                if ckpt.get("enabled") is not True or ckpt.get("checkpoint_event_count") < 2 or ckpt.get("all_checkpoints_deleted_after_hash") is not True:
                    failures.append({"code": "checkpoint_cadence_probe_invalid", "path": rel, "checkpoint_cadence": ckpt})
                if measured is None or required is None or measured >= required:
                    failures.append({"code": "checkpoint_cadence_must_preserve_overhead_gap", "path": rel, "measured": measured, "required": required})
                if "not a long-run checkpoint policy receipt" not in str(receipt.get("completion_limit", "")):
                    failures.append({"code": "checkpoint_cadence_completion_guard_missing", "path": rel})
            if rel == "receipts/4090-checkpoint-cadence-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_CHECKPOINT_CADENCE_PROBE_VALIDATED":
                    failures.append({"code": "checkpoint_cadence_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-real-data-eval-accounting-probe-pretraining-equivalent.json":
                if receipt.get("verdict") != "FULL_STACK_LM_LOSS_PROBE_NOT_COMPLETION":
                    failures.append({"code": "eval_accounting_probe_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                eval_accounting = receipt.get("eval_accounting") or {}
                measured = receipt.get("estimated_stack_training_tflops_lower_bound")
                required = receipt.get("full_config_required_sustained_tflops")
                if eval_accounting.get("enabled") is not True or eval_accounting.get("eval_window_count") != 2 or eval_accounting.get("eval_uses_no_grad") is not True:
                    failures.append({"code": "eval_accounting_probe_invalid", "path": rel, "eval_accounting": eval_accounting})
                if measured is None or required is None or measured >= required:
                    failures.append({"code": "eval_accounting_must_preserve_overhead_gap", "path": rel, "measured": measured, "required": required})
                if "not a full external evaluation suite" not in str(receipt.get("completion_limit", "")):
                    failures.append({"code": "eval_accounting_completion_guard_missing", "path": rel})
            if rel == "receipts/4090-eval-accounting-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_EVAL_ACCOUNTING_PROBE_VALIDATED":
                    failures.append({"code": "eval_accounting_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-real-data-recovery-accounting-probe-pretraining-equivalent.json":
                if receipt.get("verdict") != "FULL_STACK_LM_LOSS_PROBE_NOT_COMPLETION":
                    failures.append({"code": "recovery_accounting_probe_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                recovery = receipt.get("recovery_accounting") or {}
                measured = receipt.get("estimated_stack_training_tflops_lower_bound")
                required = receipt.get("full_config_required_sustained_tflops")
                if recovery.get("enabled") is not True or recovery.get("checkpoint_deleted_after_hash") is not True or recovery.get("recovery_included_in_total_elapsed") is not True:
                    failures.append({"code": "recovery_accounting_probe_invalid", "path": rel, "recovery": recovery})
                if measured is None or required is None or measured >= required:
                    failures.append({"code": "recovery_accounting_must_preserve_overhead_gap", "path": rel, "measured": measured, "required": required})
                if "not a long-run recovery policy receipt" not in str(receipt.get("completion_limit", "")):
                    failures.append({"code": "recovery_accounting_completion_guard_missing", "path": rel})
            if rel == "receipts/4090-recovery-accounting-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_RECOVERY_ACCOUNTING_PROBE_VALIDATED":
                    failures.append({"code": "recovery_accounting_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-integrated-policy-probe-pretraining-equivalent.json":
                if receipt.get("verdict") != "FULL_STACK_LM_LOSS_PROBE_NOT_COMPLETION":
                    failures.append({"code": "integrated_policy_probe_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                if receipt.get("steps_completed") != 8 or receipt.get("checkpoint_cadence", {}).get("checkpoint_event_count") != 2:
                    failures.append({"code": "integrated_policy_probe_scope_mismatch", "path": rel, "steps": receipt.get("steps_completed"), "cadence": receipt.get("checkpoint_cadence")})
                if receipt.get("eval_accounting", {}).get("eval_window_count") != 2 or receipt.get("recovery_accounting", {}).get("recovery_window_base") != 10:
                    failures.append({"code": "integrated_policy_eval_recovery_mismatch", "path": rel})
                measured = receipt.get("estimated_stack_training_tflops_lower_bound")
                required = receipt.get("full_config_required_sustained_tflops")
                if measured is None or required is None or measured >= required:
                    failures.append({"code": "integrated_policy_must_preserve_overhead_gap", "path": rel, "measured": measured, "required": required})
            if rel == "receipts/4090-integrated-policy-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_INTEGRATED_POLICY_PROBE_VALIDATED":
                    failures.append({"code": "integrated_policy_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-policy-amortized-256-window-probe-pretraining-equivalent.json":
                if receipt.get("verdict") != "FULL_STACK_LM_LOSS_PROBE_NOT_COMPLETION":
                    failures.append({"code": "policy_amortized_probe_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                measured = receipt.get("estimated_stack_training_tflops_lower_bound")
                required = receipt.get("full_config_required_sustained_tflops")
                cadence = receipt.get("checkpoint_cadence", {})
                eval_accounting = receipt.get("eval_accounting", {})
                recovery = receipt.get("recovery_accounting", {})
                if receipt.get("steps_completed") != 256 or cadence.get("checkpoint_event_count") != 2 or cadence.get("checkpoint_interval_steps") != 128:
                    failures.append({"code": "policy_amortized_checkpoint_scope_mismatch", "path": rel, "steps": receipt.get("steps_completed"), "cadence": cadence})
                if eval_accounting.get("eval_window_count") != 4 or recovery.get("recovery_window_base") != 260:
                    failures.append({"code": "policy_amortized_eval_recovery_mismatch", "path": rel, "eval": eval_accounting, "recovery": recovery})
                if measured is None or required is None or measured >= required:
                    failures.append({"code": "policy_amortized_must_preserve_overhead_gap", "path": rel, "measured": measured, "required": required})
            if rel == "receipts/4090-policy-amortized-256-window-power-2026-06-30.json":
                sampling = receipt.get("power_sampling") or {}
                if receipt.get("verdict") != "C1_POLICY_AMORTIZED_256_WINDOW_READY_NOT_COMPLETION":
                    failures.append({"code": "policy_amortized_power_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                if receipt.get("child_returncode") != 0 or sampling.get("sample_count", 0) < 20 or sampling.get("energy_joules_trapezoid", 0) <= 0:
                    failures.append({"code": "policy_amortized_power_invalid", "path": rel, "child_returncode": receipt.get("child_returncode"), "sampling": sampling})
                if "not full-run energy accounting" not in str(receipt.get("completion_limit", "")):
                    failures.append({"code": "policy_amortized_power_completion_guard_missing", "path": rel})
            if rel == "receipts/4090-policy-amortized-256-window-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_POLICY_AMORTIZED_256_WINDOW_VALIDATED":
                    failures.append({"code": "policy_amortized_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if rel == "receipts/4090-policy-optimized-1024-window-probe-pretraining-equivalent.json":
                if receipt.get("verdict") != "FULL_STACK_LM_LOSS_PROBE_NOT_COMPLETION":
                    failures.append({"code": "policy_optimized_probe_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                measured = receipt.get("estimated_stack_training_tflops_lower_bound")
                required = receipt.get("full_config_required_sustained_tflops")
                cadence = receipt.get("checkpoint_cadence", {})
                eval_accounting = receipt.get("eval_accounting", {})
                recovery = receipt.get("recovery_accounting", {})
                if receipt.get("steps_completed") != 1024 or cadence.get("checkpoint_event_count") != 1 or cadence.get("checkpoint_interval_steps") != 1024:
                    failures.append({"code": "policy_optimized_checkpoint_scope_mismatch", "path": rel, "steps": receipt.get("steps_completed"), "cadence": cadence})
                if eval_accounting.get("eval_window_count") != 4 or recovery.get("recovery_window_base") != 1028:
                    failures.append({"code": "policy_optimized_eval_recovery_mismatch", "path": rel, "eval": eval_accounting, "recovery": recovery})
                if measured is None or required is None or measured < required:
                    failures.append({"code": "policy_optimized_must_clear_overhead_threshold", "path": rel, "measured": measured, "required": required})
            if rel == "receipts/4090-policy-optimized-1024-window-power-2026-06-30.json":
                sampling = receipt.get("power_sampling") or {}
                if receipt.get("verdict") != "C1_POLICY_OPTIMIZED_1024_WINDOW_READY_NOT_COMPLETION":
                    failures.append({"code": "policy_optimized_power_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                if receipt.get("child_returncode") != 0 or sampling.get("sample_count", 0) < 100 or sampling.get("energy_joules_trapezoid", 0) <= 0:
                    failures.append({"code": "policy_optimized_power_invalid", "path": rel, "child_returncode": receipt.get("child_returncode"), "sampling": sampling})
                if "not full-run energy accounting" not in str(receipt.get("completion_limit", "")):
                    failures.append({"code": "policy_optimized_power_completion_guard_missing", "path": rel})
            if rel == "receipts/4090-policy-optimized-1024-window-validation-2026-06-30.json":
                if receipt.get("verdict") != "C1_POLICY_OPTIMIZED_1024_WINDOW_VALIDATED":
                    failures.append({"code": "policy_optimized_validation_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
            if "native-kernel-probe" in rel and not rel.endswith("-parse.json"):
                if receipt.get("verdict") != "NATIVE_KERNEL_PROBE_NOT_COMPLETION":
                    failures.append({"code": "native_kernel_probe_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                if receipt.get("toolchain", {}).get("triton_available") is not True or receipt.get("toolchain", {}).get("nvcc_available") is not True:
                    failures.append({"code": "native_kernel_toolchain_missing", "path": rel, "toolchain": receipt.get("toolchain")})
                if not receipt.get("benchmarks"):
                    failures.append({"code": "native_kernel_benchmarks_missing", "path": rel})
            if "full-memory-probe" in rel and not rel.endswith("-parse.json"):
                if receipt.get("verdict") != "FULL_CONFIG_MEMORY_PROBE_NOT_COMPLETION":
                    failures.append({"code": "full_memory_probe_receipt_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                if receipt.get("fits_memory_probe") is not True:
                    failures.append({"code": "full_memory_probe_did_not_fit", "path": rel, "actual": receipt.get("fits_memory_probe")})
            if "governed-probe" in rel and not rel.endswith("-parse.json"):
                if receipt.get("verdict") != "GOVERNED_PROBE_NOT_COMPLETION":
                    failures.append({"code": "governed_probe_receipt_bad_verdict", "path": rel, "verdict": receipt.get("verdict")})
                if receipt.get("steps_completed", 0) < 1:
                    failures.append({"code": "governed_probe_no_steps", "path": rel, "actual": receipt.get("steps_completed")})

    v5_manifest = read_json(root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v5-2026-07-01.json") if (root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v5-2026-07-01.json").exists() else {}
    if v5_manifest.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V5_READY_NOT_COMPLETION":
        failures.append({"code": "v5_cumulative_exclusion_manifest_bad_verdict", "actual": v5_manifest.get("verdict")})
    if v5_manifest.get("exclusion_document_count") != 1733 or v5_manifest.get("exclusion_token_floor") != 3039393 or v5_manifest.get("source_overlap_count") != 0:
        failures.append({"code": "v5_cumulative_exclusion_manifest_counts_invalid", "actual": v5_manifest})
    v5_manifest_validation = read_json(root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v5-validation-2026-07-01.json") if (root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v5-validation-2026-07-01.json").exists() else {}
    if v5_manifest_validation.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V5_VALIDATED":
        failures.append({"code": "v5_cumulative_exclusion_manifest_validation_bad_verdict", "actual": v5_manifest_validation.get("verdict")})
    v5_view = read_json(root / "receipts/4090-cumulative-filtered-corpus-view-v5-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-corpus-view-v5-2026-07-01.json").exists() else {}
    filtered = v5_view.get("cumulative_filtered_view", {})
    if v5_view.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V5_READY_NOT_COMPLETION":
        failures.append({"code": "v5_cumulative_filtered_view_bad_verdict", "actual": v5_view.get("verdict")})
    if filtered.get("excluded_document_count") != 1733 or filtered.get("excluded_token_floor") != 3039393 or filtered.get("remaining_document_count") != 4234725 or filtered.get("remaining_content_token_floor") != 6974829365 or filtered.get("binary_shards_rewritten") is not False:
        failures.append({"code": "v5_cumulative_filtered_view_counts_invalid", "actual": filtered})
    v5_view_validation = read_json(root / "receipts/4090-cumulative-filtered-corpus-view-v5-validation-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-corpus-view-v5-validation-2026-07-01.json").exists() else {}
    if v5_view_validation.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V5_VALIDATED":
        failures.append({"code": "v5_cumulative_filtered_view_validation_bad_verdict", "actual": v5_view_validation.get("verdict")})

    v5_candidate = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v5-band48-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v5-band48-2026-07-01.json").exists() else {}
    if v5_candidate.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V5_MATERIALIZED_NOT_COMPLETION":
        failures.append({"code": "v5_lsh_candidate_index_bad_verdict", "actual": v5_candidate.get("verdict")})
    if v5_candidate.get("collision_bucket_count") != 28278 or v5_candidate.get("candidate_pair_upper_bound_before_deduplication") != 20991648 or v5_candidate.get("excluded_document_count") != 1733:
        failures.append({"code": "v5_lsh_candidate_index_counts_invalid", "actual": v5_candidate})
    v5_candidate_validation = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v5-band48-validation-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v5-band48-validation-2026-07-01.json").exists() else {}
    if v5_candidate_validation.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V5_VALIDATED":
        failures.append({"code": "v5_lsh_candidate_index_validation_bad_verdict", "actual": v5_candidate_validation.get("verdict")})
    v5_adjudication = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v5-band48-adjudication-partial25-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v5-band48-adjudication-partial25-2026-07-01.json").exists() else {}
    if v5_adjudication.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V5_EXACT_ADJUDICATION_CROSSINGS_FOUND_NOT_COMPLETION":
        failures.append({"code": "v5_lsh_partial_adjudication_bad_verdict", "actual": v5_adjudication.get("verdict")})
    if v5_adjudication.get("index_rows_adjudicated") != 25 or v5_adjudication.get("crossing_pair_count") != 18 or v5_adjudication.get("max_exact_jaccard_observed") != 0.975309:
        failures.append({"code": "v5_lsh_partial_adjudication_counts_invalid", "actual": v5_adjudication})
    v5_adjudication_validation = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v5-band48-adjudication-partial25-validation-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v5-band48-adjudication-partial25-validation-2026-07-01.json").exists() else {}
    if v5_adjudication_validation.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V5_EXACT_ADJUDICATION_VALIDATED":
        failures.append({"code": "v5_lsh_partial_adjudication_validation_bad_verdict", "actual": v5_adjudication_validation.get("verdict")})
    v5_remediation = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v5-band48-adjudication-partial25-remediation-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v5-band48-adjudication-partial25-remediation-2026-07-01.json").exists() else {}
    if v5_remediation.get("verdict") != "C1_LSH_CANDIDATE_ADJUDICATION_V5_REMEDIATION_PACKET_READY_NOT_COMPLETION":
        failures.append({"code": "v5_lsh_partial_remediation_bad_verdict", "actual": v5_remediation.get("verdict")})
    if v5_remediation.get("remediation_exclusion_document_count") != 9 or v5_remediation.get("existing_cumulative_v5_manifest_overlap_count") != 0:
        failures.append({"code": "v5_lsh_partial_remediation_counts_invalid", "actual": v5_remediation})
    v6_manifest = read_json(root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v6-2026-07-01.json") if (root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v6-2026-07-01.json").exists() else {}
    if v6_manifest.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V6_READY_NOT_COMPLETION":
        failures.append({"code": "v6_cumulative_exclusion_manifest_bad_verdict", "actual": v6_manifest.get("verdict")})
    if v6_manifest.get("exclusion_document_count") != 1742 or v6_manifest.get("exclusion_token_floor") != 3050833 or v6_manifest.get("source_overlap_count") != 0:
        failures.append({"code": "v6_cumulative_exclusion_manifest_counts_invalid", "actual": v6_manifest})
    v6_manifest_validation = read_json(root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v6-validation-2026-07-01.json") if (root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v6-validation-2026-07-01.json").exists() else {}
    if v6_manifest_validation.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V6_VALIDATED":
        failures.append({"code": "v6_cumulative_exclusion_manifest_validation_bad_verdict", "actual": v6_manifest_validation.get("verdict")})
    v6_view = read_json(root / "receipts/4090-cumulative-filtered-corpus-view-v6-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-corpus-view-v6-2026-07-01.json").exists() else {}
    v6_filtered = v6_view.get("cumulative_filtered_view", {})
    if v6_view.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V6_READY_NOT_COMPLETION":
        failures.append({"code": "v6_cumulative_filtered_view_bad_verdict", "actual": v6_view.get("verdict")})
    if v6_filtered.get("excluded_document_count") != 1742 or v6_filtered.get("excluded_token_floor") != 3050833 or v6_filtered.get("remaining_document_count") != 4234716 or v6_filtered.get("remaining_content_token_floor") != 6974817925 or v6_filtered.get("binary_shards_rewritten") is not False:
        failures.append({"code": "v6_cumulative_filtered_view_counts_invalid", "actual": v6_filtered})
    v6_view_validation = read_json(root / "receipts/4090-cumulative-filtered-corpus-view-v6-validation-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-corpus-view-v6-validation-2026-07-01.json").exists() else {}
    if v6_view_validation.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V6_VALIDATED":
        failures.append({"code": "v6_cumulative_filtered_view_validation_bad_verdict", "actual": v6_view_validation.get("verdict")})

    v6_candidate = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v6-band48-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v6-band48-2026-07-01.json").exists() else {}
    if v6_candidate.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V6_MATERIALIZED_NOT_COMPLETION":
        failures.append({"code": "v6_lsh_candidate_index_bad_verdict", "actual": v6_candidate.get("verdict")})
    if v6_candidate.get("collision_bucket_count") != 28274 or v6_candidate.get("candidate_pair_upper_bound_before_deduplication") != 20991630 or v6_candidate.get("excluded_document_count") != 1742:
        failures.append({"code": "v6_lsh_candidate_index_counts_invalid", "actual": v6_candidate})
    v6_candidate_validation = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v6-band48-validation-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v6-band48-validation-2026-07-01.json").exists() else {}
    if v6_candidate_validation.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V6_VALIDATED":
        failures.append({"code": "v6_lsh_candidate_index_validation_bad_verdict", "actual": v6_candidate_validation.get("verdict")})
    v6_adjudication = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v6-band48-adjudication-partial25-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v6-band48-adjudication-partial25-2026-07-01.json").exists() else {}
    if v6_adjudication.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V6_EXACT_ADJUDICATION_CROSSINGS_FOUND_NOT_COMPLETION":
        failures.append({"code": "v6_lsh_partial_adjudication_bad_verdict", "actual": v6_adjudication.get("verdict")})
    if v6_adjudication.get("index_rows_adjudicated") != 25 or v6_adjudication.get("crossing_pair_count") != 3 or v6_adjudication.get("max_exact_jaccard_observed") != 0.978495:
        failures.append({"code": "v6_lsh_partial_adjudication_counts_invalid", "actual": v6_adjudication})
    v6_adjudication_validation = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v6-band48-adjudication-partial25-validation-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v6-band48-adjudication-partial25-validation-2026-07-01.json").exists() else {}
    if v6_adjudication_validation.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V6_EXACT_ADJUDICATION_VALIDATED":
        failures.append({"code": "v6_lsh_partial_adjudication_validation_bad_verdict", "actual": v6_adjudication_validation.get("verdict")})
    v6_remediation = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v6-band48-adjudication-partial25-remediation-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v6-band48-adjudication-partial25-remediation-2026-07-01.json").exists() else {}
    if v6_remediation.get("verdict") != "C1_LSH_CANDIDATE_ADJUDICATION_V6_REMEDIATION_PACKET_READY_NOT_COMPLETION":
        failures.append({"code": "v6_lsh_partial_remediation_bad_verdict", "actual": v6_remediation.get("verdict")})
    if v6_remediation.get("remediation_exclusion_document_count") != 3 or v6_remediation.get("existing_cumulative_v6_manifest_overlap_count") != 0:
        failures.append({"code": "v6_lsh_partial_remediation_counts_invalid", "actual": v6_remediation})
    v7_manifest = read_json(root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v7-2026-07-01.json") if (root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v7-2026-07-01.json").exists() else {}
    if v7_manifest.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V7_READY_NOT_COMPLETION":
        failures.append({"code": "v7_cumulative_exclusion_manifest_bad_verdict", "actual": v7_manifest.get("verdict")})
    if v7_manifest.get("exclusion_document_count") != 1745 or v7_manifest.get("exclusion_token_floor") != 3055337 or v7_manifest.get("source_overlap_count") != 0:
        failures.append({"code": "v7_cumulative_exclusion_manifest_counts_invalid", "actual": v7_manifest})
    v7_manifest_validation = read_json(root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v7-validation-2026-07-01.json") if (root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v7-validation-2026-07-01.json").exists() else {}
    if v7_manifest_validation.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V7_VALIDATED":
        failures.append({"code": "v7_cumulative_exclusion_manifest_validation_bad_verdict", "actual": v7_manifest_validation.get("verdict")})
    v7_view = read_json(root / "receipts/4090-cumulative-filtered-corpus-view-v7-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-corpus-view-v7-2026-07-01.json").exists() else {}
    v7_filtered = v7_view.get("cumulative_filtered_view", {})
    if v7_view.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V7_READY_NOT_COMPLETION":
        failures.append({"code": "v7_cumulative_filtered_view_bad_verdict", "actual": v7_view.get("verdict")})
    if v7_filtered.get("excluded_document_count") != 1745 or v7_filtered.get("excluded_token_floor") != 3055337 or v7_filtered.get("remaining_document_count") != 4234713 or v7_filtered.get("remaining_content_token_floor") != 6974813421 or v7_filtered.get("binary_shards_rewritten") is not False:
        failures.append({"code": "v7_cumulative_filtered_view_counts_invalid", "actual": v7_filtered})
    v7_view_validation = read_json(root / "receipts/4090-cumulative-filtered-corpus-view-v7-validation-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-corpus-view-v7-validation-2026-07-01.json").exists() else {}
    if v7_view_validation.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V7_VALIDATED":
        failures.append({"code": "v7_cumulative_filtered_view_validation_bad_verdict", "actual": v7_view_validation.get("verdict")})

    v7_candidate = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v7-band48-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v7-band48-2026-07-01.json").exists() else {}
    if v7_candidate.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V7_MATERIALIZED_NOT_COMPLETION":
        failures.append({"code": "v7_lsh_candidate_index_bad_verdict", "actual": v7_candidate.get("verdict")})
    if v7_candidate.get("collision_bucket_count") != 28271 or v7_candidate.get("candidate_pair_upper_bound_before_deduplication") != 20991627 or v7_candidate.get("excluded_document_count") != 1745:
        failures.append({"code": "v7_lsh_candidate_index_counts_invalid", "actual": v7_candidate})
    v7_candidate_validation = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v7-band48-validation-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v7-band48-validation-2026-07-01.json").exists() else {}
    if v7_candidate_validation.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V7_VALIDATED":
        failures.append({"code": "v7_lsh_candidate_index_validation_bad_verdict", "actual": v7_candidate_validation.get("verdict")})
    v7_adjudication = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v7-band48-adjudication-partial25-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v7-band48-adjudication-partial25-2026-07-01.json").exists() else {}
    if v7_adjudication.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V7_EXACT_ADJUDICATION_CROSSINGS_FOUND_NOT_COMPLETION":
        failures.append({"code": "v7_lsh_partial_adjudication_bad_verdict", "actual": v7_adjudication.get("verdict")})
    if v7_adjudication.get("index_rows_adjudicated") != 25 or v7_adjudication.get("crossing_pair_count") != 3 or v7_adjudication.get("max_exact_jaccard_observed") != 0.952118:
        failures.append({"code": "v7_lsh_partial_adjudication_counts_invalid", "actual": v7_adjudication})
    v7_adjudication_validation = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v7-band48-adjudication-partial25-validation-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v7-band48-adjudication-partial25-validation-2026-07-01.json").exists() else {}
    if v7_adjudication_validation.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V7_EXACT_ADJUDICATION_VALIDATED":
        failures.append({"code": "v7_lsh_partial_adjudication_validation_bad_verdict", "actual": v7_adjudication_validation.get("verdict")})
    v7_remediation = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v7-band48-adjudication-partial25-remediation-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v7-band48-adjudication-partial25-remediation-2026-07-01.json").exists() else {}
    if v7_remediation.get("verdict") != "C1_LSH_CANDIDATE_ADJUDICATION_V7_REMEDIATION_PACKET_READY_NOT_COMPLETION":
        failures.append({"code": "v7_lsh_partial_remediation_bad_verdict", "actual": v7_remediation.get("verdict")})
    if v7_remediation.get("remediation_exclusion_document_count") != 2 or v7_remediation.get("existing_cumulative_v7_manifest_overlap_count") != 0:
        failures.append({"code": "v7_lsh_partial_remediation_counts_invalid", "actual": v7_remediation})
    v8_manifest = read_json(root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v8-2026-07-01.json") if (root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v8-2026-07-01.json").exists() else {}
    if v8_manifest.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V8_READY_NOT_COMPLETION":
        failures.append({"code": "v8_cumulative_exclusion_manifest_bad_verdict", "actual": v8_manifest.get("verdict")})
    if v8_manifest.get("exclusion_document_count") != 1747 or v8_manifest.get("exclusion_token_floor") != 3058613 or v8_manifest.get("source_overlap_count") != 0:
        failures.append({"code": "v8_cumulative_exclusion_manifest_counts_invalid", "actual": v8_manifest})
    v8_manifest_validation = read_json(root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v8-validation-2026-07-01.json") if (root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v8-validation-2026-07-01.json").exists() else {}
    if v8_manifest_validation.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V8_VALIDATED":
        failures.append({"code": "v8_cumulative_exclusion_manifest_validation_bad_verdict", "actual": v8_manifest_validation.get("verdict")})
    v8_view = read_json(root / "receipts/4090-cumulative-filtered-corpus-view-v8-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-corpus-view-v8-2026-07-01.json").exists() else {}
    v8_filtered = v8_view.get("cumulative_filtered_view", {})
    if v8_view.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V8_READY_NOT_COMPLETION":
        failures.append({"code": "v8_cumulative_filtered_view_bad_verdict", "actual": v8_view.get("verdict")})
    if v8_filtered.get("excluded_document_count") != 1747 or v8_filtered.get("excluded_token_floor") != 3058613 or v8_filtered.get("remaining_document_count") != 4234711 or v8_filtered.get("remaining_content_token_floor") != 6974810145 or v8_filtered.get("binary_shards_rewritten") is not False:
        failures.append({"code": "v8_cumulative_filtered_view_counts_invalid", "actual": v8_filtered})
    v8_view_validation = read_json(root / "receipts/4090-cumulative-filtered-corpus-view-v8-validation-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-corpus-view-v8-validation-2026-07-01.json").exists() else {}
    if v8_view_validation.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V8_VALIDATED":
        failures.append({"code": "v8_cumulative_filtered_view_validation_bad_verdict", "actual": v8_view_validation.get("verdict")})

    v8_candidate = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v8-band48-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v8-band48-2026-07-01.json").exists() else {}
    if v8_candidate.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V8_MATERIALIZED_NOT_COMPLETION":
        failures.append({"code": "v8_lsh_candidate_index_bad_verdict", "actual": v8_candidate.get("verdict")})
    if v8_candidate.get("collision_bucket_count") != 28270 or v8_candidate.get("candidate_pair_upper_bound_before_deduplication") != 20991624 or v8_candidate.get("excluded_document_count") != 1747:
        failures.append({"code": "v8_lsh_candidate_index_counts_invalid", "actual": v8_candidate})
    v8_candidate_validation = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v8-band48-validation-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v8-band48-validation-2026-07-01.json").exists() else {}
    if v8_candidate_validation.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V8_VALIDATED":
        failures.append({"code": "v8_lsh_candidate_index_validation_bad_verdict", "actual": v8_candidate_validation.get("verdict")})
    v8_skip0 = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v8-band48-adjudication-partial25-skip0-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v8-band48-adjudication-partial25-skip0-2026-07-01.json").exists() else {}
    if v8_skip0.get("index_row_start_offset") != 0 or v8_skip0.get("index_row_end_exclusive") != 25 or v8_skip0.get("crossing_pair_count") != 1:
        failures.append({"code": "v8_lsh_skip0_counts_invalid", "actual": v8_skip0})
    v8_skip25 = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v8-band48-adjudication-partial25-skip25-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v8-band48-adjudication-partial25-skip25-2026-07-01.json").exists() else {}
    if v8_skip25.get("index_row_start_offset") != 25 or v8_skip25.get("index_row_end_exclusive") != 50 or v8_skip25.get("crossing_pair_count") != 22:
        failures.append({"code": "v8_lsh_skip25_counts_invalid", "actual": v8_skip25})
    for rel in ["receipts/4090-cumulative-filtered-lsh-candidate-index-v8-band48-adjudication-partial25-skip0-validation-2026-07-01.json", "receipts/4090-cumulative-filtered-lsh-candidate-index-v8-band48-adjudication-partial25-skip25-validation-2026-07-01.json"]:
        row = read_json(root / rel) if (root / rel).exists() else {}
        if row.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V8_EXACT_ADJUDICATION_VALIDATED":
            failures.append({"code": "v8_lsh_window_validation_bad_verdict", "path": rel, "actual": row.get("verdict")})
    v8_remediation = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v8-band48-adjudication-window50-remediation-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v8-band48-adjudication-window50-remediation-2026-07-01.json").exists() else {}
    if v8_remediation.get("verdict") != "C1_LSH_CANDIDATE_ADJUDICATION_V8_REMEDIATION_PACKET_READY_NOT_COMPLETION" or v8_remediation.get("remediation_exclusion_document_count") != 19 or v8_remediation.get("index_rows_adjudicated") != 50:
        failures.append({"code": "v8_lsh_window50_remediation_invalid", "actual": v8_remediation})
    v9_manifest = read_json(root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v9-2026-07-01.json") if (root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v9-2026-07-01.json").exists() else {}
    if v9_manifest.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V9_READY_NOT_COMPLETION":
        failures.append({"code": "v9_cumulative_exclusion_manifest_bad_verdict", "actual": v9_manifest.get("verdict")})
    if v9_manifest.get("exclusion_document_count") != 1766 or v9_manifest.get("exclusion_token_floor") != 3087096 or v9_manifest.get("source_overlap_count") != 0:
        failures.append({"code": "v9_cumulative_exclusion_manifest_counts_invalid", "actual": v9_manifest})
    v9_manifest_validation = read_json(root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v9-validation-2026-07-01.json") if (root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v9-validation-2026-07-01.json").exists() else {}
    if v9_manifest_validation.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V9_VALIDATED":
        failures.append({"code": "v9_cumulative_exclusion_manifest_validation_bad_verdict", "actual": v9_manifest_validation.get("verdict")})
    v9_view = read_json(root / "receipts/4090-cumulative-filtered-corpus-view-v9-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-corpus-view-v9-2026-07-01.json").exists() else {}
    v9_filtered = v9_view.get("cumulative_filtered_view", {})
    if v9_view.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V9_READY_NOT_COMPLETION":
        failures.append({"code": "v9_cumulative_filtered_view_bad_verdict", "actual": v9_view.get("verdict")})
    if v9_filtered.get("excluded_document_count") != 1766 or v9_filtered.get("excluded_token_floor") != 3087096 or v9_filtered.get("remaining_document_count") != 4234692 or v9_filtered.get("remaining_content_token_floor") != 6974781662 or v9_filtered.get("binary_shards_rewritten") is not False:
        failures.append({"code": "v9_cumulative_filtered_view_counts_invalid", "actual": v9_filtered})
    v9_view_validation = read_json(root / "receipts/4090-cumulative-filtered-corpus-view-v9-validation-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-corpus-view-v9-validation-2026-07-01.json").exists() else {}
    if v9_view_validation.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V9_VALIDATED":
        failures.append({"code": "v9_cumulative_filtered_view_validation_bad_verdict", "actual": v9_view_validation.get("verdict")})

    v9_index = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v9-band48-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v9-band48-2026-07-01.json").exists() else {}
    if v9_index.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V9_MATERIALIZED_NOT_COMPLETION" or v9_index.get("collision_bucket_count") != 28258 or v9_index.get("collision_document_memberships") != 113496 or v9_index.get("candidate_pair_upper_bound_before_deduplication") != 20991589:
        failures.append({"code": "v9_lsh_candidate_index_invalid", "actual": v9_index})
    v9_index_validation = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v9-band48-validation-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v9-band48-validation-2026-07-01.json").exists() else {}
    if v9_index_validation.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V9_VALIDATED":
        failures.append({"code": "v9_lsh_candidate_index_validation_bad_verdict", "actual": v9_index_validation.get("verdict")})
    expected_v9_adjudications = {0: (70, 0, 0.799622), 25: (119, 8, 0.947971), 50: (478, 50, 0.988074), 75: (90, 36, 0.988072)}
    for skip, expected in expected_v9_adjudications.items():
        rel = f"receipts/4090-cumulative-filtered-lsh-candidate-index-v9-band48-adjudication-partial25-skip{skip}-2026-07-01.json"
        row = read_json(root / rel) if (root / rel).exists() else {}
        pairs, crossings, max_j = expected
        if row.get("verdict") not in {"C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V9_EXACT_ADJUDICATION_NO_CROSSINGS_NOT_COMPLETION", "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V9_EXACT_ADJUDICATION_CROSSINGS_FOUND_NOT_COMPLETION"} or row.get("candidate_pair_count") != pairs or row.get("crossing_pair_count") != crossings or row.get("max_exact_jaccard_observed") != max_j:
            failures.append({"code": "v9_lsh_adjudication_window_invalid", "skip": skip, "actual": row})
        val_rel = f"receipts/4090-cumulative-filtered-lsh-candidate-index-v9-band48-adjudication-partial25-skip{skip}-validation-2026-07-01.json"
        val = read_json(root / val_rel) if (root / val_rel).exists() else {}
        if val.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V9_EXACT_ADJUDICATION_VALIDATED":
            failures.append({"code": "v9_lsh_adjudication_validation_bad_verdict", "skip": skip, "actual": val.get("verdict")})
    v9_remediation = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v9-band48-adjudication-window100-remediation-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v9-band48-adjudication-window100-remediation-2026-07-01.json").exists() else {}
    if v9_remediation.get("verdict") != "C1_LSH_CANDIDATE_ADJUDICATION_V9_REMEDIATION_PACKET_READY_NOT_COMPLETION" or v9_remediation.get("remediation_exclusion_document_count") != 48 or v9_remediation.get("input_crossing_pair_count") != 94 or v9_remediation.get("index_rows_adjudicated") != 100 or v9_remediation.get("cluster_count") != 30:
        failures.append({"code": "v9_lsh_window100_remediation_invalid", "actual": v9_remediation})
    v10_manifest = read_json(root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v10-2026-07-01.json") if (root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v10-2026-07-01.json").exists() else {}
    if v10_manifest.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V10_READY_NOT_COMPLETION" or v10_manifest.get("exclusion_document_count") != 1814 or v10_manifest.get("exclusion_token_floor") != 3155898 or v10_manifest.get("source_overlap_count") != 0:
        failures.append({"code": "v10_cumulative_exclusion_manifest_invalid", "actual": v10_manifest})
    v10_manifest_validation = read_json(root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v10-validation-2026-07-01.json") if (root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v10-validation-2026-07-01.json").exists() else {}
    if v10_manifest_validation.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V10_VALIDATED":
        failures.append({"code": "v10_cumulative_exclusion_manifest_validation_bad_verdict", "actual": v10_manifest_validation.get("verdict")})
    v10_view = read_json(root / "receipts/4090-cumulative-filtered-corpus-view-v10-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-corpus-view-v10-2026-07-01.json").exists() else {}
    v10_filtered = v10_view.get("cumulative_filtered_view", {})
    if v10_view.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V10_READY_NOT_COMPLETION" or v10_filtered.get("excluded_document_count") != 1814 or v10_filtered.get("excluded_token_floor") != 3155898 or v10_filtered.get("remaining_document_count") != 4234644 or v10_filtered.get("remaining_content_token_floor") != 6974712860 or v10_filtered.get("binary_shards_rewritten") is not False:
        failures.append({"code": "v10_cumulative_filtered_view_invalid", "actual": v10_filtered})
    v10_view_validation = read_json(root / "receipts/4090-cumulative-filtered-corpus-view-v10-validation-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-corpus-view-v10-validation-2026-07-01.json").exists() else {}
    if v10_view_validation.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V10_VALIDATED":
        failures.append({"code": "v10_cumulative_filtered_view_validation_bad_verdict", "actual": v10_view_validation.get("verdict")})

    v10_index = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v10-band48-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v10-band48-2026-07-01.json").exists() else {}
    if v10_index.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V10_MATERIALIZED_NOT_COMPLETION" or v10_index.get("collision_bucket_count") != 28236 or v10_index.get("collision_document_memberships") != 113426 or v10_index.get("candidate_pair_upper_bound_before_deduplication") != 20991240:
        failures.append({"code": "v10_lsh_candidate_index_invalid", "actual": v10_index})
    v10_index_validation = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v10-band48-validation-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v10-band48-validation-2026-07-01.json").exists() else {}
    if v10_index_validation.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V10_VALIDATED":
        failures.append({"code": "v10_lsh_candidate_index_validation_bad_verdict", "actual": v10_index_validation.get("verdict")})
    expected_v10_adjudications = {0: (70, 0, 0.799622), 25: (106, 0, 0.795349), 50: (222, 16, 0.985433), 75: (182, 15, 0.979626), 100: (125, 28, 0.997024)}
    for skip, expected in expected_v10_adjudications.items():
        rel = f"receipts/4090-cumulative-filtered-lsh-candidate-index-v10-band48-adjudication-partial25-skip{skip}-2026-07-01.json"
        row = read_json(root / rel) if (root / rel).exists() else {}
        pairs, crossings, max_j = expected
        if row.get("verdict") not in {"C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V10_EXACT_ADJUDICATION_NO_CROSSINGS_NOT_COMPLETION", "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V10_EXACT_ADJUDICATION_CROSSINGS_FOUND_NOT_COMPLETION"} or row.get("candidate_pair_count") != pairs or row.get("crossing_pair_count") != crossings or row.get("max_exact_jaccard_observed") != max_j:
            failures.append({"code": "v10_lsh_adjudication_window_invalid", "skip": skip, "actual": row})
        val_rel = f"receipts/4090-cumulative-filtered-lsh-candidate-index-v10-band48-adjudication-partial25-skip{skip}-validation-2026-07-01.json"
        val = read_json(root / val_rel) if (root / val_rel).exists() else {}
        if val.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V10_EXACT_ADJUDICATION_VALIDATED":
            failures.append({"code": "v10_lsh_adjudication_validation_bad_verdict", "skip": skip, "actual": val.get("verdict")})
    v10_remediation = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v10-band48-adjudication-window125-remediation-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v10-band48-adjudication-window125-remediation-2026-07-01.json").exists() else {}
    if v10_remediation.get("verdict") != "C1_LSH_CANDIDATE_ADJUDICATION_V10_REMEDIATION_PACKET_READY_NOT_COMPLETION" or v10_remediation.get("remediation_exclusion_document_count") != 40 or v10_remediation.get("input_crossing_pair_count") != 59 or v10_remediation.get("index_rows_adjudicated") != 125 or v10_remediation.get("cluster_count") != 25:
        failures.append({"code": "v10_lsh_window125_remediation_invalid", "actual": v10_remediation})
    v11_manifest = read_json(root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v11-2026-07-01.json") if (root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v11-2026-07-01.json").exists() else {}
    if v11_manifest.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V11_READY_NOT_COMPLETION" or v11_manifest.get("exclusion_document_count") != 1854 or v11_manifest.get("exclusion_token_floor") != 3221182 or v11_manifest.get("source_overlap_count") != 0:
        failures.append({"code": "v11_cumulative_exclusion_manifest_invalid", "actual": v11_manifest})
    v11_manifest_validation = read_json(root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v11-validation-2026-07-01.json") if (root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v11-validation-2026-07-01.json").exists() else {}
    if v11_manifest_validation.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V11_VALIDATED":
        failures.append({"code": "v11_cumulative_exclusion_manifest_validation_bad_verdict", "actual": v11_manifest_validation.get("verdict")})
    v11_view = read_json(root / "receipts/4090-cumulative-filtered-corpus-view-v11-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-corpus-view-v11-2026-07-01.json").exists() else {}
    v11_filtered = v11_view.get("cumulative_filtered_view", {})
    if v11_view.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V11_READY_NOT_COMPLETION" or v11_filtered.get("excluded_document_count") != 1854 or v11_filtered.get("excluded_token_floor") != 3221182 or v11_filtered.get("remaining_document_count") != 4234604 or v11_filtered.get("remaining_content_token_floor") != 6974647576 or v11_filtered.get("binary_shards_rewritten") is not False:
        failures.append({"code": "v11_cumulative_filtered_view_invalid", "actual": v11_filtered})
    v11_view_validation = read_json(root / "receipts/4090-cumulative-filtered-corpus-view-v11-validation-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-corpus-view-v11-validation-2026-07-01.json").exists() else {}
    if v11_view_validation.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V11_VALIDATED":
        failures.append({"code": "v11_cumulative_filtered_view_validation_bad_verdict", "actual": v11_view_validation.get("verdict")})

    v11_index = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v11-band48-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v11-band48-2026-07-01.json").exists() else {}
    if v11_index.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V11_MATERIALIZED_NOT_COMPLETION" or v11_index.get("collision_bucket_count") != 28220 or v11_index.get("collision_document_memberships") != 113370 or v11_index.get("candidate_pair_upper_bound_before_deduplication") != 20991071:
        failures.append({"code": "v11_lsh_candidate_index_invalid", "actual": v11_index})
    v11_index_validation = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v11-band48-validation-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v11-band48-validation-2026-07-01.json").exists() else {}
    if v11_index_validation.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V11_VALIDATED":
        failures.append({"code": "v11_lsh_candidate_index_validation_bad_verdict", "actual": v11_index_validation.get("verdict")})
    expected_v11_adjudications = {0: (70, 0, 0.799622), 25: (106, 0, 0.795349), 50: (135, 0, 0.797549), 75: (207, 0, 0.789764), 100: (758357, 41, 0.997024), 125: (900, 15, 0.991576)}
    for skip, expected in expected_v11_adjudications.items():
        rel = f"receipts/4090-cumulative-filtered-lsh-candidate-index-v11-band48-adjudication-partial25-skip{skip}-2026-07-01.json"
        row = read_json(root / rel) if (root / rel).exists() else {}
        pairs, crossings, max_j = expected
        if row.get("verdict") not in {"C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V11_EXACT_ADJUDICATION_NO_CROSSINGS_NOT_COMPLETION", "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V11_EXACT_ADJUDICATION_CROSSINGS_FOUND_NOT_COMPLETION"} or row.get("candidate_pair_count") != pairs or row.get("crossing_pair_count") != crossings or row.get("max_exact_jaccard_observed") != max_j:
            failures.append({"code": "v11_lsh_adjudication_window_invalid", "skip": skip, "actual": row})
        val_rel = f"receipts/4090-cumulative-filtered-lsh-candidate-index-v11-band48-adjudication-partial25-skip{skip}-validation-2026-07-01.json"
        val = read_json(root / val_rel) if (root / val_rel).exists() else {}
        if val.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V11_EXACT_ADJUDICATION_VALIDATED":
            failures.append({"code": "v11_lsh_adjudication_validation_bad_verdict", "skip": skip, "actual": val.get("verdict")})
    v11_remediation = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v11-band48-adjudication-window150-remediation-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v11-band48-adjudication-window150-remediation-2026-07-01.json").exists() else {}
    if v11_remediation.get("verdict") != "C1_LSH_CANDIDATE_ADJUDICATION_V11_REMEDIATION_PACKET_READY_NOT_COMPLETION" or v11_remediation.get("remediation_exclusion_document_count") != 38 or v11_remediation.get("input_crossing_pair_count") != 56 or v11_remediation.get("index_rows_adjudicated") != 150 or v11_remediation.get("cluster_count") != 33:
        failures.append({"code": "v11_lsh_window150_remediation_invalid", "actual": v11_remediation})
    v12_manifest = read_json(root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v12-2026-07-01.json") if (root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v12-2026-07-01.json").exists() else {}
    if v12_manifest.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V12_READY_NOT_COMPLETION" or v12_manifest.get("exclusion_document_count") != 1892 or v12_manifest.get("exclusion_token_floor") != 3250574 or v12_manifest.get("source_overlap_count") != 0:
        failures.append({"code": "v12_cumulative_exclusion_manifest_invalid", "actual": v12_manifest})
    v12_manifest_validation = read_json(root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v12-validation-2026-07-01.json") if (root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v12-validation-2026-07-01.json").exists() else {}
    if v12_manifest_validation.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V12_VALIDATED":
        failures.append({"code": "v12_cumulative_exclusion_manifest_validation_bad_verdict", "actual": v12_manifest_validation.get("verdict")})
    v12_view = read_json(root / "receipts/4090-cumulative-filtered-corpus-view-v12-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-corpus-view-v12-2026-07-01.json").exists() else {}
    v12_filtered = v12_view.get("cumulative_filtered_view", {})
    if v12_view.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V12_READY_NOT_COMPLETION" or v12_filtered.get("excluded_document_count") != 1892 or v12_filtered.get("excluded_token_floor") != 3250574 or v12_filtered.get("remaining_document_count") != 4234566 or v12_filtered.get("remaining_content_token_floor") != 6974618184 or v12_filtered.get("binary_shards_rewritten") is not False:
        failures.append({"code": "v12_cumulative_filtered_view_invalid", "actual": v12_filtered})
    v12_view_validation = read_json(root / "receipts/4090-cumulative-filtered-corpus-view-v12-validation-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-corpus-view-v12-validation-2026-07-01.json").exists() else {}
    if v12_view_validation.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V12_VALIDATED":
        failures.append({"code": "v12_cumulative_filtered_view_validation_bad_verdict", "actual": v12_view_validation.get("verdict")})

    v12_index = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v12-band48-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v12-band48-2026-07-01.json").exists() else {}
    if v12_index.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V12_MATERIALIZED_NOT_COMPLETION" or v12_index.get("collision_bucket_count") != 28206 or v12_index.get("collision_document_memberships") != 113318 or v12_index.get("candidate_pair_upper_bound_before_deduplication") != 20966617:
        failures.append({"code": "v12_lsh_candidate_index_invalid", "actual": v12_index})
    v12_index_validation = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v12-band48-validation-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v12-band48-validation-2026-07-01.json").exists() else {}
    if v12_index_validation.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V12_VALIDATED":
        failures.append({"code": "v12_lsh_candidate_index_validation_bad_verdict", "actual": v12_index_validation.get("verdict")})
    expected_v12_adjudications = {0: (70, 0, 0.799622), 25: (106, 0, 0.795349), 50: (135, 0, 0.797549), 75: (207, 0, 0.789764), 100: (733927, 14, 0.970588), 125: (1045, 8, 0.972816), 150: (51, 14, 0.979872)}
    for skip, expected in expected_v12_adjudications.items():
        rel = f"receipts/4090-cumulative-filtered-lsh-candidate-index-v12-band48-adjudication-partial25-skip{skip}-2026-07-01.json"
        row = read_json(root / rel) if (root / rel).exists() else {}
        pairs, crossings, max_j = expected
        if row.get("verdict") not in {"C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V12_EXACT_ADJUDICATION_NO_CROSSINGS_NOT_COMPLETION", "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V12_EXACT_ADJUDICATION_CROSSINGS_FOUND_NOT_COMPLETION"} or row.get("candidate_pair_count") != pairs or row.get("crossing_pair_count") != crossings or row.get("max_exact_jaccard_observed") != max_j:
            failures.append({"code": "v12_lsh_adjudication_window_invalid", "skip": skip, "actual": row})
        val_rel = f"receipts/4090-cumulative-filtered-lsh-candidate-index-v12-band48-adjudication-partial25-skip{skip}-validation-2026-07-01.json"
        val = read_json(root / val_rel) if (root / val_rel).exists() else {}
        if val.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V12_EXACT_ADJUDICATION_VALIDATED":
            failures.append({"code": "v12_lsh_adjudication_validation_bad_verdict", "skip": skip, "actual": val.get("verdict")})
    v12_remediation = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v12-band48-adjudication-window175-remediation-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v12-band48-adjudication-window175-remediation-2026-07-01.json").exists() else {}
    if v12_remediation.get("verdict") != "C1_LSH_CANDIDATE_ADJUDICATION_V12_REMEDIATION_PACKET_READY_NOT_COMPLETION" or v12_remediation.get("remediation_exclusion_document_count") != 32 or v12_remediation.get("input_crossing_pair_count") != 36 or v12_remediation.get("index_rows_adjudicated") != 175 or v12_remediation.get("cluster_count") != 28:
        failures.append({"code": "v12_lsh_window175_remediation_invalid", "actual": v12_remediation})
    v13_manifest = read_json(root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v13-2026-07-01.json") if (root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v13-2026-07-01.json").exists() else {}
    if v13_manifest.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V13_READY_NOT_COMPLETION" or v13_manifest.get("exclusion_document_count") != 1924 or v13_manifest.get("exclusion_token_floor") != 3295935 or v13_manifest.get("source_overlap_count") != 0:
        failures.append({"code": "v13_cumulative_exclusion_manifest_invalid", "actual": v13_manifest})
    v13_manifest_validation = read_json(root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v13-validation-2026-07-01.json") if (root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v13-validation-2026-07-01.json").exists() else {}
    if v13_manifest_validation.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V13_VALIDATED":
        failures.append({"code": "v13_cumulative_exclusion_manifest_validation_bad_verdict", "actual": v13_manifest_validation.get("verdict")})
    v13_view = read_json(root / "receipts/4090-cumulative-filtered-corpus-view-v13-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-corpus-view-v13-2026-07-01.json").exists() else {}
    v13_filtered = v13_view.get("cumulative_filtered_view", {})
    if v13_view.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V13_READY_NOT_COMPLETION" or v13_filtered.get("excluded_document_count") != 1924 or v13_filtered.get("excluded_token_floor") != 3295935 or v13_filtered.get("remaining_document_count") != 4234534 or v13_filtered.get("remaining_content_token_floor") != 6974572823 or v13_filtered.get("binary_shards_rewritten") is not False:
        failures.append({"code": "v13_cumulative_filtered_view_invalid", "actual": v13_filtered})
    v13_view_validation = read_json(root / "receipts/4090-cumulative-filtered-corpus-view-v13-validation-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-corpus-view-v13-validation-2026-07-01.json").exists() else {}
    if v13_view_validation.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V13_VALIDATED":
        failures.append({"code": "v13_cumulative_filtered_view_validation_bad_verdict", "actual": v13_view_validation.get("verdict")})

    v13_index = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v13-band48-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v13-band48-2026-07-01.json").exists() else {}
    if v13_index.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V13_MATERIALIZED_NOT_COMPLETION" or v13_index.get("collision_bucket_count") != 28187 or v13_index.get("collision_document_memberships") != 113267 or v13_index.get("candidate_pair_upper_bound_before_deduplication") != 20960528:
        failures.append({"code": "v13_lsh_candidate_index_invalid", "actual": v13_index})
    v13_index_validation = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v13-band48-validation-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v13-band48-validation-2026-07-01.json").exists() else {}
    if v13_index_validation.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V13_VALIDATED":
        failures.append({"code": "v13_lsh_candidate_index_validation_bad_verdict", "actual": v13_index_validation.get("verdict")})
    expected_v13_adjudications = {0: (70, 0, 0.799622), 25: (106, 0, 0.795349), 50: (135, 0, 0.797549), 75: (207, 0, 0.789764), 100: (728699, 0, 0.799472), 125: (217, 0, 0.796676), 150: (80, 17, 0.972644), 175: (77, 44, 0.976217)}
    for skip, expected in expected_v13_adjudications.items():
        rel = f"receipts/4090-cumulative-filtered-lsh-candidate-index-v13-band48-adjudication-partial25-skip{skip}-2026-07-01.json"
        row = read_json(root / rel) if (root / rel).exists() else {}
        pairs, crossings, max_j = expected
        if row.get("verdict") not in {"C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V13_EXACT_ADJUDICATION_NO_CROSSINGS_NOT_COMPLETION", "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V13_EXACT_ADJUDICATION_CROSSINGS_FOUND_NOT_COMPLETION"} or row.get("candidate_pair_count") != pairs or row.get("crossing_pair_count") != crossings or row.get("max_exact_jaccard_observed") != max_j:
            failures.append({"code": "v13_lsh_adjudication_window_invalid", "skip": skip, "actual": row})
        val_rel = f"receipts/4090-cumulative-filtered-lsh-candidate-index-v13-band48-adjudication-partial25-skip{skip}-validation-2026-07-01.json"
        val = read_json(root / val_rel) if (root / val_rel).exists() else {}
        if val.get("verdict") != "C1_CUMULATIVE_FILTERED_LSH_CANDIDATE_INDEX_V13_EXACT_ADJUDICATION_VALIDATED":
            failures.append({"code": "v13_lsh_adjudication_validation_bad_verdict", "skip": skip, "actual": val.get("verdict")})
    v13_remediation = read_json(root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v13-band48-adjudication-window200-remediation-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-lsh-candidate-index-v13-band48-adjudication-window200-remediation-2026-07-01.json").exists() else {}
    if v13_remediation.get("verdict") != "C1_LSH_CANDIDATE_ADJUDICATION_V13_REMEDIATION_PACKET_READY_NOT_COMPLETION" or v13_remediation.get("remediation_exclusion_document_count") != 28 or v13_remediation.get("input_crossing_pair_count") != 61 or v13_remediation.get("index_rows_adjudicated") != 200 or v13_remediation.get("cluster_count") != 17:
        failures.append({"code": "v13_lsh_window200_remediation_invalid", "actual": v13_remediation})
    v14_manifest = read_json(root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v14-2026-07-01.json") if (root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v14-2026-07-01.json").exists() else {}
    if v14_manifest.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V14_READY_NOT_COMPLETION" or v14_manifest.get("exclusion_document_count") != 1952 or v14_manifest.get("exclusion_token_floor") != 3329164 or v14_manifest.get("source_overlap_count") != 0:
        failures.append({"code": "v14_cumulative_exclusion_manifest_invalid", "actual": v14_manifest})
    v14_manifest_validation = read_json(root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v14-validation-2026-07-01.json") if (root / "receipts/4090-near-duplicate-cumulative-exclusion-manifest-v14-validation-2026-07-01.json").exists() else {}
    if v14_manifest_validation.get("verdict") != "C1_NEAR_DUPLICATE_CUMULATIVE_EXCLUSION_MANIFEST_V14_VALIDATED":
        failures.append({"code": "v14_cumulative_exclusion_manifest_validation_bad_verdict", "actual": v14_manifest_validation.get("verdict")})
    v14_view = read_json(root / "receipts/4090-cumulative-filtered-corpus-view-v14-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-corpus-view-v14-2026-07-01.json").exists() else {}
    v14_filtered = v14_view.get("cumulative_filtered_view", {})
    if v14_view.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V14_READY_NOT_COMPLETION" or v14_filtered.get("excluded_document_count") != 1952 or v14_filtered.get("excluded_token_floor") != 3329164 or v14_filtered.get("remaining_document_count") != 4234506 or v14_filtered.get("remaining_content_token_floor") != 6974539594 or v14_filtered.get("binary_shards_rewritten") is not False:
        failures.append({"code": "v14_cumulative_filtered_view_invalid", "actual": v14_filtered})
    v14_view_validation = read_json(root / "receipts/4090-cumulative-filtered-corpus-view-v14-validation-2026-07-01.json") if (root / "receipts/4090-cumulative-filtered-corpus-view-v14-validation-2026-07-01.json").exists() else {}
    if v14_view_validation.get("verdict") != "C1_CUMULATIVE_FILTERED_CORPUS_VIEW_V14_VALIDATED":
        failures.append({"code": "v14_cumulative_filtered_view_validation_bad_verdict", "actual": v14_view_validation.get("verdict")})

    for rel in REQUIRED_ENGINEERING_ARTIFACTS:
        if not (root / rel).exists():
            failures.append({"code": "engineering_artifact_missing", "path": rel})

    lock = read_json(lock_path) if lock_path.exists() else {}
    family = lock.get("mandatory_claim_families", {}).get("single_4090_ge_1b_foundation_ceiling")
    if not isinstance(family, dict):
        failures.append({"code": "lock_family_missing"})
    else:
        expected = {
            "status": "ENGINEERING_BASELINE_SURFACE_READY",
            "contract_path": "contracts/C1-4090-1B-feasibility.md",
            "report_path": "4090-ceiling-v0.md",
            "verifier_receipt": "receipts/4090-ceiling-validation-2026-06-29.json",
        }
        for field, value in expected.items():
            if family.get(field) != value:
                failures.append({"code": "lock_field_mismatch", "field": field, "expected": value, "actual": family.get(field)})
        for source_id in REQUIRED_SOURCES:
            if source_id not in family.get("source_rows", []):
                failures.append({"code": "lock_missing_source_row", "id": source_id})

    theoretical = lock.get("theoretical_ceiling") if isinstance(lock, dict) else None
    if not isinstance(theoretical, dict) or theoretical.get("validation_receipt") != "receipts/4090-ceiling-validation-2026-06-29.json":
        failures.append({"code": "theoretical_ceiling_validation_receipt_missing"})

    anti = lock.get("anti_cheat") if isinstance(lock, dict) else None
    if not isinstance(anti, dict) or anti.get("no_missing_theoretical_ceiling") is not True:
        failures.append({"code": "anti_cheat_no_missing_theoretical_ceiling_not_true"})

    sources = read_sources(sources_path) if sources_path.exists() else {}
    for source_id in REQUIRED_SOURCES:
        row = sources.get(source_id)
        if not isinstance(row, dict):
            failures.append({"code": "source_row_missing", "id": source_id})
            continue
        if not (row.get("access_date") or row.get("accessed")):
            failures.append({"code": "source_access_date_missing", "id": source_id})

    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "SINGLE_4090_ENGINEERING_BASELINE_SURFACE_READY" if not failures else "SINGLE_4090_CEILING_BASELINE_INCOMPLETE",
        "failure_count": len(failures),
        "failures": failures,
        "contract_path": "contracts/C1-4090-1B-feasibility.md",
        "report_path": "4090-ceiling-v0.md",
        "completion_limit": "This validates only the single_4090_ge_1b_foundation_ceiling baseline family. It is not an Ember win and not overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())