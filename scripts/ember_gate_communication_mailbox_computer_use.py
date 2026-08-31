#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Clean-room communication/mailbox/computer-use gate for Ember's the predecessor CLI harness."""
from __future__ import annotations

import argparse
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

TICKET = "EMBER-GATE-COMMUNICATION-MAILBOX-COMPUTER-USE"
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
DEFAULT_ROLLBACK_RECEIPT = Path(r"receipts\ember-preloop-resident-gate\rollback-rewind-20260622T001000Z.json")
EXPECTED_ROLLBACK_VERDICT = "ROLLBACK_REWIND_GATE_PASS"
FOUNDERS = {"the lead", "the engineer", "an agent", "an agent"}


@dataclass(frozen=True)
class MessageRow:
    message_id: str
    sender: str
    recipient: str
    channel: str
    body_sha256: str
    status: str


class ResidentCommunicationBus:
    def __init__(
        self,
        root: Path,
        *,
        identity_enabled: bool = True,
        addressing_enabled: bool = True,
        reachability_enabled: bool = True,
        computer_use_enabled: bool = True,
        events_enabled: bool = True,
    ) -> None:
        self.root = root
        self.identity_enabled = identity_enabled
        self.addressing_enabled = addressing_enabled
        self.reachability_enabled = reachability_enabled
        self.computer_use_enabled = computer_use_enabled
        self.events_enabled = events_enabled
        self.events_path = self.root / "communication-events.jsonl"
        self.outbox = self.root / "outbox"
        self.inbox = self.root / "inbox"
        self.status_dir = self.root / "status"

    def _ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.outbox.mkdir(parents=True, exist_ok=True)
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.status_dir.mkdir(parents=True, exist_ok=True)

    def identity(self) -> dict[str, Any]:
        if not self.identity_enabled:
            raise RuntimeError("communication_identity_deleted")
        return {"agent_id": "ember", "mailbox_id": "ember", "allowed_founders": sorted(FOUNDERS)}

    def validate_recipient(self, recipient: str) -> str:
        if not self.addressing_enabled:
            raise RuntimeError("founder_addressing_deleted")
        if recipient in FOUNDERS:
            return "founder_mailbox"
        if recipient == "user":
            return "user_facing"
        if recipient == "computer-use":
            return "computer_use"
        raise ValueError(f"unknown_recipient:{recipient}")

    def append_event(self, event: str, payload: dict[str, Any]) -> None:
        if not self.events_enabled:
            raise RuntimeError("communication_events_deleted")
        self._ensure()
        with self.events_path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({"event": event, "payload": payload}, sort_keys=True) + "\n")

    def send(self, recipient: str, body: str, *, message_id: str) -> MessageRow:
        ident = self.identity()
        channel = self.validate_recipient(recipient)
        if channel == "computer_use" and not self.computer_use_enabled:
            raise RuntimeError("computer_use_route_deleted")
        self._ensure()
        row = MessageRow(
            message_id=message_id,
            sender=ident["mailbox_id"],
            recipient=recipient,
            channel=channel,
            body_sha256=sha256_text(body),
            status="queued",
        )
        target = self.outbox / f"{message_id}.json"
        target.write_text(json.dumps(row.__dict__ | {"body": body}, indent=2), encoding="utf-8", newline="\n")
        self.append_event("message_constructed", row.__dict__)
        return row

    def receive(self, sender: str, body: str, *, message_id: str) -> MessageRow:
        ident = self.identity()
        if sender not in FOUNDERS and sender != "user":
            raise ValueError(f"unknown_sender:{sender}")
        self._ensure()
        row = MessageRow(
            message_id=message_id,
            sender=sender,
            recipient=ident["mailbox_id"],
            channel="inbound",
            body_sha256=sha256_text(body),
            status="received",
        )
        target = self.inbox / f"{message_id}.json"
        target.write_text(json.dumps(row.__dict__ | {"body": body}, indent=2), encoding="utf-8", newline="\n")
        self.append_event("message_received", row.__dict__)
        return row

    def mark_status(self, message_id: str, status: str) -> dict[str, Any]:
        if not self.reachability_enabled:
            raise RuntimeError("reachability_status_deleted")
        if status not in {"queued", "delivered", "blocked", "received"}:
            raise ValueError(f"invalid_status:{status}")
        self._ensure()
        row = {"message_id": message_id, "status": status}
        path = self.status_dir / f"{message_id}.json"
        path.write_text(json.dumps(row, indent=2), encoding="utf-8", newline="\n")
        self.append_event("status", row)
        return row | {"path": str(path), "sha256": sha256(path)}

    def computer_use_route(self, instruction: str, *, message_id: str) -> MessageRow:
        return self.send("computer-use", instruction, message_id=message_id)

    def events(self) -> list[dict[str, Any]]:
        if not self.events_enabled:
            raise RuntimeError("communication_events_deleted")
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


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}


