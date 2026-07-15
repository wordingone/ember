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
SPEC = importlib.util.spec_from_file_location("raw_forward_shared_execute", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_execute_shared_route_loads_only_shared_state(tmp_path, monkeypatch):
    source = tmp_path / "model.py"
    source.write_text("import torch\nclass RestartDecoderConfig:\n @classmethod\n def from_contract(cls, path): return cls()\nclass UnifiedDecoder(torch.nn.Module):\n def __init__(self, config, device='cpu', allow_production_allocation=False):\n  super().__init__(); self.weight=torch.nn.Parameter(torch.zeros(1,4,device=device))\n def forward(self, ids, active_expert=None): return self.weight.expand(ids.shape[0],ids.shape[1],4)\n", encoding="utf-8")
    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")
    torch.save({"model": {"weight": torch.zeros(1, 4)}}, tmp_path / "shared.pt")
    monkeypatch.setattr(MODULE, "require_execution_authority", lambda arguments: None)
    arguments = SimpleNamespace(model_source=source, model_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(), model_config=config, model_config_sha256=hashlib.sha256(config.read_bytes()).hexdigest(), checkpoint_manifest=tmp_path / "checkpoint-manifest.json", active_expert="shared", device="cpu", input_token_id=0, max_new_tokens=1, stop_token_id=2)

    result = MODULE.execute(arguments, {"active_expert_ids": ["shared"]})

    assert result["active_expert"] == "shared"
