#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Clean-room full parity harness gate for Ember's the predecessor CLI resident body.

This gate is intentionally fail-closed. The previous goal-mode adapter proves a
bootstrap action channel only; this script records the full product/harness
surface that must exist before RLM/iGRPO resident training may continue.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# issue2015 exact-local-import:src/ember/governance/scripts/receipt_write.py
import importlib.util as _ember_66ee9e91637922dc_importlib
import sys as _ember_66ee9e91637922dc_sys
from pathlib import Path as _ember_66ee9e91637922dc_Path
_ember_66ee9e91637922dc_path = _ember_66ee9e91637922dc_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_write.py')
if not _ember_66ee9e91637922dc_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/receipt_write.py')
_ember_66ee9e91637922dc_aliases = ('_ember_issue2015_66ee9e91637922dc', 'receipt_write', 'scripts.receipt_write')
_ember_66ee9e91637922dc_existing = []
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_candidate = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_candidate is not None and all(_ember_66ee9e91637922dc_candidate is not item for item in _ember_66ee9e91637922dc_existing):
        _ember_66ee9e91637922dc_existing.append(_ember_66ee9e91637922dc_candidate)
if len(_ember_66ee9e91637922dc_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/receipt_write.py')
if _ember_66ee9e91637922dc_existing:
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_existing[0]
    _ember_66ee9e91637922dc_observed = getattr(_ember_66ee9e91637922dc_module, '__file__', None)
    if _ember_66ee9e91637922dc_observed is None or _ember_66ee9e91637922dc_Path(_ember_66ee9e91637922dc_observed).resolve() != _ember_66ee9e91637922dc_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/receipt_write.py')
else:
    _ember_66ee9e91637922dc_spec = _ember_66ee9e91637922dc_importlib.spec_from_file_location('_ember_issue2015_66ee9e91637922dc', _ember_66ee9e91637922dc_path)
    if _ember_66ee9e91637922dc_spec is None or _ember_66ee9e91637922dc_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_importlib.module_from_spec(_ember_66ee9e91637922dc_spec)
    for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
        _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
        if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
        _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
    try:
        _ember_66ee9e91637922dc_spec.loader.exec_module(_ember_66ee9e91637922dc_module)
    except BaseException:
        for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
            if _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias) is _ember_66ee9e91637922dc_module:
                _ember_66ee9e91637922dc_sys.modules.pop(_ember_66ee9e91637922dc_alias, None)
        raise
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
checked_write = getattr(_ember_66ee9e91637922dc_module, 'checked_write')
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py

TICKET = "EMBER-GATE-FULL-PARITY-HARNESS"
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
DEFAULT_INVENTORY_RECEIPT = Path(r"receipts\ember-preloop-resident-gate\gate-cleanroom-inventory-20260621T153049Z.json")
DEFAULT_BOOTSTRAP_RECEIPT = Path(r"receipts\ember-preloop-resident-gate\gate-goal-mode-parity-adapter-20260621T155157Z.json")
REAL_reference_OBSERVATION_PASS = "REAL_PREDECESSOR_CLI_UIUX_AX_OBSERVATION_PASS"

SURFACE_SPECS: list[dict[str, Any]] = [
    {
        "surface_id": "function_slash_commands",
        "name": "Slash command surface",
        "reference_evidence": ["legal/ui-parity-audit.md", "src/commands.ts", "src/commands"],
        "required_cleanroom_surface": "Ember-visible command registry with near-complete the predecessor CLI command behavior and goal-safe replacements for cloud-only/upstream-branded commands.",
    },
    {
        "surface_id": "uiux_repl_components",
        "name": "REPL UI and interaction components",
        "reference_evidence": ["legal/ui-parity-audit-pass2.md", "src/screens/REPL.tsx", "src/components"],
        "required_cleanroom_surface": "Native Ember REPL/tool surface with prompt input, message rendering, settings, help, tasks, permissions, model picker, and diagnostics parity.",
    },
    {
        "surface_id": "backend_coordinator_agents",
        "name": "Coordinator, agent, and delegation backend",
        "reference_evidence": ["legal/ui-parity-audit-pass3.md", "src/coordinator", "src/tools/AgentTool", "src/tasks"],
        "required_cleanroom_surface": "Resident local agent orchestration, delegation, task panels, built-in agent definitions, and worker lifecycle without proprietary copy-through.",
    },
    {
        "surface_id": "launch_packaging",
        "name": "Launch, packaging, and executable entrypoints",
        "reference_evidence": ["package.json", "predecessor-cli.exe", "src/entrypoints/cli.tsx"],
        "required_cleanroom_surface": "Working ember launch path, package/build contract, and Windows entrypoint that does not point at a missing launch.ps1.",
    },
    {
        "surface_id": "process_supervision",
        "name": "Process supervision and cleanup",
        "reference_evidence": ["native/windows-job-object", "windows_job_object.win32-x64-msvc.node", "src"],
        "required_cleanroom_surface": "Windows process-tree cleanup, timeout, background task, and child-process lifecycle controls with deletion-sensitive tests.",
    },
    {
        "surface_id": "hook_runner",
        "name": "Hook runner and event policy",
        "reference_evidence": ["src/components/hooks", "src"],
        "required_cleanroom_surface": "Hook configuration, event dispatch, read-only policy surfaces, and fail-closed permission handling.",
    },
    {
        "surface_id": "tool_dispatch_permissions",
        "name": "Tool dispatch and permission gating",
        "reference_evidence": ["src/tools", "src/components/permissions", "docs/api/generated/src/tools"],
        "required_cleanroom_surface": "Native tool registry, permission prompts, allow/deny rules, and tool-call execution with verifier and rollback hooks.",
    },
    {
        "surface_id": "state_persistence",
        "name": "State, sessions, memory, and compaction",
        "reference_evidence": ["src", "state", ".predecessor-cli", "docs"],
        "required_cleanroom_surface": "Local session state, durable memory, compaction, resume, settings, and model/account state under Ember-owned storage.",
    },
    {
        "surface_id": "receipt_store",
        "name": "Receipts, telemetry, and replayable evidence",
        "reference_evidence": ["dogfood-receipts", "docs/adr/0004-real-work-replaces-scripted-dogfood.md", "docs/api/generated/scripts/dogfood"],
        "required_cleanroom_surface": "Fail-closed receipt writer/reader, event logs, replay hooks, and evidence rows tied to every gate.",
    },
    {
        "surface_id": "rollback_rewind",
        "name": "Rollback, rewind, and branch restoration",
        "reference_evidence": ["src/commands/rewind", "src/commands/branch", "src/commands/diff"],
        "required_cleanroom_surface": "Local branch/session rewind, diff, restore, and delete/ablate-sensitive rollback tests.",
    },
    {
        "surface_id": "communication_mailbox_computer_use",
        "name": "Communication and computer-use reachability",
        "reference_evidence": ["src/tools/SendMessageTool", "docs/reference/en/agent-teams.md", "docs/upstream-docs/en/sub-agents.md"],
        "required_cleanroom_surface": "Ember mailbox identity, user-facing communication, founder communication, and computer-use route where applicable.",
    },
    {
        "surface_id": "native_goal_organ",
        "name": "Native Codex goal-mode organ",
        "reference_evidence": ["docs/domains/governance/authority/GOAL.md", "src/ember/infrastructure/tools/reference-goal-mode/goal-mode.ps1", "src/ember/governance/scripts/ember_gate_goal_mode_parity_adapter.py"],
        "required_cleanroom_surface": "Resident goal organ that parses goal, reads receipts, selects blocker, compiles action, runs/delegates, verifies, writes receipt, and preserves next blocker without Codex steering.",
    },
    {
        "surface_id": "cleanroom_legal_boundary",
        "name": "Clean-room provenance and copyright boundary",
        "reference_evidence": ["legal/origin.md", "legal/dependencies.md", "legal/file-inventory.csv", "legal/product-shape.md"],
        "required_cleanroom_surface": "Reference-only evidence boundary, no inherited implementation copying, and per-surface provenance receipt.",
    },
]
REQUIRED_SURFACE_IDS = [row["surface_id"] for row in SURFACE_SPECS]


def ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def repo_root() -> Path:
    return next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def extract_bullet(text: str, label: str) -> str:
    pattern = re.compile(
        rf"- \*\*{re.escape(label)}:\*\*(.*?)(?=\n- \*\*|\n\n## |\Z)",
        flags=re.S,
    )
    match = pattern.search(text)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""


def extract_first_code(text: str) -> str:
    match = re.search(r"`([^`]+)`", text)
    return re.sub(r"\s+", " ", match.group(1).strip()) if match else ""


def inspect_goal(repo: Path) -> dict[str, Any]:
    path = repo / "docs/domains/governance/authority/GOAL.md"
    text = read_text(path)
    labels = {
        "current_blocker": "Current blocker",
        "current_executable_command": "Current executable command",
        "required_receipt": "Required receipt",
        "kill_ablate_test": "Kill/ablate test",
        "next_blocker_if_pass": "Next blocker if pass",
        "next_blocker_if_fail": "Next blocker if fail",
    }
    extracted = {key: extract_bullet(text, label) for key, label in labels.items()}
    extracted["current_executable_command"] = extract_first_code(extracted["current_executable_command"])
    markers = {f"has_{key}": bool(value) for key, value in extracted.items()}
    return {
        "path": str(path),
        "exists": path.exists(),
        "sha256": sha256(path) if path.exists() else None,
        "status": "PASS" if all(markers.values()) else "BLOCKED",
        "markers": markers,
        **extracted,
    }


def reference_status(reference_root: Path, references: list[str], repo: Path | None = None) -> list[dict[str, Any]]:
    rows = []
    for rel in references:
        source_root = "reference_root"
        path = reference_root / rel
        if not path.exists() and repo is not None:
            repo_path = repo / rel
            if repo_path.exists():
                source_root = "ember_repo"
                path = repo_path
        exists = path.exists()
        rows.append(
            {
                "path": rel,
                "source_root": source_root,
                "exists": exists,
                "sha256": sha256(path) if exists and path.is_file() else None,
                "kind": "directory" if exists and path.is_dir() else "file" if exists else "missing",
            }
        )
    return rows


def legal_receipt(inventory: dict[str, Any], reference_root: Path) -> dict[str, Any]:
    legal_files = inventory.get("copyright_cleanroom_boundary", {}).get("legal_provenance_files", [])
    locally_present = reference_status(
        reference_root,
        [
            "legal/origin.md",
            "legal/ui-parity-audit.md",
            "legal/ui-parity-audit-pass2.md",
            "legal/ui-parity-audit-pass3.md",
            "legal/file-inventory.csv",
            "legal/product-shape.md",
        ],
    )
    return {
        "inventory_legal_provenance_count": len(legal_files),
        "required_local_legal_files": locally_present,
        "status": "REFERENCE_AVAILABLE" if legal_files and all(row["exists"] for row in locally_present[:4]) else "BLOCKED",
        "copying_policy": "reference/provenance inspection only; no the predecessor CLI source import or inherited implementation copying",
    }


