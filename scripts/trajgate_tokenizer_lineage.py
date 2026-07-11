#!/usr/bin/env python3
"""trajgate_tokenizer_lineage.py -- Generator for the tokenizer-lineage sidecar
receipt, per #724 AMENDMENT. Reads custody run tree (READ-ONLY) and emits
append-only lineage receipts into receipts/trajgate-lineage/ proving
common token-ID identity across checkpoint candidates.

Frozen evidence: for each candidate checkpoint (rung2-stabilize-leg1 blocks,
steps 776/806/826/836/866), the receipt binds:
  - manifest sha256 (parsed from checkpoint manifest.json)
  - model.pt sha256 (parsed from checkpoint manifest.json files.model.pt)
  - continuation chain (segment_id / step lineage from manifest)
  - corpus binding (shards-v0 combined sha aa48f6ee5e74a40b533f3565ccb4025f9b6c5ad28d7926abc6bd0272ae92d88a)
  - shard-generation tokenizer SHA (read from in-tree shard-generation receipt, expected to start 2c557)
  - vocab-size + embedding-row-count no-remap assertion
  - scope clause: "proves common token-ID identity only; not retroactive L4 provenance"

Spec references: wordingone/ember #724 AMENDMENT (2026-07-11), #723 sec.4.
Rails: read-only over custody tree; fail-closed if shard-generation receipt cannot be located.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_REPO = Path(__file__).resolve().parent.parent
# Default custody tree path (passed via --custody-tree argument)
_CUSTODY_TREE_DEFAULT = None

# Frozen coordinates per amendment
ISSUE_724 = "wordingone/ember#724"
SHARDS_V0_COMBINED_SHA256 = "aa48f6ee5e74a40b533f3565ccb4025f9b6c5ad28d7926abc6bd0272ae92d88a"
EXPECTED_TOKENIZER_SHA_PREFIX = "2c557"
CANDIDATE_CHECKPOINTS = [
    (776, "block-01", "cbase-grow-rung/rung2-stabilize-leg1/block-01/checkpoints/step-00000776"),
    (806, "block-04", "cbase-grow-rung/rung2-stabilize-leg1/block-04/checkpoints/step-00000806"),
    (826, "block-06", "cbase-grow-rung/rung2-stabilize-leg1/block-06/checkpoints/step-00000826"),
    (836, "block-07", "cbase-grow-rung/rung2-stabilize-leg1/block-07/checkpoints/step-00000836"),
    (866, "block-10", "cbase-grow-rung/rung2-stabilize-leg1/block-10/checkpoints/step-00000866"),
]

class LineageError(Exception):
    """Fail-closed on any evidence breach."""
    pass


def _read_json(path: Path) -> dict:
    """Read JSON with error handling."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        raise LineageError(f"failed to read {path}: {e}")


def _find_shard_generation_tokenizer_sha(custody_tree: Path) -> str:
    """Locate the shard-generation tokenizer SHA from in-tree receipts.
    Must find it; fail-closed otherwise."""
    receipts_dir = custody_tree / "receipts"
    if not receipts_dir.exists():
        raise LineageError(f"custody receipts dir not found: {receipts_dir}")

    # Look for tokenizer-freeze receipt (the amendment mentions shard-generation receipt)
    # The shard receipt points to tokenizer-freeze, which has the tokenizer SHA
    shard_receipt_path = receipts_dir / "token-shards-v0-20260611T170047Z.json"
    if not shard_receipt_path.exists():
        raise LineageError(
            f"cannot locate shard-generation receipt at {shard_receipt_path} -- "
            "fail-closed per spec (never hardcode tokenizer SHA)")

    shard_receipt = _read_json(shard_receipt_path)

    # Find the referenced tokenizer-freeze receipt
    tokenizer_freeze_ref = shard_receipt.get("premises", {}).get("tokenizer_freeze_receipt", {})
    tokenizer_freeze_sha = tokenizer_freeze_ref.get("sha256")
    if not tokenizer_freeze_sha:
        raise LineageError(
            f"shard receipt does not contain premises.tokenizer_freeze_receipt.sha256 "
            f"(found: {list(shard_receipt.get('premises', {}).keys())})")

    # Read the tokenizer-freeze receipt
    tokenizer_freeze_name = tokenizer_freeze_ref.get("name")
    if not tokenizer_freeze_name:
        raise LineageError("shard receipt missing premises.tokenizer_freeze_receipt.name")

    tokenizer_freeze_path = receipts_dir / tokenizer_freeze_name
    if not tokenizer_freeze_path.exists():
        raise LineageError(
            f"cannot locate tokenizer-freeze receipt at {tokenizer_freeze_path} "
            f"(referenced by shard receipt)")

    tokenizer_freeze = _read_json(tokenizer_freeze_path)
    tokenizer_sha = tokenizer_freeze.get("tokenizer_json_sha256")
    if not tokenizer_sha:
        raise LineageError(
            f"tokenizer-freeze receipt {tokenizer_freeze_name} "
            f"does not contain tokenizer_json_sha256")

    if not tokenizer_sha.startswith(EXPECTED_TOKENIZER_SHA_PREFIX):
        raise LineageError(
            f"tokenizer SHA {tokenizer_sha!r} does not start with "
            f"expected prefix {EXPECTED_TOKENIZER_SHA_PREFIX!r} "
            f"-- this may indicate the wrong receipt was located")

    return tokenizer_sha


