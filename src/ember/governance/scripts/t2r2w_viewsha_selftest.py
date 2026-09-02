# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""t2r2w_viewsha_selftest.py — eng #150: t2_r2w receipt carries the
sha256 of every view it writes.

Pins, with NO GPU and NO ledger access:
  1. file_sha256 == hashlib.sha256 over raw on-disk bytes (CRLF bytes
     preserved — no line-ending normalization).
  2. _view_entry returns {path, rows, sha256} with the sha taken from
     the file as written.
  3. Source-position asserts: each _view_entry call sits AFTER the
     write that produces its file (write_view / the sft view's
     vf.write loop), so the sha is post-write by construction.
  4. Receipt wiring: "views_written" + top-level "sha_convention" land
     in the receipt dict; build_sft_examples returns the views dict.
  5. No new CLI args (args surface unchanged → dispatch fps unaffected).
  6. checked_write PASS on a fixture receipt shaped like the new
     t2-r2w receipt (sha256 keys present + top-level sha_convention —
     the receipt_check contract for sha-bearing receipts).

Run: python src/ember/governance/scripts/t2r2w_viewsha_selftest.py
"""
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

# t2_r2w's module-level launch interlock parses sys.argv at import and
# exits without a gate token — shim argv BEFORE the import. The token
# value is inert here: nothing below builds views or trains.
sys.argv = ["t2r2w_viewsha_selftest.py", "--the lead-gate-token", "selftest"]
# issue2015 exact-local-import:src/ember/governance/scripts/t2_r2w.py
import importlib.util as _ember_b558cbdef3a0f0b5_importlib
import sys as _ember_b558cbdef3a0f0b5_sys
from pathlib import Path as _ember_b558cbdef3a0f0b5_Path
_ember_b558cbdef3a0f0b5_path = _ember_b558cbdef3a0f0b5_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 't2_r2w.py')
if not _ember_b558cbdef3a0f0b5_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/t2_r2w.py')
_ember_b558cbdef3a0f0b5_aliases = ('_ember_issue2015_b558cbdef3a0f0b5', 'scripts.t2_r2w', 't2_r2w')
_ember_b558cbdef3a0f0b5_existing = []
for _ember_b558cbdef3a0f0b5_alias in _ember_b558cbdef3a0f0b5_aliases:
    _ember_b558cbdef3a0f0b5_candidate = _ember_b558cbdef3a0f0b5_sys.modules.get(_ember_b558cbdef3a0f0b5_alias)
    if _ember_b558cbdef3a0f0b5_candidate is not None and all(_ember_b558cbdef3a0f0b5_candidate is not item for item in _ember_b558cbdef3a0f0b5_existing):
        _ember_b558cbdef3a0f0b5_existing.append(_ember_b558cbdef3a0f0b5_candidate)
if len(_ember_b558cbdef3a0f0b5_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/t2_r2w.py')
if _ember_b558cbdef3a0f0b5_existing:
    _ember_b558cbdef3a0f0b5_module = _ember_b558cbdef3a0f0b5_existing[0]
    _ember_b558cbdef3a0f0b5_observed = getattr(_ember_b558cbdef3a0f0b5_module, '__file__', None)
    if _ember_b558cbdef3a0f0b5_observed is None or _ember_b558cbdef3a0f0b5_Path(_ember_b558cbdef3a0f0b5_observed).resolve() != _ember_b558cbdef3a0f0b5_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/t2_r2w.py')
else:
    _ember_b558cbdef3a0f0b5_spec = _ember_b558cbdef3a0f0b5_importlib.spec_from_file_location('_ember_issue2015_b558cbdef3a0f0b5', _ember_b558cbdef3a0f0b5_path)
    if _ember_b558cbdef3a0f0b5_spec is None or _ember_b558cbdef3a0f0b5_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/t2_r2w.py')
    _ember_b558cbdef3a0f0b5_module = _ember_b558cbdef3a0f0b5_importlib.module_from_spec(_ember_b558cbdef3a0f0b5_spec)
    for _ember_b558cbdef3a0f0b5_alias in _ember_b558cbdef3a0f0b5_aliases:
        _ember_b558cbdef3a0f0b5_prior = _ember_b558cbdef3a0f0b5_sys.modules.get(_ember_b558cbdef3a0f0b5_alias)
        if _ember_b558cbdef3a0f0b5_prior is not None and _ember_b558cbdef3a0f0b5_prior is not _ember_b558cbdef3a0f0b5_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/t2_r2w.py')
        _ember_b558cbdef3a0f0b5_sys.modules[_ember_b558cbdef3a0f0b5_alias] = _ember_b558cbdef3a0f0b5_module
    try:
        _ember_b558cbdef3a0f0b5_spec.loader.exec_module(_ember_b558cbdef3a0f0b5_module)
    except BaseException:
        for _ember_b558cbdef3a0f0b5_alias in _ember_b558cbdef3a0f0b5_aliases:
            if _ember_b558cbdef3a0f0b5_sys.modules.get(_ember_b558cbdef3a0f0b5_alias) is _ember_b558cbdef3a0f0b5_module:
                _ember_b558cbdef3a0f0b5_sys.modules.pop(_ember_b558cbdef3a0f0b5_alias, None)
        raise
for _ember_b558cbdef3a0f0b5_alias in _ember_b558cbdef3a0f0b5_aliases:
    _ember_b558cbdef3a0f0b5_prior = _ember_b558cbdef3a0f0b5_sys.modules.get(_ember_b558cbdef3a0f0b5_alias)
    if _ember_b558cbdef3a0f0b5_prior is not None and _ember_b558cbdef3a0f0b5_prior is not _ember_b558cbdef3a0f0b5_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/t2_r2w.py')
    _ember_b558cbdef3a0f0b5_sys.modules[_ember_b558cbdef3a0f0b5_alias] = _ember_b558cbdef3a0f0b5_module
t2_r2w = _ember_b558cbdef3a0f0b5_module
# issue2015 exact-local-import-end:src/ember/governance/scripts/t2_r2w.py  # noqa: E402

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
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py  # noqa: E402


def main():
    checks = {}

    # 1+2. file_sha256 / _view_entry over raw bytes, CRLF preserved
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "view.jsonl")
        payload = b'{"task":"a"}\r\n{"task":"b"}\n'
        with open(p, "wb") as f:
            f.write(payload)
        want = hashlib.sha256(payload).hexdigest()
        assert t2_r2w.file_sha256(p) == want, "file_sha256 != hashlib raw"
        entry = t2_r2w._view_entry(p, 2)
        assert entry == {"path": p, "rows": 2, "sha256": want}
        assert isinstance(entry["rows"], int)
        # rewrite with different bytes -> sha follows the on-disk state
        with open(p, "wb") as f:
            f.write(b'{"task":"a"}\n')
        assert t2_r2w._view_entry(p, 1)["sha256"] == \
            hashlib.sha256(b'{"task":"a"}\n').hexdigest()
    checks["sha_over_raw_bytes"] = True

    src = open(os.path.join(HERE, "t2_r2w.py"), encoding="utf-8").read()

    # 3. sha computed AFTER the write, for every view the runner writes
    build_src = src.split("def build_sft_examples")[1].split("def main")[0]
    pos_wcode_write = build_src.index('write_view(LEDGER, f"{VIEWS}/wcode-r2.jsonl")')
    pos_wcode_entry = build_src.index('views = {"wcode-r2.jsonl"')
    assert pos_wcode_write < pos_wcode_entry, \
        "wcode-r2 sha must be computed after write_view"
    pos_sft_write = build_src.index("vf.write(json.dumps(r)")
    pos_sft_entry = build_src.index('views["wcode-r2-sft.jsonl"] = _view_entry')
    assert pos_sft_write < pos_sft_entry, \
        "sft view sha must be computed after the vf.write loop"
    main_src = src.split("def main():")[1]
    pos_ctrl_write = main_src.index("write_view(CONTROL_POOL")
    pos_ctrl_entry = main_src.index('views["wcode-r2-control.jsonl"] = _view_entry')
    assert pos_ctrl_write < pos_ctrl_entry, \
        "control view sha must be computed after write_view"
    checks["sha_post_write_positions"] = True

    # 4. receipt wiring
    assert '"views_written": views' in main_src
    assert '"sha_convention": SHA_CONVENTION' in main_src
    assert "return examples, counts, info, views" in build_src
    assert "sft_examples, sft_counts, info, views = build_sft_examples" \
        in main_src
    checks["receipt_wiring"] = True

    # 5. args surface unchanged: exactly the 6 pre-eng-150 arguments
    arg_names = ["--the lead-gate-token", "--arm", "--model", "--tag-suffix",
                 "--license-allow", "--dry-run"]
    assert main_src.count("ap.add_argument") == len(arg_names)
    for a in arg_names:
        assert f'"{a}"' in main_src, f"expected arg {a} present"
    checks["args_surface_unchanged"] = True

    # 6. fixture receipt in the new shape passes the receipt contract
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    with tempfile.TemporaryDirectory() as td:
        fixture = {
            "ticket": "NC0-T2-R2W", "arm": "sft", "ts": ts, "round": 2,
            "frontier_filter": {"theta": 0.5, "view_rows_after_theta": 2},
            "views_written": {
                "wcode-r2.jsonl": {"path": "x/wcode-r2.jsonl", "rows": 3,
                                   "sha256": "a" * 64},
                "wcode-r2-sft.jsonl": {"path": "x/wcode-r2-sft.jsonl",
                                       "rows": 2, "sha256": "b" * 64},
            },
            "sha_convention": t2_r2w.SHA_CONVENTION,
            "dry_run": True,
        }
        checked_write(os.path.join(td, "fixture.json"), fixture)
    checks["fixture_receipt_check_pass"] = True

    receipt = {
        "ticket": "ENG40-T2R2W-VIEWSHA-SELFTEST", "ts": ts,
        "issue": "wordingone/ember#150",
        "checks": checks,
        "sha_convention": t2_r2w.SHA_CONVENTION,
        "no_network": True, "no_gpu": True,
        "note": ("append-only: existing certified t2-r2w receipts are "
                 "untouched; views_written lands on the NEXT run"),
    }
    out = os.path.join(REPO, "receipts",
                       f"eng40-t2r2w-viewsha-selftest-{ts}.json")
    checked_write(out, receipt)
    print(json.dumps(receipt, indent=2))
    print(f"[selftest] receipt: {out}")
    print("ENG40_T2R2W_VIEWSHA_SELFTEST_PASS")


if __name__ == "__main__":
    main()
