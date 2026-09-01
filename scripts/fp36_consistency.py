#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""fp-36 consistency guard (#326).

Fail-closed assertions binding docs/archive/pre-restart/fp36-1b-info-interpretation-v0.md to the
on-disk receipts it quotes:
  1. The two pre-protocol probe receipts exist, are receipt_check-clean, and
     carry exactly the (tokens, verified, governed-min) the doc's table pins.
  2. The doc quotes each receipt's sha256 prefix correctly (byte-derived).
  3. Frame is frozen PRE-data: no fp24-verdict-1B-*.json exists yet. At
     fp-36b execution time this assertion is EXPECTED to fail — pass
     --post-data to skip it (the rest still must hold).

Exit 0 + FP36_CONSISTENCY_PASS, else exit 1 with the named mismatch.
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOC = os.path.join(ROOT, "docs", "archive", "pre-restart", "fp36-1b-info-interpretation-v0.md")

PINS = [
    {
        "receipt": "receipts/sp-checkpoint-probe-step-25000-20260612T090913Z.json",
        "tokens": 102_400_000,
        "verified": 0,
        "governed_min": 51.685,
    },
    {
        "receipt": "receipts/sp-checkpoint-probe-step-50000-20260612T093809Z.json",
        "tokens": 204_800_000,
        "verified": 0,
        "governed_min": 48.965,
    },
]


