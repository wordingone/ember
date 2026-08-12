# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

"""Consume one daemon-owned Ember process dispatch capability before effects."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path


_PIPE_PREFIX = r"\\.\pipe\ember-lab-"
_MAX_FRAME_BYTES = 64 * 1024
_SOURCE_FILES = (
    "runtime/ember-lab/src/lib.rs",
    "runtime/ember-lab/src/data_catalog.rs",
    "runtime/ember-lab/src/rpc.rs",
    "runtime/ember-lab/src/main.rs",
    "runtime/ember-lab/src/training_verify.rs",
    "runtime/ember-lab/Cargo.toml",
    "runtime/ember-lab/Cargo.lock",
)


class DispatchRefused(RuntimeError):
    pass


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not isinstance(value, str) or not value:
        raise DispatchRefused(f"EMBER_LAB_DISPATCH_REQUIRED: missing {name}")
    return value


def _canonical_binary(root: Path) -> Path:
    root = root.resolve(strict=True)
    name = "ember-lab.exe" if os.name == "nt" else "ember-lab"
    for relative in (
        Path("runtime/ember-lab/target/release") / name,
        Path("runtime/ember-lab/target/debug") / name,
    ):
        candidate = (root / relative).resolve(strict=False)
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved.is_file() and resolved.is_relative_to(root):
            return resolved
    raise DispatchRefused("EMBER_LAB_DISPATCH_REFUSED: canonical daemon binary is unavailable")


def _source_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for relative in _SOURCE_FILES:
        raw = (root / relative).read_bytes()
        digest.update(len(raw).to_bytes(8, "little"))
        digest.update(raw)
    return digest.hexdigest()


def _call(
    pipe_name: str,
    request: bytes,
    expected_pid: int,
    expected_binary: Path,
) -> dict[str, object]:
    if os.name != "nt":
        raise DispatchRefused("EMBER_LAB_DISPATCH_REFUSED: named-pipe authentication is Windows-only")
    from ctypes import wintypes
    import msvcrt

    try:
        with open(pipe_name, "r+b", buffering=0) as stream:
            handle = wintypes.HANDLE(msvcrt.get_osfhandle(stream.fileno()))
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            get_server_pid = kernel32.GetNamedPipeServerProcessId
            get_server_pid.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
            get_server_pid.restype = wintypes.BOOL
            server_pid = wintypes.ULONG()
            if not get_server_pid(handle, ctypes.byref(server_pid)) or server_pid.value != expected_pid:
                raise DispatchRefused("EMBER_LAB_DISPATCH_REFUSED: daemon PID identity mismatch")
            open_process = kernel32.OpenProcess
            open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            open_process.restype = wintypes.HANDLE
            query_image = kernel32.QueryFullProcessImageNameW
            query_image.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
            query_image.restype = wintypes.BOOL
            close_handle = kernel32.CloseHandle
            process = open_process(0x1000, False, server_pid.value)
            if not process:
                raise DispatchRefused("EMBER_LAB_DISPATCH_REFUSED: daemon image is unavailable")
            try:
                capacity = wintypes.DWORD(32768)
                image = ctypes.create_unicode_buffer(capacity.value)
                if not query_image(process, 0, image, ctypes.byref(capacity)):
                    raise DispatchRefused("EMBER_LAB_DISPATCH_REFUSED: daemon image is unavailable")
                server_binary = Path(image.value).resolve(strict=True)
            finally:
                close_handle(process)
            if os.path.normcase(str(server_binary)) != os.path.normcase(str(expected_binary)) or hashlib.sha256(server_binary.read_bytes()).digest() != hashlib.sha256(expected_binary.read_bytes()).digest():
                raise DispatchRefused("EMBER_LAB_DISPATCH_REFUSED: daemon image identity mismatch")
            stream.write(request)
            raw = stream.readline(_MAX_FRAME_BYTES + 1)
    except OSError as error:
        raise DispatchRefused("EMBER_LAB_DISPATCH_REFUSED: daemon pipe unavailable") from error
    if len(raw) > _MAX_FRAME_BYTES or not raw.endswith(b"\n"):
        raise DispatchRefused("EMBER_LAB_DISPATCH_REFUSED: invalid daemon response frame")
    try:
        response = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DispatchRefused("EMBER_LAB_DISPATCH_REFUSED: malformed daemon response") from error
    if not isinstance(response, dict) or set(response) != {"jsonrpc", "id", "result"}:
        raise DispatchRefused("EMBER_LAB_DISPATCH_REFUSED: unexpected daemon response")
    result = response.get("result")
    if response.get("jsonrpc") != "2.0" or response.get("id") != 1 or not isinstance(result, dict):
        raise DispatchRefused("EMBER_LAB_DISPATCH_REFUSED: mismatched daemon response")
    return result


def consume_dispatch(root: Path) -> None:
    """Authenticate one resident daemon and atomically consume its child token."""
    root = root.resolve(strict=True)
    pipe = _required("EMBER_LAB_PIPE")
    job_id = _required("EMBER_LAB_DISPATCH_JOB_ID")
    token = _required("EMBER_LAB_DISPATCH_TOKEN")
    pid_text = _required("EMBER_LAB_DISPATCH_DAEMON_PID")
    if (
        not pipe.startswith(_PIPE_PREFIX)
        or len(pipe) > 240
        or any(value in pipe for value in ("\r", "\n", "\0"))
        or not job_id.strip()
        or len(token) != 64
        or any(character not in "0123456789abcdef" for character in token)
    ):
        raise DispatchRefused("EMBER_LAB_DISPATCH_REFUSED: invalid dispatch identity")
    try:
        expected_pid = int(pid_text)
    except ValueError as error:
        raise DispatchRefused("EMBER_LAB_DISPATCH_REFUSED: invalid daemon PID") from error
    if expected_pid < 1:
        raise DispatchRefused("EMBER_LAB_DISPATCH_REFUSED: invalid daemon PID")
    request = (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "consume_dispatch_token",
                "params": {"job_id": job_id, "token": token},
            },
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    canonical_binary = _canonical_binary(root)
    result = _call(pipe, request, expected_pid, canonical_binary)
    identity = result.get("daemon_identity")
    binary_sha = hashlib.sha256(canonical_binary.read_bytes()).hexdigest()
    if (
        result.get("consumed") is not True
        or not isinstance(identity, dict)
        or identity.get("schema_version") != "ember-lab-runtime-identity-v1"
        or identity.get("pid") != expected_pid
        or identity.get("binary_sha256") != binary_sha
        or identity.get("source_sha256") != _source_sha256(root)
    ):
        raise DispatchRefused("EMBER_LAB_DISPATCH_REFUSED: daemon identity mismatch")
    for name in (
        "EMBER_LAB_DISPATCH_TOKEN",
        "EMBER_LAB_DISPATCH_JOB_ID",
        "EMBER_LAB_DISPATCH_DAEMON_PID",
    ):
        os.environ.pop(name, None)
