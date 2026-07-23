# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pathlib
import subprocess
import sys
import tempfile
from typing import Any, NamedTuple


EMBERD_SOURCE_PATHS = (
    "runtime/emberd/src/lib.rs",
    "runtime/emberd/src/rpc.rs",
    "runtime/emberd/src/main.rs",
    "runtime/emberd/Cargo.toml",
    "runtime/emberd/Cargo.lock",
)
CERTIFICATE_KEYS = {
    "schema_version",
    "event_kind",
    "declared_by_role",
    "declared_at_utc",
    "superseded_by",
    "completion_receipt_path",
    "completion_receipt_sha256",
    "evidence_bundle_path",
    "evidence_bundle_sha256",
    "public_master_sha",
    "config_sha256",
    "input_identity_sha256",
    "input_shard_sha256",
    "input_admission_receipt_sha256",
    "certified_consumer_sha256",
    "disk_budget_runner_sha256",
    "governed_runner_sha256",
    "input_identity_validator_sha256",
    "tokenizer_sha256",
    "emberd_binary_sha256",
    "emberd_source_sha256",
    "declaration_conjuncts",
    "execution_scope",
}
CERTIFICATE_SHA256_KEYS = {
    "completion_receipt_sha256",
    "evidence_bundle_sha256",
    "config_sha256",
    "input_identity_sha256",
    "input_shard_sha256",
    "input_admission_receipt_sha256",
    "certified_consumer_sha256",
    "disk_budget_runner_sha256",
    "governed_runner_sha256",
    "input_identity_validator_sha256",
    "tokenizer_sha256",
    "emberd_binary_sha256",
    "emberd_source_sha256",
}
CERTIFICATE_EVIDENCE_SHA256_KEYS = (
    CERTIFICATE_SHA256_KEYS
    - {
        "completion_receipt_sha256",
        "evidence_bundle_sha256",
        "emberd_source_sha256",
    }
)
EVIDENCE_BUNDLE_KEYS = {"schema_version", "evidence"}
EVIDENCE_ENTRY_KEYS = {"scope", "path"}
FIXED_REPO_EVIDENCE_PATHS = {
    "config_sha256": "configs/ember-restart-3b.json",
    "input_identity_sha256": "data/ember-restart-3b/input-identity.json",
    "input_shard_sha256": (
        "data/ember-restart-3b/owned-four-domain-production-rung-v1.json"
    ),
    "input_admission_receipt_sha256": (
        "data/ember-restart-3b/"
        "owned-four-domain-production-rung-v1.receipt.json"
    ),
    "certified_consumer_sha256": (
        "tools/ember-restart-3b/certified_train_launch.py"
    ),
    "disk_budget_runner_sha256": (
        "tools/ember-restart-3b/disk_budget_runner.py"
    ),
    "governed_runner_sha256": (
        "tools/ember-restart-3b/run_vertical_slice.py"
    ),
    "input_identity_validator_sha256": (
        "tools/ember-restart-3b/input_identity.py"
    ),
    "tokenizer_sha256": "tokenizer/tokenizer.json",
}
DECLARATION_CONJUNCT_KEYS = {
    "record_coherent",
    "nine_leg_completion",
    "birth_failure_classes_disposed",
}
LEDGER_ROW_KEYS = {
    "schema_version",
    "event_kind",
    "declared_by_role",
    "certificate_sha256",
}
RUN_SPEC_KEYS = {
    "schema_version",
    "certificate_sha256",
    "run_id",
    "seed",
    "runner_receipt",
    "requested_scope",
}
AUTHORIZED_SCOPE_KEYS = {
    "purpose",
    "allowed_modes",
    "max_optimizer_steps",
    "max_records",
    "max_active_expert_families",
    "max_gpu_vram_gib",
    "max_transient_checkpoint_gib",
    "max_wall_minutes",
    "max_b_write_gib",
    "max_c_write_gib",
    "max_write_budget_bytes",
    "allowed_artifact_roots",
    "allowed_custody_roots",
    "model_server_allowed",
    "wsl_allowed",
    "persistent_worker_allowed",
    "docker_allowed",
    "expected_gpu_uuid",
    "storage_reserves",
    "required_available_maximum_commit_bytes",
    "maximum_job_memory_bytes",
    "simulated_peak_commit_bytes",
}
REQUESTED_SCOPE_KEYS = {
    "mode",
    "optimizer_steps",
    "max_records",
    "active_expert_families",
    "gpu_vram_gib",
    "transient_checkpoint_gib",
    "wall_minutes",
    "max_b_write_gib",
    "max_c_write_gib",
    "write_budget_bytes",
    "artifact_root",
    "custody_root",
}
COMPLETION_RECEIPT_KEYS = {
    "schema",
    "ok",
    "verified_at_utc",
    "completed_goal_id",
    "goal_id",
    "workstream_id",
    "next_executed_outcome",
    "certificate_legs",
    "leg_detail",
    "leg_summary",
    "claim_scope",
    "checkout",
    "selection",
    "authority_certificate",
}
OPERATOR_STORAGE_FLOORS_BYTES = {
    "b:": 250 * 1024**3,
    "c:": 150 * 1024**3,
}
PROVISIONAL_HOST_COMMIT_BOUNDS_BYTES = {
    "simulated_peak": 24 * 1024**3,
    "maximum_job": 32 * 1024**3,
    "required_available": 40 * 1024**3,
}


