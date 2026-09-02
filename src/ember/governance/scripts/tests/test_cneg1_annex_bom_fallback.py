#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""TDD: C(-1)'s spend-annex reader must survive a BOM'd newest file, and a
genuinely unparseable newest file must fall back to the next-newest
PARSEABLE annex instead of blinding the probe to all annex coverage.

Incident (2026-07-07): PR #337 shipped a new "newest" spend-annex file
(spend-annex-20260707T105959Z.json) written with a leading UTF-8 BOM. The
prior _newest_spend_annex() opened only the single newest file with strict
encoding="utf-8"; json.load() raised on the BOM, the bare except swallowed
it and returned ({}, None) -- treating the annex as totally ABSENT. Net
effect: C(-1)'s undeclared-receipt count regressed from 18/260 to 229/261
on the very next board run, because every OLDER, perfectly valid annex
file was also discarded along with the one bad file.

Two independent assertions this test locks in:
  (a) a BOM'd file parses cleanly under the new reader (utf-8-sig strips a
      BOM when present, no-ops when absent).
  (b) a newest file that is unparseable even with utf-8-sig (truncated/
      invalid JSON) does not blind the probe -- it falls back to the next-
      newest file that DOES parse.
"""

import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO_ROOT)

_SPEC = importlib.util.spec_from_file_location(
    "test_c_neg1_probe",
    os.path.join(REPO_ROOT, "scripts", "ember_totality", "test_c_neg1.py"),
)
cneg1 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cneg1)


def _write_annex(path, rows, bom=False):
    body = json.dumps({"rows": rows}, indent=2)
    data = body.encode("utf-8")
    if bom:
        data = b"\xef\xbb\xbf" + data
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


def test_bom_annex_parses():
    """A BOM'd newest annex file must parse and its rows must be usable --
    not treated as malformed/absent."""
    with tempfile.TemporaryDirectory() as tmpdir:
        annex_dir = os.path.join(tmpdir, "receipts", "spend-annex")
        _write_annex(
            os.path.join(annex_dir, "spend-annex-20260707T105959Z.json"),
            rows=[{"path": "receipts/some-decisive-receipt.json",
                   "evidence_class": "script_scanned_clean"}],
            bom=True,
        )

        by_path, used_path = cneg1._newest_spend_annex(tmpdir)

        assert used_path is not None, "BOM'd annex was treated as absent"
        assert "receipts/some-decisive-receipt.json" in by_path, (
            f"expected row missing from parsed annex: {by_path!r}"
        )
        print("[PASS] BOM'd newest annex file parses under the utf-8-sig reader")


def test_unparseable_newest_falls_back_to_older_parseable():
    """A newest file that is genuinely unparseable (bad JSON, not just a
    BOM) must not blind the probe to an older, valid annex."""
    with tempfile.TemporaryDirectory() as tmpdir:
        annex_dir = os.path.join(tmpdir, "receipts", "spend-annex")

        # Older, valid annex -- this is the one the fallback must recover.
        _write_annex(
            os.path.join(annex_dir, "spend-annex-20260707T094500Z.json"),
            rows=[{"path": "receipts/older-covered-receipt.json",
                   "evidence_class": "declared"}],
            bom=False,
        )

        # Newest file: lexicographically sorts after the one above, and is
        # genuinely broken (truncated JSON) -- not recoverable by any
        # encoding fix, unlike the BOM case above.
        newest_path = os.path.join(annex_dir, "spend-annex-20260707T105959Z.json")
        os.makedirs(annex_dir, exist_ok=True)
        with open(newest_path, "wb") as fh:
            fh.write(b'{"rows": [ { "path": "truncated mid-object"')

        by_path, used_path = cneg1._newest_spend_annex(tmpdir)

        # The path returned must be the OLDER file (094500Z), not the broken
        # newest one (105959Z) -- the walk must have skipped it.
        assert used_path is not None and "094500Z" in used_path, (
            f"fallback did not select the older parseable annex: {used_path!r}"
        )
        assert "receipts/older-covered-receipt.json" in by_path, (
            f"older annex's own coverage was lost during fallback: {by_path!r}"
        )
        print("[PASS] unparseable newest annex falls back to the next-newest parseable file")


if __name__ == "__main__":
    test_bom_annex_parses()
    test_unparseable_newest_falls_back_to_older_parseable()
    print("\n[SUCCESS] All tests passed!")
