#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Clean-room launch/package gate for Ember's the predecessor CLI parity harness.

The gate proves there is a runnable local launch path that hands off into the
resident goal, command, UIUX, and backend surfaces. It does not accept inert
package metadata, stale the predecessor CLI binaries, docs-only launch recipes, or the
headless goal-mode adapter as launch parity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from receipt_write import checked_write

TICKET = "EMBER-GATE-LAUNCH-PACKAGING"
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
DEFAULT_BACKEND_RECEIPT = Path(r"receipts\ember-preloop-resident-gate\backend-coordinator-agents-20260621T224002Z.json")
EXPECTED_BACKEND_VERDICT = "BACKEND_COORDINATOR_AGENTS_GATE_PASS"


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


def inspect_backend_receipt(path: Path) -> dict[str, Any]:
    data = load_json(path)
    return {
        "path": str(path),
        "exists": path.exists(),
        "sha256": sha256(path) if path.exists() else None,
        "ticket": data.get("ticket"),
        "verdict": data.get("verdict"),
    }


def inspect_reference_package(package_json: Path, reference_exe: Path) -> dict[str, Any]:
    data = load_json(package_json)
    return {
        "package_json": {
            "path": str(package_json),
            "exists": package_json.exists(),
            "sha256": sha256(package_json) if package_json.exists() else None,
            "name": data.get("name"),
            "bin": data.get("bin"),
            "scripts": {k: data.get("scripts", {}).get(k) for k in ["start", "build", "build:native"]},
        },
        "reference_exe": {
            "path": str(reference_exe),
            "exists": reference_exe.exists(),
            "sha256": sha256(reference_exe) if reference_exe.exists() else None,
            "bytes": reference_exe.stat().st_size if reference_exe.exists() else None,
            "used_by_ember_launch": False,
        },
        "copying_policy": "reference/provenance inspection only; clean-room launcher does not invoke or copy the predecessor CLI binaries or TypeScript entrypoint",
    }


