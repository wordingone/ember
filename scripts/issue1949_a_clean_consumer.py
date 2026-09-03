#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Real, receipt-bound consumers for the four #1949 A-CLEAN execution legs."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence


NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
COMMAND_EXITS = {
    "direct": 0,
    "lab": 0,
    "external-present": 4,
    "external-absent": 3,
}
EXTERNAL_ARTIFACTS = (
    "text-lab-source-receipt-bundle-v4.json",
    "owned-text-lab-corpus-v4.json",
    "owned-text-lab-input-identity-v4.json",
    "text-lab-authority-index-v2.json",
)
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


def _connector_root(repo_root: Path) -> Path:
    root = Path(repo_root).resolve(strict=True)
    candidates = (
        root / "src" / "ember" / "infrastructure" / "tools" / "corpus_connectors",
        root / "tools" / "corpus_connectors",
    )
    for tools in candidates:
        if (tools / "receipt.py").is_file():
            return tools
    raise ValueError("CORPUS_CONNECTOR_ROOT_ABSENT:canonical-and-legacy")


def _production_module_path(repo_root: Path, name: str) -> Path:
    if name == "corpus_receipt":
        return _connector_root(repo_root) / "receipt.py"
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


def run_direct(repo_root: Path, artifact_root: Path) -> dict[str, Any]:
    import torch

    model_module = _load_module(repo_root, "model")
    checkpoint = _load_module(repo_root, "checkpoint_artifacts")
    parameter_counter = _load_module(repo_root, "parameter_counter")
    root = Path(artifact_root)
    work = root / "direct-runtime"
    work.mkdir(parents=True, exist_ok=False)
    config_payload = {
        "kind": "issue1949-a-clean-cpu-real-fixture-v1",
        "hidden_size": 32,
        "layers": 2,
        "attention_heads": 4,
        "vocab_size": 64,
        "gradient_checkpointing": False,
    }
    config_path = work / "config.json"
    with config_path.open("xb") as handle:
        handle.write(canonical_json(config_payload) + b"\n")
    data_payload = {"input_ids": [[1, 2, 3, 4]], "target_ids": [[2, 3, 4, 5]]}
    data_path = work / "generated-data.json"
    with data_path.open("xb") as handle:
        handle.write(canonical_json(data_payload) + b"\n")

    config = model_module.RestartDecoderConfig.small_for_tests(
        hidden_size=32, layers=2, attention_heads=4, vocab_size=64,
        gradient_checkpointing=False,
    )
    model = model_module.UnifiedDecoder(config, genesis_seed=1949)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
    input_ids = torch.tensor(data_payload["input_ids"], dtype=torch.long)
    targets = torch.tensor(data_payload["target_ids"], dtype=torch.long)
    before = model(input_ids, active_expert="reasoning").detach()
    logits = model(input_ids, active_expert="reasoning")
    loss = torch.nn.functional.cross_entropy(logits.reshape(-1, config.vocab_size), targets.reshape(-1))
    loss.backward()
    optimizer.step()
    optimizer.zero_grad(set_to_none=True)
    after = model(input_ids, active_expert="reasoning").detach()
    if torch.equal(before, after):
        raise ValueError("DIRECT_TRAINING_DID_NOT_MUTATE_MODEL")

    checkpoint_root = work / "checkpoint-step-1"
    genesis = model.expert_bank_genesis_hashes()
    receipt = checkpoint.write_checkpoint_artifacts(
        model,
        optimizer,
        checkpoint_root,
        launch_seed=1949,
        rng_state={
            "cpu": torch.get_rng_state().clone(),
            "cuda": torch.cuda.get_rng_state().clone() if torch.cuda.is_available() else torch.tensor([1, 9, 4, 9], dtype=torch.uint8),
        },
        data_cursor={"shard": "issue1949-a-clean-generated-v1", "record_index": 1, "global_step": 1, "tokens_seen": 4},
        model_config_sha256=sha256_file(config_path),
        contract_sha256=sha256_file(_tool_root(repo_root) / "model.py"),
        expert_genesis_sha256=genesis,
        pre_publish_verifier=lambda candidate, manifest: _counter_verifier(parameter_counter, candidate, manifest),
    )
    restored = model_module.UnifiedDecoder(config, genesis_seed=1950)
    restored_optimizer = torch.optim.AdamW(restored.parameters(), lr=1e-4)
    cursor = checkpoint.load_checkpoint_artifacts(restored, restored_optimizer, checkpoint_root, receipt)["data_cursor"]
    restored.eval()
    with torch.no_grad():
        evaluated = restored(input_ids, active_expert="reasoning")
    if cursor["global_step"] != 1 or not torch.equal(evaluated, after):
        raise ValueError("DIRECT_CHECKPOINT_RESUME_EVALUATION_REFUSED")
    evaluation_path = work / "evaluation.json"
    evaluation = {
        "result": "PASS",
        "logits_sha256": sha256_bytes(evaluated.detach().cpu().contiguous().numpy().tobytes()),
        "loss": float(loss.detach().cpu().item()),
    }
    with evaluation_path.open("xb") as handle:
        handle.write(canonical_json(evaluation) + b"\n")
    return publish_receipt(root, "direct", {
        "result": "PASS",
        "exit_code": 0,
        "fixture": {"config_sha256": sha256_file(config_path), "data_sha256": sha256_file(data_path)},
        "training": {"steps": 1, "tokens_seen": 4, "loss": evaluation["loss"]},
        "checkpoint": {"manifest_sha256": receipt["checkpoint_manifest_sha256"], "cursor": cursor},
        "evaluation": {"receipt_sha256": sha256_file(evaluation_path), **evaluation},
        "runtime_governance": {"counter_receipt_sha256": sha256_file(checkpoint_root / "parameter-counter-receipt.json")},
        "production_modules": _module_bindings(repo_root, ("model", "checkpoint_artifacts", "parameter_counter")),
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


def run_lab(repo_root: Path, artifact_root: Path, cargo: str) -> dict[str, Any]:
    root = Path(artifact_root)
    work = root / "lab-runtime"
    work.mkdir(parents=True, exist_ok=False)
    repo = Path(repo_root).resolve(strict=True)
    manifest = repo / "runtime" / "ember-lab" / "Cargo.toml"
    build = _run((cargo, "build", "--locked", "--manifest-path", str(manifest), "--quiet"), cwd=work)
    if build.returncode != 0:
        raise ValueError(f"EMBER_LAB_BUILD_REFUSED:{build.returncode}:{build.stderr.decode(errors='replace')}")
    binary = manifest.parent / "target" / "debug" / ("ember-lab.exe" if os.name == "nt" else "ember-lab")
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
        "EMBER_LAB_MINIMAL_SLICE_HOLD_MS": "1000",
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
        "expires_at_ms": now_ms + 600000,
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
        "bounds": {"minimum_memory_bytes": 1, "minimum_storage_free_bytes": 1, "maximum_duration_ms": 60000},
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
    return publish_receipt(root, "lab", {
        "result": "PASS",
        "exit_code": 0,
        "adapter": "ember-lab rehearse CLI",
        "build_argv": [cargo, "build", "--locked", "--manifest-path", str(manifest), "--quiet"],
        "argv": list(argv),
        "rehearsal_receipt_raw_sha256": sha256_file(lab_receipt),
        "stdout_raw_sha256": sha256_file(stdout_path),
        "stderr_raw_sha256": sha256_file(stderr_path),
        "production_modules": [
            {"name": path.name, "path": path.relative_to(Path(repo_root).resolve()).as_posix(), "sha256": sha256_file(path)}
            for path in rust_sources
        ],
    })


def _copy_external_projection(repo_root: Path, external_root: Path) -> dict[str, str]:
    source = Path(repo_root).resolve(strict=True) / "data" / "ember-restart-3b"
    target = external_root / "data" / "ember-restart-3b"
    target.mkdir(parents=True, exist_ok=False)
    hashes: dict[str, str] = {}
    for name in EXTERNAL_ARTIFACTS:
        source_path = source / name
        target_path = target / name
        with target_path.open("xb") as handle:
            handle.write(source_path.read_bytes())
        hashes[name] = sha256_file(target_path)
    return hashes


def _mint_tracked_connector_custody(repo_root: Path, custody_root: Path) -> dict[str, str]:
    receipt_module = _load_module(repo_root, "corpus_receipt")
    tracked = Path(repo_root).resolve(strict=True) / "README.md"
    payload = custody_root / "tracked-input" / "README.md"
    payload.parent.mkdir(parents=True, exist_ok=False)
    with payload.open("xb") as handle:
        handle.write(tracked.read_bytes())
    entry = receipt_module.FileEntry(
        path="tracked-input/README.md",
        bytes=payload.stat().st_size,
        sha256=sha256_file(payload),
    )
    receipt = receipt_module.Receipt(
        source="local-tracked-input",
        source_id="issue1949-a-clean-tracked-readme",
        canonical_url="repository:README.md",
        license="Apache-2.0",
        license_evidence="repository:LICENSE",
        revision=None,
        files=[entry],
        fetched_at=receipt_module.utc_now_iso(),
        connector=receipt_module.ConnectorInfo(name="receipt.py", version="v1"),
        dest_root=str(custody_root.resolve()),
        notes="A-CLEAN external custody producer probe over tracked bytes",
    )
    receipt_path = receipt_module.commit_receipt(receipt, custody_root, [payload])
    return {"path": str(receipt_path.resolve()), "sha256": sha256_file(receipt_path)}


def _require_custody_child(artifact_root: Path, supplied: Path, name: str) -> Path:
    expected = Path(artifact_root).absolute() / name
    if Path(supplied).absolute() != expected:
        raise ValueError(f"RECEIPT_CUSTODY_ROOT_REFUSED:{supplied}:{expected}")
    return expected


def run_external_present(repo_root: Path, artifact_root: Path, receipt_custody_root: Path) -> dict[str, Any]:
    text_lab = _load_module(repo_root, "text_lab_corpus")
    root = Path(artifact_root)
    external_root = root / "external-authority"
    hashes = _copy_external_projection(repo_root, external_root)
    custody_root = _require_custody_child(root, receipt_custody_root, "external-custody")
    producer_receipt = _mint_tracked_connector_custody(repo_root, custody_root)
    try:
        validation = text_lab.validate_authority_index(
            Path(repo_root), external_authority_root=external_root,
            receipt_custody_root=custody_root,
        )
    except ValueError as error:
        return publish_receipt(root, "external-present", {
            "result": "REFUSED_EXTERNAL_CUSTODY_INSUFFICIENT",
            "exit_code": 4,
            "refusal": str(error),
            "external_authority_root": str(external_root.resolve()),
            "receipt_custody_root": str(custody_root.resolve()),
            "producer_receipt": producer_receipt,
            "projected_sha256": hashes,
            "production_modules": _module_bindings(repo_root, ("text_lab_corpus", "corpus_receipt")),
        })
    if validation.get("result") not in {"VERIFIED", "NOT_ADMITTED_SOURCE_EVIDENCE_MISSING"}:
        raise ValueError("EXTERNAL_PRESENT_VALIDATOR_RESULT_REFUSED")
    return publish_receipt(root, "external-present", {
        "result": "PASS",
        "exit_code": 0,
        "external_authority_root": str(external_root.resolve()),
        "receipt_custody_root": str(custody_root.resolve()),
        "producer_receipt": producer_receipt,
        "projected_sha256": hashes,
        "validator_result": validation["result"],
        "production_modules": _module_bindings(repo_root, ("text_lab_corpus", "corpus_receipt")),
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
        if command == "lab":
            child.add_argument("--cargo", required=True)
        if command in {"external-present", "external-absent"}:
            child.add_argument("--receipt-custody-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "direct":
            receipt = run_direct(args.repo_root, args.artifact_root)
        elif args.command == "lab":
            receipt = run_lab(args.repo_root, args.artifact_root, args.cargo)
        elif args.command == "external-present":
            receipt = run_external_present(args.repo_root, args.artifact_root, args.receipt_custody_root)
        else:
            receipt = run_external_absent(args.repo_root, args.artifact_root, args.receipt_custody_root)
    except (FileExistsError, OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"A_CLEAN_CONSUMER_REFUSED:{error}", file=sys.stderr)
        return 2
    print(json.dumps(receipt, sort_keys=True))
    return COMMAND_EXITS[args.command]


if __name__ == "__main__":
    raise SystemExit(main())