class ValidatedLaunch(NamedTuple):
    certificate_sha256: str
    run_spec_sha256: str
    public_master_sha: str
    run_id: str
    artifact_root: pathlib.Path
    custody_root: pathlib.Path
    runner_receipt: pathlib.Path
    seed: int
    write_budget_bytes: int
    max_records: int
    max_c_write_gib: float
    max_b_write_gib: float
    max_wall_seconds: float
    gpu_vram_gib: float
    expected_gpu_uuid: str
    emberd_binary_path: pathlib.Path
    expected_emberd_source_sha256: str
    tokenizer_path: pathlib.Path
    input_identity_path: pathlib.Path
    input_shard_path: pathlib.Path
    input_admission_receipt_path: pathlib.Path
    input_identity_validator_path: pathlib.Path
    storage_reserves: list[dict[str, object]]
    required_available_maximum_commit_bytes: int
    maximum_job_memory_bytes: int
    simulated_peak_commit_bytes: int


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_sha256(path: pathlib.Path, label: str) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise ValueError(f"{label} is unreadable") from error


def _emberd_source_sha256(repo_root: pathlib.Path) -> str:
    digest = hashlib.sha256()
    for relative in EMBERD_SOURCE_PATHS:
        path = (repo_root / pathlib.PurePosixPath(relative)).resolve(strict=True)
        payload = path.read_bytes()
        digest.update(len(payload).to_bytes(8, "little"))
        digest.update(payload)
    return digest.hexdigest()


def _require_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _require_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} schema keys mismatch")


def _require_sha256(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or value.lower() != value
    ):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    try:
        int(value, 16)
    except ValueError as error:
        raise ValueError(f"{label} must be a lowercase SHA-256") from error
    return value


def _require_git_sha(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or value.lower() != value
    ):
        raise ValueError(f"{label} must be a lowercase 40-hex Git object ID")
    try:
        int(value, 16)
    except ValueError as error:
        raise ValueError(
            f"{label} must be a lowercase 40-hex Git object ID"
        ) from error
    return value


