# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import receipt_write  # noqa: E402


VALID = {
    "ticket": "ISSUE-378-VALID",
    "ts": "20260728T000000Z",
    "sha_convention": "bytes on disk as-is",
    "artifact_sha256": "a" * 64,
}


def test_valid_candidate_atomically_replaces_canonical_receipt(tmp_path: Path) -> None:
    destination = tmp_path / "receipt.json"
    destination.write_text('{"ticket": "OLD"}', encoding="utf-8")

    receipt_write.checked_write(str(destination), VALID)

    assert destination.read_bytes() == json.dumps(VALID, indent=2).encode("utf-8")
    assert not Path(str(destination) + ".INVALID.quarantine").exists()
    assert not list(tmp_path.glob(".receipt.json.*.tmp"))


def test_invalid_candidate_never_replaces_last_known_good_receipt(tmp_path: Path) -> None:
    destination = tmp_path / "receipt.json"
    original = json.dumps(VALID, indent=2).encode("utf-8")
    destination.write_bytes(original)

    invalid = {"ts": "20260728T000001Z", "n_rows": 3}
    with pytest.raises(ValueError, match="QUARANTINED"):
        receipt_write.checked_write(str(destination), invalid)

    assert destination.read_bytes() == original
    quarantine = Path(str(destination) + ".INVALID.quarantine")
    assert json.loads(quarantine.read_text(encoding="utf-8")) == invalid
    assert not list(tmp_path.glob(".receipt.json.*.tmp"))


def test_serializer_failure_never_exposes_partial_canonical_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "receipt.json"
    original = json.dumps(VALID, indent=2).encode("utf-8")
    destination.write_bytes(original)

    def partial_then_fail(obj, stream, *, indent):
        stream.write('{"ticket": "PARTIAL"')
        stream.flush()
        raise OSError("injected serializer failure")

    monkeypatch.setattr(receipt_write.json, "dump", partial_then_fail)

    with pytest.raises(OSError, match="injected serializer failure"):
        receipt_write.checked_write(str(destination), VALID)

    assert destination.read_bytes() == original
    assert not Path(str(destination) + ".INVALID.quarantine").exists()
    assert not list(tmp_path.glob(".receipt.json.*.tmp"))


def test_publication_failure_retains_valid_candidate_for_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "receipt.json"
    original = json.dumps({"ticket": "OLD"}, indent=2).encode("utf-8")
    destination.write_bytes(original)
    real_replace = receipt_write.os.replace

    def fail_canonical_publish(source, target):
        if Path(target) == destination:
            raise PermissionError("injected canonical publication failure")
        return real_replace(source, target)

    monkeypatch.setattr(receipt_write.os, "replace", fail_canonical_publish)

    with pytest.raises(PermissionError, match="PUBLISH_FAILED"):
        receipt_write.checked_write(str(destination), VALID)

    assert destination.read_bytes() == original
    retained = Path(str(destination) + ".PUBLISH_FAILED.quarantine")
    assert retained.read_bytes() == json.dumps(VALID, indent=2).encode("utf-8")
    assert not list(tmp_path.glob(".receipt.json.*.tmp"))


def test_quarantine_failure_retains_invalid_staging_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "receipt.json"
    original = json.dumps(VALID, indent=2).encode("utf-8")
    destination.write_bytes(original)
    invalid = {"ts": "20260728T000001Z", "n_rows": 3}
    quarantine = Path(str(destination) + ".INVALID.quarantine")
    real_replace = receipt_write.os.replace

    def fail_quarantine_publish(source, target):
        if Path(target) == quarantine:
            raise PermissionError("injected quarantine publication failure")
        return real_replace(source, target)

    monkeypatch.setattr(receipt_write.os, "replace", fail_quarantine_publish)

    with pytest.raises(PermissionError, match="staging retained"):
        receipt_write.checked_write(str(destination), invalid)

    assert destination.read_bytes() == original
    staging = list(tmp_path.glob(".receipt.json.*.tmp"))
    assert len(staging) == 1
    assert json.loads(staging[0].read_text(encoding="utf-8")) == invalid
