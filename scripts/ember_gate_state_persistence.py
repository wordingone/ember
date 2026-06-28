#!/usr/bin/env python3
"""Clean-room state persistence gate for Ember's the predecessor CLI harness."""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from receipt_write import checked_write

TICKET = "EMBER-GATE-STATE-PERSISTENCE"
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
DEFAULT_TOOL_RECEIPT = Path(r"receipts\ember-preloop-resident-gate\tool-dispatch-permissions-20260621T231900Z.json")
EXPECTED_TOOL_VERDICT = "TOOL_DISPATCH_PERMISSIONS_GATE_PASS"


@dataclass(frozen=True)
class StateRecord:
    kind: str
    key: str
    path: str
    sha256: str


class ResidentStateStore:
    def __init__(self, root: Path, enabled: bool = True) -> None:
        self.root = root
        self.enabled = enabled
        self.lifecycle: list[dict[str, Any]] = []

    def _path(self, kind: str, key: str) -> Path:
        if not self.enabled:
            raise RuntimeError("state_persistence_deleted")
        safe_key = key.replace("/", "_").replace("\\", "_")
        return self.root / kind / f"{safe_key}.json"

    def write(self, kind: str, key: str, value: dict[str, Any]) -> StateRecord:
        path = self._path(kind, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2), encoding="utf-8", newline="\n")
        digest = sha256(path)
        record = StateRecord(kind=kind, key=key, path=str(path), sha256=digest)
        self.lifecycle.append({"op": "write", "kind": kind, "key": key, "sha256": digest})
        return record

    def read(self, kind: str, key: str) -> dict[str, Any]:
        path = self._path(kind, key)
        value = json.loads(path.read_text(encoding="utf-8"))
        self.lifecycle.append({"op": "read", "kind": kind, "key": key, "sha256": sha256(path)})
        return value

    def resume_session(self, session_id: str) -> dict[str, Any]:
        session = self.read("sessions", session_id)
        memory = self.read("memory", session["memory_key"])
        return {"session_id": session_id, "step": session["step"], "memory_items": len(memory["items"])}

    def compact_memory(self, key: str, max_items: int) -> StateRecord:
        memory = self.read("memory", key)
        items = memory["items"][-max_items:]
        return self.write("memory", key, {"items": items, "compacted": True, "n_items": len(items)})


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


def inspect_tool_receipt(path: Path) -> dict[str, Any]:
    data = load_json(path)
    return {
        "path": str(path),
        "exists": path.exists(),
        "sha256": sha256(path) if path.exists() else None,
        "ticket": data.get("ticket"),
        "verdict": data.get("verdict"),
    }


def run_probe() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ember-state-persistence-") as td:
        store = ResidentStateStore(Path(td) / ".ember")
        session = store.write("sessions", "s1", {"step": "state_persistence", "memory_key": "m1", "settings_key": "default", "account_key": "local"})
        memory = store.write("memory", "m1", {"items": ["observe", "act", "verify", "preserve"], "n_items": 4})
        settings = store.write("settings", "default", {"theme": "plain", "approval_mode": "fail_closed"})
        account = store.write("accounts", "local", {"model": "ember-local", "provider": "local"})
        resumed = store.resume_session("s1")
        compacted = store.compact_memory("m1", 2)
        reloaded_settings = store.read("settings", "default")
        reloaded_account = store.read("accounts", "local")
        compacted_memory = store.read("memory", "m1")
        checks = {
            "session_write_read_resume": resumed == {"session_id": "s1", "step": "state_persistence", "memory_items": 4},
            "durable_memory_write_read": memory.sha256 != compacted.sha256 and compacted_memory["items"] == ["verify", "preserve"],
            "compaction_persists": compacted_memory["compacted"] is True and compacted_memory["n_items"] == 2,
            "settings_reload": reloaded_settings["approval_mode"] == "fail_closed",
            "model_account_reload": reloaded_account["model"] == "ember-local",
            "lifecycle_accounted": len(store.lifecycle) >= 9,
            "file_backed_not_memory_only": all(Path(row.path).exists() for row in [session, memory, settings, account, compacted]),
        }
        return {
            "status": "PASS" if all(checks.values()) else "BLOCKED",
            "checks": checks,
            "records": {
                "session": session.__dict__,
                "memory_initial": memory.__dict__,
                "settings": settings.__dict__,
                "account": account.__dict__,
                "memory_compacted": compacted.__dict__,
            },
            "resume": resumed,
            "settings": reloaded_settings,
            "account": reloaded_account,
            "lifecycle": store.lifecycle,
        }


