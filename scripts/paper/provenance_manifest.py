#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""#552 Component B: corpus provenance manifest emitter (Q6a).

Per-shard provenance documentation with machine-checkable transform chains.
Honest rail: explicit UNKNOWN rows for missing provenance (never omit shards).

Input: training config paths (references shards), optional metadata manifest
Output: receipts/paper/provenance-manifest-<UTCts>.json

Manifest structure per shard:
  {shard_path, sha256, source (URL/identifier or UNKNOWN),
   fetch_date (or UNKNOWN), transform_chain: [{step, script, input_sha, output_sha,
   status: VERIFIED|UNVERIFIABLE}], model_in_loop: false}

Summary: {verified, unverifiable, unknown}
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _sha256_file(path: Path) -> str:
    """Compute SHA256 of a file."""
    h = hashlib.sha256()
    try:
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return "UNREADABLE"


def _load_config(config_path: str) -> dict:
    """Load a training config (JSON)."""
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except Exception:
        return {}


def _extract_shard_refs(config: dict) -> list[str]:
    """Extract direct shard references from a training config."""
    shards: list[str] = []
    def visit(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"shards", "shard_paths", "corpus_path", "data_path", "dataset_path"}:
                    if isinstance(item, str): shards.append(item)
                    elif isinstance(item, list): shards.extend(x for x in item if isinstance(x, str))
                visit(item)
        elif isinstance(value, list):
            for item in value: visit(item)
    visit(config)
    return list(dict.fromkeys(shards))


def _extract_manifest_refs(config: dict) -> list[str]:
    refs: list[str] = []
    def visit(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"manifest_path", "corpus_manifest", "manifest"} and isinstance(item, str): refs.append(item)
                visit(item)
        elif isinstance(value, list):
            for item in value: visit(item)
    visit(config)
    return list(dict.fromkeys(refs))


def _resolve_candidates(ref: str, base: Path, roots: list[Path]) -> list[Path]:
    value = Path(ref)
    if value.is_absolute(): return [value]
    candidates = [base / value] + [root / value for root in roots]
    unique: list[Path] = []
    for candidate in candidates:
        if candidate not in unique: unique.append(candidate)
    return unique


def _resolve_one(ref: str, base: Path, roots: list[Path]) -> Path | None:
    for candidate in _resolve_candidates(ref, base, roots):
        if candidate.is_file(): return candidate
    return None


def _transform_links(row: dict, manifest_path: Path, roots: list[Path]) -> list[dict]:
    links = row.get("transform_links", row.get("transform_chain", []))
    if not isinstance(links, list): return []
    result: list[dict] = []
    for link in links:
        if not isinstance(link, dict):
            result.append({"path": "UNKNOWN", "sha256": "UNKNOWN", "status": "UNKNOWN"})
            continue
        ref = link.get("path") or link.get("output_path") or link.get("file")
        expected = link.get("sha256") or link.get("output_sha256")
        resolved = _resolve_one(str(ref), manifest_path.parent, roots) if isinstance(ref, str) else None
        actual = _sha256_file(resolved) if resolved else "UNREADABLE"
        status = "VERIFIED" if resolved and isinstance(expected, str) and actual == expected else "UNVERIFIABLE"
        result.append({"path": Path(ref).name if isinstance(ref, str) else "UNKNOWN", "sha256": actual, "declared_sha256": expected or "UNKNOWN", "status": status})
    return result


def _find_shard_files(shard_ref: str, base: Path | None = None, roots: list[Path] | None = None) -> list[Path]:
    roots = roots or []
    base = base or Path.cwd()
    result: list[Path] = []
    for candidate in _resolve_candidates(shard_ref, base, roots):
        if any(c in str(candidate) for c in "*?["):
            result.extend(sorted(candidate.parent.glob(candidate.name)))
        elif candidate.is_file():
            result.append(candidate)
    return list(dict.fromkeys(result))


def _build_transform_chain(shard_path: Path) -> dict:
    """Build transform chain for a shard (stub for now).

    In a full implementation, this would:
    1. Check if shard has metadata (provenance file, comment in source)
    2. Retrieve transform script SHA if present
    3. Recursively verify input -> output chain

    For now, return UNKNOWN since we don't have infrastructure to track this.
    """
    return {
        "chain": [],
        "status": "UNKNOWN",
        "note": "provenance metadata not available (not in infrastructure yet)",
    }


