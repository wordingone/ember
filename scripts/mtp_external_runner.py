#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Parent-side authority for MTP execution candidates."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
import time
from types import SimpleNamespace
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from mtp_parameter_manifest import _GOVERNED_RUNNER_CAPABILITY, _finalize_governed_execution_receipt, validate_parameter_manifest
Runner = Callable[..., int]

def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def _canonical_sha256(value: Mapping[str, Any], *, omit: str | None = None) -> str:
    payload = dict(value)
    if omit is not None:
        payload.pop(omit, None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

def _load_disk_budget_runner() -> tuple[Callable[..., int], Path, object]:
    runner_path = Path(__file__).resolve().parents[1] / "tools" / "ember-restart-3b" / "disk_budget_runner.py"
    spec = importlib.util.spec_from_file_location("ember_owned_disk_budget_runner", runner_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the owned disk-budget runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.run_budgeted, runner_path, module

def _disk_projection(receipt: Mapping[str, Any]) -> dict[str, Any]:
    required = {"schema_version", "receipt_sha256", "outcome", "child_exit_code", "runner_exit_code", "command", "child_pid", "child_start_time_ns", "child_executable_sha256"}
    if not required.issubset(receipt):
        raise ValueError("governed disk-budget receipt is incomplete")
    projection = {key: receipt[key] for key in required}
    if projection["schema_version"] != 7 or projection["outcome"] != "COMPLETED":
        raise ValueError("governed disk-budget runner did not complete")
    if projection["child_exit_code"] != 0 or projection["runner_exit_code"] != 0:
        raise ValueError("governed disk-budget runner exited unsuccessfully")
    if type(projection["child_pid"]) is not int or projection["child_pid"] <= 0:
        raise ValueError("governed disk-budget child identity is invalid")
    if type(projection["child_start_time_ns"]) is not int or projection["child_start_time_ns"] <= 0:
        raise ValueError("governed disk-budget child identity is invalid")
    if not isinstance(projection["command"], list) or not projection["command"]:
        raise ValueError("governed disk-budget command is invalid")
    if not isinstance(projection["child_executable_sha256"], str) or len(projection["child_executable_sha256"]) != 64:
        raise ValueError("governed disk-budget executable identity is invalid")
    if projection["receipt_sha256"] != _canonical_sha256(receipt, omit="receipt_sha256"):
        raise ValueError("governed disk-budget receipt hash mismatch")
    return projection

def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)

def run_external_candidate(*, manifest_path: Path | str, candidate_path: Path | str, receipt_path: Path | str, source_path: Path | str, config_path: Path | str, command: Sequence[str], cwd: Path | str | None = None, write_roots: Mapping[str, Path | str] | None = None, max_write_gib: Mapping[str, float] | None = None, runner_receipt_path: Path | str | None = None, runner: Runner | None = None) -> dict[str, Any]:
    """Run one child through the governed runner and persist parent authority."""
    del cwd
    manifest_file = Path(manifest_path).resolve(strict=True)
    candidate_file = Path(candidate_path).resolve()
    receipt_file = Path(receipt_path).resolve()
    source_file = Path(source_path).resolve(strict=True)
    config_file = Path(config_path).resolve(strict=True)
    command_list = [str(item) for item in command]
    if not command_list or any(not item or "\x00" in item for item in command_list):
        raise ValueError("external command must contain nonempty strings")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    validate_parameter_manifest(manifest)
    source_sha_before = _sha256_file(source_file)
    config_sha_before = _sha256_file(config_file)
    if candidate_file.exists():
        raise ValueError("execution candidate must be absent before spawn")
    runner_receipt_file = Path(runner_receipt_path).resolve() if runner_receipt_path is not None else receipt_file.with_name(receipt_file.stem + ".disk.json")
    run_roots = {str(k): Path(v).resolve() for k, v in (write_roots or {}).items()}
    run_budgets = dict(max_write_gib or {})
    runner_module = None
    observed_process: list[dict[str, int | str]] = []
    if runner is None:
        if not run_roots or not run_budgets:
            raise ValueError("production governed runner requires write roots and budgets")
        runner, runner_module_path, runner_module = _load_disk_budget_runner()
    else:
        runner_module_path = Path(__file__).resolve()
    invocation_started_ns = time.time_ns()
    if runner_module is None:
        runner(command_list, run_budgets, runner_receipt_file, write_roots=run_roots)
    else:
        # Keep process observation at the external launcher boundary. The
        # owned disk runner remains the only production child launcher, while
        # this isolated proxy records the exact Popen identity it created.
        original_subprocess = runner_module.subprocess
        original_popen = original_subprocess.Popen

        def observed_popen(*args: Any, **kwargs: Any) -> Any:
            process = original_popen(*args, **kwargs)
            observed_process.append(
                {
                    "pid": int(process.pid),
                    "start_time_ns": time.time_ns(),
                    "executable_sha256": _sha256_file(
                        Path(os.sys.executable).resolve(strict=True)
                    ),
                }
            )
            return process

        runner_module.subprocess = SimpleNamespace(
            Popen=observed_popen,
            run=original_subprocess.run,
            DEVNULL=original_subprocess.DEVNULL,
            TimeoutExpired=original_subprocess.TimeoutExpired,
        )
        try:
            runner(command_list, run_budgets, runner_receipt_file, write_roots=run_roots)
        finally:
            runner_module.subprocess = original_subprocess
    if not runner_receipt_file.is_file():
        raise ValueError("governed disk-budget receipt was not produced")
    disk_receipt = json.loads(runner_receipt_file.read_text(encoding="utf-8"))
    if runner_module is not None:
        if len(observed_process) != 1:
            raise ValueError("governed runner must create exactly one observed child")
        observed = observed_process[0]
        for field, value in (
            ("child_pid", observed["pid"]),
            ("child_start_time_ns", observed["start_time_ns"]),
            ("child_executable_sha256", observed["executable_sha256"]),
        ):
            if field in disk_receipt and disk_receipt[field] != value:
                raise ValueError(f"governed runner {field} mismatch")
            disk_receipt[field] = value
        disk_receipt["receipt_sha256"] = _canonical_sha256(
            disk_receipt, omit="receipt_sha256"
        )
        _write_json_atomic(runner_receipt_file, disk_receipt)
    projection = _disk_projection(disk_receipt)
    if projection["command"] != command_list:
        raise ValueError("governed disk-budget command mismatch")
    if not candidate_file.is_file():
        raise ValueError("execution candidate was not created by the child")
    if candidate_file.stat().st_mtime_ns < invocation_started_ns - 1_000_000_000:
        raise ValueError("execution candidate was not created during this run")
    candidate = json.loads(candidate_file.read_text(encoding="utf-8"))
    source_sha_after = _sha256_file(source_file)
    config_sha_after = _sha256_file(config_file)
    if source_sha_before != source_sha_after:
        raise ValueError("external source_sha256 changed during execution")
    if config_sha_before != config_sha_after:
        raise ValueError("external config_sha256 changed during execution")
    if candidate.get("source_sha256") != source_sha_before:
        raise ValueError("external source_sha256 mismatch")
    if candidate.get("config_sha256") != config_sha_before:
        raise ValueError("external config_sha256 mismatch")
    parent = _finalize_governed_execution_receipt(manifest, candidate, command=command_list, process_identity={"pid": projection["child_pid"], "start_time_ns": projection["child_start_time_ns"], "executable_sha256": projection["child_executable_sha256"]}, child_exit_code=int(projection["child_exit_code"]), verifier_id="ember-mtp-external-runner-v1", verifier_sha256=_sha256_file(Path(__file__).resolve()), disk_budget_receipt=projection, disk_budget_receipt_sha256=projection["receipt_sha256"], runner_module_sha256=_sha256_file(runner_module_path), capability=_GOVERNED_RUNNER_CAPABILITY)
    _write_json_atomic(receipt_file, parent)
    return parent
