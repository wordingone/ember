# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Guarded deterministic remint for the indexed specialist stream's config pin."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

_REMINT_MODULE_DIRECTORY = Path(__file__).resolve().parent
if str(_REMINT_MODULE_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(_REMINT_MODULE_DIRECTORY))
# issue2015 exact-local-import:tools/ember-restart-3b/repository_layout.py
import importlib.util as _ember_93a28f5fd2fd0068_importlib
import sys as _ember_93a28f5fd2fd0068_sys
from pathlib import Path as _ember_93a28f5fd2fd0068_Path
_ember_93a28f5fd2fd0068_path = _ember_93a28f5fd2fd0068_Path(__file__).resolve().parents[5].joinpath('tools', 'ember-restart-3b', 'repository_layout.py')
if not _ember_93a28f5fd2fd0068_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:tools/ember-restart-3b/repository_layout.py')
_ember_93a28f5fd2fd0068_aliases = ('_ember_issue2015_93a28f5fd2fd0068', 'repository_layout', 'tools.ember-restart-3b.repository_layout')
_ember_93a28f5fd2fd0068_existing = []
for _ember_93a28f5fd2fd0068_alias in _ember_93a28f5fd2fd0068_aliases:
    _ember_93a28f5fd2fd0068_candidate = _ember_93a28f5fd2fd0068_sys.modules.get(_ember_93a28f5fd2fd0068_alias)
    if _ember_93a28f5fd2fd0068_candidate is not None and all(_ember_93a28f5fd2fd0068_candidate is not item for item in _ember_93a28f5fd2fd0068_existing):
        _ember_93a28f5fd2fd0068_existing.append(_ember_93a28f5fd2fd0068_candidate)
