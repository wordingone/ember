# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
import torch


ROOT = Path(__file__).resolve().parents[1]
WRITER_PATH = ROOT / "q2_capture_writer.py"
LOADER_PATH = ROOT / "q2_capture_loader.py"


def _load(path: Path, name: str):
    assert path.exists(), f"{path.name} is not implemented"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _authority(root: Path) -> tuple[Path, dict[str, Path]]:
    root.mkdir(parents=True)
    source_commit = "f3c92ba984711ee34e91c6bea90713e6c89b4b4d"
    dispatch = {
        "schema_version": "ember-lab-dispatch-preflight-v1",
        "result": "PREFLIGHT_PASSED",
        "job_id": "q2-writer-test",
        "source_commit": source_commit,
        "dispatch_manifest_sha256": "a" * 64,
        "ember_lab_identity": {"binary_sha256": "c" * 64, "source_sha256": "d" * 64},
    }
    dispatch_path = root / "dispatch-preflight.json"
    dispatch_path.write_bytes(_canonical(dispatch))
    keys = [
        "source_sha256",
        "config_sha256",
        "checkpoint_sha256",
        "optimizer_sha256",
        "momentum_sha256",
        "batch_sha256",
        "b3_receipt_sha256",
        "replay_sha256",
        "threshold_sha256",
        "verifier_sha256",
    ]
    files = {}
    for index, key in enumerate(keys):
        path = root / f"binding-{index}.bin"
        path.write_bytes(f"{key}:{index}".encode())
        files[key] = path
    return dispatch_path, files


