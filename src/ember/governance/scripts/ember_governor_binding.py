#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Governor/artifact binding receipt for Ember MVP v0.

Fixture mode records governor rails and a hashable checkpoint artifact tied to
one cycle id. It does not claim `governor.preflight()` or GPU training ran.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# issue2015 exact-local-import:src/ember/governance/scripts/governor.py
import importlib.util as _ember_86cfcf0844b5c48e_importlib
import sys as _ember_86cfcf0844b5c48e_sys
from pathlib import Path as _ember_86cfcf0844b5c48e_Path
_ember_86cfcf0844b5c48e_path = _ember_86cfcf0844b5c48e_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'governor.py')
if not _ember_86cfcf0844b5c48e_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/governor.py')
_ember_86cfcf0844b5c48e_aliases = ('_ember_issue2015_86cfcf0844b5c48e', 'governor', 'scripts.governor')
_ember_86cfcf0844b5c48e_existing = []
for _ember_86cfcf0844b5c48e_alias in _ember_86cfcf0844b5c48e_aliases:
    _ember_86cfcf0844b5c48e_candidate = _ember_86cfcf0844b5c48e_sys.modules.get(_ember_86cfcf0844b5c48e_alias)
    if _ember_86cfcf0844b5c48e_candidate is not None and all(_ember_86cfcf0844b5c48e_candidate is not item for item in _ember_86cfcf0844b5c48e_existing):
        _ember_86cfcf0844b5c48e_existing.append(_ember_86cfcf0844b5c48e_candidate)
