# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

"""Fail-closed tests for scripts/ember_dispatch_token.py (#1344).

These pin the refusal-without-token / pass-with-token contract every
inventoried Ember entry point relies on. Most cases here mock the
named-pipe RPC boundary (`_call_consume_rpc`) rather than driving a live
`ember-lab serve` daemon -- exactly the boundary the pre-existing
`tests/ember_restart_model/test_certified_train_launch.py::DispatchAuthorityTests`
suite mocks for the same reason (a real dispatch daemon is not resident
during unit tests). Everything on this side of that boundary --
environment validation, canonical binary/source resolution, and daemon
identity cross-checks -- runs for real.

The one exception is
`test_live_named_pipe_fixture_consumption_uses_true_client_pid`, which
does NOT mock `_call_consume_rpc` / `_open_and_consume_direct`: it stands
up a real Windows named pipe server (a fixture standing in for
`ember-lab serve`) and drives `consume_dispatch()` through the actual
`CreateFileW`/`ReadFile`/`WriteFile` pipe connect. That boundary is the
one #1690's redo (issue #1344) fixes -- the prior implementation spawned
a helper subprocess to do this connect, so the daemon's
`GetNamedPipeClientProcessId` observed the helper's PID, never the PID
the daemon recorded at spawn time, and every real dispatch refused
unconditionally. Mocking `_call_consume_rpc` cannot catch that class of
bug because it mocks away the exact boundary the bug lives on.
"""

import hashlib
import json
import os
import sys
import threading
import uuid
from pathlib import Path

import pytest

from scripts import ember_dispatch_token as token

VALID_TOKEN = "a" * 64
VALID_PIPE = r"\\.\pipe\ember-lab-1234"
VALID_JOB_ID = "job-1344"
VALID_DAEMON_PID = "4321"
VALID_MAXIMUM_JOB_MEMORY_BYTES = 58_032_391_267


