#!/usr/bin/env python3
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

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts" / "ember_totality"))
import test_c_grow as probe  # noqa: E402  (read-only import of the frozen probe)


def classify(path: str) -> dict:
    row = {"path": os.path.relpath(path, probe.ROOT)}
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


def main() -> int:
    import datetime

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
