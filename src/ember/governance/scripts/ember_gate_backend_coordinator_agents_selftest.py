#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import ember_gate_backend_coordinator_agents as gate


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        audit = root / "ui-parity-audit-pass3.md"
        uiux = root / "uiux.json"
        out = root / "backend.json"
        _write(
            audit,
            """| Component | Tag | Source file:line | Rationale |
|-----------|-----|------------------|-----------|
| `coordinator/coordinatorMode` | `derivative` | coordinator/coordinatorMode.ts:38 | Local mode switch. |
| `coordinator/workerAgent` | `derivative` | coordinator/workerAgent.ts:1 | Worker pool contract. |
| `AgentTool/built-in/exploreAgent` | `derivative` | tools/AgentTool/built-in/exploreAgent.ts:13 | Local search agent. |
| `AgentTool/built-in/generalPurposeAgent` | `derivative` | tools/AgentTool/built-in/generalPurposeAgent.ts:3 | Local general agent. |
| `AgentTool/built-in/planAgent` | `derivative` | tools/AgentTool/built-in/planAgent.ts:21 | Local planning agent. |
| `AgentTool/built-in/verificationAgent` | `identical` | tools/AgentTool/built-in/verificationAgent.ts:22 | Local verification agent. |
| `AgentTool/AgentTool` | `identical` | tools/AgentTool/AgentTool.tsx:1 | Tool infra. |
| `AgentTool/prompt` | `identical` | tools/AgentTool/prompt.ts:1 | Listing prompt. |
| `AgentTool/runAgent` | `derivative` | tools/AgentTool/runAgent.ts:1 | Runner. |
| `AgentTool/builtInAgents` | `derivative` | tools/AgentTool/builtInAgents.ts:1 | Registry. |
| `SendMessageTool/SendMessageTool` | `identical` | tools/SendMessageTool/SendMessageTool.ts:589 | Remote the assistant model cloud bridge. |
| `SendMessageTool/prompt` | `identical` | tools/SendMessageTool/prompt.ts:1 | Local message prompt. |
| `TeamCreateTool` | `identical` | tools/TeamCreateTool/*.ts | Team create. |
| `TeamDeleteTool` | `identical` | tools/TeamDeleteTool/*.ts | Team delete. |
| `tasks/LocalAgentTask/LocalAgentTask` | `derivative` | tasks/LocalAgentTask/LocalAgentTask.tsx:44 | Local lifecycle. |
| `tasks/RemoteAgentTask/RemoteAgentTask` | `identical` | tasks/RemoteAgentTask/RemoteAgentTask.tsx:149 | the assistant model.ai remote. |
| `components/CoordinatorAgentStatus` | `derivative` | components/CoordinatorAgentStatus.tsx:34 | Task panel. |
| `skills/bundled/scheduleRemoteAgents` | `identical` | skills/bundled/scheduleRemoteAgents.ts:176 | the model vendor cloud scheduler. |
| `skills/bundled/assistantApi` | `identical` | skills/bundled/assistantApi.ts:184 | the assistant model API skill. |
| `skills/bundled/assistantApiContent` | `identical` | skills/bundled/assistantApiContent.ts:38 | the assistant model model docs. |
""",
        )
        _write(uiux, json.dumps({"ticket": "EMBER-GATE-UIUX-REPL-COMPONENTS", "verdict": "UIUX_REPL_COMPONENTS_GATE_PASS"}))
        receipt = gate.build_receipt(repo=root, audit=audit, uiux_receipt=uiux, out=out)
        assert receipt["verdict"] == "BACKEND_COORDINATOR_AGENTS_GATE_PASS"
        assert receipt["backend_coordinator_agents"]["contract_counts"]["n_components"] == 20
        assert receipt["backend_coordinator_agents"]["contract_counts"]["n_unclassified"] == 0
        assert receipt["verification"]["checks"]["lifecycle_executes_delegation_worker_completion_and_handoff"] is True
        assert receipt["verification"]["checks"]["built_in_agent_selection_not_single_route"] is True
        assert receipt["deletion_ablation"]["coordinator_backend_deleted_blocks_delegation"] is True
        assert receipt["deletion_ablation"]["manual_codex_steering_insufficient"] is True
    print("EMBER_GATE_BACKEND_COORDINATOR_AGENTS_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
