# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

"""Scratch-only #1413 launch-readiness gate; not product authority."""

import hashlib
import ctypes
import json
import math
import os
import re
import secrets
import subprocess
import sys
import time
import tempfile
from pathlib import Path


_SHA = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_SOURCE_RECEIPT_SCHEMA = "llmq-governed-source-receipt-v1"
_SOURCE_MANIFEST_SCHEMA = "llmq-source-manifest-v1"
_BUILD_RECEIPT_SCHEMA = "ember-lab-build-receipt-v1"
_BENCHMARK_RECEIPT_SCHEMA = "ember-lab-benchmark-receipt-v1"
_DAEMON_RECEIPT_SCHEMA = "ember-lab-operational-receipt-v1"
_ASSESSMENT_EVIDENCE_SCHEMA = "ember-lab-assessment-evidence-v1"
_SCHEDULE_ALARM_SCHEMA = "ember-lab-schedule-alarm-state-v1"
_GOVERNED_ORIGIN = "https://github.com/IST-DASLab/llmq.git"
_ADOPTION_DESIGN_PATH = "docs/domains/governance/spec/llmq/adoption-design-v1.json"
_MECHANISM_ATTRIBUTION_PATH = "docs/domains/governance/spec/llmq/mechanism-attribution-v1.json"
_LLMQ_PIN = "f5b234c4b95009dfe43ee15181be93bc3fb34563"
_EMBER_LAB_SOURCE_PATH = "runtime/ember-lab/src/lib.rs"
_PIPE_PREFIX = r"\\.\pipe\ember-lab-"
_OPERATOR_PIPE_PREFIX = r"\\.\pipe\ember-operator-"
_MAX_RPC_FRAME_BYTES = 64 * 1024
# Private in-process marker: only _acquire_live_daemon_assessment may mint this.
# JSON packets and caller-authored dictionaries cannot reproduce daemon custody.
_DAEMON_AUTHORITY_TOKEN = object()


def _configured_ember_lab_pipe() -> str | None:
    pipe_name = os.environ.get("EMBER_LAB_PIPE")
    if (
        not isinstance(pipe_name, str)
        or not pipe_name.startswith(_PIPE_PREFIX)
        or pipe_name.startswith(_OPERATOR_PIPE_PREFIX)
        or len(pipe_name) > 240
        or any(value in pipe_name for value in ("\r", "\n", "\0"))
    ):
        return None
    return pipe_name


def _rpc_export_assessment_direct(pipe_name: str, job_id: str, directory: Path) -> tuple[dict, str, Path]:
    """Call one resident daemon over one server-authenticated pipe handle."""
    if os.name != "nt":
        raise OSError("Ember Lab named-pipe assessment is Windows-only")
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create_file.restype = wintypes.HANDLE
    get_server_pid = kernel32.GetNamedPipeServerProcessId
    get_server_pid.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
    get_server_pid.restype = wintypes.BOOL
    open_process = kernel32.OpenProcess
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE
    query_image = kernel32.QueryFullProcessImageNameW
    query_image.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    query_image.restype = wintypes.BOOL
    write_file = kernel32.WriteFile
    write_file.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    write_file.restype = wintypes.BOOL
    read_file = kernel32.ReadFile
    read_file.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    read_file.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    handle = create_file(pipe_name, 0xC0000000, 0, None, 3, 0, None)
    invalid_handle = ctypes.c_void_p(-1).value
    if handle == invalid_handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        server_pid = wintypes.ULONG()
        if not get_server_pid(handle, ctypes.byref(server_pid)):
            raise ctypes.WinError(ctypes.get_last_error())
        process = open_process(0x1000, False, server_pid.value)
        if not process:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            capacity = wintypes.DWORD(32768)
            image = ctypes.create_unicode_buffer(capacity.value)
            if not query_image(process, 0, image, ctypes.byref(capacity)):
                raise ctypes.WinError(ctypes.get_last_error())
            server_binary_sha = hashlib.sha256(Path(image.value).read_bytes()).hexdigest()
        finally:
            close_handle(process)

        request_id = f"llmq-readiness-{secrets.token_hex(16)}"
        request = (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "export_assessment_evidence",
                    "params": {"job_id": job_id, "directory": str(directory)},
                },
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
        if len(request) > _MAX_RPC_FRAME_BYTES:
            raise OSError("Ember Lab RPC request exceeds frame limit")
        written = wintypes.DWORD()
        if not write_file(handle, request, len(request), ctypes.byref(written), None) or written.value != len(request):
            raise ctypes.WinError(ctypes.get_last_error())
        raw = bytearray()
        while b"\n" not in raw:
            chunk = ctypes.create_string_buffer(4096)
            read = wintypes.DWORD()
            ok = read_file(handle, chunk, len(chunk), ctypes.byref(read), None)
            if read.value:
                raw.extend(chunk.raw[: read.value])
            if len(raw) > _MAX_RPC_FRAME_BYTES:
                raise OSError("Ember Lab RPC response exceeds frame limit")
            if not ok and ctypes.get_last_error() != 234:
                raise ctypes.WinError(ctypes.get_last_error())
        line, trailing = bytes(raw).split(b"\n", 1)
        if trailing.strip():
            raise OSError("Ember Lab RPC returned multiple frames")
        response = json.loads(line.decode("utf-8", errors="strict"))
        if (
            not isinstance(response, dict)
            or set(response) != {"jsonrpc", "id", "result"}
            or response.get("jsonrpc") != "2.0"
            or response.get("id") != request_id
            or not isinstance(response.get("result"), dict)
        ):
            raise OSError("Ember Lab RPC response is not the requested result")
        return response["result"], server_binary_sha, Path(image.value)
    finally:
        close_handle(handle)


def _rpc_export_assessment(pipe_name: str, job_id: str, directory: Path) -> tuple[dict, str, Path]:
    """Run blocking Win32 pipe I/O in an owned, deadline-bounded worker."""
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                str(Path(__file__).resolve()),
                "--private-ember-lab-assessment-rpc",
                pipe_name,
                job_id,
                str(directory),
            ],
            capture_output=True,
            check=False,
            shell=False,
            creationflags=creationflags,
            timeout=10,
        )
    except subprocess.TimeoutExpired as error:
        raise OSError("Ember Lab RPC exceeded its end-to-end deadline") from error
    if completed.returncode != 0 or completed.stderr or len(completed.stdout) > _MAX_RPC_FRAME_BYTES:
        raise OSError("bounded Ember Lab RPC worker failed")
    value = json.loads(completed.stdout.decode("utf-8", errors="strict"))
    if not isinstance(value, dict) or set(value) != {"result", "server_binary_sha256", "server_binary_path"}:
        raise OSError("bounded Ember Lab RPC worker returned an invalid envelope")
    digest = value.get("server_binary_sha256")
    path = value.get("server_binary_path")
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest) or not isinstance(path, str):
        raise OSError("bounded Ember Lab RPC worker returned an invalid identity")
    return value["result"], digest, Path(path)


def _canonical_ember_lab_binary(repository_root: Path) -> Path | None:
    """Resolve the one repository-governed daemon binary, never a packet/env path."""
    exe_name = "ember-lab.exe" if os.name == "nt" else "ember-lab"
    root = repository_root.resolve(strict=True)
    candidates = (
        root / "runtime" / "ember-lab" / "target" / "release" / exe_name,
        root / "runtime" / "ember-lab" / "target" / "debug" / exe_name,
    )
    for candidate in candidates:
        try:
            if _has_reparse_component(candidate, root):
                continue
            resolved = candidate.resolve(strict=True)
            if resolved.is_file() and resolved.is_relative_to(root):
                return resolved
        except OSError:
            continue
    return None


