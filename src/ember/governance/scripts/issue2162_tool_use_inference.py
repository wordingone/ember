#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""#2162: produce the E-MATRIX-TOOL-USE inference receipt from real checkpoint inference.

The designated release-candidate checkpoint emits ONE SQL query per frozen prompt of the #2153
protected tool-use contract, in the contract's frozen item order, under a frozen decode contract.
Every emission is executed read-only against a private copy of the admitted database bytes,
canonicalized by the contract's result rule, and compared with the contract's `gold_result_sha256`.
The receipt binds checkpoint manifest, contract, decode contract, model source/config/tokenizer and
every per-item record, and is self-hashed.

Claim boundary: totality of emission + execution + receipt. PASS means 1,034 records were produced
in frozen order with a verifiable receipt; it is not a score bar. The execution-match rate is a
reported number; capability, threshold, release, campaign, EMBER-02 and goal credit are out of scope.

Subcommands:
  produce  real inference (CUDA) -> receipt            (the governed producer)
  verify   re-verify a receipt against the contract   (the adapter's checks, standalone)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import tempfile
import time
import types
from pathlib import Path
from typing import Any, Callable

RECEIPT_SCHEMA = "ember-tool-use-inference-receipt-v1"
CONTRACT_SCHEMA = "ember-issue1947-protected-tool-use-contract-v1"
DESIGNATION_SCHEMA = "ember-issue1947-release-candidate-checkpoint-designation-v1"
CONNECTOR_SCHEMA = "corpus-connector-receipt-v1"
ITEM_COUNT = 1034
ACTIVE_EXPERT = "tool"
SHARED_SHARD = "shared-model.pt"
EXPERT_SHARD = f"expert-{ACTIVE_EXPERT}.pt"
RESULT_PASS = "TOOL_USE_INFERENCE_PASS"

# The only degree of freedom between a checkpoint and its emissions. Literal, hashed, bound.
DECODE_CONTRACT: dict[str, Any] = {
    "strategy": "greedy_argmax",
    "temperature": 0,
    "sampling": False,
    "retries": 0,
    "batch": 1,
    "kv_cache": False,
    "max_new_tokens": 256,
    "eos_token_id": 0,
    "stop_rules": ["eos_token", "first_semicolon_in_decoded_text", "first_blank_line_in_decoded_text", "max_new_tokens"],
    "emission_extraction": "decoded text up to and including the first ';' if present, else up to the first blank line, else whole text; stripped",
    "prompt": "the contract's admitted prompt object bytes decoded as UTF-8, verbatim; no system prompt, no template, tokenizer default encoding",
    "active_expert": ACTIVE_EXPERT,
    "parameter_dtype": "bfloat16",
}
RESULT_CANONICALIZATION = (
    "rows fetched fully; each cell -> null | int | float | str | hex(bytes); text decoded utf-8 with "
    "U+FFFD replacement; row order preserved when the emitted query contains ORDER BY, else rows "
    "sorted by their canonical JSON; result sha256 = sha256(canonical JSON of the row list)"
)
DATABASE_ACCESS = "sqlite3 uri mode=ro&immutable=1 on a private copy of the admitted bytes; bytes rehashed after execution"
CLAIM_BOUNDARY = (
    "EMISSION + EXECUTION + RECEIPT TOTALITY ONLY; the execution-match rate is a reported number; "
    "NOT CAPABILITY, THRESHOLD, RELEASE, CAMPAIGN, EMBER-02, OR GOAL CREDIT"
)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def decode_contract_sha256() -> str:
    return sha(canonical(DECODE_CONTRACT))


def item_identifier(index: int) -> str:
    return f"spider-dev-{index:04d}"


def load_self_hashed(path: Path, schema_version: str, label: str) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label}_UNREADABLE_REFUSED") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != schema_version:
        raise ValueError(f"{label}_SCHEMA_REFUSED")
    body = dict(payload)
    claimed = body.pop("self_sha256", None)
    if claimed != sha(canonical(body)):
        raise ValueError(f"{label}_SELF_HASH_REFUSED")
    return payload, raw