def inspect_real_observation(receipt_path: Path | None) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    data = load_json(receipt_path) if receipt_path and receipt_path.exists() else {}
    summary = {
        "path": str(receipt_path) if receipt_path else None,
        "exists": bool(receipt_path and receipt_path.exists()),
        "sha256": sha256(receipt_path) if receipt_path and receipt_path.exists() else None,
        "ticket": data.get("ticket"),
        "verdict": data.get("verdict"),
        "classification": data.get("classification"),
        "observed_real_reference_binary": data.get("observed_real_reference_binary"),
        "observed_real_tui": data.get("observed_real_tui"),
        "observed_agent_loop": data.get("observed_agent_loop"),
        "observed_uiux_ax": data.get("observed_uiux_ax"),
        "resource_governed": data.get("resource_governed"),
    }
    if receipt_path is None or not receipt_path.exists():
        errors.append("real_reference_uiux_ax_observation_missing")
        return summary, errors
    if data.get("ticket") != "EMBER-REAL-PREDECESSOR-CLI-UIUX-AX-OBSERVATION":
        errors.append("real_reference_uiux_ax_observation_wrong_ticket")
    if data.get("verdict") != REAL_reference_OBSERVATION_PASS:
        errors.append("real_reference_uiux_ax_observation_not_pass")
    for key in [
        "observed_real_reference_binary",
        "observed_real_tui",
        "observed_agent_loop",
        "observed_uiux_ax",
        "resource_governed",
    ]:
        if data.get(key) is not True:
            errors.append(f"{key}_not_true")
    return summary, errors


def build_surface_matrix(reference_root: Path, repo: Path) -> list[dict[str, Any]]:
    matrix = []
    for spec in SURFACE_SPECS:
        refs = reference_status(reference_root, spec["reference_evidence"], repo)
        matrix.append(
            {
                "surface_id": spec["surface_id"],
                "name": spec["name"],
                "reference_evidence": refs,
                "required_cleanroom_surface": spec["required_cleanroom_surface"],
                "implemented_cleanroom_surface": None,
                "cleanroom_implemented": False,
                "parity_test": None,
                "delete_ablate_test": None,
                "status": "BLOCKED",
                "remaining_gap": "clean-room Ember implementation and executable parity/deletion test missing",
            }
        )
    return matrix

def apply_native_goal_organ_receipt(matrix: list[dict[str, Any]], receipt_path: Path | None) -> dict[str, Any]:
    data = load_json(receipt_path) if receipt_path else {}
    consumed = {
        "path": str(receipt_path) if receipt_path else None,
        "exists": bool(receipt_path and receipt_path.exists()),
        "sha256": sha256(receipt_path) if receipt_path and receipt_path.exists() else None,
        "ticket": data.get("ticket"),
        "verdict": data.get("verdict"),
        "applied": False,
    }
    if data.get("verdict") != "NATIVE_GOAL_ORGAN_PASS":
        return consumed
    for row in matrix:
        if row["surface_id"] == "native_goal_organ":
            row["implemented_cleanroom_surface"] = data.get("native_goal_organ", {}).get("implemented_surface")
            row["cleanroom_implemented"] = True
            row["parity_test"] = str(receipt_path)
            row["delete_ablate_test"] = data.get("deletion_ablation")
            row["status"] = "PASS"
            row["remaining_gap"] = None
            consumed["applied"] = True
            break
    return consumed

def apply_function_slash_commands_receipt(matrix: list[dict[str, Any]], receipt_path: Path | None) -> dict[str, Any]:
    data = load_json(receipt_path) if receipt_path else {}
    consumed = {
        "path": str(receipt_path) if receipt_path else None,
        "exists": bool(receipt_path and receipt_path.exists()),
        "sha256": sha256(receipt_path) if receipt_path and receipt_path.exists() else None,
        "ticket": data.get("ticket"),
        "verdict": data.get("verdict"),
        "applied": False,
    }
    if data.get("verdict") != "FUNCTION_SLASH_COMMANDS_GATE_PASS":
        return consumed
    for row in matrix:
        if row["surface_id"] == "function_slash_commands":
            counts = data.get("command_surface", {}).get("registry_counts", {})
            row["implemented_cleanroom_surface"] = (
                "clean-room executable slash-command registry and dispatcher; "
                f"registered={counts.get('n_registered')} local={counts.get('n_local')} "
                f"goal_safe_replacement={counts.get('n_goal_safe_replacement')} "
                f"trigger_gated={counts.get('n_trigger_gated')}"
            )
            row["cleanroom_implemented"] = True
            row["parity_test"] = str(receipt_path)
            row["delete_ablate_test"] = data.get("deletion_ablation")
            row["status"] = "PASS"
            row["remaining_gap"] = None
            consumed["applied"] = True
            break
    return consumed

def apply_uiux_repl_components_receipt(matrix: list[dict[str, Any]], receipt_path: Path | None) -> dict[str, Any]:
    data = load_json(receipt_path) if receipt_path else {}
    consumed = {
        "path": str(receipt_path) if receipt_path else None,
        "exists": bool(receipt_path and receipt_path.exists()),
        "sha256": sha256(receipt_path) if receipt_path and receipt_path.exists() else None,
        "ticket": data.get("ticket"),
        "verdict": data.get("verdict"),
        "applied": False,
    }
    if data.get("verdict") != "UIUX_REPL_COMPONENTS_GATE_PASS":
        return consumed
    for row in matrix:
        if row["surface_id"] == "uiux_repl_components":
            counts = data.get("uiux_repl_components", {}).get("contract_counts", {})
            row["implemented_cleanroom_surface"] = (
                "clean-room executable REPL/component affordance contract; "
                f"components={counts.get('n_components')} local={counts.get('n_local')} "
                f"goal_safe_replacement={counts.get('n_goal_safe_replacement')} "
                f"trigger_gated={counts.get('n_trigger_gated')}"
            )
            row["cleanroom_implemented"] = True
            row["parity_test"] = str(receipt_path)
            row["delete_ablate_test"] = data.get("deletion_ablation")
            row["status"] = "PASS"
            row["remaining_gap"] = None
            consumed["applied"] = True
            break
    return consumed

