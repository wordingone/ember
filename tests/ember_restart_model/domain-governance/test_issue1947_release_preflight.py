# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src" / "ember" / "governance" / "scripts"))

from issue1947_release_preflight import (  # noqa: E402
    ReleasePreflightRefusal,
    build_release_preflight,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_self_hashed(path: Path, payload: dict) -> None:
    payload = dict(payload)
    payload["self_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")


def _inputs(tmp_path: Path) -> tuple[dict, dict, dict, dict, dict]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    custody = tmp_path / "checkpoint-custody"
    custody.mkdir()
    checkpoint = custody / "checkpoint-manifest.json"
    shared = custody / "shared-model.pt"
    expert = custody / "expert-vision.pt"
    matrix = tmp_path / "matrix.json"
    analysis = tmp_path / "analysis.json"
    checkpoint.write_text("checkpoint", encoding="utf-8")
    shared.write_bytes(b"shared")
    expert.write_bytes(b"expert")
    recompute_receipt = tmp_path / "composition-recompute.json"
    _write_self_hashed(
        recompute_receipt,
        {
            "schema_version": "ember-issue2055-independent-recompute-v1",
            "result": "PASS",
        },
    )
    recompute_payload = json.loads(recompute_receipt.read_text(encoding="utf-8"))
    composition = tmp_path / "composition-terminal.json"
    _write_self_hashed(
        composition,
        {
            "schema_version": "c2-e-composition-statistics-v1",
            "result": "PASS",
            "issue": 2055,
            "independent_recomputation": {
                "result": "PASS",
                "receipt_raw_sha256": _sha(recompute_receipt),
                "receipt_self_sha256": recompute_payload["self_sha256"],
            },
            "control_summary": {
                "positive_passed": 8,
                "positive_total": 8,
                "planted_refused_as_named": 8,
                "planted_total": 8,
            },
        },
    )
    _write_self_hashed(
        matrix,
        {
            "schema_version": "ember-issue1964-current-protected-row-census-v1",
            "result": "PASS",
            "rows": [
                {"row_id": row_id}
                for row_id in (
                    "E-MATRIX-TEXT-LANGUAGE",
                    "E-MATRIX-IMAGE",
                    "E-MATRIX-AUDIO",
                    "E-MATRIX-IMAGE-TEXT",
                    "E-MATRIX-AUDIO-TEXT",
                    "E-MATRIX-IMAGE-AUDIO-TEXT",
                    "E-MATRIX-REASONING",
                    "E-MATRIX-TOOL-USE",
                    "E-MATRIX-ROUTING-PATHWAY",
                )
            ],
            "totality": {
                "census_family_count": 9,
                "required_family_count": 9,
                "duplicate_contract_count": 0,
                "duplicate_family_count": 0,
                "omitted_contract_ids": [],
            },
        },
    )
    matrix_payload = json.loads(matrix.read_text(encoding="utf-8"))
    _write_self_hashed(
        analysis,
        {
            "schema_version": "ember-issue2055-prospective-analysis-manifest-v2",
            "status": "FROZEN_BEFORE_TREATMENT_OUTPUTS",
            "authority": {
                "protected_row_census_raw_sha256": _sha(matrix),
                "protected_row_census_self_sha256": matrix_payload["self_sha256"],
            },
            "frozen_population": {
                "checkpoint_manifest_sha256": _sha(checkpoint),
            },
        },
    )
    designation = {
        "schema_version": "ember-issue1947-release-candidate-checkpoint-designation-v1",
        "result": "DESIGNATED",
        "candidate_id": "candidate-test",
        "candidate_custody": str(custody),
        "manifest": {
            "path": checkpoint.name,
            "bytes": checkpoint.stat().st_size,
            "raw_sha256": _sha(checkpoint),
        },
        "shards": [
            {"path": shared.name, "bytes": shared.stat().st_size, "raw_sha256": _sha(shared)},
            {"path": expert.name, "bytes": expert.stat().st_size, "raw_sha256": _sha(expert)},
        ],
        "byte_verification": {
            "manifest_match": True,
            "shards_verified": 2,
            "shards_matching_manifest": 2,
            "missing_shards": 0,
            "mismatched_shards": 0,
        },
        "designation_authority": {"integrator_mail_id": 12345, "verdict": "DESIGNATED"},
    }
    designation["self_sha256"] = hashlib.sha256(
        json.dumps(designation, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    composition_binding = {
        "path": str(composition),
        "raw_sha256": _sha(composition),
        "independent_recompute": {
            "path": str(recompute_receipt),
            "raw_sha256": _sha(recompute_receipt),
        },
    }
    matrix_binding = {"path": str(matrix), "raw_sha256": _sha(matrix)}
    analysis_binding = {"path": str(analysis), "raw_sha256": _sha(analysis)}
    execution_spec = tmp_path / "release-execution-spec.json"
    _write_self_hashed(
        execution_spec,
        {
            "schema_version": "ember-issue1947-release-execution-spec-v1",
            "rows": [
                {
                    "row_id": row_id,
                    "command": ["runner", row_id],
                    "result_path": f"results/{row_id}.json",
                    "threshold": 0.5,
                }
                for row_id in (
                    "E-MATRIX-TEXT-LANGUAGE",
                    "E-MATRIX-IMAGE",
                    "E-MATRIX-AUDIO",
                    "E-MATRIX-IMAGE-TEXT",
                    "E-MATRIX-AUDIO-TEXT",
                    "E-MATRIX-IMAGE-AUDIO-TEXT",
                    "E-MATRIX-REASONING",
                    "E-MATRIX-TOOL-USE",
                    "E-MATRIX-ROUTING-PATHWAY",
                )
            ],
        },
    )
    execution_spec_payload = json.loads(execution_spec.read_text(encoding="utf-8"))
    tiers = {}
    for tier, role in (
        ("pr", "mechanics_only"),
        ("scheduled", "family_smoke"),
        ("release", "full_matrix"),
    ):
        workflow = tmp_path / f"{tier}.yml"
        runner = tmp_path / f"{tier}-runner.py"
        protected = tmp_path / f"{tier}-protected.json"
        workflow.write_text(tier, encoding="utf-8")
        runner.write_text(role, encoding="utf-8")
        protected.write_text("protected", encoding="utf-8")
        tiers[tier] = {
            "role": role,
            "workflow": {"path": str(workflow), "raw_sha256": _sha(workflow)},
            "runner": {"path": str(runner), "raw_sha256": _sha(runner)},
            "protected_inputs": [
                {"path": str(protected), "raw_sha256": _sha(protected)}
            ],
            "checkpoint_manifest_raw_sha256": _sha(checkpoint),
            "fail_closed_missing_input": True,
            "triggers": {
                "pr": ["pull_request_paths_filtered", "workflow_dispatch"],
                "scheduled": ["schedule:23 10 * * *", "workflow_dispatch"],
                "release": ["workflow_dispatch"],
            }[tier],
            "runner_label": "ubuntu-latest",
            "timeout_minutes": {"pr": 20, "scheduled": 45, "release": 60}[tier],
            "artifact_retention_days": {"pr": 30, "scheduled": 30, "release": 90}[tier],
        }
    tiers["release"]["windows_loader_smoke_runner"] = "windows-latest"
    tiers["release"]["windows_loader_smoke_timeout_minutes"] = 25
    tiers["release"]["execution_spec"] = {
        "path": str(execution_spec),
        "raw_sha256": _sha(execution_spec),
        "self_sha256": execution_spec_payload["self_sha256"],
    }
    return designation, composition_binding, matrix_binding, analysis_binding, tiers


def test_positive_binds_all_three_tiers_and_checkpoint(tmp_path: Path) -> None:
    designation, composition, matrix, analysis, tiers = _inputs(tmp_path)
    receipt = build_release_preflight(designation, composition, matrix, analysis, tiers)
    assert receipt["result"] == "PASS"
    assert [row["tier"] for row in receipt["tiers"]] == ["pr", "scheduled", "release"]
    assert len(receipt["checkpoint_shards"]) == 2
    assert receipt["designation_authority"] == {"integrator_mail_id": 12345, "verdict": "DESIGNATED"}
    assert all(row["checkpoint_manifest_raw_sha256"] == designation["manifest"]["raw_sha256"] for row in receipt["tiers"])
    release = next(row for row in receipt["tiers"] if row["tier"] == "release")
    assert release["execution_spec"] == {
        "path": str(tmp_path / "release-execution-spec.json"),
        "bytes": (tmp_path / "release-execution-spec.json").stat().st_size,
        "raw_sha256": _sha(tmp_path / "release-execution-spec.json"),
        "self_sha256": tiers["release"]["execution_spec"]["self_sha256"],
        "schema_version": "ember-issue1947-release-execution-spec-v1",
    }
    self_sha256 = receipt.pop("self_sha256")
    assert self_sha256 == hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def test_missing_tier_refuses(tmp_path: Path) -> None:
    designation, composition, matrix, analysis, tiers = _inputs(tmp_path)
    tiers.pop("release")
    with pytest.raises(ReleasePreflightRefusal, match="MISSING_TIER:release"):
        build_release_preflight(designation, composition, matrix, analysis, tiers)


def test_checkpoint_identity_drift_refuses(tmp_path: Path) -> None:
    designation, composition, matrix, analysis, tiers = _inputs(tmp_path)
    tiers["scheduled"]["checkpoint_manifest_raw_sha256"] = "0" * 64
    with pytest.raises(ReleasePreflightRefusal, match="CHECKPOINT_IDENTITY_DRIFT:scheduled"):
        build_release_preflight(designation, composition, matrix, analysis, tiers)


def test_missing_or_corrupt_bound_input_refuses(tmp_path: Path) -> None:
    designation, composition, matrix, analysis, tiers = _inputs(tmp_path)
    tiers["pr"]["workflow"]["raw_sha256"] = "f" * 64
    with pytest.raises(ReleasePreflightRefusal, match="RAW_HASH_DRIFT:pr.workflow"):
        build_release_preflight(designation, composition, matrix, analysis, tiers)


def test_release_execution_spec_raw_and_self_hashes_are_required(tmp_path: Path) -> None:
    designation, composition, matrix, analysis, tiers = _inputs(tmp_path)
    tiers["release"]["execution_spec"]["raw_sha256"] = "f" * 64
    with pytest.raises(ReleasePreflightRefusal, match="RAW_HASH_DRIFT:release.execution_spec"):
        build_release_preflight(designation, composition, matrix, analysis, tiers)

    designation, composition, matrix, analysis, tiers = _inputs(tmp_path / "self")
    path = Path(tiers["release"]["execution_spec"]["path"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["self_sha256"] = "0" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")
    tiers["release"]["execution_spec"]["raw_sha256"] = _sha(path)
    with pytest.raises(ReleasePreflightRefusal, match="SELF_HASH_DRIFT:release.execution_spec"):
        build_release_preflight(designation, composition, matrix, analysis, tiers)


def test_release_workflow_routes_dispatch_inputs_through_step_environment() -> None:
    workflow = (
        ROOT / ".github/workflows/issue1947-protected-eval-release.yml"
    ).read_text(encoding="utf-8")
    for variable, input_name in (
        ("BUNDLE_PATH", "bundle_path"),
        ("DESIGNATION_MANIFEST_SHA256", "designation_receipt_raw_sha256"),
        ("MATRIX_SELF_SHA256", "matrix_self_sha256"),
        ("ANALYSIS_SELF_SHA256", "analysis_self_sha256"),
    ):
        assert f'{variable}: "${{{{ inputs.{input_name} }}}}"' in workflow
    assert '--bundle "$BUNDLE_PATH"' in workflow
    assert '${{ inputs.bundle_path }}' not in workflow.replace(
        'BUNDLE_PATH: "${{ inputs.bundle_path }}"', ""
    )

def test_tier_role_and_fail_closed_semantics_are_exact(tmp_path: Path) -> None:
    designation, composition, matrix, analysis, tiers = _inputs(tmp_path)
    tiers["pr"]["role"] = "full_matrix"
    with pytest.raises(ReleasePreflightRefusal, match="TIER_ROLE_DRIFT:pr"):
        build_release_preflight(designation, composition, matrix, analysis, tiers)
    designation, composition, matrix, analysis, tiers = _inputs(tmp_path / "second")
    tiers["release"]["fail_closed_missing_input"] = False
    with pytest.raises(ReleasePreflightRefusal, match="FAIL_OPEN_TIER:release"):
        build_release_preflight(designation, composition, matrix, analysis, tiers)


@pytest.mark.parametrize(
    ("case", "refusal"),
    [
        ("designation", "CHECKPOINT_NOT_DESIGNATED"),
        ("unexpected_tier", "UNEXPECTED_TIER:development"),
        ("protected_inputs", "MISSING_PROTECTED_INPUT:scheduled"),
        ("timeout", "INVALID_TIMEOUT_OR_ARTIFACT_RETENTION:release"),
        ("retention", "INVALID_TIMEOUT_OR_ARTIFACT_RETENTION:pr"),
        ("matrix_hash", "RAW_HASH_DRIFT:matrix"),
        ("analysis_missing", "MISSING_INPUT:analysis"),
    ],
)
def test_long_run_gate_failure_classes_are_preidentified(
    tmp_path: Path, case: str, refusal: str
) -> None:
    designation, composition, matrix, analysis, tiers = _inputs(tmp_path)
    if case == "designation":
        designation["result"] = "NOT_DESIGNATED"
    elif case == "unexpected_tier":
        tiers["development"] = dict(tiers["pr"])
    elif case == "protected_inputs":
        tiers["scheduled"]["protected_inputs"] = []
    elif case == "timeout":
        tiers["release"]["timeout_minutes"] = 0
    elif case == "retention":
        tiers["pr"]["artifact_retention_days"] = False
    elif case == "matrix_hash":
        matrix["raw_sha256"] = "a" * 64
    elif case == "analysis_missing":
        Path(analysis["path"]).unlink()
    with pytest.raises(ReleasePreflightRefusal, match=refusal):
        build_release_preflight(designation, composition, matrix, analysis, tiers)


@pytest.mark.parametrize(
    ("case", "refusal"),
    [
        ("trigger", "TRIGGER_DRIFT:scheduled"),
        ("runner", "NON_HOSTED_RUNNER_LABEL:pr"),
        ("windows", "NON_HOSTED_RUNNER_LABEL:release.windows_loader_smoke"),
    ],
)
def test_exact_integrator_workflow_rulings_fail_closed(tmp_path: Path, case: str, refusal: str) -> None:
    designation, composition, matrix, analysis, tiers = _inputs(tmp_path)
    if case == "trigger":
        tiers["scheduled"]["triggers"] = ["schedule:0 0 * * *"]
    elif case == "runner":
        tiers["pr"]["runner_label"] = "self-hosted"
    else:
        tiers["release"]["windows_loader_smoke_runner"] = "self-hosted"
    with pytest.raises(ReleasePreflightRefusal, match=refusal):
        build_release_preflight(designation, composition, matrix, analysis, tiers)


def test_composition_terminal_and_self_hashes_are_required(tmp_path: Path) -> None:
    designation, composition, matrix, analysis, tiers = _inputs(tmp_path)
    composition["raw_sha256"] = "e" * 64
    with pytest.raises(ReleasePreflightRefusal, match="RAW_HASH_DRIFT:composition_terminal"):
        build_release_preflight(designation, composition, matrix, analysis, tiers)
    designation, composition, matrix, analysis, tiers = _inputs(tmp_path / "self")
    payload = json.loads(Path(analysis["path"]).read_text(encoding="utf-8"))
    payload["self_sha256"] = "0" * 64
    Path(analysis["path"]).write_text(json.dumps(payload), encoding="utf-8")
    analysis["raw_sha256"] = _sha(Path(analysis["path"]))
    with pytest.raises(ReleasePreflightRefusal, match="SELF_HASH_DRIFT:analysis"):
        build_release_preflight(designation, composition, matrix, analysis, tiers)


def test_composition_recompute_receipt_must_exist_and_match_terminal(tmp_path: Path) -> None:
    designation, composition, matrix, analysis, tiers = _inputs(tmp_path)
    Path(composition["independent_recompute"]["path"]).write_text("{}", encoding="utf-8")
    with pytest.raises(ReleasePreflightRefusal, match="RAW_HASH_DRIFT:composition_recompute"):
        build_release_preflight(designation, composition, matrix, analysis, tiers)

    designation, composition, matrix, analysis, tiers = _inputs(tmp_path / "hash-mismatch")
    terminal = json.loads(Path(composition["path"]).read_text(encoding="utf-8"))
    terminal["independent_recomputation"]["receipt_raw_sha256"] = "0" * 64
    terminal.pop("self_sha256")
    terminal["self_sha256"] = hashlib.sha256(
        json.dumps(terminal, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    Path(composition["path"]).write_text(json.dumps(terminal), encoding="utf-8")
    composition["raw_sha256"] = _sha(Path(composition["path"]))
    with pytest.raises(ReleasePreflightRefusal, match="COMPOSITION_RECOMPUTE_BINDING_DRIFT"):
        build_release_preflight(designation, composition, matrix, analysis, tiers)


@pytest.mark.parametrize("case", ["missing", "duplicate", "reordered", "totality"])
def test_protected_matrix_requires_exact_nine_row_order_and_totality(
    tmp_path: Path, case: str
) -> None:
    designation, composition, matrix, analysis, tiers = _inputs(tmp_path)
    payload = json.loads(Path(matrix["path"]).read_text(encoding="utf-8"))
    payload.pop("self_sha256")
    if case == "missing":
        payload["rows"].pop()
    elif case == "duplicate":
        payload["rows"][-1] = dict(payload["rows"][0])
    elif case == "reordered":
        payload["rows"][0], payload["rows"][1] = payload["rows"][1], payload["rows"][0]
    elif case == "totality":
        payload["totality"]["required_family_count"] = 8
    payload["self_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    Path(matrix["path"]).write_text(json.dumps(payload), encoding="utf-8")
    matrix["raw_sha256"] = _sha(Path(matrix["path"]))
    with pytest.raises(ReleasePreflightRefusal, match="MATRIX_TOTALITY_DRIFT"):
        build_release_preflight(designation, composition, matrix, analysis, tiers)


@pytest.mark.parametrize("case", ["matrix_raw", "matrix_self", "checkpoint"])
def test_analysis_freeze_must_cross_bind_matrix_and_checkpoint(
    tmp_path: Path, case: str
) -> None:
    designation, composition, matrix, analysis, tiers = _inputs(tmp_path)
    payload = json.loads(Path(analysis["path"]).read_text(encoding="utf-8"))
    payload.pop("self_sha256")
    if case == "matrix_raw":
        payload["authority"]["protected_row_census_raw_sha256"] = "0" * 64
    elif case == "matrix_self":
        payload["authority"]["protected_row_census_self_sha256"] = "0" * 64
    elif case == "checkpoint":
        payload["frozen_population"]["checkpoint_manifest_sha256"] = "0" * 64
    payload["self_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    Path(analysis["path"]).write_text(json.dumps(payload), encoding="utf-8")
    analysis["raw_sha256"] = _sha(Path(analysis["path"]))
    with pytest.raises(ReleasePreflightRefusal, match="ANALYSIS_BINDING_DRIFT"):
        build_release_preflight(designation, composition, matrix, analysis, tiers)


@pytest.mark.parametrize(
    ("case", "refusal"),
    [
        ("designation_self", "SELF_HASH_DRIFT:designation"),
        ("authority", "DESIGNATION_AUTHORITY_NOT_GRANTED"),
        ("manifest_bytes", "BYTE_COUNT_DRIFT:checkpoint_manifest"),
        ("shard_hash", "RAW_HASH_DRIFT:checkpoint_shards\\[0\\]"),
        ("shard_missing", "MISSING_INPUT:checkpoint_shards\\[1\\]"),
        ("verification_count", "DESIGNATION_BYTE_VERIFICATION_DRIFT"),
        ("path_escape", "CHECKPOINT_PATH_ESCAPE:checkpoint_shards\\[0\\]"),
    ],
)
def test_designation_and_every_checkpoint_shard_fail_closed(
    tmp_path: Path, case: str, refusal: str
) -> None:
    designation, composition, matrix, analysis, tiers = _inputs(tmp_path)
    if case == "designation_self":
        designation["self_sha256"] = "0" * 64
    elif case == "authority":
        designation["designation_authority"] = {"integrator_mail_id": None, "verdict": "PENDING"}
    elif case == "manifest_bytes":
        designation["manifest"]["bytes"] += 1
    elif case == "shard_hash":
        designation["shards"][0]["raw_sha256"] = "0" * 64
    elif case == "shard_missing":
        (Path(designation["candidate_custody"]) / designation["shards"][1]["path"]).unlink()
    elif case == "verification_count":
        designation["byte_verification"]["shards_verified"] = 1
    elif case == "path_escape":
        designation["shards"][0]["path"] = "../outside.pt"
    if case != "designation_self":
        designation.pop("self_sha256")
        designation["self_sha256"] = hashlib.sha256(
            json.dumps(designation, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    with pytest.raises(ReleasePreflightRefusal, match=refusal):
        build_release_preflight(designation, composition, matrix, analysis, tiers)
