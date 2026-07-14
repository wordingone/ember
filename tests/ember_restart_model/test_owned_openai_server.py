# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""TDD coverage for the owned loopback OpenAI-compatible serving path."""

from __future__ import annotations

import json
import torch
import sys
import subprocess
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

from serve_owned_openai import (
    OwnedIdentity,
    create_loopback_server,
    LoadedOwnedRuntime,
    resolve_central_owned_admission,
)


class _Runtime:
    def __init__(self) -> None:
        checkpoint = "a" * 64
        self.identity = OwnedIdentity(
            checkpoint_sha256=checkpoint,
            model_config_sha256="b" * 64,
            tokenizer_sha256="c" * 64,
            server_source_sha256="d" * 64,
        )
        self.calls: list[list[dict[str, object]]] = []

    def chat(self, messages: list[dict[str, object]], *, max_tokens: int) -> tuple[str, str]:
        self.calls.append(messages)
        return ("owned answer", "stop")


class OwnedOpenAiServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = _Runtime()
        self.server = create_loopback_server(self.runtime, host="127.0.0.1", port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def _request(self, path: str, payload: dict[str, object] | None = None) -> tuple[int, dict[str, object]]:
        request = urllib.request.Request(
            self.base + path,
            data=None if payload is None else json.dumps(payload).encode("utf-8"),
            headers={} if payload is None else {"Content-Type": "application/json"},
            method="GET" if payload is None else "POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def test_models_identity_and_chat_share_exact_owned_runtime(self) -> None:
        status, identity = self._request("/v1/models")
        expected_name = "ember-owned:" + ("a" * 12)
        self.assertEqual(status, 200)
        self.assertEqual(identity["seat"], "OWNED_ADMITTED")
        self.assertEqual(identity["checkpoint_sha256"], "a" * 64)
        self.assertEqual(identity["model_name"], expected_name)
        self.assertEqual(identity["data"][0]["id"], expected_name)
        status, completion = self._request("/v1/chat/completions", {"model": expected_name, "messages": [{"role": "user", "content": "hello"}], "max_tokens": 3})
        self.assertEqual(status, 200)
        self.assertEqual(completion["model"], expected_name)
        self.assertEqual(completion["choices"][0]["message"]["content"], "owned answer")
        self.assertEqual(len(self.runtime.calls), 1)

    def test_chat_rejects_identity_mismatch_and_target_leak_before_runtime(self) -> None:
        status, response = self._request("/v1/chat/completions", {"model": "ember-owned:wrong", "messages": [{"role": "user", "content": "hello"}]})
        self.assertEqual(status, 400)
        self.assertIn("model identity", response["error"]["message"])
        status, response = self._request("/v1/chat/completions", {"model": self.runtime.identity.model_name, "messages": [{"role": "user", "content": "hello", "target_ids": [1]}]})
        self.assertEqual(status, 400)
        self.assertIn("target", response["error"]["message"])
        self.assertEqual(self.runtime.calls, [])



    def test_loaded_runtime_stops_on_tokenizer_derived_eos(self) -> None:
        class Tokenizer:
            eos_token_ids = {4}

            def encode(self, text: str) -> list[int]:
                if text != "user: hello":
                    raise AssertionError(text)
                return [1, 2]

            def decode(self, token_ids: list[int]) -> str:
                if token_ids != [4]:
                    raise AssertionError(token_ids)
                return "eos"

        class Model:
            def __init__(self) -> None:
                self.inputs: list[list[int]] = []

            def __call__(self, input_ids: torch.Tensor, **kwargs: object) -> torch.Tensor:
                self.inputs.append(input_ids.squeeze(0).tolist())
                if kwargs != {"active_expert": "shared"}:
                    raise AssertionError(kwargs)
                logits = torch.full((1, input_ids.shape[1], 8), -100.0)
                logits[0, -1, 4] = 100.0
                return logits

        model = Model()
        runtime = LoadedOwnedRuntime(
            model=model,
            tokenizer=Tokenizer(),
            identity=self.runtime.identity,
            device=torch.device("cpu"),
        )

        answer, reason = runtime.chat([{"role": "user", "content": "hello"}], max_tokens=3)
        self.assertEqual((answer, reason, model.inputs), ("eos", "stop", [[1, 2]]))
    def test_central_admission_requires_exact_resolved_owned_seat(self) -> None:
        checkpoint = "a" * 64
        payload = {
            "valid": True,
            "seat": "OWNED_ADMITTED",
            "checkpoint_sha256": checkpoint,
            "model_name": "ember-owned:" + checkpoint[:12],
            "errors": [],
        }
        calls: list[list[str]] = []

        def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

        resolved = resolve_central_owned_admission(
            run_manifest=Path("run.json"),
            trusted_verifier_registry=Path("registry.json"),
            checkpoint_sha256=checkpoint,
            runner=runner,
        )
        self.assertEqual(resolved, payload)
        self.assertEqual(calls[0][1], "-I")
        self.assertEqual(calls[0][-3:], ["run.json", "--trusted-verifier-registry", "registry.json"])

        payload["checkpoint_sha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "checkpoint hash"):
            resolve_central_owned_admission(
                run_manifest=Path("run.json"),
                trusted_verifier_registry=Path("registry.json"),
                checkpoint_sha256=checkpoint,
                runner=runner,
            )
if __name__ == "__main__":
    unittest.main()