def apply_backend_coordinator_agents_receipt(matrix: list[dict[str, Any]], receipt_path: Path | None) -> dict[str, Any]:
    data = load_json(receipt_path) if receipt_path else {}
    consumed = {
        "path": str(receipt_path) if receipt_path else None,
        "exists": bool(receipt_path and receipt_path.exists()),
        "sha256": sha256(receipt_path) if receipt_path and receipt_path.exists() else None,
        "ticket": data.get("ticket"),
        "verdict": data.get("verdict"),
        "applied": False,
    }
    if data.get("verdict") != "BACKEND_COORDINATOR_AGENTS_GATE_PASS":
        return consumed
    for row in matrix:
        if row["surface_id"] == "backend_coordinator_agents":
            counts = data.get("backend_coordinator_agents", {}).get("contract_counts", {})
            row["implemented_cleanroom_surface"] = (
                "clean-room executable resident coordination backend; "
                f"components={counts.get('n_components')} local={counts.get('n_local')} "
                f"goal_safe_replacement={counts.get('n_goal_safe_replacement')} "
                f"trigger_gated={counts.get('n_trigger_gated')}"
            )
            row["cleanroom_implemented"] = True
            row["parity_test"] = str(receipt_path)
            row["delete_ablate_test"] = data.get("deletion_ablation")
            row["status"] = "PASS"
            row["remaining_gap"] = None
            consumed["applied"] = True
            break
    return consumed
def apply_launch_packaging_receipt(matrix: list[dict[str, Any]], receipt_path: Path | None) -> dict[str, Any]:
    data = load_json(receipt_path) if receipt_path else {}
    consumed = {
        "path": str(receipt_path) if receipt_path else None,
        "exists": bool(receipt_path and receipt_path.exists()),
        "sha256": sha256(receipt_path) if receipt_path and receipt_path.exists() else None,
        "ticket": data.get("ticket"),
        "verdict": data.get("verdict"),
        "applied": False,
    }
    if data.get("verdict") != "LAUNCH_PACKAGING_GATE_PASS":
        return consumed
    for row in matrix:
        if row["surface_id"] == "launch_packaging":
            launch = data.get("launch_packaging", {})
            row["implemented_cleanroom_surface"] = (
                "clean-room executable launcher and package entrypoint; "
                f"bin={launch.get('bin_name')} launcher={launch.get('launcher_path')}"
            )
            row["cleanroom_implemented"] = True
            row["parity_test"] = str(receipt_path)
            row["delete_ablate_test"] = data.get("deletion_ablation")
            row["status"] = "PASS"
            row["remaining_gap"] = None
            consumed["applied"] = True
            break
    return consumed
def apply_process_supervision_receipt(matrix: list[dict[str, Any]], receipt_path: Path | None) -> dict[str, Any]:
    data = load_json(receipt_path) if receipt_path else {}
    consumed = {
        "path": str(receipt_path) if receipt_path else None,
        "exists": bool(receipt_path and receipt_path.exists()),
        "sha256": sha256(receipt_path) if receipt_path and receipt_path.exists() else None,
        "ticket": data.get("ticket"),
        "verdict": data.get("verdict"),
        "applied": False,
    }
    if data.get("verdict") != "PROCESS_SUPERVISION_GATE_PASS":
        return consumed
    for row in matrix:
        if row["surface_id"] == "process_supervision":
            probe = data.get("verification", {}).get("probe", {}).get("record", {})
            row["implemented_cleanroom_surface"] = (
                "clean-room executable process supervisor; "
                f"timeout_s={probe.get('timeout_s')} status={probe.get('status')}"
            )
            row["cleanroom_implemented"] = True
            row["parity_test"] = str(receipt_path)
            row["delete_ablate_test"] = data.get("deletion_ablation")
            row["status"] = "PASS"
            row["remaining_gap"] = None
            consumed["applied"] = True
            break
    return consumed
def apply_hook_runner_receipt(matrix: list[dict[str, Any]], receipt_path: Path | None) -> dict[str, Any]:
    data = load_json(receipt_path) if receipt_path else {}
    consumed = {
        "path": str(receipt_path) if receipt_path else None,
        "exists": bool(receipt_path and receipt_path.exists()),
        "sha256": sha256(receipt_path) if receipt_path and receipt_path.exists() else None,
        "ticket": data.get("ticket"),
        "verdict": data.get("verdict"),
        "applied": False,
    }
    if data.get("verdict") != "HOOK_RUNNER_GATE_PASS":
        return consumed
    for row in matrix:
        if row["surface_id"] == "hook_runner":
            hook = data.get("hook_runner", {})
            events = ",".join(hook.get("event_surface", []))
            row["implemented_cleanroom_surface"] = (
                "clean-room executable hook runner and policy engine; "
                f"events={events} policy={','.join(hook.get('policy_surface', []))}"
            )
            row["cleanroom_implemented"] = True
            row["parity_test"] = str(receipt_path)
            row["delete_ablate_test"] = data.get("deletion_ablation")
            row["status"] = "PASS"
            row["remaining_gap"] = None
            consumed["applied"] = True
            break
    return consumed


def apply_tool_dispatch_permissions_receipt(matrix: list[dict[str, Any]], receipt_path: Path | None) -> dict[str, Any]:
    data = load_json(receipt_path) if receipt_path else {}
    consumed = {
        "path": str(receipt_path) if receipt_path else None,
        "exists": bool(receipt_path and receipt_path.exists()),
        "sha256": sha256(receipt_path) if receipt_path and receipt_path.exists() else None,
        "ticket": data.get("ticket"),
        "verdict": data.get("verdict"),
        "applied": False,
    }
    if data.get("verdict") != "TOOL_DISPATCH_PERMISSIONS_GATE_PASS":
        return consumed
    for row in matrix:
        if row["surface_id"] == "tool_dispatch_permissions":
            tool = data.get("tool_dispatch_permissions", {})
            row["implemented_cleanroom_surface"] = (
                "clean-room executable tool registry, permission policy, dispatcher, verifier, and rollback handoff; "
                f"tools={','.join(tool.get('tool_surface', []))} permissions={','.join(tool.get('permission_surface', []))}"
            )
            row["cleanroom_implemented"] = True
            row["parity_test"] = str(receipt_path)
            row["delete_ablate_test"] = data.get("deletion_ablation")
            row["status"] = "PASS"
            row["remaining_gap"] = None
            consumed["applied"] = True
            break
    return consumed


