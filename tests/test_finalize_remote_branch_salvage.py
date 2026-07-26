# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from test_remote_branch_salvage import capture  # noqa: E402
from scripts.remote_branch_salvage import build_packet, build_public_summary  # noqa: E402


FINALIZER = ROOT / "scripts" / "finalize_remote_branch_salvage.py"
WORKFLOW = ROOT / ".github" / "workflows" / "remote-branch-salvage-capture.yml"


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def publication_context(*, mutated_refs: list[str] | None = None) -> dict:
    return {
        "schema_version": "ember-remote-branch-publication-context-v1",
        "repository": "wordingone/ember",
        "mode": "GITHUB_ACTIONS_WORKFLOW_ARTIFACT",
        "workflow_ref": "refs/heads/master",
        "workflow_sha": "a" * 40,
        "run_id": "123456789",
        "run_attempt": 1,
        "excluded_refs": [],
        "ref_mutations_performed": mutated_refs or [],
    }


def run_finalizer(tmp_path: Path, context: dict) -> subprocess.CompletedProcess[str]:
    packet = build_packet(capture())
    summary = build_public_summary(packet)
    packet_path = tmp_path / "packet.json"
    summary_path = tmp_path / "summary.json"
    context_path = tmp_path / "publication.json"
    output_path = tmp_path / "receipt.json"
    write_json(packet_path, packet)
    write_json(summary_path, summary)
    write_json(context_path, context)
    return subprocess.run(
        [
            sys.executable,
            "-B",
            str(FINALIZER),
            "--packet",
            str(packet_path),
            "--summary",
            str(summary_path),
            "--publication-context",
            str(context_path),
            "--output",
            str(output_path),
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def test_finalizer_accepts_master_workflow_artifact_without_ref_mutation(
    tmp_path: Path,
) -> None:
    result = run_finalizer(tmp_path, publication_context())

    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads((tmp_path / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "CERTIFIED_NON_AUTHORIZING_CAPTURE"
    assert receipt["master_sha"] == "a" * 40
    assert receipt["branch_count"] == 2
    assert receipt["excluded_refs"] == []
    assert receipt["ref_mutations_performed"] == []
    assert receipt["deletion_authority"] == "NOT_GRANTED"
    assert receipt["public_mutation_performed"] is False


def test_finalizer_rejects_publication_that_mutates_a_captured_ref(
    tmp_path: Path,
) -> None:
    result = run_finalizer(
        tmp_path,
        publication_context(mutated_refs=["refs/heads/feat/contained"]),
    )

    assert result.returncode == 2
    assert "publication mutated a ref inside the captured population" in result.stdout
    assert not (tmp_path / "receipt.json").exists()


def test_finalizer_rejects_undeclared_population_exclusions(tmp_path: Path) -> None:
    context = publication_context()
    context["excluded_refs"] = ["refs/heads/feat/contained"]

    result = run_finalizer(tmp_path, context)

    assert result.returncode == 2
    assert "certification capture cannot exclude live refs" in result.stdout


def test_finalizer_rejects_ref_drift_inside_the_capture_window(tmp_path: Path) -> None:
    drifted = capture()
    drifted["branches"][1]["ref_stability"]["preexecution_sha"] = "f" * 40
    packet = build_packet(drifted)
    summary = build_public_summary(packet)
    packet_path = tmp_path / "packet.json"
    summary_path = tmp_path / "summary.json"
    context_path = tmp_path / "publication.json"
    output_path = tmp_path / "receipt.json"
    write_json(packet_path, packet)
    write_json(summary_path, summary)
    write_json(context_path, publication_context())

    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(FINALIZER),
            "--packet",
            str(packet_path),
            "--summary",
            str(summary_path),
            "--publication-context",
            str(context_path),
            "--output",
            str(output_path),
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 2
    assert "capture window contains ref drift" in result.stdout


def test_post_merge_capture_workflow_is_manual_read_only_and_artifact_only() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in text
    assert "pull_request:" not in text
    assert "\npush:" not in text
    assert "contents: read" in text
    assert "actions/upload-artifact@v4" in text
    assert "git push" not in text
    assert "gh pr comment" not in text
    assert "finalize_remote_branch_salvage.py" in text
