# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import torch


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "q2_actual_event_adapter.py"
LOADER_PATH = ROOT / "q2_capture_loader.py"
MUON_PATH = ROOT / "q2_muon_primitives.py"
LINEAGE_PATH = ROOT / "q2_model_lineage.py"


def _load():
    assert ADAPTER_PATH.exists(), "q2_actual_event_adapter.py is not implemented"
    sys.path.insert(0, str(ROOT))
    try:
        spec = importlib.util.spec_from_file_location("q2_actual_event_adapter", ADAPTER_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(ROOT))


def _load_loader():
    spec = importlib.util.spec_from_file_location("q2_capture_loader_adapter_test", LOADER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_lineage():
    spec = importlib.util.spec_from_file_location("q2_model_lineage_fixture", LINEAGE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _authority(
    root: Path,
    b2_receipt: Path,
    runtime_config: Path,
    b1m_receipt: Path,
    b3_receipt: Path,
    batch_manifest: Path,
    job_id: str = "q2-adapter-test",
) -> tuple[Path, dict[str, Path]]:
    root.mkdir(parents=True, exist_ok=True)
    receipt = {
        "schema_version": "ember-lab-dispatch-preflight-v1",
        "result": "PREFLIGHT_PASSED",
        "job_id": job_id,
        "source_commit": "a" * 40,
        "dispatch_manifest_sha256": "a" * 64,
        "ember_lab_identity": {"binary_sha256": "c" * 64, "source_sha256": "d" * 64},
    }
    receipt_path = root / "dispatch-preflight.json"
    receipt_path.write_bytes(_canonical(receipt))
    keys = (
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
    )
    files: dict[str, Path] = {}
    for index, key in enumerate(keys):
        path = root / f"binding-{index}.bin"
        if key == "source_sha256":
            path.write_bytes(ADAPTER_PATH.read_bytes())
        elif key == "optimizer_sha256":
            path.write_bytes(MUON_PATH.read_bytes())
        elif key == "checkpoint_sha256":
            path.write_bytes(b2_receipt.read_bytes())
        elif key == "config_sha256":
            path.write_bytes(runtime_config.read_bytes())
        elif key == "momentum_sha256":
            path.write_bytes(b1m_receipt.read_bytes())
        elif key == "batch_sha256":
            path.write_bytes(batch_manifest.read_bytes())
        elif key == "b3_receipt_sha256":
            path.write_bytes(b3_receipt.read_bytes())
        else:
            path.write_bytes(f"{key}:{index}".encode())
        files[key] = path
    return receipt_path, files


def _terminal(root: Path) -> Path:
    receipt = {
        "schema": "ember-lab-operational-receipt-v1",
        "ember_lab_identity": {"binary_sha256": "c" * 64, "source_sha256": "d" * 64},
        "job_id": "q2-adapter-test",
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


class TinyMLP(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.gate_proj = torch.nn.Linear(2, 4, bias=False)
        self.up_proj = torch.nn.Linear(2, 4, bias=False)
        self.down_proj = torch.nn.Linear(4, 2, bias=False)


class TinyLayer(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.mlp = TinyMLP()


class TinyBackbone(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.layers = torch.nn.ModuleList([TinyLayer()])
        self.norm = torch.nn.LayerNorm(2)


class TinyModel(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.backbone_model = TinyBackbone()
        self.register_buffer("aux_counter", torch.tensor([7.0], dtype=torch.bfloat16))
        self.to(dtype=torch.bfloat16)


def _lineage(root: Path, model: TinyModel, run_id: str) -> dict[str, object]:
    root.mkdir(parents=True, exist_ok=True)
    lineage_module = _load_lineage()
    lineage_run_id = lineage_module.CANONICAL_B2_LINEAGE_RUN_ID
    prefix = "backbone_model.layers.0.mlp."
    seed = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
    seed[prefix + "gate_proj.weight"] = torch.tensor(
        [[1.0, 2.0], [3.0, 4.0]], dtype=torch.bfloat16
    )
    seed[prefix + "up_proj.weight"] = torch.tensor(
        [[0.5, 1.5], [2.5, 3.5]], dtype=torch.bfloat16
    )
    seed[prefix + "down_proj.weight"] = torch.tensor(
        [[1.0, 2.0], [4.0, 8.0]], dtype=torch.bfloat16
    )
    seed_model = root / "seed-model.pt"
    torch.save(seed, seed_model)
    seed_manifest = root / "seed-manifest.json"
    pre_momentum = torch.tensor(
        [[1.0, -0.5], [0.25, 2.0]], dtype=torch.float32
    )
    muon_names = [
        name
        for name, tensor in seed.items()
        if tensor.dim() == 2 and "embed" not in name.lower() and "head" not in name.lower()
    ]
    target_name = prefix + "gate_proj.weight"
    muon_id = muon_names.index(target_name)
    seed_optimizer = root / "seed-optimizer.pt"
    torch.save(
        {"muon": {"state": {muon_id: {"momentum_buffer": pre_momentum.clone()}}}},
        seed_optimizer,
    )
    seed_manifest.write_text(
        json.dumps(
            {
                "files": {
                    "model.pt": hashlib.sha256(seed_model.read_bytes()).hexdigest(),
                    "optimizer.pt": hashlib.sha256(seed_optimizer.read_bytes()).hexdigest(),
                }
            }
        ),
        encoding="utf-8",
    )
    persisted_pre_momentum = root / f"{lineage_run_id}-pre-momentum.pt"
    torch.save(pre_momentum, persisted_pre_momentum)
    b1m_receipt = root / "b1m.json"
    b1m_receipt.write_text(
        json.dumps(
            {
                "ticket": "CBASE-GROW-RUNG2-EVENT-B1M",
                "run_id": lineage_run_id,
                "u_pre": {
                    "gate_key": target_name,
                    "momentum_buffer_source": "B1 snapshot pre-grow momentum_buffer (parent-carried)",
                },
                "cache_paths": {"pre_momentum": persisted_pre_momentum.name},
                "verdict": "B1M_CAPTURED",
            }
        ),
        encoding="utf-8",
    )
    grow_operator = root / "q2_model_lineage.py"
    grow_operator.write_bytes(LINEAGE_PATH.read_bytes())
    b2_receipt = root / "b2.json"
    b2_receipt.write_text(
        json.dumps(
            {
                "ticket": "CBASE-GROW-RUNG2-EVENT-B2",
                "run_id": lineage_run_id,
                "eps": {"eps_sigma": lineage_module.CANONICAL_B2_EPS_SIGMA, "eps_seed": lineage_module.CANONICAL_B2_EPS_SEED, "banned_zero_assertion_passed": True},
                "operator_sha256": lineage_module.CANONICAL_B2_OPERATOR_SHA256,
                "cache": {"cache_path": "grown-model.pt", "distinct_from_eps0_cache": True},
                "realized_proof": {"eta_band_pass": True, "twin_cosine_pass": True},
                "verdict": "B2_REALIZED_PASS",
            }
        ),
        encoding="utf-8",
    )
    grown = lineage_module.replay_b2_widen(
        seed,
        n_layers=1,
        eps_sigma=lineage_module.CANONICAL_B2_EPS_SIGMA,
        eps_seed=lineage_module.CANONICAL_B2_EPS_SEED,
    )
    grown_model = root / "grown-model.pt"
    torch.save(grown, grown_model)
    runtime_config = root / "runtime-config.json"
    runtime_body = {
        "schema": "q2-event-runtime-config-v1",
        "source_commit": "a" * 40,
        "historical_config_sha256": "4" * 64,
        "scope": "TARGET_TENSOR_COUNTERFACTUAL",
        "execution_authority": "EMBER_LAB_Q2_EVENT_ONLY",
        "model": {"vocab": 32, "hidden": 2, "layers": 1, "heads": 1, "seq": 4, "tied_embeddings": True, "grad_checkpointing": False},
        "objective": {"mtp_aux_heads": {"enabled": True, "n_heads": 1, "weight": 0.3}},
        "precision": {"qat": {"enabled": True}},
        "optimizer": {"lr_muon": 0.02},
        "no_new_parallel_authority": True,
    }
    runtime_body["config_sha256"] = hashlib.sha256(_canonical(runtime_body) + b"\n").hexdigest()
    runtime_config.write_bytes(_canonical(runtime_body) + b"\n")
    replay_receipt = {
        "schema": "q2-b2-replay-remint-receipt-v1",
        "source_commit": "a" * 40,
        "lineage_run_id": lineage_run_id,
        "verdict": "B2_REPLAY_REMINTED",
        "historical": {
            "receipt_sha256": lineage_module.CANONICAL_B2_RECEIPT_SHA256,
            "operator_sha256": lineage_module.CANONICAL_B2_OPERATOR_SHA256,
            "ticket": "CBASE-GROW-RUNG2-EVENT-B2",
            "verdict": "B2_REALIZED_PASS",
        },
        "law": {
            "n_layers": 1,
            "eps_sigma": lineage_module.CANONICAL_B2_EPS_SIGMA,
            "eps_seed": lineage_module.CANONICAL_B2_EPS_SEED,
            "banned_zero_assertion_passed": True,
            "distinct_from_eps0_cache": True,
            "eta_band_pass": True,
            "twin_cosine_pass": True,
        },
        "inputs": {
            "seed_manifest_sha256": hashlib.sha256(seed_manifest.read_bytes()).hexdigest(),
            "seed_model_sha256": hashlib.sha256(seed_model.read_bytes()).hexdigest(),
            "runtime_config_sha256": hashlib.sha256(runtime_config.read_bytes()).hexdigest(),
        },
        "operator_sha256": hashlib.sha256(grow_operator.read_bytes()).hexdigest(),
        "output": {"grown_model_sha256": hashlib.sha256(grown_model.read_bytes()).hexdigest()},
    }
    replay_receipt["receipt_sha256"] = hashlib.sha256(
        _canonical(replay_receipt) + b"\n"
    ).hexdigest()
    b2_receipt.write_bytes(_canonical(replay_receipt))
    model.load_state_dict(grown, strict=True)
    batch_sha = "b" * 64
    persisted_gradient = root / f"{run_id}-grad-post-gate.pt"
    torch.save(
        torch.full(grown[prefix + "gate_proj.weight"].shape, 0.25, dtype=torch.float32),
        persisted_gradient,
    )
    b3_receipt = root / "b3.json"
    b3_receipt.write_text(
        json.dumps(
            {
                "ticket": "CBASE-GROW-RUNG2-EVENT-B3",
                "run_id": run_id,
                "batch_pin_check": {
                    "b1m_sha256": batch_sha,
                    "b3_recomputed_sha256": batch_sha,
                    "match": True,
                },
                "cache_paths": {"grad_post_gate": persisted_gradient.name},
                "cache_sha256": {
                    "grad_post_gate": hashlib.sha256(
                        persisted_gradient.read_bytes()
                    ).hexdigest()
                },
                "gradient_lineage": {
                    "target_name": prefix + "gate_proj.weight",
                    "dtype": "float32",
                    "shape": list(grown[prefix + "gate_proj.weight"].shape),
                    "source": "pinned-batch-backward",
                    "batch_sha256": batch_sha,
                },
                "verdict": "B3_CAPTURED",
            }
        ),
        encoding="utf-8",
    )
    batch_manifest = root / "batch-manifest.json"
    batch_manifest.write_text(
        json.dumps({"schema": "q2-event-batch-input-v1", "batch_sha256": batch_sha}),
        encoding="utf-8",
    )
    return {
        "lineage_run_id": lineage_run_id,
        "expected_source_commit": "a" * 40,
        "seed_manifest_path": seed_manifest,
        "seed_model_path": seed_model,
        "seed_optimizer_path": seed_optimizer,
        "grown_model_path": grown_model,
        "b2_receipt_path": b2_receipt,
        "b1m_receipt_path": b1m_receipt,
        "b3_receipt_path": b3_receipt,
        "batch_manifest_path": batch_manifest,
        "persisted_pre_momentum_path": persisted_pre_momentum,
        "persisted_gradient_path": persisted_gradient,
        "gradient_data_root": root,
        "expected_batch_sha256": batch_sha,
        "grow_operator_path": grow_operator,
        "runtime_config_path": runtime_config,
        "n_layers": 1,
    }


def _arm_momenta(lineage: dict[str, object], gradient: torch.Tensor):
    pre = torch.load(
        lineage["persisted_pre_momentum_path"], map_location="cpu", weights_only=True
    )
    return torch.zeros_like(gradient), torch.cat([pre, pre], dim=0)


def _loss(target: torch.Tensor, non_target: dict[str, torch.Tensor]) -> float:
    return float(target.sum() + sum(value.sum() for value in non_target.values()))


@pytest.mark.skipif(not torch.cuda.is_available(), reason="actual post-state capture requires CUDA")
def test_adapter_derives_gpu_applied_target_arms_and_non_target_identity(tmp_path: Path):
    adapter = _load()
    model = TinyModel().cuda()
    custody = tmp_path / "custody"
    lineage = _lineage(custody, model, "q2-adapter-test")
    dispatch, bindings = _authority(
        custody,
        lineage["b2_receipt_path"],
        lineage["runtime_config_path"],
        lineage["b1m_receipt_path"],
        lineage["b3_receipt_path"],
        lineage["batch_manifest_path"],
    )
    gradient = torch.load(
        lineage["persisted_gradient_path"], map_location="cpu", weights_only=True
    )
    reset_momentum, transplant_momentum = _arm_momenta(lineage, gradient)

    manifest_path = adapter.capture_actual_event(
        custody_root=custody,
        run_id="q2-adapter-test",
        dispatch_receipt_path=dispatch,
        binding_files=bindings,
        model=model,
        target_name="backbone_model.layers.0.mlp.gate_proj.weight",
        reset_momentum=reset_momentum,
        transplant_momentum=transplant_momentum,
        loss_replay=_loss,
        learning_rate=0.02,
        optimizer_scale=1.0,
        **lineage,
    )

    manifest = json.loads(manifest_path.read_text())
    assert manifest["target"]["name"] == "backbone_model.layers.0.mlp.gate_proj.weight"
    assert manifest["non_target_manifest"]["entry_count"] >= 5
    assert manifest["paired_losses"]["replay_count_per_arm"] == 2
    assert manifest["manifest_sha256"] == hashlib.sha256(
        _canonical({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    ).hexdigest()
    admitted = _load_loader().load_capture(manifest_path, dispatch, _terminal(custody))
    assert admitted["non_target_state"]["aux_counter"].dtype == torch.bfloat16
    assert admitted["non_target_state"]["aux_counter"].item() == 7


def test_adapter_refuses_cpu_reconstruction_before_manifest(tmp_path: Path):
    adapter = _load()
    model = TinyModel()
    custody = tmp_path / "custody"
    lineage = _lineage(custody, model, "q2-adapter-test")
    dispatch, bindings = _authority(
        custody,
        lineage["b2_receipt_path"],
        lineage["runtime_config_path"],
        lineage["b1m_receipt_path"],
        lineage["b3_receipt_path"],
        lineage["batch_manifest_path"],
    )
    gradient = torch.load(
        lineage["persisted_gradient_path"], map_location="cpu", weights_only=True
    )

    with pytest.raises(adapter.CaptureAdapterRefusal, match="EVENT_GPU_APPLICATION_REQUIRED"):
        adapter.capture_actual_event(
            custody_root=custody,
            run_id="q2-adapter-test",
            dispatch_receipt_path=dispatch,
            binding_files=bindings,
            model=model,
            target_name="backbone_model.layers.0.mlp.gate_proj.weight",
            reset_momentum=_arm_momenta(lineage, gradient)[0],
            transplant_momentum=_arm_momenta(lineage, gradient)[1],
            loss_replay=_loss,
            learning_rate=0.02,
            optimizer_scale=1.0,
            **lineage,
        )

    assert not (custody / "capture-manifest.json").exists()


def test_adapter_refuses_foreign_dispatch_source_before_model_use(tmp_path: Path):
    adapter = _load()
    model = TinyModel()
    custody = tmp_path / "custody"
    lineage = _lineage(custody, model, "q2-adapter-test")
    dispatch, bindings = _authority(
        custody,
        lineage["b2_receipt_path"],
        lineage["runtime_config_path"],
        lineage["b1m_receipt_path"],
        lineage["b3_receipt_path"],
        lineage["batch_manifest_path"],
    )
    receipt = json.loads(dispatch.read_text(encoding="utf-8"))
    receipt["source_commit"] = "b" * 40
    dispatch.write_bytes(_canonical(receipt))
    before = {name: tensor.detach().clone() for name, tensor in model.state_dict().items()}
    gradient = torch.load(lineage["persisted_gradient_path"], map_location="cpu", weights_only=True)

    with pytest.raises(adapter.CaptureAdapterRefusal, match="EVENT_DISPATCH_SOURCE_MISMATCH"):
        adapter.capture_actual_event(
            custody_root=custody,
            run_id="q2-adapter-test",
            dispatch_receipt_path=dispatch,
            binding_files=bindings,
            model=model,
            target_name="backbone_model.layers.0.mlp.gate_proj.weight",
            reset_momentum=_arm_momenta(lineage, gradient)[0],
            transplant_momentum=_arm_momenta(lineage, gradient)[1],
            loss_replay=_loss,
            learning_rate=0.02,
            optimizer_scale=1.0,
            **lineage,
        )

    assert all(torch.equal(before[name], value) for name, value in model.state_dict().items())
    assert not (custody / "capture-manifest.json").exists()


def test_adapter_refuses_self_hashed_unsealed_runtime_config_before_model_use(tmp_path: Path):
    adapter = _load()
    model = TinyModel()
    custody = tmp_path / "custody"
    lineage = _lineage(custody, model, "q2-adapter-test")
    dispatch, bindings = _authority(
        custody,
        lineage["b2_receipt_path"],
        lineage["runtime_config_path"],
        lineage["b1m_receipt_path"],
        lineage["b3_receipt_path"],
        lineage["batch_manifest_path"],
    )
    runtime_path = lineage["runtime_config_path"]
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    runtime["scope"] = "FOREIGN_UNSEALED_SCOPE"
    runtime.pop("config_sha256")
    runtime["config_sha256"] = hashlib.sha256(_canonical(runtime) + b"\n").hexdigest()
    runtime_path.write_bytes(_canonical(runtime) + b"\n")
    replay = json.loads(lineage["b2_receipt_path"].read_text(encoding="utf-8"))
    replay["inputs"]["runtime_config_sha256"] = hashlib.sha256(runtime_path.read_bytes()).hexdigest()
    replay.pop("receipt_sha256")
    replay["receipt_sha256"] = hashlib.sha256(_canonical(replay) + b"\n").hexdigest()
    lineage["b2_receipt_path"].write_bytes(_canonical(replay))
    bindings["config_sha256"].write_bytes(runtime_path.read_bytes())
    bindings["checkpoint_sha256"].write_bytes(lineage["b2_receipt_path"].read_bytes())
    before = {name: tensor.detach().clone() for name, tensor in model.state_dict().items()}
    gradient = torch.load(lineage["persisted_gradient_path"], map_location="cpu", weights_only=True)

    with pytest.raises(adapter.CaptureAdapterRefusal, match="EVENT_RUNTIME_CONFIG_REFUSED"):
        adapter.capture_actual_event(
            custody_root=custody,
            run_id="q2-adapter-test",
            dispatch_receipt_path=dispatch,
            binding_files=bindings,
            model=model,
            target_name="backbone_model.layers.0.mlp.gate_proj.weight",
            reset_momentum=_arm_momenta(lineage, gradient)[0],
            transplant_momentum=_arm_momenta(lineage, gradient)[1],
            loss_replay=_loss,
            learning_rate=0.02,
            optimizer_scale=1.0,
            **lineage,
        )

    assert all(torch.equal(before[name], value) for name, value in model.state_dict().items())
    assert not (custody / "capture-manifest.json").exists()


def test_adapter_refuses_foreign_lineage_path_before_model_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    adapter = _load()
    model = TinyModel()
    custody = tmp_path / "custody"
    lineage = _lineage(custody, model, "q2-adapter-test")
    dispatch, bindings = _authority(
        custody,
        lineage["b2_receipt_path"],
        lineage["runtime_config_path"],
        lineage["b1m_receipt_path"],
        lineage["b3_receipt_path"],
        lineage["batch_manifest_path"],
    )
    foreign = tmp_path / "foreign-b2.json"
    foreign.write_bytes(lineage["b2_receipt_path"].read_bytes())
    lineage["b2_receipt_path"] = foreign
    gradient = torch.load(
        lineage["persisted_gradient_path"], map_location="cpu", weights_only=True
    )
    monkeypatch.setattr(
        adapter,
        "_snapshot",
        lambda _model: (_ for _ in ()).throw(AssertionError("model accessed")),
    )

    with pytest.raises(
        adapter.CaptureAdapterRefusal, match="EVENT_B2_RECEIPT_CUSTODY_REFUSED"
    ):
        adapter.capture_actual_event(
            custody_root=custody,
            run_id="q2-adapter-test",
            dispatch_receipt_path=dispatch,
            binding_files=bindings,
            model=model,
            target_name="backbone_model.layers.0.mlp.gate_proj.weight",
            reset_momentum=_arm_momenta(lineage, gradient)[0],
            transplant_momentum=_arm_momenta(lineage, gradient)[1],
            loss_replay=_loss,
            learning_rate=0.02,
            optimizer_scale=1.0,
            **lineage,
        )

    assert not (custody / "capture-manifest.json").exists()


def test_adapter_refuses_binding_symlink_escape_before_model_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    adapter = _load()
    model = TinyModel()
    custody = tmp_path / "custody"
    lineage = _lineage(custody, model, "q2-adapter-test")
    dispatch, bindings = _authority(
        custody,
        lineage["b2_receipt_path"],
        lineage["runtime_config_path"],
        lineage["b1m_receipt_path"],
        lineage["b3_receipt_path"],
        lineage["batch_manifest_path"],
    )
    foreign = tmp_path / "foreign-binding.bin"
    foreign.write_bytes(bindings["config_sha256"].read_bytes())
    link = custody / "binding-escape.bin"
    try:
        link.symlink_to(foreign)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    bindings["config_sha256"] = link
    gradient = torch.load(
        lineage["persisted_gradient_path"], map_location="cpu", weights_only=True
    )
    monkeypatch.setattr(
        adapter,
        "_snapshot",
        lambda _model: (_ for _ in ()).throw(AssertionError("model accessed")),
    )

    with pytest.raises(
        adapter.CaptureAdapterRefusal, match="EVENT_BINDING_CUSTODY_REFUSED"
    ):
        adapter.capture_actual_event(
            custody_root=custody,
            run_id="q2-adapter-test",
            dispatch_receipt_path=dispatch,
            binding_files=bindings,
            model=model,
            target_name="backbone_model.layers.0.mlp.gate_proj.weight",
            reset_momentum=_arm_momenta(lineage, gradient)[0],
            transplant_momentum=_arm_momenta(lineage, gradient)[1],
            loss_replay=_loss,
            learning_rate=0.02,
            optimizer_scale=1.0,
            **lineage,
        )

    assert not (custody / "capture-manifest.json").exists()


def test_adapter_refuses_forged_optimizer_binding_before_manifest(tmp_path: Path):
    adapter = _load()
    model = TinyModel()
    custody = tmp_path / "custody"
    lineage = _lineage(custody, model, "q2-adapter-test")
    dispatch, bindings = _authority(
        custody,
        lineage["b2_receipt_path"],
        lineage["runtime_config_path"],
        lineage["b1m_receipt_path"],
        lineage["b3_receipt_path"],
        lineage["batch_manifest_path"],
    )
    bindings["optimizer_sha256"].write_text("forged optimizer", encoding="utf-8")
    gradient = torch.load(
        lineage["persisted_gradient_path"], map_location="cpu", weights_only=True
    )

    with pytest.raises(adapter.CaptureAdapterRefusal, match="EVENT_OPTIMIZER_BINDING_MISMATCH"):
        adapter.capture_actual_event(
            custody_root=custody,
            run_id="q2-adapter-test",
            dispatch_receipt_path=dispatch,
            binding_files=bindings,
            model=model,
            target_name="backbone_model.layers.0.mlp.gate_proj.weight",
            reset_momentum=_arm_momenta(lineage, gradient)[0],
            transplant_momentum=_arm_momenta(lineage, gradient)[1],
            loss_replay=_loss,
            learning_rate=0.02,
            optimizer_scale=1.0,
            **lineage,
        )

    assert not (custody / "capture-manifest.json").exists()


def test_adapter_refuses_mutated_persisted_gradient_before_manifest(tmp_path: Path):
    adapter = _load()
    model = TinyModel()
    custody = tmp_path / "custody"
    lineage = _lineage(custody, model, "q2-adapter-test")
    dispatch, bindings = _authority(
        custody,
        lineage["b2_receipt_path"],
        lineage["runtime_config_path"],
        lineage["b1m_receipt_path"],
        lineage["b3_receipt_path"],
        lineage["batch_manifest_path"],
    )
    original = torch.load(
        lineage["persisted_gradient_path"], map_location="cpu", weights_only=True
    )
    torch.save(torch.ones_like(original), lineage["persisted_gradient_path"])

    with pytest.raises(adapter.CaptureAdapterRefusal, match="EVENT_GRADIENT_LINEAGE_REFUSED"):
        adapter.capture_actual_event(
            custody_root=custody,
            run_id="q2-adapter-test",
            dispatch_receipt_path=dispatch,
            binding_files=bindings,
            model=model,
            target_name="backbone_model.layers.0.mlp.gate_proj.weight",
            reset_momentum=_arm_momenta(lineage, original)[0],
            transplant_momentum=_arm_momenta(lineage, original)[1],
            loss_replay=_loss,
            learning_rate=0.02,
            optimizer_scale=1.0,
            **lineage,
        )

    assert not (custody / "capture-manifest.json").exists()