def apply_state_persistence_receipt(matrix: list[dict[str, Any]], receipt_path: Path | None) -> dict[str, Any]:
    data = load_json(receipt_path) if receipt_path else {}
    consumed = {
        "path": str(receipt_path) if receipt_path else None,
        "exists": bool(receipt_path and receipt_path.exists()),
        "sha256": sha256(receipt_path) if receipt_path and receipt_path.exists() else None,
        "ticket": data.get("ticket"),
        "verdict": data.get("verdict"),
        "applied": False,
    }
    if data.get("verdict") != "STATE_PERSISTENCE_GATE_PASS":
        return consumed
    for row in matrix:
        if row["surface_id"] == "state_persistence":
            state = data.get("state_persistence", {})
            row["implemented_cleanroom_surface"] = (
                "clean-room file-backed local session state, memory, settings, model/account, compaction, and resume; "
                f"surfaces={','.join(state.get('state_surface', []))}"
            )
            row["cleanroom_implemented"] = True
            row["parity_test"] = str(receipt_path)
            row["delete_ablate_test"] = data.get("deletion_ablation")
            row["status"] = "PASS"
            row["remaining_gap"] = None
            consumed["applied"] = True
            break
    return consumed


def apply_receipt_store_receipt(matrix: list[dict[str, Any]], receipt_path: Path | None) -> dict[str, Any]:
    data = load_json(receipt_path) if receipt_path else {}
    consumed = {
        "path": str(receipt_path) if receipt_path else None,
        "exists": bool(receipt_path and receipt_path.exists()),
        "sha256": sha256(receipt_path) if receipt_path and receipt_path.exists() else None,
        "ticket": data.get("ticket"),
        "verdict": data.get("verdict"),
        "applied": False,
    }
    if data.get("verdict") != "RECEIPT_STORE_GATE_PASS":
        return consumed
    for row in matrix:
        if row["surface_id"] == "receipt_store":
            store = data.get("receipt_store", {})
            row["implemented_cleanroom_surface"] = (
                "clean-room fail-closed receipt writer/reader, schema validator, event log, replay, and evidence lookup; "
                f"surfaces={','.join(store.get('receipt_surface', []))}"
            )
            row["cleanroom_implemented"] = True
            row["parity_test"] = str(receipt_path)
            row["delete_ablate_test"] = data.get("deletion_ablation")
            row["status"] = "PASS"
            row["remaining_gap"] = None
            consumed["applied"] = True
            break
    return consumed


def apply_rollback_rewind_receipt(matrix: list[dict[str, Any]], receipt_path: Path | None) -> dict[str, Any]:
    data = load_json(receipt_path) if receipt_path else {}
    consumed = {
        "path": str(receipt_path) if receipt_path else None,
        "exists": bool(receipt_path and receipt_path.exists()),
        "sha256": sha256(receipt_path) if receipt_path and receipt_path.exists() else None,
        "ticket": data.get("ticket"),
        "verdict": data.get("verdict"),
        "applied": False,
    }
    if data.get("verdict") != "ROLLBACK_REWIND_GATE_PASS":
        return consumed
    for row in matrix:
        if row["surface_id"] == "rollback_rewind":
            rollback = data.get("rollback_rewind", {})
            row["implemented_cleanroom_surface"] = (
                "clean-room local checkpoint, diff, restore, selector, and rollback event log; "
                f"surfaces={','.join(rollback.get('rollback_surface', []))}"
            )
            row["cleanroom_implemented"] = True
            row["parity_test"] = str(receipt_path)
            row["delete_ablate_test"] = data.get("deletion_ablation")
            row["status"] = "PASS"
            row["remaining_gap"] = None
            consumed["applied"] = True
            break
    return consumed


def apply_communication_mailbox_computer_use_receipt(matrix: list[dict[str, Any]], receipt_path: Path | None) -> dict[str, Any]:
    data = load_json(receipt_path) if receipt_path else {}
    consumed = {
        "path": str(receipt_path) if receipt_path else None,
        "exists": bool(receipt_path and receipt_path.exists()),
        "sha256": sha256(receipt_path) if receipt_path and receipt_path.exists() else None,
        "ticket": data.get("ticket"),
        "verdict": data.get("verdict"),
        "applied": False,
    }
    if data.get("verdict") != "COMMUNICATION_MAILBOX_COMPUTER_USE_GATE_PASS":
        return consumed
    for row in matrix:
        if row["surface_id"] == "communication_mailbox_computer_use":
            comm = data.get("communication_mailbox_computer_use", {})
            row["implemented_cleanroom_surface"] = (
                "clean-room resident identity, user/founder communication, reachability status, and computer-use route; "
                f"surfaces={','.join(comm.get('communication_surface', []))}"
            )
            row["cleanroom_implemented"] = True
            row["parity_test"] = str(receipt_path)
            row["delete_ablate_test"] = data.get("deletion_ablation")
            row["status"] = "PASS"
            row["remaining_gap"] = None
            consumed["applied"] = True
            break
    return consumed


