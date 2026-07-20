# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ember_01_custody" / "compact_receipt.py"


def write_run(
    root: Path,
    stem: str,
    canonical: str = "c" * 64,
    transient: list | None = None,
    authority: dict | None = None,
) -> Path:
    receipt = root / f"{stem}.json"
    identity = {
        "authority": authority or {
            "goal_id": "EMBER-01",
            "workstream_id": "EMBER-01B",
            "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
        },
        "execution_id": hashlib.sha256(stem.encode("utf-8")).hexdigest()[:32],
        "source_commit": "a" * 40,
        "root_spec_sha256": "1" * 64,
        "benchmark_registry_sha256": "2" * 64,
        "issue_census_sha256": "3" * 64,
        "canonical_root_census_sha256": "4" * 64,
        "canonical_manifest_sha256": canonical,
        "summary": {"artifact_count": 7, "issue_row_count": 5},
        "benchmark_validation_errors": [],
        "issue_validation_errors": [],
        "contradiction_count": 2,
        "transient_contradictions": transient or [],
    }
    receipt.write_text(json.dumps({"run_identity": identity, "full": "stable"}), encoding="utf-8")
    sidecar = root / f"{stem}.sidecar.json"
    payload = {
        "schema": "ember-01-custody-run-sidecar-v1",
        "receipt_name": receipt.name,
        "receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
        "receipt_size_bytes": receipt.stat().st_size,
        "run_identity": identity,
    }
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    return sidecar


def run_compact(tmp_path: Path, first: Path, second: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--run-one-sidecar", str(first), "--run-two-sidecar", str(second), "--publication-sha", "b" * 40, "--output", str(tmp_path / "compact.json")],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_compact_receipt_binds_equal_canonical_runs(tmp_path: Path) -> None:
    result = run_compact(tmp_path, write_run(tmp_path, "one"), write_run(tmp_path, "two"))
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads((tmp_path / "compact.json").read_text(encoding="utf-8"))
    assert payload["canonical_output_byte_identical"] is True
    assert len(payload["full_receipts"]) == 2


def test_compact_receipt_reads_identity_from_large_receipts(tmp_path: Path) -> None:
    first = write_run(tmp_path, "one")
    second = write_run(tmp_path, "two")
    for stem in ("one", "two"):
        receipt = tmp_path / f"{stem}.json"
        payload = json.loads(receipt.read_text(encoding="utf-8"))
        payload["large"] = "€" * 300_000
        receipt.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        sidecar = tmp_path / f"{stem}.sidecar.json"
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        metadata["receipt_size_bytes"] = receipt.stat().st_size
        metadata["receipt_sha256"] = hashlib.sha256(receipt.read_bytes()).hexdigest()
        sidecar.write_text(json.dumps(metadata), encoding="utf-8")
    assert run_compact(tmp_path, first, second).returncode == 0


def test_compact_receipt_rejects_copied_receipt_as_second_run(tmp_path: Path) -> None:
    first = write_run(tmp_path, "one")
    second = write_run(tmp_path, "two")
    first_receipt = tmp_path / "one.json"
    second_receipt = tmp_path / "two.json"
    second_receipt.write_bytes(first_receipt.read_bytes())
    metadata = json.loads(second.read_text(encoding="utf-8"))
    metadata["receipt_size_bytes"] = second_receipt.stat().st_size
    metadata["receipt_sha256"] = hashlib.sha256(second_receipt.read_bytes()).hexdigest()
    metadata["run_identity"] = json.loads(first_receipt.read_text(encoding="utf-8"))["run_identity"]
    second.write_text(json.dumps(metadata), encoding="utf-8")
    result = run_compact(tmp_path, first, second)
    assert "distinct execution" in result.stdout


def test_compact_receipt_rejects_payload_drift_outside_identity(tmp_path: Path) -> None:
    first = write_run(tmp_path, "one")
    second = write_run(tmp_path, "two")
    receipt = tmp_path / "two.json"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["full"] = "drift"
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    metadata = json.loads(second.read_text(encoding="utf-8"))
    metadata["receipt_size_bytes"] = receipt.stat().st_size
    metadata["receipt_sha256"] = hashlib.sha256(receipt.read_bytes()).hexdigest()
    second.write_text(json.dumps(metadata), encoding="utf-8")
    assert "normalized receipt bytes mismatch" in run_compact(tmp_path, first, second).stdout




def test_compact_receipt_rejects_drift_torn_snapshot_and_receipt_tamper(tmp_path: Path) -> None:
    first = write_run(tmp_path, "one")
    second = write_run(tmp_path, "two", canonical="d" * 64)
    assert "run identity mismatch" in run_compact(tmp_path, first, second).stdout
    second = write_run(tmp_path, "two", transient=[{"code": "artifact_changed_after_hash"}])
    assert "transient snapshot contradiction" in run_compact(tmp_path, first, second).stdout
    second = write_run(tmp_path, "two")
    (tmp_path / "two.json").write_text("tampered", encoding="utf-8")
    assert "full receipt" in run_compact(tmp_path, first, second).stdout


def test_compact_receipt_rejects_self_attested_identity_and_reused_run(tmp_path: Path) -> None:
    first = write_run(tmp_path, "one")
    second = write_run(tmp_path, "two")
    sidecar = json.loads(second.read_text(encoding="utf-8"))
    sidecar["run_identity"]["canonical_manifest_sha256"] = "d" * 64
    second.write_text(json.dumps(sidecar), encoding="utf-8")
    assert "receipt identity mismatch" in run_compact(tmp_path, first, second).stdout
    assert "distinct" in run_compact(tmp_path, first, first).stdout


def test_compact_receipt_rejects_invalid_authority_hash_and_receipt_name(tmp_path: Path) -> None:
    first = write_run(tmp_path, "one")
    second = write_run(tmp_path, "two", authority={"goal_id": "WRONG", "workstream_id": "EMBER-01B"})
    assert "authority" in run_compact(tmp_path, first, second).stdout

    second = write_run(tmp_path, "two")
    sidecar = json.loads(second.read_text(encoding="utf-8"))
    sidecar["run_identity"]["root_spec_sha256"] = "not-a-hash"
    second.write_text(json.dumps(sidecar), encoding="utf-8")
    assert "root_spec_sha256" in run_compact(tmp_path, first, second).stdout

    second = write_run(tmp_path, "two")
    sidecar = json.loads(second.read_text(encoding="utf-8"))
    sidecar["receipt_name"] = "../two.json"
    second.write_text(json.dumps(sidecar), encoding="utf-8")
    assert "receipt_name" in run_compact(tmp_path, first, second).stdout
