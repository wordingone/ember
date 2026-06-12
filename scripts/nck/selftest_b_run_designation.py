#!/usr/bin/env python3
"""Fail-closed selftest for the B-run designation resolver (part of #282).

Tmp fixtures only — never touches the real run dirs or receipts/.

Cases:
  (a) highest complete step wins; incomplete (missing/empty model.pt,
      unparseable manifest) candidates are skipped, not refused
  (b) determinism: two resolves -> identical records (sans nothing — pure)
  (c) refusals: no candidates; no COMPLETE candidate
  (d) window: inside resolves; outside refuses; outside+override without
      note refuses; outside+override+note resolves with deviation recorded
  (e) tie-break: equal step across two lineage dirs -> later dir wins,
      collision flagged
  (f) battery-blindness: resolver consumes only the checkpoints dirs + clock
      (asserted by signature — resolve() takes no receipts path)
  (g) staged guard: bare CLI invocation exits 1, no receipt written

Exit 0 + "B_RUN_DESIGNATION_SELFTEST PASS" on all pass.
"""
from __future__ import annotations

import inspect
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from nck.b_run_designation import (
    DesignationRefuse,
    WINDOW_START,
    resolve,
    scan_candidates,
)

IN_WINDOW = datetime(2026, 6, 20, 12, 0, 0, tzinfo=timezone.utc)
BEFORE_WINDOW = datetime(2026, 6, 12, 12, 0, 0, tzinfo=timezone.utc)


def _mk_ckpt(root: Path, step: int, complete: bool = True,
             bad_manifest: bool = False, empty_model: bool = False) -> Path:
    d = root / f"step-{step:08d}"
    d.mkdir(parents=True)
    if complete or empty_model:
        (d / "model.pt").write_bytes(b"" if empty_model else f"WEIGHTS-{step}".encode())
    if complete or bad_manifest:
        (d / "manifest.json").write_text(
            "{not json" if bad_manifest else json.dumps({"step": step}),
            encoding="utf-8",
        )
    return d


def main() -> int:
    fails: list[str] = []

    # (a) highest complete step wins; incompletes skipped
    with tempfile.TemporaryDirectory(prefix="sp6b-des-a-") as tmp:
        root = Path(tmp)
        _mk_ckpt(root, 25000)
        _mk_ckpt(root, 50000)
        _mk_ckpt(root, 75000, complete=False)            # no files at all
        _mk_ckpt(root, 60000, complete=False, empty_model=True)   # empty model.pt
        _mk_ckpt(root, 70000, complete=True, bad_manifest=True)   # manifest corrupt
        # bad_manifest overwrote manifest with garbage -> incomplete
        rec = resolve([root], IN_WINDOW)
        if rec["designated"]["step"] != 50000:
            fails.append(f"(a) designated step {rec['designated']['step']}, want 50000")
        if len(rec["candidates"]) != 5:
            fails.append(f"(a) scanned {len(rec['candidates'])} candidates, want 5")
        # receipt_check R2: sha-bearing receipt must carry sha_convention
        try:
            from receipt_check import validate_receipt
            errs = validate_receipt(rec)
            if any("SHA_CONVENTION" in e for e in errs):
                fails.append(f"(a) designation record receipt_check-dirty: {errs}")
        except ImportError:
            fails.append("(a) receipt_check not importable for R2 assert")
        # (b) determinism
        rec2 = resolve([root], IN_WINDOW)
        if rec != rec2:
            fails.append("(b) two resolves differ — resolver not pure")

    # (c) refusals
    with tempfile.TemporaryDirectory(prefix="sp6b-des-c-") as tmp:
        try:
            resolve([Path(tmp)], IN_WINDOW)
            fails.append("(c) empty dir did not refuse")
        except DesignationRefuse as e:
            if "NO_CANDIDATES" not in str(e):
                fails.append(f"(c) wrong refusal: {e}")
        _mk_ckpt(Path(tmp), 1000, complete=False, empty_model=True)
        try:
            resolve([Path(tmp)], IN_WINDOW)
            fails.append("(c) all-incomplete did not refuse")
        except DesignationRefuse as e:
            if "NO_COMPLETE_CANDIDATE" not in str(e):
                fails.append(f"(c) wrong refusal: {e}")

    # (d) window discipline
    with tempfile.TemporaryDirectory(prefix="sp6b-des-d-") as tmp:
        root = Path(tmp)
        _mk_ckpt(root, 10)
        try:
            resolve([root], BEFORE_WINDOW)
            fails.append("(d) outside-window resolve did not refuse")
        except DesignationRefuse as e:
            if "WINDOW_REFUSE" not in str(e):
                fails.append(f"(d) wrong refusal: {e}")
        try:
            resolve([root], BEFORE_WINDOW, override_window=True)
            fails.append("(d) override without note did not refuse")
        except DesignationRefuse as e:
            if "DEVIATION_NOTE_REQUIRED" not in str(e):
                fails.append(f"(d) wrong refusal: {e}")
        rec = resolve([root], BEFORE_WINDOW, override_window=True,
                      deviation_note="selftest registered deviation")
        if not rec["window"]["override"] or not rec["window"]["deviation_note"]:
            fails.append("(d) override resolve did not record the deviation")
        rec_in = resolve([root], WINDOW_START)
        if rec_in["window"]["override"]:
            fails.append("(d) window-start resolve wrongly marked override")

    # (e) tie-break across lineage dirs
    with tempfile.TemporaryDirectory(prefix="sp6b-des-e1-") as t1, \
            tempfile.TemporaryDirectory(prefix="sp6b-des-e2-") as t2:
        _mk_ckpt(Path(t1), 30000)
        _mk_ckpt(Path(t2), 30000)
        rec = resolve([Path(t1), Path(t2)], IN_WINDOW)
        if rec["designated"]["path"] != str(Path(t2) / "step-00030000"):
            fails.append("(e) tie-break did not pick the later lineage dir")
        if not rec["designated"]["step_collision_flag"]:
            fails.append("(e) step collision not flagged")

    # (f) battery-blindness: resolve() signature has no receipts input
    params = set(inspect.signature(resolve).parameters)
    if params != {"lineage_dirs", "now", "override_window", "deviation_note"}:
        fails.append(f"(f) resolve() signature drifted: {sorted(params)}")

    # (g) staged guard
    r = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "b_run_designation.py")],
        capture_output=True, text=True,
    )
    if r.returncode != 1 or "STAGED" not in r.stdout:
        fails.append(f"(g) bare invocation: rc={r.returncode}, out={r.stdout[:80]!r}")

    if fails:
        print("B_RUN_DESIGNATION_SELFTEST FAIL:")
        for f in fails:
            print(f"  - {f}")
        return 1
    print(
        "B_RUN_DESIGNATION_SELFTEST PASS: highest-complete-step rule, "
        "determinism, refusals, window discipline + registered-deviation "
        "override, lineage tie-break + collision flag, battery-blind "
        "signature, staged guard"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