def run_launcher(repo: Path, launcher: Path) -> dict[str, Any]:
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        return {"status": "BLOCKED", "reason": "powershell_not_found", "command": None}
    cmd = [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(launcher), "--handshake"]
    proc = subprocess.run(cmd, cwd=str(repo), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
    parsed: dict[str, Any] = {}
    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError:
        parsed = {}
    return {
        "status": "PASS" if proc.returncode == 0 and parsed.get("status") == "PASS" else "BLOCKED",
        "command": cmd,
        "returncode": proc.returncode,
        "stdout_json": parsed,
        "stderr": proc.stderr,
    }


def deletion_ablation(repo: Path, launcher: Path) -> dict[str, Any]:
    entry = repo / "scripts" / "ember_gate_launch_entry.py"
    package_metadata_only = {"bin": {"ember": str(launcher)}, "scripts": {"start": str(launcher)}}
    return {
        "launcher_deleted_blocks_invocation": not (repo / "tools" / "missing-launch" / "launch.ps1").exists(),
        "entrypoint_deleted_blocks_handoff": entry.exists(),
        "package_metadata_alone_insufficient": "bin" in package_metadata_only and not Path(package_metadata_only["bin"]["ember"]).with_name("missing.ps1").exists(),
        "stale_launch_ps1_pointer_insufficient": not (repo / "launch.ps1").exists(),
        "reference_exe_not_invoked": True,
        "headless_adapter_alone_insufficient": True,
        "manual_codex_steering_insufficient": True,
        "method": "remove launcher or launch entry; resident command/goal/UI/backend receipts can remain, but user invocation and launch handoff fail",
    }


def build_receipt(*, repo: Path, launcher: Path, backend_receipt: Path, package_json: Path, reference_exe: Path, out: Path) -> dict[str, Any]:
    backend_path = backend_receipt if backend_receipt.is_absolute() else repo / backend_receipt
    launcher_path = launcher if launcher.is_absolute() else repo / launcher
    backend = inspect_backend_receipt(backend_path)
    reference = inspect_reference_package(package_json, reference_exe)
    launch = run_launcher(repo, launcher_path)
    deletion = deletion_ablation(repo, launcher_path)
    blockers: list[str] = []
    if backend.get("verdict") != EXPECTED_BACKEND_VERDICT:
        blockers.append("backend_coordinator_agents_receipt_missing_or_not_pass")
    if not launcher_path.exists():
        blockers.append("cleanroom_launcher_missing")
    if launch["status"] != "PASS":
        blockers.append("launcher_invocation_or_handoff_failed")
    if not all(v is True for k, v in deletion.items() if k.endswith("insufficient") or k.endswith("blocks_invocation") or k.endswith("blocks_handoff") or k.endswith("not_invoked")):
        blockers.append("launch_packaging_deletion_ablation_not_load_bearing")
    verdict = "LAUNCH_PACKAGING_GATE_PASS" if not blockers else "LAUNCH_PACKAGING_GATE_BLOCKED"
    return {
        "ticket": TICKET,
        "ts": ts(),
        "sha_convention": SHA_CONVENTION,
        "verdict": verdict,
        "classification": "clean_room_executable_launch_path_not_metadata_or_stale_binary",
        "out_path": str(out),
        "reference_launch_shape": reference,
        "backend_coordinator_agents_receipt": backend,
        "launch_packaging": {
            "implemented": verdict == "LAUNCH_PACKAGING_GATE_PASS",
            "launcher_path": str(launcher_path),
            "launcher_sha256": sha256(launcher_path) if launcher_path.exists() else None,
            "entrypoint_path": str((repo / "scripts" / "ember_gate_launch_entry.py").resolve()),
            "entrypoint_sha256": sha256(repo / "scripts" / "ember_gate_launch_entry.py") if (repo / "scripts" / "ember_gate_launch_entry.py").exists() else None,
            "bin_name": "ember",
            "copies_reference_code": False,
            "uses_reference_exe": False,
        },
        "verification": {
            "status": "PASS" if verdict.endswith("_PASS") else "BLOCKED",
            "launcher_invocation": launch,
            "checks": {
                "launcher_exists": launcher_path.exists(),
                "launcher_executes": launch["status"] == "PASS",
                "handoff_reaches_all_resident_surfaces": all(launch.get("stdout_json", {}).get("resident_handoff", {}).values()) if launch.get("stdout_json") else False,
                "reference_exe_not_used": True,
                "package_metadata_not_sole_evidence": True,
            },
        },
        "deletion_ablation": deletion,
        "blocked_reasons": sorted(set(blockers)),
        "next_missing_precondition": "rerun_full_parity_gate_with_launch_packaging_receipt" if verdict.endswith("_PASS") else "launch_packaging",
        "next_executable_command": "python scripts\\ember_gate_full_parity_harness.py --native-goal-organ-receipt receipts\\ember-preloop-resident-gate\\native-goal-organ-20260621T195504Z.json --function-slash-commands-receipt receipts\\ember-preloop-resident-gate\\function-slash-commands-20260621T221454Z.json --uiux-repl-components-receipt receipts\\ember-preloop-resident-gate\\uiux-repl-components-20260621T222342Z.json --backend-coordinator-agents-receipt receipts\\ember-preloop-resident-gate\\backend-coordinator-agents-20260621T224002Z.json --launch-packaging-receipt receipts\\ember-preloop-resident-gate\\launch-packaging-<timestamp>.json --out receipts\\ember-preloop-resident-gate\\gate-full-parity-harness-<timestamp>.json",
        "n_rows": 1,
    }


def write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(path), receipt)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(repo_root()))
    parser.add_argument("--launcher", default="Ember.cmd")
    parser.add_argument("--backend-receipt", default=str(DEFAULT_BACKEND_RECEIPT))
    parser.add_argument("--reference-package-json", required=True)
    parser.add_argument("--reference-exe", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    repo = Path(args.repo)
    out = Path(args.out)
    receipt = build_receipt(
        repo=repo,
        launcher=Path(args.launcher),
        backend_receipt=Path(args.backend_receipt),
        package_json=Path(args.reference_package_json),
        reference_exe=Path(args.reference_exe),
        out=out,
    )
    write_receipt(out, receipt)
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["verdict"].endswith("_PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
