# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Worktree-invariant, content-addressed training-input admission for #812."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


class InputIdentityError(ValueError):
    """A fail-closed input admission error with a stable machine-readable code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


@dataclass(frozen=True)
class ResolvedInputIdentity:
    identity_manifest: str
    artifact_id: str
    shard_path: str
    sha256: str
    bytes: int
    selection_source: str
    admission_receipt_path: str | None = None
    admission_receipt_sha256: str | None = None

    def packet_value(self) -> dict[str, Any]:
        value = {
            "identity_manifest": self.identity_manifest,
            "artifact_id": self.artifact_id,
            "shard_path": self.shard_path,
            "sha256": self.sha256,
            "bytes": self.bytes,
        }
        if self.admission_receipt_path is not None and self.admission_receipt_sha256 is not None:
            value["admission_receipt_path"] = self.admission_receipt_path
            value["admission_receipt_sha256"] = self.admission_receipt_sha256
        return value

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative_file(repo_root: Path, value: str, *, missing_code: str) -> tuple[Path, str]:
    if not isinstance(value, str) or not value:
        raise InputIdentityError("wrong_identity", "path must be a non-empty repository-relative string")
    normalized = PurePosixPath(value.replace("\\", "/"))
    if normalized.is_absolute() or ".." in normalized.parts:
        raise InputIdentityError("wrong_identity", "path must remain inside the selected worktree")
    relative = normalized.as_posix()
    resolved = (repo_root / relative).resolve()
    try:
        resolved.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise InputIdentityError("wrong_identity", "path escapes the selected worktree") from exc
    if not resolved.is_file():
        raise InputIdentityError(missing_code, f"required file is absent: {relative}")
    return resolved, relative


def _load_contract(config_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InputIdentityError("wrong_identity", f"cannot read config contract: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("training"), dict):
        raise InputIdentityError("wrong_identity", "config must declare a training object")
    return payload


def resolve_input_identity(
    *,
    repo_root: Path,
    config_path: Path,
    input_identity_arg: str | None = None,
) -> ResolvedInputIdentity:
    """Resolve bytes from the selected worktree, never CWD or an ambient default."""

    repo_root = repo_root.resolve()
    try:
        config_relative = config_path.resolve().relative_to(repo_root).as_posix()
    except ValueError as exc:
        raise InputIdentityError("wrong_identity", "config must reside in the selected worktree") from exc
    contract = _load_contract(repo_root / config_relative)
    training = contract["training"]
    requested = input_identity_arg
    selection_source = "explicit_cli" if requested is not None else "contract_default"
    if requested is None:
        requested = training.get("input_identity_manifest")
    manifest_path, manifest_relative = _relative_file(repo_root, requested, missing_code="missing_input")
    try:
        identity = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InputIdentityError("wrong_identity", f"input identity manifest is unreadable: {exc}") from exc
    if not isinstance(identity, dict) or identity.get("schema_version") != "ember-input-identity-v1":
        raise InputIdentityError("wrong_identity", "input identity schema is not admitted")
    artifact_id = identity.get("artifact_id")
    expected_id = training.get("expected_input_artifact_id")
    if not isinstance(artifact_id, str) or not artifact_id or artifact_id != expected_id:
        raise InputIdentityError("wrong_identity", "input artifact identity does not match the contract")
    shard_path, shard_relative = _relative_file(repo_root, identity.get("shard_path"), missing_code="missing_input")
    actual_sha = _sha256(shard_path)
    actual_bytes = shard_path.stat().st_size
    expected_sha = identity.get("sha256")
    expected_bytes = identity.get("bytes")
    if not isinstance(expected_sha, str) or actual_sha != expected_sha:
        raise InputIdentityError("byte_drift", "shard content hash differs from the selected identity")
    if not isinstance(expected_bytes, int) or actual_bytes != expected_bytes:
        raise InputIdentityError("byte_drift", "shard byte count differs from the selected identity")
    receipt_relative: str | None = None
    receipt_sha256: str | None = None
    if artifact_id == "owned-four-domain-production-rung-v1":
        from production_rung import ARTIFACT_ID, RECEIPT_RELATIVE, SHARD_RELATIVE, verify_bound_rung

        if artifact_id != ARTIFACT_ID or shard_relative != SHARD_RELATIVE:
            raise InputIdentityError("wrong_identity", "production rung identity does not bind the canonical owned shard")
        receipt_path, receipt_relative = _relative_file(repo_root, identity.get("admission_receipt_path"), missing_code="missing_input")
        expected_receipt_sha = identity.get("admission_receipt_sha256")
        if receipt_relative != RECEIPT_RELATIVE or not isinstance(expected_receipt_sha, str):
            raise InputIdentityError("wrong_identity", "production rung identity lacks the canonical admission receipt")
        receipt_sha256 = _sha256(receipt_path)
        if receipt_sha256 != expected_receipt_sha:
            raise InputIdentityError("byte_drift", "production rung receipt hash differs from the selected identity")
        try:
            verify_bound_rung(root=repo_root, shard_path=shard_path, receipt_path=receipt_path)
        except ValueError as error:
            raise InputIdentityError("wrong_identity", f"production rung receipt verification failed: {error}") from error
    return ResolvedInputIdentity(
        identity_manifest=manifest_relative,
        artifact_id=artifact_id,
        shard_path=shard_relative,
        sha256=actual_sha,
        bytes=actual_bytes,
        selection_source=selection_source,
        admission_receipt_path=receipt_relative,
        admission_receipt_sha256=receipt_sha256,
    )


def build_launch_packet(
    *,
    repo_root: Path,
    config_path: Path,
    input_identity_arg: str | None = None,
) -> dict[str, Any]:
    """Build the live caller packet; the selected identity is a required value."""

    repo_root = repo_root.resolve()
    identity = resolve_input_identity(
        repo_root=repo_root,
        config_path=config_path,
        input_identity_arg=input_identity_arg,
    )
    config_relative = config_path.resolve().relative_to(repo_root).as_posix()
    return {
        "schema_version": "ember-launch-packet-v1",
        "config_path": config_relative,
        "config_sha256": _sha256(repo_root / config_relative),
        "requested_input_identity": identity.identity_manifest,
        "selection_source": identity.selection_source,
        "input_identity": identity.packet_value(),
    }


def validate_launch_packet(packet: dict[str, Any], *, repo_root: Path) -> dict[str, str]:
    """Re-resolve and consume the caller identity; decorative fields fail closed."""

    if not isinstance(packet, dict) or packet.get("schema_version") != "ember-launch-packet-v1":
        raise InputIdentityError("caller_omission", "launch packet schema is absent")
    if not isinstance(packet.get("config_path"), str) or not isinstance(packet.get("requested_input_identity"), str):
        raise InputIdentityError("caller_omission", "caller did not forward config and selected input identity")
    if not isinstance(packet.get("input_identity"), dict):
        raise InputIdentityError("caller_omission", "caller did not forward resolved input identity")
    repo_root = repo_root.resolve()
    config_path, _ = _relative_file(repo_root, packet["config_path"], missing_code="caller_omission")
    if packet.get("config_sha256") != _sha256(config_path):
        raise InputIdentityError("config_drift", "launch config bytes changed after packet construction")
    resolved = resolve_input_identity(
        repo_root=repo_root,
        config_path=config_path,
        input_identity_arg=packet["requested_input_identity"],
    )
    if packet["input_identity"] != resolved.packet_value():
        raise InputIdentityError("decorative_argument", "caller packet identity was not the consumed identity")
    return {"decision": "ACCEPTED", "input_sha256": resolved.sha256}


def read_admitted_shard_bytes(packet: dict[str, Any], *, repo_root: Path) -> bytes:
    """Read the consumer artifact once and bind that exact buffer to the launch packet."""

    identity = packet.get("input_identity") if isinstance(packet, dict) else None
    if not isinstance(identity, dict):
        raise InputIdentityError("caller_omission", "launch packet lacks a concrete input identity")
    shard_path, _ = _relative_file(repo_root.resolve(), identity.get("shard_path"), missing_code="missing_input")
    try:
        shard_bytes = shard_path.read_bytes()
    except OSError as exc:
        raise InputIdentityError("missing_input", "admitted shard cannot be read by the consumer") from exc
    expected_sha = identity.get("sha256")
    expected_bytes = identity.get("bytes")
    if not isinstance(expected_sha, str) or _sha256_bytes(shard_bytes) != expected_sha:
        raise InputIdentityError("byte_drift", "admitted shard changed after launch admission")
    if not isinstance(expected_bytes, int) or len(shard_bytes) != expected_bytes:
        raise InputIdentityError("byte_drift", "admitted shard byte count changed after launch admission")
    return shard_bytes


def emit_integration_receipt(
    packet: dict[str, Any],
    validation: dict[str, str],
    *,
    code_commit: str,
) -> dict[str, Any]:
    """Produce a path-free receipt payload for a later bounded write."""

    if not isinstance(code_commit, str) or re.fullmatch(r"[0-9a-f]{40}", code_commit) is None:
        raise InputIdentityError("wrong_identity", "receipt requires an exact code commit")
    if validation.get("decision") != "ACCEPTED":
        raise InputIdentityError("wrong_identity", "only accepted launch packets receive a receipt")
    identity = packet["input_identity"]
    receipt = {
        "schema_version": "ember-input-integration-receipt-v1",
        "code_commit": code_commit,
        "config_sha256": packet["config_sha256"],
        "input_identity_manifest": identity["identity_manifest"],
        "input_artifact_sha256": identity["sha256"],
        "validator_sha256": _sha256(Path(__file__)),
        "launch_decision": validation["decision"],
        "selection_source": packet["selection_source"],
    }
    admission_receipt_sha256 = identity.get("admission_receipt_sha256")
    if admission_receipt_sha256 is not None:
        if not isinstance(admission_receipt_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", admission_receipt_sha256) is None:
            raise InputIdentityError("wrong_identity", "input admission receipt hash is malformed")
        receipt["input_admission_receipt_sha256"] = admission_receipt_sha256
    return receipt


def _verified_catalog_import_receipt(raw: bytes, *, expected_export_sha256: str | None = None) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InputIdentityError("catalog_receipt_drift", "catalog import receipt is unreadable") from exc
    if not isinstance(value, dict) or value.get("schema_version") != "ember-data-catalog-import-receipt-v1" or value.get("result") != "PASS":
        raise InputIdentityError("catalog_receipt_drift", "catalog import receipt is not PASS")
    claimed = value.pop("self_sha256", None)
    if claimed != _sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")):
        raise InputIdentityError("catalog_receipt_drift", "catalog import receipt self hash is invalid")
    value["self_sha256"] = claimed
    if expected_export_sha256 is not None and value.get("canonical_export_sha256") != expected_export_sha256:
        raise InputIdentityError("catalog_receipt_drift", "catalog import receipt does not bind the canonical export")
    return value


def resolve_catalog_evaluation_dataset(
    *,
    catalog_export_raw: bytes,
    dataset_import_receipt_raw: bytes,
    consumer_import_receipt_raw: bytes,
    expected_dataset_id: str,
    expected_split: str = "heldout",
) -> dict[str, Any]:
    """Resolve one exact heldout catalog dataset for evaluation only."""

    resolved = _resolve_catalog_dataset(
        catalog_export_raw=catalog_export_raw,
        dataset_import_receipt_raw=dataset_import_receipt_raw,
        consumer_import_receipt_raw=consumer_import_receipt_raw,
        expected_dataset_id=expected_dataset_id,
        expected_split=expected_split,
        _required_split="heldout",
        _dataset_edge_kind="evaluation_dataset",
        _attempt_record_kind="evaluation_attempt",
        _attempt_evaluation_edge_kind="evaluation_definition",
        _attempt_receipt_edge_kind="evaluation_import_receipt",
    )
    resolved["evaluation_attempt_id"] = resolved.pop("consumer_attempt_id")
    resolved["protected_eval_item_admission"] = True
    return resolved


def _resolve_catalog_dataset(
    *,
    catalog_export_raw: bytes,
    dataset_import_receipt_raw: bytes,
    consumer_import_receipt_raw: bytes,
    expected_dataset_id: str,
    expected_split: str = "train",
    _required_split: str = "train",
    _dataset_edge_kind: str = "consumer_dataset",
    _attempt_record_kind: str = "consumer_attempt",
    _attempt_evaluation_edge_kind: str = "consumer_evaluation",
    _attempt_receipt_edge_kind: str = "consumer_receipt",
) -> dict[str, Any]:
    """Resolve one exact split-honest catalog dataset consumed by certified preflight."""

    if expected_split != _required_split:
        raise InputIdentityError(
            "catalog_dataset_split_refused", f"resolver admits only {_required_split} datasets"
        )

    catalog_export_sha256 = _sha256_bytes(catalog_export_raw)
    _verified_catalog_import_receipt(dataset_import_receipt_raw)
    _verified_catalog_import_receipt(
        consumer_import_receipt_raw, expected_export_sha256=catalog_export_sha256
    )
    try:
        catalog = json.loads(catalog_export_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InputIdentityError("catalog_receipt_drift", "canonical catalog export is unreadable") from exc
    records = catalog.get("records") if isinstance(catalog, dict) else None
    edges = catalog.get("edges") if isinstance(catalog, dict) else None
    if not isinstance(records, list) or not isinstance(edges, list):
        raise InputIdentityError("catalog_receipt_drift", "canonical catalog export schema is invalid")
    if json.dumps(catalog, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    ) != catalog_export_raw:
        raise InputIdentityError("catalog_receipt_drift", "canonical catalog export bytes have drifted")
    expected_dataset_rows = [
        row
        for row in records
        if isinstance(row, dict)
        and row.get("kind") == "dataset_version"
        and row.get("id") == expected_dataset_id
    ]
    if len(expected_dataset_rows) != 1:
        raise InputIdentityError(
            "catalog_dataset_substitution",
            "catalog must carry exactly one dataset version row for the expected identity",
        )
    admitted_datasets = {
        row["id"]: row
        for row in expected_dataset_rows
        if row.get("state") == "admitted" and isinstance(row.get("id"), str)
    }
    consumer_dataset_edges = [
        edge
        for edge in edges
        if isinstance(edge, dict)
        and edge.get("kind") == _dataset_edge_kind
        and edge.get("to_id") == expected_dataset_id
        and expected_dataset_id in admitted_datasets
        and isinstance(edge.get("from_id"), str)
    ]
    if len(consumer_dataset_edges) != 1:
        raise InputIdentityError(
            "catalog_dataset_substitution",
            "catalog must derive one exact admitted dataset consumer binding",
        )
    derived_dataset_id = consumer_dataset_edges[0]["to_id"]
    if expected_dataset_id != derived_dataset_id:
        raise InputIdentityError(
            "catalog_dataset_substitution",
            "caller dataset identity does not equal the catalog-derived identity",
        )
    dataset = admitted_datasets[derived_dataset_id]
    forbidden_dataset_prefix = (
        "dataset:issue1581-bulk-heldout:"
        if _required_split == "train"
        else "dataset:issue1581-bulk-train:"
    )
    if derived_dataset_id.startswith(forbidden_dataset_prefix):
        raise InputIdentityError(
            "catalog_dataset_split_refused",
            f"{_required_split} resolver refuses an opposite-split dataset",
        )
    consumer_id = consumer_dataset_edges[0]["from_id"]
    consumer_records = [
        row
        for row in records
        if isinstance(row, dict)
        and row.get("kind") == _attempt_record_kind
        and row.get("id") == consumer_id
        and row.get("state") in {"admitted", "completed"}
    ]
    if len(consumer_records) != 1:
        raise InputIdentityError(
            "catalog_dataset_substitution", "catalog-derived consumer attempt is absent"
        )
    version_membership_edges = [
        edge
        for edge in edges
        if isinstance(edge, dict)
        and edge.get("kind") == "version_membership"
        and edge.get("from_id") == derived_dataset_id
        and isinstance(edge.get("to_id"), str)
    ]
    membership_ids = {edge["to_id"] for edge in version_membership_edges}
    if len(version_membership_edges) != len(membership_ids):
        raise InputIdentityError(
            "catalog_dataset_substitution",
            "catalog dataset carries duplicate version membership edges",
        )
    memberships = [
        row
        for row in records
        if isinstance(row, dict)
        and row.get("kind") == "membership"
        and row.get("id") in membership_ids
    ]
    if len(memberships) != len(membership_ids) or not memberships or any(
        row.get("split") != expected_split or row.get("admission_state") != "admitted"
        for row in memberships
    ):
        raise InputIdentityError("catalog_dataset_substitution", "catalog dataset does not match the exact admitted split")
    membership_object_edges = [
        edge
        for edge in edges
        if isinstance(edge, dict)
        and edge.get("kind") == "membership_object"
        and edge.get("from_id") in membership_ids
        and isinstance(edge.get("to_id"), str)
    ]
    if len(membership_object_edges) != len(membership_ids) or {
        edge["from_id"] for edge in membership_object_edges
    } != membership_ids:
        raise InputIdentityError(
            "catalog_dataset_substitution",
            "each catalog membership must bind one immutable object",
        )
    object_ids = {edge["to_id"] for edge in membership_object_edges}
    selected_object_rows = [
        row
        for row in records
        if isinstance(row, dict)
        and row.get("kind") == "immutable_object"
        and row.get("id") in object_ids
    ]
    if len(selected_object_rows) != len(object_ids):
        raise InputIdentityError(
            "catalog_dataset_substitution",
            "catalog must carry exactly one immutable object row per selected object",
        )
    object_records = {
        row["id"]: row
        for row in records
        if isinstance(row, dict)
        and row.get("kind") == "immutable_object"
        and row.get("id") in object_ids
        and row.get("custody_state") == "available"
    }
    if set(object_records) != object_ids or any(
        row.get("id") != f"sha256:{row.get('sha256')}" for row in object_records.values()
    ):
        raise InputIdentityError(
            "catalog_dataset_substitution",
            "catalog objects are absent or not available under their hashes",
        )
    source_object_pair_counts: dict[tuple[str, str], int] = {}
    for edge in edges:
        if (
            isinstance(edge, dict)
            and edge.get("kind") == "source_object"
            and isinstance(edge.get("from_id"), str)
            and edge["from_id"].startswith("source:")
            and isinstance(edge.get("to_id"), str)
        ):
            pair = (edge["from_id"], edge["to_id"])
            source_object_pair_counts[pair] = source_object_pair_counts.get(pair, 0) + 1
    source_record_ids = set()
    for edge in membership_object_edges:
        object_digest = edge["to_id"].removeprefix("sha256:")
        membership_id = edge["from_id"]
        prefix = "membership:"
        suffix = f":{object_digest}"
        if not membership_id.startswith(prefix) or not membership_id.endswith(suffix):
            raise InputIdentityError(
                "catalog_dataset_substitution",
                "catalog membership does not encode its exact source/object binding",
            )
        source_id = membership_id[len(prefix) : -len(suffix)]
        source_record_id = f"source:{source_id}"
        if source_object_pair_counts.get((source_record_id, edge["to_id"])) != 1:
            raise InputIdentityError(
                "catalog_dataset_substitution",
                "catalog dataset objects do not derive from exact source/object edges",
            )
        source_record_ids.add(source_record_id)
    selected_source_rows = [
        row
        for row in records
        if isinstance(row, dict)
        and row.get("kind") == "source"
        and row.get("id") in source_record_ids
    ]
    if len(selected_source_rows) != len(source_record_ids):
        raise InputIdentityError(
            "catalog_dataset_substitution",
            "catalog must carry exactly one source row per derived selected source",
        )
    source_records = {
        row["id"]
        for row in selected_source_rows
        if row.get("license_verdict") == "accepted"
    }
    if source_records != source_record_ids:
        raise InputIdentityError(
            "catalog_dataset_substitution",
            "catalog source/object edges do not resolve accepted sources",
        )
    evaluation_edges = [
        edge
        for edge in edges
        if isinstance(edge, dict)
        and edge.get("kind") == _attempt_evaluation_edge_kind
        and edge.get("from_id") == consumer_id
        and isinstance(edge.get("to_id"), str)
    ]
    if len(evaluation_edges) != 1:
        raise InputIdentityError("catalog_dataset_substitution", "catalog consumer lacks one evaluation-isolation binding")
    evaluation_id = evaluation_edges[0]["to_id"]
    evaluation_records = [
        row
        for row in records
        if isinstance(row, dict)
        and row.get("kind") == "protected_eval"
        and row.get("id") == evaluation_id
    ]
    if len(evaluation_records) != 1:
        raise InputIdentityError(
            "catalog_dataset_substitution",
            "catalog evaluation isolation record is absent or duplicated",
        )
    evaluation_object_edges = [
        edge
        for edge in edges
        if isinstance(edge, dict)
        and edge.get("kind") == "evaluation_object"
        and edge.get("from_id") == evaluation_id
        and isinstance(edge.get("to_id"), str)
    ]
    if len(evaluation_object_edges) != 1:
        raise InputIdentityError(
            "catalog_dataset_substitution",
            "catalog evaluation isolation lacks one immutable object",
        )
    evaluation_object_id = evaluation_object_edges[0]["to_id"]
    if evaluation_object_id in object_ids:
        raise InputIdentityError("catalog_dataset_substitution", "catalog objects overlap the protected evaluation identity")
    evaluation_digest = evaluation_object_id.removeprefix("sha256:")
    evaluation_object_records = [
        row
        for row in records
        if isinstance(row, dict)
        and row.get("kind") == "immutable_object"
        and row.get("id") == evaluation_object_id
        and row.get("sha256") == evaluation_digest
        and row.get("custody_state") == "available"
    ]
    evaluation_receipt_edges = [
        edge
        for edge in edges
        if isinstance(edge, dict)
        and edge.get("kind") == "evaluation_receipt"
        and edge.get("from_id") == evaluation_id
        and edge.get("to_id") == evaluation_object_id
    ]
    evaluation_receipt_records = [
        row
        for row in records
        if isinstance(row, dict)
        and row.get("kind") == "receipt"
        and row.get("id") == evaluation_object_id
        and row.get("sha256") == evaluation_digest
        and row.get("state") == "accepted"
    ]
    evaluation_record = evaluation_records[0]
    if (
        not evaluation_object_id.startswith("sha256:")
        or re.fullmatch(r"[0-9a-f]{64}", evaluation_digest) is None
        or len(evaluation_object_records) != 1
        or len(evaluation_receipt_edges) != 1
        or len(evaluation_receipt_records) != 1
        or evaluation_record.get("frozen_manifest_sha256") != evaluation_digest
        or evaluation_record.get("test_set_sha256") != evaluation_digest
        or (
            _required_split == "heldout"
            and (
                evaluation_record.get("ngram_ruling") != "not_run"
                or evaluation_record.get("near_dup_ruling") != "not_run"
                or evaluation_record.get("exclusion_reason") is not None
                or evaluation_record.get("overlap_state") != "isolated"
            )
        )
    ):
        raise InputIdentityError(
            "catalog_receipt_drift",
            "catalog evaluation receipt or immutable object binding has drifted",
        )
    dataset_receipt_id = f"sha256:{_sha256_bytes(dataset_import_receipt_raw)}"
    receipt_records = [
        row
        for row in records
        if isinstance(row, dict)
        and row.get("kind") == "receipt"
        and row.get("id") == dataset_receipt_id
        and row.get("sha256") == dataset_receipt_id.removeprefix("sha256:")
        and row.get("state") == "accepted"
    ]
    consumer_receipt_edges = [
        edge
        for edge in edges
        if isinstance(edge, dict)
        and edge.get("kind") == _attempt_receipt_edge_kind
        and edge.get("from_id") == consumer_id
        and edge.get("to_id") == dataset_receipt_id
    ]
    if len(receipt_records) != 1 or len(consumer_receipt_edges) != 1:
        raise InputIdentityError(
            "catalog_receipt_drift",
            "dataset import receipt is not the catalog-derived consumer receipt",
        )
    return {
        "dataset_id": derived_dataset_id,
        "dataset_manifest_sha256": dataset["manifest_sha256"],
        "catalog_export_sha256": catalog_export_sha256,
        "consumer_attempt_id": consumer_id,
        "split": expected_split,
        "source_ids": sorted(
            source_id.removeprefix("source:") for source_id in source_record_ids
        ),
        "object_count": len(object_ids),
        "object_set_sha256": _sha256_bytes(json.dumps(sorted(object_ids), separators=(",", ":")).encode("utf-8")),
        "protected_eval_item_admission": False,
    }


def resolve_catalog_training_datasets(
    *,
    catalog_export_raw: bytes,
    dataset_import_receipt_raw: bytes,
    consumer_import_receipt_raw: bytes,
    expected_dataset_id: str,
    expected_split: str = "train",
) -> dict[str, Any]:
    """Resolve one exact train catalog dataset for certified preflight."""

    return _resolve_catalog_dataset(
        catalog_export_raw=catalog_export_raw,
        dataset_import_receipt_raw=dataset_import_receipt_raw,
        consumer_import_receipt_raw=consumer_import_receipt_raw,
        expected_dataset_id=expected_dataset_id,
        expected_split=expected_split,
        _required_split="train",
        _dataset_edge_kind="consumer_dataset",
        _attempt_record_kind="consumer_attempt",
        _attempt_evaluation_edge_kind="consumer_evaluation",
        _attempt_receipt_edge_kind="consumer_receipt",
    )