def _terminal(root: Path) -> Path:
    receipt = {
        "schema": "ember-lab-operational-receipt-v1",
        "ember_lab_identity": {"binary_sha256": "c" * 64, "source_sha256": "d" * 64},
        "job_id": "q2-writer-test",
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
    path = root / f"{_sha(raw)}.json"
    path.write_bytes(raw)
    return path


def _inputs():
    pre = torch.tensor([[1.0, 2.0], [3.0, 4.0]], dtype=torch.float32)
    def loss_replay(target: torch.Tensor, non_target: dict[str, torch.Tensor]) -> float:
        return float(target.sum() + sum(value.sum() for value in non_target.values()))
    return {
        "target_name": "backbone.blocks.0.ff.gate_proj.weight",
        "pre": pre,
        "reset_post": pre - 0.1,
        "transplant_post": pre - 0.2,
        "gradient": torch.tensor([[0.1, 0.2], [0.3, 0.4]], dtype=torch.float32),
        "reset_momentum": torch.zeros_like(pre),
        "transplant_momentum": torch.ones_like(pre),
        "non_target_pre": {"backbone.blocks.0.norm.weight": torch.tensor([1.0, 2.0])},
        "non_target_reset": {"backbone.blocks.0.norm.weight": torch.tensor([1.0, 2.0])},
        "non_target_transplant": {"backbone.blocks.0.norm.weight": torch.tensor([1.0, 2.0])},
        "loss_replay": loss_replay,
        "learning_rate": 0.02,
        "optimizer_scale": 1.0,
    }


def test_write_capture_is_manifest_last_and_loader_admits_rederived_bytes(tmp_path: Path):
    writer = _load(WRITER_PATH, "q2_capture_writer")
    loader = _load(LOADER_PATH, "q2_capture_loader")
    custody = tmp_path / "custody"
    dispatch_path, binding_files = _authority(custody)

    manifest_path = writer.write_capture(
        custody_root=custody,
        run_id="q2-writer-test",
        dispatch_receipt_path=dispatch_path,
        binding_files=binding_files,
        **_inputs(),
    )

    assert manifest_path.name == "capture-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["manifest_sha256"] == _sha(_canonical({k: v for k, v in manifest.items() if k != "manifest_sha256"}))
    admitted = loader.load_capture(manifest_path, dispatch_path, _terminal(custody))
    assert admitted["event_authority"] == "EMBER_LAB_TERMINAL_EXIT_ZERO"
    assert admitted["artifact_hashes"]["pre"] == manifest["artifacts"]["pre"]["sha256"]
    assert set(admitted["non_target_state"]) == {"backbone.blocks.0.norm.weight"}
    assert torch.equal(
        admitted["non_target_state"]["backbone.blocks.0.norm.weight"],
        torch.tensor([1.0, 2.0]),
    )
    assert manifest["paired_losses"]["reset"] == pytest.approx(12.6)
    assert manifest["paired_losses"]["transplant"] == pytest.approx(12.2)
    assert manifest["paired_losses"]["replay_count_per_arm"] == 2
    assert manifest["paired_losses"]["deterministic"] is True


def test_write_capture_refuses_non_target_drift_before_any_capture_bytes(tmp_path: Path):
    writer = _load(WRITER_PATH, "q2_capture_writer")
    custody = tmp_path / "custody"
    dispatch_path, binding_files = _authority(custody)
    inputs = _inputs()
    inputs["non_target_reset"] = {"backbone.blocks.0.norm.weight": torch.tensor([1.0, 3.0])}

    with pytest.raises(writer.CaptureWriteRefusal, match="NON_TARGET_DRIFT_RESET"):
        writer.write_capture(
            custody_root=custody,
            run_id="q2-writer-test",
            dispatch_receipt_path=dispatch_path,
            binding_files=binding_files,
            **inputs,
        )

    assert not (custody / "capture-manifest.json").exists()
    assert not list(custody.glob("q2-writer-test-*.pt"))


def test_write_capture_refuses_momentum_laundering_and_run_reuse(tmp_path: Path):
    writer = _load(WRITER_PATH, "q2_capture_writer")
    custody = tmp_path / "custody"
    dispatch_path, binding_files = _authority(custody)
    inputs = _inputs()
    inputs["reset_momentum"] = torch.ones((2, 2), dtype=torch.float32)
    with pytest.raises(writer.CaptureWriteRefusal, match="RESET_MOMENTUM_NOT_ZERO"):
        writer.write_capture(
            custody_root=custody,
            run_id="q2-writer-test",
            dispatch_receipt_path=dispatch_path,
            binding_files=binding_files,
            **inputs,
        )

    inputs = _inputs()
    inputs["transplant_momentum"] = torch.zeros((2, 2), dtype=torch.float32)
    with pytest.raises(writer.CaptureWriteRefusal, match="TRANSPLANT_MOMENTUM_ZERO"):
        writer.write_capture(
            custody_root=custody,
            run_id="q2-writer-test",
            dispatch_receipt_path=dispatch_path,
            binding_files=binding_files,
            **inputs,
        )

    writer.write_capture(
        custody_root=custody,
        run_id="q2-writer-test",
        dispatch_receipt_path=dispatch_path,
        binding_files=binding_files,
        **_inputs(),
    )
    with pytest.raises(writer.CaptureWriteRefusal, match="CAPTURE_RUN_ALREADY_EXISTS"):
        writer.write_capture(
            custody_root=custody,
            run_id="q2-writer-test",
            dispatch_receipt_path=dispatch_path,
            binding_files=binding_files,
            **_inputs(),
        )


def test_write_capture_refuses_nondeterministic_or_mutating_loss_replay(tmp_path: Path):
    writer = _load(WRITER_PATH, "q2_capture_writer")
    custody = tmp_path / "custody"
    dispatch_path, binding_files = _authority(custody)
    calls = 0

    def nondeterministic(target: torch.Tensor, non_target: dict[str, torch.Tensor]) -> float:
        nonlocal calls
        calls += 1
        return float(target.sum()) + calls * 0.01

    inputs = _inputs()
    inputs["loss_replay"] = nondeterministic
    with pytest.raises(writer.CaptureWriteRefusal, match="PAIRED_LOSS_REPLAY_NONDETERMINISTIC"):
        writer.write_capture(
            custody_root=custody,
            run_id="q2-writer-test",
            dispatch_receipt_path=dispatch_path,
            binding_files=binding_files,
            **inputs,
        )
    assert not (custody / "capture-manifest.json").exists()

    def mutating(target: torch.Tensor, non_target: dict[str, torch.Tensor]) -> float:
        non_target["backbone.blocks.0.norm.weight"].add_(1)
        return float(target.sum())

    inputs = _inputs()
    inputs["loss_replay"] = mutating
    with pytest.raises(writer.CaptureWriteRefusal, match="PAIRED_LOSS_REPLAY_MUTATED_STATE"):
        writer.write_capture(
            custody_root=custody,
            run_id="q2-writer-test",
            dispatch_receipt_path=dispatch_path,
            binding_files=binding_files,
            **inputs,
        )
