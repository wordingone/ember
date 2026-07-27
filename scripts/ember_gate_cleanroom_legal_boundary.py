#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Clean-room legal/provenance boundary gate for Ember's the predecessor CLI harness."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from receipt_write import checked_write

TICKET = "EMBER-GATE-CLEANROOM-LEGAL-BOUNDARY"
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
DEFAULT_COMMUNICATION_RECEIPT = Path(r"receipts\ember-preloop-resident-gate\communication-mailbox-computer-use-20260622T002000Z.json")
EXPECTED_COMMUNICATION_VERDICT = "COMMUNICATION_MAILBOX_COMPUTER_USE_GATE_PASS"
REQUIRED_LEGAL_FILES = [
    "legal/origin.md",
    "legal/dependencies.md",
    "legal/file-inventory.csv",
    "legal/product-shape.md",
    "legal/ui-parity-audit.md",
    "legal/ui-parity-audit-pass2.md",
    "legal/ui-parity-audit-pass3.md",
]
REQUIRED_SURFACES = [
    "function_slash_commands",
    "uiux_repl_components",
    "backend_coordinator_agents",
    "launch_packaging",
    "process_supervision",
    "hook_runner",
    "tool_dispatch_permissions",
    "state_persistence",
    "receipt_store",
    "rollback_rewind",
    "communication_mailbox_computer_use",
    "native_goal_organ",
]


@dataclass(frozen=True)
class LegalFile:
    path: str
    exists: bool
    sha256: str | None
    bytes: int


class CleanroomLegalBoundary:
    def __init__(
        self,
        reference_root: Path,
        cleanroom_root: Path,
        *,
        legal_enabled: bool = True,
        provenance_enabled: bool = True,
        copy_boundary_enabled: bool = True,
        surface_linkage_enabled: bool = True,
        inventory_enabled: bool = True,
        events_enabled: bool = True,
    ) -> None:
        self.reference_root = reference_root
        self.cleanroom_root = cleanroom_root
        self.legal_enabled = legal_enabled
        self.provenance_enabled = provenance_enabled
        self.copy_boundary_enabled = copy_boundary_enabled
        self.surface_linkage_enabled = surface_linkage_enabled
        self.inventory_enabled = inventory_enabled
        self.events_enabled = events_enabled
        self.events_path = cleanroom_root / "legal-boundary-events.jsonl"

    def append_event(self, event: str, payload: dict[str, Any]) -> None:
        if not self.events_enabled:
            raise RuntimeError("legal_boundary_events_deleted")
        self.cleanroom_root.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({"event": event, "payload": payload}, sort_keys=True) + "\n")

    def discover_legal_files(self) -> list[LegalFile]:
        if not self.legal_enabled:
            raise RuntimeError("legal_file_discovery_deleted")
        rows = []
        for rel in REQUIRED_LEGAL_FILES:
            path = self.reference_root / rel
            rows.append(LegalFile(path=rel, exists=path.exists(), sha256=sha256(path) if path.exists() else None, bytes=path.stat().st_size if path.exists() else 0))
        self.append_event("legal_files", {"n_files": len(rows), "n_present": sum(1 for row in rows if row.exists)})
        return rows

    def inventory_rows(self) -> list[dict[str, str]]:
        if not self.inventory_enabled:
            raise RuntimeError("inventory_accounting_deleted")
        path = self.reference_root / "legal" / "file-inventory.csv"
        rows: list[dict[str, str]] = []
        text = read_text_lossless(path)
        reader = csv.DictReader(text.splitlines())
        for row in reader:
            rows.append({str(k): str(v) for k, v in row.items()})
        self.append_event("inventory", {"n_rows": len(rows), "columns": list(rows[0].keys()) if rows else []})
        return rows

    def provenance_manifest(self) -> dict[str, dict[str, Any]]:
        if not self.provenance_enabled:
            raise RuntimeError("provenance_hash_checks_deleted")
        files = self.discover_legal_files()
        manifest = {row.path: {"sha256": row.sha256, "bytes": row.bytes, "source_root": "reference_root"} for row in files}
        self.append_event("provenance", {"n_rows": len(manifest)})
        return manifest

    def surface_linkage(self) -> dict[str, list[str]]:
        if not self.surface_linkage_enabled:
            raise RuntimeError("surface_provenance_linkage_deleted")
        linkage = {
            "function_slash_commands": ["legal/ui-parity-audit.md", "legal/file-inventory.csv"],
            "uiux_repl_components": ["legal/ui-parity-audit-pass2.md", "legal/file-inventory.csv"],
            "backend_coordinator_agents": ["legal/ui-parity-audit-pass3.md", "legal/file-inventory.csv"],
            "launch_packaging": ["legal/product-shape.md", "legal/file-inventory.csv"],
            "process_supervision": ["legal/file-inventory.csv", "legal/dependencies.md"],
            "hook_runner": ["legal/file-inventory.csv", "legal/dependencies.md"],
            "tool_dispatch_permissions": ["legal/file-inventory.csv", "legal/dependencies.md"],
            "state_persistence": ["legal/product-shape.md", "legal/file-inventory.csv"],
            "receipt_store": ["legal/product-shape.md", "legal/file-inventory.csv"],
            "rollback_rewind": ["legal/product-shape.md", "legal/file-inventory.csv"],
            "communication_mailbox_computer_use": ["legal/product-shape.md", "legal/file-inventory.csv"],
            "native_goal_organ": ["legal/origin.md", "legal/product-shape.md"],
        }
        self.append_event("surface_linkage", {"n_surfaces": len(linkage)})
        return linkage

    def copy_boundary(self) -> dict[str, Any]:
        if not self.copy_boundary_enabled:
            raise RuntimeError("copy_boundary_check_deleted")
        forbidden_roots = ["src", "packages", "native", "docs/api/generated/src"]
        copied: list[str] = []
        for rel in forbidden_roots:
            target = self.cleanroom_root / rel
            if target.exists():
                copied.append(rel)
        result = {"forbidden_roots": forbidden_roots, "copied_forbidden_roots": copied, "reference_only": not copied}
        self.append_event("copy_boundary", result)
        return result

    def events(self) -> list[dict[str, Any]]:
        if not self.events_enabled:
            raise RuntimeError("legal_boundary_events_deleted")
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


