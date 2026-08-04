# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from typing import Any, NamedTuple


# A certificate that carries closure_sha256 binds the TRAINING DEPENDENCY
# CLOSURE (scripts/training_closure.py) instead of the whole repository tip, so
# a merge outside the closure no longer invalidates a pending launch.
# public_master_sha stays the VERIFIED-AT commit either way. Certificates minted
# before this field existed keep whole-tip equality.
#
# CERTIFICATE_KEYS and OPTIONAL_CERTIFICATE_KEYS are the key template the
# out-of-repo mint producer reads (it already exec-loads this module), so
# producer and consumer cannot skew.
CLOSURE_MODULE_RELATIVE_PATH = "scripts/training_closure.py"
# Guard-floor keys (issue #1410): the remote guard's receipt_check requires
# ticket/ts/sha_convention on any receipt carrying sha256 fields, and authority
# leg 4 requires goal_id/next_executed_outcome on committed artifacts. They are
# ACCEPTED as validated optional keys -- each shape-checked below, and any key
# outside this enumeration still hard-fails -- so a minted triple can be born
# guard-compliant instead of riding frozen-receipt exceptions. Presence of any
# guard-floor key marks a post-#1410 certificate, which must carry a RELATIVE
# completion_receipt_path (resolved against the certificate's own directory
# inside the custody root) so no absolute local path is baked into the
# sha-cited payload.
GUARD_FLOOR_CERTIFICATE_KEYS = {
    "ticket",
    "ts",
    "sha_convention",
    "goal_id",
    "next_executed_outcome",
}
OPTIONAL_CERTIFICATE_KEYS = {"closure_sha256"} | GUARD_FLOOR_CERTIFICATE_KEYS
CERTIFICATE_KEYS = {
    "schema_version",
    "event_kind",
    "declared_by_role",
    "declared_at_utc",
    "superseded_by",
    "completion_receipt_path",
    "completion_receipt_sha256",
    "public_master_sha",
    "checkout_sha256",
    "config_sha256",
    "tokenizer_sha256",
    "input_authority_sha256",
    "cli_binary_sha256",
    "launch_packet_sha256",
    "board_receipt_sha256",
    "benchmark_registry_sha256",
    "failure_class_ledger_sha256",
    "subject_manifest_sha256",
    "seat_sha256",
    "root_summary_sha256",
    "declaration_conjuncts",
    "execution_scope",
}
CERTIFICATE_SHA256_KEYS = {
    "completion_receipt_sha256",
    "checkout_sha256",
    "config_sha256",
    "tokenizer_sha256",
    "input_authority_sha256",
    "cli_binary_sha256",
    "launch_packet_sha256",
    "board_receipt_sha256",
    "benchmark_registry_sha256",
    "failure_class_ledger_sha256",
    "subject_manifest_sha256",
    "seat_sha256",
    "root_summary_sha256",
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
# Mirrors the EXACT emission of scripts/verify_ember01_completion.py (the
# producer is the source of truth): top-level goal_id is the ACTIVE goal
# ("EMBER-02"); the EMBER-01 subject binding is completion_subject_goal_id.
COMPLETION_RECEIPT_KEYS = {
    "schema",
    "ok",
    "verified_at_utc",
    "goal_id",
    "completion_subject_goal_id",
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
# scripts/verify_ember01_completion.py RESOLVED_TRUE -- lowercase-hyphen form.
COMPLETION_LEG_RESOLVED_TRUE = "resolved-true"


class ValidatedLaunch(NamedTuple):
    certificate_sha256: str
    run_spec_sha256: str
    public_master_sha: str
    closure_sha256: str | None
    artifact_root: pathlib.Path
    custody_root: pathlib.Path
    runner_receipt: pathlib.Path
    seed: int
    write_budget_bytes: int
    max_records: int
    max_c_write_gib: float
    max_b_write_gib: float


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


def load_closure_module(repo_root: pathlib.Path):
    """Load the single closure implementation out of the tree being launched."""

    module_path = pathlib.Path(repo_root) / CLOSURE_MODULE_RELATIVE_PATH
    specification = importlib.util.spec_from_file_location(
        "ember_training_closure", module_path
    )
    if specification is None or specification.loader is None:
        raise ValueError("training dependency closure module cannot be loaded")
    module = importlib.util.module_from_spec(specification)
    try:
        specification.loader.exec_module(module)
    except OSError as error:
        raise ValueError("training dependency closure module is unreadable") from error
    return module


def read_live_closure_sha256(repo_root: pathlib.Path) -> str:
    """Recompute the training closure from LIVE TREE BYTES, boundary included.

    Not a format check. The declared closure is re-audited against the live
    import/exec graph first -- a stale manifest is the shape that would let
    unverified code train under a green certificate -- and only then are the
    member bytes re-hashed. CI runs this same function; it is the mechanism,
    not a mirror of one.
    """

    repo_root = pathlib.Path(repo_root)
    closure = load_closure_module(repo_root)
    try:
        manifest = closure.load_manifest(repo_root)
        audit = closure.audit_closure(repo_root, manifest)
    except ValueError as error:
        raise ValueError(f"training dependency closure is unusable: {error}") from error
    if not audit.ok:
        raise ValueError(
            "live training dependency closure fails its own boundary guard:\n"
            + audit.failure_report()
        )
    return _require_sha256(
        closure.compute_closure_hash(repo_root, manifest),
        "live training dependency closure hash",
    )


def read_pin_is_ancestor(repo_root: pathlib.Path, pin: str) -> bool:
    """Whether the certificate's verified-at commit is an ancestor of live HEAD.

    Closure equality alone would accept a tree that never contained the
    verified commit; this keeps the launch on the same history.
    """

    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "merge-base",
            "--is-ancestor",
            pin,
            "HEAD",
        ],
        check=False,
        capture_output=True,
        text=True,
        shell=False,
    )
    return result.returncode == 0


