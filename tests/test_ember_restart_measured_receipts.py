# goal_id: EMBER-01
# workstream_id: EMBER-01A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Tests for checkpoint-bound measured receipt admission."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "ember_restart_measured_receipts.py"
CAPABILITIES = ("text", "image", "audio", "reasoning", "tool")
CHECKPOINT = "a" * 64
VERIFIER = "b" * 64


def write_case(root: Path, trusted: bool = True) -> tuple[Path, Path]:
    records = []
    for capability in CAPABILITIES:
        receipt = {
            "capability": capability,
            "result": "MEASURED",
            "subject_checkpoint_sha256": CHECKPOINT,
            "verifier_sha256": VERIFIER,
        }
        receipt_path = root / f"{capability}.json"
        receipt_path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
        records.append({
            "capability": capability,
            "benchmark_id": f"frozen-{capability}-v1",
            "receipt_path": receipt_path.name,
            "receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            "subject_checkpoint_sha256": CHECKPOINT,
        })
    manifest_path = root / "receipt-manifest.json"
    manifest_path.write_text(json.dumps({"measured_receipts": records}), encoding="utf-8")
    registry_path = root / "trusted-verifiers.json"
    registry_path.write_text(json.dumps({"trusted_verifier_sha256": [VERIFIER] if trusted else []}), encoding="utf-8")
    return manifest_path, registry_path


def run(manifest: Path, registry: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--receipt-manifest", str(manifest), "--trusted-verifier-registry", str(registry)],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
    )


def test_accepts_all_five_checkpoint_bound_measured_receipts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        manifest, registry = write_case(Path(tmp))
        result = run(manifest, registry)
    assert result.returncode == 0, result.stderr
    assert "EMBER_RESTART_MEASURED_RECEIPTS: VALID" in result.stdout


def test_rejects_verifier_not_in_external_registry() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        manifest, registry = write_case(Path(tmp), trusted=False)
        result = run(manifest, registry)
    assert result.returncode == 2
    assert "UNTRUSTED_VERIFIER: audio" in result.stderr
