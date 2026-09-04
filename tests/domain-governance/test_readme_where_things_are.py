# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import re
import subprocess
from pathlib import Path, PurePosixPath

import pytest


ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
HEADING = "## Where things are"

EXPECTED_DOMAINS = {
    "Model": "src/ember/model",
    "Data": "src/ember/data",
    "Training": "src/ember/training",
    "Evaluation": "src/ember/evaluation",
    "Runtime": "src/ember/runtime",
    "Lab": "domains/lab",
    "Infrastructure": "src/ember/infrastructure",
    "Governance/contracts": "src/ember/governance",
}

EXPECTED_ARTIFACTS = {
    "Model": "src/ember/model/model.py",
    "Training loop": "src/ember/training/pretrain.py",
    "Evaluator": "src/ember/evaluation/cbase_heldout_eval.py",
    "Runtime entry": "src/ember/runtime/infer.py",
    "Data pipeline": "src/ember/infrastructure/tools/ember-restart-3b/text_lab_corpus.py",
    "Governing contracts": "docs/domains/governance/authority",
}

TOP_LEVEL_ALLOWLIST = {
    ".github": "Hosted automation and repository policy workflows.",
    ".githooks": "Repository-local lifecycle and commit guards.",
    "artifacts": "Versioned machine-readable evidence artifacts.",
    "baseline": "Frozen comparison baselines.",
    "configs": "Versioned runtime and experiment configuration.",
    "data": "Versioned data inputs distinct from data-domain implementation code.",
    "manifests": "Immutable input, environment, and run manifests.",
    "receipts": "Versioned verification and execution receipts.",
    "runtime": "The Rust application runtime and operator lab workspace.",
    "scripts": "Repository maintenance and compatibility entry points.",
    "state": "Checked-in public state required by governed consumers.",
    "tests": "Cross-domain and acceptance test suites.",
    "tools": "Root launchers and repository maintenance tools.",
}


def _table_block(readme: str) -> str:
    assert readme.count(HEADING) == 1, f"expected exactly one {HEADING!r} heading"
    tail = readme.split(HEADING, 1)[1]
    next_heading = re.search(r"^## ", tail, flags=re.MULTILINE)
    return tail[: next_heading.start()] if next_heading else tail


def _table_rows(table: str) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for line in table.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        assert len(cells) == 4, f"malformed Where-things-are row: {line}"
        if cells[0] == "Kind" or set(cells[0]) == {"-"}:
            continue
        rows.append((cells[0], cells[1], cells[2].strip("`")))
    return rows


def _assert_paths_exist(rows: list[tuple[str, str, str]], root: Path) -> None:
    missing = [path for _kind, _name, path in rows if not (root / path).exists()]
    assert not missing, f"README Where-things-are paths missing: {missing}"


def _assert_top_level_explained(
    rows: list[tuple[str, str, str]], tracked_dirs: set[str]
) -> None:
    table_top_levels = {PurePosixPath(path).parts[0] for _kind, _name, path in rows}
    unexplained = tracked_dirs - table_top_levels - set(TOP_LEVEL_ALLOWLIST)
    assert not unexplained, f"tracked top-level directories are unexplained: {sorted(unexplained)}"
    stale = set(TOP_LEVEL_ALLOWLIST) - tracked_dirs
    assert not stale, f"top-level allow-list contains absent directories: {sorted(stale)}"
    assert all(reason and "\n" not in reason for reason in TOP_LEVEL_ALLOWLIST.values())


def _tracked_top_level_directories() -> set[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return {
        PurePosixPath(path).parts[0]
        for path in result.stdout.splitlines()
        if len(PurePosixPath(path).parts) > 1
    }


def test_readme_where_things_are_is_complete_and_live() -> None:
    table = _table_block(README.read_text(encoding="utf-8"))
    assert re.search(r"#\d+\b", table) is None, "issue-number token found in public map"
    rows = _table_rows(table)

    domains = [(name, path) for kind, name, path in rows if kind == "Domain"]
    artifacts = [(name, path) for kind, name, path in rows if kind == "Artifact"]
    assert len(domains) == len(dict(domains)) == len(EXPECTED_DOMAINS)
    assert len(artifacts) == len(dict(artifacts)) == len(EXPECTED_ARTIFACTS)
    assert dict(domains) == EXPECTED_DOMAINS
    assert dict(artifacts) == EXPECTED_ARTIFACTS

    _assert_paths_exist(rows, ROOT)
    _assert_top_level_explained(rows, _tracked_top_level_directories())


def test_planted_missing_path_row_is_rejected() -> None:
    rows = _table_rows(_table_block(README.read_text(encoding="utf-8")))
    with pytest.raises(AssertionError, match="paths missing"):
        _assert_paths_exist(rows + [("Artifact", "Planted missing", "missing/planted.file")], ROOT)


def test_planted_unlisted_top_level_directory_is_rejected() -> None:
    rows = _table_rows(_table_block(README.read_text(encoding="utf-8")))
    tracked_dirs = _tracked_top_level_directories() | {"planted-unlisted-directory"}
    with pytest.raises(AssertionError, match="unexplained"):
        _assert_top_level_explained(rows, tracked_dirs)
