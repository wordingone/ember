# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Consumer validator identities must be frozen before execution."""

from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCER_ROOT = REPO_ROOT / "scripts" / "ember_admission"
sys.path.insert(0, str(PRODUCER_ROOT))

import consumers  # noqa: E402


def _use_minimal_closures(
    monkeypatch: pytest.MonkeyPatch,
    repo: Path,
) -> None:
    monkeypatch.setattr(consumers, "REPO_ROOT", repo)
    monkeypatch.setattr(
        consumers,
        "CONSUMER_CLOSURE_RELATIVE_PATHS",
        {
            "identity": ("identity.py",),
            "restart": ("restart.py",),
        },
    )
    monkeypatch.setattr(
        consumers,
        "CONSUMER_ENTRYPOINTS",
        {"identity": "identity.py", "restart": "restart.py"},
    )


def test_consumer_validator_snapshot_binds_bytes_and_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = tmp_path / "identity.py"
    restart = tmp_path / "restart.py"
    identity.write_bytes(b"identity-v1")
    restart.write_bytes(b"restart-v1")
    monkeypatch.setattr(consumers, "IDENTITY_VALIDATOR", identity)
    monkeypatch.setattr(consumers, "RESTART_SEAT_CONSUMER", restart)
    _use_minimal_closures(monkeypatch, tmp_path)

    snapshots = consumers.snapshot_consumer_validators()

    assert snapshots["identity"].sha256 == hashlib.sha256(b"identity-v1").hexdigest()
    assert snapshots["restart"].sha256 == hashlib.sha256(b"restart-v1").hexdigest()
    assert consumers.verify_consumer_validators(snapshots)

    time.sleep(0.02)
    identity.write_bytes(b"identity-v2")
    identity.write_bytes(b"identity-v1")

    assert not consumers.verify_consumer_validators(snapshots)


def test_identity_consumer_executes_snapshotted_validator_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = tmp_path / "identity.py"
    restart = tmp_path / "restart.py"
    identity.write_text("print('snapshot-identity')\n", encoding="utf-8")
    restart.write_text("print('snapshot-restart')\n", encoding="utf-8")
    monkeypatch.setattr(consumers, "IDENTITY_VALIDATOR", identity)
    monkeypatch.setattr(consumers, "RESTART_SEAT_CONSUMER", restart)
    _use_minimal_closures(monkeypatch, tmp_path)
    snapshots = consumers.snapshot_consumer_validators()

    identity.write_text("print('swapped-live-identity')\n", encoding="utf-8")
    paths = {
        role: tmp_path / f"{role}.json"
        for role in (
            "artifact_bundle",
            "checkpoint",
            "identity_manifest",
            "identity_trusted_verifier_registry",
            "receipt_bundle",
            "tensor_hashes",
            "tensor_manifest",
        )
    }
    for path in paths.values():
        path.write_text("{}\n", encoding="utf-8")

    result = consumers.run_identity_consumer(paths, snapshots["identity"])

    assert result.returncode == 0
    assert result.stdout.strip() == "snapshot-identity"
    assert "swapped-live-identity" not in result.stdout


def test_restart_consumer_executes_snapshotted_validator_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = tmp_path / "identity.py"
    restart = tmp_path / "restart.py"
    identity.write_text("print('snapshot-identity')\n", encoding="utf-8")
    restart.write_text("print('snapshot-restart')\n", encoding="utf-8")
    monkeypatch.setattr(consumers, "IDENTITY_VALIDATOR", identity)
    monkeypatch.setattr(consumers, "RESTART_SEAT_CONSUMER", restart)
    _use_minimal_closures(monkeypatch, tmp_path)
    snapshots = consumers.snapshot_consumer_validators()

    restart.write_text("print('swapped-live-restart')\n", encoding="utf-8")
    manifest = tmp_path / "restart_run_manifest.json"
    registry = tmp_path / "restart_trusted_verifier_registry.json"
    manifest.write_text("{}\n", encoding="utf-8")
    registry.write_text("{}\n", encoding="utf-8")

    result = consumers.run_restart_consumer(
        {
            "restart_run_manifest": manifest,
            "restart_trusted_verifier_registry": registry,
        },
        snapshots["restart"],
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "snapshot-restart"
    assert "swapped-live-restart" not in result.stdout


def test_restart_consumer_executes_snapshotted_import_closure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    identity = repo / "scripts" / "ember_01_identity" / "validate_identity.py"
    restart = repo / "scripts" / "ember_restart" / "cli_seat.py"
    contract = repo / "scripts" / "ember_restart" / "contract.py"
    identity.parent.mkdir(parents=True)
    restart.parent.mkdir(parents=True)
    identity.write_text("print('identity')\n", encoding="utf-8")
    restart.write_text(
        "from contract import VALUE\nprint(VALUE)\n",
        encoding="utf-8",
    )
    contract.write_text("VALUE = 'snapshot-contract'\n", encoding="utf-8")
    monkeypatch.setattr(consumers, "REPO_ROOT", repo)
    monkeypatch.setattr(consumers, "IDENTITY_VALIDATOR", identity)
    monkeypatch.setattr(consumers, "RESTART_SEAT_CONSUMER", restart)
    monkeypatch.setattr(
        consumers,
        "CONSUMER_CLOSURE_RELATIVE_PATHS",
        {
            "identity": ("scripts/ember_01_identity/validate_identity.py",),
            "restart": (
                "src/ember/governance/scripts/ember_restart/cli_seat.py",
                "src/ember/governance/scripts/ember_restart/contract.py",
            ),
        },
    )
    monkeypatch.setattr(
        consumers, "CONSUMER_ENTRYPOINTS",
        {"identity": identity.relative_to(repo).as_posix(),
         "restart": restart.relative_to(repo).as_posix()},
    )
    snapshots = consumers.snapshot_consumer_validators()
    contract.write_text("VALUE = 'swapped-live-contract'\n", encoding="utf-8")

    manifest = tmp_path / "restart_run_manifest.json"
    registry = tmp_path / "restart_trusted_verifier_registry.json"
    manifest.write_text("{}\n", encoding="utf-8")
    registry.write_text("{}\n", encoding="utf-8")
    result = consumers.run_restart_consumer(
        {
            "restart_run_manifest": manifest,
            "restart_trusted_verifier_registry": registry,
        },
        snapshots["restart"],
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "snapshot-contract"
    assert "swapped-live-contract" not in result.stdout
