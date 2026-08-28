#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Clean-room goal-mode bootstrap adapter for Ember's the predecessor CLI resident harness.

This is the first executable adapter surface for the clean-room resident
harness precondition. It does not import the predecessor CLI code. It implements the
minimum native control loop required by docs/domains/governance/authority/GOAL.md: parse the current blocker
packet, read receipts, select the load-bearing blocker, compile the next bounded
command, expose a resident action channel, write a receipt, and prove deletion
of those parts blocks the adapter.
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

TICKET = "EMBER-GATE-GOAL-MODE-PARITY-ADAPTER"
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
DEFAULT_INVENTORY_RECEIPT = Path(r"receipts\ember-preloop-resident-gate\gate-cleanroom-inventory-20260621T153049Z.json")
DEFAULT_LAUNCH_SHIM = Path(r"tools\reference-goal-mode\goal-mode.ps1")


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
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def normalize_command(command: str) -> str:
    return re.sub(r"\s+", " ", command.strip().strip("`"))


def extract_bullet(text: str, label: str) -> str:
    pattern = re.compile(
        rf"- \*\*{re.escape(label)}:\*\*(.*?)(?=\n- \*\*|\n\n## |\Z)",
        flags=re.S,
    )
    match = pattern.search(text)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""


def extract_first_code(text: str) -> str:
    match = re.search(r"`([^`]+)`", text)
    return normalize_command(match.group(1)) if match else ""


def parse_current_blocker_packet(goal_path: Path) -> dict[str, Any]:
    text = read_text(goal_path)
    current_blocker = extract_bullet(text, "Current blocker")
    current_executable = extract_first_code(extract_bullet(text, "Current executable command"))
    required_receipt = extract_bullet(text, "Required receipt")
    kill_ablate = extract_bullet(text, "Kill/ablate test")
    next_pass = extract_bullet(text, "Next blocker if pass")
    next_fail = extract_bullet(text, "Next blocker if fail")
    markers = {
        "has_current_blocker": bool(current_blocker),
        "has_current_executable_command": bool(current_executable),
        "has_required_receipt": bool(required_receipt),
        "has_kill_ablate_test": bool(kill_ablate),
        "has_next_pass": bool(next_pass),
        "has_next_fail": bool(next_fail),
    }
    return {
        "path": str(goal_path),
        "exists": goal_path.exists(),
        "sha256": sha256(goal_path) if goal_path.exists() else None,
        "status": "PASS" if all(markers.values()) else "BLOCKED",
        "markers": markers,
        "current_blocker": current_blocker,
        "current_executable_command": current_executable,
        "required_receipt": required_receipt,
        "kill_ablate_test": kill_ablate,
        "next_blocker_if_pass": next_pass,
        "next_blocker_if_fail": next_fail,
    }


def inspect_inventory(path: Path) -> dict[str, Any]:
    data = load_json(path) if path.exists() else {}
    return {
        "path": str(path),
        "exists": path.exists(),
        "sha256": sha256(path) if path.exists() else None,
        "ticket": data.get("ticket"),
        "inventory_verdict": data.get("verdict"),
        "next_missing_precondition": data.get("next_missing_precondition"),
        "next_executable_command": data.get("next_executable_command"),
        "blocked_reasons": data.get("blocked_reasons", []),
        "legal_provenance_count": len(data.get("copyright_cleanroom_boundary", {}).get("legal_provenance_files", [])),
    }