# ---------------------------------------------------------------------------------------------
# Contract + admitted objects
# ---------------------------------------------------------------------------------------------

def load_contract(path: Path) -> tuple[dict[str, Any], bytes]:
    contract, raw = load_self_hashed(path, CONTRACT_SCHEMA, "TOOL_USE_CONTRACT")
    frozen = contract.get("frozen_items")
    if (
        contract.get("result") != "PASS"
        or contract.get("task_class") != "adapter_totality"
        or contract.get("totality") != {"expected": ITEM_COUNT, "observed": ITEM_COUNT, "complete": True}
        or not isinstance(frozen, list)
        or len(frozen) != ITEM_COUNT
    ):
        raise ValueError("TOOL_USE_CONTRACT_TOTALITY_REFUSED")
    for index, item in enumerate(frozen):
        if not isinstance(item, dict) or item.get("item_id") != item_identifier(index):
            raise ValueError(f"TOOL_USE_CONTRACT_ORDER_REFUSED:{index}")
        for key in ("prompt_object", "database_object"):
            obj = item.get(key)
            if not isinstance(obj, dict) or not isinstance(obj.get("sha256"), str) or not isinstance(obj.get("byte_count"), int):
                raise ValueError(f"TOOL_USE_CONTRACT_ITEM_SCHEMA_REFUSED:{item.get('item_id')}:{key}")
        for key in ("gold_result_sha256", "gold_item_sha256"):
            if not isinstance(item.get(key), str) or len(item[key]) != 64:
                raise ValueError(f"TOOL_USE_CONTRACT_ITEM_SCHEMA_REFUSED:{item.get('item_id')}:{key}")
    return contract, raw


def bound_receipt_shas(contract: dict[str, Any]) -> list[str]:
    source = contract.get("source")
    bound = source.get("connector_receipt_raw_sha256s") if isinstance(source, dict) else None
    if isinstance(bound, dict):
        values = list(bound.values())
    elif isinstance(bound, list):
        values = list(bound)
    else:
        values = []
    if not values or any(not isinstance(value, str) for value in values):
        raise ValueError("TOOL_USE_CONTRACT_SOURCE_BINDING_REFUSED")
    return sorted(values)


def load_sources(contract: dict[str, Any], receipt_paths: list[Path]) -> tuple[dict[str, tuple[Path, dict[str, Any]]], list[str]]:
    """Every supplied source must be a connector receipt the contract binds; the bound set must be
    supplied in full. Any other schema is a forbidden input, refused before a byte under it is read."""

    bound = bound_receipt_shas(contract)
    by_sha: dict[str, tuple[Path, dict[str, Any]]] = {}
    supplied: list[str] = []
    for receipt_path in receipt_paths:
        raw = receipt_path.read_bytes()
        try:
            receipt = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("TOOL_USE_SOURCE_RECEIPT_UNREADABLE_REFUSED") from error
        if not isinstance(receipt, dict) or receipt.get("schema") != CONNECTOR_SCHEMA:
            raise ValueError("TOOL_USE_FORBIDDEN_INPUT_REFUSED:source_schema")
        digest = sha(raw)
        if digest not in bound:
            raise ValueError("TOOL_USE_SOURCE_RECEIPT_BINDING_DRIFT_REFUSED")
        if digest in supplied:
            raise ValueError("TOOL_USE_SOURCE_RECEIPT_DUPLICATE_REFUSED")
        supplied.append(digest)
        root_value, files = receipt.get("dest_root"), receipt.get("files")
        if not isinstance(root_value, str) or not isinstance(files, list):
            raise ValueError("TOOL_USE_SOURCE_RECEIPT_TOTALITY_REFUSED")
        root = Path(root_value)
        if not root.is_absolute() or not root.is_dir():
            raise ValueError("TOOL_USE_CUSTODY_ROOT_MISSING_REFUSED")
        root = root.resolve()
        for row in files:
            if not isinstance(row, dict) or not isinstance(row.get("sha256"), str):
                raise ValueError("TOOL_USE_SOURCE_RECEIPT_FILE_SCHEMA_REFUSED")
            if row["sha256"] in by_sha:
                raise ValueError("TOOL_USE_SOURCE_RECEIPT_DUPLICATE_OBJECT_REFUSED")
            by_sha[row["sha256"]] = (root, row)
    if sorted(supplied) != bound:
        raise ValueError("TOOL_USE_SOURCE_RECEIPT_SET_INCOMPLETE_REFUSED")
    return by_sha, sorted(supplied)


