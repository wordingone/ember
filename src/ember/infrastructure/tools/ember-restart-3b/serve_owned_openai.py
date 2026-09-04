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
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Protocol

import torch

_REPO_IMPORT_HOME = Path(__file__).resolve().parents[5]
if str(_REPO_IMPORT_HOME) not in sys.path:
    sys.path.insert(0, str(_REPO_IMPORT_HOME))
from src.ember.runtime.infer import FrozenTokenizer, frozen_split_prompt, greedy_generate, load_frozen_tokenizer, sha
# issue2015 exact-local-import:src/ember/model/model.py
import importlib.util as _ember_4108d33796031947_importlib
import sys as _ember_4108d33796031947_sys
from pathlib import Path as _ember_4108d33796031947_Path
_ember_4108d33796031947_path = _ember_4108d33796031947_Path(__file__).resolve().parents[5].joinpath('src', 'ember', 'model', 'model.py')
if not _ember_4108d33796031947_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/model/model.py')
_ember_4108d33796031947_aliases = ('_ember_issue2015_4108d33796031947', 'model')
_ember_4108d33796031947_existing = []
for _ember_4108d33796031947_alias in _ember_4108d33796031947_aliases:
    _ember_4108d33796031947_candidate = _ember_4108d33796031947_sys.modules.get(_ember_4108d33796031947_alias)
    if _ember_4108d33796031947_candidate is not None and all(_ember_4108d33796031947_candidate is not item for item in _ember_4108d33796031947_existing):
        _ember_4108d33796031947_existing.append(_ember_4108d33796031947_candidate)
if len(_ember_4108d33796031947_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/model/model.py')
if _ember_4108d33796031947_existing:
    _ember_4108d33796031947_module = _ember_4108d33796031947_existing[0]
    _ember_4108d33796031947_observed = getattr(_ember_4108d33796031947_module, '__file__', None)
    if _ember_4108d33796031947_observed is None or _ember_4108d33796031947_Path(_ember_4108d33796031947_observed).resolve() != _ember_4108d33796031947_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/model/model.py')
else:
    _ember_4108d33796031947_spec = _ember_4108d33796031947_importlib.spec_from_file_location('_ember_issue2015_4108d33796031947', _ember_4108d33796031947_path)
    if _ember_4108d33796031947_spec is None or _ember_4108d33796031947_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/model/model.py')
    _ember_4108d33796031947_module = _ember_4108d33796031947_importlib.module_from_spec(_ember_4108d33796031947_spec)
    for _ember_4108d33796031947_alias in _ember_4108d33796031947_aliases:
        _ember_4108d33796031947_prior = _ember_4108d33796031947_sys.modules.get(_ember_4108d33796031947_alias)
        if _ember_4108d33796031947_prior is not None and _ember_4108d33796031947_prior is not _ember_4108d33796031947_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/model/model.py')
        _ember_4108d33796031947_sys.modules[_ember_4108d33796031947_alias] = _ember_4108d33796031947_module
    try:
        _ember_4108d33796031947_spec.loader.exec_module(_ember_4108d33796031947_module)
    except BaseException:
        for _ember_4108d33796031947_alias in _ember_4108d33796031947_aliases:
            if _ember_4108d33796031947_sys.modules.get(_ember_4108d33796031947_alias) is _ember_4108d33796031947_module:
                _ember_4108d33796031947_sys.modules.pop(_ember_4108d33796031947_alias, None)
        raise
for _ember_4108d33796031947_alias in _ember_4108d33796031947_aliases:
    _ember_4108d33796031947_prior = _ember_4108d33796031947_sys.modules.get(_ember_4108d33796031947_alias)
    if _ember_4108d33796031947_prior is not None and _ember_4108d33796031947_prior is not _ember_4108d33796031947_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/model/model.py')
    _ember_4108d33796031947_sys.modules[_ember_4108d33796031947_alias] = _ember_4108d33796031947_module
model_module = _ember_4108d33796031947_module
# issue2015 exact-local-import-end:src/ember/model/model.py
# issue2015 exact-local-import:src/ember/model/model.py
import importlib.util as _ember_4108d33796031947_importlib
import sys as _ember_4108d33796031947_sys
from pathlib import Path as _ember_4108d33796031947_Path
_ember_4108d33796031947_path = _ember_4108d33796031947_Path(__file__).resolve().parents[5].joinpath('src', 'ember', 'model', 'model.py')
if not _ember_4108d33796031947_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/model/model.py')
_ember_4108d33796031947_aliases = ('_ember_issue2015_4108d33796031947', 'model')
_ember_4108d33796031947_existing = []
for _ember_4108d33796031947_alias in _ember_4108d33796031947_aliases:
    _ember_4108d33796031947_candidate = _ember_4108d33796031947_sys.modules.get(_ember_4108d33796031947_alias)
    if _ember_4108d33796031947_candidate is not None and all(_ember_4108d33796031947_candidate is not item for item in _ember_4108d33796031947_existing):
        _ember_4108d33796031947_existing.append(_ember_4108d33796031947_candidate)
if len(_ember_4108d33796031947_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/model/model.py')
if _ember_4108d33796031947_existing:
    _ember_4108d33796031947_module = _ember_4108d33796031947_existing[0]
    _ember_4108d33796031947_observed = getattr(_ember_4108d33796031947_module, '__file__', None)
    if _ember_4108d33796031947_observed is None or _ember_4108d33796031947_Path(_ember_4108d33796031947_observed).resolve() != _ember_4108d33796031947_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/model/model.py')
else:
    _ember_4108d33796031947_spec = _ember_4108d33796031947_importlib.spec_from_file_location('_ember_issue2015_4108d33796031947', _ember_4108d33796031947_path)
    if _ember_4108d33796031947_spec is None or _ember_4108d33796031947_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/model/model.py')
    _ember_4108d33796031947_module = _ember_4108d33796031947_importlib.module_from_spec(_ember_4108d33796031947_spec)
    for _ember_4108d33796031947_alias in _ember_4108d33796031947_aliases:
        _ember_4108d33796031947_prior = _ember_4108d33796031947_sys.modules.get(_ember_4108d33796031947_alias)
        if _ember_4108d33796031947_prior is not None and _ember_4108d33796031947_prior is not _ember_4108d33796031947_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/model/model.py')
        _ember_4108d33796031947_sys.modules[_ember_4108d33796031947_alias] = _ember_4108d33796031947_module
    try:
        _ember_4108d33796031947_spec.loader.exec_module(_ember_4108d33796031947_module)
    except BaseException:
        for _ember_4108d33796031947_alias in _ember_4108d33796031947_aliases:
            if _ember_4108d33796031947_sys.modules.get(_ember_4108d33796031947_alias) is _ember_4108d33796031947_module:
                _ember_4108d33796031947_sys.modules.pop(_ember_4108d33796031947_alias, None)
        raise
for _ember_4108d33796031947_alias in _ember_4108d33796031947_aliases:
    _ember_4108d33796031947_prior = _ember_4108d33796031947_sys.modules.get(_ember_4108d33796031947_alias)
    if _ember_4108d33796031947_prior is not None and _ember_4108d33796031947_prior is not _ember_4108d33796031947_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/model/model.py')
    _ember_4108d33796031947_sys.modules[_ember_4108d33796031947_alias] = _ember_4108d33796031947_module
RestartDecoderConfig = getattr(_ember_4108d33796031947_module, 'RestartDecoderConfig')
UnifiedDecoder = getattr(_ember_4108d33796031947_module, 'UnifiedDecoder')
# issue2015 exact-local-import-end:src/ember/model/model.py
_SERVE_MODULE_DIRECTORY = Path(__file__).resolve().parent
if str(_SERVE_MODULE_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(_SERVE_MODULE_DIRECTORY))
from repository_layout import resolve_repository_authority  # noqa: E402

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "scripts"))
# issue2015 exact-local-import:src/ember/infrastructure/tools/ember-restart-3b/tokenizer/reconstruct_frozen_tokenizer.py
import importlib.util as _ember_eeb5f5eab9d46a80_importlib
import sys as _ember_eeb5f5eab9d46a80_sys
from pathlib import Path as _ember_eeb5f5eab9d46a80_Path
_ember_eeb5f5eab9d46a80_path = _ember_eeb5f5eab9d46a80_Path(__file__).resolve().parent.joinpath('tokenizer', 'reconstruct_frozen_tokenizer.py')
if not _ember_eeb5f5eab9d46a80_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/infrastructure/tools/ember-restart-3b/tokenizer/reconstruct_frozen_tokenizer.py')
_ember_eeb5f5eab9d46a80_aliases = ('_ember_issue2015_eeb5f5eab9d46a80', 'reconstruct_frozen_tokenizer', 'tokenizer.reconstruct_frozen_tokenizer', 'src.ember.infrastructure.tools.ember-restart-3b.tokenizer.reconstruct_frozen_tokenizer')
_ember_eeb5f5eab9d46a80_existing = []
for _ember_eeb5f5eab9d46a80_alias in _ember_eeb5f5eab9d46a80_aliases:
    _ember_eeb5f5eab9d46a80_candidate = _ember_eeb5f5eab9d46a80_sys.modules.get(_ember_eeb5f5eab9d46a80_alias)
    if _ember_eeb5f5eab9d46a80_candidate is not None and all(_ember_eeb5f5eab9d46a80_candidate is not item for item in _ember_eeb5f5eab9d46a80_existing):
        _ember_eeb5f5eab9d46a80_existing.append(_ember_eeb5f5eab9d46a80_candidate)
