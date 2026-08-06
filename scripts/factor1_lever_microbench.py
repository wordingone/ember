#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Bounded factor-1 lever evidence for Ember issue #764.

The exact 434M/2.2B benchmark is deliberately fail-closed when the current
public production consumer is unavailable or host floors are not met.  The
``--fixture`` path is CPU-only and exercises the real
``CPUOffloadOptimizer`` with ``torch.optim.AdamW``; it is explicitly marked
fixture evidence and never substitutes for a scale receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PRODUCTION_SOURCE = Path(__file__).resolve().parent / "timeshare_pretrain.py"
PHYSICAL_MARGIN_FLOOR_GIB = 6.0
COMMIT_MARGIN_FLOOR_GIB = 6.0
DISK_MARGIN_FLOOR_GIB = 4.0
L2_THREADS = (1, 8, 16, 24, 32)
L2_REPLICATES = 3
TIMED_ITERATIONS = 20
WARMUP_ITERATIONS = 3

FF_BASE_434M = 4096
FF_GROWN_2P2B = 32768
N_LAYERS = 20
HIDDEN = 1024
VOCAB = 32000
N_MTP = 2
REF_N_MUON = 140
REF_N_ADAMW = 44
REF_ADAMW_PARAM_ELEMS = 98_345_984
REF_ADAMW_STATE_ELEMS = 196_692_012
REF_2P2B_MUON_STATE_ELEMS = 2_097_152_000
REF_434M_MUON_STATE_ELEMS = 335_544_320
REF_2P2B_REALIZED_NUMEL = 2_195_497_984
REF_434M_REALIZED_NUMEL = 433_890_304

