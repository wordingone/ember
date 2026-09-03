# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Bounded CUDA one-batch sparse slice; invoke only through the disk budget runner."""

from __future__ import annotations

import contextlib
import ctypes
import gc
import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping

import tokenizers
import torch

from checkpoint_artifacts import CheckpointDeferredLowCommit, _atomic_publish_no_replace, _default_optimizer_contract, _empty_failure_comparison_operands, _normalize_failure_comparison_operands, _optimizer_realization, _select_detached_state, _write_atomic, available_host_commit_bytes, load_checkpoint_artifacts, load_checkpoint_model_only_transition, optimizer_covers_every_expert_route, preflight_specialist_lineage_sources, published_checkpoint_receipt, write_checkpoint_artifacts
from parameter_counter import derive_expert_genesis_sha256, validate_realization_receipt
from model import RestartDecoderConfig, UnifiedDecoder
from pretrain import CensusBoundStage2Executor, run_manifest_bound_semantic_segment, run_pretraining_segment
from training_acceleration import (
    Stage1Policy,
    TrainingSignatureCensus,
    compare_stage2_ab_receipts,
    load_stage2_activation_authority,
    load_training_signature_census,
    stage1_policy,
    write_stage2_arm_receipt,
    write_stage2_eager_workspace_diagnostic_receipt,
    write_stage2_graph_only_diagnostic_receipt,
)
from durable_io import atomic_create_durable, atomic_replace_durable
from parameter_counter import measure_parameter_counts
from semantic_stream import ManifestBoundTokenStream
from semantic_contract import semantic_model_contract_sha256
from optimizer_transition import validate_optimizer_transition_registry
from step2_realization_registry import validate_step2_realization_registry_bundle
from train import run_launch, run_text_lab_preflight
from text_lab_corpus import validate_admitted_authority_subset
from a1_execution import run_dense_a1
from a1_dense import DenseA1Config
from a1_dense import DenseA1Decoder
from a1_tier2_contract import admit_tier2_resources, derive_tier2_resource_inventory, load_tier2_contract
from a1_tier2_execution import run_dense_a1_tier2

# R1-E4 measurement receipt (issue #1464): the two constants the MFU arithmetic
# depends on, stated here so the receipt can carry them verbatim. Active count
# matches the post-training assertion below (measure_parameter_counts); the
# assumed peak is RTX 4090 BF16 dense without structured sparsity -- with FP32
# accumulate the achievable peak is ~82.6e12, which would double the reported
# utilization, so the receipt names both.
_E4_ACTIVE_PARAMETERS = 1_725_232_640
_E4_ASSUMED_PEAK_FLOPS = 165.2e12

_STAGE2_AB_SOURCE_COMMIT = "e2283dfd04aa7e61436764d6821d3afe6c64f13b"
_STAGE2_CENSUS_SOURCE_COMMIT = "728421bcca5092a89df483f7df804c7177c337a7"
_STAGE2_CENSUS_RELATIVE_PATH = Path(
    "docs/domains/governance/spec/llmq/ember-training-signature-census-v1.json"
)
_STAGE2_CENSUS_RAW_SHA256 = "86e37ad5868da1ef77419d643c3ff31ee0a38b7e9f603b9c0807376958ef5d0c"
_STAGE2_MATCHED_LOSS_RELATIVE_TOLERANCE = 0.01
_STAGE2_PREPARATION_REGIONS_PER_SIGNATURE = 4
_STAGE2_PRODUCTION_ACCELERATED_ARM_SELF_SHA256 = (
    "f3baa9473802c0f9088fc30e883692b4c460a1bf67ba5221fda986a0425a7699"
)
_STAGE2_DIAGNOSTIC_CLAIM_BOUNDARY = "DIAGNOSTIC_ONLY_NOT_CLOSE_EVIDENCE"

_GENESIS_INVENTORY_SCHEMA = "ember-genesis-inventory-v1"
_GENESIS_INVENTORY_KEYS = {
    "schema_version", "launch_seed", "active_expert", "model_config",
    "parameter_counter", "shards",
}
_GENESIS_SHARD_NAMES = {
    "shared-model.pt", "optimizer-state.pt", "replay-state.pt",
    "expert-vision.pt", "expert-audio.pt", "expert-reasoning.pt", "expert-tool.pt",
}
_GENESIS_CLAIM_BOUNDARY = {
    "schema_version": "ember-genesis-claim-boundary-v1",
    "global_step": 0,
    "tokens_seen": 0,
    "optimizer_steps": 0,
    "training_executed": False,
    "observed_training": False,
    "positive_modality_exposure": False,
    "evaluation_eligible": False,
    "trained_authority": False,
    "sufficiency": False,
    "capability": False,
    "benchmark": False,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _genesis_relative_file(root: Path, value: object, *, label: str) -> tuple[Path, str]:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"{label} must be a closed relative POSIX path")
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError(f"{label} must be a closed relative POSIX path")
    path = root.joinpath(*relative.parts)
    try:
        info = path.lstat()
    except OSError as error:
        raise ValueError(f"{label} is absent") from error
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & reparse):
        raise ValueError(f"{label} must not be a symlink or reparse point")
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"{label} must be a regular file")
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as error:
        raise ValueError(f"{label} escapes the inventory root") from error
    return path, relative.as_posix()


