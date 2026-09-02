#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import ember_gate_function_slash_commands as gate


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    audit_text = """
| Command | Description (verbatim from source) | Source file:line | Upstream brand in description? |
|---------|-------------------------------------|-----------------|-------------------------------|
| /help | 'Show help and available commands' | commands/help/index.ts:6 | no |
| /commit | 'Create a git commit' | commands/commit.ts:60 | no |
| /chrome | 'the assistant model in Chrome (Beta) settings' | commands/chrome/index.ts:6 | **yes** - the assistant model |
| /voice | 'Toggle voice mode' | commands/voice/index.ts:10 | no |
| /version | 'Print the version this session is running' | commands/version.ts:15 | no |
"""
    registry = gate.build_registry(audit_text)
    assert registry["n_registered"] == 5
    assert gate.dispatch(registry, "/help")["status"] == "EXECUTABLE_LOCAL_PLAN"
    assert gate.dispatch(registry, "/chrome")["status"] == "GOAL_SAFE_REPLACEMENT"
    assert gate.dispatch(registry, "/voice")["status"] == "GOAL_SAFE_REPLACEMENT"
    assert gate.dispatch(registry, "/version")["status"] == "TRIGGER_GATED"
    assert gate.dispatch(registry, "/missing")["status"] == "BLOCKED"
    deletion = gate.deletion_ablation(registry, {"status": "PASS"})
    assert deletion["registry_deleted_blocks_resolution"] is True
    assert deletion["static_docs_only_insufficient"] is True

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        audit = root / "legal" / "ui-parity-audit.md"
        native = root / "receipts" / "native.json"
        out = root / "receipt.json"
        write(audit, Path(gate.DEFAULT_AUDIT).read_text(encoding="utf-8", errors="replace"))
        write(
            native,
            json.dumps(
                {
                    "ticket": "EMBER-NATIVE-GOAL-ORGAN",
                    "ts": "20260621T000000Z",
                    "sha_convention": gate.SHA_CONVENTION,
                    "verdict": "NATIVE_GOAL_ORGAN_PASS",
                },
                indent=2,
            ),
        )
        receipt = gate.build_receipt(repo=root, audit=audit, native_goal_receipt=native, out=out)
        assert receipt["verdict"] == "FUNCTION_SLASH_COMMANDS_GATE_PASS"
        assert receipt["command_surface"]["registry_counts"]["n_registered"] >= 66
        assert receipt["verification"]["coverage_ratio"] == 1.0
        assert receipt["deletion_ablation"]["headless_adapter_alone_insufficient"] is True
        missing_native = gate.build_receipt(repo=root, audit=audit, native_goal_receipt=root / "missing.json", out=out)
        assert missing_native["verdict"] == "FUNCTION_SLASH_COMMANDS_GATE_BLOCKED"
        assert "native_goal_organ_receipt_missing_or_not_pass" in missing_native["blocked_reasons"]

    print("EMBER_GATE_FUNCTION_SLASH_COMMANDS_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