def _load_json(path: pathlib.Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is unreadable or invalid JSON") from error
    return _require_object(value, label)


def _load_bound_json(
    path: pathlib.Path, expected_sha256: str, label: str
) -> dict[str, Any]:
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise ValueError(f"{label} is unreadable") from error
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ValueError(f"{label} hash mismatch")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is invalid JSON") from error
    return _require_object(value, label)


def _resolve_relative_evidence_path(
    *,
    base: pathlib.Path,
    raw_path: object,
    label: str,
) -> pathlib.Path:
    if (
        not isinstance(raw_path, str)
        or not raw_path
        or "\\" in raw_path
        or any(character.isspace() for character in raw_path)
    ):
        raise ValueError(f"{label} path must be a portable relative path")
    relative = pathlib.PurePosixPath(raw_path)
    if (
        relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.as_posix() != raw_path
    ):
        raise ValueError(f"{label} path must be a portable relative path")
    try:
        resolved_base = base.resolve(strict=True)
        resolved = (
            resolved_base.joinpath(*relative.parts).resolve(strict=True)
        )
        resolved.relative_to(resolved_base)
    except (OSError, ValueError) as error:
        raise ValueError(f"{label} path is missing or escapes its root") from error
    if not resolved.is_file():
        raise ValueError(f"{label} path is not a file")
    return resolved


def _validate_certificate_evidence(
    *,
    repo_root: pathlib.Path,
    certificate_path: pathlib.Path,
    certificate: dict[str, Any],
) -> dict[str, pathlib.Path]:
    bundle_path = _resolve_relative_evidence_path(
        base=certificate_path.parent,
        raw_path=certificate["evidence_bundle_path"],
        label="certificate evidence bundle",
    )
    bundle = _load_bound_json(
        bundle_path,
        certificate["evidence_bundle_sha256"],
        "certificate evidence bundle",
    )
    _require_keys(bundle, EVIDENCE_BUNDLE_KEYS, "certificate evidence bundle")
    if (
        bundle["schema_version"]
        != "ember-spine-certificate-evidence-bundle-v1"
    ):
        raise ValueError("certificate evidence bundle schema")
    evidence = _require_object(
        bundle["evidence"], "certificate evidence bundle entries"
    )
    if set(evidence) != CERTIFICATE_EVIDENCE_SHA256_KEYS:
        raise ValueError("certificate evidence bundle entry keys mismatch")

    resolved_paths: dict[str, pathlib.Path] = {}
    for field in sorted(CERTIFICATE_EVIDENCE_SHA256_KEYS):
        entry = _require_object(
            evidence[field], f"certificate evidence entry {field}"
        )
        _require_keys(
            entry, EVIDENCE_ENTRY_KEYS, f"certificate evidence entry {field}"
        )
        scope = entry["scope"]
        if scope not in {"repo", "certificate"}:
            raise ValueError(f"certificate evidence scope invalid: {field}")
        fixed_path = FIXED_REPO_EVIDENCE_PATHS.get(field)
        if fixed_path is not None and (
            scope != "repo" or entry["path"] != fixed_path
        ):
            raise ValueError(f"certificate evidence canonical path mismatch: {field}")
        base = repo_root if scope == "repo" else certificate_path.parent
        evidence_path = _resolve_relative_evidence_path(
            base=base,
            raw_path=entry["path"],
            label=f"certificate evidence {field}",
        )
        if (
            _file_sha256(evidence_path, f"certificate evidence {field}")
            != certificate[field]
        ):
            raise ValueError(f"certificate evidence hash mismatch: {field}")
        resolved_paths[field] = evidence_path
    return resolved_paths


def _load_ledger(path: pathlib.Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise ValueError("declaration ledger is unreadable") from error
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = _require_object(
                json.loads(line), f"declaration ledger row {index}"
            )
        except json.JSONDecodeError as error:
            raise ValueError(
                f"declaration ledger row {index} is invalid JSON"
            ) from error
        _require_keys(row, LEDGER_ROW_KEYS, f"declaration ledger row {index}")
        if row["schema_version"] != "ember-spine-declaration-ledger-row-v1":
            raise ValueError("declaration ledger row schema")
        if row["event_kind"] != "SPINE_CERTIFIED":
            raise ValueError("declaration ledger event")
        if row["declared_by_role"] != "EMBER_CERTIFICATE_AUTHORITY":
            raise ValueError("declaration ledger role")
        _require_sha256(
            row["certificate_sha256"],
            f"declaration ledger row {index} certificate_sha256",
        )
        rows.append(row)
    return rows


def read_current_master(repo_root: pathlib.Path) -> str:
    head_result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
        shell=False,
    )
    if head_result.returncode != 0:
        raise ValueError("current public master is unreadable")
    status_result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ],
        check=False,
        capture_output=True,
        text=True,
        shell=False,
    )
    if status_result.returncode != 0:
        raise ValueError("current public checkout status is unreadable")
    if status_result.stdout:
        raise ValueError("current public checkout is not clean")
    return _require_git_sha(
        head_result.stdout.strip(), "current public master"
    )


def _validate_completion_receipt(
    value: dict[str, Any], public_master_sha: str
) -> None:
    _require_keys(value, COMPLETION_RECEIPT_KEYS, "completion receipt")
    if value["schema"] != "ember-01-completion-receipt-v1" or value["ok"] is not True:
        raise ValueError("completion receipt is not a successful EMBER-01 receipt")
    if (
        value["completed_goal_id"] != "EMBER-01"
        or value["goal_id"] != "EMBER-02"
        or value["workstream_id"] != "EMBER-02A"
    ):
        raise ValueError("completion receipt completed/active authority identity")

    legs = _require_object(value["certificate_legs"], "completion certificate legs")
    expected_legs = {str(index) for index in range(1, 10)}
    if set(legs) != expected_legs or any(
        state != "RESOLVED_TRUE" for state in legs.values()
    ):
        raise ValueError("completion receipt must contain exactly nine resolved-true legs")

    checkout = _require_object(value["checkout"], "completion checkout")
    checkout_head = _require_git_sha(
        checkout.get("head"), "completion checkout head"
    )
    if checkout_head != public_master_sha:
        raise ValueError(
            "completion checkout head does not match declared public master"
        )
    if not (
        checkout.get("clean") is True
        and checkout.get("detached") is True
        and checkout.get("head_unchanged") is True
    ):
        raise ValueError("completion checkout integrity")

    selection = _require_object(value["selection"], "completion selection")
    if (
        selection.get("goal_id") != "EMBER-02"
        or selection.get("unchanged_during_verification") is not True
    ):
        raise ValueError("completion selection integrity")


