#!/usr/bin/env python3
"""Selftest for the avir-cli clean-room resident harness inventory."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    import ember_avir_cli_cleanroom_inventory as inventory

    with tempfile.TemporaryDirectory(prefix="ember-avir-cli-inventory-") as td:
        root = Path(td)
        repo = root / "repo"
        avir = root / "avir-cli"
        receipt_path = repo / "receipts" / "ember-preloop-resident-gate" / "preloop.json"

        _write(
            receipt_path,
            json.dumps(
                {
                    "ticket": "EMBER-PRELOOP-RESIDENT-GATE",
                    "ts": "20260621T000000Z",
                    "sha_convention": "bytes on disk as-is",
                    "verdict": "PRELOOP_RESIDENT_GATE_BLOCKED",
                    "next_missing_precondition": "clean_room_avir_cli_resident_harness",
                    "next_executable_command": "python scripts\\ember_avir_cli_cleanroom_inventory.py --out receipts\\ember-preloop-resident-gate\\avir-cli-cleanroom-inventory-<timestamp>.json",
                    "preconditions": {
                        "clean_room_avir_cli": {
                            "status": "BLOCKED",
                            "blockers": [
                                "avir_ps1_surface_missing_or_command_points_to_missing_script",
                                "clean_room_avir_cli_parity_receipt_missing",
                            ],
                        }
                    },
                },
                indent=2,
            ),
        )
        _write(avir / "avir.exe", "placeholder exe")
        _write(avir / "package.json", json.dumps({"name": "avir-cli", "bin": {"avir": "src/entrypoints/cli.tsx"}}, indent=2))
        _write(avir / "src" / "entrypoints" / "cli.tsx", "export function main() { /* CLI entry */ }\n")
        _write(avir / "src" / "tools.ts", "export const tools = ['AgentTool', 'EnterPlanModeTool', 'ExitPlanModeV2Tool']\n")
        _write(avir / "src" / "coordinator" / "coordinatorMode.ts", "export const coordinator = 'agent worker SendMessage TaskStop'\n")
        _write(avir / "src" / "services" / "compact" / "compact.ts", "export const plan = 'plan_file_reference plan_mode attachment'\n")
        _write(avir / "legal" / "NOTICE.md", "Local fixture provenance notice.\n")

        out = root / "out.json"
        receipt = inventory.build_receipt(
            repo=repo,
            avir_root=avir,
            preloop_receipt=receipt_path,
            out=out,
            avir_command_definition='& "<local-path>" @args',
        )

        assert receipt["verdict"] == "AVIR_CLI_CLEANROOM_INVENTORY_BLOCKED"
        assert receipt["cleanroom_pass_allowed"] is False
        assert receipt["preloop_receipt"]["verdict"] == "PRELOOP_RESIDENT_GATE_BLOCKED"
        assert receipt["launch_surface"]["avir_exe"]["exists"] is True
        assert receipt["launch_surface"]["avir_ps1"]["exists"] is False
        assert "goal_mode_parity_target_missing" in receipt["blocked_reasons"]
        assert "resident_action_channel_not_implemented" in receipt["blocked_reasons"]
        assert receipt["source_inventory"]["package_json"]["name"] == "avir-cli"
        assert receipt["parity_surface_map"]["goal_parse"]["candidate_files"]
        assert receipt["parity_surface_map"]["receipt_write"]["status"] == "MISSING"
        assert receipt["next_missing_precondition"] == "avir_cli_goal_mode_parity_adapter"
        assert "ember_avir_cli_goal_mode_parity_adapter.py" in receipt["next_executable_command"]
        assert receipt["copyright_cleanroom_boundary"]["status"] == "BLOCKED"

    print("EMBER_AVIR_CLI_CLEANROOM_INVENTORY_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
