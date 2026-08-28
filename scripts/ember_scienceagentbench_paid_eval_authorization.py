#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Emit a no-secret authorization receipt for ScienceAgentBench paid visual judging."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TICKET = "EMBER-SCIENCEAGENTBENCH-PAID-EVAL-AUTHORIZATION"
SHA_CONVENTION = "bytes on disk/as fetched as-is; text hashes are UTF-8 encoded"
DEFAULT_FIRST_LOOP = Path("receipts/ember-post-resident-discovery/scienceagentbench-first-loop-20260622T172643Z.json")
DEFAULT_OUT_DIR = Path("receipts/ember-post-resident-discovery")
OPENAI_ENV = "OPENAI_API_KEY"
AZURE_ENVS = ["AZURE_OPENAI_KEY", "AZURE_OPENAI_API_VERSION", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT_NAME"]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def bool_env(env: dict[str, str], name: str) -> bool:
    return bool(env.get(name))


def build_receipt(
    *,
    repo: Path,
    out: Path,
    first_loop_receipt_path: Path,
    allow_paid_visual_judge: bool,
    max_visual_judge_calls: int,
    user_budget_note: str | None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = env if env is not None else os.environ
    blocked_reasons: list[str] = []
    first_loop = load_json(first_loop_receipt_path) if first_loop_receipt_path.exists() else {}
    visual_status = dict(first_loop.get("visual_judge_status", {}))
    expected_calls = int(visual_status.get("expected_visual_judge_calls") or 0)
    openai_present = bool_env(env, OPENAI_ENV)
    azure_present = all(bool_env(env, name) for name in AZURE_ENVS)
    configured = openai_present or azure_present
    call_cap_sufficient = max_visual_judge_calls >= expected_calls if expected_calls else False
    if not first_loop_receipt_path.exists():
        blocked_reasons.append("first_loop_receipt_missing")
    if not expected_calls:
        blocked_reasons.append("expected_visual_judge_calls_missing")
    if not configured:
        blocked_reasons.append("visual_judge_key_or_azure_config_missing")
    if not allow_paid_visual_judge:
        blocked_reasons.append("paid_visual_judge_not_authorized")
    if allow_paid_visual_judge and not call_cap_sufficient:
        blocked_reasons.append("paid_visual_judge_call_cap_too_low")
    if allow_paid_visual_judge and not user_budget_note:
        blocked_reasons.append("paid_visual_judge_budget_note_missing")

    ready = not blocked_reasons
    goal_path = repo / "docs/domains/governance/authority/GOAL.md"
    receipt = {
        "ticket": TICKET,
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "repo": str(repo),
        "goal_path": str(goal_path),
        "goal_source_sha256": sha256_file(goal_path) if goal_path.exists() else None,
        "sha_convention": SHA_CONVENTION,
        "first_loop_receipt": str(first_loop_receipt_path),
        "first_loop_receipt_sha256": sha256_file(first_loop_receipt_path) if first_loop_receipt_path.exists() else None,
        "secret_values_recorded": False,
        "visual_judge_env_presence": {
            "openai_env_checked": OPENAI_ENV,
            "openai_key_present": openai_present,
            "azure_envs_checked": AZURE_ENVS,
            "azure_config_present": azure_present,
        },
        "paid_visual_judge_authorization": {
            "paid_api_surface": True,
            "authorized": allow_paid_visual_judge,
            "user_budget_note_present": bool(user_budget_note),
            "user_budget_note_sha256": hashlib.sha256(user_budget_note.encode("utf-8")).hexdigest() if user_budget_note else None,
            "max_visual_judge_calls": max_visual_judge_calls,
            "expected_visual_judge_calls": expected_calls,
            "expected_call_formula": visual_status.get("expected_call_formula"),
            "call_cap_sufficient": call_cap_sufficient,
        },
        "blocked_reasons": blocked_reasons,
        "next_executable_command": (
            "Rerun scripts\\ember_scienceagentbench_first_loop.py with --allow-paid-visual-judge and the recorded call cap."
            if ready else
            "Provide visual-judge key/config plus explicit paid-eval authorization and call cap, then rerun this authorization packet."
        ),
        "verdict": "SCIENCEAGENTBENCH_PAID_EVAL_AUTHORIZATION_READY" if ready else "SCIENCEAGENTBENCH_PAID_EVAL_AUTHORIZATION_BLOCKED",
    }
    write_json(out, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first-loop-receipt", default=str(DEFAULT_FIRST_LOOP))
    parser.add_argument("--allow-paid-visual-judge", action="store_true")
    parser.add_argument("--max-visual-judge-calls", type=int, default=0)
    parser.add_argument("--user-budget-note", default=None, help="Short non-secret note proving explicit current-session paid-eval authorization.")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    repo = Path.cwd().resolve()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out) if args.out else DEFAULT_OUT_DIR / f"scienceagentbench-paid-eval-authorization-{ts}.json"
    if not out.is_absolute():
        out = repo / out
    receipt = build_receipt(
        repo=repo,
        out=out,
        first_loop_receipt_path=Path(args.first_loop_receipt),
        allow_paid_visual_judge=args.allow_paid_visual_judge,
        max_visual_judge_calls=args.max_visual_judge_calls,
        user_budget_note=args.user_budget_note,
    )
    print(json.dumps({
        "receipt": str(out),
        "verdict": receipt["verdict"],
        "blocked_reasons": receipt["blocked_reasons"],
        "next_executable_command": receipt["next_executable_command"],
    }, indent=2, sort_keys=True))
    return 0 if receipt["verdict"] in {"SCIENCEAGENTBENCH_PAID_EVAL_AUTHORIZATION_READY", "SCIENCEAGENTBENCH_PAID_EVAL_AUTHORIZATION_BLOCKED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
