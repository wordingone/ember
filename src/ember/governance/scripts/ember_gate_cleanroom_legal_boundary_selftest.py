#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Selftest for the clean-room legal/provenance boundary gate."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    import ember_gate_cleanroom_legal_boundary as gate

    with tempfile.TemporaryDirectory(prefix="ember-gate-legal-boundary-") as td:
        root = Path(td)
        repo = root / "repo"
        reference_root = root / "predecessor-cli-reference"
        gate.write_reference_fixture(reference_root)
        receipt_dir = repo / "receipts" / "ember-preloop-resident-gate"
        communication = receipt_dir / "communication.json"
        out = root / "legal.json"
        _write(
            communication,
            json.dumps(
                {
                    "ticket": "EMBER-GATE-COMMUNICATION-MAILBOX-COMPUTER-USE",
                    "ts": "20260622T000000Z",
                    "sha_convention": gate.SHA_CONVENTION,
                    "verdict": "COMMUNICATION_MAILBOX_COMPUTER_USE_GATE_PASS",
                    "n_rows": 1,
                },
                indent=2,
            ),
        )
        receipt = gate.build_receipt(repo=repo, reference_root=reference_root, communication_receipt=communication, out=out)
        assert receipt["verdict"] == "CLEANROOM_LEGAL_BOUNDARY_GATE_PASS"
        assert receipt["cleanroom_legal_boundary"]["implemented"] is True
        assert receipt["cleanroom_legal_boundary"]["copies_reference_code"] is False
        checks = receipt["verification"]["probe"]["checks"]
        for key in [
            "required_legal_files_available",
            "provenance_hash_checks",
            "file_inventory_accounting",
            "surface_provenance_linkage",
            "copy_boundary_reference_only",
            "receipt_visible_legal_rows",
        ]:
            assert checks[key] is True, key
        deletion = receipt["deletion_ablation"]
        for key in [
            "legal_file_discovery_deleted_blocks_legal_files",
            "provenance_deleted_blocks_hash_checks",
            "copy_boundary_deleted_blocks_copy_enforcement",
            "surface_linkage_deleted_blocks_per_surface_provenance",
            "inventory_deleted_blocks_file_inventory_accounting",
            "legal_events_deleted_blocks_receipt_rows",
            "static_policy_text_insufficient",
            "handwaved_cleanroom_claim_insufficient",
            "copied_the predecessor CLI_implementation_insufficient",
            "prompt_only_provenance_narration_insufficient",
            "headless_adapter_alone_insufficient",
            "manual_codex_steering_insufficient",
        ]:
            assert deletion[key] is True, key
        assert receipt["next_missing_precondition"] == "rerun_full_parity_gate_with_cleanroom_legal_boundary_receipt"

        missing_communication = gate.build_receipt(
            repo=repo,
            reference_root=reference_root,
            communication_receipt=receipt_dir / "missing.json",
            out=out,
        )
        assert missing_communication["verdict"] == "CLEANROOM_LEGAL_BOUNDARY_GATE_BLOCKED"
        assert "communication_mailbox_computer_use_receipt_missing_or_not_pass" in missing_communication["blocked_reasons"]

    print("EMBER_GATE_CLEANROOM_LEGAL_BOUNDARY_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
