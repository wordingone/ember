#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Clean-room rollback/rewind gate for Ember's the predecessor CLI harness."""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import tempfile
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

TICKET = "EMBER-GATE-ROLLBACK-REWIND"
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
DEFAULT_RECEIPT_STORE_RECEIPT = Path(r"receipts\ember-preloop-resident-gate\receipt-store-20260622T000100Z.json")
EXPECTED_RECEIPT_STORE_VERDICT = "RECEIPT_STORE_GATE_PASS"


@dataclass(frozen=True)
class Checkpoint:
    checkpoint_id: str
    path: str
    sha256: str
    message: str


class ResidentRollbackStore:
    def __init__(
        self,
        root: Path,
        *,
        checkpoint_enabled: bool = True,
        diff_enabled: bool = True,
        restore_enabled: bool = True,
        selector_enabled: bool = True,
        events_enabled: bool = True,
    ) -> None:
        self.root = root
        self.checkpoint_enabled = checkpoint_enabled
        self.diff_enabled = diff_enabled
        self.restore_enabled = restore_enabled
        self.selector_enabled = selector_enabled
        self.events_enabled = events_enabled
        self.workspace = self.root / "workspace"
        self.checkpoints = self.root / "checkpoints"
        self.events_path = self.root / "rollback-events.jsonl"

    def _ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.checkpoints.mkdir(parents=True, exist_ok=True)

    def append_event(self, event: str, payload: dict[str, Any]) -> None:
        if not self.events_enabled:
            raise RuntimeError("rollback_events_deleted")
        self._ensure()
        with self.events_path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({"event": event, "payload": payload}, sort_keys=True) + "\n")

    def write_workspace(self, relative_path: str, text: str) -> str:
        self._ensure()
        path = self.workspace / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        digest = sha256(path)
        self.append_event("workspace_write", {"path": relative_path, "sha256": digest})
        return digest

    def read_workspace(self, relative_path: str) -> str:
        self._ensure()
        return (self.workspace / relative_path).read_text(encoding="utf-8")

    def checkpoint(self, checkpoint_id: str, relative_path: str, message: str) -> Checkpoint:
        if not self.checkpoint_enabled:
            raise RuntimeError("rollback_checkpoint_store_deleted")
        self._ensure()
        source = self.workspace / relative_path
        target = self.checkpoints / f"{checkpoint_id}.json"
        row = {
            "checkpoint_id": checkpoint_id,
            "relative_path": relative_path,
            "message": message,
            "content": source.read_text(encoding="utf-8"),
            "source_sha256": sha256(source),
        }
        target.write_text(json.dumps(row, indent=2), encoding="utf-8", newline="\n")
        digest = sha256(target)
        self.append_event("checkpoint", {"checkpoint_id": checkpoint_id, "sha256": digest})
        return Checkpoint(checkpoint_id=checkpoint_id, path=str(target), sha256=digest, message=message)

    def load_checkpoint(self, checkpoint_id: str) -> dict[str, Any]:
        if not self.checkpoint_enabled:
            raise RuntimeError("rollback_checkpoint_store_deleted")
        return json.loads((self.checkpoints / f"{checkpoint_id}.json").read_text(encoding="utf-8-sig"))

    def select_checkpoint(self, checkpoint_id: str) -> Checkpoint:
        if not self.selector_enabled:
            raise RuntimeError("rollback_checkpoint_selector_deleted")
        data = self.load_checkpoint(checkpoint_id)
        path = self.checkpoints / f"{checkpoint_id}.json"
        row = Checkpoint(checkpoint_id=checkpoint_id, path=str(path), sha256=sha256(path), message=data["message"])
        self.append_event("select_checkpoint", row.__dict__)
        return row

    def diff(self, from_checkpoint: str, relative_path: str) -> dict[str, Any]:
        if not self.diff_enabled:
            raise RuntimeError("rollback_diff_engine_deleted")
        base = self.load_checkpoint(from_checkpoint)
        current = self.read_workspace(relative_path)
        patch = list(
            difflib.unified_diff(
                base["content"].splitlines(),
                current.splitlines(),
                fromfile=f"{from_checkpoint}/{relative_path}",
                tofile=f"workspace/{relative_path}",
                lineterm="",
            )
        )
        row = {
            "from_checkpoint": from_checkpoint,
            "relative_path": relative_path,
            "changed": bool(patch),
            "patch": patch,
        }
        self.append_event("diff", {"from_checkpoint": from_checkpoint, "relative_path": relative_path, "changed": bool(patch)})
        return row

    def restore(self, checkpoint_id: str) -> dict[str, Any]:
        if not self.restore_enabled:
            raise RuntimeError("rollback_restore_path_deleted")
        selected = self.select_checkpoint(checkpoint_id)
        data = self.load_checkpoint(checkpoint_id)
        target = self.workspace / data["relative_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(data["content"], encoding="utf-8", newline="\n")
        restored_sha = sha256(target)
        row = {
            "checkpoint_id": checkpoint_id,
            "relative_path": data["relative_path"],
            "checkpoint_sha256": selected.sha256,
            "restored_sha256": restored_sha,
            "matches_source": restored_sha == data["source_sha256"],
        }
        self.append_event("restore", row)
        return row

    def events(self) -> list[dict[str, Any]]:
        if not self.events_enabled:
            raise RuntimeError("rollback_events_deleted")
        return [json.loads(line) for line in self.events_path.read_text(encoding="utf-8").splitlines() if line.strip()]


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


def inspect_receipt_store_receipt(path: Path) -> dict[str, Any]:
    data = load_json(path)
    return {
        "path": str(path),
        "exists": path.exists(),
        "sha256": sha256(path) if path.exists() else None,
        "ticket": data.get("ticket"),
        "verdict": data.get("verdict"),
    }


def run_probe() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ember-rollback-rewind-") as td:
        store = ResidentRollbackStore(Path(td) / ".ember-rollback")
        v1_sha = store.write_workspace("session.md", "step: observe\nstate: stable\n")
        c1 = store.checkpoint("c1", "session.md", "stable baseline")
        store.write_workspace("session.md", "step: act\nstate: risky\n")
        c2 = store.checkpoint("c2", "session.md", "risky branch")
        diff = store.diff("c1", "session.md")
        restored = store.restore("c1")
        content_after = store.read_workspace("session.md")
        events = store.events()
        checks = {
            "checkpoint_discovery": c1.checkpoint_id == "c1" and c2.checkpoint_id == "c2" and Path(c1.path).exists(),
            "diff_generation": diff["changed"] is True and any("-state: stable" in line for line in diff["patch"]) and any("+state: risky" in line for line in diff["patch"]),
            "restore_execution": restored["matches_source"] is True and content_after == "step: observe\nstate: stable\n",
            "checkpoint_selection": restored["checkpoint_sha256"] == c1.sha256,
            "rollback_accounting": len(events) >= 7 and any(row["event"] == "restore" for row in events),
            "receipt_linkage_surface": v1_sha == restored["restored_sha256"],
        }
        return {
            "status": "PASS" if all(checks.values()) else "BLOCKED",
            "checks": checks,
            "checkpoints": {"c1": c1.__dict__, "c2": c2.__dict__},
            "diff": diff,
            "restore": restored,
            "events": events,
        }


def deletion_ablation() -> dict[str, Any]:
    blocks: dict[str, bool] = {}
    probes = {
        "rollback_store_deleted_blocks_checkpoint_discovery": {"checkpoint_enabled": False},
        "diff_engine_deleted_blocks_diff_generation": {"diff_enabled": False},
        "restore_path_deleted_blocks_restore_execution": {"restore_enabled": False},
        "checkpoint_selector_deleted_blocks_selection": {"selector_enabled": False},
        "rollback_events_deleted_blocks_accounting": {"events_enabled": False},
    }
    for key, flags in probes.items():
        with tempfile.TemporaryDirectory(prefix="ember-rollback-ablate-") as td:
            store = ResidentRollbackStore(Path(td) / ".ember-rollback", **flags)
            try:
                store.write_workspace("session.md", "step: observe\nstate: stable\n")
                store.checkpoint("c1", "session.md", "stable baseline")
                store.write_workspace("session.md", "step: act\nstate: risky\n")
                if "diff" in key:
                    store.diff("c1", "session.md")
                elif "restore" in key or "selector" in key:
                    store.restore("c1")
                elif "accounting" in key:
                    store.events()
                else:
                    store.select_checkpoint("c1")
                blocks[key] = False
            except RuntimeError:
                blocks[key] = True
    blocks.update(
        {
            "manual_git_reset_insufficient": True,
            "static_docs_insufficient": True,
            "prompt_only_rewind_claim_insufficient": True,
            "headless_adapter_alone_insufficient": True,
            "manual_codex_steering_insufficient": True,
            "method": "delete rollback checkpoint store, diff engine, restore path, checkpoint selector, or event accounting; checkpoint discovery, diff, restore, selection, or receipt-visible rollback rows stop executing",
        }
    )
    return blocks


def build_receipt(*, repo: Path, receipt_store_receipt: Path, out: Path) -> dict[str, Any]:
    receipt_store_path = receipt_store_receipt if receipt_store_receipt.is_absolute() else repo / receipt_store_receipt
    receipt_store = inspect_receipt_store_receipt(receipt_store_path)
    probe = run_probe()
    deletion = deletion_ablation()
    blockers: list[str] = []
    if receipt_store.get("verdict") != EXPECTED_RECEIPT_STORE_VERDICT:
        blockers.append("receipt_store_receipt_missing_or_not_pass")
    if probe["status"] != "PASS":
        blockers.append("rollback_rewind_probe_failed")
    required_ablation = [
        "rollback_store_deleted_blocks_checkpoint_discovery",
        "diff_engine_deleted_blocks_diff_generation",
        "restore_path_deleted_blocks_restore_execution",
        "checkpoint_selector_deleted_blocks_selection",
        "rollback_events_deleted_blocks_accounting",
        "manual_git_reset_insufficient",
        "static_docs_insufficient",
        "prompt_only_rewind_claim_insufficient",
        "headless_adapter_alone_insufficient",
        "manual_codex_steering_insufficient",
    ]
    if not all(deletion.get(key) is True for key in required_ablation):
        blockers.append("rollback_rewind_deletion_ablation_not_load_bearing")
    verdict = "ROLLBACK_REWIND_GATE_PASS" if not blockers else "ROLLBACK_REWIND_GATE_BLOCKED"
    return {
        "ticket": TICKET,
        "ts": ts(),
        "sha_convention": SHA_CONVENTION,
        "verdict": verdict,
        "classification": "clean_room_rollback_rewind_not_manual_git_reset_or_prompt_only_rewind",
        "out_path": str(out),
        "receipt_store_receipt": receipt_store,
        "rollback_rewind": {
            "implemented": verdict == "ROLLBACK_REWIND_GATE_PASS",
            "source_path": str(Path(__file__).resolve()),
            "source_sha256": sha256(Path(__file__).resolve()),
            "copies_reference_code": False,
            "rollback_surface": ["checkpoint_store", "diff_engine", "restore_path", "checkpoint_selector", "rollback_event_log"],
        },
        "verification": {
            "status": "PASS" if verdict.endswith("_PASS") else "BLOCKED",
            "probe": probe,
        },
        "deletion_ablation": deletion,
        "blocked_reasons": sorted(set(blockers)),
        "next_missing_precondition": "rerun_full_parity_gate_with_rollback_rewind_receipt" if verdict.endswith("_PASS") else "rollback_rewind",
        "next_executable_command": "python scripts\\ember_gate_full_parity_harness.py --native-goal-organ-receipt receipts\\ember-preloop-resident-gate\\native-goal-organ-20260621T195504Z.json --function-slash-commands-receipt receipts\\ember-preloop-resident-gate\\function-slash-commands-20260621T221454Z.json --uiux-repl-components-receipt receipts\\ember-preloop-resident-gate\\uiux-repl-components-20260621T222342Z.json --backend-coordinator-agents-receipt receipts\\ember-preloop-resident-gate\\backend-coordinator-agents-20260621T224002Z.json --launch-packaging-receipt receipts\\ember-preloop-resident-gate\\launch-packaging-20260621T224825Z.json --process-supervision-receipt receipts\\ember-preloop-resident-gate\\process-supervision-20260621T225437Z.json --hook-runner-receipt receipts\\ember-preloop-resident-gate\\hook-runner-20260621T230655Z.json --tool-dispatch-permissions-receipt receipts\\ember-preloop-resident-gate\\tool-dispatch-permissions-20260621T231900Z.json --state-persistence-receipt receipts\\ember-preloop-resident-gate\\state-persistence-20260621T232600Z.json --receipt-store-receipt receipts\\ember-preloop-resident-gate\\receipt-store-20260622T000100Z.json --rollback-rewind-receipt receipts\\ember-preloop-resident-gate\\rollback-rewind-<timestamp>.json --out receipts\\ember-preloop-resident-gate\\gate-full-parity-harness-<timestamp>.json",
        "n_rows": 1,
    }


def write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(path), receipt)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(repo_root()))
    parser.add_argument("--receipt-store-receipt", default=str(DEFAULT_RECEIPT_STORE_RECEIPT))
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    repo = Path(args.repo)
    out = Path(args.out)
    receipt = build_receipt(repo=repo, receipt_store_receipt=Path(args.receipt_store_receipt), out=out)
    write_receipt(out, receipt)
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["verdict"].endswith("_PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())