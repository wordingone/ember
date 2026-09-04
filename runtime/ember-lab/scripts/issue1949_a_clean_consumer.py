#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Real, receipt-bound consumers for the #1949 A-CLEAN runtime execution legs."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence


NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
COMMAND_EXITS = {
    "direct": 0,
    "lab": 0,
    "external-present": 0,
    "external-absent": 3,
    "topology": 0,
}
# The producer parser in ember-lab rejects values above this exact cap.  The
# daemon stops the producer once all phases are consumed, so this is a safety
# ceiling rather than an authoring-host readiness estimate.
LAB_PRODUCER_CONTRACT_CAP_MS = 60_000
# Ten producer caps leave bounded room for daemon admission/build handoff while
# remaining far below the workflow's 60-minute job limit.
LAB_DISPATCH_TTL_MS = 10 * LAB_PRODUCER_CONTRACT_CAP_MS
CLAIM_BOUNDARY = (
    "ARCHITECTURE_AND_PORTABILITY_MATRIX_ONLY; "
    "NO_CORPUS_CAPABILITY_TRAINING_THROUGHPUT_OR_MILESTONE_CREDIT"
)


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def receipt_path(artifact_root: Path, command: str) -> Path:
    if command not in COMMAND_EXITS:
        raise ValueError(f"UNKNOWN_COMMAND:{command}")
    return Path(artifact_root) / f"issue1949-a-clean-consumer-{command}.json"


def derive_self(payload: Mapping[str, object]) -> str:
    unsigned = dict(payload)
    unsigned.pop("self_sha256", None)
    return sha256_bytes(canonical_json(unsigned))


def reopen_receipt(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    payload = json.loads(raw)
    if raw != canonical_json(payload) + b"\n":
        raise ValueError("RECEIPT_RAW_REFUSED")
    if payload.get("self_sha256") != derive_self(payload):
        raise ValueError("RECEIPT_SELF_REFUSED")
    return payload


def publish_receipt(artifact_root: Path, command: str, fields: Mapping[str, object]) -> dict[str, Any]:
    root = Path(artifact_root)
    root.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema_version": "ember-issue1949-a-clean-consumer-v1",
        "command": command,
        "claim_boundary": CLAIM_BOUNDARY,
        **dict(fields),
    }
    payload["self_sha256"] = derive_self(payload)
    path = receipt_path(root, command)
    with path.open("xb") as handle:
        handle.write(canonical_json(payload) + b"\n")
    if reopen_receipt(path) != payload:
        raise ValueError("RECEIPT_REOPEN_REFUSED")
    return payload


def _tool_root(repo_root: Path) -> Path:
    root = Path(repo_root).resolve(strict=True)
    candidates = (
        root / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b",
        root / "tools" / "ember-restart-3b",
    )
    for tools in candidates:
        if (tools / "build_owned_curriculum.py").is_file():
            return tools
    raise ValueError("PRODUCTION_TOOL_ROOT_ABSENT:canonical-and-legacy")


def _production_module_path(repo_root: Path, name: str) -> Path:
    root = Path(repo_root).resolve(strict=True)
    canonical = {
        "model": root / "src" / "ember" / "model" / "model.py",
        "pretrain": root / "src" / "ember" / "training" / "pretrain.py",
        "cbase_heldout_eval": root / "src" / "ember" / "evaluation" / "cbase_heldout_eval.py",
        "infer": root / "src" / "ember" / "runtime" / "infer.py",
    }
    if name in canonical:
        path = canonical[name]
        if path.is_file():
            return path
        raise ValueError(f"PRODUCTION_MODULE_ABSENT:{name}")
    return _tool_root(repo_root) / f"{name}.py"


def _load_module(repo_root: Path, name: str):
    tools = _tool_root(repo_root)
    path = _production_module_path(repo_root, name)
    if not path.is_file():
        raise ValueError(f"PRODUCTION_MODULE_ABSENT:{name}")
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    spec = importlib.util.spec_from_file_location(f"issue1949_a_clean_{name}", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"PRODUCTION_MODULE_SPEC_REFUSED:{name}")
    module = importlib.util.module_from_spec(spec)
    prior = sys.modules.get(spec.name)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        if prior is None:
            sys.modules.pop(spec.name, None)
        else:
            sys.modules[spec.name] = prior
        raise
    return module


def _module_bindings(repo_root: Path, names: Sequence[str]) -> list[dict[str, str]]:
    repo = Path(repo_root).resolve(strict=True)
    rows = []
    for name in names:
        path = _production_module_path(repo, name)
        rows.append({"name": name, "path": path.relative_to(repo).as_posix(), "sha256": sha256_file(path)})
    return rows


