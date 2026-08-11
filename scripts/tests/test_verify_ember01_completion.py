#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Focused regressions for the unified EMBER-01 completion runner."""

from __future__ import annotations

import hashlib
import os
import shutil
import json
import subprocess
import sys
import base64
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import verify_ember01_completion as completion  # noqa: E402
import cond4_behavior_surface as cond4_surface  # noqa: E402
from ember_01_identity.cond4_battery_surface import (  # noqa: E402
    COMPLETION_VERIFIER_SYMBOLS,
    behavior_surface_sha256,
    completion_verifier_binding_valid,
    cond4_battery_output_sha256,
    cond4_receipt_transition_valid,
)


def _live_issue(number: int = 7, title: str = "Live obligation") -> dict:
    return {
        "number": number,
        "title": title,
        "body": "body",
        "url": f"https://github.com/wordingone/ember/issues/{number}",
        "createdAt": "2026-07-23T00:00:00Z",
        "updatedAt": "2026-07-23T01:00:00Z",
        "labels": [{"name": "research"}],
        "author": {"login": "wordingone"},
        "state": "OPEN",
        "stateReason": None,
        "closedAt": None,
        "comments": [],
    }


def _live_census_payload(issue: dict | None = None) -> dict:
    source = issue or _live_issue()
    return {
        "captured_at": "2026-07-23T02:00:00Z",
        "public_master_sha": "a" * 40,
        "open_issue_count": 1,
        "issue_snapshot_sha256": "d" * 64,
        "issue_source_snapshot": [
            {
                "number": source["number"],
                "title": source["title"],
                "body_base64": base64.b64encode(
                    source["body"].encode("utf-8")
                ).decode("ascii"),
                "url": source["url"],
                "created_at": source["createdAt"],
                "updated_at": source["updatedAt"],
                "labels": ["research"],
                "author": "wordingone",
                "state": "OPEN",
                "state_reason": "None",
                "closed_at": "None",
                "comments": [],
            }
        ]
    }


def test_selection_evidence_persists_only_goal_basename(tmp_path: Path) -> None:
    goal = tmp_path / "private" / "operator" / "goal.md"
    goal.parent.mkdir(parents=True)
    goal.write_text("# goal\n", encoding="utf-8")
    selection = tmp_path / "EMBER-GOAL-RESUME.md"
    selection.write_text(
        f"active_goal_path: {goal}\n",
        encoding="utf-8",
    )

    evidence = completion.selection_evidence(selection)
    assert evidence == {
        "selected_goal_suffix": "goal.md",
        "selector_sha256": hashlib.sha256(selection.read_bytes()).hexdigest(),
    }
    assert "private" not in json.dumps(evidence)
    assert "operator" not in json.dumps(evidence)


def test_selection_evidence_detects_same_basename_target_change(
    tmp_path: Path,
) -> None:
    first_goal = tmp_path / "first" / "goal.md"
    second_goal = tmp_path / "second" / "goal.md"
    first_goal.parent.mkdir()
    second_goal.parent.mkdir()
    first_goal.write_text("# first\n", encoding="utf-8")
    second_goal.write_text("# second\n", encoding="utf-8")
    selection = tmp_path / "EMBER-GOAL-RESUME.md"
    selection.write_text(
        f"active_goal_path: {first_goal}\n",
        encoding="utf-8",
    )
    before = completion.selection_evidence(selection)

    selection.write_text(
        f"active_goal_path: {second_goal}\n",
        encoding="utf-8",
    )
    after = completion.selection_evidence(selection)

    assert before["selected_goal_suffix"] == after["selected_goal_suffix"]
    assert before["selector_sha256"] != after["selector_sha256"]


def test_completion_receipt_declares_one_active_workstream() -> None:
    assert completion.RECEIPT_WORKSTREAM_ID == "EMBER-02A"
    assert completion.RECEIPT_WORKSTREAM_ID in completion.ACTIVE_WORKSTREAM_IDS


def test_completion_subject_goal_id_is_ember01_and_distinct_from_active_goal_id() -> None:
    # goal_id must stay the active-authority goal per docs/authority/GOAL.md's
    # required_future_artifact_fields binding rule (same value
    # verify_ember00_completion.py's receipt stamps for the same reason) --
    # this is not the field the 2026-08-01 cert adjudication flagged.
    assert completion.ACTIVE_GOAL_ID == "EMBER-02"
    # What the adjudication actually asked for: an unambiguous field naming
    # which goal this receipt certifies, distinct from goal_id.
    assert completion.COMPLETION_SUBJECT_GOAL_ID == "EMBER-01"
    assert completion.COMPLETION_SUBJECT_GOAL_ID != completion.ACTIVE_GOAL_ID