def read_current_master(repo_root: pathlib.Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
        shell=False,
    )
    if result.returncode != 0:
        raise ValueError("current public master is unreadable")
    return _require_git_sha(result.stdout.strip(), "current public master")


def _validate_completion_receipt(
    value: dict[str, Any], public_master_sha: str
) -> None:
    _require_keys(value, COMPLETION_RECEIPT_KEYS, "completion receipt")
    if value["schema"] != "ember-01-completion-receipt-v1" or value["ok"] is not True:
        raise ValueError("completion receipt is not a successful EMBER-01 receipt")

    legs = _require_object(value["certificate_legs"], "completion certificate legs")
    expected_legs = {str(index) for index in range(1, 10)}
    if set(legs) != expected_legs or any(
        state != COMPLETION_LEG_RESOLVED_TRUE for state in legs.values()
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

    if value["completion_subject_goal_id"] != "EMBER-01":
        raise ValueError("completion subject is not EMBER-01")
    selection = _require_object(value["selection"], "completion selection")
    if selection.get("unchanged_during_verification") is not True:
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
        if (
            isinstance(requested_value, bool)
            or not isinstance(requested_value, (int, float))
            or isinstance(authorized_value, bool)
            or not isinstance(authorized_value, (int, float))
            or requested_value < 0
            or requested_value > authorized_value
        ):
            raise ValueError(
                f"run scope exceeds certificate: {requested_key}"
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
    if set(certificate) - OPTIONAL_CERTIFICATE_KEYS != CERTIFICATE_KEYS:
        raise ValueError("certificate schema keys mismatch")
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
    guard_floor_present = GUARD_FLOOR_CERTIFICATE_KEYS & set(certificate)
    for key in sorted(guard_floor_present):
        value = certificate[key]
        if not isinstance(value, str) or not value:
            raise ValueError(f"certificate {key} must be a non-empty string")

    certificate_sha256 = _canonical_sha256(certificate)
    ledger_rows = _load_ledger(declaration_ledger_path)
    if not any(
        row["certificate_sha256"] == certificate_sha256 for row in ledger_rows
    ):
        raise ValueError("declaration ledger membership is missing")

    completion_receipt_path = certificate["completion_receipt_path"]
    if not isinstance(completion_receipt_path, str) or not completion_receipt_path:
        raise ValueError("certificate completion_receipt_path must be a non-empty string")
    completion_path = pathlib.Path(completion_receipt_path)
    if guard_floor_present:
        # Post-#1410 certificates: the path must be custody-portable. An
        # absolute local path baked into a sha-cited payload is unredactable
        # post-mint; a ".." segment would let the sha-cited payload reference
        # bytes outside the custody root.
        if completion_path.is_absolute():
            raise ValueError(
                "certificate completion_receipt_path must be relative to the "
                "certificate directory, not absolute"
            )
        if ".." in completion_path.parts:
            raise ValueError(
                "certificate completion_receipt_path must not traverse above "
                "the certificate directory"
            )
        # is_absolute() is False on Windows for anchored-but-incomplete paths:
        # "/M/ember/x.json" (drive-root-relative) and "C:x.json" (drive-relative)
        # both carry an anchor with no ".." part, so the two checks above admit
        # them. Neither is custody-portable -- what they name depends on the
        # drive the certificate happens to sit on.
        if completion_path.drive or completion_path.root:
            raise ValueError(
                "certificate completion_receipt_path must not name a drive or "
                "root anchor"
            )
        # Resolved backstop for anything the syntactic checks miss (a symlinked
        # segment, a differing drive letter).
        certificate_directory = certificate_path.parent.resolve()
        resolved = (certificate_path.parent / completion_path).resolve()
        if not resolved.is_relative_to(certificate_directory):
            raise ValueError(
                "certificate completion_receipt_path must resolve under the "
                "certificate directory"
            )
    if not completion_path.is_absolute():
        completion_path = certificate_path.parent / completion_path
    completion = _load_json(completion_path, "completion receipt")
    if _file_sha256(
        completion_path, "completion receipt"
    ) != certificate["completion_receipt_sha256"]:
        raise ValueError("completion receipt hash mismatch")
    _validate_completion_receipt(completion, certificate["public_master_sha"])

    conjuncts = _require_object(
        certificate["declaration_conjuncts"], "declaration conjuncts"
    )
    _require_keys(conjuncts, DECLARATION_CONJUNCT_KEYS, "declaration conjuncts")
    if any(value is not True for value in conjuncts.values()):
        raise ValueError("B7 declaration conjunct is false")

    # Closure binding when the certificate carries one. public_master_sha stays
    # the VERIFIED-AT commit, and live-HEAD equality is replaced by exactly two
    # checks: the closure recomputed from live bytes equals the certificate's,
    # and the verified-at commit is an ancestor of live HEAD. So a docs-only
    # merge -- which cannot affect a training run -- no longer stalls one, while
    # "you train exactly the verified training code" is untouched: a changed
    # closure file still rejects, even at the pinned tip. Certificates minted
    # before closure_sha256 existed fall back to whole-tip equality.
    current_master = read_current_master(repo_root)
    certificate_closure_sha256 = certificate.get("closure_sha256")
    if certificate_closure_sha256 is None:
        if certificate["public_master_sha"] != current_master:
            raise ValueError("certificate does not bind current public master")
    else:
        _require_sha256(certificate_closure_sha256, "certificate closure_sha256")
        if read_live_closure_sha256(repo_root) != certificate_closure_sha256:
            raise ValueError(
                "certificate does not bind the live training dependency closure"
            )
        if not read_pin_is_ancestor(repo_root, certificate["public_master_sha"]):
            raise ValueError(
                "certificate verified-at commit is not an ancestor of current HEAD"
            )

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
        or not isinstance(run_spec["runner_receipt"], str)
        or not run_spec["runner_receipt"]
    ):
        raise ValueError("run spec scalar fields are invalid")

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
        closure_sha256=certificate_closure_sha256,
        artifact_root=pathlib.Path(requested_scope["artifact_root"]),
        custody_root=custody_root,
        runner_receipt=runner_receipt,
        seed=run_spec["seed"],
        write_budget_bytes=int(requested_scope["write_budget_bytes"]),
        max_records=int(requested_scope["max_records"]),
        max_c_write_gib=float(requested_scope["max_c_write_gib"]),
        max_b_write_gib=float(requested_scope["max_b_write_gib"]),
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
        "--seed",
        str(launch.seed),
        "--artifact-root",
        str(launch.artifact_root),
        "--write-budget-bytes",
        str(launch.write_budget_bytes),
        "--max-records",
        str(launch.max_records),
    ]