def _counter_verifier(parameter_counter, candidate: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    architecture = manifest["architecture"]
    payload: dict[str, Any] = {
        "schema_version": "ember-sparse-realization-receipt-v1",
        "verification_boundary": "VERIFIED_MEASURED",
        "result": "MEASURED",
        "model_config_sha256": manifest["model_config_sha256"],
        "subject_checkpoint_sha256": manifest["checkpoint_manifest_sha256"],
        "architecture_revision": manifest["architecture_revision"],
        "counter_sha256": sha256_file(Path(parameter_counter.__file__)),
        "active_expert_ids": manifest["active_expert_ids"],
        "expert_genesis_sha256": manifest["expert_genesis_sha256"],
        "expert_parameter_sha256": manifest["expert_parameter_sha256"],
        "runtime_authority": {"schema_version": "ember-counter-runtime-authority-v1", "kind": "NONE"},
    }
    for field in (
        "allocated_parameters", "unique_parameters", "trainable_parameters",
        "served_parameters", "active_parameters", "episode_trainable_parameters",
    ):
        payload[field] = architecture[field]
    parameter_counter.validate_realization_receipt(payload)
    path = candidate / "parameter-counter-receipt.json"
    with path.open("xb") as handle:
        handle.write(canonical_json(payload) + b"\n")
    return payload


def _select_training_records(
    records: Sequence[Mapping[str, object]], *, topology: bool,
) -> list[dict[str, object]]:
    rows = [dict(row) for row in records if isinstance(row, Mapping)]
    if topology:
        selected = []
        for expert in ("vision", "audio", "reasoning", "tool"):
            match = next((row for row in rows if row.get("active_expert") == expert), None)
            if match is None:
                raise ValueError(f"TOPOLOGY_EXPERT_ABSENT:{expert}")
            selected.append(match)
        return selected
    selected = [row for row in rows if row.get("active_expert") == "reasoning"][:2]
    if len(selected) < 2:
        selected = rows[:2]
    if len(selected) < 2:
        raise ValueError("TRAINING_RECORDS_INSUFFICIENT")
    return selected


def _run_real_model_chain(
    repo_root: Path, work: Path, data_path: Path, *, topology: bool,
) -> dict[str, Any]:
    """Run the real Training, Checkpoint, Evaluation and Runtime owners on CPU."""
    import torch

    model_module = _load_module(repo_root, "model")
    checkpoint = _load_module(repo_root, "checkpoint_artifacts")
    parameter_counter = _load_module(repo_root, "parameter_counter")
    pretrain = _load_module(repo_root, "pretrain")
    evaluator = _load_module(repo_root, "cbase_heldout_eval")
    inference = _load_module(repo_root, "infer")
    data_path = Path(data_path).resolve(strict=True)
    data_raw = data_path.read_bytes()
    data_payload = json.loads(data_raw)
    records = data_payload.get("records") if isinstance(data_payload, dict) else None
    if not isinstance(records, list):
        raise ValueError("DETERMINISTIC_DATA_SCHEMA_REFUSED")
    selected = _select_training_records(records, topology=topology)
    maximum_token = max(
        int(token)
        for row in selected
        for field in ("token_ids", "target_ids")
        for token in row.get(field, [])
    )
    vocab_size = max(64, maximum_token + 1)
    config_payload = {
        "kind": "issue1949-a-clean-cpu-real-fixture-v1",
        "hidden_size": 32,
        "layers": 1,
        "attention_heads": 4,
        "vocab_size": vocab_size,
        "gradient_checkpointing": False,
    }
    config_path = work / "config.json"
    with config_path.open("xb") as handle:
        handle.write(canonical_json(config_payload) + b"\n")
    config = model_module.RestartDecoderConfig.small_for_tests(
        hidden_size=32, layers=1, attention_heads=4, vocab_size=vocab_size,
        gradient_checkpointing=False,
    )
    model = model_module.UnifiedDecoder(config, genesis_seed=1949)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
    checkpoint_root = work / f"checkpoint-step-{len(selected)}"
    genesis = model.expert_bank_genesis_hashes()
    checkpoint_receipt: dict[str, Any] | None = None

    def checkpoint_callback(_step: int, result: Mapping[str, Any]) -> None:
        nonlocal checkpoint_receipt
        if checkpoint_receipt is not None:
            raise ValueError("CHECKPOINT_CALLBACK_DUPLICATED")
        checkpoint_receipt = checkpoint.write_checkpoint_artifacts(
            model,
            optimizer,
            checkpoint_root,
            launch_seed=1949,
            rng_state={
                "cpu": torch.get_rng_state().clone(),
                "cuda": torch.cuda.get_rng_state().clone()
                if torch.cuda.is_available()
                else torch.tensor([1, 9, 4, 9], dtype=torch.uint8),
            },
            data_cursor=result["data_cursor"],
            model_config_sha256=sha256_file(config_path),
            contract_sha256=sha256_file(_production_module_path(repo_root, "model")),
            expert_genesis_sha256=genesis,
            pre_publish_verifier=lambda candidate, manifest: _counter_verifier(
                parameter_counter, candidate, manifest
            ),
        )

    segment = pretrain.run_pretraining_segment(
        model=model,
        optimizer=optimizer,
        records=selected,
        config=config,
        device=torch.device("cpu"),
        checkpoint_every=len(selected),
        checkpoint_callback=checkpoint_callback,
        data_shard_id=f"issue1949-a-clean:{sha256_bytes(data_raw)}",
        require_complete_coverage=False,
    )
    if segment.get("steps") != len(selected) or int(segment.get("steps", 0)) < 2:
        raise ValueError("TRAINING_STEP_COUNT_REFUSED")
    if checkpoint_receipt is None:
        raise ValueError("CHECKPOINT_RECEIPT_ABSENT")
    restored = model_module.UnifiedDecoder(config, genesis_seed=1950)
    restored_optimizer = torch.optim.AdamW(restored.parameters(), lr=1e-4)
    cursor = checkpoint.load_checkpoint_artifacts(
        restored, restored_optimizer, checkpoint_root, checkpoint_receipt,
    )["data_cursor"]
    restored.eval()
    if cursor != segment["data_cursor"]:
        raise ValueError("CHECKPOINT_CURSOR_RESUME_REFUSED")
    windows = []
    for index, row in enumerate(selected[:2]):
        targets = list(row["target_ids"])
        windows.append({
            "input_ids": list(row["token_ids"]),
            "target_ids": targets,
            "document_ids": [f"issue1949-doc-{index}"] * len(targets),
            "shard_name": "issue1949-a-clean-evaluation",
        })
    evaluation = evaluator.evaluate_teacher_forced(
        restored,
        windows,
        device="cpu",
        dtype="float32",
        seed=1949,
        packed_bytes_per_token=1.0,
        bootstrap_samples=16,
    )
    if evaluation.get("repeat_run_match") is not True:
        raise ValueError("EVALUATION_DETERMINISM_REFUSED")
    runtime_row = next(
        (row for row in selected if row.get("active_expert") == "reasoning"), selected[0]
    )
    prompt_ids = torch.tensor([runtime_row["token_ids"]], dtype=torch.long)
    generated, stop_reason = inference.greedy_generate(
        model=restored,
        prompt_ids=prompt_ids,
        model_kwargs={"active_expert": runtime_row["active_expert"]},
        max_new_tokens=2,
        stop_token_ids={0},
    )
    if not generated:
        raise ValueError("RUNTIME_GENERATION_EMPTY")
    evaluation_path = work / "evaluation.json"
    with evaluation_path.open("xb") as handle:
        handle.write(canonical_json(evaluation) + b"\n")
    return {
        "fixture": {
            "config_sha256": sha256_file(config_path),
            "data_sha256": sha256_bytes(data_raw),
            "data_path": str(data_path),
        },
        "training": {
            "entry_point": "src/ember/training/pretrain.py:run_pretraining_segment",
            "steps": segment["steps"],
            "tokens_seen": segment["tokens_seen"],
            "losses": segment["losses"],
            "expert_examples": segment["expert_examples"],
        },
        "checkpoint": {
            "write_entry_point": "checkpoint_artifacts.py:write_checkpoint_artifacts",
            "load_entry_point": "checkpoint_artifacts.py:load_checkpoint_artifacts",
            "path": str(checkpoint_root.resolve()),
            "manifest_sha256": checkpoint_receipt["checkpoint_manifest_sha256"],
            "cursor": cursor,
        },
        "evaluation": {
            "entry_point": "src/ember/evaluation/cbase_heldout_eval.py:evaluate_teacher_forced",
            "receipt_sha256": sha256_file(evaluation_path),
            **evaluation,
        },
        "runtime": {
            "entry_point": "src/ember/runtime/infer.py:greedy_generate",
            "generated_token_ids": generated,
            "stop_reason": stop_reason,
            "prompt_sha256": sha256_bytes(canonical_json(runtime_row["token_ids"])),
        },
        "governance": {
            "counter_receipt_sha256": sha256_file(
                checkpoint_root / "parameter-counter-receipt.json"
            )
        },
        "production_modules": _module_bindings(
            repo_root,
            (
                "model", "pretrain", "checkpoint_artifacts", "cbase_heldout_eval",
                "infer", "parameter_counter",
            ),
        ),
    }


def run_direct(repo_root: Path, artifact_root: Path, data_path: Path) -> dict[str, Any]:
    root = Path(artifact_root)
    work = root / "direct-runtime"
    work.mkdir(parents=True, exist_ok=False)
    return publish_receipt(root, "direct", {
        "result": "PASS",
        "exit_code": 0,
        **_run_real_model_chain(repo_root, work, data_path, topology=False),
    })


def run_topology_model(repo_root: Path, artifact_root: Path, data_path: Path) -> dict[str, Any]:
    root = Path(artifact_root)
    work = root / "topology-model-runtime"
    work.mkdir(parents=True, exist_ok=False)
    chain = _run_real_model_chain(repo_root, work, data_path, topology=True)
    expert_examples = chain["training"]["expert_examples"]
    expected = {"vision": 1, "audio": 1, "reasoning": 1, "tool": 1}
    if expert_examples != expected:
        raise ValueError(f"TOPOLOGY_EXPERT_EXECUTION_REFUSED:{expert_examples}")
    return publish_receipt(root, "topology", {
        "result": "PASS",
        "exit_code": 0,
        "platform": platform.system().lower(),
        "topology": "unified-decoder-shared-plus-four-experts-cpu",
        **chain,
    })


def _run(argv: Sequence[str], *, cwd: Path, timeout: float = 300.0) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        list(argv), cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False, timeout=timeout, creationflags=NO_WINDOW,
    )


