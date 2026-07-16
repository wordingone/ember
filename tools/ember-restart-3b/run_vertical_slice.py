# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Bounded CUDA one-batch sparse slice; invoke only through the disk budget runner."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Callable

import tokenizers
import torch
import torch.nn.functional as F

from batch import decode_owned_batch
from checkpoint_artifacts import load_checkpoint_artifacts, preflight_specialist_lineage_sources, write_checkpoint_artifacts
from model import RestartDecoderConfig, UnifiedDecoder
from pretrain import run_manifest_bound_semantic_segment, run_pretraining_segment
from parameter_counter import measure_parameter_counts
from semantic_stream import ManifestBoundTokenStream
from train import run_launch


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def specialist_resume_cursor(cursor: dict[str, object], *, data_shard_id: str) -> dict[str, object]:
    """Preserve global accounting while starting a new verified specialist source at zero."""
    if not isinstance(data_shard_id, str) or not data_shard_id.startswith("VERIFIED_SPECIALIST:"):
        raise ValueError("specialist cursor requires a verified specialist source identity")
    global_step, tokens_seen = cursor.get("global_step"), cursor.get("tokens_seen")
    if type(global_step) is not int or global_step < 0 or type(tokens_seen) is not int or tokens_seen < 0:
        raise ValueError("resume cursor lacks nonnegative global counters")
    return {"shard": data_shard_id, "record_index": 0, "global_step": global_step, "tokens_seen": tokens_seen}


def resume_expert_genesis(manifest: dict[str, Any], *, requested_seed: int) -> dict[str, str]:
    """Carry verified parent genesis through resume; a new launch seed cannot rewrite lineage."""

    if not isinstance(requested_seed, int) or requested_seed < 0:
        raise ValueError("resume requested seed must be nonnegative")
    genesis = manifest.get("expert_genesis_sha256")
    expected = {"vision", "audio", "reasoning", "tool"}
    if not isinstance(genesis, dict) or set(genesis) != expected:
        raise ValueError("resume manifest lacks four verified expert genesis hashes")
    for name, digest in genesis.items():
        if not isinstance(digest, str) or len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError(f"resume manifest has malformed {name} genesis hash")
    return dict(genesis)

def production_memory_preflight(*, total_parameters: int, active_parameters: int, device_free_bytes: int) -> dict[str, int | str]:
    """Derive the exact BF16 episode envelope before CUDA model construction."""
    if min(total_parameters, active_parameters, device_free_bytes) <= 0 or active_parameters > total_parameters:
        raise ValueError("production memory preflight requires positive total/active/free byte values")
    parameter_bytes = total_parameters * 2
    gradient_bytes = active_parameters * 2
    optimizer_state_bytes = active_parameters * 2
    activation_reserve_bytes = 4 * 1024**3
    runtime_reserve_bytes = 2 * 1024**3
    required_bytes = parameter_bytes + gradient_bytes + optimizer_state_bytes + activation_reserve_bytes + runtime_reserve_bytes
    if required_bytes > device_free_bytes:
        raise MemoryError(f"BF16 production envelope requires {required_bytes} bytes but only {device_free_bytes} are free; refusing before allocation")
    return {
        "parameter_dtype": "bfloat16",
        "parameter_bytes": parameter_bytes,
        "gradient_bytes": gradient_bytes,
        "optimizer_state_bytes": optimizer_state_bytes,
        "activation_reserve_bytes": activation_reserve_bytes,
        "runtime_reserve_bytes": runtime_reserve_bytes,
        "required_bytes": required_bytes,
        "device_free_bytes": device_free_bytes,
    }
def checkpoint_serialization_byte_bound(config_path: Path, *, active_parameters: int | None = None) -> int:
    """Derive one publishable checkpoint bound from the frozen architecture and optimizer contract."""

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    serialization = payload.get("checkpoints", {}).get("serialization")
    required = {"model_parameter_bytes", "optimizer_state_bytes_per_active_parameter", "format_overhead_bytes"}
    if not isinstance(serialization, dict) or set(serialization) != required:
        raise ValueError("checkpoint serialization contract has an invalid shape")
    if any(type(serialization[field]) is not int or serialization[field] < 1 for field in required):
        raise ValueError("checkpoint serialization contract requires positive integer bounds")
    memory = load_memory_contract(config_path)
    if serialization["model_parameter_bytes"] != memory["parameter_bytes"] or serialization["optimizer_state_bytes_per_active_parameter"] != memory["optimizer_state_bytes_per_active_parameter"]:
        raise ValueError("checkpoint serialization contract drifts from the BF16 optimizer memory contract")
    config = RestartDecoderConfig.from_contract(config_path)
    specialist_parameters = config.layers * 12 * config.hidden_size * config.hidden_size
    shared_active_parameters = config.structural_parameter_count() - len(config.expert_names) * specialist_parameters
    selected_active_parameters = shared_active_parameters if active_parameters is None else active_parameters
    if type(selected_active_parameters) is not int or selected_active_parameters < shared_active_parameters or selected_active_parameters > config.structural_parameter_count():
        raise ValueError("checkpoint serialization active parameter count is outside the frozen architecture")
    return (
        config.structural_parameter_count() * serialization["model_parameter_bytes"]
        + selected_active_parameters * serialization["optimizer_state_bytes_per_active_parameter"]
        + serialization["format_overhead_bytes"]
    )


def semantic_publication_plan(*, steps: int, checkpoint_interval: int, checkpoint_byte_bound: int, write_budget_bytes: int, initial_global_step: int = 0) -> dict[str, int]:
    """Bound checkpoint publications using a frozen derived byte bound, never a caller estimate."""

    if (not isinstance(steps, int) or steps < 1 or not isinstance(checkpoint_interval, int) or checkpoint_interval < 1
            or not isinstance(checkpoint_byte_bound, int) or checkpoint_byte_bound < 1
            or not isinstance(write_budget_bytes, int) or write_budget_bytes < 1 or not isinstance(initial_global_step, int) or initial_global_step < 0):
        raise ValueError("semantic publication plan requires positive integer steps, interval, derived bound, and write budget")
    final_global_step = initial_global_step + steps
    periodic = sum(1 for step in range(initial_global_step + 1, final_global_step + 1) if step % checkpoint_interval == 0)
    publication_count = periodic + (0 if final_global_step % checkpoint_interval == 0 else 1)
    projected_write_bytes = publication_count * checkpoint_byte_bound
    if projected_write_bytes > write_budget_bytes:
        raise ValueError("semantic publication plan exceeds the declared write budget")
    return {"publication_count": publication_count, "checkpoint_byte_bound": checkpoint_byte_bound, "projected_write_bytes": projected_write_bytes}