def bound_payload(by_sha: dict[str, tuple[Path, dict[str, Any]]], obj: dict[str, Any], item_id: str) -> bytes:
    digest, byte_count = obj.get("sha256"), obj.get("byte_count")
    entry = by_sha.get(digest) if isinstance(digest, str) else None
    if entry is None:
        raise ValueError(f"TOOL_USE_PAYLOAD_MISSING_REFUSED:{item_id}:{digest}")
    root, row = entry
    if row.get("bytes") != byte_count or not isinstance(row.get("path"), str):
        raise ValueError(f"TOOL_USE_PAYLOAD_MISSING_REFUSED:{item_id}:{digest}")
    physical = (root / Path(row["path"])).resolve()
    try:
        physical.relative_to(root)
    except ValueError as error:
        raise ValueError(f"TOOL_USE_PAYLOAD_PATH_ESCAPE_REFUSED:{item_id}:{digest}") from error
    if not physical.is_file():
        raise ValueError(f"TOOL_USE_PAYLOAD_MISSING_REFUSED:{item_id}:{digest}")
    raw = physical.read_bytes()
    if sha(raw) != digest or len(raw) != byte_count:
        raise ValueError(f"TOOL_USE_PAYLOAD_DRIFT_REFUSED:{item_id}:{digest}")
    return raw


# ---------------------------------------------------------------------------------------------
# Emission extraction + read-only execution (mirrors #2153's gold execution byte for byte)
# ---------------------------------------------------------------------------------------------

def extract_sql(decoded: str) -> str:
    semicolon = decoded.find(";")
    if semicolon >= 0:
        return decoded[: semicolon + 1].strip()
    blank = decoded.find("\n\n")
    if blank >= 0:
        return decoded[:blank].strip()
    return decoded.strip()


def canonical_result(rows: list[tuple[Any, ...]], *, ordered: bool) -> str:
    def cell(value: Any) -> Any:
        if value is None or isinstance(value, (int, float, str)) and not isinstance(value, bool):
            return value
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (bytes, bytearray, memoryview)):
            return bytes(value).hex()
        return str(value)
    canon_rows = [[cell(value) for value in row] for row in rows]
    if not ordered:
        canon_rows.sort(key=lambda row: canonical(row))
    return sha(canonical(canon_rows))


def open_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro&immutable=1", uri=True)
    connection.text_factory = lambda raw: raw.decode("utf-8", "replace")
    return connection


class _Deadline(Exception):
    pass


def execute_emission(
    connection: sqlite3.Connection, emission: str, gold_result_sha256: str, *, timeout_seconds: float,
) -> dict[str, Any]:
    """One emission against one read-only connection. A parse/execution error or a timeout is a
    counted mismatch (`executed: false, matched: false`), never a refusal of the pass."""

    if not emission.strip():
        return {"executed": False, "error_class": "EMPTY_EMISSION", "result_sha256": None, "matched": False}
    deadline = time.monotonic() + timeout_seconds

    def guard() -> int:
        return 1 if time.monotonic() > deadline else 0

    connection.set_progress_handler(guard, 1000)
    try:
        cursor = connection.execute(emission)
        rows = cursor.fetchall()
        if cursor.description is None:
            return {"executed": False, "error_class": "NO_RESULT_SET", "result_sha256": None, "matched": False}
    except sqlite3.OperationalError as error:
        message = str(error)
        error_class = "TIMEOUT" if "interrupted" in message.lower() or time.monotonic() > deadline else "OperationalError"
        return {"executed": False, "error_class": error_class, "result_sha256": None, "matched": False}
    except sqlite3.Error as error:
        return {"executed": False, "error_class": type(error).__name__, "result_sha256": None, "matched": False}
    finally:
        connection.set_progress_handler(None, 0)
    result_sha256 = canonical_result(rows, ordered="order by" in emission.lower())
    return {"executed": True, "error_class": None, "result_sha256": result_sha256, "matched": result_sha256 == gold_result_sha256}