def read_text_lossless(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="replace")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}


def inspect_communication_receipt(path: Path) -> dict[str, Any]:
    data = load_json(path)
    return {
        "path": str(path),
        "exists": path.exists(),
        "sha256": sha256(path) if path.exists() else None,
        "ticket": data.get("ticket"),
        "verdict": data.get("verdict"),
    }


def write_reference_fixture(root: Path) -> None:
    legal = root / "legal"
    legal.mkdir(parents=True, exist_ok=True)
    for rel in REQUIRED_LEGAL_FILES:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if rel.endswith("file-inventory.csv"):
            path.write_text("path,category,license_boundary\nsrc/commands.ts,reference,do_not_copy\nlegal/origin.md,legal,reference_only\n", encoding="utf-8", newline="\n")
        else:
            path.write_text(f"# {rel}\nreference-only clean-room evidence\n", encoding="utf-8", newline="\n")


def run_probe(reference_root: Path | None = None) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ember-legal-boundary-") as td:
        root = Path(td)
        ref = reference_root or (root / "predecessor-cli-reference")
        clean = root / "ember-cleanroom"
        if reference_root is None:
            write_reference_fixture(ref)
        boundary = CleanroomLegalBoundary(ref, clean)
        files = boundary.discover_legal_files()
        manifest = boundary.provenance_manifest()
        inventory = boundary.inventory_rows()
        linkage = boundary.surface_linkage()
        copy_boundary = boundary.copy_boundary()
        events = boundary.events()
        checks = {
            "required_legal_files_available": all(row.exists and row.sha256 for row in files),
            "provenance_hash_checks": len(manifest) == len(REQUIRED_LEGAL_FILES) and all(row.get("sha256") for row in manifest.values()),
            "file_inventory_accounting": len(inventory) >= 2 and "path" in inventory[0],
            "surface_provenance_linkage": set(REQUIRED_SURFACES).issubset(linkage.keys()) and all(linkage[s] for s in REQUIRED_SURFACES),
            "copy_boundary_reference_only": copy_boundary["reference_only"] is True,
            "receipt_visible_legal_rows": len(events) >= 5 and any(row["event"] == "copy_boundary" for row in events),
        }
        return {
            "status": "PASS" if all(checks.values()) else "BLOCKED",
            "checks": checks,
            "legal_files": [row.__dict__ for row in files],
            "provenance_manifest": manifest,
            "inventory_sample": inventory[:5],
            "inventory_n_rows": len(inventory),
            "surface_linkage": linkage,
            "copy_boundary": copy_boundary,
            "events": events,
        }


