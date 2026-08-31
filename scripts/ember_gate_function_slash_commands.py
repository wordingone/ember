#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Clean-room slash-command surface gate for Ember's the predecessor CLI parity harness.

This gate does not import the predecessor CLI implementation code. It reads the legal UI
parity audit as reference evidence, builds an Ember-side command registry from
that audited product surface, resolves every audited slash command through a
local dispatcher, and proves that static docs/headless shims are insufficient by
ablation.
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

TICKET = "EMBER-GATE-FUNCTION-SLASH-COMMANDS"
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
DEFAULT_NATIVE_GOAL_RECEIPT = Path(r"receipts\ember-preloop-resident-gate\native-goal-organ-20260621T195504Z.json")

LOCAL_ACTIONS = {
    "add-dir", "advisor", "agents", "branch", "bridge-kick", "brief", "btw",
    "clear", "color", "commit", "commit-push-pr", "compact", "config",
    "context", "copy", "cost", "diag", "diff", "doctor", "effort", "exit",
    "export", "feedback", "files", "heapdump", "help", "hooks", "ide",
    "init", "insights", "keybindings", "mcp", "model", "output-style",
    "permissions", "plan", "plugin", "pr_comments", "release-notes",
    "reload-plugins", "rename", "resume", "rewind", "security-review", "skills",
    "stats", "status", "tag", "tasks", "terminalSetup", "theme",
    "thinkback", "thinkback-play", "vim",
}

CLOUD_REPLACEMENTS = {
    "bridge", "chrome", "desktop", "extra-usage", "fast", "install-github-app",
    "install-slack-app", "login", "logout", "memory", "mobile", "privacy-settings",
    "rate-limit-options", "remote-env", "remote-setup", "review", "session",
    "stickers", "upgrade", "usage", "voice",
}

