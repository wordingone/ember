#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Selftest for the clean-room the predecessor CLI rollback/rewind gate."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    import ember_gate_rollback_rewind as gate

    with tempfile.TemporaryDirectory(prefix="ember-gate-rollback-rewind-") as td:
        root = Path(td)
        repo = root / "repo"
        receipt_dir = repo / "receipts" / "ember-preloop-resident-gate"
        receipt_store = receipt_dir / "receipt-store.json"
        out = root / "rollback-rewind.json"
        _write(
            receipt_store,
            json.dumps(
                {
                    "ticket": "EMBER-GATE-RECEIPT-STORE",
                    "ts": "20260621T000000Z",
                    "sha_convention": gate.SHA_CONVENTION,
                    "verdict": "RECEIPT_STORE_GATE_PASS",
                    "n_rows": 1,
                },
                indent=2,
            ),
        )
        receipt = gate.build_receipt(repo=repo, receipt_store_receipt=receipt_store, out=out)
        assert receipt["verdict"] == "ROLLBACK_REWIND_GATE_PASS"
        assert receipt["rollback_rewind"]["implemented"] is True
        assert receipt["rollback_rewind"]["copies_reference_code"] is False
        checks = receipt["verification"]["probe"]["checks"]
        for key in [
            "checkpoint_discovery",
            "diff_generation",
            "restore_execution",
            "checkpoint_selection",
            "rollback_accounting",
            "receipt_linkage_surface",
        ]:
            assert checks[key] is True, key
        deletion = receipt["deletion_ablation"]
        for key in [
            "rollback_store_deleted_blocks_checkpoint_discovery",
            "diff_engine_deleted_blocks_diff_generation",
            "restore_path_deleted_blocks_restore_execution",
            "checkpoint_selector_deleted_blocks_selection",
            "rollback_events_deleted_blocks_accounting",
            "manual_git_reset_insufficient",
            "static_docs_insufficient",
            "prompt_only_rewind_claim_insufficient",
            "headless_adapter_alone_insufficient",
            "manual_codex_steering_insufficient",
        ]:
            assert deletion[key] is True, key
        assert receipt["next_missing_precondition"] == "rerun_full_parity_gate_with_rollback_rewind_receipt"

        missing_receipt_store = gate.build_receipt(repo=repo, receipt_store_receipt=receipt_dir / "missing.json", out=out)
        assert missing_receipt_store["verdict"] == "ROLLBACK_REWIND_GATE_BLOCKED"
        assert "receipt_store_receipt_missing_or_not_pass" in missing_receipt_store["blocked_reasons"]

    print("EMBER_GATE_ROLLBACK_REWIND_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
