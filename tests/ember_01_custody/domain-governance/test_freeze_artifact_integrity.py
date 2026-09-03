# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Regression tests for receipt-pinned in-tree artifact re-verification."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
MODULE_PATH = ROOT / "src" / "ember" / "governance" / "scripts" / "ember_01_custody" / "freeze_artifact_integrity.py"


def load_module():
    spec = importlib.util.spec_from_file_location(
        "freeze_artifact_integrity", MODULE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8", newline="\n")


def test_matching_path_sha_pair_is_verified(tmp_path: Path) -> None:
    module = load_module()
    artifact = tmp_path / "data" / "artifact.bin"
    artifact.parent.mkdir()
    artifact.write_bytes(b"owned-bytes")
    receipt = tmp_path / "receipts" / "r.json"
    write_json(
        receipt, {"artifact": {"path": "data/artifact.bin", "sha256": digest(artifact)}}
    )

    report = module.scan_receipts(tmp_path, tmp_path / "receipts")

    assert report["summary"] == {
        "receipt_count": 1,
        "pin_count": 1,
        "verified_count": 1,
        "violation_count": 0,
    }
    assert report["goal_id"] == "EMBER-02"
    assert report["workstream_id"] == "EMBER-02A"
    assert (
        report["next_executed_outcome"]
        == "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
    )
    assert report["ticket"] == "FREEZE-ARTIFACT-INTEGRITY-ISSUE531"
    assert report["sha_convention"] == module.SHA_CONVENTION
    assert report["invariant_sha256"] == module.INVARIANT_SHA256
    assert report["pins"][0]["status"] == "VERIFIED"
    assert report["pins"][0]["field"] == "artifact.sha256"


def test_mismatch_and_missing_file_are_explicit(tmp_path: Path) -> None:
    module = load_module()
    artifact = tmp_path / "data" / "artifact.bin"
    artifact.parent.mkdir()
    artifact.write_bytes(b"actual")
    receipt = tmp_path / "receipts" / "r.json"
    write_json(
        receipt,
        {
            "mismatch": {"path": "data/artifact.bin", "sha256": "0" * 64},
            "missing": {"path": "data/missing.bin", "sha256": "1" * 64},
        },
    )

    report = module.scan_receipts(tmp_path, tmp_path / "receipts")

    rows = {row["field"]: row for row in report["pins"]}
    assert rows["mismatch.sha256"]["violations"] == ["SHA256_MISMATCH"]
    assert rows["mismatch.sha256"]["actual_sha256"] == digest(artifact)
    assert rows["missing.sha256"]["violations"] == ["FILE_MISSING"]
    assert rows["missing.sha256"]["actual_sha256"] is None


def test_valid_provenance_transition_replaces_stale_pin(tmp_path: Path) -> None:
    module = load_module()
    artifact = tmp_path / "data" / "artifact.bin"
    artifact.parent.mkdir()
    artifact.write_bytes(b"new")
    receipt = tmp_path / "receipts" / "r.json"
    write_json(
        receipt,
        {
            "artifact_path": "data/artifact.bin",
            "artifact_sha256": "0" * 64,
            "provenance_230": [
                {
                    "field": "artifact_sha256",
                    "old_artifact_sha256": "0" * 64,
                    "new_artifact_sha256": digest(artifact),
                }
            ],
        },
    )

    row = module.scan_receipts(tmp_path, tmp_path / "receipts")["pins"][0]

    assert row["status"] == "VERIFIED"
    assert row["expected_sha256"] == digest(artifact)
    assert row["pin_source"] == "provenance_transition"


def test_invalid_provenance_transition_does_not_suppress_mismatch(
    tmp_path: Path,
) -> None:
    module = load_module()
    artifact = tmp_path / "data" / "artifact.bin"
    artifact.parent.mkdir()
    artifact.write_bytes(b"actual")
    receipt = tmp_path / "receipts" / "r.json"
    write_json(
        receipt,
        {
            "artifact": {"path": "data/artifact.bin", "sha256": "0" * 64},
            "provenance_230": [
                {
                    "fields": ["artifact.sha256"],
                    "old": {"artifact.sha256": "0" * 64},
                    "new": {"artifact.sha256": "1" * 64},
                }
            ],
        },
    )

    row = module.scan_receipts(tmp_path, tmp_path / "receipts")["pins"][0]

    assert row["expected_sha256"] == "1" * 64
    assert row["pin_source"] == "provenance_transition"
    assert row["violations"] == ["SHA256_MISMATCH"]


def test_superseded_transition_is_not_current_authority(tmp_path: Path) -> None:
    module = load_module()
    artifact = tmp_path / "domains" / "model" / "tokenizer" / "tokenizer.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text('{"version":"1.0","truncation":null}', encoding="utf-8")
    receipt = tmp_path / "receipts" / "r.json"
    write_json(
        receipt,
        {
            "premises": {
                "tokenizer_json": {
                    "path": "domains/model/tokenizer/tokenizer.json",
                    "sha256": digest(artifact),
                }
            },
            "superseded_provenance_230": [
                {
                    "fields": ["premises.tokenizer_json.sha256"],
                    "new": {"tokenizer_json.sha256": "1" * 64},
                }
            ],
        },
    )

    row = module.scan_receipts(
        tmp_path,
        tmp_path / "receipts",
        format_probes={},
    )["pins"][0]

    assert row["expected_sha256"] == digest(artifact)
    assert row["pin_source"] == "receipt"
    assert row["status"] == "VERIFIED"


def test_tokenizer_format_failure_is_a_violation_even_when_hash_matches(
    tmp_path: Path,
) -> None:
    module = load_module()
    artifact = tmp_path / "domains" / "model" / "tokenizer" / "tokenizer.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text('{"not":"a-tokenizer"}', encoding="utf-8")
    receipt = tmp_path / "receipts" / "r.json"
    write_json(
        receipt,
        {"tokenizer": {"path": "domains/model/tokenizer/tokenizer.json", "sha256": digest(artifact)}},
    )

    row = module.scan_receipts(tmp_path, tmp_path / "receipts")["pins"][0]

    assert row["actual_sha256"] == digest(artifact)
    assert row["format_probe"]["kind"] == "tokenizer"
    assert row["format_probe"]["status"] == "FAIL"
    assert "FORMAT_INVALID" in row["violations"]


@pytest.mark.parametrize(
    ("payload", "expected_status"),
    [(b"PK\x03\x04rest", "PASS"), (b"not-a-pt", "FAIL")],
)
def test_pt_header_probe(payload: bytes, expected_status: str, tmp_path: Path) -> None:
    module = load_module()
    artifact = tmp_path / "models" / "checkpoint.pt"
    artifact.parent.mkdir()
    artifact.write_bytes(payload)
    receipt = tmp_path / "receipts" / "r.json"
    write_json(
        receipt,
        {"checkpoint": {"path": "models/checkpoint.pt", "sha256": digest(artifact)}},
    )

    row = module.scan_receipts(tmp_path, tmp_path / "receipts")["pins"][0]

    assert row["format_probe"] == {
        "kind": "pytorch_header",
        "status": expected_status,
    }
    assert ("FORMAT_INVALID" in row["violations"]) is (expected_status == "FAIL")


def test_receipt_name_resolves_inside_receipts_tree(tmp_path: Path) -> None:
    module = load_module()
    artifact = tmp_path / "receipts" / "nested" / "artifact.json"
    write_json(artifact, {"ok": True})
    receipt = tmp_path / "receipts" / "nested" / "r.json"
    write_json(
        receipt,
        {"upstream": {"name": "artifact.json", "sha256": digest(artifact)}},
    )

    row = module.scan_receipts(tmp_path, tmp_path / "receipts")["pins"][0]

    assert row["artifact_path"] == "receipts/nested/artifact.json"
    assert row["status"] == "VERIFIED"


def test_embedded_base64_body_is_verified_without_filesystem_lookup(
    tmp_path: Path,
) -> None:
    module = load_module()
    body = b'{"owned":"embedded"}\n'
    receipt = tmp_path / "receipts" / "raw-sources.json"
    write_json(
        receipt,
        {
            "entries": [
                {
                    "body_base64": base64.b64encode(body).decode("ascii"),
                    "byte_count": len(body),
                    "name": "comments-105-post.json",
                    "sha256": hashlib.sha256(body).hexdigest(),
                }
            ]
        },
    )

    report = module.scan_receipts(tmp_path, tmp_path / "receipts")

    assert report["summary"] == {
        "receipt_count": 1,
        "pin_count": 1,
        "verified_count": 1,
        "violation_count": 0,
    }
    row = report["pins"][0]
    assert row["field"] == "entries.0.sha256"
    assert row["raw_artifact_reference"] == "comments-105-post.json"
    assert row["artifact_path"] is None
    assert row["actual_sha256"] == hashlib.sha256(body).hexdigest()
    assert row["pin_source"] == "embedded_receipt"
    assert row["status"] == "VERIFIED"


@pytest.mark.parametrize(
    ("body_base64", "byte_count", "expected_sha256", "violation"),
    [
        ("***not-base64***", 4, hashlib.sha256(b"body").hexdigest(), "EMBEDDED_BASE64_INVALID"),
        (
            base64.b64encode(b"body").decode("ascii"),
            5,
            hashlib.sha256(b"body").hexdigest(),
            "EMBEDDED_BYTE_COUNT_MISMATCH",
        ),
        (
            base64.b64encode(b"body").decode("ascii"),
            4,
            "0" * 64,
            "SHA256_MISMATCH",
        ),
    ],
)
def test_embedded_base64_body_corruption_fails_closed(
    body_base64: str,
    byte_count: int,
    expected_sha256: str,
    violation: str,
    tmp_path: Path,
) -> None:
    module = load_module()
    receipt = tmp_path / "receipts" / "raw-sources.json"
    write_json(
        receipt,
        {
            "entries": [
                {
                    "body_base64": body_base64,
                    "byte_count": byte_count,
                    "name": "comments-105-post.json",
                    "sha256": expected_sha256,
                }
            ]
        },
    )

    row = module.scan_receipts(tmp_path, tmp_path / "receipts")["pins"][0]

    assert row["artifact_path"] is None
    assert row["status"] == "VIOLATION"
    assert row["violations"] == [violation]


def test_shard_name_resolves_through_declared_shard_directory(
    tmp_path: Path,
) -> None:
    module = load_module()
    receipt = tmp_path / "receipts" / "token-shards.json"
    write_json(
        receipt,
        {
            "shard_dir": "../shards-v0",
            "shards": [
                {
                    "name": "v0-00000.bin",
                    "sha256": "0" * 64,
                    "n_tokens": 1,
                }
            ],
        },
    )

    row = module.scan_receipts(tmp_path, tmp_path / "receipts")["pins"][0]

    assert row["artifact_path"] == "shards-v0/v0-00000.bin"
    assert row["raw_artifact_reference"] == "v0-00000.bin"
    assert row["violations"] == ["FILE_MISSING"]


@pytest.mark.parametrize(
    "shard_dir",
    [
        "../../outside",
        "C:/outside",
        "/outside",
    ],
)
def test_declared_shard_directory_cannot_escape_repository(
    shard_dir: str,
    tmp_path: Path,
) -> None:
    module = load_module()
    receipt = tmp_path / "receipts" / "token-shards.json"
    write_json(
        receipt,
        {
            "shard_dir": shard_dir,
            "shards": [
                {"name": "v0-00000.bin", "sha256": "0" * 64, "n_tokens": 1}
            ],
        },
    )

    row = module.scan_receipts(tmp_path, tmp_path / "receipts")["pins"][0]

    assert row["artifact_path"] is None
    assert row["violations"] == ["PATH_OUTSIDE_REPOSITORY"]


def test_windows_separators_are_normalized_for_repo_relative_paths(
    tmp_path: Path,
) -> None:
    module = load_module()
    artifact = tmp_path / "data" / "artifact.bin"
    artifact.parent.mkdir()
    artifact.write_bytes(b"actual")
    receipt = tmp_path / "receipts" / "r.json"
    write_json(
        receipt,
        {"artifact": {"path": r"data\artifact.bin", "sha256": digest(artifact)}},
    )

    row = module.scan_receipts(tmp_path, tmp_path / "receipts")["pins"][0]

    assert row["artifact_path"] == "data/artifact.bin"
    assert row["status"] == "VERIFIED"


def test_path_escape_is_refused_not_read(tmp_path: Path) -> None:
    module = load_module()
    receipt = tmp_path / "receipts" / "r.json"
    write_json(receipt, {"artifact": {"path": "../outside.bin", "sha256": "0" * 64}})

    row = module.scan_receipts(tmp_path, tmp_path / "receipts")["pins"][0]

    assert row["violations"] == ["PATH_OUTSIDE_REPOSITORY"]
    assert row["actual_sha256"] is None


@pytest.mark.parametrize(
    "raw_path",
    [r"C:\outside.bin", r"\\server\share\outside.bin", "/outside.bin"],
)
def test_absolute_paths_are_refused_not_read(
    raw_path: str,
    tmp_path: Path,
) -> None:
    module = load_module()
    receipt = tmp_path / "receipts" / "r.json"
    write_json(receipt, {"artifact": {"path": raw_path, "sha256": "0" * 64}})

    row = module.scan_receipts(tmp_path, tmp_path / "receipts")["pins"][0]
    assert row["violations"] == ["PATH_OUTSIDE_REPOSITORY"]


def test_cli_report_hash_binds_verifier_and_all_prior_fields(tmp_path: Path) -> None:
    module = load_module()
    artifact = tmp_path / "data" / "artifact.bin"
    artifact.parent.mkdir()
    artifact.write_bytes(b"actual")
    receipt = tmp_path / "receipts" / "r.json"
    write_json(
        receipt,
        {"artifact": {"path": "data/artifact.bin", "sha256": digest(artifact)}},
    )
    output = tmp_path / "report.json"

    exit_code = module.main(
        [
            "--root",
            str(tmp_path),
            "--receipts",
            str(receipt.parent),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    expected = report.pop("report_sha256")
    assert report["ts"] == report["captured_at"]
    assert "verifier_sha256" in report
    assert hashlib.sha256(module.canonical_json_bytes(report)).hexdigest() == expected


def test_cli_excludes_its_output_from_repeat_scans(tmp_path: Path) -> None:
    module = load_module()
    artifact = tmp_path / "data" / "artifact.bin"
    artifact.parent.mkdir()
    artifact.write_bytes(b"actual")
    receipts = tmp_path / "receipts"
    receipt = receipts / "r.json"
    write_json(
        receipt,
        {"artifact": {"path": "data/artifact.bin", "sha256": digest(artifact)}},
    )
    output = receipts / "freeze.json"
    arguments = [
        "--root",
        str(tmp_path),
        "--receipts",
        str(receipts),
        "--output",
        str(output),
    ]

    assert module.main(arguments) == 0
    first = json.loads(output.read_text(encoding="utf-8"))
    assert module.main(arguments) == 0
    second = json.loads(output.read_text(encoding="utf-8"))

    assert first["summary"] == second["summary"]
