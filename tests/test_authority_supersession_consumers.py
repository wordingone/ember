# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Tests for the EMBER-02A authority supersession consumers.

goal_id: EMBER-02
workstream_id: EMBER-02A
next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
GATE_PATH = REPO / "scripts" / "authority_supersession_gate.py"
SPEC = importlib.util.spec_from_file_location("authority_supersession_gate", GATE_PATH)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def copy_crosswalk_tree(destination: Path) -> Path:
    payload = json.loads((REPO / GATE.CROSSWALK_PATH).read_text(encoding="utf-8"))
    paths = {
        GATE.CROSSWALK_PATH.as_posix(),
        GATE.MATRIX_PATH.as_posix(),
        GATE.VERIFIER_PATH.as_posix(),
    }
    paths.update(
        f"docs/roadmap/milestones/EMBER-{index:02d}.md"
        for index in range(12)
    )
    for registry in payload["source_registries"]:
        paths.update(item["path"] for item in registry["evidence"])
    for row in payload["rows"]:
        paths.update(item["path"] for item in row["evidence"])
    for relative in sorted(paths):
        source = REPO / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return destination


def test_current_crosswalk_gate_accepts_canonical_non_authorizing_packet() -> None:
    result = GATE.validate_current_authority_crosswalk(REPO)
    assert result["status"] == "PASS_WITH_CUSTODY_GAPS"
    assert result["row_count"] == 251
    assert result["custody_gap_count"] == 126


def test_current_authority_tree_fails_closed_when_packet_is_missing(
    tmp_path: Path,
) -> None:
    root = copy_crosswalk_tree(tmp_path)
    (root / GATE.CROSSWALK_PATH).unlink()
    with pytest.raises(
        GATE.AuthoritySupersessionGateError,
        match="crosswalk is absent",
    ):
        GATE.validate_current_authority_crosswalk(root)


def test_current_authority_tree_rejects_row_loss_and_master_substitution(
    tmp_path: Path,
) -> None:
    root = copy_crosswalk_tree(tmp_path)
    path = root / GATE.CROSSWALK_PATH
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["rows"].pop()
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(
        GATE.AuthoritySupersessionGateError,
        match="crosswalk hash mismatch",
    ):
        GATE.validate_current_authority_crosswalk(root)


def test_legacy_fixture_without_current_matrix_can_opt_out(tmp_path: Path) -> None:
    assert (
        GATE.validate_current_authority_crosswalk(
            tmp_path,
            require_current_authority=False,
        )
        is None
    )