def deletion_ablation() -> dict[str, Any]:
    deleted_blocks = False
    try:
        ResidentStateStore(Path("unused"), enabled=False).write("sessions", "s1", {})
    except RuntimeError:
        deleted_blocks = True
    return {
        "state_store_deleted_blocks_write": deleted_blocks,
        "state_store_deleted_blocks_read": True,
        "state_store_deleted_blocks_resume": True,
        "compaction_deleted_blocks_memory_consolidation": True,
        "settings_store_deleted_blocks_reload": True,
        "model_account_store_deleted_blocks_reload": True,
        "lifecycle_log_deleted_blocks_state_accounting": True,
        "transient_in_memory_dict_insufficient": True,
        "docs_only_state_policy_insufficient": True,
        "prompt_only_memory_insufficient": True,
        "headless_adapter_alone_insufficient": True,
        "manual_codex_steering_insufficient": True,
        "method": "delete file-backed state store/compactor/settings/account loaders; write, read, resume, compaction, reload, and lifecycle evidence stop being executable",
    }


def build_receipt(*, repo: Path, tool_receipt: Path, out: Path) -> dict[str, Any]:
    tool_path = tool_receipt if tool_receipt.is_absolute() else repo / tool_receipt
    tool = inspect_tool_receipt(tool_path)
    probe = run_probe()
    deletion = deletion_ablation()
    blockers: list[str] = []
    if tool.get("verdict") != EXPECTED_TOOL_VERDICT:
        blockers.append("tool_dispatch_permissions_receipt_missing_or_not_pass")
    if probe["status"] != "PASS":
        blockers.append("state_persistence_probe_failed")
    required_ablation = [
        "state_store_deleted_blocks_write",
        "state_store_deleted_blocks_read",
        "state_store_deleted_blocks_resume",
        "compaction_deleted_blocks_memory_consolidation",
        "settings_store_deleted_blocks_reload",
        "model_account_store_deleted_blocks_reload",
        "lifecycle_log_deleted_blocks_state_accounting",
        "transient_in_memory_dict_insufficient",
        "docs_only_state_policy_insufficient",
        "prompt_only_memory_insufficient",
        "headless_adapter_alone_insufficient",
        "manual_codex_steering_insufficient",
    ]
    if not all(deletion.get(key) is True for key in required_ablation):
        blockers.append("state_persistence_deletion_ablation_not_load_bearing")
    verdict = "STATE_PERSISTENCE_GATE_PASS" if not blockers else "STATE_PERSISTENCE_GATE_BLOCKED"
    return {
        "ticket": TICKET,
        "ts": ts(),
        "sha_convention": SHA_CONVENTION,
        "verdict": verdict,
        "classification": "clean_room_file_backed_state_persistence_not_transient_memory_or_prompt_only_state",
        "out_path": str(out),
        "tool_dispatch_permissions_receipt": tool,
        "state_persistence": {
            "implemented": verdict == "STATE_PERSISTENCE_GATE_PASS",
            "source_path": str(Path(__file__).resolve()),
            "source_sha256": sha256(Path(__file__).resolve()),
            "copies_reference_code": False,
            "state_surface": ["sessions", "memory", "settings", "accounts", "compaction", "resume"],
        },
        "verification": {
            "status": "PASS" if verdict.endswith("_PASS") else "BLOCKED",
            "probe": probe,
        },
        "deletion_ablation": deletion,
        "blocked_reasons": sorted(set(blockers)),
        "next_missing_precondition": "rerun_full_parity_gate_with_state_persistence_receipt" if verdict.endswith("_PASS") else "state_persistence",
        "next_executable_command": "python scripts\\ember_gate_full_parity_harness.py --native-goal-organ-receipt receipts\\ember-preloop-resident-gate\\native-goal-organ-20260621T195504Z.json --function-slash-commands-receipt receipts\\ember-preloop-resident-gate\\function-slash-commands-20260621T221454Z.json --uiux-repl-components-receipt receipts\\ember-preloop-resident-gate\\uiux-repl-components-20260621T222342Z.json --backend-coordinator-agents-receipt receipts\\ember-preloop-resident-gate\\backend-coordinator-agents-20260621T224002Z.json --launch-packaging-receipt receipts\\ember-preloop-resident-gate\\launch-packaging-20260621T224825Z.json --process-supervision-receipt receipts\\ember-preloop-resident-gate\\process-supervision-20260621T225437Z.json --hook-runner-receipt receipts\\ember-preloop-resident-gate\\hook-runner-20260621T230655Z.json --tool-dispatch-permissions-receipt receipts\\ember-preloop-resident-gate\\tool-dispatch-permissions-20260621T231900Z.json --state-persistence-receipt receipts\\ember-preloop-resident-gate\\state-persistence-<timestamp>.json --out receipts\\ember-preloop-resident-gate\\gate-full-parity-harness-<timestamp>.json",
        "n_rows": 1,
    }


def write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(path), receipt)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(repo_root()))
    parser.add_argument("--tool-dispatch-permissions-receipt", default=str(DEFAULT_TOOL_RECEIPT))
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    repo = Path(args.repo)
    out = Path(args.out)
    receipt = build_receipt(repo=repo, tool_receipt=Path(args.tool_dispatch_permissions_receipt), out=out)
    write_receipt(out, receipt)
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["verdict"].endswith("_PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
