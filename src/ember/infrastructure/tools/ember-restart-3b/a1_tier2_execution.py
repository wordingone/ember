# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Real dense Tier-2 execution and terminal parity-run finalization."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any

import torch
import torch.nn.functional as F

from a1_dense import A1_CONFIG_SHA256, DenseA1Config, DenseA1Decoder
# issue2015 exact-local-import:src/ember/infrastructure/tools/ember-restart-3b/a1_execution.py
import importlib.util as _ember_dae9355feddb7be8_importlib
import sys as _ember_dae9355feddb7be8_sys
from pathlib import Path as _ember_dae9355feddb7be8_Path
_ember_dae9355feddb7be8_path = _ember_dae9355feddb7be8_Path(__file__).resolve().parent.joinpath('a1_execution.py')
if not _ember_dae9355feddb7be8_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/infrastructure/tools/ember-restart-3b/a1_execution.py')
_ember_dae9355feddb7be8_aliases = ('_ember_issue2015_dae9355feddb7be8', 'a1_execution', 'src.ember.infrastructure.tools.ember-restart-3b.a1_execution')
_ember_dae9355feddb7be8_existing = []
for _ember_dae9355feddb7be8_alias in _ember_dae9355feddb7be8_aliases:
    _ember_dae9355feddb7be8_candidate = _ember_dae9355feddb7be8_sys.modules.get(_ember_dae9355feddb7be8_alias)
    if _ember_dae9355feddb7be8_candidate is not None and all(_ember_dae9355feddb7be8_candidate is not item for item in _ember_dae9355feddb7be8_existing):
        _ember_dae9355feddb7be8_existing.append(_ember_dae9355feddb7be8_candidate)
