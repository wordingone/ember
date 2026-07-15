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
SPEC = importlib.util.spec_from_file_location("raw_forward_expert_execute", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_execute_specialist_route_loads_only_shared_and_selected_expert(tmp_path, monkeypatch):
    source = tmp_path / "model.py"
    source.write_text(
        "import torch\n"
        "class RestartDecoderConfig:\n"
        " @classmethod\n"
        " def from_contract_payload(cls, payload): obj=cls(); obj.vocab_size=4; return obj\n"
        "class Block(torch.nn.Module):\n"
        " def __init__(self, device):\n"
        "  super().__init__(); self.experts=torch.nn.ModuleDict({'tool':torch.nn.Linear(1,4,bias=False,device=device)})\n"
        "class UnifiedDecoder(torch.nn.Module):\n"
        " def __init__(self, config, device='cpu', allow_production_allocation=False):\n"
        "  super().__init__(); self.weight=torch.nn.Parameter(torch.zeros(1,device=device)); self.layers=torch.nn.ModuleList([Block(device)])\n"
        " def forward(self, ids, active_expert=None):\n"
        "  return self.layers[0].experts[active_expert](self.weight.expand(ids.shape[0],ids.shape[1],1))\n",
        encoding="utf-8",
    )
    shared_path, expert_path = tmp_path / "shared.pt", tmp_path / "expert-tool.pt"
    torch.save({"model": {"weight": torch.zeros(1)}}, shared_path)
    torch.save({"expert": "tool", "model": {"layers.0.experts.tool.weight": torch.zeros(4, 1)}}, expert_path)
    shared_sha = hashlib.sha256(shared_path.read_bytes()).hexdigest()
    expert_sha = hashlib.sha256(expert_path.read_bytes()).hexdigest()
    loaded = []
    original = MODULE.hash_and_load_torch

    def recorded(torch_module, path, expected_sha256, *, device):
        loaded.append(path.name)
        return original(torch_module, path, expected_sha256, device=device)

    monkeypatch.setattr(MODULE, "hash_and_load_torch", recorded)
    monkeypatch.setattr(MODULE, "require_execution_authority", lambda arguments, identities: {"inference_implementation_sha256": "f" * 64})
    arguments = SimpleNamespace(
        model_source=source,
        model_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        checkpoint_manifest=tmp_path / "checkpoint-manifest.json",
        active_expert="tool",
        device="cpu",
        input_token_id=1,
        max_new_tokens=1,
        stop_token_id=3,
    )
    checkpoint = {
        "active_expert_ids": ["tool"],
        "model_config": {},
        "model_config_sha256": "a" * 64,
        "tokenizer_sha256": "b" * 64,
        "checkpoint_manifest_sha256": "0" * 64,
        "counter_sha256": "c" * 64,
        "trusted_verifier_registry_sha256": "d" * 64,
        "parameter_receipt_sha256": "e" * 64,
        "required_shards": {"shared.pt": shared_sha, "expert-tool.pt": expert_sha},
    }

    result = MODULE.execute(arguments, checkpoint, model_source_bytes=source.read_bytes())

    assert result["active_expert"] == "tool"
    assert loaded == ["shared.pt", "expert-tool.pt"]