def _env(**overrides) -> dict:
    base = {
        "EMBER_LAB_PIPE": VALID_PIPE,
        "EMBER_LAB_DISPATCH_JOB_ID": VALID_JOB_ID,
        "EMBER_LAB_DISPATCH_TOKEN": VALID_TOKEN,
        "EMBER_LAB_DISPATCH_DAEMON_PID": VALID_DAEMON_PID,
        "EMBER_LAB_DISPATCH_MAXIMUM_JOB_MEMORY_BYTES": str(
            VALID_MAXIMUM_JOB_MEMORY_BYTES
        ),
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

    armed_cap = token.consume_dispatch(tmp_path)

    assert armed_cap == VALID_MAXIMUM_JOB_MEMORY_BYTES
    for name in token._REQUIRED_ENV:
        assert name not in os.environ


def _vram_contract_env() -> dict[str, str]:
    return {
        "EMBER_LAB_DISPATCH_VRAM_PROVIDER": "nvidia_smi_nvml",
        "EMBER_LAB_DISPATCH_VRAM_DEVICE_UUID": "GPU-00000000-1111-2222-3333-444444444444",
        "EMBER_LAB_DISPATCH_VRAM_FRACTION_MILLIONTHS": "500000",
        "EMBER_LAB_DISPATCH_MAXIMUM_PROCESS_VRAM_BYTES": str(12 * 1024**3),
        "EMBER_LAB_DISPATCH_MINIMUM_FREE_VRAM_BYTES": str(2 * 1024**3),
    }


def test_daemon_vram_contract_is_validated_then_preserved_for_caged_child(monkeypatch, tmp_path):
    fixture = _write_canonical_repo(tmp_path)
    vram = _vram_contract_env()
    monkeypatch.setattr(os, "environ", _env(**vram))
    envelope = _well_formed_envelope(fixture, int(VALID_DAEMON_PID))
    monkeypatch.setattr(token, "_call_consume_rpc", lambda *a, **k: envelope)

    assert token.consume_dispatch(tmp_path) == VALID_MAXIMUM_JOB_MEMORY_BYTES
    for name in token._REQUIRED_ENV:
        assert name not in os.environ
    for name, value in vram.items():
        assert os.environ[name] == value


def test_partial_or_noncanonical_vram_contract_refuses_before_rpc(monkeypatch, tmp_path):
    vram = _vram_contract_env()
    vram.pop("EMBER_LAB_DISPATCH_VRAM_DEVICE_UUID")
    monkeypatch.setattr(os, "environ", _env(**vram))
    with pytest.raises(token.DispatchTokenError, match="EMBER_LAB_DISPATCH_REQUIRED"):
        token.consume_dispatch(tmp_path)

    malformed = _vram_contract_env()
    malformed["EMBER_LAB_DISPATCH_VRAM_FRACTION_MILLIONTHS"] = "0500000"
    monkeypatch.setattr(os, "environ", _env(**malformed))
    with pytest.raises(token.DispatchTokenError, match="EMBER_LAB_DISPATCH_TOKEN_INVALID"):
        token.consume_dispatch(tmp_path)


@pytest.mark.parametrize(
    "bad_cap",
    ["", "0", "-1", "1.5", "not-bytes", str(2**64)],
)
def test_malformed_daemon_owned_job_cap_refuses(monkeypatch, tmp_path, bad_cap):
    fixture = _write_canonical_repo(tmp_path)
    monkeypatch.setattr(
        os,
        "environ",
        _env(EMBER_LAB_DISPATCH_MAXIMUM_JOB_MEMORY_BYTES=bad_cap),
    )
    envelope = _well_formed_envelope(fixture, int(VALID_DAEMON_PID))
    monkeypatch.setattr(token, "_call_consume_rpc", lambda *a, **k: envelope)

    expected = (
        "EMBER_LAB_DISPATCH_REQUIRED"
        if not bad_cap
        else "EMBER_LAB_DISPATCH_TOKEN_INVALID"
    )
    with pytest.raises(token.DispatchTokenError, match=expected):
        token.consume_dispatch(tmp_path)


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


class _FakeDaemonPipe:
    """A real Windows named pipe server standing in for `ember-lab serve` for exactly
    one request/response exchange.

    Used only by `test_live_named_pipe_fixture_consumption_uses_true_client_pid` to
    drive `consume_dispatch()` through the REAL, unmocked pipe-connect boundary
    (`_call_consume_rpc` / `_open_and_consume_direct`) -- the boundary every other test
    in this file mocks. Captures the OS-level PID Windows reports as the connecting
    client via `GetNamedPipeClientProcessId`: exactly what
    `runtime/ember-lab/src/rpc.rs::named_pipe_client_pid` reads on the real daemon, and
    what `Daemon::consume_dispatch_token` (`runtime/ember-lab/src/lib.rs`) compares
    against the PID it recorded when it spawned the job. If the RPC connect is ever
    again routed through a spawned helper process instead of running in this process,
    the observed PID diverges from `os.getpid()` and this test fails.
    """

    def __init__(self, pipe_name: str, response_result: dict):
        self.pipe_name = pipe_name
        self.response_result = response_result
        self.observed_client_pid: int | None = None
        self.error: BaseException | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._serve_once, name="fake-ember-lab-daemon", daemon=True
        )

    def __enter__(self) -> "_FakeDaemonPipe":
        self._thread.start()
        if not self._ready.wait(timeout=5):
            raise TimeoutError("fake daemon pipe fixture did not start listening in time")
        return self

    def __exit__(self, *_exc_info) -> None:
        self._thread.join(timeout=5)

    def _serve_once(self) -> None:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        pipe_access_duplex = 0x00000003
        pipe_type_byte = 0x00000000
        pipe_wait = 0x00000000
        error_pipe_connected = 535

        create_named_pipe = kernel32.CreateNamedPipeW
        create_named_pipe.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
            wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        ]
        create_named_pipe.restype = wintypes.HANDLE
        connect_named_pipe = kernel32.ConnectNamedPipe
        connect_named_pipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
        connect_named_pipe.restype = wintypes.BOOL
        get_client_pid = kernel32.GetNamedPipeClientProcessId
        get_client_pid.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
        get_client_pid.restype = wintypes.BOOL
        read_file = kernel32.ReadFile
        read_file.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
        read_file.restype = wintypes.BOOL
        write_file = kernel32.WriteFile
        write_file.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
        write_file.restype = wintypes.BOOL
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL

        handle = create_named_pipe(
            self.pipe_name, pipe_access_duplex, pipe_type_byte | pipe_wait,
            1, 65536, 65536, 0, None,
        )
        invalid_handle = ctypes.c_void_p(-1).value
        if handle == invalid_handle:
            self.error = ctypes.WinError(ctypes.get_last_error())
            self._ready.set()
            return
        self._ready.set()
        try:
            ok = connect_named_pipe(handle, None)
            if not ok and ctypes.get_last_error() != error_pipe_connected:
                raise ctypes.WinError(ctypes.get_last_error())

            client_pid = wintypes.ULONG()
            if not get_client_pid(handle, ctypes.byref(client_pid)):
                raise ctypes.WinError(ctypes.get_last_error())
            self.observed_client_pid = client_pid.value

            raw = bytearray()
            while b"\n" not in raw:
                chunk = ctypes.create_string_buffer(4096)
                read = wintypes.DWORD()
                if not read_file(handle, chunk, len(chunk), ctypes.byref(read), None):
                    raise ctypes.WinError(ctypes.get_last_error())
                raw.extend(chunk.raw[: read.value])
            request = json.loads(bytes(raw).split(b"\n", 1)[0].decode("utf-8"))

            response = {
                "jsonrpc": "2.0",
                "id": request.get("id", 1),
                "result": self.response_result,
            }
            payload = (json.dumps(response, separators=(",", ":")) + "\n").encode("utf-8")
            written = wintypes.DWORD()
            if not write_file(handle, payload, len(payload), ctypes.byref(written), None):
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException as error:  # surfaced to the test thread via self.error
            self.error = error
        finally:
            close_handle(handle)


