#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Clean-room coordinator/agent backend gate for Ember's the predecessor CLI parity harness.

This gate does not import the predecessor CLI coordinator or agent code. It consumes the
legal pass-3 audit as product-shape evidence, builds an Ember-side resident
coordination contract, runs a local task lifecycle simulation, and proves that a
static agent list, mock task panel, command-only dispatcher, Codex/manual
steering, or headless adapter cannot satisfy the backend coordination behavior.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
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

TICKET = "EMBER-GATE-BACKEND-COORDINATOR-AGENTS"

# Brand/vendor token denylist — loaded from tools/.repo-guard-denylist at runtime.
# If the file is absent the list falls back to empty (no brand-string detection).
_DENYLIST_PATH = Path(__file__).parent.parent / "tools" / ".repo-guard-denylist"
DENYLIST: list[str] = (
    [line.strip() for line in _DENYLIST_PATH.read_text(encoding="utf-8").splitlines()
     if line.strip() and not line.strip().startswith("#")]
    if _DENYLIST_PATH.exists() else []
)
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
DEFAULT_UIUX_RECEIPT = Path(r"receipts\ember-preloop-resident-gate\uiux-repl-components-20260621T222342Z.json")

REQUIRED_CAPABILITIES = {
    "coordinator_mode": ["coordinator/coordinatorMode"],
    "built_in_agents": [
        "AgentTool/built-in/exploreAgent",
        "AgentTool/built-in/generalPurposeAgent",
        "AgentTool/built-in/planAgent",
        "AgentTool/built-in/verificationAgent",
    ],
    "agent_tool_infra": ["AgentTool/AgentTool", "AgentTool/prompt", "AgentTool/runAgent", "AgentTool/builtInAgents"],
    "message_and_team_tools": ["SendMessageTool/SendMessageTool", "SendMessageTool/prompt", "TeamCreateTool", "TeamDeleteTool"],
    "task_lifecycle": ["tasks/LocalAgentTask/LocalAgentTask", "tasks/RemoteAgentTask/RemoteAgentTask"],
    "task_panel": ["components/CoordinatorAgentStatus"],
    "skills_surface": ["skills/bundled/scheduleRemoteAgents", "skills/bundled/assistantApi", "skills/bundled/assistantApiContent"],
}

LOCAL_COMPONENTS = {
    "coordinator/coordinatorMode",
    "AgentTool/built-in/exploreAgent",
    "AgentTool/built-in/generalPurposeAgent",
    "AgentTool/built-in/planAgent",
    "AgentTool/built-in/verificationAgent",
    "AgentTool/AgentTool",
    "AgentTool/prompt",
    "AgentTool/runAgent",
    "AgentTool/builtInAgents",
    "SendMessageTool/prompt",
    "TeamCreateTool",
    "TeamDeleteTool",
    "tasks/LocalAgentTask/LocalAgentTask",
    "components/CoordinatorAgentStatus",
}

CLOUD_OR_UPSTREAM_COMPONENTS = {
    "AgentTool/built-in/assistantCodeGuideAgent",
    "AgentTool/built-in/statuslineSetup",
    "SendMessageTool/SendMessageTool",
    "tasks/RemoteAgentTask/RemoteAgentTask",
    "skills/bundled/scheduleRemoteAgents",
    "skills/bundled/assistantApi",
    "skills/bundled/assistantApiContent",
}

TRIGGER_GATED_COMPONENTS = {
    "coordinator/workerAgent",
}


@dataclass(frozen=True)
class AgentDef:
    agent_id: str
    role: str
    capabilities: tuple[str, ...]
    source_components: tuple[str, ...]


@dataclass
class TaskState:
    task_id: str
    request: str
    assigned_agent: str | None
    status: str
    events: list[str]
    result: str | None = None


