#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Current-native CPU-offload producer for the #764 factor-1 boundary.

This module is the executable producer/identity boundary that the historical
``timeshare_pretrain.py`` path no longer supplies.  It does not claim a
2.2B performance result by constructing a surrogate: the exact ordered
Muon's 140 matrices and AdamW's 44 parameters are defined here, and the
explicit scale entrypoint constructs those exact tensors before handing them
to the repository's real ``CPUOffloadOptimizer``.  The CPU-only smoke path
uses the same wrapper and the same optimizer classes with a tiny shape.

The Muon arithmetic is the production optimizer algorithm carried forward
from the last executable timeshare source before the historical-only lock
(``4f758db^``).  The source/optimizer bytes are recorded in every identity
receipt; caller-supplied hashes are never accepted as authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

CPU_OFFLOAD_SOURCE = SCRIPT_DIR / "cpu_offload_adamw.py"
EXACT_SCALE = "2.2B"
EXACT_WORKING_SET_GIB = 24.9029695
RESOURCE_MARGIN_GIB = 6.0
DISK_MARGIN_GIB = 4.0


def _canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _shape_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for layer in range(20):
        for name in ("q", "k", "v", "o"):
            rows.append({"name": f"layers.{layer}.self_attn.{name}.weight", "optimizer": "muon", "shape": [1024, 1024]})
        rows.append({"name": f"layers.{layer}.mlp.gate.weight", "optimizer": "muon", "shape": [32768, 1024]})
        rows.append({"name": f"layers.{layer}.mlp.up.weight", "optimizer": "muon", "shape": [32768, 1024]})
        rows.append({"name": f"layers.{layer}.mlp.down.weight", "optimizer": "muon", "shape": [1024, 32768]})
    rows.extend(
        {"name": name, "optimizer": "adamw", "shape": [32000, 1024]}
        for name in ("embed.weight", "mtp_heads.0.weight", "mtp_heads.1.weight")
    )
    rows.extend(
        {"name": f"norms.{idx}.weight", "optimizer": "adamw", "shape": [1024]}
        for idx in range(41)
    )
    return rows


def exact_shape_manifest() -> dict[str, Any]:
    rows = _shape_rows()
    groups: dict[str, dict[str, Any]] = {}
    for optimizer in ("muon", "adamw"):
        selected = [row for row in rows if row["optimizer"] == optimizer]
        parameter_numel = sum(math.prod(row["shape"]) for row in selected)
        # The frozen #764 identity is an optimizer-state contract: Muon has
        # one FP32 momentum tensor per routed matrix; AdamW has two FP32
        # moments plus one scalar step per parameter group entry.
        state_numel = parameter_numel if optimizer == "muon" else 2 * parameter_numel + len(selected)
        groups[optimizer] = {
            "count": len(selected),
            "parameter_numel": parameter_numel,
            "state_numel": state_numel,
            "numel": state_numel,
            "ordered_shape_sha256": _sha256_bytes(_canonical_bytes(selected)),
        }
    return {
        "schema": "ember-factor1-exact-shape-v1",
        "scale": EXACT_SCALE,
        "rows": rows,
        "muon": groups["muon"],
        "adamw": groups["adamw"],
        "shape_sha256": _sha256_bytes(_canonical_bytes(rows)),
    }


def source_identity() -> dict[str, str]:
    """Hash the exact producer and optimizer bytes used by this process."""
    producer_bytes = Path(__file__).read_bytes()
    optimizer_bytes = CPU_OFFLOAD_SOURCE.read_bytes()
    return {
        "producer_basename": Path(__file__).name,
        "producer_sha256": _sha256_bytes(producer_bytes),
        "optimizer_basename": CPU_OFFLOAD_SOURCE.name,
        "optimizer_sha256": _sha256_bytes(optimizer_bytes),
    }


