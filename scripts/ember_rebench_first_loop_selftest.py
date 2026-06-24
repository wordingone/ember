#!/usr/bin/env python3
"""Selftest for RE-Bench first-loop preflight receipts."""
from __future__ import annotations

import tempfile
from pathlib import Path

import ember_rebench_first_loop as first_loop


def _fake_task(root: Path) -> Path:
    task = root / "ai_rd_rust_codecontests_inference"
    task.mkdir(parents=True)
    (task / "README.md").write_text("# Build scaffolding for Rust Codecontests\n", encoding="utf-8")
    (task / "manifest.yaml").write_text(
        """version: 0.2.3
meta:
  name: Build scaffolding for Rust Codecontests
tasks:
  main:
    resources:
      cpus: 20
      memory_gb: 100
    scoring:
      visible_to_agent: true
      score_on_usage_limits: true
""",
        encoding="utf-8",
    )
    (task / "build_steps.json").write_text("[]", encoding="utf-8")
    (task / "official_solution.zip").write_bytes(b"protected")
    return task


def test_blocked_receipt_names_missing_runtime_and_preserves_next_route() -> None:
    with tempfile.TemporaryDirectory(prefix="rebench-first-loop-") as td:
        root = Path(td) / "repo"
        task = _fake_task(root)
        out = Path(td) / "receipt.json"
        preflight = first_loop.evaluate_preflight(
            task_dir=task,
            env={"AI_RD_RUST_CODECONTESTS_INFERENCE_OPENAI_API_KEY": ""},
            module_available=lambda _name: False,
            which=lambda name: "<local-path>" + name if name in {"rustc", "cargo", "docker"} else None,
            cpu_count=lambda: 8,
            memory_gb=lambda: 32,
        )
        receipt = first_loop.build_receipt(repo=Path.cwd(), task_family="ai_rd_rust_codecontests_inference", task_dir=task, out=out, preflight=preflight)
        assert receipt["verdict"] == "REBENCH_FIRST_LOOP_BLOCKED"
        assert "task_standard_runtime_missing" in receipt["blocked_reasons"]
        assert "task_openai_key_missing" in receipt["blocked_reasons"]
        assert "resource_envelope_insufficient" in receipt["blocked_reasons"]
        assert receipt["protected_solution_handling"]["extracted_protected_solutions"] is False
        assert receipt["deleted_selector_routing"]["admission_state"] == "ROUTING_BLOCKED_DELETED_SELECTOR"
        assert receipt["next_benchmark_if_unfixable"]["selected"] == "paperbench"
        assert out.exists()

def test_default_missing_metr_module_probe_does_not_raise() -> None:
    with tempfile.TemporaryDirectory(prefix="rebench-first-loop-") as td:
        root = Path(td) / "repo"
        task = _fake_task(root)
        preflight = first_loop.evaluate_preflight(
            task_dir=task,
            env={"AI_RD_RUST_CODECONTESTS_INFERENCE_OPENAI_API_KEY": "present"},
            which=lambda name: "<local-path>" + name,
            cpu_count=lambda: 32,
            memory_gb=lambda: 128,
        )
        assert "task_standard_runtime_missing" in preflight["blocked_reasons"]

def main() -> int:
    test_blocked_receipt_names_missing_runtime_and_preserves_next_route()
    test_default_missing_metr_module_probe_does_not_raise()
    print("EMBER_REBENCH_FIRST_LOOP_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())