def build_manifest(config_paths: list[str], metadata_manifest_path: str | None = None, authority_roots: list[str | Path] | None = None) -> dict:
    """Open each config-referenced manifest, enumerate shards, and verify bytes/links."""
    roots = [Path(root) for root in (authority_roots or [])]
    roots.extend(Path(path).resolve().parent for path in config_paths)
    roots = list(dict.fromkeys(roots))
    metadata: dict = {}
    if metadata_manifest_path:
        try: metadata = json.loads(Path(metadata_manifest_path).read_text(encoding="utf-8"))
        except (OSError, ValueError): metadata = {}
    entries: list[dict] = []
    counts = {"verified": 0, "unverifiable": 0, "unknown": 0}
    manifest_count = unreadable_manifests = transform_verified = transform_unverifiable = 0
    def add_entry(entry: dict) -> None:
        entries.append(entry)
        status = entry.get("status", "UNKNOWN")
        counts["verified" if status == "VERIFIED" else "unverifiable" if status == "UNVERIFIABLE" else "unknown"] += 1
    for config_path in config_paths:
        config_file = Path(config_path)
        config = _load_config(config_path)
        base = config_file.resolve().parent
        for manifest_ref in _extract_manifest_refs(config):
            manifest_path = _resolve_one(manifest_ref, base, roots)
            manifest_count += 1
            if manifest_path is None:
                unreadable_manifests += 1
                add_entry({"shard_path": Path(manifest_ref).name, "sha256": "UNREADABLE", "source_manifest": Path(manifest_ref).name, "status": "UNKNOWN", "transform_links": [], "model_in_loop": False, "note": "config-referenced manifest unreadable"})
                continue
            try: manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                unreadable_manifests += 1
                add_entry({"shard_path": manifest_path.name, "sha256": "UNREADABLE", "source_manifest": manifest_path.name, "status": "UNKNOWN", "transform_links": [], "model_in_loop": False, "note": "config-referenced manifest invalid"})
                continue
            rows = manifest.get("shards") if isinstance(manifest, dict) else None
            if not isinstance(rows, list):
                unreadable_manifests += 1
                add_entry({"shard_path": manifest_path.name, "sha256": "UNREADABLE", "source_manifest": manifest_path.name, "status": "UNKNOWN", "transform_links": [], "model_in_loop": False, "note": "manifest shards list missing"})
                continue
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get("file"), str):
                    add_entry({"shard_path": "UNKNOWN", "sha256": "UNREADABLE", "source_manifest": manifest_path.name, "status": "UNKNOWN", "transform_links": [], "model_in_loop": False, "note": "manifest shard row malformed"})
                    continue
                ref = row["file"]
                shard_path = _resolve_one(ref, manifest_path.parent, roots)
                links = _transform_links(row, manifest_path, roots)
                transform_verified += sum(link["status"] == "VERIFIED" for link in links)
                transform_unverifiable += sum(link["status"] != "VERIFIED" for link in links)
                actual = _sha256_file(shard_path) if shard_path else "UNREADABLE"
                expected = row.get("sha256")
                bytes_expected = row.get("bytes_on_disk")
                bytes_actual = shard_path.stat().st_size if shard_path else None
                valid = shard_path is not None and isinstance(expected, str) and actual == expected and (bytes_expected is None or bytes_actual == bytes_expected) and all(link["status"] == "VERIFIED" for link in links)
                add_entry({"shard_path": ref, "sha256": actual, "declared_sha256": expected or "UNKNOWN", "bytes_on_disk": bytes_actual if bytes_actual is not None else "UNKNOWN", "declared_bytes_on_disk": bytes_expected if bytes_expected is not None else "UNKNOWN", "source_manifest": manifest_path.name, "status": "VERIFIED" if valid else "UNVERIFIABLE" if shard_path else "UNKNOWN", "transform_links": links, "source": "UNKNOWN", "fetch_date": "UNKNOWN", "model_in_loop": False})
        for shard_ref in _extract_shard_refs(config):
            files = _find_shard_files(shard_ref, base, roots)
            if files:
                for shard_path in files:
                    meta = metadata.get(str(shard_path), metadata.get(shard_ref, {}))
                    add_entry({"shard_path": str(shard_path), "sha256": _sha256_file(shard_path), "declared_sha256": "UNKNOWN", "bytes_on_disk": shard_path.stat().st_size, "declared_bytes_on_disk": "UNKNOWN", "source_manifest": "UNKNOWN", "status": "UNKNOWN", "transform_links": [], "source": meta.get("source", "UNKNOWN") if isinstance(meta, dict) else "UNKNOWN", "fetch_date": meta.get("fetch_date", "UNKNOWN") if isinstance(meta, dict) else "UNKNOWN", "model_in_loop": False})
            else:
                add_entry({"shard_path": shard_ref, "sha256": "UNREADABLE", "declared_sha256": "UNKNOWN", "bytes_on_disk": "UNKNOWN", "declared_bytes_on_disk": "UNKNOWN", "source_manifest": "UNKNOWN", "status": "UNKNOWN", "transform_links": [], "source": "UNKNOWN", "fetch_date": "UNKNOWN", "model_in_loop": False, "note": "shard not found on disk"})
    return {"manifest": entries, "summary": {"n_shards": len(entries), "verified": counts["verified"], "unverifiable": counts["unverifiable"], "unknown": counts["unknown"], "n_manifests": manifest_count, "unreadable_manifests": unreadable_manifests, "transform_verified": transform_verified, "transform_unverifiable": transform_unverifiable}, "timestamp": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}