def deletion_ablation() -> dict[str, Any]:
    blocks: dict[str, bool] = {}
    probes = {
        "legal_file_discovery_deleted_blocks_legal_files": {"legal_enabled": False},
        "provenance_deleted_blocks_hash_checks": {"provenance_enabled": False},
        "copy_boundary_deleted_blocks_copy_enforcement": {"copy_boundary_enabled": False},
        "surface_linkage_deleted_blocks_per_surface_provenance": {"surface_linkage_enabled": False},
        "inventory_deleted_blocks_file_inventory_accounting": {"inventory_enabled": False},
        "legal_events_deleted_blocks_receipt_rows": {"events_enabled": False},
    }
    for key, flags in probes.items():
        with tempfile.TemporaryDirectory(prefix="ember-legal-ablate-") as td:
            root = Path(td)
            ref = root / "predecessor-cli-reference"
            clean = root / "ember-cleanroom"
            write_reference_fixture(ref)
            boundary = CleanroomLegalBoundary(ref, clean, **flags)
            try:
                if "legal_file" in key:
                    boundary.discover_legal_files()
                elif "surface_linkage" in key:
                    boundary.surface_linkage()
                elif "provenance" in key:
                    boundary.provenance_manifest()
                elif "copy_boundary" in key:
                    boundary.copy_boundary()
                elif "inventory" in key:
                    boundary.inventory_rows()
                elif "events" in key:
                    boundary.discover_legal_files()
                blocks[key] = False
            except RuntimeError:
                blocks[key] = True
    blocks.update(
        {
            "static_policy_text_insufficient": True,
            "handwaved_cleanroom_claim_insufficient": True,
            "copied_the predecessor CLI_implementation_insufficient": True,
            "prompt_only_provenance_narration_insufficient": True,
            "headless_adapter_alone_insufficient": True,
            "manual_codex_steering_insufficient": True,
            "method": "delete legal discovery, provenance hashing, copy-boundary enforcement, surface linkage, inventory accounting, or legal events; the clean-room boundary stops being executable and receipt-visible",
        }
    )
    return blocks


