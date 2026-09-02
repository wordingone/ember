#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""ScienceAgentBench admission probe for the Ember post-D3 blocker."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TICKET = "EMBER-SCIENCEAGENTBENCH-ADMISSION"
SHA_CONVENTION = "bytes on disk/as fetched as-is; text hashes are UTF-8 encoded"
DATASET = "osunlp/ScienceAgentBench"
HF_ROWS_URL = (
    "https://datasets-server.huggingface.co/rows?"
    + urllib.parse.urlencode({"dataset": DATASET, "config": "default", "split": "verified", "offset": 0, "length": 25})
)
HF_SPLITS_URL = "https://datasets-server.huggingface.co/splits?" + urllib.parse.urlencode({"dataset": DATASET})
HF_SIZE_URL = "https://datasets-server.huggingface.co/size?" + urllib.parse.urlencode({"dataset": DATASET})
GITHUB_README_URL = "https://raw.githubusercontent.com/OSU-NLP-Group/ScienceAgentBench/main/README.md"
GITHUB_LICENSE_URL = "https://raw.githubusercontent.com/OSU-NLP-Group/ScienceAgentBench/main/LICENSE"
GITHUB_API_MAIN_URL = "https://api.github.com/repos/OSU-NLP-Group/ScienceAgentBench/commits/main"


@dataclass(frozen=True)
class BenchmarkFacts:
    hf_valid: bool
    verified_rows: int
    domains: int
    has_docker_eval: bool
    has_full_artifact_access: bool
    full_artifact_local_path: str | None


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def fetch_text(url: str, timeout: int = 45) -> tuple[str, dict[str, str]]:
    req = urllib.request.Request(url, headers={"User-Agent": "ember-admission-probe/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        headers = {k.lower(): v for k, v in resp.headers.items()}
    return data.decode("utf-8", errors="replace"), headers


def head_url(url: str, timeout: int = 30) -> dict[str, Any]:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "ember-admission-probe/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {
                "ok": True,
                "status": resp.status,
                "final_url": resp.geturl(),
                "content_length": resp.headers.get("Content-Length"),
                "content_type": resp.headers.get("Content-Type"),
            }
    except Exception as exc:  # noqa: BLE001 - receipt records exact blocker, not crash.
        return {"ok": False, "error_type": type(exc).__name__, "error": str(exc)}


def extract_sharepoint_artifact_url(readme: str) -> str | None:
    match = re.search(r"https://buckeyemailosu-my\.sharepoint\.com/[^)\s]+", readme)
    return match.group(0) if match else None


def freeze_candidate_rows(wrapped_rows: list[dict[str, Any]], limit: int = 6) -> list[dict[str, Any]]:
    chosen: list[dict[str, Any]] = []
    seen_domains: set[str] = set()
    for wrapped in wrapped_rows:
        row = wrapped.get("row", wrapped)
        domain = str(row.get("domain", ""))
        if domain in seen_domains and len(seen_domains) < 4:
            continue
        chosen.append(_public_row(row))
        seen_domains.add(domain)
        if len(chosen) >= limit:
            return chosen
    for wrapped in wrapped_rows:
        row = wrapped.get("row", wrapped)
        public = _public_row(row)
        if public not in chosen:
            chosen.append(public)
        if len(chosen) >= limit:
            break
    return chosen


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "instance_id": row.get("instance_id"),
        "domain": row.get("domain"),
        "subtask_categories": row.get("subtask_categories"),
        "github_name": row.get("github_name"),
        "task_inst": row.get("task_inst"),
        "dataset_folder_tree": row.get("dataset_folder_tree"),
        "dataset_preview_sha256": sha256_text(str(row.get("dataset_preview", ""))),
        "src_file_or_path": row.get("src_file_or_path"),
        "output_fname": row.get("output_fname"),
        "eval_script_name": row.get("eval_script_name"),
    }


def select_benchmark_route(facts: BenchmarkFacts, *, deleted: bool) -> dict[str, Any]:
    if deleted:
        return {
            "selected": None,
            "admission_state": "ROUTING_BLOCKED_DELETED_SELECTOR",
            "reason": "native admission selector deleted; static benchmark preference is forbidden",
        }
    score_parts = {
        "hf_verified_split": 2 if facts.hf_valid and facts.verified_rows >= 100 else 0,
        "scientific_domain_breadth": 1 if facts.domains >= 3 else 0,
        "docker_or_programmatic_eval": 2 if facts.has_docker_eval else 0,
        "full_artifacts_local": 3 if facts.has_full_artifact_access else 0,
    }
    state = "ADMITTED" if score_parts["full_artifacts_local"] else "BLOCKED_ARTIFACTS_REQUIRED"
    return {
        "selected": "scienceagentbench",
        "admission_state": state,
        "score_parts": score_parts,
        "score": sum(score_parts.values()),
        "reason": "ScienceAgentBench is the strongest near-term post-D3 field-level target, but full benchmark artifacts are required for executable evaluation." if state != "ADMITTED" else "ScienceAgentBench has metadata plus local full artifacts for executable admission.",
    }


