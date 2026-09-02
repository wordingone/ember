#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Resident-training gate for Ember's non-killable RLM/iGRPO + the predecessor CLI precondition.

This runner is intentionally fail-closed. It can validate paper-source preflight,
clean-room harness evidence, and a candidate resident-training manifest. It must
emit BLOCKED, not PASS, unless the candidate supplies a real learned/update path,
matched A/B/C/deleted rows, and deletion-sensitive improvement.
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
# issue2015 exact-local-import:src/ember/governance/scripts/loop_econ_gate.py
import importlib.util as _ember_f7f7bf161a2ec86b_importlib
import sys as _ember_f7f7bf161a2ec86b_sys
from pathlib import Path as _ember_f7f7bf161a2ec86b_Path
_ember_f7f7bf161a2ec86b_path = _ember_f7f7bf161a2ec86b_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'loop_econ_gate.py')
if not _ember_f7f7bf161a2ec86b_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/loop_econ_gate.py')
_ember_f7f7bf161a2ec86b_aliases = ('_ember_issue2015_f7f7bf161a2ec86b', 'loop_econ_gate', 'scripts.loop_econ_gate')
_ember_f7f7bf161a2ec86b_existing = []
for _ember_f7f7bf161a2ec86b_alias in _ember_f7f7bf161a2ec86b_aliases:
    _ember_f7f7bf161a2ec86b_candidate = _ember_f7f7bf161a2ec86b_sys.modules.get(_ember_f7f7bf161a2ec86b_alias)
    if _ember_f7f7bf161a2ec86b_candidate is not None and all(_ember_f7f7bf161a2ec86b_candidate is not item for item in _ember_f7f7bf161a2ec86b_existing):
        _ember_f7f7bf161a2ec86b_existing.append(_ember_f7f7bf161a2ec86b_candidate)
if len(_ember_f7f7bf161a2ec86b_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/loop_econ_gate.py')
if _ember_f7f7bf161a2ec86b_existing:
    _ember_f7f7bf161a2ec86b_module = _ember_f7f7bf161a2ec86b_existing[0]
    _ember_f7f7bf161a2ec86b_observed = getattr(_ember_f7f7bf161a2ec86b_module, '__file__', None)
    if _ember_f7f7bf161a2ec86b_observed is None or _ember_f7f7bf161a2ec86b_Path(_ember_f7f7bf161a2ec86b_observed).resolve() != _ember_f7f7bf161a2ec86b_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/loop_econ_gate.py')
else:
    _ember_f7f7bf161a2ec86b_spec = _ember_f7f7bf161a2ec86b_importlib.spec_from_file_location('_ember_issue2015_f7f7bf161a2ec86b', _ember_f7f7bf161a2ec86b_path)
    if _ember_f7f7bf161a2ec86b_spec is None or _ember_f7f7bf161a2ec86b_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/loop_econ_gate.py')
    _ember_f7f7bf161a2ec86b_module = _ember_f7f7bf161a2ec86b_importlib.module_from_spec(_ember_f7f7bf161a2ec86b_spec)
    for _ember_f7f7bf161a2ec86b_alias in _ember_f7f7bf161a2ec86b_aliases:
        _ember_f7f7bf161a2ec86b_prior = _ember_f7f7bf161a2ec86b_sys.modules.get(_ember_f7f7bf161a2ec86b_alias)
        if _ember_f7f7bf161a2ec86b_prior is not None and _ember_f7f7bf161a2ec86b_prior is not _ember_f7f7bf161a2ec86b_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/loop_econ_gate.py')
        _ember_f7f7bf161a2ec86b_sys.modules[_ember_f7f7bf161a2ec86b_alias] = _ember_f7f7bf161a2ec86b_module
    try:
        _ember_f7f7bf161a2ec86b_spec.loader.exec_module(_ember_f7f7bf161a2ec86b_module)
    except BaseException:
        for _ember_f7f7bf161a2ec86b_alias in _ember_f7f7bf161a2ec86b_aliases:
            if _ember_f7f7bf161a2ec86b_sys.modules.get(_ember_f7f7bf161a2ec86b_alias) is _ember_f7f7bf161a2ec86b_module:
                _ember_f7f7bf161a2ec86b_sys.modules.pop(_ember_f7f7bf161a2ec86b_alias, None)
        raise
for _ember_f7f7bf161a2ec86b_alias in _ember_f7f7bf161a2ec86b_aliases:
    _ember_f7f7bf161a2ec86b_prior = _ember_f7f7bf161a2ec86b_sys.modules.get(_ember_f7f7bf161a2ec86b_alias)
    if _ember_f7f7bf161a2ec86b_prior is not None and _ember_f7f7bf161a2ec86b_prior is not _ember_f7f7bf161a2ec86b_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/loop_econ_gate.py')
    _ember_f7f7bf161a2ec86b_sys.modules[_ember_f7f7bf161a2ec86b_alias] = _ember_f7f7bf161a2ec86b_module
DT6_REQUIRED_FIELDS = getattr(_ember_f7f7bf161a2ec86b_module, 'REQUIRED_FIELDS')
check_econ_gate = getattr(_ember_f7f7bf161a2ec86b_module, 'check_econ_gate')
# issue2015 exact-local-import-end:src/ember/governance/scripts/loop_econ_gate.py

TICKET = "EMBER-RESIDENT-TRAINING-GATE"
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
REQUIRED_PAPERS = {"RLM", "iGRPO"}
SUPERSEDED_PARALLEL_SPECS = [
    Path("docs/domains/governance/archive/pre-restart/ember-mvp-v0.md"),
    Path("docs/archive/pre-restart/20260617-maximally-viable-product.md"),
]
def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(cwd), text=True, capture_output=True)


def _git_head(repo: Path) -> str | None:
    proc = _git(["rev-parse", "HEAD"], repo)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _git_tracked(repo: Path, path: Path) -> bool:
    rel = path.relative_to(repo) if path.is_absolute() else path
    proc = _git(["ls-files", "--error-unmatch", str(rel)], repo)
    return proc.returncode == 0


def _line_count(path: Path) -> int:
    if not path.exists() or not path.is_file():
        return 0
    return len(path.read_text(encoding="utf-8", errors="replace").splitlines())


def _classify_path(path: Path) -> str:
    norm = str(path).replace("\\", "/").lower()
    name = path.name.lower()
    if norm.startswith("scripts/") and name.endswith(".py"):
        if "selftest" in name or name.startswith("test_"):
            return "code_test"
        return "code"
    if norm.startswith("tests/") or "selftest" in name:
        return "code_test"
    if norm.startswith("docs/") or name.endswith(".md") or name.endswith(".json"):
        return "documentation_receipt_spec"
    return "other"


def code_vs_docs_metric(repo: Path, changed_paths: list[Path]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    totals = {
        "code_added_lines": 0,
        "code_test_added_lines": 0,
        "documentation_receipt_spec_added_lines": 0,
        "other_added_lines": 0,
    }
    for raw_path in changed_paths:
        path = raw_path if raw_path.is_absolute() else repo / raw_path
        try:
            rel = path.relative_to(repo)
        except ValueError:
            rel = path
        category = _classify_path(rel)
        added = 0
        deleted = 0
        if path.exists() and not _git_tracked(repo, path):
            added = _line_count(path)
        else:
            proc = _git(["diff", "--numstat", "HEAD", "--", str(rel)], repo)
            if proc.returncode == 0 and proc.stdout.strip():
                first = proc.stdout.strip().splitlines()[0].split("\t")
                if len(first) >= 2:
                    added = int(first[0]) if first[0].isdigit() else 0
                    deleted = int(first[1]) if first[1].isdigit() else 0
        if category == "code":
            totals["code_added_lines"] += added
        elif category == "code_test":
            totals["code_test_added_lines"] += added
        elif category == "documentation_receipt_spec":
            totals["documentation_receipt_spec_added_lines"] += added
        else:
            totals["other_added_lines"] += added
        rows.append({"path": str(rel), "category": category, "added_lines": added, "deleted_lines": deleted})
    return {"rows": rows, **totals}


def inspect_goal_authority(repo: Path) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    goal_path = repo / "docs/domains/governance/authority/GOAL.md"
    goal_markers = [
        "Authority And Precedence",
        "Current Blocker Packet",
        "resident_training_gate_status",
        "RLM, iGRPO, and the clean-room",
    ]
    if not goal_path.exists():
        errors.append("goal_authority.goal_missing")
        goal_text = ""
    else:
        goal_text = goal_path.read_text(encoding="utf-8", errors="replace")
        for marker in goal_markers:
            if marker not in goal_text:
                errors.append(f"goal_authority.goal_missing_marker.{marker}")

    superseded_rows: list[dict[str, Any]] = []
    for rel in SUPERSEDED_PARALLEL_SPECS:
        path = repo / rel
        if not path.exists():
            errors.append(f"goal_authority.{rel.as_posix()}.missing")
            superseded_rows.append({"path": rel.as_posix(), "status": "MISSING"})
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        head = text[:2000]
        markers_present = {
            "superseded": "SUPERSEDED" in head,
            "sole_active_goal": "docs/domains/governance/authority/GOAL.md is the sole active goal file" in head,
            "scope_not_reduced": "no scope is reduced" in head,
            "resident_gate": "resident_training_gate_status=PASS" in head,
        }
        status = "SUPERSEDED_STUB" if all(markers_present.values()) else "STALE_PARALLEL_SPEC"
        if status != "SUPERSEDED_STUB":
            errors.append(f"goal_authority.{rel.as_posix()}.stale_parallel_spec")
        superseded_rows.append(
            {
                "path": rel.as_posix(),
                "status": status,
                "sha256": _sha256(path),
                "markers_present": markers_present,
            }
        )

    return {
        "status": "PASS" if not errors else "BLOCKED",
        "goal_path": "docs/domains/governance/authority/GOAL.md",
        "goal_sha256": _sha256(goal_path) if goal_path.exists() else None,
        "required_goal_markers": goal_markers,
        "superseded_parallel_specs": superseded_rows,
        "one_goal_file_rule": "docs/domains/governance/authority/GOAL.md is the only active Ember goal/control document; superseded docs are imported history, not clearance surfaces.",
    }, errors

def _extract_abstract(abs_html_path: Path) -> str:
    text = abs_html_path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r'meta name="citation_abstract" content="(.*?)"', text, flags=re.S)
    if match:
        return html.unescape(match.group(1)).strip()
    match = re.search(r'<blockquote class="abstract mathjax">(.*?)</blockquote>', text, flags=re.S)
    if match:
        cleaned = re.sub(r"<.*?>", " ", match.group(1))
        return html.unescape(re.sub(r"\s+", " ", cleaned)).replace("Abstract:", "").strip()
    return ""


