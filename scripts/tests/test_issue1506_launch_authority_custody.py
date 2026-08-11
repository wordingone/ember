# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import subprocess

import pytest


MODULE_PATH = Path(__file__).parents[1] / "mint_launch_authority.py"
SPEC = importlib.util.spec_from_file_location("mint_launch_authority", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
mint = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mint)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _packet(root: Path) -> dict[str, Path]:
    root.mkdir()
    values = {
        "certificate": ("certificate.json", b'{"certificate":"fresh"}\n'),
        "declaration_ledger": ("declaration-ledger.jsonl", b'{"row":1}\n'),
        "run_spec": ("run-spec.json", b'{"run_id":"run-1506"}\n'),
        "sha_binding_map": ("sha-binding-map.json", b'{"map":"closed"}\n'),
    }
    result = {}
    for key, (name, payload) in values.items():
        path = root / name
        path.write_bytes(payload)
        result[key] = path
    return result


def _repo(root: Path) -> Path:
    repo = root / "ember"
    historical = repo / "receipts" / "ember-02-launch-authority"
    historical.mkdir(parents=True)
    (historical / "certificate.json").write_bytes(b"historical-immutable\n")
    return repo


def test_external_publication_validates_before_atomic_publish_and_preserves_history(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    custody = tmp_path / "live-receipts"
    custody.mkdir()
    packet = _packet(tmp_path / "candidate")
    historical = repo / "receipts" / "ember-02-launch-authority" / "certificate.json"
    before = _sha(historical)
    validation_observations: list[tuple[bool, bool, bool]] = []

    def validate(certificate: Path, ledger: Path, run_spec: Path) -> None:
        validation_observations.append(
            (certificate.is_file(), ledger.is_file(), run_spec.is_file())
        )
        assert not (custody / "run-1506" / "launch-authority").exists()

    receipt = mint.publish_launch_authority(
        repo_root=repo,
        custody_root=custody,
        run_id="run-1506",
        validator=validate,
        **packet,
    )

    destination = custody / "run-1506" / "launch-authority"
    assert validation_observations == [(True, True, True)]
    assert receipt["custody_root"] == str(destination)
    assert receipt["training_executed"] is False
    assert _sha(historical) == before
    assert set(path.name for path in destination.iterdir()) == {
        *mint.FILES,
        "launch-authority-custody.json",
    }
    assert receipt["files"] == {name: _sha(destination / name) for name in mint.FILES}


def test_validation_refusal_leaves_no_destination_or_historical_mutation(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    custody = tmp_path / "live-receipts"
    custody.mkdir()
    packet = _packet(tmp_path / "candidate")
    historical = repo / "receipts" / "ember-02-launch-authority" / "certificate.json"
    before = historical.read_bytes()

    def refuse(*_paths: Path) -> None:
        raise ValueError("CERTIFICATE_INVALID")

    with pytest.raises(ValueError, match="CERTIFICATE_INVALID"):
        mint.publish_launch_authority(
            repo_root=repo,
            custody_root=custody,
            run_id="run-1506",
            validator=refuse,
            **packet,
        )

    assert not (custody / "run-1506" / "launch-authority").exists()
    assert historical.read_bytes() == before
    assert list(custody.iterdir()) == []


@pytest.mark.parametrize("inside", ["repo", "relative"])
def test_repository_or_relative_custody_is_refused_without_output(
    tmp_path: Path, inside: str
) -> None:
    repo = _repo(tmp_path)
    packet = _packet(tmp_path / "candidate")
    custody = repo / "live" if inside == "repo" else Path("relative-live")
    if custody.is_absolute():
        custody.mkdir()

    with pytest.raises(mint.PublicationRefusal):
        mint.publish_launch_authority(
            repo_root=repo,
            custody_root=custody,
            run_id="run-1506",
            validator=lambda *_: None,
            **packet,
        )

    assert not (repo / "live" / "run-1506").exists()


def test_existing_destination_is_never_overwritten(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    custody = tmp_path / "live-receipts"
    destination = custody / "run-1506" / "launch-authority"
    destination.mkdir(parents=True)
    sentinel = destination / "sentinel"
    sentinel.write_bytes(b"keep")
    packet = _packet(tmp_path / "candidate")

    with pytest.raises(mint.PublicationRefusal, match="DESTINATION_ALREADY_EXISTS"):
        mint.publish_launch_authority(
            repo_root=repo,
            custody_root=custody,
            run_id="run-1506",
            validator=lambda *_: None,
            **packet,
        )

    assert sentinel.read_bytes() == b"keep"


def test_fresh_execute_leaves_the_repository_clean(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=issue1506-test",
            "-c",
            "user.email=issue1506@example.invalid",
            "commit",
            "-q",
            "-m",
            "historical authority record",
        ],
        check=True,
    )
    custody = tmp_path / "live-receipts"
    custody.mkdir()
    packet = _packet(tmp_path / "candidate")

    mint.publish_launch_authority(
        repo_root=repo,
        custody_root=custody,
        run_id="run-1506",
        validator=lambda *_: None,
        **packet,
    )

    status = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert status.stdout == ""
