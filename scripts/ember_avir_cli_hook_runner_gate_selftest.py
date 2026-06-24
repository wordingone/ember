#!/usr/bin/env python3
"""Selftest for the clean-room avir-cli hook runner gate."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    import ember_avir_cli_hook_runner_gate as gate

    with tempfile.TemporaryDirectory(prefix="ember-avir-hook-runner-") as td:
        root = Path(td)
        repo = root / "repo"
        receipt_dir = repo / "receipts" / "ember-preloop-resident-gate"
        process = receipt_dir / "process-supervision.json"
        out = root / "hook-runner.json"
        _write(
            process,
            json.dumps(
                {
                    "ticket": "EMBER-AVIR-CLI-PROCESS-SUPERVISION-GATE",
                    "ts": "20260621T000000Z",
                    "sha_convention": gate.SHA_CONVENTION,
                    "verdict": "PROCESS_SUPERVISION_GATE_PASS",
                },
                indent=2,
            ),
        )
        receipt = gate.build_receipt(repo=repo, process_receipt=process, out=out)
        assert receipt["verdict"] == "HOOK_RUNNER_GATE_PASS"
        assert receipt["hook_runner"]["implemented"] is True
        assert receipt["hook_runner"]["copies_avir_code"] is False
        checks = receipt["verification"]["probe"]["checks"]
        assert checks["read_only_hook_allowed"] is True
        assert checks["mutation_hook_denied"] is True
        assert checks["forbidden_result_denied"] is True
        assert checks["unknown_event_fail_closed"] is True
        assert checks["lifecycle_accounted"] is True
        assert len(receipt["verification"]["probe"]["lifecycle"]) == 4
        deletion = receipt["deletion_ablation"]
        for key in [
            "hook_runner_deleted_blocks_event_dispatch",
            "policy_engine_deleted_blocks_read_only_enforcement",
            "permission_denial_deleted_blocks_fail_closed_unknown_event",
            "lifecycle_log_deleted_blocks_receipt_accounting",
            "static_hook_list_insufficient",
            "docs_only_policy_insufficient",
            "permissive_callback_runner_insufficient",
            "headless_adapter_alone_insufficient",
            "manual_codex_steering_insufficient",
        ]:
            assert deletion[key] is True, key
        assert receipt["next_missing_precondition"] == "rerun_full_parity_gate_with_hook_runner_receipt"

        missing_process = gate.build_receipt(repo=repo, process_receipt=receipt_dir / "missing.json", out=out)
        assert missing_process["verdict"] == "HOOK_RUNNER_GATE_BLOCKED"
        assert "process_supervision_receipt_missing_or_not_pass" in missing_process["blocked_reasons"]

    print("EMBER_AVIR_CLI_HOOK_RUNNER_GATE_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
