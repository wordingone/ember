#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""cbase_grow_rung2_completion_audit.py — issue #626 read-only audit.

Enumerates every growth receipt scripts/ember_totality/test_c_grow.py itself
scans (via that module's own candidate_files()) and tables, per receipt,
which of the probe's four R-text requirements its raw text already
satisfies:

  - grow_method                (GROW_METHOD regex)
  - param_counts_before_after  (PARAM_BEFORE and PARAM_AFTER regexes)
  - loss_continuity            (LOSS_CONTINUITY regex)
  - flop_saving_vs_fromscratch (FLOP_SAVING regex)

plus the probe's own measured/invalid/smoke/near-miss classification, so
this table matches test_c_grow.py's real verdict exactly (same regex
objects, imported directly -- zero duplication, zero probe edits; this
script only READS scripts/ember_totality/test_c_grow.py as a module).

Read-only: never writes to receipts/, never touches the probe file.
Usage: wsl python3 scripts/cbase_grow_rung2_completion_audit.py
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "ember_totality"))
import test_c_grow as probe  # noqa: E402  (read-only import of the frozen probe)
from scripts.lib.invariant import stamp  # noqa: E402


GOAL_ID = "EMBER-02"
WORKSTREAM_ID = "EMBER-02A"
NEXT_EXECUTED_OUTCOME = (
    "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
)
HISTORICAL_RECEIPT = (
    REPO / "receipts" / "cbase-grow-rung"
    / "cbase-grow-rung2-completion-20260710T172500Z.json"
)
SATISFYING_RECEIPT = (
    REPO / "receipts" / "cbase-grow-rung"
    / "cbase-grow-measured-flops-20260710T005231Z.json"
)
DEFAULT_SOURCES = {
    "producer": Path(__file__).resolve(),
    "probe": REPO / "scripts" / "ember_totality" / "test_c_grow.py",
    "historical_receipt": HISTORICAL_RECEIPT,
    "satisfying_receipt": SATISFYING_RECEIPT,
}


def classify(path: str) -> dict:
    row = {"path": Path(path).resolve().relative_to(probe.ROOT).as_posix()}
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            raw = fh.read()
    except Exception as exc:
        row["unreadable"] = str(exc)
        return row

    low = raw.lower()
    row["invalid_tokens"] = [t for t in probe.INVALID_TOKENS if t.lower() in low]

    try:
        obj = json.loads(raw)
    except Exception:
        obj = None
    ticket = obj.get("ticket") if isinstance(obj, dict) else None
    row["ticket"] = ticket

    smoke_markers = []
    if isinstance(obj, dict):
        for fld in ("verdict", "mode", "run_mode", "kind"):
            v = obj.get(fld)
            if isinstance(v, str) and "smoke" in v.lower():
                smoke_markers.append(f"{fld}={v}")
    if "smoke" in os.path.basename(path).lower():
        smoke_markers.append("filename")
    row["smoke_markers"] = smoke_markers

    row["loop_readiness_or_budget_ticket"] = ticket in (
        "EMBER-GROWTH-CONTRACTION-STABILITY", "EMBER-BOUNDED-SCALE-UP")

    unmeasured_flop = probe.flop_saving_self_declares_unmeasured(obj) if isinstance(obj, dict) else None
    row["flop_block_self_declares_unmeasured"] = unmeasured_flop

    row["grow_method"] = bool(probe.GROW_METHOD.search(raw))
    row["param_counts_before_after"] = bool(probe.PARAM_BEFORE.search(raw) and probe.PARAM_AFTER.search(raw))
    row["loss_continuity"] = bool(probe.LOSS_CONTINUITY.search(raw))
    row["flop_saving_vs_fromscratch"] = bool(probe.FLOP_SAVING.search(raw))
    row["measured_on_train_daemon"] = bool(probe.MEASURED_MARKER.search(raw))

    excluded = bool(row["invalid_tokens"] or smoke_markers or row["loop_readiness_or_budget_ticket"] or unmeasured_flop)
    row["excluded_from_candidacy"] = excluded
    all_chk = (row["grow_method"] and row["param_counts_before_after"]
               and row["loss_continuity"] and row["flop_saving_vs_fromscratch"]
               and row["measured_on_train_daemon"])
    row["would_satisfy_full_chk"] = bool(all_chk and not excluded)
    return row


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repo_relative(path: Path) -> str:
    return path.resolve().relative_to(REPO).as_posix()


