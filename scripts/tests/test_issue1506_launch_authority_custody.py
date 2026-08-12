# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _git(*args: str, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        check=True,
        capture_output=capture_output,
        text=True,
        shell=False,
        creationflags=NO_WINDOW,
    )


MODULE_PATH = Path(__file__).parents[1] / "mint_launch_authority.py"
SPEC = importlib.util.spec_from_file_location("mint_launch_authority", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
mint = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mint)
PUBLIC_PUBLISH = mint.publish_launch_authority
PUBLIC_REOPEN = mint.reopen_launch_authority
PUBLIC_MINT = mint.mint_and_publish_launch_authority
# Unit fixtures use intentionally minimal certificates.  Redirect only this
# imported test module to the private validation seam; public production APIs
# expose no validator override.
mint.publish_launch_authority = mint._publish_launch_authority
mint.reopen_launch_authority = mint._reopen_launch_authority


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_public_custody_apis_expose_no_alternate_validator_authority() -> None:
    # Read the unmodified public wrappers from the module globals: the aliases
    # above are test-local conveniences for minimal fixture validation.
    assert "validator" not in inspect.signature(PUBLIC_PUBLISH).parameters
    assert "validator" not in inspect.signature(PUBLIC_REOPEN).parameters
    assert "validator" not in inspect.signature(PUBLIC_MINT).parameters
    assert "binding_paths" not in inspect.signature(PUBLIC_MINT).parameters
    assert "closure_sha256" not in inspect.signature(PUBLIC_MINT).parameters


def test_default_external_bindings_are_environment_located_and_hash_pinned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    expected: dict[str, str] = {}
    for key, env_name in mint.EXTERNAL_BINDING_ENV.items():
        source = tmp_path / "external" / f"{key}.bin"
        source.parent.mkdir(exist_ok=True)
        source.write_bytes(f"governed-{key}\n".encode())
        monkeypatch.setenv(env_name, str(source))
        expected[key] = _sha(source)

    certificate = (
        repo
        / "receipts"
        / "ember-02-launch-authority"
        / "certificate.json"
    )
    certificate.parent.mkdir(parents=True, exist_ok=True)
    certificate.write_text(json.dumps(expected) + "\n", encoding="utf-8")

    paths = mint._default_binding_paths(repo)
    source_hashes = {key: _sha(paths[key]) for key in expected}
    mint._require_frozen_external_binding_hashes(repo, source_hashes)

    source_hashes[sorted(expected)[0]] = "f" * 64
    with pytest.raises(
        mint.PublicationRefusal, match="FROZEN_EXTERNAL_BINDING_HASH_MISMATCH"
    ):
        mint._require_frozen_external_binding_hashes(repo, source_hashes)


def test_default_external_binding_env_is_required_without_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    for env_name in mint.EXTERNAL_BINDING_ENV.values():
        monkeypatch.delenv(env_name, raising=False)
    first_env = mint.EXTERNAL_BINDING_ENV["tokenizer_sha256"]
    with pytest.raises(
        mint.PublicationRefusal,
        match=f"EXTERNAL_BINDING_ENV_MISSING:{first_env}",
    ):
        mint._default_binding_paths(repo)


