#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Selftest for the the predecessor CLI clean-room resident harness inventory."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    import ember_gate_cleanroom_inventory as inventory

    with tempfile.TemporaryDirectory(prefix="ember-the predecessor CLI-inventory-") as td:
        root = Path(td)
        repo = root / "repo"
        ref_src = root / "the predecessor CLI"
        receipt_path = repo / "receipts" / "ember-preloop-resident-gate" / "preloop.json"

        _write(
            receipt_path,
            json.dumps(
                {
                    "ticket": "EMBER-PRELOOP-RESIDENT-GATE",
                    "ts": "20260621T000000Z",
                    "sha_convention": "bytes on disk as-is",
                    "verdict": "PRELOOP_RESIDENT_GATE_BLOCKED",
                    "next_missing_precondition": "clean_room_the predecessor CLI_resident_harness",
                    "next_executable_command": "python scripts\\ember_gate_cleanroom_inventory.py --out receipts\\ember-preloop-resident-gate\\gate-cleanroom-inventory-<timestamp>.json",
                    "preconditions": {
                        "clean_room_the predecessor CLI": {
                            "status": "BLOCKED",
                            "blockers": [
                                "launch_ps1_surface_missing_or_command_points_to_missing_script",
                                "clean_room_the predecessor CLI_parity_receipt_missing",
                            ],
                        }
                    },
                },
                indent=2,
            ),
        )
        _write(ref_src / "predecessor-cli.exe", "placeholder exe")
        _write(ref_src / "package.json", json.dumps({"name": "the predecessor CLI", "bin": {"ember": "src/entrypoints/cli.tsx"}}, indent=2))
        _write(ref_src / "src" / "entrypoints" / "cli.tsx", "export function main() { /* CLI entry */ }\n")
        _write(ref_src / "src" / "tools.ts", "export const tools = ['AgentTool', 'EnterPlanModeTool', 'ExitPlanModeV2Tool']\n")
        _write(ref_src / "src" / "coordinator" / "coordinatorMode.ts", "export const coordinator = 'agent worker SendMessage TaskStop'\n")
        _write(ref_src / "src" / "services" / "compact" / "compact.ts", "export const plan = 'plan_file_reference plan_mode attachment'\n")
        _write(ref_src / "legal" / "NOTICE.md", "Local fixture provenance notice.\n")

        out = root / "out.json"
        receipt = inventory.build_receipt(
            repo=repo,
            reference_root=ref_src,
            preloop_receipt=receipt_path,
            out=out,
            reference_command_definition='& "<local-path>" @args',
        )

        assert receipt["verdict"] == "THE_PREDECESSOR_CLI_CLEANROOM_INVENTORY_BLOCKED"
        assert receipt["cleanroom_pass_allowed"] is False
        assert receipt["preloop_receipt"]["verdict"] == "PRELOOP_RESIDENT_GATE_BLOCKED"
        assert receipt["launch_surface"]["reference_exe"]["exists"] is True
        assert receipt["launch_surface"]["launch_ps1"]["exists"] is False
        assert "goal_mode_parity_target_missing" in receipt["blocked_reasons"]
        assert "resident_action_channel_not_implemented" in receipt["blocked_reasons"]
        assert receipt["source_inventory"]["package_json"]["name"] == "the predecessor CLI"
        assert receipt["parity_surface_map"]["goal_parse"]["candidate_files"]
        assert receipt["parity_surface_map"]["receipt_write"]["status"] == "MISSING"
        assert receipt["next_missing_precondition"] == "the predecessor CLI_goal_mode_parity_adapter"
        assert "ember_gate_goal_mode_parity_adapter.py" in receipt["next_executable_command"]
        assert receipt["copyright_cleanroom_boundary"]["status"] == "BLOCKED"

    print("EMBER_GATE_CLEANROOM_INVENTORY_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