def _require_scope_subset(
    requested: dict[str, Any], authorized: dict[str, Any]
) -> None:
    _require_keys(requested, REQUESTED_SCOPE_KEYS, "requested scope")
    _require_keys(authorized, AUTHORIZED_SCOPE_KEYS, "certificate execution scope")

    if authorized["purpose"] != "BOUNDED_CANARY":
        raise ValueError("certificate execution scope is not a bounded canary")
    if not (
        authorized["model_server_allowed"] is False
        and authorized["wsl_allowed"] is False
        and authorized["persistent_worker_allowed"] is False
        and authorized["docker_allowed"] is False
    ):
        raise ValueError("certificate execution scope enables a forbidden runtime")

    allowed_modes = authorized["allowed_modes"]
    if (
        not isinstance(allowed_modes, list)
        or allowed_modes != ["governed-vertical"]
        or requested["mode"] not in allowed_modes
    ):
        raise ValueError("run scope exceeds certificate: mode")

    numeric_pairs = (
        ("optimizer_steps", "max_optimizer_steps"),
        ("max_records", "max_records"),
        ("active_expert_families", "max_active_expert_families"),
        ("gpu_vram_gib", "max_gpu_vram_gib"),
        ("transient_checkpoint_gib", "max_transient_checkpoint_gib"),
        ("wall_minutes", "max_wall_minutes"),
        ("max_b_write_gib", "max_b_write_gib"),
        ("max_c_write_gib", "max_c_write_gib"),
        ("write_budget_bytes", "max_write_budget_bytes"),
    )
    for requested_key, authorized_key in numeric_pairs:
        requested_value = requested[requested_key]
        authorized_value = authorized[authorized_key]
        zero_allowed = requested_key == "max_c_write_gib"
        if (
            isinstance(requested_value, bool)
            or not isinstance(requested_value, (int, float))
            or isinstance(authorized_value, bool)
            or not isinstance(authorized_value, (int, float))
            or not math.isfinite(float(requested_value))
            or not math.isfinite(float(authorized_value))
            or requested_value < 0
            or (not zero_allowed and requested_value == 0)
            or authorized_value < 0
            or (not zero_allowed and authorized_value == 0)
            or requested_value > authorized_value
        ):
            if (
                not isinstance(requested_value, bool)
                and isinstance(requested_value, (int, float))
                and not math.isfinite(float(requested_value))
            ):
                raise ValueError(
                    f"run scope requires finite {requested_key}"
                )
            if (
                not isinstance(requested_value, bool)
                and isinstance(requested_value, (int, float))
                and requested_value == 0
                and not zero_allowed
            ):
                raise ValueError(
                    f"run scope requires positive {requested_key}"
                )
            raise ValueError(
                f"run scope exceeds certificate: {requested_key}"
            )
    if requested["optimizer_steps"] != requested["max_records"]:
        raise ValueError(
            "run scope optimizer_steps must equal max_records"
        )
    if requested["active_expert_families"] != 1:
        raise ValueError(
            "run scope active_expert_families must be exactly one"
        )

    root_pairs = (
        ("artifact_root", "allowed_artifact_roots"),
        ("custody_root", "allowed_custody_roots"),
    )
    for requested_key, allowed_key in root_pairs:
        allowed = authorized[allowed_key]
        if (
            not isinstance(allowed, list)
            or not all(isinstance(item, str) for item in allowed)
            or requested[requested_key] not in allowed
        ):
            raise ValueError(
                f"run scope exceeds certificate: {requested_key}"
            )