def _canonical_ember_lab_source_sha256(repository_root: Path) -> str | None:
    """Reproduce Rust's length-delimited daemon source identity over canonical files."""
    root = repository_root.resolve(strict=True)
    relative_sources = (
        "runtime/ember-lab/src/lib.rs",
        "runtime/ember-lab/src/data_catalog.rs",
        "runtime/ember-lab/src/rpc.rs",
        "runtime/ember-lab/src/main.rs",
        "runtime/ember-lab/src/training_verify.rs",
        "runtime/ember-lab/Cargo.toml",
        "runtime/ember-lab/Cargo.lock",
    )
    digest = hashlib.sha256()
    try:
        for relative in relative_sources:
            path = root / relative
            if _has_reparse_component(path, root) or not path.is_file():
                return None
            raw = path.read_bytes()
            digest.update(len(raw).to_bytes(8, "little"))
            digest.update(raw)
    except OSError:
        return None
    return digest.hexdigest()


def _acquire_live_daemon_assessment(repository_root: Path, job_id: object) -> dict | None:
    """Fetch and reopen a fresh daemon export; never trust packet locators."""
    pipe_name = _configured_ember_lab_pipe()
    if pipe_name is None or not isinstance(job_id, str) or not job_id:
        return None
    try:
        canonical_source_sha = _canonical_ember_lab_source_sha256(repository_root)
        daemon_source_commit = _run_git(repository_root, "rev-parse", "HEAD")
        if canonical_source_sha is None or not isinstance(daemon_source_commit, str) or not _SHA.fullmatch(daemon_source_commit):
            return None
        with tempfile.TemporaryDirectory(prefix="ember-llmq-assessment-") as temporary:
            directory = Path(temporary) / "daemon-export"
            result, server_binary_sha, server_binary_path = _rpc_export_assessment(pipe_name, job_id, directory)
            canonical_binary = _canonical_ember_lab_binary(repository_root)
            if canonical_binary is None:
                return None
            if (
                server_binary_path.resolve(strict=True) != canonical_binary
                or hashlib.sha256(canonical_binary.read_bytes()).hexdigest() != server_binary_sha
            ):
                return None
            expected_fields = {
                "schema", "ember_lab_identity", "preflight_receipt", "operational_receipt",
                "stdout_log", "stderr_log", "schedule_alarm_state",
            }
            identity = result.get("ember_lab_identity") if isinstance(result, dict) else None
            if (
                set(result) != expected_fields
                or result.get("schema") != _ASSESSMENT_EVIDENCE_SCHEMA
                or not isinstance(identity, dict)
                or set(identity) != {"binary_sha256", "source_sha256"}
                or identity.get("binary_sha256") != server_binary_sha
                or identity.get("source_sha256") != canonical_source_sha
            ):
                return None
            suffixes = {
                "preflight_receipt": ".preflight.json",
                "operational_receipt": ".operational.json",
                "stdout_log": ".stdout.log",
                "stderr_log": ".stderr.log",
                "schedule_alarm_state": ".schedule.json",
            }
            reopened: dict[str, bytes] = {}
            resolved_directory = directory.resolve(strict=True)
            for field, suffix in suffixes.items():
                artifact = result.get(field)
                if not isinstance(artifact, dict) or set(artifact) != {"path", "sha256"}:
                    return None
                digest = artifact.get("sha256")
                path_value = artifact.get("path")
                if not isinstance(digest, str) or not _DIGEST.fullmatch(digest) or not isinstance(path_value, str):
                    return None
                path = Path(path_value)
                if not path.is_absolute():
                    return None
                path = path.resolve(strict=True)
                if path.parent != resolved_directory or _has_reparse_component(path, resolved_directory):
                    return None
                raw = path.read_bytes()
                if path.name != f"{digest}{suffix}" or hashlib.sha256(raw).hexdigest() != digest:
                    return None
                reopened[field] = raw
            operational = json.loads(reopened["operational_receipt"].decode("utf-8", errors="strict"))
            preflight = json.loads(reopened["preflight_receipt"].decode("utf-8", errors="strict"))
            schedule = json.loads(reopened["schedule_alarm_state"].decode("utf-8", errors="strict"))
            preflight_program = preflight.get("program") if isinstance(preflight, dict) else None
            preflight_bindings = preflight.get("bindings") if isinstance(preflight, dict) else None
            if (
                not isinstance(preflight, dict)
                or set(preflight) != {
                    "schema_version", "result", "job_id", "source_commit", "observed_at_ms",
                    "not_before_ms", "expires_at_ms", "dispatch_manifest_sha256", "workload_profile",
                    "program", "bindings", "args_sha256", "env_sha256", "custody_root",
                    "storage_reserves", "vram_reserve", "maximum_job_memory_bytes", "host_commit",
                    "ember_lab_identity",
                }
                or preflight.get("schema_version") != "ember-lab-dispatch-preflight-v1"
                or preflight.get("result") != "PREFLIGHT_PASSED"
                or preflight.get("job_id") != job_id
                or preflight.get("ember_lab_identity") != identity
                or not isinstance(preflight.get("source_commit"), str)
                or not _SHA.fullmatch(preflight["source_commit"])
                or preflight.get("source_commit") != daemon_source_commit
                or not isinstance(preflight_program, dict)
                or set(preflight_program) != {"path", "sha256"}
                or not isinstance(preflight_program.get("path"), str)
                or not preflight_program["path"]
                or not isinstance(preflight_program.get("sha256"), str)
                or not _DIGEST.fullmatch(preflight_program["sha256"])
                or not isinstance(preflight_bindings, list)
                or not preflight_bindings
            ):
                return None
            expected_receipt_fields = {
                "schema", "ember_lab_identity", "job_id", "identity_sha256", "resource_lease",
                "state", "pid", "executable_identity", "restart_policy", "exit_code", "logs",
                "events", "outage_events", "scientific_capability_evidence",
            }
            logs = operational.get("logs") if isinstance(operational, dict) else None
            stdout_log = logs.get("stdout") if isinstance(logs, dict) else None
            stderr_log = logs.get("stderr") if isinstance(logs, dict) else None
            if (
                not isinstance(operational, dict)
                or set(operational) != expected_receipt_fields
                or operational.get("schema") != _DAEMON_RECEIPT_SCHEMA
                or operational.get("job_id") != job_id
                or operational.get("ember_lab_identity") != identity
                or operational.get("state") not in {"stopped", "exited", "failed"}
                or operational.get("exit_code") != 0
                or operational.get("scientific_capability_evidence") is not False
                or not isinstance(operational.get("pid"), int)
                or operational.get("pid", 0) <= 0
                or not isinstance(operational.get("executable_identity"), str)
                or not operational.get("executable_identity")
                or not isinstance(stdout_log, dict)
                or not isinstance(stderr_log, dict)
                or stdout_log.get("sealed") is not True
                or stderr_log.get("sealed") is not True
                or stdout_log.get("sha256") != result["stdout_log"]["sha256"]
                or stderr_log.get("sha256") != result["stderr_log"]["sha256"]
                or not isinstance(schedule, dict)
                or schedule.get("schema_version") != _SCHEDULE_ALARM_SCHEMA
                or schedule.get("ember_lab_identity") != identity
            ):
                return None
            return {
                "response": result,
                "operational_receipt": operational,
                "preflight_receipt": preflight,
                "preflight_receipt_bytes": reopened["preflight_receipt"],
                "preflight_receipt_sha256": hashlib.sha256(reopened["preflight_receipt"]).hexdigest(),
                "schedule_alarm_state": schedule,
                "stdout_bytes": reopened["stdout_log"],
                "stderr_bytes": reopened["stderr_log"],
                "server_binary_sha256": server_binary_sha,
                "canonical_source_sha256": canonical_source_sha,
                "_daemon_source_commit": daemon_source_commit,
                "_daemon_authority_token": _DAEMON_AUTHORITY_TOKEN,
            }
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError):
        return None


