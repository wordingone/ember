# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""TDD coverage for the owned loopback OpenAI-compatible serving path."""

from __future__ import annotations

import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

from serve_owned_openai import OwnedIdentity, create_loopback_server, validate_admission_identity


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


    def test_admission_rejects_config_or_server_source_substitution(self) -> None:
        checkpoint = "a" * 64
        admission = {
            "seat": "OWNED_ADMITTED",
            "checkpoint_sha256": checkpoint,
            "model_config_sha256": "b" * 64,
            "tokenizer_sha256": "c" * 64,
            "server_source_sha256": "d" * 64,
            "model_name": "ember-owned:" + checkpoint[:12],
        }
        validate_admission_identity(
            admission,
            checkpoint_sha256=checkpoint,
            model_config_sha256="b" * 64,
            server_source_sha256="d" * 64,
        )
        with self.assertRaisesRegex(ValueError, "model config hash"):
            validate_admission_identity(
                admission,
                checkpoint_sha256=checkpoint,
                model_config_sha256="e" * 64,
                server_source_sha256="d" * 64,
            )
        with self.assertRaisesRegex(ValueError, "server source hash"):
            validate_admission_identity(
                admission,
                checkpoint_sha256=checkpoint,
                model_config_sha256="b" * 64,
                server_source_sha256="e" * 64,
            )

if __name__ == "__main__":
    unittest.main()