def apply_cleanroom_legal_boundary_receipt(matrix: list[dict[str, Any]], receipt_path: Path | None) -> dict[str, Any]:
    data = load_json(receipt_path) if receipt_path else {}
    consumed = {
        "path": str(receipt_path) if receipt_path else None,
        "exists": bool(receipt_path and receipt_path.exists()),
        "sha256": sha256(receipt_path) if receipt_path and receipt_path.exists() else None,
        "ticket": data.get("ticket"),
        "verdict": data.get("verdict"),
        "applied": False,
    }
    if data.get("verdict") != "CLEANROOM_LEGAL_BOUNDARY_GATE_PASS":
        return consumed
    for row in matrix:
        if row["surface_id"] == "cleanroom_legal_boundary":
            legal = data.get("cleanroom_legal_boundary", {})
            row["implemented_cleanroom_surface"] = (
                "clean-room reference-only legal boundary, provenance hash checks, copy-boundary enforcement, surface linkage, and inventory accounting; "
                f"surfaces={','.join(legal.get('legal_surface', []))}"
            )
            row["cleanroom_implemented"] = True
            row["parity_test"] = str(receipt_path)
            row["delete_ablate_test"] = data.get("deletion_ablation")
            row["status"] = "PASS"
            row["remaining_gap"] = None
            consumed["applied"] = True
            break
    return consumed

def deletion_requirements(matrix: list[dict[str, Any]]) -> dict[str, bool]:
    implemented = {row["surface_id"]: bool(row["cleanroom_implemented"]) for row in matrix}
    return {
        "visible_uiux_deleted_blocks": implemented.get("uiux_repl_components", False),
        "backend_coordinator_agents_deleted_blocks": implemented.get("backend_coordinator_agents", False),
        "launch_packaging_deleted_blocks": implemented.get("launch_packaging", False),
        "backend_command_router_deleted_blocks": implemented.get("function_slash_commands", False),
        "process_supervisor_deleted_blocks": implemented.get("process_supervision", False),
        "hook_runner_deleted_blocks": implemented.get("hook_runner", False),
        "tool_dispatch_permissions_deleted_blocks": implemented.get("tool_dispatch_permissions", False),
        "state_persistence_deleted_blocks": implemented.get("state_persistence", False),
        "receipt_store_deleted_blocks": implemented.get("receipt_store", False),
        "state_receipt_store_deleted_blocks": implemented.get("state_persistence", False) and implemented.get("receipt_store", False),
        "rollback_path_deleted_blocks": implemented.get("rollback_rewind", False),
        "native_goal_organ_deleted_blocks": implemented.get("native_goal_organ", False),
        "communication_bridge_deleted_blocks": implemented.get("communication_mailbox_computer_use", False),
    }


