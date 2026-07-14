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
    domains = payload.get("domains")
    if not isinstance(domains, list):
        raise ValueError("domain training manifest must bind all four specialists")
    experts = [entry.get("expert") for entry in domains if isinstance(entry, dict)]
    if len(domains) != 4 or len(experts) != 4 or set(experts) != {"vision", "audio", "reasoning", "tool"}:
        raise ValueError("domain training manifest must bind all four specialists exactly once")
    for domain in domains:
        if not isinstance(domain, dict):
            raise ValueError("domain training manifest must bind all four specialists exactly once")
        shard = domain.get("shard_path")
        shard_sha256 = domain.get("shard_sha256")
        source_receipt = domain.get("source_receipt_path")
        source_receipt_sha256 = domain.get("source_receipt_sha256")
        hashes = (shard_sha256, source_receipt_sha256)
        if (
            not isinstance(shard, str)
            or not isinstance(source_receipt, str)
            or any(not isinstance(value, str) or len(value) != 64 or any(character not in "0123456789abcdef" for character in value) for value in hashes)
        ):
            raise ValueError("each specialist must bind a content-addressed shard and source receipt")
        root = repo_root.resolve()
        for relative, expected_sha256, label in ((shard, shard_sha256, "shard"), (source_receipt, source_receipt_sha256, "source receipt")):
            candidate = (root / relative).resolve()
            try:
                candidate.relative_to(root)
            except ValueError as error:
                raise ValueError(f"domain {label} path escapes the repository root") from error
            if not candidate.is_file() or _sha256(candidate) != expected_sha256:
                raise ValueError(f"domain {label} bytes do not match the content-addressed binding")
        try:
            source_payload = json.loads((root / source_receipt).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("domain source receipt must be readable JSON") from error
        provenance = source_payload.get("provenance") if isinstance(source_payload, dict) else None
        if source_payload.get("schema_version") != "ember-owned-domain-source-receipt-v1" or source_payload.get("result") != "VERIFIED" or not isinstance(provenance, dict):
            raise ValueError("domain source receipt is not a verified provenance record")
        for field, message in (("generated_labels", "generated labels"), ("borrowed_model_outputs", "borrowed model outputs"), ("teacher_outputs", "teacher outputs"), ("model_derived_data", "model-derived data")):
            if provenance.get(field) is not False:
                raise ValueError(f"domain source receipt permits forbidden {message}")
    return payload
