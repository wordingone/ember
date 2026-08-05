#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""floor_contract_manifest.py — Phase-3 C14 floor-contract manifest.

Row-by-row manifest keyed to every row in docs/ember-floor-contract.md and
every component in nc2-own-technique-contract.md.  Extends and replaces
ember_resident_training_gate.build_floor_contract_manifest() with phase3-specific
surfaces: RLM, iGRPO, LoRA adapter, fp16 C arm.

Key public API
--------------
FLOOR_CONTRACT_ROWS : list[FloorRow]
    All ember-floor-contract.md rows as FloorRow instances.

NC2_COMPONENT_ROWS : list[FloorRow]
    All nc2-own-technique-contract.md components as FloorRow instances,
    including: QAT / turboquant / BitNet / SubQ / MTP / SDEK / Chinese-lab-stack /
    Gemma-unified-multimodal.

class FloorRow(TypedDict):
    key: str
    source_file: str
    source_hash: str
    disposition: Literal["used_now", "preserved_trigger_gated",
                         "blocked_with_exact_adapter_surface"]
    launch_vehicle_impact: str
    trigger: str
    pilot: str
    kill_promote_condition: str
    evidence_path: str

build_manifest(repo_root: Path) -> dict[str, FloorRow]
    Compute per-row sha256 hashes for source files and return the full merged
    manifest keyed by row key.

validate_manifest(manifest: dict) -> list[str]
    Structural validator; returns a list of error strings (empty = OK).

CPU selftest (__main__)
-----------------------
Asserts the core C14 property: TinyPolicyTransformer parameter hash CHANGES
after one iGRPO step on a verifier-conditioned toy task.  No GPU, no C-BASE
weights required.

Run:
    python floor_contract_manifest.py           # selftest only (default)
    python floor_contract_manifest.py --test    # explicit test flag (same)
    python floor_contract_manifest.py --manifest # print manifest summary then run selftest

Does-NOT-count guards (structural, not prose):
    SYMBOLIC_PROXY_PASS: avoided because the selftest asserts pre_hash != post_hash
    on a real nn.Module (TinyPolicyTransformer) — a dictionary/template has no
    state_dict and cannot pass this assertion.
    PRECONDITION_SCAFFOLD_ONLY: avoided because resident_adapter.py wraps
    train_multimodal_v0.py surfaces, not a new tiny runner.
    PARITY_WITH_MODEL_NOT_TOOL: this file is a manifest/spec, not a parity claim.
