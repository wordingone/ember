# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
import torch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "q2_capture_loader.py"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _tensor_sha(name: str, tensor: torch.Tensor) -> str:
    identity = _canonical({
        "name": name,
        "dtype": str(tensor.dtype).removeprefix("torch."),
        "shape": list(tensor.shape),
    })
    raw = tensor.contiguous().reshape(-1).view(torch.uint8).numpy().tobytes()
    return _sha(identity + b"\0" + raw)


def _load_module():
    assert MODULE_PATH.exists(), "q2_capture_loader.py is not implemented"
    spec = importlib.util.spec_from_file_location("q2_capture_loader", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_fixture(root: Path) -> tuple[Path, Path, Path]:
    root.mkdir(parents=True)
    tensor_names = [
        "pre.pt",
        "reset-post.pt",
        "transplant-post.pt",
        "gradient.pt",
        "reset-momentum.pt",
        "transplant-momentum.pt",
    ]
    binding_names = [
        "source.py",
        "config.json",
        "checkpoint.manifest.json",
        "optimizer.json",
        "momentum.json",
        "batch.manifest.json",
        "replay.json",
        "threshold.json",
        "verifier.py",
    ]
    payloads: dict[str, bytes] = {}
    tensors = {
        "pre.pt": torch.tensor([[1.0, 2.0], [3.0, 4.0]], dtype=torch.float32),
        "reset-post.pt": torch.tensor([[0.9, 1.9], [2.9, 3.9]], dtype=torch.float32),
        "transplant-post.pt": torch.tensor([[0.8, 1.8], [2.8, 3.8]], dtype=torch.float32),
        "gradient.pt": torch.tensor([[0.1, 0.2], [0.3, 0.4]], dtype=torch.float32),
        "reset-momentum.pt": torch.zeros((2, 2), dtype=torch.float32),
        "transplant-momentum.pt": torch.ones((2, 2), dtype=torch.float32),
    }
    for name, tensor in tensors.items():
        torch.save(tensor, root / name)
        payloads[name] = (root / name).read_bytes()
    for index, name in enumerate(binding_names, start=1):
        payloads[name] = f"issue675:{index}:{name}".encode()
        (root / name).write_bytes(payloads[name])

    non_target_tensor = torch.tensor([1.0, 2.0], dtype=torch.float32)
    non_target_state = {"backbone.blocks.0.norm.weight": non_target_tensor}
    non_target_state_path = root / "non-target-state.pt"
    torch.save(non_target_state, non_target_state_path)
    non_target_state_bytes = non_target_state_path.read_bytes()
    non_target_bytes = _canonical({
        "schema": "q2-non-target-byte-manifest-v1",
        "entries": [{
            "name": "backbone.blocks.0.norm.weight",
            "dtype": "float32",
            "shape": [2],
            "sha256": _tensor_sha("backbone.blocks.0.norm.weight", non_target_tensor),
        }],
    })
    (root / "non-target-manifest.json").write_bytes(non_target_bytes)

    source_commit = "f3c92ba984711ee34e91c6bea90713e6c89b4b4d"
    dispatch_manifest_sha = "a" * 64
    dispatch = {
        "schema_version": "ember-lab-dispatch-preflight-v1",
        "result": "PREFLIGHT_PASSED",
        "job_id": "q2-actual-update-test",
        "source_commit": source_commit,
        "dispatch_manifest_sha256": dispatch_manifest_sha,
        "ember_lab_identity": {"binary_sha256": "c" * 64, "source_sha256": "d" * 64},
    }
    dispatch_path = root / "dispatch-preflight.json"
    dispatch_path.write_bytes(_canonical(dispatch))
    terminal = {
        "schema": "ember-lab-operational-receipt-v1",
        "ember_lab_identity": dispatch["ember_lab_identity"],
        "job_id": "q2-actual-update-test",
        "identity_sha256": dispatch_manifest_sha,
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
    terminal_bytes = json.dumps(terminal, sort_keys=True, indent=2).encode()
    terminal_path = root / f"{_sha(terminal_bytes)}.json"
    terminal_path.write_bytes(terminal_bytes)

    tensor_keys = [
        "pre",
        "reset_post",
        "transplant_post",
        "gradient",
        "reset_momentum",
        "transplant_momentum",
    ]
    artifacts = {}
    for key, name in zip(tensor_keys, tensor_names):
        artifacts[key] = {
            "logical_name": name,
            "sha256": _sha(payloads[name]),
            "bytes": len(payloads[name]),
            "dtype": "float32",
            "shape": [2, 2],
        }

    binding_keys = [
        "source_sha256",
        "config_sha256",
        "checkpoint_sha256",
        "optimizer_sha256",
        "momentum_sha256",
        "batch_sha256",
        "replay_sha256",
        "threshold_sha256",
        "verifier_sha256",
    ]
    bindings = {}
    binding_files = {}
    for key, name in zip(binding_keys, binding_names):
        bindings[key] = _sha(payloads[name])
        binding_files[key] = name

    manifest = {
        "schema": "q2-actual-update-capture-v1",
        "issue": 675,
        "scope": "TARGET_TENSOR_COUNTERFACTUAL",
        "run_id": "q2-actual-update-test",
        "event_captured_at": "2026-08-10T07:33:42Z",
        "source_commit": source_commit,
        "dispatch": {
            "job_id": "q2-actual-update-test",
            "manifest_sha256": dispatch_manifest_sha,
            "preflight_receipt_sha256": _sha(dispatch_path.read_bytes()),
        },
        "bindings": bindings,
        "binding_files": binding_files,
        "target": {"name": "backbone.blocks.0.ff.gate_proj.weight", "dtype": "float32", "shape": [2, 2], "mn": 4},
        "artifacts": artifacts,
        "non_target_manifest": {
            "logical_name": "non-target-manifest.json",
            "bytes": len(non_target_bytes),
            "entry_count": 1,
            "sha256": _sha(non_target_bytes),
            "state_logical_name": "non-target-state.pt",
            "state_bytes": len(non_target_state_bytes),
            "state_sha256": _sha(non_target_state_bytes),
            "byte_identical_reset": True,
            "byte_identical_transplant": True,
        },
        "optimizer": {
            "name": "Muon",
            "learning_rate": 0.02,
            "scale": 1.0,
            "reset_momentum_exact_zero": True,
            "transplant_momentum_nonzero": True,
        },
        "paired_losses": {
            "reset": 1.0,
            "transplant": 0.9,
            "finite": True,
            "same_frozen_batch": True,
            "non_target_state_reused": True,
            "replay_count_per_arm": 2,
            "deterministic": True,
            "replay_sha256": bindings["replay_sha256"],
        },
        "credits": {
            "whole_step": False,
            "null_confirmed": False,
            "material_loss_bridge": False,
            "training": False,
            "checkpoint": False,
            "capability": False,
            "sufficient_pretraining": False,
        },
        "no_new_parallel_authority": True,
        "verdict": "CAPTURED_NOT_ADJUDICATED",
    }
    manifest["manifest_sha256"] = _sha(_canonical(manifest))
    manifest_path = root / "capture-manifest.json"
    manifest_path.write_bytes(_canonical(manifest))
    return manifest_path, dispatch_path, terminal_path


def test_load_capture_rederives_every_file_and_returns_path_free_authority(tmp_path: Path):
    loader = _load_module()
    manifest_path, dispatch_path, terminal_path = _write_fixture(tmp_path / "custody")

    loaded = loader.load_capture(manifest_path, dispatch_path, terminal_path)

    assert loaded["event_authority"] == "EMBER_LAB_TERMINAL_EXIT_ZERO"
    assert loaded["capture_manifest_sha256"] == json.loads(manifest_path.read_text())["manifest_sha256"]
    encoded = json.dumps(
        {key: value for key, value in loaded.items() if key not in {
            "non_target_state", "pre_state", "reset_state", "transplant_state", "gradients"
        }},
        sort_keys=True,
    )
    assert str(tmp_path) not in encoded
    assert ":\\" not in encoded


def test_load_capture_refuses_tensor_tamper_before_return(tmp_path: Path):
    loader = _load_module()
    manifest_path, dispatch_path, terminal_path = _write_fixture(tmp_path / "custody")
    (manifest_path.parent / "reset-post.pt").write_bytes(b"tampered")

    with pytest.raises(loader.CaptureRefusal, match="CAPTURE_ARTIFACT_HASH_MISMATCH"):
        loader.load_capture(manifest_path, dispatch_path, terminal_path)


def test_load_capture_refuses_nonterminal_or_failed_operational_receipt(tmp_path: Path):
    loader = _load_module()
    manifest_path, dispatch_path, terminal_path = _write_fixture(tmp_path / "custody")
    terminal = json.loads(terminal_path.read_text())
    terminal["state"] = "failed"
    terminal["exit_code"] = 1
    terminal_path.unlink()
    raw = json.dumps(terminal, sort_keys=True, indent=2).encode()
    failed_path = manifest_path.parent / f"{_sha(raw)}.json"
    failed_path.write_bytes(raw)

    with pytest.raises(loader.CaptureRefusal, match="TERMINAL_RECEIPT_NOT_SUCCESSFUL"):
        loader.load_capture(manifest_path, dispatch_path, failed_path)


def test_load_capture_refuses_non_target_state_tamper_before_return(tmp_path: Path):
    loader = _load_module()
    manifest_path, dispatch_path, terminal_path = _write_fixture(tmp_path / "custody")
    state_path = manifest_path.parent / "non-target-state.pt"
    state_path.write_bytes(state_path.read_bytes() + b"tampered")

    with pytest.raises(loader.CaptureRefusal, match="NON_TARGET_STATE_HASH_MISMATCH"):
        loader.load_capture(manifest_path, dispatch_path, terminal_path)


def test_load_capture_refuses_binding_tamper_and_forged_dispatch(tmp_path: Path):
    loader = _load_module()
    manifest_path, dispatch_path, terminal_path = _write_fixture(tmp_path / "custody")
    (manifest_path.parent / "config.json").write_bytes(b"tampered-config")
    with pytest.raises(loader.CaptureRefusal, match="CAPTURE_BINDING_HASH_MISMATCH"):
        loader.load_capture(manifest_path, dispatch_path, terminal_path)

    manifest_path, dispatch_path, terminal_path = _write_fixture(tmp_path / "second")
    dispatch = json.loads(dispatch_path.read_text())
    dispatch["result"] = "REFUSED_HOST_COMMIT_CAP"
    dispatch_path.write_bytes(_canonical(dispatch))
    manifest = json.loads(manifest_path.read_text())
    manifest["dispatch"]["preflight_receipt_sha256"] = _sha(dispatch_path.read_bytes())
    manifest.pop("manifest_sha256")
    manifest["manifest_sha256"] = _sha(_canonical(manifest))
    manifest_path.write_bytes(_canonical(manifest))
    with pytest.raises(loader.CaptureRefusal, match="DISPATCH_PREFLIGHT_NOT_GREEN"):
        loader.load_capture(manifest_path, dispatch_path, terminal_path)


def test_load_capture_refuses_path_escape_and_manifest_tamper(tmp_path: Path):
    loader = _load_module()
    manifest_path, dispatch_path, terminal_path = _write_fixture(tmp_path / "custody")
    manifest = json.loads(manifest_path.read_text())
    manifest["artifacts"]["pre"]["logical_name"] = "../pre.pt"
    manifest.pop("manifest_sha256")
    manifest["manifest_sha256"] = _sha(_canonical(manifest))
    manifest_path.write_bytes(_canonical(manifest))
    with pytest.raises(loader.CaptureRefusal, match="CAPTURE_LOGICAL_NAME_INVALID"):
        loader.load_capture(manifest_path, dispatch_path, terminal_path)

    manifest_path, dispatch_path, terminal_path = _write_fixture(tmp_path / "second")
    manifest = json.loads(manifest_path.read_text())
    manifest["paired_losses"]["transplant"] = 0.8
    manifest_path.write_bytes(_canonical(manifest))
    with pytest.raises(loader.CaptureRefusal, match="CAPTURE_MANIFEST_HASH_MISMATCH"):
        loader.load_capture(manifest_path, dispatch_path, terminal_path)


def test_load_capture_refuses_unknown_false_credit_and_duplicate_binding(tmp_path: Path):
    loader = _load_module()
    manifest_path, dispatch_path, terminal_path = _write_fixture(tmp_path / "custody")
    manifest = json.loads(manifest_path.read_text())
    manifest["credits"]["future_scientific_credit"] = False
    manifest.pop("manifest_sha256")
    manifest["manifest_sha256"] = _sha(_canonical(manifest))
    manifest_path.write_bytes(_canonical(manifest))
    with pytest.raises(loader.CaptureRefusal, match="CAPTURE_FALSE_CREDIT_SCHEMA_INVALID"):
        loader.load_capture(manifest_path, dispatch_path, terminal_path)

    manifest_path, dispatch_path, terminal_path = _write_fixture(tmp_path / "second")
    manifest = json.loads(manifest_path.read_text())
    manifest["binding_files"]["config_sha256"] = manifest["binding_files"]["source_sha256"]
    manifest["bindings"]["config_sha256"] = manifest["bindings"]["source_sha256"]
    manifest.pop("manifest_sha256")
    manifest["manifest_sha256"] = _sha(_canonical(manifest))
    manifest_path.write_bytes(_canonical(manifest))
    with pytest.raises(loader.CaptureRefusal, match="CAPTURE_BINDING_DUPLICATE"):
        loader.load_capture(manifest_path, dispatch_path, terminal_path)


def test_load_capture_refuses_preflight_receipt_outside_custody(tmp_path: Path):
    loader = _load_module()
    manifest_path, dispatch_path, terminal_path = _write_fixture(tmp_path / "custody")
    foreign = tmp_path / "foreign-preflight.json"
    foreign.write_bytes(dispatch_path.read_bytes())

    with pytest.raises(loader.CaptureRefusal, match="DISPATCH_PREFLIGHT_OUTSIDE_CUSTODY"):
        loader.load_capture(manifest_path, foreign, terminal_path)


def test_load_capture_reopens_and_refuses_non_target_manifest_tamper(tmp_path: Path):
    loader = _load_module()
    manifest_path, dispatch_path, terminal_path = _write_fixture(tmp_path / "custody")
    (manifest_path.parent / "non-target-manifest.json").write_bytes(b"tampered")

    with pytest.raises(loader.CaptureRefusal, match="NON_TARGET_MANIFEST_HASH_MISMATCH"):
        loader.load_capture(manifest_path, dispatch_path, terminal_path)


def test_load_capture_reopens_tensor_and_refuses_forged_dtype_shape(tmp_path: Path):
    loader = _load_module()
    manifest_path, dispatch_path, terminal_path = _write_fixture(tmp_path / "custody")
    manifest = json.loads(manifest_path.read_text())
    manifest["artifacts"]["pre"]["shape"] = [4]
    manifest.pop("manifest_sha256")
    manifest["manifest_sha256"] = _sha(_canonical(manifest))
    manifest_path.write_bytes(_canonical(manifest))

    with pytest.raises(loader.CaptureRefusal, match="CAPTURE_ARTIFACT_TENSOR_IDENTITY_MISMATCH"):
        loader.load_capture(manifest_path, dispatch_path, terminal_path)
