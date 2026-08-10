# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import torch


ROOT = Path(__file__).resolve().parents[1]
ADJUDICATOR_PATH = ROOT / "q2_capture_adjudicator.py"
ADAPTER_PATH = ROOT / "q2_actual_event_adapter.py"
ADAPTER_FIXTURE_PATH = ROOT / "tests" / "test_actual_event_adapter.py"
PRESERVED_CONSUMER = ROOT / "q2_actual_update_successor.py"


def _load(path: Path, name: str):
    assert path.exists(), f"{path.name} is not implemented"
    sys.path.insert(0, str(path.parent))
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(path.parent))


class TinyModel(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.gate = torch.nn.Linear(2, 2, bias=False)
        self.norm = torch.nn.LayerNorm(2)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _terminal(root: Path) -> Path:
    import hashlib

    receipt = {
        "schema": "ember-lab-operational-receipt-v1",
        "ember_lab_identity": {"binary_sha256": "c" * 64, "source_sha256": "d" * 64},
        "job_id": "q2-adjudicator-test",
        "identity_sha256": "a" * 64,
        "resource_lease": "gpu:0",
        "state": "exited",
        "pid": 1234,
        "executable_identity": "python-test",
        "restart_policy": "never",
        "exit_code": 0,
        "logs": {"stdout": {"sha256": "e" * 64}, "stderr": {"sha256": "f" * 64}},
        "events": [],
        "outage_events": [],
        "scientific_capability_evidence": False,
    }
    raw = json.dumps(receipt, sort_keys=True, indent=2).encode()
    path = root / f"{hashlib.sha256(raw).hexdigest()}.json"
    path.write_bytes(raw)
    return path


def test_adjudicator_binds_terminal_event_and_exact_replay_bytes(tmp_path: Path):
    adapter = _load(ADAPTER_PATH, "q2_adapter_adjudicator_test")
    adjudicator = _load(ADJUDICATOR_PATH, "q2_capture_adjudicator")
    verifier = _load(PRESERVED_CONSUMER, "q2_preserved_consumer")
    fixture = _load(ADAPTER_FIXTURE_PATH, "q2_adapter_fixture")
    custody = tmp_path / "custody"
    model = fixture.TinyModel()
    lineage = fixture._lineage(custody, model, "q2-adjudicator-test")
    dispatch_path, bindings = fixture._authority(
        custody,
        lineage["b2_receipt_path"],
        lineage["b1m_receipt_path"],
        lineage["batch_manifest_path"],
        "q2-adjudicator-test",
    )
    bindings["replay_sha256"] = custody / "replay.py"
    bindings["threshold_sha256"] = custody / "threshold.json"
    bindings["verifier_sha256"] = custody / "verifier.py"
    bindings["verifier_sha256"].write_bytes(PRESERVED_CONSUMER.read_bytes())
    bindings["threshold_sha256"].write_bytes(
        _canonical(verifier.build_threshold_artifact(mn=8))
    )
    bindings["replay_sha256"].write_text(
        "def loss_from_state(state):\n"
        "    return float(sum((value.float() ** 2).sum() for value in state.values()))\n",
        encoding="utf-8",
    )
    replay = _load(bindings["replay_sha256"], "q2_bound_replay")

    target_name = "backbone_model.layers.0.mlp.gate_proj.weight"
    gradient = torch.load(
        lineage["persisted_gradient_path"], map_location="cpu", weights_only=True
    )
    manifest_path = adapter.capture_actual_event(
        custody_root=custody,
        run_id="q2-adjudicator-test",
        dispatch_receipt_path=dispatch_path,
        binding_files=bindings,
        model=model,
        target_name=target_name,
        reset_momentum=fixture._arm_momenta(lineage, gradient)[0],
        transplant_momentum=fixture._arm_momenta(lineage, gradient)[1],
        loss_replay=lambda target, non_target: replay.loss_from_state(
            {target_name: target, **non_target}
        ),
        learning_rate=0.02,
        optimizer_scale=1.0,
        **lineage,
    )

    receipt = adjudicator.adjudicate_capture(
        manifest_path=manifest_path,
        dispatch_receipt_path=dispatch_path,
        terminal_receipt_path=_terminal(custody),
    )

    assert receipt["scope"] == "TARGET_TENSOR_COUNTERFACTUAL"
    assert receipt["event_custody"]["authority"] == "EMBER_LAB_TERMINAL_EXIT_ZERO"
    assert receipt["event_custody"]["terminal_receipt_sha256"]
    assert receipt["credits"]["whole_step"] is False
    assert receipt["credits"]["material_loss_bridge"] is False
    assert verifier.artifact_sha256(receipt) == receipt["receipt_sha256"]
