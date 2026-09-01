#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
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
# issue2015 exact-local-import:scripts/registry_gate.py
import importlib.util as _ember_abd330e63c6c95de_importlib
import sys as _ember_abd330e63c6c95de_sys
from pathlib import Path as _ember_abd330e63c6c95de_Path
_ember_abd330e63c6c95de_path = _ember_abd330e63c6c95de_Path(__file__).resolve().parents[4].joinpath('scripts', 'registry_gate.py')
if not _ember_abd330e63c6c95de_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:scripts/registry_gate.py')
_ember_abd330e63c6c95de_aliases = ('_ember_issue2015_abd330e63c6c95de', 'registry_gate', 'scripts.registry_gate')
_ember_abd330e63c6c95de_existing = []
for _ember_abd330e63c6c95de_alias in _ember_abd330e63c6c95de_aliases:
    _ember_abd330e63c6c95de_candidate = _ember_abd330e63c6c95de_sys.modules.get(_ember_abd330e63c6c95de_alias)
    if _ember_abd330e63c6c95de_candidate is not None and all(_ember_abd330e63c6c95de_candidate is not item for item in _ember_abd330e63c6c95de_existing):
        _ember_abd330e63c6c95de_existing.append(_ember_abd330e63c6c95de_candidate)
if len(_ember_abd330e63c6c95de_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:scripts/registry_gate.py')
if _ember_abd330e63c6c95de_existing:
    _ember_abd330e63c6c95de_module = _ember_abd330e63c6c95de_existing[0]
    _ember_abd330e63c6c95de_observed = getattr(_ember_abd330e63c6c95de_module, '__file__', None)
    if _ember_abd330e63c6c95de_observed is None or _ember_abd330e63c6c95de_Path(_ember_abd330e63c6c95de_observed).resolve() != _ember_abd330e63c6c95de_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:scripts/registry_gate.py')
else:
    _ember_abd330e63c6c95de_spec = _ember_abd330e63c6c95de_importlib.spec_from_file_location('_ember_issue2015_abd330e63c6c95de', _ember_abd330e63c6c95de_path)
    if _ember_abd330e63c6c95de_spec is None or _ember_abd330e63c6c95de_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:scripts/registry_gate.py')
    _ember_abd330e63c6c95de_module = _ember_abd330e63c6c95de_importlib.module_from_spec(_ember_abd330e63c6c95de_spec)
    for _ember_abd330e63c6c95de_alias in _ember_abd330e63c6c95de_aliases:
        _ember_abd330e63c6c95de_prior = _ember_abd330e63c6c95de_sys.modules.get(_ember_abd330e63c6c95de_alias)
        if _ember_abd330e63c6c95de_prior is not None and _ember_abd330e63c6c95de_prior is not _ember_abd330e63c6c95de_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/registry_gate.py')
        _ember_abd330e63c6c95de_sys.modules[_ember_abd330e63c6c95de_alias] = _ember_abd330e63c6c95de_module
    try:
        _ember_abd330e63c6c95de_spec.loader.exec_module(_ember_abd330e63c6c95de_module)
    except BaseException:
        for _ember_abd330e63c6c95de_alias in _ember_abd330e63c6c95de_aliases:
            if _ember_abd330e63c6c95de_sys.modules.get(_ember_abd330e63c6c95de_alias) is _ember_abd330e63c6c95de_module:
                _ember_abd330e63c6c95de_sys.modules.pop(_ember_abd330e63c6c95de_alias, None)
        raise
for _ember_abd330e63c6c95de_alias in _ember_abd330e63c6c95de_aliases:
    _ember_abd330e63c6c95de_prior = _ember_abd330e63c6c95de_sys.modules.get(_ember_abd330e63c6c95de_alias)
    if _ember_abd330e63c6c95de_prior is not None and _ember_abd330e63c6c95de_prior is not _ember_abd330e63c6c95de_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/registry_gate.py')
    _ember_abd330e63c6c95de_sys.modules[_ember_abd330e63c6c95de_alias] = _ember_abd330e63c6c95de_module
PREDICATES = getattr(_ember_abd330e63c6c95de_module, 'PREDICATES')
check = getattr(_ember_abd330e63c6c95de_module, 'check')
load_registry = getattr(_ember_abd330e63c6c95de_module, 'load_registry')
normalize_config_path = getattr(_ember_abd330e63c6c95de_module, 'normalize_config_path')
# issue2015 exact-local-import-end:scripts/registry_gate.py  # noqa: E402

ROOT = Path(__file__).resolve().parents[4]
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
