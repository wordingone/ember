# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

"""Fail-closed tests for scripts/ember_dispatch_token.py (#1344).

These pin the refusal-without-token / pass-with-token contract every
inventoried Ember entry point relies on. The named-pipe RPC boundary
(`_call_consume_rpc`) is mocked rather than driven against a live
`ember-lab serve` daemon -- exactly the boundary the pre-existing
`tests/ember_restart_model/test_certified_train_launch.py::DispatchAuthorityTests`
suite mocks for the same reason (a real dispatch daemon is not resident
during unit tests). Everything on this side of that boundary --
environment validation, canonical binary/source resolution, and daemon
identity cross-checks -- runs for real.
"""

import hashlib
import os

import pytest

from scripts import ember_dispatch_token as token

VALID_TOKEN = "a" * 64
VALID_PIPE = r"\\.\pipe\ember-lab-1234"
VALID_JOB_ID = "job-1344"
VALID_DAEMON_PID = "4321"


def _env(**overrides) -> dict:
    base = {
        "EMBER_LAB_PIPE": VALID_PIPE,
        "EMBER_LAB_DISPATCH_JOB_ID": VALID_JOB_ID,
        "EMBER_LAB_DISPATCH_TOKEN": VALID_TOKEN,
        "EMBER_LAB_DISPATCH_DAEMON_PID": VALID_DAEMON_PID,
    }
    base.update(overrides)
    return base


def _write_canonical_repo(tmp_path):
    """A minimal repo tree with the canonical daemon binary + source fixture in place."""
    binary_path = tmp_path / "runtime" / "ember-lab" / "target" / "release" / "ember-lab.exe"
    binary_path.parent.mkdir(parents=True)
    binary_bytes = b"fixture ember-lab daemon binary"
    binary_path.write_bytes(binary_bytes)

    digest = hashlib.sha256()
    for relative in token._EMBER_LAB_SOURCE_RELATIVE:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = f"fixture: {relative}\n".encode()
        path.write_bytes(payload)
        digest.update(len(payload).to_bytes(8, "little"))
        digest.update(payload)

    return {
        "binary_path": binary_path,
        "binary_sha256": hashlib.sha256(binary_bytes).hexdigest(),
        "source_sha256": digest.hexdigest(),
    }


def _well_formed_envelope(repo_fixture, daemon_pid: int) -> dict:
    return {
        "server_pid": daemon_pid,
        "server_binary_sha256": repo_fixture["binary_sha256"],
        "server_binary_path": str(repo_fixture["binary_path"]),
        "result": {
            "consumed": True,
            "daemon_identity": {
                "schema_version": token._RUNTIME_IDENTITY_SCHEMA,
                "pid": daemon_pid,
                "binary_sha256": repo_fixture["binary_sha256"],
                "source_sha256": repo_fixture["source_sha256"],
            },
        },
    }


def test_missing_env_var_refuses_with_required_code(monkeypatch, tmp_path):
    monkeypatch.setattr(os, "environ", {})
    with pytest.raises(token.DispatchTokenError, match="EMBER_LAB_DISPATCH_REQUIRED"):
        token.consume_dispatch(tmp_path)


def test_malformed_pipe_name_refuses_before_rpc(monkeypatch, tmp_path):
    monkeypatch.setattr(os, "environ", _env(EMBER_LAB_PIPE=r"\\.\pipe\not-ember-lab"))

    def _never(*_args, **_kwargs):
        raise AssertionError("RPC must not be attempted for a malformed pipe name")

    monkeypatch.setattr(token, "_call_consume_rpc", _never)
    with pytest.raises(token.DispatchTokenError, match="EMBER_LAB_DISPATCH_TOKEN_INVALID"):
        token.consume_dispatch(tmp_path)


def test_operator_pipe_is_refused_as_a_verifier_dispatch_pipe(monkeypatch, tmp_path):
    monkeypatch.setattr(
        os, "environ", _env(EMBER_LAB_PIPE=r"\\.\pipe\ember-operator-1234")
    )
    with pytest.raises(token.DispatchTokenError, match="EMBER_LAB_DISPATCH_TOKEN_INVALID"):
        token.consume_dispatch(tmp_path)


@pytest.mark.parametrize(
    "bad_token",
    ["A" * 64, "a" * 63, "a" * 65, "g" * 64],
)
def test_malformed_token_shape_refuses_with_token_invalid(monkeypatch, tmp_path, bad_token):
    monkeypatch.setattr(os, "environ", _env(EMBER_LAB_DISPATCH_TOKEN=bad_token))
    with pytest.raises(token.DispatchTokenError, match="EMBER_LAB_DISPATCH_TOKEN_INVALID"):
        token.consume_dispatch(tmp_path)


@pytest.mark.parametrize("bad_pid", ["0", "-1", "not-a-pid"])
def test_non_positive_daemon_pid_refuses_with_daemon_identity_refused(monkeypatch, tmp_path, bad_pid):
    monkeypatch.setattr(os, "environ", _env(EMBER_LAB_DISPATCH_DAEMON_PID=bad_pid))
    with pytest.raises(token.DispatchTokenError, match="EMBER_LAB_DISPATCH_DAEMON_IDENTITY_REFUSED"):
        token.consume_dispatch(tmp_path)