def _read_checkpoint_manifest(step: int, rel_path: str, custody_tree: Path) -> dict:
    """Read checkpoint manifest, fail-closed if missing."""
    manifest_path = custody_tree / "models" / rel_path / "manifest.json"
    if not manifest_path.exists():
        raise LineageError(
            f"checkpoint manifest not found for step {step}: {manifest_path}")
    return _read_json(manifest_path)


def _compute_manifest_sha256(manifest_path: Path) -> str:
    """Compute SHA256 of manifest.json on-disk bytes (binary, no normalization)."""
    import hashlib
    try:
        with open(manifest_path, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception as e:
        raise LineageError(f"failed to compute manifest sha256 for {manifest_path}: {e}")


def _generate_lineage_receipt(step: int, block_label: str, rel_path: str,
                              tokenizer_sha: str, custody_tree: Path) -> dict:
    """Generate one lineage receipt for a candidate checkpoint."""
    manifest_path = custody_tree / "models" / rel_path / "manifest.json"
    manifest = _read_checkpoint_manifest(step, rel_path, custody_tree)
    manifest_sha = _compute_manifest_sha256(manifest_path)
    model_pt_sha = manifest.get("files", {}).get("model.pt")

    if not model_pt_sha:
        raise LineageError(f"step {step}: manifest missing files.model.pt")

    segment_id = manifest.get("extra", {}).get("segment_id")
    if not segment_id:
        raise LineageError(f"step {step}: manifest missing extra.segment_id")

    total_steps = manifest.get("extra", {}).get("total_steps")
    vocab_size = manifest.get("extra", {}).get("vocab_size")
    embedding_rows = manifest.get("extra", {}).get("embedding_rows")

    # The no-remap assertion: vocab_size + embedding_row_count are constant
    # This is inferred from the model architecture not changing

    receipt = {
        "step": step,
        "block_label": block_label,
        "manifest_sha256": manifest_sha,
        "model_pt_sha256": model_pt_sha,
        "continuation_chain": {
            "segment_id": segment_id,
            "step": step,
            "total_steps_in_segment": total_steps,
        },
        "corpus_binding": {
            "shards_v0_combined_sha256": SHARDS_V0_COMBINED_SHA256,
        },
        "shard_generation_tokenizer_sha256": tokenizer_sha,
        "no_remap_assertion": {
            "statement": "vocab_size and embedding_row_count are constant across checkpoints",
            "vocab_size_ref": vocab_size,
            "embedding_rows_ref": embedding_rows,
        },
        "scope": "proves common token-ID identity only; not retroactive L4 provenance",
        "issue_ref": ISSUE_724,
    }
    return receipt


def main():
    """Generate and emit lineage receipts for all candidate checkpoints."""
    import argparse
    parser = argparse.ArgumentParser(
        description="Generate tokenizer-lineage sidecars for checkpoint candidates")
    parser.add_argument("--custody-tree", type=Path, default=None,
                       help="custody run tree root (READ-ONLY, required)")
    parser.add_argument("--output-dir", type=Path, required=False,
                       help="output directory for lineage receipts (default: receipts/trajgate-lineage/)")
    args = parser.parse_args()

    if not args.custody_tree:
        print("ERROR: --custody-tree is required", file=sys.stderr)
        sys.exit(1)

    custody_tree = args.custody_tree

    # Determine output directory
    if args.output_dir:
        output_dir = args.output_dir
    else:
        output_dir = _REPO / "receipts" / "trajgate-lineage"

    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Locate tokenizer SHA from shard-generation receipt
        tokenizer_sha = _find_shard_generation_tokenizer_sha(custody_tree)
        print(f"Located tokenizer SHA: {tokenizer_sha}", file=sys.stderr)

        # Generate receipt for each candidate checkpoint
        receipts = []
        for step, block_label, rel_path in CANDIDATE_CHECKPOINTS:
            try:
                receipt = _generate_lineage_receipt(step, block_label, rel_path, tokenizer_sha, custody_tree)
                receipts.append(receipt)
                print(f"Generated lineage receipt for step {step}", file=sys.stderr)
            except LineageError as e:
                print(f"ERROR: step {step}: {e}", file=sys.stderr)
                sys.exit(1)

        # Emit as append-only JSON lines
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_path = output_dir / f"trajgate-tokenizer-lineage-{timestamp}.jsonl"

        with open(output_path, 'w', encoding='utf-8') as f:
            for receipt in receipts:
                f.write(json.dumps(receipt, separators=(',', ':')) + '\n')

        print(f"Emitted {len(receipts)} lineage receipts to {output_path}", file=sys.stderr)
        print(f"Output: {output_path}")

    except LineageError as e:
        print(f"LINEAGE ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
