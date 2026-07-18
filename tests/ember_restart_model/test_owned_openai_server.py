# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""TDD coverage for the owned loopback OpenAI-compatible serving path."""

from __future__ import annotations

import json
import hashlib
import inspect
import os
import torch
import sys
import tempfile
import subprocess
import threading
import unittest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

from serve_owned_openai import (
    DevelopmentIdentity,
    OwnedIdentity,
    create_loopback_server,
    bind_parent_process,
    require_live_parent,
    LoadedOwnedRuntime,
    resolve_central_owned_admission,
    resolve_development_identity,
    load_development_shared_runtime,
    resolve_runtime_inputs,
    start_parent_watchdog,
    _read_bound_json_snapshot,
    _config_snapshot_path,
    _same_root_snapshot,
    main as serve_main,
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
        self.calls: list[tuple[str, list[dict[str, object]]]] = []
        self.max_tokens_seen: list[int] = []

    def chat(self, messages: list[dict[str, object]], *, frozen_row_id: str, max_tokens: int) -> tuple[str, str]:
        self.calls.append((frozen_row_id, messages))
        self.max_tokens_seen.append(max_tokens)
        return ("owned answer", "stop")


class OwnedOpenAiServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = _Runtime()
        self.server = create_loopback_server(self.runtime, host="127.0.0.1", port=0, mode="FROZEN_EVAL")
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

    def test_central_resolver_uses_same_root_snapshot_not_mutable_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "run.json"
            original = b'{"authority":"captured"}'
            manifest.write_bytes(original)
            snapshot = root / ".run.json.snapshot"
            snapshot.write_bytes(original)
            checkpoint = "a" * 64

            def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
                self.assertEqual(Path(command[3]), snapshot)
                self.assertEqual(snapshot.read_bytes(), original)
                manifest.write_text('{"authority":"mutated"}', encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, json.dumps({"valid": True, "seat": "OWNED_ADMITTED", "checkpoint_sha256": checkpoint, "model_name": "ember-owned:" + checkpoint[:12]}), "")

            admitted = resolve_central_owned_admission(
                run_manifest=manifest, snapshot_manifest=snapshot,
                trusted_verifier_registry=root / "registry.json", trusted_verifier_registry_approval=root / "approval.json", checkpoint_sha256=checkpoint, runner=runner,
            )
        self.assertEqual(admitted["checkpoint_sha256"], checkpoint)
    def test_development_identity_and_sse_completion_are_non_admissible(self) -> None:
        runtime = _Runtime()
        runtime.identity = DevelopmentIdentity(
            checkpoint_sha256="a" * 64, model_config_sha256="b" * 64,
            tokenizer_sha256="c" * 64, server_source_sha256="d" * 64,
            tokens_seen=2048, allocated_parameters=3_839_161_856,
            active_parameters=1_020_589_568,
        )
        server = create_loopback_server(runtime, host="127.0.0.1", port=0, mode="INTERACTIVE")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            with urllib.request.urlopen(base + "/v1/models", timeout=2) as response:
                identity = json.loads(response.read().decode("utf-8"))
            self.assertEqual(identity["seat"], "OWNED_DEVELOPMENT")
            self.assertEqual(identity["claim_status"], "NON_ADMISSIBLE")
            self.assertEqual(identity["tokens_seen"], 2048)
            request = urllib.request.Request(
                base + "/v1/chat/completions",
                data=json.dumps({"model": runtime.identity.model_name, "messages": [{"role": "user", "content": "hello"}], "stream": True, "max_tokens": 8096}).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(request, timeout=2) as response:
                stream = response.read().decode("utf-8")
            lines = [line for line in stream.splitlines() if line.startswith("data: ")]
            self.assertEqual(len(lines), 2)
            chunk = json.loads(lines[0][6:])
            self.assertEqual(chunk["object"], "chat.completion.chunk")
            self.assertEqual(chunk["choices"], [{"index": 0, "delta": {"role": "assistant", "content": "owned answer"}, "finish_reason": "stop"}])
            self.assertEqual(lines[1], "data: [DONE]")
            self.assertEqual(runtime.max_tokens_seen, [1024])
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)
    def test_models_identity_and_chat_share_exact_owned_runtime(self) -> None:
        status, identity = self._request("/v1/models")
        expected_name = "ember-owned:" + ("a" * 12)
        self.assertEqual(status, 200)
        self.assertEqual(identity["seat"], "OWNED_ADMITTED")
        self.assertEqual(identity["checkpoint_sha256"], "a" * 64)
        self.assertEqual(identity["model_name"], expected_name)
        self.assertEqual(identity["data"][0]["id"], expected_name)
        self.assertEqual(identity["mode"], "FROZEN_EVAL")
        status, completion = self._request("/v1/chat/completions", {"model": expected_name, "ember_frozen_row_id": "row-1", "messages": [{"role": "user", "content": "hello"}], "max_tokens": 3})
        self.assertEqual(status, 200)
        self.assertEqual(completion["model"], expected_name)
        self.assertEqual(completion["choices"][0]["message"]["content"], "owned answer")
        self.assertEqual(len(self.runtime.calls), 1)
        self.assertEqual(self.runtime.calls[0][0], "row-1")

    def test_chat_rejects_identity_mismatch_and_target_leak_before_runtime(self) -> None:
        status, response = self._request("/v1/chat/completions", {"model": "ember-owned:wrong", "messages": [{"role": "user", "content": "hello"}]})
        self.assertEqual(status, 400)
        self.assertIn("model identity", response["error"]["message"])
        status, response = self._request("/v1/chat/completions", {"model": self.runtime.identity.model_name, "messages": [{"role": "user", "content": "hello", "target_ids": [1]}]})
        self.assertEqual(status, 400)
        self.assertIn("target", response["error"]["message"])
        self.assertEqual(self.runtime.calls, [])
    def test_frozen_eval_tool_schema_with_label_is_not_target_sensitive(self) -> None:
        status, response = self._request("/v1/chat/completions", {
            "model": self.runtime.identity.model_name,
            "ember_frozen_row_id": "row-1",
            "messages": [{"role": "user", "content": "hello"}],
            "tools": [{"type": "function", "function": {"name": "AskUserQuestion", "parameters": {"type": "object", "properties": {"label": {"type": "string"}}}}}],
        })
        self.assertEqual(status, 200, response)
        self.assertEqual(len(self.runtime.calls), 1)
    def test_chat_requires_a_frozen_row_id_before_runtime(self) -> None:
        status, response = self._request("/v1/chat/completions", {
            "model": self.runtime.identity.model_name,
            "messages": [{"role": "user", "content": "hello"}],
        })
        self.assertEqual(status, 400)
        self.assertIn("frozen row", response["error"]["message"])
        self.assertEqual(self.runtime.calls, [])

    def test_interactive_mode_accepts_chat_without_frozen_row(self) -> None:
        runtime = _Runtime()
        server = create_loopback_server(runtime, host="127.0.0.1", port=0, mode="INTERACTIVE")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            request = urllib.request.Request(
                base + "/v1/chat/completions",
                data=json.dumps({
                    "model": runtime.identity.model_name,
                    "messages": [{"role": "user", "content": "hello"}],
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=2) as response:
                self.assertEqual(response.status, 200)
            self.assertEqual(runtime.calls, [(None, [{"role": "user", "content": "hello"}])])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_interactive_tool_schema_with_labels_is_not_a_frozen_target_leak(self) -> None:
        runtime = _Runtime()
        server = create_loopback_server(runtime, host="127.0.0.1", port=0, mode="INTERACTIVE")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            request = urllib.request.Request(
                base + "/v1/chat/completions",
                data=json.dumps({
                    "model": runtime.identity.model_name,
                    "messages": [{"role": "user", "content": "ask a question"}],
                    "tools": [{"type": "function", "function": {"name": "AskUserQuestion", "parameters": {"type": "object", "properties": {"label": {"type": "string"}}}}}],
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(request, timeout=2) as response:
                self.assertEqual(response.status, 200)
            self.assertEqual(len(runtime.calls), 1)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)
    def test_mode_inputs_and_parent_liveness_fail_closed_before_allocation(self) -> None:
        split = Path("frozen.json")
        self.assertIsNone(resolve_runtime_inputs("INTERACTIVE", None))
        self.assertEqual(resolve_runtime_inputs("FROZEN_EVAL", split), split)
        with self.assertRaisesRegex(ValueError, "forbids"):
            resolve_runtime_inputs("INTERACTIVE", split)
        with self.assertRaisesRegex(ValueError, "requires"):
            resolve_runtime_inputs("FROZEN_EVAL", None)
        with self.assertRaisesRegex(ValueError, "mode"):
            resolve_runtime_inputs("UNKNOWN", None)
        require_live_parent(os.getpid())
        bound_parent = bind_parent_process(os.getpid())
        self.assertTrue(bound_parent.alive())
        bound_parent.close()
        self.assertFalse(bound_parent.alive())
        with self.assertRaisesRegex(RuntimeError, "parent process"):
            require_live_parent(12345, checker=lambda _pid: False)
        checks = iter((True, False, True, False, False))
        exits: list[int] = []
        receipts: list[dict[str, object]] = []
        watchdog = start_parent_watchdog(
            12345,
            poll_seconds=0.001,
            checker=lambda _pid: next(checks),
            exit_process=exits.append,
            emit_receipt=receipts.append,
        )
        watchdog.join(timeout=1)
        self.assertFalse(watchdog.is_alive())
        self.assertEqual(exits, [0])
        self.assertEqual(receipts, [{
            "schema_version": "ember-owned-parent-watchdog-v1",
            "event": "PARENT_GONE_EXIT",
            "result": "MEASURED",
            "parent_pid": 12345,
            "consecutive_missed_polls": 2,
            "poll_seconds": 0.001,
        }])

    def test_parent_watchdog_binds_one_parent_probe_and_receipts_before_exit(self) -> None:
        class Probe:
            def __init__(self) -> None:
                self.states = iter((True, False, False))
                self.closed = False

            def alive(self) -> bool:
                return next(self.states)

            def close(self) -> None:
                self.closed = True

        probe = Probe()
        events: list[object] = []
        with patch("serve_owned_openai.bind_parent_process", return_value=probe) as bind:
            watchdog = start_parent_watchdog(
                12345,
                poll_seconds=0.001,
                emit_receipt=lambda receipt: events.append(("receipt", receipt)),
                exit_process=lambda code: events.append(("exit", code)),
            )
        watchdog.join(timeout=1)
        self.assertFalse(watchdog.is_alive())
        bind.assert_called_once_with(12345)
        self.assertTrue(probe.closed)
        self.assertEqual([event[0] for event in events], ["receipt", "exit"])

    def test_parent_watchdog_probe_and_receipt_errors_still_exit(self) -> None:
        checks = iter((True, RuntimeError("probe failed"), RuntimeError("probe failed")))
        exits: list[int] = []

        def checker(_pid: int) -> bool:
            result = next(checks)
            if isinstance(result, BaseException):
                raise result
            return result

        def broken_receipt(_receipt: dict[str, object]) -> None:
            raise OSError("stderr unavailable")

        watchdog = start_parent_watchdog(
            12345,
            poll_seconds=0.001,
            checker=checker,
            emit_receipt=broken_receipt,
            exit_process=exits.append,
        )
        watchdog.join(timeout=1)
        self.assertFalse(watchdog.is_alive())
        self.assertEqual(exits, [0])
    def test_parent_watchdog_default_grace_is_two_ten_second_misses(self) -> None:
        signature = inspect.signature(start_parent_watchdog)
        self.assertEqual(signature.parameters["poll_seconds"].default, 10.0)
        self.assertEqual(signature.parameters["misses_before_exit"].default, 2)



    def test_main_checks_parent_before_loading_checkpoint(self) -> None:
        events: list[tuple[str, object]] = []
        runtime = object()
        server = MagicMock()

        def load_runtime(**kwargs: object) -> object:
            events.append(("load", kwargs))
            return runtime

        with (
            patch("serve_owned_openai.start_parent_watchdog", side_effect=lambda pid: events.append(("parent", pid))),
            patch.object(LoadedOwnedRuntime, "from_paths", side_effect=load_runtime) as load,
            patch("serve_owned_openai.create_loopback_server", return_value=server) as create,
        ):
            result = serve_main([
                "--checkpoint", "checkpoint",
                "--tokenizer", "tokenizer.json",
                "--config", "config.json",
                "--run-manifest", "run.json",
                "--trusted-verifier-registry", "registry.json",
                "--trusted-verifier-registry-approval", "approval.json",
                "--mode", "INTERACTIVE",
                "--parent-pid", str(os.getpid()),
                "--device", "cpu",
            ])

        self.assertEqual(result, 0)
        self.assertEqual(events[0], ("parent", os.getpid()))
        self.assertEqual(events[1][0], "load")
        self.assertEqual(load.call_args.kwargs["config_path"], Path("config.json"))
        self.assertIsNone(load.call_args.kwargs["frozen_split"])
        self.assertEqual(load.call_args.kwargs["trusted_verifier_registry_approval"], Path("approval.json"))
        create.assert_called_once_with(runtime, host="127.0.0.1", port=8000, mode="INTERACTIVE")
        server.serve_forever.assert_called_once_with()
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

        answer, reason = runtime.chat([{"role": "user", "content": "hello"}], frozen_row_id="row-1", max_tokens=3)
        self.assertEqual((answer, reason, model.inputs), ("eos", "stop", [[1, 2]]))
    def test_loaded_runtime_binds_chat_to_exact_frozen_split_row(self) -> None:
        class Tokenizer:
            eos_token_ids = {4}
            sha256 = "c" * 64

            def encode(self, text: str) -> list[int]:
                if text != "hello":
                    raise AssertionError(text)
                return [1, 2]

            def decode(self, token_ids: list[int]) -> str:
                return "eos"

        class Model:
            def __call__(self, input_ids: torch.Tensor, **kwargs: object) -> torch.Tensor:
                self.inputs = input_ids.squeeze(0).tolist()
                logits = torch.full((1, input_ids.shape[1], 8), -100.0)
                logits[0, -1, 4] = 100.0
                return logits

        with tempfile.TemporaryDirectory() as directory:
            split = Path(directory) / "split.json"
            split.write_text(json.dumps({"schema_version": "ember-owned-frozen-inference-split-v1", "tokenizer_sha256": "c" * 64, "rows": [{"id": "row-1", "prompt": "hello", "active_expert": "shared"}]}), encoding="utf-8")
            model = Model()
            runtime = LoadedOwnedRuntime(model=model, tokenizer=Tokenizer(), identity=self.runtime.identity, device=torch.device("cpu"), frozen_split=split)
            answer, reason = runtime.chat([{"role": "user", "content": "hello"}], frozen_row_id="row-1", max_tokens=3)
            self.assertEqual((answer, reason, model.inputs), ("eos", "stop", [1, 2]))
            with self.assertRaisesRegex(ValueError, "does not match frozen"):
                runtime.chat([{"role": "user", "content": "unbound"}], frozen_row_id="row-1", max_tokens=3)

    def test_main_requires_explicit_config_before_any_runtime_loader(self) -> None:
        with (
            patch("serve_owned_openai.start_parent_watchdog") as watchdog,
            patch.object(LoadedOwnedRuntime, "from_paths") as admitted_loader,
            patch("serve_owned_openai.resolve_development_identity") as development_resolver,
            patch("serve_owned_openai.create_loopback_server"),
        ):
            with self.assertRaises(SystemExit):
                serve_main([
                    "--checkpoint", "checkpoint", "--tokenizer", "tokenizer.json",
                    "--run-manifest", "run.json", "--trusted-verifier-registry", "registry.json",
                    "--mode", "INTERACTIVE", "--parent-pid", str(os.getpid()), "--device", "cpu",
                ])
        watchdog.assert_not_called()
        admitted_loader.assert_not_called()
        development_resolver.assert_not_called()

    def test_bound_json_snapshot_parses_the_hashed_bytes_after_path_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bound.json"
            original = b'{"identity":"original"}'
            path.write_bytes(original)
            expected = hashlib.sha256(original).hexdigest()
            read_once = Path.read_bytes

            def mutate_after_read(candidate: Path) -> bytes:
                payload = read_once(candidate)
                if candidate == path:
                    path.write_bytes(b'{"identity":"mutated"}')
                return payload

            with patch.object(Path, "read_bytes", new=mutate_after_read):
                payload, digest, snapshot = _read_bound_json_snapshot(path, expected_sha256=expected, label="development config")
        self.assertEqual(payload, {"identity": "original"})
        self.assertEqual(digest, expected)
        self.assertEqual(snapshot, original)
    def test_development_config_mismatch_stops_before_tokenizer_or_loader(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint = root / "checkpoint"
            checkpoint.mkdir()
            checkpoint_manifest = checkpoint / "checkpoint-manifest.json"
            checkpoint_manifest.write_text("{}", encoding="utf-8")
            config = root / "config.json"
            config.write_text("{}", encoding="utf-8")
            development = {
                "checkpoint_sha256": hashlib.sha256(checkpoint_manifest.read_bytes()).hexdigest(),
                "model_config_sha256": "0" * 64,
                "tokenizer_sha256": "c" * 64,
                "server_source_sha256": hashlib.sha256((ROOT / "tools" / "ember-restart-3b" / "serve_owned_openai.py").read_bytes()).hexdigest(),
                "tokens_seen": 2048,
                "allocated_parameters": 3_839_161_856,
                "active_parameters": 1_020_589_568,
            }
            with (
                patch("serve_owned_openai.start_parent_watchdog"),
                patch("serve_owned_openai.resolve_development_identity", return_value=development),
                patch("serve_owned_openai.load_frozen_tokenizer") as tokenizer,
                patch("serve_owned_openai.load_development_shared_runtime") as loader,
            ):
                with self.assertRaisesRegex(ValueError, "model config"):
                    serve_main([
                        "--checkpoint", str(checkpoint), "--tokenizer", "tokenizer.json", "--config", str(config),
                        "--development-manifest", "development.json", "--expected-development-manifest-sha256", "a" * 64, "--expected-runtime-index-sha256", "b" * 64, "--mode", "INTERACTIVE",
                        "--parent-pid", str(os.getpid()), "--device", "cpu",
                    ])
            tokenizer.assert_not_called()
            loader.assert_not_called()
    def test_development_main_requires_both_hashes_before_side_effects(self) -> None:
        for option in ("--expected-development-manifest-sha256", "--expected-runtime-index-sha256"):
            with self.subTest(option=option), patch("serve_owned_openai.start_parent_watchdog") as watchdog, patch("serve_owned_openai.resolve_development_identity") as resolver, patch("serve_owned_openai.load_frozen_tokenizer") as tokenizer, patch("serve_owned_openai.load_development_shared_runtime") as loader:
                args = ["--checkpoint", "checkpoint", "--tokenizer", "tokenizer.json", "--config", "config.json", "--development-manifest", "development.json", "--mode", "INTERACTIVE", "--parent-pid", str(os.getpid())]
                if option != "--expected-development-manifest-sha256":
                    args.extend(["--expected-development-manifest-sha256", "a" * 64])
                if option != "--expected-runtime-index-sha256":
                    args.extend(["--expected-runtime-index-sha256", "b" * 64])
                with self.assertRaisesRegex(ValueError, "exact manifest and runtime-index"):
                    serve_main(args)
                watchdog.assert_not_called()
                resolver.assert_not_called()
                tokenizer.assert_not_called()
                loader.assert_not_called()
    def test_development_main_binds_exact_config_and_constructs_resolved_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint = root / "checkpoint"
            checkpoint.mkdir()
            checkpoint_manifest = checkpoint / "checkpoint-manifest.json"
            checkpoint_manifest.write_text("{}", encoding="utf-8")
            config = root / "config.json"
            config.write_text("{}", encoding="utf-8")
            tokenizer_path = root / "tokenizer.json"
            tokenizer_path.write_text("{}", encoding="utf-8")
            tokenizer_sha256 = hashlib.sha256(tokenizer_path.read_bytes()).hexdigest()
            development = {
                "checkpoint_sha256": hashlib.sha256(checkpoint_manifest.read_bytes()).hexdigest(),
                "model_config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
                "tokenizer_sha256": tokenizer_sha256,
                "server_source_sha256": hashlib.sha256((ROOT / "tools" / "ember-restart-3b" / "serve_owned_openai.py").read_bytes()).hexdigest(),
                "tokens_seen": 2048,
                "allocated_parameters": 3_839_161_856,
                "active_parameters": 1_020_589_568,
            }
            server = MagicMock()
            with (
                patch("serve_owned_openai.start_parent_watchdog"),
                patch("serve_owned_openai.resolve_development_identity", return_value=development) as resolver,
                patch("serve_owned_openai.load_frozen_tokenizer", return_value=SimpleNamespace(sha256=tokenizer_sha256)) as tokenizer,
                patch("serve_owned_openai.load_development_shared_runtime", return_value=object()) as loader,
                patch("serve_owned_openai.create_loopback_server", return_value=server) as create,
            ):
                result = serve_main([
                    "--checkpoint", str(checkpoint), "--tokenizer", str(tokenizer_path), "--config", str(config),
                    "--development-manifest", "development.json", "--expected-development-manifest-sha256", "a" * 64, "--expected-runtime-index-sha256", "b" * 64, "--mode", "INTERACTIVE",
                    "--parent-pid", str(os.getpid()), "--device", "cpu",
                ])
        self.assertEqual(result, 0)
        resolver.assert_called_once_with(Path("development.json"), expected_manifest_sha256="a" * 64, expected_runtime_index_sha256="b" * 64)
        loader.assert_called_once_with(checkpoint=checkpoint, config_path=config, checkpoint_manifest={}, device="cpu", config_bytes=b"{}")
        tokenizer.assert_called_once_with(tokenizer_path, expected_sha256=tokenizer_sha256, snapshot_bytes=b"{}")
        runtime = create.call_args.args[0]
        self.assertEqual(runtime.identity, DevelopmentIdentity(
            checkpoint_sha256=development["checkpoint_sha256"], model_config_sha256=development["model_config_sha256"],
            tokenizer_sha256=tokenizer_sha256, server_source_sha256=development["server_source_sha256"],
            tokens_seen=2048, allocated_parameters=3_839_161_856, active_parameters=1_020_589_568,
        ))
        create.assert_called_once_with(runtime, host="127.0.0.1", port=8000, mode="INTERACTIVE")
        server.serve_forever.assert_called_once_with()
    def test_development_source_mismatch_stops_before_tokenizer_or_loader(self) -> None:
        development = {
            "checkpoint_sha256": "a" * 64,
            "model_config_sha256": "b" * 64,
            "tokenizer_sha256": "c" * 64,
            "server_source_sha256": "0" * 64,
            "tokens_seen": 2048,
            "allocated_parameters": 3_839_161_856,
            "active_parameters": 1_020_589_568,
        }
        with (
            patch("serve_owned_openai.start_parent_watchdog"),
            patch("serve_owned_openai.resolve_development_identity", return_value=development),
            patch("serve_owned_openai.load_frozen_tokenizer") as tokenizer,
            patch("serve_owned_openai.load_development_shared_runtime") as loader,
        ):
            with self.assertRaisesRegex(ValueError, "server source"):
                serve_main([
                    "--checkpoint", "checkpoint", "--tokenizer", "tokenizer.json", "--config", "config.json",
                    "--development-manifest", "development.json", "--expected-development-manifest-sha256", "a" * 64, "--expected-runtime-index-sha256", "b" * 64, "--mode", "INTERACTIVE",
                    "--parent-pid", str(os.getpid()), "--device", "cpu",
                ])
        tokenizer.assert_not_called()
        loader.assert_not_called()

    def test_private_snapshot_helpers_execute_with_real_stdlib_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authority = root / "authority.json"
            authority.write_bytes(b"original")
            same_root = _same_root_snapshot(authority, b"exact-authority")
            self.assertEqual(same_root.parent, root)
            self.assertEqual(same_root.read_bytes(), b"exact-authority")
            self.assertNotEqual(same_root, authority)

            config_snapshot = _config_snapshot_path(b'{"exact":true}')
            try:
                self.assertEqual(config_snapshot.read_bytes(), b'{"exact":true}')
            finally:
                config_snapshot.unlink(missing_ok=True)

    def test_development_loader_uses_real_validator_canonicalize_materialize_chain(self) -> None:
        from model import RestartDecoderConfig, UnifiedDecoder

        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=1, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, device="cpu")
        payload = {"model": {
            key: value.detach().clone()
            for key, value in model.state_dict().items()
            if ".experts." not in key
        }}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            config_path.write_text("{}", encoding="utf-8")
            with (
                patch("serve_owned_openai.RestartDecoderConfig.from_contract", return_value=config),
                patch("serve_owned_openai.construct_runtime_model", return_value=model) as construct,
                patch("serve_owned_openai.tied_embeddings_from_contract", return_value=True),
                patch("serve_owned_openai.hash_and_load_torch", return_value=payload) as load,
            ):
                loaded = load_development_shared_runtime(
                    checkpoint=root,
                    config_path=config_path,
                    checkpoint_manifest={"shards": [{"path": "shared.pt", "sha256": "a" * 64}]},
                    device="cpu",
                )
        self.assertIs(loaded, model)
        construct.assert_called_once()
        load.assert_called_once_with(torch, root / "shared.pt", "a" * 64, device="cpu")
        self.assertNotIn("expert-vision.pt", str(load.call_args))
        self.assertEqual(model.active_expert, "shared")
        self.assertIs(model.lm_head.weight, model.token_embedding.weight)
    def test_development_resolver_requires_exact_non_admissible_seat(self) -> None:
        payload = {"valid": True, "seat": "OWNED_DEVELOPMENT", "claim_status": "NON_ADMISSIBLE"}
        calls: list[list[str]] = []
        def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        self.assertEqual(
            resolve_development_identity(
                Path("development.json"),
                expected_manifest_sha256="a" * 64,
                expected_runtime_index_sha256="b" * 64,
                runner=runner,
            ),
            payload,
        )
        self.assertEqual(calls[0][1], "-I")
        self.assertEqual(calls[0][-4:], ["--expected-manifest-sha256", "a" * 64, "--expected-runtime-index-sha256", "b" * 64])
        payload["claim_status"] = "ADMISSIBLE"
        with self.assertRaisesRegex(ValueError, "invalid identity"):
            resolve_development_identity(
                Path("development.json"),
                expected_manifest_sha256="a" * 64,
                expected_runtime_index_sha256="b" * 64,
                runner=runner,
            )
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
            trusted_verifier_registry_approval=Path("approval.json"),
            checkpoint_sha256=checkpoint,
            runner=runner,
        )
        self.assertEqual(resolved, payload)
        self.assertEqual(calls[0][1], "-I")
        self.assertEqual(calls[0][-5:], ["run.json", "--trusted-verifier-registry", "registry.json", "--trusted-verifier-registry-approval", "approval.json"])

        payload["checkpoint_sha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "checkpoint hash"):
            resolve_central_owned_admission(
                run_manifest=Path("run.json"),
                trusted_verifier_registry=Path("registry.json"),
                trusted_verifier_registry_approval=Path("approval.json"),
                checkpoint_sha256=checkpoint,
                runner=runner,
            )
if __name__ == "__main__":
    unittest.main()
