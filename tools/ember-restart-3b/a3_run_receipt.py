# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Mint the R1-E8 A3-arm run receipt (schema `ember02-r1-e8-run-v1`, arm_id "A3").

`scripts/r1_e8_validator.validate_e8` and `certified_train_launch.py`'s matched-A3
verification both consume a matched A3 run receipt, but no producer existed in the
repository: `tools/ember-restart-3b/a1_execution.py` mints only the A1 counterpart.
Without an A3 producer no matched pair can ever exist and R1-E8 stays evidence-missing.

Every emitted field is either reopened from a named, already-produced artifact or the
mint refuses -- there are no caller-typed literal measurements. The six real inputs:

  telemetry_path + run_id   -- the run's own telemetry JSONL; proves the run executed
                                and stepped under the claimed run_id (existence gate
                                only, contributes no receipt field).
  energy_receipt_path       -- `ember-energy-proxy-run-v1` (energy_proxy_logger.py
                                run_watch output) -- energy_sample_coverage, reopened
                                and arithmetic-reverified the same way
                                a1_execution.finalize_tier1_run reverifies the A1 leg.
  checkpoint_receipt_path   -- a small pointer receipt naming the real checkpoint
                                artifact on disk; checkpoint_sha256 is *recomputed*
                                from those bytes, never trusted from the pointer.
  comparison_authority_path -- the shared A1/A3 comparison-identity document (the same
                                shape certified_train_launch.py's A1 route consumes,
                                short of the matched_a3_run back-reference, which
                                cannot exist before this receipt does -- see the module
                                docstring note below); comparison_id and every identity
                                hash come from here.
  certificate_path          -- the certified-launch certificate governing this run
                                (the same public_master_sha the paired A1 launch
                                certifies against); source_commit.
  run_spec_path              -- the certified run spec bytes this A3 run executed
                                under; certified_launch_sha256 = sha256(bytes).
  architecture_manifest_path -- `ember-a3-architecture-manifest-v1`, the closed
                                architecture/optimizer facts of the run (no A3
                                training module exists in this repository yet, so
                                this is the declared artifact contract a future A3
                                harness must produce -- mirroring how a1_execution.py
                                requires a resource_preflight receipt from its caller
                                rather than deriving it itself).

Before persisting, the assembled receipt is self-validated against the REAL consumer
validator (`scripts.r1_e8_validator._validate_run`) so producer and consumer can never
silently drift.

Bootstrap-order note on `comparison_authority_path`: certified_train_launch.py's own
A1 route requires the comparison-authority document's `matched_a3_run` field to
already point at a real, self-consistent A3 receipt -- which cannot be true before
this function has run once. This mint therefore accepts the comparison authority
identified only by the fields it actually needs (comparison_id and the identity
hashes), not the full closed A1-route schema; the `matched_a3_run` back-reference is
added by whoever refreezes the comparison authority AFTER this receipt is minted.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from durable_io import atomic_create_durable

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent.parent / "scripts"