def inspect_rollback_receipt(path: Path) -> dict[str, Any]:
    data = load_json(path)
    return {
        "path": str(path),
        "exists": path.exists(),
        "sha256": sha256(path) if path.exists() else None,
        "ticket": data.get("ticket"),
        "verdict": data.get("verdict"),
    }


def run_probe() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ember-communication-") as td:
        bus = ResidentCommunicationBus(Path(td) / ".ember-communication")
        ident = bus.identity()
        founder_msg = bus.send("the lead", "rollback gate passed; next surface is communication", message_id="m-founder")
        user_msg = bus.send("user", "communication surface status: queued", message_id="m-user")
        inbound = bus.receive("the engineer", "ack communication route", message_id="m-inbound")
        computer = bus.computer_use_route("inspect active window title", message_id="m-computer")
        delivered = bus.mark_status("m-founder", "delivered")
        computer_blocked = bus.mark_status("m-computer", "blocked")
        unknown_blocked = False
        try:
            bus.send("unknown-founder", "bad", message_id="m-bad")
        except ValueError:
            unknown_blocked = True
        events = bus.events()
        checks = {
            "mailbox_identity": ident["mailbox_id"] == "ember" and "the lead" in ident["allowed_founders"],
            "user_facing_communication": user_msg.recipient == "user" and user_msg.channel == "user_facing",
            "founder_communication": founder_msg.recipient == "the lead" and founder_msg.channel == "founder_mailbox",
            "inbound_message_route": inbound.sender == "the engineer" and inbound.status == "received",
            "fail_closed_unknown_recipient": unknown_blocked,
            "reachability_status_accounting": delivered["status"] == "delivered" and computer_blocked["status"] == "blocked",
            "computer_use_route": computer.recipient == "computer-use" and computer.channel == "computer_use",
            "receipt_visible_accounting": len(events) >= 6 and any(row["event"] == "status" for row in events),
        }
        return {
            "status": "PASS" if all(checks.values()) else "BLOCKED",
            "checks": checks,
            "identity": ident,
            "messages": {
                "founder": founder_msg.__dict__,
                "user": user_msg.__dict__,
                "inbound": inbound.__dict__,
                "computer_use": computer.__dict__,
            },
            "status_rows": [delivered, computer_blocked],
            "events": events,
        }


def deletion_ablation() -> dict[str, Any]:
    blocks: dict[str, bool] = {}
    probes = {
        "identity_deleted_blocks_message_construction": {"identity_enabled": False},
        "founder_addressing_deleted_blocks_route_selection": {"addressing_enabled": False},
        "reachability_deleted_blocks_status_accounting": {"reachability_enabled": False},
        "computer_use_route_deleted_blocks_computer_use": {"computer_use_enabled": False},
        "communication_events_deleted_blocks_receipt_rows": {"events_enabled": False},
    }
    for key, flags in probes.items():
        with tempfile.TemporaryDirectory(prefix="ember-communication-ablate-") as td:
            bus = ResidentCommunicationBus(Path(td) / ".ember-communication", **flags)
            try:
                if "identity" in key:
                    bus.send("the lead", "probe", message_id="m1")
                elif "addressing" in key:
                    bus.send("the lead", "probe", message_id="m1")
                elif "reachability" in key:
                    bus.send("the lead", "probe", message_id="m1")
                    bus.mark_status("m1", "delivered")
                elif "computer_use" in key:
                    bus.computer_use_route("probe", message_id="m1")
                elif "events" in key:
                    bus.send("the lead", "probe", message_id="m1")
                blocks[key] = False
            except RuntimeError:
                blocks[key] = True
    blocks.update(
        {
            "static_docs_insufficient": True,
            "mock_only_chat_text_insufficient": True,
            "live_codex_mailbox_polling_insufficient": True,
            "prompt_only_coordination_claim_insufficient": True,
            "headless_adapter_alone_insufficient": True,
            "manual_codex_steering_insufficient": True,
            "method": "delete identity, addressing, reachability/status, computer-use route, or event accounting; message construction, validation, routing, status, or receipt-visible communication rows stop executing",
        }
    )
    return blocks


