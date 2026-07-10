"""Mocked test for hf_fetch.py -- no network. Patches HfApi/snapshot_download."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hf_fetch
import receipt as rcpt


class FakeHfApi:
    def __init__(self, sha="abcdef1234567890", license_str="mit"):
        self._sha = sha
        self._license = license_str

    def dataset_info(self, repo_id, revision=None):
        return SimpleNamespace(sha=self._sha, card_data={"license": self._license})

    def model_info(self, repo_id, revision=None):
        return self.dataset_info(repo_id, revision)


def _fake_snapshot_download(**kwargs):
    local_dir = Path(kwargs["local_dir"])
    local_dir.mkdir(parents=True, exist_ok=True)
    (local_dir / "data.txt").write_text("hello corpus\n", encoding="utf-8")
    (local_dir / "sub").mkdir(exist_ok=True)
    (local_dir / "sub" / "more.txt").write_text("more data\n", encoding="utf-8")
    return str(local_dir)


class HfFetchMockedTests(unittest.TestCase):
    def test_fetch_writes_receipt_and_manifest_row(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "hfdata"
            args = hf_fetch.build_parser().parse_args(
                ["org/dataset-name", "--dest", str(dest), "--dataset"]
            )
            with patch.object(hf_fetch, "HfApi", return_value=FakeHfApi()), \
                 patch.object(hf_fetch, "snapshot_download", side_effect=_fake_snapshot_download):
                receipt_path = hf_fetch.fetch(args)

            self.assertTrue(receipt_path.is_file())
            data = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(data["source"], "huggingface")
            self.assertEqual(data["source_id"], "org/dataset-name")
            self.assertEqual(data["license"], "mit")
            self.assertEqual(data["revision"], "abcdef1234567890")
            self.assertEqual(len(data["files"]), 2)
            self.assertEqual(data["total_bytes"], sum(f["bytes"] for f in data["files"]))

            manifest_lines = (dest / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(manifest_lines), 2)
            row = json.loads(manifest_lines[0])
            self.assertEqual(row["source_url"], "https://huggingface.co/datasets/org/dataset-name")
            self.assertEqual(row["license"], "mit")

    def test_fetch_blocks_on_unverified_license_without_flag(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "hfdata"
            args = hf_fetch.build_parser().parse_args(["org/name", "--dest", str(dest)])
            with patch.object(hf_fetch, "HfApi", return_value=FakeHfApi(license_str=None)), \
                 patch.object(hf_fetch, "snapshot_download", side_effect=_fake_snapshot_download):
                with self.assertRaises(rcpt.UnverifiedLicenseError):
                    hf_fetch.fetch(args)

    def test_main_prints_receipt_line_on_success(self):
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "hfdata"
            argv = ["org/dataset-name", "--dest", str(dest)]
            with patch.object(hf_fetch, "HfApi", return_value=FakeHfApi()), \
                 patch.object(hf_fetch, "snapshot_download", side_effect=_fake_snapshot_download):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    code = hf_fetch.main(argv)
            self.assertEqual(code, 0)
            self.assertTrue(buf.getvalue().strip().startswith("RECEIPT "))


if __name__ == "__main__":
    unittest.main()