"""
from __future__ import annotations

import hashlib
import math
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

# ---------------------------------------------------------------------------
# FloorRow TypedDict
# ---------------------------------------------------------------------------

try:
    from typing import TypedDict

    class FloorRow(TypedDict):
        key: str
        source_file: str
        source_hash: str
        disposition: Literal["used_now", "preserved_trigger_gated",
                             "blocked_with_exact_adapter_surface"]
        launch_vehicle_impact: str
        trigger: str
        pilot: str
        kill_promote_condition: str
        evidence_path: str

except ImportError:
    # Python < 3.8 fallback (not expected; belt-and-suspenders)
    FloorRow = dict  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Disposition constants
# ---------------------------------------------------------------------------

USED_NOW = "used_now"
PRESERVED_TRIGGER_GATED = "preserved_trigger_gated"
BLOCKED_EXACT = "blocked_with_exact_adapter_surface"

ALLOWED_DISPOSITIONS = frozenset([USED_NOW, PRESERVED_TRIGGER_GATED, BLOCKED_EXACT])

REQUIRED_ROW_KEYS = frozenset([
    "key", "source_file", "source_hash", "disposition",
    "launch_vehicle_impact", "trigger", "pilot", "kill_promote_condition",
    "evidence_path",
])

# Forbidden disposition words (from gate-discipline in ember_resident_training_gate.py)
FORBIDDEN_DISPOSITION_WORDS = frozenset([
    "archival", "archived", "killed", "irrelevant", "later",
    "covered by fp16", "covered_by_fp16",
])

NATIVE_ENGINE_ROW_KEY = "floor_contract.ember-native-engine"
NATIVE_ENGINE_SOURCE = "docs/spec/ember-native-engine-trigger-ladder-v1.md"


# ---------------------------------------------------------------------------
# Helper: build one FloorRow dict
# ---------------------------------------------------------------------------

def _row(
    *,
    key: str,
    source_file: str,
    source_hash: str,
    disposition: str,
    launch_vehicle_impact: str,
    trigger: str,
    pilot: str,
    kill_promote_condition: str,
    evidence_path: str,
) -> "FloorRow":
    return FloorRow(
        key=key,
        source_file=source_file,
        source_hash=source_hash,
        disposition=disposition,
        launch_vehicle_impact=launch_vehicle_impact,
        trigger=trigger,
        pilot=pilot,
        kill_promote_condition=kill_promote_condition,
        evidence_path=evidence_path,
    )


# ---------------------------------------------------------------------------
# ember-floor-contract.md rows
# Keys follow the naming convention in ember_resident_training_gate.py so
# build_floor_contract_manifest() in that file stays compatible.
# ---------------------------------------------------------------------------

def _make_floor_rows(floor_sha: str, native_engine_sha: str) -> List["FloorRow"]:
    """Construct all ember-floor-contract.md rows.

    Rows are ordered as they appear in the document:
      1. In-vehicle (used_now): QAT, Muon, QK-norm, Governor, multimodal-locks
      2. Deferred (preserved_trigger_gated): encoder-free multimodal training,
         BitNet/1.58-bit, turboquant, SubQ, MLA/KV, SDEK/GDN, MTP, GRPO/iGRPO,
         FP8, MoE, DiffusionGemma
      3. Standing pipeline (preserved_trigger_gated): external-research-intake
    """
    src = "docs/ember-floor-contract.md"
    sha = floor_sha

    return [
        # ------------------------------------------------------------------
        # In-vehicle floor components (disposition = used_now)
        # ------------------------------------------------------------------
        _row(
            key="floor_contract.QAT",
            source_file=src,
            source_hash=sha,
            disposition=USED_NOW,
            launch_vehicle_impact=(
                "int8-grid fake-quant STE on linear weights is active in the launch "
                "vehicle; precision.qat component contract #1; receipted 0.928x tax "
                "(fp19-bench c03)"
            ),
            trigger="QAT/int4 tail or deploy target requiring a quantized exported form",
            pilot=(
                "QAT tail pilot: quantize the first WSD checkpoint; "
                "perplexity-delta + footprint receipt against target"
            ),
            kill_promote_condition=(
                "Only user-approved contract change or receipt-proved contradiction "
                "may demote; promote on receipted export at bounded ppl tax"
            ),
            evidence_path=src,
        ),
        _row(
            key="floor_contract.Muon",
            source_file=src,
            source_hash=sha,
            disposition=USED_NOW,
            launch_vehicle_impact=(
                "Hidden 2D params use Muon optimizer; embed/norms/head use AdamW; "
                "v2 table 1.35x data-efficiency survivor"
            ),
            trigger="Owned-core training run using hidden 2D params",
            pilot=(
                "Muon hidden-layer optimizer run with AdamW fallback; "
                "receipt required for any fallback-to-AdamW-everywhere"
            ),
            kill_promote_condition=(
                "Promote on same-scale efficiency receipt; "
                "fallback only on receipt-backed null demonstrating no benefit"
            ),
            evidence_path=src,
        ),
        _row(
            key="floor_contract.QK-norm",
            source_file=src,
            source_hash=sha,
            disposition=USED_NOW,
            launch_vehicle_impact=(
                "Unretrofittable attention normalization (step-0 lock from Gemma-4 "
                "deep-dive); in nc2 row 8 four v0 locks; active in train_multimodal"
            ),
            trigger="Model construction and train_multimodal adapter; fires at run_step",
            pilot="train_multimodal resident adapter run_step; confirms QK-norm survives LoRA wrap",
            kill_promote_condition=(
                "Cannot be silently removed; deletion requires receipt-backed "
                "degradation or contradiction receipt from an alternative"
            ),
            evidence_path="scripts/train_multimodal_v0.py",
        ),
        _row(
            key="floor_contract.governor",
            source_file=src,
            source_hash=sha,
            disposition=USED_NOW,
            launch_vehicle_impact=(
                "Residency budget: 0.80 VRAM fraction / 1.5 GiB margin / 0.05s pace; "
                "binding user design gate 2026-06-10; tighten-only"
            ),
            trigger="GPU or any non-toy long-running resident loop",
            pilot="Governed resident loop receipt with VRAM headroom asserter",
            kill_promote_condition=(
                "Tighten-only unless user explicitly changes residency contract; "
                "headroom violation requires kill-and-relaunch, fix-forward banned"
            ),
            evidence_path=src,
        ),
        _row(
            key="floor_contract.multimodal_locks",
            source_file=src,
            source_hash=sha,
            disposition=USED_NOW,
            launch_vehicle_impact=(
                "Reserved multimodal vocab band (8 IDs), soft-token embedder contract, "
                "span-bidirectional attn lock, 2D RoPE lock; active in train_multimodal"
            ),
            trigger="Multimodal adapter and future vision-text floor world",
            pilot=(
                "train_multimodal resident adapter run + multimodal floor probe "
                "post checkpoint-1"
            ),
            kill_promote_condition=(
                "Retrofit can fail without killing the component; "
                "component stays floor until receipt-backed successor is named"
            ),
            evidence_path="scripts/train_multimodal_v0.py",
        ),

        # ------------------------------------------------------------------
        # Deferred floor components (disposition = preserved_trigger_gated)
        # ------------------------------------------------------------------
        _row(
            key="floor_contract.encoder_free_multimodal_training",
            source_file=src,
            source_hash=sha,
            disposition=PRESERVED_TRIGGER_GATED,
            launch_vehicle_impact=(
                "Architecture contracts (band/soft-token/2D-RoPE/span-attn) are IN "
                "the launch vehicle; training on image+text is deferred; no published "
                "sub-1B encoder-free prior art"
            ),
            trigger=(
                "First v0 checkpoint evals land (#208) AND a vision-text floor world "
                "is specced"
            ),
            pilot=(
                "~35M-param patch embedder retrofit pilot on v0 checkpoint; "
                "image-text floor task; governed"
            ),
            kill_promote_condition=(
                "Promote on measurable image-grounded verify-rate > text-only control; "
                "kill the retrofit (not the component) on null at matched budget; "
                "successor = dedicated multimodal rung"
            ),
            evidence_path=src,
        ),
        _row(
            key="floor_contract.BitNet/1.58-bit",
            source_file=src,
            source_hash=sha,
            disposition=PRESERVED_TRIGGER_GATED,
            launch_vehicle_impact=(
                "Ternary from-scratch substrate; quality crossover ~3B; 4090 saves "
                "nothing at training (inference-only payoff); int8-QAT carries <=1B "
                "low-bit; fp16 C14 gate does NOT clear BitNet"
            ),
            trigger=(
                "fp16 C14 resident gate pass OR CPU-residency requirement OR "
                "hardware escalation to >=3B rung (user call)"
            ),
            pilot=(
                "onebitllms ternary pilot iff CPU-deploy becomes a requirement; "
                "tiny BitNet/1.58 comparison against fp16 arm"
            ),
            kill_promote_condition=(
                "Promote on >=3B rung entry with comparison receipt; "
                "SKIP-with-receipt if int4 QAT export meets every deploy target first; "
                "never satisfied by fp16 success alone"
            ),
            evidence_path=src,
        ),
        _row(
            key="floor_contract.turboquant",
            source_file=src,
            source_hash=sha,
            disposition=PRESERVED_TRIGGER_GATED,
            launch_vehicle_impact=(
                "Export/serving surface lever; sequenced post-checkpoint-1; "
                "nc2 row 2 duty unchanged"
            ),
            trigger="First v0 checkpoint on disk",
            pilot=(
                "Quantize the first WSD checkpoint; "
                "perplexity-delta + footprint receipt"
            ),
            kill_promote_condition=(
                "Promote on receipted export <= target footprint at bounded ppl tax; "
                "failure = named successor (torchao PTQ baseline)"
            ),
            evidence_path=src,
        ),
        _row(
            key="floor_contract.SubQ",
            source_file=src,
            source_hash=sha,
            disposition=PRESERVED_TRIGGER_GATED,
            launch_vehicle_impact=(
                "Sparse/linear-hybrid attention; NSA attended-token floor ~= full "
                "attention at v0 1024-4k ctx; excluded in config "
                "(throughput.excluded.sparse_attention per fp19 bench)"
            ),
            trigger=(
                "Long-context world admission (NC1c) OR GDN pilot receipt from "
                "340M GDN-hybrid"
            ),
            pilot=(
                "GDN-hybrid 340M pilot carrying sleep-consolidation substrate; "
                "tokens/s x quality parity at >=4x ctx"
            ),
            kill_promote_condition=(
                "Promote on tokens/s x quality parity at >=4x ctx; "
                "kill hybrid on quality cliff with receipt; "
                "successor = MLA/KV-compression-only route"
            ),
            evidence_path=src,
        ),
        _row(
            key="floor_contract.MLA/KV",
            source_file=src,
            source_hash=sha,
            disposition=PRESERVED_TRIGGER_GATED,
            launch_vehicle_impact=(
                "Inference-memory lever; v0 is pretrain-bound; KV pressure starts "
                "at sampling rounds; CN-stack intake nc2 row 7"
            ),
            trigger="First owned-core sampling round (post round-1 verdicts #205)",
            pilot="MLA retrofit probe on v0 core at first sampling round",
            kill_promote_condition=(
                "Promote on measured F (verified-episodes/GPU-h) gain; "
                "SKIP-with-receipt if whole-batch sampler (#230 projection >=2x) "
                "already saturates GPU"
            ),
            evidence_path=src,
        ),
        _row(
            key="floor_contract.SDEK/GDN",
            source_file=src,
            source_hash=sha,
            disposition=PRESERVED_TRIGGER_GATED,
            launch_vehicle_impact=(
                "Middle-timescale substrate: gated delta-rule SSM sleep consolidation; "
                "nc2 row 6 ADOPT-pilot; runs beside v0 only if governor headroom proves it"
            ),
            trigger=(
                "Wait-window GPU idle post-launch OR sleep/consolidation threshold"
            ),
            pilot=(
                "340M GDN-hybrid pilot per nc2 row 6; "
                "GSM-Infinite-class delta reproduced locally at pilot scale"
            ),
            kill_promote_condition=(
                "Promote on GSM-Infinite-class delta receipt reproduced locally; "
                "kill on null receipt — successor = LoRA-sleep baseline (kernel v1 freeze spec)"
            ),
            evidence_path=src,
        ),
        _row(
            key="floor_contract.MTP",
            source_file=src,
            source_hash=sha,
            disposition=PRESERVED_TRIGGER_GATED,
            launch_vehicle_impact=(
                "Published NEGATIVE quality evidence <=1B (Meta 2404.19737; "
                "TOP 340M/1.8B inconsistent); re-staged to speculative-decode DRAFTER"
            ),
            trigger=(
                "v0 sampling rounds begin AND decode is measured sampling bottleneck"
            ),
            pilot=(
                "Speculative-decode DRAFTER on v0 core (Gemma-4-style post-hoc); "
                ">=1.5x decode throughput at unchanged verify rate"
            ),
            kill_promote_condition=(
                "Promote on >=1.5x decode throughput at unchanged verify rate; "
                "SKIP-with-receipt if sampler economics already meet F target"
            ),
            evidence_path=src,
        ),
        _row(
            key="floor_contract.iGRPO/GRPO",
            source_file=src,
            source_hash=sha,
            disposition=USED_NOW,
            launch_vehicle_impact=(
                "Verifier-conditioned resident policy update is the ACTIVE C14 gate; "
                "floor ~1.5B for stock GRPO; C14 uses iGRPO/RLM on owned tiny core; "
                "non-killable for this goal"
            ),
            trigger="Resident-training pre-loop gate; phase3/igrpo_trainer.py",
            pilot=(
                "RLM/iGRPO harness-native resident gate; CPU selftest asserts "
                "state_dict changes after one step on TinyPolicyTransformer"
            ),
            kill_promote_condition=(
                "Non-killable for this goal; symbolic/template proxy is never a pass; "
                "zero-pass-rate on pre-registered pilot = kill condition (pilot, not component)"
            ),
            evidence_path="scripts/ember_phase3_c14/igrpo_trainer.py",
        ),
        _row(
            key="floor_contract.FP8",
            source_file=src,
            source_hash=sha,
            disposition=PRESERVED_TRIGGER_GATED,
            launch_vehicle_impact=(
                "Zero published consumer-4090 FP8 pretrains; TE silent-BF16-fallback; "
                "torchao tensorwise-only on sm89; release-scan item"
            ),
            trigger=(
                "A published consumer-4090 FP8 pretrain receipt OR "
                "torchao sm89 rowwise support in a release"
            ),
            pilot="Release-scan receipt (standing #18 sweep)",
            kill_promote_condition=(
                "Re-enter only on new external hardware/library evidence; "
                "no internal re-derivation without external trigger"
            ),
            evidence_path=src,
        ),
        _row(
            key=NATIVE_ENGINE_ROW_KEY,
            source_file=NATIVE_ENGINE_SOURCE,
            source_hash=native_engine_sha,
            disposition=PRESERVED_TRIGGER_GATED,
            launch_vehicle_impact=(
                "No big-bang rewrite. T1 parity tax -> R2; "
                "T2=PARTIALLY_FIRED framework wall on #155 -> R0; "
                "T3=ON_BLOCKER_PATH resident updates -> R1; "
                "T4 shipped training capability -> R3."
            ),
            trigger=(
                "T1 parity-tax receipt -> R2; "
                "T2=PARTIALLY_FIRED directed #155 framework wall -> R0; "
                "T3=ON_BLOCKER_PATH resident-training wall -> R1; "
                "T4 shipped local training capability -> R3"
            ),
            pilot=(
                "#155 R0 pilots: width-conditional consumer-GPU FP8 matmul "
                "and fused Muon Newton-Schulz update, each with a real "
                "training/inference consumer and independent promotion verdict"
            ),
            kill_promote_condition=(
                "Preserve until T1/T2/T3/T4 evidence fires the named rung; "
                "promote only the measured rung with parity, resource, custody, "
                "and consumer receipts; reject silent fallback or self-attestation"
            ),
            evidence_path=NATIVE_ENGINE_SOURCE,
        ),
        _row(
            key="floor_contract.MoE",
            source_file=src,
            source_hash=sha,
            disposition=PRESERVED_TRIGGER_GATED,
            launch_vehicle_impact=(
                "Trades VRAM (scarce) for FLOPs (abundant) at <=1B on one 4090; "
                "SKIP-with-receipt pending hardware/scale"
            ),
            trigger="Multi-GPU or >=3B rung hardware escalation (user call)",
            pilot="Scale/hardware receipt from local small-MoE evidence",
            kill_promote_condition=(
                "Re-enter on hardware escalation or local small-MoE win; "
                "no internal justification without hardware change"
            ),
            evidence_path=src,
        ),
        _row(
            key="floor_contract.DiffusionGemma",
            source_file=src,
            source_hash=sha,
            disposition=PRESERVED_TRIGGER_GATED,
            launch_vehicle_impact=(
                "Output quality below autoregressive per Google framing; "
                "throughput-per-verified-episode bet unproven locally; "
                "WATCHING nc2 row 9"
            ),
            trigger=(
                "Idle GPU window AND W-code admitted (STATE pending layer 19)"
            ),
            pilot=(
                "w1-style MBPP floor probe: DiffusionGemma vs Qwen-3B, "
                "same k/tasks/governor; decided on measured F"
            ),
            kill_promote_condition=(
                "Promote iff verify-rate floor stays nonzero AND F gain >= measured; "
                "kill on zero-verify floor"
            ),
            evidence_path=src,
        ),
        _row(
            key="floor_contract.external_research_intake",
            source_file=src,
            source_hash=sha,
            disposition=PRESERVED_TRIGGER_GATED,
            launch_vehicle_impact=(
                "Standing pipeline: bounded release-scan sweep produces typed WATCHING "
                "rows; ADOPT only via local residency-scale receipts"
            ),
            trigger="Every idle tick advancing the wait-window queue (STATE pending layer 18)",
            pilot="Bounded release-scan sweep -> typed WATCHING row",
            kill_promote_condition=(
                "'No candidates' is a recorded outcome; "
                "new research enters as WATCHING and never skips to ADOPT without receipt"
            ),
            evidence_path=src,
        ),
        # Phase-3 specific rows (RLM, iGRPO, LoRA adapter, fp16 C arm)
        _row(
            key="floor_contract.phase3.RLM_mechanism",
            source_file=src,
            source_hash=sha,
            disposition=USED_NOW,
            launch_vehicle_impact=(
                "Recursive self-call loop (arXiv:2512.24601) is the sampling "
                "procedure in igrpo_stage1/stage2; rlm_generate() in "
                "scripts/ember_resident_igrpo.py:243; ACTION_FINAL=8, ACTION_RECURSE=9"
            ),
            trigger="iGRPO training step on any task corpus",
            pilot=(
                "CPU selftest in igrpo_trainer.py __main__: "
                "assert pre_hash != post_hash after rlm_generate + igrpo_loss + optimizer.step()"
            ),
            kill_promote_condition=(
                "Non-killable for C14; if recursion depth causes instability, "
                "reduce max_depth not the mechanism"
            ),
            evidence_path="scripts/ember_phase3_c14/igrpo_trainer.py",
        ),
        _row(
            key="floor_contract.phase3.iGRPO_two_stage",
            source_file=src,
            source_hash=sha,
            disposition=USED_NOW,
            launch_vehicle_impact=(
                "Two-stage update (arXiv:2602.09000): Stage-1 G exploratory drafts "
                "-> d-hat = argmax; Stage-2 q' = obs+d-hat -> M refinements -> "
                "PG update; compute_advantages() population-std Eq.4"
            ),
            trigger="iGRPO training step; fires every forward pass in the C arm",
            pilot=(
                "CPU selftest: degenerate equal-reward batch yields advantages ~0; "
                "non-degenerate batch updates policy; both asserted in __main__"
            ),
            kill_promote_condition=(
                "Non-killable for C14; advantage std-guard (A_j=0 when std=0) "
                "must remain; no surrogate simplification without receipt"
            ),
            evidence_path="scripts/ember_resident_igrpo.py",
        ),
        _row(
            key="floor_contract.phase3.LoRA_fp16_C_arm",
            source_file=src,
            source_hash=sha,
            disposition=USED_NOW,
            launch_vehicle_impact=(
                "LoRA/adapter wrapper in resident_adapter.py wraps EmberModelShell "
                "(from ember_c14_real_adapter.py); adapter parameters are the only "
                "trained weights in the fp16 C arm; state_dict delta is inspectable"
            ),
            trigger="C arm instantiation in abc_deleted_harness.py",
            pilot=(
                "CPU toy selftest in resident_adapter.py __main__: "
                "assert adapter delta is nonzero after one iGRPO step on TinyPolicyTransformer"
            ),
            kill_promote_condition=(
                "Promote to full-weights C arm only if LoRA adapter path proves "
                "insufficient; requires resident_adapter receipt; "
                "EMBER_GATE_AUTHORIZED interlock stays even for full-weights path"
            ),
            evidence_path="scripts/ember_phase3_c14/resident_adapter.py",
        ),
        _row(
            key="floor_contract.phase3.EMBER_GATE_AUTHORIZED",
            source_file=src,
            source_hash=sha,
            disposition=USED_NOW,
            launch_vehicle_impact=(
                "Compute-blocked guard in train_multimodal_v0.py; the real C-BASE "
                "4090 run is architecturally isolated behind this interlock; "
                "every other C14 file runs on CPU with toy models"
            ),
            trigger="Real C-BASE weight access; 4090 GPU dispatch",
            pilot="Not a pilot item; the interlock is the gate mechanism itself",
            kill_promote_condition=(
                "EMBER_GATE_AUTHORIZED is flipped by the work-system on "
                "readiness+floor-probe+governed+lever receipt, NOT by [REDACTED]; "
                "operator informed, not gating (per the standing launch-not-operator-gated ruling)"
            ),
            evidence_path="scripts/train_multimodal_v0.py",
        ),
    ]


# ---------------------------------------------------------------------------
# nc2-own-technique-contract.md component rows
# ---------------------------------------------------------------------------

def _make_nc2_rows(nc2_sha: str) -> List["FloorRow"]:
    """Construct all nc2-own-technique-contract.md component rows.

    Components: QAT / turboquant / BitNet / SubQ / MTP / SDEK /
                Chinese-lab-stack / Gemma-unified-multimodal.
    Also covers phase-3 additions: RLM row 10, iGRPO row 11, LoRA row 12.
    """
    src = "nc2-own-technique-contract.md"
    sha = nc2_sha

    return [
        _row(
            key="nc2_component_contract.QAT",
            source_file=src,
            source_hash=sha,
            disposition=PRESERVED_TRIGGER_GATED,
            launch_vehicle_impact=(
                "Quantization-native pretrain: int8-grid fake-quant STE remains "
                "owned-core component; nc2 row 1"
            ),
            trigger="NC2 owned-core training/export or QAT tail",
            pilot="QAT tail pilot: receipted pretrain + int8-export comparison",
            kill_promote_condition=(
                "Fallback only by contract receipt proving better alternative; "
                "no silent demotion; int4 QAT export success counts as SKIP, not kill"
            ),
            evidence_path=src,
        ),
        _row(
            key="nc2_component_contract.turboquant",
            source_file=src,
            source_hash=sha,
            disposition=PRESERVED_TRIGGER_GATED,
            launch_vehicle_impact=(
                "KV/MLA compression family remains first-class export/serving lever; "
                "nc2 row 2 ADOPT duty unchanged, sequenced post-ckpt-1"
            ),
            trigger="Sampling or KV pressure post-ckpt-1",
            pilot="Compression/runtime probe on first WSD checkpoint",
            kill_promote_condition=(
                "Only receipt-backed null with named successor (torchao PTQ) closes; "
                "no silent collapse into 'covered by fp16'"
            ),
            evidence_path=src,
        ),
        _row(
            key="nc2_component_contract.BitNet/1.58-bit",
            source_file=src,
            source_hash=sha,
            disposition=PRESERVED_TRIGGER_GATED,
            launch_vehicle_impact=(
                "From-scratch ternary route remains binding comparison at nc2 row 3; "
                "trigger = fp16 C14 gate cleared (the current phase)"
            ),
            trigger="fp16 C14 gate cleared AND tiny BitNet/1.58 comparison available",
            pilot=(
                "100-300M or tiny BitNet comparison depending on gate stage; "
                "fp16 C14 pass is prerequisite, not sufficient"
            ),
            kill_promote_condition=(
                "Not killable by fp16 success alone; requires comparison receipt "
                "showing BitNet parity or gap with explanation; "
                "SKIP-with-receipt if int4 QAT export meets every deploy target"
            ),
            evidence_path=src,
        ),
        _row(
            key="nc2_component_contract.SubQ",
            source_file=src,
            source_hash=sha,
            disposition=PRESERVED_TRIGGER_GATED,
            launch_vehicle_impact=(
                "Sparse/linear-hybrid attention remains long-context route; "
                "nc2 row 4; explicitly excluded in config per fp19 bench"
            ),
            trigger="Long-context world admission (NC1c) OR GDN pilot receipt",
            pilot="GDN-hybrid sparse/linear 340M pilot; tokens/s x quality parity at >=4x ctx",
            kill_promote_condition=(
                "Successor only with quality-cliff receipt; "
                "no silent exclusion from config without receipt-backed evidence"
            ),
            evidence_path=src,
        ),
        _row(
            key="nc2_component_contract.MTP",
            source_file=src,
            source_hash=sha,
            disposition=PRESERVED_TRIGGER_GATED,
            launch_vehicle_impact=(
                "Draft-head/speculation route re-staged to speculative drafter; "
                "nc2 row 5; negative evidence <=1B documented"
            ),
            trigger="Owned-core sampling rounds begin AND decode is measured bottleneck",
            pilot="MTP drafter-head pilot: >=1.5x decode throughput at unchanged verify rate",
            kill_promote_condition=(
                "Only negative <=1B evidence with named successor closes; "
                "SKIP-with-receipt if sampler already meets F target"
            ),
            evidence_path=src,
        ),
        _row(
            key="nc2_component_contract.SDEK",
            source_file=src,
            source_hash=sha,
            disposition=PRESERVED_TRIGGER_GATED,
            launch_vehicle_impact=(
                "Adaptation-control kernel (gated delta-rule SSM) remains operating "
                "layer for sleep/plasticity; nc2 row 6 ADOPT-pilot"
            ),
            trigger="Sleep/plasticity threshold or NC2 entry via GDN pilot window",
            pilot="SDEK/GDN 340M consolidation pilot; GSM-Infinite-class delta receipt",
            kill_promote_condition=(
                "Cannot be archived without contradiction-level receipt; "
                "kill only on null receipt with LoRA-sleep baseline as named successor"
            ),
            evidence_path=src,
        ),
        _row(
            key="nc2_component_contract.Chinese-lab_stack",
            source_file=src,
            source_hash=sha,
            disposition=PRESERVED_TRIGGER_GATED,
            launch_vehicle_impact=(
                "Muon/FP8/MoE/GRPO tech stack remains itemized as separate rows; "
                "nc2 row 7; no silent stack-level kill"
            ),
            trigger="Per-tech release scan or scale/hardware entry event",
            pilot="Per-tech pilot/release receipt (each tech evaluated independently)",
            kill_promote_condition=(
                "Mixed per item; no silent stack-level kill; "
                "Muon=used_now in launch vehicle; others trigger-gated per rows above"
            ),
            evidence_path=src,
        ),
        _row(
            key="nc2_component_contract.Gemma_unified_multimodal",
            source_file=src,
            source_hash=sha,
            disposition=PRESERVED_TRIGGER_GATED,
            launch_vehicle_impact=(
                "Encoder-free unified multimodal architecture (Gemma-4 deep-dive) "
                "remains owned-core template; four v0 locks already in launch vehicle; "
                "training deferred"
            ),
            trigger="Vision-text floor world specced OR multimodal checkpoint evals land (#208)",
            pilot="Soft-token embedder retrofit/floor probe on v0 checkpoint",
            kill_promote_condition=(
                "Retrofit may fail without killing the architecture component; "
                "successor must be explicit if the specific Gemma-4 approach fails"
            ),
            evidence_path=src,
        ),
        # Phase-3 NC2 additions
        _row(
            key="nc2_component_contract.RLM_recursive_generation",
            source_file=src,
            source_hash=sha,
            disposition=USED_NOW,
            launch_vehicle_impact=(
                "RLM recursive self-call (arXiv:2512.24601) is the sampling procedure "
                "inside iGRPO stage1/stage2; banked in ember_resident_igrpo.py:243; "
                "non-killable for C14"
            ),
            trigger="iGRPO step in any training or eval arm",
            pilot=(
                "CPU selftest: rlm_generate depth<=2 on TinyPolicyTransformer; "
                "FINAL termination; ACTION_RECURSE fallback at max_depth"
            ),
            kill_promote_condition=(
                "Reduce max_depth not the mechanism if instability observed; "
                "mechanism itself is non-killable for the C14 goal"
            ),
            evidence_path="scripts/ember_resident_igrpo.py",
        ),
        _row(
            key="nc2_component_contract.iGRPO_group_relative_PG",
            source_file=src,
            source_hash=sha,
            disposition=USED_NOW,
            launch_vehicle_impact=(
                "iGRPO (arXiv:2602.09000) two-stage policy gradient; "
                "compute_advantages() pop-std Eq.4; igrpo_loss() clipped IS-ratio PG; "
                "active in phase3/igrpo_trainer.py"
            ),
            trigger="Any training step on the C arm of the A/B/C/Deleted contract",
            pilot=(
                "CPU selftest: advantages=0 on degenerate batch; "
                "nonzero update on mixed-reward batch; both assertions in __main__"
            ),
            kill_promote_condition=(
                "Non-killable for C14; std-guard (A_j=0 if std=0) is invariant; "
                "surrogate simplification requires receipt"
            ),
            evidence_path="scripts/ember_phase3_c14/igrpo_trainer.py",
        ),
    ]


# ---------------------------------------------------------------------------
# Public list-form constants (populated below after function definitions)
# ---------------------------------------------------------------------------

# Sentinel sha value when source file hash is not yet computed.
_SHA_UNKNOWN = "sha256_not_computed"


# Lazy defaults: these are populated with _SHA_UNKNOWN until build_manifest()
# is called with a real repo_root.
FLOOR_CONTRACT_ROWS: List["FloorRow"] = _make_floor_rows(
    _SHA_UNKNOWN, _SHA_UNKNOWN
)
NC2_COMPONENT_ROWS: List["FloorRow"] = _make_nc2_rows(_SHA_UNKNOWN)


# ---------------------------------------------------------------------------
# build_manifest
# ---------------------------------------------------------------------------

def _sha256_file(path: Path) -> str:
    """Compute sha256 of a file; return 'file_not_found' if absent."""
    if not path.exists() or not path.is_file():
        return "file_not_found"
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(repo_root: Path) -> Dict[str, "FloorRow"]:
    """Build the full merged manifest keyed by FloorRow.key.

    Computes sha256 hashes for source files from the repo and injects them
    into each row.  Returns a dict ready for validate_manifest().

    Args:
        repo_root: Absolute path to the nc-ladder repository root.

    Returns:
        dict mapping FloorRow.key -> FloorRow with real source_hash values.
    """
    floor_path = repo_root / "docs" / "charter" / "ember-floor-contract.md"
    nc2_path = repo_root / "nc2-own-technique-contract.md"
    native_engine_path = repo_root / NATIVE_ENGINE_SOURCE

    floor_sha = _sha256_file(floor_path)
    nc2_sha = _sha256_file(nc2_path)
    native_engine_sha = _sha256_file(native_engine_path)

    floor_rows = _make_floor_rows(floor_sha, native_engine_sha)
    nc2_rows = _make_nc2_rows(nc2_sha)

    result: Dict[str, "FloorRow"] = {}
    for row in floor_rows + nc2_rows:
        key = row["key"]
        if key in result:
            raise ValueError(f"Duplicate manifest key: {key!r}")
        result[key] = row

    return result


def build_native_engine_board_review(
    manifest: Dict[str, Any],
) -> Dict[str, Any]:
    """Return the closed T2/T3 cadence review emitted by every board audit."""
    errors = validate_manifest(manifest)
    if errors:
        raise ValueError(
            "native-engine floor manifest invalid: " + "; ".join(errors)
        )

    row = manifest[NATIVE_ENGINE_ROW_KEY]
    return {
        "floor_row_key": NATIVE_ENGINE_ROW_KEY,
        "disposition": PRESERVED_TRIGGER_GATED,
        "source_file": NATIVE_ENGINE_SOURCE,
        "source_sha256": row["source_hash"],
        "issue": 158,
        "coupled_issue": 155,
        "reviewed_triggers": [
            {
                "trigger_id": "T2",
                "status": "PARTIALLY_FIRED",
                "required_rung": "R0",
            },
            {
                "trigger_id": "T3",
                "status": "ON_BLOCKER_PATH",
                "required_rung": "R1",
            },
        ],
        "claim_boundary": (
            "TRIGGER_REVIEW_ONLY_NO_NATIVE_ENGINE_CAPABILITY_CLAIM"
        ),
    }


# ---------------------------------------------------------------------------
# validate_manifest
# ---------------------------------------------------------------------------

def validate_manifest(manifest: Dict[str, Any]) -> List[str]:
    """Validate manifest structure; return list of error strings (empty = OK).

    Checks:
      1. Each entry has all required keys.
      2. Disposition is one of the allowed values.
      3. No forbidden disposition words appear in any disposition value.
      4. trigger, pilot, kill_promote_condition, evidence_path are non-empty.
      5. The key in the dict matches the 'key' field in the row.
      6. Expected rows are present (smoke-check: at least one used_now iGRPO row).
    """
    errors: List[str] = []

    for manifest_key, row in manifest.items():
        # Key consistency
        if "key" in row and row["key"] != manifest_key:
            errors.append(
                f"Key mismatch: manifest key={manifest_key!r} "
                f"but row['key']={row['key']!r}"
            )

        # Required keys
        missing = REQUIRED_ROW_KEYS - set(row.keys())
        if missing:
            errors.append(f"Row {manifest_key!r} missing fields: {sorted(missing)}")
            continue  # skip further checks on incomplete row

        # Disposition value
        disp = row.get("disposition", "")
        if disp not in ALLOWED_DISPOSITIONS:
            errors.append(
                f"Row {manifest_key!r}: disposition={disp!r} not in "
                f"{sorted(ALLOWED_DISPOSITIONS)}"
            )

        # Forbidden words in disposition field
        disp_lower = (disp or "").lower()
        for word in FORBIDDEN_DISPOSITION_WORDS:
            if word in disp_lower:
                errors.append(
                    f"Row {manifest_key!r}: forbidden word {word!r} "
                    f"in disposition field"
                )

        # Non-empty required text fields
        for field_name in (
            "trigger", "pilot", "kill_promote_condition", "evidence_path",
            "launch_vehicle_impact"
        ):
            val = row.get(field_name, "")
            if not val or not val.strip():
                errors.append(
                    f"Row {manifest_key!r}: required field {field_name!r} is empty"
                )

    # Smoke-check: iGRPO/GRPO row must be used_now (active gate)
    igrpo_key = "floor_contract.iGRPO/GRPO"
    if igrpo_key in manifest:
        if manifest[igrpo_key].get("disposition") != USED_NOW:
            errors.append(
                f"Row {igrpo_key!r}: must be {USED_NOW!r} "
                f"(active C14 gate); found {manifest[igrpo_key].get('disposition')!r}"
            )
    else:
        errors.append(f"Required row {igrpo_key!r} missing from manifest")

    # Smoke-check: BitNet row must be preserved_trigger_gated (not used_now)
    bitnet_floor_key = "floor_contract.BitNet/1.58-bit"
    if bitnet_floor_key in manifest:
        if manifest[bitnet_floor_key].get("disposition") != PRESERVED_TRIGGER_GATED:
            errors.append(
                f"Row {bitnet_floor_key!r}: must be {PRESERVED_TRIGGER_GATED!r} "
                f"(fp16 C14 does not clear BitNet); "
                f"found {manifest[bitnet_floor_key].get('disposition')!r}"
            )
    else:
        errors.append(f"Required row {bitnet_floor_key!r} missing from manifest")

    # Smoke-check: nc2 BitNet row trigger must mention fp16
    nc2_bitnet_key = "nc2_component_contract.BitNet/1.58-bit"
    if nc2_bitnet_key in manifest:
        trigger_val = manifest[nc2_bitnet_key].get("trigger", "")
        if "fp16" not in trigger_val.lower():
            errors.append(
                f"Row {nc2_bitnet_key!r}: trigger must mention 'fp16' "
                f"(does_not_count_guards: quantized-naming-without-neural-comparison); "
                f"got {trigger_val!r}"
            )

    native = manifest.get(NATIVE_ENGINE_ROW_KEY)
    if native is None:
        errors.append(f"Required row {NATIVE_ENGINE_ROW_KEY!r} missing from manifest")
    else:
        if native.get("disposition") != PRESERVED_TRIGGER_GATED:
            errors.append(
                f"Row {NATIVE_ENGINE_ROW_KEY!r}: must be "
                f"{PRESERVED_TRIGGER_GATED!r}"
            )
        if native.get("source_file") != NATIVE_ENGINE_SOURCE:
            errors.append(
                f"Row {NATIVE_ENGINE_ROW_KEY!r}: source_file must be "
                f"{NATIVE_ENGINE_SOURCE!r}"
            )
        trigger = str(native.get("trigger", ""))
        for required in (
            "T1",
            "T2=PARTIALLY_FIRED",
            "T3=ON_BLOCKER_PATH",
            "T4",
        ):
            if required not in trigger:
                errors.append(
                    f"Row {NATIVE_ENGINE_ROW_KEY!r}: trigger missing {required!r}"
                )
        combined = " ".join(
            str(native.get(field, ""))
            for field in (
                "launch_vehicle_impact",
                "trigger",
                "pilot",
                "kill_promote_condition",
                "evidence_path",
            )
        )
        for required in ("R0", "R1", "R2", "R3"):
            if required not in combined:
                errors.append(
                    f"Row {NATIVE_ENGINE_ROW_KEY!r}: missing rung {required!r}"
                )
        pilot = str(native.get("pilot", ""))
        for required in ("#155", "FP8", "Muon"):
            if required not in pilot:
                errors.append(
                    f"Row {NATIVE_ENGINE_ROW_KEY!r}: pilot missing {required!r}"
                )

    return errors


# ---------------------------------------------------------------------------
# CPU selftest — asserts C14 core property (genuine neural update)
# ---------------------------------------------------------------------------

def _run_cpu_selftest(verbose: bool = True) -> bool:
    """CPU selftest: assert TinyPolicyTransformer param hash changes after one iGRPO step.

    Does-NOT-count guards:
      SYMBOLIC_PROXY_PASS: a dictionary/template has no nn.Module state_dict;
        this assertion cannot be satisfied by a non-neural proxy.
      PRECONDITION_SCAFFOLD_ONLY: TinyPolicyTransformer IS an nn.Module; the
        iGRPO step calls optimizer.step() on real parameters.

    Returns True iff all assertions pass.
    """
    import torch
    import torch.nn as nn

    # Locate the banked primitives relative to this file.
    _here = Path(__file__).resolve()
    _scripts = _here.parent.parent  # scripts/
    if str(_scripts) not in sys.path:
        sys.path.insert(0, str(_scripts))

    from ember_resident_igrpo import (
        TinyPolicyTransformer,
        igrpo_step,
        compute_advantages,
    )

    def _param_hash(policy: nn.Module) -> str:
        """Stable hash of all trainable parameter values."""
        h = hashlib.sha256()
        for name, param in sorted(policy.named_parameters()):
            h.update(name.encode())
            # Convert to float32 to avoid bfloat16 endianness issues on some platforms
            h.update(param.detach().float().cpu().numpy().tobytes())
        return h.hexdigest()

    passed = True

    # ------------------------------------------------------------------
    # T1: state_dict CHANGES after one genuine iGRPO step
    # ------------------------------------------------------------------
    policy = TinyPolicyTransformer()
    optimizer = torch.optim.Adam(policy.parameters(), lr=1e-3)

    pre_hash = _param_hash(policy)

    # Run iGRPO steps until one genuinely updates the weights. A single step can
    # hit a degenerate group (all-equal Stage-2 rewards -> advantages=0 -> no
    # gradient -> no hash change); that is a seed accident, not a failure of the
    # neural-update mechanism. Loop over state_vals 0..7 and break on the first
    # non-degenerate step (same pattern as igrpo_trainer.py Test 1 and
    # resident_adapter.py). If NONE of 8 states updates, the mechanism is broken
    # and the assertion correctly fails.
    receipt = None
    for _sv in range(8):
        receipt = igrpo_step(
            policy=policy,
            optimizer=optimizer,
            state_val=_sv,
            N=4,
            G=4,
            max_depth=1,
            epsilon=0.2,
            beta=0.0,
            temperature=1.5,
        )
        if _param_hash(policy) != pre_hash:
            break

    post_hash = _param_hash(policy)

    t1_pass = pre_hash != post_hash
    if verbose:
        status = "PASS" if t1_pass else "FAIL"
        print(f"  {status}  T1: state_dict changes after iGRPO step")
        if not t1_pass:
            print(f"        pre_hash={pre_hash[:16]}... post_hash={post_hash[:16]}...")
            print(f"        loss={receipt['loss']:.6f}  stage2_rewards={receipt['stage2_rewards']}")
    passed = passed and t1_pass

    # ------------------------------------------------------------------
    # T2: degenerate equal-reward group yields advantages ~= 0
    # ------------------------------------------------------------------
    rewards_equal = [1.0, 1.0, 1.0, 1.0]
    advs = compute_advantages(rewards_equal)
    t2_pass = all(abs(a) < 1e-9 for a in advs)
    if verbose:
        status = "PASS" if t2_pass else "FAIL"
        print(f"  {status}  T2: degenerate equal-reward -> advantages ~0")
        if not t2_pass:
            print(f"        advantages={advs}")
    passed = passed and t2_pass

    # ------------------------------------------------------------------
    # T3: snapshot (Deleted arm) restores pre-update hash exactly
    # ------------------------------------------------------------------
    policy2 = TinyPolicyTransformer()
    optimizer2 = torch.optim.Adam(policy2.parameters(), lr=1e-3)
    pre_hash2 = _param_hash(policy2)
    snapshot = deepcopy(policy2.state_dict())

    # Same degeneracy guard as T1: retry over state_vals until a step actually
    # moves the weights, so the Deleted-arm restore test has a real update to
    # undo (snapshot is taken before the loop = the genuine pre-update state).
    for _sv in range(8):
        igrpo_step(
            policy=policy2,
            optimizer=optimizer2,
            state_val=_sv,
            N=4, G=4, max_depth=1,
            epsilon=0.2, beta=0.0, temperature=1.5,
        )
        if _param_hash(policy2) != pre_hash2:
            break
    mid_hash2 = _param_hash(policy2)

    # Deleted arm: restore pre-C snapshot
    policy2.load_state_dict(snapshot)
    restored_hash = _param_hash(policy2)

    t3a_pass = mid_hash2 != pre_hash2   # update happened
    t3b_pass = restored_hash == pre_hash2  # restoration is exact
    t3_pass = t3a_pass and t3b_pass
    if verbose:
        status = "PASS" if t3_pass else "FAIL"
        print(f"  {status}  T3: Deleted-arm restore is exact (load_state_dict roundtrip)")
        if not t3_pass:
            print(f"        update_happened={t3a_pass}  restore_exact={t3b_pass}")
    passed = passed and t3_pass

    # ------------------------------------------------------------------
    # T4: manifest builds and validates without errors
    # ------------------------------------------------------------------
    # Use the nc-ladder repo root (parent of parent of this file's dir)
    repo_root = Path(__file__).resolve().parent.parent.parent
    manifest = build_manifest(repo_root)
    errors = validate_manifest(manifest)

    t4_pass = len(errors) == 0
    if verbose:
        status = "PASS" if t4_pass else "FAIL"
        print(f"  {status}  T4: manifest builds and validates ({len(manifest)} rows)")
        if not t4_pass:
            for err in errors[:5]:
                print(f"        ERROR: {err}")
            if len(errors) > 5:
                print(f"        ... and {len(errors) - 5} more errors")
    passed = passed and t4_pass

    # ------------------------------------------------------------------
    # T5: all FLOOR_CONTRACT_ROWS and NC2_COMPONENT_ROWS have valid dispositions
    # ------------------------------------------------------------------
    all_rows = FLOOR_CONTRACT_ROWS + NC2_COMPONENT_ROWS
    bad_disp = [
        r["key"] for r in all_rows
        if r["disposition"] not in ALLOWED_DISPOSITIONS
    ]
    t5_pass = len(bad_disp) == 0
    if verbose:
        status = "PASS" if t5_pass else "FAIL"
        print(f"  {status}  T5: all {len(all_rows)} row dispositions are valid")
        if not t5_pass:
            print(f"        Bad dispositions: {bad_disp}")
    passed = passed and t5_pass

    # ------------------------------------------------------------------
    # T6: BitNet rows are preserved_trigger_gated (not used_now)
    # ------------------------------------------------------------------
    bitnet_rows = [
        r for r in all_rows
        if "bitnet" in r["key"].lower() or "1.58" in r["key"]
    ]
    t6_pass = all(r["disposition"] == PRESERVED_TRIGGER_GATED for r in bitnet_rows)
    if verbose:
        status = "PASS" if t6_pass else "FAIL"
        print(
            f"  {status}  T6: BitNet rows are {PRESERVED_TRIGGER_GATED!r} "
            f"({len(bitnet_rows)} rows)"
        )
        if not t6_pass:
            for r in bitnet_rows:
                if r["disposition"] != PRESERVED_TRIGGER_GATED:
                    print(f"        BAD: {r['key']} -> {r['disposition']!r}")
    passed = passed and t6_pass

    # ------------------------------------------------------------------
    # T7: iGRPO/GRPO and phase3 RLM/iGRPO rows are used_now
    # ------------------------------------------------------------------
    active_gate_keys = {
        "floor_contract.iGRPO/GRPO",
        "floor_contract.phase3.RLM_mechanism",
        "floor_contract.phase3.iGRPO_two_stage",
        "floor_contract.phase3.LoRA_fp16_C_arm",
        "nc2_component_contract.RLM_recursive_generation",
        "nc2_component_contract.iGRPO_group_relative_PG",
    }
    all_rows_by_key = {r["key"]: r for r in all_rows}
    bad_active = [
        k for k in active_gate_keys
        if k in all_rows_by_key
        and all_rows_by_key[k]["disposition"] != USED_NOW
    ]
    t7_pass = len(bad_active) == 0
    if verbose:
        status = "PASS" if t7_pass else "FAIL"
        print(f"  {status}  T7: active C14 gate rows are {USED_NOW!r}")
        if not t7_pass:
            print(f"        Not used_now: {bad_active}")
    passed = passed and t7_pass

    return passed


# ---------------------------------------------------------------------------
# __main__
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="floor_contract_manifest.py — C14 floor contract manifest + CPU selftest"
    )
    parser.add_argument(
        "--test",
        action="store_true",
        default=False,
        help="Run CPU selftest (default: always run)",
    )
    parser.add_argument(
        "--manifest",
        action="store_true",
        default=False,
        help="Print manifest summary before running selftest",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        default=False,
        help="Suppress per-test output",
    )
    args = parser.parse_args()

    verbose = not args.quiet

    if args.manifest:
        repo_root = Path(__file__).resolve().parent.parent.parent
        manifest = build_manifest(repo_root)
        print(f"Manifest: {len(manifest)} rows")
        used_now = sum(1 for r in manifest.values() if r["disposition"] == USED_NOW)
        trigger_gated = sum(
            1 for r in manifest.values() if r["disposition"] == PRESERVED_TRIGGER_GATED
        )
        blocked = sum(
            1 for r in manifest.values() if r["disposition"] == BLOCKED_EXACT
        )
        print(f"  used_now={used_now}  preserved_trigger_gated={trigger_gated}  "
              f"blocked_with_exact_adapter_surface={blocked}")
        print()
        for key, row in sorted(manifest.items()):
            disp = row["disposition"]
            print(f"  [{disp[:4].upper()}] {key}")
        print()

    print("floor_contract_manifest.py CPU selftest")
    print("-" * 50)

    ok = _run_cpu_selftest(verbose=verbose)

    print("-" * 50)
    if ok:
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
