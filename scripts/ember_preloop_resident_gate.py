#!/usr/bin/env python3
"""Fail-closed inspector for Ember's pre-loop resident-training gate.

This script does not implement the resident organs. It makes the current gate
state explicit: read the binding sources, reject symbolic substitutions, and
name the next executable implementation command until the three non-killable
preconditions are actually receipted.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from receipt_write import checked_write

TICKET = "EMBER-PRELOOP-RESIDENT-GATE"
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
DEFAULT_PAPER_ROOT = Path(r"<local-path>")
DEFAULT_AVIR_ROOT = Path(r"<local-path>")
INVALID_SUBSTITUTIONS = [
    "symbolic-template-policy",
    "prompt-only substitution",
    "handcrafted routing",
    "static registry",
    "scalar dictionary",
    "rerank-only wrapper",
    "frozen-model inference",
    "RLM/iGRPO-style wording without neural parameter updates",
]

FLOOR_ROWS = {
    "QAT": ["QAT"],
    "Muon": ["Muon"],
    "QK-norm": ["QK-norm", "QK norm"],
    "Governor": ["Governor", "governor"],
    "Encoder-free multimodal TRAINING": ["Encoder-free multimodal", "multimodal TRAINING"],
    "BitNet / 1.58-bit ternary": ["BitNet", "1.58"],
    "SDEK / GDN-Jet fast-weight sleep consolidation": ["SDEK", "GDN"],
    "MLA / KV-cache compression": ["MLA", "KV-cache", "KV compression"],
    "GRPO / RL-on-verifier-reward": ["GRPO", "verifier"],
    "FP8 training": ["FP8"],
    "MoE": ["MoE"],
    "DiffusionGemma sampler": ["DiffusionGemma"],
}

NC2_COMPONENTS = {
    "QAT": ["QAT"],
    "turboquant": ["turboquant"],
    "BitNet/1.58-bit": ["BitNet", "1.58"],
    "SubQ/sparse attention": ["SubQ", "sparse attention"],
    "MTP": ["MTP"],
    "SDEK": ["SDEK"],
    "Gemma-4 unified multimodal architecture": ["Gemma", "unified multimodal"],
}


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


def has_any(text: str, needles: list[str]) -> bool:
    low = text.lower()
    return any(needle.lower() in low for needle in needles)


def extract_abstract(abs_html_path: Path) -> str:
    if not abs_html_path.exists():
        return ""
    text = read_text(abs_html_path)
    match = re.search(r'meta name="citation_abstract" content="(.*?)"', text, flags=re.S)
    if match:
        return html.unescape(match.group(1)).strip()
    match = re.search(r'<blockquote class="abstract mathjax">(.*?)</blockquote>', text, flags=re.S)
    if not match:
        return ""
    cleaned = re.sub(r"<.*?>", " ", match.group(1))
    return html.unescape(re.sub(r"\s+", " ", cleaned)).replace("Abstract:", "").strip()


def inspect_goal(repo: Path) -> dict[str, Any]:
    path = repo / "GOAL.md"
    text = read_text(path)
    markers = {
        "current_blocker_packet": "Current Blocker Packet" in text,
        "requirement_14": "Requirement 14" in text or "RLM/iGRPO harness-native training organ" in text,
        "neural_update_floor": "actual neural parameter" in text and "state_dict" in text,
        "invalid_symbolic_substitutions": all(term in text for term in ["deterministic template", "scalar dictionary", "prompt"]),
        "clean_room_avir_cli": "clean-room `avir-cli`" in text or "clean-room avir-cli" in text,
    }
    return {
        "path": str(path),
        "exists": path.exists(),
        "sha256": sha256(path) if path.exists() else None,
        "markers": markers,
        "status": "PRESENT" if path.exists() and all(markers.values()) else "INCOMPLETE",
    }


def inspect_train_multimodal(repo: Path) -> dict[str, Any]:
    path = repo / "scripts" / "train_multimodal_v0.py"
    text = read_text(path)
    primitives = ["emit-token", "emit-scalar", "emit-pointer", "commit", "stop"]
    return {
        "path": str(path),
        "exists": path.exists(),
        "sha256": sha256(path) if path.exists() else None,
        "has_adamw": "AdamW" in text,
        "has_state_dict": "state_dict" in text,
        "has_action_log_contract": "action-log" in text or "action_log" in text,
        "has_multimodal_locks": all(term in text for term in ["QK-norm", "inputs_embeds", "bidirectional"]),
        "action_log_primitives_present": [primitive for primitive in primitives if primitive in text],
        "adapter_decision": "ADAPT_REQUIRED_BEFORE_TINY_FALLBACK",
        "status": "AVAILABLE_LAUNCH_VEHICLE" if path.exists() and "AdamW" in text and "state_dict" in text else "BLOCKED",
    }


def inspect_floor_contract(repo: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    floor = repo / "docs" / "ember-floor-contract.md"
    nc2 = repo / "nc2-own-technique-contract.md"
    floor_text = read_text(floor)
    nc2_text = read_text(nc2)
    floor_sha = sha256(floor) if floor.exists() else None
    nc2_sha = sha256(nc2) if nc2.exists() else None
    manifest: dict[str, dict[str, Any]] = {}
    for name, needles in FLOOR_ROWS.items():
        present = has_any(floor_text, needles)
        manifest[name] = {
            "source_file": "docs/ember-floor-contract.md",
            "source_hash": floor_sha,
            "status": "preserved_trigger_gated" if present else "blocked_with_exact_adapter_surface",
            "present": present,
            "launch_vehicle_impact": "must be preserved/accounted by resident gate; not silently archived or killed",
            "trigger": "row-specific trigger or resident-training gate if active",
            "pilot": "row-specific receipt-producing pilot",
            "kill_ablate_condition": "only contradiction-level receipt or user-approved contract change can remove",
            "evidence_path": str(floor),
        }
    for name, needles in NC2_COMPONENTS.items():
        present = has_any(nc2_text, needles)
        manifest[f"nc2:{name}"] = {
            "source_file": "nc2-own-technique-contract.md",
            "source_hash": nc2_sha,
            "status": "preserved_trigger_gated" if present else "blocked_with_exact_adapter_surface",
            "present": present,
            "launch_vehicle_impact": "binding owned-core component contract remains in GOAL authority",
            "trigger": "resident-training adapter or owned-core scale trigger",
            "pilot": "component-specific receipt-producing pilot",
            "kill_ablate_condition": "no archival/killed disposition without physics-level contradiction receipt",
            "evidence_path": str(nc2),
        }
    summary = {
        "floor_path": str(floor),
        "floor_exists": floor.exists(),
        "floor_sha256": floor_sha,
        "nc2_path": str(nc2),
        "nc2_exists": nc2.exists(),
        "nc2_sha256": nc2_sha,
        "rows": len(manifest),
        "missing_rows": [key for key, row in manifest.items() if not row["present"]],
    }
    return manifest, summary


def inspect_papers(paper_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    index_path = paper_root / "INDEX.json"
    if not index_path.exists():
        return [], ["paper_index_missing"]
    index = load_json(index_path)
    rows: list[dict[str, Any]] = []
    for paper in index.get("papers", []):
        receipt_path = Path(str(paper.get("receipt", "")))
        if not receipt_path.is_absolute():
            receipt_path = paper_root / receipt_path
        source_receipt_read = receipt_path.exists()
        receipt = load_json(receipt_path) if source_receipt_read else {}
        if not source_receipt_read:
            errors.append(f"paper_source_receipt_missing.{paper.get('kind')}")
        abs_path = Path(str(receipt.get("files", {}).get("abs_html", {}).get("path", ""))) if receipt else Path()
        abstract = extract_abstract(abs_path) if str(abs_path) else ""
        rows.append(
            {
                "kind": paper.get("kind"),
                "title": paper.get("title"),
                "arxiv_id": paper.get("arxiv_id"),
                "index_path": str(index_path),
                "index_sha256": sha256(index_path),
                "source_receipt_path": str(receipt_path),
                "source_receipt_sha256": sha256(receipt_path) if source_receipt_read else None,
                "source_receipt_read": source_receipt_read,
                "pdf_sha256": paper.get("pdf_sha256") or receipt.get("files", {}).get("pdf", {}).get("sha256"),
                "source_sha256": paper.get("source_sha256") or receipt.get("files", {}).get("source", {}).get("sha256"),
                "abs_html_path": str(abs_path) if str(abs_path) else None,
                "abs_html_read": bool(abstract),
                "abstract_excerpt": abstract[:500],
                "mechanism_primitives": mechanism_primitives(str(paper.get("kind", ""))),
            }
        )
    seen = {row["kind"] for row in rows}
    for required in {"RLM", "iGRPO"} - seen:
        errors.append(f"paper_missing.{required}")
    return rows, errors


def mechanism_primitives(kind: str) -> list[str]:
    if kind == "RLM":
        return [
            "bounded recursive inspection of external context/state",
            "model call over selected subproblem or snippet",
            "aggregation of recursive sub-results into action or answer",
            "learned policy for what to inspect, recurse on, and aggregate",
        ]
    if kind == "iGRPO":
        return [
            "sample multiple draft attempts under matched budget",
            "score attempts with verifier/reward",
            "condition refinement on the best scored draft",
            "update trainable policy parameters from verifier-conditioned experience",
            "ablate against plain/fixed GRPO-style baseline",
        ]
    return []


def inspect_avir_root(avir_root: Path, avir_command_definition: str | None) -> dict[str, Any]:
    exe = avir_root / "avir.exe"
    ps1 = avir_root / "avir.ps1"
    parity_receipts = sorted(avir_root.glob("**/*cleanroom*receipt*.json")) if avir_root.exists() else []
    implementation_files = sorted((avir_root / "src").glob("**/*"))[:50] if (avir_root / "src").exists() else []
    exe_info: dict[str, Any] = {"path": str(exe), "exists": exe.exists()}
    if exe.exists():
        exe_info["bytes"] = exe.stat().st_size
        if exe.stat().st_size <= 50_000_000:
            exe_info["sha256"] = sha256(exe)
        else:
            exe_info["sha256"] = None
            exe_info["sha256_note"] = "large binary hash deferred; gate requires parity receipt, not binary hash"
    blockers = []
    if not ps1.exists():
        blockers.append("avir_ps1_surface_missing_or_command_points_to_missing_script")
    if not parity_receipts:
        blockers.append("clean_room_avir_cli_parity_receipt_missing")
    if not implementation_files:
        blockers.append("avir_cli_source_inventory_missing")
    return {
        "status": "BLOCKED" if blockers else "PRESENT_BUT_NEEDS_RESIDENT_LOAD_BEARING_TEST",
        "avir_root": str(avir_root),
        "avir_root_exists": avir_root.exists(),
        "avir_exe": exe_info,
        "avir_ps1": {"path": str(ps1), "exists": ps1.exists()},
        "powershell_avir_command_definition": avir_command_definition,
        "candidate_cleanroom_receipts": [str(path) for path in parity_receipts[:20]],
        "src_inventory_sample": [str(path) for path in implementation_files if path.is_file()][:20],
        "blockers": blockers,
        "required_receipt": "clean-room avir-cli resident harness parity receipt with /goal-mode-equivalent action loop, deletion-sensitive harness action channel, and no copyright taint",
    }


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


def precondition_block(status: str, blockers: list[str], evidence: dict[str, Any], required_next: str) -> dict[str, Any]:
    return {
        "status": status,
        "blockers": blockers,
        "evidence": evidence,
        "required_next": required_next,
        "pass_condition": "actual implementation plus before/after, A/B/C/deleted, transfer, and deletion-sensitive evidence",
    }


def build_receipt(
    *,
    repo: Path,
    paper_root: Path,
    avir_root: Path,
    out: Path,
    avir_command_definition: str | None = None,
) -> dict[str, Any]:
    goal = inspect_goal(repo)
    train = inspect_train_multimodal(repo)
    floor_manifest, floor_summary = inspect_floor_contract(repo)
    papers, paper_errors = inspect_papers(paper_root)
    avir = inspect_avir_root(avir_root, avir_command_definition)

    rlm_read = any(row.get("kind") == "RLM" and row.get("source_receipt_read") for row in papers)
    igrpo_read = any(row.get("kind") == "iGRPO" and row.get("source_receipt_read") for row in papers)
    rlm_blockers = []
    igrpo_blockers = []
    if not rlm_read:
        rlm_blockers.append("rlm_paper_source_preflight_missing")
    rlm_blockers.extend(
        [
            "rlm_harness_native_recursive_policy_not_implemented",
            "rlm_neural_parameter_update_not_receipted",
            "rlm_deletion_sensitive_ablation_missing",
        ]
    )
    if not igrpo_read:
        igrpo_blockers.append("igrpo_paper_source_preflight_missing")
    igrpo_blockers.extend(
        [
            "igrpo_verifier_conditioned_training_organ_not_implemented",
            "igrpo_neural_parameter_update_not_receipted",
            "igrpo_ab_compare_deleted_transfer_missing",
        ]
    )

    preconditions = {
        "clean_room_avir_cli": precondition_block(
            "BLOCKED",
            list(avir["blockers"]) or ["clean_room_avir_cli_load_bearing_resident_evidence_missing"],
            avir,
            "implement clean-room avir-cli resident harness inventory/parity receipt",
        ),
        "rlm": precondition_block(
            "BLOCKED",
            rlm_blockers,
            {"paper_source_read": rlm_read, "mechanism_primitives": mechanism_primitives("RLM")},
            "adapt train_multimodal_v0.py into a trainable RLM recursive policy with neural state_dict delta",
        ),
        "igrpo": precondition_block(
            "BLOCKED",
            igrpo_blockers,
            {"paper_source_read": igrpo_read, "mechanism_primitives": mechanism_primitives("iGRPO")},
            "adapt train_multimodal_v0.py into a verifier-conditioned iGRPO update organ",
        ),
    }

    next_missing = "clean_room_avir_cli_resident_harness"
    next_command = (
        "python scripts\\ember_avir_cli_cleanroom_inventory.py --out "
        "receipts\\ember-preloop-resident-gate\\avir-cli-cleanroom-inventory-<timestamp>.json"
    )
    blockers = (
        ["goal_authority_incomplete"] if goal["status"] != "PRESENT" else []
    ) + paper_errors + list(avir["blockers"]) + rlm_blockers + igrpo_blockers

    return {
        "ticket": TICKET,
        "ts": ts(),
        "sha_convention": SHA_CONVENTION,
        "verdict": "PRELOOP_RESIDENT_GATE_BLOCKED",
        "gate_allows_loops": False,
        "out_path": str(out),
        "goal_authority": goal,
        "paper_sources_read": papers,
        "train_multimodal_inventory": train,
        "floor_contract_summary": floor_summary,
        "floor_contract_manifest": floor_manifest,
        "invalid_substitutions_rejected": INVALID_SUBSTITUTIONS,
        "preconditions": preconditions,
        "blocked_reasons": sorted(set(blockers)),
        "next_missing_precondition": next_missing,
        "next_executable_command": next_command,
        "kill_ablate_test_required": "deleting any of clean-room avir-cli resident harness, RLM organ, or iGRPO organ must block or degrade the gate",
        "classification": "precondition_inspector_only_not_resident_training_pass",
        "n_rows": len(floor_manifest) + len(papers) + 3,
    }


def write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(path), receipt)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--repo", default=str(repo_root()))
    parser.add_argument("--paper-root", default=str(DEFAULT_PAPER_ROOT))
    parser.add_argument("--avir-root", default=str(DEFAULT_AVIR_ROOT))
    args = parser.parse_args()

    out = Path(args.out)
    receipt = build_receipt(
        repo=Path(args.repo),
        paper_root=Path(args.paper_root),
        avir_root=Path(args.avir_root),
        out=out,
        avir_command_definition=get_powershell_avir_definition(),
    )
    write_receipt(out, receipt)
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["verdict"] == "PRELOOP_RESIDENT_GATE_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())