def build_receipt(
    *,
    repo: Path,
    reference_root: Path,
    inventory_receipt: Path,
    bootstrap_receipt: Path,
    native_goal_organ_receipt: Path | None = None,
    function_slash_commands_receipt: Path | None = None,
    uiux_repl_components_receipt: Path | None = None,
    backend_coordinator_agents_receipt: Path | None = None,
    launch_packaging_receipt: Path | None = None,
    process_supervision_receipt: Path | None = None,
    hook_runner_receipt: Path | None = None,
    tool_dispatch_permissions_receipt: Path | None = None,
    state_persistence_receipt: Path | None = None,
    receipt_store_receipt: Path | None = None,
    rollback_rewind_receipt: Path | None = None,
    communication_mailbox_computer_use_receipt: Path | None = None,
    cleanroom_legal_boundary_receipt: Path | None = None,
    real_observation_receipt: Path | None = None,
    out: Path,
) -> dict[str, Any]:
    goal = inspect_goal(repo)
    inventory = load_json(inventory_receipt)
    bootstrap = load_json(bootstrap_receipt)
    matrix = build_surface_matrix(reference_root, repo)
    native_goal_evidence = apply_native_goal_organ_receipt(matrix, native_goal_organ_receipt)
    function_slash_evidence = apply_function_slash_commands_receipt(matrix, function_slash_commands_receipt)
    uiux_evidence = apply_uiux_repl_components_receipt(matrix, uiux_repl_components_receipt)
    backend_coordinator_evidence = apply_backend_coordinator_agents_receipt(matrix, backend_coordinator_agents_receipt)
    launch_packaging_evidence = apply_launch_packaging_receipt(matrix, launch_packaging_receipt)
    process_supervision_evidence = apply_process_supervision_receipt(matrix, process_supervision_receipt)
    hook_runner_evidence = apply_hook_runner_receipt(matrix, hook_runner_receipt)
    tool_dispatch_permissions_evidence = apply_tool_dispatch_permissions_receipt(matrix, tool_dispatch_permissions_receipt)
    state_persistence_evidence = apply_state_persistence_receipt(matrix, state_persistence_receipt)
    receipt_store_evidence = apply_receipt_store_receipt(matrix, receipt_store_receipt)
    rollback_rewind_evidence = apply_rollback_rewind_receipt(matrix, rollback_rewind_receipt)
    communication_evidence = apply_communication_mailbox_computer_use_receipt(matrix, communication_mailbox_computer_use_receipt)
    cleanroom_legal_boundary_evidence = apply_cleanroom_legal_boundary_receipt(matrix, cleanroom_legal_boundary_receipt)
    delete_ablate = deletion_requirements(matrix)
    legal = legal_receipt(inventory, reference_root)
    real_observation, real_observation_errors = inspect_real_observation(real_observation_receipt)
    blocked_surfaces = [row["surface_id"] for row in matrix if row["status"] != "PASS"]

    blocked: list[str] = []
    if blocked_surfaces:
        blocked.append("full_cleanroom_parity_not_implemented")
        if bootstrap.get("does_not_satisfy_full_the predecessor CLI_parity") is True:
            blocked.append("headless_bootstrap_only")
    if bootstrap.get("does_not_satisfy_full_the predecessor CLI_parity") is not True:
        blocked.append("bootstrap_receipt_does_not_block_full_parity_substitution")
    if goal.get("status") != "PASS":
        blocked.append("goal_current_blocker_packet_parse_failed")
    if inventory.get("ticket") != "EMBER-GATE-CLEANROOM-INVENTORY":
        blocked.append("inventory_receipt_missing_or_wrong_ticket")
    if bootstrap.get("ticket") != "EMBER-GATE-GOAL-MODE-PARITY-ADAPTER":
        blocked.append("bootstrap_receipt_missing_or_wrong_ticket")
    if legal["status"] != "REFERENCE_AVAILABLE":
        blocked.append("cleanroom_reference_legal_files_incomplete")
    blocked.extend(real_observation_errors)
    for surface_id, deleted_blocks in delete_ablate.items():
        if not deleted_blocks:
            blocked.append(f"{surface_id}_not_deletion_sensitive")

    blocked = sorted(set(blocked))
    gate_passed = not blocked and not blocked_surfaces
    verdict = "THE_PREDECESSOR_CLI_FULL_PARITY_HARNESS_GATE_PASS" if gate_passed else "THE_PREDECESSOR_CLI_FULL_PARITY_HARNESS_GATE_BLOCKED"
    classification = "FULL_PARITY_GATE_PASS" if gate_passed else "FULL_PARITY_GATE_BLOCKED_NOT_HEADLESS_PASS"
    headless_classification = (
        "SUPERSEDED_BY_FULL_CLEANROOM_PARITY_RECEIPTS"
        if gate_passed
        else "HEADLESS_BOOTSTRAP_ONLY"
    )

    next_parts = ["python scripts\\ember_gate_full_parity_harness.py"]
    if native_goal_organ_receipt is not None:
        next_parts.extend(["--native-goal-organ-receipt", str(native_goal_organ_receipt)])
    if function_slash_commands_receipt is not None:
        next_parts.extend(["--function-slash-commands-receipt", str(function_slash_commands_receipt)])
    if uiux_repl_components_receipt is not None:
        next_parts.extend(["--uiux-repl-components-receipt", str(uiux_repl_components_receipt)])
    if backend_coordinator_agents_receipt is not None:
        next_parts.extend(["--backend-coordinator-agents-receipt", str(backend_coordinator_agents_receipt)])
    if launch_packaging_receipt is not None:
        next_parts.extend(["--launch-packaging-receipt", str(launch_packaging_receipt)])
    if process_supervision_receipt is not None:
        next_parts.extend(["--process-supervision-receipt", str(process_supervision_receipt)])
    if hook_runner_receipt is not None:
        next_parts.extend(["--hook-runner-receipt", str(hook_runner_receipt)])
    if tool_dispatch_permissions_receipt is not None:
        next_parts.extend(["--tool-dispatch-permissions-receipt", str(tool_dispatch_permissions_receipt)])
    if state_persistence_receipt is not None:
        next_parts.extend(["--state-persistence-receipt", str(state_persistence_receipt)])
    if receipt_store_receipt is not None:
        next_parts.extend(["--receipt-store-receipt", str(receipt_store_receipt)])
    if rollback_rewind_receipt is not None:
        next_parts.extend(["--rollback-rewind-receipt", str(rollback_rewind_receipt)])
    if communication_mailbox_computer_use_receipt is not None:
        next_parts.extend(["--communication-mailbox-computer-use-receipt", str(communication_mailbox_computer_use_receipt)])
    if cleanroom_legal_boundary_receipt is not None:
        next_parts.extend(["--cleanroom-legal-boundary-receipt", str(cleanroom_legal_boundary_receipt)])
    next_parts.extend(["--out", "receipts\\ember-preloop-resident-gate\\gate-full-parity-harness-<timestamp>.json"])
    next_command = " ".join(next_parts)
    return {
        "ticket": TICKET,
        "ts": ts(),
        "sha_convention": SHA_CONVENTION,
        "verdict": verdict,
        "classification": classification,
        "headless_bootstrap_classification": headless_classification,
        "parity_target": "near_99_percent_complete_parity_in_function_uiux_backend_and_native_goal_mode",
        "out_path": str(out),
        "goal_parse": goal,
        "inventory_receipt": {
            "path": str(inventory_receipt),
            "exists": inventory_receipt.exists(),
            "sha256": sha256(inventory_receipt) if inventory_receipt.exists() else None,
            "ticket": inventory.get("ticket"),
            "verdict": inventory.get("verdict"),
        },
        "bootstrap_receipt": {
            "path": str(bootstrap_receipt),
            "exists": bootstrap_receipt.exists(),
            "sha256": sha256(bootstrap_receipt) if bootstrap_receipt.exists() else None,
            "ticket": bootstrap.get("ticket"),
            "verdict": bootstrap.get("verdict"),
            "does_not_satisfy_full_the predecessor CLI_parity": bootstrap.get("does_not_satisfy_full_the predecessor CLI_parity"),
        },
        "native_goal_organ_receipt": native_goal_evidence,
        "function_slash_commands_receipt": function_slash_evidence,
        "uiux_repl_components_receipt": uiux_evidence,
        "backend_coordinator_agents_receipt": backend_coordinator_evidence,
        "launch_packaging_receipt": launch_packaging_evidence,
        "process_supervision_receipt": process_supervision_evidence,
        "hook_runner_receipt": hook_runner_evidence,
        "tool_dispatch_permissions_receipt": tool_dispatch_permissions_evidence,
        "state_persistence_receipt": state_persistence_evidence,
        "receipt_store_receipt": receipt_store_evidence,
        "rollback_rewind_receipt": rollback_rewind_evidence,
        "communication_mailbox_computer_use_receipt": communication_evidence,
        "reference_root": {
            "path": str(reference_root),
            "exists": reference_root.exists(),
            "package_json_sha256": sha256(reference_root / "package.json") if (reference_root / "package.json").exists() else None,
        },
        "cleanroom_legal_boundary": legal,
        "cleanroom_legal_boundary_receipt": cleanroom_legal_boundary_evidence,
        "real_reference_uiux_ax_observation_receipt": real_observation,
        "surface_matrix": matrix,
        "delete_ablate_required": delete_ablate,
        "blocked_reasons": blocked,
        "next_missing_precondition": blocked_surfaces[0] if blocked_surfaces else "real_reference_uiux_ax_observation" if real_observation_errors else "rlm_igrpo_train_multimodal_adapter",
        "next_executable_command": next_command,
        "next_blocker_if_pass": "rlm_igrpo_train_multimodal_adapter",
        "n_rows": len(matrix),
    }