def _has_reparse_component(path: Path, root: Path) -> bool:
    """Reject symlink/junction/reparse components before resolving a custody path."""
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    current = root
    for part in relative.parts:
        current /= part
        try:
            stat_result = os.lstat(current)
        except OSError:
            return True
        if current.is_symlink() or (getattr(stat_result, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT):
            return True
    return False


def _safe_file(root: Path, relative_value: object) -> Path | None:
    if (
        not isinstance(relative_value, str)
        or not relative_value
        or Path(relative_value).is_absolute()
        or ".." in Path(relative_value).parts
    ):
        return None
    try:
        root = root.resolve(strict=True)
        candidate = root / relative_value
        if _has_reparse_component(candidate, root):
            return None
        candidate = candidate.resolve(strict=True)
    except OSError:
        return None
    return candidate if candidate.is_file() and candidate.is_relative_to(root) else None


def _safe_dir(root: Path, relative_value: object) -> Path | None:
    """Reopen a governed directory without crossing a reparse component."""
    if not isinstance(relative_value, str) or not relative_value or Path(relative_value).is_absolute() or ".." in Path(relative_value).parts:
        return None
    try:
        root = root.resolve(strict=True)
        candidate = root / relative_value
        if _has_reparse_component(candidate, root):
            return None
        candidate = candidate.resolve(strict=True)
    except OSError:
        return None
    return candidate if candidate.is_dir() and candidate.is_relative_to(root) else None


def _closed_json(path: Path) -> object:
    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON key")
            value[key] = item
        return value

    return json.loads(path.read_text(encoding="utf-8", errors="strict"), object_pairs_hook=unique_object)


def _valid_adoption_design(value: object) -> bool:
    expected_transfer = [
        {"mechanism": "fp8_matmul", "decision": "CANDIDATE_AFTER_ONE_FACTOR_ATTRIBUTION", "scope": "matmul dtype only"},
        {"mechanism": "cuda_graphs", "decision": "CANDIDATE_AFTER_ONE_FACTOR_ATTRIBUTION", "scope": "training-step launch capture only"},
        {"mechanism": "master_weight_offload", "decision": "CANDIDATE_AFTER_ONE_FACTOR_ATTRIBUTION", "scope": "master weights only"},
        {"mechanism": "fused_classifier", "decision": "CANDIDATE_AFTER_ONE_FACTOR_ATTRIBUTION", "scope": "classifier loss and dlogits only"},
    ]
    return isinstance(value, dict) and value == {
        "schema": "ember-llmq-adoption-design-v1",
        "status": "FROZEN_NOT_EXECUTED",
        "issue": 1413,
        "source": {"repository": "https://github.com/IST-DASLab/llmq.git", "branch": "dev", "commit": _LLMQ_PIN},
        "target": {"architecture": "ember-sparse-3b-v2", "runner": "governed Ember training pipeline"},
        "mechanism_transfer": expected_transfer,
        "non_transfer": [
            "Qwen2.5-3B architecture",
            "LLMQ checkpoint bytes",
            "LLMQ dataset or tokenizer authority",
            "LLMQ launch or receipt authority",
            "unmeasured optimizer-moment offload",
            "a broad all-fused-kernels claim",
        ],
        "preserved_authority": [
            "Ember corpus identity and tokenizer",
            "Ember architecture and checkpoint lineage",
            "Ember CLI to Ember Lab launch authority",
            "Ember source, binary, input, runtime, and receipt custody",
            "independent exact-head review before trainer changes",
        ],
        "target_gate": {
            "metric": "ember02_training_tok_s",
            "threshold": "greater_than_1000",
            "operator_trigger": "ping_on_crossing",
            "before_after_receipts_required": True,
        },
        "implementation_gate": "SEPARATE_REVIEW_REQUIRED",
        "refusal_over_substitution": "REFUSAL_OVER_SUBSTITUTION",
        "execution_claim": False,
        "result_credit": False,
    }


def _valid_mechanism_attribution(value: object) -> bool:
    return isinstance(value, dict) and value == {
        "schema": "ember-llmq-mechanism-attribution-v1",
        "status": "NOT_MEASURED",
        "issue": 1413,
        "source_commit": _LLMQ_PIN,
        "common_base": {
            "model": "Qwen2.5-3B",
            "sequence_length": 1024,
            "microbatch": 1,
            "gradient_accumulation": 512,
            "tokens_per_step": 524288,
            "matmul_dtype": "e4m3",
            "cuda_graphs": True,
            "classifier_kernel": "fused",
            "offload_master": True,
            "offload_adam_m": True,
            "offload_adam_v": True,
            "recompute_swiglu": False,
        },
        "run_order": [
            {"run": "FP8_BASE_A", "factor": "none"},
            {"run": "BF16_ONLY", "factor": "matmul_dtype", "from": "e4m3", "to": "bf16"},
            {"run": "FP8_BASE_B", "factor": "none"},
            {"run": "GRAPHS_OFF", "factor": "cuda_graphs", "from": True, "to": False},
            {"run": "FP8_BASE_C", "factor": "none"},
            {"run": "MASTER_OFF", "factor": "offload_master", "from": True, "to": False},
            {"run": "FP8_BASE_D", "factor": "none"},
            {"run": "FUSED_REFERENCE", "factor": "classifier_kernel", "from": "fused", "to": "unfused-reference"},
            {"run": "FP8_BASE_E", "factor": "none"},
        ],
        "measurement": {
            "excluded_steps": [0],
            "measured_steps": [1, 2, 3, 4, 5],
            "throughput_law": "sum(tokens)/sum(elapsed_seconds)",
            "base_repeat_policy": "each toggle is bracketed by adjacent base runs",
            "required_environment": [
                "GPU UUID",
                "exact binary SHA256",
                "source commit",
                "ordered argv and factor map",
                "dataset and tokenizer hashes",
                "CUDA, cuDNN, and NCCL versions",
                "pre and post clocks, temperature, and power",
                "VRAM and pinned-host memory ledger",
                "matched loss",
            ],
        },
        "claim_limits": [
            "FP8-002 and BF16-003 are reproduction evidence, not a one-factor precision pair",
            "MASTER_OFF attributes master-weight offload only",
            "FUSED_REFERENCE attributes the classifier kernel only",
            "an arm that does not fit receives a capacity refusal, not a throughput delta",
            "no mechanism fraction is credited before every required receipt is reopened",
        ],
        "refusal_over_substitution": "REFUSAL_OVER_SUBSTITUTION",
        "execution_claim": False,
        "result_credit": False,
    }


def _contract_missing(root: Path, payload: dict, path_field: str, digest_field: str, exact_path: str, validator) -> list[str]:
    missing = []
    digest = payload.get(digest_field)
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        missing.append(digest_field)
    if payload.get(path_field) != exact_path:
        missing.append(path_field)
        return missing
    path = _safe_file(root, exact_path)
    if path is None:
        missing.append(path_field)
        return missing
    try:
        raw = path.read_bytes()
        if isinstance(digest, str) and _DIGEST.fullmatch(digest) and hashlib.sha256(raw).hexdigest() != digest:
            missing.append(digest_field)
        if not validator(_closed_json(path)):
            missing.append(path_field.replace("_path", "_contract"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        missing.append(path_field.replace("_path", "_contract"))
    return missing


def _authority_file(root: Path | None, path_value: object) -> Path | None:
    """Reopen a daemon-exported file under its authenticated export root."""
    if root is None or not isinstance(path_value, str) or not path_value:
        return None
    try:
        authority_root = root.resolve(strict=True)
        candidate = Path(path_value)
        if candidate.is_absolute():
            if ".." in candidate.parts or not candidate.is_relative_to(authority_root):
                return None
            if _has_reparse_component(candidate, authority_root):
                return None
            candidate = candidate.resolve(strict=True)
            if not candidate.is_relative_to(authority_root):
                return None
        else:
            candidate = _safe_file(authority_root, path_value)
            if candidate is None:
                return None
        return candidate if candidate.is_file() else None
    except OSError:
        return None


def _git_env() -> dict[str, str]:
    """Drop caller-controlled Git config/object/worktree transport overrides."""
    blocked = {
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "GIT_HTTP_PROXY",
        "GIT_HTTPS_PROXY",
    }
    return {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("GIT_") and key.upper() not in blocked
    }


def _run_git(repo: Path, *args: str) -> str | None:
    """Run one read-only Git identity probe without opening a Windows console."""
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=False,
            creationflags=creationflags,
            env=_git_env(),
        )
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _run_git_bytes(repo: Path, *args: str) -> bytes | None:
    """Read one exact Git object without text decoding or console creation."""
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            check=False,
            creationflags=creationflags,
            env=_git_env(),
        )
    except OSError:
        return None
    return result.stdout if result.returncode == 0 else None


def _run_git_ok(repo: Path, *args: str) -> bool:
    """Run a read-only Git predicate without opening a Windows console."""
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            check=False,
            creationflags=creationflags,
            env=_git_env(),
        )
    except OSError:
        return False
    return result.returncode == 0


