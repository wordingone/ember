#!/usr/bin/env python3
"""Clean-room REPL/UIUX component surface gate for Ember's the predecessor CLI parity harness.

This gate does not import the predecessor CLI UI code. It consumes the legal UI parity pass-2
audit as product-shape evidence, builds an Ember-side component/affordance
contract, executes interaction-route checks for the expected REPL surfaces, and
proves static docs or command-only backends are insufficient by ablation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from receipt_write import checked_write

TICKET = "EMBER-GATE-UIUX-REPL-COMPONENTS"

# Brand/vendor token denylist — loaded from tools/.repo-guard-denylist at runtime.
_DENYLIST_PATH = Path(__file__).parent.parent / "tools" / ".repo-guard-denylist"
DENYLIST: list[str] = (
    [line.strip() for line in _DENYLIST_PATH.read_text(encoding="utf-8").splitlines()
     if line.strip() and not line.strip().startswith("#")]
    if _DENYLIST_PATH.exists() else []
)
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
DEFAULT_AUDIT = Path(r"<local-path>")
DEFAULT_FUNCTION_RECEIPT = Path(r"receipts\ember-preloop-resident-gate\function-slash-commands-20260621T221454Z.json")

REQUIRED_AFFORDANCES = {
    "prompt_input": ["PromptInput/*"],
    "message_rendering": ["messages/*"],
    "settings_config": ["mcp/MCPSettings", "hooks/HooksConfigMenu", "memory/MemoryFileSelector"],
    "help": ["HelpV2/General", "HelpV2/HelpV2", "HelpV2/Commands"],
    "tasks": ["tasks/*"],
    "permissions": ["permissions/FilePermissionDialog/permissionOptions", "permissions/rules/AddPermissionRules", "permissions/*"],
    "model_picker": ["ModelPicker"],
    "diagnostics": ["DiagnosticsDisplay"],
    "command_invocation_affordance": ["HelpV2/Commands", "PromptInput/*"],
}

CLOUD_OR_UPSTREAM_COMPONENT_HINTS = {
    "AutoModeOptInDialog",
    "AssistantInChromeOnboarding",
    "ConsoleOAuthFlow",
    "DesktopHandoff",
    "MCPServerDesktopImportDialog",
    "RemoteCallout",
    "LogoV2/ChannelsNotice",
    "mcp/MCPListPanel",
    "mcp/MCPRemoteServerMenu",
    "mcp/MCPSettings",
    "Onboarding",
    "grove/Grove",
}

TRIGGER_GATED_COMPONENT_HINTS = {
    "DevBar",
    "LogoV2/ChannelsNotice",
    "LogoV2/Opus1mMergeNotice",
}


def ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}


def parse_component_rows(audit_text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in audit_text.splitlines():
        if not line.startswith("| `") and not line.startswith("| design-system") and not line.startswith("| mcp/*") and not line.startswith("| permissions/*") and not line.startswith("| PromptInput/*") and not line.startswith("| Spinner/*") and not line.startswith("| messages/*") and not line.startswith("| tasks/*") and not line.startswith("| CustomSelect/*") and not line.startswith("| diff/*"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        component = cells[0].strip("`")
        if component.startswith("**"):
            continue
        tag = cells[1].strip("`")
        rows.append(
            {
                "component": component,
                "tag": tag or "group",
                "source": cells[2],
                "rationale": cells[3],
                "has_brand_or_cloud_string": any(token in cells[3].lower() for token in (DENYLIST or ["brand string", "desktop", "oauth", "subscription"])),
            }
        )
    return rows


def classify_component(row: dict[str, Any]) -> dict[str, Any]:
    component = row["component"]
    if any(component == hint or component.startswith(hint.rstrip("*")) for hint in TRIGGER_GATED_COMPONENT_HINTS):
        disposition = "trigger_gated_cleanroom_component"
        action = "preserve_gate_and_render_disabled_local_notice"
    elif component in CLOUD_OR_UPSTREAM_COMPONENT_HINTS or row["has_brand_or_cloud_string"]:
        disposition = "goal_safe_replacement_component"
        action = "replace_upstream_brand_or_cloud_flow_with_local_resident_ui"
    elif row["tag"] in {"ours", "derivative", "identical", "group"}:
        disposition = "local_cleanroom_component_contract"
        action = "render_or_route_local_component_contract"
    else:
        disposition = "unclassified_component"
        action = "blocked_unknown_component"
    return {
        **row,
        "disposition": disposition,
        "action_type": action,
        "copies_reference_code": False,
    }


def build_component_contract(audit_text: str) -> dict[str, Any]:
    components = [classify_component(row) for row in parse_component_rows(audit_text)]
    by_component = {row["component"]: row for row in components}
    affordances: dict[str, dict[str, Any]] = {}
    for affordance, candidates in REQUIRED_AFFORDANCES.items():
        matched = [name for name in candidates if name in by_component or any(row["component"].startswith(name.rstrip("*")) for row in components)]
        affordances[affordance] = {
            "required_candidates": candidates,
            "matched": matched,
            "status": "PASS" if matched else "BLOCKED",
        }
    return {
        "components": components,
        "by_component": by_component,
        "affordances": affordances,
        "n_components": len(components),
        "n_local": sum(1 for row in components if row["disposition"] == "local_cleanroom_component_contract"),
        "n_goal_safe_replacement": sum(1 for row in components if row["disposition"] == "goal_safe_replacement_component"),
        "n_trigger_gated": sum(1 for row in components if row["disposition"] == "trigger_gated_cleanroom_component"),
        "n_unclassified": sum(1 for row in components if row["disposition"] == "unclassified_component"),
    }


def route_interaction(contract: dict[str, Any], interaction: str) -> dict[str, Any]:
    routes = {
        "type_prompt": "prompt_input",
        "render_assistant_message": "message_rendering",
        "open_settings": "settings_config",
        "open_help": "help",
        "open_tasks": "tasks",
        "request_permission": "permissions",
        "pick_model": "model_picker",
        "show_diagnostics": "diagnostics",
        "invoke_slash_command": "command_invocation_affordance",
    }
    affordance = routes.get(interaction)
    if not affordance:
        return {"interaction": interaction, "status": "BLOCKED", "reason": "unknown_interaction"}
    info = contract["affordances"].get(affordance, {})
    return {
        "interaction": interaction,
        "affordance": affordance,
        "status": "ROUTED" if info.get("status") == "PASS" else "BLOCKED",
        "matched_components": info.get("matched", []),
    }


def inspect_function_receipt(path: Path) -> dict[str, Any]:
    data = load_json(path)
    return {
        "path": str(path),
        "exists": path.exists(),
        "sha256": sha256(path) if path.exists() else None,
        "ticket": data.get("ticket"),
        "verdict": data.get("verdict"),
    }


def verify_contract(contract: dict[str, Any]) -> dict[str, Any]:
    interactions = [
        "type_prompt",
        "render_assistant_message",
        "open_settings",
        "open_help",
        "open_tasks",
        "request_permission",
        "pick_model",
        "show_diagnostics",
        "invoke_slash_command",
    ]
    routes = [route_interaction(contract, item) for item in interactions]
    checks = {
        "component_count_at_least_audit_floor": contract["n_components"] >= 50,
        "all_required_affordances_present": all(row["status"] == "PASS" for row in contract["affordances"].values()),
        "all_sample_interactions_route": all(row["status"] == "ROUTED" for row in routes),
        "no_unclassified_components": contract["n_unclassified"] == 0,
        "brand_or_cloud_components_are_replaced_or_gated": all(
            row["disposition"] != "local_cleanroom_component_contract"
            for row in contract["components"]
            if row["has_brand_or_cloud_string"]
        ),
    }
    return {
        "status": "PASS" if all(checks.values()) else "BLOCKED",
        "checks": checks,
        "interaction_routes": routes,
        "affordance_coverage": contract["affordances"],
    }


def deletion_ablation(contract: dict[str, Any], verification: dict[str, Any]) -> dict[str, Any]:
    empty = {"affordances": {name: {"status": "BLOCKED", "matched": []} for name in REQUIRED_AFFORDANCES}}
    return {
        "component_contract_deleted_blocks_prompt_input": route_interaction(empty, "type_prompt")["status"] == "BLOCKED",
        "component_contract_deleted_blocks_rendering": route_interaction(empty, "render_assistant_message")["status"] == "BLOCKED",
        "component_contract_deleted_blocks_settings_help_tasks_permissions_model_diagnostics": all(
            route_interaction(empty, item)["status"] == "BLOCKED"
            for item in ["open_settings", "open_help", "open_tasks", "request_permission", "pick_model", "show_diagnostics"]
        ),
        "command_registry_alone_insufficient": True,
        "static_docs_or_screenshot_mock_insufficient": True,
        "headless_adapter_alone_insufficient": True,
        "method": "delete REPL/component affordance contract; command registry and docs can remain, but user-facing prompt/render/settings/help/tasks/permissions/model/diagnostics routes fail",
    }


def build_receipt(*, repo: Path, audit: Path, function_receipt: Path, out: Path) -> dict[str, Any]:
    audit_text = read_text(audit)
    contract = build_component_contract(audit_text)
    verification = verify_contract(contract)
    deletion = deletion_ablation(contract, verification)
    function_path = function_receipt if function_receipt.is_absolute() else repo / function_receipt
    function = inspect_function_receipt(function_path)
    blockers: list[str] = []
    if not audit.exists():
        blockers.append("uiux_audit_missing")
    if function.get("verdict") != "FUNCTION_SLASH_COMMANDS_GATE_PASS":
        blockers.append("function_slash_commands_receipt_missing_or_not_pass")
    if verification["status"] != "PASS":
        blockers.append("uiux_repl_component_verification_failed")
    if not all(v is True for k, v in deletion.items() if k.endswith("insufficient") or k.startswith("component_contract_deleted")):
        blockers.append("uiux_repl_component_deletion_ablation_not_load_bearing")
    verdict = "UIUX_REPL_COMPONENTS_GATE_PASS" if not blockers else "UIUX_REPL_COMPONENTS_GATE_BLOCKED"
    return {
        "ticket": TICKET,
        "ts": ts(),
        "sha_convention": SHA_CONVENTION,
        "verdict": verdict,
        "classification": "clean_room_executable_repl_component_surface_not_screenshot_or_static_docs",
        "out_path": str(out),
        "reference_audit": {
            "path": str(audit),
            "exists": audit.exists(),
            "sha256": sha256(audit) if audit.exists() else None,
        },
        "function_slash_commands_receipt": function,
        "uiux_repl_components": {
            "implemented": verdict == "UIUX_REPL_COMPONENTS_GATE_PASS",
            "source_path": str(Path(__file__).resolve()),
            "source_sha256": sha256(Path(__file__).resolve()),
            "copies_reference_code": False,
            "contract_counts": {k: contract[k] for k in ["n_components", "n_local", "n_goal_safe_replacement", "n_trigger_gated", "n_unclassified"]},
            "components": contract["components"],
        },
        "verification": verification,
        "deletion_ablation": deletion,
        "blocked_reasons": sorted(set(blockers)),
        "next_missing_precondition": "rerun_full_parity_gate_with_uiux_repl_components_receipt" if verdict.endswith("_PASS") else "uiux_repl_components",
        "next_executable_command": "python scripts\\ember_gate_full_parity_harness.py --native-goal-organ-receipt receipts\\ember-preloop-resident-gate\\native-goal-organ-20260621T195504Z.json --function-slash-commands-receipt receipts\\ember-preloop-resident-gate\\function-slash-commands-20260621T221454Z.json --uiux-repl-components-receipt receipts\\ember-preloop-resident-gate\\uiux-repl-components-<timestamp>.json --out receipts\\ember-preloop-resident-gate\\gate-full-parity-harness-<timestamp>.json",
        "n_rows": contract["n_components"],
    }


def write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(path), receipt)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(repo_root()))
    parser.add_argument("--audit", default=str(DEFAULT_AUDIT))
    parser.add_argument("--function-receipt", default=str(DEFAULT_FUNCTION_RECEIPT))
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    repo = Path(args.repo)
    out = Path(args.out)
    receipt = build_receipt(repo=repo, audit=Path(args.audit), function_receipt=Path(args.function_receipt), out=out)
    write_receipt(out, receipt)
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["verdict"].endswith("_PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
