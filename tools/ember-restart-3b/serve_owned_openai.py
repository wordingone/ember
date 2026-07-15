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
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Protocol

import torch

from checkpoint_artifacts import load_checkpoint_artifacts
from infer import FrozenTokenizer, frozen_split_prompt, greedy_generate, load_frozen_tokenizer, sha
from model import RestartDecoderConfig, UnifiedDecoder

ROOT = Path(__file__).resolve().parents[2]
RuntimeMode = Literal["INTERACTIVE", "FROZEN_EVAL"]


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


def start_parent_watchdog(
    parent_pid: int,
    *,
    poll_seconds: float = 1.0,
    checker: Callable[[int], bool] = parent_process_alive,
    exit_process: Callable[[int], None] = os._exit,
) -> threading.Thread:
    require_live_parent(parent_pid, checker=checker)

    def watch() -> None:
        while True:
            time.sleep(poll_seconds)
            if not checker(parent_pid):
                exit_process(0)
                return

    thread = threading.Thread(target=watch, name="ember-owned-parent-watchdog", daemon=True)
    thread.start()
    return thread



def resolve_central_owned_admission(
    *,
    run_manifest: Path,
    trusted_verifier_registry: Path,
    checkpoint_sha256: str,
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
) -> dict[str, object]:
    """Execute the central seat resolver and bind its decision to the loaded checkpoint."""

    command = [
        sys.executable,
        "-I",
        str(ROOT / "scripts" / "ember_restart" / "cli_seat.py"),
        str(run_manifest),
        "--trusted-verifier-registry",
        str(trusted_verifier_registry),
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

def resolve_development_identity(development_manifest: Path, *, runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None) -> dict[str, object]:
    command = [sys.executable, "-I", str(ROOT / "scripts" / "ember_restart" / "development_cli_seat.py"), str(development_manifest)]
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
            if _contains_target_leak(request):
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
            if not isinstance(max_tokens, int) or not 0 < max_tokens <= 1024:
                self._write(400, _error("max_tokens must be an integer in [1, 1024]"))
                return
            text, finish_reason = runtime.chat(messages, frozen_row_id=frozen_row_id, max_tokens=max_tokens)
            completion = {
                "id": "chatcmpl-owned-" + runtime.identity.checkpoint_sha256[:12],
                "object": "chat.completion",
                "created": int(time.time()), "model": runtime.identity.model_name,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": finish_reason}],
                "owned_identity": runtime.identity.payload(),
            }
            if request.get("stream") is True:
                self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.send_header("Cache-Control", "no-cache"); self.end_headers()
                self.wfile.write(("data: " + json.dumps(completion, sort_keys=True, separators=(",", ":")) + "\n\ndata: [DONE]\n\n").encode("utf-8")); self.wfile.flush()
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
        run_manifest: Path,
        frozen_split: Path | None,
        trusted_verifier_registry: Path,
        device: str,
    ) -> "LoadedOwnedRuntime":
        config_path = ROOT / "configs" / "ember-restart-3b.json"
        manifest_path = checkpoint / "checkpoint-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        checkpoint_sha256 = sha(manifest_path)
        run_manifest_sha256 = sha(run_manifest)
        admission = resolve_central_owned_admission(
            run_manifest=run_manifest,
            trusted_verifier_registry=trusted_verifier_registry,
            checkpoint_sha256=checkpoint_sha256,
        )
        if sha(run_manifest) != run_manifest_sha256:
            raise ValueError("central run manifest changed during owned-seat resolution")
        try:
            central_manifest = json.loads(run_manifest.read_text(encoding="utf-8"))
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
        model_config_sha256 = sha(config_path)
        if model_config_sha256 != expected_config_sha256:
            raise ValueError("central model config hash does not match loaded configuration")
        tokenizer = load_frozen_tokenizer(tokenizer_path, expected_sha256=expected_tokenizer_sha256)
        config = RestartDecoderConfig.from_contract(config_path)
        model = UnifiedDecoder(config, device=device, allow_production_allocation=True).eval()
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    authority = parser.add_mutually_exclusive_group(required=True)
    authority.add_argument("--run-manifest", type=Path)
    authority.add_argument("--development-manifest", type=Path)
    parser.add_argument("--trusted-verifier-registry", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--mode", choices=("INTERACTIVE", "FROZEN_EVAL"), required=True)
    parser.add_argument("--parent-pid", type=int, required=True)
    parser.add_argument("--frozen-split", type=Path)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args(argv)
    frozen_split = resolve_runtime_inputs(args.mode, args.frozen_split)
    start_parent_watchdog(args.parent_pid)
    if args.development_manifest is not None:
        development = resolve_development_identity(args.development_manifest)
        config_path = ROOT / "configs" / "ember-restart-3b.json"
        checkpoint_manifest = args.checkpoint / "checkpoint-manifest.json"
        if sha(checkpoint_manifest) != development["checkpoint_sha256"] or sha(config_path) != development["model_config_sha256"]:
            raise ValueError("development authority does not match checkpoint/config bytes")
        tokenizer = load_frozen_tokenizer(args.tokenizer, expected_sha256=str(development["tokenizer_sha256"]))
        model = UnifiedDecoder(RestartDecoderConfig.from_contract(config_path), device=args.device, allow_production_allocation=True).eval()
        manifest = json.loads(checkpoint_manifest.read_text(encoding="utf-8"))
        load_checkpoint_artifacts(model, None, args.checkpoint, {**manifest, "checkpoint_manifest_sha256": development["checkpoint_sha256"]})
        identity = DevelopmentIdentity(checkpoint_sha256=str(development["checkpoint_sha256"]), model_config_sha256=str(development["model_config_sha256"]), tokenizer_sha256=tokenizer.sha256, server_source_sha256=sha(Path(__file__)), tokens_seen=int(development["tokens_seen"]), allocated_parameters=int(development["allocated_parameters"]), active_parameters=int(development["active_parameters"]))
        runtime = LoadedOwnedRuntime(model=model, tokenizer=tokenizer, identity=identity, device=torch.device(args.device), frozen_split=frozen_split)
    else:
        if args.trusted_verifier_registry is None:
            raise ValueError("admitted server requires trusted verifier registry")
        runtime = LoadedOwnedRuntime.from_paths(checkpoint=args.checkpoint, tokenizer_path=args.tokenizer, run_manifest=args.run_manifest, trusted_verifier_registry=args.trusted_verifier_registry, device=args.device, frozen_split=frozen_split)
    server = create_loopback_server(runtime, host=args.host, port=args.port, mode=args.mode)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())