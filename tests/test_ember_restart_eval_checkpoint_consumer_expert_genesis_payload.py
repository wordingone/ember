# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import tempfile
from pathlib import Path

import torch

from test_ember_restart_eval_checkpoint_consumer_v3_contract import invoke, write_v3


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_rejects_expert_payload_genesis_that_drifts_from_the_manifest_before_output():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        manifest_path = write_v3(root)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        shard = root / "expert-tool.pt"
        payload = torch.load(shard, map_location="cpu", weights_only=True)
        payload["genesis_sha256"] = "0" * 64
        torch.save(payload, shard)
        for record in manifest["shards"]:
            if record["path"] == shard.name:
                record["bytes"] = shard.stat().st_size
                record["sha256"] = _digest(shard)
        manifest["expert_checkpoint_sha256"]["tool"] = _digest(shard)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        output = root / "receipt.json"

        completed = invoke(manifest_path, output)

        assert completed.returncode != 0
        assert not output.exists()
