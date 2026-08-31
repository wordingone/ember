# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import importlib.util
import json
import sys
from argparse import Namespace
from pathlib import Path

import pytest
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import q2_governed_event_producer as producer


class Tiny(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.target = torch.nn.Parameter(torch.ones((4, 2), dtype=torch.float32))
        self.other = torch.nn.Parameter(torch.ones(1, dtype=torch.float32))


def _fixture(tmp_path):
    root = tmp_path / "custody"; root.mkdir()
    run = "q2-producer-test"; source = "a" * 40; batch = "b" * 64
    (root / "dispatch-preflight.json").write_text(json.dumps({
        "schema_version": "ember-lab-dispatch-preflight-v1", "result": "PREFLIGHT_PASSED",
        "job_id": run, "source_commit": source, "dispatch_manifest_sha256": "c" * 64,
    }), encoding="utf-8")
    model = Tiny()
    files = {}
    for name in ("seed_model", "seed_optimizer", "grown_model", "seed_manifest", "b2_receipt", "grow_operator"):
        path = root / f"{name}.bin"; path.write_bytes(name.encode()); files[name] = path
    files["config"] = root / "config.json"
    files["config"].write_text(json.dumps({
        "model": {"layers": 1},
        "optimizer": {"lr_muon": 0.02, "lr_adamw": 0.0003},
    }), encoding="utf-8")
    files["b1m_receipt"] = root / "b1m.json"
    files["b1m_receipt"].write_text(json.dumps({"batch": {"overall_sha256": batch}}), encoding="utf-8")
    files["pre_momentum"] = root / "pre-momentum.pt"; torch.save(torch.ones((2, 2)), files["pre_momentum"])
    torch.save(model.state_dict(), files["grown_model"])
    cp = root / "checkpoint.json"; cp.write_text("checkpoint", encoding="utf-8")
    bp = root / "batch.json"; bp.write_text("batch", encoding="utf-8")
    threshold = root / "threshold.json"; threshold.write_text("threshold", encoding="utf-8")
    verifier = root / "verifier.py"; verifier.write_text("verifier", encoding="utf-8")
    args = Namespace(run_id=run, custody_root=str(root), checkpoint_manifest=str(cp), batch_manifest=str(bp), threshold=str(threshold), verifier=str(verifier), config=str(files["config"]), mode="governed-vertical")
    admitted = {"files": files, "microsteps": [{"x": torch.ones((1, 2), dtype=torch.int64), "y0": torch.ones((1, 2), dtype=torch.int64), "y_mtp": []}], "batch_sha256": batch, "lineage_run_id": "historical", "target_name": "target", "intermediate_size": 8}
    return root, run, batch, model, args, admitted


def test_producer_mints_future_b3_then_calls_capture(tmp_path, monkeypatch):
    root, run, batch, model, args, admitted = _fixture(tmp_path)
    monkeypatch.setattr(producer, "admit_event_inputs", lambda **kwargs: admitted)
    monkeypatch.setattr(producer, "build_rung2_model", lambda *a, **k: (model, 8, 2, 0))
    gradient = torch.full((4, 2), 0.25, dtype=torch.float32)
    monkeypatch.setattr(producer, "compute_frozen_batch_gradient", lambda **kwargs: (gradient, 1.0, "cut_ce_chunked"))
    captured = {}
    def fake_capture(**kwargs):
        captured.update(kwargs)
        receipt = json.loads(Path(kwargs["b3_receipt_path"]).read_text())
        assert receipt["gradient_lineage"]["batch_sha256"] == batch
        assert hashlib.sha256(Path(kwargs["persisted_gradient_path"]).read_bytes()).hexdigest() == receipt["cache_sha256"]["grad_post_gate"]
        path = root / "capture-manifest.json"; path.write_text("captured", encoding="utf-8"); return path
    monkeypatch.setattr(producer, "capture_actual_event", fake_capture)
    result = producer.run_governed_vertical(args)
    assert result.name == "capture-manifest.json"
    assert captured["batch_manifest_path"] == Path(args.batch_manifest)
    assert captured["lineage_run_id"] == "historical"
    assert captured["learning_rate"] == 0.02
    assert set(captured["binding_files"]) == {"source_sha256", "config_sha256", "checkpoint_sha256", "optimizer_sha256", "momentum_sha256", "b3_receipt_sha256", "batch_sha256", "replay_sha256", "threshold_sha256", "verifier_sha256"}


def test_producer_refuses_b1m_batch_mismatch_before_capture(tmp_path, monkeypatch):
    _root, _run, _batch, model, args, admitted = _fixture(tmp_path)
    admitted["batch_sha256"] = "d" * 64
    monkeypatch.setattr(producer, "admit_event_inputs", lambda **kwargs: admitted)
    monkeypatch.setattr(producer, "build_rung2_model", lambda *a, **k: (model, 8, 2, 0))
    monkeypatch.setattr(producer, "compute_frozen_batch_gradient", lambda **kwargs: (torch.ones((4, 2)), 1.0, "cut_ce_chunked"))
    with pytest.raises(producer.GovernedEventRefusal, match="EVENT_B1M_BATCH_BINDING_MISMATCH"):
        producer.run_governed_vertical(args)


@pytest.mark.parametrize("optimizer", [
    {"lr": 0.02},
    {"lr_muon": 0.0},
    {"lr_muon": float("nan")},
    {"lr_muon": True},
])
def test_producer_refuses_invalid_canonical_muon_rate_before_outputs(tmp_path, monkeypatch, optimizer):
    root, run, _batch, model, args, admitted = _fixture(tmp_path)
    Path(args.config).write_text(json.dumps({"model": {"layers": 1}, "optimizer": optimizer}), encoding="utf-8")
    monkeypatch.setattr(producer, "admit_event_inputs", lambda **kwargs: admitted)
    monkeypatch.setattr(producer, "build_rung2_model", lambda *a, **k: (model, 8, 2, 0))
    monkeypatch.setattr(producer, "compute_frozen_batch_gradient", lambda **kwargs: (torch.ones((4, 2)), 1.0, "cut_ce_chunked"))
    with pytest.raises(producer.GovernedEventRefusal, match="EVENT_MUON_LEARNING_RATE_INVALID"):
        producer.run_governed_vertical(args)
    assert not (root / f"{run}-grad-post-gate.pt").exists()
    assert not (root / f"{run}-b3.json").exists()


def test_b3_outputs_are_atomic_and_nonoverwriting(tmp_path):
    root = tmp_path / "custody"; root.mkdir(); gradient = torch.ones((2, 2), dtype=torch.float32)
    gradient_path, receipt_path = producer._mint_b3(root=root, run_id="r", batch_sha256="a" * 64, target_name="target", gradient=gradient)
    assert gradient_path.exists() and receipt_path.exists()
    with pytest.raises(producer.GovernedEventRefusal, match="EVENT_OUTPUT_ALREADY_EXISTS"):
        producer._mint_b3(root=root, run_id="r", batch_sha256="a" * 64, target_name="target", gradient=gradient)
