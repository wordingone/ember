# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Loopback-only OpenAI-compatible serving for an admitted owned Ember checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Protocol

import torch

from infer import FrozenTokenizer, frozen_split_prompt, greedy_generate, load_frozen_tokenizer, sha
import model as model_module
from model import RestartDecoderConfig, UnifiedDecoder

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from ember_restart_eval_raw_forward import (  # noqa: E402
    canonicalize_tied_embedding_state,
    construct_runtime_model,
    hash_and_load_torch,
    materialize_state_map,
    rebind_tied_embeddings,
    tied_embeddings_from_contract,
    validate_state_map,
)
RuntimeMode = Literal["INTERACTIVE", "FROZEN_EVAL"]
_MAX_REQUEST_TOKENS = 8096
_MAX_RUNTIME_GENERATION_TOKENS = 1024


@dataclass(frozen=True)
class OwnedIdentity:
    checkpoint_sha256: str
    model_config_sha256: str
    tokenizer_sha256: str
    server_source_sha256: str
    seat: str = "OWNED_ADMITTED"

    @property
    def model_name(self) -> str:
        return "ember-owned:" + self.checkpoint_sha256[:12]

    def payload(self) -> dict[str, object]:
        return {
            "object": "list",
            "data": [{"id": self.model_name, "object": "model"}],
            "seat": self.seat,
            "checkpoint_sha256": self.checkpoint_sha256,
            "model_name": self.model_name,
            "model_config_sha256": self.model_config_sha256,
            "tokenizer_sha256": self.tokenizer_sha256,
            "server_source_sha256": self.server_source_sha256,
        }


@dataclass(frozen=True)
class DevelopmentIdentity:
    checkpoint_sha256: str
    model_config_sha256: str
    tokenizer_sha256: str
    server_source_sha256: str
    tokens_seen: int
    allocated_parameters: int
    active_parameters: int
    seat: str = "OWNED_DEVELOPMENT"
    claim_status: str = "NON_ADMISSIBLE"

    @property
    def model_name(self) -> str:
        return "ember-owned-development:" + self.checkpoint_sha256[:12]

    def payload(self) -> dict[str, object]:
        return {
            "object": "list", "data": [{"id": self.model_name, "object": "model"}],
            "seat": self.seat, "claim_status": self.claim_status,
            "checkpoint_sha256": self.checkpoint_sha256, "model_name": self.model_name,
            "model_config_sha256": self.model_config_sha256, "tokenizer_sha256": self.tokenizer_sha256,
            "server_source_sha256": self.server_source_sha256, "tokens_seen": self.tokens_seen,
            "allocated_parameters": self.allocated_parameters, "active_parameters": self.active_parameters,
        }

class OwnedChatRuntime(Protocol):
    identity: OwnedIdentity | DevelopmentIdentity

    def chat(self, messages: list[dict[str, object]], *, frozen_row_id: str | None, max_tokens: int) -> tuple[str, str]: ...