# ---------------------------------------------------------------------------------------------
# The pass: frozen order, one emission per item, execution, receipt
# ---------------------------------------------------------------------------------------------

Emitter = Callable[[str, int], dict[str, Any]]
"""emit(prompt_text, position) -> {"decoded_text": str, "generated_token_count": int,
"prompt_token_count": int, "stop_reason": str}. The real emitter is `build_real_emitter`; tests
inject a stub. The emitter never sees gold, database bytes, or another item's record."""


def run_pass(
    contract: dict[str, Any],
    by_sha: dict[str, tuple[Path, dict[str, Any]]],
    emit: Emitter,
    *,
    sql_timeout_seconds: float = 5.0,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    frozen = contract["frozen_items"]
    database_digests = sorted({item["database_object"]["sha256"] for item in frozen})
    items: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="issue2162-inference-") as temporary:
        root = Path(temporary)
        paths: dict[str, Path] = {}
        for digest in database_digests:
            sample = next(item for item in frozen if item["database_object"]["sha256"] == digest)
            raw = bound_payload(by_sha, sample["database_object"], sample["item_id"])
            paths[digest] = root / f"{digest}.sqlite"
            paths[digest].write_bytes(raw)
        connections = {digest: open_read_only(path) for digest, path in paths.items()}
        try:
            for position, item in enumerate(frozen):
                item_id = item["item_id"]
                prompt_raw = bound_payload(by_sha, item["prompt_object"], item_id)
                prompt_text = prompt_raw.decode("utf-8")
                started = time.monotonic()
                emitted = emit(prompt_text, position)
                decoded = emitted.get("decoded_text")
                if not isinstance(decoded, str):
                    raise ValueError(f"TOOL_USE_EMITTER_CONTRACT_REFUSED:{item_id}")
                emission = extract_sql(decoded)
                execution = execute_emission(
                    connections[item["database_object"]["sha256"]], emission, item["gold_result_sha256"],
                    timeout_seconds=sql_timeout_seconds,
                )
                record = {
                    "position": position,
                    "item_id": item_id,
                    "prompt_sha256": item["prompt_object"]["sha256"],
                    "database_sha256": item["database_object"]["sha256"],
                    "emission": emission,
                    "emission_sha256": sha(emission.encode("utf-8")),
                    "decoded_text_sha256": sha(decoded.encode("utf-8")),
                    "prompt_token_count": int(emitted.get("prompt_token_count", -1)),
                    "generated_token_count": int(emitted.get("generated_token_count", -1)),
                    "stop_reason": str(emitted.get("stop_reason", "unknown")),
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    **execution,
                }
                items.append(record)
                if progress is not None:
                    progress(record)
        finally:
            for connection in connections.values():
                connection.close()
        after = {digest: sha(path.read_bytes()) for digest, path in paths.items()}
    if any(after[digest] != digest for digest in after):
        raise ValueError("TOOL_USE_DATABASE_BYTES_CHANGED_REFUSED")
    if len(items) != ITEM_COUNT:
        raise ValueError(f"TOOL_USE_INFERENCE_TOTALITY_REFUSED:{len(items)}")
    return {
        "items": items,
        "item_count": len(items),
        "emitted_count": len(items),
        "executed_count": sum(1 for item in items if item["executed"]),
        "matched_count": sum(1 for item in items if item["matched"]),
        "database_bytes_unchanged": True,
    }


def frozen_order_sha256(item_ids: list[str]) -> str:
    return sha(canonical(item_ids))


