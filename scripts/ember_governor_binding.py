#!/usr/bin/env python3
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

import governor
from receipt_write import checked_write

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