if len(_ember_eeb5f5eab9d46a80_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/tokenizer/reconstruct_frozen_tokenizer.py')
if _ember_eeb5f5eab9d46a80_existing:
    _ember_eeb5f5eab9d46a80_module = _ember_eeb5f5eab9d46a80_existing[0]
    _ember_eeb5f5eab9d46a80_observed = getattr(_ember_eeb5f5eab9d46a80_module, '__file__', None)
    if _ember_eeb5f5eab9d46a80_observed is None or _ember_eeb5f5eab9d46a80_Path(_ember_eeb5f5eab9d46a80_observed).resolve() != _ember_eeb5f5eab9d46a80_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/infrastructure/tools/ember-restart-3b/tokenizer/reconstruct_frozen_tokenizer.py')
else:
    _ember_eeb5f5eab9d46a80_spec = _ember_eeb5f5eab9d46a80_importlib.spec_from_file_location('_ember_issue2015_eeb5f5eab9d46a80', _ember_eeb5f5eab9d46a80_path)
    if _ember_eeb5f5eab9d46a80_spec is None or _ember_eeb5f5eab9d46a80_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/infrastructure/tools/ember-restart-3b/tokenizer/reconstruct_frozen_tokenizer.py')
    _ember_eeb5f5eab9d46a80_module = _ember_eeb5f5eab9d46a80_importlib.module_from_spec(_ember_eeb5f5eab9d46a80_spec)
    for _ember_eeb5f5eab9d46a80_alias in _ember_eeb5f5eab9d46a80_aliases:
        _ember_eeb5f5eab9d46a80_prior = _ember_eeb5f5eab9d46a80_sys.modules.get(_ember_eeb5f5eab9d46a80_alias)
        if _ember_eeb5f5eab9d46a80_prior is not None and _ember_eeb5f5eab9d46a80_prior is not _ember_eeb5f5eab9d46a80_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/tokenizer/reconstruct_frozen_tokenizer.py')
        _ember_eeb5f5eab9d46a80_sys.modules[_ember_eeb5f5eab9d46a80_alias] = _ember_eeb5f5eab9d46a80_module
    try:
        _ember_eeb5f5eab9d46a80_spec.loader.exec_module(_ember_eeb5f5eab9d46a80_module)
    except BaseException:
        for _ember_eeb5f5eab9d46a80_alias in _ember_eeb5f5eab9d46a80_aliases:
            if _ember_eeb5f5eab9d46a80_sys.modules.get(_ember_eeb5f5eab9d46a80_alias) is _ember_eeb5f5eab9d46a80_module:
                _ember_eeb5f5eab9d46a80_sys.modules.pop(_ember_eeb5f5eab9d46a80_alias, None)
        raise
for _ember_eeb5f5eab9d46a80_alias in _ember_eeb5f5eab9d46a80_aliases:
    _ember_eeb5f5eab9d46a80_prior = _ember_eeb5f5eab9d46a80_sys.modules.get(_ember_eeb5f5eab9d46a80_alias)
    if _ember_eeb5f5eab9d46a80_prior is not None and _ember_eeb5f5eab9d46a80_prior is not _ember_eeb5f5eab9d46a80_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/tokenizer/reconstruct_frozen_tokenizer.py')
    _ember_eeb5f5eab9d46a80_sys.modules[_ember_eeb5f5eab9d46a80_alias] = _ember_eeb5f5eab9d46a80_module
ensure_serving_tokenizer = getattr(_ember_eeb5f5eab9d46a80_module, 'ensure_serving_tokenizer')
# issue2015 exact-local-import-end:src/ember/infrastructure/tools/ember-restart-3b/tokenizer/reconstruct_frozen_tokenizer.py

from ember_restart_eval_raw_forward import (  # noqa: E402
    canonicalize_tied_embedding_state,
    construct_runtime_model,
    hash_and_load_torch,
    materialize_state_map,
    rebind_tied_embeddings,
    tied_embeddings_from_contract,
    validate_state_map,
)

_TRACKED_TOKENIZER_SOURCE = resolve_repository_authority(ROOT, "tokenizer").path
_CHEAP_PROBE_SUITE_SCHEMA = "ember02-r1-r2-cheap-probe-suite/v1"
_CHEAP_PROBE_SUITE_SHA256 = "b08073b505581bd4cc634f9ca5c3a872755de867db26dd83fe27406f858288a3"
_TOKENIZER_FREEZE_RECEIPT = (
    ROOT / "receipts" / "tokenizer-freeze-20260611T154111Z.json"
)
_TOKENIZER_FREEZE_RECEIPT_SHA256 = (
    "2e96e70fe7463b272c00ea49e61e001402319a398a447debb9afe283586ac1c4"
)
_SERVING_TOKENIZER = ROOT / "models" / "cbase-serving" / "tokenizer.json"
RuntimeMode = Literal["INTERACTIVE", "FROZEN_EVAL"]
_MAX_REQUEST_TOKENS = 8096
_MAX_RUNTIME_GENERATION_TOKENS = 1024


@dataclass(frozen=True)
class OwnedIdentity:
    checkpoint_sha256: str
    model_config_sha256: str
    tokenizer_sha256: str
    server_source_sha256: str
    vram_bytes: int = 0
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
            "vram_bytes": self.vram_bytes,
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
    vram_bytes: int = 0
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
            "vram_bytes": self.vram_bytes,
        }