def test_public_preminted_publisher_is_refused_without_output(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    custody = tmp_path / "live-receipts"
    custody.mkdir()
    packet = _packet(tmp_path / "candidate")

    with pytest.raises(mint.PublicationRefusal, match="PREMINTED_PUBLICATION_FORBIDDEN"):
        PUBLIC_PUBLISH(
            repo_root=repo,
            custody_root=custody,
            run_id="run-1506",
            **packet,
        )

    assert list(custody.iterdir()) == []


def _packet(root: Path) -> dict[str, Path]:
    root.mkdir()
    certificate = {key: hashlib.sha256(key.encode("utf-8")).hexdigest() for key in mint.SHA_BINDING_KEYS}
    certificate["certificate"] = "fresh"
    binding_map = {
        key: f"sha256:{certificate[key]};path:governed-source:{key}"
        for key in mint.SHA_BINDING_KEYS
    }
    values = {
        "certificate": (
            "certificate.json",
            (json.dumps(certificate, sort_keys=True) + "\n").encode("utf-8"),
        ),
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


def _fresh_mint_fixture(root: Path) -> tuple[Path, Path, Path, Path, dict[str, Path]]:
    repo = _repo(root)
    (repo / "source.py").write_bytes(b"source-before-validation\n")
    _git("init", "-q", str(repo))
    _git("-C", str(repo), "add", ".")
    _git(
        "-C",
        str(repo),
        "-c",
        "user.name=issue1506-test",
        "-c",
        "user.email=issue1506@example.invalid",
        "commit",
        "-q",
        "-m",
        "current launch source",
    )
    custody = root / "live-receipts"
    custody.mkdir()
    completion = root / "completion.json"
    completion.write_bytes(b'{"completion":"owned"}\n')
    training_verify = root / "training-verify.json"
    training_verify.write_bytes(b'{"ok":true}\n')
    binding_root = root / "bindings"
    binding_root.mkdir()
    binding_paths = {}
    for key in mint.SHA_BINDING_KEYS:
        path = binding_root / key
        path.write_bytes((key + "\n").encode("utf-8"))
        binding_paths[key] = path
    return repo, custody, completion, training_verify, binding_paths


def test_cockpit_has_no_tracked_or_standalone_leaf_launch_authority_path() -> None:
    repl_source = (
        Path(__file__).parents[2]
        / "tools"
        / "ember-cli"
        / "src"
        / "screens"
        / "repl.ts"
    ).read_text(encoding="utf-8")

    assert "EMBER_RUN_SPEC_PATH" not in repl_source
    assert '"receipts", "ember-02-launch-authority", "run-spec.json"' not in repl_source
    assert "EMBER_LAUNCH_AUTHORITY_CUSTODY_ROOT" in repl_source
    assert "EMBER_LAUNCH_AUTHORITY_RUN_ID" in repl_source


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
        receipt_path = certificate.parent / mint.RECEIPT_FILE
        receipt = mint._decode_closed_receipt(receipt_path.read_bytes())
        assert receipt["run_id"] == "run-1506"
        assert receipt["files"] == {
            name: _sha(certificate.parent / name) for name in mint.FILES
        }
        validation_observations.append(
            (certificate.is_file(), ledger.is_file(), run_spec.is_file())
        )
        destination_exists = (custody / "run-1506" / "launch-authority").exists()
        assert destination_exists is (len(validation_observations) == 2)

    receipt = mint.publish_launch_authority(
        repo_root=repo,
        custody_root=custody,
        run_id="run-1506",
        validator=validate,
        **packet,
    )

    destination = custody / "run-1506" / "launch-authority"
    assert validation_observations == [(True, True, True), (True, True, True)]
    assert receipt["custody_root"] == str(destination)
    assert receipt["training_executed"] is False
    assert _sha(historical) == before
    assert set(path.name for path in destination.iterdir()) == {
        *mint.FILES,
        "launch-authority-custody.json",
    }
    assert receipt["files"] == {name: _sha(destination / name) for name in mint.FILES}


def test_shared_reopener_refuses_published_tamper_and_closed_schema_drift(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
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
    destination = custody / "run-1506" / "launch-authority"

    accepted = mint.reopen_launch_authority(
        repo_root=repo,
        custody_root=custody,
        run_id="run-1506",
        validator=lambda *_: None,
    )
    assert accepted["files"] == {name: _sha(destination / name) for name in mint.FILES}

    (destination / "sha-binding-map.json").write_bytes(b'{"substituted":true}\n')
    with pytest.raises(mint.PublicationRefusal, match="PUBLISHED_FILE_HASH_MISMATCH"):
        mint.reopen_launch_authority(
            repo_root=repo,
            custody_root=custody,
            run_id="run-1506",
            validator=lambda *_: None,
        )

    (destination / "sha-binding-map.json").write_bytes(packet["sha_binding_map"].read_bytes())
    (destination / "unexpected.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(mint.PublicationRefusal, match="CUSTODY_PACKET_SCHEMA_MISMATCH"):
        mint.reopen_launch_authority(
            repo_root=repo,
            custody_root=custody,
            run_id="run-1506",
            validator=lambda *_: None,
        )


def test_shared_reopener_refuses_noncanonical_or_claiming_receipt(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
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
    receipt_path = custody / "run-1506" / "launch-authority" / mint.RECEIPT_FILE
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["training_executed"] = True
    receipt_path.write_text(json.dumps(receipt) + "\n", encoding="utf-8")

    with pytest.raises(mint.PublicationRefusal, match="CUSTODY_RECEIPT_EXECUTION_CLAIM"):
        mint.reopen_launch_authority(
            repo_root=repo,
            custody_root=custody,
            run_id="run-1506",
            validator=lambda *_: None,
        )


def test_python_publisher_output_is_consumed_by_run_scoped_cli_locator(
    tmp_path: Path,
) -> None:
    """The real producer layout must feed the real /train default authority path."""

    repo = _repo(tmp_path)
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

    source_root = Path(__file__).parents[2]
    train_module = (
        source_root / "tools" / "ember-cli" / "src" / "commands" / "train.ts"
    ).resolve()
    preflight = "\n".join(
        [
            json.dumps(
                {"record": "preflight", "name": name, "status": "pass"},
                separators=(",", ":"),
            )
            for name in ("storage", "resource", "no-sub-3B", "recovery", "clean-genesis")
        ]
        + [
            json.dumps(
                {
                    "record": "launch-packet-summary",
                    "overall_ready": True,
                    "named_ember02_command": {
                        "command": "governed-placeholder-never-executed",
                        "library_entrypoint": "run_vertical_slice.py::run_semantic",
                    },
                },
                separators=(",", ":"),
            )
        ]
    )
    probe = tmp_path / "issue1506-cli-probe.ts"
    probe.write_text(
        "\n".join(
            [
                f'import {{ createTrainCommand }} from {json.dumps(train_module.as_uri())};',
                "const command = createTrainCommand({",
                f"  repoRoot: {json.dumps(str(repo))},",
                f"  launchAuthorityCustodyRoot: {json.dumps(str(custody))},",
                '  launchAuthorityRunId: "run-1506",',
                f"  runLaunchPacket: () => ({{ status: 0, stdout: {json.dumps(preflight)} }}),",
                "});",
                "const result = await command.execute('', {",
                '  sessionId: "issue1506-cross-language",',
                '  mode: "test",',
                f"  cwd: {json.dumps(str(repo))},",
                "});",
                "console.log(JSON.stringify(result));",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.pop("EMBER_LAUNCH_AUTHORITY_ROOT", None)
    environment.pop("EMBER_LAUNCH_AUTHORITY_CUSTODY_ROOT", None)
    environment.pop("EMBER_LAUNCH_AUTHORITY_RUN_ID", None)
    bun = shutil.which("bun")
    assert bun is not None, "bun is required for the producer-to-consumer integration"
    if os.name == "nt" and bun.lower().endswith(".ps1"):
        bun = str(Path(bun).parent / "node_modules" / "bun" / "bin" / "bun.exe")
    completed = subprocess.run(
        [bun, str(probe)],
        cwd=source_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        shell=False,
        creationflags=NO_WINDOW,
        timeout=30,
    )
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result.get("exitCode") is None
    assert "OFFER " in result["message"]
    assert str(custody / "run-1506" / "launch-authority" / "certificate.json") in result[
        "message"
    ]


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
    binding_map = {
        key: f"sha256:{hashlib.sha256(key.encode('utf-8')).hexdigest()};path:governed-source:{key}"
        for key in mint.SHA_BINDING_KEYS
    }
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


def test_path_only_sha_binding_identity_is_refused_before_publication(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    custody = tmp_path / "live-receipts"
    custody.mkdir()
    packet = _packet(tmp_path / "candidate")
    binding_map = {key: f"governed-source:{key}" for key in mint.SHA_BINDING_KEYS}
    packet["sha_binding_map"].write_text(
        json.dumps(binding_map, sort_keys=True) + "\n", encoding="utf-8"
    )

    with pytest.raises(mint.PublicationRefusal, match="SHA_BINDING_MAP_SOURCE_IDENTITY_INVALID"):
        mint.publish_launch_authority(
            repo_root=repo,
            custody_root=custody,
            run_id="run-1506",
            validator=lambda *_: None,
            **packet,
        )

    assert list(custody.iterdir()) == []


def test_sha_binding_identity_digest_must_match_certificate_before_publication(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    custody = tmp_path / "live-receipts"
    custody.mkdir()
    packet = _packet(tmp_path / "candidate")
    binding_map = json.loads(packet["sha_binding_map"].read_text(encoding="utf-8"))
    key = sorted(binding_map)[0]
    binding_map[key] = f"sha256:{'f' * 64};path:governed-source:{key}"
    packet["sha_binding_map"].write_text(
        json.dumps(binding_map, sort_keys=True) + "\n", encoding="utf-8"
    )

    with pytest.raises(
        mint.PublicationRefusal, match="SHA_BINDING_MAP_CERTIFICATE_HASH_MISMATCH"
    ):
        mint.publish_launch_authority(
            repo_root=repo,
            custody_root=custody,
            run_id="run-1506",
            validator=lambda *_: None,
            **packet,
        )

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


@pytest.mark.parametrize("inside", ["repo", "relative", "dot-segment"])
def test_repository_or_relative_custody_is_refused_without_output(
    tmp_path: Path, inside: str
) -> None:
    repo = _repo(tmp_path)
    packet = _packet(tmp_path / "candidate")
    custody = (
        repo / "live"
        if inside == "repo"
        else Path("relative-live")
        if inside == "relative"
        else tmp_path / "live-receipts" / ".." / "live-receipts"
    )
    if inside == "dot-segment":
        (tmp_path / "live-receipts").mkdir()
    if custody.is_absolute() and inside != "dot-segment":
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


def test_concurrent_empty_destination_is_not_replaced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path)
    custody = tmp_path / "live-receipts"
    custody.mkdir()
    packet = _packet(tmp_path / "candidate")
    destination_parent = custody / "run-1506"
    destination = custody / "run-1506" / "launch-authority"
    sentinel = destination_parent / "foreign-owner"
    atomic_publish = mint._atomic_publish_no_replace

    def create_foreign_destination_at_publish(source: Path, target: Path) -> None:
        assert target == destination_parent
        assert (source / "launch-authority" / mint.RECEIPT_FILE).is_file()
        destination_parent.mkdir(parents=True)
        sentinel.write_bytes(b"foreign")
        atomic_publish(source, target)

    monkeypatch.setattr(mint, "_atomic_publish_no_replace", create_foreign_destination_at_publish)
    with pytest.raises(mint.PublicationRefusal, match="DESTINATION_ALREADY_EXISTS"):
        mint.publish_launch_authority(
            repo_root=repo,
            custody_root=custody,
            run_id="run-1506",
            validator=lambda *_: None,
            **packet,
        )

    assert sentinel.read_bytes() == b"foreign"
    assert set(destination_parent.iterdir()) == {sentinel}
    assert not destination.exists()
    assert not list(custody.glob(".issue1506-*.staging"))


def test_fresh_execute_leaves_the_repository_clean(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _git("init", "-q", str(repo))
    _git("-C", str(repo), "add", ".")
    _git(
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

    status = _git("-C", str(repo), "status", "--porcelain", capture_output=True)
    assert status.stdout == ""


def test_fresh_mint_builds_current_closure_bound_packet_without_caller_packet(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    _git("init", "-q", str(repo))
    _git("-C", str(repo), "add", ".")
    _git(
        "-C",
        str(repo),
        "-c",
        "user.name=issue1506-test",
        "-c",
        "user.email=issue1506@example.invalid",
        "commit",
        "-q",
        "-m",
        "current launch source",
    )
    head = _git("-C", str(repo), "rev-parse", "HEAD", capture_output=True).stdout.strip()
    custody = tmp_path / "live-receipts"
    custody.mkdir()
    completion = tmp_path / "completion.json"
    completion.write_bytes(b'{"completion":"owned"}\n')
    training_verify = tmp_path / "training-verify.json"
    training_verify.write_bytes(b'{"ok":true}\n')
    binding_root = tmp_path / "bindings"
    binding_root.mkdir()
    binding_paths: dict[str, Path] = {}
    for key in mint.SHA_BINDING_KEYS:
        path = binding_root / key
        path.write_bytes((key + "\n").encode("utf-8"))
        binding_paths[key] = path

    observations: list[dict[str, object]] = []

    def validate(certificate: Path, ledger: Path, run_spec: Path) -> None:
        cert = json.loads(certificate.read_text(encoding="utf-8"))
        spec = json.loads(run_spec.read_text(encoding="utf-8"))
        observations.append({"certificate": cert, "run_spec": spec})
        assert cert["public_master_sha"] == head
        assert cert["closure_sha256"] == "a" * 64
        assert cert["completion_receipt_sha256"] == _sha(completion)
        assert spec["training_verify_receipt_path"] == str(training_verify.resolve())
        assert spec["training_verify_receipt_sha256"] == _sha(training_verify)
        assert spec["run_id"] == "fresh-1506"
        assert ledger.read_text(encoding="utf-8").count("\n") == 1

    receipt = mint._mint_and_publish_launch_authority(
        repo_root=repo,
        custody_root=custody,
        run_id="fresh-1506",
        training_verify_receipt=training_verify,
        completion_receipt=completion,
        binding_paths=binding_paths,
        closure_sha256="a" * 64,
        validator=validate,
        declared_at_utc="2026-08-11T00:00:00Z",
    )

    assert len(observations) == 2
    assert receipt["training_executed"] is False
    destination = custody / "fresh-1506" / "launch-authority"
    assert set(path.name for path in destination.iterdir()) == {
        *mint.FILES,
        mint.RECEIPT_FILE,
    }
    assert json.loads((destination / "certificate.json").read_text(encoding="utf-8"))[
        "public_master_sha"
    ] == head
    assert _git("-C", str(repo), "status", "--porcelain", capture_output=True).stdout == ""


def test_fresh_mint_refuses_source_binding_drift_before_atomic_publish(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    _git("init", "-q", str(repo))
    _git("-C", str(repo), "add", ".")
    _git(
        "-C",
        str(repo),
        "-c",
        "user.name=issue1506-test",
        "-c",
        "user.email=issue1506@example.invalid",
        "commit",
        "-q",
        "-m",
        "current launch source",
    )
    custody = tmp_path / "live-receipts"
    custody.mkdir()
    completion = tmp_path / "completion.json"
    completion.write_bytes(b'{"completion":"owned"}\n')
    training_verify = tmp_path / "training-verify.json"
    training_verify.write_bytes(b'{"ok":true}\n')
    binding_root = tmp_path / "bindings"
    binding_root.mkdir()
    binding_paths: dict[str, Path] = {}
    for key in mint.SHA_BINDING_KEYS:
        path = binding_root / key
        path.write_bytes((key + "\n").encode("utf-8"))
        binding_paths[key] = path
    changed = binding_paths[sorted(binding_paths)[0]]

    def validate_then_drift(*_paths: Path) -> None:
        changed.write_bytes(b"changed-after-mint\n")

    with pytest.raises(mint.PublicationRefusal, match="MINT_SOURCE_BINDING_CHANGED"):
        mint._mint_and_publish_launch_authority(
            repo_root=repo,
            custody_root=custody,
            run_id="fresh-1506",
            training_verify_receipt=training_verify,
            completion_receipt=completion,
            binding_paths=binding_paths,
            closure_sha256="a" * 64,
            validator=validate_then_drift,
            declared_at_utc="2026-08-11T00:00:00Z",
        )

    assert not (custody / "fresh-1506").exists()


@pytest.mark.parametrize("drift_kind", ["tracked", "untracked", "head", "closure"])
def test_fresh_mint_final_fence_refuses_post_validation_repository_drift(
    tmp_path: Path,
    drift_kind: str,
) -> None:
    repo, custody, completion, training_verify, binding_paths = _fresh_mint_fixture(
        tmp_path
    )
    closure = ["a" * 64]
    validator_calls = 0

    def validate_then_drift(*_paths: Path) -> None:
        nonlocal validator_calls
        validator_calls += 1
        if validator_calls != 1:
            return
        if drift_kind == "tracked":
            (repo / "source.py").write_bytes(b"source-after-validation\n")
        elif drift_kind == "untracked":
            (repo / "post-validation-untracked").write_bytes(b"untracked\n")
        elif drift_kind == "head":
            _git(
                "-C",
                str(repo),
                "-c",
                "user.name=issue1506-test",
                "-c",
                "user.email=issue1506@example.invalid",
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                "post-validation head drift",
            )
        else:
            closure[0] = "b" * 64

    expected = {
        "tracked": "REPOSITORY_NOT_CLEAN",
        "untracked": "REPOSITORY_NOT_CLEAN",
        "head": "MINT_REPOSITORY_HEAD_CHANGED",
        "closure": "MINT_LIVE_CLOSURE_CHANGED",
    }[drift_kind]
    with pytest.raises(mint.PublicationRefusal, match=expected):
        mint._mint_and_publish_launch_authority(
            repo_root=repo,
            custody_root=custody,
            run_id=f"fresh-1506-{drift_kind}",
            training_verify_receipt=training_verify,
            completion_receipt=completion,
            binding_paths=binding_paths,
            closure_sha256="a" * 64,
            closure_reader=lambda _repo: closure[0],
            validator=validate_then_drift,
            declared_at_utc="2026-08-11T00:00:00Z",
        )

    assert list(custody.iterdir()) == []


@pytest.mark.parametrize("binding_key", sorted(mint.SHA_BINDING_KEYS))
def test_fresh_mint_final_fence_refuses_each_post_validation_binding_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    binding_key: str,
) -> None:
    repo, custody, completion, training_verify, binding_paths = _fresh_mint_fixture(
        tmp_path
    )
    private_publish = mint._publish_launch_authority

    def publish_with_post_validation_drift(**kwargs: object) -> dict[str, object]:
        final_fence = kwargs["final_fence"]
        assert callable(final_fence)

        def drift_then_fence() -> None:
            binding_paths[binding_key].write_bytes(b"changed-after-validation\n")

            final_fence()

        kwargs["final_fence"] = drift_then_fence
        return private_publish(**kwargs)

    monkeypatch.setattr(mint, "_publish_launch_authority", publish_with_post_validation_drift)

    with pytest.raises(mint.PublicationRefusal, match="MINT_SOURCE_BINDING_CHANGED"):
        mint._mint_and_publish_launch_authority(
            repo_root=repo,
            custody_root=custody,
            run_id=f"fresh-1506-{binding_key.removesuffix('_sha256')}",
            training_verify_receipt=training_verify,
            completion_receipt=completion,
            binding_paths=binding_paths,
            closure_sha256="a" * 64,
            closure_reader=lambda _repo: "a" * 64,
            validator=lambda *_paths: None,
            declared_at_utc="2026-08-11T00:00:00Z",
        )

    assert list(custody.iterdir()) == []


@pytest.mark.parametrize(
    ("receipt_kind", "reason"),
    [
        ("training", "MINT_TRAINING_VERIFY_RECEIPT_CHANGED"),
        ("completion", "MINT_COMPLETION_RECEIPT_CHANGED"),
    ],
)
def test_fresh_mint_final_fence_refuses_each_external_receipt_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    receipt_kind: str,
    reason: str,
) -> None:
    repo, custody, completion, training_verify, binding_paths = _fresh_mint_fixture(
        tmp_path
    )
    private_publish = mint._publish_launch_authority

    def publish_with_post_validation_drift(**kwargs: object) -> dict[str, object]:
        final_fence = kwargs["final_fence"]
        assert callable(final_fence)

        def drift_then_fence() -> None:
            target = training_verify if receipt_kind == "training" else completion
            target.write_bytes(b"changed-after-validation\n")
            final_fence()

        kwargs["final_fence"] = drift_then_fence
        return private_publish(**kwargs)

    monkeypatch.setattr(mint, "_publish_launch_authority", publish_with_post_validation_drift)

    with pytest.raises(mint.PublicationRefusal, match=reason):
        mint._mint_and_publish_launch_authority(
            repo_root=repo,
            custody_root=custody,
            run_id=f"fresh-1506-{receipt_kind}-receipt",
            training_verify_receipt=training_verify,
            completion_receipt=completion,
            binding_paths=binding_paths,
            closure_sha256="a" * 64,
            closure_reader=lambda _repo: "a" * 64,
            validator=lambda *_paths: None,
            declared_at_utc="2026-08-11T00:00:00Z",
        )

    assert list(custody.iterdir()) == []


@pytest.mark.parametrize(
    "source_kind",
    ["binding", "training", "completion"],
)
def test_fresh_mint_final_fence_reopens_source_identity_before_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_kind: str,
) -> None:
    repo, custody, completion, training_verify, binding_paths = _fresh_mint_fixture(
        tmp_path
    )
    private_publish = mint._publish_launch_authority
    regular_source = mint._regular_source
    fence_active = False
    binding_key = sorted(mint.SHA_BINDING_KEYS)[0]
    target = {
        "binding": binding_paths[binding_key],
        "training": training_verify,
        "completion": completion,
    }[source_kind]
    reason = {
        "binding": f"{binding_key.upper()}_REPARSE_COMPONENT",
        "training": "TRAINING_VERIFY_RECEIPT_REPARSE_COMPONENT",
        "completion": "COMPLETION_RECEIPT_REPARSE_COMPONENT",
    }[source_kind]

    def refuse_reparse_at_final_fence(path: Path, label: str) -> Path:
        if fence_active and Path(path) == target:
            raise mint.PublicationRefusal(reason)
        return regular_source(path, label)

    def publish_with_identity_substitution(**kwargs: object) -> dict[str, object]:
        final_fence = kwargs["final_fence"]
        assert callable(final_fence)

        def substitute_then_fence() -> None:
            nonlocal fence_active
            fence_active = True
            final_fence()

        kwargs["final_fence"] = substitute_then_fence
        return private_publish(**kwargs)

    monkeypatch.setattr(mint, "_regular_source", refuse_reparse_at_final_fence)
    monkeypatch.setattr(mint, "_publish_launch_authority", publish_with_identity_substitution)

    with pytest.raises(mint.PublicationRefusal, match=reason):
        mint._mint_and_publish_launch_authority(
            repo_root=repo,
            custody_root=custody,
            run_id=f"fresh-1506-{source_kind}-identity",
            training_verify_receipt=training_verify,
            completion_receipt=completion,
            binding_paths=binding_paths,
            closure_sha256="a" * 64,
            closure_reader=lambda _repo: "a" * 64,
            validator=lambda *_paths: None,
            declared_at_utc="2026-08-11T00:00:00Z",
        )

    assert list(custody.iterdir()) == []


@pytest.mark.parametrize("foreign_mode", ["extra", "tampered"])
def test_failed_post_publish_reopen_never_deletes_foreign_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    foreign_mode: str,
) -> None:
    repo, custody, completion, training_verify, binding_paths = _fresh_mint_fixture(
        tmp_path
    )
    atomic_publish = mint._atomic_publish_no_replace

    def publish_then_foreign_write(source: Path, destination: Path) -> None:
        atomic_publish(source, destination)
        leaf = destination / "launch-authority"
        if foreign_mode == "extra":
            (leaf / "foreign.bin").write_bytes(b"not-owned\n")
        else:
            (leaf / "certificate.json").write_bytes(b"foreign-replacement\n")

    monkeypatch.setattr(mint, "_atomic_publish_no_replace", publish_then_foreign_write)
    expected = (
        "CUSTODY_PACKET_SCHEMA_MISMATCH"
        if foreign_mode == "extra"
        else "PUBLISHED_FILE_HASH_MISMATCH"
    )
    with pytest.raises(mint.PublicationRefusal, match=expected):
        mint._mint_and_publish_launch_authority(
            repo_root=repo,
            custody_root=custody,
            run_id="fresh-1506-foreign-race",
            training_verify_receipt=training_verify,
            completion_receipt=completion,
            binding_paths=binding_paths,
            closure_sha256="a" * 64,
            closure_reader=lambda _repo: "a" * 64,
            validator=lambda *_paths: None,
            declared_at_utc="2026-08-11T00:00:00Z",
        )

    destination = custody / "fresh-1506-foreign-race" / "launch-authority"
    if foreign_mode == "extra":
        assert (destination / "foreign.bin").read_bytes() == b"not-owned\n"
        assert (destination / "certificate.json").is_file()
    else:
        assert (destination / "certificate.json").read_bytes() == b"foreign-replacement\n"


def test_fresh_mint_refuses_a_dirty_repository_before_output(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _git("init", "-q", str(repo))
    _git("-C", str(repo), "add", ".")
    _git(
        "-C",
        str(repo),
        "-c",
        "user.name=issue1506-test",
        "-c",
        "user.email=issue1506@example.invalid",
        "commit",
        "-q",
        "-m",
        "current launch source",
    )
    (repo / "untracked-authority-drift").write_bytes(b"dirty\n")
    custody = tmp_path / "live-receipts"
    custody.mkdir()
    completion = tmp_path / "completion.json"
    completion.write_bytes(b'{"completion":"owned"}\n')
    training_verify = tmp_path / "training-verify.json"
    training_verify.write_bytes(b'{"ok":true}\n')
    binding_root = tmp_path / "bindings"
    binding_root.mkdir()
    binding_paths: dict[str, Path] = {}
    for key in mint.SHA_BINDING_KEYS:
        path = binding_root / key
        path.write_bytes((key + "\n").encode("utf-8"))
        binding_paths[key] = path

    with pytest.raises(mint.PublicationRefusal, match="REPOSITORY_NOT_CLEAN"):
        mint._mint_and_publish_launch_authority(
            repo_root=repo,
            custody_root=custody,
            run_id="fresh-1506",
            training_verify_receipt=training_verify,
            completion_receipt=completion,
            binding_paths=binding_paths,
            closure_sha256="a" * 64,
            validator=lambda *_: None,
            declared_at_utc="2026-08-11T00:00:00Z",
        )

    assert list(custody.iterdir()) == []
