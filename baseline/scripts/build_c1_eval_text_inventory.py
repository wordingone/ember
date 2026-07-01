#!/usr/bin/env python3
"""Build available-eval normalized-span inventory and local text-surface scan.

This script inventories eval text that is actually present in the repository and
scans its normalized 200-character windows against checked-in training JSONL
surfaces. Imported external benchmark receipts are indexed as metadata-only when
they do not carry raw eval prompts/cases, preserving the full-suite blocker.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERDICT = "C1_AVAILABLE_EVAL_TEXT_NORMALIZED_SPAN_LOCAL_SURFACE_SCAN_PASS_WITH_BLOCKING_FULL_SUITE_GAP"
SPAN_CHARS = 200


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8-sig") as fh:
        for line_no, line in enumerate(fh, start=1):
            if line.strip():
                row = json.loads(line)
                row["_line"] = line_no
                rows.append(row)
    return rows


def stable_eval_doc(row: dict[str, Any]) -> str:
    payload = {k: v for k, v in row.items() if not k.startswith("_")}
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def span_windows(text: str, width: int = SPAN_CHARS) -> list[str]:
    if len(text) < width:
        return []
    return [text[idx:idx + width] for idx in range(0, len(text) - width + 1)]


def digest_span_set(spans: set[str]) -> str:
    joined = "\n".join(sorted(sha256_bytes(span.encode("utf-8")) for span in spans))
    return sha256_bytes(joined.encode("utf-8"))


def repo_rel(path: Path, repo_root: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def imported_receipts(import_root: Path, repo_root: Path) -> dict[str, Any]:
    files = sorted(import_root.rglob("*.json")) if import_root.exists() else []
    rows = []
    for path in files:
        receipt = read_json(path)
        rows.append({
            "id": receipt.get("ticket") or receipt.get("id") or path.stem,
            "repo_path": repo_rel(path, repo_root),
            "sha256": sha256_file(path),
            "classification": receipt.get("classification"),
            "verdict": receipt.get("verdict"),
            "metadata_only": True,
            "raw_eval_text_available": False,
            "raw_eval_text_gap": "imported receipt carries artifact hashes/metadata but not raw benchmark prompts, cases, or private evaluator text",
        })
    return {
        "receipt_count": len(rows),
        "metadata_only_receipt_count": sum(1 for row in rows if row["metadata_only"]),
        "raw_eval_text_available_count": sum(1 for row in rows if row["raw_eval_text_available"]),
        "receipts": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    baseline_root = repo_root / "baseline"
    heldout_path = repo_root / "data" / "ember_avir_tasks" / "heldout.jsonl"
    train_path = repo_root / "data" / "ember_avir_tasks" / "train.jsonl"
    import_root = baseline_root / "receipts" / "external-benchmark-imports"

    heldout = load_jsonl(heldout_path)
    spans: set[str] = set()
    local_items = []
    for row in heldout:
        doc = normalize_text(stable_eval_doc(row))
        doc_spans = span_windows(doc)
        spans.update(doc_spans)
        local_items.append({
            "id": str(row.get("id", f"line-{row.get('_line')}")),
            "line": row.get("_line"),
            "normalized_chars": len(doc),
            "span_count": len(doc_spans),
            "normalized_doc_sha256": sha256_bytes(doc.encode("utf-8")),
        })

    scan_surfaces = []
    hit_samples = []
    exact_hits = 0
    if train_path.exists():
        normalized_train = normalize_text(train_path.read_text(encoding="utf-8-sig", errors="replace"))
        surface_hits = []
        for span in sorted(spans):
            pos = normalized_train.find(span)
            if pos >= 0:
                exact_hits += 1
                if len(hit_samples) < 25:
                    hit_samples.append({"surface": repo_rel(train_path, repo_root), "offset": pos, "span_sha256": sha256_bytes(span.encode("utf-8"))})
                surface_hits.append(sha256_bytes(span.encode("utf-8")))
        scan_surfaces.append({
            "repo_path": repo_rel(train_path, repo_root),
            "sha256": sha256_file(train_path),
            "normalized_chars": len(normalized_train),
            "exact_normalized_span_hits": len(surface_hits),
            "hit_span_hashes_sha256": digest_span_set(set(surface_hits)) if surface_hits else None,
        })

    external = imported_receipts(import_root, repo_root)
    failures = []
    if len(heldout) != 20:
        failures.append({"code": "unexpected_local_heldout_count", "actual": len(heldout)})
    if not spans:
        failures.append({"code": "no_normalized_spans"})
    if not scan_surfaces:
        failures.append({"code": "no_training_text_surfaces_scanned"})
    if exact_hits:
        failures.append({"code": "normalized_span_hits_present", "count": exact_hits})

    result = {
        "kind": "single_4090_c1_available_eval_text_inventory_normalized_span_scan",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": VERDICT if not failures else "C1_AVAILABLE_EVAL_TEXT_NORMALIZED_SPAN_LOCAL_SURFACE_SCAN_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "normalized_span_min_chars": SPAN_CHARS,
        "normalization": "NFKC, lowercase, collapse whitespace, strip boundaries; exact contiguous normalized character windows",
        "eval_text_inventory": {
            "local_ember_heldout": {
                "repo_path": repo_rel(heldout_path, repo_root),
                "sha256": sha256_file(heldout_path),
                "item_count": len(heldout),
                "normalized_doc_count": len(local_items),
                "span_count": len(spans),
                "span_hashes_sha256": digest_span_set(spans),
                "items": local_items,
            },
            "external_benchmark_import_receipts": external,
        },
        "checked_in_training_text_surfaces_scanned": scan_surfaces,
        "exact_normalized_span_hits": exact_hits,
        "hit_samples": hit_samples,
        "blocks_full_eval_suite_pass": True,
        "blocking_gap": "Full external eval-suite contamination PASS still requires raw/frozen external eval prompts/cases and a token-shard or full-corpus normalized-span scan. Imported receipts here are metadata/hash receipts, not raw eval text.",
        "completion_limit": "This inventories available local/imported eval text and scans normalized 200-character spans against checked-in local training JSONL only. It is not a full external eval-suite contamination PASS, not a token-shard or full-corpus normalized-span PASS, not a near-duplicate PASS, and not overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