def test_completion_receipt_payload_stamps_goal_id_and_subject_separately(
    tmp_path: Path,
) -> None:
    """End-to-end regression: run the real script against this checkout and
    read the actual receipt bytes back, rather than inspecting the source.
    On the pre-fix code this fails with a KeyError on
    'completion_subject_goal_id' -- the field did not exist."""
    selection = tmp_path / "selection.md"
    selection.write_text(
        f"active_goal_path: {REPO_ROOT / 'docs/authority/GOAL.md'}\n", encoding="utf-8"
    )
    receipt = tmp_path / "receipt.json"
    subprocess.run(
        [
            sys.executable,
            "-B",
            str(REPO_ROOT / "scripts" / "verify_ember01_completion.py"),
            "--root", str(REPO_ROOT),
            "--selection", str(selection),
            "--receipt", str(receipt),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert receipt.is_file()
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["schema"] == "ember-01-completion-receipt-v1"
    assert payload["goal_id"] == "EMBER-02"
    assert payload["completion_subject_goal_id"] == "EMBER-01"
    assert payload["goal_id"] != payload["completion_subject_goal_id"]


def test_receipt_top_level_keys_match_the_launch_consumer_exactly(
    tmp_path: Path,
) -> None:
    """The launch validator compares the receipt's top-level key set with set
    equality, so a new top-level field makes every certificate minted afterwards
    unlaunchable. New evidence belongs inside an existing object instead."""
    sys.path.insert(0, str(REPO_ROOT / "tools" / "ember-restart-3b"))
    import certified_train_launch  # noqa: PLC0415

    selection = tmp_path / "selection.md"
    selection.write_text(
        f"active_goal_path: {REPO_ROOT / 'docs/authority/GOAL.md'}\n", encoding="utf-8"
    )
    receipt = tmp_path / "receipt.json"
    subprocess.run(
        [
            sys.executable,
            "-B",
            str(REPO_ROOT / "scripts" / "verify_ember01_completion.py"),
            "--root", str(REPO_ROOT),
            "--selection", str(selection),
            "--receipt", str(receipt),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    payload = json.loads(receipt.read_text(encoding="utf-8"))

    assert set(payload) == certified_train_launch.COMPLETION_RECEIPT_KEYS


def test_custody_legs_bind_census_to_remote_master_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []
    live_issue_census = tmp_path / "public-issue-census-live.json"
    live_issue_census.write_text(
        json.dumps(_live_census_payload()), encoding="utf-8"
    )

    monkeypatch.setattr(
        completion,
        "git",
        lambda *_args: SimpleNamespace(stdout="a" * 40 + "\n"),
    )
    monkeypatch.setattr(
        completion,
        "fetch_live_open_issues",
        lambda *_args, **_kwargs: {
            "returncode": 0,
            "issues": [_live_issue()],
            "stdout_sha256": "b" * 64,
            "command": ["gh", "issue", "list"],
        },
    )

    def fake_run(args: list[str], **_: object) -> dict[str, object]:
        captured.extend(args)
        return {
            "returncode": 2,
            "timed_out": False,
            "stdout": "",
            "stderr": "",
        }

    monkeypatch.setattr(completion, "run", fake_run)

    completion.custody_legs(
        REPO_ROOT,
        ["public-repository=B:/tmp/public"],
        run_custody=True,
        issue_census=live_issue_census,
    )

    ref_index = captured.index("--public-master-ref")
    assert captured[ref_index + 1] == "refs/remotes/origin/master"


def test_custody_legs_use_explicit_live_issue_census(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []
    live_issue_census = tmp_path / "public-issue-census-live.json"
    live_issue_census.write_text(
        json.dumps(_live_census_payload()), encoding="utf-8"
    )

    monkeypatch.setattr(
        completion,
        "git",
        lambda *_args: SimpleNamespace(stdout="a" * 40 + "\n"),
    )
    monkeypatch.setattr(
        completion,
        "fetch_live_open_issues",
        lambda *_args, **_kwargs: {
            "returncode": 0,
            "issues": [_live_issue()],
            "stdout_sha256": "b" * 64,
            "command": ["gh", "issue", "list"],
        },
    )

    def fake_run(args: list[str], **_: object) -> dict[str, object]:
        captured.extend(args)
        return {
            "returncode": 2,
            "timed_out": False,
            "stdout": "",
            "stderr": "",
        }

    monkeypatch.setattr(completion, "run", fake_run)

    completion.custody_legs(
        REPO_ROOT,
        ["public-repository=B:/tmp/public"],
        run_custody=True,
        issue_census=live_issue_census,
    )

    issue_index = captured.index("--issue-census")
    assert captured[issue_index + 1] == str(live_issue_census)
    digest_index = captured.index("--issue-census-sha256")
    assert captured[digest_index + 1] == hashlib.sha256(
        live_issue_census.read_bytes()
    ).hexdigest()


def test_custody_legs_preserve_custody_output_on_green_and_red(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ember-cli's /verify needs census.py's raw per-file output even on a red
    run (5 legs resolved-false, contradictions>0) -- not just on green. The
    in-checkout scratch file is always deleted ("keep the checkout clean"); a
    caller-supplied --preserve-custody-output copies it out first, regardless
    of census.py's exit code."""
    live_issue_census = tmp_path / "public-issue-census-live.json"
    live_issue_census.write_text(
        json.dumps(_live_census_payload()), encoding="utf-8"
    )

    monkeypatch.setattr(
        completion, "git", lambda *_args: SimpleNamespace(stdout="a" * 40 + "\n"),
    )
    monkeypatch.setattr(
        completion,
        "fetch_live_open_issues",
        lambda *_args, **_kwargs: {
            "returncode": 0,
            "issues": [_live_issue()],
            "stdout_sha256": "b" * 64,
            "command": ["gh", "issue", "list"],
        },
    )

    for returncode, contradictions in ((0, 0), (2, 8050)):
        def fake_run(
            args: list[str], returncode: int = returncode,
            contradictions: int = contradictions, **_: object,
        ) -> dict[str, object]:
            out_path = Path(args[args.index("--output") + 1])
            out_path.write_text(
                json.dumps({"contradictions": contradictions}), encoding="utf-8"
            )
            return {"returncode": returncode, "timed_out": False, "stdout": "", "stderr": ""}

        monkeypatch.setattr(completion, "run", fake_run)

        preserved = tmp_path / f"preserved-{returncode}.json"
        completion.custody_legs(
            REPO_ROOT,
            ["public-repository=B:/tmp/public"],
            run_custody=True,
            issue_census=live_issue_census,
            preserve_custody_output=preserved,
        )

        assert preserved.is_file()
        assert json.loads(preserved.read_text(encoding="utf-8"))["contradictions"] == contradictions
        # the in-checkout scratch file is always cleaned up, preserved or not
        assert not (REPO_ROOT / ".ember01-verify-custody.tmp.json").exists()


def test_red_census_output_survives_beside_the_receipt_with_no_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A red census's per-file contradiction rows ARE the diagnosis. Without any
    caller opt-in they must land beside the receipt (outside the checkout) with
    the path named in leg evidence; a green census must still leave nothing
    behind but a clean checkout."""
    live_issue_census = tmp_path / "public-issue-census-live.json"
    live_issue_census.write_text(
        json.dumps(_live_census_payload()), encoding="utf-8"
    )

    monkeypatch.setattr(
        completion, "git", lambda *_args: SimpleNamespace(stdout="a" * 40 + "\n"),
    )
    monkeypatch.setattr(
        completion,
        "fetch_live_open_issues",
        lambda *_args, **_kwargs: {
            "returncode": 0,
            "issues": [_live_issue()],
            "stdout_sha256": "b" * 64,
            "command": ["gh", "issue", "list"],
        },
    )

    for returncode, contradictions in ((2, 8050), (0, 0)):
        def fake_run(
            args: list[str], returncode: int = returncode,
            contradictions: int = contradictions, **_: object,
        ) -> dict[str, object]:
            out_path = Path(args[args.index("--output") + 1])
            out_path.write_text(
                json.dumps({"contradictions": contradictions}), encoding="utf-8"
            )
            return {"returncode": returncode, "timed_out": False, "stdout": "", "stderr": ""}

        monkeypatch.setattr(completion, "run", fake_run)

        receipt_dir = tmp_path / f"receipt-{returncode}"
        result = completion.custody_legs(
            REPO_ROOT,
            ["public-repository=B:/tmp/public"],
            run_custody=True,
            issue_census=live_issue_census,
            receipt_dir=receipt_dir,
        )

        # the in-checkout scratch file is gone either way
        assert not (REPO_ROOT / ".ember01-verify-custody.tmp.json").exists()
        evidence = result["1"]["evidence"]
        preserved = [p for p in receipt_dir.glob("*.json")] if receipt_dir.exists() else []

        if returncode == 0:
            assert "preserved_custody_output" not in evidence
            assert preserved == []
            continue

        recorded = Path(evidence["preserved_custody_output"])
        assert recorded.is_file()
        assert preserved == [recorded]
        assert json.loads(recorded.read_text(encoding="utf-8"))["contradictions"] == 8050
        # every custody leg carries the pointer, not just leg 1
        for key in ("1", "2", "6", "9"):
            assert result[key]["evidence"]["preserved_custody_output"] == str(recorded)


def test_custody_legs_reject_issue_census_mutated_during_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    live_issue_census = tmp_path / "public-issue-census-live.json"
    live_issue_census.write_text(
        json.dumps(_live_census_payload()), encoding="utf-8"
    )

    monkeypatch.setattr(
        completion,
        "git",
        lambda *_args: SimpleNamespace(stdout="a" * 40 + "\n"),
    )
    monkeypatch.setattr(
        completion,
        "fetch_live_open_issues",
        lambda *_args, **_kwargs: {
            "returncode": 0,
            "issues": [_live_issue()],
            "stdout_sha256": "b" * 64,
            "command": ["gh", "issue", "list"],
        },
    )

    def fake_run(_args: list[str], **_: object) -> dict[str, object]:
        live_issue_census.write_text(
            json.dumps(_live_census_payload(_live_issue(title="mutated"))),
            encoding="utf-8",
        )
        return {
            "returncode": 0,
            "timed_out": False,
            "stdout": "",
            "stderr": "",
        }

    monkeypatch.setattr(completion, "run", fake_run)

    result = completion.custody_legs(
        REPO_ROOT,
        ["public-repository=B:/tmp/public"],
        run_custody=True,
        issue_census=live_issue_census,
    )

    assert {row["state"] for row in result.values()} == {
        completion.RESOLVED_FALSE
    }
    assert {row["reason"] for row in result.values()} == {
        "issue census changed during custody run"
    }


def _passing_custody_run(
    monkeypatch: pytest.MonkeyPatch, live_issues: list[dict] | None = None,
) -> None:
    """Stub git + gh + census so custody_legs resolves on its own evidence."""
    monkeypatch.setattr(
        completion,
        "git",
        lambda *_args: SimpleNamespace(stdout="a" * 40 + "\n"),
    )
    monkeypatch.setattr(
        completion,
        "fetch_live_open_issues",
        lambda *_args, **_kwargs: {
            "returncode": 0,
            "issues": live_issues if live_issues is not None else [_live_issue()],
            "stdout_sha256": "c" * 64,
            "command": ["gh", "issue", "list"],
        },
    )
    monkeypatch.setattr(
        completion,
        "run",
        lambda *_args, **_kwargs: {
            "returncode": 0,
            "timed_out": False,
            "stdout": "",
            "stderr": "",
        },
    )


def test_issue_snapshot_capture_requires_two_agreeing_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A torn paginated read must not become the certified snapshot: the second
    read has to agree before the capture counts."""
    reads = [
        [_live_issue(title="torn")],
        [_live_issue(title="settled")],
        [_live_issue(title="settled")],
        [_live_issue(title="settled")],
    ]
    monkeypatch.setattr(
        completion,
        "fetch_live_open_issues",
        lambda *_args, **_kwargs: {
            "returncode": 0,
            "issues": reads.pop(0),
            "stdout_sha256": "c" * 64,
            "command": ["gh", "issue", "list"],
        },
    )

    snapshot = completion.capture_issue_snapshot(REPO_ROOT)

    assert snapshot["ok"] is True
    assert snapshot["attempts"] == 2
    assert len(snapshot["torn_reads"]) == 1
    assert snapshot["issue_count"] == 1
    assert completion.ISO_INSTANT_RE.fullmatch(snapshot["captured_at_utc"])
    assert len(snapshot["capture_nonce"]) == 32


def test_issue_snapshot_capture_refuses_a_persistently_torn_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter = iter(range(100))
    monkeypatch.setattr(
        completion,
        "fetch_live_open_issues",
        lambda *_args, **_kwargs: {
            "returncode": 0,
            "issues": [_live_issue(title=f"churn-{next(counter)}")],
            "stdout_sha256": "c" * 64,
            "command": ["gh", "issue", "list"],
        },
    )

    snapshot = completion.capture_issue_snapshot(REPO_ROOT)

    assert snapshot["ok"] is False
    assert snapshot["failure"] == "torn_read"
    assert snapshot["attempts"] == completion.ISSUE_SNAPSHOT_ATTEMPTS


def test_custody_legs_reject_a_torn_issue_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot_file = tmp_path / "public-issue-census-live.json"
    snapshot_file.write_text(json.dumps(_live_census_payload()), encoding="utf-8")
    monkeypatch.setattr(
        completion,
        "capture_issue_snapshot",
        lambda *_args, **_kwargs: {"ok": False, "failure": "torn_read", "attempts": 3},
    )
    monkeypatch.setattr(
        completion,
        "run",
        lambda *_args, **_kwargs: pytest.fail("census must not run"),
    )

    result = completion.custody_legs(
        REPO_ROOT,
        ["public-repository=B:/tmp/public"],
        run_custody=True,
        issue_census=snapshot_file,
    )

    assert {row["reason"] for row in result.values()} == {
        "issue snapshot torn across repeated live reads"
    }
    assert {row["state"] for row in result.values()} == {completion.RESOLVED_FALSE}


def test_custody_legs_survive_github_mutation_after_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#1331: issues filed/closed/relabelled DURING the census run must not
    invalidate the certificate. The legs bind to the captured snapshot, so a
    live list that has moved on since capture is evidence, never a verdict."""
    snapshot = tmp_path / "public-issue-census-live.json"
    snapshot.write_text(json.dumps(_live_census_payload()), encoding="utf-8")
    mutated_live = [
        _live_issue(title="relabelled after capture"),
        _live_issue(number=9, title="filed after capture"),
    ]
    _passing_custody_run(monkeypatch, live_issues=mutated_live)

    result = completion.custody_legs(
        REPO_ROOT,
        ["public-repository=B:/tmp/public"],
        run_custody=True,
        issue_census=snapshot,
    )

    assert {row["state"] for row in result.values()} == {completion.RESOLVED_TRUE}
    in_run = result["9"]["evidence"]["in_run_issue_snapshot"]
    assert in_run["equals_census_snapshot"] is False
    assert in_run["divergence_resolves_leg_state"] is False
    assert in_run["issue_count"] == 2


def test_custody_legs_refuse_when_the_issue_snapshot_cannot_be_captured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The in-run snapshot is what the certificate claims, so failing to take it
    is a refusal -- unlike divergence from it, which is only evidence."""
    snapshot = tmp_path / "public-issue-census-live.json"
    snapshot.write_text(json.dumps(_live_census_payload()), encoding="utf-8")
    _passing_custody_run(monkeypatch)
    monkeypatch.setattr(
        completion,
        "fetch_live_open_issues",
        lambda *_args, **_kwargs: {
            "returncode": 1,
            "issues": None,
            "stdout_sha256": "0" * 64,
            "command": ["gh", "issue", "list"],
            "stderr": "rate limited",
        },
    )

    result = completion.custody_legs(
        REPO_ROOT,
        ["public-repository=B:/tmp/public"],
        run_custody=True,
        issue_census=snapshot,
    )

    assert {row["state"] for row in result.values()} == {completion.RESOLVED_FALSE}
    assert {row["reason"] for row in result.values()} == {
        "in-run issue snapshot could not be captured"
    }


def test_custody_legs_record_snapshot_binding_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = tmp_path / "public-issue-census-live.json"
    snapshot.write_text(json.dumps(_live_census_payload()), encoding="utf-8")
    expected_sha = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    _passing_custody_run(monkeypatch)

    result = completion.custody_legs(
        REPO_ROOT,
        ["public-repository=B:/tmp/public"],
        run_custody=True,
        issue_census=snapshot,
    )

    for row in result.values():
        evidence = row["evidence"]
        assert evidence["issue_census_binding_mode"] == "point_in_time_snapshot"
        assert evidence["issue_census_sha256"] == expected_sha
        assert evidence["issue_census_capture_instant"] == "2026-07-23T02:00:00Z"
        assert (
            evidence["issue_census_capture_instant_source"]
            == "census.captured_at"
        )
        assert evidence["issue_census_public_master_sha"] == "a" * 40
        assert evidence["issue_census_open_issue_count"] == 1
        assert evidence["verified_checkout_head"] == "a" * 40
        assert expected_sha in evidence["issue_census_claim"]
        assert "2026-07-23T02:00:00Z" in evidence["issue_census_claim"]
        # Freshness the external mint consumer reads, stamped by this process.
        in_run = evidence["in_run_issue_snapshot"]
        assert completion.ISO_INSTANT_RE.fullmatch(in_run["captured_at_utc"])
        assert completion.ISO_INSTANT_RE.fullmatch(in_run["capture_started_at_utc"])
        assert len(in_run["capture_nonce"]) == 32
        assert len(in_run["snapshot_sha256"]) == 64
        assert in_run["capture_attempts"] == 1
        assert evidence["issue_census_age_seconds"] > 0


def test_custody_legs_fall_back_to_snapshot_max_updated_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Snapshots predating `captured_at` are still bindable through the newest
    issue update they contain -- a true lower bound on capture."""
    payload = _live_census_payload()
    del payload["captured_at"]
    payload["snapshot_max_issue_updated_at"] = "2026-07-23T01:00:00Z"
    snapshot = tmp_path / "legacy-census.json"
    snapshot.write_text(json.dumps(payload), encoding="utf-8")
    _passing_custody_run(monkeypatch)

    result = completion.custody_legs(
        REPO_ROOT,
        ["public-repository=B:/tmp/public"],
        run_custody=True,
        issue_census=snapshot,
    )

    assert {row["state"] for row in result.values()} == {completion.RESOLVED_TRUE}
    evidence = result["9"]["evidence"]
    assert evidence["issue_census_capture_instant"] == "2026-07-23T01:00:00Z"
    assert "lower bound" in evidence["issue_census_capture_instant_source"]


def test_custody_legs_reject_census_without_capture_instant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A snapshot that cannot say WHEN it was taken cannot be certified: the
    certificate's claim is 'issues as of <instant>' and there is no instant."""
    payload = _live_census_payload()
    del payload["captured_at"]
    snapshot = tmp_path / "instantless-census.json"
    snapshot.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        completion,
        "run",
        lambda *_args, **_kwargs: pytest.fail("census must not run"),
    )

    result = completion.custody_legs(
        REPO_ROOT,
        ["public-repository=B:/tmp/public"],
        run_custody=True,
        issue_census=snapshot,
    )

    assert {row["state"] for row in result.values()} == {
        completion.RESOLVED_FALSE
    }
    assert {row["reason"] for row in result.values()} == {
        "issue census carries no capture instant"
    }


def test_custody_legs_without_explicit_live_census_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        completion,
        "run",
        lambda *_args, **_kwargs: pytest.fail("census must not run"),
    )

    result = completion.custody_legs(
        REPO_ROOT,
        ["public-repository=B:/tmp/public"],
        run_custody=True,
    )

    assert {row["state"] for row in result.values()} == {
        completion.RESOLVED_FALSE
    }
    assert {row["reason"] for row in result.values()} == {
        "explicit live issue census is required for a custody run"
    }


def test_fetch_live_open_issues_uses_fixed_repository_state_and_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []
    executable = tmp_path / "gh.exe"
    executable.write_bytes(b"trusted-gh")
    monkeypatch.setattr(completion.shutil, "which", lambda _name: str(executable))

    def fake_run(args: list[str], **kwargs: object) -> dict[str, object]:
        assert Path(args[0]) != executable
        assert Path(args[0]).name == "gh.exe"
        assert Path(args[0]).read_bytes() == b"trusted-gh"
        captured.extend(["gh", *args[1:]])
        assert kwargs["display"][:3] == ["gh", "issue", "list"]
        return {
            "returncode": 0,
            "timed_out": False,
            "command": kwargs["display"],
            "stdout": json.dumps([_live_issue()]),
            "stderr": "",
        }

    monkeypatch.setattr(completion, "run", fake_run)
    result = completion.fetch_live_open_issues(REPO_ROOT)

    assert captured == [
        "gh",
        "issue",
        "list",
        "--repo",
        "wordingone/ember",
        "--state",
        "open",
        "--limit",
        str(completion.LIVE_ISSUE_LIMIT),
        "--json",
        completion.LIVE_ISSUE_JSON_FIELDS,
    ]
    assert result["issues"] == [_live_issue()]
    assert result["stdout_sha256"] == hashlib.sha256(
        json.dumps([_live_issue()]).encode("utf-8")
    ).hexdigest()
    assert result["executable_sha256"] == hashlib.sha256(b"trusted-gh").hexdigest()
    assert result["executable_name"] == "gh.exe"


def test_fetch_live_open_issues_rejects_non_json_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "gh.exe"
    executable.write_bytes(b"trusted-gh")
    monkeypatch.setattr(completion.shutil, "which", lambda _name: str(executable))
    monkeypatch.setattr(
        completion,
        "run",
        lambda *_args, **_kwargs: {
            "returncode": 0,
            "timed_out": False,
            "command": ["gh", "issue", "list"],
            "stdout": "not-json",
            "stderr": "",
        },
    )

    result = completion.fetch_live_open_issues(REPO_ROOT)

    assert result["returncode"] == 2
    assert result["issues"] is None


def test_fetch_live_open_issues_executes_snapshot_during_source_swap_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "gh.exe"
    executable.write_bytes(b"before")
    monkeypatch.setattr(completion.shutil, "which", lambda _name: str(executable))

    def fake_run(args: list[str], **kwargs: object) -> dict[str, object]:
        assert Path(args[0]) != executable
        assert Path(args[0]).read_bytes() == b"before"
        executable.write_bytes(b"after")
        executable.write_bytes(b"before")
        return {
            "returncode": 0,
            "timed_out": False,
            "command": kwargs["display"],
            "stdout": json.dumps([_live_issue()]),
            "stderr": "",
        }

    monkeypatch.setattr(completion, "run", fake_run)

    result = completion.fetch_live_open_issues(REPO_ROOT)

    assert result["returncode"] == 0
    assert result["issues"] == [_live_issue()]
    assert result["executable_sha256"] == hashlib.sha256(b"before").hexdigest()


def test_fetch_live_open_issues_rejects_snapshot_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "gh.exe"
    executable.write_bytes(b"before")
    monkeypatch.setattr(completion.shutil, "which", lambda _name: str(executable))

    def fake_run(args: list[str], **kwargs: object) -> dict[str, object]:
        Path(args[0]).write_bytes(b"after")
        return {
            "returncode": 0,
            "timed_out": False,
            "command": kwargs["display"],
            "stdout": json.dumps([_live_issue()]),
            "stderr": "",
        }

    monkeypatch.setattr(completion, "run", fake_run)
    result = completion.fetch_live_open_issues(REPO_ROOT)

    assert result["returncode"] == 2
    assert result["issues"] is None
    assert (
        result["stderr"]
        == "GitHub CLI executable snapshot changed during acquisition"
    )


def test_fetch_live_open_issues_rejects_limit_length_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "gh.exe"
    executable.write_bytes(b"trusted-gh")
    monkeypatch.setattr(completion.shutil, "which", lambda _name: str(executable))
    monkeypatch.setattr(completion, "LIVE_ISSUE_LIMIT", 1)
    monkeypatch.setattr(
        completion,
        "run",
        lambda *_args, **kwargs: {
            "returncode": 0,
            "timed_out": False,
            "command": kwargs["display"],
            "stdout": json.dumps([_live_issue()]),
            "stderr": "",
        },
    )

    result = completion.fetch_live_open_issues(REPO_ROOT)

    assert result["returncode"] == 2
    assert result["issues"] is None
    assert (
        result["stderr"]
        == "live GitHub issue result reached the acquisition limit; "
        "completeness is unproven"
    )


def test_custody_legs_do_not_impose_arbitrary_census_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_timeout: list[int | None] = []
    live_issue_census = tmp_path / "public-issue-census-live.json"
    live_issue_census.write_text(
        json.dumps(_live_census_payload()), encoding="utf-8"
    )

    monkeypatch.setattr(
        completion,
        "git",
        lambda *_args: SimpleNamespace(stdout="a" * 40 + "\n"),
    )
    monkeypatch.setattr(
        completion,
        "fetch_live_open_issues",
        lambda *_args, **_kwargs: {
            "returncode": 0,
            "issues": [_live_issue()],
            "stdout_sha256": "b" * 64,
            "command": ["gh", "issue", "list"],
        },
    )

    def fake_run(_args: list[str], **kwargs: object) -> dict[str, object]:
        captured_timeout.append(kwargs.get("timeout"))  # type: ignore[arg-type]
        return {
            "returncode": 2,
            "timed_out": False,
            "stdout": "",
            "stderr": "",
        }

    monkeypatch.setattr(completion, "run", fake_run)

    completion.custody_legs(
        REPO_ROOT,
        ["public-repository=B:/tmp/public"],
        run_custody=True,
        issue_census=live_issue_census,
    )

    assert captured_timeout == [None]


def test_run_reports_missing_executable_without_aborting_receipt(
    tmp_path: Path,
) -> None:
    result = completion.run(
        ["ember-command-that-does-not-exist"],
        root=tmp_path,
        name="missing",
    )

    assert result["returncode"] is None
    assert result["timed_out"] is False
    assert result["command"] == ["ember-command-that-does-not-exist"]
    assert result["stderr"]


def test_seat_leg_invokes_resolved_bun_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seat = tmp_path / completion.SEAT_TEST_REL
    seat.parent.mkdir(parents=True)
    seat.write_text("test('seat', () => {});\n", encoding="utf-8")
    resolved_bun = str(tmp_path / "bin" / "bun.cmd")
    captured: list[str] = []

    monkeypatch.setattr(completion.shutil, "which", lambda name: resolved_bun)

    def fake_run(args: list[str], **_: object) -> dict[str, object]:
        captured.extend(args)
        return {
            "returncode": 0,
            "timed_out": False,
            "stdout": "",
            "stderr": "",
        }

    monkeypatch.setattr(completion, "run", fake_run)

    result = completion.seat_leg(tmp_path, run_seat=True)

    assert captured == [
        resolved_bun,
        "test",
        "src/entrypoints/model-seat.test.ts",
    ]
    assert result["5"]["state"] == completion.RESOLVED_TRUE


def test_identity_legs_remeasure_real_manifest_and_execute_tamper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoint_manifest = tmp_path / "checkpoint-manifest.json"
    checkpoint_payload = {
        "schema_version": "ember-sparse-checkpoint-v3",
        "shards": [
            {
                "path": "shared.pt",
                "bytes": 4,
                "sha256": "a" * 64,
            }
        ],
    }
    checkpoint_manifest.write_text(
        json.dumps(checkpoint_payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    checkpoint_sha = hashlib.sha256(checkpoint_manifest.read_bytes()).hexdigest()
    model_config = tmp_path / "config.json"
    model_config.write_text('{"architecture_revision":"ember-sparse-3b-v2"}', encoding="utf-8")
    identity_manifest = tmp_path / "identity.json"
    identity_manifest.write_text(
        json.dumps(
            {
                "identity": {
                    "disposition": "HISTORICAL_ONLY",
                    "selected_as_owned_ember": False,
                },
                "checkpoint": {
                    "format": "ember-sparse-checkpoint-v3",
                    "byte_sha256": checkpoint_sha,
                    "tensors": [
                        {
                            "name": "shared.pt",
                            "shape": [4],
                            "dtype": "ember-checkpoint-shard-v1",
                            "sha256": "a" * 64,
                        }
                    ],
                },
                "parameters": {
                    "allocated": 3_839_161_856,
                    "unique": 3_839_161_856,
                    "trainable": 3_839_161_856,
                    "served": 3_839_161_856,
                    "active": 1_020_589_568,
                    "actually_trained": 1_020_589_568,
                },
                "evaluation": {"counts_toward_owned_completion": False},
                "provenance": {"ownership": "EXCLUDED_CONTAMINATED"},
            }
        ),
        encoding="utf-8",
    )
    receipt = {
        "subject_checkpoint_sha256": checkpoint_sha,
        "allocated_parameters": 3_839_161_856,
        "unique_parameters": 3_839_161_856,
        "trainable_parameters": 3_839_161_856,
        "served_parameters": 3_839_161_856,
        "active_parameters": 1_020_589_568,
        "episode_trainable_parameters": 1_020_589_568,
    }
    surface_source = tmp_path / "surface.py"
    surface_source.write_text("def exercised():\n    return 1\n", encoding="utf-8")
    validator = tmp_path / cond4_surface.VALIDATOR_REL
    validator.parent.mkdir(parents=True)
    validator.write_bytes((REPO_ROOT / cond4_surface.VALIDATOR_REL).read_bytes())
    surface_manifest = cond4_surface.build_surface_manifest(
        tmp_path, {"surface.py": ["exercised"]}
    )
    verified_paths: list[Path] = []

    monkeypatch.setattr(
        completion.identity_validator,
        "validate_manifest",
        lambda payload: payload,
    )
    monkeypatch.setattr(
        completion,
        "measure_live_checkpoint",
        lambda **_: receipt,
    )

    def fake_verify(*_: object, checkpoint_manifest: Path, **__: object) -> int:
        verified_paths.append(checkpoint_manifest)
        return 1

    monkeypatch.setattr(completion, "verify_parameter_identity_binding", fake_verify)
    monkeypatch.setattr(
        completion,
        "_run_identity_tamper_battery",
        lambda **_: {
            "tool": "test",
            "axis_count": 8,
            "axes": {
                axis: {
                    "rejected": True,
                    "finding_codes": [f"binding.{axis}"],
                    "duration_ms": index + 1,
                }
                for index, axis in enumerate(cond4_surface.COND4_AXES)
            },
            "failures": [],
            "all_rejected": True,
        },
    )
    monkeypatch.setattr(completion, "_load_cond4_surface_manifest", lambda _root: surface_manifest)

    result = completion.identity_legs(
        tmp_path,
        identity_manifest,
        checkpoint_manifest,
        model_config,
        tmp_path,
    )

    assert result["3"]["state"] == completion.RESOLVED_TRUE
    assert result["4"]["state"] == completion.RESOLVED_TRUE
    cond4_surface.validate_execution_packet(
        tmp_path,
        result["4"]["evidence"]["behavior_surface"],
        result["4"]["evidence"]["execution_evidence"],
    )
    assert len(verified_paths) == 1
    assert verified_paths[0] == checkpoint_manifest


def test_cond4_surface_mutation_refuses_before_any_axis_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "verifier.py"
    source.write_text("def exercised():\n    return 1\n", encoding="utf-8")
    manifest = cond4_surface.build_surface_manifest(
        tmp_path, {"verifier.py": ["exercised"]}
    )
    manifest_rel = "manifests/cond4-surface.json"
    manifest_path = tmp_path / manifest_rel
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(completion, "COND4_SURFACE_MANIFEST_REL", manifest_rel)
    monkeypatch.setattr(completion, "_cond4_surface_manifest", lambda _root: manifest)
    axis_calls: list[str] = []
    monkeypatch.setattr(
        completion,
        "_run_identity_tamper_battery",
        lambda **_kwargs: axis_calls.append("ran"),
    )

    source.write_text("def exercised():\n    return 2\n", encoding="utf-8")
    with pytest.raises(
        completion.Cond4SurfaceRefusal,
        match="COND4_SURFACE_MISMATCH",
    ):
        completion._run_bound_cond4_battery(
            root=tmp_path,
            payload={},
            receipt={},
            checkpoint_bytes=b"{}",
            model_config=tmp_path / "config.json",
            scratch_root=tmp_path / "scratch",
        )

    assert axis_calls == []


def test_cond4_surface_reduced_manifest_refuses_before_any_axis_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("def exercised():\n    return 1\n", encoding="utf-8")
    second.write_text("def required():\n    return 2\n", encoding="utf-8")
    expected = cond4_surface.build_surface_manifest(
        tmp_path,
        {"first.py": ["exercised"], "second.py": ["required"]},
    )
    reduced = cond4_surface.build_surface_manifest(
        tmp_path,
        {"first.py": ["exercised"]},
    )
    manifest_rel = "manifests/cond4-surface.json"
    manifest_path = tmp_path / manifest_rel
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps(reduced), encoding="utf-8")
    monkeypatch.setattr(completion, "COND4_SURFACE_MANIFEST_REL", manifest_rel)
    monkeypatch.setattr(completion, "_cond4_surface_manifest", lambda _root: expected)
    axis_calls: list[str] = []
    monkeypatch.setattr(
        completion,
        "_run_identity_tamper_battery",
        lambda **_kwargs: axis_calls.append("ran"),
    )

    with pytest.raises(
        completion.Cond4SurfaceRefusal,
        match="COND4_SURFACE_SPEC_MISMATCH",
    ):
        completion._run_bound_cond4_battery(
            root=tmp_path,
            payload={},
            receipt={},
            checkpoint_bytes=b"{}",
            model_config=tmp_path / "config.json",
            scratch_root=tmp_path / "scratch",
        )

    assert axis_calls == []


def _historical_identity_payload() -> dict[str, object]:
    return json.loads(
        (
            REPO_ROOT
            / "manifests"
            / "ember-01-identity"
            / "historical-checkpoint-semantic-seed83-step2-v1.json"
        ).read_text(encoding="utf-8")
    )


def _battery_receipt(payload: dict[str, object]) -> dict[str, object]:
    checkpoint = payload["checkpoint"]
    parameters = payload["parameters"]
    assert isinstance(checkpoint, dict)
    assert isinstance(parameters, dict)
    return {
        "subject_checkpoint_sha256": checkpoint["byte_sha256"],
        "allocated_parameters": parameters["allocated"],
        "unique_parameters": parameters["unique"],
        "trainable_parameters": parameters["trainable"],
        "served_parameters": parameters["served"],
        "active_parameters": parameters["active"],
        "episode_trainable_parameters": parameters["actually_trained"],
    }


def _rederive_cond4_battery(scratch_root: Path) -> dict[str, object]:
    payload = _historical_identity_payload()
    return completion._run_identity_tamper_battery(
        root=REPO_ROOT,
        payload=payload,
        receipt=_battery_receipt(payload),
        checkpoint_bytes=b'{"real":"checkpoint-manifest"}',
        model_config=REPO_ROOT / "configs" / "ember-restart-3b.json",
        scratch_root=scratch_root,
    )


def test_cond4_tamper_battery_runs_all_eight_axes_through_real_validator(
    tmp_path: Path,
) -> None:
    result = _rederive_cond4_battery(tmp_path)

    assert result["all_rejected"] is True
    assert result["failures"] == []
    assert set(result["axes"]) == {
        "checkpoint_bytes",
        "param_count",
        "tokenizer",
        "data_learned_signal",
        "mechanism",
        "backend",
        "benchmark_id",
        "comparator",
    }
    assert all(row["rejected"] is True for row in result["axes"].values())
    assert all(row["duration_ms"] > 0 for row in result["axes"].values())
    assert list(tmp_path.glob(".ember01-cond4-*")) == []


def test_tamper_battery_names_one_seeded_fail_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _historical_identity_payload()
    original_run = completion.run
    monkeypatch.setattr(
        completion,
        "verify_parameter_identity_binding",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            completion.ParameterIdentityMismatch("tampered checkpoint manifest")
        ),
    )

    def one_axis_accepts(args: list[str], **kwargs: object) -> dict[str, object]:
        if kwargs.get("name") == "cond4_tokenizer":
            return {
                "returncode": 0,
                "timed_out": False,
                "stdout": '{"ok":true}',
                "stderr": "",
            }
        return original_run(args, **kwargs)

    monkeypatch.setattr(completion, "run", one_axis_accepts)

    result = completion._run_identity_tamper_battery(
        root=REPO_ROOT,
        payload=payload,
        receipt=_battery_receipt(payload),
        checkpoint_bytes=b'{"real":"checkpoint-manifest"}',
        model_config=tmp_path / "config.json",
        scratch_root=tmp_path,
    )

    assert result["all_rejected"] is False
    assert result["failures"] == ["tokenizer"]
    assert result["axes"]["tokenizer"]["rejected"] is False


def test_cond4_execution_evidence_binds_surface_checkpoint_loads_and_axis_timings(
    tmp_path: Path,
) -> None:
    source = tmp_path / "surface.py"
    source.write_text("def exercised():\n    return 1\n", encoding="utf-8")
    validator = tmp_path / cond4_surface.VALIDATOR_REL
    validator.parent.mkdir(parents=True)
    validator.write_bytes((REPO_ROOT / cond4_surface.VALIDATOR_REL).read_bytes())
    manifest = cond4_surface.build_surface_manifest(
        tmp_path, {"surface.py": ["exercised"]}
    )
    checkpoint_bytes = b'{"shards":[{"bytes":7},{"bytes":11}]}'
    battery = {
        "axes": {
            axis: {
                "rejected": True,
                "finding_codes": [f"binding.{axis}"],
                "duration_ms": index + 1,
            }
            for index, axis in enumerate(cond4_surface.COND4_AXES)
        }
    }

    evidence = completion._cond4_execution_evidence(
        checkpoint_bytes=checkpoint_bytes,
        surface_manifest=manifest,
        battery=battery,
        load_count=2,
    )

    cond4_surface.validate_execution_packet(tmp_path, manifest, evidence)
    assert evidence["subject"] == {
        "behavior_surface_validator_sha256": hashlib.sha256(
            (REPO_ROOT / "scripts" / "cond4_behavior_surface.py").read_bytes()
        ).hexdigest(),
        "checkpoint_manifest_sha256": hashlib.sha256(checkpoint_bytes).hexdigest(),
        "surface_aggregate_sha256": manifest["aggregate_sha256"],
        "checkpoint_bytes_loaded": 36,
        "load_count": 2,
    }
    assert [row["axis"] for row in evidence["axes"]] == list(
        cond4_surface.COND4_AXES
    )


def test_cond4_execution_evidence_refuses_missing_or_false_axis(
    tmp_path: Path,
) -> None:
    source = tmp_path / "surface.py"
    source.write_text("def exercised():\n    return 1\n", encoding="utf-8")
    manifest = cond4_surface.build_surface_manifest(
        tmp_path, {"surface.py": ["exercised"]}
    )
    battery = {
        "axes": {
            axis: {
                "rejected": axis != "backend",
                "finding_codes": [f"binding.{axis}"],
                "duration_ms": 1,
            }
            for axis in cond4_surface.COND4_AXES
        }
    }

    with pytest.raises(ValueError, match="COND4_EXECUTION_EVIDENCE_INVALID"):
        completion._cond4_execution_evidence(
            checkpoint_bytes=b'{"shards":[{"bytes":1}]}',
            surface_manifest=manifest,
            battery=battery,
            load_count=2,
        )


def test_identity_legs_are_unresolved_without_real_checkpoint(
    tmp_path: Path,
) -> None:
    result = completion.identity_legs(
        REPO_ROOT,
        REPO_ROOT
        / "manifests"
        / "ember-01-identity"
        / "historical-checkpoint-semantic-seed83-step2-v1.json",
        tmp_path / "missing-checkpoint-manifest.json",
        tmp_path / "missing-config.json",
        tmp_path,
    )

    assert result["3"]["state"] == completion.UNRESOLVED
    assert result["4"]["state"] == completion.UNRESOLVED


def test_committed_cond4_receipt_binds_shipping_verifiers_and_all_axes(
    tmp_path: Path,
) -> None:
    receipt = json.loads(
        (
            REPO_ROOT
            / "receipts"
            / "ember-01-completion"
            / "cond4-tamper-battery-bf20f050-v7.json"
        ).read_text(encoding="utf-8")
    )
    assert receipt["invariant_sha256"] == (
        "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
    )
    assert receipt["schema"] == "ember-cond4-tamper-battery-receipt-v7"
    assert receipt["result"] == "PASS"
    assert receipt["migration"]["command"] == (
        "scripts/verify_ember01_completion.py::identity_legs"
    )
    implementation = receipt["implementation"]["behavior_surface_validator"]
    assert hashlib.sha256((REPO_ROOT / implementation["path"]).read_bytes()).hexdigest() == implementation["sha256"]
    config = receipt["migration"]["historical_config"]
    config_bytes = subprocess.run(
        ["git", "show", f"{config['source_commit']}:{config['repository_path']}"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    ).stdout
    assert hashlib.sha256(config_bytes).hexdigest() == config["sha256"]
    evidence = receipt["leg4"]["evidence"]
    cond4_surface.validate_execution_packet(
        REPO_ROOT,
        evidence["behavior_surface"],
        evidence["execution_evidence"],
    )
    assert receipt["leg3"]["state"] == completion.RESOLVED_TRUE
    assert receipt["leg4"]["state"] == completion.RESOLVED_TRUE
    identity_binding = receipt["subject"]["identity_manifest"]
    assert (
        hashlib.sha256((REPO_ROOT / identity_binding["path"]).read_bytes()).hexdigest()
        == identity_binding["sha256"]
    )
    assert evidence["axis_count"] == 8
    assert evidence["all_rejected"] is True
    assert evidence["failures"] == []
    assert set(evidence["axes"]) == {
        "checkpoint_bytes",
        "param_count",
        "tokenizer",
        "data_learned_signal",
        "mechanism",
        "backend",
        "benchmark_id",
        "comparator",
    }
    assert all(axis["rejected"] is True for axis in evidence["axes"].values())
    assert receipt["claim_boundary"] == {
        "supports_completion_condition": 4,
        "counts_as_owned_checkpoint": False,
        "counts_as_sufficient_pretraining": False,
        "counts_as_capability_evidence": False,
        "counts_as_full_ember_completion": False,
    }


def _init_git_repo(root: Path) -> None:
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@e.st", "-c", "user.name=t",
         "commit", "--allow-empty", "-q", "-m", "init"],
        cwd=root, check=True,
    )


def test_inspect_checkout_retries_transient_git_failure_then_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real class this cures: `git rev-parse HEAD` returns nonzero with
    EMPTY stderr once, then works fine on retry -- inspect_checkout must
    survive that instead of discarding the whole run."""
    root = tmp_path / "repo"
    _init_git_repo(root)

    real_git = completion.git
    call_counts: dict[tuple, int] = {}

    def flaky_git(call_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        call_counts[args] = call_counts.get(args, 0) + 1
        if args[:2] == ("rev-parse", "HEAD") and call_counts[args] == 1:
            return subprocess.CompletedProcess(args, returncode=128, stdout="", stderr="")
        return real_git(call_root, *args)

    monkeypatch.setattr(completion, "git", flaky_git)

    sleeps: list[float] = []
    result = completion.inspect_checkout(root, sleep=sleeps.append)

    assert result["git_retries"] == 1
    assert result["head"]
    assert sleeps == [2.0]


def test_inspect_checkout_raises_with_full_diagnostics_after_persistent_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    root.mkdir()  # deliberately not a git repo -- persistent failure case

    def always_fails(call_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args, returncode=128, stdout="", stderr="fatal: not a git repository"
        )

    monkeypatch.setattr(completion, "git", always_fails)

    sleeps: list[float] = []
    with pytest.raises(RuntimeError) as excinfo:
        completion.inspect_checkout(root, sleep=sleeps.append)

    message = str(excinfo.value)
    assert "rev-parse HEAD" in message
    diagnostics = json.loads(message.split(": ", 1)[1])
    assert diagnostics["returncode"] == 128
    assert diagnostics["stderr"] == "fatal: not a git repository"
    assert diagnostics["stdout"] == ""
    assert diagnostics["cwd"] == str(root)
    assert diagnostics["git_dir_exists"] is False
    assert sleeps == [2.0, 5.0, 10.0]


def test_inspect_checkout_dirty_tree_reported_without_retry_masking(
    tmp_path: Path,
) -> None:
    """A successful git-status call that legitimately reports a dirty tree
    must never be retried or reinterpreted -- returncode 0 is accepted on
    the first try regardless of what the tree state says."""
    root = tmp_path / "repo"
    _init_git_repo(root)
    (root / "untracked.txt").write_text("dirty", encoding="utf-8")

    sleeps: list[float] = []
    result = completion.inspect_checkout(root, sleep=sleeps.append)

    assert result["clean"] is False
    assert result["git_retries"] == 0
    assert sleeps == []


def test_inspect_checkout_detached_head_symbolic_ref_not_retried(
    tmp_path: Path,
) -> None:
    """`git symbolic-ref` returning 1 means detached HEAD -- an expected
    result, not an error -- and must never trigger a retry."""
    root = tmp_path / "repo"
    _init_git_repo(root)
    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    subprocess.run(["git", "checkout", "-q", head_sha], cwd=root, check=True)

    sleeps: list[float] = []
    result = completion.inspect_checkout(root, sleep=sleeps.append)

    assert result["detached"] is True
    assert result["git_retries"] == 0
    assert sleeps == []


def _sandbox_closure_repo(root: Path, *, entrypoint: str = "import json\n") -> Path:
    """A miniature repo carrying a real closure module and a declared closure."""
    repo = root / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copyfile(
        REPO_ROOT / "scripts" / "training_closure.py",
        repo / "scripts" / "training_closure.py",
    )
    (repo / "tools").mkdir(parents=True)
    (repo / "tools" / "entrypoint.py").write_text(entrypoint, encoding="utf-8")
    (repo / "configs").mkdir(parents=True)
    (repo / "configs" / "training.json").write_text('{"steps": 1}\n', encoding="utf-8")
    manifest = repo / "manifests" / "training-dependency-closure.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "ember-training-dependency-closure-v1",
                "entrypoints": ["tools/entrypoint.py"],
                "dynamic_entrypoints": [],
                "code": ["scripts/training_closure.py"],
                "data": ["configs/training.json"],
                "dynamic_call_sites": {},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return repo


def test_closure_evidence_pins_the_hash_on_a_clean_boundary(tmp_path: Path) -> None:
    repo = _sandbox_closure_repo(tmp_path)
    value, reason = completion.closure_evidence_at(repo)
    assert reason == "ok"
    assert value is not None and len(value) == 64


def test_closure_evidence_refuses_to_pin_over_a_violated_boundary(
    tmp_path: Path,
) -> None:
    """A green certificate must never pin a closure hash over a broken boundary.

    The launch consumer falls back to whole-tip equality when no hash is
    pinned, so a violated boundary loses the relaxation and gets the older,
    stricter binding instead of a hash that would look authoritative.
    """
    repo = _sandbox_closure_repo(tmp_path, entrypoint="from smuggled import SECRET\n")
    (repo / "tools" / "smuggled.py").write_text("SECRET = 1\n", encoding="utf-8")

    value, reason = completion.closure_evidence_at(repo)

    assert value is None
    assert reason.startswith("violated:")
    assert "tools/smuggled.py" in reason


def test_closure_evidence_distinguishes_unavailable_from_violated(
    tmp_path: Path,
) -> None:
    """A bare None cannot tell predates-the-manifest from boundary-broken."""
    bare = tmp_path / "bare"
    bare.mkdir()

    value, reason = completion.closure_evidence_at(bare)

    assert value is None
    assert reason.startswith("unavailable:")


def test_closure_evidence_missing_manifest_is_unavailable(tmp_path: Path) -> None:
    repo = _sandbox_closure_repo(tmp_path)
    (repo / "manifests" / "training-dependency-closure.json").unlink()

    value, reason = completion.closure_evidence_at(repo)

    assert value is None
    assert reason.startswith("unavailable:")
