# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Certified dense >=3B A1 training core and post-energy receipt finalizer."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import struct
import time
from typing import Any, Iterator

import torch
import torch.nn.functional as F

from a1_checkpoint import write_dense_checkpoint
from a1_dense import A1_CONFIG_SHA256, DenseA1Config, DenseA1Decoder
from a1_optimizer import FullStateAdamWCPUOffload, load_a1_optimizer_contract
from durable_io import atomic_create_durable


CORE_SCHEMA = "ember-a1-dense-run-core-v1"
RUN_SCHEMA = "ember02-r1-e8-run-v1"
CORE_FIELDS = {
    "schema_version", "status", "source_commit", "certified_launch_sha256",
    "parameter_count", "optimizer_inventory", "checkpoint_sha256",
    "comparison_authority", "checkpoint_identity", "resource_preflight",
}
RESOURCE_PREFLIGHT_FIELDS = {
    "schema_version", "status", "parameter_count", "model_bytes",
    "gradient_bytes", "cpu_fp32_optimizer_bytes", "checkpoint_payload_floor_bytes",
    "transient_checkpoint_bytes", "host_commit_reserve_bytes",
    "gpu_free_margin_bytes", "b_custody_floor_bytes", "available_commit_bytes",
    "device_free_bytes", "custody_free_bytes", "required_commit_bytes",
    "required_device_bytes", "required_custody_bytes", "governor",
    # #1464: the a1-dense-tier1 route now binds the same canonical disk
    # budget runner authority every other production route embeds (was
    # previously an unconditional-refusal stub); this closed-schema field
    # carries that startup authority alongside the governor receipt so the
    # dense receipt records the same runner evidence the semantic route does.
    "canonical_runner",
}
OPTIMIZER_INVENTORY_FIELDS = {
    "schema_version", "state_format", "registered_parameters", "registered_numel",
    "initialized_parameters", "cpu_fp32_master_numel",
    "cpu_fp32_first_moment_numel", "cpu_fp32_second_moment_numel", "complete",
}


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    atomic_create_durable(path, _canonical(value) + b"\n")


