# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import hashlib
import importlib.util
import json
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
    binding_map = {key: f"governed-source:{key}" for key in mint.SHA_BINDING_KEYS}
    values = {
        "certificate": ("certificate.json", b'{"certificate":"fresh"}\n'),
        "declaration_ledger": ("declaration-ledger.jsonl", b'{"row":1}\n'),
        "run_spec": ("run-spec.json", b'{"run_id":"run-1506"}\n'),
        "sha_binding_map": (
            "sha-binding-map.json",
            (json.dumps(binding_map, sort_keys=True) + "\n").encode("utf-8"),
        ),
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


def test_malformed_sha_binding_map_is_refused_before_destination_mutation(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    custody = tmp_path / "live-receipts"
    custody.mkdir()
    packet = _packet(tmp_path / "candidate")
    packet["sha_binding_map"].write_bytes(b"not-json\n")

    with pytest.raises(mint.PublicationRefusal, match="SHA_BINDING_MAP_INVALID"):
        mint.publish_launch_authority(
            repo_root=repo,
            custody_root=custody,
            run_id="run-1506",
            validator=lambda *_: None,
            **packet,
        )

    assert not (custody / "run-1506").exists()
    assert list(custody.iterdir()) == []


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("missing", "SHA_BINDING_MAP_SCHEMA_MISMATCH"),
        ("extra", "SHA_BINDING_MAP_SCHEMA_MISMATCH"),
        ("blank", "SHA_BINDING_MAP_SOURCE_IDENTITY_INVALID"),
        ("duplicate", "SHA_BINDING_MAP_DUPLICATE_KEY"),
    ],
)
def test_sha_binding_map_schema_is_closed_and_nonempty_before_publication(
    tmp_path: Path,
    mutation: str,
    reason: str,
) -> None:
    repo = _repo(tmp_path)
    custody = tmp_path / "live-receipts"
    custody.mkdir()
    packet = _packet(tmp_path / "candidate")
    binding_map = {key: f"governed-source:{key}" for key in mint.SHA_BINDING_KEYS}
    if mutation == "missing":
        binding_map.pop(next(iter(mint.SHA_BINDING_KEYS)))
    elif mutation == "extra":
        binding_map["foreign_sha256"] = "governed-source:foreign"
    else:
        binding_map[next(iter(mint.SHA_BINDING_KEYS))] = "  "
    serialized = json.dumps(binding_map, sort_keys=True)
    if mutation == "duplicate":
        key = sorted(mint.SHA_BINDING_KEYS)[0]
        serialized = "{" + json.dumps(key) + ':"duplicate",' + serialized[1:]
    packet["sha_binding_map"].write_text(serialized + "\n", encoding="utf-8")

    with pytest.raises(mint.PublicationRefusal, match=reason):
        mint.publish_launch_authority(
            repo_root=repo,
            custody_root=custody,
            run_id="run-1506",
            validator=lambda *_: None,
            **packet,
        )

    assert not (custody / "run-1506").exists()
    assert list(custody.iterdir()) == []


def test_publisher_copies_the_exact_map_bytes_that_passed_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path)
    custody = tmp_path / "live-receipts"
    custody.mkdir()
    packet = _packet(tmp_path / "candidate")
    admitted = packet["sha_binding_map"].read_bytes()
    validate = mint._validate_sha_binding_map_bytes

    def validate_then_replace_source(raw: bytes) -> None:
        validate(raw)
        packet["sha_binding_map"].write_bytes(b"not-the-admitted-map\n")

    monkeypatch.setattr(
        mint,
        "_validate_sha_binding_map_bytes",
        validate_then_replace_source,
    )
    receipt = mint.publish_launch_authority(
        repo_root=repo,
        custody_root=custody,
        run_id="run-1506",
        validator=lambda *_: None,
        **packet,
    )

    published = custody / "run-1506" / "launch-authority" / "sha-binding-map.json"
    assert packet["sha_binding_map"].read_bytes() == b"not-the-admitted-map\n"
    assert published.read_bytes() == admitted
    assert receipt["files"]["sha-binding-map.json"] == hashlib.sha256(admitted).hexdigest()


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