def main() -> int:
    post_data = "--post-data" in sys.argv
    fails = []

    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    # issue2015 exact-local-import:src/ember/governance/scripts/receipt_check.py
    import importlib.util as _ember_2ad73f5df12b45ee_importlib
    import sys as _ember_2ad73f5df12b45ee_sys
    from pathlib import Path as _ember_2ad73f5df12b45ee_Path
    _ember_2ad73f5df12b45ee_path = _ember_2ad73f5df12b45ee_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_check.py')
    if not _ember_2ad73f5df12b45ee_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/receipt_check.py')
    _ember_2ad73f5df12b45ee_aliases = ('_ember_issue2015_2ad73f5df12b45ee', 'receipt_check', 'scripts.receipt_check')
    _ember_2ad73f5df12b45ee_existing = []
    for _ember_2ad73f5df12b45ee_alias in _ember_2ad73f5df12b45ee_aliases:
        _ember_2ad73f5df12b45ee_candidate = _ember_2ad73f5df12b45ee_sys.modules.get(_ember_2ad73f5df12b45ee_alias)
        if _ember_2ad73f5df12b45ee_candidate is not None and all(_ember_2ad73f5df12b45ee_candidate is not item for item in _ember_2ad73f5df12b45ee_existing):
            _ember_2ad73f5df12b45ee_existing.append(_ember_2ad73f5df12b45ee_candidate)
    if len(_ember_2ad73f5df12b45ee_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/receipt_check.py')
    if _ember_2ad73f5df12b45ee_existing:
        _ember_2ad73f5df12b45ee_module = _ember_2ad73f5df12b45ee_existing[0]
        _ember_2ad73f5df12b45ee_observed = getattr(_ember_2ad73f5df12b45ee_module, '__file__', None)
        if _ember_2ad73f5df12b45ee_observed is None or _ember_2ad73f5df12b45ee_Path(_ember_2ad73f5df12b45ee_observed).resolve() != _ember_2ad73f5df12b45ee_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/receipt_check.py')
    else:
        _ember_2ad73f5df12b45ee_spec = _ember_2ad73f5df12b45ee_importlib.spec_from_file_location('_ember_issue2015_2ad73f5df12b45ee', _ember_2ad73f5df12b45ee_path)
        if _ember_2ad73f5df12b45ee_spec is None or _ember_2ad73f5df12b45ee_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/receipt_check.py')
        _ember_2ad73f5df12b45ee_module = _ember_2ad73f5df12b45ee_importlib.module_from_spec(_ember_2ad73f5df12b45ee_spec)
        for _ember_2ad73f5df12b45ee_alias in _ember_2ad73f5df12b45ee_aliases:
            _ember_2ad73f5df12b45ee_prior = _ember_2ad73f5df12b45ee_sys.modules.get(_ember_2ad73f5df12b45ee_alias)
            if _ember_2ad73f5df12b45ee_prior is not None and _ember_2ad73f5df12b45ee_prior is not _ember_2ad73f5df12b45ee_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_check.py')
            _ember_2ad73f5df12b45ee_sys.modules[_ember_2ad73f5df12b45ee_alias] = _ember_2ad73f5df12b45ee_module
        try:
            _ember_2ad73f5df12b45ee_spec.loader.exec_module(_ember_2ad73f5df12b45ee_module)
        except BaseException:
            for _ember_2ad73f5df12b45ee_alias in _ember_2ad73f5df12b45ee_aliases:
                if _ember_2ad73f5df12b45ee_sys.modules.get(_ember_2ad73f5df12b45ee_alias) is _ember_2ad73f5df12b45ee_module:
                    _ember_2ad73f5df12b45ee_sys.modules.pop(_ember_2ad73f5df12b45ee_alias, None)
            raise
    for _ember_2ad73f5df12b45ee_alias in _ember_2ad73f5df12b45ee_aliases:
        _ember_2ad73f5df12b45ee_prior = _ember_2ad73f5df12b45ee_sys.modules.get(_ember_2ad73f5df12b45ee_alias)
        if _ember_2ad73f5df12b45ee_prior is not None and _ember_2ad73f5df12b45ee_prior is not _ember_2ad73f5df12b45ee_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_check.py')
        _ember_2ad73f5df12b45ee_sys.modules[_ember_2ad73f5df12b45ee_alias] = _ember_2ad73f5df12b45ee_module
    validate_receipt = getattr(_ember_2ad73f5df12b45ee_module, 'validate_receipt')
    # issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_check.py

    doc_text = open(DOC, encoding="utf-8").read()

    for pin in PINS:
        path = os.path.join(ROOT, pin["receipt"])
        if not os.path.isfile(path):
            fails.append(f"missing receipt {pin['receipt']}")
            continue
        raw = open(path, "rb").read()
        sha = hashlib.sha256(raw).hexdigest()
        rec = json.loads(raw)

        errs = validate_receipt(rec)
        if errs:
            fails.append(f"{pin['receipt']} receipt_check-dirty: {errs}")
        if rec.get("checkpoint_tokens") != pin["tokens"]:
            fails.append(f"{pin['receipt']} tokens {rec.get('checkpoint_tokens')} != doc {pin['tokens']}")
        if rec.get("l1_verified_episodes") != pin["verified"]:
            fails.append(f"{pin['receipt']} verified {rec.get('l1_verified_episodes')} != doc {pin['verified']}")
        if rec.get("l1_governed_minutes") != pin["governed_min"]:
            fails.append(f"{pin['receipt']} governed-min {rec.get('l1_governed_minutes')} != doc {pin['governed_min']}")
        if sha[:16] not in doc_text:
            fails.append(f"doc does not quote sha prefix {sha[:16]} of {pin['receipt']}")
        if os.path.basename(pin["receipt"]) not in doc_text:
            fails.append(f"doc does not name {os.path.basename(pin['receipt'])}")

    # Frame frozen pre-data: no 1B verdict receipt may exist yet.
    if not post_data:
        verdicts = [f for f in os.listdir(os.path.join(ROOT, "receipts"))
                    if re.match(r"fp24-verdict-1B-.*\.json$", f)]
        if verdicts:
            fails.append(f"frame not pre-data: 1B verdict receipt(s) exist: {verdicts}")

    if fails:
        print("FP36_CONSISTENCY_FAIL:")
        for f in fails:
            print(f"  - {f}")
        return 1
    print("FP36_CONSISTENCY_PASS: doc table byte-derives from the named "
          "receipts; sha prefixes quoted; "
          + ("post-data mode (1B-verdict check skipped)" if post_data
             else "frame frozen pre-data (no 1B verdict receipt exists)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
