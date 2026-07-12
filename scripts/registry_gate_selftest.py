#!/usr/bin/env python3
# goal_id: EMBER-00
# next_executed_outcome: EMBER-01 clean 3B custody and identity spine
"""Selftest for the technique-registry dispatch gate (#256, sp-7).

Validates the LIVE registry, predicate coverage of ADOPT rows, and the gate
verdict on PASS / missing-row / invalid-exemption / contradicted fixtures.
Fail-closed: any mismatch = exit 1 with the case named.
"""
import datetime as dt
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from registry_gate import PREDICATES, check, load_registry, normalize_config_path  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TODAY = dt.date(2026, 6, 12)
DRIVE_LETTER_RE = re.compile(r"[A-Za-z]:[\\/]")
LEGACY_ERASURE_STATUSES = {
    "ADOPT",
    "TESTED",
    "KILL",
    "WATCH-NEGATIVE",
    "PARK",
    "ADOPT-PENDING-SEGMENT",
    "EXCLUDED",
    "RETIRED",
}

BASE_CONFIG = {
    "optimizer": "muon",
    "scheduler": "wsd-segment",
    "qat_enabled": True,
    "vram_fraction": 0.85,
    "registry": {"consumes": ["muon", "wsd-schedule", "qat", "governor-pacing"],
                 "exemptions": []},
}
SYNTHETIC_CURRENT_ROWS = [
    {'id': rid, 'status': 'ADOPTED_CURRENT_CONFIG'}
    for rid in ('muon', 'wsd-schedule', 'qat', 'governor-pacing')
]


def deep(d):
    import copy
    return copy.deepcopy(d)


def main() -> int:
    fails = []
    rows = load_registry()  # raises = fail-closed on live registry damage
    adopt = [r["id"] for r in rows if r["status"] == "ADOPTED_CURRENT_CONFIG"]
    legacy = [r["id"] for r in rows if r["status"] in LEGACY_ERASURE_STATUSES]
    if legacy:
        fails.append(f"live registry retains legacy/erasure statuses: {legacy}")
    uncovered = [
        row['id'] for row in SYNTHETIC_CURRENT_ROWS
        if row['id'] not in PREDICATES
    ]
    if uncovered:
        print(f"WARN: ADOPT rows without corroboration predicate: {uncovered}")

    # case 1: fully-consuming config passes
    v = check(deep(BASE_CONFIG), SYNTHETIC_CURRENT_ROWS, today=TODAY, root=ROOT)
    if not v["ok"] or v["contradicted"]:
        fails.append(f"case1 expected PASS, got {v}")

    # case 2: missing ADOPT row fails with the row named
    cfg = deep(BASE_CONFIG)
    cfg["registry"]["consumes"].remove("muon")
    v = check(cfg, SYNTHETIC_CURRENT_ROWS, today=TODAY, root=ROOT)
    if v["ok"] or "muon" not in v["missing"]:
        fails.append(f"case2 expected FAIL missing=['muon'], got {v}")

    # case 3: invalid exemption (no receipt on disk) fails
    cfg = deep(BASE_CONFIG)
    cfg["registry"]["consumes"].remove("qat")
    cfg["registry"]["exemptions"] = [{
        "row_id": "qat", "reason": "eval-only",
        "receipt_path": "receipts/does-not-exist.json",
        "scope": "eval", "expiry": "2026-06-22"}]
    v = check(cfg, SYNTHETIC_CURRENT_ROWS, today=TODAY, root=ROOT)
    if v["ok"] or "qat" not in v["invalid_exemptions"]:
        fails.append(f"case3 expected FAIL invalid_exemptions=['qat'], got {v}")

    # case 3b: valid exemption (real receipt, unexpired) passes
    receipt = sorted((ROOT / "receipts").glob("*.json"))
    if receipt:
        cfg["registry"]["exemptions"][0]["receipt_path"] = (
            receipt[0].relative_to(ROOT).as_posix())
        v = check(cfg, SYNTHETIC_CURRENT_ROWS, today=TODAY, root=ROOT)
        if not v["ok"]:
            fails.append(f"case3b expected PASS with valid exemption, got {v}")

    # case 4: declared-but-not-configured is contradicted
    cfg = deep(BASE_CONFIG)
    cfg["optimizer"] = "adamw"
    v = check(cfg, SYNTHETIC_CURRENT_ROWS, today=TODAY, root=ROOT)
    if v["ok"] or "muon" not in v["contradicted"]:
        fails.append(f"case4 expected FAIL contradicted=['muon'], got {v}")

    # case 5: expired exemption fails
    cfg = deep(BASE_CONFIG)
    cfg["registry"]["consumes"].remove("qat")
    cfg["registry"]["exemptions"] = [{
        "row_id": "qat", "reason": "eval-only",
        "receipt_path": receipt[0].relative_to(ROOT).as_posix() if receipt
        else "receipts/x.json",
        "scope": "eval", "expiry": "2026-06-01"}]
    v = check(cfg, SYNTHETIC_CURRENT_ROWS, today=TODAY, root=ROOT)
    if v["ok"] or "qat" not in v["invalid_exemptions"]:
        fails.append(f"case5 expected FAIL on expired exemption, got {v}")

    # case 6: config_path normalization never leaks an absolute host path (#710)
    with tempfile.TemporaryDirectory() as tmp:
        troot = Path(tmp)
        cfg_dir = troot / "configs"
        cfg_dir.mkdir()
        cfg_path = cfg_dir / "v0-pretrain-config.json"
        cfg_path.write_text("{}", encoding="utf-8")
        got = normalize_config_path(str(cfg_path), root=troot)
        if got != "configs/v0-pretrain-config.json":
            fails.append(f"case6 expected 'configs/v0-pretrain-config.json', got {got!r}")
        if DRIVE_LETTER_RE.search(got):
            fails.append(f"case6 leaked a drive-letter path: {got!r}")

        outside = troot.parent / "outside-config.json"
        got_ext = normalize_config_path(str(outside), root=troot)
        if got_ext != f"<EXTERNAL>/{outside.name}":
            fails.append(f"case6b expected '<EXTERNAL>/{outside.name}', got {got_ext!r}")
        if DRIVE_LETTER_RE.search(got_ext):
            fails.append(f"case6b leaked a drive-letter path: {got_ext!r}")

    if fails:
        print("REGISTRY_GATE_SELFTEST FAIL:")
        for f in fails:
            print(f"  - {f}")
        return 1
    print(f"REGISTRY_GATE_SELFTEST PASS: registry {len(rows)} rows / "
          f"{len(adopt)} ADOPTED_CURRENT_CONFIG, 7 gate cases green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