if len(_ember_dae9355feddb7be8_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/a1_execution.py')
if _ember_dae9355feddb7be8_existing:
    _ember_dae9355feddb7be8_module = _ember_dae9355feddb7be8_existing[0]
    _ember_dae9355feddb7be8_observed = getattr(_ember_dae9355feddb7be8_module, '__file__', None)
    if _ember_dae9355feddb7be8_observed is None or _ember_dae9355feddb7be8_Path(_ember_dae9355feddb7be8_observed).resolve() != _ember_dae9355feddb7be8_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/infrastructure/tools/ember-restart-3b/a1_execution.py')
else:
    _ember_dae9355feddb7be8_spec = _ember_dae9355feddb7be8_importlib.spec_from_file_location('_ember_issue2015_dae9355feddb7be8', _ember_dae9355feddb7be8_path)
    if _ember_dae9355feddb7be8_spec is None or _ember_dae9355feddb7be8_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/infrastructure/tools/ember-restart-3b/a1_execution.py')
    _ember_dae9355feddb7be8_module = _ember_dae9355feddb7be8_importlib.module_from_spec(_ember_dae9355feddb7be8_spec)
    for _ember_dae9355feddb7be8_alias in _ember_dae9355feddb7be8_aliases:
        _ember_dae9355feddb7be8_prior = _ember_dae9355feddb7be8_sys.modules.get(_ember_dae9355feddb7be8_alias)
        if _ember_dae9355feddb7be8_prior is not None and _ember_dae9355feddb7be8_prior is not _ember_dae9355feddb7be8_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/a1_execution.py')
        _ember_dae9355feddb7be8_sys.modules[_ember_dae9355feddb7be8_alias] = _ember_dae9355feddb7be8_module
    try:
        _ember_dae9355feddb7be8_spec.loader.exec_module(_ember_dae9355feddb7be8_module)
    except BaseException:
        for _ember_dae9355feddb7be8_alias in _ember_dae9355feddb7be8_aliases:
            if _ember_dae9355feddb7be8_sys.modules.get(_ember_dae9355feddb7be8_alias) is _ember_dae9355feddb7be8_module:
                _ember_dae9355feddb7be8_sys.modules.pop(_ember_dae9355feddb7be8_alias, None)
        raise
for _ember_dae9355feddb7be8_alias in _ember_dae9355feddb7be8_aliases:
    _ember_dae9355feddb7be8_prior = _ember_dae9355feddb7be8_sys.modules.get(_ember_dae9355feddb7be8_alias)
    if _ember_dae9355feddb7be8_prior is not None and _ember_dae9355feddb7be8_prior is not _ember_dae9355feddb7be8_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/a1_execution.py')
    _ember_dae9355feddb7be8_sys.modules[_ember_dae9355feddb7be8_alias] = _ember_dae9355feddb7be8_module
_atomic_json = getattr(_ember_dae9355feddb7be8_module, '_atomic_json')
_load = getattr(_ember_dae9355feddb7be8_module, '_load')
_sha = getattr(_ember_dae9355feddb7be8_module, '_sha')
_threshold = getattr(_ember_dae9355feddb7be8_module, '_threshold')
_tokens = getattr(_ember_dae9355feddb7be8_module, '_tokens')
_train_step_envelope = getattr(_ember_dae9355feddb7be8_module, '_train_step_envelope')
# issue2015 exact-local-import-end:src/ember/infrastructure/tools/ember-restart-3b/a1_execution.py
from a1_tier2_checkpoint import write_tier2_checkpoint
from a1_tier2_contract import Tier2Contract, load_tier2_contract
from a1_tier2_optimizer import ProjectedQuantizedAdamWCUDA, Tier2OptimizerContract


CORE_SCHEMA = "ember-a1-tier2-execution-core-v1"
RUN_SCHEMA = "ember02-r1-e8-run-v1"
CORE_FIELDS = {
    "schema_version", "status", "source_commit", "certified_launch_sha256",
    "parameter_count", "optimizer_inventory", "checkpoint_sha256",
    "checkpoint_identity", "resource_preflight", "comparison_authority",
    "tier2_contract", "liveness_receipt",
}
OPTIMIZER_INVENTORY_FIELDS = {
    "schema_version", "state_format", "registered_parameters",
    "registered_numel", "initialized_parameters", "quantized_payload_bytes",
    "fp32_scale_bytes", "persistent_state_device",
    "cpu_persistent_state_bytes", "complete",
}


def _optimizer_contract(contract: Tier2Contract) -> Tier2OptimizerContract:
    return Tier2OptimizerContract(
        learning_rate=contract.learning_rate,
        beta1=contract.betas[0],
        beta2=contract.betas[1],
        epsilon=contract.epsilon,
        weight_decay=contract.weight_decay,
        max_rank=contract.max_rank,
        refresh_gap=contract.refresh_gap,
        projection_scale=contract.projection_scale,
        block_size=contract.block_size,
        state_format=contract.state_format,
    )


def run_dense_a1_tier2(
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
    telemetry_path: Path,
    telemetry_run_id: str,
    tier2_contract_path: Path,
    expected_tier2_contract_sha256: str,
    liveness_receipt: Path,
    expected_liveness_receipt_sha256: str,
    resource_preflight: dict[str, Any],
) -> dict[str, Any]:
    if (
        not isinstance(resource_preflight, dict)
        or resource_preflight.get("schema_version") != "ember-a1-tier2-resource-preflight-v1"
        or resource_preflight.get("status") != "PASS"
        or resource_preflight.get("cpu_persistent_state_bytes") != 0
        or resource_preflight.get("host_full_gradient_bytes") != 0
        or resource_preflight.get("host_master_weight_bytes") != 0
    ):
        raise ValueError("Tier-2 resource preflight receipt is absent or invalid")
    source_commit = os.environ.get("EMBER_A1_SOURCE_COMMIT")
    certified_launch_sha256 = os.environ.get("EMBER_A1_CERTIFIED_LAUNCH_SHA256")
    if (
        not isinstance(source_commit, str) or len(source_commit) != 40
        or any(character not in "0123456789abcdef" for character in source_commit)
        or not isinstance(certified_launch_sha256, str) or len(certified_launch_sha256) != 64
        or any(character not in "0123456789abcdef" for character in certified_launch_sha256)
    ):
        raise RuntimeError("Tier-2 certified source identity is unavailable")
    if os.environ.get("CUBLAS_WORKSPACE_CONFIG") != ":4096:8":
        raise RuntimeError("Tier-2 deterministic CUBLAS workspace authority is unavailable")
    torch.use_deterministic_algorithms(True)
    if not torch.are_deterministic_algorithms_enabled():
        raise RuntimeError("Tier-2 deterministic algorithms could not be enabled")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for certified Tier-2 execution")
    repo_root = Path(repo_root)
    artifact_root = Path(artifact_root)
    if _sha(Path(tier2_contract_path)) != expected_tier2_contract_sha256:
        raise ValueError("Tier-2 contract changed after certified admission")
    if _sha(Path(liveness_receipt)) != expected_liveness_receipt_sha256:
        raise ValueError("Tier-2 liveness receipt changed after certified admission")
    contract = load_tier2_contract(tier2_contract_path)
    config_path = repo_root / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b" / "ember-restart-3b-a1.json"
    config = DenseA1Config.from_contract(config_path, repo_root=repo_root)
    if resource_preflight.get("parameter_count") != config.structural_parameter_count():
        raise ValueError("Tier-2 resource preflight parameter count drifted")
    comparison = _load(Path(comparison_authority), "A1 comparison authority")
    matched_ref = comparison.get("matched_a3_run")
    if not isinstance(matched_ref, dict) or set(matched_ref) != {"path", "sha256"}:
        raise ValueError("Tier-2 comparison matched-run reference is invalid")
    matched_path = Path(comparison_authority).parent / matched_ref["path"]
    if _sha(matched_path) != matched_ref["sha256"]:
        raise ValueError("matched A3 run changed before Tier-2 allocation")
    matched = _load(matched_path, "matched A3 run")
    if not isinstance(matched.get("identity"), dict):
        raise ValueError("matched A3 identity is unavailable")
    checkpoint_identity = {
        "comparison_id": comparison.get("comparison_id"),
        "matched_identity": dict(matched["identity"]),
        "config_sha256": _sha(config_path),
        "tier2_contract_sha256": _sha(Path(tier2_contract_path)),
        "liveness_sha256": _sha(Path(liveness_receipt)),
        "source_commit": source_commit,
        "certified_launch_sha256": certified_launch_sha256,
        "tier": "TIER_2",
        "mechanism": "OWNED_Q_GALORE_PROJECTED_GRADIENT",
        "predecessor": None,
    }
    meta = DenseA1Decoder(config, device="meta")
    if sum(parameter.numel() for parameter in meta.parameters()) != config.structural_parameter_count():
        raise RuntimeError("Tier-2 dense meta inventory differs from contract")
    del meta
    model = DenseA1Decoder(config, device="cuda", allow_production_allocation=True, genesis_seed=seed)
    optimizer = ProjectedQuantizedAdamWCUDA(
        list(model.named_parameters()), contract=_optimizer_contract(contract)
    )
    optimizer.initialize_state()
    optimizer.enable_fused_backward()
    stream = iter(_tokens(Path(token_shards_receipt), Path(shards_root)))
    telemetry_path = Path(telemetry_path)
    telemetry_path.parent.mkdir(parents=True, exist_ok=True)
    tokens_seen = 0
    checkpoint_sha: str | None = None
    with telemetry_path.open("x", encoding="utf-8", newline="\n") as telemetry:
        for step in range(1, steps + 1):
            started = time.perf_counter()
            batch = [next(stream) for _ in range(sequence_length + 1)]
            inputs = torch.tensor(batch[:-1], device="cuda", dtype=torch.long).unsqueeze(0)
            targets = torch.tensor(batch[1:], device="cuda", dtype=torch.long).unsqueeze(0)
            optimizer.zero_grad(set_to_none=True)
            loss = F.cross_entropy(model(inputs).reshape(-1, config.vocab_size), targets.reshape(-1))
            loss.backward()
            optimizer.step()
            grad_norm = optimizer.finish_gradient_norm()
            tokens_seen += sequence_length
            telemetry.write(json.dumps(_train_step_envelope(
                run_id=telemetry_run_id, step=step, tokens=sequence_length,
                loss=float(loss.detach()), grad_norm=grad_norm,
                wall_seconds=time.perf_counter() - started,
            ), sort_keys=True) + "\n")
            telemetry.flush()
            if step % checkpoint_interval == 0 or step == steps:
                _, checkpoint_sha = write_tier2_checkpoint(
                    artifact_root / f"checkpoint-a1-tier2-step-{step}",
                    model=model, optimizer=optimizer, global_step=step,
                    tokens_seen=tokens_seen, identity=checkpoint_identity,
                )
    if checkpoint_sha is None:
        raise RuntimeError("Tier-2 execution produced no checkpoint")
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
        "tier2_contract": {"path": str(tier2_contract_path), "sha256": _sha(Path(tier2_contract_path))},
        "liveness_receipt": {"path": str(liveness_receipt), "sha256": _sha(Path(liveness_receipt))},
    }
    _atomic_json(artifact_root / "a1-tier2-run-core.json", core)
    return core