@pytest.mark.parametrize(
    "missing_var",
    ["EMBER_LAB_PIPE", "EMBER_LAB_DISPATCH_JOB_ID", "EMBER_LAB_DISPATCH_TOKEN", "EMBER_LAB_DISPATCH_DAEMON_PID"],
)
def test_blank_env_value_refuses_with_required_code(monkeypatch, tmp_path, missing_var):
    monkeypatch.setattr(os, "environ", _env(**{missing_var: ""}))
    with pytest.raises(token.DispatchTokenError, match="EMBER_LAB_DISPATCH_REQUIRED"):
        token.consume_dispatch(tmp_path)


def test_missing_canonical_binary_refuses_before_rpc_call(monkeypatch, tmp_path):
    monkeypatch.setattr(os, "environ", _env())

    def _never(*_args, **_kwargs):
        raise AssertionError("RPC must not be attempted when the daemon build is missing")

    monkeypatch.setattr(token, "_call_consume_rpc", _never)
    with pytest.raises(token.DispatchTokenError, match="EMBER_LAB_DISPATCH_REFUSED"):
        token.consume_dispatch(tmp_path)


def test_well_formed_dispatch_is_consumed_and_env_is_cleared(monkeypatch, tmp_path):
    fixture = _write_canonical_repo(tmp_path)
    monkeypatch.setattr(os, "environ", _env())
    envelope = _well_formed_envelope(fixture, int(VALID_DAEMON_PID))
    monkeypatch.setattr(token, "_call_consume_rpc", lambda *a, **k: envelope)

    token.consume_dispatch(tmp_path)

    for name in token._REQUIRED_ENV:
        assert name not in os.environ


def test_daemon_pid_mismatch_between_pipe_server_and_claim_refuses(monkeypatch, tmp_path):
    fixture = _write_canonical_repo(tmp_path)
    monkeypatch.setattr(os, "environ", _env())
    envelope = _well_formed_envelope(fixture, int(VALID_DAEMON_PID) + 1)
    monkeypatch.setattr(token, "_call_consume_rpc", lambda *a, **k: envelope)

    with pytest.raises(token.DispatchTokenError, match="EMBER_LAB_DISPATCH_DAEMON_IDENTITY_REFUSED"):
        token.consume_dispatch(tmp_path)
    assert "EMBER_LAB_DISPATCH_TOKEN" in os.environ


def test_foreign_server_binary_refuses_identity_check(monkeypatch, tmp_path):
    fixture = _write_canonical_repo(tmp_path)
    foreign = tmp_path / "foreign-ember-lab.exe"
    foreign.write_bytes(b"not the repository's build")
    monkeypatch.setattr(os, "environ", _env())
    envelope = _well_formed_envelope(fixture, int(VALID_DAEMON_PID))
    envelope["server_binary_path"] = str(foreign)
    envelope["server_binary_sha256"] = hashlib.sha256(foreign.read_bytes()).hexdigest()
    monkeypatch.setattr(token, "_call_consume_rpc", lambda *a, **k: envelope)

    with pytest.raises(token.DispatchTokenError, match="EMBER_LAB_DISPATCH_DAEMON_IDENTITY_REFUSED"):
        token.consume_dispatch(tmp_path)


def test_daemon_identity_hash_mismatch_in_rpc_result_refuses(monkeypatch, tmp_path):
    fixture = _write_canonical_repo(tmp_path)
    monkeypatch.setattr(os, "environ", _env())
    envelope = _well_formed_envelope(fixture, int(VALID_DAEMON_PID))
    envelope["result"]["daemon_identity"]["source_sha256"] = "0" * 64
    monkeypatch.setattr(token, "_call_consume_rpc", lambda *a, **k: envelope)

    with pytest.raises(token.DispatchTokenError, match="EMBER_LAB_DISPATCH_REFUSED"):
        token.consume_dispatch(tmp_path)


def test_daemon_did_not_confirm_consumption_refuses(monkeypatch, tmp_path):
    fixture = _write_canonical_repo(tmp_path)
    monkeypatch.setattr(os, "environ", _env())
    envelope = _well_formed_envelope(fixture, int(VALID_DAEMON_PID))
    envelope["result"]["consumed"] = False
    monkeypatch.setattr(token, "_call_consume_rpc", lambda *a, **k: envelope)

    with pytest.raises(token.DispatchTokenError, match="EMBER_LAB_DISPATCH_REFUSED"):
        token.consume_dispatch(tmp_path)


def test_worker_main_rejects_malformed_invocation():
    assert token._worker_main([]) == 2
    assert token._worker_main(["--wrong-flag", "a", "b", "c"]) == 2
    assert token._worker_main([token._WORKER_FLAG, "pipe", "job"]) == 2


def test_worker_main_rejects_missing_token_or_pid(monkeypatch):
    monkeypatch.delenv("EMBER_LAB_DISPATCH_TOKEN", raising=False)
    assert token._worker_main([token._WORKER_FLAG, VALID_PIPE, VALID_JOB_ID, "0"]) == 2
    assert token._worker_main([token._WORKER_FLAG, VALID_PIPE, VALID_JOB_ID, "not-an-int"]) == 2
