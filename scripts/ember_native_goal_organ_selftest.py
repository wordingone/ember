#!/usr/bin/env python3
"""Selftest for Ember's clean-room native goal organ."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    import ember_native_goal_organ as organ

    with tempfile.TemporaryDirectory(prefix="ember-native-goal-organ-") as td:
        root = Path(td)
        repo = root / "repo"
        receipt_dir = repo / "receipts" / "ember-preloop-resident-gate"
        full_gate = receipt_dir / "full-gate.json"
        out = root / "native-goal.json"

        _write(
            repo / "GOAL.md",
            """
# Ember Goal
## Current Blocker Packet
- **Current blocker:** native_goal_organ row is missing.
- **Current executable command:** implement and run
  `python scripts/ember_native_goal_organ.py --out receipts/ember-preloop-resident-gate/native-goal-organ-<timestamp>.json`.
- **Required receipt:** `NATIVE_GOAL_ORGAN_PASS` or `NATIVE_GOAL_ORGAN_BLOCKED`.
- **Kill/ablate test:** deleting native goal organ blocks current-blocker selection.
- **Next blocker if pass:** rerun full parity gate.
- **Next blocker if fail:** continue native goal organ.
""",
        )
        _write(
            full_gate,
            json.dumps(
                {
                    "ticket": "EMBER-AVIR-CLI-FULL-PARITY-HARNESS-GATE",
                    "ts": "20260621T000000Z",
                    "sha_convention": organ.SHA_CONVENTION,
                    "verdict": "AVIR_CLI_FULL_PARITY_HARNESS_GATE_BLOCKED",
                    "surface_matrix": [
                        {
                            "surface_id": "native_goal_organ",
                            "status": "BLOCKED",
                            "cleanroom_implemented": False,
                        }
                    ],
                    "next_missing_precondition": "avir_cli_full_parity_harness_gate",
                },
                indent=2,
            ),
        )

        receipt = organ.build_receipt(repo=repo, full_parity_receipt=full_gate, out=out)
        assert receipt["verdict"] == "NATIVE_GOAL_ORGAN_PASS"
        assert receipt["native_goal_organ"]["implemented"] is True
        assert receipt["native_goal_organ"]["codex_ablation_required"] is True
        assert receipt["goal_parse"]["status"] == "PASS"
        assert receipt["receipt_reader"]["selected_surface_id"] == "native_goal_organ"
        assert receipt["blocker_selection"]["selected_blocker"] == "native_goal_organ"
        assert receipt["bounded_action"]["channel_type"] == "bounded_command_delegation"
        assert "ember_avir_cli_full_parity_harness_gate.py" in receipt["bounded_action"]["compiled_action"]["command"]
        assert "--native-goal-organ-receipt" in receipt["bounded_action"]["compiled_action"]["command"]
        assert receipt["verification"]["status"] == "PASS"
        assert receipt["deletion_ablation"]["organ_deleted_blocks_selection"] is True
        assert receipt["deletion_ablation"]["receipt_reader_alone_insufficient"] is True
        assert receipt["next_missing_precondition"] == "rerun_full_parity_gate_with_native_goal_organ_receipt"

    print("EMBER_NATIVE_GOAL_ORGAN_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