def _json_file(root: Path, path_value: object) -> dict | None:
    path = _authority_file(root, path_value)
    if path is None:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _digest_file(root: Path, path_value: object, digest: object) -> bool:
    """Reopen a path under custody and compare its raw bytes to a declared SHA."""
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        return False
    path = _authority_file(root, path_value)
    if path is None:
        return False
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest() == digest
    except OSError:
        return False


def _ember_lab_daemon_authority_missing(
    root: Path, build_receipt: object, benchmark_receipt: object, live_assessment: object = None
) -> list[str]:
    """Require daemon-owned job/run state, not a self-consistent receipt bundle."""
    if not isinstance(live_assessment, dict):
        return ["ember_lab_build_receipt.daemon_authority.live_pipe"]
    if not isinstance(build_receipt, dict):
        return ["ember_lab_build_receipt.daemon_authority"]
    missing: list[str] = []
    operational = live_assessment.get("operational_receipt")
    response = live_assessment.get("response")
    schedule = live_assessment.get("schedule_alarm_state")
    if not isinstance(operational, dict) or not isinstance(response, dict):
        return ["ember_lab_build_receipt.daemon_authority"]
    identity = operational.get("ember_lab_identity")
    if (
        operational.get("job_id") != build_receipt.get("job_id")
        or build_receipt.get("operational_receipt_sha256") != response.get("operational_receipt", {}).get("sha256")
        or build_receipt.get("producer_binary_sha256") != live_assessment.get("server_binary_sha256")
        or build_receipt.get("producer_source_sha256") != live_assessment.get("canonical_source_sha256")
    ):
        missing.append("ember_lab_build_receipt.daemon_authority.binding")
    if isinstance(benchmark_receipt, dict):
        runs = schedule.get("runs") if isinstance(schedule, dict) else None
        matching = [
            run for run in runs
            if isinstance(run, dict) and run.get("job_id") == build_receipt.get("job_id")
        ] if isinstance(runs, list) else []
        run = matching[0] if len(matching) == 1 else None
        if (
            benchmark_receipt.get("raw_log_sha256") != response.get("stdout_log", {}).get("sha256")
            or benchmark_receipt.get("schedule_alarm_state_sha256") != response.get("schedule_alarm_state", {}).get("sha256")
            or not isinstance(run, dict)
            or not isinstance(run.get("measured_at_ms"), int)
            or run.get("measurement_receipt_sha256") != benchmark_receipt.get("measurement_receipt_sha256")
            or run.get("prediction_daemon_identity") != identity
            or run.get("measurement_daemon_identity") != identity
        ):
            missing.append("ember_lab_build_receipt.daemon_authority.measurement")
    return missing

