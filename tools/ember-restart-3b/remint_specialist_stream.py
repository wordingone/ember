# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Guarded deterministic remint for the indexed specialist stream's config pin."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from specialist_stream import canonical_record_bytes, emit_stream_manifest, write_stream_build_receipt


MANIFEST_RELATIVE = Path("data/ember-restart-3b/owned-specialist-stream-v1-4096.json")
RECEIPT_RELATIVE = Path("data/ember-restart-3b/owned-specialist-stream-v1-4096-build-receipt.json")
CONFIG_RELATIVE = Path("configs/ember-restart-3b.json")
TOKENIZER_RELATIVE = Path("tokenizer/tokenizer.json")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _load(path: Path) -> tuple[bytes, dict[str, Any]]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"specialist stream artifact is not an object: {path}")
    if raw != canonical_record_bytes(value) + b"\n":
        raise ValueError(f"specialist stream artifact is not canonical JSON: {path}")
    return raw, value


def _assert_manifest_remint(
    original: dict[str, Any], candidate: dict[str, Any], *, current_config_sha256: str,
) -> None:
    if candidate.get("model_config") != {
        "path": CONFIG_RELATIVE.as_posix(), "sha256": current_config_sha256,
    }:
        raise ValueError("specialist stream remint does not bind the current model config")
    original_without_config = dict(original)
    candidate_without_config = dict(candidate)
    original_without_config.pop("model_config", None)
    candidate_without_config.pop("model_config", None)
    if original_without_config != candidate_without_config:
        raise ValueError("specialist stream remint changed a non-config commitment")


def _assert_build_receipt_matches_manifest(
    receipt: dict[str, Any], *, manifest_raw: bytes, manifest: dict[str, Any],
) -> None:
    expected = {
        "schema_version": "ember-owned-specialist-stream-build-receipt-v1",
        "result": "MEASURED",
        "boundary": "STREAM_CONSTRUCTION_NOT_SUFFICIENT_PRETRAINING_OR_CAPABILITY",
        "stream_manifest_sha256": _sha256(manifest_raw),
        "lineage": manifest["lineage"],
        "data_class": manifest["data_class"],
        "corpus_root_sha256": manifest["corpus_root_sha256"],
        "record_count_per_family": manifest["range"]["record_count_per_family"],
        "families": {
            capability: {
                "records": family["record_count"],
                "tokens": family["token_count"],
                "serialized_bytes_not_materialized": family["serialized_bytes"],
            }
            for capability, family in manifest["families"].items()
        },
    }
    actual = dict(receipt)
    elapsed = actual.pop("elapsed_ms", None)
    if type(elapsed) is not int or elapsed < 0 or actual != expected:
        raise ValueError("specialist stream build receipt does not bind the reminted manifest")


def _candidate(repo_root: Path, output_root: Path) -> tuple[Path, Path, dict[str, Any], dict[str, Any]]:
    manifest_path = output_root / MANIFEST_RELATIVE.name
    receipt_path = output_root / RECEIPT_RELATIVE.name
    manifest, elapsed_ms = emit_stream_manifest(
        repo_root=repo_root, output_path=manifest_path,
        tokenizer_path=repo_root / TOKENIZER_RELATIVE,
        model_config_path=repo_root / CONFIG_RELATIVE,
        record_count=4096, chunk_size=256, data_class="SEMANTIC_PRETRAINING",
    )
    receipt = write_stream_build_receipt(
        manifest_path=manifest_path, output_path=receipt_path, elapsed_ms=elapsed_ms,
    )
    return manifest_path, receipt_path, manifest, receipt


def remint_checked_in_stream(repo_root: Path, *, write: bool) -> dict[str, object]:
    repo_root = repo_root.resolve(strict=True)
    manifest_path = repo_root / MANIFEST_RELATIVE
    receipt_path = repo_root / RECEIPT_RELATIVE
    original_manifest_raw, original_manifest = _load(manifest_path)
    _original_receipt_raw, original_receipt = _load(receipt_path)
    current_config_sha256 = _sha256((repo_root / CONFIG_RELATIVE).read_bytes())
    with tempfile.TemporaryDirectory(dir=manifest_path.parent, prefix=".specialist-remint-") as directory:
        candidate_manifest_path, candidate_receipt_path, candidate_manifest, candidate_receipt = _candidate(repo_root, Path(directory))
        candidate_manifest_raw = candidate_manifest_path.read_bytes()
        candidate_receipt_raw = candidate_receipt_path.read_bytes()
        _assert_manifest_remint(original_manifest, candidate_manifest, current_config_sha256=current_config_sha256)
        _assert_build_receipt_matches_manifest(candidate_receipt, manifest_raw=candidate_manifest_raw, manifest=candidate_manifest)
        current = original_manifest_raw == candidate_manifest_raw
        if current:
            _assert_build_receipt_matches_manifest(original_receipt, manifest_raw=original_manifest_raw, manifest=original_manifest)
        if write and not current:
            os.replace(candidate_manifest_path, manifest_path)
            os.replace(candidate_receipt_path, receipt_path)
        checked_receipt_raw = receipt_path.read_bytes() if current else candidate_receipt_raw
        return {
            "result": "CURRENT" if current else "REMINTED" if write else "STALE",
            "write": write,
            "manifest_sha256": _sha256(candidate_manifest_raw),
            "build_receipt_sha256": _sha256(checked_receipt_raw),
            "model_config_sha256": current_config_sha256,
            "corpus_root_sha256": candidate_manifest["corpus_root_sha256"],
            "boundary": candidate_receipt["boundary"],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--write", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    result = remint_checked_in_stream(args.repo_root, write=args.write)
    print(json.dumps(result, sort_keys=True))
    return 1 if args.check and result["result"] == "STALE" else 0


if __name__ == "__main__":
    raise SystemExit(main())
