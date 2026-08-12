# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

"""Shared Ember Lab dispatch-token consumer (#1344).

`ember-cli` (`ember-lab`) is the sole entry point for every Ember process:
verification, training, certification, census, mint, eval, export. Every
Python script that can start one of those processes imports this module and
calls `consume_dispatch(repo_root)` as its first action, before touching any
receipt, certificate, or source file. A script run directly from a shell has
none of the four environment variables below set, so `consume_dispatch`
refuses immediately -- that refusal, not a policy or a README, is the
enforcement mechanism #1344 asks for.

This is the Python mirror of
`runtime/ember-lab/src/main.rs::consume_verifier_dispatch_token`: the same
four environment variables, the same named-pipe JSON-RPC method
(`consume_verifier_dispatch_token` -- generic despite the name; see
`runtime/ember-lab/src/rpc.rs`, which routes it straight to
`Daemon::consume_dispatch_token`, the identical call every dispatch consumer
uses), and the same fail-closed posture. `ember-lab serve` -- the resident
daemon -- is the only process that ever *issues* a dispatch token: it does
so when IT spawns a child process, stamping that child's environment with
EMBER_LAB_PIPE / EMBER_LAB_DISPATCH_JOB_ID / EMBER_LAB_DISPATCH_TOKEN /
EMBER_LAB_DISPATCH_DAEMON_PID. Nothing else in the codebase writes those
four variables.

Trust anchors are resolved from the repository, never from anything the
caller (env, argv) supplies: the daemon binary is the one committed build
output at `runtime/ember-lab/target/{release,debug}/ember-lab.exe`, and the
source identity hash is computed over the same seven files, the same
length-delimited way, as `ember_lab_source_hash()` in
`runtime/ember-lab/src/lib.rs`. The named pipe's real OS server process is
authenticated (PID + binary path + binary hash, via
`GetNamedPipeServerProcessId`/`QueryFullProcessImageNameW`) before a single
byte of its RPC response is trusted, and the daemon's own self-reported
identity in that response is cross-checked against the same canonical
binary/source hashes -- a forged or unrelated pipe cannot pass either check.

All blocking Win32 I/O runs in a short-lived, deadline-bounded subprocess
(`_worker_main`, invoked as `--private-ember-lab-dispatch-rpc`) so a wedged
daemon or a pipe that never responds cannot hang the caller. Windows-only,
matching the daemon itself (`ember-lab.exe` is a Windows named-pipe server).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

_REQUIRED_ENV: tuple[str, ...] = (
    "EMBER_LAB_PIPE",
    "EMBER_LAB_DISPATCH_JOB_ID",
    "EMBER_LAB_DISPATCH_TOKEN",
    "EMBER_LAB_DISPATCH_DAEMON_PID",
)
_RUNTIME_IDENTITY_SCHEMA = "ember-lab-runtime-identity-v1"
_PIPE_PREFIX = r"\\.\pipe\ember-lab-"
_OPERATOR_PIPE_PREFIX = r"\\.\pipe\ember-operator-"
_MAX_RPC_FRAME_BYTES = 64 * 1024
_RPC_DEADLINE_SECONDS = 10
_WORKER_FLAG = "--private-ember-lab-dispatch-rpc"

# Mirrors `ember_lab_source_hash()` in runtime/ember-lab/src/lib.rs byte-for-byte:
# same 7 relative files, same order, same length-prefixed sha256 digest.
_EMBER_LAB_SOURCE_RELATIVE = (
    "runtime/ember-lab/src/lib.rs",
    "runtime/ember-lab/src/data_catalog.rs",
    "runtime/ember-lab/src/rpc.rs",
    "runtime/ember-lab/src/main.rs",
    "runtime/ember-lab/src/training_verify.rs",
    "runtime/ember-lab/Cargo.toml",
    "runtime/ember-lab/Cargo.lock",
)


class DispatchTokenError(RuntimeError):
    """Refusal to consume a dispatch token. `str(error)` starts with a named code."""


def _refuse(code: str, detail: str) -> DispatchTokenError:
    return DispatchTokenError(f"{code}: {detail}")


def _canonical_ember_lab_binary(repo_root: Path) -> Path | None:
    """The one repository-governed daemon binary -- never a caller-supplied path."""
    root = repo_root.resolve(strict=True)
    for candidate in (
        root / "runtime" / "ember-lab" / "target" / "release" / "ember-lab.exe",
        root / "runtime" / "ember-lab" / "target" / "debug" / "ember-lab.exe",
    ):
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved.is_file() and resolved.is_relative_to(root):
            return resolved
    return None


def _canonical_ember_lab_source_sha256(repo_root: Path) -> str | None:
    """Reproduce Rust's `ember_lab_source_hash()` over the same 7 canonical files."""
    root = repo_root.resolve(strict=True)
    digest = hashlib.sha256()
    for relative in _EMBER_LAB_SOURCE_RELATIVE:
        path = root / relative
        try:
            raw = path.read_bytes()
        except OSError:
            return None
        digest.update(len(raw).to_bytes(8, "little"))
        digest.update(raw)
    return digest.hexdigest()


