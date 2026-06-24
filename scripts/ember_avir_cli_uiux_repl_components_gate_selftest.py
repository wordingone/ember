#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import ember_avir_cli_uiux_repl_components_gate as gate


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    mini = """
| Component | Tag | Source file:line | Rationale |
|-----------|-----|------------------|-----------|
| `screens/REPL` | `derivative` | screens/REPL.tsx:1 | Main REPL screen |
| `DiagnosticsDisplay` | `ours` | components/DiagnosticsDisplay.tsx:17 | avir `/diag` command output renderer |
| `ModelPicker` | `derivative` | components/ModelPicker.tsx:39 | local model picker |
| `HelpV2/General` | `derivative` | components/HelpV2/General.tsx:9 | help |
| `HelpV2/HelpV2` | `derivative` | components/HelpV2/HelpV2.tsx:1 | help |
| `HelpV2/Commands` | `identical` | components/HelpV2/Commands.tsx:1 | commands |
| `hooks/HooksConfigMenu` | `identical` | components/hooks/HooksConfigMenu.tsx:354 | Brand string: ask Claude. |
| `mcp/MCPSettings` | `identical` | components/mcp/MCPSettings.tsx:210 | Brand string: claude.ai |
| `memory/MemoryFileSelector` | `derivative` | components/memory/MemoryFileSelector.tsx:1 | memory |
| `permissions/FilePermissionDialog/permissionOptions` | `derivative` | components/permissions/FilePermissionDialog/permissionOptions.tsx:1 | permissions |
| `permissions/rules/AddPermissionRules` | `derivative` | components/permissions/rules/AddPermissionRules.tsx:1 | permissions |
| PromptInput/* (8 files) | `identical` | components/PromptInput/*.tsx | Prompt input subsystem |
| messages/* (45 files) | `identical` | components/messages/**/*.tsx | Message rendering subsystem |
| tasks/* (14 files) | `identical` | components/tasks/**/*.tsx | Task management UI |
"""
    contract = gate.build_component_contract(mini)
    assert contract["affordances"]["prompt_input"]["status"] == "PASS"
    assert gate.route_interaction(contract, "type_prompt")["status"] == "ROUTED"
    assert gate.route_interaction(contract, "show_diagnostics")["status"] == "ROUTED"
    assert gate.route_interaction(contract, "missing")["status"] == "BLOCKED"
    verification = gate.verify_contract(contract)
    assert verification["checks"]["all_required_affordances_present"] is True
    deletion = gate.deletion_ablation(contract, verification)
    assert deletion["command_registry_alone_insufficient"] is True
    assert deletion["component_contract_deleted_blocks_rendering"] is True

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        audit = root / "uiux.md"
        function_receipt = root / "function.json"
        out = root / "receipt.json"
        write(audit, Path(gate.DEFAULT_AUDIT).read_text(encoding="utf-8", errors="replace"))
        write(
            function_receipt,
            json.dumps(
                {
                    "ticket": "EMBER-AVIR-CLI-FUNCTION-SLASH-COMMANDS-GATE",
                    "ts": "20260621T000000Z",
                    "sha_convention": gate.SHA_CONVENTION,
                    "verdict": "FUNCTION_SLASH_COMMANDS_GATE_PASS",
                },
                indent=2,
            ),
        )
        receipt = gate.build_receipt(repo=root, audit=audit, function_receipt=function_receipt, out=out)
        assert receipt["verdict"] == "UIUX_REPL_COMPONENTS_GATE_PASS"
        assert receipt["uiux_repl_components"]["contract_counts"]["n_components"] >= 50
        assert receipt["verification"]["checks"]["all_sample_interactions_route"] is True
        assert receipt["deletion_ablation"]["static_docs_or_screenshot_mock_insufficient"] is True
        missing_function = gate.build_receipt(repo=root, audit=audit, function_receipt=root / "missing.json", out=out)
        assert missing_function["verdict"] == "UIUX_REPL_COMPONENTS_GATE_BLOCKED"
        assert "function_slash_commands_receipt_missing_or_not_pass" in missing_function["blocked_reasons"]

    print("EMBER_AVIR_CLI_UIUX_REPL_COMPONENTS_GATE_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
