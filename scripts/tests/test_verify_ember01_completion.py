#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Focused regressions for the unified EMBER-01 completion runner."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import verify_ember01_completion as completion  # noqa: E402


def test_custody_legs_bind_census_to_remote_master_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []

    monkeypatch.setattr(
        completion,
        "git",
        lambda *_args: SimpleNamespace(stdout="a" * 40 + "\n"),
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
    )

    ref_index = captured.index("--public-master-ref")
    assert captured[ref_index + 1] == "refs/remotes/origin/master"


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
