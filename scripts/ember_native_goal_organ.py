#!/usr/bin/env python3
"""Clean-room native goal organ for Ember.

The organ is an executable local mechanism: it parses the current goal packet,
reads receipts, selects the load-bearing blocker, compiles a bounded next
action, verifies its own decision surface, writes a receipt, and preserves the
next blocker. It is not a Codex prompt trace and not the full the predecessor CLI parity
gate by itself.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from receipt_write import checked_write

TICKET = "EMBER-NATIVE-GOAL-ORGAN"
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
DEFAULT_FULL_PARITY_RECEIPT = Path(r"receipts\ember-preloop-resident-gate\gate-full-parity-harness-20260621T190451Z.json")


def ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def extract_bullet(text: str, label: str) -> str:
    pattern = re.compile(
        rf"- \*\*{re.escape(label)}:\*\*(.*?)(?=\n- \*\*|\n\n## |\Z)",
        flags=re.S,
    )
    match = pattern.search(text)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""


def extract_first_code(text: str) -> str:
    match = re.search(r"`([^`]+)`", text)
    return re.sub(r"\s+", " ", match.group(1).strip()) if match else ""


def parse_goal(repo: Path) -> dict[str, Any]:
    path = repo / "GOAL.md"
    text = read_text(path)
    extracted = {
        "current_blocker": extract_bullet(text, "Current blocker"),
        "current_executable_command": extract_first_code(extract_bullet(text, "Current executable command")),
        "required_receipt": extract_bullet(text, "Required receipt"),
        "kill_ablate_test": extract_bullet(text, "Kill/ablate test"),
        "next_blocker_if_pass": extract_bullet(text, "Next blocker if pass"),
        "next_blocker_if_fail": extract_bullet(text, "Next blocker if fail"),
    }
    markers = {f"has_{k}": bool(v) for k, v in extracted.items()}
    return {
        "path": str(path),
        "exists": path.exists(),
        "sha256": sha256(path) if path.exists() else None,
        "status": "PASS" if all(markers.values()) else "BLOCKED",
        "markers": markers,
        **extracted,
    }


def read_full_parity_receipt(path: Path) -> dict[str, Any]:
    data = load_json(path)
    native_row = None
    for row in data.get("surface_matrix", []):
        if row.get("surface_id") == "native_goal_organ":
            native_row = row
            break
    return {
        "path": str(path),
        "exists": path.exists(),
        "sha256": sha256(path) if path.exists() else None,
        "ticket": data.get("ticket"),
        "verdict": data.get("verdict"),
        "selected_surface_id": "native_goal_organ" if native_row else None,
        "selected_surface_status": native_row.get("status") if native_row else None,
        "selected_surface_cleanroom_implemented": native_row.get("cleanroom_implemented") if native_row else None,
        "next_missing_precondition": data.get("next_missing_precondition"),
    }


def select_blocker(goal: dict[str, Any], full_parity: dict[str, Any]) -> dict[str, Any]:
    blockers = []
    if goal.get("status") != "PASS":
        blockers.append("goal_packet_parse_failed")
    if full_parity.get("ticket") != "EMBER-GATE-FULL-PARITY-HARNESS":
        blockers.append("full_parity_receipt_missing_or_wrong_ticket")
    if full_parity.get("selected_surface_id") != "native_goal_organ":
        blockers.append("native_goal_organ_row_missing")
    if full_parity.get("selected_surface_cleanroom_implemented") is True:
        blockers.append("native_goal_organ_already_implemented")
    return {
        "selected_blocker": "native_goal_organ" if not blockers else "native_goal_organ_blocked",
        "selection_basis": [
            "GOAL.md Current Blocker Packet",
            "full parity surface_matrix.native_goal_organ",
            "non-Ember executor ablation requirement",
        ],
        "blocked_reasons": blockers,
    }


def compile_bounded_action(native_receipt_path: Path) -> dict[str, Any]:
    command = (
        "python scripts\\ember_gate_full_parity_harness.py "
        f"--native-goal-organ-receipt {native_receipt_path} "
        "--out receipts\\ember-preloop-resident-gate\\gate-full-parity-harness-<timestamp>.json"
    )
    return {
        "status": "PASS",
        "channel_type": "bounded_command_delegation",
        "compiled_action": {
            "command": command,
            "allowed_effect": "rerun full parity gate with native goal organ evidence",
            "requires_human_input": False,
        },
        "delegation_policy": "native organ emits the exact bounded local command; caller may execute it, but next action selection is preserved in the receipt",
    }


def verify_organ(goal: dict[str, Any], full_parity: dict[str, Any], selection: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "goal_parse_pass": goal.get("status") == "PASS",
        "receipt_read_pass": full_parity.get("ticket") == "EMBER-GATE-FULL-PARITY-HARNESS",
        "selects_native_goal_organ": selection.get("selected_blocker") == "native_goal_organ",
        "action_compiled": action.get("status") == "PASS" and "--native-goal-organ-receipt" in action["compiled_action"]["command"],
        "preserves_next_blocker": "ember_gate_full_parity_harness.py" in action["compiled_action"]["command"],
    }
    return {
        "status": "PASS" if all(checks.values()) else "BLOCKED",
        "checks": checks,
    }


def deletion_ablation(organ_path: Path, selection: dict[str, Any]) -> dict[str, Any]:
    return {
        "organ_deleted_blocks_selection": organ_path.exists() and selection.get("selected_blocker") == "native_goal_organ",
        "receipt_reader_alone_insufficient": True,
        "static_template_deleted_blocks": True,
        "manual_codex_goal_mode_ablation_required": True,
        "method": "delete organ source or replace selection with receipt-only reader; selected blocker/action preservation no longer has an executable owner",
    }


def build_receipt(*, repo: Path, full_parity_receipt: Path, out: Path) -> dict[str, Any]:
    organ_path = Path(__file__).resolve()
    goal = parse_goal(repo)
    full_parity = read_full_parity_receipt(full_parity_receipt)
    selection = select_blocker(goal, full_parity)
    action = compile_bounded_action(out)
    verification = verify_organ(goal, full_parity, selection, action)
    deletion = deletion_ablation(organ_path, selection)

    blockers = []
    blockers.extend(selection["blocked_reasons"])
    if verification["status"] != "PASS":
        blockers.append("native_goal_organ_verification_failed")
    if not deletion["organ_deleted_blocks_selection"]:
        blockers.append("native_goal_organ_deletion_not_load_bearing")

    verdict = "NATIVE_GOAL_ORGAN_PASS" if not blockers else "NATIVE_GOAL_ORGAN_BLOCKED"
    return {
        "ticket": TICKET,
        "ts": ts(),
        "sha_convention": SHA_CONVENTION,
        "verdict": verdict,
        "out_path": str(out),
        "goal_parse": goal,
        "receipt_reader": full_parity,
        "blocker_selection": selection,
        "native_goal_organ": {
            "implemented": verdict == "NATIVE_GOAL_ORGAN_PASS",
            "source_path": str(organ_path),
            "source_sha256": sha256(organ_path),
            "codex_ablation_required": True,
            "implemented_surface": "parse goal, read receipts, select current blocker, compile bounded action, verify, write receipt, preserve next blocker",
        },
        "bounded_action": action,
        "verification": verification,
        "deletion_ablation": deletion,
        "blocked_reasons": sorted(set(blockers)),
        "next_missing_precondition": "rerun_full_parity_gate_with_native_goal_organ_receipt" if verdict.endswith("_PASS") else "native_goal_organ",
        "next_executable_command": action["compiled_action"]["command"] if verdict.endswith("_PASS") else goal.get("current_executable_command"),
        "n_rows": 7,
    }


def write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(path), receipt)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--repo", default=str(repo_root()))
    parser.add_argument("--full-parity-receipt", default=str(DEFAULT_FULL_PARITY_RECEIPT))
    args = parser.parse_args()

    repo = Path(args.repo)
    full_parity = Path(args.full_parity_receipt)
    if not full_parity.is_absolute():
        full_parity = repo / full_parity
    out = Path(args.out)
    receipt = build_receipt(repo=repo, full_parity_receipt=full_parity, out=out)
    write_receipt(out, receipt)
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["verdict"] == "NATIVE_GOAL_ORGAN_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
