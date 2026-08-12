# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "ember_dispatch_token.py"


def load_module():
    spec = importlib.util.spec_from_file_location("ember_dispatch_token_under_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def environment() -> dict[str, str]:
    return {
        "EMBER_LAB_PIPE": r"\\.\pipe\ember-lab-owned",
        "EMBER_LAB_DISPATCH_JOB_ID": "owned-job",
        "EMBER_LAB_DISPATCH_TOKEN": "a" * 64,
        "EMBER_LAB_DISPATCH_DAEMON_PID": "4321",
    }


def identity(binary_sha: str, source_sha: str) -> dict[str, object]:
    return {
        "consumed": True,
        "daemon_identity": {
            "schema_version": "ember-lab-runtime-identity-v1",
            "pid": 4321,
            "binary_sha256": binary_sha,
            "source_sha256": source_sha,
        },
    }


def test_open_pipe_retries_only_the_bounded_server_instance_handoff() -> None:
    module = load_module()
    transient = OSError("pipe busy")
    transient.winerror = 231
    opened = mock.MagicMock()
    attempts = [transient, opened]

    def open_attempt(*_args, **_kwargs):
        outcome = attempts.pop(0)
        if isinstance(outcome, OSError):
            raise outcome
        return outcome

    with (
        mock.patch("builtins.open", side_effect=open_attempt),
        mock.patch.object(module.time, "sleep", return_value=None) as sleep,
    ):
        assert module._open_pipe(r"\\.\pipe\ember-lab-owned") is opened
    assert attempts == []
    sleep.assert_called_once_with(0.02)


def test_open_pipe_does_not_retry_a_nontransient_error() -> None:
    module = load_module()
    refused = OSError("access denied")
    refused.winerror = 5
    with (
        mock.patch("builtins.open", side_effect=refused) as opened,
        mock.patch.object(module.time, "sleep", return_value=None) as sleep,
    ):
        try:
            module._open_pipe(r"\\.\pipe\ember-lab-owned")
        except module.DispatchRefused as error:
            assert "daemon pipe unavailable" in str(error)
        else:
            raise AssertionError("nontransient pipe failure was accepted")
    assert opened.call_count == 1
    sleep.assert_not_called()


def test_consumes_once_and_clears_daemon_secret_before_runner_effects(tmp_path: Path) -> None:
    module = load_module()
    binary = tmp_path / "ember-lab.exe"
    binary.write_bytes(b"daemon")
    binary_sha = module.hashlib.sha256(binary.read_bytes()).hexdigest()
    source_sha = "b" * 64
    with (
        mock.patch.dict(os.environ, environment(), clear=True),
        mock.patch.object(module, "_canonical_binary", return_value=binary),
        mock.patch.object(module, "_source_sha256", return_value=source_sha),
        mock.patch.object(module, "_call", return_value=identity(binary_sha, source_sha)) as call,
    ):
        module.consume_dispatch(tmp_path)
        assert "EMBER_LAB_DISPATCH_TOKEN" not in os.environ
        assert "EMBER_LAB_DISPATCH_JOB_ID" not in os.environ
        assert "EMBER_LAB_DISPATCH_DAEMON_PID" not in os.environ
    assert call.call_count == 1
    assert call.call_args.args[2:] == (4321, binary)


def test_self_consistent_response_with_wrong_daemon_binary_refuses(tmp_path: Path) -> None:
    module = load_module()
    binary = tmp_path / "ember-lab.exe"
    binary.write_bytes(b"daemon")
    source_sha = "b" * 64
    with (
        mock.patch.dict(os.environ, environment(), clear=True),
        mock.patch.object(module, "_canonical_binary", return_value=binary),
        mock.patch.object(module, "_source_sha256", return_value=source_sha),
        mock.patch.object(module, "_call", return_value=identity("c" * 64, source_sha)),
    ):
        try:
            module.consume_dispatch(tmp_path)
        except module.DispatchRefused as error:
            assert "daemon identity mismatch" in str(error)
        else:
            raise AssertionError("wrong daemon binary identity was accepted")
