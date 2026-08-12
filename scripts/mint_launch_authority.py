# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

"""Mint and atomically publish launch-authority bytes outside the repo.

The tracked ``receipts/ember-02-launch-authority`` tree is an immutable
historical record.  The public producer reopens a daemon-owned training verify
receipt, derives a fresh current-head/current-closure four-file packet from the
reviewed source bindings, validates it through the certified consumer, and
promotes it into run-scoped external custody.  It does not execute training.
"""

from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid
from collections.abc import Callable
from typing import Any


SCHEMA = "ember-launch-authority-external-custody-v1"
FILES = (
    "certificate.json",
    "declaration-ledger.jsonl",
    "run-spec.json",
    "sha-binding-map.json",
)
SHA_BINDING_KEYS = frozenset(
    {
        "benchmark_registry_sha256",
        "board_receipt_sha256",
        "checkout_sha256",
        "cli_binary_sha256",
        "config_sha256",
        "failure_class_ledger_sha256",
        "input_authority_sha256",
        "launch_packet_sha256",
        "root_summary_sha256",
        "seat_sha256",
        "subject_manifest_sha256",
        "tokenizer_sha256",
    }
)
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
RECEIPT_FILE = "launch-authority-custody.json"
RECEIPT_KEYS = frozenset(
    {"schema_version", "run_id", "custody_kind", "training_executed", "files"}
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SOURCE_IDENTITY = re.compile(r"^sha256:([0-9a-f]{64});path:(\S.*)$")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
EXTERNAL_BINDING_ENV = {
    "input_authority_sha256": "EMBER_GOAL_SELECTION",
    "seat_sha256": "EMBER_VERIFY_MODEL_CONFIG",
    "subject_manifest_sha256": "EMBER_VERIFY_CHECKPOINT_MANIFEST",
    "tokenizer_sha256": "EMBER_MODEL_IDENTITY_MANIFEST",
}


class PublicationRefusal(ValueError):
    """A fail-closed refusal raised before live custody is changed."""


def _atomic_publish_no_replace(source: Path, destination: Path) -> None:
    """Atomically rename one directory while refusing an existing destination."""

    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        move_file = kernel32.MoveFileExW
        move_file.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
        move_file.restype = ctypes.c_int
        if move_file(str(source), str(destination), 0) != 0:
            return
        error = ctypes.get_last_error()
        if error in {80, 183}:  # ERROR_FILE_EXISTS / ERROR_ALREADY_EXISTS
            raise PublicationRefusal("DESTINATION_ALREADY_EXISTS")
        raise OSError(error, os.strerror(error), str(destination))

    libc = ctypes.CDLL(None, use_errno=True)
    source_raw = os.fsencode(source)
    destination_raw = os.fsencode(destination)
    if sys.platform.startswith("linux"):
        rename = getattr(libc, "renameat2", None)
        if rename is None:
            raise PublicationRefusal("ATOMIC_NO_REPLACE_UNSUPPORTED")
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        result = rename(-100, source_raw, -100, destination_raw, 1)
    elif sys.platform == "darwin":
        rename = getattr(libc, "renamex_np", None)
        if rename is None:
            raise PublicationRefusal("ATOMIC_NO_REPLACE_UNSUPPORTED")
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(source_raw, destination_raw, 4)
    else:
        raise PublicationRefusal("ATOMIC_NO_REPLACE_UNSUPPORTED")
    if result == 0:
        return
    error = ctypes.get_errno()
    if error in {errno.EEXIST, errno.ENOTEMPTY}:
        raise PublicationRefusal("DESTINATION_ALREADY_EXISTS")
    raise OSError(error, os.strerror(error), str(destination))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_no_reparse_components(path: Path, label: str) -> None:
    if any(part in {".", ".."} for part in path.parts):
        raise PublicationRefusal(f"{label.upper()}_DOT_SEGMENT")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if not current.exists():
            continue
        stat = current.lstat()
        if current.is_symlink() or bool(
            getattr(stat, "st_file_attributes", 0) & 0x400
        ):
            raise PublicationRefusal(f"{label.upper()}_REPARSE_COMPONENT")


def _regular_source(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise PublicationRefusal(f"{label.upper()}_PATH_NOT_ABSOLUTE")
    _assert_no_reparse_components(path, label)
    if path.is_symlink() or not path.is_file():
        raise PublicationRefusal(f"{label.upper()}_NOT_REGULAR_FILE")
    return path.resolve(strict=True)


def _validate_sha_binding_map_bytes(raw: bytes) -> None:
    """Reopen the required disclosure map as a closed, nonempty schema.

    The certificate carries the authoritative digest values; this sidecar records the
    source identity from which each digest was derived. Publishing arbitrary bytes under
    its governed filename would make the four-file packet self-contradictory even though
    the three-file certified consumer remained green.
    """
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for key, value in pairs:
            if key in payload:
                raise PublicationRefusal("SHA_BINDING_MAP_DUPLICATE_KEY")
            payload[key] = value
        return payload

    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PublicationRefusal("SHA_BINDING_MAP_INVALID") from error
    if not isinstance(payload, dict) or set(payload) != SHA_BINDING_KEYS:
        raise PublicationRefusal("SHA_BINDING_MAP_SCHEMA_MISMATCH")
    if any(
        not isinstance(value, str) or SOURCE_IDENTITY.fullmatch(value) is None
        for value in payload.values()
    ):
        raise PublicationRefusal("SHA_BINDING_MAP_SOURCE_IDENTITY_INVALID")


def _validate_sha_binding_map_matches_certificate(
    map_raw: bytes, certificate_raw: bytes
) -> None:
    try:
        binding_map = json.loads(map_raw.decode("utf-8"))
        certificate = json.loads(certificate_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PublicationRefusal("SHA_BINDING_MAP_CERTIFICATE_INVALID") from error
    if not isinstance(binding_map, dict) or not isinstance(certificate, dict):
        raise PublicationRefusal("SHA_BINDING_MAP_CERTIFICATE_INVALID")
    for key, identity in binding_map.items():
        match = SOURCE_IDENTITY.fullmatch(identity) if isinstance(identity, str) else None
        if match is None or certificate.get(key) != match.group(1):
            raise PublicationRefusal("SHA_BINDING_MAP_CERTIFICATE_HASH_MISMATCH")


def _decode_closed_receipt(raw: bytes) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for key, value in pairs:
            if key in payload:
                raise PublicationRefusal("CUSTODY_RECEIPT_DUPLICATE_KEY")
            payload[key] = value
        return payload

    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PublicationRefusal("CUSTODY_RECEIPT_INVALID") from error
    if not isinstance(payload, dict) or set(payload) != RECEIPT_KEYS:
        raise PublicationRefusal("CUSTODY_RECEIPT_SCHEMA_MISMATCH")
    if payload.get("schema_version") != SCHEMA:
        raise PublicationRefusal("CUSTODY_RECEIPT_SCHEMA_MISMATCH")
    if payload.get("custody_kind") != "external-run-scoped":
        raise PublicationRefusal("CUSTODY_RECEIPT_CUSTODY_KIND_MISMATCH")
    if payload.get("training_executed") is not False:
        raise PublicationRefusal("CUSTODY_RECEIPT_EXECUTION_CLAIM")
    if not isinstance(payload.get("run_id"), str) or RUN_ID.fullmatch(payload["run_id"]) is None:
        raise PublicationRefusal("CUSTODY_RECEIPT_RUN_ID_INVALID")
    files = payload.get("files")
    if not isinstance(files, dict) or set(files) != set(FILES):
        raise PublicationRefusal("CUSTODY_RECEIPT_FILES_SCHEMA_MISMATCH")
    if any(not isinstance(value, str) or SHA256.fullmatch(value) is None for value in files.values()):
        raise PublicationRefusal("CUSTODY_RECEIPT_FILE_HASH_INVALID")
    canonical = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if canonical != raw:
        raise PublicationRefusal("CUSTODY_RECEIPT_NONCANONICAL")
    return payload


def _external_root(repo_root: Path, custody_root: Path) -> tuple[Path, Path]:
    repo = repo_root.resolve(strict=True)
    if not custody_root.is_absolute():
        raise PublicationRefusal("CUSTODY_ROOT_NOT_ABSOLUTE")
    _assert_no_reparse_components(custody_root, "custody_root")
    custody = custody_root.resolve(strict=True)
    try:
        custody.relative_to(repo)
    except ValueError:
        return repo, custody
    raise PublicationRefusal("CUSTODY_ROOT_INSIDE_REPOSITORY")


def _historical_hashes(repo: Path) -> dict[str, str]:
    root = repo / "receipts" / "ember-02-launch-authority"
    if not root.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def _git_output(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
        shell=False,
        creationflags=NO_WINDOW,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise PublicationRefusal("REPOSITORY_IDENTITY_UNREADABLE")
    return completed.stdout.strip()


def _require_clean_repository(repo: Path) -> None:
    completed = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=all"],
        check=False,
        capture_output=True,
        text=True,
        shell=False,
        creationflags=NO_WINDOW,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    )
    if completed.returncode != 0:
        raise PublicationRefusal("REPOSITORY_STATUS_UNREADABLE")
    if completed.stdout:
        raise PublicationRefusal("REPOSITORY_NOT_CLEAN")


def _external_binding_path(key: str) -> Path:
    env_name = EXTERNAL_BINDING_ENV[key]
    raw = os.environ.get(env_name)
    if raw is None or not raw.strip():
        raise PublicationRefusal(f"EXTERNAL_BINDING_ENV_MISSING:{env_name}")
    return Path(raw)


def _frozen_external_binding_hashes(repo: Path) -> dict[str, str]:
    certificate_path = _regular_source(
        repo
        / "receipts"
        / "ember-02-launch-authority"
        / "certificate.json",
        "frozen_launch_authority_certificate",
    )
    try:
        certificate = json.loads(certificate_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PublicationRefusal("FROZEN_EXTERNAL_BINDING_CERTIFICATE_INVALID") from error
    if not isinstance(certificate, dict):
        raise PublicationRefusal("FROZEN_EXTERNAL_BINDING_CERTIFICATE_INVALID")
    expected: dict[str, str] = {}
    for key in EXTERNAL_BINDING_ENV:
        digest = certificate.get(key)
        if not isinstance(digest, str) or SHA256.fullmatch(digest) is None:
            raise PublicationRefusal("FROZEN_EXTERNAL_BINDING_CERTIFICATE_INVALID")
        expected[key] = digest
    return expected


def _require_frozen_external_binding_hashes(
    repo: Path, source_hashes: dict[str, str]
) -> None:
    expected = _frozen_external_binding_hashes(repo)
    for key, digest in expected.items():
        if source_hashes.get(key) != digest:
            raise PublicationRefusal(f"FROZEN_EXTERNAL_BINDING_HASH_MISMATCH:{key}")


def _default_binding_paths(repo: Path) -> dict[str, Path]:
    """The reviewed producer-owned sources for the legacy certificate fields."""

    git_dir = Path(_git_output(repo, "rev-parse", "--absolute-git-dir"))
    return {
        "checkout_sha256": git_dir / "HEAD",
        "config_sha256": repo / "configs" / "ember-restart-3b.json",
        "tokenizer_sha256": _external_binding_path("tokenizer_sha256"),
        "input_authority_sha256": _external_binding_path("input_authority_sha256"),
        "cli_binary_sha256": repo / "Ember.cmd",
        "launch_packet_sha256": repo / "tools" / "ember-restart-3b" / "launch_packet.py",
        "board_receipt_sha256": repo
        / "scripts"
        / "ember_totality"
        / "receipts-totality"
        / "ember-totality-20260801T052815Z.json",
        "benchmark_registry_sha256": repo
        / "manifests"
        / "ember-01-custody"
        / "benchmark-registry.json",
        "failure_class_ledger_sha256": repo
        / "docs"
        / "ledgers"
        / "ember-debt-ledger.md",
        "subject_manifest_sha256": _external_binding_path("subject_manifest_sha256"),
        "seat_sha256": _external_binding_path("seat_sha256"),
        "root_summary_sha256": repo
        / "manifests"
        / "ember-01-custody"
        / "root-spec.json",
    }


def _read_live_closure_sha256(repo: Path) -> str:
    module_path = repo / "tools" / "ember-restart-3b" / "certified_train_launch.py"
    spec = importlib.util.spec_from_file_location("ember_certified_train_launch", module_path)
    if spec is None or spec.loader is None:
        raise PublicationRefusal("CERTIFIED_CONSUMER_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True
    spec.loader.exec_module(module)
    return module.read_live_closure_sha256(repo)


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _mint_and_publish_launch_authority(
    *,
    repo_root: Path,
    custody_root: Path,
    run_id: str,
    training_verify_receipt: Path,
    completion_receipt: Path,
    binding_paths: dict[str, Path] | None = None,
    closure_sha256: str | None = None,
    validator: Callable[[Path, Path, Path], Any] | None = None,
    closure_reader: Callable[[Path], str] | None = None,
    declared_at_utc: str | None = None,
) -> dict[str, Any]:
    """Mint current-source bytes, then pass them through the atomic publisher."""

    repo, custody = _external_root(repo_root, custody_root)
    _require_clean_repository(repo)
    if RUN_ID.fullmatch(run_id) is None:
        raise PublicationRefusal("RUN_ID_INVALID")
    training_receipt_input = Path(training_verify_receipt)
    completion_input = Path(completion_receipt)
    training_receipt = _regular_source(
        training_receipt_input, "training_verify_receipt"
    )
    completion = _regular_source(completion_input, "completion_receipt")
    training_receipt_sha256 = _sha256(training_receipt)
    completion_sha256 = _sha256(completion)
    using_default_bindings = binding_paths is None
    paths = _default_binding_paths(repo) if using_default_bindings else binding_paths
    if set(paths) != SHA_BINDING_KEYS:
        raise PublicationRefusal("MINT_BINDING_SCHEMA_MISMATCH")
    binding_inputs = {key: Path(path) for key, path in paths.items()}
    admitted_paths = {
        key: _regular_source(path, key) for key, path in binding_inputs.items()
    }
    head = _git_output(repo, "rev-parse", "HEAD")
    if re.fullmatch(r"[0-9a-f]{40}", head) is None:
        raise PublicationRefusal("REPOSITORY_IDENTITY_INVALID")
    live_closure = closure_reader or _read_live_closure_sha256
    if closure_sha256 is None:
        closure_sha256 = live_closure(repo)
    elif closure_reader is None:
        # Private tests may inject a frozen closure for a minimal synthetic repo.
        # The public producer exposes neither override.
        live_closure = lambda _repo: closure_sha256
    if not isinstance(closure_sha256, str) or SHA256.fullmatch(closure_sha256) is None:
        raise PublicationRefusal("TRAINING_CLOSURE_SHA256_INVALID")

    run_root = custody / run_id
    artifact_root = run_root / "artifacts"
    source_hashes = {key: _sha256(path) for key, path in admitted_paths.items()}
    if using_default_bindings:
        _require_frozen_external_binding_hashes(repo, source_hashes)
    certificate = {
        "schema_version": "ember-spine-certified-declaration-v1",
        "event_kind": "SPINE_CERTIFIED",
        "declared_by_role": "EMBER_CERTIFICATE_AUTHORITY",
        "declared_at_utc": declared_at_utc
        or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "superseded_by": None,
        "completion_receipt_path": str(completion),
        "completion_receipt_sha256": completion_sha256,
        "public_master_sha": head,
        "closure_sha256": closure_sha256,
        **source_hashes,
        "declaration_conjuncts": {
            "record_coherent": True,
            "nine_leg_completion": True,
            "birth_failure_classes_disposed": True,
        },
        "execution_scope": {
            "purpose": "BOUNDED_CANARY",
            "allowed_modes": ["governed-vertical"],
            "max_optimizer_steps": 200,
            "max_records": 4096,
            "max_active_expert_families": 1,
            "max_gpu_vram_gib": 20.0,
            "max_transient_checkpoint_gib": 4.0,
            "max_wall_minutes": 15,
            "max_b_write_gib": 34.0,
            "max_c_write_gib": 0.25,
            "max_write_budget_bytes": 34 * 1024**3,
            "allowed_artifact_roots": [str(artifact_root)],
            "allowed_custody_roots": [str(run_root)],
            "model_server_allowed": False,
            "wsl_allowed": False,
            "persistent_worker_allowed": False,
        },
    }
    certificate_sha256 = hashlib.sha256(_canonical_bytes(certificate)).hexdigest()
    ledger_row = {
        "schema_version": "ember-spine-declaration-ledger-row-v1",
        "event_kind": "SPINE_CERTIFIED",
        "declared_by_role": "EMBER_CERTIFICATE_AUTHORITY",
        "certificate_sha256": certificate_sha256,
    }
    run_spec = {
        "schema_version": "ember-certified-train-run-v1",
        "certificate_sha256": certificate_sha256,
        "run_id": run_id,
        "seed": 830001,
        "runner_receipt": str(run_root / "disk-budget-runner-receipt.json"),
        "training_verify_receipt_path": str(training_receipt),
        "training_verify_receipt_sha256": training_receipt_sha256,
        "requested_scope": {
            "mode": "governed-vertical",
            "optimizer_steps": 100,
            "max_records": 200,
            "active_expert_families": 1,
            "gpu_vram_gib": 20.0,
            "transient_checkpoint_gib": 4.0,
            "wall_minutes": 14,
            "max_b_write_gib": 34.0,
            "max_c_write_gib": 0.25,
            "write_budget_bytes": 34 * 1024**3,
            "artifact_root": str(artifact_root),
            "custody_root": str(run_root),
        },
    }
    source_map = {
        key: f"sha256:{source_hashes[key]};path:{path}"
        for key, path in admitted_paths.items()
    }
    packet_destination = run_root / "launch-authority"
    canonical_validate = validator or _canonical_validator(
        repo, expected_packet_directory=packet_destination
    )

    def validate_minted_sources(
        certificate_path: Path,
        ledger_path: Path,
        run_spec_path: Path,
    ) -> Any:
        result = canonical_validate(certificate_path, ledger_path, run_spec_path)
        if any(_sha256(admitted_paths[key]) != digest for key, digest in source_hashes.items()):
            raise PublicationRefusal("MINT_SOURCE_BINDING_CHANGED")
        if _sha256(training_receipt) != training_receipt_sha256:
            raise PublicationRefusal("MINT_TRAINING_VERIFY_RECEIPT_CHANGED")
        if _sha256(completion) != completion_sha256:
            raise PublicationRefusal("MINT_COMPLETION_RECEIPT_CHANGED")
        return result

    def final_fence() -> None:
        # This fence is deliberately after canonical validation and immediately
        # before the atomic namespace claim. A validator or concurrent actor must
        # not make a stale HEAD/closure/source packet visible even momentarily.
        _require_clean_repository(repo)
        if _git_output(repo, "rev-parse", "HEAD") != head:
            raise PublicationRefusal("MINT_REPOSITORY_HEAD_CHANGED")
        if live_closure(repo) != closure_sha256:
            raise PublicationRefusal("MINT_LIVE_CLOSURE_CHANGED")
        for key, admitted in admitted_paths.items():
            if _regular_source(binding_inputs[key], key) != admitted:
                raise PublicationRefusal(f"{key.upper()}_IDENTITY_CHANGED")
        if (
            _regular_source(training_receipt_input, "training_verify_receipt")
            != training_receipt
        ):
            raise PublicationRefusal("TRAINING_VERIFY_RECEIPT_IDENTITY_CHANGED")
        if _regular_source(completion_input, "completion_receipt") != completion:
            raise PublicationRefusal("COMPLETION_RECEIPT_IDENTITY_CHANGED")
        if any(_sha256(admitted_paths[key]) != digest for key, digest in source_hashes.items()):
            raise PublicationRefusal("MINT_SOURCE_BINDING_CHANGED")
        if _sha256(training_receipt) != training_receipt_sha256:
            raise PublicationRefusal("MINT_TRAINING_VERIFY_RECEIPT_CHANGED")
        if _sha256(completion) != completion_sha256:
            raise PublicationRefusal("MINT_COMPLETION_RECEIPT_CHANGED")

    mint_source = custody / f".issue1506-{run_id}-{uuid.uuid4().hex}.mint"
    mint_source.mkdir(mode=0o700)
    try:
        (mint_source / "certificate.json").write_bytes(_canonical_bytes(certificate))
        (mint_source / "declaration-ledger.jsonl").write_bytes(
            _canonical_bytes(ledger_row)
        )
        (mint_source / "run-spec.json").write_bytes(_canonical_bytes(run_spec))
        (mint_source / "sha-binding-map.json").write_bytes(
            (json.dumps(source_map, indent=2, sort_keys=True) + "\n").encode("utf-8")
        )
        return _publish_launch_authority(
            repo_root=repo,
            custody_root=custody,
            run_id=run_id,
            certificate=mint_source / "certificate.json",
            declaration_ledger=mint_source / "declaration-ledger.jsonl",
            run_spec=mint_source / "run-spec.json",
            sha_binding_map=mint_source / "sha-binding-map.json",
            validator=validate_minted_sources,
            final_fence=final_fence,
        )
    finally:
        shutil.rmtree(mint_source, ignore_errors=True)


def mint_and_publish_launch_authority(
    *,
    repo_root: Path,
    custody_root: Path,
    run_id: str,
    training_verify_receipt: Path,
    completion_receipt: Path,
) -> dict[str, Any]:
    """Public producer: mint current authority and publish it atomically."""

    return _mint_and_publish_launch_authority(
        repo_root=repo_root,
        custody_root=custody_root,
        run_id=run_id,
        training_verify_receipt=training_verify_receipt,
        completion_receipt=completion_receipt,
    )


def _canonical_validator(
    repo: Path,
    *,
    expected_packet_directory: Path | None = None,
) -> Callable[[Path, Path, Path], Any]:
    module_path = repo / "tools" / "ember-restart-3b" / "certified_train_launch.py"
    spec = importlib.util.spec_from_file_location("ember_certified_train_launch", module_path)
    if spec is None or spec.loader is None:
        raise PublicationRefusal("CERTIFIED_CONSUMER_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True
    spec.loader.exec_module(module)

    def validate(certificate: Path, ledger: Path, run_spec: Path) -> Any:
        receipt = certificate.parent / "launch-authority-custody.json"
        return module.validate_certified_request(
            repo,
            certificate,
            ledger,
            run_spec,
            hashlib.sha256(receipt.read_bytes()).hexdigest(),
            expected_launch_authority_packet_directory=expected_packet_directory,
        )

    return validate


def _reopen_launch_authority(
    *,
    repo_root: Path,
    custody_root: Path,
    run_id: str,
    validator: Callable[[Path, Path, Path], Any] | None = None,
) -> dict[str, Any]:
    """Reopen one derived external run packet through every consumer authority."""

    repo, custody = _external_root(repo_root, custody_root)
    if RUN_ID.fullmatch(run_id) is None:
        raise PublicationRefusal("RUN_ID_INVALID")
    destination_parent = custody / run_id
    destination = destination_parent / "launch-authority"
    _assert_no_reparse_components(destination_parent, "custody_run")
    _assert_no_reparse_components(destination, "custody_packet")
    if not destination.is_dir():
        if destination_parent.is_dir():
            raise PublicationRefusal("RUN_ID_MISMATCH")
        raise PublicationRefusal("CUSTODY_DESTINATION_MISSING")
    expected_names = {*FILES, RECEIPT_FILE}
    try:
        actual_names = {entry.name for entry in destination.iterdir()}
    except OSError as error:
        raise PublicationRefusal("CUSTODY_PACKET_UNREADABLE") from error
    if actual_names != expected_names:
        raise PublicationRefusal("CUSTODY_PACKET_SCHEMA_MISMATCH")
    receipt_path = _regular_source(destination / RECEIPT_FILE, "custody_receipt")
    try:
        receipt_bytes = receipt_path.read_bytes()
    except OSError as error:
        raise PublicationRefusal("CUSTODY_PACKET_UNREADABLE") from error
    payload = _decode_closed_receipt(receipt_bytes)
    if payload["run_id"] != run_id:
        raise PublicationRefusal("RUN_ID_MISMATCH")
    paths = {
        name: _regular_source(destination / name, name.replace(".", "_"))
        for name in FILES
    }
    for name, path in paths.items():
        if _sha256(path) != payload["files"][name]:
            raise PublicationRefusal("PUBLISHED_FILE_HASH_MISMATCH")
    _validate_sha_binding_map_bytes(paths["sha-binding-map.json"].read_bytes())
    _validate_sha_binding_map_matches_certificate(
        paths["sha-binding-map.json"].read_bytes(),
        paths["certificate.json"].read_bytes(),
    )
    (validator or _canonical_validator(repo))(
        paths["certificate.json"],
        paths["declaration-ledger.jsonl"],
        paths["run-spec.json"],
    )
    return {
        **payload,
        "custody_root": str(destination),
        "receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
    }


def reopen_launch_authority(
    *,
    repo_root: Path,
    custody_root: Path,
    run_id: str,
) -> dict[str, Any]:
    """Public canonical reopener; no alternate validation authority is accepted."""

    return _reopen_launch_authority(
        repo_root=repo_root,
        custody_root=custody_root,
        run_id=run_id,
    )


def _publish_launch_authority(
    *,
    repo_root: Path,
    custody_root: Path,
    run_id: str,
    certificate: Path,
    declaration_ledger: Path,
    run_spec: Path,
    sha_binding_map: Path,
    validator: Callable[[Path, Path, Path], Any] | None = None,
    final_fence: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Validate, atomically publish, reopen, and receipt one authority packet."""

    repo, custody = _external_root(repo_root, custody_root)
    if RUN_ID.fullmatch(run_id) is None:
        raise PublicationRefusal("RUN_ID_INVALID")
    source_paths = {
        "certificate.json": _regular_source(certificate, "certificate"),
        "declaration-ledger.jsonl": _regular_source(
            declaration_ledger, "declaration_ledger"
        ),
        "run-spec.json": _regular_source(run_spec, "run_spec"),
        "sha-binding-map.json": _regular_source(sha_binding_map, "sha_binding_map"),
    }
    try:
        source_bytes = {name: path.read_bytes() for name, path in source_paths.items()}
    except OSError as error:
        raise PublicationRefusal("SOURCE_READ_FAILED") from error
    _validate_sha_binding_map_bytes(source_bytes["sha-binding-map.json"])
    _validate_sha_binding_map_matches_certificate(
        source_bytes["sha-binding-map.json"], source_bytes["certificate.json"]
    )
    destination_parent = custody / run_id
    destination = destination_parent / "launch-authority"

    historical_before = _historical_hashes(repo)
    staging_parent = custody / f".issue1506-{run_id}-{uuid.uuid4().hex}.staging"
    staging = staging_parent / "launch-authority"
    staging.mkdir(mode=0o700, parents=True)
    try:
        for name in FILES:
            (staging / name).write_bytes(source_bytes[name])

        source_hashes = {name: _sha256(staging / name) for name in FILES}
        receipt = {
            "schema_version": SCHEMA,
            "run_id": run_id,
            "custody_kind": "external-run-scoped",
            "training_executed": False,
            "files": source_hashes,
        }
        receipt_bytes = (
            json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        (staging / "launch-authority-custody.json").write_bytes(receipt_bytes)

        # The canonical consumer binds the raw receipt hash, so the complete
        # five-file packet must exist before either pre-publication validation
        # or the post-publication reopen.  Nothing is externally visible yet:
        # staging remains outside the claimed run-id namespace.
        (validator or _canonical_validator(
            repo, expected_packet_directory=destination
        ))(
            staging / "certificate.json",
            staging / "declaration-ledger.jsonl",
            staging / "run-spec.json",
        )

        if final_fence is not None:
            final_fence()

        # Claim the complete run-id namespace atomically.  Renaming the
        # staging parent (rather than first creating a visible empty run-id
        # directory) prevents a crash from exposing partial output.
        _atomic_publish_no_replace(staging_parent, destination_parent)
        reopened = _reopen_launch_authority(
            repo_root=repo,
            custody_root=custody,
            run_id=run_id,
            validator=validator,
        )
        if reopened["files"] != source_hashes:
            raise PublicationRefusal("PUBLISHED_BYTES_CHANGED")
        if _historical_hashes(repo) != historical_before:
            raise PublicationRefusal("HISTORICAL_RECORD_CHANGED")
        return {
            **receipt,
            "custody_root": reopened["custody_root"],
            "receipt_sha256": reopened["receipt_sha256"],
        }
    except Exception:
        shutil.rmtree(staging_parent, ignore_errors=True)
        # The atomic no-replace rename is the publication commit point. Every
        # producer-controlled refusal occurs before it. After it, never use a
        # check-then-delete sequence: another actor could add or replace bytes
        # between the ownership check and recursive removal. The reopener fails
        # closed and preserves any foreign/tampered namespace for adjudication.
        raise


def publish_launch_authority(
    *,
    repo_root: Path,
    custody_root: Path,
    run_id: str,
    certificate: Path,
    declaration_ledger: Path,
    run_spec: Path,
    sha_binding_map: Path,
) -> dict[str, Any]:
    """Refuse pre-minted public packets; fresh minting is the sole authority."""

    del (
        repo_root,
        custody_root,
        run_id,
        certificate,
        declaration_ledger,
        run_spec,
        sha_binding_map,
    )
    raise PublicationRefusal("PREMINTED_PUBLICATION_FORBIDDEN")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--custody-root", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--training-verify-receipt", required=True, type=Path)
    parser.add_argument(
        "--completion-receipt",
        type=Path,
        help=(
            "owned EMBER-01 completion receipt; defaults to the canonical "
            "tracked evidence-pack receipt under --repo-root"
        ),
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="publish after canonical validation; without this flag no files are written",
    )
    args = parser.parse_args(argv)
    completion_receipt = args.completion_receipt or (
        args.repo_root
        / "receipts"
        / "ember-01-completion"
        / "evidence-pack-v1"
        / "verifier-receipt-9leg-20260804.json"
    )
    if not args.execute:
        print(
            json.dumps(
                {
                    "outcome": "DRY_RUN",
                    "destination": str(
                        args.custody_root / args.run_id / "launch-authority"
                    ),
                    "training_executed": False,
                },
                sort_keys=True,
            )
        )
        return 0
    try:
        receipt = mint_and_publish_launch_authority(
            repo_root=args.repo_root,
            custody_root=args.custody_root,
            run_id=args.run_id,
            training_verify_receipt=args.training_verify_receipt,
            completion_receipt=completion_receipt,
        )
    except (OSError, PublicationRefusal, ValueError) as error:
        print(json.dumps({"outcome": "REFUSED", "reason": str(error)}, sort_keys=True))
        return 2
    print(json.dumps({"outcome": "PUBLISHED", **receipt}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