@pytest.mark.skipif(sys.platform != "win32", reason="named-pipe RPC is Windows-only")
def test_live_named_pipe_fixture_consumption_uses_true_client_pid(monkeypatch, tmp_path):
    """Unmocked regression test for the #1344 redo (PR #1690).

    Drives `consume_dispatch()` through the real pipe-connect boundary against a real
    named pipe server fixture -- `_call_consume_rpc` and `_open_and_consume_direct` run
    for real, nothing is monkeypatched past them. Only the canonical-binary/source
    resolution is stubbed (an orthogonal concern: which build this test trusts, not how
    it talks to the pipe) so a live `ember-lab.exe` build is not required to run this
    suite.

    Before the fix, `_call_consume_rpc` spawned a helper subprocess to perform this
    exact connect, so the fixture would have observed the helper's PID here, never this
    test process's own PID -- the same reason the real daemon always refused. This test
    fails exactly the way the real daemon would have.
    """
    own_pid = os.getpid()
    own_binary = Path(sys.executable).resolve(strict=True)
    own_binary_sha256 = hashlib.sha256(own_binary.read_bytes()).hexdigest()
    fixture_source_sha256 = "b" * 64

    monkeypatch.setattr(token, "_canonical_ember_lab_binary", lambda repo_root: own_binary)
    monkeypatch.setattr(
        token, "_canonical_ember_lab_source_sha256", lambda repo_root: fixture_source_sha256
    )

    pipe_name = rf"\\.\pipe\ember-lab-test-live-{uuid.uuid4().hex}"
    monkeypatch.setattr(
        os,
        "environ",
        _env(EMBER_LAB_PIPE=pipe_name, EMBER_LAB_DISPATCH_DAEMON_PID=str(own_pid)),
    )

    response_result = {
        "consumed": True,
        "daemon_identity": {
            "schema_version": token._RUNTIME_IDENTITY_SCHEMA,
            "pid": own_pid,
            "binary_sha256": own_binary_sha256,
            "source_sha256": fixture_source_sha256,
        },
    }

    with _FakeDaemonPipe(pipe_name, response_result) as daemon:
        armed_cap = token.consume_dispatch(tmp_path)

    assert daemon.error is None, f"fake daemon pipe fixture failed: {daemon.error!r}"
    assert daemon.observed_client_pid == own_pid, (
        "the named pipe's real OS client PID must be THIS process's PID; if it is not, "
        "the pipe connect happened in a spawned helper process again and the real "
        "dispatch daemon would refuse every consumption"
    )
    assert armed_cap == VALID_MAXIMUM_JOB_MEMORY_BYTES
    for name in token._REQUIRED_ENV:
        assert name not in os.environ
