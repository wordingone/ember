#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Selftest for RE-Bench admission receipt generation."""
from __future__ import annotations

import tempfile
from pathlib import Path

import ember_rebench_admission as rebench


def _write_fake_rebench(root: Path) -> None:
    (root / ".git").mkdir()
    (root / "README.md").write_text("# RE-Bench\n\nAI R&D tasks\n", encoding="utf-8")
    (root / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    (root / "suite_manifest.yaml").write_text(
        """task_families:
  ai_rd_rust_codecontests_inference:
    version: 0.2.3
    tasks:
    - main
  ai_rd_fix_embedding:
    version: 0.2.5
    tasks:
    - main
  ai_rd_triton_cumsum:
    version: 0.2.5
    tasks:
    - main
""",
        encoding="utf-8",
    )
    for family, name, canary, resources in [
        ("ai_rd_rust_codecontests_inference", "Build scaffolding", "ghi", "cpus: 20\n      memory_gb: 100"),
        ("ai_rd_fix_embedding", "Fix Embedding", "abc", "model: h100\n      cpus: 13\n      memory_gb: 100"),
        ("ai_rd_triton_cumsum", "Optimize kernel", "def", "model: h100\n      cpus: 8\n      memory_gb: 64"),
    ]:
        task = root / family
        task.mkdir()
        (task / "README.md").write_text(
            f"# {name}\n\nStarting score: 0.1\nOfficial solution score: 0.9\nUse the score action.\n",
            encoding="utf-8",
        )
        (task / "manifest.yaml").write_text(
            f"""version: 0.2.5
meta:
  name: {name}
  expertise:
  - machine_learning
  canary: {canary}
tasks:
  main:
    scoring:
      visible_to_agent: false
      score_on_usage_limits: true
    resources:
      gpu:
        count_range:
        - 1
        - 1
        {resources}
    meta:
      scoring:
        manual: false
        intermediate: true
      task_description: public task summary only
""",
            encoding="utf-8",
        )
        (task / "official_solution.zip").write_bytes(b"encrypted-or-protected")


def test_admission_freezes_public_metadata_and_excludes_protected_solution_contents() -> None:
    with tempfile.TemporaryDirectory(prefix="rebench-admission-") as td:
        root = Path(td) / "repo"
        root.mkdir()
        _write_fake_rebench(root)
        out = Path(td) / "receipt.json"
        receipt = rebench.build_admission_receipt(repo=Path.cwd(), rebench_root=root, out=out)
        assert receipt["verdict"] == "REBENCH_ADMITTED"
        assert receipt["benchmark_facts"]["task_families"] == 3
        assert receipt["protected_solution_handling"]["extracted_protected_solutions"] is False
        assert receipt["protected_solution_handling"]["protected_solution_files"] == 3
        assert "encrypted-or-protected" not in out.read_text(encoding="utf-8")
        assert receipt["frozen_heldout_slice"]["rows"][0]["id"] == "ai_rd_rust_codecontests_inference"
        assert receipt["native_operator_routing"]["selected"] == "re-bench"
        assert receipt["deleted_selector_routing"]["admission_state"] == "ROUTING_BLOCKED_DELETED_SELECTOR"
        assert receipt["deletion_sensitive"] is True
        assert "--task-family ai_rd_rust_codecontests_inference" in receipt["next_executable_command"]


def main() -> int:
    test_admission_freezes_public_metadata_and_excludes_protected_solution_contents()
    print("EMBER_REBENCH_ADMISSION_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())