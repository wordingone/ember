# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Mocked tests for license_spotcheck.py -- no network."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import license_spotcheck  # noqa: E402

ABS_PAGE_CC_BY = b"""<html><div class="abs-license"><a href="http://creativecommons.org/licenses/by/4.0/" title="Rights">
<span>view license</span></a></div></html>"""

ABS_PAGE_PERPETUAL = b"""<html><p>No abs-license block on this page.</p></html>"""


class _FakeResp:
    def __init__(self, data: bytes):
        self._buf = io.BytesIO(data)

    def read(self, size=-1):
        return self._buf.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _manifest(ids):
    return {
        "sha256_manifest": "deadbeef00112233",
        "files": [{"path": f"{i}.pdf"} for i in ids],
    }


class LicenseSpotcheckTests(unittest.TestCase):
    def test_fetch_abs_license_extracts_cc_url(self):
        opener = lambda req, timeout=30: _FakeResp(ABS_PAGE_CC_BY)
        result = license_spotcheck.fetch_abs_license("2401.09400v1", opener=opener)
        self.assertEqual(result, "http://creativecommons.org/licenses/by/4.0/")

    def test_fetch_abs_license_returns_none_when_no_license_block(self):
        opener = lambda req, timeout=30: _FakeResp(ABS_PAGE_PERPETUAL)
        result = license_spotcheck.fetch_abs_license("2401.09400v1", opener=opener)
        self.assertIsNone(result)

    def test_sample_ids_is_deterministic_for_same_seed(self):
        manifest = _manifest([f"230{i}.0000{i}v1" for i in range(10)])
        a = license_spotcheck.sample_ids(manifest, 5, seed=42)
        b = license_spotcheck.sample_ids(manifest, 5, seed=42)
        self.assertEqual(a, b)
        self.assertEqual(len(a), 5)

    def test_run_spot_check_all_match(self):
        with tempfile.TemporaryDirectory() as td:
            manifest_path = Path(td) / "manifest.json"
            manifest_path.write_text(
                json.dumps(_manifest([f"230{i}.0000{i}v1" for i in range(5)])), encoding="utf-8"
            )
            opener = lambda req, timeout=30: _FakeResp(ABS_PAGE_CC_BY)
            report = license_spotcheck.run_spot_check(
                manifest_path, sample_size=3, opener=opener, sleeper=lambda s: None
            )
            self.assertTrue(report["all_match"])
            self.assertEqual(report["sample_size"], 3)
            self.assertEqual(len(report["results"]), 3)
            for r in report["results"]:
                self.assertTrue(r["match"])
                self.assertIsNone(r["error"])

    def test_run_spot_check_detects_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            manifest_path = Path(td) / "manifest.json"
            manifest_path.write_text(
                json.dumps(_manifest([f"230{i}.0000{i}v1" for i in range(3)])), encoding="utf-8"
            )
            opener = lambda req, timeout=30: _FakeResp(ABS_PAGE_PERPETUAL)
            report = license_spotcheck.run_spot_check(
                manifest_path, sample_size=3, opener=opener, sleeper=lambda s: None
            )
            self.assertFalse(report["all_match"])
            self.assertTrue(all(not r["match"] for r in report["results"]))

    def test_seed_defaults_from_manifest_hash_reproducibly(self):
        with tempfile.TemporaryDirectory() as td:
            manifest_path = Path(td) / "manifest.json"
            manifest_path.write_text(
                json.dumps(_manifest([f"230{i}.0000{i}v1" for i in range(5)])), encoding="utf-8"
            )
            opener = lambda req, timeout=30: _FakeResp(ABS_PAGE_CC_BY)
            r1 = license_spotcheck.run_spot_check(manifest_path, sample_size=3, opener=opener, sleeper=lambda s: None)
            r2 = license_spotcheck.run_spot_check(manifest_path, sample_size=3, opener=opener, sleeper=lambda s: None)
            self.assertEqual(r1["seed"], r2["seed"])
            self.assertEqual([x["arxiv_id"] for x in r1["results"]], [x["arxiv_id"] for x in r2["results"]])


if __name__ == "__main__":
    unittest.main()