def _load(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is unavailable or invalid") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _tokens(receipt_path: Path, shards_root: Path) -> Iterator[int]:
    receipt = _load(receipt_path, "A1 token shards receipt")
    shards = receipt.get("shards")
    if receipt.get("ticket") != "TOKEN-SHARDS-V0" or not isinstance(shards, list) or not shards:
        raise ValueError("A1 token shards receipt is not admitted")
    for row in shards:
        if not isinstance(row, dict) or set(row) != {"name", "sha256", "n_tokens"}:
            raise ValueError("A1 token shard inventory is invalid")
        path = shards_root / row["name"]
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != row["sha256"] or len(raw) != 2 * row["n_tokens"]:
            raise ValueError("A1 token shard bytes disagree with receipt")
        yield from struct.unpack(f"<{row['n_tokens']}H", raw)


def _train_step_envelope(
    *, run_id: str, step: int, tokens: int, loss: float, grad_norm: float,
    wall_seconds: float,
) -> dict[str, Any]:
    """The frozen `train_step` telemetry envelope
    (`docs/spec/ember02-r1-e8-receipts-v1.md`): `{"ts":..., "kind":"train_step",
    "source":"ember-restart-3b", "payload": {...}}`, extended with `tokens` and
    `wall_seconds` for `a1_e8_evidence.derive_liveness_series`.

    `wall_seconds` is the whole-boundary per-step duration, measured the same
    way `pretrain.py`'s `step_ms` is (`time.perf_counter()` at step start,
    differenced at telemetry-write time) -- reported in seconds rather than
    milliseconds because that is the unit the liveness series requires.

    `proxy_joules` is deliberately absent HERE. `energy_proxy_logger.py`
    samples GPU/CPU draw through an out-of-process sidecar communicating
    with this training process only through a pidfile (the #1489 lesson: an
    evidence sampler must never be able to block or crash certified
    training), so this function has no live channel to a sample while a
    step is executing -- there is nothing honest to attribute in-loop.
    `proxy_joules` is instead derived by a POST-PASS,
    `a1_energy_apportionment.enrich_telemetry_with_energy` (issue #1464's
    second residual), which reopens this envelope's `ts`/`wall_seconds` and
    the sidecar's raw persisted samples once both processes have closed,
    and rewrites the telemetry file in place wherever a real sample record
    honestly covers a step's interval -- never a placeholder. A run whose
    sidecar samples do not cover a given step (no sampler ran, sparse
    coverage, or the step's interval reaches outside the sample record's
    own timestamp range) leaves that row exactly as this function emits it,
    and `derive_liveness_series` correctly continues to find it
    liveness-incomplete.
    """
    return {
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "kind": "train_step",
        "source": "ember-restart-3b",
        "payload": {
            "run_id": run_id,
            "step": step,
            "tokens": tokens,
            "loss": format(float(loss), ".12f"),
            "grad_norm": format(float(grad_norm), ".12f"),
            "wall_seconds": format(float(wall_seconds), ".12f"),
        },
    }


def run_dense_a1(
    *,
    repo_root: Path,
    seed: int,
    artifact_root: Path,
    token_shards_receipt: Path,
    shards_root: Path,
    comparison_authority: Path,
    steps: int,
    sequence_length: int,
    checkpoint_interval: int,
    write_budget_bytes: int,
    telemetry_path: Path,
    telemetry_run_id: str,
    resource_preflight: dict[str, Any],
) -> dict[str, Any]:
    if (
        not isinstance(resource_preflight, dict)
        or set(resource_preflight) != RESOURCE_PREFLIGHT_FIELDS
        or resource_preflight.get("schema_version") != "ember-a1-resource-preflight-v1"
        or resource_preflight.get("status") != "PASS"
    ):
        raise ValueError("dense A1 resource preflight receipt is absent or invalid")
    source_commit = os.environ.get("EMBER_A1_SOURCE_COMMIT")
    certified_launch_sha256 = os.environ.get("EMBER_A1_CERTIFIED_LAUNCH_SHA256")
    if (
        not isinstance(source_commit, str)
        or len(source_commit) != 40
        or any(character not in "0123456789abcdef" for character in source_commit)
        or not isinstance(certified_launch_sha256, str)
        or len(certified_launch_sha256) != 64
        or any(character not in "0123456789abcdef" for character in certified_launch_sha256)
    ):
        raise RuntimeError("dense A1 certified source identity is unavailable")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for certified dense A1 execution")
    config_path = Path(repo_root) / "tools" / "ember-restart-3b" / "ember-restart-3b-a1.json"
    config = DenseA1Config.from_contract(config_path, repo_root=Path(repo_root))
    if resource_preflight.get("parameter_count") != config.structural_parameter_count():
        raise ValueError("dense A1 resource preflight parameter count drifted")
    comparison = _load(Path(comparison_authority), "A1 comparison authority")
    matched_ref = comparison.get("matched_a3_run")
    if not isinstance(matched_ref, dict) or set(matched_ref) != {"path", "sha256"}:
        raise ValueError("A1 comparison matched-run reference is invalid")
    matched_path = Path(comparison_authority).parent / matched_ref["path"]
    if _sha(matched_path) != matched_ref["sha256"]:
        raise ValueError("matched A3 run changed before dense allocation")
    matched = _load(matched_path, "matched A3 run")
    matched_identity = matched.get("identity")
    if not isinstance(matched_identity, dict):
        raise ValueError("matched A3 identity is unavailable")
    checkpoint_identity = {
        "comparison_id": comparison.get("comparison_id"),
        "matched_identity": dict(matched_identity),
        "config_sha256": _sha(config_path),
        "source_commit": source_commit,
        "certified_launch_sha256": certified_launch_sha256,
        "tier": "TIER_1",
        "mechanism": "FULL_STATE_ADAMW_CPU_OFFLOAD",
        "predecessor": None,
    }
    # Meta construction is the no-allocation structural admission. The live
    # allocation below is a separate dense class, never UnifiedDecoder.
    meta = DenseA1Decoder(config, device="meta")
    if sum(parameter.numel() for parameter in meta.parameters()) != config.structural_parameter_count():
        raise RuntimeError("dense A1 meta inventory differs from contract")
    del meta
    model = DenseA1Decoder(
        config,
        device="cuda",
        allow_production_allocation=True,
        genesis_seed=seed,
    )
    optimizer = FullStateAdamWCPUOffload(
        model.parameters(), contract=load_a1_optimizer_contract(config_path)
    )
    optimizer.initialize_state()
    # #1464: the whole-model gradient set is the eliminable component of the
    # OOM composite (CPU optimizer state ~46 GiB + GPU params + GPU grads +
    # transients exceeded every lawful job-commit cap). Fusing the update
    # into backward frees each parameter's gradient immediately after its
    # own contribution lands, so the full gradient set never coexists.
    optimizer.enable_fused_backward()
    stream = iter(_tokens(Path(token_shards_receipt), Path(shards_root)))
    telemetry_path.parent.mkdir(parents=True, exist_ok=True)
    tokens_seen = 0
    checkpoint_sha = None
    with telemetry_path.open("a", encoding="utf-8", newline="\n") as telemetry:
        for step in range(1, steps + 1):
            step_started = time.perf_counter()
            batch = [next(stream) for _ in range(sequence_length + 1)]
            input_ids = torch.tensor(batch[:-1], device="cuda", dtype=torch.long).unsqueeze(0)
            targets = torch.tensor(batch[1:], device="cuda", dtype=torch.long).unsqueeze(0)
            optimizer.zero_grad(set_to_none=True)
            loss = F.cross_entropy(model(input_ids).reshape(-1, config.vocab_size), targets.reshape(-1))
            loss.backward()
            optimizer.step()
            grad_norm = optimizer.finish_gradient_norm()
            tokens_seen += sequence_length
            telemetry.write(json.dumps(
                _train_step_envelope(
                    run_id=telemetry_run_id, step=step, tokens=sequence_length,
                    loss=float(loss.detach()), grad_norm=grad_norm,
                    wall_seconds=time.perf_counter() - step_started,
                ),
                sort_keys=True,
            ) + "\n")
            telemetry.flush()
            if step % checkpoint_interval == 0 or step == steps:
                checkpoint = artifact_root / f"checkpoint-a1-step-{step}"
                _, checkpoint_sha = write_dense_checkpoint(
                    checkpoint,
                    model=model,
                    optimizer=optimizer,
                    global_step=step,
                    tokens_seen=tokens_seen,
                    identity=checkpoint_identity,
                )
    if checkpoint_sha is None:
        raise RuntimeError("dense A1 execution produced no checkpoint")
    core = {
        "schema_version": CORE_SCHEMA,
        "status": "TERMINAL",
        "source_commit": source_commit,
        "certified_launch_sha256": certified_launch_sha256,
        "parameter_count": config.structural_parameter_count(),
        "optimizer_inventory": optimizer.state_inventory(),
        "checkpoint_sha256": checkpoint_sha,
        "checkpoint_identity": checkpoint_identity,
        "resource_preflight": resource_preflight,
        "comparison_authority": {"path": str(comparison_authority), "sha256": _sha(Path(comparison_authority))},
    }
    _atomic_json(artifact_root / "a1-run-core.json", core)
    return core


def _threshold(path: Path, identifier: str) -> Decimal:
    payload = _load(path, "R1 threshold authority")
    entries = payload.get("entries")
    if payload.get("schema_version") != "ember02-preregistration-thresholds-v1" or payload.get("frozen") is not True or not isinstance(entries, list):
        raise ValueError("R1 threshold authority is invalid")
    matches = [row for row in entries if isinstance(row, dict) and row.get("id") == identifier]
    if len(matches) != 1:
        raise ValueError(f"R1 threshold {identifier} is absent or duplicated")
    try:
        value = Decimal(str(matches[0]["value"]))
    except (InvalidOperation, KeyError, TypeError) as error:
        raise ValueError(f"R1 threshold {identifier} is invalid") from error
    if not value.is_finite():
        raise ValueError(f"R1 threshold {identifier} is invalid")
    return value


def finalize_tier1_run(
    *,
    artifact_root: Path,
    energy_receipt: Path,
    thresholds_path: Path,
    expected_source_commit: str,
    expected_certified_launch_sha256: str,
    expected_comparison_authority: Path,
) -> Path:
    """Mint Packet-A run only after a complete, consistent energy window."""
    artifact_root = Path(artifact_root)
    output = artifact_root / "tier1-run.json"
    core_path = artifact_root / "a1-run-core.json"
    core = _load(core_path, "A1 run core")
    energy = _load(Path(energy_receipt), "energy receipt")
    if set(core) != CORE_FIELDS:
        raise ValueError("A1 run core schema is not closed")
    if (
        core.get("schema_version") != CORE_SCHEMA
        or core.get("status") != "TERMINAL"
        or core.get("source_commit") != expected_source_commit
        or core.get("certified_launch_sha256") != expected_certified_launch_sha256
        or type(core.get("parameter_count")) is not int
        or core["parameter_count"] < 3_000_000_000
    ):
        raise ValueError("A1 run core is not terminal")
    resource_preflight = core.get("resource_preflight")
    if (
        not isinstance(resource_preflight, dict)
        or set(resource_preflight) != RESOURCE_PREFLIGHT_FIELDS
        or resource_preflight.get("schema_version") != "ember-a1-resource-preflight-v1"
        or resource_preflight.get("status") != "PASS"
        or resource_preflight.get("parameter_count") != core.get("parameter_count")
    ):
        raise ValueError("A1 run core resource preflight is invalid")
    energy_block = energy.get("energy")
    t06 = _threshold(Path(thresholds_path), "T-06")
    if (
        energy.get("schema_version") != "ember-energy-proxy-run-v1"
        or energy.get("result") != "MEASURED"
        or energy.get("executed") is not True
        or energy.get("training_launched") is not True
        or not isinstance(energy_block, dict)
    ):
        raise ValueError("energy receipt is not a measured training window")
    coverage_value = energy_block.get("sample_coverage_fraction")
    try:
        coverage = Decimal(str(coverage_value))
    except (InvalidOperation, TypeError) as error:
        raise ValueError("energy sample coverage is invalid") from error
    intended = energy.get("intended_samples")
    captured = energy.get("captured_samples")
    if (
        type(intended) is not int
        or intended <= 0
        or type(captured) is not int
        or not 0 <= captured <= intended
        or coverage != Decimal(captured) / Decimal(intended)
        or Decimal(str(energy.get("t06_coverage_floor"))) != t06
        or energy.get("coverage_meets_t06") is not (coverage >= t06)
    ):
        raise ValueError("energy sample coverage is inconsistent")
    if not coverage.is_finite() or coverage < t06 or coverage > Decimal("1"):
        raise ValueError("energy sample coverage is incomplete or inconsistent")
    comparison_ref = core.get("comparison_authority")
    if not isinstance(comparison_ref, dict) or set(comparison_ref) != {"path", "sha256"}:
        raise ValueError("A1 comparison authority binding is absent")
    comparison_path = Path(comparison_ref["path"])
    if comparison_path.resolve(strict=False) != Path(
        expected_comparison_authority
    ).resolve(strict=False):
        raise ValueError("A1 run core substituted its comparison authority")
    if _sha(comparison_path) != comparison_ref["sha256"]:
        raise ValueError("A1 comparison authority changed after execution")
    comparison = _load(comparison_path, "A1 comparison authority")
    matched = comparison_path.parent / comparison["matched_a3_run"]["path"]
    if _sha(matched) != comparison["matched_a3_run"]["sha256"]:
        raise ValueError("matched A3 run changed after execution")
    a3 = _load(matched, "matched A3 run")
    expected_checkpoint_identity = {
        "comparison_id": comparison.get("comparison_id"),
        "matched_identity": dict(a3["identity"]),
        "config_sha256": A1_CONFIG_SHA256,
        "source_commit": core["source_commit"],
        "certified_launch_sha256": core["certified_launch_sha256"],
        "tier": "TIER_1",
        "mechanism": "FULL_STATE_ADAMW_CPU_OFFLOAD",
        "predecessor": None,
    }
    if core.get("checkpoint_identity") != expected_checkpoint_identity:
        raise ValueError("A1 checkpoint identity is thin, stale, or swapped")
    optimizer_inventory = core.get("optimizer_inventory")
    expected_parameters = core.get("parameter_count")
    if (
        not isinstance(optimizer_inventory, dict)
        or set(optimizer_inventory) != OPTIMIZER_INVENTORY_FIELDS
        or optimizer_inventory.get("complete") is not True
        or any(
            optimizer_inventory.get(field) != expected_parameters
            for field in (
                "registered_numel", "cpu_fp32_master_numel",
                "cpu_fp32_first_moment_numel", "cpu_fp32_second_moment_numel",
            )
        )
    ):
        raise ValueError("A1 run core does not prove complete full-state AdamW")
    identity = dict(a3["identity"])
    identity["genesis_sha256"] = comparison["genesis_authority_sha256"]
    run = {
        "schema_version": RUN_SCHEMA,
        "arm_id": "A1",
        "tier": "TIER1",
        "mechanism": "FULL_STATE_ADAMW_CPU_OFFLOAD",
        "status": "TERMINAL",
        "certified_launch_sha256": core["certified_launch_sha256"],
        "source_commit": core["source_commit"],
        "architecture_revision": "ember-dense-a1-3b-v1",
        "parameter_count": core["parameter_count"],
        "active_parameter_count": core["parameter_count"],
        "contains_router_or_experts": False,
        "optimizer": {
            "kind": "AdamW", "full_state": True, "cpu_offload": True,
            "covered_parameter_count": core["parameter_count"],
        },
        "identity": identity,
        "energy_sample_coverage": format(coverage, ".12f"),
        "checkpoint_sha256": core["checkpoint_sha256"],
    }
    run["receipt_sha256"] = hashlib.sha256(_canonical(run)).hexdigest()
    _atomic_json(output, run)
    return output
