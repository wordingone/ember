#!/usr/bin/env python3
"""Run a broader D3 multi-family A/B/C/deleted loop from an admission receipt."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import ember_d3_generalized_candidate_exec as generalized

DEFAULT_ADMISSION_GLOB = "receipts/ember-post-resident-discovery/d3-broader-multifamily-admission-*.json"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def latest_admission(repo: Path) -> Path:
    matches = sorted(repo.glob(DEFAULT_ADMISSION_GLOB))
    if not matches:
        raise FileNotFoundError(f"no broader D3 admission receipt found: {repo / DEFAULT_ADMISSION_GLOB}")
    return matches[-1]


def load_frozen_rows(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = read_json(path)
    if isinstance(payload, dict):
        rows = payload.get("tasks") or payload.get("rows") or []
    elif isinstance(payload, list):
        rows = payload
        payload = {}
    else:
        rows = []
        payload = {}
    return payload if isinstance(payload, dict) else {}, [row for row in rows if isinstance(row, dict)]


def row_task_id(row: dict[str, Any]) -> str | None:
    return row.get("task_id") or row.get("id") or row.get("task")


def materialize_fresh_rows_from_admission(admission_path: Path, out_dir: Path, task_ids: list[str] | None = None) -> Path:
    admission = read_json(admission_path)
    if admission.get("verdict") != "D3_BROADER_MULTIFAMILY_ADMITTED":
        raise ValueError(f"admission is not admitted: {admission.get('verdict')}")
    selected = admission.get("frozen_heldout_slice", {}).get("rows", [])
    requested = set(task_ids or [row.get("task_id") for row in selected if row.get("task_id")])
    selected_refs = [row for row in selected if row.get("task_id") in requested]
    materialized: list[dict[str, Any]] = []
    seen: set[str] = set()
    source_meta: dict[str, Any] = {}
    for ref in selected_refs:
        tid = str(ref["task_id"])
        source_path = Path(ref["source_path"])
        source_payload, source_rows = load_frozen_rows(source_path)
        if not source_meta:
            source_meta = source_payload
        for row in source_rows:
            if row_task_id(row) == tid and tid not in seen:
                full_row = dict(row)
                full_row["task_id"] = tid
                materialized.append({
                    "row_idx": full_row.get("source_row_idx", ref.get("source_row_idx")),
                    "row": full_row,
                    "truncated_cells": [],
                })
                seen.add(tid)
                break
    missing = sorted(requested - seen)
    if missing:
        raise FileNotFoundError(f"selected D3 rows missing from frozen source: {missing}")
    split = source_meta.get("split", {}) if isinstance(source_meta.get("split"), dict) else {}
    payload = {
        "config": split.get("config", "default"),
        "dataset": split.get("dataset", "osunlp/D3-Gym"),
        "split": split.get("split", "train"),
        "offset": split.get("offset"),
        "length": len(materialized),
        "num_rows_total": source_meta.get("num_rows_total"),
        "source_url": source_meta.get("source_url") or "https://huggingface.co/datasets/osunlp/D3-Gym",
        "admission_receipt": str(admission_path),
        "rows": materialized,
    }
    out_path = out_dir / "d3-broader-multifamily-fresh-rows.json"
    write_json(out_path, payload)
    return out_path


def build_loop_receipt(
    *,
    repo: Path,
    admission_path: Path,
    out_dir: Path,
    task_ids: list[str] | None,
    timeout_seconds: int,
    execute: bool,
) -> dict[str, Any]:
    fresh_rows_path = materialize_fresh_rows_from_admission(admission_path, out_dir, task_ids=task_ids)
    selected_task_ids = task_ids or [row["row"]["task_id"] for row in read_json(fresh_rows_path)["rows"]]
    receipt = generalized.build_receipt(
        repo=repo,
        fresh_rows_path=fresh_rows_path,
        out_dir=out_dir,
        task_ids=selected_task_ids,
        timeout_seconds=timeout_seconds,
        execute=execute,
    )
    verdict_map = {
        "D3_MULTI_TASK_GENERALIZATION_PASS": "D3_BROADER_MULTIFAMILY_LOOP_PASS",
        "D3_MULTI_TASK_GENERALIZATION_DRYRUN_PASS": "D3_BROADER_MULTIFAMILY_LOOP_DRYRUN_PASS",
    }
    receipt["ticket"] = "EMBER-D3-BROADER-MULTIFAMILY-LOOP"
    receipt["broader_d3_admission_receipt"] = str(admission_path)
    receipt["broader_d3_fresh_rows_path"] = str(fresh_rows_path)
    receipt["broader_d3_loop_ts"] = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt["verdict"] = verdict_map.get(receipt["verdict"], "D3_BROADER_MULTIFAMILY_LOOP_BLOCKED")
    if receipt["verdict"] == "D3_BROADER_MULTIFAMILY_LOOP_PASS":
        receipt["next_blocker"] = "assess whether broader-D3 positive delta survives transfer/re-use and field-level contribution pressure"
    else:
        receipt["next_blocker"] = "continue from exact broader-D3 loop errors before any duration/readiness growth"
    generalized.write_json_lf(out_dir / "d3-broader-multifamily-loop-receipt.json", receipt)
    return receipt


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--admission", default=None)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--task-id", action="append", default=[])
    ap.add_argument("--timeout-seconds", type=int, default=180)
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        import ember_d3_broader_multifamily_loop_selftest

        return ember_d3_broader_multifamily_loop_selftest.main()

    # Guard: check C14 RESIDENT_TRAINING_GATE_PASS precondition before launch
    try:
        import loop_launch_guard
        repo = Path.cwd().resolve()
        loop_launch_guard.guard_loop_launch(repo, datetime.now(timezone.utc))
    except RuntimeError as e:
        print(f"Loop launch blocked by precondition guard: {e}", file=__import__("sys").stderr)
        return 2

    repo = Path.cwd().resolve()
    admission = Path(args.admission) if args.admission else latest_admission(repo)
    if not admission.is_absolute():
        admission = (repo / admission).resolve()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out_dir) if args.out_dir else Path("receipts/ember-d3-native-loop") / f"d3-broader-multifamily-loop-{ts}"
    if not out_dir.is_absolute():
        out_dir = (repo / out_dir).resolve()
    receipt = build_loop_receipt(
        repo=repo,
        admission_path=admission,
        out_dir=out_dir,
        task_ids=args.task_id or None,
        timeout_seconds=args.timeout_seconds,
        execute=args.execute,
    )
    print(json.dumps({
        "receipt": str(out_dir / "d3-broader-multifamily-loop-receipt.json"),
        "verdict": receipt["verdict"],
        "selected_task_ids": receipt["selected_task_ids"],
        "aggregate_scores": receipt["aggregate_scores"],
        "positive_delta": receipt["positive_delta"],
        "deletion_sensitive": receipt["deletion_sensitive"],
        "errors": receipt["errors"],
    }, indent=2, sort_keys=True))
    return 0 if receipt["verdict"] in {"D3_BROADER_MULTIFAMILY_LOOP_PASS", "D3_BROADER_MULTIFAMILY_LOOP_DRYRUN_PASS", "D3_BROADER_MULTIFAMILY_LOOP_BLOCKED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