def build_receipt(
    *,
    contract: dict[str, Any],
    contract_raw: bytes,
    pass_result: dict[str, Any],
    checkpoint_manifest_raw_sha256: str,
    model_bindings: dict[str, Any],
    connector_receipt_raw_sha256s: list[str],
) -> dict[str, Any]:
    binding = contract.get("catalog_binding") if isinstance(contract.get("catalog_binding"), dict) else {}
    receipt: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA,
        "result": RESULT_PASS,
        "row_id": "E-MATRIX-TOOL-USE",
        "contract_self_sha256": contract["self_sha256"],
        "contract_raw_sha256": sha(contract_raw),
        "catalog_export_raw_sha256": binding.get("catalog_export_raw_sha256"),
        "connector_receipt_raw_sha256s": connector_receipt_raw_sha256s,
        "checkpoint_manifest_raw_sha256": checkpoint_manifest_raw_sha256,
        "model_bindings": model_bindings,
        "decode_contract": DECODE_CONTRACT,
        "decode_contract_sha256": decode_contract_sha256(),
        "result_canonicalization": RESULT_CANONICALIZATION,
        "database_access": DATABASE_ACCESS,
        "frozen_order_sha256": frozen_order_sha256([item["item_id"] for item in pass_result["items"]]),
        "item_count": pass_result["item_count"],
        "emitted_count": pass_result["emitted_count"],
        "executed_count": pass_result["executed_count"],
        "matched_count": pass_result["matched_count"],
        "database_bytes_unchanged": pass_result["database_bytes_unchanged"],
        "items": pass_result["items"],
        "claim_boundary": CLAIM_BOUNDARY,
    }
    receipt["self_sha256"] = sha(canonical(receipt))
    return receipt


# ---------------------------------------------------------------------------------------------
# Verification (what the release-row adapter re-derives; also the `verify` subcommand)
# ---------------------------------------------------------------------------------------------

def verify_receipt(
    receipt_path: Path, contract_path: Path, *, expected_checkpoint_manifest_sha256: str,
) -> dict[str, Any]:
    """Re-derive every binding from the contract. `matched` is recomputed from the contract's
    gold_result_sha256, never trusted from the receipt. Returns {receipt, contract, items, score}."""

    contract, contract_raw = load_contract(contract_path)
    raw = receipt_path.read_bytes()
    try:
        receipt = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("TOOL_USE_INFERENCE_RECEIPT_SELF_HASH_REFUSED") from error
    if not isinstance(receipt, dict) or receipt.get("schema_version") != RECEIPT_SCHEMA:
        raise ValueError("TOOL_USE_INFERENCE_RECEIPT_SELF_HASH_REFUSED")
    body = dict(receipt)
    claimed = body.pop("self_sha256", None)
    if claimed != sha(canonical(body)):
        raise ValueError("TOOL_USE_INFERENCE_RECEIPT_SELF_HASH_REFUSED")
    if receipt.get("checkpoint_manifest_raw_sha256") != expected_checkpoint_manifest_sha256:
        raise ValueError("TOOL_USE_INFERENCE_CHECKPOINT_BINDING_REFUSED")
    if (
        receipt.get("contract_self_sha256") != contract["self_sha256"]
        or receipt.get("contract_raw_sha256") != sha(contract_raw)
        or receipt.get("decode_contract_sha256") != decode_contract_sha256()
        or receipt.get("decode_contract") != DECODE_CONTRACT
    ):
        raise ValueError("TOOL_USE_INFERENCE_CONTRACT_BINDING_REFUSED")
    items = receipt.get("items")
    if (
        receipt.get("result") != RESULT_PASS
        or not isinstance(items, list)
        or len(items) != ITEM_COUNT
        or receipt.get("item_count") != ITEM_COUNT
        or receipt.get("emitted_count") != ITEM_COUNT
        or receipt.get("database_bytes_unchanged") is not True
    ):
        raise ValueError("TOOL_USE_INFERENCE_TOTALITY_REFUSED")
    frozen = contract["frozen_items"]
    ordered_ids = [item["item_id"] for item in frozen]
    if receipt.get("frozen_order_sha256") != frozen_order_sha256(ordered_ids):
        raise ValueError("TOOL_USE_EMISSION_ORDER_REFUSED")
    rows: list[dict[str, Any]] = []
    executed = matched = 0
    for position, (record, item) in enumerate(zip(items, frozen)):
        if not isinstance(record, dict) or record.get("position") != position or record.get("item_id") != item["item_id"]:
            raise ValueError("TOOL_USE_EMISSION_ORDER_REFUSED")
        if record.get("prompt_sha256") != item["prompt_object"]["sha256"] or record.get("database_sha256") != item["database_object"]["sha256"]:
            raise ValueError(f"TOOL_USE_INFERENCE_CONTRACT_BINDING_REFUSED:{item['item_id']}")
        emission = record.get("emission")
        if not isinstance(emission, str) or record.get("emission_sha256") != sha(emission.encode("utf-8")):
            raise ValueError(f"TOOL_USE_INFERENCE_RECEIPT_SELF_HASH_REFUSED:{item['item_id']}")
        is_executed = record.get("executed") is True and isinstance(record.get("result_sha256"), str)
        is_matched = is_executed and record["result_sha256"] == item["gold_result_sha256"]
        if record.get("matched") is not is_matched:
            raise ValueError(f"TOOL_USE_INFERENCE_CONTRACT_BINDING_REFUSED:matched:{item['item_id']}")
        executed += int(is_executed)
        matched += int(is_matched)
        rows.append({
            "item_id": item["item_id"],
            "gold_item_sha256": item["gold_item_sha256"],
            "prediction": record["emission_sha256"],
            "score": 1.0 if is_matched else 0.0,
        })
    if receipt.get("executed_count") != executed or receipt.get("matched_count") != matched:
        raise ValueError("TOOL_USE_INFERENCE_TOTALITY_REFUSED:counts")
    return {
        "receipt": receipt,
        "receipt_raw_sha256": sha(raw),
        "contract": contract,
        "contract_raw_sha256": sha(contract_raw),
        "items": rows,
        "executed_count": executed,
        "matched_count": matched,
        "score": matched / ITEM_COUNT,
    }


