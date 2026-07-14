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
    checkpoint_index = tmp_path / "checkpoint" / "checkpoint-manifest.json"
    checkpoint_index_hash = _write_json(
        checkpoint_index,
        {
            "shards": [
                {
                    "path": str(shard.relative_to(tmp_path)),
                    "sha256": _sha256(shard),
                    "bytes": shard.stat().st_size,
                }
            ]
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
            "allocated_parameters": 3_134_000_000,
            "unique_parameters": 3_134_000_000,
            "trainable_parameters": 3_134_000_000,
            "active_parameters": 1_021_000_000,
            "episode_trainable_parameters": 1_021_000_000,
            "served_parameters": 3_134_000_000,
            "shared_core": True,
            "sparse_differentiated_capacity": True,
            "task_level_expert_routing": True,
            "asymmetric_expert_initialization": True,
            "expert_banks": [
                {"id": domain, "domain": domain, "genesis_sha256": f"{index + 1:064x}"}
                for index, domain in enumerate(("vision", "audio", "reasoning", "tool"))
            ],
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
