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
    tokenizer.write_text('{"owned":true}\n', encoding="utf-8")

    data_entries = []
    for capability in ("text", "image", "audio", "reasoning", "tool"):
        data_manifest = tmp_path / "data" / f"{capability}.json"
        data_hash = _write_json(
            data_manifest,
            {"capability": capability, "owned": True, "rows": 1},
        )
        data_entries.append(
            {
                "capability": capability,
                "manifest_path": str(data_manifest.relative_to(tmp_path)),
                "sha256": data_hash,
                "owned": True,
                "locally_verified": True,
            }
        )

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
        {"shards": shard_records},
    )
    parameter_counts = {
        "allocated_parameters": 3_134_515_200,
        "unique_parameters": 3_134_515_200,
        "trainable_parameters": 3_134_515_200,
        "active_parameters": 1_020_585_984,
        "episode_trainable_parameters": 1_020_585_984,
        "served_parameters": 3_134_515_200,
    }
    counter = tmp_path / "counter" / "instantiated_meta_counter.py"
    counter.parent.mkdir(parents=True)
    counter.write_text("# fixture instantiated-meta counter\n", encoding="utf-8")
    counter_record = {
        "path": str(counter.relative_to(tmp_path)),
        "sha256": _sha256(counter),
    }
    parameter_receipt = tmp_path / "receipts" / "parameter-count.json"
    parameter_receipt_hash = _write_json(
        parameter_receipt,
        {
            "result": "MEASURED",
            "subject_checkpoint_sha256": checkpoint_index_hash,
            "counter_sha256": counter_record["sha256"],
            **parameter_counts,
            "active_expert_ids": ["reasoning"],
            "expert_genesis_sha256": {
                bank["id"]: bank["genesis_sha256"] for bank in expert_banks
            },
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
            "sha256": _sha256(tokenizer),
            "owned": True,
        },
        "training_data": data_entries,
        "training": {
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
        [sys.executable, str(VALIDATOR), "validate", str(manifest)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["valid"] is True
    assert payload["stage"] == "CHECKPOINT_CANDIDATE"
