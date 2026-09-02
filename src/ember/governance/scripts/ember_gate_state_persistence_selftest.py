#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Selftest for the clean-room the predecessor CLI state persistence gate."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    import ember_gate_state_persistence as gate

    with tempfile.TemporaryDirectory(prefix="ember-gate-state-persistence-") as td:
        root = Path(td)
        repo = root / "repo"
        receipt_dir = repo / "receipts" / "ember-preloop-resident-gate"
        tool = receipt_dir / "tool-dispatch.json"
        out = root / "state-persistence.json"
        _write(
            tool,
            json.dumps(
                {
                    "ticket": "EMBER-GATE-TOOL-DISPATCH-PERMISSIONS",
                    "ts": "20260621T000000Z",
                    "sha_convention": gate.SHA_CONVENTION,
                    "verdict": "TOOL_DISPATCH_PERMISSIONS_GATE_PASS",
                },
                indent=2,
            ),
        )
        receipt = gate.build_receipt(repo=repo, tool_receipt=tool, out=out)
        assert receipt["verdict"] == "STATE_PERSISTENCE_GATE_PASS"
        assert receipt["state_persistence"]["implemented"] is True
        assert receipt["state_persistence"]["copies_reference_code"] is False
        checks = receipt["verification"]["probe"]["checks"]
        for key in [
            "session_write_read_resume",
            "durable_memory_write_read",
            "compaction_persists",
            "settings_reload",
            "model_account_reload",
            "lifecycle_accounted",
            "file_backed_not_memory_only",
        ]:
            assert checks[key] is True, key
        deletion = receipt["deletion_ablation"]
        for key in [
            "state_store_deleted_blocks_write",
            "state_store_deleted_blocks_read",
            "state_store_deleted_blocks_resume",
            "compaction_deleted_blocks_memory_consolidation",
            "settings_store_deleted_blocks_reload",
            "model_account_store_deleted_blocks_reload",
            "lifecycle_log_deleted_blocks_state_accounting",
            "transient_in_memory_dict_insufficient",
            "docs_only_state_policy_insufficient",
            "prompt_only_memory_insufficient",
            "headless_adapter_alone_insufficient",
            "manual_codex_steering_insufficient",
        ]:
            assert deletion[key] is True, key
        assert receipt["next_missing_precondition"] == "rerun_full_parity_gate_with_state_persistence_receipt"

        missing_tool = gate.build_receipt(repo=repo, tool_receipt=receipt_dir / "missing.json", out=out)
        assert missing_tool["verdict"] == "STATE_PERSISTENCE_GATE_BLOCKED"
        assert "tool_dispatch_permissions_receipt_missing_or_not_pass" in missing_tool["blocked_reasons"]

    print("EMBER_GATE_STATE_PERSISTENCE_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
