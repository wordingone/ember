#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Selftest for the clean-room the predecessor CLI goal-mode bootstrap adapter."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    import ember_gate_goal_mode_parity_adapter as adapter

    with tempfile.TemporaryDirectory(prefix="ember-gate-goal-parity-") as td:
        root = Path(td)
        repo = root / "repo"
        inv = repo / "receipts" / "ember-preloop-resident-gate" / "inventory.json"
        goal = repo / "docs/domains/governance/authority/GOAL.md"
        shim = repo / "tools" / "reference-goal-mode" / "launch.ps1"

        _write(
            goal,
            """
# Ember Breakthrough Loop
## Current Blocker Packet
- **Current blocker:** inventory receipt blocked on the predecessor CLI_goal_mode_parity_adapter.
- **Current executable command:** implement and run
  `python scripts\\ember_gate_goal_mode_parity_adapter.py --out receipts\\ember-preloop-resident-gate\\gate-goal-mode-parity-adapter-<timestamp>.json`.
- **Required receipt:** `THE_PREDECESSOR_CLI_GOAL_MODE_PARITY_ADAPTER_PASS`.
- **Kill/ablate test:** deleting the launch shim or resident action channel blocks.
- **Next blocker if pass:** complete near-99% clean-room the predecessor CLI function/UI/UX/backend parity with Codex goal mode transplanted.
- **Next blocker if fail:** continue exact missing adapter surface.
""",
        )
        _write(
            inv,
            json.dumps(
                {
                    "ticket": "EMBER-GATE-CLEANROOM-INVENTORY",
                    "ts": "20260621T000000Z",
                    "sha_convention": "bytes on disk as-is",
                    "verdict": "THE_PREDECESSOR_CLI_CLEANROOM_INVENTORY_BLOCKED",
                    "next_missing_precondition": "the predecessor CLI_goal_mode_parity_adapter",
                    "next_executable_command": "python scripts\\ember_gate_goal_mode_parity_adapter.py --out receipts\\ember-preloop-resident-gate\\gate-goal-mode-parity-adapter-<timestamp>.json",
                    "blocked_reasons": [
                        "goal_mode_parity_target_missing",
                        "resident_action_channel_not_implemented",
                    ],
                    "copyright_cleanroom_boundary": {
                        "legal_provenance_files": [
                            {"path": "legal/origin.md", "sha256": "a" * 64}
                        ]
                    },
                },
                indent=2,
            ),
        )
        _write(
            shim,
            """
param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Args)
python scripts\\ember_gate_goal_mode_parity_adapter.py @Args
""",
        )

        out = root / "receipt.json"
        receipt = adapter.build_receipt(
            repo=repo,
            inventory_receipt=inv,
            out=out,
            launch_shim=shim,
        )

        assert receipt["verdict"] == "THE_PREDECESSOR_CLI_GOAL_MODE_PARITY_ADAPTER_PASS"
        assert receipt["cleanroom_source_boundary"]["status"] == "PASS"
        assert receipt["goal_parse"]["current_executable_command"].startswith("python scripts\\ember_gate_goal_mode_parity_adapter.py")
        assert receipt["receipt_reader"]["inventory_verdict"] == "THE_PREDECESSOR_CLI_CLEANROOM_INVENTORY_BLOCKED"
        assert receipt["blocker_selection"]["selected_blocker"] == "the predecessor CLI_goal_mode_parity_adapter"
        assert "ember_gate_full_parity_harness.py" in receipt["next_executable_command"]
        assert receipt["resident_action_channel"]["status"] == "PASS"
        assert receipt["deletion_ablation"]["launch_shim_deleted_blocks"] is True
        assert receipt["deletion_ablation"]["adapter_deleted_blocks"] is True
        assert receipt["deletion_ablation"]["receipt_reader_deleted_blocks"] is True
        assert receipt["gate_allows_next_precondition"] is True
        assert receipt["next_missing_precondition"] == "the predecessor CLI_full_parity_harness_gate"
        assert receipt["does_not_satisfy_full_the predecessor CLI_parity"] is True
        assert receipt["full_the predecessor CLI_parity_requirement"]["target"] == "near_99_percent_complete_parity_in_function_uiux_backend_and_goal_mode"

    print("EMBER_GATE_GOAL_MODE_PARITY_ADAPTER_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