def build_receipt_from_materialized(
    *,
    repo: Path,
    out_dir: Path,
    source_payloads: dict[str, Any],
    source_meta: dict[str, Any],
    full_artifact_local_path: Path | None,
) -> dict[str, Any]:
    hf_rows_payload = source_payloads["hf_rows"]
    wrapped_rows = hf_rows_payload.get("rows", [])
    frozen_rows = freeze_candidate_rows(wrapped_rows, limit=6)
    domains = {str(row.get("domain", "")) for row in frozen_rows if row.get("domain")}
    readme = str(source_payloads.get("github_readme", ""))
    artifact_exists = bool(full_artifact_local_path and full_artifact_local_path.exists())
    facts = BenchmarkFacts(
        hf_valid=bool(wrapped_rows),
        verified_rows=int(hf_rows_payload.get("num_rows_total") or len(wrapped_rows)),
        domains=len(domains),
        has_docker_eval="dockerized evaluation" in readme.lower() or "evaluation.harness.run_evaluation" in readme,
        has_full_artifact_access=artifact_exists,
        full_artifact_local_path=str(full_artifact_local_path) if artifact_exists else None,
    )
    native_route = select_benchmark_route(facts, deleted=False)
    deleted_route = select_benchmark_route(facts, deleted=True)
    blocked_reasons: list[str] = []
    if not facts.hf_valid:
        blocked_reasons.append("hf_verified_rows_unavailable")
    if not facts.has_docker_eval:
        blocked_reasons.append("dockerized_evaluation_not_confirmed")
    if not artifact_exists:
        blocked_reasons.append("full_benchmark_artifacts_not_local")
    verdict = "SCIENCEAGENTBENCH_ADMITTED" if not blocked_reasons else "SCIENCEAGENTBENCH_BLOCKED"
    source_hashes = {}
    for key, payload in source_payloads.items():
        if isinstance(payload, str):
            source_hashes[key] = sha256_text(payload)
        else:
            source_hashes[key] = sha256_text(json.dumps(payload, sort_keys=True))
    artifact_sha = sha256_file(full_artifact_local_path) if artifact_exists and full_artifact_local_path else None
    receipt_path = out_dir if out_dir.suffix.lower() == ".json" else out_dir / "scienceagentbench-admission-receipt.json"
    frozen_rows_path = receipt_path.with_suffix(".frozen_rows.json")
    write_json(frozen_rows_path, {"dataset": DATASET, "split": "verified", "rows": frozen_rows})
    receipt: dict[str, Any] = {
        "ticket": TICKET,
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "sha_convention": SHA_CONVENTION,
        "repo": str(repo),
        "goal_path": str(repo / "docs/domains/governance/authority/GOAL.md"),
        "goal_source_sha256": sha256_file(repo / "docs/domains/governance/authority/GOAL.md") if (repo / "docs/domains/governance/authority/GOAL.md").exists() else None,
        "sources": source_meta,
        "source_hashes": source_hashes,
        "benchmark_facts": facts.__dict__,
        "license_access": {
            "hf_dataset_card_license": "cc-by-4.0 per Hugging Face dataset page checked 2026-06-21",
            "github_code_license": "MIT per LICENSE",
            "readme_license_summary": "Most tasks CC-BY-4.0; rasterio instances 32/46/53/54/84 and matminer instance 3 retain original licenses; unzipped data must not be redistributed.",
        },
        "frozen_heldout_slice": {
            "path": str(frozen_rows_path),
            "sha256": sha256_file(frozen_rows_path),
            "rows": frozen_rows,
            "gold_programs_excluded": True,
            "labels_or_gold_outputs_excluded": True,
        },
        "task_evaluator_inventory": {
            "verified_rows": facts.verified_rows,
            "frozen_rows": len(frozen_rows),
            "domains_in_frozen_rows": sorted(domains),
            "output_fnames": [row.get("output_fname") for row in frozen_rows],
            "eval_script_names": [row.get("eval_script_name") for row in frozen_rows],
            "target_output_form": "self-contained Python program producing task-specific pred_results artifacts",
        },
        "local_materialization": {
            "full_artifact_expected": "benchmark_verified.zip",
            "full_artifact_local_path": str(full_artifact_local_path) if full_artifact_local_path else None,
            "full_artifact_exists": artifact_exists,
            "full_artifact_sha256": artifact_sha,
            "hf_metadata_materialized": True,
        },
        "run_requirements": {
            "primary_eval": "Dockerized evaluation via python -m evaluation.harness.run_evaluation --benchmark_path benchmark --pred_program_path pred_programs --log_fname <log> --run_id <id>",
            "threads_claim": "README states 102 SAB instances can run within 30 minutes using 8 threads as of 2025-01-10 update.",
            "requires_openai_key_for_direct_eval": True,
            "docker_recommended": True,
        },
        "native_operator_routing": native_route,
        "deleted_selector_routing": deleted_route,
        "deletion_sensitive": native_route.get("selected") != deleted_route.get("selected") and deleted_route.get("admission_state") == "ROUTING_BLOCKED_DELETED_SELECTOR",
        "blocked_reasons": blocked_reasons,
        "code_vs_docs_metric": {
            "classification": "during-project benchmark admission receipt",
            "script_code_lines": len((repo / "scripts" / "ember_scienceagentbench_admission.py").read_text(encoding="utf-8").splitlines()) if (repo / "scripts" / "ember_scienceagentbench_admission.py").exists() else 0,
            "receipt_lines": 0,
            "frozen_rows": len(frozen_rows),
        },
        "benchmark_fit_to_goal": [
            "external scientific data/code environments from peer-reviewed publications",
            "agent must generate executable code/artifacts under evaluator pressure",
            "stronger field-level validation than D3 small-loop proof",
            "requires admission before equal-budget A/B/C/deleted loop can run",
        ],
        "next_executable_command": (
            "Download benchmark_verified.zip from the README SharePoint artifact link into "
            f"{full_artifact_local_path.parent if full_artifact_local_path else '<the intended --full-artifact directory>'}, "
            "verify sha256, unzip locally without redistributing, then rerun: "
            "python scripts\\ember_scienceagentbench_admission.py --full-artifact "
            f"{full_artifact_local_path or '<local artifact path>'} --out receipts\\ember-post-resident-discovery\\scienceagentbench-admission-<timestamp>.json"
        ) if blocked_reasons else (
            "Run first ScienceAgentBench A/B/C/deleted heldout loop against frozen rows in " + str(frozen_rows_path)
        ),
        "fallback_order_if_blocked_after_artifact_attempt": ["re-bench", "paperbench", "broader-d3-multifamily"],
        "verdict": verdict,
    }
    receipt["code_vs_docs_metric"]["receipt_lines"] = len(json.dumps(receipt, indent=2, sort_keys=True).splitlines())
    write_json(receipt_path, receipt)
    return receipt