def _genesis_bound_file(root: Path, record: object, *, label: str) -> tuple[Path, str]:
    if not isinstance(record, Mapping) or set(record) != {"path", "sha256"}:
        raise ValueError(f"{label} has a closed schema violation")
    path, relative = _genesis_relative_file(root, record.get("path"), label=f"{label}.path")
    digest = record.get("sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError(f"{label}.sha256 is invalid")
    if _sha256(path) != digest:
        raise ValueError(f"{label}.sha256 does not match bytes")
    return path, relative


def _copy_genesis_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as reader, target.open("xb") as writer:
        shutil.copyfileobj(reader, writer, length=1024 * 1024)
        writer.flush()
        os.fsync(writer.fileno())


def _genesis_json(path: Path, payload: Mapping[str, object]) -> None:
    atomic_create_durable(
        path,
        (json.dumps(dict(payload), sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"),
    )


def initialize_genesis_inventory(
    *, config_path: Path, seed: int, output_root: Path,
) -> dict[str, object]:
    """Materialize the closed zero-step inventory consumed by ``genesis``.

    The production config fixes CUDA-resident AdamW8bit.  This function only
    constructs initialization state: it has no data input and never executes a
    forward pass, backward pass, or optimizer step.
    """

    if type(seed) is not int or seed < 0:
        raise ValueError("genesis initialization seed must be nonnegative")
    output_root = Path(output_root).resolve()
    output_root.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(str(output_root)):
        raise FileExistsError(output_root)
    config_path = Path(config_path).resolve(strict=True)
    config = RestartDecoderConfig.from_contract(config_path)
    device = "cuda" if config.production else "cpu"
    if config.production and not torch.cuda.is_available():
        raise RuntimeError("production genesis initialization requires CUDA")

    staging = output_root.parent / f".{output_root.name}.staging-{os.getpid()}-{uuid.uuid4().hex}"
    staging.mkdir()
    model: UnifiedDecoder | None = None
    optimizer: torch.optim.Optimizer | None = None
    try:
        model = UnifiedDecoder(
            config,
            device=device,
            allow_production_allocation=config.production,
            genesis_seed=seed,
        )
        model._activate_expert("shared")
        if config.production:
            optimizer_contract = load_optimizer_contract(config_path)
            optimizer = build_production_optimizer(
                model, optimizer_contract=optimizer_contract
            )
        else:
            optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
            optimizer_contract = _default_optimizer_contract(optimizer)
        optimizer_realization = _optimizer_realization(optimizer, optimizer_contract)

        config_target = staging / "configs" / "ember-restart-3b.json"
        counter_source = Path(__file__).with_name("parameter_counter.py").resolve(strict=True)
        counter_target = staging / "counter" / "parameter_counter.py"
        _copy_genesis_file(config_path, config_target)
        _copy_genesis_file(counter_source, counter_target)
        checkpoint_root = staging / "checkpoint"
        checkpoint_root.mkdir()
        model_state = model.state_dict()
        shared_state = _select_detached_state(
            model_state, lambda name: ".experts." not in name
        )
        shard_paths = [
            _write_atomic(
                checkpoint_root,
                "shared-model.pt",
                lambda handle: torch.save({"model": shared_state}, handle),
            ),
            _write_atomic(
                checkpoint_root,
                "optimizer-state.pt",
                lambda handle: torch.save(
                    {
                        "optimizer": optimizer.state_dict(),
                        "optimizer_contract": optimizer_contract,
                        "optimizer_realization": optimizer_realization,
                    },
                    handle,
                ),
            ),
        ]
        data_cursor = {
            "shard": "GENESIS",
            "record_index": 0,
            "global_step": 0,
            "tokens_seen": 0,
        }
        cuda_rng_state = (
            torch.cuda.get_rng_state()
            if config.production
            else torch.empty(0, dtype=torch.uint8)
        )
        shard_paths.append(
            _write_atomic(
                checkpoint_root,
                "replay-state.pt",
                lambda handle: torch.save(
                    {
                        "rng_state": {
                            "cpu": torch.get_rng_state(),
                            "cuda": cuda_rng_state,
                        },
                        "data_cursor": data_cursor,
                    },
                    handle,
                ),
            )
        )
        for name in ("vision", "audio", "reasoning", "tool"):
            expert_state = _select_detached_state(
                model_state,
                lambda key, selected=name: f".experts.{selected}." in key,
            )
            shard_paths.append(
                _write_atomic(
                    checkpoint_root,
                    f"expert-{name}.pt",
                    lambda handle, selected=name, state=expert_state: torch.save(
                        {"expert": selected, "model": state}, handle
                    ),
                )
            )
        records = [
            {
                "path": f"checkpoint/{path.name}",
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in sorted(shard_paths, key=lambda item: item.name)
        ]
        inventory_path = staging / "inventory.json"
        _genesis_json(
            inventory_path,
            {
                "schema_version": _GENESIS_INVENTORY_SCHEMA,
                "launch_seed": seed,
                "active_expert": "shared",
                "model_config": {
                    "path": "configs/ember-restart-3b.json",
                    "sha256": _sha256(config_target),
                },
                "parameter_counter": {
                    "path": "counter/parameter_counter.py",
                    "sha256": _sha256(counter_target),
                },
                "shards": records,
            },
        )
        _atomic_publish_no_replace(staging, output_root)
        return {
            "result": "GENESIS_INVENTORY_INITIALIZED",
            "inventory_path": str(output_root / "inventory.json"),
            "shard_count": len(records),
            "launch_seed": seed,
            "training_executed": False,
            "optimizer_steps": 0,
        }
    finally:
        optimizer = None
        model = None
        gc.collect()
        if config.production and torch.cuda.is_available():
            torch.cuda.empty_cache()
        if staging.exists():
            shutil.rmtree(staging)


def mint_genesis_candidate(
    *, inventory_path: Path, output_root: Path, source_commit: str, run_id: str,
) -> dict[str, object]:
    """Mint one immutable zero-step candidate from a closed physical inventory.

    This is initialization publication only.  It neither constructs an optimizer
    nor exposes any resume, step, training, evaluation, or sufficiency surface.
    """

    if not isinstance(source_commit, str) or re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        raise ValueError("source_commit must be a lowercase 40-character Git SHA")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be non-empty")
    inventory_path = Path(inventory_path).resolve(strict=True)
    inventory_root = inventory_path.parent
    try:
        inventory = json.loads(inventory_path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("genesis inventory is unreadable") from error
    if not isinstance(inventory, dict) or set(inventory) != _GENESIS_INVENTORY_KEYS:
        raise ValueError("genesis inventory has a closed schema violation")
    if inventory.get("schema_version") != _GENESIS_INVENTORY_SCHEMA:
        raise ValueError("genesis inventory schema is unsupported")
    if type(inventory.get("launch_seed")) is not int or inventory["launch_seed"] < 0:
        raise ValueError("genesis inventory launch_seed must be nonnegative")
    if inventory.get("active_expert") != "shared":
        raise ValueError("genesis inventory must use the shared initialization route")

    config_source, _ = _genesis_bound_file(
        inventory_root, inventory.get("model_config"), label="genesis model_config"
    )
    counter_source, _ = _genesis_bound_file(
        inventory_root, inventory.get("parameter_counter"), label="genesis parameter_counter"
    )
    shard_records = inventory.get("shards")
    if not isinstance(shard_records, list):
        raise ValueError("genesis inventory has a closed shard inventory violation")
    sources: dict[str, tuple[Path, dict[str, object]]] = {}
    for record in shard_records:
        if not isinstance(record, dict) or set(record) != {"path", "sha256", "bytes"}:
            raise ValueError("genesis inventory has a closed shard inventory violation")
        source, relative = _genesis_relative_file(
            inventory_root, record.get("path"), label="genesis shard.path"
        )
        name = PurePosixPath(relative).name
        if PurePosixPath(relative).parent.as_posix() != "checkpoint" or name in sources:
            raise ValueError("genesis inventory has a closed shard inventory violation")
        digest, size = record.get("sha256"), record.get("bytes")
        if (
            not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or type(size) is not int
            or size < 0
            or source.stat().st_size != size
            or _sha256(source) != digest
        ):
            raise ValueError("genesis shard bytes do not match their inventory")
        sources[name] = (source, dict(record))
    if set(sources) != _GENESIS_SHARD_NAMES:
        raise ValueError("genesis inventory has a closed shard inventory violation")
    actual_shards = {
        child.name
        for child in (inventory_root / "checkpoint").iterdir()
        if child.is_file()
    }
    if actual_shards != _GENESIS_SHARD_NAMES:
        raise ValueError("genesis inventory contains a foreign shard")
    expert_genesis = derive_expert_genesis_sha256(
        model_config_path=config_source,
        checkpoint_root=inventory_root / "checkpoint",
    )

    output_root = Path(output_root).resolve()
    output_root.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(str(output_root)):
        raise FileExistsError(output_root)
    staging = output_root.parent / f".{output_root.name}.staging-{os.getpid()}-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        config_target = staging / "configs" / "ember-restart-3b.json"
        counter_target = staging / "counter" / "parameter_counter.py"
        _copy_genesis_file(config_source, config_target)
        _copy_genesis_file(counter_source, counter_target)
        candidate_shards: list[dict[str, object]] = []
        for name in sorted(sources):
            source, record = sources[name]
            target = staging / "checkpoint" / name
            _copy_genesis_file(source, target)
            candidate_shards.append(
                {"path": name, "sha256": record["sha256"], "bytes": record["bytes"]}
            )
        checkpoint = {
            "schema_version": "ember-sparse-checkpoint-v5",
            "contract_version": 5,
            "architecture_revision": "ember-sparse-3b-v2",
            "launch_seed": inventory["launch_seed"],
            "data_cursor": {"shard": "GENESIS", "record_index": 0, "global_step": 0, "tokens_seen": 0},
            "model_config_sha256": _sha256(config_target),
            "contract_sha256": _sha256(Path(__file__).resolve().parents[2] / "src" / "ember" / "governance" / "scripts" / "ember_restart" / "contract.py"),
            "active_expert_ids": ["shared"],
            "expert_genesis_sha256": expert_genesis,
            "expert_checkpoint_sha256": {
                name: str(sources[f"expert-{name}.pt"][1]["sha256"])
                for name in ("vision", "audio", "reasoning", "tool")
            },
            "shared_model_shard_sha256": str(sources["shared-model.pt"][1]["sha256"]),
            "optimizer_state_shard_sha256": str(sources["optimizer-state.pt"][1]["sha256"]),
            "genesis_claim_boundary": dict(_GENESIS_CLAIM_BOUNDARY),
            "shards": candidate_shards,
        }
        checkpoint_path = staging / "checkpoint" / "checkpoint-manifest.json"
        _genesis_json(checkpoint_path, checkpoint)
        counter_command = [
            sys.executable, "-I", str(counter_target),
            "--model-config", str(config_target),
            "--checkpoint-manifest", str(checkpoint_path),
            "--active-expert", "shared",
        ]
        completed = subprocess.run(
            counter_command,
            cwd=staging,
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
            creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0),
        )
        if completed.returncode != 0:
            raise ValueError(f"genesis parameter counter refused inventory: {completed.stderr.strip()}")
        try:
            parameter_receipt = validate_realization_receipt(json.loads(completed.stdout))
        except (json.JSONDecodeError, ValueError) as error:
            raise ValueError("genesis parameter counter returned an invalid receipt") from error
        if (
            parameter_receipt["subject_checkpoint_sha256"] != _sha256(checkpoint_path)
            or parameter_receipt["model_config_sha256"] != _sha256(config_target)
            or parameter_receipt["counter_sha256"] != _sha256(counter_target)
            or parameter_receipt["active_expert_ids"] != ["shared"]
            or parameter_receipt["expert_genesis_sha256"] != expert_genesis
            or parameter_receipt["expert_parameter_sha256"] != expert_genesis
        ):
            raise ValueError("genesis parameter receipt does not bind the initialization inventory")
        receipt_path = staging / "receipts" / "parameter-count.json"
        _genesis_json(receipt_path, parameter_receipt)
        registry_path = staging / "trusted-verifiers.json"
        _genesis_json(
            registry_path,
            {
                "schema_version": "ember-trusted-verifiers-v1",
                "verifiers": [{
                    "path": "counter/parameter_counter.py",
                    "sha256": _sha256(counter_target),
                    "evidence_classes": ["parameter_realization"],
                    "criterion_ids": [],
                }],
            },
        )
        architecture = {
            "family": "ember-unified-decoder",
            "revision": "ember-sparse-3b-v2",
            "model_config": {"path": "configs/ember-restart-3b.json", "sha256": _sha256(config_target)},
            **{field: parameter_receipt[field] for field in (
                "allocated_parameters", "unique_parameters", "trainable_parameters",
                "served_parameters", "active_parameters", "episode_trainable_parameters",
            )},
            "parameter_counter": {"path": "counter/parameter_counter.py", "sha256": _sha256(counter_target)},
            "parameter_receipt": {"path": "receipts/parameter-count.json", "sha256": _sha256(receipt_path)},
            "shared_core": True,
            "sparse_differentiated_capacity": True,
            "task_level_expert_routing": True,
            "asymmetric_expert_initialization": True,
            "expert_banks": [
                {
                    "id": name,
                    "domain": name,
                    "path": f"checkpoint/expert-{name}.pt",
                    "artifact_sha256": str(sources[f"expert-{name}.pt"][1]["sha256"]),
                    "genesis_sha256": expert_genesis[name],
                }
                for name in ("vision", "audio", "reasoning", "tool")
            ],
            "active_expert_ids": ["shared"],
            "raw_image_patches": True,
            "raw_audio_frames": True,
            "soft_token_splicing": True,
            "multimodal_span_attention": True,
            "rope_2d": True,
            "separate_pretrained_encoders": False,
        }
        outer_manifest = {
            "schema_version": "ember-owned-genesis-v1",
            "stage": "GENESIS_CANDIDATE",
            "run_id": run_id,
            "source_commit": source_commit,
            "lineage": {
                "genesis": "OWNED_RANDOM_INIT",
                "parent_checkpoint_sha256": None,
                "borrowed_weights": False,
                "borrowed_teachers": False,
                "borrowed_judges": False,
                "borrowed_filters": False,
                "borrowed_generated_labels": False,
            },
            "architecture": architecture,
            "checkpoint": {"manifest_path": "checkpoint/checkpoint-manifest.json", "sha256": _sha256(checkpoint_path)},
            "genesis_claim_boundary": dict(_GENESIS_CLAIM_BOUNDARY),
        }
        manifest_path = staging / "run.json"
        _genesis_json(manifest_path, outer_manifest)
        _atomic_publish_no_replace(staging, output_root)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return {
        "result": "GENESIS_CANDIDATE_MINTED",
        "manifest_path": str(output_root / "run.json"),
        "manifest_sha256": _sha256(output_root / "run.json"),
        "checkpoint_manifest_sha256": _sha256(output_root / "checkpoint" / "checkpoint-manifest.json"),
        "trusted_verifier_registry": str(output_root / "trusted-verifiers.json"),
    }


def governed_resource_preflight() -> dict[str, object]:
    """Run the repository-owned GPU governor before any CUDA allocation."""

    governor_path = (
        Path(__file__).resolve().parents[2]
        / "src" / "ember" / "governance" / "scripts" / "governor.py"
    )
    if not governor_path.is_file():
        raise RuntimeError("repository resource governor is unavailable")
    spec = importlib.util.spec_from_file_location("ember_governor_bound", governor_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("repository resource governor cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    preflight = getattr(module, "preflight", None)
    if not callable(preflight):
        raise RuntimeError("repository resource governor has no preflight")
    receipt = preflight()
    if not isinstance(receipt, Mapping):
        raise RuntimeError("repository resource governor returned an invalid receipt")
    return {**dict(receipt), "governor_source_sha256": _sha256(governor_path)}

_CANONICAL_RUNNER_CACHE_ENV = ("TEMP", "TMP", "TORCH_HOME", "TRITON_CACHE_DIR", "CUDA_CACHE_PATH", "HF_HOME", "XDG_CACHE_HOME")
# Owner-sharded v5 keeps each temporary optimizer shard and the aggregate
# transient write set within the 4 GiB scratch contract. The checkpoint writer
# derives the per-owner projection and enforces this ceiling before and during
# every shard write; retained checkpoint bytes remain governed separately.
_MAX_TRANSIENT_CHECKPOINT_SCRATCH_BYTES = 4 * 1024**3


def _canonical_json_bytes(payload: Mapping[str, object]) -> bytes:
    return json.dumps(dict(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")


def _canonical_disk_budget_runner_authority() -> tuple[dict[str, object], Path]:
    """Bind this process to the canonical runner's nonce-protected child assertion."""
    assertion_raw = os.environ.get("EMBER_DISK_BUDGET_ENV_ASSERTION")
    nonce = os.environ.get("EMBER_DISK_BUDGET_ENV_NONCE")
    if not isinstance(assertion_raw, str) or not assertion_raw or not isinstance(nonce, str) or not re.fullmatch(r"[0-9a-f]{32}", nonce):
        raise RuntimeError("vertical production launch requires the canonical disk budget runner assertion")
    live_bindings = {name: os.environ.get(name) for name in _CANONICAL_RUNNER_CACHE_ENV}
    if any(not isinstance(value, str) or not value for value in live_bindings.values()):
        raise RuntimeError("canonical disk budget runner cache bindings are incomplete")
    custody = Path(str(live_bindings["TEMP"])).resolve().parent
    assertion_path = Path(assertion_raw).resolve(strict=True)
    if assertion_path.name != "child-env-startup.json" or assertion_path.parent != custody:
        raise RuntimeError("canonical disk budget runner assertion is not the custody startup assertion")
    if not assertion_path.is_relative_to(custody):
        raise RuntimeError("canonical disk budget runner assertion escapes the custody root")
    try:
        assertion_bytes = assertion_path.read_bytes()
        assertion = json.loads(assertion_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("canonical disk budget runner assertion is unreadable") from error
    if not isinstance(assertion, dict) or set(assertion) != {"schema_version", "nonce", "bindings"}:
        raise RuntimeError("canonical disk budget runner assertion has an invalid schema")
    bindings = assertion.get("bindings")
    if assertion.get("schema_version") != 1 or assertion.get("nonce") != nonce or not isinstance(bindings, dict):
        raise RuntimeError("canonical disk budget runner assertion does not match this launch")
    if set(bindings) != set(_CANONICAL_RUNNER_CACHE_ENV) or bindings != live_bindings:
        raise RuntimeError("canonical disk budget runner cache bindings do not match this launch")
    try:
        resolved_bindings = {name: Path(value).resolve(strict=True) for name, value in bindings.items()}
    except OSError as error:
        raise RuntimeError("canonical disk budget runner cache binding is unavailable") from error
    if any(not value.is_relative_to(custody) for value in resolved_bindings.values()):
        raise RuntimeError("canonical disk budget runner cache binding escapes custody")
    return ({
        "schema_version": "ember-canonical-disk-budget-startup-v1",
        "assertion_sha256": hashlib.sha256(assertion_bytes).hexdigest(),
        "cache_bindings_sha256": hashlib.sha256(_canonical_json_bytes(bindings)).hexdigest(),
    }, custody)


def canonical_disk_budget_runner_authority() -> dict[str, object]:
    """Return only the path-free canonical runner authority projection."""

    authority, _custody = _canonical_disk_budget_runner_authority()
    return authority


def governed_vertical_checkpoint_byte_bound(config_path: Path) -> int:
    """Budget the full-coverage governed-vertical checkpoint before allocation.

    The governed-vertical shard routes one record through every specialist, so
    the optimizer legitimately covers every structural parameter and the
    serialized checkpoint carries full-coverage optimizer state (the state the
    storage projection admits at factor 1). Budgeting shared-plus-one-expert
    here under-declares that checkpoint and refuses the by-design publication.
    """

    config = RestartDecoderConfig.from_contract(config_path)
    return checkpoint_serialization_byte_bound(
        config_path,
        active_parameters=config.structural_parameter_count(),
    )


def run_governed_vertical(
    *,
    seed: int,
    artifact_root: Path,
    write_budget_bytes: int,
    max_records: int | None = None,
    resume_checkpoint: Path | None = None,
    resume_counter_receipt: Path | None = None,
    resume_realization_registry: Path | None = None,
    resume_optimizer_transition_registry: Path | None = None,
    resume_optimizer_transition_registry_sha256: str | None = None,
    c_relocated_under_disk_budget_runner: bool = False,
    relocation_custody_root: Path | None = None,
    signature_census_output: Path | None = None,
    signature_census_source_commit: str | None = None,
    stage2_acceleration: bool = False,
    stage2_diagnostic_bf16_down: bool = False,
    stage2_diagnostic_eager_workspace: bool = False,
    stage2_diagnostic_pre_optimizer_sync: bool = False,
    stage2_arm_receipt_output: Path | None = None,
) -> dict[str, object]:
    """Canonical-runner entrypoint; check launch inputs before governor/CUDA admission."""
    if type(seed) is not int or seed < 0 or type(write_budget_bytes) is not int or write_budget_bytes < 1:
        raise ValueError("governed vertical launch requires a nonnegative seed and positive byte budget")
    config_path = Path(__file__).resolve().parents[2] / "configs" / "ember-restart-3b.json"
    checkpoint_bound = governed_vertical_checkpoint_byte_bound(config_path)
    if checkpoint_bound > write_budget_bytes:
        raise ValueError("governed vertical checkpoint publication bound exceeds the declared write budget")
    startup_authority, custody = _canonical_disk_budget_runner_authority()
    resolved_artifact_root = artifact_root.resolve()
    if not resolved_artifact_root.is_relative_to(custody):
        raise ValueError("governed vertical artifact root escapes canonical runner custody")
    census_output, census_source_commit = validate_signature_census_request(
        signature_census_output, signature_census_source_commit,
    )
    if census_output is not None and not census_output.is_relative_to(resolved_artifact_root):
        raise ValueError("training signature census output must stay inside the governed artifact root")
    authority = {
        **startup_authority,
        "config_sha256": _sha256(config_path),
        "runner_source_sha256": _sha256(Path(__file__).resolve()),
        "checkpoint_byte_bound": checkpoint_bound,
        "write_budget_bytes": write_budget_bytes,
    }
    return run(
        seed=seed,
        artifact_root=resolved_artifact_root,
        resume_checkpoint=resume_checkpoint,
        resume_counter_receipt=resume_counter_receipt,
        resume_realization_registry=resume_realization_registry,
        resume_optimizer_transition_registry=resume_optimizer_transition_registry,
        resume_optimizer_transition_registry_sha256=resume_optimizer_transition_registry_sha256,
        write_budget_bytes=write_budget_bytes,
        max_records=max_records,
        canonical_runner_authority=authority,
        c_relocated_under_disk_budget_runner=c_relocated_under_disk_budget_runner,
        relocation_custody_root=relocation_custody_root,
        signature_census_output=census_output,
        signature_census_source_commit=census_source_commit,
        stage2_acceleration=stage2_acceleration,
        stage2_diagnostic_bf16_down=stage2_diagnostic_bf16_down,
        stage2_diagnostic_eager_workspace=stage2_diagnostic_eager_workspace,
        stage2_diagnostic_pre_optimizer_sync=stage2_diagnostic_pre_optimizer_sync,
        stage2_arm_receipt_output=stage2_arm_receipt_output,
    )


def preflight_governed_vertical(
    *, seed: int, artifact_root: Path, write_budget_bytes: int,
    max_records: int | None = None, stage2_acceleration: bool = False,
    stage2_diagnostic_bf16_down: bool = False,
    stage2_diagnostic_eager_workspace: bool = False,
    stage2_diagnostic_pre_optimizer_sync: bool = False,
    stage2_arm_receipt_output: Path | None = None,
) -> dict[str, object]:
    """CPU-only canonical-runner child preflight; it never admits CUDA or a training step."""

    if type(seed) is not int or seed < 0 or type(write_budget_bytes) is not int or write_budget_bytes < 1:
        raise ValueError("governed vertical launch requires a nonnegative seed and positive byte budget")
    if max_records is not None and (type(max_records) is not int or not 1 <= max_records <= 200):
        raise ValueError("governed vertical max records must be in 1..200")
    config_path = Path(__file__).resolve().parents[2] / "configs" / "ember-restart-3b.json"
    checkpoint_bound = governed_vertical_checkpoint_byte_bound(config_path)
    if checkpoint_bound > write_budget_bytes:
        raise ValueError("governed vertical checkpoint publication bound exceeds the declared write budget")
    startup_authority, custody = _canonical_disk_budget_runner_authority()
    resolved_artifact_root = artifact_root.resolve()
    if not resolved_artifact_root.is_relative_to(custody):
        raise ValueError("governed vertical artifact root escapes canonical runner custody")
    receipt_output = validate_stage2_activation_request(
        enabled=stage2_acceleration,
        diagnostic_bf16_down=stage2_diagnostic_bf16_down,
        diagnostic_eager_workspace=stage2_diagnostic_eager_workspace,
        diagnostic_pre_optimizer_sync=stage2_diagnostic_pre_optimizer_sync,
        artifact_root=resolved_artifact_root,
        receipt_output=stage2_arm_receipt_output,
        signature_census_output=None,
        resume_checkpoint=None,
    )
    root = Path(__file__).resolve().parents[2]
    records, _launch_packet, input_receipt = load_authorized_records(root)
    selected_records = records[:max_records] if max_records is not None else records
    config_sha256 = _sha256(config_path)
    stage2_active = (
        stage2_acceleration or stage2_diagnostic_bf16_down
        or stage2_diagnostic_eager_workspace
    )
    return {
        "decision": "PREFLIGHT_ONLY",
        "canonical_disk_budget_runner": {
            **startup_authority,
            "config_sha256": _sha256(config_path),
            "runner_source_sha256": _sha256(Path(__file__).resolve()),
            "checkpoint_byte_bound": checkpoint_bound,
            "write_budget_bytes": write_budget_bytes,
        },
        "max_records": max_records,
        "stage2_matched_arm": {
            "arm": (
                "eager_workspace_bf16" if stage2_diagnostic_eager_workspace
                else "graph_only_bf16_down" if stage2_diagnostic_bf16_down
                else "census_bound_stage2" if stage2_acceleration
                else "bf16_baseline"
            ),
            "source_commit": _STAGE2_AB_SOURCE_COMMIT,
            "model_config_sha256": config_sha256,
            "input_identity_sha256": _json_sha256(input_receipt),
            "record_order_sha256": _json_sha256({"records": selected_records}),
            "checkpoint_lineage_sha256": _stage2_fresh_genesis_lineage_sha256(
                seed=seed, config_sha256=config_sha256,
            ),
            "seed": seed,
            "initial_cursor": {"record_index": 0, "global_step": 0, "tokens_seen": 0},
            "census_raw_sha256": (
                _STAGE2_CENSUS_RAW_SHA256 if stage2_active else None
            ),
            "matched_loss_relative_tolerance_exclusive": _STAGE2_MATCHED_LOSS_RELATIVE_TOLERANCE,
            "preparation_regions_per_signature": _STAGE2_PREPARATION_REGIONS_PER_SIGNATURE,
            "preparation_signature_count": len(selected_records),
            "preparation_region_count": (
                _STAGE2_PREPARATION_REGIONS_PER_SIGNATURE * len(selected_records)
            ),
            "no_capture_in_measured_window": True,
            "receipt_output": str(receipt_output) if receipt_output is not None else None,
        },
    }


def require_disk_budget_runner_contract() -> None:
    """Refuse direct write-heavy CLI dispatch outside the canonical runner child."""
    raise RuntimeError("vertical production launch requires the disk budget runner")


def _json_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _stage2_fresh_genesis_lineage_sha256(*, seed: int, config_sha256: str) -> str:
    """Bind both matched arms to the same deterministic, resume-free genesis."""

    return _json_sha256({
        "schema_version": "ember-stage2-fresh-genesis-lineage-v1",
        "source_commit": _STAGE2_AB_SOURCE_COMMIT,
        "model_config_sha256": config_sha256,
        "seed": seed,
        "resume_checkpoint": None,
    })


_SCENE_SPLITS = ("train", "validation", "test")


def select_verified_scene_split(
    records: list[dict[str, object]], *, capability: str, scene_split: str,
    full_records_artifact_sha256: str,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Create a separate, closed selection receipt without changing verifier evidence."""

    if capability != "image" or scene_split not in _SCENE_SPLITS:
        raise ValueError("scene split selection requires image capability and a declared scene split")
    if not isinstance(full_records_artifact_sha256, str) or len(full_records_artifact_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in full_records_artifact_sha256):
        raise ValueError("scene split selection requires the full verified records artifact hash")
    if not records or any(record.get("active_expert") != "vision" for record in records):
        raise ValueError("scene split selection requires one vision route")
    if any(record.get("scene_split") not in _SCENE_SPLITS for record in records):
        raise ValueError("scene split selection requires every record to declare a scene split")
    selected = [record for record in records if record["scene_split"] == scene_split]
    if not selected:
        raise ValueError("scene split selection selected no records")
    encoded_records = json.dumps(selected, sort_keys=True, separators=(",", ":")).encode("utf-8")
    encoded_tokens = json.dumps([record["token_ids"] for record in selected], separators=(",", ":")).encode("utf-8")
    return selected, {
        "schema_version": "ember-specialist-scene-split-selection-v1",
        "capability": capability,
        "scene_split": scene_split,
        "full_records_artifact_sha256": full_records_artifact_sha256,
        "selected_record_count": len(selected),
        "selected_token_count": sum(len(record["token_ids"]) for record in selected),
        "selected_records_sha256": hashlib.sha256(encoded_records).hexdigest(),
        "selected_tokens_sha256": hashlib.sha256(encoded_tokens).hexdigest(),
    }


def validate_image_scene_split_execution(
    records: list[dict[str, object]], *, verification: Mapping[str, object],
    selection: Mapping[str, object], execution_slice: Mapping[str, object],
    full_records_artifact_bytes: bytes | None = None,
) -> None:
    """Fail before CUDA unless a train-only execution matches its closed selection receipt."""

    fields = {"schema_version", "capability", "scene_split", "full_records_artifact_sha256", "selected_record_count", "selected_token_count", "selected_records_sha256", "selected_tokens_sha256"}
    if set(selection) != fields or selection.get("schema_version") != "ember-specialist-scene-split-selection-v1" or selection.get("capability") != "image" or selection.get("scene_split") != "train":
        raise ValueError("image specialist scene split selection receipt is invalid")
    if selection.get("full_records_artifact_sha256") != verification.get("records_artifact_sha256"):
        raise ValueError("image specialist scene split selection does not bind the verified records artifact")
    if records:
        if not isinstance(full_records_artifact_bytes, bytes):
            raise ValueError("image specialist scene split execution requires the full verified records artifact bytes")
        derived_full_sha256 = hashlib.sha256(full_records_artifact_bytes).hexdigest()
        if derived_full_sha256 != selection.get("full_records_artifact_sha256"):
            raise ValueError("image specialist full records artifact hash mismatch")
        try:
            full_payload = json.loads(full_records_artifact_bytes)
        except json.JSONDecodeError as error:
            raise ValueError("image specialist full records artifact bytes are not valid JSON") from error
        full_records = full_payload.get("records") if isinstance(full_payload, dict) else None
        if not isinstance(full_records, list) or any(not isinstance(record, dict) for record in full_records):
            raise ValueError("image specialist full records artifact is malformed")
        if records != [record for record in full_records if record.get("scene_split") == "train"]:
            raise ValueError("image specialist train records are not the train subset of the verified full records artifact")
    if any(not isinstance(selection.get(name), int) or isinstance(selection.get(name), bool) or selection[name] <= 0 for name in ("selected_record_count", "selected_token_count")):
        raise ValueError("image specialist scene split selection has invalid selected counts")
    for name in ("full_records_artifact_sha256", "selected_records_sha256", "selected_tokens_sha256"):
        value = selection.get(name)
        if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise ValueError("image specialist scene split selection has an invalid hash")
    if execution_slice.get("scene_split_record_count") != selection["selected_record_count"]:
        raise ValueError("image specialist execution slice does not bind the selected train count")
    if records:
        if any(record.get("scene_split") != "train" or record.get("active_expert") != "vision" for record in records):
            raise ValueError("image specialist scene split execution requires only train vision rows")
        encoded_records = json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
        encoded_tokens = json.dumps([record.get("token_ids") for record in records], separators=(",", ":")).encode("utf-8")
        if (selection["selected_record_count"] != len(records)
                or selection["selected_token_count"] != sum(len(record.get("token_ids", [])) for record in records)
                or selection["selected_records_sha256"] != hashlib.sha256(encoded_records).hexdigest()
                or selection["selected_tokens_sha256"] != hashlib.sha256(encoded_tokens).hexdigest()):
            raise ValueError("image specialist complete train selection does not match its receipt")

def bind_specialist_execution_slice(
    records: list[dict[str, object]], *, start_record: int, max_records: int, scene_split_record_count: int | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Bind one exact contiguous execution slice without weakening full-corpus verification."""

    if type(start_record) is not int or start_record < 0 or start_record >= len(records):
        raise ValueError("specialist execution slice start record is outside the verified corpus")
    if type(max_records) is not int or max_records < 1:
        raise ValueError("specialist execution slice max records must be positive")
    if start_record + max_records > len(records):
        raise ValueError("specialist execution slice exceeds the verified corpus")
    selected = records[start_record:start_record + max_records]
    return selected, specialist_execution_slice_receipt(selected, source_start_record=start_record, scene_split_record_count=scene_split_record_count)


def _sha256_of_canonical_json_array(items: Iterable[object], *, sort_keys: bool) -> str:
    """Hash a top-level JSON array in bounded memory, byte-identical to
    ``json.dumps(list(items), sort_keys=..., separators=(",", ":")).encode("utf-8")``.

    With these separators a JSON array is exactly the element encodings joined
    by ``,`` inside ``[`` ``]``, so hashing element-by-element never changes a
    byte while capping the transient buffer at one element's encoding. The
    monolithic dumps of a whole record slice was the single largest host
    allocation of a specialist run, sat outside every commit guard, and died
    with MemoryError at final publication under host contention (#1465).
    """

    digest = hashlib.sha256()
    digest.update(b"[")
    for index, item in enumerate(items):
        if index:
            digest.update(b",")
        digest.update(json.dumps(item, sort_keys=sort_keys, separators=(",", ":")).encode("utf-8"))
    digest.update(b"]")
    return digest.hexdigest()


def specialist_execution_slice_receipt(
    records: list[dict[str, object]], *, source_start_record: int, scene_split_record_count: int | None = None,
) -> dict[str, object]:
    """Content-address records executed since the immediate checkpoint parent.

    Canonical bytes never leave this function -- only their digests do -- so the
    streaming canonicalization above is observationally identical to the former
    monolithic ``json.dumps`` while never materializing the whole slice.
    """

    if type(source_start_record) is not int or source_start_record < 0 or not records:
        raise ValueError("specialist execution slice selected no verified records")
    token_count = 0
    for record in records:
        token_ids = record.get("token_ids")
        if not isinstance(token_ids, list) or not token_ids or any(type(token) is not int or token < 0 for token in token_ids):
            raise ValueError("specialist execution slice requires nonempty nonnegative token_ids")
        token_count += len(token_ids)
    receipt: dict[str, object] = {
        "schema_version": "ember-specialist-execution-slice-v1",
        "start_record": source_start_record,
        "record_count": len(records),
        "token_count": token_count,
        "records_sha256": _sha256_of_canonical_json_array(records, sort_keys=True),
        "tokens_sha256": _sha256_of_canonical_json_array((record["token_ids"] for record in records), sort_keys=False),
    }
    if scene_split_record_count is not None:
        if type(scene_split_record_count) is not int or scene_split_record_count < len(records):
            raise ValueError("image specialist execution slice requires the selected train count")
        receipt["scene_split_record_count"] = scene_split_record_count
    return receipt


def validate_specialist_execution_slice(
    execution_slice: dict[str, object], *, verified_record_count: int,
) -> None:
    fields = {"schema_version", "start_record", "record_count", "token_count", "records_sha256", "tokens_sha256"}
    permitted = {frozenset(fields), frozenset({*fields, "scene_split_record_count"})}
    if not isinstance(execution_slice, dict) or frozenset(execution_slice) not in permitted:
        raise ValueError("specialist execution slice has an invalid shape")
    if "scene_split_record_count" in execution_slice and (type(execution_slice["scene_split_record_count"]) is not int or execution_slice["scene_split_record_count"] < execution_slice["record_count"]):
        raise ValueError("specialist execution slice has an invalid selected scene count")
    if execution_slice.get("schema_version") != "ember-specialist-execution-slice-v1":
        raise ValueError("specialist execution slice has an unsupported schema")
    if type(verified_record_count) is not int or verified_record_count < 1:
        raise ValueError("specialist execution slice requires a verified corpus size")
    start, count, tokens = execution_slice.get("start_record"), execution_slice.get("record_count"), execution_slice.get("token_count")
    if type(start) is not int or start < 0 or type(count) is not int or count < 1 or start + count > verified_record_count:
        raise ValueError("specialist execution slice exceeds the verified corpus")
    if type(tokens) is not int or tokens < 1:
        raise ValueError("specialist execution slice has no token evidence")
    for field in ("records_sha256", "tokens_sha256"):
        digest = execution_slice.get(field)
        if not isinstance(digest, str) or len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError(f"specialist execution slice has an invalid {field}")


def append_training_telemetry(path: Path, *, kind: str, payload: dict[str, object]) -> None:
    """Append one bounded, path-free cockpit event from the canonical trainer."""

    if kind not in {
        "run_status",
        "train_step",
        "checkpoint",
        "checkpoint_deferred",
        "e4_receipt_write_failure",
    }:
        raise ValueError("training telemetry kind is not authorized")
    if any("path" in key.lower() for key in payload):
        raise ValueError("training telemetry payload must not disclose filesystem paths")
    event = {
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "kind": kind,
        "source": "ember-restart-3b",
        "payload": payload,
    }
    encoded = json.dumps(event, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    if len(encoded) > 4096:
        raise ValueError("training telemetry event exceeds the bounded channel contract")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() > 0:
            handle.seek(-1, os.SEEK_END)
            if handle.read(1) != b"\n":
                handle.seek(0, os.SEEK_END)
                handle.write(b"\n")
        handle.write(encoded)


def _latest_completed_training_step(path: Path, *, run_id: str) -> int:
    """Recover the latest valid trainer-owned step without trusting partial or future rows."""

    if not path.is_file():
        return 0
    now = datetime.now(timezone.utc).timestamp()
    latest: tuple[float, int] | None = None
    try:
        with path.open("rb") as handle:
            for raw_line in handle:
                if len(raw_line) > 4096:
                    continue
                try:
                    event = json.loads(raw_line.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError):
                    continue
                if not isinstance(event, dict) or event.get("kind") != "train_step" or event.get("source") != "ember-restart-3b":
                    continue
                payload = event.get("payload")
                timestamp = event.get("ts")
                if (
                    not isinstance(payload, dict)
                    or payload.get("run_id") != run_id
                    or not isinstance(timestamp, str)
                    or not timestamp.endswith("Z")
                ):
                    continue
                step = payload.get("step")
                try:
                    event_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()
                except ValueError:
                    continue
                if type(step) is not int or step < 0 or event_time > now:
                    continue
                candidate = (event_time, step)
                if latest is None or candidate > latest:
                    latest = candidate
    except OSError:
        return 0
    return 0 if latest is None else latest[1]


def _training_failure_class(error: Exception) -> str:
    if isinstance(error, MemoryError):
        return "RESOURCE_EXHAUSTED"
    if isinstance(error, TimeoutError):
        return "TIMEOUT"
    if isinstance(error, OSError):
        return "IO_ERROR"
    if isinstance(error, ValueError):
        return "CONTRACT_ERROR"
    return "TRAINER_ERROR"


class PublishedHousekeepingError(RuntimeError):
    """A checkpoint is durable, but its post-publication housekeeping failed."""

    def __init__(self, *, published_checkpoint_id: str, cause: Exception) -> None:
        if (
            not isinstance(published_checkpoint_id, str)
            or re.fullmatch(r"checkpoint-[a-z0-9]+(?:-[a-z0-9]+)*", published_checkpoint_id) is None
            or Path(published_checkpoint_id).name != published_checkpoint_id
        ):
            raise ValueError("published checkpoint locator is not a safe checkpoint ID")
        self.published_checkpoint_id = published_checkpoint_id
        self.cause = cause
        super().__init__(f"published checkpoint housekeeping failed: {cause}")


def _record_e4_measurement_write_failure(
    accumulator: dict[str, object],
    *,
    telemetry_path: Path,
    telemetry_run_id: str,
    error: Exception,
) -> None:
    """Count every failed receipt write and disclose the first through telemetry."""

    write_failures = int(accumulator["write_failures"]) + 1
    accumulator["write_failures"] = write_failures
    if write_failures != 1:
        return
    # Deliberately unguarded: telemetry is primary evidence for the credited
    # run. If this independent channel cannot write, continuing would create an
    # uncreditable GPU leg rather than merely lose the secondary E4 receipt.
    append_training_telemetry(
        telemetry_path,
        kind="e4_receipt_write_failure",
        payload={
            "run_id": telemetry_run_id,
            "failure_class": _training_failure_class(error),
            "error_type": type(error).__name__,
            "write_failures": write_failures,
        },
    )


def _frozen_envelope_fields(progress: Mapping[str, object]) -> dict[str, object]:
    """Derive the frozen `train_step` envelope's `tokens`/`wall_seconds` fields
    (`docs/spec/ember02-r1-e8-receipts-v1.md`, `a1_execution._train_step_envelope`)
    from the shared pretraining producer's own measured quantities (issue #1464).

    `run_pretraining_segment` (`pretrain.py`) already measures the exact same
    quantities under its own names -- `tokens_consumed` is the step's exact
    token count, `step_ms` is a `time.perf_counter()`-measured wall-clock
    duration in milliseconds -- for both the governed (`run()`) and semantic
    (`run_semantic()`) routes, since `run_manifest_bound_semantic_segment`
    delegates to the same producer. This is an honest unit/name transcription,
    never a new measurement: `wall_seconds` is `step_ms / 1000.0`.

    Honest-transcription only: a source quantity that is absent or not a
    usable positive number is omitted rather than defaulted, so a row this
    cannot enrich is left exactly as before -- `a1_e8_evidence.
    derive_liveness_series` correctly continues to find it liveness-incomplete
    rather than being handed a fabricated value.
    """
    fields: dict[str, object] = {}
    tokens = progress.get("tokens_consumed")
    if type(tokens) is int and tokens > 0:
        fields["tokens"] = tokens
    step_ms = progress.get("step_ms")
    if type(step_ms) in (int, float) and math.isfinite(step_ms) and step_ms > 0:
        fields["wall_seconds"] = step_ms / 1000.0
    return fields


def _make_e4_measurement_recorder(
    *, telemetry_path: Path | None, telemetry_run_id: str | None,
) -> Callable[[dict[str, object]], None]:
    """Build the per-step R1-E4 measurement accumulator + running-upsert writer (issue #1464).

    Shared by run() and run_semantic(): each producer's own progress_callback calls the
    returned function once per training step, after its own telemetry-append logic, so the
    e4-measurement-receipt.json upsert behaves identically no matter which producer trained
    the steps. Safe to construct even when telemetry_path/telemetry_run_id are None -- the
    returned function is never actually invoked in that case, mirroring the None-guard every
    caller already applies before touching telemetry.
    """
    e4_accumulator: dict[str, object] = {
        "wall_t0": time.perf_counter(), "cpu_t0": os.times(),
        "steps": 0, "tokens_total": 0, "step_ms_sum": 0.0, "tokens_missing": 0,
        "write_failures": 0,
    }

    def _write_e4_measurement_receipt() -> None:
        # Running upsert, rewritten after EVERY step (R1-E4, issue #1464). The
        # #1489 incident proved post-publication housekeeping can raise INSIDE
        # the training segment -- after the final checkpoint published -- which
        # destroyed the child's final stdout JSON and with it the only peak-VRAM
        # capture of the run. A receipt that exists from step 1 and is complete
        # as of the last finished step cannot be destroyed by any later failure.
        wall_seconds = max(time.perf_counter() - float(e4_accumulator["wall_t0"]), 1e-9)
        cpu_t0, cpu_now = e4_accumulator["cpu_t0"], os.times()
        process_cpu_seconds = max((cpu_now.user - cpu_t0.user) + (cpu_now.system - cpu_t0.system), 0.0)
        tokens_total, steps = int(e4_accumulator["tokens_total"]), int(e4_accumulator["steps"])
        tokens_known = int(e4_accumulator["tokens_missing"]) == 0 and tokens_total > 0
        step_ms_sum = float(e4_accumulator["step_ms_sum"])
        # Run-root derivation by MARKER, not blind depth (rev-1495 finding 2):
        # the credited layout is <run_root>/telemetry/<file>.jsonl, so parent
        # .parent is right exactly when the parent directory is named
        # "telemetry"; any other launcher-supplied shape writes BESIDE the
        # telemetry file instead -- always inside the run root, so the
        # battery's rglob finds it either way, and a shallow path can no
        # longer place the receipt outside the scanned tree.
        receipt_dir = telemetry_path.parent.parent if telemetry_path.parent.name == "telemetry" else telemetry_path.parent
        _atomic_json(receipt_dir / "e4-measurement-receipt.json", {
            "schema_version": "ember02-r1-e4-measurement/v1",
            "run_id": telemetry_run_id,
            "updated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "steps": steps,
            "tokens_total": tokens_total if tokens_known else None,
            "tokens_missing_steps": int(e4_accumulator["tokens_missing"]),
            "write_failures": int(e4_accumulator["write_failures"]),
            "wall_seconds": wall_seconds,
            "step_ms_sum": step_ms_sum,
            "tokens_per_second": (tokens_total / wall_seconds) if tokens_known else None,
            "tokens_per_second_step_basis": (tokens_total / (step_ms_sum / 1000.0)) if tokens_known and step_ms_sum > 0 else None,
            "mfu": {
                "value": ((6.0 * _E4_ACTIVE_PARAMETERS * tokens_total / wall_seconds) / _E4_ASSUMED_PEAK_FLOPS) if tokens_known else None,
                "flops_model": "6 * active_parameters * tokens_total / wall_seconds",
                "active_parameters": _E4_ACTIVE_PARAMETERS,
                "assumed_peak_flops": _E4_ASSUMED_PEAK_FLOPS,
                "assumed_peak_note": "RTX 4090 BF16 dense peak without structured sparsity; with FP32 accumulate the peak is ~82.6e12, doubling the reported utilization",
            },
            "peak_vram": {
                "allocated_bytes": int(torch.cuda.max_memory_allocated()),
                "reserved_bytes": int(torch.cuda.max_memory_reserved()),
            },
            "host_utilization": {
                "process_cpu_seconds": process_cpu_seconds,
                "wall_seconds": wall_seconds,
                "process_cpu_fraction": process_cpu_seconds / wall_seconds,
                "method": "os.times() user+system delta over the segment wall clock (this process only)",
            },
        })

    def record_e4_step(progress: dict[str, object]) -> None:
        e4_accumulator["steps"] = int(e4_accumulator["steps"]) + 1
        step_tokens = progress.get("tokens_consumed")
        if isinstance(step_tokens, int) and not isinstance(step_tokens, bool) and step_tokens > 0:
            e4_accumulator["tokens_total"] = int(e4_accumulator["tokens_total"]) + step_tokens
        else:
            # A payload without per-step tokens (an unpatched segment producer)
            # poisons the throughput denominator honestly: the receipt keeps
            # counting steps but reports tokens/s and MFU as null rather than
            # extrapolating -- fail-closed, the battery refuses nulls.
            e4_accumulator["tokens_missing"] = int(e4_accumulator["tokens_missing"]) + 1
        step_ms = progress.get("step_ms")
        if isinstance(step_ms, (int, float)) and not isinstance(step_ms, bool):
            e4_accumulator["step_ms_sum"] = float(e4_accumulator["step_ms_sum"]) + float(step_ms)
        try:
            _write_e4_measurement_receipt()
        except Exception as error:
            # rev-1495 finding 1: the evidence writer must never kill the
            # certified run it documents (that would invert the #1489 lesson --
            # the receipt exists BECAUSE crashes destroy evidence). A full
            # volume, a transient sharing violation on os.replace while the
            # cockpit reads the file, or a CUDA query error costs one write,
            # counted here and disclosed in the next successful receipt; the
            # accumulator itself lost nothing. KeyboardInterrupt/SystemExit
            # still propagate (BaseException, not Exception).
            _record_e4_measurement_write_failure(
                e4_accumulator,
                telemetry_path=telemetry_path,
                telemetry_run_id=telemetry_run_id,
                error=error,
            )

    return record_e4_step


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


def dense_a1_resource_preflight(
    *,
    parameter_count: int,
    write_budget_bytes: int,
    transient_checkpoint_bytes: int,
    host_commit_reserve_bytes: int,
    gpu_free_margin_bytes: int,
    b_custody_floor_bytes: int,
    available_commit_bytes: int,
    device_free_bytes: int,
    custody_free_bytes: int,
) -> dict[str, int | str]:
    """Refuse the dense A1 allocation unless every structural floor is live."""

    operands = (
        parameter_count,
        write_budget_bytes,
        transient_checkpoint_bytes,
        host_commit_reserve_bytes,
        gpu_free_margin_bytes,
        b_custody_floor_bytes,
        available_commit_bytes,
        device_free_bytes,
        custody_free_bytes,
    )
    if any(type(value) is not int or value <= 0 for value in operands):
        raise ValueError("dense A1 resource operands must be positive integers")
    if parameter_count < 3_000_000_000:
        raise ValueError("dense A1 resource admission requires at least 3B parameters")
    model_bytes = parameter_count * 2
    gradient_bytes = parameter_count * 2
    optimizer_bytes = parameter_count * 4 * 3
    checkpoint_payload_floor_bytes = model_bytes + optimizer_bytes
    required_commit_bytes = (
        optimizer_bytes + transient_checkpoint_bytes + host_commit_reserve_bytes
    )
    required_device_bytes = model_bytes + gradient_bytes + gpu_free_margin_bytes
    required_custody_bytes = checkpoint_payload_floor_bytes + b_custody_floor_bytes
    if write_budget_bytes < checkpoint_payload_floor_bytes:
        raise OSError("dense A1 write budget is below the full-state checkpoint floor")
    if transient_checkpoint_bytes > write_budget_bytes:
        raise OSError("dense A1 transient checkpoint authority exceeds write budget")
    if available_commit_bytes < required_commit_bytes:
        raise MemoryError("dense A1 host commit headroom is insufficient before allocation")
    if device_free_bytes < required_device_bytes:
        raise MemoryError("dense A1 GPU free headroom is insufficient before allocation")
    if custody_free_bytes < required_custody_bytes:
        raise OSError("dense A1 B custody floor is insufficient before allocation")
    return {
        "schema_version": "ember-a1-resource-preflight-v1",
        "status": "PASS",
        "parameter_count": parameter_count,
        "model_bytes": model_bytes,
        "gradient_bytes": gradient_bytes,
        "cpu_fp32_optimizer_bytes": optimizer_bytes,
        "checkpoint_payload_floor_bytes": checkpoint_payload_floor_bytes,
        "transient_checkpoint_bytes": transient_checkpoint_bytes,
        "host_commit_reserve_bytes": host_commit_reserve_bytes,
        "gpu_free_margin_bytes": gpu_free_margin_bytes,
        "b_custody_floor_bytes": b_custody_floor_bytes,
        "available_commit_bytes": available_commit_bytes,
        "device_free_bytes": device_free_bytes,
        "custody_free_bytes": custody_free_bytes,
        "required_commit_bytes": required_commit_bytes,
        "required_device_bytes": required_device_bytes,
        "required_custody_bytes": required_custody_bytes,
    }
def checkpoint_serialization_byte_bound(config_path: Path, *, active_parameters: int | None = None) -> int:
    """Derive one publishable checkpoint bound from the frozen architecture and optimizer contract."""

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    serialization = payload.get("checkpoints", {}).get("serialization")
    required = {"model_parameter_bytes", "optimizer_state_bytes_per_active_parameter", "format_overhead_bytes", "host_commit_reserve_gib"}
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


def specialist_checkpoint_bound_active_parameters(
    *,
    specialist_lineage: dict | None,
    optimizer_full_route_coverage: bool,
    active_parameters: int,
    total_parameters: int,
) -> int:
    """Select the optimizer coverage the checkpoint byte bound must budget.

    Two closed optimizer coverages are admissible for a specialist episode,
    mirroring the storage projection's admission shapes (#1473): a true
    single-route episode holds moments for shared plus exactly one expert,
    while a lineage episode that exact-resumed a full-coverage parent restores
    every route's moments verbatim and serializes full-coverage state at
    projection factor 1. The coverage decision is derived from the SAME live
    optimizer the projection later measures, so the bound and the projection
    cannot budget different worlds (#1483: budgeting shared-plus-one-expert
    under-declared the inherited full set and refused the by-design
    publication). The governed-vertical shard realizes every expert, so its
    bound always admits full coverage (#1320).
    """

    if specialist_lineage is not None and not optimizer_full_route_coverage:
        return active_parameters
    return total_parameters


def checkpoint_host_commit_reserve_bytes(config_path: Path) -> int:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    serialization = payload.get("checkpoints", {}).get("serialization")
    if not isinstance(serialization, dict):
        raise ValueError("checkpoint serialization contract has an invalid shape")
    reserve_gib = serialization.get("host_commit_reserve_gib")
    if type(reserve_gib) is not int or reserve_gib < 1:
        raise ValueError("checkpoint host commit reserve must be a positive integer GiB value")
    return reserve_gib * 1024**3


_LOW_COMMIT_DEFERRAL_RECEIPT_LIMIT = 8 * 1024


def default_checkpoint_low_commit_deferral_policy_path() -> Path:
    """The finite retry-bound policy lives in its own file, deliberately never inside
    the frozen ``ember-restart-3b.json`` production contract: that config's exact
    bytes are hash-bound into checked-in input-identity/production-rung/
    specialist-stream receipts (``model_config_sha256`` / ``model_config.sha256``),
    so editing it cascades into unrelated regenerated fixtures. The deferral policy
    is operational tuning, not part of that identity chain, so it lives alongside
    this module instead."""
    return Path(__file__).resolve().with_name("checkpoint-low-commit-deferral-policy.json")


def checkpoint_low_commit_deferral_policy(policy_path: Path) -> dict[str, int]:
    """Load the finite retry bound for DEFERRED_LOW_COMMIT checkpoint publications."""
    try:
        payload = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("checkpoint low-commit deferral policy file is missing or unreadable") from error
    policy = payload.get("low_commit_deferral") if isinstance(payload, dict) else None
    if not isinstance(policy, dict):
        raise ValueError("checkpoint low-commit deferral policy has an invalid shape")
    max_deferrals = policy.get("max_deferrals")
    max_uncheckpointed_step_distance = policy.get("max_uncheckpointed_step_distance")
    if type(max_deferrals) is not int or max_deferrals < 0:
        raise ValueError("checkpoint low-commit deferral max_deferrals must be a nonnegative integer")
    if type(max_uncheckpointed_step_distance) is not int or max_uncheckpointed_step_distance < 1:
        raise ValueError("checkpoint low-commit deferral max_uncheckpointed_step_distance must be a positive integer")
    return {
        "max_deferrals": max_deferrals,
        "max_uncheckpointed_step_distance": max_uncheckpointed_step_distance,
    }


def _write_low_commit_deferral_receipt(
    checkpoint_parent: Path,
    *,
    global_step: int,
    deferral_count: int,
    uncheckpointed_step_distance: int,
    error: CheckpointDeferredLowCommit,
    retry_error: CheckpointDeferredLowCommit | None = None,
    released_record_count: int | None = None,
    comparison_operands: Mapping[str, object] | None = None,
) -> Path:
    """Bounded, receipted evidence for one DEFERRED_LOW_COMMIT checkpoint boundary.

    Never overlaps the published-checkpoint or staging namespaces, so it can never
    be mistaken for a selectable checkpoint candidate. When a final-publication
    release+retry was attempted (#1465) the receipt gains additive retry keys;
    every v1 field keeps its exact meaning (the boundary's first measurement).
    """
    receipts_dir = checkpoint_parent / ".checkpoint-deferrals"
    receipts_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "ember-checkpoint-deferred-low-commit-v1",
        "status": "DEFERRED_LOW_COMMIT",
        "global_step": global_step,
        "deferral_count": deferral_count,
        "uncheckpointed_step_distance": uncheckpointed_step_distance,
        "available_commit_bytes": error.available_commit_bytes,
        "required_commit_bytes": error.required_commit_bytes,
        "streaming_peak_bytes": error.streaming_peak_bytes,
        "reserve_bytes": error.reserve_bytes,
        "observed_at_ns": time.time_ns(),
        "comparison_operands": _normalize_failure_comparison_operands(
            comparison_operands
            if comparison_operands is not None
            else _empty_failure_comparison_operands()
        ),
    }
    if retry_error is not None:
        payload["retry_observed_commit_bytes"] = retry_error.available_commit_bytes
        payload["retry_required_commit_bytes"] = retry_error.required_commit_bytes
        payload["released_record_count"] = released_record_count
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if len(encoded) >= _LOW_COMMIT_DEFERRAL_RECEIPT_LIMIT:
        raise RuntimeError("checkpoint low-commit deferral receipt exceeds its bounded retention limit")
    digest = hashlib.sha256(encoded).hexdigest()
    target = receipts_dir / f"deferred-low-commit-step-{global_step}-{digest[:16]}.json"
    atomic_create_durable(target, encoded)
    return target


def _release_final_publication_ballast(
    records: list[dict[str, object]], *, model: torch.nn.Module | None = None,
) -> dict[str, object]:
    """Tear down every non-checkpointable allocation ahead of the final retry.

    The commit trough at final publication is structural, not contention luck:
    across canary runs the run's own footprint grew into whatever headroom the
    host offered (identical required bytes, near-identical trough, despite a
    multi-GiB higher launch baseline), so no pre-launch floor can cure it and a
    bare re-measure loop would observe the same number forever. The retry is
    only meaningful after real teardown:

    - parameter GRADIENTS (``zero_grad(set_to_none=True)``): the largest single
      releasable block, several GiB across shared plus the active expert -- and
      never part of any checkpoint artifact (checkpoints serialize parameters,
      optimizer moments, rng, cursor; ``.grad`` is not in any of them);
    - the parsed record buffers: each record dict is emptied in place, so every
      frame that still references the same dicts -- the segment loop's bounded
      slice, a caller's scene-split list -- drops the token and media payloads
      with it. Legal only after every receipt input derived from record content
      is already bound (execution-slice receipt, data cursor);
    - then ``gc.collect()`` + ``torch.cuda.empty_cache()`` so the allocator
      actually returns the pages before the commit probe re-measures.

    Parameters and optimizer moments -- the checkpointable state -- are never
    touched.
    """

    if model is not None:
        model.zero_grad(set_to_none=True)
    released_record_count = len(records)
    for record in records:
        record.clear()
    records.clear()
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return {"released_record_count": released_record_count}


def _publish_checkpoint_with_low_commit_deferral(
    *,
    checkpoint_parent: Path,
    config_path: Path,
    global_step: int,
    last_checkpointed_step: int,
    deferral_state: dict[str, int],
    publish: Callable[[], tuple[dict[str, object], dict[str, object]]],
    telemetry_path: Path | None,
    telemetry_run_id: str | None,
    policy_path: Path | None = None,
    release_for_final_retry: Callable[[], dict[str, object]] | None = None,
    comparison_operands: Mapping[str, object] | None = None,
) -> tuple[dict[str, object], dict[str, object]] | None:
    """Publish one checkpoint boundary, deferring (never silently dropping, never
    continuing indefinitely) on insufficient host commit headroom.

    Returns the new ``(checkpoint, parameter_receipt)`` pair on a normal publish.
    Returns ``None`` when this boundary was DEFERRED_LOW_COMMIT: the caller's prior
    known-good checkpoint stays exactly as it was -- untouched, still the sole
    selectable candidate -- because :func:`checkpoint_commit_preflight` always runs
    before any staging directory is created. Raises (fail-closed) once the finite
    deferral count or uncheckpointed-step distance bound configured in the policy
    file (default: :func:`default_checkpoint_low_commit_deferral_policy_path`) is
    exceeded.

    ``release_for_final_retry`` may be passed ONLY for a segment's final
    publication boundary (#1465): a final boundary has no later interval to
    absorb a deferral, so deferring forfeits the whole trained segment. On the
    first low-commit refusal the callable performs real teardown of state that
    is not part of any checkpoint artifact (parameter gradients, parsed record
    buffers -- see :func:`_release_final_publication_ballast`), the publication
    is retried exactly once against the re-measured headroom, and a retry that
    still lands short falls through to the exact deferral receipt + fail-closed
    behavior below. The receipt then carries both measurements -- pre-teardown
    (``available_commit_bytes``) and post-teardown
    (``retry_observed_commit_bytes``) -- so analysis can read how much the
    teardown actually returned.
    """
    policy = checkpoint_low_commit_deferral_policy(
        policy_path if policy_path is not None else default_checkpoint_low_commit_deferral_policy_path()
    )

    def attempt() -> tuple[dict[str, object], dict[str, object]]:
        return _retain_after_success(
            checkpoint_parent,
            max_serialized_bytes=checkpoint_retention_budget_bytes(config_path),
            max_quarantine_serialized_bytes=checkpoint_quarantine_budget_bytes(config_path),
            receipt_aware=True,
            operation=publish,
        )

    try:
        return attempt()
    except CheckpointDeferredLowCommit as error:
        retry_error: CheckpointDeferredLowCommit | None = None
        released_record_count: int | None = None
        if release_for_final_retry is not None:
            release_evidence = release_for_final_retry()
            released = release_evidence.get("released_record_count")
            released_record_count = released if type(released) is int else 0
            try:
                return attempt()
            except CheckpointDeferredLowCommit as second_error:
                retry_error = second_error
        deferral_state["count"] += 1
        distance = global_step - last_checkpointed_step
        comparison_operands = _normalize_failure_comparison_operands(
            error.comparison_operands
            if error.comparison_operands is not None
            else comparison_operands
        )
        derived_bound = checkpoint_retention_budget_bytes(config_path)
        if comparison_operands["derived_byte_bound_bytes"] is None:
            comparison_operands["derived_byte_bound_bytes"] = derived_bound
        comparison_operands["derived_byte_bound_inputs"].update(
            {
                "max_serialized_bytes": derived_bound,
                "model_config_sha256": _sha256(config_path),
            }
        )
        comparison_operands["available_commit_bytes"] = error.available_commit_bytes
        comparison_operands["required_commit_bytes"] = error.required_commit_bytes
        receipt_path = _write_low_commit_deferral_receipt(
            checkpoint_parent,
            global_step=global_step,
            deferral_count=deferral_state["count"],
            uncheckpointed_step_distance=distance,
            error=error,
            retry_error=retry_error,
            released_record_count=released_record_count,
            comparison_operands=comparison_operands,
        )
        if telemetry_path is not None and telemetry_run_id is not None:
            append_training_telemetry(telemetry_path, kind="checkpoint_deferred", payload={
                "run_id": telemetry_run_id,
                "step": global_step,
                "status": "DEFERRED_LOW_COMMIT",
                "deferral_count": deferral_state["count"],
                "uncheckpointed_step_distance": distance,
                "available_commit_bytes": error.available_commit_bytes,
                "required_commit_bytes": error.required_commit_bytes,
                "streaming_peak_bytes": error.streaming_peak_bytes,
                "reserve_bytes": error.reserve_bytes,
                "receipt_sha256": _sha256(receipt_path),
                **({"retry_observed_commit_bytes": retry_error.available_commit_bytes} if retry_error is not None else {}),
            })
        if (
            deferral_state["count"] > policy["max_deferrals"]
            or distance > policy["max_uncheckpointed_step_distance"]
        ):
            raise RuntimeError(
                "checkpoint low-commit deferral bound exceeded: "
                f"deferral_count={deferral_state['count']} (max {policy['max_deferrals']}), "
                f"uncheckpointed_step_distance={distance} "
                f"(max {policy['max_uncheckpointed_step_distance']})"
            ) from error
        return None


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

def _has_quarantine_component(path: Path) -> bool:
    return any(str(part).casefold() == ".checkpoint-quarantine" for part in Path(path).parts)


def _reject_quarantined_checkpoint_path(*paths: Path) -> None:
    if any(_has_quarantine_component(path) for path in paths):
        raise ValueError("quarantined checkpoint is not admitted or selectable")


def production_artifact_root(
    candidate: Path,
    *,
    c_relocated_under_disk_budget_runner: bool = False,
    relocation_custody_root: Path | None = None,
) -> Path:
    """Accept B: custody, or an explicit C: child of the disk-runner custody root."""

    if type(c_relocated_under_disk_budget_runner) is not bool:
        raise ValueError("C relocation custody flag must be boolean")
    lexical = Path(candidate)
    resolved = lexical.resolve()
    _reject_quarantined_checkpoint_path(lexical, resolved)
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

def _custody_link_or_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError as error:
        raise RuntimeError(f"custody byte accounting could not inspect {path}") from error
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _lexical_nonreparse_directory(path: Path) -> Path:
    """Return an absolute lexical directory only after inspecting every component."""

    lexical = Path(os.path.abspath(str(path)))
    parts = lexical.parts
    current = Path(parts[0]) if parts else lexical
    for part in parts[1:]:
        current = current / part
        if _custody_link_or_reparse(current):
            raise ValueError("checkpoint quarantine source contains a link or reparse component")
    if _custody_link_or_reparse(lexical):
        raise ValueError("checkpoint quarantine source contains a link or reparse component")
    if not lexical.is_dir():
        raise ValueError("checkpoint quarantine source must be a directory")
    return lexical


def _file_identity(path: Path) -> tuple[int, int] | str:
    stat = path.stat()
    inode = int(getattr(stat, "st_ino", 0))
    if inode:
        return (int(getattr(stat, "st_dev", 0)), inode)
    return str(path.resolve())

def _custody_file_rows(parent: Path) -> list[dict[str, object]]:
    """Snapshot every physical custody file once and classify its root bucket."""

    parent = parent.resolve()
    seen: set[tuple[int, int] | str] = set()
    rows: list[dict[str, object]] = []
    for path in parent.rglob("*"):
        try:
            if _custody_link_or_reparse(path):
                raise RuntimeError(f"custody accounting encountered a symlink or reparse point: {path}")
            if not path.is_file():
                continue
            relative = path.relative_to(parent)
            top = relative.parts[0] if relative.parts else ""
            if top == _CUSTODY_LEDGER_LOCK:
                continue
            identity = _file_identity(path)
            if identity in seen:
                continue
            seen.add(identity)
            bucket = "quarantine" if top == ".checkpoint-quarantine" else "live" if top.startswith("checkpoint-") else "evidence" if top == _CUSTODY_LEDGER else "other"
            rows.append({"path": relative.as_posix(), "bucket": bucket, "bytes": path.stat().st_size})
        except OSError as error:
            raise RuntimeError(f"custody byte accounting could not inspect {path}") from error
    return rows


def _custody_serialized_bytes(parent: Path) -> int:
    """Charge all custody bytes with a unique-inode walk."""

    return sum(int(row["bytes"]) for row in _custody_file_rows(parent))


def _canonical_custody_deletion_pointer(raw_pointer: object) -> str:
    """Return the sole portable ledger spelling for quarantine evidence paths."""

    if not isinstance(raw_pointer, str) or not raw_pointer:
        raise ValueError("custody deletion ledger lacks a canonical pointer")
    if "\\" in raw_pointer or raw_pointer != raw_pointer.casefold():
        raise ValueError("custody deletion ledger pointer is not canonical POSIX form")
    path = PurePosixPath(raw_pointer)
    parts = path.parts
    canonical = "/".join(parts)
    if (
        path.is_absolute()
        or raw_pointer != canonical
        or len(parts) != 2
        or parts[0] != ".checkpoint-quarantine"
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ValueError("custody deletion ledger lacks a safe canonical quarantine pointer")
    leaf = parts[1]
    stem = leaf.split("-", 1)[0]
    if not _EVIDENCE_FILENAME_RE.fullmatch(leaf) or stem in _WINDOWS_RESERVED_STEMS:
        raise ValueError("custody deletion ledger pointer is not a portable evidence filename")
    return canonical


def _quarantine_evidence_identity(parent: Path, path: Path) -> tuple[str, int, str, tuple[int, int]]:
    """Read one direct evidence leaf and bind its canonical path, bytes, and inode."""

    if _custody_link_or_reparse(path) or not path.is_file():
        raise ValueError("quarantine evidence leaf is not a direct regular file")
    try:
        pointer = _canonical_custody_deletion_pointer(path.relative_to(parent).as_posix())
        before = path.stat()
        payload = path.read_bytes()
        after = path.stat()
    except OSError as error:
        raise ValueError("quarantine evidence leaf could not be snapshotted") from error
    if _custody_link_or_reparse(path) or not path.is_file():
        raise ValueError("quarantine evidence leaf changed into a link or non-file")
    identity = (int(getattr(before, "st_dev", 0)), int(getattr(before, "st_ino", 0)))
    after_identity = (int(getattr(after, "st_dev", 0)), int(getattr(after, "st_ino", 0)))
    if identity != after_identity or before.st_size != after.st_size or after.st_size != len(payload):
        raise ValueError("quarantine evidence leaf changed while being snapshotted")
    return pointer, len(payload), hashlib.sha256(payload).hexdigest(), identity


def _portable_evidence_stem(name: str) -> str:
    if not isinstance(name, str) or not name:
        raise ValueError("quarantine evidence name must be a nonempty string")
    stem = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-") or "evidence"
    if stem.split("-", 1)[0] in _WINDOWS_RESERVED_STEMS:
        stem = f"evidence-{stem}"
    return stem


def _custody_deletion_path(parent: Path, pointer: str) -> Path:
    return parent.joinpath(*PurePosixPath(pointer).parts)


def _windows_custody_ledger_mutex_name_from_identity(identity: tuple[int, int, int]) -> str:
    """Name one machine-wide mutex from immutable directory volume/file identity."""

    if len(identity) != 3 or any(type(part) is not int or part < 0 for part in identity):
        raise ValueError("Windows custody directory identity is invalid")
    payload = ":".join(str(part) for part in identity).encode("ascii")
    return "Global\\ember-checkpoint-custody-" + hashlib.sha256(payload).hexdigest()


@contextlib.contextmanager
def _windows_open_custody_directory(parent: Path) -> object:
    """Hold a non-delete-share handle and yield its canonical target and identity."""

    class _ByHandleFileInformation(ctypes.Structure):
        _fields_ = [("attributes", ctypes.c_ulong), ("creation_low", ctypes.c_ulong), ("creation_high", ctypes.c_ulong), ("access_low", ctypes.c_ulong), ("access_high", ctypes.c_ulong), ("write_low", ctypes.c_ulong), ("write_high", ctypes.c_ulong), ("volume_serial", ctypes.c_ulong), ("size_high", ctypes.c_ulong), ("size_low", ctypes.c_ulong), ("link_count", ctypes.c_ulong), ("file_index_high", ctypes.c_ulong), ("file_index_low", ctypes.c_ulong)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p)
    create_file.restype = ctypes.c_void_p
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (ctypes.c_void_p,)
    close_handle.restype = ctypes.c_bool
    get_information = kernel32.GetFileInformationByHandle
    get_information.argtypes = (ctypes.c_void_p, ctypes.POINTER(_ByHandleFileInformation))
    get_information.restype = ctypes.c_bool
    get_final_name = kernel32.GetFinalPathNameByHandleW
    get_final_name.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong)
    get_final_name.restype = ctypes.c_ulong
    handle = create_file(str(parent), 0x80000000, 0x00000003, None, 3, 0x02000000, None)
    invalid = ctypes.c_void_p(-1).value
    if not handle or handle == invalid:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        information = _ByHandleFileInformation()
        if not get_information(handle, ctypes.byref(information)):
            raise ctypes.WinError(ctypes.get_last_error())
        buffer = ctypes.create_unicode_buffer(32768)
        written = int(get_final_name(handle, buffer, len(buffer), 0))
        if not written or written >= len(buffer):
            raise ctypes.WinError(ctypes.get_last_error())
        yield Path(buffer.value), (int(information.volume_serial), int(information.file_index_high), int(information.file_index_low))
    finally:
        if not close_handle(handle):
            raise ctypes.WinError(ctypes.get_last_error())


def _windows_directory_identity(parent: Path) -> tuple[int, int, int]:
    """Read volume serial and 64-bit file ID from one opened directory handle."""

    with _windows_open_custody_directory(parent) as (_, identity):
        return identity

def _windows_custody_ledger_mutex_name(parent: Path) -> str:
    """Return a machine-wide mutex name from the opened custody directory identity."""

    return _windows_custody_ledger_mutex_name_from_identity(_windows_directory_identity(parent))


@contextlib.contextmanager
def _windows_custody_ledger_mutex_from_identity(identity: tuple[int, int, int]) -> object:
    """Hold the machine-wide mutex for one already-opened custody directory."""

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_mutex = kernel32.CreateMutexW
    create_mutex.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
    create_mutex.restype = ctypes.c_void_p
    wait_for_single_object = kernel32.WaitForSingleObject
    wait_for_single_object.argtypes = (ctypes.c_void_p, ctypes.c_ulong)
    wait_for_single_object.restype = ctypes.c_ulong
    release_mutex = kernel32.ReleaseMutex
    release_mutex.argtypes = (ctypes.c_void_p,)
    release_mutex.restype = ctypes.c_bool
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (ctypes.c_void_p,)
    close_handle.restype = ctypes.c_bool
    handle = create_mutex(None, False, _windows_custody_ledger_mutex_name_from_identity(identity))
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    acquired = False
    try:
        milliseconds = max(0, int(_LEDGER_LOCK_WAIT_SECONDS * 1000))
        result = int(wait_for_single_object(handle, milliseconds))
        if result in {0x00000000, 0x00000080}:
            acquired = True
            yield
            return
        if result == 0x00000102:
            raise RuntimeError("timed out waiting for the custody ledger writer lock")
        raise ctypes.WinError(ctypes.get_last_error())
    finally:
        try:
            if acquired and not release_mutex(handle):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            if not close_handle(handle):
                raise ctypes.WinError(ctypes.get_last_error())


@contextlib.contextmanager
def _windows_custody_ledger_mutex(parent: Path) -> object:
    """Bind ledger operations to one held directory handle and its machine-wide mutex."""

    with _windows_open_custody_directory(parent) as (canonical_parent, identity):
        with _windows_custody_ledger_mutex_from_identity(identity):
            yield canonical_parent

@contextlib.contextmanager
def _custody_ledger_write_lock(parent: Path) -> object:
    """Serialize a ledger snapshot/replacement across threads and live processes."""

    if os.name == "nt":
        with _windows_custody_ledger_mutex(parent) as canonical_parent:
            yield canonical_parent
        return
    parent = parent.resolve()
    try:
        import fcntl
    except ImportError as error:
        raise RuntimeError("POSIX custody ledger requires fcntl.flock kernel locking") from error
    lock_path = parent / _CUSTODY_LEDGER_LOCK
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield parent
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)
def _canonical_frame_bytes(frame: Mapping[str, object]) -> bytes:
    return json.dumps(dict(frame), sort_keys=True, separators=(",", ":")).encode("utf-8")


def _validate_custody_ledger_frame_chain(events: list[object]) -> None:
    """Validate v4 frames: content and full-frame hashes are distinct chain authority."""
    chained = [event for event in events if isinstance(event, dict) and event.get("schema_version") == _CUSTODY_LEDGER_SCHEMA]
    legacy = [event for event in events if isinstance(event, dict) and event.get("schema_version") in {_PREVIOUS_CHAINED_LEDGER_SCHEMA, _ORDERED_CUSTODY_LEDGER_SCHEMA, _LEGACY_CUSTODY_LEDGER_SCHEMA}]
    if chained and legacy:
        raise RuntimeError("custody deletion ledger mixes chained and legacy frames")
    if legacy:
        for event in legacy:
            if event.get("schema_version") == _PREVIOUS_CHAINED_LEDGER_SCHEMA:
                required_v3 = {"schema_version", "event", "pointer", "bytes", "sha256", "reason", "sequence", "previous_frame_sha256", "frame_sha256"}
                if set(event) != required_v3 or not _is_sha256(event.get("frame_sha256")):
                    raise RuntimeError("legacy chained custody frame has invalid shape")
    previous = "0" * 64
    required = {"schema_version", "event", "pointer", "bytes", "sha256", "reason", "sequence", "previous_frame_sha256", "frame_content_sha256", "frame_sha256"}
    for sequence, event in enumerate(chained):
        if set(event) != required or event.get("sequence") != sequence or event.get("previous_frame_sha256") != previous:
            raise RuntimeError("custody deletion ledger frame chain sequence is invalid")
        body = {key: value for key, value in event.items() if key not in {"frame_content_sha256", "frame_sha256"}}
        content = hashlib.sha256(_canonical_frame_bytes(body)).hexdigest()
        full = hashlib.sha256(_canonical_frame_bytes({**body, "frame_content_sha256": content})).hexdigest()
        if event.get("frame_content_sha256") != content or event.get("frame_sha256") != full:
            raise RuntimeError("custody deletion ledger frame hash does not match canonical content")
        previous = full


def _next_custody_ledger_frame(event: dict[str, object], prior_events: list[object]) -> dict[str, object]:
    """Bind a v4 transition to the prior complete canonical frame, never only its content."""
    _validate_custody_ledger_frame_chain(prior_events)
    if any(isinstance(row, dict) and row.get("schema_version") != _CUSTODY_LEDGER_SCHEMA for row in prior_events):
        raise RuntimeError("legacy ledger requires explicit migration before v4 append")
    prior = [row for row in prior_events if isinstance(row, dict)]
    body = {"schema_version": _CUSTODY_LEDGER_SCHEMA, "event": event["event"], "pointer": event["pointer"], "bytes": event["bytes"], "sha256": event["sha256"], "reason": event["reason"], "sequence": len(prior), "previous_frame_sha256": str(prior[-1]["frame_sha256"]) if prior else "0" * 64}
    content = hashlib.sha256(_canonical_frame_bytes(body)).hexdigest()
    full = {**body, "frame_content_sha256": content}
    return {**full, "frame_sha256": hashlib.sha256(_canonical_frame_bytes(full)).hexdigest()}
def _parse_custody_ledger_payload(payload: bytes) -> list[object]:
    """Parse one complete newline-framed ledger byte snapshot without reopening it."""

    if payload and not payload.endswith(b"\n"):
        raise RuntimeError("custody deletion ledger has an unterminated or torn tail")
    events: list[object] = []
    for line in payload.splitlines():
        try:
            events.append(json.loads(line))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise RuntimeError("custody deletion ledger is malformed") from error
    return events


def _custody_ledger_snapshot(parent: Path) -> tuple[bytes, list[object]]:
    """Read one complete newline-framed ledger snapshot, rejecting torn tails."""

    ledger = parent / _CUSTODY_LEDGER
    if not ledger.exists():
        return b"", []
    try:
        payload = ledger.read_bytes()
    except OSError as error:
        raise RuntimeError("custody deletion ledger could not be read") from error
    return payload, _parse_custody_ledger_payload(payload)


def _custody_chain_head(events: list[object]) -> str:
    _validate_custody_ledger_frame_chain(events)
    chained = [event for event in events if isinstance(event, dict) and event.get("schema_version") == _CUSTODY_LEDGER_SCHEMA]
    return str(chained[-1]["frame_sha256"]) if chained else "0" * 64


_HEAD_RECEIPT_SCHEMA = "ember-custody-ledger-head-transaction-v1"


def _ledger_binding(payload: bytes) -> dict[str, object]:
    events = _parse_custody_ledger_payload(payload)
    return {"ledger_sha256": hashlib.sha256(payload).hexdigest(), "ledger_bytes": len(payload), "chain_head_sha256": _custody_chain_head(events), "frame_count": len(events)}


def _custody_path_subject(canonical_parent: Path) -> str:
    """Return the opaque receipt identity for one OS-canonical custody directory."""

    canonical = Path(canonical_parent).resolve(strict=True)
    spelling = str(canonical)
    if os.name == "nt":
        if spelling.startswith("\\\\?\\UNC\\"):
            spelling = "\\\\" + spelling[8:]
        elif spelling.startswith("\\\\?\\"):
            spelling = spelling[4:]
        normalized = os.path.normcase(os.path.normpath(spelling)).casefold()
    else:
        # POSIX path spellings are case-sensitive; collapsing their case would
        # allow distinct custody roots to share one opaque receipt identity.
        normalized = os.path.normpath(spelling)
    return "custody-path-sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _custody_subject_token(canonical_parent: Path) -> str:
    """Return only the opaque digest portion for external receipt filenames."""

    return _custody_path_subject(canonical_parent).split(":", 1)[1]


def prepare_custody_ledger_transaction(*, receipt_path: Path, old_ledger: bytes, new_ledger: bytes, operation_id: str, subject: str) -> dict[str, object]:
    """Exclusively create, or exactly resume, a durable external old/new transaction."""
    if not isinstance(operation_id, str) or not operation_id or not isinstance(subject, str) or not subject:
        raise ValueError("ledger transaction requires a nonempty operation ID and subject")
    receipt = {"schema_version": _HEAD_RECEIPT_SCHEMA, "result": "PREPARED", "operation_id": operation_id, "subject": subject, "old": _ledger_binding(old_ledger), "new": _ledger_binding(new_ledger)}
    payload = (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    try:
        atomic_create_durable(receipt_path, payload)
    except FileExistsError:
        existing = _head_transaction(receipt_path)
        if {key: existing[key] for key in receipt if key != "result"} != {key: receipt[key] for key in receipt if key != "result"}:
            raise RuntimeError("external custody ledger transaction identity collision")
        return existing
    return receipt
def _head_transaction(path: Path) -> dict[str, object]:
    receipt, _ = _json_snapshot(path, label="external custody ledger transaction")
    if set(receipt) != {"schema_version", "result", "operation_id", "subject", "old", "new"} or receipt.get("schema_version") != _HEAD_RECEIPT_SCHEMA or receipt.get("result") not in {"PREPARED", "COMMITTED", "ABORTED"} or not isinstance(receipt.get("operation_id"), str) or not receipt["operation_id"] or not isinstance(receipt.get("subject"), str) or not receipt["subject"]:
        raise RuntimeError("external custody ledger transaction has invalid shape")
    for binding in (receipt["old"], receipt["new"]):
        if not isinstance(binding, dict) or set(binding) != {"ledger_sha256", "ledger_bytes", "chain_head_sha256", "frame_count"} or any(not _is_sha256(binding.get(key)) for key in ("ledger_sha256", "chain_head_sha256")) or any(type(binding.get(key)) is not int or binding[key] < 0 for key in ("ledger_bytes", "frame_count")):
            raise RuntimeError("external custody ledger transaction has invalid bindings")
    return receipt


def _finalize_custody_ledger_transaction_locked(canonical_parent: Path, *, receipt_path: Path) -> dict[str, object]:
    expected_subject = _custody_path_subject(canonical_parent)
    receipt = _head_transaction(receipt_path)
    if receipt["subject"] != expected_subject:
        raise RuntimeError("custody ledger transaction subject does not match canonical parent")
    current, _ = _custody_ledger_snapshot(canonical_parent)
    current_binding = _ledger_binding(current)
    if receipt["result"] == "ABORTED":
        if current_binding != receipt["old"]:
            raise RuntimeError("aborted ledger transaction no longer matches its old head")
        return receipt
    if receipt["result"] == "COMMITTED":
        if current_binding != receipt["new"]:
            raise RuntimeError("committed ledger transaction no longer matches its new head")
        return receipt
    if current_binding == receipt["old"]:
        aborted = {**receipt, "result": "ABORTED"}
        _atomic_json(receipt_path, aborted)
        return aborted
    if current_binding != receipt["new"]:
        raise RuntimeError("ledger transaction refuses unbound or truncated ledger bytes")
    committed = {**receipt, "result": "COMMITTED"}
    _atomic_json(receipt_path, committed)
    return committed

def finalize_custody_ledger_transaction(parent: Path, *, receipt_path: Path) -> dict[str, object]:
    """Replay exact bytes against a pre-existing external transaction; never infer/truncate a tail."""
    with _custody_ledger_write_lock(parent) as canonical_parent:
        return _finalize_custody_ledger_transaction_locked(canonical_parent, receipt_path=receipt_path)
def _recover_parent_scoped_transactions_locked(canonical_parent: Path) -> None:
    """Resolve pending external append receipts before certifying a later head."""
    expected_subject = _custody_path_subject(canonical_parent)
    pattern = f"custody-append-{_custody_subject_token(canonical_parent)}-*.json"
    for receipt_path in sorted(canonical_parent.parent.glob(pattern)):
        receipt = _head_transaction(receipt_path)
        if receipt["subject"] != expected_subject:
            raise RuntimeError("parent-scoped custody transaction has a foreign subject")
        if receipt["result"] == "PREPARED":
            _finalize_custody_ledger_transaction_locked(canonical_parent, receipt_path=receipt_path)
        elif receipt["result"] not in {"COMMITTED", "ABORTED"}:
            raise RuntimeError("parent-scoped custody transaction is nonterminal")

_TAIL_RECOVERY_SCHEMA = "ember-custody-ledger-tail-recovery-v1"
_TAIL_RECOVERY_REFUSAL_SCHEMA = "ember-custody-ledger-tail-recovery-refusal-v1"


def _raw_byte_binding(payload: bytes) -> dict[str, object]:
    return {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}


def _split_torn_custody_ledger(payload: bytes) -> tuple[bytes, bytes]:
    """Return only the complete newline-framed prefix and its unframed tail."""

    boundary = payload.rfind(b"\n")
    prefix = payload[: boundary + 1] if boundary >= 0 else b""
    tail = payload[boundary + 1 :] if boundary >= 0 else payload
    if not tail:
        raise RuntimeError("custody deletion ledger has no torn tail to recover")
    return prefix, tail


def _tail_recovery_receipt(path: Path) -> dict[str, object]:
    receipt, _ = _json_snapshot(path, label="custody ledger tail-recovery receipt")
    required = {"schema_version", "result", "subject", "archive", "original", "prefix", "tail", "verification"}
    if set(receipt) != required or receipt.get("schema_version") != _TAIL_RECOVERY_SCHEMA or receipt.get("result") not in {"PREPARED", "COMMITTED"}:
        raise RuntimeError("custody ledger tail-recovery receipt has invalid shape")
    if not isinstance(receipt.get("subject"), str) or not receipt["subject"] or not isinstance(receipt.get("archive"), str) or not receipt["archive"]:
        raise RuntimeError("custody ledger tail-recovery receipt has invalid identity")
    original = receipt.get("original")
    tail = receipt.get("tail")
    prefix = receipt.get("prefix")
    if not isinstance(original, dict) or set(original) != {"sha256", "bytes"} or not isinstance(tail, dict) or set(tail) != {"sha256", "bytes"}:
        raise RuntimeError("custody ledger tail-recovery receipt has invalid byte bindings")
    if not isinstance(prefix, dict) or set(prefix) != {"ledger_sha256", "ledger_bytes", "chain_head_sha256", "frame_count"}:
        raise RuntimeError("custody ledger tail-recovery receipt has invalid prefix binding")
    for binding in (original, tail):
        if not _is_sha256(binding.get("sha256")) or type(binding.get("bytes")) is not int or binding["bytes"] < 0:
            raise RuntimeError("custody ledger tail-recovery receipt has invalid byte bindings")
    for key in ("ledger_sha256", "chain_head_sha256"):
        if not _is_sha256(prefix.get(key)):
            raise RuntimeError("custody ledger tail-recovery receipt has invalid prefix binding")
    for key in ("ledger_bytes", "frame_count"):
        if type(prefix.get(key)) is not int or prefix[key] < 0:
            raise RuntimeError("custody ledger tail-recovery receipt has invalid prefix binding")
    verification = receipt.get("verification")
    if not isinstance(verification, dict) or set(verification) != {"before_publication", "after_publication"} or verification.get("before_publication") != prefix:
        raise RuntimeError("custody ledger tail-recovery receipt has invalid verification binding")
    if receipt["result"] == "PREPARED" and verification.get("after_publication") is not None:
        raise RuntimeError("prepared tail-recovery receipt claims post-publication verification")
    if receipt["result"] == "COMMITTED" and verification.get("after_publication") != prefix:
        raise RuntimeError("committed tail-recovery receipt lacks post-publication verification")
    if original["bytes"] != prefix["ledger_bytes"] + tail["bytes"] or receipt["archive"] != f".checkpoint-custody-ledger-torn-{original['sha256']}.jsonl":
        raise RuntimeError("custody ledger tail-recovery receipt has inconsistent byte accounting")
    return receipt


def _tail_recovery_refusal(path: Path) -> dict[str, object]:
    receipt, _ = _json_snapshot(path, label="custody ledger tail-recovery refusal")
    required = {"schema_version", "result", "reason", "subject", "archive", "original", "candidate_prefix", "tail"}
    if set(receipt) != required or receipt.get("schema_version") != _TAIL_RECOVERY_REFUSAL_SCHEMA or receipt.get("result") != "REFUSED" or receipt.get("reason") not in {"NO_VALID_PREFIX", "PREFIX_INVALID"}:
        raise RuntimeError("custody ledger tail-recovery refusal has invalid shape")
    for name in ("original", "candidate_prefix", "tail"):
        binding = receipt.get(name)
        if not isinstance(binding, dict) or set(binding) != {"sha256", "bytes"} or not _is_sha256(binding.get("sha256")) or type(binding.get("bytes")) is not int or binding["bytes"] < 0:
            raise RuntimeError("custody ledger tail-recovery refusal has invalid byte binding")
    if not isinstance(receipt.get("subject"), str) or not receipt["subject"] or receipt.get("archive") != f".checkpoint-custody-ledger-torn-{receipt['original']['sha256']}.jsonl":
        raise RuntimeError("custody ledger tail-recovery refusal has invalid identity")
    if receipt["original"]["bytes"] != receipt["candidate_prefix"]["bytes"] + receipt["tail"]["bytes"]:
        raise RuntimeError("custody ledger tail-recovery refusal has inconsistent byte accounting")
    return receipt


def _read_bound_tail_archive(canonical_parent: Path, receipt: Mapping[str, object]) -> bytes:
    archive = canonical_parent / str(receipt["archive"])
    try:
        payload = archive.read_bytes()
    except OSError as error:
        raise RuntimeError("custody ledger tail-recovery archive is unavailable") from error
    if _raw_byte_binding(payload) != receipt["original"]:
        raise RuntimeError("custody ledger tail-recovery archive changed after preservation")
    return payload


def _persist_torn_ledger_archive(canonical_parent: Path, original: bytes) -> str:
    digest = hashlib.sha256(original).hexdigest()
    name = f".checkpoint-custody-ledger-torn-{digest}.jsonl"
    archive = canonical_parent / name
    try:
        atomic_create_durable(archive, original)
    except FileExistsError:
        try:
            if archive.read_bytes() != original:
                raise RuntimeError("custody ledger tail-recovery archive collision")
        except OSError as error:
            raise RuntimeError("custody ledger tail-recovery archive could not be rechecked") from error
    if archive.read_bytes() != original:
        raise RuntimeError("custody ledger tail-recovery archive changed after durable creation")
    return name


def _finalize_tail_recovery_locked(canonical_parent: Path, *, receipt_path: Path) -> dict[str, object]:
    receipt = _tail_recovery_receipt(receipt_path)
    if receipt["subject"] != _custody_path_subject(canonical_parent):
        raise RuntimeError("custody ledger tail-recovery receipt subject does not match canonical parent")
    original = _read_bound_tail_archive(canonical_parent, receipt)
    prefix_bytes = original[: int(receipt["prefix"]["ledger_bytes"])]
    tail_bytes = original[int(receipt["prefix"]["ledger_bytes"]) :]
    if _ledger_binding(prefix_bytes) != receipt["prefix"] or _raw_byte_binding(tail_bytes) != receipt["tail"]:
        raise RuntimeError("custody ledger tail-recovery archive does not reproduce bound prefix and tail")
    ledger = canonical_parent / _CUSTODY_LEDGER
    try:
        current = ledger.read_bytes()
    except OSError as error:
        raise RuntimeError("custody deletion ledger could not be read during recovery") from error
    if receipt["result"] == "COMMITTED":
        if _ledger_binding(current) != receipt["prefix"]:
            raise RuntimeError("committed custody ledger tail recovery no longer matches the published prefix")
        return receipt
    if _raw_byte_binding(current) == receipt["original"]:
        _atomic_bytes(ledger, prefix_bytes)
    elif _ledger_binding(current) != receipt["prefix"]:
        raise RuntimeError("custody ledger tail recovery refuses bytes outside its original/prefix transaction")
    try:
        published = ledger.read_bytes()
    except OSError as error:
        raise RuntimeError("recovered custody ledger could not be replayed") from error
    after = _ledger_binding(published)
    if after != receipt["prefix"]:
        raise RuntimeError("recovered custody ledger failed post-publication replay")
    committed = {**receipt, "result": "COMMITTED", "verification": {"before_publication": receipt["prefix"], "after_publication": after}}
    _atomic_json(receipt_path, committed)
    return _tail_recovery_receipt(receipt_path)


def _raise_persisted_tail_refusal(canonical_parent: Path, receipt: Mapping[str, object]) -> None:
    if receipt["subject"] != _custody_path_subject(canonical_parent):
        raise RuntimeError("custody ledger tail-recovery refusal subject does not match canonical parent")
    original = _read_bound_tail_archive(canonical_parent, receipt)
    candidate_bytes = int(receipt["candidate_prefix"]["bytes"])
    if _raw_byte_binding(original[:candidate_bytes]) != receipt["candidate_prefix"] or _raw_byte_binding(original[candidate_bytes:]) != receipt["tail"]:
        raise RuntimeError("custody ledger tail-recovery refusal does not reproduce its candidate prefix and tail")
    ledger = canonical_parent / _CUSTODY_LEDGER
    try:
        current = ledger.read_bytes()
    except OSError as error:
        raise RuntimeError("custody deletion ledger could not be read during refused recovery") from error
    if current != original:
        raise RuntimeError("refused custody ledger tail recovery no longer matches preserved original")
    raise RuntimeError(f"custody ledger tail recovery refused: {receipt['reason']}")


def recover_torn_custody_ledger_tail(parent: Path, *, transaction_receipt_path: Path) -> dict[str, object]:
    """Archive and recover only a verified maximal newline-framed prefix under the writer lock."""

    with _custody_ledger_write_lock(parent) as canonical_parent:
        receipt_path = transaction_receipt_path.resolve()
        if receipt_path.is_relative_to(canonical_parent.resolve()):
            raise RuntimeError("tail-recovery transaction receipt must be outside custody root")
        if receipt_path.exists():
            persisted, _ = _json_snapshot(receipt_path, label="custody ledger recovery receipt")
            schema = persisted.get("schema_version")
            if schema == _HEAD_RECEIPT_SCHEMA:
                return _finalize_custody_ledger_transaction_locked(canonical_parent, receipt_path=receipt_path)
            if schema == _TAIL_RECOVERY_SCHEMA:
                return _finalize_tail_recovery_locked(canonical_parent, receipt_path=receipt_path)
            if schema == _TAIL_RECOVERY_REFUSAL_SCHEMA:
                _raise_persisted_tail_refusal(canonical_parent, _tail_recovery_refusal(receipt_path))
            raise RuntimeError("custody ledger recovery receipt has an unsupported schema")
        ledger = canonical_parent / _CUSTODY_LEDGER
        try:
            original = ledger.read_bytes()
        except OSError as error:
            raise RuntimeError("custody deletion ledger could not be read for offline recovery") from error
        prefix, tail = _split_torn_custody_ledger(original)
        archive_name = _persist_torn_ledger_archive(canonical_parent, original)
        reason: str | None = None
        try:
            if not prefix:
                reason = "NO_VALID_PREFIX"
                raise RuntimeError("custody deletion ledger has no valid frame prefix")
            prefix_binding = _ledger_binding(prefix)
        except RuntimeError as error:
            reason = reason or "PREFIX_INVALID"
            refusal = {
                "schema_version": _TAIL_RECOVERY_REFUSAL_SCHEMA,
                "result": "REFUSED",
                "reason": reason,
                "subject": _custody_path_subject(canonical_parent),
                "archive": archive_name,
                "original": _raw_byte_binding(original),
                "candidate_prefix": _raw_byte_binding(prefix),
                "tail": _raw_byte_binding(tail),
            }
            atomic_create_durable(receipt_path, (json.dumps(refusal, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
            raise RuntimeError(f"custody ledger tail recovery refused: {error}") from error
        prepared = {
            "schema_version": _TAIL_RECOVERY_SCHEMA,
            "result": "PREPARED",
            "subject": _custody_path_subject(canonical_parent),
            "archive": archive_name,
            "original": _raw_byte_binding(original),
            "prefix": prefix_binding,
            "tail": _raw_byte_binding(tail),
            "verification": {"before_publication": prefix_binding, "after_publication": None},
        }
        atomic_create_durable(receipt_path, (json.dumps(prepared, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
        return _finalize_tail_recovery_locked(canonical_parent, receipt_path=receipt_path)


def migrate_legacy_custody_ledger(parent: Path, *, transaction_receipt_path: Path | None = None) -> dict[str, object]:
    """Explicitly archive and replay a complete legacy ledger as chained v4 frames under one writer lock."""

    with _custody_ledger_write_lock(parent) as canonical_parent:
        _recover_parent_scoped_transactions_locked(canonical_parent)
        if transaction_receipt_path is None:
            transaction_receipt_path = canonical_parent.parent / f"custody-migration-{_custody_subject_token(canonical_parent)}.json"
        if transaction_receipt_path.resolve().is_relative_to(canonical_parent.resolve()):
            raise RuntimeError("migration transaction receipt must be outside custody root")
        prior, events = _custody_ledger_snapshot(canonical_parent)
        schemas = {event.get("schema_version") for event in events if isinstance(event, dict)}
        if schemas == {_CUSTODY_LEDGER_SCHEMA} and transaction_receipt_path.exists():
            transaction = _finalize_custody_ledger_transaction_locked(canonical_parent, receipt_path=transaction_receipt_path)
            if transaction["result"] != "COMMITTED":
                raise RuntimeError("migration transaction did not converge to committed v4 ledger")
            digest = str(transaction["old"]["ledger_sha256"])
            archive = canonical_parent / f".checkpoint-custody-ledger-legacy-{digest}.jsonl"
            if not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
                raise RuntimeError("migration replay lacks its durable legacy archive")
            receipt = {"schema_version": "ember-custody-ledger-migration-v2", "result": "MIGRATED", "legacy_archive": archive.name, "legacy_sha256": digest, "new_ledger_sha256": str(transaction["new"]["ledger_sha256"]), "chain_head_sha256": str(transaction["new"]["chain_head_sha256"]), "migrated_frame_count": int(transaction["new"]["frame_count"])}
            migration_receipt_path = transaction_receipt_path.with_name(f"{transaction_receipt_path.stem}-migration-{digest}.json")
            if migration_receipt_path.exists():
                existing, _ = _json_snapshot(migration_receipt_path, label="external migration receipt")
                if existing != receipt:
                    raise RuntimeError("migration receipt identity collision")
            else:
                _atomic_json(migration_receipt_path, receipt)
            return {**receipt, "migration_receipt": str(migration_receipt_path)}
        if not events or len(schemas) != 1 or schemas not in ({_ORDERED_CUSTODY_LEDGER_SCHEMA}, {_LEGACY_CUSTODY_LEDGER_SCHEMA}, {_PREVIOUS_CHAINED_LEDGER_SCHEMA}) or any(not isinstance(event, dict) for event in events):
            raise RuntimeError("legacy migration requires one complete v1 or v2 custody ledger")
        # Validate the exact snapshot before preservation/rewrite.  This uses the
        # same reconciliation authority as normal reads, while the writer lock
        # prevents a concurrent append from changing the source snapshot.
        _custody_reconciliation(canonical_parent)
        digest = hashlib.sha256(prior).hexdigest()
        archive = canonical_parent / f".checkpoint-custody-ledger-legacy-{digest}.jsonl"
        if archive.exists():
            if archive.read_bytes() != prior:
                raise RuntimeError("legacy custody archive collision has different bytes")
        else:
            # Shared write-through replacement is the only archive publication authority;
            # a raw xb create has no directory-durability guarantee on Windows.
            _atomic_bytes(archive, prior)
        replay: list[object] = []
        rewritten_rows: list[dict[str, object]] = []
        for legacy in events:
            assert isinstance(legacy, dict)
            legacy_events = ("PREPARED", "COMMITTED") if legacy["schema_version"] == _LEGACY_CUSTODY_LEDGER_SCHEMA else (legacy["event"],)
            for event_name in legacy_events:
                chained = _next_custody_ledger_frame({
                    "event": event_name, "pointer": legacy["pointer"], "bytes": legacy["bytes"],
                    "sha256": legacy["sha256"], "reason": legacy["reason"],
                }, replay)
                replay.append(chained)
                rewritten_rows.append(chained)
        rewritten = b"".join((json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8") for row in rewritten_rows)
        prepare_custody_ledger_transaction(receipt_path=transaction_receipt_path, old_ledger=prior, new_ledger=rewritten, operation_id=f"migration-{digest}", subject=_custody_path_subject(canonical_parent))
        _atomic_bytes(canonical_parent / _CUSTODY_LEDGER, rewritten)
        _finalize_custody_ledger_transaction_locked(canonical_parent, receipt_path=transaction_receipt_path)
        published, published_events = _custody_ledger_snapshot(canonical_parent)
        if published != rewritten:
            raise RuntimeError("migrated custody ledger changed after durable publication")
        _validate_custody_ledger_frame_chain(published_events)
        _custody_reconciliation(canonical_parent)
        receipt = {
            "schema_version": "ember-custody-ledger-migration-v2",
            "result": "MIGRATED",
            "legacy_archive": archive.name,
            "legacy_sha256": digest,
            "new_ledger_sha256": hashlib.sha256(published).hexdigest(),
            "chain_head_sha256": _custody_chain_head(published_events),
            "migrated_frame_count": len(rewritten_rows),
        }
        migration_receipt_path = transaction_receipt_path.with_name(f"{transaction_receipt_path.stem}-migration-{digest}.json")
        if migration_receipt_path.resolve().is_relative_to(canonical_parent.resolve()):
            raise RuntimeError("migration receipt must be outside custody root")
        if migration_receipt_path.exists():
            existing, _ = _json_snapshot(migration_receipt_path, label="external migration receipt")
            if existing != receipt:
                raise RuntimeError("migration receipt identity collision")
        else:
            _atomic_json(migration_receipt_path, receipt)
        return {**receipt, "migration_receipt": str(migration_receipt_path)}
def _append_custody_ledger_transition_locked(canonical_parent: Path, event: dict[str, object], *, transaction_receipt_path: Path, operation_id: str, subject: str, recovery_idempotent: bool = False) -> bool:
    """Validate one semantic custody transition under lock before minting external authority."""
    _custody_reconciliation(canonical_parent)
    prior, prior_events = _custody_ledger_snapshot(canonical_parent)
    pointer = _canonical_custody_deletion_pointer(event["pointer"])
    matching = [row for row in prior_events if isinstance(row, dict) and row.get("schema_version") == _CUSTODY_LEDGER_SCHEMA and row.get("pointer") == pointer]
    if event["event"] == "PREPARED":
        if matching:
            raise RuntimeError("custody ledger PREPARED transition already exists")
    elif event["event"] == "COMMITTED":
        if recovery_idempotent and len(matching) == 2:
            prepared, committed = matching
            if (
                prepared.get("event") == "PREPARED"
                and committed.get("event") == "COMMITTED"
                and all(row.get(key) == event.get(key) for row in (prepared, committed) for key in ("pointer", "bytes", "sha256", "reason"))
                and not _custody_deletion_path(canonical_parent, pointer).exists()
            ):
                return False
        if len(matching) != 1 or matching[0].get("event") != "PREPARED":
            raise RuntimeError("custody ledger COMMITTED requires exactly one prior PREPARED transition")
        prepared = matching[0]
        if any(prepared.get(key) != event.get(key) for key in ("pointer", "bytes", "sha256", "reason")):
            raise RuntimeError("custody ledger COMMITTED identity differs from its PREPARED transition")
        target = _custody_deletion_path(canonical_parent, pointer)
        if target.exists():
            raise RuntimeError("custody ledger COMMITTED requires the prepared victim to be absent")
    else:
        raise RuntimeError("custody ledger transition event is invalid")
    framed_event = _next_custody_ledger_frame(event, prior_events)
    new_ledger = prior + (json.dumps(framed_event, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    transaction = prepare_custody_ledger_transaction(receipt_path=transaction_receipt_path, old_ledger=prior, new_ledger=new_ledger, operation_id=operation_id, subject=subject)
    if transaction["result"] != "PREPARED":
        raise RuntimeError("ledger append requires a fresh nonterminal transaction operation ID")
    _atomic_bytes(canonical_parent / _CUSTODY_LEDGER, new_ledger)
    return True

def _append_custody_ledger_transition(parent: Path, event: dict[str, object], *, transaction_receipt_path: Path | None = None, operation_id: str | None = None, subject: str | None = None, recovery_idempotent: bool = False) -> None:
    """Durably replace only through an externally bound old/new transaction."""
    effective_operation_id = operation_id or f"append-{uuid.uuid4().hex}"
    with _custody_ledger_write_lock(parent) as canonical_parent:
        expected_subject = _custody_path_subject(canonical_parent)
        if subject is not None and subject != expected_subject:
            raise RuntimeError("append transaction subject does not match custody root")
        _recover_parent_scoped_transactions_locked(canonical_parent)
        if transaction_receipt_path is None:
            transaction_receipt_path = canonical_parent.parent / f"custody-append-{_custody_subject_token(canonical_parent)}-{effective_operation_id}.json"
        if transaction_receipt_path.resolve().is_relative_to(canonical_parent.resolve()):
            raise RuntimeError("append transaction receipt must be outside custody root")
        applied = _append_custody_ledger_transition_locked(canonical_parent, event, transaction_receipt_path=transaction_receipt_path, operation_id=effective_operation_id, subject=expected_subject, recovery_idempotent=recovery_idempotent)
        if not applied:
            return
        transaction = _head_transaction(transaction_receipt_path)
        current, _ = _custody_ledger_snapshot(canonical_parent)
        if _ledger_binding(current) != transaction["new"]:
            raise RuntimeError("ledger append changed before external transaction commit")
        _atomic_json(transaction_receipt_path, {**transaction, "result": "COMMITTED"})
def _custody_reconciliation(parent: Path) -> dict[str, object]:
    """Reconcile custody bytes with an ordered, fail-closed deletion ledger."""

    parent = parent.resolve()
    rows = _custody_file_rows(parent)
    totals = {"live": 0, "quarantine": 0, "evidence": 0, "other": 0}
    for row in rows:
        totals[str(row["bucket"])] += int(row["bytes"])
    ledger = parent / _CUSTODY_LEDGER
    transitions: dict[str, dict[str, object]] = {}
    legacy_deleted: dict[str, dict[str, object]] = {}
    if ledger.exists():
        _, events = _custody_ledger_snapshot(parent)
        _validate_custody_ledger_frame_chain(events)
        for event in events:
            if not isinstance(event, dict):
                raise RuntimeError("custody deletion ledger has an invalid schema")
            schema = event.get("schema_version")
            kind = event.get("event")
            raw_pointer = event.get("pointer")
            if schema not in {_CUSTODY_LEDGER_SCHEMA, _PREVIOUS_CHAINED_LEDGER_SCHEMA, _ORDERED_CUSTODY_LEDGER_SCHEMA, _LEGACY_CUSTODY_LEDGER_SCHEMA}:
                raise RuntimeError("custody deletion ledger has an invalid schema")
            try:
                pointer = _canonical_custody_deletion_pointer(raw_pointer)
            except ValueError as error:
                raise RuntimeError(str(error)) from error
            if type(event.get("bytes")) is not int or event["bytes"] < 0 or not _is_sha256(event.get("sha256")):
                raise RuntimeError("custody deletion ledger has invalid byte evidence")
            if not isinstance(event.get("reason"), str) or not event["reason"]:
                raise RuntimeError("custody deletion ledger lacks a deletion reason")
            identity = {
                "schema_version": schema,
                "pointer": pointer,
                "bytes": event["bytes"],
                "sha256": event["sha256"],
                "reason": event["reason"],
            }
            if schema == _LEGACY_CUSTODY_LEDGER_SCHEMA:
                if kind != "DELETED":
                    raise RuntimeError("legacy custody deletion ledger permits only DELETED")
                if pointer in transitions or pointer in legacy_deleted:
                    raise RuntimeError("custody deletion ledger has a duplicate legacy deletion")
                legacy_deleted[pointer] = identity
                continue
            if kind not in {"PREPARED", "COMMITTED"}:
                raise RuntimeError("custody deletion ledger has an invalid event")
            if pointer in legacy_deleted:
                raise RuntimeError("custody deletion ledger mixes legacy and ordered events")
            prior = transitions.get(pointer)
            if prior is None:
                if kind != "PREPARED":
                    raise RuntimeError("custody deletion ledger has COMMITTED without PREPARED")
                transitions[pointer] = {**identity, "state": "PREPARED"}
                continue
            if any(prior[field] != identity[field] for field in ("schema_version", "pointer", "bytes", "sha256", "reason")):
                raise RuntimeError("custody deletion ledger changes a prepared pointer identity")
            if prior["state"] != "PREPARED" or kind != "COMMITTED":
                raise RuntimeError("custody deletion ledger has a duplicate or reversed transition")
            prior["state"] = "COMMITTED"
    deleted_bytes = 0
    for pointer, record in transitions.items():
        deleted_path = _custody_deletion_path(parent, pointer)
        if deleted_path.exists():
            if record["state"] == "COMMITTED":
                raise RuntimeError("custody deletion ledger claims deletion while bytes still exist")
            continue
        # PREPARED+missing is an interruption-safe inferred deletion; count once.
        deleted_bytes += int(record["bytes"])
    for pointer, record in legacy_deleted.items():
        if _custody_deletion_path(parent, pointer).exists():
            raise RuntimeError("legacy custody deletion claims deletion while bytes still exist")
        deleted_bytes += int(record["bytes"])
    physical_bytes = sum(int(row["bytes"]) for row in rows)
    return {
        "schema_version": "ember-checkpoint-custody-reconciliation-v1",
        "live_bytes": totals["live"],
        "quarantine_bytes": totals["quarantine"],
        "evidence_bytes": totals["evidence"],
        "other_bytes": totals["other"],
        "physical_bytes": physical_bytes,
        "deleted_bytes": deleted_bytes,
        "reconciled_bytes": physical_bytes + deleted_bytes,
        "file_count": len(rows),
    }

def _receipt_valid_for_retention(bundle: Path) -> bool:
    try:
        require_counter_success_receipt(bundle)
    except (OSError, ValueError, TypeError):
        return False
    return True

_WRITER_LEASE = ".writer-lease.json"
_MAX_QUARANTINE_FILES = 32
_MAX_QUARANTINE_BYTES = 1024 * 1024
_CUSTODY_LEDGER = ".checkpoint-custody-deletion-ledger.jsonl"
_CUSTODY_LEDGER_LOCK = ".checkpoint-custody-deletion-ledger.lock"
_LEGACY_CUSTODY_LEDGER_SCHEMA = "ember-checkpoint-custody-deletion-v1"
_CUSTODY_LEDGER_SCHEMA = "ember-checkpoint-custody-deletion-v4"
_PREVIOUS_CHAINED_LEDGER_SCHEMA = "ember-checkpoint-custody-deletion-v3"
_ORDERED_CUSTODY_LEDGER_SCHEMA = "ember-checkpoint-custody-deletion-v2"
_LEDGER_THREAD_LOCKS: dict[str, threading.Lock] = {}
_LEDGER_THREAD_LOCKS_GUARD = threading.Lock()
_LEDGER_LOCK_WAIT_SECONDS = 30.0
_EVIDENCE_FILENAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*-[0-9a-f]{64}(?:-g[1-9][0-9]*)?\.json")
_WINDOWS_RESERVED_STEMS = {"aux", "clock$", "con", "nul", "prn", *(f"com{index}" for index in range(1, 10)), *(f"lpt{index}" for index in range(1, 10))}


def _pid_is_alive(pid: object) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if os.name == "nt":
        # ``os.kill(pid, 0)`` is not a harmless existence probe on Windows.
        # Query the process object without signalling it instead.
        import ctypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _staging_writer_pid(path: Path) -> int | None:
    if not path.name.startswith(".") or not path.name.endswith(".staging"):
        return None
    parts = path.name.rsplit(".", 3)
    if len(parts) != 4 or parts[-1] != "staging":
        return None
    try:
        pid = int(parts[-3])
    except ValueError:
        return None
    return pid if pid > 0 else None


def _writer_is_active(root: Path) -> bool:
    staging_pid = _staging_writer_pid(root)
    if staging_pid is not None:
        return _pid_is_alive(staging_pid)
    try:
        lease, _ = _json_snapshot(root / _WRITER_LEASE, label="writer lease")
    except (OSError, ValueError):
        return False
    return _pid_is_alive(lease.get("pid"))


def _recover_missing_prepared_evidence(parent: Path) -> None:
    """Finish verified PREPARED deletions via normal externally receipted append transactions."""
    commits: list[dict[str, object]] = []
    with _custody_ledger_write_lock(parent) as canonical_parent:
        ledger = canonical_parent / _CUSTODY_LEDGER
        if not ledger.exists():
            return
        _custody_reconciliation(canonical_parent)
        _, events = _custody_ledger_snapshot(canonical_parent)
        _validate_custody_ledger_frame_chain(events)
        terminal: dict[str, dict[str, object]] = {}
        for event in events:
            if event.get("schema_version") == _CUSTODY_LEDGER_SCHEMA:
                terminal[_canonical_custody_deletion_pointer(event.get("pointer"))] = event
        for pointer, event in terminal.items():
            if event.get("event") != "PREPARED":
                continue
            target = _custody_deletion_path(canonical_parent, pointer)
            try:
                target.stat()
            except FileNotFoundError:
                commits.append({"event": "COMMITTED", "pointer": pointer, "bytes": event["bytes"], "sha256": event["sha256"], "reason": event["reason"]})
            except OSError as error:
                raise RuntimeError("prepared evidence could not be inspected for recovery") from error
    for committed in commits:
        _append_custody_ledger_transition(parent, committed, recovery_idempotent=True)
    if commits:
        _custody_reconciliation(parent)
def _write_bounded_quarantine_evidence(parent: Path, name: str, payload: dict[str, object]) -> Path:
    evidence_dir = parent / ".checkpoint-quarantine"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    _recover_missing_prepared_evidence(parent)
    payload_bytes = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    digest = hashlib.sha256(payload_bytes).hexdigest()
    evidence_stem = _portable_evidence_stem(name)
    ledger = parent / _CUSTODY_LEDGER

    def matching_prepared_exists(deletion: dict[str, object]) -> bool:
        if not ledger.exists():
            return False
        prepared = False
        try:
            for event in _custody_ledger_snapshot(parent)[1]:
                if not isinstance(event, dict):
                    raise ValueError("custody deletion ledger has an invalid schema")
                if _canonical_custody_deletion_pointer(event.get("pointer")) != deletion["pointer"]:
                    continue
                identity = {key: event.get(key) for key in ("schema_version", "pointer", "bytes", "sha256", "reason")}
                expected = {key: deletion[key] for key in ("schema_version", "pointer", "bytes", "sha256", "reason")}
                if identity != expected:
                    raise ValueError("prepared evidence identity does not match the current victim")
                if event.get("event") != "PREPARED" or prepared:
                    raise ValueError("prepared evidence has an invalid prior transition")
                prepared = True
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            raise RuntimeError(str(error)) from error
        return prepared

    def ledger_events(pointer_path: Path) -> set[str]:
        if not ledger.exists():
            return set()
        try:
            pointer = _canonical_custody_deletion_pointer(pointer_path.relative_to(parent).as_posix())
            events: set[str] = set()
            for event in _custody_ledger_snapshot(parent)[1]:
                if not isinstance(event, dict):
                    raise ValueError("custody deletion ledger has an invalid schema")
                if _canonical_custody_deletion_pointer(event.get("pointer")) == pointer:
                    events.add(str(event.get("event")))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            raise RuntimeError("custody deletion ledger could not be inspected") from error
        return events

    terminal_events = {"PREPARED", "COMMITTED", "DELETED"}
    base_path = evidence_dir / f"{evidence_stem}-{digest}.json"
    evidence_path = base_path
    base_events = ledger_events(base_path)
    if base_path.exists():
        if base_events & terminal_events:
            raise RuntimeError("historical quarantine evidence pointer reappeared")
        if base_path.read_bytes() != payload_bytes:
            raise RuntimeError("quarantine evidence collision is not content-addressed")
    elif base_events & terminal_events:
        generation = 1
        while True:
            candidate = evidence_dir / f"{evidence_stem}-{digest}-g{generation}.json"
            candidate_events = ledger_events(candidate)
            if candidate.exists():
                if candidate_events & terminal_events:
                    raise RuntimeError("historical quarantine evidence pointer reappeared")
                if candidate.read_bytes() != payload_bytes:
                    raise RuntimeError("quarantine evidence collision is not content-addressed")
                evidence_path = candidate
                break
            if candidate_events & terminal_events:
                generation += 1
                continue
            evidence_path = candidate
            break

    if not evidence_path.exists():
        try:
            with evidence_path.open("xb") as handle:
                handle.write(payload_bytes)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            if ledger_events(evidence_path) & terminal_events:
                raise RuntimeError("historical quarantine evidence pointer reappeared")
            if evidence_path.read_bytes() != payload_bytes:
                raise RuntimeError("quarantine evidence appeared with different bytes")
    def valid_evidence_files() -> list[Path]:
        files: list[Path] = []
        for path in evidence_dir.iterdir():
            # Preexisting foreign leaves are custody bytes, never retention victims.
            try:
                _quarantine_evidence_identity(parent, path)
            except ValueError:
                continue
            files.append(path)
        return files

    files = sorted(valid_evidence_files(), key=lambda path: (path.stat().st_mtime_ns, path.name))
    while len(files) > _MAX_QUARANTINE_FILES or sum(path.stat().st_size for path in files) > _MAX_QUARANTINE_BYTES:
        victim = next((path for path in files if path != evidence_path), None)
        if victim is None:
            break
        ledger = parent / _CUSTODY_LEDGER
        try:
            pointer, byte_count, digest, identity = _quarantine_evidence_identity(parent, victim)
        except ValueError as error:
            raise RuntimeError("bounded evidence victim is no longer a valid direct evidence leaf") from error
        deletion = {
            "schema_version": _CUSTODY_LEDGER_SCHEMA,
            "pointer": pointer,
            "bytes": byte_count,
            "sha256": digest,
            "reason": "bounded evidence retention",
        }
        recovering_prepared = matching_prepared_exists(deletion)
        if not recovering_prepared:
            prepared = {**deletion, "event": "PREPARED"}
            _append_custody_ledger_transition(parent, prepared)
        try:
            if _quarantine_evidence_identity(parent, victim) != (pointer, byte_count, digest, identity):
                raise RuntimeError("bounded evidence victim changed before unlink; bytes preserved")
            victim.unlink()
        except RuntimeError:
            raise
        except (OSError, ValueError) as error:
            raise RuntimeError("bounded evidence deletion did not commit; bytes preserved") from error
        committed = {**deletion, "event": "COMMITTED"}
        _append_custody_ledger_transition(parent, committed)
        files.remove(victim)
    return evidence_path


def _move_bundle_to_quarantine(bundle: Path, *, prefix: str = "candidate") -> Path:
    """Atomically preserve serialized bytes in the nonselectable quarantine namespace."""

    lexical = _lexical_nonreparse_directory(bundle)
    source = lexical.resolve(strict=True)
    if not source.is_dir():
        raise ValueError("checkpoint quarantine source must be a directory")
    quarantine = source.parent / ".checkpoint-quarantine"
    if quarantine.exists() and _custody_link_or_reparse(quarantine):
        raise ValueError("checkpoint quarantine target contains a link or reparse component")
    quarantine.mkdir(parents=True, exist_ok=True)
    if _custody_link_or_reparse(quarantine):
        raise ValueError("checkpoint quarantine target contains a link or reparse component")
    candidate = quarantine / f"{prefix}-{source.name}-{uuid.uuid4().hex[:16]}"
    _atomic_publish_no_replace(source, candidate)
    return candidate


def _quarantine_unverified_bundle(bundle: Path, *, reason: str) -> None:
    """Preserve an unselectable checkpoint for rejudging; only bounded JSON is prunable."""

    if not bundle.is_dir() or not bundle.name.startswith("checkpoint-"):
        raise ValueError("retention quarantine requires a checkpoint-* directory")
    manifest = bundle / "checkpoint-manifest.json"
    try:
        manifest_sha256 = _sha256(manifest) if manifest.is_file() else None
    except OSError as error:
        manifest_sha256 = None
        reason = f"{reason}; manifest_hash_error={type(error).__name__}"
    candidate = _move_bundle_to_quarantine(bundle)
    evidence = {
        "schema_version": "ember-checkpoint-quarantine-v1",
        "result": "UNSELECTABLE",
        "source_bundle": bundle.name,
        "quarantine_candidate": candidate.name,
        "reason": reason[:512],
        "manifest_sha256": manifest_sha256,
        "bulk_candidate_cleanup": "moved_to_quarantine",
    }
    _write_bounded_quarantine_evidence(candidate.parent.parent, bundle.name, evidence)


def _reclaim_stale_staging(parent: Path) -> None:
    for staging in list(parent.glob(".*.staging")):
        if not staging.is_dir() or _writer_is_active(staging):
            continue
        manifest = staging / "checkpoint-manifest.json"
        try:
            manifest_sha256 = _sha256(manifest) if manifest.is_file() else None
        except OSError:
            manifest_sha256 = None
        evidence_name = f"staging-{hashlib.sha256(staging.name.encode()).hexdigest()[:16]}"
        candidate = _move_bundle_to_quarantine(staging, prefix="candidate")
        _write_bounded_quarantine_evidence(parent, evidence_name, {
            "schema_version": "ember-staging-failure-v1",
            "result": "UNSELECTABLE",
            "source_bundle": staging.name,
            "quarantine_candidate": candidate.name,
            "manifest_sha256": manifest_sha256,
            "bulk_candidate_cleanup": "moved_to_quarantine",
        })


def _reclaim_unverified_orphans(parent: Path) -> None:
    for candidate in list(parent.iterdir()):
        if not candidate.is_dir() or not candidate.name.startswith("checkpoint-") or _writer_is_active(candidate):
            continue
        try:
            require_counter_success_receipt(candidate)
        except (OSError, ValueError, TypeError) as error:
            _quarantine_unverified_bundle(
                candidate,
                reason=f"counter receipt invalid: {type(error).__name__}: {error}",
            )
def _enforce_retention(
    parent: Path,
    *,
    max_count: int | None = None,
    max_serialized_bytes: int | None = None,
    max_quarantine_serialized_bytes: int | None = None,
    receipt_aware: bool = False,
) -> dict[str, object]:
    """Prune only older successful bundles; never delete the final known-good bundle."""
    if max_count is None and max_serialized_bytes is None:
        raise ValueError("checkpoint retention requires a count or serialized-byte budget")
    if max_count is not None and max_count < 1:
        raise ValueError("checkpoint retention count must retain at least one bundle")
    if max_serialized_bytes is not None and max_serialized_bytes < 1:
        raise ValueError("checkpoint retention serialized-byte budget must be positive")
    if max_quarantine_serialized_bytes is not None and max_quarantine_serialized_bytes < 1:
        raise ValueError("checkpoint quarantine serialized-byte budget must be positive")
    parent.mkdir(parents=True, exist_ok=True)
    if receipt_aware:
        _reclaim_stale_staging(parent)
    candidates = [path for path in parent.iterdir() if path.is_dir() and path.name.startswith("checkpoint-")]
    bundles: list[Path] = []
    for candidate in candidates:
        if not receipt_aware:
            bundles.append(candidate)
            continue
        if _writer_is_active(candidate):
            continue
        try:
            require_counter_success_receipt(candidate)
        except (OSError, ValueError, TypeError) as error:
            _quarantine_unverified_bundle(candidate, reason=f"counter receipt invalid: {type(error).__name__}: {error}")
        else:
            bundles.append(candidate)
    bundles.sort(key=lambda path: (path.stat().st_mtime_ns, path.name))
    if max_count is not None and len(bundles) > max_count:
        raise RuntimeError("selectable checkpoint count cannot be reduced without evidence-qualified deletion")
    reconciliation = _custody_reconciliation(parent)

    def accounting() -> tuple[int, int]:
        quarantine_bytes = int(reconciliation["quarantine_bytes"])
        live_charged_bytes = int(reconciliation["reconciled_bytes"]) - quarantine_bytes
        if max_quarantine_serialized_bytes is not None and quarantine_bytes > max_quarantine_serialized_bytes:
            raise RuntimeError(
                "separate quarantine byte budget exceeded: "
                f"observed={quarantine_bytes} budget={max_quarantine_serialized_bytes}; evidence preserved"
            )
        return live_charged_bytes, quarantine_bytes

    live_charged_bytes, quarantine_bytes = accounting()
    if max_serialized_bytes is not None:
        while live_charged_bytes > max_serialized_bytes and len(bundles) > 1:
            _move_bundle_to_quarantine(bundles.pop(0))
            reconciliation = _custody_reconciliation(parent)
            live_charged_bytes, quarantine_bytes = accounting()
        if live_charged_bytes > max_serialized_bytes:
            raise RuntimeError("live checkpoint custody exceeds serialized-byte retention budget")
    return {
        "schema_version": "ember-checkpoint-retention-accounting-v1",
        "live_budget_bytes": max_serialized_bytes,
        "live_charged_bytes": live_charged_bytes,
        "quarantine_budget_bytes": max_quarantine_serialized_bytes,
        "quarantine_charged_bytes": quarantine_bytes,
    }


def _retain_after_success(
    parent: Path, *, operation: Callable[[], Any], max_count: int | None = None, max_serialized_bytes: int | None = None,
    max_quarantine_serialized_bytes: int | None = None, receipt_aware: bool = False
) -> Any:
    """Publish first, then prune only successful older bundles."""

    if max_count is None and max_serialized_bytes is None:
        raise ValueError("successful checkpoint retention requires a bound")
    parent.mkdir(parents=True, exist_ok=True)
    if receipt_aware:
        _reclaim_stale_staging(parent)
        _reclaim_unverified_orphans(parent)
    result = operation()
    try:
        retention = _enforce_retention(
            parent,
            max_count=max_count,
            max_serialized_bytes=max_serialized_bytes,
            max_quarantine_serialized_bytes=max_quarantine_serialized_bytes,
            receipt_aware=receipt_aware,
        )
    except Exception as error:
        published_checkpoint_id = (
            result[0].get("published_checkpoint_id")
            if isinstance(result, tuple) and result and isinstance(result[0], Mapping)
            else None
        )
        if not isinstance(published_checkpoint_id, str):
            raise
        try:
            published_error = PublishedHousekeepingError(
                published_checkpoint_id=published_checkpoint_id, cause=error,
            )
        except ValueError:
            raise error
        raise published_error from error
    if isinstance(result, tuple) and result and isinstance(result[0], Mapping):
        return ({**result[0], "retention_accounting": retention}, *result[1:])
    return result


def load_verified_specialist_records(
    *, root: Path, data_manifest: Path, tokenizer_path: Path, capability: str,
) -> tuple[list[dict[str, object]], dict[str, object], bytes]:
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
        # -B: the child's sys.path leads with the in-tree tools directory, and -I
        # drops the parent's PYTHONDONTWRITEBYTECODE, so without it every governed
        # run compiles __pycache__ into the certified tree and reds the next census.
        [sys.executable, "-I", "-B", "-c", "import runpy,sys;sys.path[:0]=[sys.argv[1],sys.argv[2]];sys.argv=sys.argv[3:];runpy.run_path(sys.argv[0],run_name=\"__main__\")", str(verifier.parent.resolve()), str(Path(tokenizers.__file__).resolve().parent.parent), str(verifier), "--data-manifest", str(manifest), "--tokenizer", str(tokenizer_path), "--capability", capability],
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
    semantic_hash = verification.get("semantic_model_contract_sha256")
    if verification.get("admission") != "ADMISSIBLE_SEMANTIC_CONTRACT" or not isinstance(semantic_hash, str) or len(semantic_hash) != 64 or semantic_hash.lower() != semantic_hash:
        raise RuntimeError("specialist data verifier did not bind an admissible semantic model contract")
    runtime_config_path = root / "configs" / "ember-restart-3b.json"
    try:
        runtime_semantic_hash = semantic_model_contract_sha256(
            json.loads(runtime_config_path.read_bytes())
        )
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise RuntimeError("runtime model config cannot establish its semantic contract") from error
    if semantic_hash != runtime_semantic_hash:
        raise RuntimeError("specialist data semantic contract does not match the runtime model contract")
    verification["runtime_semantic_model_contract_sha256"] = runtime_semantic_hash
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
    return records, verification, records_bytes

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
    from input_identity import InputIdentityError, read_admitted_shard_bytes
    try:
        shard_bytes = read_admitted_shard_bytes(packet, repo_root=root)
    except InputIdentityError as error:
        raise RuntimeError(f"production shard changed after admission: {error}") from error
    if input_receipt.get("input_artifact_sha256") != identity.get("sha256"):
        raise RuntimeError("accepted launch receipt does not bind the consumed input hash")
    try:
        payload = json.loads(shard_bytes)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("admitted production shard is unreadable JSON") from error
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
        atomic_replace_durable(temporary, path)
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
    validated = validate_realization_receipt(receipt)
    architecture = manifest.get("architecture")
    expected = {
        "model_config_sha256": manifest.get("model_config_sha256"),
        "subject_checkpoint_sha256": manifest_sha256,
        "architecture_revision": manifest.get("architecture_revision"),
        "counter_sha256": _sha256(Path(__file__).with_name("parameter_counter.py")),
        "active_expert_ids": manifest.get("active_expert_ids"),
        "expert_genesis_sha256": manifest.get("expert_genesis_sha256"),
        "expert_parameter_sha256": manifest.get("expert_parameter_sha256"),
    }
    if not isinstance(architecture, dict):
        raise ValueError("counter-success receipt does not reproduce checkpoint capacity")
    expected.update({field: architecture.get(field) for field in _COUNTER_COUNT_FIELDS})
    if any(validated.get(field) != value for field, value in expected.items()):
        raise ValueError("counter-success receipt does not bind this checkpoint realization")
    return validated


def _quarantine_counter_failed_checkpoint(checkpoint_target: Path, error: BaseException) -> Path | None:
    """Preserve a counter-failed candidate as durable, nonselectable raw bytes."""

    if not checkpoint_target.exists():
        return None
    manifest_path = checkpoint_target / "checkpoint-manifest.json"
    manifest_sha256: str | None = None
    try:
        if manifest_path.is_file():
            manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    except OSError:
        manifest_sha256 = None
    candidate = _move_bundle_to_quarantine(checkpoint_target, prefix="candidate")
    evidence = _write_bounded_quarantine_evidence(
        candidate.parent.parent,
        f"counter-failed-{checkpoint_target.name}-{candidate.name.rsplit('-', 1)[-1]}",
        {
            "schema_version": "ember-counter-failure-v1",
            "result": "COUNTER_FAILED",
            "source_bundle": checkpoint_target.name,
            "quarantine_candidate": candidate.name,
            "checkpoint_manifest_sha256": manifest_sha256,
            "error_type": type(error).__name__,
            "error": str(error)[:512],
            "bulk_candidate_cleanup": "moved_to_quarantine",
        },
    )
    return evidence


def authorize_production_resume_checkpoint(
    candidate: Path,
    *,
    counter_success_receipt: Path | None = None,
    realization_registry: Path | None = None,
    optimizer_transition_registry: Path | None = None,
    optimizer_transition_registry_sha256: str | None = None,
    c_relocated_under_disk_budget_runner: bool = False,
    relocation_custody_root: Path | None = None,
) -> tuple[Path, dict[str, object]]:
    """Authorize a resume and disclose the exact verifier trust path used."""

    lexical = Path(candidate)
    resolved = lexical.resolve()
    _reject_quarantined_checkpoint_path(lexical, resolved)
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
    authorities = (counter_success_receipt, realization_registry, optimizer_transition_registry)
    if sum(value is not None for value in authorities) > 1:
        raise ValueError("resume authority inputs are mutually exclusive")
    if optimizer_transition_registry is not None:
        if optimizer_transition_registry_sha256 is None:
            raise ValueError("optimizer transition requires an expected registry SHA-256")
        if (
            len(optimizer_transition_registry_sha256) != 64
            or any(character not in "0123456789abcdef" for character in optimizer_transition_registry_sha256)
        ):
            raise ValueError("expected optimizer transition registry SHA-256 is invalid")
        actual_registry_sha256 = _sha256(optimizer_transition_registry.resolve())
        if actual_registry_sha256 != optimizer_transition_registry_sha256:
            raise ValueError("optimizer transition registry SHA-256 mismatch")
        current_model_config = Path(__file__).resolve().parents[2] / "configs" / "ember-restart-3b.json"
        transition = validate_optimizer_transition_registry(
            optimizer_transition_registry.resolve(),
            checkpoint_root=resolved,
            current_target_config_path=current_model_config,
        )
        authority = {
            "schema_version": "ember-resume-authority-v1",
            "mode": "MODEL_ONLY_OPTIMIZER_CONTRACT_TRANSITION",
            "checkpoint_manifest_sha256": transition["source"]["checkpoint_manifest_sha256"],
            "transition_registry_sha256": transition["registry_sha256"],
            "transition_receipt_sha256": transition["receipt_sha256"],
            "source_semantic_model_contract_sha256": transition["source"]["semantic_model_contract_sha256"],
            "target_model_config_sha256": transition["target"]["model_config_sha256"],
            "target_semantic_model_contract_sha256": transition["target"]["semantic_model_contract_sha256"],
            "model_state_reused": True,
            "optimizer_state_reused": False,
        }
        if authority["transition_registry_sha256"] != optimizer_transition_registry_sha256:
            raise ValueError("optimizer transition validator registry SHA-256 mismatch")
    elif optimizer_transition_registry_sha256 is not None:
        raise ValueError("expected optimizer transition registry SHA-256 requires its registry path")
    elif realization_registry is not None:
        current_model_config = Path(__file__).resolve().parents[2] / "configs" / "ember-restart-3b.json"
        receipt = validate_step2_realization_registry_bundle(
            realization_registry.resolve(),
            (resolved / "checkpoint-manifest.json").resolve(),
            current_model_config,
        )
        authority = {
            "schema_version": "ember-resume-authority-v1",
            "mode": "TRUSTED_HISTORICAL_REALIZATION_REGISTRY",
            "checkpoint_manifest_sha256": _sha256(resolved / "checkpoint-manifest.json"),
            "registry_sha256": _sha256(realization_registry.resolve()),
            "counter_sha256": receipt["counter_sha256"],
            "receipt_sha256": receipt["receipt_sha256"],
            "historical_model_config_sha256": receipt["historical_model_config_sha256"],
            "current_model_config_sha256": receipt["current_model_config_sha256"],
            "semantic_model_contract_sha256": receipt["semantic_model_contract_sha256"],
        }
    else:
        receipt = require_counter_success_receipt(resolved, receipt_path=counter_success_receipt)
        receipt_source = (counter_success_receipt if counter_success_receipt is not None else resolved / _COUNTER_SUCCESS_RECEIPT).resolve()
        authority = {
            "schema_version": "ember-resume-authority-v1",
            "mode": "CURRENT_COUNTER_SUCCESS_RECEIPT",
            "checkpoint_manifest_sha256": _sha256(resolved / "checkpoint-manifest.json"),
            "counter_sha256": receipt["counter_sha256"],
            "receipt_sha256": _sha256(receipt_source),
        }
    return resolved, authority


def production_resume_checkpoint(
    candidate: Path,
    *,
    counter_success_receipt: Path | None = None,
    realization_registry: Path | None = None,
    optimizer_transition_registry: Path | None = None,
    optimizer_transition_registry_sha256: str | None = None,
    c_relocated_under_disk_budget_runner: bool = False,
    relocation_custody_root: Path | None = None,
) -> Path:
    """Backward-compatible path-only wrapper around disclosed resume authority."""

    resolved, _authority = authorize_production_resume_checkpoint(
        candidate,
        counter_success_receipt=counter_success_receipt,
        realization_registry=realization_registry,
        optimizer_transition_registry=optimizer_transition_registry,
        optimizer_transition_registry_sha256=optimizer_transition_registry_sha256,
        c_relocated_under_disk_budget_runner=c_relocated_under_disk_budget_runner,
        relocation_custody_root=relocation_custody_root,
    )
    return resolved


def restore_authorized_checkpoint(
    model: UnifiedDecoder,
    optimizer: torch.optim.Optimizer,
    checkpoint: Path,
    receipt: Mapping[str, Any],
    authority: Mapping[str, Any],
) -> dict[str, Any]:
    """Restore model/replay state while enforcing explicit optimizer-state disposition."""

    expected_manifest_sha256 = authority.get("checkpoint_manifest_sha256")
    actual_manifest_sha256 = receipt.get("checkpoint_manifest_sha256")
    if not _is_sha256(expected_manifest_sha256) or not _is_sha256(actual_manifest_sha256) or expected_manifest_sha256 != actual_manifest_sha256:
        raise ValueError("resume authority checkpoint manifest SHA-256 mismatch")

    if authority.get("mode") == "MODEL_ONLY_OPTIMIZER_CONTRACT_TRANSITION":
        return load_checkpoint_model_only_transition(model, checkpoint, receipt)
    return load_checkpoint_artifacts(model, optimizer, checkpoint, receipt)

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


def checkpoint_quarantine_budget_bytes(config_path: Path) -> int:
    """Use the authorized ceiling independently for preserved quarantine custody."""

    return checkpoint_retention_budget_bytes(config_path)

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


def load_training_acceleration_policy() -> Stage1Policy:
    """Load the closed issue #1413 Stage 1 policy before any model allocation."""

    return stage1_policy()


def validate_signature_census_request(
    output: Path | None, source_commit: str | None,
) -> tuple[Path | None, str | None]:
    """Close and preflight the observation-only census request before allocation."""

    if (output is None) != (source_commit is None):
        raise ValueError("training signature census output and source commit are required together")
    if output is None:
        return None, None
    if re.fullmatch(r"[0-9a-f]{40}", str(source_commit)) is None:
        raise ValueError("training signature census source commit must be lowercase 40hex")
    resolved = output.resolve()
    if resolved.exists():
        raise FileExistsError(f"refusing to overwrite training signature census: {resolved}")
    return resolved, str(source_commit)


def validate_stage2_activation_request(
    *,
    enabled: bool,
    diagnostic_bf16_down: bool = False,
    diagnostic_eager_workspace: bool = False,
    diagnostic_pre_optimizer_sync: bool = False,
    artifact_root: Path,
    receipt_output: Path | None,
    signature_census_output: Path | None,
    resume_checkpoint: Path | None,
) -> Path | None:
    """Close the final #1413 activation boundary before model allocation."""

    if (
        type(enabled) is not bool
        or type(diagnostic_bf16_down) is not bool
        or type(diagnostic_eager_workspace) is not bool
        or type(diagnostic_pre_optimizer_sync) is not bool
    ):
        raise ValueError("Stage-2 activation and diagnostic flags must be boolean")
    if sum((enabled, diagnostic_bf16_down, diagnostic_eager_workspace)) > 1:
        raise ValueError("Stage-2 production and graph-only diagnostic modes are mutually exclusive")
    if diagnostic_pre_optimizer_sync and not diagnostic_bf16_down:
        raise ValueError("Stage-2 pre-optimizer sync requires graph-only diagnostic mode")
    active_mode = enabled or diagnostic_bf16_down or diagnostic_eager_workspace
    if active_mode and signature_census_output is not None:
        raise ValueError("Stage-2 activation cannot mint its own census authority")
    if receipt_output is not None and resume_checkpoint is not None:
        raise ValueError("Stage-2 matched A/B does not admit resume ambiguity")
    if active_mode and receipt_output is None:
        raise ValueError("Stage-2 activation requires an arm receipt output")
    if receipt_output is None:
        return None
    resolved = receipt_output.resolve()
    if not resolved.is_relative_to(artifact_root.resolve()):
        raise ValueError("Stage-2 arm receipt output escapes governed custody")
    if resolved.exists():
        raise FileExistsError(f"refusing to overwrite Stage-2 arm receipt: {resolved}")
    return resolved

def load_optimizer_contract(config_path: Path) -> dict[str, object]:
    """Load the one structured optimizer declaration used by config, runtime, and checkpoint."""

    try:
        contract = json.loads(config_path.read_text(encoding="utf-8"))["training"]["optimizer"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("production contract must declare a structured optimizer") from error
    return validate_optimizer_contract(contract)


def validate_optimizer_contract(contract: object) -> dict[str, object]:
    """Validate an optimizer object taken from an already verified config snapshot."""

    if not isinstance(contract, dict) or set(contract) != {"name", "implementation", "placement", "hyperparameters", "state_format"}:
        raise ValueError("production optimizer contract has an invalid shape")
    expected = {
        "name": "device_resident_8bit_adamw",
        "implementation": "bitsandbytes.optim.AdamW8bit",
        "placement": "cuda_non_paged",
        "state_format": "bitsandbytes-device-resident-8bit-adamw-state-dict-v1",
    }
    if any(contract.get(field) != value for field, value in expected.items()):
        raise ValueError("production optimizer contract does not declare canonical device-resident AdamW8bit")
    hyperparameters = contract.get("hyperparameters")
    if not isinstance(hyperparameters, dict) or set(hyperparameters) != {"learning_rate", "weight_decay", "percentile_clipping", "block_wise"}:
        raise ValueError("production optimizer hyperparameters have an invalid shape")
    if (not isinstance(hyperparameters["learning_rate"], (int, float)) or hyperparameters["learning_rate"] <= 0 or not isinstance(hyperparameters["weight_decay"], (int, float)) or hyperparameters["weight_decay"] < 0 or not isinstance(hyperparameters["percentile_clipping"], int) or hyperparameters["percentile_clipping"] <= 0 or not isinstance(hyperparameters["block_wise"], bool)):
        raise ValueError("production optimizer hyperparameters are invalid")
    return dict(contract)

def _rng_state(device: torch.device) -> dict[str, torch.Tensor]:
    return {"cpu": torch.get_rng_state().clone(), "cuda": torch.cuda.get_rng_state(device).clone()}


def _rng_state_hash(device: torch.device) -> dict[str, str]:
    return {
        name: hashlib.sha256(state.cpu().numpy().tobytes()).hexdigest()
        for name, state in _rng_state(device).items()
    }

def _counter_expected_counts(model: UnifiedDecoder) -> dict[str, object]:
    """Capture counter expectations at publication, after the routed expert is selected."""
    return measure_parameter_counts(model)


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
        # -B: -I also drops PYTHONDONTWRITEBYTECODE, and counter_path is in-tree.
        "-B",
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
    """Build exactly the structured device-resident AdamW8bit declared by config."""

    if optimizer_contract.get("implementation") != "bitsandbytes.optim.AdamW8bit" or optimizer_contract.get("placement") != "cuda_non_paged":
        raise ValueError("production optimizer must declare cuda_non_paged device-resident AdamW8bit")
    hyperparameters = optimizer_contract.get("hyperparameters")
    if not isinstance(hyperparameters, dict):
        raise ValueError("production optimizer contract lacks hyperparameters")
    import bitsandbytes as bnb

    return bnb.optim.AdamW8bit(
        model.parameters(),
        lr=float(hyperparameters["learning_rate"]),
        weight_decay=float(hyperparameters["weight_decay"]),
        percentile_clipping=int(hyperparameters["percentile_clipping"]),
        block_wise=bool(hyperparameters["block_wise"]),
    )

def run(
    *, seed: int, artifact_root: Path, resume_checkpoint: Path | None = None, resume_counter_receipt: Path | None = None,
    resume_realization_registry: Path | None = None,
    resume_optimizer_transition_registry: Path | None = None,
    resume_optimizer_transition_registry_sha256: str | None = None,
    records_override: list[dict[str, object]] | None = None,
    scene_split_records: list[dict[str, object]] | None = None,
    full_records_artifact_bytes: bytes | None = None,
    specialist_verification: dict[str, object] | None = None,
    specialist_lineage: dict[str, object] | None = None,
    checkpoint_interval: int | None = None,
    write_budget_bytes: int | None = None,
    max_records: int | None = None,
    canonical_runner_authority: dict[str, object] | None = None,
    c_relocated_under_disk_budget_runner: bool = False,
    relocation_custody_root: Path | None = None,
    telemetry_path: Path | None = None,
    telemetry_run_id: str | None = None,
    model_chat_restore_not_before: str | None = None,
    signature_census_output: Path | None = None,
    signature_census_source_commit: str | None = None,
    stage2_acceleration: bool = False,
    stage2_diagnostic_bf16_down: bool = False,
    stage2_diagnostic_eager_workspace: bool = False,
    stage2_diagnostic_pre_optimizer_sync: bool = False,
    stage2_arm_receipt_output: Path | None = None,
) -> dict[str, object]:
    if records_override is not None and isinstance(specialist_verification, dict) and isinstance(specialist_lineage, dict) and specialist_verification.get("capability") == "image":
        selection = specialist_lineage.get("scene_split_selection")
        execution_slice = specialist_lineage.get("execution_slice")
        if not isinstance(selection, Mapping) or not isinstance(execution_slice, Mapping):
            raise ValueError("image specialist production run requires a separate scene split receipt")
        if not isinstance(scene_split_records, list):
            raise ValueError("image specialist production run requires the complete selected train records")
        validate_image_scene_split_execution(
            scene_split_records, verification=specialist_verification, selection=selection, execution_slice=execution_slice,
            full_records_artifact_bytes=full_records_artifact_bytes,
        )
        start, count = execution_slice.get("start_record"), execution_slice.get("record_count")
        if (type(start) is not int or type(count) is not int or start < 0 or count < 1
                or start + count > selection["selected_record_count"]
                or records_override != scene_split_records[start:start + count]
                or execution_slice.get("records_sha256") != specialist_execution_slice_receipt(records_override, source_start_record=start)["records_sha256"]
                or execution_slice.get("tokens_sha256") != specialist_execution_slice_receipt(records_override, source_start_record=start)["tokens_sha256"]):
            raise ValueError("image specialist execution slice does not resolve the selected train records")
    if type(seed) is not int or seed < 0:
        raise ValueError("launch seed must be a nonnegative integer")
    if max_records is not None and (type(max_records) is not int or max_records < 1 or max_records > 200):
        raise ValueError("vertical canary max_records must be an integer from 1 through 200")
    if records_override is not None and max_records is not None:
        raise ValueError("vertical canary max_records applies only to the full authorized shard route")
    telemetry_values = (telemetry_path, telemetry_run_id, model_chat_restore_not_before)
    if any(value is not None for value in telemetry_values) and not all(value is not None for value in telemetry_values):
        raise ValueError("training telemetry requires path, run id, and model-chat restore time together")
    if telemetry_run_id is not None and (not telemetry_run_id or len(telemetry_run_id) > 128):
        raise ValueError("training telemetry run id is invalid")
    signature_census_output, signature_census_source_commit = validate_signature_census_request(
        signature_census_output, signature_census_source_commit,
    )
    artifact_root = production_artifact_root(
        artifact_root,
        c_relocated_under_disk_budget_runner=c_relocated_under_disk_budget_runner,
        relocation_custody_root=relocation_custody_root,
    )
    stage2_arm_receipt_output = validate_stage2_activation_request(
        enabled=stage2_acceleration,
        diagnostic_bf16_down=stage2_diagnostic_bf16_down,
        diagnostic_eager_workspace=stage2_diagnostic_eager_workspace,
        diagnostic_pre_optimizer_sync=stage2_diagnostic_pre_optimizer_sync,
        artifact_root=artifact_root,
        receipt_output=stage2_arm_receipt_output,
        signature_census_output=signature_census_output,
        resume_checkpoint=resume_checkpoint,
    )
    if signature_census_output is not None and not signature_census_output.is_relative_to(artifact_root):
        raise ValueError("training signature census output must stay inside the governed artifact root")
    root = Path(__file__).resolve().parents[2]
    config_path = root / "configs" / "ember-restart-3b.json"
    if write_budget_bytes is not None:
        if type(write_budget_bytes) is not int or write_budget_bytes < 1:
            raise ValueError("vertical write budget must be a positive integer")
        # The episode's own bound, not the shared-only default: a governed-vertical
        # episode (specialist_lineage is None) always serializes full-coverage
        # optimizer state (mirrors governed_vertical_checkpoint_byte_bound), and a
        # specialist episode's true coverage is decided later by the live optimizer
        # (specialist_checkpoint_bound_active_parameters) -- the shared-plus-one-
        # expert bound computed here is that path's floor, which
        # specialist_publication_plan re-checks exactly once the live coverage is
        # known (#1324: the shared-only default under-counted by ~5.6 GB against
        # the governed-vertical full-coverage bound). This scope loads its own
        # config rather than hoisting the load above -- the config file need not
        # exist when write_budget_bytes is None, and the ordering below (this
        # check, then the integration-contract file check) is pinned by existing
        # coverage.
        early_config = RestartDecoderConfig.from_contract(config_path)
        early_total_parameters = early_config.structural_parameter_count()
        if specialist_lineage is None:
            early_active_parameters = early_total_parameters
        else:
            early_active_parameters = early_total_parameters - (
                (len(early_config.expert_names) - 1) * early_config.layers * 12 * early_config.hidden_size * early_config.hidden_size
            )
        if checkpoint_serialization_byte_bound(config_path, active_parameters=early_active_parameters) > write_budget_bytes:
            raise ValueError("vertical checkpoint publication bound exceeds the declared write budget")
    if canonical_runner_authority is not None:
        if type(write_budget_bytes) is not int:
            raise RuntimeError("vertical canonical runner authority requires an explicit write budget")
        expected_canonical_authority = {
            **canonical_disk_budget_runner_authority(),
            "config_sha256": _sha256(config_path),
            "runner_source_sha256": _sha256(Path(__file__).resolve()),
            "checkpoint_byte_bound": governed_vertical_checkpoint_byte_bound(config_path),
            "write_budget_bytes": write_budget_bytes,
        }
        if not isinstance(canonical_runner_authority, Mapping) or dict(canonical_runner_authority) != expected_canonical_authority:
            raise RuntimeError("vertical canonical runner authority does not match the live startup assertion")
    integration_contract_path = (
        root
        / "docs"
        / "domains"
        / "governance"
        / "ember-restart"
        / "integration-contract-v1.md"
    )
    if not integration_contract_path.is_file():
        raise RuntimeError("the merged Ember integration contract is required for production launch")
    load_training_acceleration_policy()
    config = RestartDecoderConfig.from_contract(config_path)
    memory_contract = load_memory_contract(config_path)
    governor_receipt = governed_resource_preflight()
    if canonical_runner_authority is not None:
        governor_receipt = {**governor_receipt, "canonical_disk_budget_runner": dict(canonical_runner_authority)}
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for the production vertical slice")
    episode_expert: str | None = None
    total_parameters = config.structural_parameter_count()
    active_parameters = total_parameters - (len(config.expert_names) - 1) * config.layers * 12 * config.hidden_size * config.hidden_size
    device_free_bytes, _device_total_bytes = torch.cuda.mem_get_info()
    memory_preflight = production_memory_preflight(
        total_parameters=total_parameters,
        active_parameters=active_parameters,
        device_free_bytes=int(device_free_bytes),
    )
    if telemetry_path is not None and telemetry_run_id is not None and model_chat_restore_not_before is not None:
        append_training_telemetry(telemetry_path, kind="run_status", payload={
            "run_id": telemetry_run_id,
            "phase": "ALLOCATING",
            "model_chat": "OFFLINE",
            "restore_not_before": model_chat_restore_not_before,
        })
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
        execution_slice = specialist_lineage.get("execution_slice")
        if not isinstance(execution_slice, dict) or not isinstance(execution_slice.get("records_sha256"), str):
            raise ValueError("specialist production run requires an execution-slice receipt")
        data_shard_id = (
            "VERIFIED_SPECIALIST:"
            + str(specialist_verification["data_manifest_sha256"])[:12]
            + ":SLICE:"
            + str(execution_slice["records_sha256"])[:12]
        )
        episode_expert = verified_specialist_episode_expert(records, specialist_verification)
    stage2_active = (
        stage2_acceleration or stage2_diagnostic_bf16_down
        or stage2_diagnostic_eager_workspace
    )
    stage2_authority = None
    if stage2_active:
        if records_override is not None:
            raise ValueError("Stage-2 matched A/B admits only the canonical full-route shard")
        census_path = root / _STAGE2_CENSUS_RELATIVE_PATH
        census = load_training_signature_census(census_path)
        # The integration receipt's code_commit advances at merge while its
        # admitted artifact/config/validator bytes stay immutable. Reconstruct
        # the exact receipt projection observed by the census, then separately
        # bind both comparison arms to the merged activation source above.
        census_input_receipt = {**input_receipt, "code_commit": _STAGE2_CENSUS_SOURCE_COMMIT}
        if (
            census["source_commit"] != _STAGE2_CENSUS_SOURCE_COMMIT
            or census["model_config_sha256"] != _sha256(config_path)
            or census["input_identity_sha256"] != _json_sha256(census_input_receipt)
        ):
            raise RuntimeError("Stage-2 census authority does not bind the matched arm identity")
        stage2_authority = load_stage2_activation_authority(
            census_path,
            expected_raw_sha256=_STAGE2_CENSUS_RAW_SHA256,
        )
    signature_census = None
    if signature_census_output is not None and signature_census_source_commit is not None:
        signature_census = TrainingSignatureCensus(
            source_commit=signature_census_source_commit,
            model_config_sha256=_sha256(config_path),
            input_identity_sha256=_json_sha256(input_receipt),
            runner_source_sha256=_sha256(Path(__file__).resolve()),
        )
    checkpoint_parent = artifact_root / "checkpoints"
    checkpoint_root = checkpoint_parent / f"checkpoint-vertical-slice-seed-{seed}"
    resume_authority: dict[str, object] | None = None
    resume_receipt: dict[str, object] | None = None
    if resume_checkpoint is not None:
        resume_checkpoint, resume_authority = authorize_production_resume_checkpoint(
            resume_checkpoint,
            counter_success_receipt=resume_counter_receipt,
            realization_registry=resume_realization_registry,
            optimizer_transition_registry=resume_optimizer_transition_registry,
            optimizer_transition_registry_sha256=resume_optimizer_transition_registry_sha256,
            c_relocated_under_disk_budget_runner=c_relocated_under_disk_budget_runner,
            relocation_custody_root=relocation_custody_root,
        )
        resume_receipt = published_checkpoint_receipt(resume_checkpoint)
    frozen_resume_cursor: dict[str, object] | None = None
    if resume_receipt is not None:
        candidate_cursor = resume_receipt.get("data_cursor")
        if not isinstance(candidate_cursor, Mapping):
            raise RuntimeError("authorized production resume requires a frozen data cursor")
        frozen_record_index = candidate_cursor.get("record_index")
        frozen_global_step = candidate_cursor.get("global_step")
        frozen_tokens_seen = candidate_cursor.get("tokens_seen")
        if any(type(value) is not int or value < 0 for value in (frozen_record_index, frozen_global_step, frozen_tokens_seen)):
            raise RuntimeError("authorized production resume has an invalid frozen cursor")
        if records_override is None:
            if frozen_record_index >= len(records):
                raise RuntimeError("production resume cursor has no remaining authorized records")
            if candidate_cursor.get("shard") != data_shard_id:
                raise RuntimeError("production resume cursor does not bind the admitted input shard")
            if candidate_cursor.get("input_identity_receipt_sha256") != _json_sha256(input_receipt):
                raise RuntimeError("production resume cursor does not bind the admitted input receipt")
        frozen_resume_cursor = dict(candidate_cursor)

    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    rng_state_before_init = _rng_state_hash(torch.device("cuda"))
    previous_dtype = torch.get_default_dtype()
    torch.set_default_dtype(torch.bfloat16)
    try:
        model = UnifiedDecoder(config, device="cuda", allow_production_allocation=True, genesis_seed=seed)
    finally:
        torch.set_default_dtype(previous_dtype)
    if episode_expert is not None:
        model._activate_expert(episode_expert)
    genesis_hashes = model.expert_bank_genesis_hashes()
    model.train()
    counts = measure_parameter_counts(model)
    if counts["unique_parameters"] != 3_839_161_856 or counts["active_parameters"] != 1_725_232_640:
        raise RuntimeError("instantiated sparse counts differ from the authorized architecture")
    optimizer_contract = load_optimizer_contract(config_path)
    optimizer = build_production_optimizer(model, optimizer_contract=optimizer_contract)
    stage2_executor = (
        CensusBoundStage2Executor(
            model=model,
            optimizer=optimizer,
            config=config,
            authority=stage2_authority,
            diagnostic_bf16_down=stage2_diagnostic_bf16_down,
            diagnostic_eager_workspace=stage2_diagnostic_eager_workspace,
            diagnostic_pre_optimizer_sync=stage2_diagnostic_pre_optimizer_sync,
        )
        if stage2_authority is not None
        else None
    )
    resume_cursor = {"record_index": 0, "global_step": 0, "tokens_seen": 0}
    if resume_checkpoint is not None:
        if resume_receipt is None or resume_authority is None:
            raise RuntimeError("authorized production resume requires a frozen checkpoint receipt")
        genesis_hashes = resume_expert_genesis(resume_receipt, requested_seed=seed)
        resume_cursor = restore_authorized_checkpoint(model, optimizer, resume_checkpoint, resume_receipt, resume_authority)["data_cursor"]
        if frozen_resume_cursor is not None and resume_cursor.get("record_index") != frozen_resume_cursor.get("record_index"):
            raise RuntimeError("restored production resume cursor differs from its frozen receipt")
        for group in optimizer.param_groups:
            group["lr"] = 1e-5
        if records_override is not None:
            resume_cursor = specialist_resume_cursor(resume_cursor, data_shard_id=data_shard_id)
        remaining_records = len(records) - int(resume_cursor["record_index"])
        if remaining_records < 1:
            raise RuntimeError("production resume cursor has no remaining authorized records")
        bounded_records = remaining_records if max_records is None else min(max_records, remaining_records)
        checkpoint_root = checkpoint_parent / (
            f"checkpoint-continue-seed-{seed}-from-step-"
            f"{int(resume_cursor['global_step']) + bounded_records}"
        )
    # The optimizer restored at resume decides the coverage this episode's
    # checkpoint bound must budget -- see specialist_checkpoint_bound_active_parameters
    # for the two closed admissible shapes (#1473, #1483, #1320).
    checkpoint_byte_bound = checkpoint_serialization_byte_bound(
        config_path,
        active_parameters=specialist_checkpoint_bound_active_parameters(
            specialist_lineage=specialist_lineage,
            optimizer_full_route_coverage=optimizer_covers_every_expert_route(
                model, optimizer
            ),
            active_parameters=active_parameters,
            total_parameters=total_parameters,
        ),
    )
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
    published_specialist_records = 0
    low_commit_deferral_state = {"count": 0}
    last_checkpointed_step = int(resume_cursor["global_step"])
    # The exact record index the bounded segment stops at: run_pretraining_segment
    # slices records[cursor:cursor + max_records], so min() mirrors its clamped
    # end. Only the boundary that reaches this index may release record buffers
    # for a low-commit retry -- every earlier boundary still trains from them.
    segment_final_record_index = (
        len(records) if max_records is None
        else min(len(records), int(resume_cursor["record_index"]) + max_records)
    )

    def checkpoint_callback(global_step: int, state: dict[str, Any]) -> None:
        nonlocal checkpoint, parameter_receipt, latest_parent_manifest, published_specialist_records, last_checkpointed_step
        data_cursor = dict(state["data_cursor"])
        data_cursor["input_identity_receipt_sha256"] = _json_sha256(input_receipt)
        data_cursor["governor"] = governor_receipt
        if resume_authority is not None:
            data_cursor["resume_authority"] = resume_authority
        current_lineage: dict[str, object] | None = None
        if specialist_lineage is not None:
            if latest_parent_manifest is None:
                raise RuntimeError("specialist checkpoint publication lost its verified parent manifest")
            planned_slice = specialist_lineage["execution_slice"]
            processed_records = int(data_cursor["record_index"])
            if processed_records <= published_specialist_records or processed_records > len(records):
                raise RuntimeError("specialist checkpoint cursor does not identify a new bound episode")
            episode_slice = specialist_execution_slice_receipt(
                records[published_specialist_records:processed_records],
                source_start_record=int(planned_slice["start_record"]) + published_specialist_records,
                # The lineage spread below keeps scene_split_selection, and checkpoint_
                # artifacts._specialist_lineage requires the slice to carry the selection's
                # count whenever that key is present -- an episode slice without it can
                # never publish a vision checkpoint (#1457: the first certified image
                # canary trained 200 records and died at final publication on exactly
                # this). The planned slice's value already passed startup validation as
                # selected_record_count; None for the three capabilities with no split.
                scene_split_record_count=planned_slice.get("scene_split_record_count"),
            )
            current_lineage = {
                **specialist_lineage,
                "parent_manifest": str(latest_parent_manifest),
                "execution_slice": episode_slice,
            }
            data_cursor["specialist_verification"] = specialist_verification
            checkpoint_target = checkpoint_parent / f"checkpoint-continue-seed-{seed}-from-step-{global_step}"
        else:
            checkpoint_target = checkpoint_root

        verified_holder: dict[str, object] = {}

        def verify_staging(staging_root: Path, manifest_receipt: dict[str, object]) -> None:
            verified = _execute_realization_counter(
                root=root, config_path=config_path,
                checkpoint_manifest_path=staging_root / "checkpoint-manifest.json",
                active_expert=str(model.active_expert), expected_counts=_counter_expected_counts(model),
                parent_manifest=(Path(current_lineage["parent_manifest"]) if current_lineage is not None else None),
                root_manifest=(Path(current_lineage["root_manifest"]) if current_lineage is not None else None),
            )
            _atomic_json(staging_root / _COUNTER_SUCCESS_RECEIPT, verified)
            require_counter_success_receipt(staging_root)
            verified_holder["receipt"] = verified
            return verified

        def publish_and_verify() -> tuple[dict[str, object], dict[str, object]]:
            published = write_checkpoint_artifacts(
                model, optimizer, checkpoint_target, launch_seed=seed,
                rng_state=_rng_state(torch.device("cuda")), data_cursor=data_cursor,
                model_config_sha256=_sha256(config_path), contract_sha256=_sha256(integration_contract_path),
                expert_genesis_sha256=genesis_hashes, optimizer_contract=optimizer_contract,
                optimizer_state_layout="owner-sharded-v1",
                specialist_lineage=current_lineage, max_serialized_bytes=checkpoint_byte_bound,
                max_transient_scratch_bytes=_MAX_TRANSIENT_CHECKPOINT_SCRATCH_BYTES,
                host_commit_reserve_bytes=checkpoint_host_commit_reserve_bytes(config_path),
                pre_publish_verifier=verify_staging,
            )
            return {**published, "published_checkpoint_id": checkpoint_target.name}, verified_holder["receipt"]

        result = _publish_checkpoint_with_low_commit_deferral(
            checkpoint_parent=checkpoint_parent,
            config_path=config_path,
            global_step=global_step,
            last_checkpointed_step=last_checkpointed_step,
            deferral_state=low_commit_deferral_state,
            publish=publish_and_verify,
            telemetry_path=telemetry_path,
            telemetry_run_id=telemetry_run_id,
            # Armed only at the final boundary, where episode_slice/data_cursor --
            # the only receipt inputs derived from record content -- are already
            # built above and no further optimizer step follows, so tearing down
            # gradients and record buffers loses nothing checkpointable (#1465).
            release_for_final_retry=(
                (lambda: _release_final_publication_ballast(records, model=model))
                if int(data_cursor["record_index"]) >= segment_final_record_index
                else None
            ),
        )
        if result is None:
            return
        checkpoint, parameter_receipt = result
        last_checkpointed_step = global_step
        if current_lineage is not None:
            latest_parent_manifest = checkpoint_target / "checkpoint-manifest.json"
            published_specialist_records = int(data_cursor["record_index"])
        if telemetry_path is not None and telemetry_run_id is not None:
            append_training_telemetry(telemetry_path, kind="checkpoint", payload={
                "run_id": telemetry_run_id,
                "step": global_step,
                "checkpoint_manifest_sha256": _sha256(checkpoint_target / "checkpoint-manifest.json"),
            })

    record_e4_step = _make_e4_measurement_recorder(
        telemetry_path=telemetry_path, telemetry_run_id=telemetry_run_id,
    )

    def progress_callback(progress: dict[str, object]) -> None:
        if telemetry_path is None or telemetry_run_id is None:
            return
        free_bytes, total_bytes = torch.cuda.mem_get_info()
        append_training_telemetry(telemetry_path, kind="train_step", payload={
            "run_id": telemetry_run_id,
            **progress,
            **_frozen_envelope_fields(progress),
            "free_gib": float(free_bytes / 1024**3),
            "total_gib": float(total_bytes / 1024**3),
            "vram_fraction_applied": float(torch.cuda.get_per_process_memory_fraction()),
        })
        record_e4_step(progress)

    segment = run_pretraining_segment(
        model=model, optimizer=optimizer, records=records, config=config, device=torch.device("cuda"),
        checkpoint_every=(int(checkpoint_interval) if records_override is not None else len(records)),
        checkpoint_callback=checkpoint_callback, initial_global_step=int(resume_cursor["global_step"]),
        progress_callback=progress_callback,
        initial_tokens_seen=int(resume_cursor["tokens_seen"]), initial_data_cursor=int(resume_cursor["record_index"]),
        data_shard_id=data_shard_id, require_complete_coverage=(records_override is None and max_records is None),
        max_records=max_records,
        signature_observer=(signature_census.observe if signature_census is not None else None),
        stage2_executor=stage2_executor,
        measurement_preparation_regions_per_signature=(
            _STAGE2_PREPARATION_REGIONS_PER_SIGNATURE
            if stage2_arm_receipt_output is not None else 0
        ),
    )
    if checkpoint is None or parameter_receipt is None:
        raise RuntimeError("training segment completed without a durable verified checkpoint")
    signature_census_receipt = None
    if signature_census is not None and signature_census_output is not None:
        signature_census_receipt = signature_census.write_receipt(signature_census_output)
    stage2_arm_receipt = None
    if stage2_arm_receipt_output is not None:
        selected_records = records[
            int(resume_cursor["record_index"]):(
                None if max_records is None
                else int(resume_cursor["record_index"]) + max_records
            )
        ]
        runtime = segment["stage2_runtime"]
        if stage2_active:
            if not isinstance(runtime, Mapping):
                raise RuntimeError("Stage-2 activation completed without a runtime receipt")
            mechanisms = {
                key: int(runtime[key])
                for key in (
                    "fp8_dispatches", "fp8_fallbacks", "cuda_graph_captures",
                    "cuda_graph_replays", "cuda_graph_fallbacks",
                    "shared_trunk_gradient_parameters", "shared_trunk_gradient_bytes",
                    "expert_bank_gradient_workspace_parameters", "gradient_workspace_bytes",
                    "gradient_workspace_rebinds", "inactive_grad_none_assertions",
                )
            }
        else:
            mechanisms = {
                "fp8_dispatches": 0,
                "fp8_fallbacks": 0,
                "cuda_graph_captures": 0,
                "cuda_graph_replays": 0,
                "cuda_graph_fallbacks": 0,
                "shared_trunk_gradient_parameters": 0,
                "shared_trunk_gradient_bytes": 0,
                "expert_bank_gradient_workspace_parameters": 0,
                "gradient_workspace_bytes": 0,
                "gradient_workspace_rebinds": 0,
                "inactive_grad_none_assertions": 0,
            }
        initial_cursor = {
            key: int(resume_cursor[key])
            for key in ("record_index", "global_step", "tokens_seen")
        }
        config_sha256 = _sha256(config_path)
        preparation = segment["measurement_preparation"]
        if not isinstance(preparation, Mapping):
            raise RuntimeError("Stage-2 arm completed without preparation evidence")
        captures_during_preparation = (
            int(runtime["captures_during_preparation"])
            if stage2_active and isinstance(runtime, Mapping) else 0
        )
        captures_during_measured_window = (
            int(runtime["captures_during_measured_window"])
            if stage2_active and isinstance(runtime, Mapping) else 0
        )
        receipt_value = {
                "schema_version": (
                    "ember-stage2-eager-workspace-diagnostic-v1"
                    if stage2_diagnostic_eager_workspace
                    else "ember-stage2-graph-only-diagnostic-v1"
                    if stage2_diagnostic_bf16_down
                    else "ember-stage2-training-arm-v2"
                ),
                "arm": (
                    "eager_workspace_bf16" if stage2_diagnostic_eager_workspace
                    else "graph_only_bf16_down" if stage2_diagnostic_bf16_down
                    else "census_bound_stage2" if stage2_acceleration
                    else "bf16_baseline"
                ),
                "source_commit": _STAGE2_AB_SOURCE_COMMIT,
                "runner_source_sha256": _sha256(Path(__file__).resolve()),
                "model_config_sha256": config_sha256,
                "input_identity_sha256": _json_sha256(input_receipt),
                "record_order_sha256": _json_sha256({"records": selected_records}),
                "checkpoint_lineage_sha256": _stage2_fresh_genesis_lineage_sha256(
                    seed=seed, config_sha256=config_sha256,
                ),
                "census_raw_sha256": (
                    _STAGE2_CENSUS_RAW_SHA256 if stage2_active else None
                ),
                "seed": seed,
                "initial_cursor": initial_cursor,
                "steps": int(segment["steps"]),
                "tokens": int(segment["tokens_seen"]) - initial_cursor["tokens_seen"],
                "losses": list(segment["losses"]),
                "step_timings_seconds": list(segment["step_timings_seconds"]),
                "step_elapsed_seconds": float(segment["step_elapsed_seconds"]),
                "tokens_per_second": float(segment["tokens_per_second"]),
                "max_memory_allocated_bytes": int(torch.cuda.max_memory_allocated()),
                "max_memory_reserved_bytes": int(torch.cuda.max_memory_reserved()),
                "preparation_regions_per_signature": int(preparation["regions_per_signature"]),
                "preparation_signature_count": int(preparation["signature_count"]),
                "preparation_region_count": int(preparation["region_count"]),
                "optimizer_state_preinitialized_parameters": int(
                    preparation["optimizer_state_preinitialized_parameters"]
                ),
                "capture_gradient_zeroing": (
                    str(runtime["capture_gradient_zeroing"])
                    if stage2_active and isinstance(runtime, Mapping)
                    else "NOT_APPLICABLE"
                ),
                "preparation_memory_allocated_bytes_by_signature": (
                    dict(runtime["preparation_memory_allocated_bytes_by_signature"])
                    if stage2_active and isinstance(runtime, Mapping)
                    else {}
                ),
                "captures_during_preparation": captures_during_preparation,
                "captures_during_measured_window": captures_during_measured_window,
                "no_capture_in_measured_window": bool(
                    preparation["no_capture_in_measured_window"]
                ),
                "mechanisms": mechanisms,
            }
        if stage2_diagnostic_bf16_down or stage2_diagnostic_eager_workspace:
            receipt_value.update({
                "claim_boundary": _STAGE2_DIAGNOSTIC_CLAIM_BOUNDARY,
                "production_accelerated_arm_self_sha256": (
                    _STAGE2_PRODUCTION_ACCELERATED_ARM_SELF_SHA256
                ),
            })
        if stage2_diagnostic_eager_workspace:
            receipt_value["post_step1_parameter_delta_l2"] = dict(
                runtime["post_step1_parameter_delta_l2"]
            )
            stage2_arm_receipt = write_stage2_eager_workspace_diagnostic_receipt(
                stage2_arm_receipt_output, receipt_value,
            )
        elif stage2_diagnostic_bf16_down:
            receipt_value["pre_optimizer_sync"] = str(runtime["pre_optimizer_sync"])
            stage2_arm_receipt = write_stage2_graph_only_diagnostic_receipt(
                stage2_arm_receipt_output, receipt_value,
            )
        else:
            stage2_arm_receipt = write_stage2_arm_receipt(
                stage2_arm_receipt_output, receipt_value,
            )
    if telemetry_path is not None and telemetry_run_id is not None and model_chat_restore_not_before is not None:
        append_training_telemetry(telemetry_path, kind="run_status", payload={
            "run_id": telemetry_run_id,
            "phase": "COMPLETE",
            "model_chat": "OFFLINE",
            "restore_not_before": model_chat_restore_not_before,
        })
    counts = measure_parameter_counts(model)
    if counts["unique_parameters"] != 3_839_161_856 or counts["active_parameters"] != 1_725_232_640:
        raise RuntimeError("instantiated sparse counts differ from the authorized architecture")
    return {
        "losses": segment["losses"], "counts": counts, "memory_preflight": memory_preflight,
        "launch_seed": seed, "rng_state_before_init_sha256": rng_state_before_init,
        "expert_genesis_sha256": genesis_hashes, "peak_memory_bytes": int(torch.cuda.max_memory_allocated()),
        "input_identity_receipt": input_receipt, "post_step_checkpoint": checkpoint,
        "parameter_receipt": parameter_receipt, "publication_plan": specialist_plan,
        "resume_authority": resume_authority,
        "governor": governor_receipt,
        "training_signature_census": signature_census_receipt,
        "stage2_arm_receipt": stage2_arm_receipt,
    }

def specialist_lineage_request(
    *, capability: str, verification: dict[str, object], resume_checkpoint: Path | None,
    parent_manifest: Path, root_manifest: Path, execution_slice: dict[str, object],
    scene_split_selection: dict[str, object] | None = None,
) -> dict[str, object]:
    """Bind a specialist launch to externally supplied parent/root manifests before allocation."""

    expected_expert = {"image": "vision", "audio": "audio", "reasoning": "reasoning", "tool": "tool"}.get(capability)
    if expected_expert is None or verification.get("capability") != capability or verification.get("result") != "VERIFIED":
        raise ValueError("specialist lineage requires a verified capability-matched data receipt")
    validate_specialist_execution_slice(execution_slice, verified_record_count=verification.get("record_count"))
    if capability == "image":
        if not isinstance(scene_split_selection, dict):
            raise ValueError("image specialist lineage requires a separate scene split receipt")
        validate_image_scene_split_execution(
            [], verification=verification, selection=scene_split_selection, execution_slice=execution_slice,
        )
    elif scene_split_selection is not None:
        raise ValueError("only image specialist lineage may carry a scene split receipt")
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
        "execution_slice": execution_slice,
        **({"scene_split_selection": scene_split_selection} if scene_split_selection is not None else {}),
    }


def verified_specialist_episode_expert(
    records: list[dict[str, object]], verification: Mapping[str, object],
) -> str:
    """Bind one verified capability episode to its declared specialist before setup."""

    capability_experts = {"image": "vision", "audio": "audio", "reasoning": "reasoning", "tool": "tool"}
    capability = verification.get("capability")
    expected = capability_experts.get(capability)
    if expected is None:
        raise ValueError("verified specialist receipt lacks a declared capability")
    routed = {record.get("active_expert") for record in records}
    if routed != {expected}:
        raise ValueError(f"verified {capability} episode must route to {expected}")
    return expected


def run_specialist(
    *, seed: int, artifact_root: Path, data_manifest: Path, tokenizer_path: Path,
    capability: str, resume_checkpoint: Path | None = None, resume_counter_receipt: Path | None = None,
    resume_realization_registry: Path | None = None, resume_optimizer_transition_registry: Path | None = None,
    resume_optimizer_transition_registry_sha256: str | None = None,
    parent_manifest: Path, root_manifest: Path,
    checkpoint_interval: int, write_budget_bytes: int,
    start_record: int = 0, max_records: int | None = None,
    c_relocated_under_disk_budget_runner: bool = False,
    relocation_custody_root: Path | None = None,
    telemetry_path: Path | None = None,
    telemetry_run_id: str | None = None,
    model_chat_restore_not_before: str | None = None,
) -> dict[str, object]:
    """Run one verifier-bound specialist family through the canonical v4 lineage path."""

    root = Path(__file__).resolve().parents[2]
    records, verification, full_records_artifact_bytes = load_verified_specialist_records(
        root=root, data_manifest=data_manifest, tokenizer_path=tokenizer_path, capability=capability,
    )
    scene_split_selection: dict[str, object] | None = None
    if capability == "image":
        records, scene_split_selection = select_verified_scene_split(
            records, capability=capability, scene_split="train",
            full_records_artifact_sha256=str(verification.get("records_artifact_sha256", "")),
        )
    selected_records, execution_slice = bind_specialist_execution_slice(
        records, start_record=start_record,
        max_records=(len(records) - start_record if max_records is None else max_records),
        scene_split_record_count=(int(scene_split_selection["selected_record_count"]) if scene_split_selection is not None else None),
    )
    lineage = specialist_lineage_request(
        capability=capability, verification=verification, resume_checkpoint=resume_checkpoint,
        parent_manifest=parent_manifest, root_manifest=root_manifest, execution_slice=execution_slice,
        scene_split_selection=scene_split_selection,
    )
    try:
        return run(
            seed=seed, artifact_root=artifact_root, resume_checkpoint=resume_checkpoint, resume_counter_receipt=resume_counter_receipt,
            resume_realization_registry=resume_realization_registry,
            resume_optimizer_transition_registry=resume_optimizer_transition_registry,
            resume_optimizer_transition_registry_sha256=resume_optimizer_transition_registry_sha256,
            records_override=selected_records, scene_split_records=records,
            full_records_artifact_bytes=full_records_artifact_bytes if capability == "image" else None,
            specialist_verification=verification, specialist_lineage=lineage,
            checkpoint_interval=checkpoint_interval, write_budget_bytes=write_budget_bytes,
            c_relocated_under_disk_budget_runner=c_relocated_under_disk_budget_runner,
            relocation_custody_root=relocation_custody_root,
            telemetry_path=telemetry_path,
            telemetry_run_id=telemetry_run_id,
            model_chat_restore_not_before=model_chat_restore_not_before,
        )
    except PublishedHousekeepingError as error:
        if telemetry_path is not None and telemetry_run_id is not None and model_chat_restore_not_before is not None:
            append_training_telemetry(telemetry_path, kind="run_status", payload={
                "run_id": telemetry_run_id,
                "phase": "PUBLISHED_HOUSEKEEPING_FAILED",
                "failure_class": "PUBLISHED_HOUSEKEEPING_FAILED",
                "published_checkpoint_id": error.published_checkpoint_id,
                "model_chat": "OFFLINE",
                "restore_not_before": model_chat_restore_not_before,
                "last_completed_step": _latest_completed_training_step(telemetry_path, run_id=telemetry_run_id),
            })
        raise
    except Exception as error:
        if telemetry_path is not None and telemetry_run_id is not None and model_chat_restore_not_before is not None:
            append_training_telemetry(telemetry_path, kind="run_status", payload={
                "run_id": telemetry_run_id,
                "phase": "FAILED",
                "model_chat": "OFFLINE",
                "restore_not_before": model_chat_restore_not_before,
                "last_completed_step": _latest_completed_training_step(telemetry_path, run_id=telemetry_run_id),
                "failure_class": _training_failure_class(error),
            })
        raise


def run_semantic(
    *, seed: int, artifact_root: Path, receipt_path: Path, shards_root: Path, tokenizer_path: Path,
    expected_receipt_sha256: str, expected_tokenizer_sha256: str, expected_architecture_sha256: str,
    steps: int, sequence_length: int, checkpoint_interval: int, write_budget_bytes: int, resume_checkpoint: Path | None = None,
    resume_counter_receipt: Path | None = None, resume_realization_registry: Path | None = None,
    resume_optimizer_transition_registry: Path | None = None,
    resume_optimizer_transition_registry_sha256: str | None = None,
    telemetry_path: Path | None = None, telemetry_run_id: str | None = None,
    admitted_row_set_sha256: str | None = None,
    receipt_custody_root: Path | None = None,
) -> dict[str, object]:
    """Train receipt-bound semantic text through the shared nonlinear language path."""

    if not isinstance(seed, int) or seed < 0 or not isinstance(steps, int) or steps < 1 or not isinstance(sequence_length, int) or sequence_length < 1 or not isinstance(checkpoint_interval, int) or checkpoint_interval < 1 or not isinstance(write_budget_bytes, int) or write_budget_bytes < 1:
        raise ValueError("semantic launch requires nonnegative seed and positive steps and sequence length")
    if (telemetry_path is None) != (telemetry_run_id is None):
        raise ValueError("semantic training telemetry requires telemetry_path and telemetry_run_id together")
    if telemetry_run_id is not None and (not telemetry_run_id or len(telemetry_run_id) > 128):
        raise ValueError("semantic training telemetry run id is invalid")
    if admitted_row_set_sha256 is not None and re.fullmatch(
        r"[0-9a-f]{64}", admitted_row_set_sha256
    ) is None:
        raise ValueError("admitted row-set hash must be an exact SHA-256")
    # Shared-text authority must be complete before even a CUDA availability probe.
    root = Path(__file__).resolve().parents[2]
    text_lab_preflight = run_text_lab_preflight(
        repo_root=root,
        receipt_custody_root=receipt_custody_root,
    )
    if text_lab_preflight.get("result") != "VERIFIED":
        if (
            admitted_row_set_sha256 is None
            or text_lab_preflight.get("result")
            != "NOT_ADMITTED_SOURCE_EVIDENCE_MISSING"
        ):
            raise ValueError(str(text_lab_preflight.get("result", "text-lab authority was not admitted")))
        admitted_subset = validate_admitted_authority_subset(
            root,
            text_lab_preflight,
        )
        if (
            admitted_subset.get("result") != "VERIFIED_ADMITTED_SUBSET"
            or admitted_subset.get("admitted_row_set_sha256")
            != admitted_row_set_sha256
        ):
            raise ValueError("runtime admitted row-set hash does not match certified pin")
    artifact_root = production_artifact_root(artifact_root)
    config_path = root / "configs" / "ember-restart-3b.json"
    integration_contract_path = (
        root
        / "docs"
        / "domains"
        / "governance"
        / "ember-restart"
        / "integration-contract-v1.md"
    )
    if not integration_contract_path.is_file():
        raise RuntimeError("the merged Ember integration contract is required for production launch")
    load_training_acceleration_policy()
    config = RestartDecoderConfig.from_contract(config_path)
    memory_contract = load_memory_contract(config_path)
    governor_receipt = governed_resource_preflight()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for the production semantic runner")
    stream = ManifestBoundTokenStream.from_receipt(
        receipt_path=receipt_path, shards_root=shards_root, tokenizer_path=tokenizer_path
    )
    if stream.vocab_size != config.vocab_size:
        raise ValueError("semantic receipt tokenizer vocabulary does not match the production model config")
    # Closed identity join (#1091): a green launch-packet preflight binds to a
    # manifest-declared receipt/tokenizer/architecture digest, but nothing
    # previously carried that digest into the bytes this runner actually
    # consumes -- an operator could substitute a different, individually
    # valid, receipt/shard/tokenizer set after the green preflight and train
    # on bytes the preflight never represented. Recompute and compare BEFORE
    # any model construction or training step; refuse on any mismatch,
    # including an absent/blank expectation (never "no expectation supplied,
    # therefore proceed").
    architecture_sha256 = _sha256(config_path)
    if (
        not expected_receipt_sha256
        or not expected_tokenizer_sha256
        or not expected_architecture_sha256
        or stream.receipt_sha256 != expected_receipt_sha256
        or stream.tokenizer_sha256 != expected_tokenizer_sha256
        or architecture_sha256 != expected_architecture_sha256
    ):
        raise RuntimeError(
            "semantic launch identity mismatch: the receipt/tokenizer/architecture bytes "
            "this run would consume do not match the launch-packet-bound expected digests "
            f"(receipt_match={stream.receipt_sha256 == expected_receipt_sha256}, "
            f"tokenizer_match={stream.tokenizer_sha256 == expected_tokenizer_sha256}, "
            f"architecture_match={architecture_sha256 == expected_architecture_sha256})"
        )
    total_parameters = config.structural_parameter_count()
    shared_active_parameters = 1_020_589_568
    device_free_bytes, _device_total_bytes = torch.cuda.mem_get_info()
    memory_preflight = production_memory_preflight(
        total_parameters=total_parameters, active_parameters=shared_active_parameters, device_free_bytes=int(device_free_bytes)
    )
    if memory_preflight["parameter_dtype"] != memory_contract["parameter_dtype"]:
        raise RuntimeError("memory preflight and production numerics disagree")
    checkpoint_parent = artifact_root / "checkpoints"
    resume_authority: dict[str, object] | None = None
    resume_receipt: dict[str, object] | None = None
    if resume_checkpoint is not None:
        resume_checkpoint, resume_authority = authorize_production_resume_checkpoint(
            resume_checkpoint,
            counter_success_receipt=resume_counter_receipt,
            realization_registry=resume_realization_registry,
            optimizer_transition_registry=resume_optimizer_transition_registry,
            optimizer_transition_registry_sha256=resume_optimizer_transition_registry_sha256,
        )
        resume_receipt = published_checkpoint_receipt(resume_checkpoint)
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
        if resume_receipt is None or resume_authority is None:
            raise RuntimeError("authorized semantic resume requires a frozen checkpoint receipt")
        genesis_hashes = resume_expert_genesis(resume_receipt, requested_seed=seed)
        loaded = restore_authorized_checkpoint(
            model, optimizer, resume_checkpoint,
            resume_receipt, resume_authority,
        )
        resume_cursor = dict(loaded["data_cursor"])
        initial_global_step = int(resume_cursor["global_step"])
        initial_tokens_seen = int(resume_cursor["tokens_seen"])
    checkpoint_byte_bound = checkpoint_serialization_byte_bound(config_path, active_parameters=shared_active_parameters)
    publication_plan = semantic_publication_plan(steps=steps, checkpoint_interval=checkpoint_interval, checkpoint_byte_bound=checkpoint_byte_bound, write_budget_bytes=write_budget_bytes, initial_global_step=initial_global_step)
    torch.cuda.reset_peak_memory_stats()
    checkpoint: dict[str, object] | None = None
    parameter_receipt: dict[str, object] | None = None
    low_commit_deferral_state = {"count": 0}
    last_checkpointed_step = initial_global_step

    def checkpoint_callback(global_step: int, state: dict[str, Any]) -> None:
        nonlocal checkpoint, parameter_receipt, last_checkpointed_step
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
            return verified

        def publish_and_verify() -> tuple[dict[str, object], dict[str, object]]:
            data_cursor = dict(state["data_cursor"])
            data_cursor["governor"] = governor_receipt
            if resume_authority is not None:
                data_cursor["resume_authority"] = resume_authority
            published = write_checkpoint_artifacts(
                model, optimizer, checkpoint_root, launch_seed=seed,
                rng_state=_rng_state(torch.device("cuda")), data_cursor=data_cursor,
                model_config_sha256=_sha256(config_path), contract_sha256=_sha256(integration_contract_path),
                expert_genesis_sha256=genesis_hashes, optimizer_contract=optimizer_contract,
                optimizer_state_layout="owner-sharded-v1",
                max_serialized_bytes=checkpoint_byte_bound,
                max_transient_scratch_bytes=_MAX_TRANSIENT_CHECKPOINT_SCRATCH_BYTES,
                host_commit_reserve_bytes=checkpoint_host_commit_reserve_bytes(config_path),
                pre_publish_verifier=verify_staging,
            )
            return published, verified_holder["receipt"]

        result = _publish_checkpoint_with_low_commit_deferral(
            checkpoint_parent=checkpoint_parent,
            config_path=config_path,
            global_step=global_step,
            last_checkpointed_step=last_checkpointed_step,
            deferral_state=low_commit_deferral_state,
            publish=publish_and_verify,
            telemetry_path=telemetry_path,
            telemetry_run_id=telemetry_run_id,
        )
        if result is None:
            return
        checkpoint, parameter_receipt = result
        last_checkpointed_step = global_step

    record_e4_step = _make_e4_measurement_recorder(
        telemetry_path=telemetry_path, telemetry_run_id=telemetry_run_id,
    )

    def progress_callback(progress: dict[str, object]) -> None:
        if telemetry_path is None or telemetry_run_id is None:
            return
        append_training_telemetry(telemetry_path, kind="train_step", payload={
            "run_id": telemetry_run_id,
            **progress,
            **_frozen_envelope_fields(progress),
        })
        record_e4_step(progress)

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
        progress_callback=progress_callback,
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
        "governor": governor_receipt,
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
        "resume_authority": resume_authority,
    }


def add_genesis_init_parser(subparsers) -> None:
    genesis_init = subparsers.add_parser("genesis-init")
    genesis_init.add_argument("--config", type=Path, required=True)
    genesis_init.add_argument("--seed", type=int, required=True)
    genesis_init.add_argument("--output-root", type=Path, required=True)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    genesis = subparsers.add_parser("genesis")
    genesis.add_argument("--inventory", type=Path, required=True)
    genesis.add_argument("--artifact-root", type=Path, required=True)
    genesis.add_argument("--source-commit", required=True)
    genesis.add_argument("--run-id", required=True)
    add_genesis_init_parser(subparsers)
    vertical = subparsers.add_parser("vertical")
    vertical.add_argument("--seed", type=int, required=True)
    vertical.add_argument("--artifact-root", type=Path, required=True)
    vertical.add_argument("--resume-checkpoint", type=Path)
    vertical_resume = vertical.add_mutually_exclusive_group()
    vertical_resume.add_argument("--resume-counter-receipt", type=Path)
    vertical_resume.add_argument("--resume-realization-registry", type=Path)
    vertical_resume.add_argument("--resume-optimizer-transition-registry", type=Path)
    vertical.add_argument("--resume-optimizer-transition-registry-sha256")
    governed_vertical = subparsers.add_parser("governed-vertical")
    governed_vertical.add_argument("--seed", type=int, required=True)
    governed_vertical.add_argument("--artifact-root", type=Path, required=True)
    governed_vertical.add_argument("--write-budget-bytes", type=int, required=True)
    governed_vertical.add_argument("--max-records", type=int)
    governed_vertical.add_argument("--resume-checkpoint", type=Path)
    governed_resume = governed_vertical.add_mutually_exclusive_group()
    governed_resume.add_argument("--resume-counter-receipt", type=Path)
    governed_resume.add_argument("--resume-realization-registry", type=Path)
    governed_resume.add_argument("--resume-optimizer-transition-registry", type=Path)
    governed_vertical.add_argument("--resume-optimizer-transition-registry-sha256")
    governed_vertical.add_argument("--c-relocated-under-disk-budget-runner", action="store_true")
    governed_vertical.add_argument("--relocation-custody-root", type=Path)
    governed_vertical.add_argument("--signature-census-output", type=Path)
    governed_vertical.add_argument("--signature-census-source-commit")
    governed_vertical.add_argument("--stage2-acceleration", action="store_true")
    governed_vertical.add_argument("--stage2-diagnostic-bf16-down", action="store_true")
    governed_vertical.add_argument("--stage2-diagnostic-eager-workspace", action="store_true")
    governed_vertical.add_argument("--stage2-diagnostic-pre-optimizer-sync", action="store_true")
    governed_vertical.add_argument("--stage2-arm-receipt-output", type=Path)
    governed_preflight = subparsers.add_parser("governed-vertical-preflight")
    governed_preflight.add_argument("--seed", type=int, required=True)
    governed_preflight.add_argument("--artifact-root", type=Path, required=True)
    governed_preflight.add_argument("--write-budget-bytes", type=int, required=True)
    governed_preflight.add_argument("--max-records", type=int)
    governed_preflight.add_argument("--stage2-acceleration", action="store_true")
    governed_preflight.add_argument("--stage2-diagnostic-bf16-down", action="store_true")
    governed_preflight.add_argument("--stage2-diagnostic-eager-workspace", action="store_true")
    governed_preflight.add_argument("--stage2-diagnostic-pre-optimizer-sync", action="store_true")
    governed_preflight.add_argument("--stage2-arm-receipt-output", type=Path)
    stage2_compare = subparsers.add_parser("stage2-ab-compare")
    stage2_compare.add_argument("--baseline", type=Path, required=True)
    stage2_compare.add_argument("--accelerated", type=Path, required=True)
    stage2_compare.add_argument("--output", type=Path, required=True)

    specialist = subparsers.add_parser("specialist")
    specialist.add_argument("--seed", type=int, required=True)
    specialist.add_argument("--artifact-root", type=Path, required=True)
    specialist.add_argument("--data-manifest", type=Path, required=True)
    specialist.add_argument("--tokenizer", type=Path, required=True)
    specialist.add_argument("--capability", choices=("image", "audio", "reasoning", "tool"), required=True)
    specialist.add_argument("--resume-checkpoint", type=Path, required=True)
    specialist_resume = specialist.add_mutually_exclusive_group(required=True)
    specialist_resume.add_argument("--resume-counter-receipt", type=Path)
    specialist_resume.add_argument("--resume-realization-registry", type=Path)
    specialist_resume.add_argument("--resume-optimizer-transition-registry", type=Path)
    specialist.add_argument("--resume-optimizer-transition-registry-sha256")
    specialist.add_argument("--parent-manifest", type=Path, required=True)
    specialist.add_argument("--root-manifest", type=Path, required=True)
    specialist.add_argument("--start-record", type=int, default=0)
    specialist.add_argument("--max-records", type=int, required=True)
    specialist.add_argument("--checkpoint-interval", type=int, required=True)
    specialist.add_argument("--write-budget-gib", type=int, required=True)
    specialist.add_argument("--c-relocated-under-disk-budget-runner", action="store_true")
    specialist.add_argument("--relocation-custody-root", type=Path)
    specialist.add_argument("--telemetry-path", type=Path, required=True)
    specialist.add_argument("--telemetry-run-id", required=True)
    specialist.add_argument("--model-chat-restore-not-before", required=True)
    semantic = subparsers.add_parser("semantic")
    semantic.add_argument("--seed", type=int, required=True)
    semantic.add_argument("--artifact-root", type=Path, required=True)
    semantic.add_argument("--receipt", type=Path, required=True)
    semantic.add_argument("--shards-root", type=Path, required=True)
    semantic.add_argument("--tokenizer", type=Path, required=True)
    semantic.add_argument("--expected-receipt-sha256", required=True)
    semantic.add_argument("--expected-tokenizer-sha256", required=True)
    semantic.add_argument("--expected-architecture-sha256", required=True)
    semantic.add_argument("--admitted-row-set-sha256")
    semantic.add_argument("--text-lab-receipt-custody-root", type=Path)
    semantic.add_argument("--steps", type=int, required=True)
    semantic.add_argument("--sequence-length", type=int, required=True)
    semantic.add_argument("--checkpoint-interval", type=int, required=True)
    semantic.add_argument("--write-budget-gib", type=int, required=True)
    semantic.add_argument("--resume-checkpoint", type=Path)
    semantic_resume = semantic.add_mutually_exclusive_group()
    semantic_resume.add_argument("--resume-counter-receipt", type=Path)
    semantic_resume.add_argument("--resume-realization-registry", type=Path)
    semantic_resume.add_argument("--resume-optimizer-transition-registry", type=Path)
    semantic.add_argument("--resume-optimizer-transition-registry-sha256")
    semantic.add_argument("--telemetry-path", type=Path)
    semantic.add_argument("--telemetry-run-id")
    a1 = subparsers.add_parser("a1-dense-tier1")
    a1.add_argument("--seed", type=int, required=True)
    a1.add_argument("--artifact-root", type=Path, required=True)
    a1.add_argument("--token-shards-receipt", type=Path, required=True)
    a1.add_argument("--shards-root", type=Path, required=True)
    a1.add_argument("--comparison-authority", type=Path, required=True)
    a1.add_argument("--steps", type=int, required=True)
    a1.add_argument("--sequence-length", type=int, required=True)
    a1.add_argument("--checkpoint-interval", type=int, required=True)
    a1.add_argument("--write-budget-gib", type=int, required=True)
    a1.add_argument("--transient-checkpoint-gib", type=int, required=True)
    a1.add_argument("--host-commit-reserve-gib", type=int, required=True)
    a1.add_argument("--gpu-free-margin-gib", type=int, required=True)
    a1.add_argument("--b-custody-floor-gib", type=int, required=True)
    a1.add_argument("--telemetry-path", type=Path, required=True)
    a1.add_argument("--telemetry-run-id", required=True)
    a1_tier2 = subparsers.add_parser("a1-dense-tier2")
    a1_tier2.add_argument("--seed", type=int, required=True)
    a1_tier2.add_argument("--artifact-root", type=Path, required=True)
    a1_tier2.add_argument("--token-shards-receipt", type=Path, required=True)
    a1_tier2.add_argument("--shards-root", type=Path, required=True)
    a1_tier2.add_argument("--comparison-authority", type=Path, required=True)
    a1_tier2.add_argument("--steps", type=int, required=True)
    a1_tier2.add_argument("--sequence-length", type=int, required=True)
    a1_tier2.add_argument("--checkpoint-interval", type=int, required=True)
    a1_tier2.add_argument("--write-budget-gib", type=int, required=True)
    a1_tier2.add_argument("--transient-checkpoint-gib", type=int, required=True)
    a1_tier2.add_argument("--host-commit-reserve-gib", type=int, required=True)
    a1_tier2.add_argument("--gpu-free-margin-gib", type=int, required=True)
    a1_tier2.add_argument("--b-custody-floor-gib", type=int, required=True)
    a1_tier2.add_argument("--telemetry-path", type=Path, required=True)
    a1_tier2.add_argument("--telemetry-run-id", required=True)
    a1_tier2.add_argument("--tier2-contract", type=Path, required=True)
    a1_tier2.add_argument("--tier2-contract-sha256", required=True)
    a1_tier2.add_argument("--liveness-receipt", type=Path, required=True)
    a1_tier2.add_argument("--liveness-receipt-sha256", required=True)
    args = parser.parse_args()
    if args.command == "genesis-init":
        result = initialize_genesis_inventory(
            config_path=args.config,
            seed=args.seed,
            output_root=args.output_root,
        )
    elif args.command == "genesis":
        result = mint_genesis_candidate(
            inventory_path=args.inventory,
            output_root=args.artifact_root,
            source_commit=args.source_commit,
            run_id=args.run_id,
        )
    elif args.command == "governed-vertical":
        result = run_governed_vertical(
            seed=args.seed,
            artifact_root=args.artifact_root,
            write_budget_bytes=args.write_budget_bytes,
            max_records=args.max_records,
            resume_checkpoint=args.resume_checkpoint,
            resume_counter_receipt=args.resume_counter_receipt,
            resume_realization_registry=args.resume_realization_registry,
            resume_optimizer_transition_registry=args.resume_optimizer_transition_registry,
            resume_optimizer_transition_registry_sha256=args.resume_optimizer_transition_registry_sha256,
            c_relocated_under_disk_budget_runner=(
                args.c_relocated_under_disk_budget_runner
            ),
            relocation_custody_root=args.relocation_custody_root,
            signature_census_output=args.signature_census_output,
            signature_census_source_commit=args.signature_census_source_commit,
            stage2_acceleration=args.stage2_acceleration,
            stage2_diagnostic_bf16_down=args.stage2_diagnostic_bf16_down,
            stage2_diagnostic_eager_workspace=args.stage2_diagnostic_eager_workspace,
            stage2_diagnostic_pre_optimizer_sync=args.stage2_diagnostic_pre_optimizer_sync,
            stage2_arm_receipt_output=args.stage2_arm_receipt_output,
        )
    elif args.command == "governed-vertical-preflight":
        result = preflight_governed_vertical(
            seed=args.seed,
            artifact_root=args.artifact_root,
            write_budget_bytes=args.write_budget_bytes,
            max_records=args.max_records,
            stage2_acceleration=args.stage2_acceleration,
            stage2_diagnostic_bf16_down=args.stage2_diagnostic_bf16_down,
            stage2_diagnostic_eager_workspace=args.stage2_diagnostic_eager_workspace,
            stage2_diagnostic_pre_optimizer_sync=args.stage2_diagnostic_pre_optimizer_sync,
            stage2_arm_receipt_output=args.stage2_arm_receipt_output,
        )
    elif args.command == "stage2-ab-compare":
        result = compare_stage2_ab_receipts(
            args.baseline, args.accelerated, args.output,
        )
    elif args.command == "specialist":
        result = run_specialist(seed=args.seed, artifact_root=args.artifact_root, data_manifest=args.data_manifest, tokenizer_path=args.tokenizer, capability=args.capability, resume_checkpoint=args.resume_checkpoint, resume_counter_receipt=args.resume_counter_receipt, resume_realization_registry=args.resume_realization_registry, resume_optimizer_transition_registry=args.resume_optimizer_transition_registry, resume_optimizer_transition_registry_sha256=args.resume_optimizer_transition_registry_sha256, parent_manifest=args.parent_manifest, root_manifest=args.root_manifest, start_record=args.start_record, max_records=args.max_records, checkpoint_interval=args.checkpoint_interval, write_budget_bytes=args.write_budget_gib * 1024**3, c_relocated_under_disk_budget_runner=args.c_relocated_under_disk_budget_runner, relocation_custody_root=args.relocation_custody_root, telemetry_path=args.telemetry_path, telemetry_run_id=args.telemetry_run_id, model_chat_restore_not_before=args.model_chat_restore_not_before)
    elif args.command == "semantic":
        result = run_semantic(
            seed=args.seed,
            artifact_root=args.artifact_root,
            receipt_path=args.receipt,
            shards_root=args.shards_root,
            tokenizer_path=args.tokenizer,
            expected_receipt_sha256=args.expected_receipt_sha256,
            expected_tokenizer_sha256=args.expected_tokenizer_sha256,
            expected_architecture_sha256=args.expected_architecture_sha256,
            admitted_row_set_sha256=args.admitted_row_set_sha256,
            receipt_custody_root=args.text_lab_receipt_custody_root,
            steps=args.steps,
            sequence_length=args.sequence_length,
            checkpoint_interval=args.checkpoint_interval,
            write_budget_bytes=args.write_budget_gib * 1024**3,
            resume_checkpoint=args.resume_checkpoint,
            resume_counter_receipt=args.resume_counter_receipt,
            resume_realization_registry=args.resume_realization_registry,
            resume_optimizer_transition_registry=args.resume_optimizer_transition_registry,
            resume_optimizer_transition_registry_sha256=args.resume_optimizer_transition_registry_sha256,
            telemetry_path=args.telemetry_path,
            telemetry_run_id=args.telemetry_run_id,
        )
    elif args.command == "a1-dense-tier1":
        canonical_runner_authority = canonical_disk_budget_runner_authority()
        a1_config = DenseA1Config.from_contract(
            Path(__file__).resolve().with_name("ember-restart-3b-a1.json"),
            repo_root=Path(__file__).resolve().parents[2],
        )
        governor_receipt = governed_resource_preflight()
        device_free_bytes, _device_total_bytes = torch.cuda.mem_get_info()
        custody_anchor = args.artifact_root.anchor or str(args.artifact_root)
        resource_preflight = dense_a1_resource_preflight(
            parameter_count=a1_config.structural_parameter_count(),
            write_budget_bytes=args.write_budget_gib * 1024**3,
            transient_checkpoint_bytes=args.transient_checkpoint_gib * 1024**3,
            host_commit_reserve_bytes=args.host_commit_reserve_gib * 1024**3,
            gpu_free_margin_bytes=args.gpu_free_margin_gib * 1024**3,
            b_custody_floor_bytes=args.b_custody_floor_gib * 1024**3,
            available_commit_bytes=available_host_commit_bytes(),
            device_free_bytes=int(device_free_bytes),
            custody_free_bytes=shutil.disk_usage(custody_anchor).free,
        )
        resource_preflight["governor"] = governor_receipt
        resource_preflight["canonical_runner"] = canonical_runner_authority
        result = run_dense_a1(
            repo_root=Path(__file__).resolve().parents[2],
            seed=args.seed,
            artifact_root=args.artifact_root,
            token_shards_receipt=args.token_shards_receipt,
            shards_root=args.shards_root,
            comparison_authority=args.comparison_authority,
            steps=args.steps,
            sequence_length=args.sequence_length,
            checkpoint_interval=args.checkpoint_interval,
            write_budget_bytes=args.write_budget_gib * 1024**3,
            telemetry_path=args.telemetry_path,
            telemetry_run_id=args.telemetry_run_id,
            resource_preflight=resource_preflight,
        )
    elif args.command == "a1-dense-tier2":
        canonical_runner_authority = canonical_disk_budget_runner_authority()
        governor_receipt = governed_resource_preflight()
        repo_root = Path(__file__).resolve().parents[2]
        dense_config = DenseA1Config.from_contract(
            Path(__file__).resolve().with_name("ember-restart-3b-a1.json"),
            repo_root=repo_root,
        )
        contract = load_tier2_contract(args.tier2_contract)
        meta = DenseA1Decoder(dense_config, device="meta")
        shapes = {name: tuple(parameter.shape) for name, parameter in meta.named_parameters()}
        del meta
        inventory = derive_tier2_resource_inventory(shapes, contract=contract)
        device_free_bytes, _device_total_bytes = torch.cuda.mem_get_info()
        custody_anchor = args.artifact_root.anchor or str(args.artifact_root)
        resource_preflight = admit_tier2_resources(
            inventory,
            available_device_bytes=int(device_free_bytes),
            custody_free_bytes=shutil.disk_usage(custody_anchor).free,
            contract=contract,
        )
        resource_preflight["governor"] = governor_receipt
        resource_preflight["canonical_runner"] = canonical_runner_authority
        result = run_dense_a1_tier2(
            repo_root=repo_root,
            seed=args.seed,
            artifact_root=args.artifact_root,
            token_shards_receipt=args.token_shards_receipt,
            shards_root=args.shards_root,
            comparison_authority=args.comparison_authority,
            steps=args.steps,
            sequence_length=args.sequence_length,
            checkpoint_interval=args.checkpoint_interval,
            telemetry_path=args.telemetry_path,
            telemetry_run_id=args.telemetry_run_id,
            tier2_contract_path=args.tier2_contract,
            expected_tier2_contract_sha256=args.tier2_contract_sha256,
            liveness_receipt=args.liveness_receipt,
            expected_liveness_receipt_sha256=args.liveness_receipt_sha256,
            resource_preflight=resource_preflight,
        )
    else:
        require_disk_budget_runner_contract()
        result = run(seed=args.seed, artifact_root=args.artifact_root, resume_checkpoint=args.resume_checkpoint, resume_counter_receipt=args.resume_counter_receipt, resume_realization_registry=args.resume_realization_registry, resume_optimizer_transition_registry=args.resume_optimizer_transition_registry, resume_optimizer_transition_registry_sha256=args.resume_optimizer_transition_registry_sha256)
    print(json.dumps(result, sort_keys=True))
if __name__ == "__main__":
    main()
