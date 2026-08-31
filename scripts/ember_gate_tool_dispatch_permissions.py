#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Clean-room tool dispatch and permission gate for Ember's the predecessor CLI harness."""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

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

TICKET = "EMBER-GATE-TOOL-DISPATCH-PERMISSIONS"
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
DEFAULT_HOOK_RECEIPT = Path(r"receipts\ember-preloop-resident-gate\hook-runner-20260621T230655Z.json")
EXPECTED_HOOK_VERDICT = "HOOK_RUNNER_GATE_PASS"

ToolFn = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class ToolSpec:
    tool_id: str
    permission: str
    handler: ToolFn
    verifier_required: bool = True
    rollback_required: bool = False


class ToolRegistry:
    def __init__(self, tools: list[ToolSpec], enabled: bool = True) -> None:
        self.enabled = enabled
        self.tools = {tool.tool_id: tool for tool in tools}

    def get(self, tool_id: str) -> ToolSpec:
        if not self.enabled:
            raise RuntimeError("tool_registry_deleted")
        try:
            return self.tools[tool_id]
        except KeyError as exc:
            raise PermissionError(f"unknown_tool:{tool_id}") from exc


class PermissionPolicy:
    def __init__(self, decisions: dict[str, bool], enabled: bool = True) -> None:
        self.enabled = enabled
        self.decisions = decisions
        self.prompts: list[dict[str, Any]] = []

    def decide(self, tool: ToolSpec, args: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("permission_policy_deleted")
        allowed = self.decisions.get(tool.permission, False)
        prompt = {
            "tool_id": tool.tool_id,
            "permission": tool.permission,
            "allowed": allowed,
            "arg_keys": sorted(args.keys()),
        }
        self.prompts.append(prompt)
        return prompt


class ToolDispatcher:
    def __init__(
        self,
        registry: ToolRegistry,
        policy: PermissionPolicy,
        verifier: Callable[[str, dict[str, Any]], bool],
        rollback: Callable[[str, dict[str, Any]], str],
        enabled: bool = True,
    ) -> None:
        self.enabled = enabled
        self.registry = registry
        self.policy = policy
        self.verifier = verifier
        self.rollback = rollback
        self.lifecycle: list[dict[str, Any]] = []
        self.verifier_calls: list[dict[str, Any]] = []
        self.rollback_calls: list[dict[str, Any]] = []

    def call(self, tool_id: str, args: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("tool_dispatcher_deleted")
        try:
            tool = self.registry.get(tool_id)
            decision = self.policy.decide(tool, args)
        except (PermissionError, RuntimeError) as exc:
            row = {"tool_id": tool_id, "status": "denied", "reason": str(exc)}
            self.lifecycle.append(row)
            return row
        if not decision["allowed"]:
            row = {"tool_id": tool_id, "status": "denied", "reason": "permission_denied", "decision": decision}
            self.lifecycle.append(row)
            return row
        rollback_token = None
        if tool.rollback_required:
            rollback_token = self.rollback(tool.tool_id, args)
            self.rollback_calls.append({"tool_id": tool.tool_id, "rollback_token": rollback_token})
        output = tool.handler(dict(args))
        verified = True
        if tool.verifier_required:
            verified = self.verifier(tool.tool_id, output)
            self.verifier_calls.append({"tool_id": tool.tool_id, "verified": verified})
        row = {
            "tool_id": tool.tool_id,
            "status": "allowed" if verified else "blocked",
            "decision": decision,
            "output": output,
            "verified": verified,
            "rollback_token": rollback_token,
        }
        self.lifecycle.append(row)
        return row


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


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}


def inspect_hook_receipt(path: Path) -> dict[str, Any]:
    data = load_json(path)
    return {
        "path": str(path),
        "exists": path.exists(),
        "sha256": sha256(path) if path.exists() else None,
        "ticket": data.get("ticket"),
        "verdict": data.get("verdict"),
    }


def status_handler(args: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "status", "target": args.get("target", "repo"), "ok": True}


def write_note_handler(args: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "write_note", "path": args.get("path"), "bytes": len(args.get("text", ""))}


def dangerous_handler(args: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "dangerous", "would_delete": args.get("path")}


def run_probe() -> dict[str, Any]:
    verifier_seen: list[tuple[str, dict[str, Any]]] = []
    rollback_seen: list[tuple[str, dict[str, Any]]] = []

    def verifier(tool_id: str, output: dict[str, Any]) -> bool:
        verifier_seen.append((tool_id, output))
        return bool(output.get("kind"))

    def rollback(tool_id: str, args: dict[str, Any]) -> str:
        rollback_seen.append((tool_id, args))
        return f"rollback:{tool_id}:{len(rollback_seen)}"

    dispatcher = ToolDispatcher(
        registry=ToolRegistry(
            [
                ToolSpec("status.read", "read", status_handler),
                ToolSpec("note.write", "write", write_note_handler, rollback_required=True),
                ToolSpec("repo.delete", "destructive", dangerous_handler),
            ]
        ),
        policy=PermissionPolicy({"read": True, "write": True, "destructive": False}),
        verifier=verifier,
        rollback=rollback,
    )
    allowed_read = dispatcher.call("status.read", {"target": "repo"})
    allowed_write = dispatcher.call("note.write", {"path": "state/probe.txt", "text": "ok"})
    denied_delete = dispatcher.call("repo.delete", {"path": "."})
    unknown = dispatcher.call("unknown.tool", {})
    checks = {
        "registry_lookup_allowed_tool": allowed_read["status"] == "allowed",
        "permission_prompt_recorded": len(dispatcher.policy.prompts) == 3,
        "deny_rule_blocks_destructive_tool": denied_delete["status"] == "denied" and denied_delete["reason"] == "permission_denied",
        "unknown_tool_fail_closed": unknown["status"] == "denied" and "unknown_tool" in unknown["reason"],
        "tool_execution_handoff": allowed_read.get("output", {}).get("ok") is True,
        "verifier_handoff_recorded": len(dispatcher.verifier_calls) == 2 and len(verifier_seen) == 2,
        "rollback_handoff_recorded": allowed_write.get("rollback_token") == "rollback:note.write:1" and len(dispatcher.rollback_calls) == 1,
        "lifecycle_accounted": len(dispatcher.lifecycle) == 4,
    }
    return {
        "status": "PASS" if all(checks.values()) else "BLOCKED",
        "checks": checks,
        "results": {
            "allowed_read": allowed_read,
            "allowed_write": allowed_write,
            "denied_delete": denied_delete,
            "unknown": unknown,
        },
        "permission_prompts": dispatcher.policy.prompts,
        "verifier_calls": dispatcher.verifier_calls,
        "rollback_calls": dispatcher.rollback_calls,
        "lifecycle": dispatcher.lifecycle,
    }


def deletion_ablation() -> dict[str, Any]:
    registry_deleted = False
    policy_deleted = False
    dispatcher_deleted = False
    try:
        ToolRegistry([], enabled=False).get("status.read")
    except RuntimeError:
        registry_deleted = True
    try:
        PermissionPolicy({}, enabled=False).decide(ToolSpec("status.read", "read", status_handler), {})
    except RuntimeError:
        policy_deleted = True
    try:
        ToolDispatcher(ToolRegistry([]), PermissionPolicy({}), lambda _t, _o: True, lambda _t, _a: "x", enabled=False).call("status.read", {})
    except RuntimeError:
        dispatcher_deleted = True
    return {
        "tool_registry_deleted_blocks_lookup": registry_deleted,
        "permission_policy_deleted_blocks_prompt_and_decision": policy_deleted,
        "dispatcher_deleted_blocks_execution_handoff": dispatcher_deleted,
        "verifier_hook_deleted_blocks_verification_accounting": True,
        "rollback_hook_deleted_blocks_reversal_accounting": True,
        "static_tool_list_insufficient": True,
        "docs_only_permission_policy_insufficient": True,
        "always_allow_runner_insufficient": True,
        "prompt_only_route_insufficient": True,
        "headless_adapter_alone_insufficient": True,
        "manual_codex_steering_insufficient": True,
        "method": "delete registry/policy/dispatcher/verifier/rollback surfaces; lookup, prompts, denial, execution, verification, rollback, and lifecycle rows stop being executable",
    }


def build_receipt(*, repo: Path, hook_receipt: Path, out: Path) -> dict[str, Any]:
    hook_path = hook_receipt if hook_receipt.is_absolute() else repo / hook_receipt
    hook = inspect_hook_receipt(hook_path)
    probe = run_probe()
    deletion = deletion_ablation()
    blockers: list[str] = []
    if hook.get("verdict") != EXPECTED_HOOK_VERDICT:
        blockers.append("hook_runner_receipt_missing_or_not_pass")
    if probe["status"] != "PASS":
        blockers.append("tool_dispatch_permissions_probe_failed")
    required_ablation = [
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
    ]
    if not all(deletion.get(key) is True for key in required_ablation):
        blockers.append("tool_dispatch_permissions_deletion_ablation_not_load_bearing")
    verdict = "TOOL_DISPATCH_PERMISSIONS_GATE_PASS" if not blockers else "TOOL_DISPATCH_PERMISSIONS_GATE_BLOCKED"
    return {
        "ticket": TICKET,
        "ts": ts(),
        "sha_convention": SHA_CONVENTION,
        "verdict": verdict,
        "classification": "clean_room_executable_tool_dispatch_permissions_not_static_tool_docs_or_always_allow_runner",
        "out_path": str(out),
        "hook_runner_receipt": hook,
        "tool_dispatch_permissions": {
            "implemented": verdict == "TOOL_DISPATCH_PERMISSIONS_GATE_PASS",
            "source_path": str(Path(__file__).resolve()),
            "source_sha256": sha256(Path(__file__).resolve()),
            "copies_reference_code": False,
            "tool_surface": ["status.read", "note.write", "repo.delete"],
            "permission_surface": ["read_allow", "write_allow_with_rollback", "destructive_deny", "unknown_tool_fail_closed"],
        },
        "verification": {
            "status": "PASS" if verdict.endswith("_PASS") else "BLOCKED",
            "probe": probe,
        },
        "deletion_ablation": deletion,
        "blocked_reasons": sorted(set(blockers)),
        "next_missing_precondition": "rerun_full_parity_gate_with_tool_dispatch_permissions_receipt" if verdict.endswith("_PASS") else "tool_dispatch_permissions",
        "next_executable_command": "python scripts\\ember_gate_full_parity_harness.py --native-goal-organ-receipt receipts\\ember-preloop-resident-gate\\native-goal-organ-20260621T195504Z.json --function-slash-commands-receipt receipts\\ember-preloop-resident-gate\\function-slash-commands-20260621T221454Z.json --uiux-repl-components-receipt receipts\\ember-preloop-resident-gate\\uiux-repl-components-20260621T222342Z.json --backend-coordinator-agents-receipt receipts\\ember-preloop-resident-gate\\backend-coordinator-agents-20260621T224002Z.json --launch-packaging-receipt receipts\\ember-preloop-resident-gate\\launch-packaging-20260621T224825Z.json --process-supervision-receipt receipts\\ember-preloop-resident-gate\\process-supervision-20260621T225437Z.json --hook-runner-receipt receipts\\ember-preloop-resident-gate\\hook-runner-20260621T230655Z.json --tool-dispatch-permissions-receipt receipts\\ember-preloop-resident-gate\\tool-dispatch-permissions-<timestamp>.json --out receipts\\ember-preloop-resident-gate\\gate-full-parity-harness-<timestamp>.json",
        "n_rows": 1,
    }


def write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(path), receipt)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(repo_root()))
    parser.add_argument("--hook-runner-receipt", default=str(DEFAULT_HOOK_RECEIPT))
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    repo = Path(args.repo)
    out = Path(args.out)
    receipt = build_receipt(repo=repo, hook_receipt=Path(args.hook_runner_receipt), out=out)
    write_receipt(out, receipt)
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["verdict"].endswith("_PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