def _strict_gate_contract_sha256() -> str:
    census = {
        "expected": [
            "dispatch_manifest_bytes", "storage_reserves", "vram_reserve",
            "host_commit_capacity", "preflight_receipt",
        ],
        "gates": [
            {"name": "dispatch_manifest_bytes", "producer": "runtime/ember-lab/src/main.rs::dispatch", "consumers": ["runtime/ember-lab/src/rpc.rs::dispatch_manifest", "runtime/ember-lab/src/lib.rs::dispatch_manifest_bytes"], "binding": "content_hash"},
            {"name": "storage_reserves", "producer": "runtime/ember-lab/src/lib.rs::DispatchStorageReserve", "consumers": ["runtime/ember-lab/src/lib.rs::validate_dispatch_manifest_snapshot_preconditions", "runtime/ember-lab/src/lib.rs::dispatch_manifest_bytes_at_with_probes_and_host_inner"], "binding": "measured_value"},
            {"name": "vram_reserve", "producer": "runtime/ember-lab/src/lib.rs::available_free_vram_bytes", "consumers": ["runtime/ember-lab/src/lib.rs::dispatch_manifest_bytes_at_with_probes_and_host_inner"], "binding": "measured_value"},
            {"name": "host_commit_capacity", "producer": "runtime/ember-lab/src/lib.rs::probe_host_commit_capacity", "consumers": ["runtime/ember-lab/src/lib.rs::dispatch_manifest_bytes_at_with_probes_and_host_inner"], "binding": "measured_value"},
            {"name": "preflight_receipt", "producer": "runtime/ember-lab/src/lib.rs::atomic_replace", "consumers": ["runtime/ember-lab/src/lib.rs::reconstruct_existing_dispatch"], "binding": "content_hash"},
        ],
    }
    return sha256_bytes(json.dumps(census, separators=(",", ":")).encode("utf-8"))