def _paper_mechanism(kind: str, abstract: str) -> dict[str, Any]:
    if kind == "RLM":
        primitives = [
            "treat long/large workspace context as an external environment",
            "programmatically inspect and decompose state into snippets",
            "recursively call the model over selected snippets",
            "aggregate sub-results into a final answer or action",
            "post-train around the recursive interface rather than only prompting it",
        ]
        local_map = {
            "environment": "workspace goals, receipts, harness state, task rows, and evaluator outputs",
            "recursive_call": "bounded native goal-organ subcalls over selected state snippets",
            "learned_part": "policy deciding what to inspect/decompose/call/aggregate",
            "forbidden_analogy": "ordinary Codex file reading or a hard-coded router is not RLM training",
        }
    elif kind == "iGRPO":
        primitives = [
            "sample multiple exploratory drafts under one task budget",
            "score drafts with the same scalar verifier/reward used for optimization",
            "select the highest-reward draft",
            "condition a second refinement stage on the selected draft",
            "apply a GRPO-style update on draft-conditioned refinements under matched rollout budget",
            "ablate against plain GRPO/fixed prompting to prove the wrapper is load-bearing",
        ]
        local_map = {
            "reward": "verifier score from heldout/evaluator rows and gate checks",
            "best_draft": "best attempted next-action or solution trace selected by verifier reward",
            "learned_part": "policy update from best-draft-conditioned refinements",
            "forbidden_analogy": "reranking, prompt repair, or historical GRPO receipts without a new update step do not satisfy iGRPO",
        }
    else:
        primitives = []
        local_map = {}
    return {
        "kind": kind,
        "abstract_sha256": hashlib.sha256(abstract.encode("utf-8")).hexdigest(),
        "mechanism_primitives": primitives,
        "local_ember_map": local_map,
        "assumptions_that_do_not_automatically_hold_locally": [
            "large-model benchmark gains transfer to Ember's resident scale",
            "paper tasks match Ember's harness/action setting",
            "prompted recursion equals learned resident policy",
            "reward availability implies safe/private heldout access",
        ],
    }


def load_paper_sources(index_path: Path) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    if not index_path.exists():
        return {"index_path": str(index_path), "papers": []}, ["paper_index.missing"]
    index = _load_json(index_path)
    paper_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for paper in index.get("papers", []):
        kind = str(paper.get("kind"))
        seen.add(kind)
        receipt_path = Path(str(paper.get("receipt", "")))
        if not receipt_path.exists():
            errors.append(f"paper.{kind}.receipt_missing")
            continue
        receipt = _load_json(receipt_path)
        files = receipt.get("files", {})
        row: dict[str, Any] = {
            "kind": kind,
            "title": receipt.get("title"),
            "arxiv_id": receipt.get("arxiv_id"),
            "receipt_path": str(receipt_path),
            "receipt_sha256": _sha256(receipt_path),
            "declared_pdf_sha256": paper.get("pdf_sha256"),
            "declared_source_sha256": paper.get("source_sha256"),
            "files": {},
        }
        for label in ("pdf", "source", "abs_html"):
            file_info = files.get(label, {}) if isinstance(files, dict) else {}
            file_path = Path(str(file_info.get("path", "")))
            if not file_path.exists():
                errors.append(f"paper.{kind}.{label}_missing")
                continue
            actual = _sha256(file_path)
            declared = str(file_info.get("sha256", ""))
            if actual != declared:
                errors.append(f"paper.{kind}.{label}_sha_mismatch")
            row["files"][label] = {
                "path": str(file_path),
                "sha256": actual,
                "bytes": file_path.stat().st_size,
            }
        abs_html = row["files"].get("abs_html", {}).get("path")
        abstract = _extract_abstract(Path(abs_html)) if abs_html else ""
        row["mechanism_extraction"] = _paper_mechanism(kind, abstract)
        if not abstract:
            errors.append(f"paper.{kind}.abstract_missing")
        paper_rows.append(row)
    missing = sorted(REQUIRED_PAPERS - seen)
    errors.extend(f"paper.{kind}.missing" for kind in missing)
    return {
        "index_path": str(index_path),
        "index_sha256": _sha256(index_path),
        "papers": paper_rows,
        "forced_goal_mode_rule": index.get("forced_goal_mode_rule"),
    }, errors


def inspect_clean_room_harness(repo: Path, full_parity_receipt: Path | None = None) -> tuple[dict[str, Any], list[str]]:
    required = [
        Path("docs/domains/governance/archive/pre-restart/sp5-nck-harness-port-spec-v0.md"),
        Path("docs/domains/governance/archive/pre-restart/nck-event-loop-v0.md"),
        Path("docs/domains/governance/archive/pre-restart/nck-invariants-v0.md"),
        Path("src/ember/governance/scripts/nck/event_loop.py"),
        Path("src/ember/governance/scripts/nck/invariants.py"),
        Path("scripts/nck/nck_e2e_proof.py"),
        Path("receipts/nck-e2e-proof-20260612T142318Z.json"),
    ]
    errors: list[str] = []
    files: list[dict[str, Any]] = []
    for rel in required:
        path = repo / rel
        if not path.exists():
            errors.append(f"clean_room_harness.{rel.as_posix()}.missing")
            continue
        files.append({"path": rel.as_posix(), "sha256": _sha256(path), "bytes": path.stat().st_size})
    e2e_path = repo / "receipts/nck-e2e-proof-20260612T142318Z.json"
    e2e_summary: dict[str, Any] = {"path": str(e2e_path)}
    if e2e_path.exists():
        e2e = _load_json(e2e_path)
        e2e_summary.update(
            {
                "ticket": e2e.get("ticket"),
                "all_stages_pass": e2e.get("all_stages_pass"),
                "chain": e2e.get("chain"),
                "identity": e2e.get("identity"),
            }
        )
        if e2e.get("ticket") != "NCK-E2E-PROOF" or e2e.get("all_stages_pass") is not True:
            errors.append("clean_room_harness.nck_e2e_not_pass")

    full_parity_summary: dict[str, Any] = {
        "path": str(full_parity_receipt) if full_parity_receipt else None,
        "exists": bool(full_parity_receipt and full_parity_receipt.exists()),
    }
    if full_parity_receipt is None or not full_parity_receipt.exists():
        errors.append("clean_room_harness.full_parity_receipt_missing")
    else:
        full_parity = _load_json(full_parity_receipt)
        surface_rows = full_parity.get("surface_matrix") if isinstance(full_parity.get("surface_matrix"), list) else []
        failed_surfaces = [row.get("surface_id") for row in surface_rows if row.get("status") != "PASS"]
        delete_ablate = full_parity.get("delete_ablate_required") if isinstance(full_parity.get("delete_ablate_required"), dict) else {}
        false_delete_ablate = [key for key, value in delete_ablate.items() if value is not True]
        real_observation = full_parity.get("real_reference_uiux_ax_observation_receipt") if isinstance(full_parity.get("real_reference_uiux_ax_observation_receipt"), dict) else {}
        full_parity_summary.update(
            {
                "sha256": _sha256(full_parity_receipt),
                "ticket": full_parity.get("ticket"),
                "verdict": full_parity.get("verdict"),
                "classification": full_parity.get("classification"),
                "headless_bootstrap_classification": full_parity.get("headless_bootstrap_classification"),
                "blocked_reasons": full_parity.get("blocked_reasons"),
                "n_rows": full_parity.get("n_rows"),
                "failed_surfaces": failed_surfaces,
                "false_delete_ablate": false_delete_ablate,
                "real_reference_uiux_ax_observation_receipt": real_observation,
            }
        )
        if full_parity.get("ticket") != "EMBER-GATE-FULL-PARITY-HARNESS":
            errors.append("clean_room_harness.full_parity_receipt_wrong_ticket")
        if full_parity.get("verdict") != "THE_PREDECESSOR_CLI_FULL_PARITY_HARNESS_GATE_PASS":
            errors.append("clean_room_harness.full_parity_receipt_not_pass")
        if full_parity.get("classification") != "FULL_PARITY_GATE_PASS":
            errors.append("clean_room_harness.full_parity_classification_not_pass")
        if full_parity.get("blocked_reasons") not in ([], None):
            errors.append("clean_room_harness.full_parity_blocked_reasons_present")
        if len(surface_rows) < 13 or failed_surfaces:
            errors.append("clean_room_harness.full_parity_surface_matrix_not_all_pass")
        if false_delete_ablate:
            errors.append("clean_room_harness.full_parity_deletion_sensitivity_not_all_true")
        if real_observation.get("verdict") != "REAL_PREDECESSOR_CLI_UIUX_AX_OBSERVATION_PASS":
            errors.append("clean_room_harness.real_reference_uiux_ax_observation_missing_or_not_pass")
        for key in ["observed_real_reference_binary", "observed_real_tui", "observed_agent_loop", "observed_uiux_ax", "resource_governed"]:
            if real_observation.get(key) is not True:
                errors.append(f"clean_room_harness.{key}_not_true")
    return {
        "status": "FULL_the predecessor CLI_PARITY_PASS" if not errors else "INCOMPLETE",
        "files": files,
        "nck_e2e_proof": e2e_summary,
        "full_the predecessor CLI_parity_receipt": full_parity_summary,
        "note": "Harness evidence is not a learned RLM/iGRPO resident-training organ by itself; full the predecessor CLI parity is a required substrate for that organ.",
    }, errors


REQUIRED_ACTION_LOG_PRIMITIVES = ["emit-token", "emit-scalar", "emit-pointer", "commit", "stop"]
REQUIRED_LAUNCH_FLOOR_KEYS = ["QAT", "Muon", "QK-norm", "governor", "multimodal_locks"]
REQUIRED_FLOOR_MANIFEST_KEYS = [
    "floor_contract.QAT",
    "floor_contract.Muon",
    "floor_contract.QK-norm",
    "floor_contract.governor",
    "floor_contract.multimodal_locks",
    "floor_contract.BitNet/1.58-bit",
    "floor_contract.SDEK/GDN",
    "floor_contract.MLA/KV",
    "floor_contract.iGRPO/GRPO",
    "floor_contract.FP8",
    "floor_contract.MoE",
    "floor_contract.DiffusionGemma",
    "floor_contract.trigger-gated_rows",
    "nc2_component_contract.QAT",
    "nc2_component_contract.turboquant",
    "nc2_component_contract.BitNet/1.58-bit",
    "nc2_component_contract.SubQ",
    "nc2_component_contract.MTP",
    "nc2_component_contract.SDEK",
    "nc2_component_contract.Chinese-lab_stack",
    "nc2_component_contract.Gemma_unified_multimodal",
]
REQUIRED_FLOOR_MANIFEST_FIELDS = [
    "source_file",
    "source_hash",
    "disposition",
    "launch_vehicle_impact",
    "trigger",
    "pilot",
    "kill_promote_condition",
    "evidence_path",
]
ALLOWED_FLOOR_DISPOSITIONS = {"used_now", "preserved_trigger_gated", "blocked_with_exact_adapter_surface"}
FORBIDDEN_FLOOR_DISPOSITION_WORDS = {"archival", "archived", "killed", "irrelevant", "later", "covered by fp16", "covered_by_fp16"}