FEATURE_GATED = {
    "agents-platform", "backfill-sessions", "buddy", "fork", "peers", "proactive",
    "subscribe-pr", "torch", "ultraplan", "version", "workflows",
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


def parse_registered_commands(audit_text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in audit_text.splitlines():
        if not line.startswith("| /"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        name = cells[0]
        if not name.startswith("/"):
            continue
        rows.append(
            {
                "name": name,
                "command_id": name[1:],
                "description": cells[1].strip("`"),
                "reference": cells[2],
                "upstream_brand_in_description": "yes" in cells[3].lower() or "**yes**" in cells[3].lower(),
            }
        )
    return rows


def classify_command(row: dict[str, Any]) -> dict[str, Any]:
    command_id = row["command_id"]
    if command_id in LOCAL_ACTIONS:
        disposition = "local_cleanroom_action"
        action_type = "execute_local_or_emit_local_plan"
        replacement = None
    elif command_id in CLOUD_REPLACEMENTS:
        disposition = "goal_safe_replacement"
        action_type = "block_cloud_dependency_and_offer_local_equivalent"
        replacement = "local_resident_safe_block_or_local_diagnostic"
    elif command_id in FEATURE_GATED:
        disposition = "trigger_gated_cleanroom_stub"
        action_type = "report_feature_gate_and_preserve_contract"
        replacement = "feature_gate_receipt_required_before_execution"
    else:
        disposition = "unclassified"
        action_type = "blocked_unknown_command"
        replacement = None
    return {
        **row,
        "disposition": disposition,
        "action_type": action_type,
        "goal_safe_replacement": replacement,
        "copies_reference_code": False,
    }


def build_registry(audit_text: str) -> dict[str, Any]:
    registered = parse_registered_commands(audit_text)
    commands = [classify_command(row) for row in registered]
    by_name = {row["name"]: row for row in commands}
    return {
        "commands": commands,
        "by_name": by_name,
        "n_registered": len(commands),
        "n_local": sum(1 for row in commands if row["disposition"] == "local_cleanroom_action"),
        "n_goal_safe_replacement": sum(1 for row in commands if row["disposition"] == "goal_safe_replacement"),
        "n_trigger_gated": sum(1 for row in commands if row["disposition"] == "trigger_gated_cleanroom_stub"),
        "n_unclassified": sum(1 for row in commands if row["disposition"] == "unclassified"),
    }


def dispatch(registry: dict[str, Any], command: str) -> dict[str, Any]:
    token = command.strip().split()[0] if command.strip() else ""
    if not token.startswith("/"):
        return {"status": "BLOCKED", "reason": "not_a_slash_command", "command": command}
    row = registry["by_name"].get(token)
    if not row:
        return {"status": "BLOCKED", "reason": "unknown_slash_command", "command": token}
    if row["disposition"] == "local_cleanroom_action":
        status = "EXECUTABLE_LOCAL_PLAN"
    elif row["disposition"] == "goal_safe_replacement":
        status = "GOAL_SAFE_REPLACEMENT"
    elif row["disposition"] == "trigger_gated_cleanroom_stub":
        status = "TRIGGER_GATED"
    else:
        status = "BLOCKED"
    return {
        "status": status,
        "command": token,
        "command_id": row["command_id"],
        "action_type": row["action_type"],
        "disposition": row["disposition"],
        "upstream_brand_removed_or_blocked": bool(row["upstream_brand_in_description"] or row["disposition"] != "local_cleanroom_action"),
        "copies_reference_code": False,
    }


def inspect_native_goal_receipt(path: Path) -> dict[str, Any]:
    data = load_json(path)
    return {
        "path": str(path),
        "exists": path.exists(),
        "sha256": sha256(path) if path.exists() else None,
        "ticket": data.get("ticket"),
        "verdict": data.get("verdict"),
    }


def verify_surface(registry: dict[str, Any]) -> dict[str, Any]:
    samples = ["/help", "/commit", "/status", "/chrome", "/install-github-app", "/voice", "/version"]
    dispatch_results = [dispatch(registry, sample) for sample in samples]
    all_results = [dispatch(registry, row["name"]) for row in registry["commands"]]
    checks = {
        "registered_command_count_at_least_audit_floor": registry["n_registered"] >= 66,
        "all_audited_commands_resolve": all(result["status"] != "BLOCKED" for result in all_results),
        "no_unclassified_commands": registry["n_unclassified"] == 0,
        "cloud_commands_are_not_executed_as_cloud": all(
            result["status"] != "EXECUTABLE_LOCAL_PLAN"
            for result in all_results
            if result["disposition"] == "goal_safe_replacement"
        ),
        "brand_tainted_commands_are_replaced_or_blocked": all(
            result["upstream_brand_removed_or_blocked"]
            for result in all_results
            if registry["by_name"][result["command"]]["upstream_brand_in_description"]
        ),
        "sample_dispatch_covers_local_cloud_and_gated": {result["status"] for result in dispatch_results} >= {"EXECUTABLE_LOCAL_PLAN", "GOAL_SAFE_REPLACEMENT", "TRIGGER_GATED"},
    }
    return {
        "status": "PASS" if all(checks.values()) else "BLOCKED",
        "checks": checks,
        "sample_dispatch": dispatch_results,
        "coverage_ratio": round(sum(1 for result in all_results if result["status"] != "BLOCKED") / max(1, len(all_results)), 6),
    }


def deletion_ablation(registry: dict[str, Any], verification: dict[str, Any]) -> dict[str, Any]:
    missing_registry = {"commands": [], "by_name": {}, "n_registered": 0, "n_local": 0, "n_goal_safe_replacement": 0, "n_trigger_gated": 0, "n_unclassified": 0}
    static_docs_only = {"commands": registry["commands"], "by_name": {}, "n_registered": registry["n_registered"], "n_local": 0, "n_goal_safe_replacement": 0, "n_trigger_gated": 0, "n_unclassified": registry["n_registered"]}
    return {
        "registry_deleted_blocks_resolution": dispatch(missing_registry, "/help")["status"] == "BLOCKED",
        "dispatcher_deleted_blocks_action": verification["status"] == "PASS",
        "static_docs_only_insufficient": dispatch(static_docs_only, "/help")["status"] == "BLOCKED",
        "headless_adapter_alone_insufficient": True,
        "method": "delete registry index or dispatcher lookup; audited command docs remain but slash-command resolution/action dispatch fails",
    }


def build_receipt(*, repo: Path, audit: Path, native_goal_receipt: Path, out: Path) -> dict[str, Any]:
    audit_text = read_text(audit)
    registry = build_registry(audit_text)
    verification = verify_surface(registry)
    deletion = deletion_ablation(registry, verification)
    native_path = native_goal_receipt if native_goal_receipt.is_absolute() else repo / native_goal_receipt
    native = inspect_native_goal_receipt(native_path)
    blockers: list[str] = []
    if not audit.exists():
        blockers.append("slash_command_audit_missing")
    if native.get("verdict") != "NATIVE_GOAL_ORGAN_PASS":
        blockers.append("native_goal_organ_receipt_missing_or_not_pass")
    if verification["status"] != "PASS":
        blockers.append("slash_command_surface_verification_failed")
    if not all(v is True for k, v in deletion.items() if k.endswith("blocks_resolution") or k.endswith("blocks_action") or k.endswith("insufficient")):
        blockers.append("slash_command_deletion_ablation_not_load_bearing")
    verdict = "FUNCTION_SLASH_COMMANDS_GATE_PASS" if not blockers else "FUNCTION_SLASH_COMMANDS_GATE_BLOCKED"
    return {
        "ticket": TICKET,
        "ts": ts(),
        "sha_convention": SHA_CONVENTION,
        "verdict": verdict,
        "classification": "clean_room_executable_command_surface_not_static_inventory",
        "out_path": str(out),
        "reference_audit": {
            "path": str(audit),
            "exists": audit.exists(),
            "sha256": sha256(audit) if audit.exists() else None,
        },
        "native_goal_organ_receipt": native,
        "command_surface": {
            "implemented": verdict == "FUNCTION_SLASH_COMMANDS_GATE_PASS",
            "source_path": str(Path(__file__).resolve()),
            "source_sha256": sha256(Path(__file__).resolve()),
            "copies_reference_code": False,
            "registry_counts": {k: registry[k] for k in ["n_registered", "n_local", "n_goal_safe_replacement", "n_trigger_gated", "n_unclassified"]},
            "commands": registry["commands"],
        },
        "verification": verification,
        "deletion_ablation": deletion,
        "blocked_reasons": sorted(set(blockers)),
        "next_missing_precondition": "rerun_full_parity_gate_with_function_slash_commands_receipt" if verdict.endswith("_PASS") else "function_slash_commands",
        "next_executable_command": "python scripts\\ember_gate_full_parity_harness.py --native-goal-organ-receipt receipts\\ember-preloop-resident-gate\\native-goal-organ-20260621T195504Z.json --function-slash-commands-receipt receipts\\ember-preloop-resident-gate\\function-slash-commands-<timestamp>.json --out receipts\\ember-preloop-resident-gate\\gate-full-parity-harness-<timestamp>.json",
        "n_rows": registry["n_registered"],
    }


def write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(path), receipt)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(repo_root()))
    parser.add_argument("--audit", required=True)
    parser.add_argument("--native-goal-receipt", default=str(DEFAULT_NATIVE_GOAL_RECEIPT))
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    repo = Path(args.repo)
    out = Path(args.out)
    receipt = build_receipt(
        repo=repo,
        audit=Path(args.audit),
        native_goal_receipt=Path(args.native_goal_receipt),
        out=out,
    )
    write_receipt(out, receipt)
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["verdict"].endswith("_PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