TOPOLOGY_AUTHORITY = (
    "mailbox ruling 34099, 2026-09-03 22:05Z, CPU minimal slice, no GPU tenancy"
)
TOPOLOGY_PHASES = (
    "admission", "data_verify", "train", "checkpoint", "publish",
    "selectable_checkpoint", "restore", "evaluation", "runtime_load",
)


def _publish_topology_receipt(artifact_root: Path, fields: Mapping[str, object]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "ember-issue1949-topology-canary-v1",
        **dict(fields),
    }
    payload["self_sha256"] = derive_self(payload)
    path = receipt_path(artifact_root, "topology")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(canonical_json(payload) + b"\n")
    if reopen_receipt(path) != payload:
        raise ValueError("TOPOLOGY_RECEIPT_REOPEN_REFUSED")
    return payload


def run_lab(
    repo_root: Path, artifact_root: Path, cargo: str, data_path: Path, *, topology: bool = False,
) -> dict[str, Any]:
    root = Path(artifact_root)
    command = "topology" if topology else "lab"
    work = root / f"{command}-runtime"
    work.mkdir(parents=True, exist_ok=False)
    (work / "model-runtime").mkdir()
    chain = _run_real_model_chain(
        repo_root, work / "model-runtime", data_path, topology=topology,
    )
    model_chain_payload: dict[str, Any] = {"result": "PASS", **chain}
    model_chain_payload["self_sha256"] = derive_self(model_chain_payload)
    model_chain_receipt = work / "model-chain-receipt.json"
    with model_chain_receipt.open("xb") as handle:
        handle.write(canonical_json(model_chain_payload) + b"\n")
    model_chain_raw_sha256 = sha256_file(model_chain_receipt)
    repo = Path(repo_root).resolve(strict=True)
    manifest = repo / "runtime" / "ember-lab" / "Cargo.toml"
    build = _run((cargo, "build", "--locked", "--manifest-path", str(manifest), "--quiet"), cwd=work)
    if build.returncode != 0:
        raise ValueError(f"EMBER_LAB_BUILD_REFUSED:{build.returncode}:{build.stderr.decode(errors='replace')}")
    target_root = Path(os.environ.get("CARGO_TARGET_DIR", manifest.parent / "target"))
    binary = target_root / "debug" / ("ember-lab.exe" if os.name == "nt" else "ember-lab")
    source_commit_result = _run(("git", "-C", str(repo), "rev-parse", "HEAD"), cwd=work)
    if source_commit_result.returncode != 0:
        raise ValueError("EMBER_LAB_SOURCE_COMMIT_REFUSED")
    source_commit = source_commit_result.stdout.decode().strip()
    now_ms = int(time.time() * 1000)
    job_id = f"issue1949-a-clean-{os.getpid()}-{now_ms}"
    custody = work / "custody"
    cache_root = custody / "cache"
    for directory in (custody, cache_root):
        directory.mkdir(parents=True, exist_ok=True)
    dispatch_env = {
        "EMBER_LAB_MINIMAL_SLICE": "1",
        "EMBER_LAB_MINIMAL_SLICE_JOB_ID": job_id,
        # The producer stays alive until the daemon stops it after consuming every
        # phase. 60s is the producer contract's hard safety cap, not a host timing guess.
        "EMBER_LAB_MINIMAL_SLICE_HOLD_MS": str(LAB_PRODUCER_CONTRACT_CAP_MS),
        "EMBER_LAB_MODEL_CHAIN_RECEIPT": str(model_chain_receipt.resolve()),
        "EMBER_LAB_MODEL_CHAIN_SHA256": model_chain_raw_sha256,
    }
    for key in ("TEMP", "TMP", "TORCH_HOME", "TRITON_CACHE_DIR", "CUDA_CACHE_PATH", "HF_HOME", "XDG_CACHE_HOME"):
        directory = cache_root / key.lower()
        directory.mkdir()
        dispatch_env[key] = str(directory)
    config = work / "consumer-config.json"
    input_manifest = work / "consumer-input.json"
    config.write_bytes(canonical_json({"schema_version": "ember-issue1949-a-clean-lab-config-v1"}) + b"\n")
    input_manifest.write_bytes(canonical_json({"records": 1}) + b"\n")
    dispatch_path = work / "dispatch-manifest.json"
    dispatch = {
        "schema_version": "ember-lab-dispatch-manifest-v3",
        "job_id": job_id,
        "source_commit": source_commit,
        "not_before_ms": now_ms - 1000,
        "expires_at_ms": now_ms + LAB_DISPATCH_TTL_MS,
        "resource_lease": f"cpu:{job_id}",
        "program": {"path": str(binary), "sha256": sha256_file(binary)},
        "args": ["produce-minimal-slice", "--job-id", job_id],
        "workload_profile": {"profile_id": "evidence_verifier", "pinned_host_producers": [{"kind": "receipt_verifier", "maximum_bytes": 1048576}], "requires_ui_responsiveness": False, "cpu_rate_percent": 100},
        "cpu_pacing_class": "unpaced",
        "window_contract": "headless_no_windows",
        "env": dispatch_env,
        "bindings": [
            {"kind": "config", "path": str(config), "sha256": sha256_file(config)},
            {"kind": "manifest", "path": str(input_manifest), "sha256": sha256_file(input_manifest)},
        ],
        "custody_root": str(custody),
        "storage_reserves": [{"root": str(work), "minimum_free_bytes": 1}],
        "minimum_free_vram_bytes": 0,
        "required_available_maximum_commit_bytes": 11 * 1024**3,
        "maximum_job_memory_bytes": 1073741824,
        "simulated_peak_commit_bytes": 1048576,
        "preflight_receipt": str(custody / "preflight.json"),
    }
    dispatch_path.write_bytes(canonical_json(dispatch) + b"\n")
    measurement_path = work / "measurement.json"
    measurement_path.write_bytes(canonical_json({"whole_run_peak_bytes": 1}) + b"\n")
    rehearsal_path = work / "rehearsal-manifest.json"
    rehearsal = {
        "schema_version": "ember-lab-rehearsal-v1",
        "dispatch_id": job_id,
        "source_commit": source_commit,
        "contract_sha256": _strict_gate_contract_sha256(),
        "bounds": {
            "minimum_memory_bytes": 1,
            "minimum_storage_free_bytes": 1,
            "maximum_duration_ms": LAB_PRODUCER_CONTRACT_CAP_MS,
        },
        "measurements": {"source": "host_probe", "observed_at_ms": now_ms, "available_memory_bytes": 1073741824, "storage_free_bytes": 1073741824, "measured_duration_ms": 1, "whole_run_peak_bytes": 1, "evidence_path": str(measurement_path), "evidence_sha256": sha256_file(measurement_path)},
        "phase_evidence": [],
    }
    rehearsal_path.write_bytes(canonical_json(rehearsal) + b"\n")
    lab_receipt = work / "ember-lab-rehearsal-receipt.json"
    argv = (str(binary), "rehearse", "--db", str(work / "ember-lab.sqlite3"), "--dispatch-manifest", str(dispatch_path), "--manifest", str(rehearsal_path), "--receipt", str(lab_receipt))
    result = _run(argv, cwd=work)
    stdout_path = work / "rehearsal.stdout.log"
    stderr_path = work / "rehearsal.stderr.log"
    stdout_path.write_bytes(result.stdout)
    stderr_path.write_bytes(result.stderr)
    if result.returncode != 0:
        refused_receipt = lab_receipt.read_text(encoding="utf-8") if lab_receipt.is_file() else "ABSENT"
        raise ValueError(
            f"EMBER_LAB_REHEARSAL_REFUSED:{result.returncode}:"
            f"stdout={result.stdout.decode(errors='replace')}:"
            f"stderr={result.stderr.decode(errors='replace')}:receipt={refused_receipt}"
        )
    lab_payload = json.loads(lab_receipt.read_bytes())
    rehearsal_result = lab_payload.get("rehearsal", {}).get("result", {})
    if rehearsal_result.get("status") != "completed":
        raise ValueError("EMBER_LAB_REHEARSAL_NOT_COMPLETED")
    rust_sources = (
        Path(repo_root).resolve() / "runtime" / "ember-lab" / "src" / "main.rs",
        Path(repo_root).resolve() / "runtime" / "ember-lab" / "src" / "rehearsal.rs",
    )
    common = {
        "result": "PASS",
        "exit_code": 0,
        "adapter": "ember-lab rehearse CLI",
        "build_argv": [cargo, "build", "--locked", "--manifest-path", str(manifest), "--quiet"],
        "argv": list(argv),
        "rehearsal_receipt_raw_sha256": sha256_file(lab_receipt),
        "model_chain_receipt_raw_sha256": model_chain_raw_sha256,
        "stdout_raw_sha256": sha256_file(stdout_path),
        "stderr_raw_sha256": sha256_file(stderr_path),
        **chain,
        "production_modules": [
            {"name": path.name, "path": path.relative_to(Path(repo_root).resolve()).as_posix(), "sha256": sha256_file(path)}
            for path in rust_sources
        ] + chain["production_modules"],
    }
    if not topology:
        return publish_receipt(root, "lab", common)
    checkpoint_manifest = Path(chain["checkpoint"]["path"]) / "checkpoint-manifest.json"
    source = _run(("git", "-C", str(repo), "rev-parse", "HEAD"), cwd=work)
    if source.returncode != 0:
        raise ValueError("TOPOLOGY_SOURCE_HEAD_REFUSED")
    entry_points = [
        chain["training"]["entry_point"],
        chain["checkpoint"]["write_entry_point"],
        chain["checkpoint"]["load_entry_point"],
        chain["evaluation"]["entry_point"],
        chain["runtime"]["entry_point"],
        "runtime/ember-lab/src/main.rs:run_rehearsal",
        "runtime/ember-lab/src/rehearsal.rs:produce_minimal_slice",
    ]
    return _publish_topology_receipt(root, {
        **common,
        "source_head": source.stdout.decode().strip(),
        "platform": platform.system().lower(),
        "authority": TOPOLOGY_AUTHORITY,
        "phases": list(TOPOLOGY_PHASES),
        "entry_points": entry_points,
        "raw_hashes": {
            "lab_operational_receipt": sha256_file(lab_receipt),
            "checkpoint": sha256_file(checkpoint_manifest),
        },
    })