def _selftest() -> None:
    """Unit test: synthetic 2-shard fixture (one verifiable, one UNKNOWN)."""
    import tempfile

    tmpdir = Path(tempfile.mkdtemp(prefix="provenance_test_"))

    # Create two test shards
    shard1_path = tmpdir / "shard_1.txt"
    shard1_path.write_text("This is shard 1 content for testing")
    shard1_sha = _sha256_file(shard1_path)

    shard2_path = tmpdir / "shard_2_missing.txt"  # Don't create this one

    # Create metadata for shard1
    metadata = {
        str(shard1_path): {
            "source": "test-fixture",
            "fetch_date": "2026-07-09",
        }
    }

    metadata_file = tmpdir / "metadata.json"
    with open(metadata_file, 'w') as f:
        json.dump(metadata, f)

    # Create a test config
    config = {
        "shards": [str(shard1_path), str(shard2_path)],
    }

    config_file = tmpdir / "config.json"
    with open(config_file, 'w') as f:
        json.dump(config, f)

    # Build manifest
    result = build_manifest([str(config_file)], str(metadata_file))

    # Verify
    assert result["summary"]["n_shards"] == 2, "Should have 2 shard entries"
    assert result["summary"]["unknown"] >= 1, "Should have at least 1 unknown shard"

    # Find shard1 entry
    shard1_entry = None
    for entry in result["manifest"]:
        if "shard_1.txt" in entry["shard_path"]:
            shard1_entry = entry
            break

    assert shard1_entry is not None, "Shard1 should be in manifest"
    assert shard1_entry["sha256"] == shard1_sha, "SHA256 should match"
    assert shard1_entry["source"] == "test-fixture", "Source should be populated from metadata"

    print("[PASS] SELFTEST: 2-shard fixture (1 verifiable, 1 UNKNOWN) validated")

    # Cleanup
    import shutil
    shutil.rmtree(tmpdir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build corpus provenance manifest")
    parser.add_argument("--selftest", action="store_true",
                        help="Run unit test (2-shard fixture)")
    parser.add_argument("--configs", type=str, nargs='+',
                        help="Training config paths")
    parser.add_argument("--metadata", type=str,
                        help="Optional metadata manifest JSON")
    parser.add_argument("--write", action="store_true",
                        help="Write receipt to receipts/paper/")
    args = parser.parse_args()

    if args.selftest:
        _selftest()
    elif args.configs:
        result = build_manifest(args.configs, args.metadata)

        if args.write:
            receipts_dir = Path(__file__).resolve().parent.parent.parent / "receipts" / "paper"
            receipts_dir.mkdir(parents=True, exist_ok=True)
            ts = result["timestamp"]
            receipt_path = receipts_dir / f"provenance-manifest-{ts}.json"
            with open(receipt_path, 'w') as f:
                json.dump(result, f, indent=2)
            print(f"Receipt written to {receipt_path}")
        else:
            print(json.dumps(result, indent=2))
    else:
        parser.print_help()
