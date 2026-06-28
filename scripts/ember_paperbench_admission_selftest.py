#!/usr/bin/env python3
"""Selftest for PaperBench admission receipts."""
from __future__ import annotations

import tempfile
from pathlib import Path

import ember_paperbench_admission as paperbench


def _fake_frontier(root: Path, *, with_root_pyproject: bool = False) -> Path:
    (root / ".git").mkdir(parents=True)
    (root / "README.md").write_text("# Frontier Evals\nPaperBench\n", encoding="utf-8")
    (root / "LICENSE.md").write_text("MIT License\n", encoding="utf-8")
    if with_root_pyproject:
        (root / "pyproject.toml").write_text("[project]\nname = 'frontier-evals'\n", encoding="utf-8")
    pb = root / "project" / "paperbench"
    pb.mkdir(parents=True)
    (pb / "README.md").write_text(
        "# PaperBench\n20 ICML papers and 8316 gradable tasks\nuv sync\ngit lfs fetch\nDocker\nGPU\nOPENAI_API_KEY\n",
        encoding="utf-8",
    )
    (pb / "data" / "judge_eval").mkdir(parents=True)
    return root


def _write_paper_dirs(root: Path, count: int, *, pointer_pdf: bool = False) -> None:
    papers = root / "project" / "paperbench" / "data" / "papers"
    for i in range(count):
        paper = papers / f"paper-{i:02d}"
        paper.mkdir(parents=True)
        (paper / "addendum.md").write_text("addendum\n", encoding="utf-8")
        (paper / "paper.md").write_text("paper markdown\n", encoding="utf-8")
        if pointer_pdf:
            (paper / "paper.pdf").write_text(
                "version https://git-lfs.github.com/spec/v1\n"
                "oid sha256:0000000000000000000000000000000000000000000000000000000000000000\n"
                "size 123456\n",
                encoding="utf-8",
            )
        else:
            (paper / "paper.pdf").write_bytes(b"%PDF-1.7\nsynthetic selftest pdf bytes\n")


def test_blocks_when_paperbench_runtime_files_are_missing() -> None:
    with tempfile.TemporaryDirectory(prefix="paperbench-admission-") as td:
        root = _fake_frontier(Path(td) / "frontier-evals")
        out = Path(td) / "receipt.json"
        receipt = paperbench.build_admission_receipt(repo=Path.cwd(), frontier_root=root, out=out)
        assert receipt["verdict"] == "PAPERBENCH_BLOCKED"
        assert "paperbench_project_incomplete" in receipt["blocked_reasons"]
        assert "paperbench_data_lfs_not_hydrated" in receipt["blocked_reasons"]
        assert receipt["native_operator_routing"]["selected"] == "paperbench"
        assert receipt["deleted_selector_routing"]["admission_state"] == "ROUTING_BLOCKED_DELETED_SELECTOR"
        assert receipt["next_benchmark_if_blocked"]["selected"] == "broader-d3-multifamily"
        assert out.exists()


def test_blocks_partial_lfs_hydration() -> None:
    with tempfile.TemporaryDirectory(prefix="paperbench-admission-") as td:
        root = _fake_frontier(Path(td) / "frontier-evals", with_root_pyproject=True)
        _write_paper_dirs(root, 7)
        receipt = paperbench.build_admission_receipt(repo=Path.cwd(), frontier_root=root, out=Path(td) / "receipt.json")
        assert receipt["verdict"] == "PAPERBENCH_BLOCKED"
        assert "paperbench_data_partial" in receipt["blocked_reasons"]
        assert receipt["data_hydration_metrics"]["paper_dir_count"] == 7
        assert not receipt["protected_data_boundaries"]["data_lfs_hydrated"]


def test_blocks_lfs_pointer_substitution() -> None:
    with tempfile.TemporaryDirectory(prefix="paperbench-admission-") as td:
        root = _fake_frontier(Path(td) / "frontier-evals", with_root_pyproject=True)
        _write_paper_dirs(root, paperbench.EXPECTED_PAPER_COUNT, pointer_pdf=True)
        receipt = paperbench.build_admission_receipt(repo=Path.cwd(), frontier_root=root, out=Path(td) / "receipt.json")
        assert receipt["verdict"] == "PAPERBENCH_BLOCKED"
        assert "paperbench_data_lfs_pointer_files" in receipt["blocked_reasons"]
        assert receipt["data_hydration_metrics"]["lfs_pointer_file_count"] == paperbench.EXPECTED_PAPER_COUNT


def test_admits_minimal_hydrated_synthetic_paperbench() -> None:
    with tempfile.TemporaryDirectory(prefix="paperbench-admission-") as td:
        root = _fake_frontier(Path(td) / "frontier-evals", with_root_pyproject=True)
        _write_paper_dirs(root, paperbench.EXPECTED_PAPER_COUNT)
        receipt = paperbench.build_admission_receipt(repo=Path.cwd(), frontier_root=root, out=Path(td) / "receipt.json")
        assert receipt["verdict"] == "PAPERBENCH_ADMITTED"
        assert receipt["blocked_reasons"] == []
        assert receipt["data_hydration_metrics"]["hydration_ready"]
        assert receipt["protected_data_boundaries"]["data_lfs_hydrated"]


def main() -> int:
    test_blocks_when_paperbench_runtime_files_are_missing()
    test_blocks_partial_lfs_hydration()
    test_blocks_lfs_pointer_substitution()
    test_admits_minimal_hydrated_synthetic_paperbench()
    print("EMBER_PAPERBENCH_ADMISSION_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())