if len(_ember_86cfcf0844b5c48e_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/governor.py')
if _ember_86cfcf0844b5c48e_existing:
    _ember_86cfcf0844b5c48e_module = _ember_86cfcf0844b5c48e_existing[0]
    _ember_86cfcf0844b5c48e_observed = getattr(_ember_86cfcf0844b5c48e_module, '__file__', None)
    if _ember_86cfcf0844b5c48e_observed is None or _ember_86cfcf0844b5c48e_Path(_ember_86cfcf0844b5c48e_observed).resolve() != _ember_86cfcf0844b5c48e_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/governor.py')
else:
    _ember_86cfcf0844b5c48e_spec = _ember_86cfcf0844b5c48e_importlib.spec_from_file_location('_ember_issue2015_86cfcf0844b5c48e', _ember_86cfcf0844b5c48e_path)
    if _ember_86cfcf0844b5c48e_spec is None or _ember_86cfcf0844b5c48e_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/governor.py')
    _ember_86cfcf0844b5c48e_module = _ember_86cfcf0844b5c48e_importlib.module_from_spec(_ember_86cfcf0844b5c48e_spec)
    for _ember_86cfcf0844b5c48e_alias in _ember_86cfcf0844b5c48e_aliases:
        _ember_86cfcf0844b5c48e_prior = _ember_86cfcf0844b5c48e_sys.modules.get(_ember_86cfcf0844b5c48e_alias)
        if _ember_86cfcf0844b5c48e_prior is not None and _ember_86cfcf0844b5c48e_prior is not _ember_86cfcf0844b5c48e_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/governor.py')
        _ember_86cfcf0844b5c48e_sys.modules[_ember_86cfcf0844b5c48e_alias] = _ember_86cfcf0844b5c48e_module
    try:
        _ember_86cfcf0844b5c48e_spec.loader.exec_module(_ember_86cfcf0844b5c48e_module)
    except BaseException:
        for _ember_86cfcf0844b5c48e_alias in _ember_86cfcf0844b5c48e_aliases:
            if _ember_86cfcf0844b5c48e_sys.modules.get(_ember_86cfcf0844b5c48e_alias) is _ember_86cfcf0844b5c48e_module:
                _ember_86cfcf0844b5c48e_sys.modules.pop(_ember_86cfcf0844b5c48e_alias, None)
        raise
for _ember_86cfcf0844b5c48e_alias in _ember_86cfcf0844b5c48e_aliases:
    _ember_86cfcf0844b5c48e_prior = _ember_86cfcf0844b5c48e_sys.modules.get(_ember_86cfcf0844b5c48e_alias)
    if _ember_86cfcf0844b5c48e_prior is not None and _ember_86cfcf0844b5c48e_prior is not _ember_86cfcf0844b5c48e_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/governor.py')
    _ember_86cfcf0844b5c48e_sys.modules[_ember_86cfcf0844b5c48e_alias] = _ember_86cfcf0844b5c48e_module
governor = _ember_86cfcf0844b5c48e_module
# issue2015 exact-local-import-end:src/ember/governance/scripts/governor.py
# issue2015 exact-local-import:src/ember/governance/scripts/receipt_write.py
import importlib.util as _ember_66ee9e91637922dc_importlib
import sys as _ember_66ee9e91637922dc_sys
from pathlib import Path as _ember_66ee9e91637922dc_Path
_ember_66ee9e91637922dc_path = _ember_66ee9e91637922dc_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_write.py')
if not _ember_66ee9e91637922dc_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/receipt_write.py')
_ember_66ee9e91637922dc_aliases = ('_ember_issue2015_66ee9e91637922dc', 'receipt_write', 'scripts.receipt_write')
_ember_66ee9e91637922dc_existing = []
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_candidate = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_candidate is not None and all(_ember_66ee9e91637922dc_candidate is not item for item in _ember_66ee9e91637922dc_existing):
        _ember_66ee9e91637922dc_existing.append(_ember_66ee9e91637922dc_candidate)
if len(_ember_66ee9e91637922dc_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/receipt_write.py')
if _ember_66ee9e91637922dc_existing:
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_existing[0]
    _ember_66ee9e91637922dc_observed = getattr(_ember_66ee9e91637922dc_module, '__file__', None)
    if _ember_66ee9e91637922dc_observed is None or _ember_66ee9e91637922dc_Path(_ember_66ee9e91637922dc_observed).resolve() != _ember_66ee9e91637922dc_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/receipt_write.py')
else:
    _ember_66ee9e91637922dc_spec = _ember_66ee9e91637922dc_importlib.spec_from_file_location('_ember_issue2015_66ee9e91637922dc', _ember_66ee9e91637922dc_path)
    if _ember_66ee9e91637922dc_spec is None or _ember_66ee9e91637922dc_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_importlib.module_from_spec(_ember_66ee9e91637922dc_spec)
    for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
        _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
        if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
        _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
    try:
        _ember_66ee9e91637922dc_spec.loader.exec_module(_ember_66ee9e91637922dc_module)
    except BaseException:
        for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
            if _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias) is _ember_66ee9e91637922dc_module:
                _ember_66ee9e91637922dc_sys.modules.pop(_ember_66ee9e91637922dc_alias, None)
        raise
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
checked_write = getattr(_ember_66ee9e91637922dc_module, 'checked_write')
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py

SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"


class GovernorBindingValidationError(ValueError):
    pass


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def load_receipt(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def run_fixture_binding(root: Path, cycle_id: str) -> dict[str, Any]:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    frac, margin_gb, throttle_s = governor.env_limits()

    artifact_dir = root / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / "checkpoint-fixture.bin"
    artifact_bytes = (
        f"cycle_id={cycle_id}\n"
        f"vram_fraction={frac}\n"
        f"margin_gb={margin_gb}\n"
        f"throttle_s={throttle_s}\n"
    ).encode("utf-8")
    artifact_path.write_bytes(artifact_bytes)
    artifact_hash = sha256_bytes(artifact_bytes)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    receipt = {
        "ticket": "EMBER-GOVERNOR-BINDING-FIXTURE",
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "cycle_id": cycle_id,
        "mode": "cpu-fixture-no-gpu-preflight",
        "gpu_preflight_called": False,
        "real_gpu_training": False,
        "governor": {
            "vram_fraction": frac,
            "margin_gb": margin_gb,
            "throttle_s": throttle_s,
            "source": "governor.env_limits",
        },
        "artifact": {
            "kind": "checkpoint-fixture",
            "path": str(artifact_path),
            "checkpoint_hash": artifact_hash,
            "adapter_hash": None,
        },
        "failure_mode": None,
    }
    out = root / "receipts" / "governor" / f"governor-binding-{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out), receipt)
    receipt["receipt_path"] = str(out)
    validate_governor_receipt(receipt)
    return receipt


def run_real_governed_smoke(root: Path, cycle_id: str) -> dict[str, Any]:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    frac, margin_gb, throttle_s = governor.env_limits()

    import torch

    if not torch.cuda.is_available():
        raise GovernorBindingValidationError("CUDA is not available for real governed smoke")

    preflight = governor.preflight()
    device = torch.device("cuda:0")
    torch.manual_seed(123456)
    model = torch.nn.Linear(4, 2).to(device)
    optimizer = torch.optim.SGD(model.parameters(), lr=0.05)
    x = torch.randn(8, 4, device=device)
    y = torch.randn(8, 2, device=device)

    def loss_value() -> torch.Tensor:
        return torch.nn.functional.mse_loss(model(x), y)

    loss_before = float(loss_value().detach().cpu())
    steps = 2
    for _ in range(steps):
        optimizer.zero_grad(set_to_none=True)
        loss = loss_value()
        loss.backward()
        optimizer.step()
        governor.throttle_step()
    torch.cuda.synchronize()
    loss_after = float(loss_value().detach().cpu())

    artifact_dir = root / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / "governed-smoke-checkpoint.pt"
    torch.save(
        {
            "cycle_id": cycle_id,
            "model_state": {k: v.detach().cpu() for k, v in model.state_dict().items()},
            "optimizer_state": optimizer.state_dict(),
            "loss_before": loss_before,
            "loss_after": loss_after,
            "steps": steps,
        },
        artifact_path,
    )
    artifact_hash = sha256_bytes(artifact_path.read_bytes())
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "EMBER-GOVERNOR-REAL-RUN",
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "cycle_id": cycle_id,
        "mode": "governed-gpu-train-eval",
        "gpu_preflight_called": True,
        "real_gpu_training": True,
        "governor": {
            "vram_fraction": preflight.get("vram_fraction", frac),
            "margin_gb": preflight.get("margin_gb", margin_gb),
            "throttle_s": throttle_s,
            "free_gb": preflight.get("free_gb"),
            "total_gb": preflight.get("total_gb"),
            "source": "governor.preflight",
        },
        "train_eval": {
            "device": str(device),
            "device_name": torch.cuda.get_device_name(0),
            "steps": steps,
            "loss_before": round(loss_before, 8),
            "loss_after": round(loss_after, 8),
            "loss_delta": round(loss_before - loss_after, 8),
        },
        "artifact": {
            "kind": "checkpoint",
            "path": str(artifact_path),
            "checkpoint_hash": artifact_hash,
            "adapter_hash": None,
        },
        "failure_mode": None,
    }
    out = root / "receipts" / "governor" / f"governor-real-{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out), receipt)
    receipt["receipt_path"] = str(out)
    validate_governor_receipt(receipt)
    return receipt


def validate_governor_receipt(receipt: dict[str, Any]) -> None:
    errors: list[str] = []
    if receipt.get("ticket") not in {"EMBER-GOVERNOR-BINDING-FIXTURE", "EMBER-GOVERNOR-REAL-RUN"}:
        errors.append("bad ticket")
    if not receipt.get("cycle_id"):
        errors.append("missing cycle_id")
    if receipt.get("mode") == "cpu-fixture-no-gpu-preflight":
        if receipt.get("gpu_preflight_called") is not False:
            errors.append("fixture receipt cannot claim GPU preflight")
        if receipt.get("real_gpu_training") is not False:
            errors.append("fixture receipt cannot claim real GPU training")
    elif receipt.get("mode") == "governed-gpu-train-eval":
        if receipt.get("gpu_preflight_called") is not True:
            errors.append("real run must call GPU preflight")
        if receipt.get("real_gpu_training") is not True:
            errors.append("real run must mark real_gpu_training")
    else:
        errors.append("unknown governor binding mode")
    gov = receipt.get("governor", {})
    if gov.get("vram_fraction", 99) > 0.85:
        errors.append("governor vram_fraction looser than 0.85")
    if gov.get("margin_gb", 0) < 1.5:
        errors.append("governor margin below 1.5GB")
    if gov.get("throttle_s", -1) < 0:
        errors.append("governor throttle_s cannot be negative")
    artifact = receipt.get("artifact", {})
    artifact_path = artifact.get("path")
    if not artifact_path or not Path(artifact_path).exists():
        errors.append("artifact path missing")
    if not str(artifact.get("checkpoint_hash", "")).startswith("sha256:"):
        errors.append("missing checkpoint hash")
    if receipt.get("mode") == "governed-gpu-train-eval":
        train_eval = receipt.get("train_eval", {})
        if not str(train_eval.get("device", "")).startswith("cuda"):
            errors.append("real run must execute on cuda")
        if train_eval.get("steps", 0) < 1:
            errors.append("real run must record at least one train step")
    if errors:
        raise GovernorBindingValidationError("; ".join(errors))


def main() -> int:
    import argparse
    import tempfile

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--fixture-out", help="write a fixture governor binding receipt under this directory")
    ap.add_argument("--cycle-id", default="cycle-20260617T000000Z-0001")
    ap.add_argument("--real-smoke", action="store_true", help="run a tiny governed CUDA train/eval smoke")
    args = ap.parse_args()

    if args.selftest:
        with tempfile.TemporaryDirectory(prefix="ember-governor-binding-") as td:
            run_fixture_binding(Path(td), cycle_id=args.cycle_id)
        print("EMBER_GOVERNOR_BINDING_SELFTEST_PASS")
        return 0

    if args.fixture_out:
        if args.real_smoke:
            receipt = run_real_governed_smoke(Path(args.fixture_out), cycle_id=args.cycle_id)
        else:
            receipt = run_fixture_binding(Path(args.fixture_out), cycle_id=args.cycle_id)
        print(json.dumps(receipt, indent=2))
        return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
