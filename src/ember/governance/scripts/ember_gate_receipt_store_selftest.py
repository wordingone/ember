#!/usr/bin/env python3
"""Selftest for the clean-room the predecessor CLI receipt store gate."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    import ember_gate_receipt_store as gate

    with tempfile.TemporaryDirectory(prefix="ember-gate-receipt-store-") as td:
        root = Path(td)
        repo = root / "repo"
        receipt_dir = repo / "receipts" / "ember-preloop-resident-gate"
        state = receipt_dir / "state-persistence.json"
        out = root / "receipt-store.json"
        _write(
            state,
            json.dumps(
                {
                    "ticket": "EMBER-GATE-STATE-PERSISTENCE",
                    "ts": "20260621T000000Z",
                    "sha_convention": gate.SHA_CONVENTION,
                    "verdict": "STATE_PERSISTENCE_GATE_PASS",
                },
                indent=2,
            ),
        )
        receipt = gate.build_receipt(repo=repo, state_receipt=state, out=out)
        assert receipt["verdict"] == "RECEIPT_STORE_GATE_PASS"
        assert receipt["receipt_store"]["implemented"] is True
        assert receipt["receipt_store"]["copies_reference_code"] is False
        checks = receipt["verification"]["probe"]["checks"]
        for key in [
            "fail_closed_write_validates_schema",
            "malformed_receipt_rejected_and_removed",
            "read_validates_schema",
            "event_log_append_read",
            "replay_hook_executes",
            "evidence_lookup_finds_ticket",
            "receipt_visible_accounting",
        ]:
            assert checks[key] is True, key
        deletion = receipt["deletion_ablation"]
        for key in [
            "receipt_store_deleted_blocks_fail_closed_write",
            "receipt_store_deleted_blocks_read",
            "schema_validator_deleted_blocks_invalid_receipt_rejection",
            "event_log_deleted_blocks_append_read",
            "replay_hook_deleted_blocks_replay",
            "evidence_lookup_deleted_blocks_ticket_search",
            "loose_json_dump_insufficient",
            "docs_only_receipt_policy_insufficient",
            "non_validating_logger_insufficient",
            "prompt_only_evidence_trail_insufficient",
            "headless_adapter_alone_insufficient",
            "manual_codex_steering_insufficient",
        ]:
            assert deletion[key] is True, key
        assert receipt["next_missing_precondition"] == "rerun_full_parity_gate_with_receipt_store_receipt"

        missing_state = gate.build_receipt(repo=repo, state_receipt=receipt_dir / "missing.json", out=out)
        assert missing_state["verdict"] == "RECEIPT_STORE_GATE_BLOCKED"
        assert "state_persistence_receipt_missing_or_not_pass" in missing_state["blocked_reasons"]

    print("EMBER_GATE_RECEIPT_STORE_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
