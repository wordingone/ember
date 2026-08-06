#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Current-native, fail-closed #702 optimizer attribution runner.

This is the execution mechanism the historical ``cbase`` attribution script
does not provide.  It uses the checked-in ``CPUOffloadOptimizer`` wrapper and
its production span hooks, runs a matched unprofiled/profiled pair, and
records every named optimizer subphase.  A receipt is evidence only: source
identity, tenancy, and the full #702 contract remain explicit fields and no
claim is promoted when a required proof is absent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from scripts import factor1_cpuoffload_producer as producer


GOAL_ID = "EMBER-02"
WORKSTREAM_ID = "EMBER-02A"
NEXT_EXECUTED_OUTCOME = "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
MIN_STEPS = 10
PHASES = (
    "grad_to_cpu_fp32",
    "grad_heap_to_memmap",
    "inner_optimizer_step",
    "updated_param_to_gpu",
)
OPTIMIZERS = ("adamw", "muon")


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{label} must be finite and nonnegative")
    return result


class _StepSpans:
    def __init__(self) -> None:
        self._current: dict[str, dict[str, float]] = {}
        self._steps: list[dict[str, dict[str, float]]] = []

    def begin_step(self) -> None:
        self._current = {phase: {"seconds": 0.0, "bytes": 0.0, "numel": 0.0} for phase in PHASES}

    def add(self, phase: str, seconds: float) -> None:
        if phase not in PHASES:
            raise ValueError(f"unknown attribution phase: {phase}")
        self._current[phase]["seconds"] += _finite(seconds, f"{phase}.seconds")

    def add_bytes(self, phase: str, count: int) -> None:
        if phase not in PHASES or isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError(f"invalid {phase}.bytes")
        self._current[phase]["bytes"] += count

    def add_numel(self, count: int) -> None:
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("invalid span numel")
        # The hooks expose numel without a phase; attach it to the input copy
        # boundary, which is the only phase that consumes it.
        self._current["grad_to_cpu_fp32"]["numel"] += count

    def end_step(self) -> None:
        if not self._current:
            raise RuntimeError("end_step without begin_step")
        self._steps.append({phase: dict(values) for phase, values in self._current.items()})
        self._current = {}

    def encoded(self, steps: int) -> dict[str, Any]:
        if len(self._steps) != steps:
            raise ValueError(f"span sample count {len(self._steps)} != requested {steps}")
        result: dict[str, Any] = {}
        for phase in PHASES:
            series = [step[phase] for step in self._steps]
            result[phase] = {
                "samples": len(series),
                "seconds": [round(item["seconds"], 9) for item in series],
                "bytes": [int(item["bytes"]) for item in series],
                "numel": [int(item["numel"]) for item in series],
                "total_seconds": round(sum(item["seconds"] for item in series), 9),
                "total_bytes": int(sum(item["bytes"] for item in series)),
            }
        return result


def _build_exact(root: Path):
    import torch
    from scripts.cpu_offload_adamw import CPUOffloadOptimizer

    rows = producer._shape_rows()
    params = [
        (row["name"], torch.nn.Parameter(torch.zeros(tuple(row["shape"]), dtype=torch.float32)))
        for row in rows
    ]
    muon_params = [(name, parameter) for (name, parameter), row in zip(params, rows) if row["optimizer"] == "muon"]
    adam_params = [(name, parameter) for (name, parameter), row in zip(params, rows) if row["optimizer"] == "adamw"]
    adam = CPUOffloadOptimizer(
        adam_params,
        lambda ps: torch.optim.AdamW(ps, lr=3e-4, weight_decay=0.1),
        optstate_dir=root / "adamw",
    )
    muon = CPUOffloadOptimizer(
        muon_params,
        lambda ps: producer._muon_class()(ps, lr=0.02, momentum=0.95),
        optstate_dir=root / "muon",
    )
    return params, adam, muon


def _build_tiny(root: Path):
    adam_params, muon_params, adam, muon = producer._build_tiny_production_optimizers(root)
    return adam_params + muon_params, adam, muon


def _run_once(
    root: Path,
    *,
    steps: int,
    builder: Callable[[Path], Any],
    collect: bool,
) -> dict[str, Any]:
    params, adam, muon = builder(root)
    collectors = {name: _StepSpans() for name in OPTIMIZERS}
    if collect:
        for name, optimizer in (("adamw", adam), ("muon", muon)):
            collector = collectors[name]
            optimizer.attach_span_collector(
                add=collector.add,
                add_bytes=collector.add_bytes,
                add_numel=collector.add_numel,
                sync=lambda: None,
            )
    started = time.perf_counter()
    for _ in range(steps):
        if collect:
            collectors["adamw"].begin_step()
            collectors["muon"].begin_step()
        for _, parameter in params:
            parameter.grad = parameter.detach().clone()
        adam.step()
        muon.step()
        if collect:
            collectors["adamw"].end_step()
            collectors["muon"].end_step()
    elapsed = time.perf_counter() - started
    if collect:
        return {
            "elapsed_seconds": round(elapsed, 9),
            "steps": steps,
            "optimizers": {name: collector.encoded(steps) for name, collector in collectors.items()},
        }
    return {"elapsed_seconds": round(elapsed, 9), "steps": steps}


