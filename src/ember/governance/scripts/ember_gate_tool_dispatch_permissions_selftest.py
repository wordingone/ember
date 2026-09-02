#!/usr/bin/env python3
"""Selftest for the clean-room the predecessor CLI tool dispatch permissions gate."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    import ember_gate_tool_dispatch_permissions as gate

    with tempfile.TemporaryDirectory(prefix="ember-gate-tool-dispatch-") as td:
        root = Path(td)
        repo = root / "repo"
        receipt_dir = repo / "receipts" / "ember-preloop-resident-gate"
        hook = receipt_dir / "hook-runner.json"
        out = root / "tool-dispatch.json"
        _write(
            hook,
            json.dumps(
                {
                    "ticket": "EMBER-GATE-HOOK-RUNNER",
                    "ts": "20260621T000000Z",
                    "sha_convention": gate.SHA_CONVENTION,
                    "verdict": "HOOK_RUNNER_GATE_PASS",
                },
                indent=2,
            ),
        )
        receipt = gate.build_receipt(repo=repo, hook_receipt=hook, out=out)
        assert receipt["verdict"] == "TOOL_DISPATCH_PERMISSIONS_GATE_PASS"
        assert receipt["tool_dispatch_permissions"]["implemented"] is True
        assert receipt["tool_dispatch_permissions"]["copies_reference_code"] is False
        checks = receipt["verification"]["probe"]["checks"]
        for key in [
            "registry_lookup_allowed_tool",
            "permission_prompt_recorded",
            "deny_rule_blocks_destructive_tool",
            "unknown_tool_fail_closed",
            "tool_execution_handoff",
            "verifier_handoff_recorded",
            "rollback_handoff_recorded",
            "lifecycle_accounted",
        ]:
            assert checks[key] is True, key
        deletion = receipt["deletion_ablation"]
        for key in [
            "tool_registry_deleted_blocks_lookup",
            "permission_policy_deleted_blocks_prompt_and_decision",
            "dispatcher_deleted_blocks_execution_handoff",
            "verifier_hook_deleted_blocks_verification_accounting",
            "rollback_hook_deleted_blocks_reversal_accounting",
            "static_tool_list_insufficient",
            "docs_only_permission_policy_insufficient",
            "always_allow_runner_insufficient",
            "prompt_only_route_insufficient",
            "headless_adapter_alone_insufficient",
            "manual_codex_steering_insufficient",
        ]:
            assert deletion[key] is True, key
        assert receipt["next_missing_precondition"] == "rerun_full_parity_gate_with_tool_dispatch_permissions_receipt"

        missing_hook = gate.build_receipt(repo=repo, hook_receipt=receipt_dir / "missing.json", out=out)
        assert missing_hook["verdict"] == "TOOL_DISPATCH_PERMISSIONS_GATE_BLOCKED"
        assert "hook_runner_receipt_missing_or_not_pass" in missing_hook["blocked_reasons"]

    print("EMBER_GATE_TOOL_DISPATCH_PERMISSIONS_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
