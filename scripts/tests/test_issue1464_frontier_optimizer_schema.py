# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import json
import hashlib
import sys
from copy import deepcopy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import frontier_receipt as frontier  # noqa: E402
import r1_exit_battery as battery  # noqa: E402


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _manifest() -> dict:
    return {
        "model_config_sha256": "c" * 64,
        "optimizer_state_owner_ids": ["shared", "vision"],
        "optimizer_state_owner_shard_sha256": {
            "shared": DIGEST_A,
            "vision": DIGEST_B,
        },
        "rng_state_sha256": "d" * 64,
        "optimizer_contract": {"name": "AdamW8bit"},
        "launch_seed": 830001,
        "data_cursor": {"tokens_seen": 1024, "global_step": 100},
        "shards": [
            {"path": "optimizer-state-shared.pt", "sha256": DIGEST_A},
            {"path": "optimizer-state-vision.pt", "sha256": DIGEST_B},
        ],
    }


def test_v5_owner_shards_flow_into_reproducibility_verbatim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adjudication = tmp_path / "reproduction-adjudication.json"
    adjudication.write_text(
        json.dumps({"status": "REPRODUCED", "evidence_ref": "owned-receipt"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(frontier, "_repo_file", lambda *_args: tmp_path / "tokenizer.json")
    monkeypatch.setattr(frontier, "_sha256", lambda _path: "e" * 64)

    result = frontier.leg_reproducibility(
        tmp_path, _manifest(), {"manifest_sha256": "f" * 64}
    )

    assert result["optimizer_state_sha256"] == {
        "shared": DIGEST_A,
        "vision": DIGEST_B,
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda doc: doc.pop("optimizer_state_owner_shard_sha256"),
        lambda doc: doc.__setitem__("optimizer_state_shard_sha256", DIGEST_A),
        lambda doc: doc.__setitem__("optimizer_state_owner_shard_sha256", {}),
        lambda doc: doc.__setitem__("optimizer_state_owner_shard_sha256", []),
        lambda doc: doc.__setitem__("optimizer_state_owner_ids", ["shared"]),
        lambda doc: doc["optimizer_state_owner_shard_sha256"].__setitem__("shared", "A" * 64),
        lambda doc: doc["shards"][0].__setitem__("sha256", "0" * 64),
    ],
    ids=["neither", "both", "empty", "not-object", "key-mismatch", "non-digest", "digest-mismatch"],
)
def test_closed_optimizer_union_refuses_every_invalid_shape(mutate) -> None:
    manifest = deepcopy(_manifest())
    mutate(manifest)

    with pytest.raises(frontier.FrontierRefusal, match="OPTIMIZER_STATE_SCHEMA_INVALID"):
        frontier._select_optimizer_state_binding(manifest)


def test_v3_scalar_remains_accepted() -> None:
    manifest = _manifest()
    manifest.pop("optimizer_state_owner_ids")
    manifest.pop("optimizer_state_owner_shard_sha256")
    manifest["optimizer_state_shard_sha256"] = DIGEST_A
    manifest["shards"] = [{"path": "optimizer-state.pt", "sha256": DIGEST_A}]

    field, value, cross_refs = frontier._select_optimizer_state_binding(manifest)

    assert field == "optimizer_state_shard_sha256"
    assert value == DIGEST_A
    assert cross_refs == {"optimizer-state.pt": DIGEST_A}


CHECKPOINT_ROLES = (
    "shared_model",
    "optimizer_state_shared",
    "replay_state",
    "expert_vision",
    "expert_audio",
    "expert_reasoning",
    "expert_tool",
)


def _write_role_manifest(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    hashes: dict[str, str] = {}
    shards = []
    for role in CHECKPOINT_ROLES:
        relative = f"{role}.pt"
        payload = f"owned-{role}".encode("utf-8")
        (tmp_path / relative).write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        hashes[role] = digest
        shards.append({"role": role, "path": relative, "sha256": digest})
    manifest_path = tmp_path / "checkpoint-manifest.json"
    manifest_path.write_text(json.dumps({"shards": shards}), encoding="utf-8")
    return manifest_path, hashes


def test_identity_spine_accepts_complete_rehashed_manifest_role_map(tmp_path: Path) -> None:
    manifest_path, hashes = _write_role_manifest(tmp_path)

    assert battery._identity_spine_checkpoint_hash_defects(manifest_path, hashes) == []


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda hashes: hashes.pop("expert_tool"), "missing role 'expert_tool'"),
        (lambda hashes: hashes.__setitem__("foreign", "f" * 64), "unknown role 'foreign'"),
        (
            lambda hashes: hashes.__setitem__("shared_model", "0" * 64),
            "role 'shared_model' does not equal the independently rehashed shard",
        ),
    ],
    ids=["missing", "extra", "digest"],
)
def test_identity_spine_refuses_nonidentical_role_maps(tmp_path: Path, mutate, expected: str) -> None:
    manifest_path, hashes = _write_role_manifest(tmp_path)
    mutate(hashes)

    defects = battery._identity_spine_checkpoint_hash_defects(manifest_path, hashes)

    assert any(expected in defect for defect in defects), defects


def test_identity_spine_refuses_manifest_shard_digest_mismatch(tmp_path: Path) -> None:
    manifest_path, hashes = _write_role_manifest(tmp_path)
    (tmp_path / "replay_state.pt").write_bytes(b"changed-after-manifest")

    defects = battery._identity_spine_checkpoint_hash_defects(manifest_path, hashes)

    assert defects == [
        "identity_spine.checkpoint_file_sha256s cannot be independently rehashed: "
        "CHECKPOINT_SHARD_SHA_MISMATCH"
    ]