_CONSERVATION_KEYS = (
    "minimum_new_network_parameters=3000000000",
    "destination_total_parameters=>27000000000",
    "required_native_capabilities=text,image,audio,reasoning,structured_tool_use",
    "borrowed_lineage=frozen_reference_only",
    "mechanism_erasure=forbidden",
)


def _parse_no_deferral_floor_contract(
    content: str, floor_path: Path, manifest: dict, errors: list[str]
):
    """Parse the current no-deferral contract shape (fail-closed).

    The rewritten docs/contracts/ember-floor-contract.md deliberately carries no
    deferral ledger ("No modality ... can be deferred out of the foundation
    model"), so a deferral table is not a missing section but a shape the
    doc forbids. What IS required, each with its own error code: the
    EMBER_CONSERVATION_V1 header with its five exact keys, the Birth floor
    bullet list, the Historical boundary and Rung admission sections, and
    the closing no-deferral clause. Manifest rows are the birth-floor
    bullets themselves: every one is used_now and non-deferrable.
    """
    if "EMBER_CONSERVATION_V1" not in content:
        errors.append("floor_contract.conservation_header_missing")
    else:
        for pair in _CONSERVATION_KEYS:
            if pair not in content:
                errors.append(
                    "floor_contract.conservation_key_missing:" + pair.split("=", 1)[0]
                )
    birth = re.search(
        r"## Birth floor.*?\n(.*?)(?=\n##|\Z)", content, re.DOTALL | re.IGNORECASE
    )
    if not birth:
        errors.append("floor_contract.birth_floor_section_missing")
    else:
        # Markdown hard-wraps bullets; join continuation lines onto their bullet.
        joined: list[str] = []
        for line in birth.group(1).splitlines():
            stripped = line.strip()
            if stripped.startswith("-"):
                joined.append(stripped.lstrip("-").strip())
            elif stripped and joined:
                joined[-1] += " " + stripped
        bullets = joined
        if len(bullets) < 8:
            errors.append("floor_contract.birth_floor_rows_missing")
        for bullet in bullets:
            slug = re.sub(r"[^a-z0-9]+", "_", bullet.lower()[:48]).strip("_")
            manifest[f"birth_floor.{slug}"] = {
                "source_file": "docs/contracts/ember-floor-contract.md",
                "source_sha256": _sha256(floor_path),
                "disposition": "used_now",
                "launch_vehicle_impact": bullet,
                "trigger": "model birth (non-deferrable floor)",
                "pilot": "EMBER-02 birth evidence",
                "kill_promote_condition": (
                    "non-deferrable; only a user-approved contract change may alter"
                ),
                "evidence_path": "docs/contracts/ember-floor-contract.md",
            }
    if "## Historical boundary" not in content:
        errors.append("floor_contract.historical_boundary_missing")
    if "## Rung admission" not in content:
        errors.append("floor_contract.rung_admission_missing")
    if "deferred out of the foundation model" not in content:
        errors.append("floor_contract.no_deferral_clause_missing")
    if not manifest:
        errors.append("floor_contract.no_rows_parsed")
        return None, errors
    return manifest, errors


def parse_floor_contract_manifest(
    floor_path: Path,
) -> tuple[dict[str, dict[str, str | None]] | None, list[str]]:
    """Parse floor-contract.md and build manifest from actual rows.

    Returns (manifest_dict, errors) where manifest_dict is keyed by row component name
    and contains {source_file, source_sha256, disposition, launch_vehicle_impact, trigger,
    pilot, kill_promote_condition, evidence_path}. Missing fields get UNDECLARED-IN-DOC.

    FAIL-CLOSED: returns (None, errors) if doc missing/unparseable/zero rows.
    """
    errors: list[str] = []

    if not floor_path.exists():
        errors.append("floor_contract.missing")
        return None, errors

    try:
        content = floor_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        errors.append(f"floor_contract.read_error: {str(e)}")
        return None, errors

    if not content.strip():
        errors.append("floor_contract.empty")
        return None, errors

    # Parse markdown tables: split by |, strip whitespace
    def parse_md_table(text: str) -> list[list[str]] | None:
        """Parse a markdown table and return rows (list of cell lists)."""
        lines = [line.strip() for line in text.split("\n") if line.strip().startswith("|")]
        if len(lines) < 3:  # need at least header, separator, one data row
            return None

        rows = []
        for line in lines:
            cells = [cell.strip() for cell in line.split("|")]
            cells = [c for c in cells if c]  # remove empty cells from | at start/end
            if cells:
                rows.append(cells)
        return rows if len(rows) >= 3 else None  # header, separator, data

    # Find "What v0 already carries" section and extract its table
    invehicle_match = re.search(
        r"## What v0 already carries.*?\n(.*?)(?=\n##|\Z)",
        content,
        re.DOTALL | re.IGNORECASE,
    )

    # Find "Deferral rows" section and extract its table
    deferral_match = re.search(
        r"## Deferral rows.*?\n(.*?)(?=\n##|\Z)",
        content,
        re.DOTALL | re.IGNORECASE,
    )

    manifest: dict[str, dict[str, str | None]] = {}

    # Parse in-vehicle components (floor components IN the launch vehicle)
    if invehicle_match:
        invehicle_section = invehicle_match.group(1)
        invehicle_rows = parse_md_table(invehicle_section)

        if invehicle_rows and len(invehicle_rows) >= 3:
            header = invehicle_rows[0]

            def find_col_idx(header: list[str], names: list[str]) -> int | None:
                for i, cell in enumerate(header):
                    if any(name.lower() in cell.lower() for name in names):
                        return i
                return None

            comp_idx = find_col_idx(header, ["Component"])
            surface_idx = find_col_idx(header, ["v0 surface", "surface"])
            evidence_idx = find_col_idx(header, ["Evidence"])

            data_rows = invehicle_rows[2:]
            for row in data_rows:
                if not row or all(not cell.strip() for cell in row):
                    continue

                component = row[comp_idx].strip() if comp_idx is not None and comp_idx < len(row) else None
                if not component:
                    continue

                surface = row[surface_idx].strip() if surface_idx is not None and surface_idx < len(row) else "UNDECLARED-IN-DOC"
                evidence = row[evidence_idx].strip() if evidence_idx is not None and evidence_idx < len(row) else "UNDECLARED-IN-DOC"

                manifest[component] = {
                    "source_file": "docs/contracts/ember-floor-contract.md",
                    "source_sha256": _sha256(floor_path),
                    "disposition": "used_now",  # IN-vehicle components are currently used
                    "launch_vehicle_impact": surface,
                    "trigger": "model construction and launch",
                    "pilot": evidence,
                    "kill_promote_condition": "cannot be silently removed",
                    "evidence_path": "docs/contracts/ember-floor-contract.md",
                }

    # Current contract shape (2026-07 rewrite): the doc explicitly declares
    # it contains no deferral ledger; requiring a deferral table would enforce
    # a shape the authoritative doc forbids (#1289).
    if "contains no deferral ledger" in content:
        return _parse_no_deferral_floor_contract(content, floor_path, manifest, errors)

    # Parse deferral rows (legacy table shape)
    if not deferral_match:
        errors.append("floor_contract.deferral_section_missing")
        if manifest:
            return manifest, errors
        return None, errors

    deferral_section = deferral_match.group(1)
    deferral_rows = parse_md_table(deferral_section)

    if not deferral_rows or len(deferral_rows) < 3:
        errors.append("floor_contract.deferral_rows_unparseable_or_empty")
        return (manifest, errors) if manifest else (None, errors)

    # Header row (first row)
    header = deferral_rows[0]

    # Expected columns: Component, Why deferred, Receipt-producing pilot, Revision trigger, Owner, Status, Kill/promote
    # Find column indices (case-insensitive)
    def find_col_idx(header: list[str], names: list[str]) -> int | None:
        for i, cell in enumerate(header):
            if any(name.lower() in cell.lower() for name in names):
                return i
        return None

    comp_idx = find_col_idx(header, ["Component"])
    why_idx = find_col_idx(header, ["Why deferred"])
    pilot_idx = find_col_idx(header, ["Receipt-producing pilot", "pilot"])
    trigger_idx = find_col_idx(header, ["Revision trigger", "trigger"])
    owner_idx = find_col_idx(header, ["Owner"])
    status_idx = find_col_idx(header, ["Status"])
    kill_idx = find_col_idx(header, ["Kill", "promote"])

    # Data rows (skip header and separator)
    data_rows = deferral_rows[2:]

    if not data_rows and not manifest:
        errors.append("floor_contract.deferral_rows_empty")
        return None, errors

    for row_idx, row in enumerate(data_rows):
        if not row or all(not cell.strip() for cell in row):
            continue  # skip empty rows

        component = row[comp_idx].strip() if comp_idx is not None and comp_idx < len(row) else None
        if not component:
            continue

        # Map table columns to manifest fields
        why_deferred = (
            row[why_idx].strip() if why_idx is not None and why_idx < len(row) else "UNDECLARED-IN-DOC"
        )
        pilot = row[pilot_idx].strip() if pilot_idx is not None and pilot_idx < len(row) else "UNDECLARED-IN-DOC"
        trigger = (
            row[trigger_idx].strip() if trigger_idx is not None and trigger_idx < len(row) else "UNDECLARED-IN-DOC"
        )
        status = row[status_idx].strip() if status_idx is not None and status_idx < len(row) else "UNDECLARED-IN-DOC"
        kill_promote = (
            row[kill_idx].strip() if kill_idx is not None and kill_idx < len(row) else "UNDECLARED-IN-DOC"
        )

        # Map status to disposition
        disposition = _map_status_to_disposition(status)

        manifest[component] = {
            "source_file": "docs/contracts/ember-floor-contract.md",
            "source_sha256": _sha256(floor_path),
            "disposition": disposition,
            "launch_vehicle_impact": why_deferred,
            "trigger": trigger,
            "pilot": pilot,
            "kill_promote_condition": kill_promote,
            "evidence_path": "docs/contracts/ember-floor-contract.md",
        }

    if not manifest:
        errors.append("floor_contract.deferral_rows_no_valid_rows")
        return None, errors

    return manifest, errors


def _map_status_to_disposition(status: str) -> str:
    """Map floor contract status to manifest disposition."""
    status_lower = status.lower()

    # RE-STAGED, ADOPT -> preserved_trigger_gated (has a trigger/pilot, will be executed)
    if any(x in status_lower for x in ["re-staged", "adopt", "pilot"]):
        return "preserved_trigger_gated"

    # SKIP-with-receipt, WATCHING -> preserved_trigger_gated (gated by condition)
    if any(x in status_lower for x in ["skip", "watching"]):
        return "preserved_trigger_gated"

    # Default for undeclared
    if status == "UNDECLARED-IN-DOC":
        return "UNDECLARED-IN-DOC"

    # Unknown status: return unmapped marker with verbatim value
    return f"UNMAPPED-STATUS:{status}"


