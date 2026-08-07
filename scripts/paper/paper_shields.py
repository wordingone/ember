#!/usr/bin/env python3
"""Bounded CPU-only orchestrator for issue #552 Components A-C.

This is an evidence consumer, not a trainer: every input is explicit, missing
shards remain UNKNOWN in the provenance result, and the receipt makes no
model, capability, benchmark, or training claim.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve()
SCRIPTS = HERE.parents[1]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE.parent))

import contamination_scan  # noqa: E402
import compute_ledger  # noqa: E402
import provenance_manifest  # noqa: E402
from receipt_check import INVARIANT_SHA256  # noqa: E402
from receipt_write import checked_write  # noqa: E402

SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return "UNREADABLE"
    return h.hexdigest()


def _basename(value: object) -> str:
    return Path(str(value)).name if value is not None else "UNKNOWN"


def _load_eval(path: Path) -> list[dict]:
    raw = path.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
        raise ValueError("eval manifest must be a JSON list of objects")
    return data


def _expand_shards(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        matches = sorted(glob.glob(value)) if any(c in value for c in "*?[") else [value]
        result.extend(matches or [value])
    return list(dict.fromkeys(result))
def _config_manifest_refs(configs: list[str]) -> list[str]:
    refs: list[str] = []
    for name in configs:
        try:
            data = json.loads(Path(name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        def visit(value: object) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in {"manifest_path", "shards", "shard_paths", "corpus_path", "data_path", "dataset_path"}:
                        if isinstance(item, str): refs.append(item)
                        elif isinstance(item, list): refs.extend(x for x in item if isinstance(x, str))
                    visit(item)
            elif isinstance(value, list):
                for item in value: visit(item)
        visit(data)
    return list(dict.fromkeys(refs))


def run_shields(eval_manifest: str, shards: list[str], configs: list[str],
                receipts: list[str], out_path: str, timestamp: str | None = None) -> dict:
    """Run A/B/C on explicit bytes and atomically publish one path-free receipt."""
    eval_path = Path(eval_manifest)
    if not eval_path.is_file():
        raise FileNotFoundError(f"eval manifest missing: {eval_path}")
    if not configs:
        raise ValueError("at least one training config is required")
    if not receipts:
        raise ValueError("at least one existing claim-bearing receipt is required")
    eval_data = _load_eval(eval_path)
    shard_values = _expand_shards(shards)
    # A is intentionally executed even when a shard is unreadable; B preserves
    # the same missing input as an explicit UNKNOWN row.
    contamination = contamination_scan.scan_contamination(eval_data, shard_values)
    for key in ("per_item", "contaminated_items"):
        for row in contamination.get(key, []):
            if row.get("worst_shard") is not None:
                row["worst_shard"] = _basename(row["worst_shard"])
    provenance = provenance_manifest.build_manifest(configs)
    ledger = compute_ledger.backfill_compute_ledger(receipts)
    covered = {str(row.get("shard_path")) for row in provenance["manifest"]}
    for ref in _config_manifest_refs(configs):
        if ref not in covered:
            provenance["manifest"].append({"shard_path": ref, "sha256": _sha256(Path(ref)),
                "source": "UNKNOWN", "fetch_date": "UNKNOWN", "transform_chain": [],
                "transform_status": "UNKNOWN", "model_in_loop": False,
                "note": "config-referenced provenance input"})
            provenance["summary"]["n_shards"] += 1
            provenance["summary"]["unknown"] += 1
    ts = timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "EMBER-552-PAPER-SHIELDS",
        "ts": ts,
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": SHA_CONVENTION,
        "issue": 552,
        "goal_id": "EMBER-02",
        "workstream_id": "EMBER-02A",
        "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
        "scope": "CPU-only model-free paper-shields Components A-C",
        "claim_boundary": "No model, training, benchmark, capability, or frozen-corpus claim",
        "inputs": {
            "eval_manifest": {"basename": eval_path.name, "sha256": _sha256(eval_path)},
            "shards": [{"basename": _basename(p), "sha256": _sha256(Path(p))}
                       for p in shard_values],
            "configs": [{"basename": Path(p).name, "sha256": _sha256(Path(p))}
                        for p in configs],
            "receipts": [{"basename": Path(p).name, "sha256": _sha256(Path(p))}
                         for p in receipts],
        },
        "component_a_contamination": contamination,
        "component_b_provenance": {
            "manifest": [{**row, "shard_path": _basename(row.get("shard_path"))}
                         for row in provenance["manifest"]],
            "summary": provenance["summary"],
        },
        "component_c_compute_ledger": [
            {**row, "receipt_path": _basename(row.get("receipt_path"))}
            for row in ledger
        ],
        "component_d_status": "COORDINATOR_GATED_NOT_IMPLEMENTED",
        "component_d_transfer": {
            "carrier_issue": 123,
            "carrier_url": "https://github.com/wordingone/ember/issues/123",
            "status": "PENDING_BENCHMARK_MANDATE",
            "clauses": [
                "coordinator freeze declaration binds commit_hash suite_manifest_sha256 ts",
                "pre-freeze numbers are labeled development appendix",
                "one held-out eval selected by a published rule seeded by freeze commit",
                "no human selection and no capability claim before freeze",
            ],
        },
    }
    checked_write(out_path, receipt)
    return receipt


def _selftest() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        eval_path = root / "eval.json"
        shard = root / "shard.txt"
        config = root / "config.json"
        run = root / "run.json"
        out = root / "receipt.json"
        eval_path.write_text(json.dumps([{"item_id": "x", "text": "clean item"}]), encoding="utf-8")
        shard.write_text("planted unrelated corpus text", encoding="utf-8")
        config.write_text(json.dumps({"shards": [str(shard), str(root / "missing.txt")]}), encoding="utf-8")
        run.write_text(json.dumps({"ticket": "RUN", "ts": "20260601T000000Z", "steps": 2,
                                  "tokens_this_segment": 8, "wall_s": 4}), encoding="utf-8")
        result = run_shields(str(eval_path), [str(shard)], [str(config)], [str(run)], str(out),
                             timestamp="20260807T000000Z")
        assert result["component_a_contamination"]["suite_summary"]["n_items"] == 1
        assert result["component_b_provenance"]["summary"]["unknown"] >= 1
        assert result["component_c_compute_ledger"][0]["status"] == "BACKFILLED"
        assert "\\" not in out.read_text(encoding="utf-8")
        print("ISSUE552_PAPER_SHIELDS_SELFTEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--eval-manifest")
    parser.add_argument("--shard", action="append", default=[])
    parser.add_argument("--config", action="append", default=[])
    parser.add_argument("--receipt", action="append", default=[])
    parser.add_argument("--out")
    args = parser.parse_args()
    if args.selftest:
        _selftest(); return 0
    for name in ("eval_manifest", "out"):
        if not getattr(args, name):
            parser.error(f"--{name.replace('_', '-') } is required")
    run_shields(args.eval_manifest, args.shard, args.config, args.receipt, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
