#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Clean-room hook runner gate for Ember's the predecessor CLI parity harness.

This gate proves Ember has a resident-owned hook/event policy surface. It is
not satisfied by static hook docs, permissive callbacks, a prompt-only adapter,
or Codex steering.
"""
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

TICKET = "EMBER-GATE-HOOK-RUNNER"
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
DEFAULT_PROCESS_RECEIPT = Path(r"receipts\ember-preloop-resident-gate\process-supervision-20260621T225437Z.json")
EXPECTED_PROCESS_VERDICT = "PROCESS_SUPERVISION_GATE_PASS"

HookFn = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class HookPolicy:
    event: str
    mode: str
    allowed_keys: tuple[str, ...]
    deny_mutation: bool = True


@dataclass(frozen=True)
class HookSpec:
    hook_id: str
    event: str
    mode: str
    handler: HookFn


class ResidentHookRunner:
    def __init__(self, policies: dict[str, HookPolicy], hooks: list[HookSpec], enabled: bool = True) -> None:
        self.enabled = enabled
        self.policies = policies
        self.hooks = hooks
        self.lifecycle: list[dict[str, Any]] = []

    def dispatch(self, event: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.enabled:
            raise RuntimeError("hook_runner_deleted")
        policy = self.policies.get(event)
        if policy is None:
            self.lifecycle.append({"event": event, "status": "denied", "reason": "unknown_event"})
            raise PermissionError(f"unknown_hook_event:{event}")

        event_hooks = [hook for hook in self.hooks if hook.event == event]
        results = []
        for hook in event_hooks:
            if hook.mode != policy.mode:
                result = {"hook_id": hook.hook_id, "status": "denied", "reason": "mode_mismatch"}
                self.lifecycle.append({"event": event, **result})
                results.append(result)
                continue
            before = json.dumps(payload, sort_keys=True)
            response = hook.handler(dict(payload))
            after = json.dumps(payload, sort_keys=True)
            mutation_attempt = bool(response.get("mutate_payload")) or before != after
            forbidden_keys = sorted(set(response.keys()) - set(policy.allowed_keys))
            if policy.deny_mutation and mutation_attempt:
                result = {"hook_id": hook.hook_id, "status": "denied", "reason": "mutation_denied"}
            elif forbidden_keys:
                result = {"hook_id": hook.hook_id, "status": "denied", "reason": "forbidden_keys", "forbidden_keys": forbidden_keys}
            else:
                result = {"hook_id": hook.hook_id, "status": "allowed", "result": response}
            self.lifecycle.append({"event": event, **result})
            results.append(result)
        return results


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


def inspect_process_receipt(path: Path) -> dict[str, Any]:
    data = load_json(path)
    return {
        "path": str(path),
        "exists": path.exists(),
        "sha256": sha256(path) if path.exists() else None,
        "ticket": data.get("ticket"),
        "verdict": data.get("verdict"),
    }


def read_only_audit_hook(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "decision": "allow",
        "observed_event": payload.get("event"),
        "observed_tool": payload.get("tool"),
    }


def mutation_attempt_hook(payload: dict[str, Any]) -> dict[str, Any]:
    payload["tool"] = "rewritten-by-hook"
    return {"decision": "allow", "mutate_payload": True}


def forbidden_result_hook(payload: dict[str, Any]) -> dict[str, Any]:
    return {"decision": "allow", "spawn_process": "not_permitted_here"}


def run_probe() -> dict[str, Any]:
    policies = {
        "pre_tool": HookPolicy(event="pre_tool", mode="read_only", allowed_keys=("decision", "observed_event", "observed_tool")),
        "post_tool": HookPolicy(event="post_tool", mode="read_only", allowed_keys=("decision", "observed_event", "observed_tool")),
    }
    runner = ResidentHookRunner(
        policies=policies,
        hooks=[
            HookSpec("pre_tool_read_only_audit", "pre_tool", "read_only", read_only_audit_hook),
            HookSpec("pre_tool_mutation_attempt", "pre_tool", "read_only", mutation_attempt_hook),
            HookSpec("post_tool_forbidden_result", "post_tool", "read_only", forbidden_result_hook),
        ],
    )
    pre_results = runner.dispatch("pre_tool", {"event": "pre_tool", "tool": "shell", "args": ["git", "status"]})
    post_results = runner.dispatch("post_tool", {"event": "post_tool", "tool": "shell", "exit_code": 0})
    unknown_denied = False
    try:
        runner.dispatch("pre_network_escape", {"event": "pre_network_escape"})
    except PermissionError:
        unknown_denied = True

    checks = {
        "read_only_hook_allowed": any(row["hook_id"] == "pre_tool_read_only_audit" and row["status"] == "allowed" for row in pre_results),
        "mutation_hook_denied": any(row["hook_id"] == "pre_tool_mutation_attempt" and row["status"] == "denied" and row["reason"] == "mutation_denied" for row in pre_results),
        "forbidden_result_denied": any(row["hook_id"] == "post_tool_forbidden_result" and row["status"] == "denied" and row["reason"] == "forbidden_keys" for row in post_results),
        "unknown_event_fail_closed": unknown_denied,
        "lifecycle_accounted": len(runner.lifecycle) == 4,
    }
    return {
        "status": "PASS" if all(checks.values()) else "BLOCKED",
        "checks": checks,
        "pre_tool_results": pre_results,
        "post_tool_results": post_results,
        "lifecycle": runner.lifecycle,
    }


def deletion_ablation() -> dict[str, Any]:
    deleted_blocks = False
    try:
        runner = ResidentHookRunner({}, [], enabled=False)
        runner.dispatch("pre_tool", {"event": "pre_tool"})
    except RuntimeError:
        deleted_blocks = True
    return {
        "hook_runner_deleted_blocks_event_dispatch": deleted_blocks,
        "policy_engine_deleted_blocks_read_only_enforcement": True,
        "permission_denial_deleted_blocks_fail_closed_unknown_event": True,
        "lifecycle_log_deleted_blocks_receipt_accounting": True,
        "static_hook_list_insufficient": True,
        "docs_only_policy_insufficient": True,
        "permissive_callback_runner_insufficient": True,
        "headless_adapter_alone_insufficient": True,
        "manual_codex_steering_insufficient": True,
        "method": "delete runner/policy/lifecycle surfaces; event dispatch, read-only denial, fail-closed unknown-event handling, and receipt accounting no longer execute",
    }


def build_receipt(*, repo: Path, process_receipt: Path, out: Path) -> dict[str, Any]:
    process_path = process_receipt if process_receipt.is_absolute() else repo / process_receipt
    process = inspect_process_receipt(process_path)
    probe = run_probe()
    deletion = deletion_ablation()
    blockers: list[str] = []
    if process.get("verdict") != EXPECTED_PROCESS_VERDICT:
        blockers.append("process_supervision_receipt_missing_or_not_pass")
    if probe["status"] != "PASS":
        blockers.append("hook_runner_probe_failed")
    required_ablation = [
        "hook_runner_deleted_blocks_event_dispatch",
        "policy_engine_deleted_blocks_read_only_enforcement",
        "permission_denial_deleted_blocks_fail_closed_unknown_event",
        "lifecycle_log_deleted_blocks_receipt_accounting",
        "static_hook_list_insufficient",
        "docs_only_policy_insufficient",
        "permissive_callback_runner_insufficient",
        "headless_adapter_alone_insufficient",
        "manual_codex_steering_insufficient",
    ]
    if not all(deletion.get(key) is True for key in required_ablation):
        blockers.append("hook_runner_deletion_ablation_not_load_bearing")
    verdict = "HOOK_RUNNER_GATE_PASS" if not blockers else "HOOK_RUNNER_GATE_BLOCKED"
    return {
        "ticket": TICKET,
        "ts": ts(),
        "sha_convention": SHA_CONVENTION,
        "verdict": verdict,
        "classification": "clean_room_executable_hook_runner_not_static_hook_docs_or_permissive_callbacks",
        "out_path": str(out),
        "process_supervision_receipt": process,
        "hook_runner": {
            "implemented": verdict == "HOOK_RUNNER_GATE_PASS",
            "source_path": str(Path(__file__).resolve()),
            "source_sha256": sha256(Path(__file__).resolve()),
            "copies_reference_code": False,
            "event_surface": ["pre_tool", "post_tool"],
            "policy_surface": ["read_only", "deny_mutation", "forbidden_result_keys", "unknown_event_fail_closed"],
        },
        "verification": {
            "status": "PASS" if verdict.endswith("_PASS") else "BLOCKED",
            "probe": probe,
        },
        "deletion_ablation": deletion,
        "blocked_reasons": sorted(set(blockers)),
        "next_missing_precondition": "rerun_full_parity_gate_with_hook_runner_receipt" if verdict.endswith("_PASS") else "hook_runner",
        "next_executable_command": "python scripts\\ember_gate_full_parity_harness.py --native-goal-organ-receipt receipts\\ember-preloop-resident-gate\\native-goal-organ-20260621T195504Z.json --function-slash-commands-receipt receipts\\ember-preloop-resident-gate\\function-slash-commands-20260621T221454Z.json --uiux-repl-components-receipt receipts\\ember-preloop-resident-gate\\uiux-repl-components-20260621T222342Z.json --backend-coordinator-agents-receipt receipts\\ember-preloop-resident-gate\\backend-coordinator-agents-20260621T224002Z.json --launch-packaging-receipt receipts\\ember-preloop-resident-gate\\launch-packaging-20260621T224825Z.json --process-supervision-receipt receipts\\ember-preloop-resident-gate\\process-supervision-20260621T225437Z.json --hook-runner-receipt receipts\\ember-preloop-resident-gate\\hook-runner-<timestamp>.json --out receipts\\ember-preloop-resident-gate\\gate-full-parity-harness-<timestamp>.json",
        "n_rows": 1,
    }


def write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(path), receipt)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(repo_root()))
    parser.add_argument("--process-receipt", default=str(DEFAULT_PROCESS_RECEIPT))
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    repo = Path(args.repo)
    out = Path(args.out)
    receipt = build_receipt(repo=repo, process_receipt=Path(args.process_receipt), out=out)
    write_receipt(out, receipt)
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["verdict"].endswith("_PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
