#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Generate the cond3 Artifact B fixture: one fully-resolved schema-v1 identity
manifest bound to real checkpoint bytes on disk (state/specs/cond3-seat-bridge-spec.md).

Every hash field in the generated manifest is the REAL sha256 of REAL bytes
persisted alongside it in ``evidence.json`` (or of the checkpoint file itself) --
never a hand-typed placeholder. Idempotent: reruns regenerate byte-identical
output because every input is deterministic.

disposition=OWNED_CANDIDATE, selected_as_owned_ember=false, recovery_state=CLEAN,
unresolved=[] (no field anywhere carries the {"status":"unresolved"} marker) --
this proves the round-trip pre-birth, credit-free, unselected.
"""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
# tests/ (not tools/scripts/receipts/... control paths) -- a raw binary
# checkpoint fixture cannot carry the goal_id/workstream_id/next_executed_outcome
# comment-marker binding the authority-conservation gate requires of files
# under a control path, and manifest.json must live alongside its checkpoint
# (model.ts convention: checkpoint file named literally "checkpoint" in the
# manifest's own directory) -- so the whole fixture lives under tests/.
FIXTURE_DIR = REPO_ROOT / "tests" / "ember_restart" / "__fixtures__" / "cond3-artifact-b"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


# Real byte content backing every ancillary identity hash. Persisted verbatim
# to evidence.json so any auditor can recompute every digest below from bytes
# actually on disk -- never a fabricated hex pattern.
EVIDENCE: dict[str, str] = {
    "architecture": "cond3-artifact-b: 2x2 float32 linear probe, no experts, no router",
    "tokenizer": "cond3-artifact-b-tokenizer-fixture: byte-level, vocab_size=256",
    "data.corpus": "cond3-artifact-b-corpus-fixture: owned pre-birth candidate corpus shard",
    "data.ordering": "cond3-artifact-b-ordering-fixture: deterministic shard order [0]",
    "data.curriculum": "cond3-artifact-b-curriculum-fixture: single-stage, no curriculum switches",
    "data.verifier": "cond3-artifact-b-verifier-fixture: accepted-input verifier v1 stub",
    "data.accepted_input.authority_record": "cond3-artifact-b: accepted-training-input authority record, github-issue-1015",
    "data.accepted_input.shard_manifest": "cond3-artifact-b: shard manifest, 1 shard, 0 rows dropped",
    "data.accepted_input.caller": "cond3-artifact-b: forwarding caller identity, scripts/ember_restart/build_cond3_artifact_b_fixture.py",
    "data.accepted_input.gate": "cond3-artifact-b: accepted-input gate decision, PASS",
    "data.accepted_input.validator": "cond3-artifact-b: accepted-input validator program v1",
    "data.accepted_input.forwarding_receipt": "cond3-artifact-b: forwarding receipt, input accepted 2026-07-23",
    "training.optimizer_state": "cond3-artifact-b: optimizer state, adamw, step=100, no exposure yet",
    "training.numerics": "cond3-artifact-b: numerics profile bf16-activations-fp32-master",
    "training.stopping_rule_receipt": "cond3-artifact-b: sufficient-pretraining-v1 criterion NOT_REACHED at step 100",
    "backend.executable": "cond3-artifact-b: backend executable identity stub, ember-serve-fixture v1",
    "backend.command": "cond3-artifact-b: backend launch command, python -m ember_serve --fixture",
    "backend.process_receipt": "cond3-artifact-b: process receipt, candidate not currently running",
    "evaluation.harness": "cond3-artifact-b: evaluation harness stub, no benchmark executed pre-birth",
    "evaluation.comparator": "cond3-artifact-b: evaluation comparator stub, none selected pre-birth",
    "evaluation.receipt": "cond3-artifact-b: evaluation receipt, counts_toward_owned_completion=false",
}


def _tensor_bytes() -> bytes:
    # 2x2 float32 tensor, real packed bytes -- the checkpoint file IS these bytes.
    return struct.pack("<4f", 1.0, -1.0, 0.5, -0.5)


def build_manifest(checkpoint_bytes: bytes) -> dict[str, Any]:
    checkpoint_sha256 = _sha256_bytes(checkpoint_bytes)
    tensor_sha256 = _sha256_bytes(checkpoint_bytes)  # single tensor IS the whole checkpoint

    evidence_sha = {key: _sha256_text(value) for key, value in EVIDENCE.items()}

    manifest: dict[str, Any] = {
        "authority": {
            "goal_id": "EMBER-02",
            "workstream_id": "EMBER-02A",
            "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
        },
        "schema": "ember-model-experiment-identity-v1",
        "identity": {
            "model_id": "ember-cond3-artifact-b-candidate",
            "experiment_id": "experiment-cond3-artifact-b",
            "run_id": "run-cond3-artifact-b",
            "checkpoint_id": "checkpoint-cond3-artifact-b",
            "disposition": "OWNED_CANDIDATE",
            "selected_as_owned_ember": False,
        },
        "architecture": {
            "source": "scripts/ember_restart/build_cond3_artifact_b_fixture.py:EVIDENCE['architecture']",
            "sha256": evidence_sha["architecture"],
        },
        "checkpoint": {
            "format": "synthetic-bytes-v1",
            "byte_sha256": checkpoint_sha256,
            "tensors": [
                {
                    "name": "cond3.artifact_b.weight",
                    "shape": [2, 2],
                    "dtype": "float32",
                    "sha256": tensor_sha256,
                }
            ],
            "ancestry": [],
            "recovery_state": "CLEAN",
        },
        "tokenizer": {
            "id": "cond3-artifact-b-tokenizer",
            "sha256": evidence_sha["tokenizer"],
        },
        "data": {
            "corpus_id": "cond3-artifact-b-corpus",
            "sha256": evidence_sha["data.corpus"],
            "ordering_sha256": evidence_sha["data.ordering"],
            "curriculum_sha256": evidence_sha["data.curriculum"],
            "verifier_sha256": evidence_sha["data.verifier"],
            "clean_genesis": True,
            "accepted_input": {
                "input_id": "github-issue-1015",
                "authority_id": "ember-01-issue-1015",
                "authority_record_sha256": evidence_sha["data.accepted_input.authority_record"],
                "authority": "CURRENT_EXECUTABLE",
                "shard_manifest_sha256": evidence_sha["data.accepted_input.shard_manifest"],
                "caller_sha256": evidence_sha["data.accepted_input.caller"],
                "gate_sha256": evidence_sha["data.accepted_input.gate"],
                "validator_sha256": evidence_sha["data.accepted_input.validator"],
                "forwarding_receipt_sha256": evidence_sha["data.accepted_input.forwarding_receipt"],
            },
        },
        "parameters": {
            "allocated": 4,
            "unique": 4,
            "active": 4,
            "trainable": 4,
            "served": 4,
            "actually_trained": 0,
            "evidence_receipts": {
                "allocated": [],
                "unique": [],
                "active": [],
                "trainable": [],
                "served": [],
                "actually_trained": [],
            },
        },
        "training": {
            "steps": 100,
            "effective_tokens": 1000,
            "modality_mixture": {"text": 1.0, "image": 0.0, "audio": 0.0},
            "optimizer_state_sha256": evidence_sha["training.optimizer_state"],
            "numerics": {
                "profile": "bf16-activations-fp32-master",
                "sha256": evidence_sha["training.numerics"],
            },
            "stopping_rule": {
                "criterion_id": "sufficient-pretraining-v1",
                "result": "NOT_REACHED",
                "receipt_sha256": evidence_sha["training.stopping_rule_receipt"],
            },
        },
        "capabilities": {
            "native_modalities": {
                "text": {"state": "UNVERIFIED", "evidence_receipts": []},
                "image": {"state": "INAPPLICABLE", "evidence_receipts": []},
                "audio": {"state": "INAPPLICABLE", "evidence_receipts": []},
            },
            "reasoning": {"state": "UNVERIFIED", "evidence_receipts": []},
            "structured_tool_use": {"state": "UNVERIFIED", "evidence_receipts": []},
        },
        "mechanisms": {
            "experts": [],
            "router": [],
            "temporary_adapters": [],
            "permanent_merges": [],
            "memory_substrates": [],
            "world_models": [],
            "dreaming_updates": [],
            "deletion_objects": [],
        },
        "backend": {
            "executable_sha256": evidence_sha["backend.executable"],
            "process_identity": {
                "pid": 1,
                "start_time_utc": "2026-07-23T00:00:00Z",
                "executable_sha256": evidence_sha["backend.executable"],
                "command_sha256": evidence_sha["backend.command"],
                "nonce": "cond3-artifact-b-nonce-fixture",
            },
            "process_receipt_sha256": evidence_sha["backend.process_receipt"],
            "protocol": "fixture-v1",
            "device": "cpu",
            "runtime_dependencies": [],
            "resource_lease_id": "cond3-artifact-b-lease-fixture",
        },
        "evaluation": {
            "benchmark_id": "cond3-artifact-b-benchmark-fixture",
            "version": "v1",
            "split": "fixture",
            "harness_sha256": evidence_sha["evaluation.harness"],
            "subject_checkpoint_sha256": checkpoint_sha256,
            "comparator_identity": "cond3-artifact-b-comparator-fixture",
            "comparator_sha256": evidence_sha["evaluation.comparator"],
            "score": {"value": 0.0, "unit": "not-evaluated-pre-birth-candidate"},
            "uncertainty": {"value": 0.0, "unit": "not-evaluated-pre-birth-candidate"},
            "receipt_sha256": evidence_sha["evaluation.receipt"],
            "counts_toward_owned_completion": False,
        },
        "provenance": {
            "ownership": "OWNED_CLEAN_GENESIS",
            "exclusion_reasons": [],
            "learned_signal_sources": ["owned_training_data"],
            "neural_capability_credit_sources": ["owned_checkpoint"],
        },
        "unresolved": [],
    }
    return manifest


def main() -> int:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    checkpoint_bytes = _tensor_bytes()
    (FIXTURE_DIR / "checkpoint").write_bytes(checkpoint_bytes)
    (FIXTURE_DIR / "evidence.json").write_text(
        json.dumps(EVIDENCE, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    manifest = build_manifest(checkpoint_bytes)
    (FIXTURE_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote fixture to {FIXTURE_DIR}")
    print(f"checkpoint byte_sha256 = {_sha256_bytes(checkpoint_bytes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