def build_floor_contract_manifest(floor_sha: str | None, nc2_sha: str | None) -> dict[str, dict[str, str | None]]:
    def row(
        *,
        source_file: str,
        source_hash: str | None,
        disposition: str,
        impact: str,
        trigger: str,
        pilot: str,
        kill_promote: str,
        evidence_path: str,
    ) -> dict[str, str | None]:
        return {
            "source_file": source_file,
            "source_hash": source_hash,
            "disposition": disposition,
            "launch_vehicle_impact": impact,
            "trigger": trigger,
            "pilot": pilot,
            "kill_promote_condition": kill_promote,
            "evidence_path": evidence_path,
        }

    floor = "docs/contracts/ember-floor-contract.md"
    nc2 = "docs/contracts/nc2-own-technique-contract.md"
    return {
        "floor_contract.QAT": row(source_file=floor, source_hash=floor_sha, disposition="preserved_trigger_gated", impact="quantization-native launch floor preserved; tiny resident step does not clear it", trigger="launch vehicle QAT/int4 tail or deploy target requiring quantized form", pilot="QAT tail or governed low-bit pilot", kill_promote="only user-approved contract change or receipt-proved contradiction may demote", evidence_path=floor),
        "floor_contract.Muon": row(source_file=floor, source_hash=floor_sha, disposition="preserved_trigger_gated", impact="hidden-layer Muon floor preserved with AdamW fallback", trigger="owned-core training run using hidden 2D params", pilot="Muon hidden-layer optimizer run with AdamW fallback receipt", kill_promote="promote on same-scale efficiency; fallback only on receipt-backed null", evidence_path=floor),
        "floor_contract.QK-norm": row(source_file=floor, source_hash=floor_sha, disposition="used_now", impact="unretrofittable attention normalization remains in launch vehicle", trigger="model construction and train_multimodal adapter", pilot="train_multimodal resident adapter", kill_promote="cannot be silently removed; deletion requires receipt-backed degradation/contradiction", evidence_path="scripts/train_multimodal_v0.py"),
        "floor_contract.governor": row(source_file=floor, source_hash=floor_sha, disposition="preserved_trigger_gated", impact="residency budget remains binding for non-tiny runs", trigger="GPU or long-running resident loop", pilot="governed resident loop receipt", kill_promote="tighten-only unless user changes residency contract", evidence_path=floor),
        "floor_contract.multimodal_locks": row(source_file=floor, source_hash=floor_sha, disposition="used_now", impact="reserved IDs/soft-token/bidirectional span/2D RoPE remain launch constraints", trigger="multimodal adapter and future vision-text floor world", pilot="train_multimodal resident adapter plus multimodal floor probe", kill_promote="retrofit can fail, component remains floor until successor receipt", evidence_path="scripts/train_multimodal_v0.py"),
        "floor_contract.BitNet/1.58-bit": row(source_file=floor, source_hash=floor_sha, disposition="preserved_trigger_gated", impact="low-bit substrate remains immediate post-fp16 comparison", trigger="fp16 resident gate pass or CPU-residency/hardware escalation", pilot="tiny BitNet/1.58 comparison", kill_promote="not satisfied by fp16; promote/skip only by comparison receipt", evidence_path=floor),
        "floor_contract.SDEK/GDN": row(source_file=floor, source_hash=floor_sha, disposition="preserved_trigger_gated", impact="sleep consolidation/adaptation-control kernel remains required operating layer", trigger="sleep/consolidation threshold or GDN pilot window", pilot="340M GDN-hybrid or successor sleep receipt", kill_promote="kill only on null with named successor such as LoRA-sleep baseline", evidence_path=floor),
        "floor_contract.MLA/KV": row(source_file=floor, source_hash=floor_sha, disposition="preserved_trigger_gated", impact="inference memory/compression remains sampling-round lever", trigger="first owned-core sampling round or KV pressure", pilot="MLA retrofit probe", kill_promote="promote on verified-episodes/GPU-hour gain; skip only if sampler saturates GPU", evidence_path=floor),
        "floor_contract.iGRPO/GRPO": row(source_file=floor, source_hash=floor_sha, disposition="used_now", impact="verifier-conditioned resident policy update is the active gate", trigger="resident-training pre-loop gate", pilot="RLM/iGRPO harness-native resident gate", kill_promote="non-killable for this goal; symbolic proxy is not pass", evidence_path="scripts/ember_train_multimodal_resident_adapter.py"),
        "floor_contract.FP8": row(source_file=floor, source_hash=floor_sha, disposition="preserved_trigger_gated", impact="consumer FP8 stack evidence remains release-scan item", trigger="consumer-4090 FP8 evidence or torchao sm89 rowwise support", pilot="release-scan receipt", kill_promote="re-enter only on external hardware/library evidence", evidence_path=floor),
        "floor_contract.MoE": row(source_file=floor, source_hash=floor_sha, disposition="preserved_trigger_gated", impact="sparsity path stays gated by scale/hardware", trigger="multi-GPU or >=3B rung/local small-MoE evidence", pilot="scale/hardware receipt", kill_promote="re-enter on hardware escalation or local small-MoE win", evidence_path=floor),
        "floor_contract.DiffusionGemma": row(source_file=floor, source_hash=floor_sha, disposition="preserved_trigger_gated", impact="sampler/teacher-generator throughput bet remains trigger-gated", trigger="idle GPU window and W-code admission", pilot="MBPP floor probe DiffusionGemma vs autoregressive baseline", kill_promote="promote iff nonzero verify floor and F gain; kill on zero-verify floor", evidence_path=floor),
        "floor_contract.trigger-gated_rows": row(source_file=floor, source_hash=floor_sha, disposition="preserved_trigger_gated", impact="all deferred floor rows remain active obligations, not trashcans", trigger="row-specific revision trigger", pilot="row-specific receipt-producing pilot", kill_promote="row-specific kill/promote condition must be preserved", evidence_path=floor),
        "nc2_component_contract.QAT": row(source_file=nc2, source_hash=nc2_sha, disposition="preserved_trigger_gated", impact="quantized form remains owned-core component", trigger="NC2 owned-core training/export", pilot="QAT/int4 tail", kill_promote="fallback only by contract receipt", evidence_path=nc2),
        "nc2_component_contract.turboquant": row(source_file=nc2, source_hash=nc2_sha, disposition="preserved_trigger_gated", impact="KV/MLA compression family remains first-class", trigger="sampling or KV pressure", pilot="compression/runtime probe", kill_promote="only receipt-backed null with successor", evidence_path=nc2),
        "nc2_component_contract.BitNet/1.58-bit": row(source_file=nc2, source_hash=nc2_sha, disposition="preserved_trigger_gated", impact="from-scratch ternary route remains binding comparison", trigger="fp16 resident pass then tiny BitNet comparison", pilot="100-300M or tiny comparison depending gate stage", kill_promote="not killable by fp16 success; requires comparison receipt", evidence_path=nc2),
        "nc2_component_contract.SubQ": row(source_file=nc2, source_hash=nc2_sha, disposition="preserved_trigger_gated", impact="sparse/linear-hybrid attention remains long-context route", trigger="long-context world admission or GDN pilot", pilot="GDN-hybrid sparse/linear pilot", kill_promote="successor only with quality-cliff receipt", evidence_path=nc2),
        "nc2_component_contract.MTP": row(source_file=nc2, source_hash=nc2_sha, disposition="preserved_trigger_gated", impact="draft-head/speculation route remains training/sampler component", trigger="owned-core sampling or NC2 entry", pilot="MTP drafter-head pilot", kill_promote="only negative <=1B evidence with successor", evidence_path=nc2),
        "nc2_component_contract.SDEK": row(source_file=nc2, source_hash=nc2_sha, disposition="preserved_trigger_gated", impact="adaptation-control kernel remains operating layer", trigger="sleep/plasticity threshold or NC2 entry", pilot="SDEK/GDN consolidation pilot", kill_promote="cannot be archived without contradiction-level receipt", evidence_path=nc2),
        "nc2_component_contract.Chinese-lab_stack": row(source_file=nc2, source_hash=nc2_sha, disposition="preserved_trigger_gated", impact="Muon/FP8/MoE/GRPO stack remains itemized, not collapsed", trigger="per-tech release scan or scale entry", pilot="per-tech pilot/release receipt", kill_promote="mixed per item; no silent stack-level kill", evidence_path=nc2),
        "nc2_component_contract.Gemma_unified_multimodal": row(source_file=nc2, source_hash=nc2_sha, disposition="preserved_trigger_gated", impact="encoder-free multimodal architecture remains owned-core template", trigger="vision-text floor world or multimodal checkpoint eval", pilot="soft-token embedder retrofit/floor probe", kill_promote="retrofit may fail; architecture successor must be explicit", evidence_path=nc2),
    }


def _has_marker(text: str, needles: list[str]) -> bool:
    low = text.lower()
    return all(needle.lower() in low for needle in needles)