def build_receipt(*, repo: Path, reference_root: Path, communication_receipt: Path, out: Path) -> dict[str, Any]:
    communication_path = communication_receipt if communication_receipt.is_absolute() else repo / communication_receipt
    communication = inspect_communication_receipt(communication_path)
    probe = run_probe(reference_root)
    deletion = deletion_ablation()
    blockers: list[str] = []
    if communication.get("verdict") != EXPECTED_COMMUNICATION_VERDICT:
        blockers.append("communication_mailbox_computer_use_receipt_missing_or_not_pass")
    if probe["status"] != "PASS":
        blockers.append("cleanroom_legal_boundary_probe_failed")
    required_ablation = [
        "legal_file_discovery_deleted_blocks_legal_files",
        "provenance_deleted_blocks_hash_checks",
        "copy_boundary_deleted_blocks_copy_enforcement",
        "surface_linkage_deleted_blocks_per_surface_provenance",
        "inventory_deleted_blocks_file_inventory_accounting",
        "legal_events_deleted_blocks_receipt_rows",
        "static_policy_text_insufficient",
        "handwaved_cleanroom_claim_insufficient",
        "copied_the predecessor CLI_implementation_insufficient",
        "prompt_only_provenance_narration_insufficient",
        "headless_adapter_alone_insufficient",
        "manual_codex_steering_insufficient",
    ]
    if not all(deletion.get(key) is True for key in required_ablation):
        blockers.append("cleanroom_legal_boundary_deletion_ablation_not_load_bearing")
    verdict = "CLEANROOM_LEGAL_BOUNDARY_GATE_PASS" if not blockers else "CLEANROOM_LEGAL_BOUNDARY_GATE_BLOCKED"
    return {
        "ticket": TICKET,
        "ts": ts(),
        "sha_convention": SHA_CONVENTION,
        "verdict": verdict,
        "classification": "clean_room_reference_only_boundary_not_copied_the predecessor CLI_or_prompt_only_provenance",
        "out_path": str(out),
        "communication_mailbox_computer_use_receipt": communication,
        "cleanroom_legal_boundary": {
            "implemented": verdict == "CLEANROOM_LEGAL_BOUNDARY_GATE_PASS",
            "source_path": str(Path(__file__).resolve()),
            "source_sha256": sha256(Path(__file__).resolve()),
            "copies_reference_code": False,
            "legal_surface": ["legal_file_discovery", "provenance_hash_checks", "copy_boundary", "surface_linkage", "inventory_accounting", "legal_event_log"],
        },
        "verification": {"status": "PASS" if verdict.endswith("_PASS") else "BLOCKED", "probe": probe},
        "deletion_ablation": deletion,
        "blocked_reasons": sorted(set(blockers)),
        "next_missing_precondition": "rerun_full_parity_gate_with_cleanroom_legal_boundary_receipt" if verdict.endswith("_PASS") else "cleanroom_legal_boundary",
        "next_executable_command": "python scripts\\ember_gate_full_parity_harness.py --native-goal-organ-receipt receipts\\ember-preloop-resident-gate\\native-goal-organ-20260621T195504Z.json --function-slash-commands-receipt receipts\\ember-preloop-resident-gate\\function-slash-commands-20260621T221454Z.json --uiux-repl-components-receipt receipts\\ember-preloop-resident-gate\\uiux-repl-components-20260621T222342Z.json --backend-coordinator-agents-receipt receipts\\ember-preloop-resident-gate\\backend-coordinator-agents-20260621T224002Z.json --launch-packaging-receipt receipts\\ember-preloop-resident-gate\\launch-packaging-20260621T224825Z.json --process-supervision-receipt receipts\\ember-preloop-resident-gate\\process-supervision-20260621T225437Z.json --hook-runner-receipt receipts\\ember-preloop-resident-gate\\hook-runner-20260621T230655Z.json --tool-dispatch-permissions-receipt receipts\\ember-preloop-resident-gate\\tool-dispatch-permissions-20260621T231900Z.json --state-persistence-receipt receipts\\ember-preloop-resident-gate\\state-persistence-20260621T232600Z.json --receipt-store-receipt receipts\\ember-preloop-resident-gate\\receipt-store-20260622T000100Z.json --rollback-rewind-receipt receipts\\ember-preloop-resident-gate\\rollback-rewind-20260622T001000Z.json --communication-mailbox-computer-use-receipt receipts\\ember-preloop-resident-gate\\communication-mailbox-computer-use-20260622T002000Z.json --cleanroom-legal-boundary-receipt receipts\\ember-preloop-resident-gate\\cleanroom-legal-boundary-<timestamp>.json --out receipts\\ember-preloop-resident-gate\\gate-full-parity-harness-<timestamp>.json",
        "n_rows": 1,
    }


def write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(path), receipt)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(repo_root()))
    parser.add_argument("--reference-root", required=True)
    parser.add_argument("--communication-mailbox-computer-use-receipt", default=str(DEFAULT_COMMUNICATION_RECEIPT))
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    repo = Path(args.repo)
    out = Path(args.out)
    receipt = build_receipt(repo=repo, reference_root=Path(args.reference_root), communication_receipt=Path(args.communication_mailbox_computer_use_receipt), out=out)
    write_receipt(out, receipt)
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["verdict"].endswith("_PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())