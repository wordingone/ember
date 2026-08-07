#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Exact current-native CPU L0-L2 evidence for #764."""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any

from scripts import factor1_702_attribution_runner as attribution
from scripts import factor1_cpuoffload_producer as producer
from scripts import factor1_lever_microbench as microbench

WARMUP_STEPS = 3
ACTIVE_STEPS = 20
L2_THREADS = (1, 8, 16, 24, 32)
L2_REPLICATES = 3
PHASES = attribution.PHASES


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _rss_bytes() -> int | None:
    try:
        import psutil
        return int(psutil.Process(os.getpid()).memory_info().rss)
    except Exception:
        return None


def _rows(scale: str) -> list[dict[str, Any]]:
    if scale == producer.EXACT_SCALE:
        return list(producer._shape_rows())
    if scale == "434M":
        muon = microbench.build_muon_shape_list(microbench.FF_BASE_434M)
        adamw = microbench.build_adamw_shape_list()
        return ([{"name": x["name"], "shape": list(x["shape"]), "optimizer": "muon"} for x in muon]
                + [{"name": x["name"], "shape": list(x["shape"]), "optimizer": "adamw"} for x in adamw])
    raise ValueError("scale must be 434M or 2.2B")


def _build(root: Path, scale: str):
    import torch
    from scripts.cpu_offload_adamw import CPUOffloadOptimizer
    rows = _rows(scale)
    params = [(x["name"], torch.nn.Parameter(torch.zeros(tuple(x["shape"]), dtype=torch.float32))) for x in rows]
    adam_params = [(n, p) for (n, p), x in zip(params, rows) if x["optimizer"] == "adamw"]
    muon_params = [(n, p) for (n, p), x in zip(params, rows) if x["optimizer"] == "muon"]
    adam = CPUOffloadOptimizer(adam_params, lambda ps: torch.optim.AdamW(ps, lr=3e-4, weight_decay=0.1), optstate_dir=root / "adamw")
    muon = CPUOffloadOptimizer(muon_params, lambda ps: producer._muon_class()(ps, lr=0.02, momentum=0.95), optstate_dir=root / "muon")
    return params, adam, muon


def _one_run(root: Path, *, scale: str, threads: int, collect: bool, warmup: int, active: int) -> dict[str, Any]:
    import torch
    torch.set_num_threads(threads)
    params, adam, muon = _build(root, scale)
    spans = {n: {p: {"seconds": [], "bytes": [], "numel": []} for p in PHASES} for n in ("adamw", "muon")}
    current = {n: None for n in ("adamw", "muon")}
    def begin(name: str):
        current[name] = {p: {"seconds": 0.0, "bytes": 0, "numel": 0} for p in PHASES}
    def add(name: str, phase: str, seconds: float):
        if current[name] is None:
            raise RuntimeError("span arrived outside an active sample")
        current[name][phase]["seconds"] += float(seconds)
    def add_bytes(name: str, phase: str, count: int):
        if current[name] is None:
            raise RuntimeError("byte span arrived outside an active sample")
        current[name][phase]["bytes"] += int(count)
    def add_numel(name: str, count: int):
        if current[name] is None:
            raise RuntimeError("numel span arrived outside an active sample")
        current[name]["grad_to_cpu_fp32"]["numel"] += int(count)
    def finish(name: str):
        row = current[name]
        if row is None:
            raise RuntimeError("span finish without an active sample")
        for phase in PHASES:
            spans[name][phase]["seconds"].append(row[phase]["seconds"])
            spans[name][phase]["bytes"].append(row[phase]["bytes"])
            spans[name][phase]["numel"].append(row[phase]["numel"])
        current[name] = None
    if collect:
        for name, opt in (("adamw", adam), ("muon", muon)):
            opt.attach_span_collector(add=lambda p, s, n=name: add(n, p, s), add_bytes=lambda p, c, n=name: add_bytes(n, p, c), add_numel=lambda c, n=name: add_numel(n, c), sync=lambda: None)
        begin("adamw"); begin("muon")
    for _ in range(warmup):
        for _, parameter in params:
            parameter.grad = torch.ones_like(parameter)
        adam.step(); muon.step()
        if collect:
            finish("adamw"); finish("muon"); begin("adamw"); begin("muon")
    wall = []; cpu = []; rss = []
    for _ in range(active):
        if collect:
            if current["adamw"] is None: begin("adamw")
            if current["muon"] is None: begin("muon")
        for _, parameter in params:
            parameter.grad = torch.ones_like(parameter)
        t0, c0 = time.perf_counter(), time.process_time()
        adam.step(); muon.step()
        wall.append(time.perf_counter() - t0); cpu.append(time.process_time() - c0); rss.append(_rss_bytes())
        if collect:
            finish("adamw"); finish("muon")
    result = {"scale": scale, "threads": threads, "warmup_steps": warmup, "active_steps": active,
              "wall_seconds": [round(x, 9) for x in wall], "cpu_seconds": [round(x, 9) for x in cpu],
              "wall_median_seconds": round(statistics.median(wall), 9), "cpu_median_seconds": round(statistics.median(cpu), 9),
              "rss_bytes": {"first": next((x for x in rss if x is not None), None), "peak": max((x for x in rss if x is not None), default=None)},
              "torch_num_threads": torch.get_num_threads(), "spans": spans if collect else None,
              "transfer_bytes": ({n: {p: sum(v["bytes"]) for p, v in phases.items()} for n, phases in spans.items()} if collect else None)}
    del params, adam, muon
    gc.collect()
    return result