def resident_vram_bytes(device: torch.device | str) -> int:
    """Return allocator-owned VRAM from the loaded runtime itself."""
    resolved = torch.device(device)
    if resolved.type != "cuda":
        return 0
    measured = torch.cuda.memory_allocated(resolved)
    if isinstance(measured, bool) or not isinstance(measured, int) or measured <= 0:
        raise RuntimeError("loaded CUDA runtime did not report positive allocator VRAM")
    return measured

class OwnedChatRuntime(Protocol):
    identity: OwnedIdentity | DevelopmentIdentity

    def chat(
        self,
        messages: list[dict[str, object]],
        *,
        frozen_row_id: str | None,
        max_tokens: int,
        context_limit_tokens: int | None = None,
    ) -> tuple[str, str]: ...


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


def _contains_target_leak_on_prompt_surface(request: Mapping[str, object]) -> bool:
    """Inspect only content-bearing prompt fields, never tool/control schemas."""

    return any(
        _contains_target_leak(request[field])
        for field in ("messages", "prompt", "ember_frozen_row")
        if field in request
    )

def _read_bound_json_snapshot(path: Path, *, expected_sha256: str, label: str) -> tuple[dict[str, object], str, bytes]:
    snapshot = path.read_bytes()
    actual = hashlib.sha256(snapshot).hexdigest()
    if actual != expected_sha256:
        raise ValueError(f"{label} sha256 does not match its authority")
    try:
        payload = json.loads(snapshot)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be an object")
    return payload, actual, snapshot


def _same_root_snapshot(path: Path, payload: bytes) -> Path:
    """Publish one private immutable authority copy beside its relative artifacts."""

    snapshot = path.parent / f".{path.name}.{uuid.uuid4().hex}.snapshot"
    with snapshot.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return snapshot

def _config_snapshot_path(config_bytes: bytes) -> Path:
    handle = tempfile.NamedTemporaryFile("wb", suffix=".json", delete=False)
    try:
        handle.write(config_bytes)
        handle.flush()
        os.fsync(handle.fileno())
        return Path(handle.name)
    finally:
        handle.close()

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