def _governed_source_missing(root: Path, payload: dict, commit: object, source_sha: object) -> list[str]:
    """Require an independently replayable source manifest, not caller JSON agreement."""
    receipt = payload.get("governed_source_receipt")
    missing: list[str] = []
    if not isinstance(receipt, dict) or receipt.get("schema") != _SOURCE_RECEIPT_SCHEMA:
        return ["governed_source_receipt"]
    if receipt.get("test_only") is True or receipt.get("status") != "PASS":
        missing.append("governed_source_receipt.status")
    if receipt.get("authority") != "governed-git-source":
        missing.append("governed_source_receipt.authority")
    if receipt.get("repo") != "IST-DASLab/llmq":
        missing.append("governed_source_receipt.repo")
    if receipt.get("commit") != commit or not isinstance(commit, str) or not _SHA.fullmatch(commit):
        missing.append("governed_source_receipt.commit")
    tree = receipt.get("tree_sha256")
    if not isinstance(tree, str) or not _SHA.fullmatch(tree):
        missing.append("governed_source_receipt.tree_sha256")
    if receipt.get("source_sha256") != source_sha:
        missing.append("governed_source_receipt.source_sha256")
    if not _digest_file(root, receipt.get("source_manifest_path"), receipt.get("source_manifest_sha256")):
        missing.append("governed_source_receipt.source_manifest")
    manifest = _json_file(root, receipt.get("source_manifest_path"))
    expected_manifest = {
        "schema": _SOURCE_MANIFEST_SCHEMA,
        "repo": "IST-DASLab/llmq",
        "commit": commit,
        "tree_sha256": tree,
        "remote_ref": receipt.get("remote_ref"),
        "source_path": receipt.get("source_path"),
        "source_sha256": source_sha,
    }
    if not isinstance(manifest, dict) or set(manifest) != set(expected_manifest) or any(
        manifest.get(key) != value for key, value in expected_manifest.items()
    ):
        missing.append("governed_source_receipt.source_manifest_binding")
    if not _digest_file(root, receipt.get("source_path"), source_sha):
        missing.append("governed_source_receipt.source_path")
    if receipt.get("verification") != "git-commit-tree-replayed":
        missing.append("governed_source_receipt.verification")
    repo = _safe_dir(root, receipt.get("git_repo_path"))
    if repo is None:
        missing.append("governed_source_receipt.git_repo_path")
    else:
        origins_raw = _run_git(repo, "config", "--get-all", "remote.origin.url")
        origins = origins_raw.splitlines() if isinstance(origins_raw, str) else []
        origin = origins[0] if len(origins) == 1 else None
        if len(origins) != 1 or origin != _GOVERNED_ORIGIN:
            missing.append("governed_source_receipt.git_origin")
        rewrite_rules = _run_git(repo, "config", "--get-regexp", r"^url\..+\.")
        if isinstance(origin, str) and rewrite_rules and any(
            len(parts := line.split(None, 1)) == 2
            and (
                parts[0].lower().endswith(".insteadof")
                or parts[0].lower().endswith(".pushinsteadof")
            )
            and origin.startswith(parts[1])
            for line in rewrite_rules.splitlines()
        ):
            missing.append("governed_source_receipt.git_url_rewrite")
        resolved_commit = _run_git(repo, "rev-parse", f"{commit}^{{commit}}") if isinstance(commit, str) else None
        resolved_tree = _run_git(repo, "rev-parse", f"{commit}^{{tree}}") if isinstance(commit, str) else None
        if resolved_commit != commit:
            missing.append("governed_source_receipt.git_commit")
        if resolved_tree != receipt.get("tree_sha256"):
            missing.append("governed_source_receipt.git_tree_sha256")
        remote_refs = (
            _run_git(
                repo,
                "for-each-ref",
                "--format=%(refname)",
                "--contains",
                commit,
                "refs/remotes/origin/",
            )
            if isinstance(commit, str)
            else None
        )
        if not remote_refs or not any(
            ref.startswith("refs/remotes/origin/") and ref != "refs/remotes/origin/HEAD"
            for ref in remote_refs.splitlines()
        ):
            missing.append("governed_source_receipt.git_remote_commit")
        remote_ref = receipt.get("remote_ref")
        if not isinstance(remote_ref, str) or not re.fullmatch(r"refs/heads/[A-Za-z0-9._/-]+", remote_ref):
            missing.append("governed_source_receipt.remote_ref")
        else:
            origin_path = Path(origin) if origin is not None else None
            if origin_path is not None and origin_path.is_dir():
                remote_commit = _run_git(origin_path, "show-ref", "--hash", remote_ref)
            else:
                remote_result = _run_git(repo, "ls-remote", "origin", remote_ref)
                remote_commit = remote_result.split()[0] if remote_result else None
            tracking_ref = "refs/remotes/origin/" + remote_ref.removeprefix("refs/heads/")
            fetched_commit = _run_git(repo, "rev-parse", tracking_ref)
            if remote_commit != commit:
                missing.append("governed_source_receipt.git_remote_ref")
            if fetched_commit != remote_commit:
                missing.append("governed_source_receipt.git_remote_fetch")
            if isinstance(commit, str) and not _run_git_ok(repo, "merge-base", "--is-ancestor", commit, tracking_ref):
                missing.append("governed_source_receipt.git_remote_ancestry")
        source_file = _safe_file(root, receipt.get("source_path"))
        if source_file is None or not source_file.is_relative_to(repo):
            missing.append("governed_source_receipt.source_in_repo")
        else:
            source_relative = source_file.relative_to(repo).as_posix()
            committed_source = (
                _run_git_bytes(repo, "cat-file", "blob", f"{commit}:{source_relative}")
                if isinstance(commit, str)
                else None
            )
            try:
                worktree_source = source_file.read_bytes()
            except OSError:
                worktree_source = None
            if (
                committed_source is None
                or worktree_source is None
                or committed_source != worktree_source
                or hashlib.sha256(committed_source).hexdigest() != source_sha
            ):
                missing.append("governed_source_receipt.git_source_blob")
    return missing


