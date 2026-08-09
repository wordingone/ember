# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Content-addressed admission boundary for genuine specialist-domain training."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

RETIRED_BOOTSTRAP_ARTIFACT = "owned-clean-curriculum-128-v1"
RETIRED_BOOTSTRAP_SHARD = "data/ember-restart-3b/owned-curriculum-128.json"
DOMAIN_MANIFEST_SCHEMA = "ember-owned-domain-training-manifest-v1"
_MANIFEST_FIELDS = frozenset({"schema_version", "artifact_id", "shard_path", "domains"})
_DOMAIN_FIELDS = frozenset({"expert", "shard_path", "shard_sha256", "source_receipt_path", "source_receipt_sha256"})
_SOURCE_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "result",
        "expert",
        "shard_sha256",
        "goal_id",
        "invariant_sha256",
        "source_url",
        "sha256",
        "bytes",
        "license",
        "human_provenance_basis",
        "fetched_ts",
        "sha_convention",
        "selection_rule",
        "provenance",
        "ticket",
        "ts",
        "workstream_id",
        "next_executed_outcome",
    }
)


def _require_closed_fields(value: object, expected: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{label} has unknown or missing fields")
    return value


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_domain_training_manifest(*, manifest_path: Path, repo_root: Path) -> dict[str, Any]:
    """Load only a non-bootstrap declaration for subsequent specialist-data checks."""

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("domain training manifest must be readable JSON") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != DOMAIN_MANIFEST_SCHEMA:
        raise ValueError("domain training manifest schema is not admitted")
    artifact_id = payload.get("artifact_id")
    shard_path = payload.get("shard_path")
    if not isinstance(artifact_id, str) or not isinstance(shard_path, str):
        raise ValueError("domain training manifest must identify one concrete artifact and shard")
    if artifact_id == RETIRED_BOOTSTRAP_ARTIFACT or shard_path == RETIRED_BOOTSTRAP_SHARD:
        raise ValueError("retired bootstrap curriculum cannot be admitted as genuine specialist-domain training")
    if set(payload) != _MANIFEST_FIELDS:
        raise ValueError("domain training manifest schema is not admitted")
    domains = payload.get("domains")
    if not isinstance(domains, list):
        raise ValueError("domain training manifest must bind all four specialists")
    experts = [entry.get("expert") for entry in domains if isinstance(entry, dict)]
    if len(domains) != 4 or len(experts) != 4 or set(experts) != {"vision", "audio", "reasoning", "tool"}:
        raise ValueError("domain training manifest must bind all four specialists exactly once")
    for domain in domains:
        if isinstance(domain, dict) and "expert" in domain and not _DOMAIN_FIELDS.issubset(domain):
            raise ValueError("each specialist must bind a content-addressed shard and source receipt")
        if not isinstance(domain, dict) or not _DOMAIN_FIELDS.issubset(domain):
            raise ValueError("domain training manifest must bind all four specialists exactly once")
        domain = _require_closed_fields(domain, _DOMAIN_FIELDS, "domain training manifest entry")
        shard = domain.get("shard_path")
        shard_sha256 = domain.get("shard_sha256")
        source_receipt = domain.get("source_receipt_path")
        source_receipt_sha256 = domain.get("source_receipt_sha256")
        hashes = (shard_sha256, source_receipt_sha256)
        if (
            not isinstance(shard, str)
            or not isinstance(source_receipt, str)
            or any(not _is_sha256(value) for value in hashes)
        ):
            raise ValueError("each specialist must bind a content-addressed shard and source receipt")
        root = repo_root.resolve()
        for relative, expected_sha256, label in ((shard, shard_sha256, "shard"), (source_receipt, source_receipt_sha256, "source receipt")):
            candidate = (root / relative).resolve()
            try:
                candidate.relative_to(root)
            except ValueError as error:
                raise ValueError(f"domain {label} path escapes the repository root") from error
            if candidate.is_symlink() or not candidate.is_file() or _sha256(candidate) != expected_sha256:
                raise ValueError(f"domain {label} bytes do not match the content-addressed binding")
        try:
            source_payload = json.loads((root / source_receipt).resolve().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("domain source receipt must be readable JSON") from error
        source_payload = _require_closed_fields(source_payload, _SOURCE_RECEIPT_FIELDS, "domain source receipt")
        provenance = source_payload.get("provenance")
        if source_payload.get("schema_version") != "ember-owned-domain-source-receipt-v1" or source_payload.get("result") != "VERIFIED" or not isinstance(provenance, dict):
            raise ValueError("domain source receipt is not a verified provenance record")
        if (
            set(provenance) != {"generated_labels", "borrowed_model_outputs", "teacher_outputs", "model_derived_data"}
            or source_payload.get("expert") != domain["expert"]
            or source_payload.get("shard_sha256") != shard_sha256
            or source_payload.get("sha256") != shard_sha256
            or source_payload.get("goal_id") != "EMBER-02"
            or not _is_sha256(source_payload.get("invariant_sha256"))
            or not isinstance(source_payload.get("source_url"), str)
            or not source_payload["source_url"]
            or not isinstance(source_payload.get("license"), str)
            or not source_payload["license"]
            or not isinstance(source_payload.get("human_provenance_basis"), str)
            or not source_payload["human_provenance_basis"]
            or not isinstance(source_payload.get("fetched_ts"), str)
            or not source_payload["fetched_ts"]
            or not isinstance(source_payload.get("sha_convention"), str)
            or not source_payload["sha_convention"]
            or not isinstance(source_payload.get("selection_rule"), str)
            or not source_payload["selection_rule"]
            or not isinstance(source_payload.get("ticket"), str)
            or not source_payload["ticket"]
            or not isinstance(source_payload.get("ts"), str)
            or not source_payload["ts"]
            or source_payload.get("workstream_id") != "EMBER-02B"
            or source_payload.get("next_executed_outcome") != "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
            or isinstance(source_payload.get("bytes"), bool)
            or not isinstance(source_payload.get("bytes"), int)
            or source_payload["bytes"] != (root / shard).resolve().stat().st_size
        ):
            raise ValueError("domain source receipt does not bind this exact specialist and shard")
        for field, message in (("generated_labels", "generated labels"), ("borrowed_model_outputs", "borrowed model outputs"), ("teacher_outputs", "teacher outputs"), ("model_derived_data", "model-derived data")):
            if provenance.get(field) is not False:
                raise ValueError(f"domain source receipt permits forbidden {message}")
    return payload