def validate_certified_request(
    repo_root: pathlib.Path,
    certificate_path: pathlib.Path,
    declaration_ledger_path: pathlib.Path,
    run_spec_path: pathlib.Path,
) -> ValidatedLaunch:
    repo_root = pathlib.Path(repo_root)
    certificate_path = pathlib.Path(certificate_path)
    declaration_ledger_path = pathlib.Path(declaration_ledger_path)
    run_spec_path = pathlib.Path(run_spec_path)

    certificate = _load_json(certificate_path, "certificate")
    _require_keys(certificate, CERTIFICATE_KEYS, "certificate")
    if certificate["schema_version"] != "ember-spine-certified-declaration-v1":
        raise ValueError("certificate schema")
    if certificate["event_kind"] != "SPINE_CERTIFIED":
        raise ValueError("declaration event")
    if certificate["declared_by_role"] != "EMBER_CERTIFICATE_AUTHORITY":
        raise ValueError("declaration role")
    if certificate["superseded_by"] is not None:
        raise ValueError("certificate is superseded")
    for key in CERTIFICATE_SHA256_KEYS:
        _require_sha256(certificate[key], f"certificate {key}")
    _require_git_sha(certificate["public_master_sha"], "certificate public_master_sha")
    evidence_paths = _validate_certificate_evidence(
        repo_root=repo_root,
        certificate_path=certificate_path,
        certificate=certificate,
    )

    certificate_sha256 = _canonical_sha256(certificate)
    ledger_rows = _load_ledger(declaration_ledger_path)
    if not any(
        row["certificate_sha256"] == certificate_sha256 for row in ledger_rows
    ):
        raise ValueError("declaration ledger membership is missing")

    completion_path = _resolve_relative_evidence_path(
        base=certificate_path.parent,
        raw_path=certificate["completion_receipt_path"],
        label="completion receipt",
    )
    completion = _load_bound_json(
        completion_path,
        certificate["completion_receipt_sha256"],
        "completion receipt",
    )
    _validate_completion_receipt(completion, certificate["public_master_sha"])

    conjuncts = _require_object(
        certificate["declaration_conjuncts"], "declaration conjuncts"
    )
    _require_keys(conjuncts, DECLARATION_CONJUNCT_KEYS, "declaration conjuncts")
    if any(value is not True for value in conjuncts.values()):
        raise ValueError("B7 declaration conjunct is false")

    current_master = read_current_master(repo_root)
    if certificate["public_master_sha"] != current_master:
        raise ValueError("certificate does not bind current public master")

    run_spec = _load_json(run_spec_path, "run spec")
    _require_keys(run_spec, RUN_SPEC_KEYS, "run spec")
    if run_spec["schema_version"] != "ember-certified-train-run-v1":
        raise ValueError("run spec schema")
    if run_spec["certificate_sha256"] != certificate_sha256:
        raise ValueError("run spec certificate hash mismatch")
    if (
        not isinstance(run_spec["run_id"], str)
        or not run_spec["run_id"]
        or not isinstance(run_spec["seed"], int)
        or isinstance(run_spec["seed"], bool)
        or run_spec["seed"] < 0
        or not isinstance(run_spec["runner_receipt"], str)
        or not run_spec["runner_receipt"]
    ):
        raise ValueError(
            "run spec scalar fields require a nonnegative seed"
        )

    requested_scope = _require_object(
        run_spec["requested_scope"], "requested scope"
    )
    authorized_scope = _require_object(
        certificate["execution_scope"], "certificate execution scope"
    )
    _require_scope_subset(requested_scope, authorized_scope)
    expected_gpu_uuid = authorized_scope["expected_gpu_uuid"]
    storage_reserves = authorized_scope["storage_reserves"]
    required_available_maximum_commit_bytes = authorized_scope[
        "required_available_maximum_commit_bytes"
    ]
    maximum_job_memory_bytes = authorized_scope["maximum_job_memory_bytes"]
    simulated_peak_commit_bytes = authorized_scope[
        "simulated_peak_commit_bytes"
    ]
    if not isinstance(expected_gpu_uuid, str) or not expected_gpu_uuid.strip():
        raise ValueError("certificate expected GPU UUID is invalid")
    if not isinstance(storage_reserves, list):
        raise ValueError("certificate storage reserves are invalid")
    if (
        required_available_maximum_commit_bytes
        != PROVISIONAL_HOST_COMMIT_BOUNDS_BYTES["required_available"]
        or maximum_job_memory_bytes
        != PROVISIONAL_HOST_COMMIT_BOUNDS_BYTES["maximum_job"]
        or simulated_peak_commit_bytes
        != PROVISIONAL_HOST_COMMIT_BOUNDS_BYTES["simulated_peak"]
    ):
        raise ValueError("certificate provisional host bounds are invalid")

    custody_root = pathlib.Path(requested_scope["custody_root"])
    runner_receipt = pathlib.Path(run_spec["runner_receipt"])
    try:
        runner_receipt.resolve(strict=False).relative_to(
            custody_root.resolve(strict=False)
        )
    except ValueError as error:
        raise ValueError(
            "run scope exceeds certificate: runner_receipt"
        ) from error

    return ValidatedLaunch(
        certificate_sha256=certificate_sha256,
        run_spec_sha256=_file_sha256(run_spec_path, "run spec"),
        public_master_sha=current_master,
        run_id=run_spec["run_id"],
        artifact_root=pathlib.Path(requested_scope["artifact_root"]),
        custody_root=custody_root,
        runner_receipt=runner_receipt,
        seed=run_spec["seed"],
        write_budget_bytes=int(requested_scope["write_budget_bytes"]),
        max_records=int(requested_scope["max_records"]),
        max_c_write_gib=float(requested_scope["max_c_write_gib"]),
        max_b_write_gib=float(requested_scope["max_b_write_gib"]),
        max_wall_seconds=float(requested_scope["wall_minutes"]) * 60.0,
        gpu_vram_gib=float(requested_scope["gpu_vram_gib"]),
        expected_gpu_uuid=expected_gpu_uuid,
        emberd_binary_path=evidence_paths["emberd_binary_sha256"],
        expected_emberd_source_sha256=certificate["emberd_source_sha256"],
        tokenizer_path=evidence_paths["tokenizer_sha256"],
        input_identity_path=evidence_paths["input_identity_sha256"],
        input_shard_path=evidence_paths["input_shard_sha256"],
        input_admission_receipt_path=evidence_paths[
            "input_admission_receipt_sha256"
        ],
        input_identity_validator_path=evidence_paths[
            "input_identity_validator_sha256"
        ],
        storage_reserves=storage_reserves,
        required_available_maximum_commit_bytes=(
            required_available_maximum_commit_bytes
        ),
        maximum_job_memory_bytes=maximum_job_memory_bytes,
        simulated_peak_commit_bytes=simulated_peak_commit_bytes,
    )