def _ember_lab_build_missing(
    root: Path, payload: dict, source_receipt: dict, build: object, live_assessment: object = None
) -> list[str]:
    """Require the canonical Ember CLI -> Ember Lab build/dispatch custody chain."""
    receipt = payload.get("ember_lab_build_receipt")
    missing: list[str] = []
    if not isinstance(receipt, dict) or receipt.get("schema") != _BUILD_RECEIPT_SCHEMA:
        return ["ember_lab_build_receipt"]
    authority_files_root = root
    if not isinstance(live_assessment, dict):
        missing.append("ember_lab_build_receipt.daemon_authority.live_pipe")
    if receipt.get("test_only") is True or receipt.get("status") != "PASS":
        missing.append("ember_lab_build_receipt.status")
    if receipt.get("authority") != "ember-cli->ember-lab":
        missing.append("ember_lab_build_receipt.authority")
    daemon_custody = (
        isinstance(live_assessment, dict)
        and live_assessment.get("_daemon_authority_token") is _DAEMON_AUTHORITY_TOKEN
    )
    for field in (
        "job_id", "host_id", "toolchain", "dispatch_receipt_path",
        "operational_receipt_path", "producer_source_path", "producer_binary_path",
    ):
        if not isinstance(receipt.get(field), str) or not receipt[field]:
            missing.append(f"ember_lab_build_receipt.{field}")
    if not daemon_custody and not isinstance(receipt.get("binary_manifest_path"), str):
        missing.append("ember_lab_build_receipt.binary_manifest_path")
    if receipt.get("exit_code") != 0:
        missing.append("ember_lab_build_receipt.exit_code")
    if (
        not isinstance(source_receipt, dict)
        or not isinstance(source_receipt.get("commit"), str)
        or not _SHA.fullmatch(source_receipt["commit"])
        or not isinstance(source_receipt.get("source_manifest_sha256"), str)
        or not _DIGEST.fullmatch(source_receipt["source_manifest_sha256"])
    ):
        missing.append("governed_source_receipt.commit")
    if receipt.get("source_manifest_sha256") != source_receipt.get("source_manifest_sha256"):
        missing.append("ember_lab_build_receipt.source_manifest_sha256")
    if daemon_custody:
        daemon_preflight_sha = live_assessment.get("preflight_receipt_sha256")
        if receipt.get("dispatch_receipt_sha256") != daemon_preflight_sha:
            missing.append("ember_lab_build_receipt.daemon_preflight_sha256")
    elif not _digest_file(authority_files_root, receipt.get("dispatch_receipt_path"), receipt.get("dispatch_receipt_sha256")):
        missing.append("ember_lab_build_receipt.dispatch_receipt")
    binary_manifest_path = receipt.get("binary_manifest_path")
    if isinstance(binary_manifest_path, str):
        if not _digest_file(authority_files_root, binary_manifest_path, receipt.get("binary_manifest_sha256")):
            missing.append("ember_lab_build_receipt.binary_manifest")
    elif not daemon_custody:
        missing.append("ember_lab_build_receipt.binary_manifest")
    if not isinstance(build, dict) or build.get("binary_sha256") != receipt.get("binary_sha256"):
        missing.append("ember_lab_build_receipt.binary_sha256")
    producer_source_path = receipt.get("producer_source_path")
    producer_source_sha = receipt.get("producer_source_sha256")
    if producer_source_path != _EMBER_LAB_SOURCE_PATH:
        missing.append("ember_lab_build_receipt.producer_source_identity")
    if not isinstance(producer_source_sha, str) or not _DIGEST.fullmatch(producer_source_sha):
        missing.append("ember_lab_build_receipt.producer_source_sha256")
    elif not isinstance(live_assessment, dict) or live_assessment.get("canonical_source_sha256") != producer_source_sha:
        missing.append("ember_lab_build_receipt.producer_source_sha256")
    producer_binary_path = receipt.get("producer_binary_path")
    producer_binary_sha = receipt.get("producer_binary_sha256")
    if not isinstance(producer_binary_sha, str) or not _DIGEST.fullmatch(producer_binary_sha):
        missing.append("ember_lab_build_receipt.producer_binary_sha256")
    elif not isinstance(live_assessment, dict) or live_assessment.get("server_binary_sha256") != producer_binary_sha:
        missing.append("ember_lab_build_receipt.producer_binary_sha256")
    operational_path = receipt.get("operational_receipt_path")
    operational_sha = receipt.get("operational_receipt_sha256")
    operational = live_assessment.get("operational_receipt") if isinstance(live_assessment, dict) else None
    if (
        isinstance(live_assessment, dict)
        and operational_sha != live_assessment.get("response", {}).get("operational_receipt", {}).get("sha256")
    ):
        operational = None
    if not isinstance(operational, dict):
        missing.append("ember_lab_build_receipt.daemon_authority")
    else:
        expected_keys = {
            "schema", "ember_lab_identity", "job_id", "identity_sha256",
            "resource_lease", "state", "pid", "executable_identity",
            "restart_policy", "exit_code", "logs", "events", "outage_events",
            "scientific_capability_evidence",
        }
        identity = operational.get("ember_lab_identity")
        logs = operational.get("logs")
        streams = logs if isinstance(logs, dict) else {}
        sealed_logs = all(
            isinstance(streams.get(name), dict)
            and streams[name].get("sealed") is True
            and isinstance(streams[name].get("file_name"), str)
            and Path(streams[name]["file_name"]).name == streams[name]["file_name"]
            and isinstance(streams[name].get("sha256"), str)
            and _DIGEST.fullmatch(streams[name]["sha256"])
            for name in ("stdout", "stderr")
        )
        if (
            set(operational) != expected_keys
            or operational.get("schema") != "ember-lab-operational-receipt-v1"
            or operational.get("job_id") != receipt.get("job_id")
            or not isinstance(operational.get("identity_sha256"), str)
            or not _DIGEST.fullmatch(operational["identity_sha256"])
            or not isinstance(operational.get("resource_lease"), str)
            or not operational["resource_lease"]
            or operational.get("state") != "exited"
            or not isinstance(operational.get("pid"), int)
            or operational["pid"] <= 0
            or not isinstance(operational.get("executable_identity"), str)
            or not operational["executable_identity"]
            or operational.get("restart_policy") != "never"
            or operational.get("exit_code") != 0
            or not isinstance(operational.get("events"), list)
            or not any(isinstance(event, dict) and event.get("kind") == "job_started" for event in operational["events"])
            or not any(isinstance(event, dict) and event.get("kind") == "job_exited" for event in operational["events"])
            or not isinstance(operational.get("outage_events"), list)
            or operational.get("scientific_capability_evidence") is not False
            or not sealed_logs
            or not isinstance(identity, dict)
            or set(identity) != {"source_sha256", "binary_sha256"}
            or identity.get("source_sha256") != producer_source_sha
            or identity.get("binary_sha256") != producer_binary_sha
        ):
            missing.append("ember_lab_build_receipt.daemon_authority")
    dispatch = (
        live_assessment.get("preflight_receipt")
        if daemon_custody and isinstance(live_assessment, dict)
        else _json_file(authority_files_root, receipt.get("dispatch_receipt_path"))
    )
    dispatch_schema = dispatch.get("schema") if isinstance(dispatch, dict) else None
    if isinstance(dispatch, dict) and dispatch_schema is None:
        dispatch_schema = dispatch.get("schema_version")
    accepted_dispatch_schemas = {"ember-lab-dispatch-terminal-receipt-v1"}
    if daemon_custody:
        accepted_dispatch_schemas.add("ember-lab-dispatch-preflight-v1")
    if not isinstance(dispatch, dict) or dispatch_schema not in accepted_dispatch_schemas:
        missing.append("ember_lab_build_receipt.dispatch_schema")
    else:
        if dispatch_schema == "ember-lab-dispatch-preflight-v1":
            if dispatch.get("result") != "PREFLIGHT_PASSED":
                missing.append("ember_lab_build_receipt.dispatch_status")
        elif dispatch.get("status") != "PASS" or dispatch.get("test_only") is True:
            missing.append("ember_lab_build_receipt.dispatch_status")
        if dispatch.get("job_id") != receipt.get("job_id"):
            missing.append("ember_lab_build_receipt.dispatch_job_id")
        if dispatch_schema == "ember-lab-dispatch-preflight-v1":
            if dispatch.get("source_commit") != live_assessment.get("_daemon_source_commit"):
                missing.append("ember_lab_build_receipt.dispatch_source_commit")
            program = dispatch.get("program")
            if (
                not isinstance(program, dict)
                or set(program) != {"path", "sha256"}
                or not isinstance(program.get("path"), str)
                or not program["path"]
                or not isinstance(program.get("sha256"), str)
                or not _DIGEST.fullmatch(program["sha256"])
            ):
                missing.append("ember_lab_build_receipt.dispatch_program_identity")
            elif program["sha256"] != receipt.get("binary_sha256"):
                missing.append("ember_lab_build_receipt.dispatch_program_binding")
            bindings = dispatch.get("bindings")
            source_manifest_sha = source_receipt.get("source_manifest_sha256") if isinstance(source_receipt, dict) else None
            if (
                not isinstance(bindings, list)
                or not any(
                    isinstance(binding, dict)
                    and binding.get("kind") in {"llmq-source-manifest", "input"}
                    and isinstance(binding.get("path"), str)
                    and Path(binding["path"]).name == "llmq-source-manifest.json"
                    and binding.get("sha256") == source_manifest_sha
                    for binding in bindings
                )
            ):
                missing.append("ember_lab_build_receipt.dispatch_source_manifest_binding")
        elif dispatch.get("source_manifest_sha256") != receipt.get("source_manifest_sha256"):
            missing.append("ember_lab_build_receipt.dispatch_source_manifest_sha256")
    if isinstance(binary_manifest_path, str):
        binary = _json_file(authority_files_root, binary_manifest_path)
        if not isinstance(binary, dict) or binary.get("schema") != "ember-lab-binary-manifest-v1":
            missing.append("ember_lab_build_receipt.binary_manifest_schema")
        elif binary.get("status") != "PASS" or binary.get("test_only") is True or binary.get("binary_sha256") != receipt.get("binary_sha256"):
            missing.append("ember_lab_build_receipt.binary_manifest_binding")
    return missing


