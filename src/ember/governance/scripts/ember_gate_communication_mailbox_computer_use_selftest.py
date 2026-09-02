#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Selftest for the clean-room communication/mailbox/computer-use gate."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    import ember_gate_communication_mailbox_computer_use as gate

    with tempfile.TemporaryDirectory(prefix="ember-gate-communication-") as td:
        root = Path(td)
        repo = root / "repo"
        receipt_dir = repo / "receipts" / "ember-preloop-resident-gate"
        rollback = receipt_dir / "rollback-rewind.json"
        out = root / "communication.json"
        _write(
            rollback,
            json.dumps(
                {
                    "ticket": "EMBER-GATE-ROLLBACK-REWIND",
                    "ts": "20260622T000000Z",
                    "sha_convention": gate.SHA_CONVENTION,
                    "verdict": "ROLLBACK_REWIND_GATE_PASS",
                    "n_rows": 1,
                },
                indent=2,
            ),
        )
        receipt = gate.build_receipt(repo=repo, rollback_receipt=rollback, out=out)
        assert receipt["verdict"] == "COMMUNICATION_MAILBOX_COMPUTER_USE_GATE_PASS"
        assert receipt["communication_mailbox_computer_use"]["implemented"] is True
        assert receipt["communication_mailbox_computer_use"]["copies_reference_code"] is False
        checks = receipt["verification"]["probe"]["checks"]
        for key in [
            "mailbox_identity",
            "user_facing_communication",
            "founder_communication",
            "inbound_message_route",
            "fail_closed_unknown_recipient",
            "reachability_status_accounting",
            "computer_use_route",
            "receipt_visible_accounting",
        ]:
            assert checks[key] is True, key
        deletion = receipt["deletion_ablation"]
        for key in [
            "identity_deleted_blocks_message_construction",
            "founder_addressing_deleted_blocks_route_selection",
            "reachability_deleted_blocks_status_accounting",
            "computer_use_route_deleted_blocks_computer_use",
            "communication_events_deleted_blocks_receipt_rows",
            "static_docs_insufficient",
            "mock_only_chat_text_insufficient",
            "live_codex_mailbox_polling_insufficient",
            "prompt_only_coordination_claim_insufficient",
            "headless_adapter_alone_insufficient",
            "manual_codex_steering_insufficient",
        ]:
            assert deletion[key] is True, key
        assert receipt["next_missing_precondition"] == "rerun_full_parity_gate_with_communication_mailbox_computer_use_receipt"

        missing_rollback = gate.build_receipt(repo=repo, rollback_receipt=receipt_dir / "missing.json", out=out)
        assert missing_rollback["verdict"] == "COMMUNICATION_MAILBOX_COMPUTER_USE_GATE_BLOCKED"
        assert "rollback_rewind_receipt_missing_or_not_pass" in missing_rollback["blocked_reasons"]

    print("EMBER_GATE_COMMUNICATION_MAILBOX_COMPUTER_USE_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
