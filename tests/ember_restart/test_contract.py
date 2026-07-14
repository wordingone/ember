# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts" / "ember_restart" / "contract.py"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return _sha256(path)


def _candidate_manifest(tmp_path: Path) -> Path:
    tokenizer = tmp_path / "tokenizer.json"
    tokenizer.write_text('{"owned":true,"vocab_size":32000}\n', encoding="utf-8")
    tokenizer_sha = _sha256(tokenizer)
    tokenizer_script = tmp_path / "tokenizer" / "train_owned.py"
    tokenizer_script.parent.mkdir(parents=True)
    tokenizer_script.write_text("print('owned tokenizer training')\n", encoding="utf-8")
    tokenizer_corpus = tmp_path / "tokenizer" / "corpus-manifest.json"
    tokenizer_corpus_sha = _write_json(
        tokenizer_corpus, {"schema_version": "owned-tokenizer-corpus-v1", "documents": 1}
    )
    tokenizer_verifier = tmp_path / "verifiers" / "tokenizer_freeze.py"
    tokenizer_verifier.parent.mkdir(parents=True)
    tokenizer_verifier.write_text(
        """import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


parser = argparse.ArgumentParser()
parser.add_argument("--tokenizer", required=True)
parser.add_argument("--training-script", required=True)
parser.add_argument("--training-corpus-manifest", required=True)
args = parser.parse_args()
tokenizer = json.loads(Path(args.tokenizer).read_text(encoding="utf-8"))
if tokenizer.get("vocab_size") != 32000:
    raise SystemExit(2)
print(json.dumps({
    "schema_version": "ember-owned-tokenizer-freeze-v1",
    "result": "FROZEN",
    "tokenizer_sha256": sha(args.tokenizer),
    "vocab_size": 32000,
    "training_script_sha256": sha(args.training_script),
    "training_corpus_sha256": sha(args.training_corpus_manifest),
    "verifier_sha256": sha(__file__),
    "borrowed_tokenizer": False,
    "frozen_pre_step0": True,
}, sort_keys=True))
""",
        encoding="utf-8",
    )
    tokenizer_verifier_record = {
        "path": str(tokenizer_verifier.relative_to(tmp_path)),
        "sha256": _sha256(tokenizer_verifier),
    }
    tokenizer_freeze = tmp_path / "receipts" / "tokenizer-freeze.json"
    tokenizer_freeze_sha = _write_json(
        tokenizer_freeze,
        {
            "schema_version": "ember-owned-tokenizer-freeze-v1",
            "result": "FROZEN",
            "tokenizer_sha256": tokenizer_sha,
            "vocab_size": 32000,
            "training_script_sha256": _sha256(tokenizer_script),
            "training_corpus_sha256": tokenizer_corpus_sha,
            "verifier_sha256": tokenizer_verifier_record["sha256"],
            "borrowed_tokenizer": False,
            "frozen_pre_step0": True,
        },
    )

    data_verifier = tmp_path / "verifiers" / "training_data.py"
    data_verifier.parent.mkdir(parents=True, exist_ok=True)
    data_verifier.write_text(
        """import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


parser = argparse.ArgumentParser()
parser.add_argument("--data-manifest", required=True)
parser.add_argument("--tokenizer", required=True)
parser.add_argument("--capability", required=True)
args = parser.parse_args()
data_path = Path(args.data_manifest)
payload = json.loads(data_path.read_text(encoding="utf-8"))
root = data_path.parents[1]
source = root / payload["source_manifest"]["path"]
records = root / payload["records_artifact"]["path"]
if payload["capability"] != args.capability:
    raise SystemExit(2)
semantic_checks = {
    "text": ["token_roundtrip", "source_target_pair"],
    "image": ["token_roundtrip", "source_target_pair", "raw_image_text_pair"],
    "audio": ["token_roundtrip", "source_target_pair", "raw_audio_text_pair"],
    "reasoning": ["token_roundtrip", "source_target_pair", "local_answer_execution"],
    "tool": ["token_roundtrip", "source_target_pair", "typed_tool_execution"],
}
print(json.dumps({
    "schema_version": "ember-training-data-verification-v1",
    "result": "VERIFIED",
    "capability": args.capability,
    "data_manifest_sha256": sha(data_path),
    "tokenizer_sha256": sha(args.tokenizer),
    "verifier_sha256": sha(__file__),
    "data_class": payload["data_class"],
    "record_count": payload["record_count"],
    "token_count": payload["token_count"],
    "source_manifest_sha256": sha(source),
    "records_artifact_sha256": sha(records),
    "semantic_checks": (
        semantic_checks[args.capability]
        if payload["data_class"] == "SEMANTIC_PRETRAINING"
        else []
    ),
}, sort_keys=True))
""",
        encoding="utf-8",
    )
    data_verifier_record = {
        "path": str(data_verifier.relative_to(tmp_path)),
        "sha256": _sha256(data_verifier),
    }

    data_entries = []
    for capability in ("text", "image", "audio", "reasoning", "tool"):
        source_manifest = tmp_path / "sources" / f"{capability}.json"
        source_hash = _write_json(
            source_manifest,
            {
                "schema_version": "ember-owned-source-v1",
                "capability": capability,
                "records": 1,
                "model_mediated": False,
                "borrowed_labels": False,
            },
        )
        records_artifact = tmp_path / "records" / f"{capability}.json"
        records_hash = _write_json(
            records_artifact,
            {
                "schema_version": "ember-owned-records-v1",
                "capability": capability,
                "prompt": f"owned {capability} prompt",
                "target": f"owned {capability} target",
            },
        )
        data_manifest = tmp_path / "data" / f"{capability}.json"
        data_hash = _write_json(
            data_manifest,
            {
                "schema_version": "ember-owned-training-data-v1",
                "capability": capability,
                "data_class": "SMOKE_ONLY",
                "tokenizer_sha256": tokenizer_sha,
                "model_mediated": False,
                "borrowed_labels": False,
                "record_count": 1,
                "token_count": 1,
                "source_manifest": {
                    "path": str(source_manifest.relative_to(tmp_path)),
                    "sha256": source_hash,
                },
                "records_artifact": {
                    "path": str(records_artifact.relative_to(tmp_path)),
                    "sha256": records_hash,
                },
            },
        )
        data_receipt = tmp_path / "receipts" / f"data-{capability}.json"
        data_receipt_hash = _write_json(
            data_receipt,
            {
                "schema_version": "ember-training-data-verification-v1",
                "result": "VERIFIED",
                "capability": capability,
                "data_manifest_sha256": data_hash,
                "tokenizer_sha256": tokenizer_sha,
                "verifier_sha256": data_verifier_record["sha256"],
                "data_class": "SMOKE_ONLY",
                "record_count": 1,
                "token_count": 1,
                "source_manifest_sha256": source_hash,
                "records_artifact_sha256": records_hash,
                "semantic_checks": [],
            },
        )
        data_entries.append(
            {
                "capability": capability,
                "manifest_path": str(data_manifest.relative_to(tmp_path)),
                "sha256": data_hash,
                "owned": True,
                "locally_verified": True,
                "verifier": data_verifier_record,
                "verification_receipt": {
                    "path": str(data_receipt.relative_to(tmp_path)),
                    "sha256": data_receipt_hash,
                },
            }
        )

    optimizer = {
        "implementation": "torch.optim.AdamW",
        "hyperparameters": {
            "learning_rate": 1e-5,
            "betas": [0.9, 0.999],
            "eps": 1e-8,
            "weight_decay": 0.01,
            "foreach": False,
        },
        "state_format": "torch-optimizer-state-v1",
    }
    shard = tmp_path / "checkpoint" / "model-00001.safetensors"
    shard.parent.mkdir(parents=True)
    shard.write_bytes(b"owned-random-init-checkpoint")
    shard_records = [
        {
            "path": str(shard.relative_to(tmp_path)),
            "sha256": _sha256(shard),
            "bytes": shard.stat().st_size,
        }
    ]
    expert_banks = []
    for index, domain in enumerate(("vision", "audio", "reasoning", "tool")):
        expert = tmp_path / "checkpoint" / f"expert-{domain}.safetensors"
        expert.write_bytes(f"owned-{domain}-expert-genesis-{index}".encode("utf-8"))
        expert_hash = _sha256(expert)
        expert_path = str(expert.relative_to(tmp_path))
        shard_records.append(
            {"path": expert_path, "sha256": expert_hash, "bytes": expert.stat().st_size}
        )
        expert_banks.append(
            {"id": domain, "domain": domain, "path": expert_path, "genesis_sha256": expert_hash}
        )
    checkpoint_index = tmp_path / "checkpoint" / "checkpoint-manifest.json"
    checkpoint_index_hash = _write_json(
        checkpoint_index,
        {"shards": shard_records, "optimizer": optimizer},
    )
    parameter_counts = {
        "allocated_parameters": 3_134_515_200,
        "unique_parameters": 3_134_515_200,
        "trainable_parameters": 3_134_515_200,
        "active_parameters": 1_020_585_984,
        "episode_trainable_parameters": 1_020_585_984,
        "served_parameters": 3_134_515_200,
    }
    model_config = tmp_path / "configs" / "ember-restart-3b.json"
    model_config_hash = _write_json(
        model_config,
        {
            "contract_name": "ember-restart-3b",
            "contract_version": 2,
            "model": {
                "hidden_size": 2048,
                "layers": 14,
                "attention_heads": 16,
                "vocab_size": 32000,
                "tied_embeddings": True,
                "image_projection": {"input_shape": [48, 48, 3]},
                "audio_projection": {"frame_samples": 640},
                "expert_routing": {"expert_names": ["vision", "audio", "reasoning", "tool"]},
                "total_unique_trainable_parameters": 3_134_515_200,
            },
            "training": {"optimizer": optimizer},
        },
    )
    counter = tmp_path / "counter" / "instantiated_meta_counter.py"
    counter.parent.mkdir(parents=True)
    counter.write_text(
        """import argparse
import hashlib
import json
import math
from pathlib import Path


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


parser = argparse.ArgumentParser()
parser.add_argument("--model-config", required=True)
parser.add_argument("--checkpoint-manifest", required=True)
parser.add_argument("--active-expert", required=True)
args = parser.parse_args()
config = json.loads(Path(args.model_config).read_text(encoding="utf-8"))
checkpoint = json.loads(Path(args.checkpoint_manifest).read_text(encoding="utf-8"))
if not checkpoint.get("shards"):
    raise SystemExit(3)
model = config["model"]
hidden = model["hidden_size"]
layers = model["layers"]
experts = model["expert_routing"]["expert_names"]
image_input = math.prod(model["image_projection"]["input_shape"])
audio_input = model["audio_projection"]["frame_samples"]
expert_per_layer = 12 * hidden * hidden
total = (
    model["vocab_size"] * hidden
    + layers * (4 * hidden * hidden + 2 * hidden + len(experts) * expert_per_layer)
    + image_input * hidden
    + audio_input * hidden
    + hidden
)
active = total - layers * (len(experts) - 1) * expert_per_layer
print(json.dumps({
    "result": "MEASURED",
    "subject_checkpoint_sha256": sha256(args.checkpoint_manifest),
    "model_config_sha256": sha256(args.model_config),
    "architecture_revision": "ember-sparse-3b-v1",
    "allocated_parameters": total,
    "unique_parameters": total,
    "trainable_parameters": total,
    "served_parameters": total,
    "active_parameters": active,
    "episode_trainable_parameters": active,
    "active_expert_ids": [args.active_expert],
}, sort_keys=True))
""",
        encoding="utf-8",
    )
    counter_record = {
        "path": str(counter.relative_to(tmp_path)),
        "sha256": _sha256(counter),
    }
    _write_json(
        tmp_path / "trusted-verifiers.json",
        {
            "schema_version": "ember-trusted-verifiers-v1",
            "verifiers": [
                {
                    **counter_record,
                    "evidence_classes": ["parameter_realization"],
                    "criterion_ids": [],
                },
                {
                    **data_verifier_record,
                    "evidence_classes": ["training_data"],
                    "criterion_ids": [],
                },
                {
                    **tokenizer_verifier_record,
                    "evidence_classes": ["tokenizer_freeze"],
                    "criterion_ids": [],
                },
            ],
        },
    )
    parameter_receipt = tmp_path / "receipts" / "parameter-count.json"
    parameter_receipt_hash = _write_json(
        parameter_receipt,
        {
            "result": "MEASURED",
            "subject_checkpoint_sha256": checkpoint_index_hash,
            "counter_sha256": counter_record["sha256"],
            "model_config_sha256": model_config_hash,
            "architecture_revision": "ember-sparse-3b-v1",
            **parameter_counts,
            "active_expert_ids": ["reasoning"],
            "expert_genesis_sha256": {
                bank["id"]: bank["genesis_sha256"] for bank in expert_banks
            },
        },
    )
    optimizer_receipt = tmp_path / "receipts" / "optimizer.json"
    optimizer_receipt_hash = _write_json(
        optimizer_receipt,
        {
            "schema_version": "ember-optimizer-realization-v1",
            "result": "REALIZED",
            **optimizer,
            "model_config_sha256": model_config_hash,
        },
    )

    manifest = {
        "schema_version": "ember-owned-rung-v1",
        "stage": "CHECKPOINT_CANDIDATE",
        "run_id": "ember-3b-test",
        "source_commit": "7f751ac0b4c26e1f7d6278e46a6e6bb3f0ecd647",
        "lineage": {
            "genesis": "OWNED_RANDOM_INIT",
            "parent_checkpoint_sha256": None,
            "borrowed_weights": False,
            "borrowed_teachers": False,
            "borrowed_judges": False,
            "borrowed_filters": False,
            "borrowed_generated_labels": False,
        },
        "architecture": {
            "family": "ember-unified-decoder",
            "revision": "ember-sparse-3b-v1",
            "model_config": {
                "path": str(model_config.relative_to(tmp_path)),
                "sha256": model_config_hash,
            },
            **parameter_counts,
            "parameter_counter": counter_record,
            "parameter_receipt": {
                "path": str(parameter_receipt.relative_to(tmp_path)),
                "sha256": parameter_receipt_hash,
            },
            "shared_core": True,
            "sparse_differentiated_capacity": True,
            "task_level_expert_routing": True,
            "asymmetric_expert_initialization": True,
            "expert_banks": expert_banks,
            "active_expert_ids": ["reasoning"],
            "raw_image_patches": True,
            "raw_audio_frames": True,
            "soft_token_splicing": True,
            "multimodal_span_attention": True,
            "rope_2d": True,
            "separate_pretrained_encoders": False,
        },
        "tokenizer": {
            "path": str(tokenizer.relative_to(tmp_path)),
            "sha256": tokenizer_sha,
            "owned": True,
            "kind": "OWNED_TRAINED",
            "vocab_size": 32000,
            "training_script": {
                "path": str(tokenizer_script.relative_to(tmp_path)),
                "sha256": _sha256(tokenizer_script),
            },
            "training_corpus_manifest": {
                "path": str(tokenizer_corpus.relative_to(tmp_path)),
                "sha256": tokenizer_corpus_sha,
            },
            "freeze_receipt": {
                "path": str(tokenizer_freeze.relative_to(tmp_path)),
                "sha256": tokenizer_freeze_sha,
            },
            "verifier": tokenizer_verifier_record,
        },
        "training_data": data_entries,
        "training": {
            "input_class": "SMOKE_ONLY",
            "optimizer": optimizer,
            "optimizer_receipt": {
                "path": str(optimizer_receipt.relative_to(tmp_path)),
                "sha256": optimizer_receipt_hash,
            },
            "tokens_seen": 5,
            "modality_tokens": {
                "text": 1,
                "image": 1,
                "audio": 1,
                "reasoning": 1,
                "tool": 1,
            },
            "command": "python scripts/train_owned_3b.py --manifest run.json",
        },
        "checkpoint": {
            "manifest_path": str(checkpoint_index.relative_to(tmp_path)),
            "sha256": checkpoint_index_hash,
        },
    }
    manifest_path = tmp_path / "run.json"
    _write_json(manifest_path, manifest)
    return manifest_path

def test_checkpoint_candidate_binds_owned_multimodal_reasoning_tool_path(tmp_path: Path):
    manifest = _candidate_manifest(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "validate",
            str(manifest),
            "--trusted-verifier-registry",
            str(tmp_path / "trusted-verifiers.json"),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["valid"] is True
    assert payload["stage"] == "CHECKPOINT_CANDIDATE"