def build_completion_receipt(
    *,
    timestamp: str | None = None,
    sources: dict[str, Path] | None = None,
) -> dict:
    """Build a current-tree successor without copying stale private claims."""
    source_paths = dict(DEFAULT_SOURCES if sources is None else sources)
    required_sources = {
        "producer", "probe", "historical_receipt", "satisfying_receipt"
    }
    if set(source_paths) != required_sources:
        raise ValueError("completion receipt source roles must be exact and closed")
    for role, path in source_paths.items():
        source_paths[role] = Path(path).resolve()
        if not source_paths[role].is_file():
            raise FileNotFoundError(f"{role} source is not a file")

    completed = subprocess.run(
        [sys.executable, "-B", str(source_paths["probe"])],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=False,
    )
    probe_stdout = completed.stdout.strip()
    if completed.returncode != 0 or not probe_stdout.startswith("GREEN C-GROW:"):
        raise RuntimeError(
            "C-GROW probe refused completion receipt: "
            f"exit={completed.returncode}; stdout={probe_stdout!r}; "
            f"stderr={completed.stderr.strip()!r}"
        )

    files = probe.candidate_files()
    rows = [classify(path) for path in files]
    satisfying = [
        row["path"] for row in rows if row.get("would_satisfy_full_chk")
    ]
    expected_satisfying = _repo_relative(source_paths["satisfying_receipt"])
    if expected_satisfying not in satisfying:
        raise RuntimeError(
            "canonical satisfying C-GROW receipt is absent from current audit"
        )

    ts = timestamp or datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    receipt = {
        "ticket": "CBASE-GROW-RUNG2-COMPLETION",
        "ts": ts,
        "issue": 700,
        "source_issue": 626,
        "goal_id": GOAL_ID,
        "workstream_id": WORKSTREAM_ID,
        "next_executed_outcome": NEXT_EXECUTED_OUTCOME,
        "script": "scripts/cbase_grow_rung2_completion_audit.py",
        "mode": "READ_ONLY_REEXECUTION",
        "supersedes": _repo_relative(source_paths["historical_receipt"]),
        "scope": (
            "Current-tree re-execution of the C-GROW candidate audit and "
            "probe. This receipt binds exact source bytes and supersedes the "
            "historical completion receipt for invariant-stamp accounting."
        ),
        "probe": {
            "verdict": "GREEN",
            "command": "python -B scripts/ember_totality/test_c_grow.py",
            "stdout": probe_stdout,
            "stderr": completed.stderr.strip(),
            "exit_code": completed.returncode,
        },
        "candidate_audit": {
            "n_candidate_files": len(files),
            "n_satisfying_full_chk": len(satisfying),
            "satisfying_full_chk": satisfying,
            "candidate_rows_sha256": hashlib.sha256(
                json.dumps(
                    rows,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            ).hexdigest(),
        },
        "source_paths": {
            role: _repo_relative(path) for role, path in source_paths.items()
        },
        "source_sha256": {
            role: _sha256(path) for role, path in source_paths.items()
        },
        "sha_convention": "bytes on disk as-is (binary read, no normalization)",
        "claim_boundary": {
            "c_grow_current_probe_green": True,
            "historical_private_path_claims_reasserted": False,
            "rung2_extension_completion_claim": False,
            "training_claim": False,
            "model_capability_claim": False,
        },
        "paid_api_surface_used": False,
    }
    return stamp(receipt, str(REPO))


def publish_receipt(receipt: dict, target: Path) -> None:
    """Publish one LF-only receipt without replacing an existing path."""
    raw = (
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    with Path(target).open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write-completion-receipt",
        type=Path,
        help="write one stamped current-tree successor under receipts/cbase-grow-rung",
    )
    args = parser.parse_args()

    if args.write_completion_receipt is not None:
        target = args.write_completion_receipt.resolve()
        allowed_parent = (REPO / "receipts" / "cbase-grow-rung").resolve()
        if target.parent != allowed_parent:
            raise ValueError(
                "--write-completion-receipt must target receipts/cbase-grow-rung"
            )
        receipt = build_completion_receipt()
        publish_receipt(receipt, target)
        print(json.dumps({
            "status": "PASS",
            "receipt": target.relative_to(REPO).as_posix(),
            "ticket": receipt["ticket"],
            "probe": receipt["probe"]["verdict"],
        }, sort_keys=True))
        return 0

    if probe.ROOT is None:
        print(json.dumps({"error": "ROOT not found -- nothing to audit"}))
        return 0
    files = probe.candidate_files()
    rows = [classify(p) for p in files]
    n_full = sum(1 for r in rows if r.get("would_satisfy_full_chk"))
    satisfying = [r["path"] for r in rows if r.get("would_satisfy_full_chk")]
    receipt = {
        "ticket": "C-GROW-CANDIDATE-AUDIT",
        "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "issue": 626,
        "script": "scripts/cbase_grow_rung2_completion_audit.py",
        "scope": (
            "Read-only enumeration of every file scripts/ember_totality/test_c_grow.py's own "
            "candidate_files() scans, tabled per the probe's four R-text requirements (grow_method, "
            "param_counts_before_after, loss_continuity, flop_saving_vs_fromscratch) plus its "
            "measured/exclusion classification -- zero probe edits, direct import + reuse of the "
            "probe's own regex objects and functions."
        ),
        "n_candidate_files": len(files),
        "n_satisfying_full_chk": n_full,
        "satisfying_full_chk": satisfying,
        "rows": rows,
    }
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
