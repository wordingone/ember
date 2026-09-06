# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Content-addressed admission boundary for genuine specialist-domain training."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
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


def _connector_media_type(path: PurePosixPath) -> str:
    name = path.name.lower()
    if name in {".gitattributes", ".gitignore", "license", "makefile"}:
        return "text/plain; charset=utf-8"
    if not path.suffix:
        return "application/octet-stream"
    if name.endswith(".jsonl.zst"):
        return "application/x-ndjson+zstd"
    if name.endswith(".json.gz"):
        return "application/json+gzip"
    media_types = {
        ".json": "application/json",
        ".jsonl": "application/x-ndjson",
        ".bat": "text/x-msdos-batch; charset=utf-8",
        ".code": "text/plain; charset=utf-8",
        ".cpp": "text/x-c++src; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".cu": "text/x-cuda; charset=utf-8",
        ".flac": "audio/flac",
        ".h": "text/x-c++hdr; charset=utf-8",
        ".ico": "image/x-icon",
        ".jpg": "image/jpeg",
        ".md": "text/markdown; charset=utf-8",
        ".odg": "application/vnd.oasis.opendocument.graphics",
        ".out": "application/octet-stream",
        ".parquet": "application/vnd.apache.parquet",
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".py": "text/x-python; charset=utf-8",
        ".rst": "text/x-rst; charset=utf-8",
        ".sh": "application/x-sh; charset=utf-8",
        ".sqlite": "application/vnd.sqlite3",
        ".swp": "application/x-vim-swap",
        ".txt": "text/plain; charset=utf-8",
        ".yml": "application/yaml; charset=utf-8",
    }
    media_type = media_types.get(path.suffix.lower())
    if media_type is None:
        raise ValueError(
            f"bulk domain connector file has unsupported media type: {path.as_posix()}"
        )
    return media_type


def load_bulk_domain_connector_receipt(
    *,
    receipt_path: Path,
    expected_receipt_sha256: str,
    source_id: str,
    expected_source_selector: str,
    expected_license_text_sha256: str,
    domain: str,
    split: str,
) -> dict[str, Any]:
    """Project one immutable bulk connector receipt without durable host paths."""

    if not _is_sha256(expected_receipt_sha256) or _sha256(receipt_path) != expected_receipt_sha256:
        raise ValueError("bulk domain connector receipt bytes do not match the frozen identity")
    try:
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("bulk domain connector receipt must be readable JSON") from error
    if not isinstance(payload, dict) or payload.get("schema") != "corpus-connector-receipt-v1":
        raise ValueError("bulk domain connector receipt schema is not admitted")
    if not isinstance(source_id, str) or not source_id or not isinstance(domain, str) or not domain:
        raise ValueError("bulk domain catalog source and domain identities are required")
    if split not in {"train", "heldout"}:
        raise ValueError("bulk domain split must be train or heldout")
    canonical_url = payload.get("canonical_url")
    license_text = payload.get("license")
    fetched_at = payload.get("fetched_at")
    source_selector = payload.get("source_id")
    dest_root = payload.get("dest_root")
    manifest_sha256 = payload.get("sha256_manifest")
    files = payload.get("files")
    if (
        not isinstance(canonical_url, str)
        or not canonical_url.startswith("https://")
        or not isinstance(license_text, str)
        or not license_text
        or not isinstance(fetched_at, str)
        or not fetched_at
        or not isinstance(source_selector, str)
        or not source_selector
        or not isinstance(dest_root, str)
        or not dest_root
        or not _is_sha256(manifest_sha256)
        or not isinstance(files, list)
        or not files
    ):
        raise ValueError("bulk domain connector authority is incomplete")
    if (
        not _is_sha256(expected_license_text_sha256)
        or hashlib.sha256(license_text.encode("utf-8")).hexdigest()
        != expected_license_text_sha256
    ):
        raise ValueError("bulk domain connector license does not match the frozen authority")
    if source_selector != expected_source_selector:
        raise ValueError("bulk domain connector source selector does not match the frozen authority")
    if f"-{split}-" not in source_id:
        raise ValueError("bulk domain source identity split does not match the declared split")
    custody_root = Path(dest_root)
    if not custody_root.is_absolute() or not custody_root.is_dir():
        raise ValueError("bulk domain connector custody root is unavailable")
    custody_root = custody_root.resolve()
    normalized_files: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    total_bytes = 0
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {"path", "bytes", "sha256"}:
            raise ValueError("bulk domain connector file row has a closed-schema violation")
        relative = entry.get("path")
        byte_count = entry.get("bytes")
        digest = entry.get("sha256")
        if not isinstance(relative, str) or not relative:
            raise ValueError("bulk domain connector file path is missing")
        normalized = PurePosixPath(relative.replace("\\", "/"))
        if (
            normalized.is_absolute()
            or ".." in normalized.parts
            or any(":" in part for part in normalized.parts)
            or normalized.as_posix() in seen_paths
        ):
            raise ValueError("bulk domain connector file path is unsafe or duplicated")
        if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count <= 0 or not _is_sha256(digest):
            raise ValueError("bulk domain connector file identity is malformed")
        seen_paths.add(normalized.as_posix())
        total_bytes += byte_count
        physical = (custody_root / Path(*normalized.parts)).resolve()
        try:
            physical.relative_to(custody_root)
        except ValueError as error:
            raise ValueError("bulk domain connector physical file escapes custody") from error
        if (
            not physical.is_file()
            or physical.stat().st_size != byte_count
            or _sha256(physical) != digest
        ):
            raise ValueError("bulk domain connector physical file identity has drifted")
        media_type = _connector_media_type(normalized)
        normalized_files.append({
            "path": normalized.as_posix(),
            "bytes": byte_count,
            "sha256": digest,
            "media_type": media_type,
        })
    if payload.get("total_bytes") != total_bytes:
        raise ValueError("bulk domain connector byte total does not match its files")
    derived_manifest_sha256 = hashlib.sha256(
        "\n".join(sorted(row["sha256"] for row in normalized_files)).encode("utf-8")
    ).hexdigest()
    if manifest_sha256 != derived_manifest_sha256:
        raise ValueError("bulk domain connector manifest hash is not derived from its file rows")
    normalized_files.sort(key=lambda row: (row["path"], row["sha256"]))
    return {
        "source_id": source_id,
        "source_selector": source_selector,
        "domain": domain,
        "split": split,
        "canonical_url": canonical_url,
        "license": license_text,
        "license_text_sha256": hashlib.sha256(license_text.encode("utf-8")).hexdigest(),
        "fetched_at": fetched_at,
        "manifest_sha256": manifest_sha256,
        "receipt_sha256": expected_receipt_sha256,
        "total_bytes": total_bytes,
        "files": normalized_files,
    }


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
