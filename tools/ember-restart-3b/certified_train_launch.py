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
}
CERTIFICATE_EVIDENCE_SHA256_KEYS = (
    CERTIFICATE_SHA256_KEYS
    - {"completion_receipt_sha256", "evidence_bundle_sha256"}
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


class ValidatedLaunch(NamedTuple):
    certificate_sha256: str
    run_spec_sha256: str
    public_master_sha: str
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
) -> None:
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
    _validate_certificate_evidence(
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
            {
                "outcome": "COMPLETED" if exit_code == 0 else "FAILED",
                "execution_receipt": str(_execution_receipt_path(launch)),
                "artifact_root": str(launch.artifact_root),
                "exit_code": exit_code,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
