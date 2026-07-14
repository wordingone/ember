# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "ember_restart_eval_checkpoint_consumer.py"
EXPERTS = ("vision", "audio", "reasoning", "tool")


def write_v3(root: Path, *, mutate=None) -> Path:
    records = []
    for path, role in [("shared.pt", "shared_model_and_optimizer"), ("replay-state.pt", "replay_state"), *[(f"expert-{name}.pt", f"expert_{name}") for name in EXPERTS]]:
        shard = root / path
        shard.write_bytes(path.encode("utf-8"))
        records.append({"path": path, "role": role, "bytes": shard.stat().st_size, "sha256": hashlib.sha256(shard.read_bytes()).hexdigest()})
    contract = {"name": "AdamW", "implementation": "torch.optim.AdamW", "hyperparameters": {"param_group_count": 1}, "state_format": "torch-optimizer-state-dict-v1"}
    manifest = {"schema_version": "ember-sparse-checkpoint-v3", "launch_seed": 82, "rng_state_sha256": {"cpu": "a" * 64, "cuda": "b" * 64}, "data_cursor": {"shard": "owned.json", "record_index": 1, "global_step": 1, "tokens_seen": 3}, "model_config_sha256": "c" * 64, "contract_sha256": "d" * 64, "active_expert_ids": ["tool"], "expert_genesis_sha256": {name: "e" * 64 for name in EXPERTS}, "expert_checkpoint_sha256": {name: next(record["sha256"] for record in records if record["path"] == f"expert-{name}.pt") for name in EXPERTS}, "shared_optimizer_shard_sha256": records[0]["sha256"], "optimizer_contract": contract, "optimizer_realization": {"implementation": contract["implementation"], "implementation_source_sha256": "f" * 64, "state_format": contract["state_format"], "optimizer_contract_sha256": hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}, "shards": records}
    if mutate:
        mutate(manifest)
    path = root / "checkpoint-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def invoke(manifest: Path, output: Path):
    return subprocess.run([sys.executable, str(SCRIPT), "verify", str(manifest), "--output", str(output)], capture_output=True, text=True)


def test_accepts_closed_v3_checkpoint_manifest():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary); output = root / "receipt.json"
        completed = invoke(write_v3(root), output)
        assert completed.returncode == 0, completed.stderr
        assert json.loads(output.read_text())["shard_count"] == 6


def test_rejects_missing_optimizer_contract_before_output():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary); output = root / "receipt.json"
        completed = invoke(write_v3(root, mutate=lambda manifest: manifest.pop("optimizer_contract")), output)
        assert completed.returncode != 0
        assert not output.exists()


def test_rejects_wrong_expert_checkpoint_mapping_before_output():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary); output = root / "receipt.json"
        completed = invoke(write_v3(root, mutate=lambda manifest: manifest["expert_checkpoint_sha256"].__setitem__("tool", "0" * 64)), output)
        assert completed.returncode != 0
        assert not output.exists()
