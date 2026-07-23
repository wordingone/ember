# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

"""Build one bounded owned-text pre-admission tranche from custody-bound bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


POLICY_BYTES = b"ember-owned-text-wave1-policy-v1"
VERIFIER_BYTES = b"ember-owned-text-transform-verifier-v1"


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _inventory_evidence(path: Path) -> dict[str, bytes]:
    evidence: dict[str, bytes] = {}
    for raw_line in path.read_bytes().splitlines():
        if not raw_line:
            continue
        try:
            entry = json.loads(raw_line)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Gutenberg inventory is invalid") from error
        if not isinstance(entry, dict):
            raise ValueError("Gutenberg inventory entry is invalid")
        key = _sha(_canonical(entry))
        if key in evidence:
            raise ValueError("Gutenberg inventory evidence is ambiguous")
        evidence[key] = raw_line
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--gutenberg-root", type=Path, required=True)
    parser.add_argument("--gutenberg-limit", type=int, default=32)
    parser.add_argument("--court-csv", type=Path, required=True)
    parser.add_argument("--court-custody-receipt", type=Path, required=True)
    parser.add_argument("--max-records-per-source", type=int, default=65536)
    args = parser.parse_args()
    if not 1 <= args.gutenberg_limit <= 32:
        raise ValueError("Gutenberg source limit is invalid")
    tools = (args.repo_root / "tools" / "ember-restart-3b").resolve()
    if not tools.is_dir():
        raise ValueError("repo root lacks owned text tooling")
    sys.path.insert(0, str(tools))
    from text_lab_corpus import (
        admit_pre_admission_text_tranche,
        build_pre_admission_text_tranche,
        record_source_custody_file,
        select_numeric_inventory_files,
        source_inventory_descriptor,
    )

    inventory_path = args.gutenberg_root / "manifest.jsonl"
    selected = select_numeric_inventory_files(
        raw_root=args.gutenberg_root,
        inventory_path=inventory_path,
        limit=args.gutenberg_limit,
    )
    evidence = _inventory_evidence(inventory_path)
    sources: list[dict[str, str]] = []
    raw_paths: dict[str, Path] = {}
    custody: dict[str, dict[str, object]] = {}
    for item in selected:
        filename = item["filename"]
        source_id = f"gutenberg-{Path(filename).stem}"
        entry = item["receipt_entry"]
        descriptor = source_inventory_descriptor(
            source_id=source_id,
            domain="application_worlds",
            split="train",
            provenance_origin_id=f"gutenberg:{Path(filename).stem}",
            receipt_entry=entry,
        )
        receipt_bytes = evidence.get(_sha(_canonical(entry)))
        if receipt_bytes is None:
            raise ValueError("Gutenberg inventory evidence is missing")
        custody[source_id] = record_source_custody_file(
            descriptor=descriptor,
            raw_path=item["raw_path"],
            license_evidence_bytes=receipt_bytes,
            policy_bytes=POLICY_BYTES,
            verifier_bytes=VERIFIER_BYTES,
        )
        raw_paths[source_id] = item["raw_path"]
        sources.append({"source_id": source_id, "split": "train", "transform_id": "utf8_nonblank_lines_v1"})

    court_id = "courtlistener-scotus-caption"
    try:
        court_receipt = json.loads(args.court_custody_receipt.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("CourtListener custody receipt is invalid") from error
    if not isinstance(court_receipt, dict) or court_receipt.get("source_id") != court_id:
        raise ValueError("CourtListener custody receipt identity is invalid")
    custody[court_id] = court_receipt
    raw_paths[court_id] = args.court_csv
    sources.append({"source_id": court_id, "split": "heldout", "transform_id": "csv_case_citation_v1"})

    premise = {
        "sources": sorted(sources, key=lambda item: item["source_id"]),
        "custody": {key: _sha(_canonical(value)) for key, value in sorted(custody.items())},
        "policy_sha256": _sha(POLICY_BYTES),
        "verifier_sha256": _sha(VERIFIER_BYTES),
        "max_records_per_source": args.max_records_per_source,
    }
    build_id = "wave1-" + _sha(_canonical(premise))[:24]
    tranche = args.staging_root / build_id
    if tranche.exists():
        expected = {"manifest.json", "train.jsonl", "heldout.jsonl"}
        if not tranche.is_dir() or {path.name for path in tranche.iterdir()} != expected:
            raise ValueError("existing tranche is not recoverable pre-admission output")
        try:
            manifest = json.loads((tranche / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("existing tranche manifest is invalid") from error
        if not isinstance(manifest, dict):
            raise ValueError("existing tranche manifest is invalid")
    else:
        manifest = build_pre_admission_text_tranche(
            sources=sources, raw_paths=raw_paths, source_custody_receipts=custody,
            output_root=args.staging_root, build_id=build_id,
            max_records_per_source=args.max_records_per_source,
        )
    l4_receipt = admit_pre_admission_text_tranche(
        tranche_root=tranche, source_custody_receipts=custody,
        policy_bytes=POLICY_BYTES, verifier_bytes=VERIFIER_BYTES,
    )
    (tranche / "l4-transform-receipt.json").write_bytes(_canonical(l4_receipt))
    print(json.dumps({"result": "VERIFIED", "build_id": build_id, "manifest": manifest,
                      "l4_transform_receipt_sha256": _sha(_canonical(l4_receipt))}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