def write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(path), receipt)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--repo", default=str(repo_root()))
    parser.add_argument("--reference-root", required=True)
    parser.add_argument("--inventory-receipt", default=str(DEFAULT_INVENTORY_RECEIPT))
    parser.add_argument("--bootstrap-receipt", default=str(DEFAULT_BOOTSTRAP_RECEIPT))
    parser.add_argument("--native-goal-organ-receipt")
    parser.add_argument("--function-slash-commands-receipt")
    parser.add_argument("--uiux-repl-components-receipt")
    parser.add_argument("--backend-coordinator-agents-receipt")
    parser.add_argument("--launch-packaging-receipt")
    parser.add_argument("--process-supervision-receipt")
    parser.add_argument("--hook-runner-receipt")
    parser.add_argument("--tool-dispatch-permissions-receipt")
    parser.add_argument("--state-persistence-receipt")
    parser.add_argument("--receipt-store-receipt")
    parser.add_argument("--rollback-rewind-receipt")
    parser.add_argument("--communication-mailbox-computer-use-receipt")
    parser.add_argument("--cleanroom-legal-boundary-receipt")
    parser.add_argument("--real-observation-receipt")
    args = parser.parse_args()

    repo = Path(args.repo)
    reference_root = Path(args.reference_root)
    inventory = Path(args.inventory_receipt)
    if not inventory.is_absolute():
        inventory = repo / inventory
    bootstrap = Path(args.bootstrap_receipt)
    if not bootstrap.is_absolute():
        bootstrap = repo / bootstrap
    native_goal = Path(args.native_goal_organ_receipt) if args.native_goal_organ_receipt else None
    if native_goal is not None and not native_goal.is_absolute():
        native_goal = repo / native_goal
    function_slash = Path(args.function_slash_commands_receipt) if args.function_slash_commands_receipt else None
    if function_slash is not None and not function_slash.is_absolute():
        function_slash = repo / function_slash
    uiux = Path(args.uiux_repl_components_receipt) if args.uiux_repl_components_receipt else None
    if uiux is not None and not uiux.is_absolute():
        uiux = repo / uiux
    backend_coordinator = Path(args.backend_coordinator_agents_receipt) if args.backend_coordinator_agents_receipt else None
    if backend_coordinator is not None and not backend_coordinator.is_absolute():
        backend_coordinator = repo / backend_coordinator
    launch_packaging = Path(args.launch_packaging_receipt) if args.launch_packaging_receipt else None
    if launch_packaging is not None and not launch_packaging.is_absolute():
        launch_packaging = repo / launch_packaging
    process_supervision = Path(args.process_supervision_receipt) if args.process_supervision_receipt else None
    if process_supervision is not None and not process_supervision.is_absolute():
        process_supervision = repo / process_supervision
    hook_runner = Path(args.hook_runner_receipt) if args.hook_runner_receipt else None
    if hook_runner is not None and not hook_runner.is_absolute():
        hook_runner = repo / hook_runner
    tool_dispatch_permissions = Path(args.tool_dispatch_permissions_receipt) if args.tool_dispatch_permissions_receipt else None
    if tool_dispatch_permissions is not None and not tool_dispatch_permissions.is_absolute():
        tool_dispatch_permissions = repo / tool_dispatch_permissions
    state_persistence = Path(args.state_persistence_receipt) if args.state_persistence_receipt else None
    if state_persistence is not None and not state_persistence.is_absolute():
        state_persistence = repo / state_persistence
    receipt_store = Path(args.receipt_store_receipt) if args.receipt_store_receipt else None
    if receipt_store is not None and not receipt_store.is_absolute():
        receipt_store = repo / receipt_store
    rollback_rewind = Path(args.rollback_rewind_receipt) if args.rollback_rewind_receipt else None
    if rollback_rewind is not None and not rollback_rewind.is_absolute():
        rollback_rewind = repo / rollback_rewind
    communication = Path(args.communication_mailbox_computer_use_receipt) if args.communication_mailbox_computer_use_receipt else None
    if communication is not None and not communication.is_absolute():
        communication = repo / communication
    cleanroom_legal_boundary = Path(args.cleanroom_legal_boundary_receipt) if args.cleanroom_legal_boundary_receipt else None
    if cleanroom_legal_boundary is not None and not cleanroom_legal_boundary.is_absolute():
        cleanroom_legal_boundary = repo / cleanroom_legal_boundary
    real_observation = Path(args.real_observation_receipt) if args.real_observation_receipt else None
    if real_observation is not None and not real_observation.is_absolute():
        real_observation = repo / real_observation
    out = Path(args.out)
    receipt = build_receipt(
        repo=repo,
        reference_root=reference_root,
        inventory_receipt=inventory,
        bootstrap_receipt=bootstrap,
        native_goal_organ_receipt=native_goal,
        function_slash_commands_receipt=function_slash,
        uiux_repl_components_receipt=uiux,
        backend_coordinator_agents_receipt=backend_coordinator,
        launch_packaging_receipt=launch_packaging,
        process_supervision_receipt=process_supervision,
        hook_runner_receipt=hook_runner,
        tool_dispatch_permissions_receipt=tool_dispatch_permissions,
        state_persistence_receipt=state_persistence,
        receipt_store_receipt=receipt_store,
        rollback_rewind_receipt=rollback_rewind,
        communication_mailbox_computer_use_receipt=communication,
        cleanroom_legal_boundary_receipt=cleanroom_legal_boundary,
        real_observation_receipt=real_observation,
        out=out,
    )
    write_receipt(out, receipt)
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["verdict"] == "THE_PREDECESSOR_CLI_FULL_PARITY_HARNESS_GATE_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