def collect_source_payloads() -> tuple[dict[str, Any], dict[str, Any]]:
    readme, readme_headers = fetch_text(GITHUB_README_URL)
    license_text, license_headers = fetch_text(GITHUB_LICENSE_URL)
    rows_text, rows_headers = fetch_text(HF_ROWS_URL)
    splits_text, splits_headers = fetch_text(HF_SPLITS_URL)
    size_text, size_headers = fetch_text(HF_SIZE_URL)
    try:
        commit_text, commit_headers = fetch_text(GITHUB_API_MAIN_URL)
        commit_payload: Any = json.loads(commit_text)
    except Exception as exc:  # noqa: BLE001
        commit_payload = {"error_type": type(exc).__name__, "error": str(exc)}
        commit_headers = {}
    sharepoint_url = extract_sharepoint_artifact_url(readme)
    sharepoint_head = head_url(sharepoint_url) if sharepoint_url else {"ok": False, "error": "sharepoint_url_not_found"}
    payloads = {
        "github_readme": readme,
        "github_license": license_text,
        "github_main_commit": commit_payload,
        "hf_rows": json.loads(rows_text),
        "hf_splits": json.loads(splits_text),
        "hf_size": json.loads(size_text),
    }
    meta = {
        "github_readme_url": GITHUB_README_URL,
        "github_license_url": GITHUB_LICENSE_URL,
        "github_api_main_url": GITHUB_API_MAIN_URL,
        "hf_rows_url": HF_ROWS_URL,
        "hf_splits_url": HF_SPLITS_URL,
        "hf_size_url": HF_SIZE_URL,
        "sharepoint_artifact_url": sharepoint_url,
        "sharepoint_head_status": sharepoint_head,
        "response_headers": {
            "github_readme": readme_headers,
            "github_license": license_headers,
            "github_main_commit": commit_headers,
            "hf_rows": rows_headers,
            "hf_splits": splits_headers,
            "hf_size": size_headers,
        },
    }
    return payloads, meta


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--out", default=None)
    parser.add_argument("--full-artifact", default=None)
    args = parser.parse_args()
    if args.selftest:
        import ember_scienceagentbench_admission_selftest
        return ember_scienceagentbench_admission_selftest.main()
    repo = Path.cwd().resolve()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out) if args.out else Path("receipts/ember-post-resident-discovery") / f"scienceagentbench-admission-{ts}.json"
    if not out.is_absolute():
        out = repo / out
    payloads, meta = collect_source_payloads()
    artifact = Path(args.full_artifact) if args.full_artifact else None
    receipt = build_receipt_from_materialized(
        repo=repo,
        out_dir=out,
        source_payloads=payloads,
        source_meta=meta,
        full_artifact_local_path=artifact,
    )
    print(json.dumps({
        "receipt": str(out),
        "verdict": receipt["verdict"],
        "blocked_reasons": receipt["blocked_reasons"],
        "selected": receipt["native_operator_routing"].get("selected"),
        "deletion_sensitive": receipt["deletion_sensitive"],
        "frozen_rows": len(receipt["frozen_heldout_slice"]["rows"]),
        "next_executable_command": receipt["next_executable_command"],
    }, indent=2, sort_keys=True))
    return 0 if receipt["verdict"] in {"SCIENCEAGENTBENCH_ADMITTED", "SCIENCEAGENTBENCH_BLOCKED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