def specialist_publication_plan(
    *, records: int, checkpoint_interval: int, checkpoint_byte_bound: int,
    write_budget_bytes: int, initial_global_step: int,
) -> dict[str, int]:
    """Bound every specialist publication, including the mandatory final bundle."""

    if (
        not isinstance(records, int) or records < 1
        or not isinstance(checkpoint_interval, int) or checkpoint_interval < 1
        or not isinstance(checkpoint_byte_bound, int) or checkpoint_byte_bound < 1
        or not isinstance(write_budget_bytes, int) or write_budget_bytes < 1
        or not isinstance(initial_global_step, int) or initial_global_step < 0
    ):
        raise ValueError("specialist publication plan requires positive integer records, interval, bound, budget, and global step")
    final_global_step = initial_global_step + records
    periodic = sum(
        1
        for step in range(initial_global_step + 1, final_global_step + 1)
        if step % checkpoint_interval == 0
    )
    publication_count = periodic + (0 if final_global_step % checkpoint_interval == 0 else 1)
    projected_write_bytes = publication_count * checkpoint_byte_bound
    if projected_write_bytes > write_budget_bytes:
        raise ValueError("specialist publication plan exceeds the declared write budget")
    return {
        "publication_count": publication_count,
        "checkpoint_byte_bound": checkpoint_byte_bound,
        "projected_write_bytes": projected_write_bytes,
    }

def production_artifact_root(
    candidate: Path,
    *,
    c_relocated_under_disk_budget_runner: bool = False,
    relocation_custody_root: Path | None = None,
) -> Path:
    """Accept B: custody, or an explicit C: child of the disk-runner custody root."""

    if type(c_relocated_under_disk_budget_runner) is not bool:
        raise ValueError("C relocation custody flag must be boolean")
    resolved = candidate.resolve()
    if c_relocated_under_disk_budget_runner:
        if not isinstance(relocation_custody_root, Path):
            raise ValueError("runner-bound C relocation requires an explicit custody root")
        custody = relocation_custody_root.resolve()
        if custody.drive.upper() != "C:" or resolved.drive.upper() != "C:" or not resolved.is_relative_to(custody):
            raise ValueError("runner-bound C relocation requires a C: custody root containing the artifact root")
        return resolved
    if relocation_custody_root is not None:
        raise ValueError("relocation custody root requires runner-bound C relocation")
    if resolved.drive.upper() != "B:":
        raise ValueError("production artifact root must be an explicit B: path unless runner-bound C relocation is declared")
    return resolved


def _bundle_serialized_bytes(bundle: Path) -> int:
    """Measure exactly the bytes currently published beneath one bundle root."""
    return sum(path.stat().st_size for path in bundle.rglob("*") if path.is_file())

def _receipt_valid_for_retention(bundle: Path) -> bool:
    try:
        require_counter_success_receipt(bundle)
    except (OSError, ValueError, TypeError):
        return False
    return True

def _enforce_retention(parent: Path, *, max_count: int | None = None, max_serialized_bytes: int | None = None, receipt_aware: bool = False) -> None:
    """Prune only older successful bundles; never delete the final known-good bundle."""
    if max_count is None and max_serialized_bytes is None:
        raise ValueError("checkpoint retention requires a count or serialized-byte budget")
    if max_count is not None and max_count < 1:
        raise ValueError("checkpoint retention count must retain at least one bundle")
    if max_serialized_bytes is not None and max_serialized_bytes < 1:
        raise ValueError("checkpoint retention serialized-byte budget must be positive")
    parent.mkdir(parents=True, exist_ok=True)
    candidates = (path for path in parent.iterdir() if path.is_dir() and path.name.startswith("checkpoint-"))
    bundles = sorted(
        (path for path in candidates if not receipt_aware or _receipt_valid_for_retention(path)),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
    )
    if max_count is not None:
        while len(bundles) > max_count:
            shutil.rmtree(bundles.pop(0))
    if max_serialized_bytes is not None:
        total = sum(_bundle_serialized_bytes(bundle) for bundle in bundles)
        while total > max_serialized_bytes and len(bundles) > 1:
            shutil.rmtree(bundles.pop(0))
            total = sum(_bundle_serialized_bytes(bundle) for bundle in bundles)
        if total > max_serialized_bytes:
            raise RuntimeError("published checkpoint exceeds serialized-byte retention budget while preserving the final known-good bundle")


def _retain_after_success(
    parent: Path, *, operation: Callable[[], Any], max_count: int | None = None, max_serialized_bytes: int | None = None, receipt_aware: bool = False
) -> Any:
    """Publish first, then prune only successful older bundles."""

    if max_count is None and max_serialized_bytes is None:
        raise ValueError("successful checkpoint retention requires a bound")
    result = operation()
    _enforce_retention(parent, max_count=max_count, max_serialized_bytes=max_serialized_bytes, receipt_aware=receipt_aware)
    return result