def _marker_status(text: str, groups: dict[str, list[str]]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for name, needles in groups.items():
        present = _has_marker(text, needles)
        rows[name] = {"status": "PRESENT" if present else "MISSING", "needles": needles}
    return rows


def inspect_floor_contracts(repo: Path) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    floor_path = repo / "docs/contracts/ember-floor-contract.md"
    nc2_path = repo / "docs/contracts/nc2-own-technique-contract.md"
    train_path = repo / "scripts/train_multimodal_v0.py"

    def read_required(path: Path, code: str) -> str:
        if not path.exists():
            errors.append(f"{code}.missing")
            return ""
        return path.read_text(encoding="utf-8", errors="replace")

    floor_text = read_required(floor_path, "floor_contract")
    nc2_text = read_required(nc2_path, "nc2_component_contract")
    train_text = read_required(train_path, "train_multimodal")

    # Parse floor contract manifest from actual doc (FAIL-CLOSED)
    parsed_manifest, parse_errors = parse_floor_contract_manifest(floor_path)
    errors.extend(parse_errors)
    nc2_present = nc2_path.exists()

    floor_rows = _marker_status(
        floor_text,
        {
            "min_parameters": ["3,000,000,000"],
            "clean_genesis": ["clean-genesis"],
            "native_modalities": ["native text, image, audio"],
            "structured_tool_use": ["structured tool use"],
            "sufficient_training": ["heldout capability"],
            "capacity_accounting": ["total, trainable, active"],
            "checkpoint_bound_evidence": ["checkpoint-bound"],
            "no_borrowed_signal": ["no borrowed learned"],
            "body_identity": ["displayed identity matches the loaded bytes"],
            "rung_binding": ["binds 7B, 15B,"],
            "historical_boundary": ["cannot be trained"],
            "rung_admission": ["preregisters"],
            "vea_prediction": ["Verified Expert Accretion"],
            "no_deferral": ["deferred out of the foundation model"],
        },
    )
    nc2_rows = _marker_status(
        nc2_text,
        {
            "unified_decoder": ["one owned decoder"],
            "no_published_backbone": ["backbone"],
            "sparse_capacity": ["task-level routing"],
            "upcycling_gates": ["transfer, persistence, non-regression"],
            "mechanism_portfolio": ["Conserved mechanism portfolio"],
            "low_bit_numerics": ["BitNet"],
            "subquadratic": ["sub-quadratic"],
            "scale_boundary": ["3,000,000,000"],
            "candidate_declaration": ["total, trainable, and active"],
        },
    )
    train_rows = _marker_status(
        train_text,
        {
            "action_log_writer": ["action_log.jsonl"],
            "optimizer_step": ["AdamW"],
            "selftest": ["selftest"],
            "smoke_or_live_training": ["smoke"],
            "state_dict_or_checkpoint": ["checkpoint"],
            "qk_norm": ["QK-norm"],
            "multimodal_soft_tokens": ["2D RoPE"],
        },
    )
    for scope, rows in (("floor_contract", floor_rows), ("nc2_component_contract", nc2_rows), ("train_multimodal", train_rows)):
        for name, row in rows.items():
            if row["status"] != "PRESENT":
                errors.append(f"{scope}.{name}.missing_marker")

    present_primitives = [primitive for primitive in REQUIRED_ACTION_LOG_PRIMITIVES if primitive in train_text]
    missing_primitives = [primitive for primitive in REQUIRED_ACTION_LOG_PRIMITIVES if primitive not in present_primitives]
    if missing_primitives:
        errors.append("train_multimodal.action_log_primitives.missing")

    return {
        "status": "PASS" if not errors else "BLOCKED",
        "floor_contract_path": "docs/contracts/ember-floor-contract.md",
        "floor_contract_sha256": _sha256(floor_path) if floor_path.exists() else None,
        "nc2_component_contract_path": "docs/contracts/nc2-own-technique-contract.md",
        "nc2_component_contract_sha256": _sha256(nc2_path) if nc2_path.exists() else None,
        "train_multimodal_path": "scripts/train_multimodal_v0.py",
        "train_multimodal_sha256": _sha256(train_path) if train_path.exists() else None,
        "launch_vehicle_floor_preservation_map": floor_rows,
        "nc2_component_rows": nc2_rows,
        "train_multimodal_rows": train_rows,
        "action_log_seam_evidence": {
            "source_path": "scripts/train_multimodal_v0.py",
            "required_primitives": REQUIRED_ACTION_LOG_PRIMITIVES,
            "present_primitives": present_primitives,
            "missing_primitives": missing_primitives,
        },
        "trigger_gated_rows": {
            key: floor_rows[key]
            for key in ("BitNet/1.58-bit", "SDEK/GDN", "MLA/KV", "iGRPO/GRPO", "FP8", "MoE", "DiffusionGemma")
            if key in floor_rows
        },
        "parsed_floor_contract_manifest": parsed_manifest,
        "nc2_component_contract_present": nc2_present,
        "floor_contract_manifest_parse_status": "PASS" if parsed_manifest and not parse_errors else "BLOCKED",
        "required_floor_contract_manifest": build_floor_contract_manifest(
            _sha256(floor_path) if floor_path.exists() else None,
            _sha256(nc2_path) if nc2_path.exists() else None,
        ),
    }, errors


def _candidate_ref(manifest_path: Path, value: Any) -> Path | None:
    if not value:
        return None
    p = Path(str(value))
    if not p.is_absolute():
        p = manifest_path.parent / p
    return p


def _extract_dt6_fields(manifest_path: Path | None, candidate: dict[str, Any] | None) -> dict[str, Any]:
    """Extracts the DT-6 loop-economics fields (docs/dt6-loop-economics-gate-
    amendment.md) from the resident-training receipt under evaluation -- the
    file at candidate['resident_training_receipt_path'], resolved relative to
    the candidate manifest. Returns only the fields actually present; a
    missing field is simply absent so check_econ_gate's own AC1 (missing-
    field) check fires naturally on the caller's {"verdict": "PASS", **fields}
    construction, rather than being re-implemented here."""
    if candidate is None or manifest_path is None:
        return {}
    receipt_ref = _candidate_ref(manifest_path, candidate.get("resident_training_receipt_path"))
    if receipt_ref is None or not receipt_ref.exists():
        return {}
    try:
        receipt = _load_json(receipt_ref)
    except Exception:
        return {}
    if not isinstance(receipt, dict):
        return {}
    return {field: receipt[field] for field in DT6_REQUIRED_FIELDS if field in receipt}


def _validate_candidate_manifest(path: Path | None, floor_contracts: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, list[str]]:
    if path is None:
        return None, ["candidate_manifest.missing"]
    if not path.exists():
        return None, ["candidate_manifest.path_missing"]
    candidate = _load_json(path)
    errors: list[str] = []
    required_true = [
        "uses_real_update_step",
        "uses_externally_sourced_task_rows",
        "matched_a_b_c_deleted",
        "c_beats_a_and_b",
        "deleted_degrades_or_blocks",
        "model_learned_policy",
        "clean_room_harness_action_channel",
        "native_goal_organ_present",
        "recursive_query_policy_present",
        "verifier_conditioned_update_present",
        "persistence_checked",
    ]
    for key in required_true:
        if candidate.get(key) is not True:
            errors.append(f"candidate.{key}.not_true")

    required_path_keys = [
        "policy_update_trace_path",
        "recursive_query_policy_path",
        "native_goal_organ_path",
        "harness_interface_path",
        "resident_training_receipt_path",
        "task_rows_path",
    ]
    for key in required_path_keys:
        ref = _candidate_ref(path, candidate.get(key))
        if ref is None:
            errors.append(f"candidate.{key}.missing")
            continue
        if not ref.exists():
            errors.append(f"candidate.{key}.path_missing")
            continue
        sha_key = key.replace("_path", "_sha256")
        declared = candidate.get(sha_key)
        if declared and str(declared).replace("sha256:", "") != _sha256(ref):
            errors.append(f"candidate.{key}.sha_mismatch")

    policy_trace_ref = _candidate_ref(path, candidate.get("policy_update_trace_path"))
    if policy_trace_ref and policy_trace_ref.exists():
        trace = _load_json(policy_trace_ref)
        if trace.get("verdict") != "POLICY_UPDATE_TRACE_READY":
            errors.append("candidate.policy_update_trace.verdict")
        if not trace.get("updates"):
            errors.append("candidate.policy_update_trace.updates_missing")
        if trace.get("selected_template") == "instruction_only":
            errors.append("candidate.policy_update_trace.no_recursive_policy_selected")

    receipt_ref = _candidate_ref(path, candidate.get("resident_training_receipt_path"))
    if receipt_ref and receipt_ref.exists():
        receipt = _load_json(receipt_ref)
        if receipt.get("verdict") != "RESIDENT_TRAINING_CANDIDATE_PASS":
            errors.append("candidate.resident_training_receipt.not_pass")

    source = candidate.get("external_task_source", {})
    if not isinstance(source, dict) or not source.get("source_url"):
        errors.append("candidate.external_task_source.source_url_missing")

    rows = candidate.get("per_task_rows")
    if not isinstance(rows, list) or not rows:
        errors.append("candidate.per_task_rows.missing")
    else:
        if not any(isinstance(row, dict) and row.get("split") == "heldout" for row in rows):
            errors.append("candidate.per_task_rows.heldout_missing")
        for idx, row in enumerate(rows):
            if not isinstance(row, dict):
                errors.append(f"candidate.per_task_rows.{idx}.not_object")
                continue
            if not row.get("task_id"):
                errors.append(f"candidate.per_task_rows.{idx}.task_id_missing")
            if row.get("source_row_idx") is None:
                errors.append(f"candidate.per_task_rows.{idx}.source_row_idx_missing")
            if row.get("split") != "heldout":
                errors.append(f"candidate.per_task_rows.{idx}.not_heldout")
            if row.get("c_score", 0) <= max(row.get("a_score", 0), row.get("b_score", 0)):
                errors.append(f"candidate.per_task_rows.{idx}.c_not_gt_controls")
            if row.get("deleted_score", row.get("c_score", 0)) >= row.get("c_score", 0):
                errors.append(f"candidate.per_task_rows.{idx}.deleted_not_degraded")

    for key in ("policy_update_trace", "recursive_query_policy_path", "native_goal_organ_path", "harness_interface_path"):
        value = candidate.get(key)
        if not value:
            errors.append(f"candidate.{key}.missing")
    if candidate.get("toy_or_simulated") is True or candidate.get("prompt_only") is True or candidate.get("hand_authored_patch") is True:
        errors.append("candidate.precondition_scaffold_only")

    model_id = candidate.get("trainable_neural_model_identity")
    if not model_id:
        errors.append("candidate.neural_update.model_identity_missing")
    try:
        param_count = int(candidate.get("trainable_parameter_count", 0))
    except (TypeError, ValueError):
        param_count = 0
    if param_count <= 0:
        errors.append("candidate.neural_update.trainable_parameter_count_missing")
    pre_hash = str(candidate.get("pre_neural_parameter_hash", ""))
    post_hash = str(candidate.get("post_neural_parameter_hash", ""))
    if not pre_hash or not post_hash or pre_hash == post_hash:
        errors.append("candidate.neural_update.parameter_delta_missing")
    train_command = str(candidate.get("verifier_conditioned_training_command", ""))
    if not train_command or "train_multimodal_v0.py" not in train_command:
        errors.append("candidate.neural_update.verifier_conditioned_training_command_missing")

    transfer_rows = candidate.get("transfer_rows")
    if not isinstance(transfer_rows, list) or not transfer_rows:
        errors.append("candidate.transfer_rows.missing")
    else:
        for idx, row in enumerate(transfer_rows):
            if not isinstance(row, dict):
                errors.append(f"candidate.transfer_rows.{idx}.not_object")
                continue
            if row.get("c_score", 0) <= row.get("b_score", 0):
                errors.append(f"candidate.transfer_rows.{idx}.c_not_gt_b")
            if row.get("deleted_score", row.get("c_score", 0)) >= row.get("c_score", 0):
                errors.append(f"candidate.transfer_rows.{idx}.deleted_not_degraded")

    symbolic = candidate.get("symbolic_substitution_check")
    if not isinstance(symbolic, dict) or symbolic.get("status") != "NEURAL_UPDATE_PRESENT":
        errors.append("candidate.symbolic_proxy_substitution")
    elif any(symbolic.get(flag) is True for flag in ("symbolic_template_policy", "prompt_only", "routing_only")):
        errors.append("candidate.symbolic_proxy_substitution")
    prompt_exclusion = candidate.get("prompt_only_routing_only_exclusion_result")
    if not isinstance(prompt_exclusion, dict) or prompt_exclusion.get("status") != "PASS":
        errors.append("candidate.prompt_only_routing_only_exclusion.missing")
    elif prompt_exclusion.get("prompt_only") is True or prompt_exclusion.get("routing_only") is True:
        errors.append("candidate.prompt_only_routing_only_exclusion.failed")

    floor_contracts = floor_contracts or {}
    decision = candidate.get("train_multimodal_integration_decision")
    if not isinstance(decision, dict):
        errors.append("candidate.train_multimodal_adapter.decision_missing")
    else:
        if decision.get("status") not in {"ADAPTER_IMPLEMENTED", "ADAPT_DIRECTLY"}:
            errors.append("candidate.train_multimodal_adapter.not_integrated")
        if decision.get("source_path") != "scripts/train_multimodal_v0.py":
            errors.append("candidate.train_multimodal_adapter.source_path_mismatch")
        expected_train_sha = floor_contracts.get("train_multimodal_sha256")
        if expected_train_sha and decision.get("source_sha256") != expected_train_sha:
            errors.append("candidate.train_multimodal_adapter.source_sha_mismatch")
    adapter_ref = _candidate_ref(path, candidate.get("train_multimodal_adapter_path"))
    if adapter_ref is None or not adapter_ref.exists():
        errors.append("candidate.train_multimodal_adapter.path_missing")

    expected_floor_sha = floor_contracts.get("floor_contract_sha256")
    expected_nc2_sha = floor_contracts.get("nc2_component_contract_sha256")
    if expected_floor_sha and candidate.get("floor_contract_sha256") != expected_floor_sha:
        errors.append("candidate.floor_contract_hash.mismatch")
    if expected_nc2_sha and candidate.get("nc2_component_contract_sha256") != expected_nc2_sha:
        errors.append("candidate.nc2_component_contract_hash.mismatch")

    action_log = candidate.get("action_log_seam_evidence")
    if not isinstance(action_log, dict):
        errors.append("candidate.action_log_seam_evidence.missing")
    else:
        present = set(action_log.get("present_primitives") or [])
        missing = [primitive for primitive in REQUIRED_ACTION_LOG_PRIMITIVES if primitive not in present]
        if missing:
            errors.append("candidate.action_log_seam_evidence.primitives_missing")

    preservation = candidate.get("launch_vehicle_floor_preservation_map")
    if not isinstance(preservation, dict):
        errors.append("candidate.launch_vehicle_floor_preservation_map.missing")
    else:
        for key in REQUIRED_LAUNCH_FLOOR_KEYS:
            value = preservation.get(key)
            if value is None or str(value).lower() in {"missing", "archived", "killed", "skipped", "ignored"}:
                errors.append(f"candidate.launch_vehicle_floor_preservation_map.{key}.missing")

    floor_manifest = candidate.get("floor_contract_manifest")
    expected_floor_manifest = floor_contracts.get("required_floor_contract_manifest", {}) if isinstance(floor_contracts, dict) else {}
    if not isinstance(floor_manifest, dict):
        errors.append("candidate.floor_contract_manifest.missing")
    else:
        for key in REQUIRED_FLOOR_MANIFEST_KEYS:
            row = floor_manifest.get(key)
            expected = expected_floor_manifest.get(key, {})
            if not isinstance(row, dict):
                errors.append(f"candidate.floor_contract_manifest.{key}.missing")
                continue
            for field in REQUIRED_FLOOR_MANIFEST_FIELDS:
                if row.get(field) in (None, ""):
                    errors.append(f"candidate.floor_contract_manifest.{key}.{field}.missing")
            disposition = str(row.get("disposition", "")).lower()
            if disposition not in ALLOWED_FLOOR_DISPOSITIONS:
                errors.append(f"candidate.floor_contract_manifest.{key}.disposition_invalid")
            if any(word in disposition for word in FORBIDDEN_FLOOR_DISPOSITION_WORDS):
                errors.append(f"candidate.floor_contract_manifest.{key}.forbidden_escape_word")
            if expected.get("source_file") and row.get("source_file") != expected.get("source_file"):
                errors.append(f"candidate.floor_contract_manifest.{key}.source_file_mismatch")
            if expected.get("source_hash") and row.get("source_hash") != expected.get("source_hash"):
                errors.append(f"candidate.floor_contract_manifest.{key}.source_hash_mismatch")
    return candidate, errors

def build_gate_receipt(
    repo: Path,
    paper_index: Path,
    out_path: Path | None,
    candidate_manifest: Path | None,
    changed_paths: list[Path],
    full_parity_receipt: Path | None = None,
) -> dict[str, Any]:
    goal_path = repo / "docs/domains/governance/authority/GOAL.md"
    debt_path = repo / "docs/domains/governance/ledgers/ember-debt-ledger.md"
    errors: list[str] = []
    if not goal_path.exists():
        errors.append("goal_source.missing")
    if not debt_path.exists():
        errors.append("debt_ledger.missing")

    goal_authority, goal_authority_errors = inspect_goal_authority(repo)
    errors.extend(goal_authority_errors)
    paper_sources, paper_errors = load_paper_sources(paper_index)
    errors.extend(paper_errors)
    harness, harness_errors = inspect_clean_room_harness(repo, full_parity_receipt)
    errors.extend(harness_errors)
    floor_contracts, floor_errors = inspect_floor_contracts(repo)
    errors.extend(floor_errors)
    candidate, candidate_errors = _validate_candidate_manifest(candidate_manifest, floor_contracts)
    errors.extend(candidate_errors)

    # DT-6 loop-economics conjunct (docs/domains/governance/archive/pre-restart/dt6-loop-economics-gate-amendment.md,
    # gh #128): check_econ_gate is invoked unconditionally here -- never only
    # inside an `if status == "PASS"` branch -- so a PASS with the econ leg
    # unevaluated is impossible by construction. A missing candidate or
    # missing DT-6 fields both resolve to an empty dt6_fields dict, which
    # check_econ_gate itself rejects by name (AC1); nothing here forces a
    # pending-pass.
    dt6_fields = _extract_dt6_fields(candidate_manifest, candidate)
    econ_gate_verdict = check_econ_gate({"verdict": "PASS", **dt6_fields})
    if econ_gate_verdict["decision"] != "ACCEPT":
        errors.append(
            f"loop_econ_gate.{econ_gate_verdict.get('ac') or 'NONE'}: {econ_gate_verdict['reason']}"
        )

    source_truth = {
        "repo": str(repo),
        "git_head": _git_head(repo),
        "goal_path": str(goal_path),
        "goal_source_sha256": _sha256(goal_path) if goal_path.exists() else None,
        "debt_ledger_path": str(debt_path),
        "debt_ledger_sha256": _sha256(debt_path) if debt_path.exists() else None,
        "repo_sync_status": "LOCAL_GOAL_PRESENT_AND_HASHED" if goal_path.exists() else "INVALID_GOAL_SOURCE_SPLIT",
        "goal_authority": goal_authority,
    }

    component_status = {
        "goal_authority_and_superseded_specs": "PASS" if not goal_authority_errors else "BLOCKED",
        "paper_source_preflight": "PASS" if not paper_errors else "BLOCKED",
        "clean_room_harness_interface": "PASS" if not harness_errors else "BLOCKED",
        "train_multimodal_floor_contract": "PASS" if not floor_errors else "BLOCKED",
        "candidate_resident_training_manifest": "PASS" if candidate and not candidate_errors else "BLOCKED",
        "native_goal_organ": "PASS" if candidate and candidate.get("native_goal_organ_present") is True else "BLOCKED",
        "recursive_query_policy": "PASS" if candidate and candidate.get("recursive_query_policy_present") is True else "BLOCKED",
        "verifier_conditioned_update": "PASS" if candidate and candidate.get("verifier_conditioned_update_present") is True else "BLOCKED",
        "neural_parameter_update": "PASS" if candidate and not any(e.startswith("candidate.neural_update") or e == "candidate.symbolic_proxy_substitution" for e in candidate_errors) else "BLOCKED",
        "train_multimodal_adapter": "PASS" if candidate and not any(e.startswith("candidate.train_multimodal_adapter") for e in candidate_errors) else "BLOCKED",
        "floor_contract_accounting": "PASS" if candidate and not any(e.startswith("candidate.floor_contract") or e.startswith("candidate.nc2_component_contract") or e.startswith("candidate.action_log") or e.startswith("candidate.launch_vehicle_floor") for e in candidate_errors) else "BLOCKED",
        "a_b_c_deleted_evaluator": "PASS" if candidate and candidate.get("matched_a_b_c_deleted") is True else "BLOCKED",
        "deletion_sensitive_improvement": "PASS" if candidate and candidate.get("deleted_degrades_or_blocks") is True else "BLOCKED",
        "loop_econ_gate": "PASS" if econ_gate_verdict["decision"] == "ACCEPT" else "BLOCKED",
    }
    status = "PASS" if not errors and all(v == "PASS" for v in component_status.values()) else "BLOCKED"
    invalid_codes = []
    if "candidate.precondition_scaffold_only" in errors:
        invalid_codes.append("precondition_scaffold_only")
    if paper_errors:
        invalid_codes.append("invalid_unread_rlm_igrpo_source" if any("missing" in e for e in paper_errors) else "paper_source_integrity_error")
    if any(e.startswith("goal_authority") or e.startswith("goal_source") for e in errors):
        invalid_codes.append("invalid_goal_source_split")
    if floor_errors:
        invalid_codes.append("invalid_floor_contract_bypass")
    if harness_errors:
        invalid_codes.append("invalid_clean_room_harness_incomplete")
        if any("real_reference_uiux_ax_observation" in e for e in harness_errors):
            invalid_codes.append("real_reference_uiux_ax_observation_missing")
    if candidate is None:
        invalid_codes.append("resident_training_candidate_missing")
    elif candidate_errors:
        invalid_codes.append("resident_training_candidate_incomplete")
        if any(e.startswith("candidate.neural_update") or e == "candidate.symbolic_proxy_substitution" for e in candidate_errors):
            invalid_codes.append("symbolic_proxy_substitution")
        if any(e.startswith("candidate.train_multimodal_adapter") or e.startswith("candidate.floor_contract") or e.startswith("candidate.nc2_component_contract") or e.startswith("candidate.action_log") or e.startswith("candidate.launch_vehicle_floor") for e in candidate_errors):
            invalid_codes.append("invalid_floor_contract_bypass")
    if econ_gate_verdict["decision"] != "ACCEPT":
        invalid_codes.append("loop_econ_gate_not_accept")

    next_blocker = "resident_training_gate_passed" if status == "PASS" else _next_blocker(errors)
    receipt = {
        "ticket": TICKET,
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "sha_convention": SHA_CONVENTION,
        "source_truth": source_truth,
        "paper_sources": paper_sources,
        "mechanism_to_implementation_map": {
            paper["kind"]: paper.get("mechanism_extraction", {})
            for paper in paper_sources.get("papers", [])
        },
        "clean_room_harness_identity": harness,
        "train_multimodal_floor_contract": floor_contracts,
        "resident_training_candidate_manifest_path": str(candidate_manifest) if candidate_manifest else None,
        "resident_training_candidate": candidate,
        "loop_economics_gate_verdict": econ_gate_verdict,
        "a_b_c_deleted_contract": {
            "A": "same task/evaluator/harness envelope with no native goal organ and no resident-training update",
            "B": "clean-room harness plus fixed hand-authored or prompt/rule policy, but no learned RLM/iGRPO update",
            "C": "same harness with model-learned RLM/iGRPO update that changes later action selection or task performance",
            "Deleted": "C with native organ, recursive-query policy, verifier-conditioned update, or harness action channel removed",
            "pass_rule": "C beats A and B; Deleted degrades or blocks; budgets/evaluator/data/seeds matched; per-row scores present",
        },
        "component_status": component_status,
        "errors": errors,
        "invalid_codes": sorted(set(invalid_codes)),
        "next_blocker": next_blocker,
        "next_command_if_blocked": _next_command(next_blocker, out_path),
        "code_vs_docs_metric": code_vs_docs_metric(repo, changed_paths),
        "resident_training_gate_status": status,
        "verdict": f"RESIDENT_TRAINING_GATE_{status}",
    }
    return receipt


def _next_blocker(errors: list[str]) -> str:
    priority = [
        ("paper", "paper mechanism extraction or source integrity"),
        ("loop_econ_gate", "loop-economics gate (DT-6 fields / check_econ_gate)"),
        ("floor_contract", "floor-contract ledger and launch-vehicle preservation evidence"),
        ("nc2_component_contract", "NC2 component-contract evidence"),
        ("train_multimodal", "train_multimodal_v0.py adapter/infrastructure evidence"),
        ("candidate.neural_update", "actual neural parameter update evidence"),
        ("candidate.symbolic_proxy_substitution", "symbolic proxy substitution must be replaced with neural update"),
        ("candidate.train_multimodal_adapter", "train_multimodal_v0.py resident adapter implementation"),
        ("candidate.floor_contract", "floor-contract hash/accounting"),
        ("candidate.nc2_component_contract", "NC2 component-contract hash/accounting"),
        ("candidate.action_log", "section-6 action-log seam evidence"),
        ("candidate.launch_vehicle_floor", "launch-vehicle floor preservation map"),
        ("clean_room_harness", "clean-room harness parity/evidence"),
        ("candidate.native_goal_organ", "native goal organ implementation"),
        ("candidate.recursive_query_policy", "recursive-query policy implementation"),
        ("candidate.verifier_conditioned_update", "verifier-conditioned update step"),
        ("candidate.matched_a_b_c_deleted", "A/B/C/deleted evaluator"),
        ("candidate.deleted_degrades", "deletion-sensitive improvement"),
        ("candidate", "resident-training candidate manifest and implementation"),
    ]
    for prefix, label in priority:
        if any(e.startswith(prefix) for e in errors):
            return label
    return "resident-training gate unknown blocker"


def _next_command(next_blocker: str, out_path: Path | None) -> str:
    out = str(out_path) if out_path else r"receipts\ember-resident-training-gate\<timestamp>.json"
    base = "python scripts\\ember_resident_training_gate.py --out " + out
    if (
        "candidate manifest" in next_blocker
        or "native goal" in next_blocker
        or "recursive-query" in next_blocker
        or "verifier-conditioned" in next_blocker
        or "neural parameter" in next_blocker
        or "train_multimodal" in next_blocker
        or "floor-contract" in next_blocker
        or "NC2" in next_blocker
        or "action-log" in next_blocker
        or "launch-vehicle" in next_blocker
    ):
        return base + " --candidate-manifest <resident-training-candidate.json>"
    return base


def write_gate_receipt(out_path: Path, receipt: dict[str, Any]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out_path), receipt)