# ---------------------------------------------------------------------------------------------
# Real emitter: designated checkpoint, tool expert, greedy decode (CUDA)
# ---------------------------------------------------------------------------------------------

def load_designation(path: Path, checkpoint_manifest: Path) -> tuple[dict[str, Any], str]:
    designation, _raw = load_self_hashed(path, DESIGNATION_SCHEMA, "TOOL_USE_DESIGNATION") if _is_self_hashed(path) else (json.loads(path.read_text(encoding="utf-8")), b"")
    if designation.get("result") != "DESIGNATED" or not isinstance(designation.get("manifest"), dict):
        raise ValueError("TOOL_USE_DESIGNATION_REFUSED")
    manifest_sha = sha_file(checkpoint_manifest)
    if designation["manifest"].get("raw_sha256") != manifest_sha:
        raise ValueError("TOOL_USE_DESIGNATION_MANIFEST_BINDING_REFUSED")
    return designation, manifest_sha


def _is_self_hashed(path: Path) -> bool:
    try:
        return "self_sha256" in json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False


def _load_module_from_bytes(source_bytes: bytes, source_path: Path, name: str):
    module = types.ModuleType(name)
    module.__file__ = str(source_path)
    sys.modules[name] = module
    try:
        exec(compile(source_bytes, str(source_path), "exec"), module.__dict__)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


