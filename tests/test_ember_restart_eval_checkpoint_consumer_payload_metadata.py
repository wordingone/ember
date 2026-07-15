# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import tempfile
from pathlib import Path

import torch

from test_ember_restart_eval_checkpoint_consumer_v3_contract import invoke, write_v3


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rehash_declared_shard(manifest: Path, shard: Path) -> None:
    content = json.loads(manifest.read_text(encoding="utf-8"))
    for record in content["shards"]:
        if record["path"] == shard.name:
            record["bytes"] = shard.stat().st_size
            record["sha256"] = _sha256(shard)
            break
    else:
        raise AssertionError(f"missing shard record for {shard.name}")
    if shard.name == "shared.pt":
        content["shared_optimizer_shard_sha256"] = _sha256(shard)
    elif shard.name.startswith("expert-"):
        expert = shard.stem.removeprefix("expert-")
        content["expert_checkpoint_sha256"][expert] = _sha256(shard)
    manifest.write_text(json.dumps(content), encoding="utf-8")


def test_rejects_rehashed_replay_cursor_payload_drift_before_output():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        manifest = write_v3(root)
        replay = root / "replay-state.pt"
        content = torch.load(replay, map_location="cpu", weights_only=True)
        content["data_cursor"] = {**content["data_cursor"], "tokens_seen": 4}
        torch.save(content, replay)
        _rehash_declared_shard(manifest, replay)

        output = root / "receipt.json"
        completed = invoke(manifest, output)

        assert completed.returncode != 0
        assert "replay payload drifts" in completed.stderr
        assert not output.exists()


def test_rejects_rehashed_shared_optimizer_payload_drift_before_output():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        manifest = write_v3(root)
        shared = root / "shared.pt"
        content = torch.load(shared, map_location="cpu", weights_only=True)
        content["optimizer_contract"] = {**content["optimizer_contract"], "name": "substituted"}
        torch.save(content, shared)
        _rehash_declared_shard(manifest, shared)

        output = root / "receipt.json"
        completed = invoke(manifest, output)

        assert completed.returncode != 0
        assert "shared optimizer payload drifts" in completed.stderr
        assert not output.exists()


def test_rejects_rehashed_expert_identity_payload_drift_before_output():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        manifest = write_v3(root)
        shard = root / "expert-tool.pt"
        content = torch.load(shard, map_location="cpu", weights_only=True)
        content["expert"] = "audio"
        torch.save(content, shard)
        _rehash_declared_shard(manifest, shard)

        output = root / "receipt.json"
        completed = invoke(manifest, output)

        assert completed.returncode != 0
        assert "expert payload identity mismatch: tool" in completed.stderr
        assert not output.exists()