def build_fixture_repo(root: Path) -> tuple[Path, Path, Path]:
    """Builds the hermetic fixture repo (docs/domains/governance/authority/GOAL.md, floor contracts, clean-room
    harness files, papers index, full-parity receipt) under root. Shared by
    selftest() and test_ember_resident_training_gate_econ.py so both exercise
    the real build_gate_receipt() codepath against one fixture definition
    instead of two. Returns (repo, papers_index_path, full_parity_receipt_path)."""
    repo = root / "repo"
    repo.mkdir()
    (repo / "docs").mkdir()
    (repo / "scripts" / "nck").mkdir(parents=True)
    (repo / "receipts").mkdir()
    for rel, content in {
        "docs/domains/governance/authority/GOAL.md": (
            "Authority And Precedence\nCurrent Blocker Packet\nresident_training_gate_status\n"
            "RLM, iGRPO, and the clean-room\nBinding floor-contract surfaces imported into this goal\n"
            "Existing neural infrastructure is not missing: `scripts/train_multimodal_v0.py`\n"
        ),
        "docs/domains/governance/ledgers/ember-debt-ledger.md": "ledger\n",
        "docs/contracts/ember-floor-contract.md": (
            "<!-- EMBER_CONSERVATION_V1\n"
            "minimum_new_network_parameters=3000000000\n"
            "destination_total_parameters=>27000000000\n"
            "required_native_capabilities=text,image,audio,reasoning,structured_tool_use\n"
            "borrowed_lineage=frozen_reference_only\n"
            "mechanism_erasure=forbidden\n"
            "-->\n\n"
            "# Ember model-birth and rung floor (fixture mirror)\n\n"
            "This file is subordinate to docs/domains/governance/authority/GOAL.md. It contains no deferral ledger and no\n"
            "smaller launch vehicle.\n\n"
            "## Birth floor\n\n"
            "- at least 3,000,000,000 total unique stored neural parameters;\n"
            "- clean-genesis architecture, data, tokenizer, update, and checkpoint lineage;\n"
            "- sufficient training demonstrated by heldout capability, not a smoke run;\n"
            "- native text, image, audio, reasoning, and structured tool use in one decoder;\n"
            "- exact total, trainable, active, and trained-capacity accounting;\n"
            "- checkpoint-bound reasoning and modality evidence;\n"
            "- no borrowed learned or evaluative signal; and\n"
            "- a working body path whose displayed identity matches the loaded bytes.\n\n"
            "The same floor, without regression or capability deferral, binds 7B, 15B, and\n"
            ">27B rungs.\n\n"
            "## Historical boundary\n\n"
            "Historical artifacts cannot be trained, grown, evaluated, served, or promoted.\n\n"
            "## Rung admission\n\n"
            "Each rung preregisters equal-token/FLOP dense restart controls and a\n"
            "falsifiable Verified Expert Accretion prediction.\n\n"
            "No modality, mechanism family, benchmark obligation, or whole-stack requirement\n"
            "can be deferred out of the foundation model.\n"
        ),
        "docs/domains/governance/archive/pre-restart/ember-mvp-v0.md": "# SUPERSEDED fixture\n\ndocs/domains/governance/authority/GOAL.md is the sole active goal file; no scope is reduced; resident_training_gate_status=PASS required.\n",
        "docs/archive/pre-restart/20260617-maximally-viable-product.md": "# SUPERSEDED fixture\n\ndocs/domains/governance/authority/GOAL.md is the sole active goal file; no scope is reduced; resident_training_gate_status=PASS required.\n",
        "docs/domains/governance/archive/pre-restart/sp5-nck-harness-port-spec-v0.md": "clean-room spec\n",
        "docs/domains/governance/archive/pre-restart/nck-event-loop-v0.md": "event loop\n",
        "docs/domains/governance/archive/pre-restart/nck-invariants-v0.md": "invariants\n",
        "docs/contracts/nc2-own-technique-contract.md": (
            "# Owned architecture and mechanism research contract (fixture mirror)\n\n"
            "## Unified decoder contract\n\n"
            "Every admissible model rung uses one owned decoder. No published family can\n"
            "be Ember's backbone.\n\n"
            "## Sparse differentiated capacity\n\n"
            "A shared core with independently trainable expert banks and task-level routing;\n"
            "promoted only after transfer, persistence, non-regression, and deletion tests.\n\n"
            "## Conserved mechanism portfolio\n\n"
            "BitNet-style numerics; sub-quadratic attention and state, MTP, SDEK/adaptation\n"
            "control.\n\n"
            "## Scale and experiment boundary\n\n"
            "No candidate below 3,000,000,000 total parameters. Every executable candidate\n"
            "declares total, trainable, and active parameters.\n"
        ),
        "scripts/train_multimodal_v0.py": (
            "section 6 primitive-typed action-log contract\n"
            "action_log.jsonl\nemit-token\nemit-scalar\nemit-pointer\ncommit\nstop\n"
            "AdamW optimizer\nselftest\nsmoke/live training paths\ncheckpoint/state_dict\n"
            "QK-norm\n2D RoPE\nreserved vocab\nsoft-token\nbidirectional span\n"
        ),
        "src/ember/governance/scripts/nck/event_loop.py": "# event\n",
        "src/ember/governance/scripts/nck/invariants.py": "# inv\n",
        "scripts/nck/nck_e2e_proof.py": "# proof\n",
    }.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    (repo / "receipts/nck-e2e-proof-20260612T142318Z.json").write_text(
        json.dumps({"ticket": "NCK-E2E-PROOF", "all_stages_pass": True, "chain": ["boot_checksum"], "identity": "ember"}),
        encoding="utf-8",
    )
    papers = root / "papers"
    (papers / "rlm").mkdir(parents=True)
    (papers / "igrpo").mkdir()
    paper_entries = []
    for kind, slug, abstract in [
        ("RLM", "rlm", "Recursive Language Models inspect decompose recursively call itself over snippets."),
        ("iGRPO", "igrpo", "iGRPO samples drafts selects highest reward and applies GRPO-style update on refinements."),
    ]:
        d = papers / slug
        pdf = d / f"{slug}.pdf"
        src = d / f"{slug}.tar"
        abs_html = d / f"{slug}.html"
        pdf.write_text("pdf", encoding="utf-8")
        src.write_text("src", encoding="utf-8")
        abs_html.write_text(f'<meta name="citation_abstract" content="{abstract}" />', encoding="utf-8")
        receipt = {
            "kind": kind,
            "title": kind,
            "arxiv_id": "fixture",
            "files": {
                "pdf": {"path": str(pdf), "sha256": _sha256(pdf), "bytes": pdf.stat().st_size},
                "source": {"path": str(src), "sha256": _sha256(src), "bytes": src.stat().st_size},
                "abs_html": {"path": str(abs_html), "sha256": _sha256(abs_html), "bytes": abs_html.stat().st_size},
            },
        }
        receipt_path = d / "source-receipt.json"
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        paper_entries.append({"kind": kind, "title": kind, "arxiv_id": "fixture", "receipt": str(receipt_path), "pdf_sha256": _sha256(pdf), "source_sha256": _sha256(src)})
    index = papers / "INDEX.json"
    index.write_text(json.dumps({"papers": paper_entries}), encoding="utf-8-sig")

    full_parity_surface_ids = [
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
        "cleanroom_legal_boundary",
    ]
    full_parity_path = root / "full-parity.json"
    full_parity_path.write_text(
        json.dumps(
            {
                "ticket": "EMBER-GATE-FULL-PARITY-HARNESS",
                "ts": "20260621T000000Z",
                "sha_convention": SHA_CONVENTION,
                "verdict": "THE_PREDECESSOR_CLI_FULL_PARITY_HARNESS_GATE_PASS",
                "classification": "FULL_PARITY_GATE_PASS",
                "headless_bootstrap_classification": "SUPERSEDED_BY_FULL_CLEANROOM_PARITY_RECEIPTS",
                "blocked_reasons": [],
                "n_rows": len(full_parity_surface_ids),
                "surface_matrix": [{"surface_id": sid, "status": "PASS"} for sid in full_parity_surface_ids],
                "delete_ablate_required": {"native_goal_organ_deleted_blocks": True, "receipt_store_deleted_blocks": True},
                "real_reference_uiux_ax_observation_receipt": {
                    "ticket": "EMBER-REAL-PREDECESSOR-CLI-UIUX-AX-OBSERVATION",
                    "verdict": "REAL_PREDECESSOR_CLI_UIUX_AX_OBSERVATION_PASS",
                    "observed_real_reference_binary": True,
                    "observed_real_tui": True,
                    "observed_agent_loop": True,
                    "observed_uiux_ax": True,
                    "resource_governed": True,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return repo, index, full_parity_path


def build_symbolic_candidate_base(root: Path) -> dict[str, Any]:
    """The pre-neural-update candidate shape: passes A/B/C/deleted and all the
    process-evidence checks but carries no real trainable-parameter delta yet.
    Used both as the symbolic_proxy_substitution BLOCKED fixture and as the
    base that build_valid_candidate_manifest extends into a real candidate."""
    return {
        "uses_real_update_step": True,
        "uses_externally_sourced_task_rows": True,
        "matched_a_b_c_deleted": True,
        "c_beats_a_and_b": True,
        "deleted_degrades_or_blocks": True,
        "model_learned_policy": True,
        "clean_room_harness_action_channel": True,
        "native_goal_organ_present": True,
        "recursive_query_policy_present": True,
        "verifier_conditioned_update_present": True,
        "persistence_checked": True,
        "external_task_source": {"source_url": "https://example.invalid/fixture"},
        "policy_update_trace": str(root / "trace.json"),
        "policy_update_trace_path": str(root / "trace.json"),
        "recursive_query_policy_path": "policy.py",
        "native_goal_organ_path": "goal.py",
        "harness_interface_path": "harness.py",
        "resident_training_receipt_path": str(root / "receipt.json"),
        "task_rows_path": str(root / "tasks.json"),
        "per_task_rows": [{"task_id": "t1", "source_row_idx": 0, "split": "heldout", "a_score": 0, "b_score": 0, "c_score": 1, "deleted_score": 0}],
    }


def build_valid_candidate_manifest(root: Path, repo: Path, dt6_fields: dict[str, Any] | None = None) -> dict[str, Any]:
    """Writes the fixture artifacts (trace/policy/goal/harness/receipt/tasks/
    adapter) under root and returns the fully-valid candidate dict that clears
    every component_status check except, optionally, the loop-economics gate.
    `dt6_fields` (signal_per_gpu_hour / equal_wallclock_band / exceeds_band),
    if given, is merged onto receipt.json -- the resident-training receipt
    _extract_dt6_fields reads from -- so callers can build complete/missing/
    failing DT-6 fixtures without re-deriving the rest of this fixture. Does
    not write the manifest itself; callers json.dumps() it wherever they
    choose."""
    receipt_payload: dict[str, Any] = {"verdict": "RESIDENT_TRAINING_CANDIDATE_PASS"}
    if dt6_fields:
        receipt_payload.update(dt6_fields)
    for artifact_name in ["trace.json", "policy.py", "goal.py", "harness.py", "receipt.json", "tasks.json", "adapter.py"]:
        (root / artifact_name).write_text(
            json.dumps({"verdict": "POLICY_UPDATE_TRACE_READY", "updates": [1], "selected_template": "eval_script_recursive"})
            if artifact_name == "trace.json"
            else json.dumps(receipt_payload)
            if artifact_name == "receipt.json"
            else "fixture",
            encoding="utf-8",
        )
    real_candidate = build_symbolic_candidate_base(root)
    real_candidate.update(
        {
            "trainable_neural_model_identity": "fixture_fp16_resident_policy",
            "trainable_parameter_count": 128,
            "pre_neural_parameter_hash": "sha256:" + ("0" * 64),
            "post_neural_parameter_hash": "sha256:" + ("1" * 64),
            "verifier_conditioned_training_command": "python scripts/train_multimodal_v0.py --selftest --resident-adapter-fixture",
            "transfer_rows": [{"task_id": "transfer_1", "split": "transfer", "c_score": 1.0, "b_score": 0.5, "deleted_score": 0.0}],
            "symbolic_substitution_check": {"status": "NEURAL_UPDATE_PRESENT", "symbolic_template_policy": False, "prompt_only": False, "routing_only": False},
            "prompt_only_routing_only_exclusion_result": {"status": "PASS", "prompt_only": False, "routing_only": False},
            "train_multimodal_integration_decision": {
                "status": "ADAPTER_IMPLEMENTED",
                "source_path": "scripts/train_multimodal_v0.py",
                "adapter_path": str(root / "adapter.py"),
                "source_sha256": _sha256(repo / "scripts/train_multimodal_v0.py"),
            },
            "train_multimodal_adapter_path": str(root / "adapter.py"),
            "floor_contract_sha256": _sha256(repo / "docs/contracts/ember-floor-contract.md"),
            "nc2_component_contract_sha256": _sha256(repo / "docs/contracts/nc2-own-technique-contract.md"),
            "action_log_seam_evidence": {
                "source_path": "scripts/train_multimodal_v0.py",
                "required_primitives": ["emit-token", "emit-scalar", "emit-pointer", "commit", "stop"],
                "present_primitives": ["emit-token", "emit-scalar", "emit-pointer", "commit", "stop"],
            },
            "launch_vehicle_floor_preservation_map": {
                "QAT": "preserved",
                "Muon": "preserved",
                "QK-norm": "preserved",
                "governor": "preserved",
                "multimodal_locks": "preserved",
            },
            "floor_contract_manifest": build_floor_contract_manifest(
                _sha256(repo / "docs/contracts/ember-floor-contract.md"),
                _sha256(repo / "docs/contracts/nc2-own-technique-contract.md"),
            ),
        }
    )
    return real_candidate


def selftest() -> int:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="ember-resident-gate-") as td:
        root = Path(td)
        repo, index, full_parity_path = build_fixture_repo(root)

        blocked = build_gate_receipt(repo, index, None, None, [Path("scripts/ember_resident_training_gate.py")], full_parity_path)
        assert blocked["resident_training_gate_status"] == "BLOCKED"
        assert "resident_training_candidate_missing" in blocked["invalid_codes"]
        assert blocked["component_status"]["paper_source_preflight"] == "PASS"
        assert blocked["component_status"]["clean_room_harness_interface"] == "PASS"
        # gh #128: check_econ_gate must be invoked even with no candidate at all
        assert blocked["component_status"]["loop_econ_gate"] == "BLOCKED"
        assert blocked["loop_economics_gate_verdict"]["decision"] != "PENDING"

        toy_path = root / "toy.json"
        toy_path.write_text(json.dumps({"toy_or_simulated": True, "prompt_only": True}), encoding="utf-8")
        toy = build_gate_receipt(repo, index, None, toy_path, [], full_parity_path)
        assert toy["resident_training_gate_status"] == "BLOCKED"
        assert "precondition_scaffold_only" in toy["invalid_codes"]

        symbolic_path = root / "symbolic.json"
        (root / "trace.json").write_text(
            json.dumps({"verdict": "POLICY_UPDATE_TRACE_READY", "updates": [1], "selected_template": "eval_script_recursive"}),
            encoding="utf-8",
        )
        (root / "receipt.json").write_text(json.dumps({"verdict": "RESIDENT_TRAINING_CANDIDATE_PASS"}), encoding="utf-8")
        for artifact_name in ["policy.py", "goal.py", "harness.py", "tasks.json", "adapter.py"]:
            (root / artifact_name).write_text("fixture", encoding="utf-8")
        symbolic_base = build_symbolic_candidate_base(root)
        symbolic_path.write_text(json.dumps(symbolic_base), encoding="utf-8")
        symbolic = build_gate_receipt(repo, index, None, symbolic_path, [], full_parity_path)
        assert symbolic["resident_training_gate_status"] == "BLOCKED"
        assert "symbolic_proxy_substitution" in symbolic["invalid_codes"]

        candidate_path = root / "candidate.json"
        real_candidate = build_valid_candidate_manifest(
            root, repo,
            dt6_fields={"signal_per_gpu_hour": 1.2, "equal_wallclock_band": 0.5, "exceeds_band": True},
        )
        candidate_path.write_text(json.dumps(real_candidate), encoding="utf-8")
        passed = build_gate_receipt(repo, index, None, candidate_path, [], full_parity_path)
        assert passed["resident_training_gate_status"] == "PASS", (
            "gate fixture BLOCKED — components: "
            + json.dumps(
                {k: v for k, v in passed.get("component_status", {}).items() if v != "PASS"},
                sort_keys=True,
            )
            + " errors=" + json.dumps(passed.get("errors", []), sort_keys=True)
            + " invalid_codes=" + json.dumps(passed.get("invalid_codes", []), sort_keys=True)
        )
        # gh #128: PASS must carry a genuinely-evaluated (not placeholder) econ leg
        assert passed["component_status"]["loop_econ_gate"] == "PASS"
        assert passed["loop_economics_gate_verdict"]["decision"] == "ACCEPT"
        assert passed["loop_economics_gate_verdict"]["ac"] == "AC2"
    print("EMBER_RESIDENT_TRAINING_GATE_SELFTEST_PASS")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--paper-index", default=None)
    ap.add_argument("--candidate-manifest")
    ap.add_argument("--full-parity-receipt")
    ap.add_argument("--out")
    ap.add_argument("--changed-path", action="append", default=[])
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.out:
        ap.error("--out is required unless --selftest is used")
    if not args.paper_index:
        ap.error(
            "--paper-index is required unless --selftest is used (no baked-in "
            "default; original path was scrubbed for public export, see issue #261)"
        )
    repo = _repo_root()
    changed = [Path(p) for p in args.changed_path] or [
        Path("scripts/ember_resident_training_gate.py"),
        Path("scripts/ember_resident_training_gate_selftest.py"),
        Path("docs/domains/governance/ledgers/ember-debt-ledger.md"),
        Path("docs/domains/governance/authority/GOAL.md"),
    ]
    receipt = build_gate_receipt(
        repo,
        Path(args.paper_index),
        Path(args.out),
        Path(args.candidate_manifest) if args.candidate_manifest else None,
        changed,
        Path(args.full_parity_receipt) if args.full_parity_receipt else None,
    )
    write_gate_receipt(Path(args.out), receipt)
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["resident_training_gate_status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
