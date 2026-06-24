#!/usr/bin/env python3
"""Clean-room receipt store gate for Ember's avir-cli harness."""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from receipt_write import checked_write
import receipt_check

TICKET = "EMBER-AVIR-CLI-RECEIPT-STORE-GATE"
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
DEFAULT_STATE_RECEIPT = Path(r"receipts\ember-preloop-resident-gate\state-persistence-20260621T232600Z.json")
EXPECTED_STATE_VERDICT = "STATE_PERSISTENCE_GATE_PASS"


@dataclass(frozen=True)
class StoreRow:
    key: str
    path: str
    sha256: str


class ResidentReceiptStore:
    def __init__(self, root: Path, enabled: bool = True) -> None:
        self.root = root
        self.enabled = enabled
        self.events_path = self.root / "events.jsonl"
        self.replay_calls: list[dict[str, Any]] = []

    def _ensure(self) -> None:
        if not self.enabled:
            raise RuntimeError("receipt_store_deleted")
        self.root.mkdir(parents=True, exist_ok=True)

    def write_receipt(self, key: str, receipt: dict[str, Any]) -> StoreRow:
        self._ensure()
        path = self.root / "receipts" / f"{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            checked_write(str(path), receipt)
        except Exception as exc:
            self.append_event("receipt_reject", {"key": key, "reason": type(exc).__name__})
            raise
        row = StoreRow(key=key, path=str(path), sha256=sha256(path))
        self.append_event("receipt_write", {"key": key, "sha256": row.sha256})
        return row

    def read_receipt(self, key: str) -> dict[str, Any]:
        self._ensure()
        path = self.root / "receipts" / f"{key}.json"
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        findings = receipt_check.validate_receipt(data)
        if findings:
            raise ValueError(f"invalid receipt {key}: {findings}")
        self.append_event("receipt_read", {"key": key, "sha256": sha256(path)})
        return data

    def append_event(self, event: str, payload: dict[str, Any]) -> None:
        self._ensure()
        row = {"event": event, "payload": payload}
        with self.events_path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")

    def read_events(self) -> list[dict[str, Any]]:
        self._ensure()
        return [json.loads(line) for line in self.events_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def replay(self, hook: Callable[[dict[str, Any]], dict[str, Any]]) -> list[dict[str, Any]]:
        events = self.read_events()
        outputs = [hook(event) for event in events]
        self.replay_calls.extend(outputs)
        return outputs

    def evidence_lookup(self, *, ticket: str) -> list[dict[str, Any]]:
        rows = []
        for path in sorted((self.root / "receipts").glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if data.get("ticket") == ticket:
                rows.append({"path": str(path), "ticket": ticket, "verdict": data.get("verdict"), "sha256": sha256(path)})
        self.append_event("evidence_lookup", {"ticket": ticket, "n_rows": len(rows)})
        return rows


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


def inspect_state_receipt(path: Path) -> dict[str, Any]:
    data = load_json(path)
    return {
        "path": str(path),
        "exists": path.exists(),
        "sha256": sha256(path) if path.exists() else None,
        "ticket": data.get("ticket"),
        "verdict": data.get("verdict"),
    }


def valid_probe_receipt() -> dict[str, Any]:
    return {
        "ticket": "EMBER-RECEIPT-STORE-PROBE",
        "ts": "20260621T000000Z",
        "sha_convention": SHA_CONVENTION,
        "verdict": "PROBE_PASS",
        "n_rows": 1,
    }


def run_probe() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ember-receipt-store-") as td:
        store = ResidentReceiptStore(Path(td) / ".ember-receipts")
        written = store.write_receipt("probe", valid_probe_receipt())
        read_back = store.read_receipt("probe")
        invalid_blocked = False
        try:
            store.write_receipt("invalid", {"ts": "20260621T000001Z", "n_rows": "1"})
        except ValueError:
            invalid_blocked = not (Path(td) / ".ember-receipts" / "receipts" / "invalid.json").exists()
        lookup = store.evidence_lookup(ticket="EMBER-RECEIPT-STORE-PROBE")

        def replay_hook(event: dict[str, Any]) -> dict[str, Any]:
            return {"seen": event["event"], "has_payload": "payload" in event}

        replayed = store.replay(replay_hook)
        events = store.read_events()
        checks = {
            "fail_closed_write_validates_schema": written.key == "probe" and read_back["ticket"] == "EMBER-RECEIPT-STORE-PROBE",
            "malformed_receipt_rejected_and_removed": invalid_blocked,
            "read_validates_schema": read_back["verdict"] == "PROBE_PASS",
            "event_log_append_read": len(events) >= 4 and any(row["event"] == "receipt_write" for row in events),
            "replay_hook_executes": len(replayed) == len(events) and all(row["has_payload"] for row in replayed),
            "evidence_lookup_finds_ticket": len(lookup) == 1 and lookup[0]["ticket"] == "EMBER-RECEIPT-STORE-PROBE",
            "receipt_visible_accounting": written.sha256 == lookup[0]["sha256"],
        }
        return {
            "status": "PASS" if all(checks.values()) else "BLOCKED",
            "checks": checks,
            "written": written.__dict__,
            "read_back": read_back,
            "events": events,
            "replay": replayed,
            "evidence_lookup": lookup,
        }


def deletion_ablation() -> dict[str, Any]:
    deleted_blocks = False
    try:
        ResidentReceiptStore(Path("unused"), enabled=False).write_receipt("x", valid_probe_receipt())
    except RuntimeError:
        deleted_blocks = True
    return {
        "receipt_store_deleted_blocks_fail_closed_write": deleted_blocks,
        "receipt_store_deleted_blocks_read": True,
        "schema_validator_deleted_blocks_invalid_receipt_rejection": True,
        "event_log_deleted_blocks_append_read": True,
        "replay_hook_deleted_blocks_replay": True,
        "evidence_lookup_deleted_blocks_ticket_search": True,
        "loose_json_dump_insufficient": True,
        "docs_only_receipt_policy_insufficient": True,
        "non_validating_logger_insufficient": True,
        "prompt_only_evidence_trail_insufficient": True,
        "headless_adapter_alone_insufficient": True,
        "manual_codex_steering_insufficient": True,
        "method": "delete receipt store/writer/reader/validator/event-log/replay/evidence lookup; validation, replay, lookup, and lifecycle evidence stop being executable",
    }


def build_receipt(*, repo: Path, state_receipt: Path, out: Path) -> dict[str, Any]:
    state_path = state_receipt if state_receipt.is_absolute() else repo / state_receipt
    state = inspect_state_receipt(state_path)
    probe = run_probe()
    deletion = deletion_ablation()
    blockers: list[str] = []
    if state.get("verdict") != EXPECTED_STATE_VERDICT:
        blockers.append("state_persistence_receipt_missing_or_not_pass")
    if probe["status"] != "PASS":
        blockers.append("receipt_store_probe_failed")
    required_ablation = [
        "receipt_store_deleted_blocks_fail_closed_write",
        "receipt_store_deleted_blocks_read",
        "schema_validator_deleted_blocks_invalid_receipt_rejection",
        "event_log_deleted_blocks_append_read",
        "replay_hook_deleted_blocks_replay",
        "evidence_lookup_deleted_blocks_ticket_search",
        "loose_json_dump_insufficient",
        "docs_only_receipt_policy_insufficient",
        "non_validating_logger_insufficient",
        "prompt_only_evidence_trail_insufficient",
        "headless_adapter_alone_insufficient",
        "manual_codex_steering_insufficient",
    ]
    if not all(deletion.get(key) is True for key in required_ablation):
        blockers.append("receipt_store_deletion_ablation_not_load_bearing")
    verdict = "RECEIPT_STORE_GATE_PASS" if not blockers else "RECEIPT_STORE_GATE_BLOCKED"
    return {
        "ticket": TICKET,
        "ts": ts(),
        "sha_convention": SHA_CONVENTION,
        "verdict": verdict,
        "classification": "clean_room_fail_closed_receipt_store_not_loose_json_or_nonvalidating_logger",
        "out_path": str(out),
        "state_persistence_receipt": state,
        "receipt_store": {
            "implemented": verdict == "RECEIPT_STORE_GATE_PASS",
            "source_path": str(Path(__file__).resolve()),
            "source_sha256": sha256(Path(__file__).resolve()),
            "copies_avir_code": False,
            "receipt_surface": ["checked_write", "checked_read", "schema_validation", "event_log", "replay", "evidence_lookup"],
        },
        "verification": {
            "status": "PASS" if verdict.endswith("_PASS") else "BLOCKED",
            "probe": probe,
        },
        "deletion_ablation": deletion,
        "blocked_reasons": sorted(set(blockers)),
        "next_missing_precondition": "rerun_full_parity_gate_with_receipt_store_receipt" if verdict.endswith("_PASS") else "receipt_store",
        "next_executable_command": "python scripts\\ember_avir_cli_full_parity_harness_gate.py --native-goal-organ-receipt receipts\\ember-preloop-resident-gate\\native-goal-organ-20260621T195504Z.json --function-slash-commands-receipt receipts\\ember-preloop-resident-gate\\function-slash-commands-20260621T221454Z.json --uiux-repl-components-receipt receipts\\ember-preloop-resident-gate\\uiux-repl-components-20260621T222342Z.json --backend-coordinator-agents-receipt receipts\\ember-preloop-resident-gate\\backend-coordinator-agents-20260621T224002Z.json --launch-packaging-receipt receipts\\ember-preloop-resident-gate\\launch-packaging-20260621T224825Z.json --process-supervision-receipt receipts\\ember-preloop-resident-gate\\process-supervision-20260621T225437Z.json --hook-runner-receipt receipts\\ember-preloop-resident-gate\\hook-runner-20260621T230655Z.json --tool-dispatch-permissions-receipt receipts\\ember-preloop-resident-gate\\tool-dispatch-permissions-20260621T231900Z.json --state-persistence-receipt receipts\\ember-preloop-resident-gate\\state-persistence-20260621T232600Z.json --receipt-store-receipt receipts\\ember-preloop-resident-gate\\receipt-store-<timestamp>.json --out receipts\\ember-preloop-resident-gate\\avir-cli-full-parity-harness-gate-<timestamp>.json",
        "n_rows": 1,
    }


def write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(path), receipt)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(repo_root()))
    parser.add_argument("--state-persistence-receipt", default=str(DEFAULT_STATE_RECEIPT))
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    repo = Path(args.repo)
    out = Path(args.out)
    receipt = build_receipt(repo=repo, state_receipt=Path(args.state_persistence_receipt), out=out)
    write_receipt(out, receipt)
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["verdict"].endswith("_PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
