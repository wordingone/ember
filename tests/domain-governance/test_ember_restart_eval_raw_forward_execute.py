# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import torch

from test_ember_restart_eval_checkpoint_consumer_v3_contract import write_v3


SCRIPT = Path(__file__).parents[1] / "scripts" / "ember_restart_eval_raw_forward.py"


def test_execute_rejects_detached_canonical_scalars_before_model_or_checkpoint_consumption():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source, config, tokenizer, output, canonical = root / "model.py", root / "config.json", root / "tokenizer.json", root / "receipt.json", root / "canonical.json"
        source.write_text("import torch\nclass RestartDecoderConfig:\n @classmethod\n def from_contract(cls, path): return cls()\nclass UnifiedDecoder(torch.nn.Module):\n def __init__(self, config, device='cpu', allow_production_allocation=False):\n  super().__init__(); self.weight=torch.nn.Parameter(torch.zeros(1,4,device=device))\n def forward(self, ids, active_expert=None):\n  return self.weight.expand(ids.shape[0],ids.shape[1],4)\n", encoding="utf-8")
        config.write_text("{}", encoding="utf-8")
        tokenizer.write_text(json.dumps({"version": "1.0", "truncation": None, "padding": None, "added_tokens": [], "normalizer": None, "pre_tokenizer": None, "post_processor": None, "decoder": None, "model": {"type": "WordLevel", "vocab": {"x": 0}, "unk_token": "x"}}), encoding="utf-8")
        checkpoint = write_v3(root)
        shared = root / "shared.pt"
        shared_payload = torch.load(shared, weights_only=True)
        shared_payload["model"] = {"weight": torch.zeros(1, 4)}
        torch.save(shared_payload, shared)
        manifest = json.loads(checkpoint.read_text())
        record = next(item for item in manifest["shards"] if item["path"] == "shared.pt")
        record.update(bytes=shared.stat().st_size, sha256=hashlib.sha256(shared.read_bytes()).hexdigest())
        manifest["shared_optimizer_shard_sha256"] = record["sha256"]
        checkpoint.write_text(json.dumps(manifest), encoding="utf-8")
        completed = subprocess.run([sys.executable, str(SCRIPT), "--tokenizer", str(tokenizer), "--checkpoint-manifest", str(checkpoint), "--checkpoint-sha256", hashlib.sha256(checkpoint.read_bytes()).hexdigest(), "--output", str(output), "--execute", "--model-source", str(source), "--model-source-sha256", hashlib.sha256(source.read_bytes()).hexdigest(), "--model-config", str(config), "--model-config-sha256", hashlib.sha256(config.read_bytes()).hexdigest(), "--active-expert", "tool", "--input-token-id", "0", "--max-new-tokens", "2", "--device", "cpu", "--canonical-output", str(canonical), "--benchmark-id", "fixture", "--benchmark-version", "v1", "--benchmark-capability", "text", "--split-sha256", "a" * 64, "--protocol-sha256", "b" * 64, "--row-id", "fixture-1"], capture_output=True, text=True)
        assert completed.returncode != 0
        assert "canonical output requires owned prompt and frozen split" in completed.stderr
        assert not output.exists()
        assert not canonical.exists()

