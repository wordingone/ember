#!/usr/bin/env python3
"""Inventory avir-cli for Ember's clean-room resident harness precondition."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from receipt_write import checked_write

TICKET = "EMBER-AVIR-CLI-CLEANROOM-INVENTORY"
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
DEFAULT_AVIR_ROOT = Path(r"<local-path>")
DEFAULT_PRELOOP_RECEIPT = Path(r"receipts\ember-preloop-resident-gate\preloop-resident-gate-20260621T152149Z.json")
EXCLUDED_DIRS = {
    ".git",
    "node_modules",
    "tmp",
    ".avir",
    ".claude",
    "models",
    "vendor",
    "native",
    "kv-slots",
}
TEXT_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".json", ".md", ".toml", ".yaml", ".yml", ".csv"}


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
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def iter_source_files(root: Path, limit: int = 5000) -> list[Path]:
    if not root.exists():
        return []
    files: list[Path] = []
    for path in root.rglob("*"):
        if len(files) >= limit:
            break
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            files.append(path)
    return sorted(files)


def get_powershell_avir_definition() -> str | None:
    try:
        proc = subprocess.run(
            [
                "powershell",
                "-Command",
                "Get-Command avir -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Definition",
            ],
            text=True,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    lines = [line for line in proc.stdout.splitlines() if line.strip() != "PowerShell profile loaded - PATH refreshed"]
    definition = "\n".join(lines).strip()
    return definition or None


def inspect_launch_surface(avir_root: Path, avir_command_definition: str | None) -> dict[str, Any]:
    exe = avir_root / "avir.exe"
    ps1 = avir_root / "avir.ps1"
    exe_info: dict[str, Any] = {"path": str(exe), "exists": exe.exists()}
    if exe.exists():
        exe_info["bytes"] = exe.stat().st_size
        if exe.stat().st_size <= 50_000_000:
            exe_info["sha256"] = sha256(exe)
        else:
            exe_info["sha256"] = None
            exe_info["sha256_note"] = "large binary hash deferred; clean-room inventory depends on source/provenance receipts"
    return {
        "avir_root": str(avir_root),
        "avir_root_exists": avir_root.exists(),
        "avir_exe": exe_info,
        "avir_ps1": {"path": str(ps1), "exists": ps1.exists(), "sha256": sha256(ps1) if ps1.exists() else None},
        "powershell_avir_command_definition": avir_command_definition,
        "launch_mismatch": bool(avir_command_definition and "avir.ps1" in avir_command_definition and not ps1.exists()),
    }


def inspect_source_inventory(avir_root: Path) -> dict[str, Any]:
    package_path = avir_root / "package.json"
    package = load_json(package_path) if package_path.exists() else {}
    files = iter_source_files(avir_root)
    by_top: dict[str, int] = {}
    for path in files:
        relative = rel(path, avir_root)
        top = relative.split("/", 1)[0]
        by_top[top] = by_top.get(top, 0) + 1
    return {
        "package_json": {
            "path": str(package_path),
            "exists": package_path.exists(),
            "sha256": sha256(package_path) if package_path.exists() else None,
            "name": package.get("name"),
            "version": package.get("version"),
            "bin": package.get("bin"),
            "scripts": package.get("scripts", {}),
        },
        "text_file_count_scanned": len(files),
        "top_level_text_counts": dict(sorted(by_top.items())),
        "sample_files": [rel(path, avir_root) for path in files[:80]],
    }


def candidate_files(files: list[Path], root: Path, needles: list[str], max_hits: int = 25) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    low_needles = [needle.lower() for needle in needles]
    for path in files:
        text = read_text(path)
        low = text.lower()
        found = [needle for needle in low_needles if needle in low]
        if found:
            hits.append({"path": rel(path, root), "matched": sorted(found), "sha256": sha256(path)})
        if len(hits) >= max_hits:
            break
    return hits


def inspect_parity_surface(avir_root: Path) -> dict[str, Any]:
    files = iter_source_files(avir_root)
    surfaces = {
        "goal_parse": candidate_files(files, avir_root, ["goal", "plan", "current blocker", "task", "agent"]),
        "act_or_delegate": candidate_files(files, avir_root, ["agenttool", "sendmessage", "taskstop", "runagent", "worker"]),
        "verify_result": candidate_files(files, avir_root, ["verify", "test", "permission", "statuscheck"]),
        "receipt_write": candidate_files(files, avir_root, ["receipt", "checked_write", "jsonl", "harness-events"]),
        "state_persistence": candidate_files(files, avir_root, ["session", "plan_file_reference", "compact", "resume"]),
    }
    result: dict[str, Any] = {}
    for name, hits in surfaces.items():
        result[name] = {
            "status": "CANDIDATE_SURFACES_FOUND" if hits else "MISSING",
            "candidate_files": hits,
            "cleanroom_parity_proven": False,
            "resident_action_channel_proven": False,
        }
    if result["receipt_write"]["candidate_files"] and not any(
        "receipt" in " ".join(row["matched"]) for row in result["receipt_write"]["candidate_files"]
    ):
        result["receipt_write"]["status"] = "MISSING"
    return result


def inspect_cleanroom_boundary(avir_root: Path) -> dict[str, Any]:
    legal_files = [
        path for path in iter_source_files(avir_root)
        if "legal" in {part.lower() for part in path.parts}
    ]
    cleanroom_receipts = [
        path for path in iter_source_files(avir_root)
        if "clean" in path.name.lower() and "receipt" in path.name.lower()
    ]
    blockers = []
    if not legal_files:
        blockers.append("legal_provenance_surface_missing")
    if not cleanroom_receipts:
        blockers.append("cleanroom_parity_receipt_missing")
    return {
        "status": "BLOCKED" if blockers else "LEGAL_SURFACES_PRESENT_BUT_PARITY_UNPROVEN",
        "legal_provenance_files": [{"path": rel(path, avir_root), "sha256": sha256(path)} for path in legal_files[:40]],
        "cleanroom_receipts": [{"path": rel(path, avir_root), "sha256": sha256(path)} for path in cleanroom_receipts[:40]],
        "blockers": blockers,
    }


def build_receipt(
    *,
    repo: Path,
    avir_root: Path,
    preloop_receipt: Path,
    out: Path,
    avir_command_definition: str | None,
) -> dict[str, Any]:
    preloop = load_json(preloop_receipt) if preloop_receipt.exists() else {}
    launch = inspect_launch_surface(avir_root, avir_command_definition)
    source = inspect_source_inventory(avir_root)
    parity = inspect_parity_surface(avir_root)
    boundary = inspect_cleanroom_boundary(avir_root)

    blocked_reasons: list[str] = []
    if not preloop:
        blocked_reasons.append("preloop_gate_receipt_missing")
    if launch["launch_mismatch"]:
        blocked_reasons.append("avir_ps1_surface_missing_or_command_points_to_missing_script")
    if not launch["avir_exe"]["exists"]:
        blocked_reasons.append("avir_exe_missing")
    blocked_reasons.extend(boundary["blockers"])
    if not any(row["candidate_files"] for row in parity.values()):
        blocked_reasons.append("goal_mode_parity_target_missing")
    else:
        blocked_reasons.append("goal_mode_parity_target_missing")
    blocked_reasons.append("resident_action_channel_not_implemented")
    blocked_reasons.append("delete_ablate_harness_channel_test_missing")

    return {
        "ticket": TICKET,
        "ts": ts(),
        "sha_convention": SHA_CONVENTION,
        "verdict": "AVIR_CLI_CLEANROOM_INVENTORY_BLOCKED",
        "cleanroom_pass_allowed": False,
        "out_path": str(out),
        "preloop_receipt": {
            "path": str(preloop_receipt),
            "exists": preloop_receipt.exists(),
            "sha256": sha256(preloop_receipt) if preloop_receipt.exists() else None,
            "ticket": preloop.get("ticket"),
            "verdict": preloop.get("verdict"),
            "next_missing_precondition": preloop.get("next_missing_precondition"),
        },
        "launch_surface": launch,
        "source_inventory": source,
        "parity_surface_map": parity,
        "copyright_cleanroom_boundary": boundary,
        "blocked_reasons": sorted(set(blocked_reasons)),
        "next_missing_precondition": "avir_cli_goal_mode_parity_adapter",
        "next_executable_command": (
            "python scripts\\ember_avir_cli_goal_mode_parity_adapter.py --out "
            "receipts\\ember-preloop-resident-gate\\avir-cli-goal-mode-parity-adapter-<timestamp>.json"
        ),
        "kill_ablate_test_required": "deleting the resolved avir launch shim or resident action-channel adapter must block the clean-room harness receipt",
        "n_rows": len(parity) + len(source.get("sample_files", [])) + len(boundary.get("legal_provenance_files", [])),
    }


def write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(path), receipt)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--repo", default=str(repo_root()))
    parser.add_argument("--avir-root", default=str(DEFAULT_AVIR_ROOT))
    parser.add_argument("--preloop-receipt", default=str(DEFAULT_PRELOOP_RECEIPT))
    args = parser.parse_args()

    repo = Path(args.repo)
    preloop = Path(args.preloop_receipt)
    if not preloop.is_absolute():
        preloop = repo / preloop
    out = Path(args.out)
    receipt = build_receipt(
        repo=repo,
        avir_root=Path(args.avir_root),
        preloop_receipt=preloop,
        out=out,
        avir_command_definition=get_powershell_avir_definition(),
    )
    write_receipt(out, receipt)
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["verdict"] == "AVIR_CLI_CLEANROOM_INVENTORY_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