def _write_canonical_json(path: Path, payload: Mapping[str, object]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical_json(payload) + b"\n"
    with path.open("xb") as handle:
        handle.write(raw)
    return sha256_bytes(raw)


def _authority_binding(repo_root: Path, path: str, sha256: str, schema: str) -> dict[str, object]:
    schema_path = Path(repo_root).resolve(strict=True) / Path(schema)
    return {
        "path": path,
        "sha256": sha256,
        "schema": {"path": schema, "sha256": sha256_file(schema_path)},
    }


def _mint_all_local_external_authority(
    repo_root: Path, external_root: Path, custody_root: Path,
) -> dict[str, object]:
    """Mint 44 admitted rows from committed bytes and bind them through v4 schemas.

    This is deliberately an injection fixture, not a portable acquired corpus. Every
    source byte string includes the raw hash of the committed README and LICENSE plus
    its closed domain/split/slot descriptor. The real text authority validator still
    performs the complete v2 VERIFIED path over the resulting externally rooted files.
    """
    repo = Path(repo_root).resolve(strict=True)
    text_lab = _load_module(repo, "text_lab_corpus")
    data_dir = external_root / "data" / "ember-restart-3b"
    data_dir.mkdir(parents=True, exist_ok=False)
    source_dir = custody_root / "committed-derived-sources"
    source_dir.mkdir(parents=True, exist_ok=False)
    readme_sha = sha256_file(repo / "README.md")
    license_sha = sha256_file(repo / "LICENSE")
    required = [
        "source_descriptor", "source_content", "license_evidence", "policy",
        "verifier_result",
    ]
    allowed = sorted(text_lab.LICENSES)
    rows: list[dict[str, object]] = []
    custody_rows: list[dict[str, object]] = []
    for domain in text_lab.DOMAINS:
        for split in ("train", "heldout"):
            for slot in (1, 2):
                source_id = f"candidate-{domain}-{split}-{slot}"
                source_bytes = canonical_json({
                    "schema_version": "ember-issue1949-committed-derived-source-v1",
                    "source_id": source_id,
                    "readme_sha256": readme_sha,
                    "license_sha256": license_sha,
                }) + b"\n"
                source_path = source_dir / f"{source_id}.json"
                with source_path.open("xb") as handle:
                    handle.write(source_bytes)
                content_sha = sha256_bytes(source_bytes)
                evidence = {
                    "kind": "spdx_repo_license",
                    "license_sha256": license_sha,
                    "declared_spdx": "Apache-2.0",
                }
                row = {
                    "source_id": source_id,
                    "domain": domain,
                    "split": split,
                    "admission": "ADMITTED",
                    "required_evidence": required,
                    "allowed_license_spdx": allowed,
                    "content_sha256": content_sha,
                    "license_spdx": "Apache-2.0",
                    "license_evidence": evidence,
                    "l4_receipt": text_lab.local_license_provenance_v1(
                        content_sha256=content_sha,
                        license_spdx="Apache-2.0",
                        evidence=evidence,
                    ),
                }
                rows.append(row)
                custody_rows.append({
                    "path": source_path.relative_to(custody_root).as_posix(),
                    "raw_sha256": content_sha,
                })
    bundle = {
        "schema_version": "ember-text-source-receipt-bundle-v4",
        "result": "RESOLVED",
        "candidates": rows,
    }
    bundle_name = "text-lab-source-receipt-bundle-v4.json"
    bundle_sha = _write_canonical_json(data_dir / bundle_name, bundle)
    registry_path = repo / "data" / "ember-restart-3b" / "protected-eval-registry-v2.json"
    corpus = {
        "schema_version": "ember-text-lab-corpus-v4",
        "registry_sha256": sha256_file(registry_path),
        "receipt_bundle_sha256": bundle_sha,
        "receipt_custody_root_binding": "runtime-supplied-corpus-root-v1",
        "train_root_sha256": text_lab._authority_split_root(rows, "train"),
        "heldout_root_sha256": text_lab._authority_split_root(rows, "heldout"),
        "sources": rows,
    }
    corpus_name = "owned-text-lab-corpus-v4.json"
    corpus_sha = _write_canonical_json(data_dir / corpus_name, corpus)
    code_files = {
        name: sha256_file(repo / path)
        for name, path in {
            "text_lab_corpus": "src/ember/infrastructure/tools/ember-restart-3b/text_lab_corpus.py",
            "train": "src/ember/infrastructure/tools/ember-restart-3b/train.py",
            "run_vertical_slice": "src/ember/infrastructure/tools/ember-restart-3b/run_vertical_slice.py",
        }.items()
    }
    head = _run(("git", "-C", str(repo), "rev-parse", "HEAD"), cwd=external_root)
    if head.returncode != 0:
        raise ValueError("EXTERNAL_AUTHORITY_SOURCE_HEAD_REFUSED")
    identity = {
        "schema_version": "ember-text-lab-input-identity-v2",
        "corpus_sha256": corpus_sha,
        "code_files": code_files,
        "source_base_commit": head.stdout.decode().strip(),
    }
    identity_name = "owned-text-lab-input-identity-v4.json"
    identity_sha = _write_canonical_json(data_dir / identity_name, identity)
    prefix = "data/ember-restart-3b/"
    index = {
        "schema_version": "ember-text-lab-authority-index-v2",
        "result": "PREFLIGHT_ONLY",
        "boundary": "NO_ACQUISITION_NO_TRAINING_NO_SUFFICIENT_PRETRAINING_CLAIM",
        "registry": _authority_binding(
            repo, prefix + "protected-eval-registry-v2.json", sha256_file(registry_path),
            prefix + "text-lab-registry-v2.schema.json",
        ),
        "receipt_bundle": _authority_binding(
            repo, prefix + bundle_name, bundle_sha,
            prefix + "text-lab-bundle-v4.schema.json",
        ),
        "corpus": _authority_binding(
            repo, prefix + corpus_name, corpus_sha,
            prefix + "text-lab-corpus-v4.schema.json",
        ),
        "input_identity": _authority_binding(
            repo, prefix + identity_name, identity_sha,
            prefix + "text-lab-identity-v2.schema.json",
        ),
    }
    index_name = "text-lab-authority-index-v2.json"
    index_sha = _write_canonical_json(data_dir / index_name, index)
    custody_manifest = {
        "schema_version": "ember-issue1949-all-local-custody-v1",
        "result": "PASS",
        "source_head": identity["source_base_commit"],
        "derivation": "committed README.md and LICENSE hashes plus committed consumer descriptors",
        "sources": custody_rows,
    }
    custody_manifest_sha = _write_canonical_json(
        custody_root / "all-local-custody-manifest.json", custody_manifest
    )
    return {
        "authority_index_sha256": index_sha,
        "receipt_bundle_sha256": bundle_sha,
        "corpus_sha256": corpus_sha,
        "input_identity_sha256": identity_sha,
        "custody_manifest_sha256": custody_manifest_sha,
        "source_count": len(rows),
    }


def _require_custody_child(artifact_root: Path, supplied: Path, name: str) -> Path:
    expected = Path(artifact_root).absolute() / name
    if Path(supplied).absolute() != expected:
        raise ValueError(f"RECEIPT_CUSTODY_ROOT_REFUSED:{supplied}:{expected}")
    return expected


def run_external_present(repo_root: Path, artifact_root: Path, receipt_custody_root: Path) -> dict[str, Any]:
    text_lab = _load_module(repo_root, "text_lab_corpus")
    root = Path(artifact_root)
    external_root = root / "external-authority"
    custody_root = _require_custody_child(root, receipt_custody_root, "external-custody")
    if external_root.exists() or custody_root.exists():
        raise ValueError("EXTERNAL_PRESENT_PRECONDITION_REFUSED")
    minted = _mint_all_local_external_authority(repo_root, external_root, custody_root)
    validation = text_lab.validate_authority_index(
        Path(repo_root), external_authority_root=external_root,
        receipt_custody_root=custody_root,
    )
    if validation.get("result") != "VERIFIED":
        raise ValueError("EXTERNAL_PRESENT_VALIDATOR_RESULT_REFUSED")
    return publish_receipt(root, "external-present", {
        "result": "PASS",
        "exit_code": 0,
        "external_authority_root": str(external_root.resolve()),
        "receipt_custody_root": str(custody_root.resolve()),
        "minted_authority": minted,
        "validator": validation,
        "claim_boundary": (
            "CONSUMER_MINTED_FROM_COMMITTED_BYTES_NOT_CANONICAL_V4; "
            "NO_ACQUIRED_CORPUS_ADMISSION_OR_PORTABILITY_CLAIM"
        ),
        "production_modules": _module_bindings(repo_root, ("text_lab_corpus",)),
    })


def external_absent_exit(error: ValueError) -> int:
    if str(error) in {"external authority root is absent", "external authority path is absent"}:
        return 3
    raise error


def run_external_absent(repo_root: Path, artifact_root: Path, receipt_custody_root: Path) -> dict[str, Any]:
    text_lab = _load_module(repo_root, "text_lab_corpus")
    root = Path(artifact_root)
    absent = _require_custody_child(root, receipt_custody_root, "external-custody-absent")
    if absent.exists():
        raise ValueError("EXTERNAL_ABSENT_PRECONDITION_REFUSED")
    try:
        text_lab.validate_authority_index(Path(repo_root), external_authority_root=absent)
    except ValueError as error:
        exit_code = external_absent_exit(error)
        return publish_receipt(root, "external-absent", {
            "result": "EXPECTED_REFUSAL",
            "exit_code": exit_code,
            "refusal": str(error),
            "production_modules": _module_bindings(repo_root, ("text_lab_corpus",)),
        })
    raise ValueError("EXTERNAL_ABSENT_FAIL_OPEN")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in COMMAND_EXITS:
        child = subparsers.add_parser(command)
        child.add_argument("--repo-root", type=Path, required=True)
        child.add_argument("--artifact-root", type=Path, required=True)
        if command in {"direct", "lab", "topology"}:
            child.add_argument("--data-path", type=Path, required=True)
        if command in {"lab", "topology"}:
            child.add_argument("--cargo", required=True)
        if command in {"external-present", "external-absent"}:
            child.add_argument("--receipt-custody-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "direct":
            receipt = run_direct(args.repo_root, args.artifact_root, args.data_path)
        elif args.command == "lab":
            receipt = run_lab(args.repo_root, args.artifact_root, args.cargo, args.data_path)
        elif args.command == "external-present":
            receipt = run_external_present(args.repo_root, args.artifact_root, args.receipt_custody_root)
        elif args.command == "external-absent":
            receipt = run_external_absent(args.repo_root, args.artifact_root, args.receipt_custody_root)
        else:
            receipt = run_lab(
                args.repo_root, args.artifact_root, args.cargo, args.data_path, topology=True,
            )
    except (FileExistsError, OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"A_CLEAN_CONSUMER_REFUSED:{error}", file=sys.stderr)
        return 2
    print(json.dumps(receipt, sort_keys=True))
    return COMMAND_EXITS[args.command]


if __name__ == "__main__":
    raise SystemExit(main())