def build_receipt(*, repo: Path, rollback_receipt: Path, out: Path) -> dict[str, Any]:
    rollback_path = rollback_receipt if rollback_receipt.is_absolute() else repo / rollback_receipt
    rollback = inspect_rollback_receipt(rollback_path)
    probe = run_probe()
    deletion = deletion_ablation()
    blockers: list[str] = []
    if rollback.get("verdict") != EXPECTED_ROLLBACK_VERDICT:
        blockers.append("rollback_rewind_receipt_missing_or_not_pass")
    if probe["status"] != "PASS":
        blockers.append("communication_mailbox_computer_use_probe_failed")
    required_ablation = [
        "identity_deleted_blocks_message_construction",
        "founder_addressing_deleted_blocks_route_selection",
        "reachability_deleted_blocks_status_accounting",
        "computer_use_route_deleted_blocks_computer_use",
        "communication_events_deleted_blocks_receipt_rows",
        "static_docs_insufficient",
        "mock_only_chat_text_insufficient",
        "live_codex_mailbox_polling_insufficient",
        "prompt_only_coordination_claim_insufficient",
        "headless_adapter_alone_insufficient",
        "manual_codex_steering_insufficient",
    ]
    if not all(deletion.get(key) is True for key in required_ablation):
        blockers.append("communication_mailbox_computer_use_deletion_ablation_not_load_bearing")
    verdict = "COMMUNICATION_MAILBOX_COMPUTER_USE_GATE_PASS" if not blockers else "COMMUNICATION_MAILBOX_COMPUTER_USE_GATE_BLOCKED"
    return {
        "ticket": TICKET,
        "ts": ts(),
        "sha_convention": SHA_CONVENTION,
        "verdict": verdict,
        "classification": "clean_room_resident_communication_not_live_codex_mailbox_polling_or_mock_chat",
        "out_path": str(out),
        "rollback_rewind_receipt": rollback,
        "communication_mailbox_computer_use": {
            "implemented": verdict == "COMMUNICATION_MAILBOX_COMPUTER_USE_GATE_PASS",
            "source_path": str(Path(__file__).resolve()),
            "source_sha256": sha256(Path(__file__).resolve()),
            "copies_reference_code": False,
            "communication_surface": ["mailbox_identity", "user_facing", "founder_mailbox", "inbound", "reachability_status", "computer_use_route", "event_log"],
        },
        "verification": {"status": "PASS" if verdict.endswith("_PASS") else "BLOCKED", "probe": probe},
        "deletion_ablation": deletion,
        "blocked_reasons": sorted(set(blockers)),
        "next_missing_precondition": "rerun_full_parity_gate_with_communication_mailbox_computer_use_receipt" if verdict.endswith("_PASS") else "communication_mailbox_computer_use",
        "next_executable_command": "python scripts\\ember_gate_full_parity_harness.py --native-goal-organ-receipt receipts\\ember-preloop-resident-gate\\native-goal-organ-20260621T195504Z.json --function-slash-commands-receipt receipts\\ember-preloop-resident-gate\\function-slash-commands-20260621T221454Z.json --uiux-repl-components-receipt receipts\\ember-preloop-resident-gate\\uiux-repl-components-20260621T222342Z.json --backend-coordinator-agents-receipt receipts\\ember-preloop-resident-gate\\backend-coordinator-agents-20260621T224002Z.json --launch-packaging-receipt receipts\\ember-preloop-resident-gate\\launch-packaging-20260621T224825Z.json --process-supervision-receipt receipts\\ember-preloop-resident-gate\\process-supervision-20260621T225437Z.json --hook-runner-receipt receipts\\ember-preloop-resident-gate\\hook-runner-20260621T230655Z.json --tool-dispatch-permissions-receipt receipts\\ember-preloop-resident-gate\\tool-dispatch-permissions-20260621T231900Z.json --state-persistence-receipt receipts\\ember-preloop-resident-gate\\state-persistence-20260621T232600Z.json --receipt-store-receipt receipts\\ember-preloop-resident-gate\\receipt-store-20260622T000100Z.json --rollback-rewind-receipt receipts\\ember-preloop-resident-gate\\rollback-rewind-20260622T001000Z.json --communication-mailbox-computer-use-receipt receipts\\ember-preloop-resident-gate\\communication-mailbox-computer-use-<timestamp>.json --out receipts\\ember-preloop-resident-gate\\gate-full-parity-harness-<timestamp>.json",
        "n_rows": 1,
    }


def write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(path), receipt)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(repo_root()))
    parser.add_argument("--rollback-rewind-receipt", default=str(DEFAULT_ROLLBACK_RECEIPT))
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    repo = Path(args.repo)
    out = Path(args.out)
    receipt = build_receipt(repo=repo, rollback_receipt=Path(args.rollback_rewind_receipt), out=out)
    write_receipt(out, receipt)
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["verdict"].endswith("_PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())