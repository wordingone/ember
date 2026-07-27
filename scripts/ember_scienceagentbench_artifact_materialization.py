#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Materialize or block ScienceAgentBench verified benchmark artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GITHUB_README_URL = "https://raw.githubusercontent.com/OSU-NLP-Group/ScienceAgentBench/main/README.md"
DEFAULT_OUT_DIR = Path("receipts/ember-post-resident-discovery")
EXPECTED_ARTIFACT_SIZE_BYTES = 1_769_478_786
SHA_CONVENTION = "bytes on disk/as fetched as-is; text hashes are UTF-8 encoded"

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def fetch_readme(timeout: int = 45) -> str:
    req = urllib.request.Request(GITHUB_README_URL, headers={"User-Agent": "ember-sab-artifact-probe/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def extract_sharepoint_artifact_url(readme: str) -> str | None:
    match = re.search(r"https://buckeyemailosu-my\.sharepoint\.com/[^)\s]+", readme)
    return match.group(0) if match else None


def probe_url(url: str, *, method: str, byte_range: str | None = None, timeout: int = 45) -> dict[str, Any]:
    headers = {"User-Agent": "ember-sab-artifact-probe/1.0"}
    if byte_range:
        headers["Range"] = byte_range
    req = urllib.request.Request(url, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(32) if method == "GET" else b""
            return {
                "method": method,
                "range": byte_range,
                "ok": True,
                "status": resp.status,
                "final_url": resp.geturl(),
                "content_length": resp.headers.get("Content-Length"),
                "content_type": resp.headers.get("Content-Type"),
                "bytes_read": len(body),
            }
    except urllib.error.HTTPError as exc:
        return {
            "method": method,
            "range": byte_range,
            "ok": False,
            "status": exc.code,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "final_url": exc.geturl(),
        }
    except Exception as exc:  # noqa: BLE001 - receipt records exact operational blocker.
        return {
            "method": method,
            "range": byte_range,
            "ok": False,
            "status": None,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def blocked_reason_from_probes(probes: list[dict[str, Any]]) -> str:
    statuses = {probe.get("status") for probe in probes}
    if 401 in statuses or 403 in statuses:
        return "sharepoint_artifact_requires_authorized_access"
    if all(probe.get("ok") is False for probe in probes):
        return "sharepoint_artifact_probe_failed"
    return "sharepoint_artifact_not_materialized"


def build_blocked_receipt(
    *,
    repo: Path,
    out: Path,
    artifact_url: str,
    expected_local_path: Path,
    probes: list[dict[str, Any]],
) -> dict[str, Any]:
    if any(probe.get("ok") is True for probe in probes):
        raise ValueError("successful artifact probe cannot be converted into a blocked receipt")
    artifact_exists = expected_local_path.exists()
    if artifact_exists:
        raise ValueError("local artifact exists; rerun admission with --full-artifact instead of blocking")
    receipt = {
        "ticket": "EMBER-SCIENCEAGENTBENCH-ARTIFACT-MATERIALIZATION",
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "repo": str(repo),
        "goal_path": str(repo / "GOAL.md"),
        "goal_source_sha256": sha256_file(repo / "GOAL.md") if (repo / "GOAL.md").exists() else None,
        "sha_convention": SHA_CONVENTION,
        "sources": {
            "github_readme_url": GITHUB_README_URL,
            "sharepoint_artifact_url": artifact_url,
        },
        "artifact_probes": probes,
        "scienceagentbench_artifact_status": {
            "expected_name": "benchmark_verified.zip",
            "expected_local_path": str(expected_local_path),
            "expected_size_bytes": EXPECTED_ARTIFACT_SIZE_BYTES,
            "full_artifact_exists": False,
            "downloaded_or_unzipped_data_redistributed": False,
        },
        "blocked_reasons": [blocked_reason_from_probes(probes)],
        "native_operator_routing": {
            "selected_before_block": "scienceagentbench",
            "admission_state": "BLOCKED_ARTIFACT_MATERIALIZATION",
            "reason": "ScienceAgentBench remains the preferred stronger target, but its verified full artifact is not obtainable by safe unauthenticated local probing.",
        },
        "next_benchmark": {
            "selected": "scienceagentbench",
            "reason": "SAB remains the selected stronger target while the only blocker is local artifact arrival; do not fall back to RE-Bench/PaperBench/D3 until a fresh receipt proves a different SAB blocker.",
            "next_executable_command": (
                "Acquire benchmark_verified.zip from the ScienceAgentBench README SharePoint link through an authorized browser session, "
                f"place it at {expected_local_path}, verify size {EXPECTED_ARTIFACT_SIZE_BYTES} bytes and sha256, unzip locally with password scienceagentbench, "
                "then rerun python scripts\\ember_scienceagentbench_admission.py --full-artifact "
                f"{expected_local_path} --out receipts\\ember-post-resident-discovery\\scienceagentbench-admission-<timestamp>.json"
            ),
        },
        "deleted_selector_routing": {
            "selected": None,
            "admission_state": "ROUTING_BLOCKED_DELETED_SELECTOR",
            "reason": "Deleting the native benchmark router prevents preserving ScienceAgentBench as the selected target under a local-artifact-only block.",
        },
        "deletion_sensitive": True,
        "code_vs_docs_metric": {
            "classification": "during-project artifact-materialization blocked receipt",
            "script_code_lines": len((repo / "scripts" / "ember_scienceagentbench_artifact_materialization.py").read_text(encoding="utf-8").splitlines()) if (repo / "scripts" / "ember_scienceagentbench_artifact_materialization.py").exists() else 0,
            "receipt_lines": 0,
        },
        "verdict": "SCIENCEAGENTBENCH_ARTIFACT_MATERIALIZATION_BLOCKED",
    }
    receipt["code_vs_docs_metric"]["receipt_lines"] = len(json.dumps(receipt, indent=2, sort_keys=True).splitlines())
    write_json(out, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--artifact", default=None)
    parser.add_argument("--artifact-url", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    if args.selftest:
        import ember_scienceagentbench_artifact_materialization_selftest
        return ember_scienceagentbench_artifact_materialization_selftest.main()
    if not args.artifact:
        parser.error(
            "--artifact is required unless --selftest is used (no baked-in "
            "default; original path was scrubbed for public export, see issue #261)"
        )

    repo = Path.cwd().resolve()
    artifact = Path(args.artifact)
    if artifact.exists():
        print(json.dumps({
            "verdict": "SCIENCEAGENTBENCH_ARTIFACT_ALREADY_LOCAL",
            "artifact": str(artifact),
            "sha256": sha256_file(artifact),
            "next_executable_command": f"python scripts\\ember_scienceagentbench_admission.py --full-artifact {artifact} --out receipts\\ember-post-resident-discovery\\scienceagentbench-admission-<timestamp>.json",
        }, indent=2, sort_keys=True))
        return 0

    artifact_url = args.artifact_url
    if not artifact_url:
        readme = fetch_readme()
        artifact_url = extract_sharepoint_artifact_url(readme)
    if not artifact_url:
        raise SystemExit("ScienceAgentBench SharePoint artifact URL not found in README")

    probes = [
        probe_url(artifact_url, method="HEAD"),
        probe_url(artifact_url, method="GET", byte_range="bytes=0-0"),
    ]
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out) if args.out else DEFAULT_OUT_DIR / f"scienceagentbench-artifact-materialization-blocked-{ts}.json"
    if not out.is_absolute():
        out = repo / out
    receipt = build_blocked_receipt(
        repo=repo,
        out=out,
        artifact_url=artifact_url,
        expected_local_path=artifact,
        probes=probes,
    )
    print(json.dumps({
        "receipt": str(out),
        "verdict": receipt["verdict"],
        "blocked_reasons": receipt["blocked_reasons"],
        "next_benchmark": receipt["next_benchmark"]["selected"],
        "next_executable_command": receipt["next_benchmark"]["next_executable_command"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