def test_refuses_to_overwrite_existing_canonical_prediction_envelope():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source, config, tokenizer, output, canonical = root / "model.py", root / "config.json", root / "tokenizer.json", root / "receipt.json", root / "canonical.json"
        source.write_text("import torch\nclass RestartDecoderConfig:\n @classmethod\n def from_contract(cls, path): return cls()\nclass UnifiedDecoder(torch.nn.Module):\n def __init__(self, config, device='cpu', allow_production_allocation=False):\n  super().__init__(); self.weight=torch.nn.Parameter(torch.zeros(1,4,device=device))\n def forward(self, ids, active_expert=None):\n  return self.weight.expand(ids.shape[0],ids.shape[1],4)\n", encoding="utf-8")
        config.write_text("{}", encoding="utf-8")
        tokenizer.write_text(json.dumps({"version": "1.0", "truncation": None, "padding": None, "added_tokens": [], "normalizer": None, "pre_tokenizer": None, "post_processor": None, "decoder": None, "model": {"type": "WordLevel", "vocab": {"x": 0}, "unk_token": "x"}}), encoding="utf-8")
        checkpoint = write_v3(root)
        shared = root / "shared.pt"; shared_payload = torch.load(shared, weights_only=True); shared_payload["model"] = {"weight": torch.zeros(1, 4)}; torch.save(shared_payload, shared)
        manifest = json.loads(checkpoint.read_text()); record = next(item for item in manifest["shards"] if item["path"] == "shared.pt"); record.update(bytes=shared.stat().st_size, sha256=hashlib.sha256(shared.read_bytes()).hexdigest()); manifest["shared_optimizer_shard_sha256"] = record["sha256"]; checkpoint.write_text(json.dumps(manifest), encoding="utf-8")
        canonical.write_text("preserve", encoding="utf-8")
        completed = subprocess.run([sys.executable, str(SCRIPT), "--tokenizer", str(tokenizer), "--checkpoint-manifest", str(checkpoint), "--checkpoint-sha256", hashlib.sha256(checkpoint.read_bytes()).hexdigest(), "--output", str(output), "--execute", "--model-source", str(source), "--model-source-sha256", hashlib.sha256(source.read_bytes()).hexdigest(), "--model-config", str(config), "--model-config-sha256", hashlib.sha256(config.read_bytes()).hexdigest(), "--active-expert", "tool", "--input-token-id", "0", "--max-new-tokens", "2", "--device", "cpu", "--canonical-output", str(canonical), "--benchmark-id", "fixture", "--benchmark-version", "v1", "--benchmark-capability", "text", "--split-sha256", "a" * 64, "--protocol-sha256", "b" * 64, "--row-id", "fixture-1"], capture_output=True, text=True)
        assert completed.returncode != 0
        assert "refusing to overwrite existing canonical output" in completed.stderr
        assert canonical.read_text(encoding="utf-8") == "preserve"

def test_rejects_canonical_output_aliasing_the_receipt_path():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source, config, tokenizer, output = root / "model.py", root / "config.json", root / "tokenizer.json", root / "same.json"
        source.write_text("import torch\nclass RestartDecoderConfig:\n @classmethod\n def from_contract(cls, path): return cls()\nclass UnifiedDecoder(torch.nn.Module):\n def __init__(self, config, device='cpu', allow_production_allocation=False):\n  super().__init__(); self.weight=torch.nn.Parameter(torch.zeros(1,4,device=device))\n def forward(self, ids, active_expert=None):\n  return self.weight.expand(ids.shape[0],ids.shape[1],4)\n", encoding="utf-8")
        config.write_text("{}", encoding="utf-8")
        tokenizer.write_text(json.dumps({"version": "1.0", "truncation": None, "padding": None, "added_tokens": [], "normalizer": None, "pre_tokenizer": None, "post_processor": None, "decoder": None, "model": {"type": "WordLevel", "vocab": {"x": 0}, "unk_token": "x"}}), encoding="utf-8")
        checkpoint = write_v3(root)
        shared = root / "shared.pt"; payload = torch.load(shared, weights_only=True); payload["model"] = {"weight": torch.zeros(1, 4)}; torch.save(payload, shared)
        manifest = json.loads(checkpoint.read_text()); record = next(item for item in manifest["shards"] if item["path"] == "shared.pt"); record.update(bytes=shared.stat().st_size, sha256=hashlib.sha256(shared.read_bytes()).hexdigest()); manifest["shared_optimizer_shard_sha256"] = record["sha256"]; checkpoint.write_text(json.dumps(manifest), encoding="utf-8")
        completed = subprocess.run([sys.executable, str(SCRIPT), "--tokenizer", str(tokenizer), "--checkpoint-manifest", str(checkpoint), "--checkpoint-sha256", hashlib.sha256(checkpoint.read_bytes()).hexdigest(), "--output", str(output), "--execute", "--model-source", str(source), "--model-source-sha256", hashlib.sha256(source.read_bytes()).hexdigest(), "--model-config", str(config), "--model-config-sha256", hashlib.sha256(config.read_bytes()).hexdigest(), "--active-expert", "tool", "--input-token-id", "0", "--max-new-tokens", "2", "--device", "cpu", "--canonical-output", str(output), "--benchmark-id", "fixture", "--benchmark-version", "v1", "--benchmark-capability", "text", "--split-sha256", "a" * 64, "--protocol-sha256", "b" * 64, "--row-id", "fixture-1"], capture_output=True, text=True)
        assert completed.returncode != 0
        assert "canonical output must differ from output" in completed.stderr
