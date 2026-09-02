#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Intake ScienceAgentBench benchmark_verified.zip into Ember's local benchmark root."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TICKET = "EMBER-SCIENCEAGENTBENCH-ARTIFACT-INTAKE"
SHA_CONVENTION = "bytes on disk/as fetched as-is; text hashes are UTF-8 encoded"
EXPECTED_SIZE_BYTES = 1_769_478_786
PASSWORD = b"scienceagentbench"
DEFAULT_OUT_DIR = Path("receipts/ember-post-resident-discovery")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def zip_password_probe(path: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            encrypted = [info for info in infos if info.flag_bits & 0x1]
            first_file = next((info for info in infos if not info.is_dir()), None)
            if first_file is not None:
                with zf.open(first_file, pwd=PASSWORD) as handle:
                    sample = handle.read(32)
            else:
                sample = b""
            return {
                "ok": True,
                "file_count": len(infos),
                "encrypted_entry_count": len(encrypted),
                "first_file": first_file.filename if first_file else None,
                "password_probe_bytes_read": len(sample),
            }
    except Exception as exc:  # noqa: BLE001 - receipt records exact artifact blocker.
        return {
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def build_receipt(
    *,
    repo: Path,
    out: Path,
    source: Path,
    target: Path,
    extract_dir: Path,
    do_extract: bool,
) -> dict[str, Any]:
    source_exists = source.exists()
    target_exists_before = target.exists()
    chosen_source = source if source_exists else target if target_exists_before else source
    blocked_reasons: list[str] = []
    copied = False
    artifact_sha = None
    artifact_size = None
    zip_probe: dict[str, Any] | None = None
    extracted = False
    extracted_files_sample: list[str] = []

    if not chosen_source.exists():
        blocked_reasons.append("source_artifact_missing")
    else:
        artifact_size = chosen_source.stat().st_size
        if artifact_size != EXPECTED_SIZE_BYTES:
            blocked_reasons.append("artifact_size_mismatch")
        target.parent.mkdir(parents=True, exist_ok=True)
        if chosen_source.resolve() != target.resolve():
            shutil.copy2(chosen_source, target)
            copied = True
        artifact_sha = sha256_file(target)
        zip_probe = zip_password_probe(target)
        if not zip_probe.get("ok"):
            blocked_reasons.append("zip_password_or_integrity_probe_failed")
        if do_extract and not blocked_reasons:
            extract_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(target) as zf:
                zf.extractall(extract_dir, pwd=PASSWORD)
            extracted = True
            extracted_files_sample = [str(p.relative_to(extract_dir)) for p in sorted(extract_dir.rglob("*")) if p.is_file()][:25]

    verdict = "SCIENCEAGENTBENCH_ARTIFACT_INTAKE_READY" if not blocked_reasons else "SCIENCEAGENTBENCH_ARTIFACT_INTAKE_BLOCKED"
    goal_path = repo / "docs/domains/governance/authority/GOAL.md"
    receipt = {
        "ticket": TICKET,
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "repo": str(repo),
        "goal_path": str(goal_path),
        "goal_source_sha256": sha256_file(goal_path) if goal_path.exists() else None,
        "sha_convention": SHA_CONVENTION,
        "scienceagentbench_artifact_status": {
            "expected_name": "benchmark_verified.zip",
            "expected_size_bytes": EXPECTED_SIZE_BYTES,
            "source_path": str(source),
            "source_exists": source_exists,
            "target_path": str(target),
            "target_exists_before": target_exists_before,
            "target_exists_after": target.exists(),
            "copied_to_target": copied,
            "artifact_size_bytes": artifact_size,
            "artifact_sha256": artifact_sha,
            "zip_password_probe": zip_probe,
            "extract_requested": do_extract,
            "extract_dir": str(extract_dir),
            "extracted": extracted,
            "extracted_files_sample": extracted_files_sample,
            "downloaded_or_unzipped_data_redistributed": False,
        },
        "blocked_reasons": blocked_reasons,
        "native_operator_routing": {
            "selected": "scienceagentbench",
            "admission_state": "INTAKE_READY" if not blocked_reasons else "BLOCKED_ARTIFACT_INTAKE",
            "reason": "ScienceAgentBench remains selected; this command only validates and materializes the local benchmark artifact needed for admission.",
        },
        "deleted_selector_routing": {
            "selected": None,
            "admission_state": "ROUTING_BLOCKED_DELETED_SELECTOR",
            "reason": "Deleting the native benchmark router prevents preserving ScienceAgentBench as the selected target during artifact intake.",
        },
        "deletion_sensitive": True,
        "next_executable_command": (
            "python scripts\\ember_scienceagentbench_admission.py --full-artifact "
            f"{target} --out receipts\\ember-post-resident-discovery\\scienceagentbench-admission-<timestamp>.json"
            if not blocked_reasons
            else f"Acquire benchmark_verified.zip through the authorized browser session into {target} or the SAB benchmark root, then rerun this intake script."
        ),
        "code_vs_docs_metric": {
            "classification": "during-project artifact-intake command and receipt",
            "script_code_lines": len((repo / "scripts" / "ember_scienceagentbench_artifact_intake.py").read_text(encoding="utf-8").splitlines()) if (repo / "scripts" / "ember_scienceagentbench_artifact_intake.py").exists() else 0,
            "receipt_lines": 0,
        },
        "verdict": verdict,
    }
    receipt["code_vs_docs_metric"]["receipt_lines"] = len(json.dumps(receipt, indent=2, sort_keys=True).splitlines())
    write_json(out, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--extract-dir", required=True)
    parser.add_argument("--extract", action="store_true")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    repo = Path.cwd().resolve()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out) if args.out else DEFAULT_OUT_DIR / f"scienceagentbench-artifact-intake-{ts}.json"
    if not out.is_absolute():
        out = repo / out
    receipt = build_receipt(
        repo=repo,
        out=out,
        source=Path(args.source),
        target=Path(args.target),
        extract_dir=Path(args.extract_dir),
        do_extract=bool(args.extract),
    )
    print(json.dumps({
        "receipt": str(out),
        "verdict": receipt["verdict"],
        "blocked_reasons": receipt["blocked_reasons"],
        "next_executable_command": receipt["next_executable_command"],
    }, indent=2, sort_keys=True))
    return 0 if receipt["verdict"] in {"SCIENCEAGENTBENCH_ARTIFACT_INTAKE_READY", "SCIENCEAGENTBENCH_ARTIFACT_INTAKE_BLOCKED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())