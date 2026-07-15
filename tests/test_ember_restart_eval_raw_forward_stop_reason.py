# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import torch


SCRIPT = Path(__file__).parents[1] / "scripts" / "ember_restart_eval_raw_forward.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("raw_forward_stop_reason", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_execute_reports_eos_for_an_immediate_stop_token(tmp_path, monkeypatch):
    source = tmp_path / "model.py"
    source.write_text("import torch\nclass RestartDecoderConfig:\n @classmethod\n def from_contract_payload(cls, payload): obj=cls(); obj.vocab_size=4; return obj\nclass UnifiedDecoder(torch.nn.Module):\n def __init__(self, config, device='cpu', allow_production_allocation=False):\n  super().__init__(); self.weight=torch.nn.Parameter(torch.zeros(1,4,device=device))\n def forward(self, ids, active_expert=None): return self.weight.expand(ids.shape[0],ids.shape[1],4)\n", encoding="utf-8")
    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")
    torch.save({"model": {"weight": torch.zeros(1, 4, dtype=torch.bfloat16)}}, tmp_path / "shared.pt")
    shared_sha256 = hashlib.sha256((tmp_path / "shared.pt").read_bytes()).hexdigest()
    monkeypatch.setattr(MODULE, "require_execution_authority", lambda arguments, identities: {"inference_implementation_sha256": "f" * 64})
    arguments = SimpleNamespace(model_source=source, model_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(), model_config=config, model_config_sha256=hashlib.sha256(config.read_bytes()).hexdigest(), checkpoint_manifest=tmp_path / "checkpoint-manifest.json", active_expert="shared", device="cpu", input_token_id=1, max_new_tokens=2, stop_token_id=0)

    checkpoint = {"active_expert_ids": ["shared"], "model_config": {"training": {"memory": {"parameter_dtype": "bfloat16", "parameter_bytes": 2}}}, "model_config_sha256": "a" * 64, "tokenizer_sha256": "b" * 64, "checkpoint_manifest_sha256": "0" * 64, "counter_sha256": "c" * 64, "trusted_verifier_registry_sha256": "d" * 64, "parameter_receipt_sha256": "e" * 64, "required_shards": {"shared.pt": shared_sha256}}
    result = MODULE.execute(arguments, checkpoint, model_source_bytes=source.read_bytes())

    assert result["generated_token_ids"] == [0]
    assert result["stop_reason"] == "eos"
