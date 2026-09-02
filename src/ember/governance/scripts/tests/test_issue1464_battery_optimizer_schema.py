# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest


ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
sys.path.insert(0, str(ROOT / "scripts"))

import r1_exit_battery as battery  # noqa: E402


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _manifest() -> dict:
    return {
        "schema_version": battery.SUPPORTED_CHECKPOINT_SCHEMA,
        "optimizer_state_owner_ids": ["shared", "vision"],
        "optimizer_state_owner_shard_sha256": {
            "shared": DIGEST_A,
            "vision": DIGEST_B,
        },
        "shards": [
            {"path": "optimizer-state-shared.pt", "role": "optimizer_state_shared", "sha256": DIGEST_A},
            {"path": "optimizer-state-vision.pt", "role": "optimizer_state_vision", "sha256": DIGEST_B},
        ],
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

    with pytest.raises(battery.R1ExitBatteryRefusal, match="OPTIMIZER_STATE_SCHEMA_INVALID"):
        battery._select_optimizer_state_binding(manifest)


def test_v5_write_integrity_binds_every_owner_shard(tmp_path: Path) -> None:
    manifest = _manifest()
    for shard in manifest["shards"]:
        path = tmp_path / shard["path"]
        path.write_bytes(shard["path"].encode("utf-8"))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        shard["sha256"] = digest
        shard["bytes"] = path.stat().st_size
        owner = shard["path"].removeprefix("optimizer-state-").removesuffix(".pt")
        manifest["optimizer_state_owner_shard_sha256"][owner] = digest
    manifest_path = tmp_path / "checkpoint-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = battery.verify_checkpoint_write_integrity(manifest_path)

    assert result["all_shards_ok"] is True
    assert all(row["cross_ref_ok"] for row in result["shards"])


def test_v3_scalar_remains_accepted() -> None:
    manifest = _manifest()
    manifest.pop("optimizer_state_owner_ids")
    manifest.pop("optimizer_state_owner_shard_sha256")
    manifest["optimizer_state_shard_sha256"] = DIGEST_A
    manifest["shards"] = [{"path": "optimizer-state.pt", "role": "optimizer_state", "sha256": DIGEST_A}]

    field, value, cross_refs = battery._select_optimizer_state_binding(manifest)

    assert field == "optimizer_state_shard_sha256"
    assert value == DIGEST_A
    assert cross_refs == {"optimizer-state.pt": DIGEST_A}
