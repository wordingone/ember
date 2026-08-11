#!/usr/bin/env python3
"""Materialize a frozen D3-Gym row slice from the Hugging Face Dataset Viewer."""
from __future__ import annotations

import argparse
import hashlib
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATASET = "osunlp/D3-Gym"
CONFIG = "default"
SPLIT = "train"
BASE_URL = "https://datasets-server.huggingface.co/rows"
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def dataset_rows_url(offset: int, length: int) -> str:
    return BASE_URL + "?" + urllib.parse.urlencode({
        "dataset": DATASET,
        "config": CONFIG,
        "split": SPLIT,
        "offset": offset,
        "length": length,
    })


def fetch_rows(offset: int, length: int, timeout_seconds: int) -> tuple[str, dict[str, Any]]:
    url = dataset_rows_url(offset, length)
    req = urllib.request.Request(url, headers={"User-Agent": "ember-d3-materializer/1.0"})
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        raw = resp.read().decode("utf-8")
    return raw, json.loads(raw)


def build_receipt(*, repo: Path, out: Path, offset: int, length: int, timeout_seconds: int) -> dict[str, Any]:
    raw, payload = fetch_rows(offset, length, timeout_seconds)
    rows = payload.get("rows") or []
    task_ids = [str(w.get("row", {}).get("task_id")) for w in rows if w.get("row", {}).get("task_id")]
    duplicate_task_ids = sorted({tid for tid in task_ids if task_ids.count(tid) > 1})
    blocked_reasons: list[str] = []
    if len(rows) != length:
        blocked_reasons.append("row_count_mismatch")
    if duplicate_task_ids:
        blocked_reasons.append("duplicate_task_ids")
    if not task_ids:
        blocked_reasons.append("task_ids_missing")
    source_url = dataset_rows_url(offset, length)
    receipt = {
        "ticket": "EMBER-D3-HF-MATERIALIZE-ROWS",
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "sha_convention": SHA_CONVENTION,
        "repo": str(repo),
        "goal_path": str(repo / "docs/authority/GOAL.md"),
        "goal_source_sha256": sha256_file(repo / "docs/authority/GOAL.md") if (repo / "docs/authority/GOAL.md").exists() else None,
        "dataset": DATASET,
        "config": CONFIG,
        "split": SPLIT,
        "offset": offset,
        "length": length,
        "num_rows_total": payload.get("num_rows_total"),
        "num_rows_per_page": payload.get("num_rows_per_page"),
        "partial": payload.get("partial"),
        "source_url": source_url,
        "source_response_sha256": sha256_text(raw),
        "rows": rows,
        "task_ids": task_ids,
        "task_id_span": {"first": task_ids[0] if task_ids else None, "last": task_ids[-1] if task_ids else None},
        "external_surface_contract": {
            "fresh_relative_to_local_offsets_8_and_16": offset >= 24,
            "private_gold_excluded": True,
            "source": "Hugging Face Dataset Viewer rows endpoint",
            "max_length_policy": "length <= 100 per Dataset Viewer row endpoint",
        },
        "blocked_reasons": blocked_reasons,
        "next_executable_command": (
            "python scripts\\ember_d3_generalized_candidate_exec.py "
            f"--fresh-rows {out.relative_to(repo)} "
            "--out-dir receipts\\ember-d3-native-loop\\d3-prospective-task25-28-<timestamp> "
            "--task-id task_25 --task-id task_26 --task-id task_27 --task-id task_28 --require-prospective --execute"
        ),
        "verdict": "D3_HF_ROWS_MATERIALIZED" if not blocked_reasons else "D3_HF_ROWS_BLOCKED",
    }
    write_json(out, receipt)
    return receipt


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--offset", type=int, required=True)
    ap.add_argument("--length", type=int, required=True)
    ap.add_argument("--timeout-seconds", type=int, default=60)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    repo = Path.cwd().resolve()
    out = Path(args.out)
    if not out.is_absolute():
        out = repo / out
    receipt = build_receipt(repo=repo, out=out, offset=args.offset, length=args.length, timeout_seconds=args.timeout_seconds)
    print(json.dumps({
        "receipt": str(out),
        "verdict": receipt["verdict"],
        "task_ids": receipt["task_ids"],
        "blocked_reasons": receipt["blocked_reasons"],
        "next_executable_command": receipt["next_executable_command"],
    }, indent=2, sort_keys=True))
    return 0 if receipt["verdict"] == "D3_HF_ROWS_MATERIALIZED" else 2


if __name__ == "__main__":
    raise SystemExit(main())