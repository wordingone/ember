#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed verifier for the bounded inherited lifecycle drawdown manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping


SHA1 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ManifestError(ValueError):
    """The manifest cannot authorize a safe retirement decision."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha(value: Any, pattern: re.Pattern[str], field: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ManifestError(f"{field} must be a lowercase content hash")
    return value


def _require_ref(value: Any) -> str:
    if not isinstance(value, str) or not value.startswith("refs/heads/") or any(token in value for token in ("..", "\\", "\r", "\n", " ")):
        raise ManifestError("candidate ref is not a safe full head ref")
    return value


def _verify_candidate(row: Mapping[str, Any]) -> None:
    ref = _require_ref(row.get("ref"))
    head = _sha(row.get("head_sha"), SHA1, f"{ref}.head_sha")
    reconstruction = row.get("reconstruction")
    if not isinstance(reconstruction, Mapping) or not isinstance(reconstruction.get("command"), str) or not reconstruction["command"].strip():
        raise ManifestError(f"{ref} has no reconstruction command")
    if reconstruction.get("expected_sha") != head:
        raise ManifestError(f"{ref} reconstruction SHA does not bind head")
    compare = row.get("master_compare")
    if not isinstance(compare, Mapping) or not isinstance(compare.get("status"), str):
        raise ManifestError(f"{ref} has malformed master comparison")
    if row.get("protection") not in (True, False):
        raise ManifestError(f"{ref} protection must be explicit")
    if not isinstance(row.get("open_head_prs"), list):
        raise ManifestError(f"{ref} open_head_prs must be a list")

    verdict = row.get("verdict")
    if isinstance(verdict, str) and verdict.startswith("KEEP_"):
        return
    if verdict != "DELETE_VERIFIED":
        raise ManifestError(f"{ref} has an unknown or unsafe verdict")

    if row["protection"] is not False or row["open_head_prs"]:
        raise ManifestError(f"{ref} deletion is not unprotected and head-PR-free")
    equivalence = row.get("path_diff_blob_equivalence")
    if not isinstance(equivalence, Mapping) or equivalence.get("status") != "PROVEN_EXACT":
        raise ManifestError(f"{ref} deletion lacks exact path/blob equivalence")
    paths = equivalence.get("paths")
    blobs = equivalence.get("terminal_blobs")
    if not isinstance(paths, list) or not paths or not all(isinstance(path, str) and path for path in paths):
        raise ManifestError(f"{ref} deletion lacks a nonempty exact path set")
    if not isinstance(blobs, Mapping) or set(blobs) != set(paths):
        raise ManifestError(f"{ref} deletion lacks one terminal blob per exact path")
    for path, blob in blobs.items():
        _sha(blob, SHA1, f"{ref}.terminal_blobs[{path}]")


def verify_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ManifestError("manifest must be an object")
    canonical = dict(payload)
    recorded = canonical.pop("manifest_sha256", None)
    _sha(recorded, SHA256, "manifest_sha256")
    if hashlib.sha256(_canonical_json(canonical)).hexdigest() != recorded:
        raise ManifestError("manifest_sha256 does not match canonical bytes")
    if payload.get("schema_version") != "ember-inherited-drawdown-v2":
        raise ManifestError("unexpected lifecycle manifest schema")
    if payload.get("deletion_authority") not in {"NOT_GRANTED", "GRANTED_EXACT_ROWS"}:
        raise ManifestError("deletion_authority is not explicit")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        raise ManifestError("candidates must be a list")
    if payload.get("candidate_count") != len(candidates):
        raise ManifestError("candidate_count does not match candidates")
    for row in candidates:
        if not isinstance(row, Mapping):
            raise ManifestError("candidate row must be an object")
        _verify_candidate(row)
    return dict(payload)


def verified_delete_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return only rows with exact proof; uncertain/unique rows never authorize deletion."""
    verified = verify_manifest(payload)["candidates"]
    return [dict(row) for row in verified if row.get("verdict") == "DELETE_VERIFIED"]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = json.loads(args.manifest.read_text(encoding="utf-8"))
        rows = verified_delete_rows(payload)
    except (OSError, json.JSONDecodeError, ManifestError) as exc:
        print(f"ManifestError: {exc}")
        return 2
    print(json.dumps({"status": "PASS", "verified_delete_count": len(rows)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