def build_runner_argv(
    repo_root: pathlib.Path, launch: ValidatedLaunch
) -> list[str]:
    repo_root = pathlib.Path(repo_root)
    return [
        sys.executable,
        str(
            repo_root
            / "tools"
            / "ember-restart-3b"
            / "disk_budget_runner.py"
        ),
        "--max-c-write-gib",
        str(launch.max_c_write_gib),
        "--max-b-write-gib",
        str(launch.max_b_write_gib),
        "--max-wall-seconds",
        str(launch.max_wall_seconds),
        "--receipt",
        str(launch.runner_receipt),
        "--write-root",
        f"custody={launch.custody_root}",
        "--write-root",
        f"artifacts={launch.artifact_root}",
        "--",
        sys.executable,
        str(
            repo_root
            / "tools"
            / "ember-restart-3b"
            / "run_vertical_slice.py"
        ),
        "governed-vertical",
        "--gpu-vram-gib",
        str(launch.gpu_vram_gib),
        "--seed",
        str(launch.seed),
        "--artifact-root",
        str(launch.artifact_root),
        "--write-budget-bytes",
        str(launch.write_budget_bytes),
        "--max-records",
        str(launch.max_records),
    ]


def build_emberd_dispatch_manifest(
    repo_root: pathlib.Path,
    launch: ValidatedLaunch,
    *,
    now_ms: int,
) -> dict[str, object]:
    expected_gpu_uuid = launch.expected_gpu_uuid
    emberd_binary_path = launch.emberd_binary_path
    expected_emberd_source_sha256 = launch.expected_emberd_source_sha256
    tokenizer_path = launch.tokenizer_path
    storage_reserves = launch.storage_reserves
    required_available_maximum_commit_bytes = (
        launch.required_available_maximum_commit_bytes
    )
    maximum_job_memory_bytes = launch.maximum_job_memory_bytes
    simulated_peak_commit_bytes = launch.simulated_peak_commit_bytes
    repo_root = pathlib.Path(repo_root).resolve(strict=True)
    emberd_binary_path = pathlib.Path(emberd_binary_path).resolve(strict=True)
    tokenizer_path = pathlib.Path(tokenizer_path).resolve(strict=True)
    if not isinstance(expected_gpu_uuid, str) or not expected_gpu_uuid.strip():
        raise ValueError("expected GPU UUID is required")
    _require_sha256(expected_emberd_source_sha256, "emberd source")
    if _emberd_source_sha256(repo_root) != expected_emberd_source_sha256:
        raise ValueError("emberd source bytes do not match the certified aggregate")
    if (
        type(now_ms) is not int
        or now_ms < 0
        or type(required_available_maximum_commit_bytes) is not int
        or type(maximum_job_memory_bytes) is not int
        or type(simulated_peak_commit_bytes) is not int
        or simulated_peak_commit_bytes < 1
        or maximum_job_memory_bytes < simulated_peak_commit_bytes
        or required_available_maximum_commit_bytes < maximum_job_memory_bytes
    ):
        raise ValueError("host commit authority bounds are invalid")
    if (
        simulated_peak_commit_bytes
        != PROVISIONAL_HOST_COMMIT_BOUNDS_BYTES["simulated_peak"]
        or maximum_job_memory_bytes
        != PROVISIONAL_HOST_COMMIT_BOUNDS_BYTES["maximum_job"]
        or required_available_maximum_commit_bytes
        != PROVISIONAL_HOST_COMMIT_BOUNDS_BYTES["required_available"]
    ):
        raise ValueError(
            "provisional host commit bounds do not match operator authority"
        )
    if not isinstance(storage_reserves, list) or len(storage_reserves) != 2:
        raise ValueError("exact B/C storage reserves are required")
    reserve_roots: set[str] = set()
    reserve_by_drive: dict[str, int] = {}
    for reserve in storage_reserves:
        reserve = _require_object(reserve, "storage reserve")
        _require_keys(
            reserve,
            {"root", "minimum_free_bytes"},
            "storage reserve",
        )
        root = reserve["root"]
        minimum = reserve["minimum_free_bytes"]
        if (
            not isinstance(root, str)
            or not pathlib.PureWindowsPath(root).is_absolute()
            or type(minimum) is not int
            or minimum < 1
            or root.casefold() in reserve_roots
        ):
            raise ValueError("storage reserve is invalid")
        reserve_roots.add(root.casefold())
        drive = pathlib.PureWindowsPath(root).drive.casefold()
        if drive in reserve_by_drive:
            raise ValueError("storage reserve is invalid")
        reserve_by_drive[drive] = minimum
    if (
        set(reserve_by_drive) != set(OPERATOR_STORAGE_FLOORS_BYTES)
        or any(
            reserve_by_drive[drive] < floor
            for drive, floor in OPERATOR_STORAGE_FLOORS_BYTES.items()
        )
    ):
        raise ValueError("storage reserve is below the hard operator floor")

    certified_consumer = (
        repo_root / "tools" / "ember-restart-3b" / "certified_train_launch.py"
    ).resolve(strict=True)
    disk_budget_runner = (
        repo_root / "tools" / "ember-restart-3b" / "disk_budget_runner.py"
    ).resolve(strict=True)
    governed_runner = (
        repo_root / "tools" / "ember-restart-3b" / "run_vertical_slice.py"
    ).resolve(strict=True)
    config = (repo_root / "configs" / "ember-restart-3b.json").resolve(
        strict=True
    )
    program = pathlib.Path(sys.executable).resolve(strict=True)
    argv = build_runner_argv(repo_root, launch)[1:]
    lease_id = f"gpu:{expected_gpu_uuid}:bounded-canary"
    custody_root = launch.custody_root.resolve(strict=False)
    environment = {
        name: str(custody_root / "runtime" / name.casefold())
        for name in (
            "TEMP",
            "TMP",
            "TORCH_HOME",
            "TRITON_CACHE_DIR",
            "CUDA_CACHE_PATH",
            "HF_HOME",
            "XDG_CACHE_HOME",
        )
    }

    def bound(kind: str, path: pathlib.Path) -> dict[str, str]:
        return {
            "kind": kind,
            "path": str(path),
            "sha256": _file_sha256(path, f"dispatch {kind} binding"),
        }

    bindings = [
        bound("config", config),
        bound("certified_consumer", certified_consumer),
        bound("disk_budget_runner", disk_budget_runner),
        bound("governed_runner", governed_runner),
        bound("tokenizer", tokenizer_path),
        bound("input", launch.input_identity_path),
        bound("input", launch.input_shard_path),
        bound("verifier", launch.input_admission_receipt_path),
        bound("verifier", launch.input_identity_validator_path),
    ]
    minimum_free_vram_bytes = int(launch.gpu_vram_gib * 1024**3)
    canary_scope = {
        "dispatch_kind": "governed_vertical",
        "expected_gpu_uuid": expected_gpu_uuid,
        "minimum_free_vram_bytes": minimum_free_vram_bytes,
        "lease_id": lease_id,
        "expected_emberd_binary_sha256": _file_sha256(
            emberd_binary_path, "emberd binary"
        ),
        "expected_emberd_source_sha256": expected_emberd_source_sha256,
        "certified_consumer": {
            "path": str(certified_consumer),
            "sha256": _file_sha256(certified_consumer, "certified consumer"),
        },
        "disk_budget_runner": {
            "path": str(disk_budget_runner),
            "sha256": _file_sha256(disk_budget_runner, "disk budget runner"),
        },
        "governed_runner": {
            "path": str(governed_runner),
            "sha256": _file_sha256(governed_runner, "governed runner"),
        },
        "config": {
            "path": str(config),
            "sha256": _file_sha256(config, "model config"),
        },
        "tokenizer": {
            "path": str(tokenizer_path),
            "sha256": _file_sha256(tokenizer_path, "tokenizer"),
        },
        "forbidden_process_names": [
            "llama-server.exe",
            "qwen.exe",
            "ollama.exe",
            "koboldcpp.exe",
            "text-generation-launcher.exe",
            "vllm.exe",
        ],
        "wsl_allowed": False,
        "docker_allowed": False,
        "persistent_worker_allowed": False,
    }
    return {
        "schema_version": "emberd-governed-canary-dispatch-v1",
        "job_id": launch.run_id,
        "source_commit": launch.public_master_sha,
        "not_before_ms": now_ms,
        "expires_at_ms": now_ms + 60_000,
        "resource_lease": lease_id,
        "program": {
            "path": str(program),
            "sha256": _file_sha256(program, "dispatch Python program"),
        },
        "args": argv,
        "env": environment,
        "bindings": bindings,
        "custody_root": str(custody_root),
        "storage_reserves": storage_reserves,
        "minimum_free_vram_bytes": minimum_free_vram_bytes,
        "required_available_maximum_commit_bytes": (
            required_available_maximum_commit_bytes
        ),
        "maximum_job_memory_bytes": maximum_job_memory_bytes,
        "simulated_peak_commit_bytes": simulated_peak_commit_bytes,
        "preflight_receipt": str(
            custody_root / f"{launch.run_id}-emberd-preflight.json"
        ),
        "canary_scope": canary_scope,
    }