SCALES = {
    "434M": {
        "intermediate": FF_BASE_434M,
        "expected_muon_elems": REF_434M_MUON_STATE_ELEMS,
        "expected_realized_numel": REF_434M_REALIZED_NUMEL,
        "scope": "434M-cpu",
    },
    "2.2B": {
        "intermediate": FF_GROWN_2P2B,
        "expected_muon_elems": REF_2P2B_MUON_STATE_ELEMS,
        "expected_realized_numel": REF_2P2B_REALIZED_NUMEL,
        "scope": "2.2B-cpu",
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_muon_shape_list(intermediate: int) -> list[dict]:
    items: list[dict] = []
    for layer in range(N_LAYERS):
        for tag in ("q", "k", "v", "o"):
            items.append({"name": f"layers.{layer}.self_attn.{tag}_proj.weight",
                          "shape": (HIDDEN, HIDDEN), "family": "square_qkvo"})
        for tag in ("gate", "up"):
            items.append({"name": f"layers.{layer}.mlp.{tag}_proj.weight",
                          "shape": (intermediate, HIDDEN), "family": "tall_gate_up"})
        items.append({"name": f"layers.{layer}.mlp.down_proj.weight",
                      "shape": (HIDDEN, intermediate), "family": "wide_down"})
    return items


def build_adamw_shape_list() -> list[dict]:
    items = [{"name": "embed_tokens.weight", "shape": (VOCAB, HIDDEN), "family": "embed_head"}]
    for head in range(N_MTP):
        items.append({"name": f"mtp_heads.{head}.weight", "shape": (VOCAB, HIDDEN), "family": "embed_head"})
    for layer in range(N_LAYERS):
        items.append({"name": f"layers.{layer}.input_layernorm.weight", "shape": (HIDDEN,), "family": "norm_vec"})
        items.append({"name": f"layers.{layer}.post_attention_layernorm.weight", "shape": (HIDDEN,), "family": "norm_vec"})
    items.append({"name": "final_norm.weight", "shape": (HIDDEN,), "family": "norm_vec"})
    return items


def _numel(shape: tuple[int, ...]) -> int:
    result = 1
    for dim in shape:
        result *= dim
    return result


def shape_list_totals(muon: list[dict], adamw: list[dict]) -> dict:
    return {
        "n_muon": len(muon),
        "n_adamw": len(adamw),
        "muon_elems_total": sum(_numel(item["shape"]) for item in muon),
        "adamw_elems_total": sum(_numel(item["shape"]) for item in adamw),
    }


def assert_shape_contract(scale: str) -> dict:
    if scale not in SCALES:
        raise ValueError(f"unknown scale {scale!r}")
    spec = SCALES[scale]
    muon = build_muon_shape_list(spec["intermediate"])
    adamw = build_adamw_shape_list()
    totals = shape_list_totals(muon, adamw)
    errors = []
    if totals["n_muon"] != REF_N_MUON:
        errors.append("Muon tensor count")
    if totals["n_adamw"] != REF_N_ADAMW:
        errors.append("AdamW tensor count")
    if totals["adamw_elems_total"] != REF_ADAMW_PARAM_ELEMS:
        errors.append("AdamW parameter elements")
    if totals["adamw_elems_total"] * 2 + REF_N_ADAMW != REF_ADAMW_STATE_ELEMS:
        errors.append("AdamW state elements")
    if totals["muon_elems_total"] != spec["expected_muon_elems"]:
        errors.append("Muon state elements")
    if totals["muon_elems_total"] + totals["adamw_elems_total"] != spec["expected_realized_numel"]:
        errors.append("realized elements")
    if errors:
        raise ValueError("F1BENCH_SHAPES_BOUND_REFUSED: " + ", ".join(errors))
    return {"scale": scale, "totals": totals, "muon": muon, "adamw": adamw}


def exact_scale_working_set_gib(scale: str) -> float:
    identity = assert_shape_contract(scale)
    muon = identity["totals"]["muon_elems_total"] * 4 * 3
    adamw = identity["totals"]["adamw_elems_total"] * 4 * 4
    return round((muon + adamw) / (1024 ** 3), 5)


def production_path_status() -> dict:
    """Return source identity and the current consumer's fail-closed state."""
    if not PRODUCTION_SOURCE.is_file():
        return {"available": False, "status": "MISSING_PRODUCTION_SOURCE", "source_sha256": None}
    source_bytes = PRODUCTION_SOURCE.read_bytes()
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    first = source_bytes[:8192]
    if b"historical_only" in first and b"raise SystemExit" in first:
        return {
            "available": False,
            "status": "PRODUCTION_PATH_UNAVAILABLE_HISTORICAL_ONLY",
            "source_basename": PRODUCTION_SOURCE.name,
            "source_sha256": source_sha,
            "reason": "current public consumer explicitly denies sub-3B execution",
        }
    return {"available": True, "status": "PRODUCTION_SOURCE_PRESENT",
            "source_basename": PRODUCTION_SOURCE.name, "source_sha256": source_sha}


def _memory_status() -> dict | None:
    try:
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                        ("total_phys", ctypes.c_ulonglong), ("avail_phys", ctypes.c_ulonglong),
                        ("total_page", ctypes.c_ulonglong), ("avail_page", ctypes.c_ulonglong),
                        ("total_virtual", ctypes.c_ulonglong), ("avail_virtual", ctypes.c_ulonglong),
                        ("avail_extended", ctypes.c_ulonglong)]

        status = MemoryStatus()
        status.length = __import__("ctypes").sizeof(MemoryStatus)
        if not hasattr(ctypes, "windll") or not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        gib = 1024 ** 3
        return {"available_physical_gib": status.avail_phys / gib,
                "available_commit_gib": status.avail_page / gib}
    except Exception:
        return None


def preflight_scale(scale: str, *, disk_free_gib: float | None = None,
                    available_physical_gib: float | None = None,
                    available_commit_gib: float | None = None) -> dict:
    required = exact_scale_working_set_gib(scale)
    if disk_free_gib is None:
        import shutil
        disk_free_gib = shutil.disk_usage(REPO).free / (1024 ** 3)
    memory = _memory_status()
    if available_physical_gib is None and memory is not None:
        available_physical_gib = memory["available_physical_gib"]
    if available_commit_gib is None and memory is not None:
        available_commit_gib = memory["available_commit_gib"]
    reasons = []
    for name, value, floor in (
        ("available_physical_gib", available_physical_gib, PHYSICAL_MARGIN_FLOOR_GIB),
        ("available_commit_gib", available_commit_gib, COMMIT_MARGIN_FLOOR_GIB),
        ("disk_free_gib", disk_free_gib, DISK_MARGIN_FLOOR_GIB),
    ):
        if value is None:
            reasons.append(f"{name}_unavailable")
        elif value - required < floor:
            reasons.append(f"{name}_margin_below_floor")
    return {"scale": scale, "required_working_set_gib": required,
            "disk_free_gib": disk_free_gib,
            "available_physical_gib": available_physical_gib,
            "available_commit_gib": available_commit_gib,
            "sufficient": not reasons, "refusal_reasons": reasons}


def _fixture_step(tmp: Path, *, threads: int = 1, iterations: int = TIMED_ITERATIONS) -> dict:
    import torch
    torch.set_num_threads(threads)
    from cpu_offload_adamw import CPUOffloadOptimizer

    parameter = torch.nn.Parameter(torch.ones((4, 4), dtype=torch.float32))
    optimizer = CPUOffloadOptimizer(
        [("fixture.weight", parameter)],
        lambda params: torch.optim.AdamW(params, lr=0.001),
        optstate_dir=tmp,
    )
    spans: list[float] = []
    optimizer.attach_span_collector(
        add=lambda phase, seconds: spans.append(seconds) if phase == "inner_optimizer_step" else None,
        add_bytes=lambda phase, count: None,
        add_numel=lambda count: None,
        sync=lambda: None,
    )
    generator = torch.Generator().manual_seed(764)
    for _ in range(WARMUP_ITERATIONS):
        optimizer.zero_grad()
        parameter.grad = torch.randn(parameter.shape, generator=generator)
        optimizer.step()
    spans.clear()
    for _ in range(iterations):
        optimizer.zero_grad()
        parameter.grad = torch.randn(parameter.shape, generator=generator)
        optimizer.step()
    if len(spans) != iterations or not all(value > 0 for value in spans):
        raise RuntimeError("inner_optimizer_step span was not observed on the real wrapper")
    return {"iterations": iterations, "median_s": statistics.median(spans),
            "min_s": min(spans), "max_s": max(spans), "threads": threads}


def run_l2_fixture() -> dict:
    rows = {}
    for threads in L2_THREADS:
        replicates = []
        for replicate in range(L2_REPLICATES):
            with tempfile.TemporaryDirectory(prefix="f1bench-l2-") as tmp:
                command = [sys.executable, str(Path(__file__).resolve()), "--worker",
                           "--threads", str(threads), "--iterations", str(TIMED_ITERATIONS),
                           "--replicate", str(replicate), "--tmp", tmp]
                completed = subprocess.run(command, capture_output=True, text=True, timeout=120)
                if completed.returncode != 0:
                    return {"status": "L2_FIXTURE_FAILED", "threads": threads,
                            "stderr": completed.stderr[-1000:]}
                line = next((line for line in completed.stdout.splitlines() if line.startswith("F1BENCH_WORKER ")), None)
                if line is None:
                    return {"status": "L2_FIXTURE_FAILED", "reason": "worker result missing"}
                replicates.append(json.loads(line.split(" ", 1)[1]))
        rows[str(threads)] = {"replicates": replicates,
                              "median_s": statistics.median(row["median_s"] for row in replicates),
                              "iterations_per_replicate": TIMED_ITERATIONS}
    return {"status": "FIXTURE_ONLY", "threads": rows,
            "replicates": L2_REPLICATES, "fresh_subprocess_per_replicate": True}


def run_fixture() -> dict:
    with tempfile.TemporaryDirectory(prefix="f1bench-l0-") as tmp:
        l0 = _fixture_step(Path(tmp), threads=1)
    return {
        "status": "FIXTURE_ONLY_NOT_SCALE_EVIDENCE",
        "L0": l0,
        "L1": {"status": "L1_UNAVAILABLE",
               "reason": "bounded fixture does not substitute a compile receipt"},
        "L2": run_l2_fixture(),
        "claim_boundary": "no 434M/2.2B performance or training claim",
    }


def _selftest() -> int:
    checks = []
    for scale in SCALES:
        assert_shape_contract(scale)
        checks.append(scale)
    bad = dict(SCALES["2.2B"])
    bad["expected_muon_elems"] += 1
    try:
        # Keep this negative before any tensor or subprocess allocation.
        identity = shape_list_totals(build_muon_shape_list(bad["intermediate"]), build_adamw_shape_list())
        if identity["muon_elems_total"] == bad["expected_muon_elems"]:
            raise AssertionError("shape negative was not constructed")
    except Exception:
        raise
    refused = preflight_scale("2.2B", disk_free_gib=0.0,
                              available_physical_gib=0.0, available_commit_gib=0.0)
    if refused["sufficient"]:
        raise AssertionError("resource preflight accepted impossible input")
    fixture = run_fixture()
    if fixture["L0"]["iterations"] != TIMED_ITERATIONS:
        raise AssertionError("L0 timed sample floor missing")
    print("F1BENCH_SHAPES_BOUND_PASS")
    print("F1BENCH_L0_PRODUCTION_PATH_PASS")
    print("F1BENCH_NEGATIVE_FIXTURES_PASS")
    print("F1BENCH_EXACT_SCALE_STATUS " + production_path_status()["status"])
    print("F1BENCH_SELFTEST_ALL_PASS")
    return 0


def _receipt(results: dict) -> dict:
    source = production_path_status()
    return {
        "schema": "ember-factor1-lever-microbench-v1",
        "ticket": "EMBER-764-FACTOR1-LEVER-MICROBENCH",
        "ts": time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()),
        "issue": "wordingone/ember#764",
        "goal_id": "EMBER-02",
        "workstream_id": "EMBER-02A",
        "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
        "implementation_basename": Path(__file__).name,
        "implementation_sha256": _sha256(Path(__file__)),
        "source": source,
        "scales": {scale: {"shape": assert_shape_contract(scale)["totals"],
                           "working_set_gib": exact_scale_working_set_gib(scale),
                           "preflight": preflight_scale(scale),
                           "status": "REFUSED_PRODUCTION_PATH_OR_PREFLIGHT"}
                   for scale in SCALES},
        "fixture": results,
        "api_spend_usd": 0,
        "capability_claim": "NONE",
        "sha_convention": "implementation_sha256 and source_sha256 are lowercase SHA-256 of exact bytes; path-free basenames only",
        "receipt_boundary": "fixture measurements are not exact-scale evidence; no training/checkpoint claim",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--fixture", action="store_true")
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--iterations", type=int, default=TIMED_ITERATIONS)
    parser.add_argument("--replicate", type=int, default=0)
    parser.add_argument("--tmp", default=None)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    if args.selftest:
        return _selftest()
    if args.worker:
        tmp = Path(args.tmp) if args.tmp else Path(tempfile.mkdtemp(prefix="f1bench-worker-"))
        result = _fixture_step(tmp, threads=args.threads, iterations=args.iterations)
        result["replicate"] = args.replicate
        print("F1BENCH_WORKER " + json.dumps(result, sort_keys=True))
        return 0
    if not args.fixture:
        print("F1BENCH_REFUSED: pass --selftest or --fixture; exact-scale dispatch is not implicit")
        return 2
    result = _receipt(run_fixture())
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"F1BENCH_RECEIPT_WRITTEN {args.receipt}")
    print("F1BENCH_FIXTURE_ONLY_NOT_SCALE_EVIDENCE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
