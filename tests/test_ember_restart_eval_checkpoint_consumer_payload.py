# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import torch


SCRIPT = Path(__file__).parents[1] / "scripts" / "ember_restart_eval_checkpoint_consumer.py"
EXPERTS = ("vision", "audio", "reasoning", "tool")


def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def test_rejects_replay_payload_rng_drift_even_when_shard_is_rehashed():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        contract = {"name": "paged_8bit_adamw", "implementation": "bitsandbytes.optim.PagedAdamW8bit", "hyperparameters": {"learning_rate": 1e-5}, "state_format": "bitsandbytes-paged-8bit-adamw-state-dict-v1"}
        config = root / "config.json"; config.write_text(json.dumps({"training": {"optimizer": contract}}), encoding="utf-8")
        cursor = {"shard": "owned.json", "record_index": 1, "global_step": 1, "tokens_seen": 3}
        cpu, cuda = torch.tensor([1, 2], dtype=torch.uint8), torch.tensor([3, 4], dtype=torch.uint8)
        replay = root / "replay-state.pt"; torch.save({"rng_state": {"cpu": torch.tensor([9, 9], dtype=torch.uint8), "cuda": cuda}, "data_cursor": cursor}, replay)
        realization = {"implementation": contract["implementation"], "implementation_source_sha256": "a" * 64, "state_format": contract["state_format"], "optimizer_contract_sha256": hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
        shared = root / "shared.pt"; torch.save({"model": {}, "optimizer": {}, "optimizer_contract": contract, "optimizer_realization": realization}, shared)
        records = []
        for path, role in [(shared, "shared_model_and_optimizer"), (replay, "replay_state")]: records.append({"path": path.name, "role": role, "bytes": path.stat().st_size, "sha256": digest(path)})
        for expert in EXPERTS:
            path = root / f"expert-{expert}.pt"; torch.save({"expert": expert, "model": {}}, path); records.append({"path": path.name, "role": f"expert_{expert}", "bytes": path.stat().st_size, "sha256": digest(path)})
        manifest = {"schema_version": "ember-sparse-checkpoint-v3", "launch_seed": 82, "rng_state_sha256": {"cpu": hashlib.sha256(cpu.numpy().tobytes()).hexdigest(), "cuda": hashlib.sha256(cuda.numpy().tobytes()).hexdigest()}, "data_cursor": cursor, "model_config_sha256": digest(config), "contract_sha256": "b" * 64, "active_expert_ids": ["tool"], "expert_genesis_sha256": {name: format(index + 10, "x") * 64 for index, name in enumerate(EXPERTS)}, "expert_checkpoint_sha256": {name: next(record["sha256"] for record in records if record["path"] == f"expert-{name}.pt") for name in EXPERTS}, "shared_optimizer_shard_sha256": records[0]["sha256"], "optimizer_contract": contract, "optimizer_realization": realization, "shards": records}
        path = root / "checkpoint-manifest.json"; path.write_text(json.dumps(manifest), encoding="utf-8")
        output = root / "receipt.json"
        completed = subprocess.run([sys.executable, str(SCRIPT), "verify", str(path), "--model-config", str(config), "--output", str(output)], capture_output=True, text=True)
        assert completed.returncode != 0
        assert not output.exists()