def _ember_lab_benchmark_missing(
    root: Path, payload: dict, build_receipt: dict, live_assessment: object = None
) -> list[str]:
    """Require re-openable multi-step benchmark logs and rederived rates."""
    receipt = payload.get("ember_lab_benchmark_receipt")
    missing: list[str] = []
    if not isinstance(receipt, dict) or receipt.get("schema") != _BENCHMARK_RECEIPT_SCHEMA:
        return ["ember_lab_benchmark_receipt"]
    if not isinstance(live_assessment, dict):
        missing.append("ember_lab_benchmark_receipt.daemon_authority.live_pipe")
    if receipt.get("test_only") is True or receipt.get("status") != "PASS":
        missing.append("ember_lab_benchmark_receipt.status")
    if receipt.get("authority") != "ember-cli->ember-lab":
        missing.append("ember_lab_benchmark_receipt.authority")
    if receipt.get("job_id") != build_receipt.get("job_id"):
        missing.append("ember_lab_benchmark_receipt.job_id")
    for field in (
        "hardware_uuid", "command", "config_sha256", "raw_log_path", "raw_log_sha256",
        "operational_receipt_path", "operational_receipt_sha256",
        "schedule_alarm_state_path", "schedule_alarm_state_sha256", "measurement_receipt_sha256",
    ):
        if not isinstance(receipt.get(field), str) or not receipt[field]:
            missing.append(f"ember_lab_benchmark_receipt.{field}")
    if receipt.get("binary_sha256") != build_receipt.get("binary_sha256"):
        missing.append("ember_lab_benchmark_receipt.binary_sha256")
    if (
        receipt.get("operational_receipt_path") != build_receipt.get("operational_receipt_path")
        or receipt.get("operational_receipt_sha256") != build_receipt.get("operational_receipt_sha256")
    ):
        missing.append("ember_lab_benchmark_receipt.operational_receipt_binding")
    operational = live_assessment.get("operational_receipt") if isinstance(live_assessment, dict) else None
    if not isinstance(operational, dict):
        missing.append("ember_lab_benchmark_receipt.daemon_authority")
    elif (
        receipt.get("job_id") != operational.get("job_id")
        or receipt.get("hardware_uuid") != operational.get("resource_lease")
    ):
        missing.append("ember_lab_benchmark_receipt.hardware_run_authority")
    raw_bytes = live_assessment.get("stdout_bytes") if isinstance(live_assessment, dict) else None
    if not isinstance(raw_bytes, bytes) or hashlib.sha256(raw_bytes).hexdigest() != receipt.get("raw_log_sha256"):
        missing.append("ember_lab_benchmark_receipt.raw_log")
    if isinstance(operational, dict):
        stdout = operational.get("logs", {}).get("stdout") if isinstance(operational.get("logs"), dict) else None
        if (
            not isinstance(stdout, dict)
            or stdout.get("sealed") is not True
            or stdout.get("sha256") != receipt.get("raw_log_sha256")
        ):
            missing.append("ember_lab_benchmark_receipt.sample_log_authority")
    raw_rows: list[dict] = []
    if isinstance(raw_bytes, bytes):
        try:
            raw_rows = [json.loads(line) for line in raw_bytes.decode("utf-8", errors="strict").splitlines() if line.strip()]
        except (OSError, ValueError):
            missing.append("ember_lab_benchmark_receipt.raw_log_schema")
    if not raw_rows or any(not isinstance(row, dict) for row in raw_rows):
        missing.append("ember_lab_benchmark_receipt.raw_log_rows")
    rows = receipt.get("rate_rows")
    if not isinstance(rows, list) or not rows:
        missing.append("ember_lab_benchmark_receipt.rate_rows")
    else:
        modes = set()
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                missing.append(f"ember_lab_benchmark_receipt.rate_rows[{index}]")
                continue
            mode = row.get("mode")
            tokens = row.get("tokens")
            elapsed_ms = row.get("elapsed_ms")
            measured = row.get("tok_s")
            if mode not in {"fp8", "bf16"}:
                missing.append(f"ember_lab_benchmark_receipt.rate_rows[{index}].mode")
            else:
                modes.add(mode)
            if not isinstance(tokens, int) or tokens <= 0 or not isinstance(elapsed_ms, (int, float)) or elapsed_ms <= 0:
                missing.append(f"ember_lab_benchmark_receipt.rate_rows[{index}].measurement")
            elif not isinstance(measured, (int, float)) or not math.isfinite(measured) or abs(measured - tokens * 1000.0 / elapsed_ms) > 1e-6:
                missing.append(f"ember_lab_benchmark_receipt.rate_rows[{index}].tok_s")
        if modes != {"fp8", "bf16"}:
            missing.append("ember_lab_benchmark_receipt.rate_rows.modes")
        if len(raw_rows) != len(rows):
            missing.append("ember_lab_benchmark_receipt.raw_log_cardinality")
        else:
            for index, (raw, declared) in enumerate(zip(raw_rows, rows)):
                if any(raw.get(key) != declared.get(key) for key in ("mode", "tokens", "elapsed_ms")):
                    missing.append(f"ember_lab_benchmark_receipt.raw_log_binding[{index}]")
                if isinstance(raw.get("tokens"), int) and isinstance(raw.get("elapsed_ms"), (int, float)) and raw.get("elapsed_ms", 0) > 0:
                    expected = raw["tokens"] * 1000.0 / raw["elapsed_ms"]
                    if declared.get("tok_s") != expected:
                        missing.append(f"ember_lab_benchmark_receipt.raw_log_rate[{index}]")
    schedule = live_assessment.get("schedule_alarm_state") if isinstance(live_assessment, dict) else None
    response_schedule_sha = (
        live_assessment.get("response", {}).get("schedule_alarm_state", {}).get("sha256")
        if isinstance(live_assessment, dict) else None
    )
    if receipt.get("schedule_alarm_state_sha256") != response_schedule_sha or not isinstance(schedule, dict):
        missing.append("ember_lab_benchmark_receipt.schedule_authority")
    else:
        identity = operational.get("ember_lab_identity") if isinstance(operational, dict) else None
        runs = schedule.get("runs")
        matching = [
            run for run in runs
            if isinstance(run, dict) and run.get("job_id") == receipt.get("job_id")
        ] if isinstance(runs, list) else []
        total_tokens = sum(row.get("tokens", 0) for row in raw_rows if isinstance(row, dict))
        total_duration = sum(row.get("elapsed_ms", 0) for row in raw_rows if isinstance(row, dict))
        run = matching[0] if len(matching) == 1 else None
        if (
            schedule.get("schema_version") != "ember-lab-schedule-alarm-state-v1"
            or schedule.get("ember_lab_identity") != identity
            or not isinstance(run, dict)
            or run.get("artifact_class") != "llmq-4090x1-3b-benchmark"
            or run.get("measured_tokens") != total_tokens
            or run.get("measured_duration_ms") != total_duration
            or run.get("measurement_outcome") != "COMPLETED"
            or run.get("measurement_receipt_sha256") != receipt.get("measurement_receipt_sha256")
            or run.get("prediction_daemon_identity") != identity
            or run.get("measurement_daemon_identity") != identity
        ):
            missing.append("ember_lab_benchmark_receipt.hardware_run_sample_authority")
    return missing


