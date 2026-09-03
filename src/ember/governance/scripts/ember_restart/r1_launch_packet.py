# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

"""Build a CPU-only R1 WARM-100 packet without launching training.

The existing R1-entry and certified-launch modules remain the authorities.
This module only joins their already-defined contracts into a run-scoped
external-custody packet and a PREP-only readiness manifest.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any, Callable

from src.ember.governance.scripts.ember_restart import contract


READY_CLAIM_BOUNDARY = {
    "execution": False,
    "result": False,
    "sufficiency": False,
    "capability": False,
    "benchmark": False,
}
TEXT_AUTHORITY_INDEX = "data/ember-restart-3b/text-lab-authority-index-v1.json"
# The daemon's default named pipe. The one launch command needs a pipe, and a
# contributor should not have to invent one to start a governed run.
EMBER_LAB_PIPE = r"\\.\pipe\ember-lab"

EXIT_SOURCE_PATHS = {
    "E1": (
        "src/ember/governance/scripts/r1_exit_battery.py",
        "src/ember/infrastructure/tools/ember-restart-3b/run_vertical_slice.py",
        "src/ember/infrastructure/tools/ember-restart-3b/semantic_stream.py",
        "src/ember/infrastructure/tools/ember-restart-3b/pretrain.py",
    ),
    "E2": (
        "src/ember/governance/scripts/r1_exit_battery.py",
        "src/ember/infrastructure/tools/ember-restart-3b/run_vertical_slice.py",
        "src/ember/infrastructure/tools/ember-restart-3b/pretrain.py",
    ),
    "E3": (
        "src/ember/governance/scripts/r1_exit_battery.py",
        "src/ember/infrastructure/tools/ember-restart-3b/checkpoint_artifacts.py",
    ),
    "E4": (
        "src/ember/governance/scripts/r1_exit_battery.py",
        "src/ember/infrastructure/tools/ember-restart-3b/run_vertical_slice.py",
    ),
    "E5": (
        "src/ember/governance/scripts/r1_exit_battery.py",
        "src/ember/governance/scripts/frontier_receipt.py",
        "src/ember/governance/scripts/energy_proxy_logger.py",
    ),
    "E6": (
        "src/ember/governance/scripts/r1_exit_battery.py",
        "src/ember/governance/scripts/forecast_recalibration.py",
    ),
    "E7": ("src/ember/governance/scripts/r1_exit_battery.py",),
    "E8": (
        "src/ember/governance/scripts/r1_exit_battery.py",
        "src/ember/governance/scripts/density_ab_a1.py",
    ),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_bytes(payload: dict[str, Any], *, omit: str | None = None) -> bytes:
    body = payload if omit is None else {key: value for key, value in payload.items() if key != omit}
    return (json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_bytes(payload))


def _load_module(path: Path, name: str):
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise ValueError(f"required authority module cannot be loaded: {path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _regular_file(path: Path, label: str) -> Path:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError(f"{label} must be a regular file")
    return candidate


def _require_under(path: Path, root: Path, label: str) -> Path:
    resolved = Path(path).resolve(strict=False)
    bound = Path(root).resolve(strict=False)
    if resolved == bound or not resolved.is_relative_to(bound):
        raise ValueError(f"{label} must resolve below custody root")
    return resolved


def _validate_entry_shape(payload: dict[str, Any]) -> None:
    if payload.get("schema") != contract.R1_ENTRY_SCHEMA:
        raise ValueError("R1 entry schema is not current")
    if payload.get("entry") != "WARM-100" or payload.get("steps") != 100:
        raise ValueError("R1 entry must be exactly WARM-100")
    if payload.get("result") != "PREP_ONLY":
        raise ValueError("R1 entry must remain PREP_ONLY")
    if payload.get("claim_boundary") != contract.R1_ENTRY_CLAIM_BOUNDARY:
        raise ValueError("R1 entry claim boundary is widened")
    if payload.get("dispatch") != {
        "surface": "ember-cli",
        "authority": "ember-lab",
        "consumer": "certified_train_launch.py",
        "mode": "WARM-100",
    }:
        raise ValueError("R1 entry dispatch is not Ember CLI -> Ember Lab")


def _build_run_spec(
    certificate: dict[str, Any],
    *,
    certificate_sha256: str,
    custody_root: Path,
    artifact_root: Path,
    run_id: str,
    semantic_receipt: Path,
    semantic_shards_root: Path,
    telemetry_path: Path,
    sequence_length: int,
    checkpoint_interval: int,
    admitted_row_set_sha256: str,
) -> dict[str, Any]:
    scope = certificate.get("execution_scope")
    if not isinstance(scope, dict):
        raise ValueError("certificate execution scope is unavailable")
    if scope.get("allowed_semantic_canary_modes") != ["warm-100"]:
        raise ValueError("certificate does not exclusively authorize warm-100")
    if scope.get("max_optimizer_steps", 0) < 100:
        raise ValueError("certificate optimizer-step ceiling is below WARM-100")
    if scope.get("allowed_admitted_row_set_sha256") != admitted_row_set_sha256:
        raise ValueError(
            "certificate does not authorize the validated admitted row-set hash"
        )

    run_root = custody_root / run_id
    return {
        "schema_version": "ember-certified-train-run-v1",
        "certificate_sha256": certificate_sha256,
        "run_id": run_id,
        "seed": 83,
        "runner_receipt": str(run_root / "runner-receipt.json"),
        "requested_scope": {
            "mode": "governed-vertical",
            "optimizer_steps": 100,
            "max_records": min(1, int(scope["max_records"])),
            "active_expert_families": min(1, int(scope["max_active_expert_families"])),
            "gpu_vram_gib": scope["max_gpu_vram_gib"],
            "transient_checkpoint_gib": scope["max_transient_checkpoint_gib"],
            "wall_minutes": scope["max_wall_minutes"],
            "max_b_write_gib": scope["max_b_write_gib"],
            "max_c_write_gib": scope["max_c_write_gib"],
            "write_budget_bytes": scope["max_write_budget_bytes"],
            "artifact_root": str(artifact_root),
            "custody_root": str(custody_root),
        },
        "semantic_canary_mode": "warm-100",
        "semantic_canary_receipt": str(semantic_receipt),
        "semantic_canary_shards_root": str(semantic_shards_root),
        "semantic_canary_sequence_length": sequence_length,
        "semantic_canary_checkpoint_interval": checkpoint_interval,
        "semantic_canary_telemetry_path": str(telemetry_path),
        "admitted_row_set_sha256": admitted_row_set_sha256,
    }


def _exit_source_bindings(source_root: Path, source_commit: str) -> dict[str, Any]:
    return {
        exit_id: {
            path: contract._git_blob_sha256(source_root, source_commit, path)
            for path in paths
        }
        for exit_id, paths in EXIT_SOURCE_PATHS.items()
    }


def build_ready_for_compute_packet(
    *,
    source_root: Path,
    launch_repo_root: Path,
    r1_entry_path: Path,
    r1_manifest_path: Path,
    certificate_path: Path,
    declaration_ledger_path: Path,
    sha_binding_map_path: Path,
    custody_root: Path,
    artifact_root: Path,
    run_id: str,
    semantic_receipt: Path,
    semantic_shards_root: Path,
    telemetry_path: Path | None = None,
    sequence_length: int = 512,
    checkpoint_interval: int = 50,
    authority_index_relative: str = TEXT_AUTHORITY_INDEX,
    external_authority_root: Path | None = None,
    authority_manifest_rows: list[dict[str, Any]] | None = None,
    entry_validator: Callable[..., dict[str, Any]] | None = None,
    authority_validator: Callable[..., dict[str, Any]] | None = None,
    current_master_reader: Callable[[Path], str] | None = None,
) -> dict[str, Any]:
    """Build one canonical packet and return paths; never execute it.

    The three callable parameters are library-only hermetic test seams. Real
    callers omit them and therefore use the fixed source-tree authorities.
    """

    source_root = Path(source_root).resolve()
    launch_repo_root = Path(launch_repo_root).resolve()
    custody_root = Path(custody_root).resolve()
    artifact_root = _require_under(artifact_root, custody_root, "artifact root")
    if not custody_root.is_absolute() or custody_root.is_relative_to(launch_repo_root):
        raise ValueError("custody root must be absolute and outside the source repository")
    if not isinstance(run_id, str) or re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", run_id
    ) is None:
        raise ValueError("run_id is invalid")
    if sequence_length < 1 or checkpoint_interval < 1:
        raise ValueError("semantic sequence length and checkpoint interval must be positive")

    r1_entry_path = _regular_file(r1_entry_path, "R1 entry")
    r1_manifest_path = _regular_file(r1_manifest_path, "R1 manifest")
    try:
        entry = json.loads(r1_entry_path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("R1 entry must be readable JSON") from error
    if not isinstance(entry, dict):
        raise ValueError("R1 entry must be an object")
    _validate_entry_shape(entry)
    validate_entry = entry_validator or contract.validate_r1_warm100_entry
    validated_entry = validate_entry(
        entry,
        source_root=source_root,
        manifest_path=r1_manifest_path,
    )
    _validate_entry_shape(validated_entry)
    source_commit = validated_entry.get("source_commit")
    if not isinstance(source_commit, str):
        raise ValueError("R1 entry source commit is absent")

    text_authority = _load_module(
        source_root / "src/ember/infrastructure/tools/ember-restart-3b/text_lab_corpus.py",
        f"ember_r1_packet_text_authority_{uuid.uuid4().hex}",
    )
    validate_authority = authority_validator or text_authority.validate_authority_index
    authority_kwargs: dict[str, Any] = {"index_relative": authority_index_relative}
    if external_authority_root is not None:
        authority_kwargs["external_authority_root"] = external_authority_root
    authority_receipt = validate_authority(launch_repo_root, **authority_kwargs)
    authority = text_authority.validate_admitted_authority_subset(
        launch_repo_root,
        authority_receipt,
        index_relative=authority_index_relative,
        external_authority_root=external_authority_root,
        manifest_rows=authority_manifest_rows,
    )
    if authority.get("result") != "VERIFIED_ADMITTED_SUBSET":
        raise ValueError("current text authority admitted subset is not VERIFIED")

    certificate_path = _regular_file(certificate_path, "certificate")
    declaration_ledger_path = _regular_file(declaration_ledger_path, "declaration ledger")
    sha_binding_map_path = _regular_file(sha_binding_map_path, "SHA binding map")
    certificate = json.loads(certificate_path.read_bytes())
    if not isinstance(certificate, dict):
        raise ValueError("certificate must be an object")
    certificate_sha256 = _sha256(certificate_path)

    final_run_root = custody_root / run_id
    final_packet_directory = final_run_root / "launch-authority"
    if final_run_root.exists():
        raise ValueError("run-scoped custody destination already exists")
    selected_telemetry = telemetry_path or (final_run_root / "telemetry" / "training.jsonl")
    selected_telemetry = _require_under(selected_telemetry, custody_root, "telemetry path")
    semantic_receipt = _regular_file(semantic_receipt, "semantic canary receipt").resolve()
    if not semantic_receipt.is_relative_to(launch_repo_root):
        raise ValueError("semantic canary receipt must be inside launch repository")
    semantic_shards_root = Path(semantic_shards_root).resolve()
    if not semantic_shards_root.is_dir():
        raise ValueError("semantic shard root must be a directory")

    run_spec = _build_run_spec(
        certificate,
        certificate_sha256=certificate_sha256,
        custody_root=custody_root,
        artifact_root=artifact_root,
        run_id=run_id,
        semantic_receipt=semantic_receipt,
        semantic_shards_root=semantic_shards_root,
        telemetry_path=selected_telemetry,
        sequence_length=sequence_length,
        checkpoint_interval=checkpoint_interval,
        admitted_row_set_sha256=authority["admitted_row_set_sha256"],
    )
    if any(key.startswith("resume_") for key in run_spec):
        raise ValueError("WARM-100 packet must not contain resume authority")

    certified = _load_module(
        source_root / "src/ember/infrastructure/tools/ember-restart-3b/certified_train_launch.py",
        f"ember_r1_packet_certified_{uuid.uuid4().hex}",
    )
    if current_master_reader is not None:
        certified.read_current_master = current_master_reader

    staging_root = custody_root / f".issue1506-{run_id}-{uuid.uuid4().hex}.staging"
    staging_packet = staging_root / "launch-authority"
    try:
        staging_packet.mkdir(parents=True)
        copied = {
            "certificate.json": certificate_path,
            "declaration-ledger.jsonl": declaration_ledger_path,
            "sha-binding-map.json": sha_binding_map_path,
        }
        for name, source in copied.items():
            shutil.copyfile(source, staging_packet / name)
        run_spec_path = staging_packet / "run-spec.json"
        _write_json(run_spec_path, run_spec)

        paths_for_receipt = {
            "certificate.json": staging_packet / "certificate.json",
            "declaration-ledger.jsonl": staging_packet / "declaration-ledger.jsonl",
            "run-spec.json": run_spec_path,
            "sha-binding-map.json": staging_packet / "sha-binding-map.json",
        }
        expected_names = set(certified._RUN_SCOPED_PACKET_FILENAMES.values()) | {
            "sha-binding-map.json"
        }
        if set(paths_for_receipt) != expected_names:
            raise ValueError("certified launch packet filenames drifted")
        custody_receipt = {
            "schema_version": certified._RUN_SCOPED_CUSTODY_SCHEMA,
            "run_id": run_id,
            "custody_kind": "external-run-scoped",
            "training_executed": False,
            "files": {name: _sha256(path) for name, path in paths_for_receipt.items()},
        }
        if set(custody_receipt) != set(certified._RUN_SCOPED_CUSTODY_RECEIPT_KEYS):
            raise ValueError("certified custody receipt schema drifted")
        custody_receipt_path = staging_packet / "launch-authority-custody.json"
        _write_json(custody_receipt_path, custody_receipt)
        custody_receipt_sha256 = _sha256(custody_receipt_path)

        launch = certified.validate_certified_request(
            launch_repo_root,
            staging_packet / "certificate.json",
            staging_packet / "declaration-ledger.jsonl",
            run_spec_path,
            custody_receipt_sha256,
            expected_launch_authority_packet_directory=final_packet_directory,
        )
        runner_argv = certified.build_runner_argv(launch_repo_root, launch)

        final_certificate = final_packet_directory / "certificate.json"
        final_ledger = final_packet_directory / "declaration-ledger.jsonl"
        final_run_spec = final_packet_directory / "run-spec.json"
        # The ONE command a contributor runs (issue 898, clause 4). The daemon
        # hash-pins the validator, builds and snapshots the dispatch manifest
        # itself, and dispatches the validator as a caged child, so there is no
        # human-authored manifest and no manual step between this command and a
        # governed run. --declaration-ledger and --custody-receipt-sha256 are
        # passed through unchanged rather than derived: a derived value that
        # disagreed with the declared one would be exactly the silent divergence
        # this packet exists to prevent.
        daemon_argv = [
            "ember-lab",
            "launch",
            "--root",
            str(launch_repo_root),
            "--certificate",
            str(final_certificate),
            "--declaration-ledger",
            str(final_ledger),
            "--run-spec",
            str(final_run_spec),
            "--custody-receipt-sha256",
            custody_receipt_sha256,
            "--pipe",
            EMBER_LAB_PIPE,
            "--receipt",
            str(final_packet_directory / "certified-launch.json"),
        ]
        # The argv the daemon gives its caged child. Recorded so the packet says
        # exactly what will run inside the job object; it is NOT a command for a
        # person to type, and the validator has no command-line entry point.
        consumer_argv = [
            sys.executable,
            str(source_root / "src/ember/infrastructure/tools/ember-restart-3b/certified_train_launch.py"),
            "--root",
            str(launch_repo_root),
            "--certificate",
            str(final_certificate),
            "--declaration-ledger",
            str(final_ledger),
            "--run-spec",
            str(final_run_spec),
            "--custody-receipt-sha256",
            custody_receipt_sha256,
        ]
        surface_argv = [
            "/train",
            "--execute",
            "--certificate",
            str(final_certificate),
            "--declaration-ledger",
            str(final_ledger),
            "--run-spec",
            str(final_run_spec),
        ]
        readiness: dict[str, Any] = {
            "schema": "ember-r1-warm100-ready-for-compute-v1",
            "status": "READY_FOR_COMPUTE",
            "source_commit": source_commit,
            "run_id": run_id,
            "r1_entry_sha256": _sha256(r1_entry_path),
            "r1_manifest_sha256": _sha256(r1_manifest_path),
            "text_authority": authority,
            "certificate_sha256": certificate_sha256,
            "run_spec_sha256": _sha256(run_spec_path),
            "custody_receipt_sha256": custody_receipt_sha256,
            "dispatch": {
                "surface": "ember-cli",
                "authority": "ember-lab",
                "consumer": "certified_train_launch.py",
                "daemon_argv": daemon_argv,
                "surface_argv": surface_argv,
                "consumer_argv": consumer_argv,
            },
            "runner_argv": runner_argv,
            "exit_source_bindings": _exit_source_bindings(source_root, source_commit),
            "claim_boundary": dict(READY_CLAIM_BOUNDARY),
        }
        readiness["manifest_sha256"] = hashlib.sha256(
            _canonical_bytes(readiness, omit="manifest_sha256")
        ).hexdigest()
        readiness_path = staging_root / "r1-ready-for-compute.json"
        _write_json(readiness_path, readiness)
        os.replace(staging_root, final_run_root)
    except Exception:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise

    return {
        "status": "READY_FOR_COMPUTE",
        "packet_directory": str(final_packet_directory),
        "manifest_path": str(final_run_root / "r1-ready-for-compute.json"),
        "manifest_sha256": readiness["manifest_sha256"],
    }