def _write_execution_receipt(
    launch: ValidatedLaunch, argv: list[str], exit_code: int
) -> pathlib.Path:
    receipt_path = _execution_receipt_path(launch)
    receipt = {
        "schema_version": "ember-certified-train-execution-v1",
        "certificate_sha256": launch.certificate_sha256,
        "run_spec_sha256": launch.run_spec_sha256,
        "public_master_sha": launch.public_master_sha,
        "argv": argv,
        "exit_code": exit_code,
        "artifact_root": str(launch.artifact_root),
        "runner_receipt": str(launch.runner_receipt),
        "claim_scope": {
            "capability_claimed": False,
            "admission_claimed": False,
            "sufficient_pretraining_claimed": False,
            "verified_expert_accretion_claimed": False,
            "competitiveness_claimed": False,
        },
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=receipt_path.parent,
        prefix=f".{receipt_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary_path = pathlib.Path(handle.name)
        handle.write(_canonical_bytes(receipt))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary_path, receipt_path)
    return receipt_path


def _execution_receipt_path(launch: ValidatedLaunch) -> pathlib.Path:
    return launch.runner_receipt.with_name(
        f"{launch.runner_receipt.stem}-certified-launch.json"
    )


def _execution_response(
    launch: ValidatedLaunch, exit_code: int
) -> dict[str, object]:
    receipt_path = _execution_receipt_path(launch)
    return {
        "outcome": "COMPLETED" if exit_code == 0 else "FAILED",
        "execution_receipt": str(receipt_path),
        "execution_receipt_sha256": _file_sha256(
            receipt_path, "certified execution receipt"
        ),
        "artifact_root": str(launch.artifact_root),
        "exit_code": exit_code,
    }