def _contains_target_leak(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            name = str(key).casefold()
            if "target" in name or "answer" in name or "label" in name:
                return True
            if _contains_target_leak(child):
                return True
    elif isinstance(value, list):
        return any(_contains_target_leak(child) for child in value)
    return False


def _contains_target_leak_on_prompt_surface(request: Mapping[str, object]) -> bool:
    """Inspect only content-bearing prompt fields, never tool/control schemas."""

    return any(
        _contains_target_leak(request[field])
        for field in ("messages", "prompt", "ember_frozen_row")
        if field in request
    )

def _read_bound_json_snapshot(path: Path, *, expected_sha256: str, label: str) -> tuple[dict[str, object], str, bytes]:
    snapshot = path.read_bytes()
    actual = hashlib.sha256(snapshot).hexdigest()
    if actual != expected_sha256:
        raise ValueError(f"{label} sha256 does not match its authority")
    try:
        payload = json.loads(snapshot)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be an object")
    return payload, actual, snapshot


def _same_root_snapshot(path: Path, payload: bytes) -> Path:
    """Publish one private immutable authority copy beside its relative artifacts."""

    snapshot = path.parent / f".{path.name}.{uuid.uuid4().hex}.snapshot"
    with snapshot.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return snapshot

def _config_snapshot_path(config_bytes: bytes) -> Path:
    handle = tempfile.NamedTemporaryFile("wb", suffix=".json", delete=False)
    try:
        handle.write(config_bytes)
        handle.flush()
        os.fsync(handle.fileno())
        return Path(handle.name)
    finally:
        handle.close()

def _error(message: str) -> dict[str, object]:
    return {"error": {"message": message, "type": "invalid_request_error"}}


def resolve_runtime_inputs(mode: str, frozen_split: Path | None) -> Path | None:
    if mode == "INTERACTIVE":
        if frozen_split is not None:
            raise ValueError("INTERACTIVE mode forbids a frozen split")
        return None
    if mode == "FROZEN_EVAL":
        if frozen_split is None:
            raise ValueError("FROZEN_EVAL mode requires a frozen split")
        return frozen_split
    raise ValueError("owned server mode must be INTERACTIVE or FROZEN_EVAL")


def parent_process_alive(parent_pid: int) -> bool:
    if parent_pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        open_process = kernel32.OpenProcess
        open_process.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        open_process.restype = ctypes.c_void_p
        get_exit_code_process = kernel32.GetExitCodeProcess
        get_exit_code_process.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        get_exit_code_process.restype = ctypes.c_int
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [ctypes.c_void_p]
        close_handle.restype = ctypes.c_int
        handle = open_process(0x1000, False, parent_pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not get_exit_code_process(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == 259
        finally:
            close_handle(handle)
    try:
        os.kill(parent_pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def require_live_parent(
    parent_pid: int,
    *,
    checker: Callable[[int], bool] = parent_process_alive,
) -> None:
    if not checker(parent_pid):
        raise RuntimeError("owned server parent process is not alive")


def _emit_parent_watchdog_receipt(receipt: dict[str, object]) -> None:
    payload = (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    os.write(2, payload)


class _CallableParentProbe:
    def __init__(self, parent_pid: int, checker: Callable[[int], bool]) -> None:
        self.parent_pid = parent_pid
        self.checker = checker

    def alive(self) -> bool:
        return self.checker(self.parent_pid)

    def close(self) -> None:
        return None


class _WindowsParentProbe:
    """Hold one process handle so PID reuse cannot retether an orphaned server."""

    def __init__(self, parent_pid: int) -> None:
        import ctypes

        if parent_pid <= 0:
            raise RuntimeError("owned server parent process is not alive")
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        open_process = kernel32.OpenProcess
        open_process.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        open_process.restype = ctypes.c_void_p
        self._get_exit_code = kernel32.GetExitCodeProcess
        self._get_exit_code.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        self._get_exit_code.restype = ctypes.c_int
        self._close_handle = kernel32.CloseHandle
        self._close_handle.argtypes = [ctypes.c_void_p]
        self._close_handle.restype = ctypes.c_int
        self._ctypes = ctypes
        self._handle = open_process(0x1000, False, parent_pid)
        if not self._handle:
            raise RuntimeError("owned server parent process is not alive")

    def alive(self) -> bool:
        if not self._handle:
            return False
        exit_code = self._ctypes.c_ulong()
        return bool(self._get_exit_code(self._handle, self._ctypes.byref(exit_code))) and exit_code.value == 259

    def close(self) -> None:
        if self._handle:
            self._close_handle(self._handle)
            self._handle = None


def bind_parent_process(parent_pid: int) -> _WindowsParentProbe | _CallableParentProbe:
    if os.name == "nt":
        return _WindowsParentProbe(parent_pid)
    require_live_parent(parent_pid)
    return _CallableParentProbe(parent_pid, parent_process_alive)


def start_parent_watchdog(
    parent_pid: int,
    *,
    poll_seconds: float = 10.0,
    misses_before_exit: int = 2,
    checker: Callable[[int], bool] | None = None,
    exit_process: Callable[[int], None] = os._exit,
    emit_receipt: Callable[[dict[str, object]], None] = _emit_parent_watchdog_receipt,
) -> threading.Thread:
    if misses_before_exit < 1:
        raise ValueError("parent watchdog miss threshold must be positive")
    probe = bind_parent_process(parent_pid) if checker is None else _CallableParentProbe(parent_pid, checker)
    try:
        if not probe.alive():
            raise RuntimeError("owned server parent process is not alive")
    except BaseException:
        probe.close()
        raise

    def watch() -> None:
        consecutive_misses = 0
        try:
            while True:
                time.sleep(poll_seconds)
                try:
                    alive = probe.alive()
                except Exception:
                    alive = False
                if alive:
                    consecutive_misses = 0
                    continue
                consecutive_misses += 1
                if consecutive_misses < misses_before_exit:
                    continue
                receipt = {
                    "schema_version": "ember-owned-parent-watchdog-v1",
                    "event": "PARENT_GONE_EXIT",
                    "result": "MEASURED",
                    "parent_pid": parent_pid,
                    "consecutive_missed_polls": consecutive_misses,
                    "poll_seconds": poll_seconds,
                }
                try:
                    emit_receipt(receipt)
                except Exception:
                    pass
                finally:
                    exit_process(0)
                return
        finally:
            probe.close()

    thread = threading.Thread(target=watch, name="ember-owned-parent-watchdog", daemon=True)
    thread.start()
    return thread


def resolve_central_owned_admission(
    *,
    run_manifest: Path,
    trusted_verifier_registry: Path,
    trusted_verifier_registry_approval: Path,
    checkpoint_sha256: str,
    snapshot_manifest: Path | None = None,
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
) -> dict[str, object]:
    """Execute the central seat resolver and bind its decision to the loaded checkpoint."""

    command = [
        sys.executable,
        "-I",
        str(ROOT / "scripts" / "ember_restart" / "cli_seat.py"),
        str(snapshot_manifest if snapshot_manifest is not None else run_manifest),
        "--trusted-verifier-registry",
        str(trusted_verifier_registry),
        "--trusted-verifier-registry-approval",
        str(trusted_verifier_registry_approval),
    ]
    try:
        completed = (
            runner(command)
            if runner is not None
            else subprocess.run(
                command,
                text=True,
                capture_output=True,
                timeout=120,
                check=False,
            )
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"central owned-seat resolver failed: {exc}") from exc
    if completed.returncode != 0:
        raise ValueError("central owned-seat resolver rejected the run manifest")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("central owned-seat resolver returned invalid JSON") from exc
    if not isinstance(payload, dict) or payload.get("valid") is not True:
        raise ValueError("central owned-seat resolver did not return a valid decision")
    if payload.get("seat") != "OWNED_ADMITTED":
        raise ValueError("central owned-seat resolver did not admit the owned checkpoint")
    if payload.get("checkpoint_sha256") != checkpoint_sha256:
        raise ValueError("central admission checkpoint hash does not match loaded manifest")
    if payload.get("model_name") != "ember-owned:" + checkpoint_sha256[:12]:
        raise ValueError("central admission model name does not match loaded checkpoint")
    return payload

def resolve_development_identity(
    development_manifest: Path,
    *,
    expected_manifest_sha256: str,
    expected_runtime_index_sha256: str,
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
) -> dict[str, object]:
    command = [
        sys.executable,
        "-I",
        str(ROOT / "scripts" / "ember_restart" / "development_cli_seat.py"),
        str(development_manifest),
        "--expected-manifest-sha256",
        expected_manifest_sha256,
        "--expected-runtime-index-sha256",
        expected_runtime_index_sha256,
    ]
    completed = runner(command) if runner is not None else subprocess.run(command, text=True, capture_output=True, timeout=120, check=False)
    if completed.returncode != 0:
        raise ValueError("development seat resolver rejected the manifest")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("development seat resolver returned invalid JSON") from exc
    required = {"valid": True, "seat": "OWNED_DEVELOPMENT", "claim_status": "NON_ADMISSIBLE"}
    if not isinstance(payload, dict) or any(payload.get(key) != value for key, value in required.items()):
        raise ValueError("development seat resolver returned an invalid identity")
    return payload

def create_loopback_server(runtime: OwnedChatRuntime, *, host: str, port: int, mode: RuntimeMode) -> ThreadingHTTPServer:
    """Create a local-only server whose identity and completions share one runtime object."""

    if host != "127.0.0.1":
        raise ValueError("owned inference server must bind exactly 127.0.0.1")
    if mode not in ("INTERACTIVE", "FROZEN_EVAL"):
        raise ValueError("owned server mode must be INTERACTIVE or FROZEN_EVAL")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def _write(self, status: int, payload: Mapping[str, object]) -> None:
            encoded = json.dumps(dict(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:
            if self.path != "/v1/models":
                self._write(404, _error("unknown endpoint"))
                return
            self._write(200, {**runtime.identity.payload(), "mode": mode})

        def do_POST(self) -> None:
            if self.path != "/v1/chat/completions":
                self._write(404, _error("unknown endpoint"))
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                request = json.loads(self.rfile.read(size).decode("utf-8"))
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                self._write(400, _error("request must contain JSON"))
                return
            if not isinstance(request, dict):
                self._write(400, _error("request must be an object"))
                return
            if request.get("model") != runtime.identity.model_name:
                self._write(400, _error("model identity does not match the loaded owned checkpoint"))
                return
            if mode == "FROZEN_EVAL" and _contains_target_leak_on_prompt_surface(request):
                self._write(400, _error("request contains target leakage"))
                return
            frozen_row_id = request.get("ember_frozen_row_id")
            if mode == "FROZEN_EVAL" and (not isinstance(frozen_row_id, str) or not frozen_row_id):
                self._write(400, _error("request requires a nonempty frozen row identifier"))
                return
            if mode == "INTERACTIVE":
                frozen_row_id = None
            messages = request.get("messages")
            if not isinstance(messages, list) or not messages or any(not isinstance(message, dict) for message in messages):
                self._write(400, _error("messages must be a nonempty array of objects"))
                return
            max_tokens = request.get("max_tokens", 64)
            if not isinstance(max_tokens, int) or not 0 < max_tokens <= _MAX_REQUEST_TOKENS:
                self._write(400, _error(f"max_tokens must be an integer in [1, {_MAX_REQUEST_TOKENS}]"))
                return
            effective_max_tokens = min(max_tokens, _MAX_RUNTIME_GENERATION_TOKENS)
            text, finish_reason = runtime.chat(messages, frozen_row_id=frozen_row_id, max_tokens=effective_max_tokens)
            completion = {
                "id": "chatcmpl-owned-" + runtime.identity.checkpoint_sha256[:12],
                "object": "chat.completion",
                "created": int(time.time()), "model": runtime.identity.model_name,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": finish_reason}],
                "owned_identity": runtime.identity.payload(),
            }
            if request.get("stream") is True:
                chunk = {
                    "id": completion["id"], "object": "chat.completion.chunk", "created": completion["created"],
                    "model": runtime.identity.model_name,
                    "choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": finish_reason}],
                    "owned_identity": runtime.identity.payload(),
                }
                self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.send_header("Cache-Control", "no-cache"); self.end_headers()
                self.wfile.write(("data: " + json.dumps(chunk, sort_keys=True, separators=(",", ":")) + "\n\ndata: [DONE]\n\n").encode("utf-8")); self.wfile.flush()
                return
            self._write(200, completion)

    return ThreadingHTTPServer((host, port), Handler)


class LoadedOwnedRuntime:
    """One checkpoint/model/tokenizer realization retained for every loopback request."""

    def __init__(self, *, model: UnifiedDecoder, tokenizer: FrozenTokenizer, identity: OwnedIdentity, device: torch.device, frozen_split: Path | None = None) -> None:
        self.model = model
        self.tokenizer = tokenizer
        self.identity = identity
        self.device = device
        self.frozen_split = frozen_split

    @classmethod
    def from_paths(
        cls,
        *,
        checkpoint: Path,
        tokenizer_path: Path,
        config_path: Path,
        run_manifest: Path,
        frozen_split: Path | None,
        trusted_verifier_registry: Path,
        trusted_verifier_registry_approval: Path,
        device: str,
    ) -> "LoadedOwnedRuntime":
        manifest_path = checkpoint / "checkpoint-manifest.json"
        manifest_bytes = manifest_path.read_bytes()
        checkpoint_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        manifest = json.loads(manifest_bytes)
        run_manifest_bytes = run_manifest.read_bytes()
        run_manifest_sha256 = hashlib.sha256(run_manifest_bytes).hexdigest()
        resolver_snapshot = _same_root_snapshot(run_manifest, run_manifest_bytes)
        try:
            admission = resolve_central_owned_admission(
                run_manifest=run_manifest,
                snapshot_manifest=resolver_snapshot,
                trusted_verifier_registry=trusted_verifier_registry,
                trusted_verifier_registry_approval=trusted_verifier_registry_approval,
                checkpoint_sha256=checkpoint_sha256,
            )
        finally:
            resolver_snapshot.unlink(missing_ok=True)
        if sha(run_manifest) != run_manifest_sha256:
            raise ValueError("central run manifest changed during owned-seat resolution")
        try:
            central_manifest = json.loads(run_manifest_bytes)
            config_record = central_manifest["architecture"]["model_config"]
            tokenizer_record = central_manifest["tokenizer"]
        except (KeyError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"central run manifest lacks runtime bindings: {exc}") from exc

        def bound_sha256(record: object, name: str) -> str:
            value = record.get("sha256") if isinstance(record, Mapping) else None
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(char not in "0123456789abcdef" for char in value)
            ):
                raise ValueError(f"central run manifest lacks lowercase {name} sha256")
            return value

        expected_config_sha256 = bound_sha256(config_record, "model config")
        expected_tokenizer_sha256 = bound_sha256(tokenizer_record, "tokenizer")
        config_bytes = config_path.read_bytes()
        model_config_sha256 = hashlib.sha256(config_bytes).hexdigest()
        if model_config_sha256 != expected_config_sha256:
            raise ValueError("central model config hash does not match loaded configuration")
        tokenizer_bytes = tokenizer_path.read_bytes()
        tokenizer = load_frozen_tokenizer(tokenizer_path, expected_sha256=expected_tokenizer_sha256, snapshot_bytes=tokenizer_bytes)
        config_snapshot = _config_snapshot_path(config_bytes)
        try:
            config = RestartDecoderConfig.from_contract(config_snapshot)
        finally:
            config_snapshot.unlink(missing_ok=True)
        model = UnifiedDecoder(config, device=device, allow_production_allocation=True).eval()
        from checkpoint_artifacts import load_checkpoint_artifacts
        load_checkpoint_artifacts(
            model,
            None,
            checkpoint,
            {**manifest, "checkpoint_manifest_sha256": checkpoint_sha256},
        )
        identity = OwnedIdentity(
            checkpoint_sha256=checkpoint_sha256,
            model_config_sha256=model_config_sha256,
            tokenizer_sha256=tokenizer.sha256,
            server_source_sha256=sha(Path(__file__)),
            seat=str(admission["seat"]),
        )
        if admission["model_name"] != identity.model_name:
            raise ValueError("central admission model name does not match loaded checkpoint")
        return cls(model=model, tokenizer=tokenizer, identity=identity, device=torch.device(device), frozen_split=frozen_split)

    def chat(self, messages: list[dict[str, object]], *, frozen_row_id: str | None, max_tokens: int) -> tuple[str, str]:
        if self.frozen_split is None:
            prompt = "\n".join(f"{message.get('role', 'user')}: {message.get('content', '')}" for message in messages)
            prompt_ids = self.tokenizer.encode(prompt)
        else:
            if frozen_row_id is None:
                raise ValueError("frozen evaluation requires a frozen row identifier")
            _, record = frozen_split_prompt(self.frozen_split, frozen_row_id, self.tokenizer)
            if messages != [{"role": "user", "content": record["prompt"]}]:
                raise ValueError("chat does not match frozen split prompt")
            prompt_ids = record["token_ids"]
        with torch.inference_mode():
            generated, reason = greedy_generate(
                model=self.model,
                prompt_ids=torch.tensor([prompt_ids], dtype=torch.long, device=self.device),
                model_kwargs={"active_expert": "shared"},
                max_new_tokens=max_tokens,
                stop_token_ids=self.tokenizer.eos_token_ids,
            )
        return self.tokenizer.decode(generated), "stop" if reason == "eos" else "length"


def load_development_shared_runtime(
    *,
    checkpoint: Path,
    config_path: Path,
    checkpoint_manifest: Mapping[str, object],
    device: str,
    config_bytes: bytes | None = None,
) -> UnifiedDecoder:
    """Load the development seat shared route through the #848 BF16/meta loader."""

    try:
        contract = json.loads(config_bytes if config_bytes is not None else config_path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"development model contract is invalid: {exc}") from exc
    if not isinstance(contract, dict):
        raise ValueError("development model contract must be an object")
    snapshot_path = _config_snapshot_path(config_bytes) if config_bytes is not None else config_path
    try:
        config = RestartDecoderConfig.from_contract(snapshot_path)
    finally:
        if config_bytes is not None:
            snapshot_path.unlink(missing_ok=True)
    model = construct_runtime_model(torch, model_module, config, contract)
    tied_embeddings = tied_embeddings_from_contract(config, contract)
    shards = checkpoint_manifest.get("shards")
    if not isinstance(shards, list):
        raise ValueError("development checkpoint lacks shard records")
    records: dict[str, Mapping[str, object]] = {}
    for record in shards:
        if not isinstance(record, Mapping) or not isinstance(record.get("path"), str):
            raise ValueError("development checkpoint shard record is invalid")
        path = str(record["path"])
        if path in records:
            raise ValueError("development checkpoint contains duplicate shard records")
        records[path] = record
    shared_record = records.get("shared.pt")
    shared_sha256 = shared_record.get("sha256") if isinstance(shared_record, Mapping) else None
    if not isinstance(shared_sha256, str):
        raise ValueError("development checkpoint lacks shared shard identity")
    payload = hash_and_load_torch(torch, checkpoint / "shared.pt", shared_sha256, device=device)
    if not isinstance(payload, dict) or not isinstance(payload.get("model"), dict):
        raise ValueError("development shared checkpoint lacks a model state")
    expected = model.state_dict()
    shared_expected = {key: value for key, value in expected.items() if ".experts." not in key}
    shared_state = payload["model"]
    validate_state_map(shared_state, shared_expected, "shared")
    canonical = canonicalize_tied_embedding_state(torch, shared_state, tied_embeddings=tied_embeddings)
    model.load_state_dict(materialize_state_map(canonical, device), strict=False, assign=True)
    rebind_tied_embeddings(model, tied_embeddings=tied_embeddings)
    model._activate_expert("shared")
    return model.eval()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    authority = parser.add_mutually_exclusive_group(required=True)
    authority.add_argument("--run-manifest", type=Path)
    authority.add_argument("--development-manifest", type=Path)
    parser.add_argument("--expected-development-manifest-sha256")
    parser.add_argument("--expected-runtime-index-sha256")
    parser.add_argument("--trusted-verifier-registry", type=Path)
    parser.add_argument("--trusted-verifier-registry-approval", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--mode", choices=("INTERACTIVE", "FROZEN_EVAL"), required=True)
    parser.add_argument("--parent-pid", type=int, required=True)
    parser.add_argument("--frozen-split", type=Path)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args(argv)
    frozen_split = resolve_runtime_inputs(args.mode, args.frozen_split)
    if args.development_manifest is not None and (args.expected_development_manifest_sha256 is None or args.expected_runtime_index_sha256 is None):
        raise ValueError("development server requires exact manifest and runtime-index hashes")
    start_parent_watchdog(args.parent_pid)
    if args.development_manifest is not None:
        development = resolve_development_identity(
            args.development_manifest,
            expected_manifest_sha256=args.expected_development_manifest_sha256,
            expected_runtime_index_sha256=args.expected_runtime_index_sha256,
        )
        if development.get("server_source_sha256") != sha(Path(__file__)):
            raise ValueError("development authority does not match server source bytes")
        config_path = args.config
        checkpoint_manifest_path = args.checkpoint / "checkpoint-manifest.json"
        manifest, _checkpoint_sha256, _checkpoint_bytes = _read_bound_json_snapshot(
            checkpoint_manifest_path, expected_sha256=str(development["checkpoint_sha256"]), label="development checkpoint manifest"
        )
        _config, _config_sha256, config_bytes = _read_bound_json_snapshot(
            config_path, expected_sha256=str(development["model_config_sha256"]), label="development model config"
        )
        _tokenizer, _tokenizer_sha256, tokenizer_bytes = _read_bound_json_snapshot(
            args.tokenizer, expected_sha256=str(development["tokenizer_sha256"]), label="development tokenizer"
        )
        tokenizer = load_frozen_tokenizer(
            args.tokenizer, expected_sha256=str(development["tokenizer_sha256"]), snapshot_bytes=tokenizer_bytes
        )
        model = load_development_shared_runtime(
            checkpoint=args.checkpoint,
            config_path=config_path,
            checkpoint_manifest=manifest,
            device=args.device,
            config_bytes=config_bytes,
        )
        identity = DevelopmentIdentity(checkpoint_sha256=str(development["checkpoint_sha256"]), model_config_sha256=str(development["model_config_sha256"]), tokenizer_sha256=tokenizer.sha256, server_source_sha256=sha(Path(__file__)), tokens_seen=int(development["tokens_seen"]), allocated_parameters=int(development["allocated_parameters"]), active_parameters=int(development["active_parameters"]))
        runtime = LoadedOwnedRuntime(model=model, tokenizer=tokenizer, identity=identity, device=torch.device(args.device), frozen_split=frozen_split)
    else:
        if args.trusted_verifier_registry is None or args.trusted_verifier_registry_approval is None:
            raise ValueError("admitted server requires trusted verifier registry and external approval")
        runtime = LoadedOwnedRuntime.from_paths(checkpoint=args.checkpoint, tokenizer_path=args.tokenizer, config_path=args.config, run_manifest=args.run_manifest, trusted_verifier_registry=args.trusted_verifier_registry, trusted_verifier_registry_approval=args.trusted_verifier_registry_approval, device=args.device, frozen_split=frozen_split)
    server = create_loopback_server(runtime, host=args.host, port=args.port, mode=args.mode)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