def build_real_emitter(args: argparse.Namespace) -> tuple[Emitter, dict[str, Any], str]:
    import torch
    from tokenizers import Tokenizer

    designation, manifest_sha = load_designation(args.designation, args.checkpoint_manifest)
    manifest = json.loads(args.checkpoint_manifest.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "ember-sparse-checkpoint-v5" or manifest.get("architecture_revision") != "ember-sparse-3b-v2":
        raise ValueError("TOOL_USE_CHECKPOINT_SCHEMA_REFUSED")
    config_sha = sha_file(args.model_config)
    if manifest.get("model_config_sha256") != config_sha:
        raise ValueError("TOOL_USE_MODEL_CONFIG_BINDING_REFUSED")
    tokenizer_raw = args.tokenizer.read_bytes()
    tokenizer_sha = sha(tokenizer_raw)
    identity = designation.get("checkpoint_identity") if isinstance(designation.get("checkpoint_identity"), dict) else {}
    if identity.get("tokenizer_sha256") not in (None, tokenizer_sha):
        raise ValueError("TOOL_USE_TOKENIZER_BINDING_REFUSED")
    shards = {record["path"]: record for record in manifest.get("shards", []) if isinstance(record, dict)}
    root = args.checkpoint_manifest.parent
    for name in (SHARED_SHARD, EXPERT_SHARD):
        record = shards.get(name)
        path = root / name
        if record is None or not path.is_file() or path.stat().st_size != record.get("bytes") or sha_file(path) != record.get("sha256"):
            raise ValueError(f"TOOL_USE_SHARD_INTEGRITY_REFUSED:{name}")
    source_bytes = args.model_source.read_bytes()
    module = _load_module_from_bytes(source_bytes, args.model_source, "ember_issue2162_model")
    config = module.RestartDecoderConfig.from_contract(args.model_config)
    device = torch.device(args.device)
    previous_dtype = torch.get_default_dtype()
    torch.set_default_dtype(torch.bfloat16)
    try:
        model = module.UnifiedDecoder(config, device=device, allow_production_allocation=True)
    finally:
        torch.set_default_dtype(previous_dtype)
    expected = model.state_dict()
    shared_expected = {key for key in expected if ".experts." not in key}
    expert_expected = {key for key in expected if f".experts.{ACTIVE_EXPERT}." in key}
    for name, expected_keys, label in ((SHARED_SHARD, shared_expected, "shared"), (EXPERT_SHARD, expert_expected, ACTIVE_EXPERT)):
        payload = torch.load(root / name, map_location="cpu", weights_only=True, mmap=True)
        state = payload.get("model") if isinstance(payload, dict) else None
        if not isinstance(state, dict) or set(state) != expected_keys:
            raise ValueError(f"TOOL_USE_SHARD_STATE_REFUSED:{label}")
        if name == EXPERT_SHARD and payload.get("expert") != ACTIVE_EXPERT:
            raise ValueError("TOOL_USE_SHARD_STATE_REFUSED:expert_identity")
        for key, tensor in state.items():
            if tuple(tensor.shape) != tuple(expected[key].shape):
                raise ValueError(f"TOOL_USE_SHARD_STATE_REFUSED:{label}:{key}")
        missing, unexpected = model.load_state_dict({k: v.to(device=device, dtype=torch.bfloat16) for k, v in state.items()}, strict=False)
        if unexpected or any(key in expected_keys for key in missing):
            raise ValueError(f"TOOL_USE_SHARD_STATE_REFUSED:{label}:load")
        del payload, state
    model._activate_expert(ACTIVE_EXPERT)
    model.eval()
    tokenizer = Tokenizer.from_str(tokenizer_raw.decode("utf-8"))
    eos = int(DECODE_CONTRACT["eos_token_id"])
    limit = int(DECODE_CONTRACT["max_new_tokens"])

    def emit(prompt_text: str, position: int) -> dict[str, Any]:
        prompt_ids = tokenizer.encode(prompt_text).ids
        if not prompt_ids or any(token >= config.vocab_size for token in prompt_ids):
            raise ValueError(f"TOOL_USE_PROMPT_TOKENIZATION_REFUSED:{position}")
        tokens = torch.tensor([prompt_ids], device=device, dtype=torch.long)
        generated: list[int] = []
        stop_reason = "max_new_tokens"
        with torch.no_grad():
            for _ in range(limit):
                logits = model(tokens, active_expert=ACTIVE_EXPERT)
                token = int(torch.argmax(logits[:, -1, :], dim=-1).item())
                generated.append(token)
                if token == eos:
                    stop_reason = "eos_token"
                    break
                text = tokenizer.decode(generated)
                if ";" in text:
                    stop_reason = "first_semicolon_in_decoded_text"
                    break
                if "\n\n" in text:
                    stop_reason = "first_blank_line_in_decoded_text"
                    break
                tokens = torch.cat((tokens, torch.tensor([[token]], device=device, dtype=torch.long)), dim=1)
        decoded = tokenizer.decode([token for token in generated if token != eos])
        return {
            "decoded_text": decoded,
            "generated_token_count": len(generated),
            "prompt_token_count": len(prompt_ids),
            "stop_reason": stop_reason,
        }

    bindings = {
        "designation_candidate_id": designation.get("candidate_id"),
        "model_source_sha256": sha(source_bytes),
        "model_config_sha256": config_sha,
        "tokenizer_sha256": tokenizer_sha,
        "shared_shard_sha256": shards[SHARED_SHARD]["sha256"],
        "expert_shard_sha256": shards[EXPERT_SHARD]["sha256"],
        "active_expert": ACTIVE_EXPERT,
        "device": str(device),
        "torch_version": torch.__version__,
    }
    return emit, bindings, manifest_sha


# ---------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------

def write_new(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="operation", required=True)
    produce = subparsers.add_parser("produce")
    produce.add_argument("--contract", type=Path, required=True)
    produce.add_argument("--source-receipt", type=Path, action="append", required=True)
    produce.add_argument("--designation", type=Path, required=True)
    produce.add_argument("--checkpoint-manifest", type=Path, required=True)
    produce.add_argument("--model-config", type=Path, required=True)
    produce.add_argument("--model-source", type=Path, required=True)
    produce.add_argument("--tokenizer", type=Path, required=True)
    produce.add_argument("--output", type=Path, required=True)
    produce.add_argument("--progress-log", type=Path)
    produce.add_argument("--device", default="cuda")
    produce.add_argument("--sql-timeout-seconds", type=float, default=5.0)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--receipt", type=Path, required=True)
    verify.add_argument("--contract", type=Path, required=True)
    verify.add_argument("--expected-checkpoint-manifest-sha256", required=True)
    args = parser.parse_args()

    if args.operation == "verify":
        try:
            verified = verify_receipt(args.receipt, args.contract, expected_checkpoint_manifest_sha256=args.expected_checkpoint_manifest_sha256)
        except (OSError, TypeError, ValueError) as error:
            print(json.dumps({"result": "REFUSED", "reason": str(error)}, sort_keys=True))
            return 78
        print(json.dumps({"result": "VERIFIED", "matched_count": verified["matched_count"], "executed_count": verified["executed_count"], "score": verified["score"]}, sort_keys=True))
        return 0

    if args.output.exists():
        raise SystemExit("TOOL_USE_RECEIPT_EXISTS_REFUSED")
    contract, contract_raw = load_contract(args.contract)
    by_sha, supplied = load_sources(contract, list(args.source_receipt))
    emit, bindings, manifest_sha = build_real_emitter(args)
    log = args.progress_log.open("a", encoding="utf-8", newline="\n") if args.progress_log else None

    def progress(record: dict[str, Any]) -> None:
        if log is not None:
            log.write(json.dumps({k: record[k] for k in ("position", "item_id", "executed", "matched", "generated_token_count", "stop_reason", "elapsed_seconds")}, sort_keys=True) + "\n")
            log.flush()

    try:
        pass_result = run_pass(contract, by_sha, emit, sql_timeout_seconds=args.sql_timeout_seconds, progress=progress)
    finally:
        if log is not None:
            log.close()
    receipt = build_receipt(
        contract=contract, contract_raw=contract_raw, pass_result=pass_result,
        checkpoint_manifest_raw_sha256=manifest_sha, model_bindings=bindings, connector_receipt_raw_sha256s=supplied,
    )
    write_new(args.output, receipt)
    print(json.dumps({"result": receipt["result"], "self_sha256": receipt["self_sha256"], "matched_count": receipt["matched_count"], "executed_count": receipt["executed_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