def _configured_pipe() -> str | None:
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


def _require_env_present() -> dict[str, str]:
    missing = [name for name in _REQUIRED_ENV if not os.environ.get(name, "").strip()]
    if missing:
        raise _refuse("EMBER_LAB_DISPATCH_REQUIRED", f"missing {missing[0]}")
    return {name: os.environ[name] for name in _REQUIRED_ENV}


def _validate_env_shape(values: dict[str, str]) -> tuple[str, str, str, int]:
    pipe = _configured_pipe()
    if pipe is None or pipe != values["EMBER_LAB_PIPE"]:
        raise _refuse("EMBER_LAB_DISPATCH_TOKEN_INVALID", "pipe name is not a well-formed ember-lab pipe")
    job_id = values["EMBER_LAB_DISPATCH_JOB_ID"]
    if not job_id.strip():
        raise _refuse("EMBER_LAB_DISPATCH_TOKEN_INVALID", "job id is empty")
    token = values["EMBER_LAB_DISPATCH_TOKEN"]
    if len(token) != 64 or not all(c in "0123456789abcdef" for c in token):
        raise _refuse("EMBER_LAB_DISPATCH_TOKEN_INVALID", "token is not 64 lowercase hex bytes")
    try:
        daemon_pid = int(values["EMBER_LAB_DISPATCH_DAEMON_PID"])
    except ValueError:
        daemon_pid = -1
    if daemon_pid <= 0:
        raise _refuse("EMBER_LAB_DISPATCH_DAEMON_IDENTITY_REFUSED", "daemon pid is not a positive integer")
    return pipe, job_id, token, daemon_pid


def _open_and_consume_direct(pipe_name: str, job_id: str, token: str, expected_server_pid: int) -> dict:
    """Blocking Win32 pipe I/O. Only ever runs inside the bounded worker subprocess."""
    if os.name != "nt":
        raise OSError("ember-lab dispatch consumption is Windows-only")
    import ctypes
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
        if server_pid.value != expected_server_pid:
            raise OSError("named-pipe server pid does not match the claimed dispatch daemon pid")
        process = open_process(0x1000, False, server_pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not process:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            capacity = wintypes.DWORD(32768)
            image = ctypes.create_unicode_buffer(capacity.value)
            if not query_image(process, 0, image, ctypes.byref(capacity)):
                raise ctypes.WinError(ctypes.get_last_error())
            server_binary_path = image.value
            server_binary_sha256 = hashlib.sha256(Path(server_binary_path).read_bytes()).hexdigest()
        finally:
            close_handle(process)

        request = (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "consume_verifier_dispatch_token",
                    "params": {"job_id": job_id, "token": token},
                },
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
        if len(request) > _MAX_RPC_FRAME_BYTES:
            raise OSError("ember-lab dispatch RPC request exceeds frame limit")
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
                raise OSError("ember-lab dispatch RPC response exceeds frame limit")
            if not ok and ctypes.get_last_error() != 234:  # ERROR_MORE_DATA
                raise ctypes.WinError(ctypes.get_last_error())
        line, trailing = bytes(raw).split(b"\n", 1)
        if trailing.strip():
            raise OSError("ember-lab dispatch RPC returned multiple frames")
        response = json.loads(line.decode("utf-8", errors="strict"))
    finally:
        close_handle(handle)

    if not isinstance(response, dict) or "result" not in response:
        error = response.get("error") if isinstance(response, dict) else None
        raise OSError(f"ember-lab dispatch RPC failed: {error!r}")
    result = response["result"]
    if not isinstance(result, dict):
        raise OSError("ember-lab dispatch RPC response result is not an object")
    return {
        "result": result,
        "server_pid": server_pid.value,
        "server_binary_sha256": server_binary_sha256,
        "server_binary_path": server_binary_path,
    }


def _worker_main(argv: list[str]) -> int:
    if len(argv) != 4 or argv[0] != _WORKER_FLAG:
        return 2
    _, pipe_name, job_id, daemon_pid_raw = argv
    token = os.environ.get("EMBER_LAB_DISPATCH_TOKEN", "")
    try:
        daemon_pid = int(daemon_pid_raw)
        if daemon_pid <= 0 or not token:
            return 2
        envelope = _open_and_consume_direct(pipe_name, job_id, token, daemon_pid)
        raw = json.dumps(envelope, separators=(",", ":")).encode("utf-8")
        if len(raw) > _MAX_RPC_FRAME_BYTES:
            return 2
        sys.stdout.buffer.write(raw)
        return 0
    except (OSError, ValueError, UnicodeError):
        return 2


def _call_consume_rpc(pipe_name: str, job_id: str, token: str, daemon_pid: int) -> dict:
    """Run the blocking pipe RPC in a bounded, deadline-limited worker subprocess."""
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    env = dict(os.environ)
    env["EMBER_LAB_DISPATCH_TOKEN"] = token
    try:
        completed = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).resolve()), _WORKER_FLAG, pipe_name, job_id, str(daemon_pid)],
            capture_output=True,
            check=False,
            shell=False,
            env=env,
            creationflags=creationflags,
            timeout=_RPC_DEADLINE_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise _refuse("EMBER_LAB_DISPATCH_REFUSED", "dispatch daemon did not respond before the deadline") from error
    if completed.returncode != 0 or len(completed.stdout) > _MAX_RPC_FRAME_BYTES:
        raise _refuse("EMBER_LAB_DISPATCH_REFUSED", "dispatch daemon pipe is unreachable or refused the request")
    try:
        envelope = json.loads(completed.stdout.decode("utf-8", errors="strict"))
    except (json.JSONDecodeError, UnicodeError) as error:
        raise _refuse("EMBER_LAB_DISPATCH_REFUSED", "dispatch daemon RPC returned a malformed envelope") from error
    if not isinstance(envelope, dict) or set(envelope) != {"result", "server_pid", "server_binary_sha256", "server_binary_path"}:
        raise _refuse("EMBER_LAB_DISPATCH_REFUSED", "dispatch daemon RPC returned an invalid envelope")
    return envelope