def _child_log_path(launch: ValidatedLaunch) -> pathlib.Path:
    """Log file the fixed runner's stdout+stderr are redirected to.

    Lives under custody_root (preserved, not devnulled) so the consumer's own
    stdout stays a single pure JSON line for the cockpit handshake. Named
    alongside the runner receipt so the two are trivially correlated.
    """
    return launch.custody_root / f"{launch.runner_receipt.stem}-child.log"


def _write_execution_receipt(
    launch: ValidatedLaunch,
    argv: list[str],
    exit_code: int,
    child_log_path: pathlib.Path | None = None,
) -> pathlib.Path:
    receipt_path = _execution_receipt_path(launch)
    receipt = {
        "schema_version": "ember-certified-train-execution-v1",
        "certificate_sha256": launch.certificate_sha256,
        "run_spec_sha256": launch.run_spec_sha256,
        "public_master_sha": launch.public_master_sha,
        "closure_sha256": launch.closure_sha256,
        "argv": argv,
        "exit_code": exit_code,
        "artifact_root": str(launch.artifact_root),
        "runner_receipt": str(launch.runner_receipt),
        "child_log": str(child_log_path) if child_log_path is not None else None,
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
    # argv is certificate-visible (an execution receipt pins argv[1] to the
    # fixed runner path) so bytecode suppression rides the spawn env instead
    # of an -B argv insertion, which would shift that pinned position.
    child_env = os.environ.copy()
    child_env["PYTHONDONTWRITEBYTECODE"] = "1"
    # The child (disk_budget_runner -> run_vertical_slice) must NEVER inherit
    # this consumer's stdout: this process's own final line is the cockpit's
    # machine-readable handshake (main()'s json.dumps), and any training-log
    # noise interleaved ahead of it breaks JSON.parse on the whole stream
    # (issue #1408). Redirect the child's stdout+stderr to a log file under
    # custody_root instead -- preserved for debugging, never devnulled.
    child_log_path = _child_log_path(launch)
    child_log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(child_log_path, "wb") as child_log:
        result = run_process(
            argv,
            shell=False,
            check=False,
            cwd=repo_root,
            env=child_env,
            stdout=child_log,
            stderr=subprocess.STDOUT,
        )
    exit_code = int(result.returncode)
    _write_execution_receipt(launch, argv, exit_code, child_log_path=child_log_path)
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
