# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Loopback-only OpenAI-compatible serving for an admitted owned Ember checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import subprocess
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

import torch

from checkpoint_artifacts import load_checkpoint_artifacts
from infer import FrozenTokenizer, greedy_generate, load_frozen_tokenizer, sha
from model import RestartDecoderConfig, UnifiedDecoder

ROOT = Path(__file__).resolve().parents[2]


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


class OwnedChatRuntime(Protocol):
    identity: OwnedIdentity

    def chat(self, messages: list[dict[str, object]], *, max_tokens: int) -> tuple[str, str]: ...


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
def create_loopback_server(runtime: OwnedChatRuntime, *, host: str, port: int) -> ThreadingHTTPServer:
    """Create a local-only server whose identity and completions share one runtime object."""

    if host != "127.0.0.1":
        raise ValueError("owned inference server must bind exactly 127.0.0.1")

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
            self._write(200, runtime.identity.payload())

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
            messages = request.get("messages")
            if not isinstance(messages, list) or not messages or any(not isinstance(message, dict) for message in messages):
                self._write(400, _error("messages must be a nonempty array of objects"))
                return
            max_tokens = request.get("max_tokens", 64)
            if not isinstance(max_tokens, int) or not 0 < max_tokens <= 1024:
                self._write(400, _error("max_tokens must be an integer in [1, 1024]"))
                return
            text, finish_reason = runtime.chat(messages, max_tokens=max_tokens)
            self._write(200, {
                "id": "chatcmpl-owned-" + runtime.identity.checkpoint_sha256[:12],
                "object": "chat.completion",
                "created": int(time.time()),
                "model": runtime.identity.model_name,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": finish_reason}],
                "owned_identity": runtime.identity.payload(),
            })

    return ThreadingHTTPServer((host, port), Handler)


class LoadedOwnedRuntime:
    """One checkpoint/model/tokenizer realization retained for every loopback request."""

    def __init__(self, *, model: UnifiedDecoder, tokenizer: FrozenTokenizer, identity: OwnedIdentity, device: torch.device) -> None:
        self.model = model
        self.tokenizer = tokenizer
        self.identity = identity
        self.device = device

    @classmethod
    def from_paths(
        cls,
        *,
        checkpoint: Path,
        tokenizer_path: Path,
        run_manifest: Path,
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
        return cls(model=model, tokenizer=tokenizer, identity=identity, device=torch.device(device))

    def chat(self, messages: list[dict[str, object]], *, max_tokens: int) -> tuple[str, str]:
        prompt = "\n".join(f"{message.get('role', 'user')}: {message.get('content', '')}" for message in messages)
        prompt_ids = self.tokenizer.encode(prompt)
        with torch.inference_mode():
            generated, reason = greedy_generate(
                model=self.model,
                prompt_ids=torch.tensor([prompt_ids], dtype=torch.long, device=self.device),
                model_kwargs={"active_expert": "shared"},
                max_new_tokens=max_tokens,
                stop_token_ids={0},
            )
        return self.tokenizer.decode(generated), "stop" if reason == "eos" else "length"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--run-manifest", type=Path, required=True)
    parser.add_argument("--trusted-verifier-registry", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args(argv)
    runtime = LoadedOwnedRuntime.from_paths(
        checkpoint=args.checkpoint,
        tokenizer_path=args.tokenizer,
        run_manifest=args.run_manifest,
        trusted_verifier_registry=args.trusted_verifier_registry,
        device=args.device,
    )
    server = create_loopback_server(runtime, host=args.host, port=args.port)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())