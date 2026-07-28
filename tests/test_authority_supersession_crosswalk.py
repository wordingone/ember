from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "verify_authority_supersession_crosswalk.py"
SPEC = importlib.util.spec_from_file_location("authority_crosswalk", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def canonical_sha256(payload: dict) -> str:
    body = copy.deepcopy(payload)
    body.pop("crosswalk_sha256", None)
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def write_authority(root: Path) -> tuple[str, str]:
    matrix = root / "docs" / "ember-authority-matrix.md"
    matrix.parent.mkdir(parents=True, exist_ok=True)
    matrix.write_text(
        "| discrepancy | disposition | enforced by | evidence/open question |\n"
        "|---|---|---|---|\n"
        "| D-001 | ENFORCED | GOAL.md | identity |\n"
        "| D-002 | HISTORICAL_ONLY | STATE.md | history |\n",
        encoding="utf-8",
    )
    milestone = root / "docs" / "roadmap" / "milestones" / "EMBER-00.md"
    milestone.parent.mkdir(parents=True, exist_ok=True)
    milestone.write_text("# EMBER-00\n", encoding="utf-8")
    evidence = root / "docs" / "legacy.md"
    evidence.write_text("legacy evidence\n", encoding="utf-8")
    return (
        hashlib.sha256(matrix.read_bytes()).hexdigest(),
        hashlib.sha256(evidence.read_bytes()).hexdigest(),
    )


def valid_payload(root: Path) -> dict:
    matrix_sha, evidence_sha = write_authority(root)
    payload = {
        "schema_version": "ember-authority-supersession-crosswalk-v1",
        "repository": "wordingone/ember",
        "source_commit": "a" * 40,
        "current_authority": {
            "matrix_path": "docs/ember-authority-matrix.md",
            "matrix_sha256": matrix_sha,
            "discrepancy_ids": ["D-001", "D-002"],
            "milestone_ids": ["EMBER-00"],
            "historical_terminal": "HISTORICAL_ORPHANED",
        },
        "source_registries": [
            {
                "registry_id": "ISSUE35-DEFECTS",
                "expected_source_ids": ["G-s41-numeric", "G-unrecovered-013"],
                "evidence": [
                    {"path": "docs/legacy.md", "sha256": evidence_sha},
                ],
            }
        ],
        "rows": [
            {
                "source_registry": "ISSUE35-DEFECTS",
                "source_id": "G-s41-numeric",
                "source_kind": "defect",
                "statement": "Registry count text diverged from the live registry.",
                "disposition": "SUPERSEDED",
                "targets": ["D-001", "EMBER-00"],
                "evidence": [
                    {"path": "docs/legacy.md", "sha256": evidence_sha},
                ],
                "completion_credit": False,
            },
            {
                "source_registry": "ISSUE35-DEFECTS",
                "source_id": "G-unrecovered-013",
                "source_kind": "defect",
                "statement": "Unrecovered source row 13; clause text is absent from public custody.",
                "disposition": "CUSTODY_GAP",
                "targets": [],
                "evidence": [
                    {"path": "docs/legacy.md", "sha256": evidence_sha},
                ],
                "completion_credit": False,
            },
        ],
    }
    payload["crosswalk_sha256"] = canonical_sha256(payload)
    return payload


def validate(root: Path, payload: dict) -> dict:
    return MODULE.validate_crosswalk(
        root, payload, expected_source_commit="a" * 40
    )


def resign(payload: dict) -> dict:
    payload["crosswalk_sha256"] = canonical_sha256(payload)
    return payload


def test_valid_crosswalk_preserves_custody_gap_without_completion(tmp_path: Path) -> None:
    result = validate(tmp_path, valid_payload(tmp_path))
    assert result["status"] == "PASS_WITH_CUSTODY_GAPS"
    assert result["row_count"] == 2
    assert result["custody_gap_count"] == 1


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda p: p.update({"extra": True}), "top-level fields"),
        (
            lambda p: p["rows"][0].update({"extra": True}),
            r"row.*fields",
        ),
        (
            lambda p: p["rows"][1].update(
                {"source_id": p["rows"][0]["source_id"]}
            ),
            "duplicate source row",
        ),
        (
            lambda p: p["rows"][0].update({"targets": ["D-999"]}),
            "unknown current target",
        ),
        (
            lambda p: p["rows"][0].update({"evidence": []}),
            "evidence",
        ),
        (
            lambda p: p["rows"][1].update({"completion_credit": True}),
            "completion credit",
        ),
        (
            lambda p: p["rows"].pop(),
            "unaccounted source ids",
        ),
    ],
)
def test_crosswalk_rejects_silent_loss_and_open_schema(
    tmp_path: Path, mutate, match: str
) -> None:
    payload = valid_payload(tmp_path)
    mutate(payload)
    resign(payload)
    with pytest.raises(MODULE.CrosswalkError, match=match):
        validate(tmp_path, payload)


def test_crosswalk_rejects_tampered_evidence_and_matrix(tmp_path: Path) -> None:
    payload = valid_payload(tmp_path)
    (tmp_path / "docs" / "legacy.md").write_text("changed\n", encoding="utf-8")
    with pytest.raises(MODULE.CrosswalkError, match="evidence hash"):
        validate(tmp_path, payload)

    payload = valid_payload(tmp_path)
    payload["current_authority"]["matrix_sha256"] = "0" * 64
    resign(payload)
    with pytest.raises(MODULE.CrosswalkError, match="matrix hash"):
        validate(tmp_path, payload)


def test_crosswalk_rejects_source_commit_and_self_hash_mismatch(
    tmp_path: Path,
) -> None:
    payload = valid_payload(tmp_path)
    with pytest.raises(MODULE.CrosswalkError, match="source commit"):
        MODULE.validate_crosswalk(
            tmp_path, payload, expected_source_commit="b" * 40
        )

    payload = valid_payload(tmp_path)
    payload["crosswalk_sha256"] = "0" * 64
    with pytest.raises(MODULE.CrosswalkError, match="crosswalk hash"):
        validate(tmp_path, payload)