def _compile_probe() -> dict[str, Any]:
    try:
        import torch
        if not hasattr(torch, "compile"):
            return {"status": "UNAVAILABLE", "reason": "torch.compile missing"}
        def inner(x):
            return x * x + 1
        if torch.compile(inner, backend="eager")(torch.ones(2)).tolist() != [2.0, 2.0]:
            raise ValueError("compiled probe mismatch")
        return {"status": "PROBE_PASS", "production_optimizer_step_compiled": False, "reason": "CPUOffloadOptimizer.step is Python/memmap-bound; probe is not L1 production evidence"}
    except Exception as exc:
        return {"status": "UNAVAILABLE", "reason": type(exc).__name__ + ": " + str(exc)[:240]}


def run_exact(root: Path, *, scale: str, execute: bool, warmup: int = WARMUP_STEPS, active: int = ACTIVE_STEPS, l2_replicates: int = L2_REPLICATES) -> dict[str, Any]:
    if not execute:
        raise PermissionError("exact CPU L0-L2 requires --execute")
    if warmup < 3 or active < 20 or l2_replicates < 1:
        raise ValueError("requires warmup >=3, active >=20, and one or more L2 replicates")
    root = Path(root).resolve(); root.mkdir(parents=True, exist_ok=True)
    snapshot = producer._resource_snapshot()
    gate = producer.preflight_exact_scale(snapshot) if scale == producer.EXACT_SCALE else {"scale": scale, "sufficient": True, "observed": snapshot, "refusal_reasons": []}
    if not gate["sufficient"]:
        raise RuntimeError("CPU exact preflight refused: " + "; ".join(gate["refusal_reasons"]))
    with tempfile.TemporaryDirectory(prefix="l0-control-", dir=root) as td:
        control = _one_run(Path(td), scale=scale, threads=1, collect=False, warmup=warmup, active=active)
    with tempfile.TemporaryDirectory(prefix="l0-profile-", dir=root) as td:
        profile = _one_run(Path(td), scale=scale, threads=1, collect=True, warmup=warmup, active=active)
    l2 = {}
    for threads in L2_THREADS:
        rows = []
        for replicate in range(l2_replicates):
            with tempfile.TemporaryDirectory(prefix=f"l2-{threads}-{replicate}-", dir=root) as td:
                rows.append(_one_run(Path(td), scale=scale, threads=threads, collect=True, warmup=warmup, active=active))
        l2[str(threads)] = {"replicates": rows, "median_seconds": statistics.median(x["wall_median_seconds"] for x in rows)}
    return {"schema": "ember-764-exact-cpu-l0-l2-v1", "issue": "wordingone/ember#764", "scale": scale,
            "warmup_steps": warmup, "active_steps": active, "l0_control_unprofiled": control, "l0_profiled": profile,
            "l1_torch_compile": _compile_probe(), "l2_thread_sweep": l2, "preflight": gate,
            "source_identity": {"runner_basename": Path(__file__).name, "runner_sha256": _sha256(Path(__file__)), "producer_sha256": _sha256(Path(producer.__file__).resolve()), "optimizer_sha256": _sha256(producer.CPU_OFFLOAD_SOURCE.resolve())},
            "controls": {"matched_unprofiled_control": True, "warmup_active_windows": True, "host_wall_and_process_counters": True, "transfer_bytes_from_production_hooks": True, "tenancy": "CPU_ONLY_GPU_NOT_COLLECTED"},
            "claim_boundary": {"gpu": False, "training": False, "capability": False, "issue_764_completion": False, "issue_702_completion": False},
            "verdict": "CPU_L0_L2_EXECUTED_NONTERMINAL_PENDING_GPU_L3_AND_CURE_A_B"}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(); p.add_argument("--optstate-dir", type=Path, required=True); p.add_argument("--scale", choices=("434M", producer.EXACT_SCALE), required=True); p.add_argument("--output", type=Path, required=True); p.add_argument("--warmup", type=int, default=WARMUP_STEPS); p.add_argument("--active", type=int, default=ACTIVE_STEPS); p.add_argument("--l2-replicates", type=int, default=L2_REPLICATES); p.add_argument("--execute", action="store_true"); args = p.parse_args(argv)
    result = run_exact(args.optstate_dir, scale=args.scale, execute=args.execute, warmup=args.warmup, active=args.active, l2_replicates=args.l2_replicates)
    args.output.parent.mkdir(parents=True, exist_ok=True); raw = (json.dumps(result, indent=2, sort_keys=True) + "\n").encode(); tmp = args.output.with_name("." + args.output.name + ".tmp"); tmp.write_bytes(raw); os.replace(tmp, args.output); print(json.dumps({"status": "PASS", "scale": args.scale, "output": args.output.name}, sort_keys=True)); return 0

if __name__ == "__main__":
    raise SystemExit(main())
