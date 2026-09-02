# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest


REPO = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
MODULE_PATH = REPO / "scripts" / "roadmap" / "validate_roadmap.py"


def load_module():
    spec = importlib.util.spec_from_file_location("validate_roadmap", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def copy_roadmap(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / "manifests").mkdir(parents=True)
    shutil.copytree(REPO / "docs" / "roadmap", root / "docs" / "roadmap")
    shutil.copytree(
        REPO / "manifests" / "roadmap", root / "manifests" / "roadmap"
    )
    return root


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_real_roadmap_validates() -> None:
    module = load_module()
    result = module.validate_repository(REPO)
    assert result["status"] == "ROADMAP_VALID"
    assert result["contract_count"] == 12
    assert result["issue_count"] == 214
    assert result["issue_closures"] == 0


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("missing_issue", "issue census and reconciliation differ"),
        ("duplicate_issue", "duplicate reconciliation issue"),
        ("unknown_milestone", "unknown affected milestone"),
        ("closure", "issue closure mutation is forbidden"),
        ("stale_master", "source master mismatch"),
        ("dependency_cycle", "parent dependency cycle"),
        ("lost_clause", "public clause marker count"),
        ("baseline_labels", "stale issue mutation"),
    ],
)
def test_validator_rejects_integrity_failures(
    tmp_path: Path, mutation: str, expected: str
) -> None:
    module = load_module()
    root = copy_roadmap(tmp_path)
    manifests = root / "manifests" / "roadmap"
    reconciliation_path = manifests / "issue-reconciliation-v1.json"
    projection_path = manifests / "github-projection-v1.json"
    reconciliation = read_json(reconciliation_path)
    projection = read_json(projection_path)

    if mutation == "missing_issue":
        reconciliation["issues"].pop()
        reconciliation["source_issue_count"] -= 1
        write_json(reconciliation_path, reconciliation)
    elif mutation == "duplicate_issue":
        reconciliation["issues"].append(reconciliation["issues"][0])
        reconciliation["source_issue_count"] += 1
        write_json(reconciliation_path, reconciliation)
    elif mutation == "unknown_milestone":
        reconciliation["issues"][0]["affected_milestones"] = ["EMBER-99"]
        write_json(reconciliation_path, reconciliation)
    elif mutation == "closure":
        projection["issue_mutations"][0]["close"] = True
        write_json(projection_path, projection)
    elif mutation == "stale_master":
        projection["source_master_sha"] = "f" * 40
        write_json(projection_path, projection)
    elif mutation == "dependency_cycle":
        projection["parent_issues"][0]["depends_on"] = [
            projection["parent_issues"][-1]["tracking_key"]
        ]
        write_json(projection_path, projection)
    elif mutation == "baseline_labels":
        projection["issue_mutations"][0]["expected_labels"] = ["fabricated"]
        write_json(projection_path, projection)
    elif mutation == "lost_clause":
        public_path = root / "docs" / "roadmap" / "milestones" / "EMBER-00.md"
        text = public_path.read_text(encoding="utf-8")
        text = text.replace("<!-- clause-id: EMBER-00.OUTCOME.001 -->", "", 1)
        public_path.write_text(text, encoding="utf-8")
        crosswalk_path = manifests / "clause-crosswalk-v1.json"
        crosswalk = read_json(crosswalk_path)
        contract = crosswalk["contracts"][0]
        import hashlib

        contract["public_sha256"] = hashlib.sha256(
            public_path.read_bytes()
        ).hexdigest()
        write_json(crosswalk_path, crosswalk)

    with pytest.raises(module.RoadmapValidationError, match=expected):
        module.validate_repository(root)