def _load_e8_validator():
    spec = importlib.util.spec_from_file_location(
        "r1_e8_validator_for_a3_mint", SCRIPTS / "r1_e8_validator.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUN_SCHEMA = "ember02-r1-e8-run-v1"
ARCHITECTURE_SCHEMA = "ember-a3-architecture-manifest-v1"
CHECKPOINT_POINTER_SCHEMA = "ember-a3-checkpoint-receipt-v1"
CURSOR_ZERO = {"global_step": 0, "record_index": 0, "tokens_seen": 0}

ARCHITECTURE_FIELDS = {
    "schema_version", "tier", "mechanism", "architecture_revision",
    "parameter_count", "active_parameter_count", "contains_router_or_experts",
    "optimizer",
}
OPTIMIZER_FIELDS = {"kind", "full_state", "cpu_offload", "covered_parameter_count"}
CHECKPOINT_POINTER_FIELDS = {"schema_version", "checkpoint_path", "checkpoint_sha256"}
COMPARISON_IDENTITY_KEYS = (
    "comparison_id", "token_shards_receipt_sha256", "shard_sequence_sha256",
    "tokenizer_sha256", "seed", "cursor_start", "schedule_sha256",
    "genesis_authority_sha256",
)


class A3ReceiptRefused(ValueError):
    """Every refusal names the missing or invalid input; never a silent None."""


def _canonical(value: object) -> bytes:
    # Self-digest input bytes: compact JSON, NO trailing newline, matching
    # a1_execution.py's own A1-arm receipt minting and
    # scripts/r1_e8_validator.py's `_self_digest`/`_reopen_ref` -- the check
    # the real `validate_e8` pipeline runs on every reopened A3 run receipt.
    # certified_train_launch.py's matched-A3 gate was amended (fix(training):
    # align matched-A3 self-digest convention, #1464) to a dedicated
    # `_matched_a3_self_digest_sha256` helper matching this same convention,
    # so one receipt_sha256 now satisfies both real full pipelines.
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha_file(path: Path, label: str) -> str:
    try:
        return _sha_bytes(path.read_bytes())
    except OSError as error:
        raise A3ReceiptRefused(f"{label} is unreadable: {path}") from error


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise A3ReceiptRefused(f"{label} is absent or invalid JSON: {path}") from error
    if not isinstance(value, dict):
        raise A3ReceiptRefused(f"{label} must be a JSON object: {path}")
    return value


def _require_git_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 40 or value.lower() != value:
        raise A3ReceiptRefused(f"{label} must be a lowercase 40-hex Git object id")
    try:
        int(value, 16)
    except ValueError as error:
        raise A3ReceiptRefused(f"{label} must be a lowercase 40-hex Git object id") from error
    return value


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or value.lower() != value:
        raise A3ReceiptRefused(f"{label} must be a lowercase SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as error:
        raise A3ReceiptRefused(f"{label} must be a lowercase SHA-256 hex digest") from error
    return value


# ---------------------------------------------------------------------------
# Leg 1: telemetry -- run existence + step evidence gate only, no field derives
# from it. A receipt whose run never stepped is refused before anything else
# is even opened.
# ---------------------------------------------------------------------------

def _require_run_stepped(telemetry_path: Path, run_id: str) -> None:
    try:
        lines = Path(telemetry_path).read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise A3ReceiptRefused(f"A3 run telemetry is unavailable: {telemetry_path}") from error
    matched_steps = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise A3ReceiptRefused(f"A3 run telemetry contains an unparseable row: {telemetry_path}") from error
        if not isinstance(row, dict):
            raise A3ReceiptRefused(f"A3 run telemetry row is not an object: {telemetry_path}")
        if row.get("run_id") == run_id and isinstance(row.get("step"), int) and row["step"] > 0:
            matched_steps += 1
    if matched_steps == 0:
        raise A3ReceiptRefused(
            f"A3 run telemetry names no stepped row for run_id={run_id!r}: {telemetry_path}"
        )


# ---------------------------------------------------------------------------
# Leg 2: energy -- reopened and arithmetic-reverified the same way
# a1_execution.finalize_tier1_run reverifies the A1 leg; refuses below T-06.
# ---------------------------------------------------------------------------

def _threshold_t06(thresholds_path: Path) -> Decimal:
    payload = _load_json(Path(thresholds_path), "R1 threshold authority")
    entries = payload.get("entries")
    if (
        payload.get("schema_version") != "ember02-preregistration-thresholds-v1"
        or payload.get("frozen") is not True
        or not isinstance(entries, list)
    ):
        raise A3ReceiptRefused("R1 threshold authority is invalid or not frozen")
    matches = [row for row in entries if isinstance(row, dict) and row.get("id") == "T-06"]
    if len(matches) != 1:
        raise A3ReceiptRefused("R1 threshold T-06 is absent or duplicated")
    try:
        value = Decimal(str(matches[0]["value"]))
    except (InvalidOperation, KeyError, TypeError) as error:
        raise A3ReceiptRefused("R1 threshold T-06 is invalid") from error
    if not value.is_finite():
        raise A3ReceiptRefused("R1 threshold T-06 is invalid")
    return value


def _energy_sample_coverage(energy_receipt_path: Path, t06: Decimal) -> Decimal:
    energy = _load_json(Path(energy_receipt_path), "A3 energy proxy receipt")
    energy_block = energy.get("energy")
    if (
        energy.get("schema_version") != "ember-energy-proxy-run-v1"
        or energy.get("result") != "MEASURED"
        or energy.get("executed") is not True
        or energy.get("training_launched") is not True
        or not isinstance(energy_block, dict)
    ):
        raise A3ReceiptRefused("A3 energy proxy receipt is not a measured training window")
    coverage_value = energy_block.get("sample_coverage_fraction")
    try:
        coverage = Decimal(str(coverage_value))
    except (InvalidOperation, TypeError) as error:
        raise A3ReceiptRefused("A3 energy sample coverage is invalid") from error
    intended = energy.get("intended_samples")
    captured = energy.get("captured_samples")
    if (
        type(intended) is not int
        or intended <= 0
        or type(captured) is not int
        or not 0 <= captured <= intended
        or coverage != Decimal(captured) / Decimal(intended)
    ):
        raise A3ReceiptRefused("A3 energy sample coverage is arithmetically inconsistent")
    try:
        declared_floor = Decimal(str(energy.get("t06_coverage_floor")))
    except (InvalidOperation, TypeError) as error:
        raise A3ReceiptRefused("A3 energy receipt T-06 floor is invalid") from error
    if declared_floor != t06 or energy.get("coverage_meets_t06") is not (coverage >= t06):
        raise A3ReceiptRefused("A3 energy receipt T-06 floor binding is inconsistent")
    if not coverage.is_finite() or coverage < Decimal("0") or coverage > Decimal("1"):
        raise A3ReceiptRefused("A3 energy sample coverage is out of range")
    if coverage < t06:
        raise A3ReceiptRefused(
            f"A3 energy sample coverage {coverage} is below the T-06 floor {t06}; run is not credited"
        )
    return coverage


# ---------------------------------------------------------------------------
# Leg 3: checkpoint -- the pointer receipt is only a locator; checkpoint_sha256
# is recomputed from the real bytes on disk, never trusted from the pointer.
# ---------------------------------------------------------------------------

def _checkpoint_sha256(checkpoint_receipt_path: Path) -> str:
    checkpoint_receipt_path = Path(checkpoint_receipt_path)
    pointer = _load_json(checkpoint_receipt_path, "A3 checkpoint pointer receipt")
    if set(pointer) != CHECKPOINT_POINTER_FIELDS or pointer.get("schema_version") != CHECKPOINT_POINTER_SCHEMA:
        raise A3ReceiptRefused("A3 checkpoint pointer receipt schema is invalid")
    rel = pointer.get("checkpoint_path")
    if not isinstance(rel, str) or not rel:
        raise A3ReceiptRefused("A3 checkpoint pointer receipt names no checkpoint_path")
    rel_path = Path(rel)
    if rel_path.is_absolute() or ".." in rel_path.parts:
        raise A3ReceiptRefused("A3 checkpoint pointer path must be receipt-relative and non-traversing")
    checkpoint_path = (checkpoint_receipt_path.parent / rel_path).resolve()
    if checkpoint_receipt_path.parent.resolve() not in checkpoint_path.parents:
        raise A3ReceiptRefused("A3 checkpoint pointer path escaped the receipt directory")
    if not checkpoint_path.is_file():
        raise A3ReceiptRefused(f"A3 checkpoint artifact is absent: {checkpoint_path}")
    actual = _sha_file(checkpoint_path, "A3 checkpoint artifact")
    declared = pointer.get("checkpoint_sha256")
    if not isinstance(declared, str) or declared.lower() != declared or actual != declared:
        raise A3ReceiptRefused("A3 checkpoint pointer sha256 disagrees with the real checkpoint bytes")
    return actual


# ---------------------------------------------------------------------------
# Leg 4: comparison authority (identity) + Leg 5: certificate + run spec
# (certified_launch_sha256, source_commit) -- consumed, never invented.
# ---------------------------------------------------------------------------

def _identity_from_comparison_authority(comparison_authority_path: Path) -> dict[str, Any]:
    comparison = _load_json(Path(comparison_authority_path), "A1/A3 comparison authority")
    if comparison.get("schema_version") != "ember-a1-comparison-authority-v1":
        raise A3ReceiptRefused("comparison authority schema mismatch")
    missing = [key for key in COMPARISON_IDENTITY_KEYS if key not in comparison]
    if missing:
        raise A3ReceiptRefused(f"comparison authority is missing identity keys: {missing}")
    cursor_start = comparison.get("cursor_start")
    if cursor_start != CURSOR_ZERO:
        raise A3ReceiptRefused("comparison authority cursor_start is not the clean-genesis zero cursor")
    if type(comparison.get("seed")) is not int:
        raise A3ReceiptRefused("comparison authority seed must be an integer")
    identity = {
        "comparison_id": comparison["comparison_id"],
        "corpus_authority_sha256": _require_sha256(
            comparison["token_shards_receipt_sha256"], "comparison authority token_shards_receipt_sha256"
        ),
        "shard_sequence_sha256": _require_sha256(
            comparison["shard_sequence_sha256"], "comparison authority shard_sequence_sha256"
        ),
        "tokenizer_sha256": _require_sha256(
            comparison["tokenizer_sha256"], "comparison authority tokenizer_sha256"
        ),
        "seed": comparison["seed"],
        "cursor_start": cursor_start,
        "schedule_sha256": _require_sha256(
            comparison["schedule_sha256"], "comparison authority schedule_sha256"
        ),
        "genesis_sha256": _require_sha256(
            comparison["genesis_authority_sha256"], "comparison authority genesis_authority_sha256"
        ),
    }
    if not isinstance(comparison["comparison_id"], str) or not comparison["comparison_id"]:
        raise A3ReceiptRefused("comparison authority comparison_id must be a non-empty string")
    return identity


def _source_commit(certificate_path: Path) -> str:
    certificate = _load_json(Path(certificate_path), "A3 certified-launch certificate")
    return _require_git_sha(certificate.get("public_master_sha"), "certificate public_master_sha")


def _certified_launch_sha256(run_spec_path: Path) -> str:
    return _sha_file(Path(run_spec_path), "A3 certified run spec")


# ---------------------------------------------------------------------------
# Leg 6: architecture -- no A3 training module exists in this repository yet;
# this is the declared artifact contract a real A3 harness must produce.
# ---------------------------------------------------------------------------

def _architecture(architecture_manifest_path: Path) -> dict[str, Any]:
    manifest = _load_json(Path(architecture_manifest_path), "A3 architecture manifest")
    if set(manifest) != ARCHITECTURE_FIELDS or manifest.get("schema_version") != ARCHITECTURE_SCHEMA:
        raise A3ReceiptRefused("A3 architecture manifest schema is not closed")
    if not isinstance(manifest.get("tier"), str) or not manifest["tier"]:
        raise A3ReceiptRefused("A3 architecture manifest tier must be a non-empty string")
    if not isinstance(manifest.get("mechanism"), str) or not manifest["mechanism"]:
        raise A3ReceiptRefused("A3 architecture manifest mechanism must be a non-empty string")
    revision = manifest.get("architecture_revision")
    if not isinstance(revision, str) or not revision:
        raise A3ReceiptRefused("A3 architecture manifest architecture_revision must be a non-empty string")
    parameter_count = manifest.get("parameter_count")
    active_parameter_count = manifest.get("active_parameter_count")
    if (
        type(parameter_count) is not int or parameter_count <= 0
        or type(active_parameter_count) is not int or active_parameter_count <= 0
        or active_parameter_count > parameter_count
    ):
        raise A3ReceiptRefused("A3 architecture manifest parameter counts are invalid")
    if not isinstance(manifest.get("contains_router_or_experts"), bool):
        raise A3ReceiptRefused("A3 architecture manifest contains_router_or_experts must be a bool")
    optimizer = manifest.get("optimizer")
    if not isinstance(optimizer, dict) or set(optimizer) != OPTIMIZER_FIELDS:
        raise A3ReceiptRefused("A3 architecture manifest optimizer block is not closed")
    if (
        not isinstance(optimizer.get("kind"), str) or not optimizer["kind"]
        or not isinstance(optimizer.get("full_state"), bool)
        or not isinstance(optimizer.get("cpu_offload"), bool)
        or optimizer.get("covered_parameter_count") != parameter_count
    ):
        raise A3ReceiptRefused("A3 architecture manifest optimizer block is invalid")
    return {
        "tier": manifest["tier"],
        "mechanism": manifest["mechanism"],
        "architecture_revision": revision,
        "parameter_count": parameter_count,
        "active_parameter_count": active_parameter_count,
        "contains_router_or_experts": manifest["contains_router_or_experts"],
        "optimizer": dict(optimizer),
    }


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def mint_a3_run_receipt(
    *,
    output_path: Path,
    telemetry_path: Path,
    run_id: str,
    energy_receipt_path: Path,
    thresholds_path: Path,
    checkpoint_receipt_path: Path,
    comparison_authority_path: Path,
    certificate_path: Path,
    run_spec_path: Path,
    architecture_manifest_path: Path,
) -> Path:
    """Mint the A3-arm run receipt from real executed-run artifacts only.

    Every distinguishable missing/invalid input raises `A3ReceiptRefused` naming
    which artifact failed, before anything is written. The output is written with
    `atomic_create_durable`, which refuses to overwrite an existing file.
    """
    if not isinstance(run_id, str) or not run_id:
        raise A3ReceiptRefused("run_id must be a non-empty string")

    _require_run_stepped(Path(telemetry_path), run_id)
    t06 = _threshold_t06(Path(thresholds_path))
    coverage = _energy_sample_coverage(Path(energy_receipt_path), t06)
    checkpoint_sha256 = _checkpoint_sha256(Path(checkpoint_receipt_path))
    identity = _identity_from_comparison_authority(Path(comparison_authority_path))
    source_commit = _source_commit(Path(certificate_path))
    certified_launch_sha256 = _certified_launch_sha256(Path(run_spec_path))
    architecture = _architecture(Path(architecture_manifest_path))

    run: dict[str, Any] = {
        "schema_version": RUN_SCHEMA,
        "arm_id": "A3",
        "tier": architecture["tier"],
        "mechanism": architecture["mechanism"],
        "status": "TERMINAL",
        "certified_launch_sha256": certified_launch_sha256,
        "source_commit": source_commit,
        "architecture_revision": architecture["architecture_revision"],
        "parameter_count": architecture["parameter_count"],
        "active_parameter_count": architecture["active_parameter_count"],
        "contains_router_or_experts": architecture["contains_router_or_experts"],
        "optimizer": architecture["optimizer"],
        "identity": identity,
        "energy_sample_coverage": format(coverage, ".12f"),
        "checkpoint_sha256": checkpoint_sha256,
    }
    run["receipt_sha256"] = _sha_bytes(_canonical(run))

    # Self-check against the REAL consumer validator before persisting anything,
    # so this producer and scripts/r1_e8_validator.py can never silently drift.
    validator = _load_e8_validator()
    try:
        validator._validate_run(run, arm="A3", tier=None, t06=t06)
    except validator.E8ValidationError as error:
        raise A3ReceiptRefused(f"assembled A3 receipt fails the real R1-E8 validator: {error}") from error

    output_path = Path(output_path)
    # On-disk bytes carry a trailing newline (matching a1_execution.py's own
    # `_atomic_json`); the digest above was computed on `_canonical(run)`
    # without one, over `run` before `receipt_sha256` was added -- the file
    # write re-serializes the now-complete dict, so the two calls to
    # `_canonical` intentionally differ only by the receipt_sha256 key and
    # this trailing newline, never by convention.
    atomic_create_durable(output_path, _canonical(run) + b"\n")
    return output_path