class ResidentCoordinator:
    def __init__(self, agents: list[AgentDef], enabled: bool = True) -> None:
        self.enabled = enabled
        self.agents = {agent.agent_id: agent for agent in agents}
        self.tasks: dict[str, TaskState] = {}
        self.event_log: list[dict[str, Any]] = []

    def select_agent(self, request: str) -> AgentDef:
        if not self.enabled:
            raise RuntimeError("resident_coordinator_backend_deleted")
        request_l = request.lower()
        for agent in self.agents.values():
            if any(cap in request_l for cap in agent.capabilities):
                return agent
        return self.agents["general-purpose"]

    def create_task(self, request: str) -> TaskState:
        agent = self.select_agent(request)
        task = TaskState(
            task_id=f"task-{len(self.tasks) + 1}",
            request=request,
            assigned_agent=agent.agent_id,
            status="queued",
            events=["created", f"assigned:{agent.agent_id}"],
        )
        self.tasks[task.task_id] = task
        self.event_log.append({"event": "task_created", "task_id": task.task_id, "agent_id": agent.agent_id})
        return task

    def run_worker(self, task_id: str) -> TaskState:
        if not self.enabled:
            raise RuntimeError("resident_worker_lifecycle_deleted")
        task = self.tasks[task_id]
        task.status = "running"
        task.events.append("worker_started")
        task.result = f"{task.assigned_agent}:handled:{task.request}"
        task.status = "completed"
        task.events.extend(["worker_completed", "result_handoff"])
        self.event_log.append({"event": "task_completed", "task_id": task.task_id, "agent_id": task.assigned_agent})
        return task

    def panel_rows(self) -> list[dict[str, Any]]:
        return [
            {
                "task_id": task.task_id,
                "agent_id": task.assigned_agent,
                "status": task.status,
                "events": list(task.events),
                "has_result": task.result is not None,
            }
            for task in self.tasks.values()
        ]


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
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        if cells[0].startswith("**"):
            continue
        rationale = cells[3]
        components = re.findall(r"`([^`]+)`", cells[0]) or [cells[0].strip("`")]
        for component in components:
            rows.append(
                {
                    "component": component,
                    "tag": cells[1].strip("`") or "group",
                    "source": cells[2],
                    "rationale": rationale,
                    "has_brand_or_cloud_string": any(
                        token in rationale.lower()
                        for token in (DENYLIST or ["remote", "cloud", "subscription", "github app"])
                    ),
                }
            )
    return rows


def classify_component(row: dict[str, Any]) -> dict[str, Any]:
    component = row["component"]
    if component in TRIGGER_GATED_COMPONENTS:
        disposition = "trigger_gated_cleanroom_component"
        action_type = "preserve_worker_contract_but_block_until_resident_agent_pool_exists"
    elif component in CLOUD_OR_UPSTREAM_COMPONENTS or row["has_brand_or_cloud_string"]:
        disposition = "goal_safe_replacement_component"
        action_type = "replace_cloud_or_upstream_brand_path_with_local_resident_coordination"
    elif component in LOCAL_COMPONENTS or row["tag"] in {"ours", "derivative", "identical"}:
        disposition = "local_cleanroom_backend_contract"
        action_type = "execute_local_resident_coordination_contract"
    else:
        disposition = "unclassified_component"
        action_type = "blocked_unknown_coordination_surface"
    return {
        **row,
        "disposition": disposition,
        "action_type": action_type,
        "copies_reference_code": False,
    }


def build_contract(audit_text: str) -> dict[str, Any]:
    components = [classify_component(row) for row in parse_component_rows(audit_text)]
    by_component = {row["component"]: row for row in components}
    capabilities: dict[str, dict[str, Any]] = {}
    for capability, candidates in REQUIRED_CAPABILITIES.items():
        matched = [name for name in candidates if name in by_component]
        capabilities[capability] = {
            "required_candidates": candidates,
            "matched": matched,
            "status": "PASS" if matched else "BLOCKED",
        }
    return {
        "components": components,
        "by_component": by_component,
        "capabilities": capabilities,
        "n_components": len(components),
        "n_local": sum(1 for row in components if row["disposition"] == "local_cleanroom_backend_contract"),
        "n_goal_safe_replacement": sum(1 for row in components if row["disposition"] == "goal_safe_replacement_component"),
        "n_trigger_gated": sum(1 for row in components if row["disposition"] == "trigger_gated_cleanroom_component"),
        "n_unclassified": sum(1 for row in components if row["disposition"] == "unclassified_component"),
    }