def load_verified_specialist_records(
    *, root: Path, data_manifest: Path, tokenizer_path: Path, capability: str,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Execute the independent manifest verifier and admit one routed expert family."""

    expert_for_capability = {"image": "vision", "audio": "audio", "reasoning": "reasoning", "tool": "tool"}
    if capability not in expert_for_capability:
        raise ValueError("specialist capability must be image, audio, reasoning, or tool")
    root = root.resolve()
    manifest = data_manifest.resolve()
    if root not in manifest.parents:
        raise ValueError("specialist data manifest must reside in the selected worktree")
    verifier = Path(__file__).with_name("verify_training_data.py")
    completed = subprocess.run(
        [sys.executable, "-I", "-c", "import runpy,sys;sys.path[:0]=[sys.argv[1],sys.argv[2]];sys.argv=sys.argv[3:];runpy.run_path(sys.argv[0],run_name=\"__main__\")", str(verifier.parent.resolve()), str(Path(tokenizers.__file__).resolve().parent.parent), str(verifier), "--data-manifest", str(manifest), "--tokenizer", str(tokenizer_path), "--capability", capability],
        cwd=root, env={name: os.environ[name] for name in ("SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP") if name in os.environ}, text=True, capture_output=True, check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"specialist data verifier failed: {completed.stderr.strip() or completed.stdout.strip()}")
    try:
        verification = json.loads(completed.stdout)
        manifest_bytes = manifest.read_bytes()
        payload = json.loads(manifest_bytes)
    except json.JSONDecodeError as error:
        raise RuntimeError("specialist data verifier or manifest did not emit JSON") from error
    if not isinstance(verification, dict) or verification.get("result") != "VERIFIED" or verification.get("capability") != capability:
        raise RuntimeError("specialist data verifier did not produce the required verified receipt")
    if verification.get("generator_replay_verified") is not True:
        raise RuntimeError("specialist data verifier did not prove canonical generator replay")
    if verification.get("data_manifest_sha256") != hashlib.sha256(manifest_bytes).hexdigest():
        raise RuntimeError("verified specialist data manifest changed after verification")

    def reread_bound_artifact(reference: object, *, receipt_field: str, label: str) -> tuple[Path, bytes]:
        relative = reference.get("path") if isinstance(reference, dict) else None
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            raise RuntimeError(f"verified specialist manifest lacks a {label} artifact path")
        path = (root / relative).resolve()
        if root not in path.parents or not path.is_file():
            raise RuntimeError(f"verified specialist {label} artifact path escapes the worktree")
        artifact_bytes = path.read_bytes()
        if verification.get(receipt_field) != hashlib.sha256(artifact_bytes).hexdigest():
            raise RuntimeError(f"verified specialist {label} artifact changed after verification")
        return path, artifact_bytes

    reread_bound_artifact(payload.get("source_manifest") if isinstance(payload, dict) else None, receipt_field="source_manifest_sha256", label="source manifest")
    _records_path, records_bytes = reread_bound_artifact(payload.get("records_artifact") if isinstance(payload, dict) else None, receipt_field="records_artifact_sha256", label="records")
    records_payload = json.loads(records_bytes)
    records = records_payload.get("records") if isinstance(records_payload, dict) else None
    if not isinstance(records, list) or not records or any(not isinstance(record, dict) for record in records):
        raise RuntimeError("verified specialist records artifact is malformed")
    if {record.get("active_expert") for record in records} != {expert_for_capability[capability]}:
        raise RuntimeError("verified specialist records do not contain exactly the requested route")
    return records, verification

def load_authorized_records(root: Path) -> tuple[list[dict[str, object]], dict[str, object], dict[str, object]]:
    """Consume #812 identity before reading the exact owned four-domain bytes."""

    packet, validation, input_receipt = run_launch(repo_root=root)
    if validation["decision"] != "ACCEPTED":
        raise RuntimeError("input launch gate did not accept the selected shard")
    identity = packet.get("input_identity")
    if not isinstance(identity, dict):
        raise RuntimeError("accepted launch packet lacks a concrete input identity")
    if identity.get("artifact_id") == "owned-clean-curriculum-128-v1" or identity.get("shard_path") == "data/ember-restart-3b/owned-curriculum-128.json":
        raise RuntimeError("retired bootstrap curriculum is mechanics-only evidence and cannot drive production training")
    shard = root / str(packet["input_identity"]["shard_path"])
    payload = json.loads(shard.read_text(encoding="utf-8"))
    records = payload.get("records") if isinstance(payload, dict) else None
    if payload.get("schema_version") != "ember-owned-pretraining-shard-v1" or not isinstance(records, list) or not records:
        raise RuntimeError("production slice requires a nonempty owned four-domain shard")
    if {record.get("active_expert") for record in records if isinstance(record, dict)} != {"vision", "audio", "reasoning", "tool"}:
        raise RuntimeError("production slice requires one record for every declared expert")
    return records, packet, input_receipt


_COUNTER_SUCCESS_RECEIPT = "parameter-counter-receipt.json"
_COUNTER_FAILURE_RECEIPT = "counter-failure.json"
_COUNTER_COUNT_FIELDS = (
    "allocated_parameters",
    "unique_parameters",
    "trainable_parameters",
    "served_parameters",
    "active_parameters",
    "episode_trainable_parameters",
)


def _atomic_bytes(path: Path, payload: bytes) -> None:
    """Publish small custody evidence only after complete bytes are durable."""

    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    _atomic_bytes(path, (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))


def _json_snapshot(path: Path, *, label: str) -> tuple[dict[str, object], str]:
    try:
        payload = path.read_bytes()
        parsed = json.loads(payload)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not valid JSON") from error
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must be a JSON object")
    return parsed, hashlib.sha256(payload).hexdigest()


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def require_counter_success_receipt(checkpoint_root: Path, *, receipt_path: Path | None = None) -> dict[str, object]:
    """Make resumability contingent on the exact successful realization counter output."""

    checkpoint_root = checkpoint_root.resolve()
    manifest, manifest_sha256 = _json_snapshot(checkpoint_root / "checkpoint-manifest.json", label="checkpoint manifest")
    receipt_source = (receipt_path if receipt_path is not None else checkpoint_root / _COUNTER_SUCCESS_RECEIPT).resolve()
    receipt, _receipt_sha256 = _json_snapshot(receipt_source, label="counter-success receipt")
    expected = {
        "schema_version": "ember-sparse-realization-receipt-v1", "verification_boundary": "VERIFIED_MEASURED",
        "result": "MEASURED", "subject_checkpoint_sha256": manifest_sha256,
        "model_config_sha256": manifest.get("model_config_sha256"), "architecture_revision": manifest.get("architecture_revision"),
        "active_expert_ids": manifest.get("active_expert_ids"), "counter_sha256": _sha256(Path(__file__).with_name("parameter_counter.py")),
    }
    if any(receipt.get(field) != value for field, value in expected.items()):
        raise ValueError("counter-success receipt does not bind this checkpoint realization")
    architecture = manifest.get("architecture")
    if not isinstance(architecture, dict) or any(receipt.get(field) != architecture.get(field) for field in _COUNTER_COUNT_FIELDS):
        raise ValueError("counter-success receipt does not reproduce checkpoint capacity")
    if not _is_sha256(receipt.get("counter_sha256")):
        raise ValueError("counter-success receipt has an invalid counter source hash")
    return receipt


def _quarantine_counter_failed_checkpoint(checkpoint_target: Path, error: BaseException) -> Path | None:
    """Delete bulk candidate bytes while retaining only bounded manifest/failure evidence."""

    if not checkpoint_target.exists():
        return None
    evidence = checkpoint_target.parent / f".counter-failed-{checkpoint_target.name}-{uuid.uuid4().hex}"
    evidence.mkdir()
    manifest_path = checkpoint_target / "checkpoint-manifest.json"
    manifest_sha256: str | None = None
    if manifest_path.is_file():
        manifest_bytes = manifest_path.read_bytes()
        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        _atomic_bytes(evidence / "checkpoint-manifest.json", manifest_bytes)
    _atomic_json(evidence / _COUNTER_FAILURE_RECEIPT, {
        "schema_version": "ember-counter-failure-v1", "result": "COUNTER_FAILED",
        "checkpoint_manifest_sha256": manifest_sha256, "error_type": type(error).__name__,
        "error": str(error), "bulk_candidate_cleanup": "deleted",
    })
    shutil.rmtree(checkpoint_target)
    if checkpoint_target.exists():
        raise RuntimeError("counter-failed checkpoint could not be removed from the selectable namespace")
    return evidence


def publish_counter_verified_checkpoint(*, checkpoint_target: Path, write_candidate: Callable[[], dict[str, object]], execute_counter: Callable[[], dict[str, object]]) -> tuple[dict[str, object], dict[str, object]]:
    """Cover candidate creation through realization verification in one fail-closed transaction."""

    target_existed = checkpoint_target.exists()
    if target_existed:
        raise FileExistsError(f"published checkpoint bundle already exists: {checkpoint_target}")
    try:
        published = write_candidate()
        counter_receipt = execute_counter()
        _atomic_json(checkpoint_target / _COUNTER_SUCCESS_RECEIPT, counter_receipt)
        require_counter_success_receipt(checkpoint_target)
    except BaseException as error:
        if not target_existed:
            _quarantine_counter_failed_checkpoint(checkpoint_target, error)
        raise
    return published, counter_receipt

def production_resume_checkpoint(
    candidate: Path,
    *,
    counter_success_receipt: Path | None = None,
    c_relocated_under_disk_budget_runner: bool = False,
    relocation_custody_root: Path | None = None,
) -> Path:
    """Accept only a published, counter-verified B: or runner-custodied C: bundle."""

    resolved = candidate.resolve()
    accepted = resolved.drive.upper() == "B:" and resolved.is_dir()
    if not accepted and c_relocated_under_disk_budget_runner:
        resolved = production_artifact_root(
            resolved,
            c_relocated_under_disk_budget_runner=True,
            relocation_custody_root=relocation_custody_root,
        )
        accepted = resolved.is_dir()
    if not accepted:
        raise ValueError("resume checkpoint must be a published B: bundle or declared C: custody bundle")
    require_counter_success_receipt(resolved, receipt_path=counter_success_receipt)
    return resolved

def checkpoint_retention_budget_bytes(config_path: Path) -> int:
    """Load the measured serialized-byte ceiling for published checkpoint bundles."""
    try:
        retention = json.loads(config_path.read_text(encoding="utf-8"))["checkpoints"]["retention"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("production contract must declare checkpoint retention") from error
    gib = retention.get("max_serialized_gib") if isinstance(retention, dict) else None
    if not isinstance(gib, int) or gib < 1 or retention.get("preserve_last_known_good") is not True:
        raise ValueError("checkpoint retention must declare a positive serialized-byte budget and preserve the last good bundle")
    return gib * 1024**3

def checkpoint_retention_limit(config_path: Path) -> int:
    """Read the contract retention policy instead of maintaining a runner-local copy."""

    try:
        value = json.loads(config_path.read_text(encoding="utf-8"))["checkpoints"]["retention"]["max_count"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("production contract must declare checkpoint retention") from error
    if not isinstance(value, int) or value < 1:
        raise ValueError("checkpoint retention max_count must be a positive integer")
    return value


def load_memory_contract(config_path: Path) -> dict[str, object]:
    """Load the numerics declaration that must agree with the allocation preflight."""
    try:
        value = json.loads(config_path.read_text(encoding="utf-8"))["training"]["memory"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("production contract must declare BF16 memory numerics") from error
    expected = {
        "parameter_dtype": "bfloat16",
        "parameter_bytes": 2,
        "gradient_bytes_per_active_parameter": 2,
        "optimizer_state_bytes_per_active_parameter": 2,
        "activation_reserve_gib": 4,
        "runtime_reserve_gib": 2,
    }
    if value != expected:
        raise ValueError("production BF16 memory contract differs from the audited numerical envelope")
    return dict(value)

def load_optimizer_contract(config_path: Path) -> dict[str, object]:
    """Load the one structured optimizer declaration used by config, runtime, and checkpoint."""

    try:
        contract = json.loads(config_path.read_text(encoding="utf-8"))["training"]["optimizer"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("production contract must declare a structured optimizer") from error
    if not isinstance(contract, dict) or set(contract) != {"name", "implementation", "hyperparameters", "state_format"}:
        raise ValueError("production optimizer contract has an invalid shape")
    expected = {
        "name": "paged_8bit_adamw",
        "implementation": "bitsandbytes.optim.PagedAdamW8bit",
        "state_format": "bitsandbytes-paged-8bit-adamw-state-dict-v1",
    }
    if any(contract.get(field) != value for field, value in expected.items()):
        raise ValueError("production optimizer contract does not declare canonical PagedAdamW8bit")
    hyperparameters = contract.get("hyperparameters")
    if not isinstance(hyperparameters, dict) or set(hyperparameters) != {"learning_rate", "weight_decay", "percentile_clipping", "block_wise"}:
        raise ValueError("production optimizer hyperparameters have an invalid shape")
    if (not isinstance(hyperparameters["learning_rate"], (int, float)) or hyperparameters["learning_rate"] <= 0 or not isinstance(hyperparameters["weight_decay"], (int, float)) or hyperparameters["weight_decay"] < 0 or not isinstance(hyperparameters["percentile_clipping"], int) or hyperparameters["percentile_clipping"] <= 0 or not isinstance(hyperparameters["block_wise"], bool)):
        raise ValueError("production optimizer hyperparameters are invalid")
    return contract

def _rng_state(device: torch.device) -> dict[str, torch.Tensor]:
    return {"cpu": torch.get_rng_state().clone(), "cuda": torch.cuda.get_rng_state(device).clone()}


def _rng_state_hash(device: torch.device) -> dict[str, str]:
    return {
        name: hashlib.sha256(state.cpu().numpy().tobytes()).hexdigest()
        for name, state in _rng_state(device).items()
    }

def _execute_realization_counter(
    *,
    root: Path,
    config_path: Path,
    checkpoint_manifest_path: Path,
    active_expert: str,
    expected_counts: dict[str, object],
    parent_manifest: Path | None = None,
    root_manifest: Path | None = None,
) -> dict[str, object]:
    counter_path = root / "tools" / "ember-restart-3b" / "parameter_counter.py"
    if (parent_manifest is None) != (root_manifest is None):
        raise ValueError("counter replay requires both external parent and root manifests")
    arguments = [
        sys.executable,
        "-I",
        str(counter_path),
        "--model-config",
        str(config_path),
        "--checkpoint-manifest",
        str(checkpoint_manifest_path),
        "--active-expert",
        active_expert,
    ]
    if parent_manifest is not None and root_manifest is not None:
        arguments.extend(["--parent-manifest", str(parent_manifest), "--root-manifest", str(root_manifest)])
    completed = subprocess.run(
        arguments,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"isolated parameter counter failed: {completed.stderr.strip()}")
    try:
        receipt = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("isolated parameter counter did not emit JSON") from error
    required = (
        "allocated_parameters",
        "unique_parameters",
        "trainable_parameters",
        "served_parameters",
        "active_parameters",
        "episode_trainable_parameters",
        "active_expert_ids",
    )
    if any(receipt.get(name) != expected_counts.get(name) for name in required):
        raise RuntimeError("isolated parameter counter disagrees with instantiated capacity")
    if receipt.get("counter_sha256") != _sha256(counter_path):
        raise RuntimeError("isolated parameter counter source hash is not self-consistent")
    return receipt


def build_production_optimizer(model: UnifiedDecoder, *, optimizer_contract: dict[str, object]) -> torch.optim.Optimizer:
    """Build exactly the structured PagedAdamW8bit optimizer declared by config."""

    if optimizer_contract.get("implementation") != "bitsandbytes.optim.PagedAdamW8bit":
        raise ValueError("production optimizer implementation must be PagedAdamW8bit")
    hyperparameters = optimizer_contract.get("hyperparameters")
    if not isinstance(hyperparameters, dict):
        raise ValueError("production optimizer contract lacks hyperparameters")
    import bitsandbytes as bnb

    return bnb.optim.PagedAdamW8bit(
        model.parameters(),
        lr=float(hyperparameters["learning_rate"]),
        weight_decay=float(hyperparameters["weight_decay"]),
        percentile_clipping=int(hyperparameters["percentile_clipping"]),
        block_wise=bool(hyperparameters["block_wise"]),
    )

def run(
    *, seed: int, artifact_root: Path, resume_checkpoint: Path | None = None, resume_counter_receipt: Path | None = None,
    records_override: list[dict[str, object]] | None = None,
    specialist_verification: dict[str, object] | None = None,
    specialist_lineage: dict[str, object] | None = None,
    checkpoint_interval: int | None = None,
    write_budget_bytes: int | None = None,
    c_relocated_under_disk_budget_runner: bool = False,
    relocation_custody_root: Path | None = None,
) -> dict[str, object]:
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for the production vertical slice")
    if not isinstance(seed, int) or seed < 0:
        raise ValueError("launch seed must be a nonnegative integer")
    artifact_root = production_artifact_root(
        artifact_root,
        c_relocated_under_disk_budget_runner=c_relocated_under_disk_budget_runner,
        relocation_custody_root=relocation_custody_root,
    )
    root = Path(__file__).resolve().parents[2]
    config_path = root / "configs" / "ember-restart-3b.json"
    integration_contract_path = root / "docs" / "ember-restart" / "integration-contract-v1.md"
    if not integration_contract_path.is_file():
        raise RuntimeError("the merged Ember integration contract is required for production launch")
    config = RestartDecoderConfig.from_contract(config_path)
    memory_contract = load_memory_contract(config_path)
    total_parameters = config.structural_parameter_count()
    active_parameters = total_parameters - (len(config.expert_names) - 1) * config.layers * 12 * config.hidden_size * config.hidden_size
    device_free_bytes, _device_total_bytes = torch.cuda.mem_get_info()
    memory_preflight = production_memory_preflight(
        total_parameters=total_parameters,
        active_parameters=active_parameters,
        device_free_bytes=int(device_free_bytes),
    )
    if memory_preflight["parameter_dtype"] != memory_contract["parameter_dtype"]:
        raise RuntimeError("memory preflight and production numerics disagree")
    if records_override is None:
        records, launch_packet, input_receipt = load_authorized_records(root)
        data_shard_id = str(launch_packet["input_identity"]["shard_path"])
    else:
        if not records_override or not isinstance(specialist_verification, dict) or not isinstance(specialist_lineage, dict):
            raise ValueError("specialist production run requires verified routed records and v4 lineage")
        if checkpoint_interval is None or write_budget_bytes is None:
            raise ValueError("specialist production run requires an explicit checkpoint interval and write budget")
        records = records_override
        launch_packet = {"input_identity": {"shard_path": "verified-specialist"}}
        input_receipt = specialist_verification
        data_shard_id = "VERIFIED_SPECIALIST:" + str(specialist_verification["data_manifest_sha256"])[:12]
    checkpoint_parent = artifact_root / "checkpoints"
    checkpoint_root = checkpoint_parent / f"checkpoint-vertical-slice-seed-{seed}"

    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    rng_state_before_init = _rng_state_hash(torch.device("cuda"))
    previous_dtype = torch.get_default_dtype()
    torch.set_default_dtype(torch.bfloat16)
    try:
        model = UnifiedDecoder(config, device="cuda", allow_production_allocation=True, genesis_seed=seed)
    finally:
        torch.set_default_dtype(previous_dtype)
    genesis_hashes = model.expert_bank_genesis_hashes()
    model.train()
    counts = measure_parameter_counts(model)
    if counts["unique_parameters"] != 3_839_161_856 or counts["active_parameters"] != 1_725_232_640:
        raise RuntimeError("instantiated sparse counts differ from the authorized architecture")
    optimizer_contract = load_optimizer_contract(config_path)
    optimizer = build_production_optimizer(model, optimizer_contract=optimizer_contract)
    resume_cursor = {"record_index": 0, "global_step": 0, "tokens_seen": 0}
    if resume_checkpoint is not None:
        resume_checkpoint = production_resume_checkpoint(
            resume_checkpoint,
            counter_success_receipt=resume_counter_receipt,
            c_relocated_under_disk_budget_runner=c_relocated_under_disk_budget_runner,
            relocation_custody_root=relocation_custody_root,
        )
        manifest_path = resume_checkpoint / "checkpoint-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        genesis_hashes = resume_expert_genesis(manifest, requested_seed=seed)
        receipt = {**manifest, "checkpoint_manifest_sha256": _sha256(manifest_path)}
        resume_cursor = load_checkpoint_artifacts(model, optimizer, resume_checkpoint, receipt)["data_cursor"]
        for group in optimizer.param_groups:
            group["lr"] = 1e-5
        if records_override is not None:
            resume_cursor = specialist_resume_cursor(resume_cursor, data_shard_id=data_shard_id)
        checkpoint_root = checkpoint_parent / f"checkpoint-continue-seed-{seed}-from-step-{resume_cursor['global_step'] + len(records)}"
    checkpoint_byte_bound = checkpoint_serialization_byte_bound(config_path, active_parameters=active_parameters)
    specialist_plan: dict[str, int] | None = None
    if records_override is not None:
        specialist_plan = specialist_publication_plan(
            records=len(records), checkpoint_interval=int(checkpoint_interval),
            checkpoint_byte_bound=checkpoint_byte_bound, write_budget_bytes=int(write_budget_bytes),
            initial_global_step=int(resume_cursor["global_step"]),
        )
    torch.cuda.reset_peak_memory_stats()
    checkpoint: dict[str, object] | None = None
    parameter_receipt: dict[str, object] | None = None
    latest_parent_manifest = Path(specialist_lineage["parent_manifest"]) if specialist_lineage is not None else None

    def checkpoint_callback(global_step: int, state: dict[str, Any]) -> None:
        nonlocal checkpoint, parameter_receipt, latest_parent_manifest
        data_cursor = dict(state["data_cursor"])
        data_cursor["input_identity_receipt_sha256"] = _json_sha256(input_receipt)
        current_lineage: dict[str, object] | None = None
        if specialist_lineage is not None:
            if latest_parent_manifest is None:
                raise RuntimeError("specialist checkpoint publication lost its verified parent manifest")
            current_lineage = {**specialist_lineage, "parent_manifest": str(latest_parent_manifest)}
            data_cursor["specialist_verification"] = specialist_verification
            checkpoint_target = checkpoint_parent / f"checkpoint-continue-seed-{seed}-from-step-{global_step}"
        else:
            checkpoint_target = checkpoint_root

        verified_holder: dict[str, object] = {}

        def verify_staging(staging_root: Path, manifest_receipt: dict[str, object]) -> None:
            verified = _execute_realization_counter(
                root=root, config_path=config_path,
                checkpoint_manifest_path=staging_root / "checkpoint-manifest.json",
                active_expert=str(model.active_expert), expected_counts=counts,
                parent_manifest=(Path(current_lineage["parent_manifest"]) if current_lineage is not None else None),
                root_manifest=(Path(current_lineage["root_manifest"]) if current_lineage is not None else None),
            )
            _atomic_json(staging_root / _COUNTER_SUCCESS_RECEIPT, verified)
            require_counter_success_receipt(staging_root)
            verified_holder["receipt"] = verified

        def publish_and_verify() -> tuple[dict[str, object], dict[str, object]]:
            published = write_checkpoint_artifacts(
                model, optimizer, checkpoint_target, launch_seed=seed,
                rng_state=_rng_state(torch.device("cuda")), data_cursor=data_cursor,
                model_config_sha256=_sha256(config_path), contract_sha256=_sha256(integration_contract_path),
                expert_genesis_sha256=genesis_hashes, optimizer_contract=optimizer_contract,
                specialist_lineage=current_lineage, max_serialized_bytes=checkpoint_byte_bound,
                pre_publish_verifier=verify_staging,
            )
            return published, verified_holder["receipt"]

        checkpoint, parameter_receipt = _retain_after_success(
            checkpoint_parent,
            max_serialized_bytes=checkpoint_retention_budget_bytes(config_path),
            receipt_aware=True,
            operation=publish_and_verify,
        )
        if current_lineage is not None:
            latest_parent_manifest = checkpoint_target / "checkpoint-manifest.json"

    segment = run_pretraining_segment(
        model=model, optimizer=optimizer, records=records, config=config, device=torch.device("cuda"),
        checkpoint_every=(int(checkpoint_interval) if records_override is not None else len(records)),
        checkpoint_callback=checkpoint_callback, initial_global_step=int(resume_cursor["global_step"]),
        initial_tokens_seen=int(resume_cursor["tokens_seen"]), initial_data_cursor=int(resume_cursor["record_index"]),
        data_shard_id=data_shard_id, require_complete_coverage=(records_override is None),
    )
    if checkpoint is None or parameter_receipt is None:
        raise RuntimeError("training segment completed without a durable verified checkpoint")
    counts = measure_parameter_counts(model)
    if counts["unique_parameters"] != 3_839_161_856 or counts["active_parameters"] != 1_725_232_640:
        raise RuntimeError("instantiated sparse counts differ from the authorized architecture")
    return {
        "losses": segment["losses"], "counts": counts, "memory_preflight": memory_preflight,
        "launch_seed": seed, "rng_state_before_init_sha256": rng_state_before_init,
        "expert_genesis_sha256": genesis_hashes, "peak_memory_bytes": int(torch.cuda.max_memory_allocated()),
        "input_identity_receipt": input_receipt, "post_step_checkpoint": checkpoint,
        "parameter_receipt": parameter_receipt, "publication_plan": specialist_plan,
    }

def specialist_lineage_request(
    *, capability: str, verification: dict[str, object], resume_checkpoint: Path | None,
    parent_manifest: Path, root_manifest: Path,
) -> dict[str, object]:
    """Bind a specialist launch to externally supplied parent/root manifests before allocation."""

    expected_expert = {"image": "vision", "audio": "audio", "reasoning": "reasoning", "tool": "tool"}.get(capability)
    if expected_expert is None or verification.get("capability") != capability or verification.get("result") != "VERIFIED":
        raise ValueError("specialist lineage requires a verified capability-matched data receipt")
    if resume_checkpoint is None:
        raise ValueError("specialist v4 launch requires the parent checkpoint for resume")
    resume_manifest = resume_checkpoint.resolve() / "checkpoint-manifest.json"
    if parent_manifest.resolve() != resume_manifest:
        raise ValueError("specialist parent manifest must be the exact resumed checkpoint manifest")
    preflight = preflight_specialist_lineage_sources(
        parent_manifest=parent_manifest.resolve(), root_manifest=root_manifest.resolve(),
    )
    parent_history = preflight["parent_history"]
    return {
        "parent_manifest": parent_manifest.resolve(),
        "root_manifest": root_manifest.resolve(),
        "trained_expert_ids": [*parent_history, *([] if expected_expert in parent_history else [expected_expert])],
        "data_verification_receipt": verification,
    }


def run_specialist(
    *, seed: int, artifact_root: Path, data_manifest: Path, tokenizer_path: Path,
    capability: str, resume_checkpoint: Path | None = None, resume_counter_receipt: Path | None = None, parent_manifest: Path, root_manifest: Path,
    checkpoint_interval: int, write_budget_bytes: int,
    c_relocated_under_disk_budget_runner: bool = False,
    relocation_custody_root: Path | None = None,
) -> dict[str, object]:
    """Run one verifier-bound specialist family through the canonical v4 lineage path."""

    root = Path(__file__).resolve().parents[2]
    records, verification = load_verified_specialist_records(
        root=root, data_manifest=data_manifest, tokenizer_path=tokenizer_path, capability=capability,
    )
    lineage = specialist_lineage_request(
        capability=capability, verification=verification, resume_checkpoint=resume_checkpoint,
        parent_manifest=parent_manifest, root_manifest=root_manifest,
    )
    return run(
        seed=seed, artifact_root=artifact_root, resume_checkpoint=resume_checkpoint, resume_counter_receipt=resume_counter_receipt,
        records_override=records, specialist_verification=verification, specialist_lineage=lineage,
        checkpoint_interval=checkpoint_interval, write_budget_bytes=write_budget_bytes,
        c_relocated_under_disk_budget_runner=c_relocated_under_disk_budget_runner,
        relocation_custody_root=relocation_custody_root,
    )
def run_semantic(
    *, seed: int, artifact_root: Path, receipt_path: Path, shards_root: Path, tokenizer_path: Path,
    steps: int, sequence_length: int, checkpoint_interval: int, write_budget_bytes: int, resume_checkpoint: Path | None = None, resume_counter_receipt: Path | None = None,
) -> dict[str, object]:
    """Train receipt-bound semantic text through the shared nonlinear language path."""

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for the production semantic runner")
    if not isinstance(seed, int) or seed < 0 or not isinstance(steps, int) or steps < 1 or not isinstance(sequence_length, int) or sequence_length < 1 or not isinstance(checkpoint_interval, int) or checkpoint_interval < 1 or not isinstance(write_budget_bytes, int) or write_budget_bytes < 1:
        raise ValueError("semantic launch requires nonnegative seed and positive steps and sequence length")
    artifact_root = production_artifact_root(artifact_root)
    root = Path(__file__).resolve().parents[2]
    config_path = root / "configs" / "ember-restart-3b.json"
    integration_contract_path = root / "docs" / "ember-restart" / "integration-contract-v1.md"
    if not integration_contract_path.is_file():
        raise RuntimeError("the merged Ember integration contract is required for production launch")
    stream = ManifestBoundTokenStream.from_receipt(
        receipt_path=receipt_path, shards_root=shards_root, tokenizer_path=tokenizer_path
    )
    config = RestartDecoderConfig.from_contract(config_path)
    if stream.vocab_size != config.vocab_size:
        raise ValueError("semantic receipt tokenizer vocabulary does not match the production model config")
    total_parameters = config.structural_parameter_count()
    shared_active_parameters = 1_020_589_568
    device_free_bytes, _device_total_bytes = torch.cuda.mem_get_info()
    memory_preflight = production_memory_preflight(
        total_parameters=total_parameters, active_parameters=shared_active_parameters, device_free_bytes=int(device_free_bytes)
    )
    if memory_preflight["parameter_dtype"] != load_memory_contract(config_path)["parameter_dtype"]:
        raise RuntimeError("memory preflight and production numerics disagree")
    checkpoint_parent = artifact_root / "checkpoints"
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    rng_state_before_init = _rng_state_hash(torch.device("cuda"))
    previous_dtype = torch.get_default_dtype()
    torch.set_default_dtype(torch.bfloat16)
    try:
        model = UnifiedDecoder(config, device="cuda", allow_production_allocation=True, genesis_seed=seed)
    finally:
        torch.set_default_dtype(previous_dtype)
    model._activate_expert("shared")
    genesis_hashes = model.expert_bank_genesis_hashes()
    counts = measure_parameter_counts(model)
    if counts["unique_parameters"] != 3_839_161_856 or counts["active_parameters"] != shared_active_parameters:
        raise RuntimeError("instantiated shared semantic counts differ from the authorized architecture")
    optimizer_contract = load_optimizer_contract(config_path)
    optimizer = build_production_optimizer(model, optimizer_contract=optimizer_contract)
    resume_cursor: dict[str, object] | None = None
    initial_global_step = 0
    initial_tokens_seen = 0
    if resume_checkpoint is not None:
        resume_checkpoint = production_resume_checkpoint(
            resume_checkpoint,
            counter_success_receipt=resume_counter_receipt,
        )
        manifest_path = resume_checkpoint / "checkpoint-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        genesis_hashes = resume_expert_genesis(manifest, requested_seed=seed)
        loaded = load_checkpoint_artifacts(
            model, optimizer, resume_checkpoint, {**manifest, "checkpoint_manifest_sha256": _sha256(manifest_path)}
        )
        resume_cursor = dict(loaded["data_cursor"])
        initial_global_step = int(resume_cursor["global_step"])
        initial_tokens_seen = int(resume_cursor["tokens_seen"])
    checkpoint_byte_bound = checkpoint_serialization_byte_bound(config_path, active_parameters=shared_active_parameters)
    publication_plan = semantic_publication_plan(steps=steps, checkpoint_interval=checkpoint_interval, checkpoint_byte_bound=checkpoint_byte_bound, write_budget_bytes=write_budget_bytes, initial_global_step=initial_global_step)
    torch.cuda.reset_peak_memory_stats()
    checkpoint: dict[str, object] | None = None
    parameter_receipt: dict[str, object] | None = None

    def checkpoint_callback(global_step: int, state: dict[str, Any]) -> None:
        nonlocal checkpoint, parameter_receipt
        checkpoint_root = checkpoint_parent / f"checkpoint-semantic-seed-{seed}-step-{global_step}"
        verified_holder: dict[str, object] = {}

        def verify_staging(staging_root: Path, manifest_receipt: dict[str, object]) -> None:
            verified = _execute_realization_counter(
                root=root, config_path=config_path,
                checkpoint_manifest_path=staging_root / "checkpoint-manifest.json",
                active_expert="shared", expected_counts=counts,
            )
            _atomic_json(staging_root / _COUNTER_SUCCESS_RECEIPT, verified)
            require_counter_success_receipt(staging_root)
            verified_holder["receipt"] = verified

        def publish_and_verify() -> tuple[dict[str, object], dict[str, object]]:
            published = write_checkpoint_artifacts(
                model, optimizer, checkpoint_root, launch_seed=seed,
                rng_state=_rng_state(torch.device("cuda")), data_cursor=dict(state["data_cursor"]),
                model_config_sha256=_sha256(config_path), contract_sha256=_sha256(integration_contract_path),
                expert_genesis_sha256=genesis_hashes, optimizer_contract=optimizer_contract,
                max_serialized_bytes=checkpoint_byte_bound, pre_publish_verifier=verify_staging,
            )
            return published, verified_holder["receipt"]

        checkpoint, parameter_receipt = _retain_after_success(
            checkpoint_parent,
            max_serialized_bytes=checkpoint_retention_budget_bytes(config_path),
            receipt_aware=True,
            operation=publish_and_verify,
        )

    segment = run_manifest_bound_semantic_segment(
        model=model,
        optimizer=optimizer,
        stream=stream,
        config=config,
        device=torch.device("cuda"),
        sequence_length=sequence_length,
        steps=steps,
        checkpoint_every=checkpoint_interval,
        checkpoint_callback=checkpoint_callback,
        initial_data_cursor=resume_cursor,
        initial_global_step=initial_global_step,
        initial_tokens_seen=initial_tokens_seen,
    )
    if checkpoint is None or parameter_receipt is None:
        raise RuntimeError("semantic runner did not publish its required counter-verified checkpoint")
    counts = measure_parameter_counts(model)
    return {
        "segment": segment,
        "counts": counts,
        "memory_preflight": memory_preflight,
        "launch_seed": seed,
        "rng_state_before_init_sha256": rng_state_before_init,
        "expert_genesis_sha256": genesis_hashes,
        "peak_memory_bytes": int(torch.cuda.max_memory_allocated()),
        "post_step_checkpoint": checkpoint,
        "parameter_receipt": parameter_receipt,
        "publication_plan": publication_plan,
        "stream_receipt_sha256": stream.receipt_sha256,
        "tokenizer_sha256": stream.tokenizer_sha256,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    vertical = subparsers.add_parser("vertical")
    vertical.add_argument("--seed", type=int, required=True)
    vertical.add_argument("--artifact-root", type=Path, required=True)
    vertical.add_argument("--resume-checkpoint", type=Path)
    vertical.add_argument("--resume-counter-receipt", type=Path)
    specialist = subparsers.add_parser("specialist")
    specialist.add_argument("--seed", type=int, required=True)
    specialist.add_argument("--artifact-root", type=Path, required=True)
    specialist.add_argument("--data-manifest", type=Path, required=True)
    specialist.add_argument("--tokenizer", type=Path, required=True)
    specialist.add_argument("--capability", choices=("image", "audio", "reasoning", "tool"), required=True)
    specialist.add_argument("--resume-checkpoint", type=Path, required=True)
    specialist.add_argument("--resume-counter-receipt", type=Path, required=True)
    specialist.add_argument("--parent-manifest", type=Path, required=True)
    specialist.add_argument("--root-manifest", type=Path, required=True)
    specialist.add_argument("--checkpoint-interval", type=int, required=True)
    specialist.add_argument("--write-budget-gib", type=int, required=True)
    specialist.add_argument("--c-relocated-under-disk-budget-runner", action="store_true")
    specialist.add_argument("--relocation-custody-root", type=Path)
    semantic = subparsers.add_parser("semantic")
    semantic.add_argument("--seed", type=int, required=True)
    semantic.add_argument("--artifact-root", type=Path, required=True)
    semantic.add_argument("--receipt", type=Path, required=True)
    semantic.add_argument("--shards-root", type=Path, required=True)
    semantic.add_argument("--tokenizer", type=Path, required=True)
    semantic.add_argument("--steps", type=int, required=True)
    semantic.add_argument("--sequence-length", type=int, required=True)
    semantic.add_argument("--checkpoint-interval", type=int, required=True)
    semantic.add_argument("--write-budget-gib", type=int, required=True)
    semantic.add_argument("--resume-checkpoint", type=Path)
    semantic.add_argument("--resume-counter-receipt", type=Path)
    args = parser.parse_args()
    if args.command == "specialist":
        result = run_specialist(seed=args.seed, artifact_root=args.artifact_root, data_manifest=args.data_manifest, tokenizer_path=args.tokenizer, capability=args.capability, resume_checkpoint=args.resume_checkpoint, resume_counter_receipt=args.resume_counter_receipt, parent_manifest=args.parent_manifest, root_manifest=args.root_manifest, checkpoint_interval=args.checkpoint_interval, write_budget_bytes=args.write_budget_gib * 1024**3, c_relocated_under_disk_budget_runner=args.c_relocated_under_disk_budget_runner, relocation_custody_root=args.relocation_custody_root)
    elif args.command == "semantic":
        result = run_semantic(
            seed=args.seed,
            artifact_root=args.artifact_root,
            receipt_path=args.receipt,
            shards_root=args.shards_root,
            tokenizer_path=args.tokenizer,
            steps=args.steps,
            sequence_length=args.sequence_length,
            checkpoint_interval=args.checkpoint_interval,
            write_budget_bytes=args.write_budget_gib * 1024**3,
            resume_checkpoint=args.resume_checkpoint,
            resume_counter_receipt=args.resume_counter_receipt,
        )
    else:
        result = run(seed=args.seed, artifact_root=args.artifact_root, resume_checkpoint=args.resume_checkpoint, resume_counter_receipt=args.resume_counter_receipt)
    print(json.dumps(result, sort_keys=True))
if __name__ == "__main__":
    main()