def finalize_tier2_run(
    *, artifact_root: Path, energy_receipt: Path, thresholds_path: Path,
    expected_source_commit: str, expected_certified_launch_sha256: str,
    expected_comparison_authority: Path, expected_tier2_contract: Path,
    expected_liveness_receipt: Path,
) -> Path:
    artifact_root = Path(artifact_root)
    output = artifact_root / "tier2-run.json"
    core = _load(artifact_root / "a1-tier2-run-core.json", "Tier-2 run core")
    energy = _load(Path(energy_receipt), "energy receipt")
    if set(core) != CORE_FIELDS:
        raise ValueError("Tier-2 run core schema is not closed")
    if (
        core.get("schema_version") != CORE_SCHEMA or core.get("status") != "TERMINAL"
        or core.get("source_commit") != expected_source_commit
        or core.get("certified_launch_sha256") != expected_certified_launch_sha256
        or type(core.get("parameter_count")) is not int or core["parameter_count"] < 3_000_000_000
    ):
        raise ValueError("Tier-2 run core is not terminal")
    for field, expected in (
        ("comparison_authority", Path(expected_comparison_authority)),
        ("tier2_contract", Path(expected_tier2_contract)),
        ("liveness_receipt", Path(expected_liveness_receipt)),
    ):
        ref = core.get(field)
        if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
            raise ValueError(f"Tier-2 {field} binding is absent")
        path = Path(ref["path"])
        if path.resolve(strict=False) != expected.resolve(strict=False) or _sha(path) != ref["sha256"]:
            raise ValueError(f"Tier-2 {field} changed or was substituted")
    resource_preflight = core.get("resource_preflight")
    if (
        not isinstance(resource_preflight, dict)
        or resource_preflight.get("schema_version") != "ember-a1-tier2-resource-preflight-v1"
        or resource_preflight.get("status") != "PASS"
        or resource_preflight.get("parameter_count") != core["parameter_count"]
        or resource_preflight.get("cpu_persistent_state_bytes") != 0
        or resource_preflight.get("host_full_gradient_bytes") != 0
        or resource_preflight.get("host_master_weight_bytes") != 0
        or resource_preflight.get("persistent_state_device") != "cuda"
    ):
        raise ValueError("Tier-2 run core resource preflight is invalid")
    t06 = _threshold(Path(thresholds_path), "T-06")
    energy_block = energy.get("energy")
    if (
        energy.get("schema_version") != "ember-energy-proxy-run-v1"
        or energy.get("result") != "MEASURED"
        or energy.get("executed") is not True
        or energy.get("training_launched") is not True
        or not isinstance(energy_block, dict)
    ):
        raise ValueError("Tier-2 energy receipt is not a measured training window")
    try:
        coverage = Decimal(str(energy_block.get("sample_coverage_fraction")))
    except (InvalidOperation, TypeError) as error:
        raise ValueError("Tier-2 energy sample coverage is invalid") from error
    intended = energy.get("intended_samples")
    captured = energy.get("captured_samples")
    if (
        type(intended) is not int or intended <= 0
        or type(captured) is not int or not 0 <= captured <= intended
        or coverage != Decimal(captured) / Decimal(intended)
        or Decimal(str(energy.get("t06_coverage_floor"))) != t06
        or energy.get("coverage_meets_t06") is not (coverage >= t06)
    ):
        raise ValueError("Tier-2 energy sample coverage is inconsistent")
    if (
        not coverage.is_finite()
        or coverage < t06 or coverage > Decimal("1")
    ):
        raise ValueError("Tier-2 energy sample coverage is incomplete or inconsistent")
    comparison = _load(Path(expected_comparison_authority), "A1 comparison authority")
    matched_path = Path(expected_comparison_authority).parent / comparison["matched_a3_run"]["path"]
    if _sha(matched_path) != comparison["matched_a3_run"]["sha256"]:
        raise ValueError("matched A3 run changed after Tier-2 execution")
    a3 = _load(matched_path, "matched A3 run")
    expected_identity = {
        "comparison_id": comparison.get("comparison_id"),
        "matched_identity": dict(a3["identity"]),
        "config_sha256": A1_CONFIG_SHA256,
        "tier2_contract_sha256": _sha(Path(expected_tier2_contract)),
        "liveness_sha256": _sha(Path(expected_liveness_receipt)),
        "source_commit": core["source_commit"],
        "certified_launch_sha256": core["certified_launch_sha256"],
        "tier": "TIER_2", "mechanism": "OWNED_Q_GALORE_PROJECTED_GRADIENT",
        "predecessor": None,
    }
    if core.get("checkpoint_identity") != expected_identity:
        raise ValueError("Tier-2 checkpoint identity is thin, stale, or swapped")
    inventory = core.get("optimizer_inventory")
    if (
        not isinstance(inventory, dict) or set(inventory) != OPTIMIZER_INVENTORY_FIELDS
        or inventory.get("schema_version") != "ember-a1-tier2-state-inventory-v1"
        or inventory.get("state_format") != "ember-a1-tier2-q-galore-cuda-v1"
        or inventory.get("complete") is not True
        or inventory.get("registered_numel") != core["parameter_count"]
        or inventory.get("initialized_parameters") != inventory.get("registered_parameters")
        or inventory.get("cpu_persistent_state_bytes") != 0
        or inventory.get("persistent_state_device") != "cuda"
    ):
        raise ValueError("Tier-2 optimizer inventory is incomplete or off-device")
    identity = dict(a3["identity"])
    identity["genesis_sha256"] = comparison["genesis_authority_sha256"]
    run = {
        "schema_version": RUN_SCHEMA, "arm_id": "A1", "tier": "TIER2",
        "mechanism": "OWNED_Q_GALORE_PROJECTED_GRADIENT", "status": "TERMINAL",
        "certified_launch_sha256": core["certified_launch_sha256"],
        "source_commit": core["source_commit"],
        "architecture_revision": "ember-dense-a1-3b-v1",
        "parameter_count": core["parameter_count"],
        "active_parameter_count": core["parameter_count"],
        "contains_router_or_experts": False,
        "optimizer": {
            "kind": "OWNED_Q_GALORE_PROJECTED_GRADIENT", "full_state": False,
            "cpu_offload": False, "covered_parameter_count": core["parameter_count"],
        },
        "identity": identity,
        "energy_sample_coverage": format(coverage, ".12f"),
        "checkpoint_sha256": core["checkpoint_sha256"],
    }
    raw = json.dumps(run, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    run["receipt_sha256"] = hashlib.sha256(raw).hexdigest()
    _atomic_json(output, run)
    return output
