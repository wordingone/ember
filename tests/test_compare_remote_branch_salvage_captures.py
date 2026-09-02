# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from test_remote_branch_salvage import capture  # noqa: E402
from src.ember.governance.scripts.remote_branch_salvage import (  # noqa: E402
    _canonical,
    build_packet,
    build_public_summary,
)


FINALIZER = ROOT / "scripts" / "finalize_remote_branch_salvage.py"
COMPARATOR = ROOT / "scripts" / "compare_remote_branch_salvage_captures.py"
SOURCE_NAMES = (
    "branches_pre",
    "branches_post",
    "pulls",
    "tags",
    "releases",
    "deployments",
    "public_master",
)


def write_json(path: Path, value: object) -> None:
    path.write_bytes(_canonical(value) + b"\n")


def materialize_artifact(
    root: Path,
    *,
    captured_at: str,
    run_id: str,
    changed_source: str | None = None,
) -> None:
    root.mkdir()
    value = capture()
    value["captured_at"] = captured_at
    for name in SOURCE_NAMES:
        content = f"{name}:stable\n".encode()
        if name == changed_source:
            content = f"{name}:changed\n".encode()
        (root / f"{name}.json").write_bytes(content)
        value["source_evidence"][name] = hashlib.sha256(content).hexdigest()
    packet = build_packet(value)
    summary = build_public_summary(packet)
    context = {
        "schema_version": "ember-remote-branch-publication-context-v1",
        "repository": "wordingone/ember",
        "mode": "GITHUB_ACTIONS_WORKFLOW_ARTIFACT",
        "workflow_ref": "refs/heads/master",
        "workflow_sha": "a" * 40,
        "run_id": run_id,
        "run_attempt": 1,
        "excluded_refs": [],
        "ref_mutations_performed": [],
    }
    write_json(root / "packet.json", packet)
    write_json(root / "public-summary.json", summary)
    write_json(root / "publication-context.json", context)
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(FINALIZER),
            "--packet",
            str(root / "packet.json"),
            "--summary",
            str(root / "public-summary.json"),
            "--publication-context",
            str(root / "publication-context.json"),
            "--output",
            str(root / "candidate-receipt.json"),
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def run_compare(
    first: Path,
    second: Path,
    output: Path,
    *,
    expected_first_run_id: str = "1001",
    expected_second_run_id: str = "1002",
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-B",
            str(COMPARATOR),
            "--first-artifact",
            str(first),
            "--second-artifact",
            str(second),
            "--expected-first-run-id",
            expected_first_run_id,
            "--expected-second-run-id",
            expected_second_run_id,
            "--output",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def test_two_downloaded_artifacts_certify_only_allowed_run_and_time_variance(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    output = tmp_path / "certification.json"
    materialize_artifact(
        first, captured_at="2026-07-26T09:20:00Z", run_id="1001"
    )
    materialize_artifact(
        second, captured_at="2026-07-26T09:25:00Z", run_id="1002"
    )

    result = run_compare(first, second, output)

    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert receipt["status"] == "CERTIFIED_TWO_RUN_NON_AUTHORIZING_CAPTURE"
    assert receipt["run_ids"] == ["1001", "1002"]
    assert receipt["master_sha"] == "a" * 40
    assert receipt["branch_count"] == 2
    assert receipt["deletion_authority"] == "NOT_GRANTED"


def test_two_run_comparator_rejects_same_run_reused_twice(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    materialize_artifact(
        first, captured_at="2026-07-26T09:20:00Z", run_id="1001"
    )
    materialize_artifact(
        second, captured_at="2026-07-26T09:25:00Z", run_id="1001"
    )

    result = run_compare(
        first,
        second,
        tmp_path / "certification.json",
        expected_second_run_id="1001",
    )

    assert result.returncode == 2
    assert "two distinct workflow runs are required" in result.stdout


def test_two_run_comparator_rejects_element_level_evidence_drift(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    materialize_artifact(
        first, captured_at="2026-07-26T09:20:00Z", run_id="1001"
    )
    materialize_artifact(
        second,
        captured_at="2026-07-26T09:25:00Z",
        run_id="1002",
        changed_source="branches_post",
    )

    result = run_compare(first, second, tmp_path / "certification.json")

    assert result.returncode == 2
    assert "capture evidence differs across workflow runs" in result.stdout


def test_two_run_comparator_binds_downloaded_bytes_to_expected_run_ids(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    materialize_artifact(
        first, captured_at="2026-07-26T09:20:00Z", run_id="9999"
    )
    materialize_artifact(
        second, captured_at="2026-07-26T09:25:00Z", run_id="1002"
    )

    result = run_compare(first, second, tmp_path / "certification.json")

    assert result.returncode == 2
    assert "downloaded artifact run ID does not match expected workflow run" in result.stdout
