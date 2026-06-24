#!/usr/bin/env python3
"""Preflight D3-Gym prospective execution without pulling Docker images."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def inspect_image(image: str, timeout_seconds: int) -> dict[str, Any]:
    cmd = ["docker", "image", "inspect", image, "--format", "{{json .RepoDigests}}"]
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        return {
            "image": image,
            "command": cmd,
            "available_local": False,
            "returncode": None,
            "stdout": (exc.stdout or "") if isinstance(exc.stdout, str) else "",
            "stderr": "timeout_expired",
        }
    return {
        "image": image,
        "command": cmd,
        "available_local": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "").strip(),
        "stderr": (proc.stderr or "").strip(),
    }


def task_ids_from_materialized(path: Path, requested: list[str]) -> list[str]:
    payload = read_json(path)
    materialized = [str(w.get("row", {}).get("task_id")) for w in payload.get("rows", []) if w.get("row", {}).get("task_id")]
    if requested:
        return [tid for tid in requested if tid in materialized]
    return materialized


def build_receipt(*, repo: Path, materialized_rows: Path, dryrun_receipt: Path, out: Path, task_ids: list[str], timeout_seconds: int) -> dict[str, Any]:
    selected = task_ids_from_materialized(materialized_rows, task_ids)
    inspections = [inspect_image(f"hananemoussa/d3-gym:{tid}", timeout_seconds) for tid in selected]
    missing = [row["image"] for row in inspections if not row["available_local"]]
    blocked_reasons: list[str] = []
    if not selected:
        blocked_reasons.append("selected_task_ids_missing_from_materialized_rows")
    if missing:
        blocked_reasons.append("docker_images_missing_local")
    if any("permission denied" in (row.get("stderr") or "").lower() for row in inspections):
        blocked_reasons.append("docker_api_permission_denied")
    dryrun = read_json(dryrun_receipt)
    if dryrun.get("verdict") != "D3_MULTI_TASK_GENERALIZATION_DRYRUN_PASS":
        blocked_reasons.append("prospective_dryrun_not_pass")
    if not dryrun.get("prospective_surface", {}).get("fresh_surface_no_prior_failed_receipt_overlap"):
        blocked_reasons.append("prospective_surface_not_fresh")
    receipt = {
        "ticket": "EMBER-D3-PROSPECTIVE-EXECUTION-PREFLIGHT",
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "sha_convention": SHA_CONVENTION,
        "repo": str(repo),
        "goal_path": str(repo / "GOAL.md"),
        "goal_source_sha256": sha256_file(repo / "GOAL.md") if (repo / "GOAL.md").exists() else None,
        "materialized_rows_path": str(materialized_rows),
        "materialized_rows_sha256": sha256_file(materialized_rows),
        "dryrun_receipt_path": str(dryrun_receipt),
        "dryrun_receipt_sha256": sha256_file(dryrun_receipt),
        "selected_task_ids": selected,
        "docker_image_inspections": inspections,
        "missing_local_images": missing,
        "blocked_reasons": blocked_reasons,
        "execution_policy": {
            "implicit_pull_allowed": False,
            "reason": "Prevent surprise disk/network use; missing images must be pulled by an explicit load-bearing command and receipt.",
        },
        "next_executable_command": (
            "Explicitly pull or otherwise provision missing D3 Docker images, then run: "
            "python scripts\\ember_d3_generalized_candidate_exec.py "
            f"--fresh-rows {materialized_rows.relative_to(repo)} "
            "--out-dir receipts\\ember-d3-native-loop\\d3-prospective-task25-28-exec-<timestamp> "
            + " ".join(f"--task-id {tid}" for tid in selected)
            + " --require-prospective --execute"
        ),
        "verdict": "D3_PROSPECTIVE_EXECUTION_PREFLIGHT_PASS" if not blocked_reasons else "D3_PROSPECTIVE_EXECUTION_BLOCKED",
    }
    write_json(out, receipt)
    return receipt


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--materialized-rows", required=True)
    ap.add_argument("--dryrun-receipt", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--task-id", action="append", default=[])
    ap.add_argument("--timeout-seconds", type=int, default=10)
    args = ap.parse_args()
    repo = Path.cwd().resolve()
    out = Path(args.out)
    if not out.is_absolute():
        out = repo / out
    receipt = build_receipt(
        repo=repo,
        materialized_rows=(repo / args.materialized_rows).resolve(),
        dryrun_receipt=(repo / args.dryrun_receipt).resolve(),
        out=out,
        task_ids=args.task_id,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps({
        "receipt": str(out),
        "verdict": receipt["verdict"],
        "blocked_reasons": receipt["blocked_reasons"],
        "missing_local_images": receipt["missing_local_images"],
        "next_executable_command": receipt["next_executable_command"],
    }, indent=2, sort_keys=True))
    return 0 if receipt["verdict"] == "D3_PROSPECTIVE_EXECUTION_PREFLIGHT_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())