def consume_dispatch(repo_root: Path) -> None:
    """Consume this process's Ember Lab dispatch token, or raise `DispatchTokenError`.

    Every inventoried Ember entry point calls this as its first action. Fail-closed:
    any missing/malformed environment variable, unreachable pipe, unauthenticated
    daemon, or identity mismatch raises before the caller does anything else. On
    success the four dispatch env vars are removed from this process's environment
    (a spawned child never inherits a token meant for this process alone).
    """
    values = _require_env_present()
    pipe_name, job_id, token, daemon_pid = _validate_env_shape(values)

    canonical_binary = _canonical_ember_lab_binary(repo_root)
    canonical_source_sha256 = _canonical_ember_lab_source_sha256(repo_root)
    if canonical_binary is None or canonical_source_sha256 is None:
        raise _refuse("EMBER_LAB_DISPATCH_REFUSED", "canonical ember-lab daemon build is not available")
    canonical_binary_sha256 = hashlib.sha256(canonical_binary.read_bytes()).hexdigest()

    envelope = _call_consume_rpc(pipe_name, job_id, token, daemon_pid)
    if envelope["server_pid"] != daemon_pid:
        raise _refuse("EMBER_LAB_DISPATCH_DAEMON_IDENTITY_REFUSED", "named-pipe server pid does not match the claimed daemon")
    try:
        server_binary_path = Path(envelope["server_binary_path"]).resolve(strict=True)
    except OSError as error:
        raise _refuse("EMBER_LAB_DISPATCH_DAEMON_IDENTITY_REFUSED", "named-pipe server binary is unreadable") from error
    if server_binary_path != canonical_binary or envelope["server_binary_sha256"] != canonical_binary_sha256:
        raise _refuse("EMBER_LAB_DISPATCH_DAEMON_IDENTITY_REFUSED", "named-pipe server is not the repository's ember-lab build")

    result = envelope["result"]
    identity = result.get("daemon_identity") if isinstance(result, dict) else None
    if (
        not isinstance(result, dict)
        or result.get("consumed") is not True
        or not isinstance(identity, dict)
        or identity.get("schema_version") != _RUNTIME_IDENTITY_SCHEMA
        or identity.get("pid") != daemon_pid
        or identity.get("binary_sha256") != canonical_binary_sha256
        or identity.get("source_sha256") != canonical_source_sha256
    ):
        raise _refuse("EMBER_LAB_DISPATCH_REFUSED", "dispatch daemon did not confirm token consumption")

    for name in _REQUIRED_ENV:
        os.environ.pop(name, None)


if __name__ == "__main__":
    raise SystemExit(_worker_main(sys.argv[1:]))