def _frozen_prompt_authority(
    authority_path: Path,
    row_id: str,
    tokenizer: FrozenTokenizer,
    *,
    expected_suite_sha256: str = _CHEAP_PROBE_SUITE_SHA256,
) -> tuple[str, dict[str, Any]]:
    """Load a legacy split or the hash-bound canonical #1498 text suite."""

    try:
        raw = authority_path.read_bytes()
        payload = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("frozen prompt authority is unreadable or malformed") from exc
    if not isinstance(payload, dict) or payload.get("schema") != _CHEAP_PROBE_SUITE_SCHEMA:
        return frozen_split_prompt(authority_path, row_id, tokenizer)
    if hashlib.sha256(raw).hexdigest() != expected_suite_sha256:
        raise ValueError("canonical #1498 suite hash does not match frozen authority")
    tasks = payload.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("canonical #1498 suite tasks must be an array")
    selected = [task for task in tasks if isinstance(task, dict) and task.get("row_id") == row_id]
    if len(selected) != 1 or not isinstance(selected[0].get("prompt"), str):
        raise ValueError("canonical #1498 suite must contain exactly one requested row")
    prompt = selected[0]["prompt"]
    target_free = {"id": row_id, "prompt": prompt, "active_expert": "shared"}
    return row_id, {
        "schema_version": "ember-owned-inference-prompt-v1",
        **target_free,
        "token_ids": tokenizer.encode(prompt),
        "frozen_row_sha256": hashlib.sha256(
            json.dumps(target_free, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }


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


def _emit_parent_watchdog_receipt(receipt: dict[str, object]) -> None:
    payload = (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    os.write(2, payload)


def _emit_pre_load_validation_receipt(receipt: dict[str, object]) -> None:
    """Write one structured pre-load identity-validation receipt to stderr.

    cond3 inc2b: emitted the instant checkpoint identity is VALIDATED --
    the moment the loaded checkpoint-manifest.json bytes have been hashed
    and the central owned-seat resolver has bound that hash to an admitted
    claim -- never merely claimed. This is audit-trail evidence distinct
    from any resolver/admission receipt: it exists even when the resolver
    output is itself trusted, so the exact instant of validation (not just
    its outcome) is receipted before any state_dict load touches the model.
    """
    payload = (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    os.write(2, payload)


class _CallableParentProbe:
    def __init__(self, parent_pid: int, checker: Callable[[int], bool]) -> None:
        self.parent_pid = parent_pid
        self.checker = checker

    def alive(self) -> bool:
        return self.checker(self.parent_pid)

    def close(self) -> None:
        return None


class _WindowsParentProbe:
    """Hold one process handle so PID reuse cannot retether an orphaned server."""

    def __init__(self, parent_pid: int) -> None:
        import ctypes

        if parent_pid <= 0:
            raise RuntimeError("owned server parent process is not alive")
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        open_process = kernel32.OpenProcess
        open_process.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        open_process.restype = ctypes.c_void_p
        self._get_exit_code = kernel32.GetExitCodeProcess
        self._get_exit_code.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        self._get_exit_code.restype = ctypes.c_int
        self._close_handle = kernel32.CloseHandle
        self._close_handle.argtypes = [ctypes.c_void_p]
        self._close_handle.restype = ctypes.c_int
        self._ctypes = ctypes
        self._handle = open_process(0x1000, False, parent_pid)
        if not self._handle:
            raise RuntimeError("owned server parent process is not alive")

    def alive(self) -> bool:
        if not self._handle:
            return False
        exit_code = self._ctypes.c_ulong()
        return bool(self._get_exit_code(self._handle, self._ctypes.byref(exit_code))) and exit_code.value == 259

    def close(self) -> None:
        if self._handle:
            self._close_handle(self._handle)
            self._handle = None


def bind_parent_process(parent_pid: int) -> _WindowsParentProbe | _CallableParentProbe:
    if os.name == "nt":
        return _WindowsParentProbe(parent_pid)
    require_live_parent(parent_pid)
    return _CallableParentProbe(parent_pid, parent_process_alive)


def start_parent_watchdog(
    parent_pid: int,
    *,
    poll_seconds: float = 10.0,
    misses_before_exit: int = 2,
    checker: Callable[[int], bool] | None = None,
    exit_process: Callable[[int], None] = os._exit,
    emit_receipt: Callable[[dict[str, object]], None] = _emit_parent_watchdog_receipt,
) -> threading.Thread:
    if misses_before_exit < 1:
        raise ValueError("parent watchdog miss threshold must be positive")
    probe = bind_parent_process(parent_pid) if checker is None else _CallableParentProbe(parent_pid, checker)
    try:
        if not probe.alive():
            raise RuntimeError("owned server parent process is not alive")
    except BaseException:
        probe.close()
        raise

    def watch() -> None:
        consecutive_misses = 0
        try:
            while True:
                time.sleep(poll_seconds)
                try:
                    alive = probe.alive()
                except Exception:
                    alive = False
                if alive:
                    consecutive_misses = 0
                    continue
                consecutive_misses += 1
                if consecutive_misses < misses_before_exit:
                    continue
                receipt = {
                    "schema_version": "ember-owned-parent-watchdog-v1",
                    "event": "PARENT_GONE_EXIT",
                    "result": "MEASURED",
                    "parent_pid": parent_pid,
                    "consecutive_missed_polls": consecutive_misses,
                    "poll_seconds": poll_seconds,
                }
                try:
                    emit_receipt(receipt)
                except Exception:
                    pass
                finally:
                    exit_process(0)
                return
        finally:
            probe.close()

    thread = threading.Thread(target=watch, name="ember-owned-parent-watchdog", daemon=True)
    thread.start()
    return thread


def resolve_central_owned_admission(
    *,
    run_manifest: Path,
    trusted_verifier_registry: Path,
    trusted_verifier_registry_approval: Path,
    checkpoint_sha256: str,
    snapshot_manifest: Path | None = None,
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
) -> dict[str, object]:
    """Execute the central seat resolver and bind its decision to the loaded checkpoint."""

    command = [
        sys.executable,
        "-I",
        str(ROOT / "src" / "ember" / "governance" / "scripts" / "ember_restart" / "cli_seat.py"),
        str(snapshot_manifest if snapshot_manifest is not None else run_manifest),
        "--trusted-verifier-registry",
        str(trusted_verifier_registry),
        "--trusted-verifier-registry-approval",
        str(trusted_verifier_registry_approval),
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

def resolve_development_identity(
    development_manifest: Path,
    *,
    expected_manifest_sha256: str,
    expected_runtime_index_sha256: str,
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
) -> dict[str, object]:
    command = [
        sys.executable,
        "-I",
        str(ROOT / "src" / "ember" / "governance" / "scripts" / "ember_restart" / "development_cli_seat.py"),
        str(development_manifest),
        "--expected-manifest-sha256",
        expected_manifest_sha256,
        "--expected-runtime-index-sha256",
        expected_runtime_index_sha256,
    ]
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
            if mode == "FROZEN_EVAL" and _contains_target_leak_on_prompt_surface(request):
                self._write(400, _error("request contains target leakage"))
                return
            frozen_row_id = request.get("ember_frozen_row_id")
            if mode == "FROZEN_EVAL" and (not isinstance(frozen_row_id, str) or not frozen_row_id):
                self._write(400, _error("request requires a nonempty frozen row identifier"))
                return
            if mode == "INTERACTIVE":
                frozen_row_id = None
            context_limit_tokens = request.get("ember_context_limit_tokens")
            if mode == "FROZEN_EVAL" and (
                isinstance(context_limit_tokens, bool)
                or not isinstance(context_limit_tokens, int)
                or context_limit_tokens < 1
            ):
                self._write(400, _error("request requires a positive integer context limit"))
                return
            if mode == "INTERACTIVE":
                context_limit_tokens = None
            messages = request.get("messages")
            if not isinstance(messages, list) or not messages or any(not isinstance(message, dict) for message in messages):
                self._write(400, _error("messages must be a nonempty array of objects"))
                return
            max_tokens = request.get("max_tokens", 64)
            if not isinstance(max_tokens, int) or not 0 < max_tokens <= _MAX_REQUEST_TOKENS:
                self._write(400, _error(f"max_tokens must be an integer in [1, {_MAX_REQUEST_TOKENS}]"))
                return
            effective_max_tokens = min(max_tokens, _MAX_RUNTIME_GENERATION_TOKENS)
            try:
                text, finish_reason = runtime.chat(
                    messages,
                    frozen_row_id=frozen_row_id,
                    max_tokens=effective_max_tokens,
                    context_limit_tokens=context_limit_tokens,
                )
            except ValueError as exc:
                self._write(400, _error(str(exc)))
                return
            completion = {
                "id": "chatcmpl-owned-" + runtime.identity.checkpoint_sha256[:12],
                "object": "chat.completion",
                "created": int(time.time()), "model": runtime.identity.model_name,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": finish_reason}],
                "owned_identity": runtime.identity.payload(),
            }
            if request.get("stream") is True:
                chunk = {
                    "id": completion["id"], "object": "chat.completion.chunk", "created": completion["created"],
                    "model": runtime.identity.model_name,
                    "choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": finish_reason}],
                    "owned_identity": runtime.identity.payload(),
                }
                self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.send_header("Cache-Control", "no-cache"); self.end_headers()
                self.wfile.write(("data: " + json.dumps(chunk, sort_keys=True, separators=(",", ":")) + "\n\ndata: [DONE]\n\n").encode("utf-8")); self.wfile.flush()
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
        config_path: Path,
        run_manifest: Path,
        frozen_split: Path | None,
        trusted_verifier_registry: Path,
        expected_registry_root_sha256: str,
        trusted_verifier_registry_approval: Path,
        expected_registry_approval_sha256: str,
        device: str,
        emit_validation_receipt: Callable[[dict[str, object]], None] = _emit_pre_load_validation_receipt,
    ) -> "LoadedOwnedRuntime":
        """Load the serving runtime's identity-bound checkpoint (cond3 inc2b).

        Identity-binding contract: the served checkpoint's identity claim
        (its checkpoint_sha256) is DERIVED from `checkpoint-manifest.json`
        bytes on disk and VALIDATED -- against the central owned-seat
        resolver's admitted claim, and against the central run manifest's
        pinned model-config/tokenizer hashes -- before any model bytes are
        loaded via `load_checkpoint_artifacts`. `checkpoint-manifest.json`
        is immutable at this point: it is read once, hashed, and every
        downstream binding (admission, receipt, load) is checked against
        that one read. If validation fails for any reason -- manifest
        missing, manifest JSON corrupt, admission checkpoint hash mismatch,
        model config or tokenizer hash mismatch -- this method raises and
        the server refuses to load or serve; it never falls back to a
        guessed or partially-validated identity. On success, a structured
        pre-load validation receipt is emitted (see
        `_emit_pre_load_validation_receipt`) recording the exact moment
        identity was validated, distinct from the resolver's own admission
        receipt.

        Registry trust-anchor (cond3 harden): the caller-supplied
        `trusted_verifier_registry` file is hashed and checked against
        `expected_registry_root_sha256` BEFORE it is trusted at all -- the
        registry's own inner sha256 pins (see contract.py
        `_load_trusted_verifiers`) only bind entries against hashes
        declared inside the same file, which a forged, self-consistent
        registry would trivially satisfy. Without this outer pin, the
        registry file itself is the un-anchored trust root.
        """
        manifest_path = checkpoint / "checkpoint-manifest.json"
        manifest_bytes = manifest_path.read_bytes()
        checkpoint_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        try:
            manifest = json.loads(manifest_bytes)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"checkpoint manifest is not valid JSON: {manifest_path}") from exc
        if not isinstance(manifest, dict):
            raise ValueError(f"checkpoint manifest must be a JSON object: {manifest_path}")
        run_manifest_bytes = run_manifest.read_bytes()
        run_manifest_sha256 = hashlib.sha256(run_manifest_bytes).hexdigest()
        # Registry trust-anchor pin (cond3 harden): _load_trusted_verifiers
        # (scripts/ember_restart/contract.py) pins the registry's INNER
        # entries only against sha256 values declared inside that same
        # registry file -- a self-consistent, attacker-authored registry
        # would otherwise be trusted as-supplied. Hash the registry FILE
        # itself and fail closed unless it matches the caller's pinned
        # expected root hash, before the registry is ever handed to the
        # central resolver subprocess.
        approval_bytes = trusted_verifier_registry_approval.read_bytes()
        approval_sha256 = hashlib.sha256(approval_bytes).hexdigest()
        if approval_sha256 != expected_registry_approval_sha256:
            raise ValueError(
                "trusted verifier registry approval hash does not match the pinned "
                "expected-registry-approval-sha256"
            )
        try:
            approval = json.loads(approval_bytes)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("trusted verifier registry approval is not valid JSON") from exc
        if not isinstance(approval, dict) or set(approval) != {
            "schema_version",
            "trusted_verifier_registry_sha256",
        }:
            raise ValueError("trusted verifier registry approval has invalid schema")
        if approval.get("schema_version") != "ember-trusted-verifier-registry-approval-v1":
            raise ValueError("trusted verifier registry approval has invalid schema")
        if approval.get("trusted_verifier_registry_sha256") != expected_registry_root_sha256:
            raise ValueError(
                "trusted verifier registry approval does not authorize the pinned registry root"
            )
        registry_bytes = trusted_verifier_registry.read_bytes()
        registry_root_sha256 = hashlib.sha256(registry_bytes).hexdigest()
        if registry_root_sha256 != expected_registry_root_sha256:
            raise ValueError(
                "trusted verifier registry root hash does not match the pinned "
                "expected-registry-root-sha256 -- refusing to trust an "
                "unpinned or substituted registry file"
            )
        resolver_snapshot = _same_root_snapshot(run_manifest, run_manifest_bytes)
        registry_snapshot: Path | None = None
        approval_snapshot: Path | None = None
        try:
            registry_snapshot = _same_root_snapshot(trusted_verifier_registry, registry_bytes)
            approval_snapshot = _same_root_snapshot(
                trusted_verifier_registry_approval,
                approval_bytes,
            )
            admission = resolve_central_owned_admission(
                run_manifest=run_manifest,
                snapshot_manifest=resolver_snapshot,
                trusted_verifier_registry=registry_snapshot,
                trusted_verifier_registry_approval=approval_snapshot,
                checkpoint_sha256=checkpoint_sha256,
            )
        finally:
            if approval_snapshot is not None:
                approval_snapshot.unlink(missing_ok=True)
            if registry_snapshot is not None:
                registry_snapshot.unlink(missing_ok=True)
            resolver_snapshot.unlink(missing_ok=True)
        if sha(run_manifest) != run_manifest_sha256:
            raise ValueError("central run manifest changed during owned-seat resolution")
        emit_validation_receipt({
            "schema_version": "ember-owned-pre-load-validation-receipt-v1",
            "ts": time.time(),
            "manifest_path": str(manifest_path),
            "manifest_sha256": checkpoint_sha256,
            "claimed_checkpoint_sha256": str(admission["checkpoint_sha256"]),
            "actual_checkpoint_sha256": checkpoint_sha256,
            "trusted_verifier_registry_sha256": registry_root_sha256,
            "trusted_verifier_registry_approval_sha256": approval_sha256,
            "validation_status": "PASS",
        })
        try:
            central_manifest = json.loads(run_manifest_bytes)
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
        config_bytes = config_path.read_bytes()
        model_config_sha256 = hashlib.sha256(config_bytes).hexdigest()
        if model_config_sha256 != expected_config_sha256:
            raise ValueError("central model config hash does not match loaded configuration")
        tokenizer_bytes = tokenizer_path.read_bytes()
        tokenizer = load_frozen_tokenizer(tokenizer_path, expected_sha256=expected_tokenizer_sha256, snapshot_bytes=tokenizer_bytes)
        config_snapshot = _config_snapshot_path(config_bytes)
        try:
            config = RestartDecoderConfig.from_contract(config_snapshot)
        finally:
            config_snapshot.unlink(missing_ok=True)
        model = UnifiedDecoder(config, device=device, allow_production_allocation=True).eval()
        # issue2015 exact-local-import:src/ember/infrastructure/tools/ember-restart-3b/checkpoint_artifacts.py
        import importlib.util as _ember_f5951795c08a31e2_importlib
        import sys as _ember_f5951795c08a31e2_sys
        from pathlib import Path as _ember_f5951795c08a31e2_Path
        _ember_f5951795c08a31e2_path = _ember_f5951795c08a31e2_Path(__file__).resolve().parent.joinpath('checkpoint_artifacts.py')
        if not _ember_f5951795c08a31e2_path.is_file():
            raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/infrastructure/tools/ember-restart-3b/checkpoint_artifacts.py')
        _ember_f5951795c08a31e2_aliases = ('_ember_issue2015_f5951795c08a31e2', 'checkpoint_artifacts', 'src.ember.infrastructure.tools.ember-restart-3b.checkpoint_artifacts')
        _ember_f5951795c08a31e2_existing = []
        for _ember_f5951795c08a31e2_alias in _ember_f5951795c08a31e2_aliases:
            _ember_f5951795c08a31e2_candidate = _ember_f5951795c08a31e2_sys.modules.get(_ember_f5951795c08a31e2_alias)
            if _ember_f5951795c08a31e2_candidate is not None and all(_ember_f5951795c08a31e2_candidate is not item for item in _ember_f5951795c08a31e2_existing):
                _ember_f5951795c08a31e2_existing.append(_ember_f5951795c08a31e2_candidate)
        if len(_ember_f5951795c08a31e2_existing) > 1:
            raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/checkpoint_artifacts.py')
        if _ember_f5951795c08a31e2_existing:
            _ember_f5951795c08a31e2_module = _ember_f5951795c08a31e2_existing[0]
            _ember_f5951795c08a31e2_observed = getattr(_ember_f5951795c08a31e2_module, '__file__', None)
            if _ember_f5951795c08a31e2_observed is None or _ember_f5951795c08a31e2_Path(_ember_f5951795c08a31e2_observed).resolve() != _ember_f5951795c08a31e2_path:
                raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/infrastructure/tools/ember-restart-3b/checkpoint_artifacts.py')
        else:
            _ember_f5951795c08a31e2_spec = _ember_f5951795c08a31e2_importlib.spec_from_file_location('_ember_issue2015_f5951795c08a31e2', _ember_f5951795c08a31e2_path)
            if _ember_f5951795c08a31e2_spec is None or _ember_f5951795c08a31e2_spec.loader is None:
                raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/infrastructure/tools/ember-restart-3b/checkpoint_artifacts.py')
            _ember_f5951795c08a31e2_module = _ember_f5951795c08a31e2_importlib.module_from_spec(_ember_f5951795c08a31e2_spec)
            for _ember_f5951795c08a31e2_alias in _ember_f5951795c08a31e2_aliases:
                _ember_f5951795c08a31e2_prior = _ember_f5951795c08a31e2_sys.modules.get(_ember_f5951795c08a31e2_alias)
                if _ember_f5951795c08a31e2_prior is not None and _ember_f5951795c08a31e2_prior is not _ember_f5951795c08a31e2_module:
                    raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/checkpoint_artifacts.py')
                _ember_f5951795c08a31e2_sys.modules[_ember_f5951795c08a31e2_alias] = _ember_f5951795c08a31e2_module
            try:
                _ember_f5951795c08a31e2_spec.loader.exec_module(_ember_f5951795c08a31e2_module)
            except BaseException:
                for _ember_f5951795c08a31e2_alias in _ember_f5951795c08a31e2_aliases:
                    if _ember_f5951795c08a31e2_sys.modules.get(_ember_f5951795c08a31e2_alias) is _ember_f5951795c08a31e2_module:
                        _ember_f5951795c08a31e2_sys.modules.pop(_ember_f5951795c08a31e2_alias, None)
                raise
        for _ember_f5951795c08a31e2_alias in _ember_f5951795c08a31e2_aliases:
            _ember_f5951795c08a31e2_prior = _ember_f5951795c08a31e2_sys.modules.get(_ember_f5951795c08a31e2_alias)
            if _ember_f5951795c08a31e2_prior is not None and _ember_f5951795c08a31e2_prior is not _ember_f5951795c08a31e2_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/checkpoint_artifacts.py')
            _ember_f5951795c08a31e2_sys.modules[_ember_f5951795c08a31e2_alias] = _ember_f5951795c08a31e2_module
        load_checkpoint_artifacts = getattr(_ember_f5951795c08a31e2_module, 'load_checkpoint_artifacts')
        published_checkpoint_receipt = getattr(_ember_f5951795c08a31e2_module, 'published_checkpoint_receipt')
        # issue2015 exact-local-import-end:src/ember/infrastructure/tools/ember-restart-3b/checkpoint_artifacts.py
        checkpoint_receipt = published_checkpoint_receipt(checkpoint)
        if checkpoint_receipt["checkpoint_manifest_sha256"] != checkpoint_sha256:
            raise ValueError("checkpoint manifest changed during owned runtime construction")
        load_checkpoint_artifacts(
            model,
            None,
            checkpoint,
            checkpoint_receipt,
        )
        # Post-load identity assert (cond3 inc2b): the architecture ties
        # lm_head.weight to token_embedding.weight at construction time
        # (see UnifiedDecoder.__init__). A silent partial/misrouted load
        # (e.g. a strict=False state_dict load that skips a tied parameter)
        # would desynchronize this invariant without raising on its own --
        # catch that here, fail closed, and never serve a checkpoint whose
        # loaded weights diverge from the architecture's own identity.
        if not torch.equal(model.lm_head.weight.detach(), model.token_embedding.weight.detach()):
            raise RuntimeError(
                "post-load value-equality assertion failed: lm_head weight values "
                "do not match token embedding weight values (checked by value, not "
                "storage identity -- a broken tie desynchronizes even the values)"
            )
        identity = OwnedIdentity(
            checkpoint_sha256=checkpoint_sha256,
            model_config_sha256=model_config_sha256,
            tokenizer_sha256=tokenizer.sha256,
            server_source_sha256=sha(Path(__file__)),
            vram_bytes=resident_vram_bytes(device),
            seat=str(admission["seat"]),
        )
        if admission["model_name"] != identity.model_name:
            raise ValueError("central admission model name does not match loaded checkpoint")
        return cls(model=model, tokenizer=tokenizer, identity=identity, device=torch.device(device), frozen_split=frozen_split)

    def chat(
        self,
        messages: list[dict[str, object]],
        *,
        frozen_row_id: str | None,
        max_tokens: int,
        context_limit_tokens: int | None = None,
    ) -> tuple[str, str]:
        if self.frozen_split is None:
            prompt = "\n".join(f"{message.get('role', 'user')}: {message.get('content', '')}" for message in messages)
            prompt_ids = self.tokenizer.encode(prompt)
        else:
            if frozen_row_id is None:
                raise ValueError("frozen evaluation requires a frozen row identifier")
            _, record = _frozen_prompt_authority(
                self.frozen_split, frozen_row_id, self.tokenizer
            )
            if messages != [{"role": "user", "content": record["prompt"]}]:
                raise ValueError("chat does not match frozen split prompt")
            prompt_ids = record["token_ids"]
            if context_limit_tokens is None:
                raise ValueError("frozen evaluation requires a context limit")
            if len(prompt_ids) + max_tokens > context_limit_tokens:
                raise ValueError("frozen evaluation prompt plus output exceeds context limit")
        with torch.inference_mode():
            generated, reason = greedy_generate(
                model=self.model,
                prompt_ids=torch.tensor([prompt_ids], dtype=torch.long, device=self.device),
                model_kwargs={"active_expert": "shared"},
                max_new_tokens=max_tokens,
                stop_token_ids=self.tokenizer.eos_token_ids,
            )
        return self.tokenizer.decode(generated), "stop" if reason == "eos" else "length"


def load_development_shared_runtime(
    *,
    checkpoint: Path,
    config_path: Path,
    checkpoint_manifest: Mapping[str, object],
    device: str,
    config_bytes: bytes | None = None,
) -> UnifiedDecoder:
    """Load the development seat shared route through the #848 BF16/meta loader."""

    try:
        contract = json.loads(config_bytes if config_bytes is not None else config_path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"development model contract is invalid: {exc}") from exc
    if not isinstance(contract, dict):
        raise ValueError("development model contract must be an object")
    snapshot_path = _config_snapshot_path(config_bytes) if config_bytes is not None else config_path
    try:
        config = RestartDecoderConfig.from_contract(snapshot_path)
    finally:
        if config_bytes is not None:
            snapshot_path.unlink(missing_ok=True)
    model = construct_runtime_model(torch, model_module, config, contract)
    tied_embeddings = tied_embeddings_from_contract(config, contract)
    shards = checkpoint_manifest.get("shards")
    if not isinstance(shards, list):
        raise ValueError("development checkpoint lacks shard records")
    records: dict[str, Mapping[str, object]] = {}
    for record in shards:
        if not isinstance(record, Mapping) or not isinstance(record.get("path"), str):
            raise ValueError("development checkpoint shard record is invalid")
        path = str(record["path"])
        if path in records:
            raise ValueError("development checkpoint contains duplicate shard records")
        records[path] = record
    schema_version = checkpoint_manifest.get("schema_version")
    if schema_version == "ember-sparse-checkpoint-v5":
        static_paths = {
            "shared-model.pt",
            "replay-state.pt",
            *(f"expert-{name}.pt" for name in model_module.EXPERT_NAMES),
        }
        optimizer_state_layout = checkpoint_manifest.get("optimizer_state_layout")
        if optimizer_state_layout is None:
            expected_paths = static_paths | {"optimizer-state.pt"}
        elif optimizer_state_layout == "owner-sharded-v1":
            owner_ids = checkpoint_manifest.get("optimizer_state_owner_ids")
            allowed_owners = {"shared", *model_module.EXPERT_NAMES}
            if (
                not isinstance(owner_ids, list)
                or not owner_ids
                or any(type(owner) is not str for owner in owner_ids)
                or owner_ids[0] != "shared"
                or len(set(owner_ids)) != len(owner_ids)
                or any(owner not in allowed_owners for owner in owner_ids)
            ):
                raise ValueError("development checkpoint owner-sharded optimizer owners are invalid")
            expected_paths = static_paths | {
                f"optimizer-state-{owner}.pt" for owner in owner_ids
            }
        else:
            raise ValueError("development checkpoint has an unsupported optimizer layout")
        if set(records) != expected_paths:
            raise ValueError("development checkpoint closed v5 shard set is invalid")
        shared_path = "shared-model.pt"
    elif schema_version in {None, "ember-sparse-checkpoint-v3", "ember-sparse-checkpoint-v4"}:
        shared_path = "shared.pt"
    else:
        raise ValueError("development checkpoint has an unsupported schema version")
    shared_record = records.get(shared_path)
    shared_sha256 = shared_record.get("sha256") if isinstance(shared_record, Mapping) else None
    if not isinstance(shared_sha256, str):
        raise ValueError("development checkpoint lacks shared shard identity")
    payload = hash_and_load_torch(torch, checkpoint / shared_path, shared_sha256, device=device)
    if not isinstance(payload, dict) or not isinstance(payload.get("model"), dict):
        raise ValueError("development shared checkpoint lacks a model state")
    expected = model.state_dict()
    shared_expected = {key: value for key, value in expected.items() if ".experts." not in key}
    shared_state = payload["model"]
    validate_state_map(shared_state, shared_expected, "shared")
    canonical = canonicalize_tied_embedding_state(torch, shared_state, tied_embeddings=tied_embeddings)
    model.load_state_dict(materialize_state_map(canonical, device), strict=False, assign=True)
    rebind_tied_embeddings(model, tied_embeddings=tied_embeddings)
    model._activate_expert("shared")
    return model.eval()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, default=_SERVING_TOKENIZER)
    parser.add_argument("--config", type=Path, required=True)
    authority = parser.add_mutually_exclusive_group(required=True)
    authority.add_argument("--run-manifest", type=Path)
    authority.add_argument("--development-manifest", type=Path)
    parser.add_argument("--expected-development-manifest-sha256")
    parser.add_argument("--expected-runtime-index-sha256")
    parser.add_argument("--trusted-verifier-registry", type=Path)
    parser.add_argument("--expected-registry-root-sha256")
    parser.add_argument("--trusted-verifier-registry-approval", type=Path)
    parser.add_argument("--expected-registry-approval-sha256")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--mode", choices=("INTERACTIVE", "FROZEN_EVAL"), required=True)
    parser.add_argument("--parent-pid", type=int, required=True)
    parser.add_argument("--frozen-split", type=Path)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args(argv)
    frozen_split = resolve_runtime_inputs(args.mode, args.frozen_split)
    if args.development_manifest is not None and (args.expected_development_manifest_sha256 is None or args.expected_runtime_index_sha256 is None):
        raise ValueError("development server requires exact manifest and runtime-index hashes")
    start_parent_watchdog(args.parent_pid)
    args.tokenizer = ensure_serving_tokenizer(
        output=args.tokenizer,
        source=_TRACKED_TOKENIZER_SOURCE,
        freeze_receipt=_TOKENIZER_FREEZE_RECEIPT,
        receipt_output=args.tokenizer.parent / "tokenizer-reconstruction-receipt.json",
        expected_freeze_receipt_sha256=_TOKENIZER_FREEZE_RECEIPT_SHA256,
    )
    if args.development_manifest is not None:
        development = resolve_development_identity(
            args.development_manifest,
            expected_manifest_sha256=args.expected_development_manifest_sha256,
            expected_runtime_index_sha256=args.expected_runtime_index_sha256,
        )
        if development.get("server_source_sha256") != sha(Path(__file__)):
            raise ValueError("development authority does not match server source bytes")
        config_path = args.config
        checkpoint_manifest_path = args.checkpoint / "checkpoint-manifest.json"
        manifest, _checkpoint_sha256, _checkpoint_bytes = _read_bound_json_snapshot(
            checkpoint_manifest_path, expected_sha256=str(development["checkpoint_sha256"]), label="development checkpoint manifest"
        )
        _config, _config_sha256, config_bytes = _read_bound_json_snapshot(
            config_path, expected_sha256=str(development["model_config_sha256"]), label="development model config"
        )
        _tokenizer, _tokenizer_sha256, tokenizer_bytes = _read_bound_json_snapshot(
            args.tokenizer, expected_sha256=str(development["tokenizer_sha256"]), label="development tokenizer"
        )
        tokenizer = load_frozen_tokenizer(
            args.tokenizer, expected_sha256=str(development["tokenizer_sha256"]), snapshot_bytes=tokenizer_bytes
        )
        model = load_development_shared_runtime(
            checkpoint=args.checkpoint,
            config_path=config_path,
            checkpoint_manifest=manifest,
            device=args.device,
            config_bytes=config_bytes,
        )
        identity = DevelopmentIdentity(checkpoint_sha256=str(development["checkpoint_sha256"]), model_config_sha256=str(development["model_config_sha256"]), tokenizer_sha256=tokenizer.sha256, server_source_sha256=sha(Path(__file__)), tokens_seen=int(development["tokens_seen"]), allocated_parameters=int(development["allocated_parameters"]), active_parameters=int(development["active_parameters"]), vram_bytes=resident_vram_bytes(args.device))
        runtime = LoadedOwnedRuntime(model=model, tokenizer=tokenizer, identity=identity, device=torch.device(args.device), frozen_split=frozen_split)
    else:
        if args.trusted_verifier_registry is None:
            raise ValueError("admitted server requires trusted verifier registry")
        if not args.expected_registry_root_sha256:
            raise ValueError("admitted server requires --expected-registry-root-sha256 to pin the trusted verifier registry file")
        if args.trusted_verifier_registry_approval is None:
            raise ValueError("admitted server requires trusted verifier registry approval")
        if not args.expected_registry_approval_sha256:
            raise ValueError("admitted server requires --expected-registry-approval-sha256 to pin the approval file")
        runtime = LoadedOwnedRuntime.from_paths(checkpoint=args.checkpoint, tokenizer_path=args.tokenizer, config_path=args.config, run_manifest=args.run_manifest, trusted_verifier_registry=args.trusted_verifier_registry, expected_registry_root_sha256=args.expected_registry_root_sha256, trusted_verifier_registry_approval=args.trusted_verifier_registry_approval, expected_registry_approval_sha256=args.expected_registry_approval_sha256, device=args.device, frozen_split=frozen_split)
    server = create_loopback_server(runtime, host=args.host, port=args.port, mode=args.mode)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