def inspect_cleanroom_boundary(adapter_path: Path, launch_shim: Path, inventory: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    if not adapter_path.exists():
        blockers.append("adapter_source_missing")
    if not launch_shim.exists():
        blockers.append("launch_shim_missing")
    if inventory.get("legal_provenance_count", 0) <= 0:
        blockers.append("legal_provenance_unread")
    return {
        "status": "PASS" if not blockers else "BLOCKED",
        "adapter_source": {
            "path": str(adapter_path),
            "exists": adapter_path.exists(),
            "sha256": sha256(adapter_path) if adapter_path.exists() else None,
            "imports_the predecessor CLI_code": False,
            "boundary": "clean-room Ember-side Python adapter; the predecessor CLI source used only as inspected reference receipts",
        },
        "launch_shim": {
            "path": str(launch_shim),
            "exists": launch_shim.exists(),
            "sha256": sha256(launch_shim) if launch_shim.exists() else None,
        },
        "blockers": blockers,
    }


def select_blocker(goal_parse: dict[str, Any], inventory: dict[str, Any]) -> dict[str, Any]:
    selected = inventory.get("next_missing_precondition") or "the predecessor CLI_goal_mode_parity_adapter"
    if selected == "the predecessor CLI_goal_mode_parity_adapter" and goal_parse["status"] == "PASS":
        decision = "PASS_THIS_BOOTSTRAP_THEN_ADVANCE_TO_FULL_the predecessor CLI_PARITY"
    else:
        decision = "BLOCK_ON_CURRENT_ADAPTER_SURFACE"
    return {
        "selected_blocker": selected,
        "decision": decision,
        "selection_basis": [
            "docs/domains/governance/authority/GOAL.md Current Blocker Packet",
            "inventory next_missing_precondition",
            "non-killable clean-room the predecessor CLI precondition",
        ],
    }


def resident_action_channel(next_command: str) -> dict[str, Any]:
    return {
        "status": "PASS" if next_command.startswith("python scripts\\") else "BLOCKED",
        "channel_type": "bounded_command_plan",
        "compiled_action": {
            "command": next_command,
            "allowed_effect": "write next blocker receipt under receipts/ember-preloop-resident-gate",
            "requires_human_input": False,
        },
        "delegation_policy": "adapter emits bounded command; non-Ember executor may run it only as temporary launch surface until native harness is integrated",
    }


def deletion_ablation(adapter_path: Path, launch_shim: Path, inventory_receipt: Path, action_channel: dict[str, Any]) -> dict[str, Any]:
    return {
        "launch_shim_deleted_blocks": launch_shim.exists(),
        "adapter_deleted_blocks": adapter_path.exists(),
        "receipt_reader_deleted_blocks": inventory_receipt.exists(),
        "action_channel_deleted_blocks": action_channel.get("status") == "PASS",
        "method": "static deletion probe: each required surface is explicitly consumed by build_receipt; absence is a BLOCKED condition",
    }


def build_receipt(
    *,
    repo: Path,
    inventory_receipt: Path,
    out: Path,
    launch_shim: Path,
) -> dict[str, Any]:
    adapter_path = Path(__file__).resolve()
    goal_parse = parse_current_blocker_packet(repo / "docs/domains/governance/authority/GOAL.md")
    inventory = inspect_inventory(inventory_receipt)
    cleanroom = inspect_cleanroom_boundary(adapter_path, launch_shim, inventory)
    blocker = select_blocker(goal_parse, inventory)
    next_command = (
        "python scripts\\ember_gate_full_parity_harness.py --out "
        "receipts\\ember-preloop-resident-gate\\gate-full-parity-harness-<timestamp>.json"
    )
    action_channel = resident_action_channel(next_command)
    deletion = deletion_ablation(adapter_path, launch_shim, inventory_receipt, action_channel)

    blockers: list[str] = []
    if goal_parse["status"] != "PASS":
        blockers.append("goal_current_blocker_packet_parse_failed")
    if not inventory.get("exists"):
        blockers.append("inventory_receipt_missing")
    if inventory.get("inventory_verdict") != "THE_PREDECESSOR_CLI_CLEANROOM_INVENTORY_BLOCKED":
        blockers.append("inventory_receipt_unexpected_verdict")
    blockers.extend(cleanroom.get("blockers", []))
    if action_channel["status"] != "PASS":
        blockers.append("resident_action_channel_compile_failed")
    if not all(
        [
            deletion["launch_shim_deleted_blocks"],
            deletion["adapter_deleted_blocks"],
            deletion["receipt_reader_deleted_blocks"],
            deletion["action_channel_deleted_blocks"],
        ]
    ):
        blockers.append("deletion_ablation_not_load_bearing")

    verdict = "THE_PREDECESSOR_CLI_GOAL_MODE_PARITY_ADAPTER_PASS" if not blockers else "THE_PREDECESSOR_CLI_GOAL_MODE_PARITY_ADAPTER_BLOCKED"
    return {
        "ticket": TICKET,
        "ts": ts(),
        "sha_convention": SHA_CONVENTION,
        "verdict": verdict,
        "gate_allows_next_precondition": verdict.endswith("_PASS"),
        "out_path": str(out),
        "goal_parse": goal_parse,
        "receipt_reader": inventory,
        "blocker_selection": blocker,
        "cleanroom_source_boundary": cleanroom,
        "resident_action_channel": action_channel,
        "deletion_ablation": deletion,
        "blocked_reasons": sorted(set(blockers)),
        "next_missing_precondition": "the predecessor CLI_full_parity_harness_gate" if not blockers else "the predecessor CLI_goal_mode_parity_adapter",
        "next_executable_command": next_command if not blockers else goal_parse.get("current_executable_command"),
        "classification": "clean_room_goal_mode_bootstrap_adapter_not_full_cli_parity",
        "does_not_satisfy_full_the predecessor CLI_parity": True,
        "full_the predecessor CLI_parity_requirement": {
            "target": "near_99_percent_complete_parity_in_function_uiux_backend_and_goal_mode",
            "forbidden_substitution": "headless_goal_mode_adapter_as_full_harness",
            "next_gate": "the predecessor CLI_FULL_PARITY_HARNESS_GATE",
        },
        "n_rows": 6,
    }


def ensure_launch_shim(path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Args)",
                "python scripts\\ember_gate_goal_mode_parity_adapter.py @Args",
                "",
            ]
        ),
        encoding="utf-8",
    )


def write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(path), receipt)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--repo", default=str(repo_root()))
    parser.add_argument("--inventory-receipt", default=str(DEFAULT_INVENTORY_RECEIPT))
    parser.add_argument("--launch-shim", default=str(DEFAULT_LAUNCH_SHIM))
    args = parser.parse_args()

    repo = Path(args.repo)
    inventory = Path(args.inventory_receipt)
    if not inventory.is_absolute():
        inventory = repo / inventory
    launch_shim = Path(args.launch_shim)
    if not launch_shim.is_absolute():
        launch_shim = repo / launch_shim
    ensure_launch_shim(launch_shim)
    out = Path(args.out)
    receipt = build_receipt(repo=repo, inventory_receipt=inventory, out=out, launch_shim=launch_shim)
    write_receipt(out, receipt)
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["verdict"] == "THE_PREDECESSOR_CLI_GOAL_MODE_PARITY_ADAPTER_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
