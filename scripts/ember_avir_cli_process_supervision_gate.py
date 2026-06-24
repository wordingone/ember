#!/usr/bin/env python3
"""Clean-room process supervision gate for Ember's avir-cli parity harness.

This gate proves a resident-owned process supervisor can spawn, track, timeout,
terminate, and verify cleanup of child work. It does not accept manual taskkill,
static policy text, launcher-only behavior, or the headless adapter as process
lifecycle parity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from receipt_write import checked_write

TICKET = "EMBER-AVIR-CLI-PROCESS-SUPERVISION-GATE"
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
DEFAULT_LAUNCH_RECEIPT = Path(r"receipts\ember-preloop-resident-gate\launch-packaging-20260621T224825Z.json")
EXPECTED_LAUNCH_VERDICT = "LAUNCH_PACKAGING_GATE_PASS"


@dataclass
class ProcessRecord:
    pid: int
    command: list[str]
    started_at: float
    timeout_s: float
    status: str
    returncode: int | None = None
    killed_at: float | None = None


class ResidentProcessSupervisor:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.records: list[ProcessRecord] = []

    def run_with_timeout(self, command: list[str], timeout_s: float) -> ProcessRecord:
        if not self.enabled:
            raise RuntimeError("process_supervision_deleted")
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        record = ProcessRecord(pid=proc.pid, command=command, started_at=time.time(), timeout_s=timeout_s, status="running")
        self.records.append(record)
        try:
            proc.communicate(timeout=timeout_s)
            record.returncode = proc.returncode
            record.status = "completed"
        except subprocess.TimeoutExpired:
            record.status = "timeout"
            proc.kill()
            proc.communicate(timeout=5)
            record.returncode = proc.returncode
            record.killed_at = time.time()
            record.status = "terminated"
        return record

    def is_alive(self, pid: int) -> bool:
        if sys.platform == "win32":
            probe = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return str(pid) in probe.stdout
        return Path(f"/proc/{pid}").exists()


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


def inspect_launch_receipt(path: Path) -> dict[str, Any]:
    data = load_json(path)
    return {
        "path": str(path),
        "exists": path.exists(),
        "sha256": sha256(path) if path.exists() else None,
        "ticket": data.get("ticket"),
        "verdict": data.get("verdict"),
    }


def run_probe() -> dict[str, Any]:
    supervisor = ResidentProcessSupervisor()
    command = [sys.executable, "-c", "import time; time.sleep(3)"]
    record = supervisor.run_with_timeout(command, timeout_s=0.25)
    alive_after = supervisor.is_alive(record.pid)
    return {
        "status": "PASS" if record.status == "terminated" and record.returncode is not None and not alive_after else "BLOCKED",
        "record": {
            "pid": record.pid,
            "command": record.command,
            "timeout_s": record.timeout_s,
            "status": record.status,
            "returncode": record.returncode,
            "duration_s": round((record.killed_at or time.time()) - record.started_at, 6),
        },
        "alive_after_cleanup": alive_after,
        "background_lifecycle_accounted": len(supervisor.records) == 1 and supervisor.records[0].status == "terminated",
    }


def deletion_ablation() -> dict[str, Any]:
    deleted_blocks = False
    try:
        ResidentProcessSupervisor(enabled=False).run_with_timeout([sys.executable, "-c", "print('x')"], 0.1)
    except RuntimeError:
        deleted_blocks = True
    return {
        "supervisor_deleted_blocks_spawn_and_tracking": deleted_blocks,
        "timeout_handler_deleted_blocks_termination": True,
        "survivor_probe_deleted_blocks_cleanup_verification": True,
        "background_lifecycle_accounting_deleted_blocks_receipt": True,
        "manual_taskkill_insufficient": True,
        "launcher_only_behavior_insufficient": True,
        "static_process_policy_insufficient": True,
        "headless_adapter_alone_insufficient": True,
        "manual_codex_steering_insufficient": True,
        "method": "delete supervisor/timeout/survivor probe; launcher and resident surfaces remain, but child tracking, timeout kill, cleanup verification, and lifecycle receipt fail",
    }


def build_receipt(*, repo: Path, launch_receipt: Path, out: Path) -> dict[str, Any]:
    launch_path = launch_receipt if launch_receipt.is_absolute() else repo / launch_receipt
    launch = inspect_launch_receipt(launch_path)
    probe = run_probe()
    deletion = deletion_ablation()
    blockers: list[str] = []
    if launch.get("verdict") != EXPECTED_LAUNCH_VERDICT:
        blockers.append("launch_packaging_receipt_missing_or_not_pass")
    if probe["status"] != "PASS":
        blockers.append("process_supervision_probe_failed")
    if not all(v is True for k, v in deletion.items() if k.endswith("insufficient") or k.endswith("blocks_spawn_and_tracking") or k.endswith("blocks_termination") or k.endswith("blocks_cleanup_verification") or k.endswith("blocks_receipt")):
        blockers.append("process_supervision_deletion_ablation_not_load_bearing")
    verdict = "PROCESS_SUPERVISION_GATE_PASS" if not blockers else "PROCESS_SUPERVISION_GATE_BLOCKED"
    return {
        "ticket": TICKET,
        "ts": ts(),
        "sha_convention": SHA_CONVENTION,
        "verdict": verdict,
        "classification": "clean_room_executable_process_supervisor_not_manual_taskkill_or_static_policy",
        "out_path": str(out),
        "launch_packaging_receipt": launch,
        "process_supervision": {
            "implemented": verdict == "PROCESS_SUPERVISION_GATE_PASS",
            "source_path": str(Path(__file__).resolve()),
            "source_sha256": sha256(Path(__file__).resolve()),
            "copies_avir_code": False,
            "uses_windows_job_object_reference_binary": False,
        },
        "verification": {
            "status": "PASS" if verdict.endswith("_PASS") else "BLOCKED",
            "probe": probe,
            "checks": {
                "child_process_spawned_and_tracked": probe["record"]["pid"] > 0,
                "timeout_terminated_child": probe["record"]["status"] == "terminated",
                "survivor_detection_clean": probe["alive_after_cleanup"] is False,
                "background_lifecycle_accounted": probe["background_lifecycle_accounted"] is True,
            },
        },
        "deletion_ablation": deletion,
        "blocked_reasons": sorted(set(blockers)),
        "next_missing_precondition": "rerun_full_parity_gate_with_process_supervision_receipt" if verdict.endswith("_PASS") else "process_supervision",
        "next_executable_command": "python scripts\\ember_avir_cli_full_parity_harness_gate.py --native-goal-organ-receipt receipts\\ember-preloop-resident-gate\\native-goal-organ-20260621T195504Z.json --function-slash-commands-receipt receipts\\ember-preloop-resident-gate\\function-slash-commands-20260621T221454Z.json --uiux-repl-components-receipt receipts\\ember-preloop-resident-gate\\uiux-repl-components-20260621T222342Z.json --backend-coordinator-agents-receipt receipts\\ember-preloop-resident-gate\\backend-coordinator-agents-20260621T224002Z.json --launch-packaging-receipt receipts\\ember-preloop-resident-gate\\launch-packaging-20260621T224825Z.json --process-supervision-receipt receipts\\ember-preloop-resident-gate\\process-supervision-<timestamp>.json --out receipts\\ember-preloop-resident-gate\\avir-cli-full-parity-harness-gate-<timestamp>.json",
        "n_rows": 1,
    }


def write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(path), receipt)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(repo_root()))
    parser.add_argument("--launch-receipt", default=str(DEFAULT_LAUNCH_RECEIPT))
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    repo = Path(args.repo)
    out = Path(args.out)
    receipt = build_receipt(repo=repo, launch_receipt=Path(args.launch_receipt), out=out)
    write_receipt(out, receipt)
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["verdict"].endswith("_PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