def _finite_gib(snapshot: dict[str, Any], field: str) -> float | None:
    value = snapshot.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def preflight_exact_scale(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Fail closed before exact tensor construction or optimizer files."""
    fields = {
        "available_commit_gib": "commit",
        "available_physical_gib": "physical",
        "disk_free_gib": "disk",
    }
    refusal_reasons: list[str] = []
    values: dict[str, float | None] = {}
    for field, label in fields.items():
        value = _finite_gib(snapshot, field)
        values[field] = value
        required = EXACT_WORKING_SET_GIB + (RESOURCE_MARGIN_GIB if label != "disk" else DISK_MARGIN_GIB)
        if value is None:
            refusal_reasons.append(f"{label} metric missing/nonfinite")
        elif value < required:
            refusal_reasons.append(f"{label} free {value:.6f} GiB < required {required:.6f} GiB")
    return {
        "scale": EXACT_SCALE,
        "required_working_set_gib": EXACT_WORKING_SET_GIB,
        "required_commit_and_physical_gib": EXACT_WORKING_SET_GIB + RESOURCE_MARGIN_GIB,
        "required_disk_gib": EXACT_WORKING_SET_GIB + DISK_MARGIN_GIB,
        "observed": values,
        "refusal_reasons": refusal_reasons,
        "sufficient": not refusal_reasons,
    }


def _zeropower_via_newtonschulz5(G, steps: int = 5, eps: float = 1e-7):
    import torch
    if G.ndim != 2:
        raise ValueError("Muon requires 2D tensors")
    a, b, c = 3.4445, -4.7750, 2.0315
    X = G.to(torch.float32)
    transposed = X.shape[0] > X.shape[1]
    if transposed:
        X = X.T
    X = X / (X.norm() + eps)
    for _ in range(steps):
        A = X @ X.T
        X = a * X + (b * A + c * (A @ A)) @ X
    return X.T if transposed else X


_MUON_CLASS = None


def _muon_class():
    global _MUON_CLASS
    if _MUON_CLASS is not None:
        return _MUON_CLASS
    import torch

    class Muon(torch.optim.Optimizer):
        def __init__(self, params, lr=0.02, momentum=0.95, nesterov=True, ns_steps=5, weight_decay=0.0):
            super().__init__(params, dict(lr=lr, momentum=momentum, nesterov=nesterov, ns_steps=ns_steps, weight_decay=weight_decay))

        @torch.no_grad()
        def step(self, closure=None):
            loss = None
            if closure is not None:
                with torch.enable_grad():
                    loss = closure()
            for group in self.param_groups:
                for p in group["params"]:
                    if p.grad is None:
                        continue
                    if p.ndim != 2:
                        raise ValueError("Muon received a non-2D parameter")
                    state = self.state[p]
                    buf = state.setdefault("momentum_buffer", torch.zeros_like(p.grad))
                    buf.mul_(group["momentum"]).add_(p.grad)
                    update = p.grad.add(buf, alpha=group["momentum"]) if group["nesterov"] else buf
                    update = _zeropower_via_newtonschulz5(update, steps=group["ns_steps"])
                    if group["weight_decay"]:
                        p.mul_(1.0 - group["lr"] * group["weight_decay"])
                    scale = max(1.0, p.shape[0] / p.shape[1]) ** 0.5
                    p.add_(update, alpha=-group["lr"] * scale)
            return loss

    _MUON_CLASS = Muon
    return _MUON_CLASS


def _build_tiny_production_optimizers(root: Path):
    import torch
    from cpu_offload_adamw import CPUOffloadOptimizer

    adam_params = [
        ("embed.weight", torch.nn.Parameter(torch.ones((8, 4), dtype=torch.float32))),
        ("norms.0.weight", torch.nn.Parameter(torch.ones((4,), dtype=torch.float32))),
    ]
    muon_params = [("layers.0.self_attn.q.weight", torch.nn.Parameter(torch.ones((4, 4), dtype=torch.float32)))]
    adam = CPUOffloadOptimizer(
        adam_params,
        lambda params: torch.optim.AdamW(params, lr=3e-4, weight_decay=0.1),
        optstate_dir=root / "adamw",
    )
    muon = CPUOffloadOptimizer(
        muon_params,
        lambda params: _muon_class()(params, lr=0.02, momentum=0.95),
        optstate_dir=root / "muon",
    )
    return adam_params, muon_params, adam, muon


def run_production_smoke(optstate_dir: Path, *, steps: int = 2) -> dict[str, Any]:
    """Execute real wrapper + optimizer classes on a bounded CPU shape."""
    if isinstance(steps, bool) or not isinstance(steps, int) or steps < 1:
        raise ValueError("steps must be a positive integer")
    optstate_dir = Path(optstate_dir)
    adam_params, muon_params, adam, muon = _build_tiny_production_optimizers(optstate_dir)
    for _ in range(steps):
        for _, parameter in adam_params + muon_params:
            parameter.grad = parameter.detach().clone()
        adam.step()
        muon.step()
    return {
        "schema": "ember-factor1-production-smoke-v1",
        "status": "PRODUCTION_SMOKE_PASS",
        "steps": steps,
        "optimizers": {"adamw": {"class": type(adam._inner).__name__}, "muon": {"class": type(muon._inner).__name__}},
        "offload_wrapper": {
            "class": type(adam).__name__,
            "used_real_cpu_offload_optimizer": True,
            "arithmetic_source": "optimizer_classes",
        },
        "identity": source_identity(),
    }


def run_exact_scale_cpu(optstate_dir: Path, snapshot: dict[str, Any], *, steps: int, execute: bool = False) -> dict[str, Any]:
    """Construct the exact shape only after explicit preflight and consent."""
    if not execute:
        raise PermissionError("exact-scale construction requires execute=True")
    gate = preflight_exact_scale(snapshot)
    if not gate["sufficient"]:
        raise RuntimeError("exact-scale preflight refused: " + "; ".join(gate["refusal_reasons"]))
    if isinstance(steps, bool) or not isinstance(steps, int) or steps < 1:
        raise ValueError("steps must be a positive integer")
    import torch
    from cpu_offload_adamw import CPUOffloadOptimizer
    rows = _shape_rows()
    params = [(row["name"], torch.nn.Parameter(torch.zeros(tuple(row["shape"]), dtype=torch.float32))) for row in rows]
    muon_params = [(name, p) for (name, p), row in zip(params, rows) if row["optimizer"] == "muon"]
    adam_params = [(name, p) for (name, p), row in zip(params, rows) if row["optimizer"] == "adamw"]
    adam = CPUOffloadOptimizer(adam_params, lambda ps: torch.optim.AdamW(ps, lr=3e-4, weight_decay=0.1), optstate_dir=Path(optstate_dir) / "adamw")
    muon = CPUOffloadOptimizer(muon_params, lambda ps: _muon_class()(ps, lr=0.02, momentum=0.95), optstate_dir=Path(optstate_dir) / "muon")
    for _ in range(steps):
        for _, parameter in params:
            parameter.grad = torch.ones_like(parameter)
        adam.step()
        muon.step()
    return {"schema": "ember-factor1-production-exact-v1", "status": "EXECUTED", "scale": EXACT_SCALE, "steps": steps, "shape": exact_shape_manifest(), "preflight": gate, "identity": source_identity()}


def _resource_snapshot() -> dict[str, float | None]:
    import ctypes
    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                    ("total_phys", ctypes.c_ulonglong), ("avail_phys", ctypes.c_ulonglong),
                    ("total_page", ctypes.c_ulonglong), ("avail_page", ctypes.c_ulonglong),
                    ("total_virtual", ctypes.c_ulonglong), ("avail_virtual", ctypes.c_ulonglong),
                    ("avail_extended", ctypes.c_ulonglong)]
    status = MemoryStatus()
    status.length = ctypes.sizeof(MemoryStatus)
    physical = commit = None
    if hasattr(ctypes, "windll") and ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        physical = status.avail_phys / 2**30
        commit = status.avail_page / 2**30
    disk = shutil.disk_usage(REPO.anchor)
    return {"available_physical_gib": physical, "available_commit_gib": commit, "disk_free_gib": disk.free / 2**30}


def _selftest() -> int:
    shape = exact_shape_manifest()
    assert shape["muon"]["count"] == 140 and shape["muon"]["numel"] == 2_097_152_000
    assert shape["adamw"]["count"] == 44 and shape["adamw"]["numel"] == 196_692_012
    with tempfile.TemporaryDirectory(prefix="factor1-native-selftest-") as td:
        smoke = run_production_smoke(Path(td), steps=2)
    assert smoke["status"] == "PRODUCTION_SMOKE_PASS"
    refused = preflight_exact_scale({"available_commit_gib": 0.0, "available_physical_gib": 0.0, "disk_free_gib": 0.0})
    assert not refused["sufficient"]
    print("F1NATIVE_SHAPES_BOUND_PASS")
    print("F1NATIVE_CPUOFFLOAD_PRODUCTION_PATH_PASS")
    print("F1NATIVE_NEGATIVE_PREFLIGHT_PASS")
    print("F1NATIVE_SELFTEST_ALL_PASS")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--steps", type=int, default=1)
    args = parser.parse_args(argv)
    if args.selftest:
        return _selftest()
    if args.smoke:
        with tempfile.TemporaryDirectory(prefix="factor1-native-smoke-") as td:
            result = run_production_smoke(Path(td), steps=args.steps)
    elif args.preflight:
        result = {"schema": "ember-factor1-preflight-v1", "shape": exact_shape_manifest(), "preflight": preflight_exact_scale(_resource_snapshot()), "identity": source_identity()}
    else:
        print("F1NATIVE_REFUSED: use --selftest, --smoke, or --preflight")
        return 2
    encoded = json.dumps(result, sort_keys=True, indent=2) + "\n"
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(encoded, encoding="utf-8", newline="\n")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