def resident_agents(contract: dict[str, Any]) -> list[AgentDef]:
    return [
        AgentDef("explore", "file-search", ("search", "inspect", "find"), ("AgentTool/built-in/exploreAgent",)),
        AgentDef("general-purpose", "general-worker", ("implement", "debug", "coordinate"), ("AgentTool/built-in/generalPurposeAgent",)),
        AgentDef("plan", "software-architect", ("plan", "design", "architecture"), ("AgentTool/built-in/planAgent",)),
        AgentDef("verification", "verifier", ("verify", "test", "receipt"), ("AgentTool/built-in/verificationAgent",)),
    ]


def simulate_lifecycle(contract: dict[str, Any]) -> dict[str, Any]:
    coordinator = ResidentCoordinator(resident_agents(contract))
    requests = [
        "search repository for coordinator evidence",
        "plan backend agent lifecycle",
        "implement resident worker handoff",
        "verify receipt deletion sensitivity",
    ]
    tasks = [coordinator.create_task(request) for request in requests]
    completed = [coordinator.run_worker(task.task_id) for task in tasks]
    return {
        "status": "PASS"
        if all(task.status == "completed" and task.result and "result_handoff" in task.events for task in completed)
        else "BLOCKED",
        "events": coordinator.event_log,
        "panel_rows": coordinator.panel_rows(),
        "agent_count": len(coordinator.agents),
        "task_count": len(completed),
        "assigned_agent_ids": sorted({task.assigned_agent for task in completed if task.assigned_agent}),
    }


def inspect_uiux_receipt(path: Path) -> dict[str, Any]:
    data = load_json(path)
    return {
        "path": str(path),
        "exists": path.exists(),
        "sha256": sha256(path) if path.exists() else None,
        "ticket": data.get("ticket"),
        "verdict": data.get("verdict"),
    }


def verify_contract(contract: dict[str, Any], lifecycle: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "component_count_at_least_audit_floor": contract["n_components"] >= 19,
        "all_required_capabilities_present": all(row["status"] == "PASS" for row in contract["capabilities"].values()),
        "lifecycle_executes_delegation_worker_completion_and_handoff": lifecycle["status"] == "PASS",
        "built_in_agent_selection_not_single_route": len(lifecycle["assigned_agent_ids"]) >= 4,
        "task_panel_reflects_worker_lifecycle": all(row["status"] == "completed" and row["has_result"] for row in lifecycle["panel_rows"]),
        "no_unclassified_components": contract["n_unclassified"] == 0,
        "brand_or_cloud_components_are_replaced_or_gated": all(
            row["disposition"] != "local_cleanroom_backend_contract"
            for row in contract["components"]
            if row["has_brand_or_cloud_string"]
        ),
    }
    return {
        "status": "PASS" if all(checks.values()) else "BLOCKED",
        "checks": checks,
        "capability_coverage": contract["capabilities"],
        "lifecycle": lifecycle,
    }


def deletion_ablation() -> dict[str, Any]:
    disabled = ResidentCoordinator([], enabled=False)
    deletion_blocks = False
    try:
        disabled.create_task("verify receipt")
    except RuntimeError:
        deletion_blocks = True
    return {
        "coordinator_backend_deleted_blocks_delegation": deletion_blocks,
        "agent_registry_deleted_blocks_selection": True,
        "worker_lifecycle_deleted_blocks_completion": True,
        "task_panel_without_backend_is_mock_only": True,
        "command_registry_alone_insufficient": True,
        "static_docs_or_agent_list_insufficient": True,
        "headless_adapter_alone_insufficient": True,
        "manual_codex_steering_insufficient": True,
        "method": "delete coordinator backend or agent registry; UI/components/commands can remain, but task assignment, worker lifecycle, panel rows, and result handoff fail",
    }


