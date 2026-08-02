#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Focused regressions for the unified EMBER-01 completion runner."""

from __future__ import annotations

import hashlib
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
    # goal_id must stay the active-authority goal per GOAL.md's
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
        f"active_goal_path: {REPO_ROOT / 'GOAL.md'}\n", encoding="utf-8"
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


def test_custody_legs_reject_explicit_census_not_equal_to_live_github(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    supplied = tmp_path / "forged-census.json"
    supplied.write_text(
        json.dumps(_live_census_payload(_live_issue(title="forged"))),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        completion,
        "fetch_live_open_issues",
        lambda *_args, **_kwargs: {
            "returncode": 0,
            "issues": [_live_issue(title="actual")],
            "stdout_sha256": "c" * 64,
            "command": ["gh", "issue", "list"],
        },
    )

    result = completion.custody_legs(
        REPO_ROOT,
        ["public-repository=B:/tmp/public"],
        run_custody=True,
        issue_census=supplied,
    )

    assert {row["state"] for row in result.values()} == {
        completion.RESOLVED_FALSE
    }
    assert {row["reason"] for row in result.values()} == {
        "issue census does not equal same-run live GitHub snapshot"
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

    def fake_verify(*_: object, checkpoint_manifest: Path, **__: object) -> None:
        verified_paths.append(checkpoint_manifest)

    monkeypatch.setattr(completion, "verify_parameter_identity_binding", fake_verify)
    monkeypatch.setattr(
        completion,
        "_run_identity_tamper_battery",
        lambda **_: {
            "tool": "test",
            "axis_count": 8,
            "axes": {f"axis-{index}": {"rejected": True} for index in range(8)},
            "failures": [],
            "all_rejected": True,
        },
    )

    result = completion.identity_legs(
        tmp_path,
        identity_manifest,
        checkpoint_manifest,
        model_config,
        tmp_path,
    )

    assert result["3"]["state"] == completion.RESOLVED_TRUE
    assert result["4"]["state"] == completion.RESOLVED_TRUE
    assert len(verified_paths) == 1
    assert verified_paths[0] == checkpoint_manifest


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


def test_tamper_battery_runs_all_eight_axes_through_real_validator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _historical_identity_payload()
    monkeypatch.setattr(
        completion,
        "verify_parameter_identity_binding",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            completion.ParameterIdentityMismatch("tampered checkpoint manifest")
        ),
    )

    result = completion._run_identity_tamper_battery(
        root=REPO_ROOT,
        payload=payload,
        receipt=_battery_receipt(payload),
        checkpoint_bytes=b'{"real":"checkpoint-manifest"}',
        model_config=tmp_path / "config.json",
        scratch_root=tmp_path,
    )

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


def test_committed_cond4_receipt_binds_shipping_verifiers_and_all_axes() -> None:
    receipt = json.loads(
        (
            REPO_ROOT
            / "receipts"
            / "ember-01-completion"
            / "cond4-tamper-battery-bf20f050-v1.json"
        ).read_text(encoding="utf-8")
    )

    for binding in receipt["implementation"].values():
        path = REPO_ROOT / binding["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == binding["sha256"]
    identity_binding = receipt["subject"]["identity_manifest"]
    assert (
        hashlib.sha256((REPO_ROOT / identity_binding["path"]).read_bytes()).hexdigest()
        == identity_binding["sha256"]
    )
    assert receipt["leg4"]["axis_count"] == 8
    assert receipt["leg4"]["all_rejected"] is True
    assert receipt["leg4"]["failures"] == []
    assert set(receipt["leg4"]["axes"]) == {
        "checkpoint_bytes",
        "param_count",
        "tokenizer",
        "data_learned_signal",
        "mechanism",
        "backend",
        "benchmark_id",
        "comparator",
    }
    assert all(axis["rejected"] is True for axis in receipt["leg4"]["axes"].values())
    assert receipt["claim_boundary"] == {
        "supports_completion_condition": 4,
        "counts_as_owned_checkpoint": False,
        "counts_as_sufficient_pretraining": False,
        "counts_as_capability_evidence": False,
        "counts_as_full_ember_completion": False,
    }