if len(_ember_93a28f5fd2fd0068_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:tools/ember-restart-3b/repository_layout.py')
if _ember_93a28f5fd2fd0068_existing:
    _ember_93a28f5fd2fd0068_module = _ember_93a28f5fd2fd0068_existing[0]
    _ember_93a28f5fd2fd0068_observed = getattr(_ember_93a28f5fd2fd0068_module, '__file__', None)
    if _ember_93a28f5fd2fd0068_observed is None or _ember_93a28f5fd2fd0068_Path(_ember_93a28f5fd2fd0068_observed).resolve() != _ember_93a28f5fd2fd0068_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:tools/ember-restart-3b/repository_layout.py')
else:
    _ember_93a28f5fd2fd0068_spec = _ember_93a28f5fd2fd0068_importlib.spec_from_file_location('_ember_issue2015_93a28f5fd2fd0068', _ember_93a28f5fd2fd0068_path)
    if _ember_93a28f5fd2fd0068_spec is None or _ember_93a28f5fd2fd0068_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:tools/ember-restart-3b/repository_layout.py')
    _ember_93a28f5fd2fd0068_module = _ember_93a28f5fd2fd0068_importlib.module_from_spec(_ember_93a28f5fd2fd0068_spec)
    for _ember_93a28f5fd2fd0068_alias in _ember_93a28f5fd2fd0068_aliases:
        _ember_93a28f5fd2fd0068_prior = _ember_93a28f5fd2fd0068_sys.modules.get(_ember_93a28f5fd2fd0068_alias)
        if _ember_93a28f5fd2fd0068_prior is not None and _ember_93a28f5fd2fd0068_prior is not _ember_93a28f5fd2fd0068_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:tools/ember-restart-3b/repository_layout.py')
        _ember_93a28f5fd2fd0068_sys.modules[_ember_93a28f5fd2fd0068_alias] = _ember_93a28f5fd2fd0068_module
    try:
        _ember_93a28f5fd2fd0068_spec.loader.exec_module(_ember_93a28f5fd2fd0068_module)
    except BaseException:
        for _ember_93a28f5fd2fd0068_alias in _ember_93a28f5fd2fd0068_aliases:
            if _ember_93a28f5fd2fd0068_sys.modules.get(_ember_93a28f5fd2fd0068_alias) is _ember_93a28f5fd2fd0068_module:
                _ember_93a28f5fd2fd0068_sys.modules.pop(_ember_93a28f5fd2fd0068_alias, None)
        raise
for _ember_93a28f5fd2fd0068_alias in _ember_93a28f5fd2fd0068_aliases:
    _ember_93a28f5fd2fd0068_prior = _ember_93a28f5fd2fd0068_sys.modules.get(_ember_93a28f5fd2fd0068_alias)
    if _ember_93a28f5fd2fd0068_prior is not None and _ember_93a28f5fd2fd0068_prior is not _ember_93a28f5fd2fd0068_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:tools/ember-restart-3b/repository_layout.py')
    _ember_93a28f5fd2fd0068_sys.modules[_ember_93a28f5fd2fd0068_alias] = _ember_93a28f5fd2fd0068_module
allowed_authority_pin_tuples = getattr(_ember_93a28f5fd2fd0068_module, 'allowed_authority_pin_tuples')
resolve_repository_authority = getattr(_ember_93a28f5fd2fd0068_module, 'resolve_repository_authority')
# issue2015 exact-local-import-end:tools/ember-restart-3b/repository_layout.py
from specialist_stream import canonical_record_bytes, emit_stream_manifest, write_stream_build_receipt


CONFIG_RELATIVE = Path("configs/ember-restart-3b.json")


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


def _candidate(
    repo_root: Path, output_root: Path, *,
    manifest_name: str, receipt_name: str, tokenizer_path: Path,
) -> tuple[Path, Path, dict[str, Any], dict[str, Any]]:
    manifest_path = output_root / manifest_name
    receipt_path = output_root / receipt_name
    manifest, elapsed_ms = emit_stream_manifest(
        repo_root=repo_root, output_path=manifest_path,
        tokenizer_path=tokenizer_path,
        model_config_path=repo_root / CONFIG_RELATIVE,
        record_count=4096, chunk_size=256, data_class="SEMANTIC_PRETRAINING",
    )
    receipt = write_stream_build_receipt(
        manifest_path=manifest_path, output_path=receipt_path, elapsed_ms=elapsed_ms,
    )
    return manifest_path, receipt_path, manifest, receipt


def remint_checked_in_stream(repo_root: Path, *, write: bool) -> dict[str, object]:
    repo_root = repo_root.resolve(strict=True)
    manifest_authority = resolve_repository_authority(repo_root, "specialist_stream_manifest")
    receipt_authority = resolve_repository_authority(repo_root, "specialist_stream_build_receipt")
    # Layout-seam caveat: a future legitimate remint that changes these
    # artifacts' bytes must update the corresponding repository_layout
    # authority pins in the SAME governed change, or this atomic-tuple
    # gate (and the per-authority hash pins) will refuse the new bytes.
    resolved_pins = (
        manifest_authority.expected_sha256,
        receipt_authority.expected_sha256,
    )
    if resolved_pins not in allowed_authority_pin_tuples(
        ("specialist_stream_manifest", "specialist_stream_build_receipt")
    ):
        raise ValueError(
            "specialist stream authorities resolved to a mixed generation: "
            f"{resolved_pins}; remint refuses a half-expanded tree"
        )
    tokenizer_authority = resolve_repository_authority(repo_root, "tokenizer")
    manifest_path = manifest_authority.path
    receipt_path = receipt_authority.path
    original_manifest_raw, original_manifest = _load(manifest_path)
    _original_receipt_raw, original_receipt = _load(receipt_path)
    current_config_sha256 = _sha256((repo_root / CONFIG_RELATIVE).read_bytes())
    with tempfile.TemporaryDirectory(dir=manifest_path.parent, prefix=".specialist-remint-") as directory:
        candidate_manifest_path, candidate_receipt_path, candidate_manifest, candidate_receipt = _candidate(
            repo_root, Path(directory),
            manifest_name=manifest_authority.path.name,
            receipt_name=receipt_authority.path.name,
            tokenizer_path=tokenizer_authority.path,
        )
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