def _validate_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    required = ("available_commit_gib", "available_physical_gib", "disk_free_gib")
    clean = {field: _finite(snapshot.get(field), field) for field in required}
    return clean


def _source_identity() -> dict[str, str]:
    runner = Path(__file__).resolve()
    producer_path = Path(producer.__file__).resolve()
    optimizer_path = producer.CPU_OFFLOAD_SOURCE.resolve()
    return {
        "runner_basename": runner.name,
        "runner_sha256": _sha256_file(runner),
        "producer_basename": producer_path.name,
        "producer_sha256": _sha256_file(producer_path),
        "optimizer_basename": optimizer_path.name,
        "optimizer_sha256": _sha256_file(optimizer_path),
        "hashes_computed_from_current_bytes": True,
    }


def run_attribution(
    optstate_dir: Path,
    snapshot: dict[str, Any],
    *,
    steps: int = MIN_STEPS,
    execute: bool = False,
    scale: str = producer.EXACT_SCALE,
) -> dict[str, Any]:
    """Run a matched CPU attribution pair; refuse all incomplete requests."""
    if not execute:
        raise PermissionError("#702 attribution requires explicit execute=True")
    if isinstance(steps, bool) or not isinstance(steps, int) or steps < MIN_STEPS:
        raise ValueError(f"#702 attribution requires at least {MIN_STEPS} steps")
    observed = _validate_snapshot(snapshot)
    gate = producer.preflight_exact_scale(snapshot)
    if not gate["sufficient"]:
        raise RuntimeError("#702 attribution preflight refused: " + "; ".join(gate["refusal_reasons"]))
    builder = _build_exact if scale == producer.EXACT_SCALE else _build_tiny if scale == "tiny-test" else None
    if builder is None:
        raise ValueError("scale must be 2.2B or tiny-test")
    root = Path(optstate_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="702-baseline-", dir=root) as baseline_dir:
        baseline = _run_once(Path(baseline_dir), steps=steps, builder=builder, collect=False)
    with tempfile.TemporaryDirectory(prefix="702-profiled-", dir=root) as profiled_dir:
        profiled = _run_once(Path(profiled_dir), steps=steps, builder=builder, collect=True)
    overhead = profiled["elapsed_seconds"] / baseline["elapsed_seconds"] if baseline["elapsed_seconds"] else float("inf")
    result = {
        "schema": "ember-702-current-native-attribution-v1",
        "ticket": "EMBER-702-ATTRIBUTION",
        "goal_id": GOAL_ID,
        "workstream_id": WORKSTREAM_ID,
        "next_executed_outcome": NEXT_EXECUTED_OUTCOME,
        "issue": "wordingone/ember#702",
        "scale": scale,
        "steps": steps,
        "preflight": gate,
        "observed_resources": observed,
        "baseline_unprofiled": baseline,
        "profiled": profiled,
        "profile_overhead_ratio": round(overhead, 9) if math.isfinite(overhead) else None,
        "source_identity": _source_identity(),
        "runtime_boundary": {
            "execution_device": "CPU",
            "gpu_telemetry": "NOT_COLLECTED",
            "interval_tenancy": "NOT_PROVEN",
            "server_wsl_persistent_worker": "NOT_PROVEN",
        },
        "claim_boundary": {
            "per_optimizer_spans_present": True,
            "matched_profiled_unprofiled_pair": True,
            "contract_grade_attribution": False,
            "issue_702_completion": False,
            "training_claim": False,
            "model_capability_claim": False,
        },
        "verdict": "CURRENT_NATIVE_ATTRIBUTION_EVIDENCE_NONTERMINAL",
    }
    return result


def _write_atomic(path: Path, value: dict[str, Any]) -> None:
    target = path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--optstate-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--steps", type=int, default=MIN_STEPS)
    parser.add_argument("--snapshot-json", type=Path)
    parser.add_argument("--scale", choices=(producer.EXACT_SCALE, "tiny-test"), default=producer.EXACT_SCALE)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    snapshot = producer._resource_snapshot() if args.snapshot_json is None else json.loads(args.snapshot_json.read_text(encoding="utf-8"))
    result = run_attribution(args.optstate_dir, snapshot, steps=args.steps, execute=args.execute, scale=args.scale)
    if args.output is None:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        _write_atomic(args.output, result)
        print(json.dumps({"status": "PASS", "output": args.output.name}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
