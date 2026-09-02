# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


REPO = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
SCRIPT = REPO / "scripts" / "roadmap" / "publish_contracts.py"


SOURCE = """---
goal_id: EMBER-02
title: Three-billion-parameter foundation birth
depends_on: [EMBER-01]
unlocks: [EMBER-03]
---

# EMBER-02 — Three-billion-parameter foundation birth

## Outcome

Create a sufficiently trained owned foundation model.

## Required work

1. Train the model.
2. Bind the checkpoint.

- Preserve native reasoning.

## Prohibited substitutions

- A smoke run is not model birth.

## Completion certificate

1. Exact checkpoint evidence passes.

## Failure and reopening

Missing evidence keeps the milestone open.

## Agent allocation

- A private founder owns private routing at {private_root}\\avir\\founder.

## Transition

Activate `{private_root}\\avir\\founder\\goals\\ember\\ember-03\\goal.md`.
"""
SOURCE = SOURCE.format(private_root="B:" + "\\M")


def run_renderer(tmp_path: Path, source_text: str = SOURCE) -> tuple[Path, Path]:
    source_root = tmp_path / "source"
    goal_root = source_root / "ember-02-3b-foundation-birth"
    goal_root.mkdir(parents=True)
    (goal_root / "goal.md").write_text(source_text, encoding="utf-8")
    output_root = tmp_path / "public"
    crosswalk = tmp_path / "crosswalk.json"
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(SCRIPT),
            "--source-dir",
            str(source_root),
            "--output-dir",
            str(output_root),
            "--crosswalk",
            str(crosswalk),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return output_root / "EMBER-02.md", crosswalk


def test_renderer_preserves_normative_text_and_removes_private_execution(
    tmp_path: Path,
) -> None:
    public_path, crosswalk_path = run_renderer(tmp_path)
    public = public_path.read_text(encoding="utf-8")
    crosswalk = json.loads(crosswalk_path.read_text(encoding="utf-8"))

    assert "Create a sufficiently trained owned foundation model." in public
    assert "A smoke run is not model birth." in public
    assert "Missing evidence keeps the milestone open." in public
    assert ("B:" + "\\M\\") not in public
    assert "private routing" not in public
    assert "Private founder assignments" in public
    assert crosswalk["schema_version"] == "ember-roadmap-clause-crosswalk-v1"
    source_path = (
        tmp_path / "source" / "ember-02-3b-foundation-birth" / "goal.md"
    )
    assert crosswalk["contracts"][0]["source_sha256"] == hashlib.sha256(
        source_path.read_bytes()
    ).hexdigest()
    excluded = crosswalk["contracts"][0]["excluded_operational_sections"]
    assert {row["heading"] for row in excluded} == {
        "Agent allocation",
        "Transition",
    }
    assert all(len(row["source_sha256"]) == 64 for row in excluded)


def test_renderer_assigns_unique_stable_ids_to_every_normative_block(
    tmp_path: Path,
) -> None:
    public_path, crosswalk_path = run_renderer(tmp_path)
    public = public_path.read_text(encoding="utf-8")
    crosswalk = json.loads(crosswalk_path.read_text(encoding="utf-8"))
    rows = crosswalk["contracts"][0]["clauses"]
    ids = [row["clause_id"] for row in rows]

    assert ids
    assert len(ids) == len(set(ids))
    assert all(f"<!-- clause-id: {clause_id} -->" in public for clause_id in ids)
    assert all(row["relation"] == "verbatim" for row in rows)
    assert all(row["source_sha256"] == row["public_sha256"] for row in rows)


def test_renderer_rejects_duplicate_goal_ids(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    for name in ("ember-one", "ember-two"):
        goal_root = source_root / name
        goal_root.mkdir(parents=True)
        (goal_root / "goal.md").write_text(SOURCE, encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(SCRIPT),
            "--source-dir",
            str(source_root),
            "--output-dir",
            str(tmp_path / "public"),
            "--crosswalk",
            str(tmp_path / "crosswalk.json"),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "duplicate goal_id" in result.stderr


def test_renderer_rejects_host_private_path_outside_excluded_sections(
    tmp_path: Path,
) -> None:
    source = SOURCE.replace(
        "Create a sufficiently trained owned foundation model.",
        "Read " + "B:" + "\\M\\private\\model.json before training.",
    )
    source_root = tmp_path / "source"
    goal_root = source_root / "ember-02"
    goal_root.mkdir(parents=True)
    (goal_root / "goal.md").write_text(source, encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(SCRIPT),
            "--source-dir",
            str(source_root),
            "--output-dir",
            str(tmp_path / "public"),
            "--crosswalk",
            str(tmp_path / "crosswalk.json"),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "host-private path in normative text" in result.stderr
