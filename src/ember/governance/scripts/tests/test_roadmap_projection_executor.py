# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path


ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file()) / "roadmap"


def load(name: str):
    path = ROOT / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_coalesce_combines_issue_labels_and_milestone() -> None:
    runner = load("roadmap_projection_runner.py")
    operations = [
        {"op": "create_label", "label": {"name": "roadmap:tracked"}},
        {"op": "add_issue_labels", "issue_number": 7, "labels": ["roadmap:tracked"]},
        {"op": "set_issue_milestone", "issue_number": 7, "milestone_id": "EMBER-05"},
        {"op": "add_subissue", "issue_number": 7, "parent_tracking_key": "roadmap-parent:EMBER-05"},
    ]
    assert runner.coalesce(operations) == [
        operations[0],
        {
            "op": "update_issue",
            "issue_number": 7,
            "add_labels": ["roadmap:tracked"],
            "set_milestone": "EMBER-05",
        },
        operations[3],
    ]


def test_file_transport_omits_null_milestone_due_date(monkeypatch, tmp_path: Path) -> None:
    launch = load("roadmap_projection_launch.py")
    base = launch.load_with_file_transport(ROOT / "roadmap_projection_executor.py")
    observed: dict[str, object] = {}

    def fake_run(command, **kwargs):
        request = Path(command[command.index("--input") + 1])
        observed["payload"] = json.loads(request.read_text(encoding="utf-8"))
        observed["command"] = command
        observed["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, '{"number":25}', "")

    monkeypatch.setattr(launch.subprocess, "run", fake_run)
    wrapper = tmp_path / "gh-safe.ps1"
    wrapper.write_text("# test wrapper", encoding="utf-8")
    github = base.SafeGitHub(wrapper, "wordingone/ember")
    result = github.api(
        "repos/wordingone/ember/milestones",
        method="POST",
        payload={"title": "EMBER-00", "due_on": None},
    )
    assert result == {"number": 25}
    assert observed["payload"] == {"title": "EMBER-00"}
    assert "--input" in observed["command"]
    assert "input" not in observed["kwargs"]

def test_published_receipt_chain_is_closed() -> None:
    repository = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
    receipt_root = repository / "receipts" / "roadmap"
    completion = json.loads(
        (receipt_root / "roadmap-publication-completion-v1.json").read_text(
            encoding="utf-8"
        )
    )
    execution_bytes = (
        receipt_root / "roadmap-projection-execution-v1.json"
    ).read_bytes()
    idempotency_bytes = (
        receipt_root / "roadmap-projection-idempotency-v1.json"
    ).read_bytes()
    execution = json.loads(execution_bytes)
    idempotency = json.loads(idempotency_bytes)

    assert hashlib.sha256(execution_bytes).hexdigest() == completion["execution"][
        "resumed_wave"
    ]["receipt_sha256"]
    assert hashlib.sha256(idempotency_bytes).hexdigest() == completion[
        "idempotency"
    ]["receipt_sha256"]
    assert completion["projection"]["planned_api_operations"] == 442
    assert completion["execution"]["total_completed_api_operations"] == 442
    assert execution["status"] == "APPLIED"
    assert execution["remaining_logical_operation_count"] == 0
    assert execution["issue_closure_count"] == 0
    assert idempotency["status"] == "APPLIED"
    assert idempotency["logical_operation_count"] == 0
    assert idempotency["planned_api_operation_count"] == 0
    assert idempotency["before_live_state_sha256"] == idempotency[
        "after_live_state_sha256"
    ] == completion["final_state"]["sha256"]
    assert completion["final_state"]["open_original_issues"] == 214
    assert completion["final_state"]["roadmap_parent_issues"] == 12
    assert completion["final_state"]["subissues"] == 175
    assert completion["claim_boundary"]["issues_closed"] == 0
    assert completion["claim_boundary"]["issue_bodies_rewritten"] is False