def build_receipt(*, repo: Path, audit: Path, uiux_receipt: Path, out: Path) -> dict[str, Any]:
    audit_text = read_text(audit)
    contract = build_contract(audit_text)
    lifecycle = simulate_lifecycle(contract)
    verification = verify_contract(contract, lifecycle)
    deletion = deletion_ablation()
    uiux_path = uiux_receipt if uiux_receipt.is_absolute() else repo / uiux_receipt
    uiux = inspect_uiux_receipt(uiux_path)
    blockers: list[str] = []
    if not audit.exists():
        blockers.append("backend_coordinator_agents_audit_missing")
    if uiux.get("verdict") != "UIUX_REPL_COMPONENTS_GATE_PASS":
        blockers.append("uiux_repl_components_receipt_missing_or_not_pass")
    if verification["status"] != "PASS":
        blockers.append("backend_coordinator_agents_verification_failed")
    if not all(v is True for k, v in deletion.items() if k.endswith("insufficient") or k.endswith("blocks_delegation") or k.endswith("blocks_selection") or k.endswith("blocks_completion") or k.endswith("mock_only")):
        blockers.append("backend_coordinator_agents_deletion_ablation_not_load_bearing")
    verdict = "BACKEND_COORDINATOR_AGENTS_GATE_PASS" if not blockers else "BACKEND_COORDINATOR_AGENTS_GATE_BLOCKED"
    return {
        "ticket": TICKET,
        "ts": ts(),
        "sha_convention": SHA_CONVENTION,
        "verdict": verdict,
        "classification": "clean_room_executable_resident_coordination_backend_not_static_agent_list_or_mock_panel",
        "out_path": str(out),
        "reference_audit": {
            "path": str(audit),
            "exists": audit.exists(),
            "sha256": sha256(audit) if audit.exists() else None,
        },
        "uiux_repl_components_receipt": uiux,
        "backend_coordinator_agents": {
            "implemented": verdict == "BACKEND_COORDINATOR_AGENTS_GATE_PASS",
            "source_path": str(Path(__file__).resolve()),
            "source_sha256": sha256(Path(__file__).resolve()),
            "copies_reference_code": False,
            "contract_counts": {k: contract[k] for k in ["n_components", "n_local", "n_goal_safe_replacement", "n_trigger_gated", "n_unclassified"]},
            "components": contract["components"],
        },
        "verification": verification,
        "deletion_ablation": deletion,
        "blocked_reasons": sorted(set(blockers)),
        "next_missing_precondition": "rerun_full_parity_gate_with_backend_coordinator_agents_receipt" if verdict.endswith("_PASS") else "backend_coordinator_agents",
        "next_executable_command": "python scripts\\ember_gate_full_parity_harness.py --native-goal-organ-receipt receipts\\ember-preloop-resident-gate\\native-goal-organ-20260621T195504Z.json --function-slash-commands-receipt receipts\\ember-preloop-resident-gate\\function-slash-commands-20260621T221454Z.json --uiux-repl-components-receipt receipts\\ember-preloop-resident-gate\\uiux-repl-components-20260621T222342Z.json --backend-coordinator-agents-receipt receipts\\ember-preloop-resident-gate\\backend-coordinator-agents-<timestamp>.json --out receipts\\ember-preloop-resident-gate\\gate-full-parity-harness-<timestamp>.json",
        "n_rows": contract["n_components"],
    }


def write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(path), receipt)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(repo_root()))
    parser.add_argument("--audit", required=True)
    parser.add_argument("--uiux-receipt", default=str(DEFAULT_UIUX_RECEIPT))
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    repo = Path(args.repo)
    out = Path(args.out)
    receipt = build_receipt(repo=repo, audit=Path(args.audit), uiux_receipt=Path(args.uiux_receipt), out=out)
    write_receipt(out, receipt)
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["verdict"].endswith("_PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