def assess(source_root: Path, payload: dict) -> dict:
    if not isinstance(payload, dict):
        return {
            "schema": "ember-llmq-adoption-readiness-v1",
            "verdict": "PRELAUNCH_REJECTED",
            "missing": ["payload"],
            "source_root": "SCRATCH_ONLY",
            "execution_claim": False,
            "result_credit": False,
            "external_remainder": ["closed readiness payload"],
            "rollback": "discard scratch-only artifact; no product state changed",
            "next_action": "supply a closed readiness payload before any dispatch",
        }
    # Work on a private copy so the live daemon response cannot mutate caller
    # custody, while ensuring all downstream validators consume one response.
    payload = json.loads(json.dumps(payload))
    missing = []
    commit = payload.get("llmq_dev_commit")
    if not isinstance(commit, str) or not _SHA.fullmatch(commit):
        missing.append("llmq_dev_commit")
    source_path = _safe_file(Path(source_root), payload.get("llmq_source_path"))
    if source_path is None:
        missing.append("llmq_source_path")
    source_sha = payload.get("source_sha256")
    if not isinstance(source_sha, str) or not _DIGEST.fullmatch(source_sha):
        missing.append("source_sha256")
    elif source_path is not None:
        try:
            if hashlib.sha256(source_path.read_bytes()).hexdigest() != source_sha:
                missing.append("source_sha256")
        except OSError:
            missing.append("source_sha256")
    build = payload.get("build_receipt")
    if not isinstance(build, dict) or build.get("schema") != "ember-llmq-build-receipt-v1":
        missing.append("build_receipt")
    else:
        if build.get("status") != "PASS":
            missing.append("build_receipt.status")
        if build.get("source_commit") != commit:
            missing.append("build_receipt.source_commit")
        if build.get("source_sha256") != source_sha:
            missing.append("build_receipt.source_sha256")
        binary_path = _safe_file(Path(source_root), build.get("binary_path"))
        if binary_path is None:
            missing.append("build_receipt.binary_path")
        if not isinstance(build.get("binary_sha256"), str) or not _DIGEST.fullmatch(build["binary_sha256"]):
            missing.append("build_receipt.binary_sha256")
        elif binary_path is not None:
            try:
                if hashlib.sha256(binary_path.read_bytes()).hexdigest() != build["binary_sha256"]:
                    missing.append("build_receipt.binary_sha256")
            except OSError:
                missing.append("build_receipt.binary_sha256")

    source_receipt = payload.get("governed_source_receipt") if isinstance(payload.get("governed_source_receipt"), dict) else {}
    ember_lab_receipt = payload.get("ember_lab_build_receipt")
    live_assessment = _acquire_live_daemon_assessment(
        Path(__file__).resolve().parents[1],
        ember_lab_receipt.get("job_id") if isinstance(ember_lab_receipt, dict) else None,
    )
    source_authority_missing = _governed_source_missing(Path(source_root), payload, commit, source_sha)
    missing.extend(source_authority_missing)
    build_authority_missing = _ember_lab_build_missing(
        Path(source_root), payload, source_receipt, build, live_assessment
    )
    missing.extend(build_authority_missing)
    daemon_authority_missing = _ember_lab_daemon_authority_missing(
        Path(source_root),
        payload.get("ember_lab_build_receipt"),
        payload.get("ember_lab_benchmark_receipt"),
        live_assessment,
    )
    missing.extend(daemon_authority_missing)
    benchmark_authority_missing = _ember_lab_benchmark_missing(
        Path(source_root), payload,
        payload.get("ember_lab_build_receipt") if isinstance(payload.get("ember_lab_build_receipt"), dict) else {},
        live_assessment,
    )
    missing.extend(benchmark_authority_missing)

    missing.extend(
        _contract_missing(
            Path(source_root), payload, "adoption_design_path", "adoption_design_sha256",
            _ADOPTION_DESIGN_PATH, _valid_adoption_design,
        )
    )
    missing.extend(
        _contract_missing(
            Path(source_root), payload, "mechanism_attribution_path", "mechanism_attribution_sha256",
            _MECHANISM_ATTRIBUTION_PATH, _valid_mechanism_attribution,
        )
    )

    benchmark = payload.get("benchmark_receipt")
    if not isinstance(benchmark, dict) or benchmark.get("schema") != "ember-4090-3b-benchmark-receipt-v1":
        missing.append("benchmark_receipt")
    else:
        if benchmark.get("hardware") != "RTX 4090":
            missing.append("benchmark_receipt.hardware")
        if benchmark.get("status") != "PASS":
            missing.append("benchmark_receipt.status")
        if benchmark.get("model") != "Qwen2.5-3B":
            missing.append("benchmark_receipt.model")
        for field in ("fp8_tok_s", "bf16_tok_s"):
            value = benchmark.get(field)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                missing.append(f"benchmark_receipt.{field}")

    source_or_design_missing = any(
        field in missing
        for field in (
            "llmq_dev_commit",
            "llmq_source_path",
            "source_sha256",
            "build_receipt",
            "adoption_design_path",
            "adoption_design_sha256",
            "adoption_design_contract",
            "mechanism_attribution_path",
            "mechanism_attribution_sha256",
            "mechanism_attribution_contract",
        )
    )
    if (
        source_or_design_missing
        or any(field.startswith("build_receipt") for field in missing)
        or any(field.startswith("governed_source_receipt") for field in missing)
        or any(field.startswith("ember_lab_build_receipt") for field in missing)
        or any(field.startswith("ember_lab_build_receipt.daemon_authority") for field in missing)
        or any(field.startswith("benchmark_receipt.") for field in missing)
        or any(field.startswith("ember_lab_benchmark_receipt.") for field in missing)
    ):
        verdict = "PRELAUNCH_REJECTED"
    elif "benchmark_receipt" in missing or "ember_lab_benchmark_receipt" in missing:
        verdict = "READY_FOR_EXTERNAL_EXECUTION"
    else:
        verdict = "READY_FOR_EXTERNAL_EXECUTION"
    external_remainder = []
    if any(field in missing for field in ("llmq_dev_commit", "llmq_source_path", "source_sha256")):
        external_remainder.append("pinned LLMQ source commit and source bytes")
    if any(field.startswith("build_receipt") for field in missing):
        external_remainder.append("governed LLMQ build receipt and binary bytes")
    if any(field in missing for field in ("adoption_design_path", "adoption_design_sha256", "adoption_design_contract")):
        external_remainder.append("frozen adoption design bytes")
    if any(field in missing for field in ("mechanism_attribution_path", "mechanism_attribution_sha256", "mechanism_attribution_contract")):
        external_remainder.append("mechanism attribution bytes")
    if any(field.startswith("benchmark_receipt") for field in missing):
        external_remainder.append("owned RTX 4090 x1 3B benchmark receipt")
    if any(field.startswith("governed_source_receipt") for field in missing):
        external_remainder.append("independently replayed governed LLMQ source receipt")
    if any(field.startswith("ember_lab_build_receipt") for field in missing):
        external_remainder.append("canonical Ember CLI -> Ember Lab build/dispatch receipt")
    if any(field.startswith("ember_lab_benchmark_receipt") for field in missing):
        external_remainder.append("canonical Ember CLI -> Ember Lab benchmark log receipt")
    return {
        "schema": "ember-llmq-adoption-readiness-v1",
        "verdict": verdict,
        "missing": missing,
        "source_root": "SCRATCH_ONLY",
        "execution_claim": False,
        "result_credit": False,
        "external_remainder": external_remainder,
        "rollback": "discard scratch-only artifact; no product state changed",
        "next_action": (
            "obtain a governed LLMQ build and one-RTX-4090 3B benchmark receipt"
            if "benchmark_receipt" in missing
            else "dispatch only through Ember CLI -> Ember Lab after external evidence"
        ),
    }


def _private_rpc_worker_main(argv: list[str]) -> int:
    if len(argv) != 4 or argv[0] != "--private-ember-lab-assessment-rpc":
        return 2
    pipe_name, job_id, directory_value = argv[1:]
    if _configured_ember_lab_pipe() != pipe_name:
        return 2
    directory = Path(directory_value)
    if not directory.is_absolute() or directory.exists():
        return 2
    try:
        result, binary_sha, binary_path = _rpc_export_assessment_direct(pipe_name, job_id, directory)
        envelope = {
            "result": result,
            "server_binary_sha256": binary_sha,
            "server_binary_path": str(binary_path),
        }
        raw = json.dumps(envelope, separators=(",", ":")).encode("utf-8")
        if len(raw) > _MAX_RPC_FRAME_BYTES:
            return 2
        sys.stdout.buffer.write(raw)
        return 0
    except (OSError, ValueError, UnicodeError):
        return 2


if __name__ == "__main__":
    raise SystemExit(_private_rpc_worker_main(sys.argv[1:]))