def execute_validated_launch(
    repo_root: pathlib.Path,
    launch: ValidatedLaunch,
    run_process=subprocess.run,
) -> int:
    repo_root = pathlib.Path(repo_root)
    argv = build_runner_argv(repo_root, launch)
    result = run_process(
        argv,
        shell=False,
        check=False,
        cwd=repo_root,
    )
    exit_code = int(result.returncode)
    _write_execution_receipt(launch, argv, exit_code)
    return exit_code


def certify_and_execute(
    repo_root: pathlib.Path,
    certificate_path: pathlib.Path,
    declaration_ledger_path: pathlib.Path,
    run_spec_path: pathlib.Path,
    run_process=subprocess.run,
) -> int:
    launch = validate_certified_request(
        repo_root,
        certificate_path,
        declaration_ledger_path,
        run_spec_path,
    )
    return execute_validated_launch(repo_root, launch, run_process=run_process)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a declared Ember canary certificate and execute its fixed runner."
    )
    parser.add_argument("--root", required=True, type=pathlib.Path)
    parser.add_argument("--certificate", required=True, type=pathlib.Path)
    parser.add_argument(
        "--declaration-ledger", required=True, type=pathlib.Path
    )
    parser.add_argument("--run-spec", required=True, type=pathlib.Path)
    arguments = parser.parse_args(argv)
    try:
        launch = validate_certified_request(
            arguments.root,
            arguments.certificate,
            arguments.declaration_ledger,
            arguments.run_spec,
        )
        exit_code = execute_validated_launch(arguments.root, launch)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            _execution_response(launch, exit_code),
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
