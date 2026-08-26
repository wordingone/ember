# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Mocked test for hf_fetch.py -- no network. Patches HfApi/snapshot_download."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hf_fetch
from tools.corpus_connectors import receipt as rcpt


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
            self.assertEqual(data["license"], "MIT")
            self.assertEqual(data["revision"], "abcdef1234567890")
            self.assertEqual(len(data["files"]), 2)
            self.assertEqual(data["total_bytes"], sum(f["bytes"] for f in data["files"]))

            manifest_lines = (dest / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(manifest_lines), 2)
            row = json.loads(manifest_lines[0])
            self.assertEqual(row["source_url"], "https://huggingface.co/datasets/org/dataset-name")
            self.assertEqual(row["license"], "MIT")

    def test_huggingface_license_tag_is_canonicalized_only_by_closed_map(self):
        self.assertEqual(hf_fetch._canonical_hf_license("apache-2.0"), "Apache-2.0")
        self.assertEqual(hf_fetch._canonical_hf_license("cc-by-4.0"), "CC-BY-4.0")
        self.assertEqual(hf_fetch._canonical_hf_license("mit"), "MIT")
        self.assertEqual(hf_fetch._canonical_hf_license("unknown-future-tag"), "unknown-future-tag")

    def test_fetch_blocks_on_unverified_license_without_flag(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "hfdata"
            args = hf_fetch.build_parser().parse_args(["org/name", "--dest", str(dest)])
            with patch.object(hf_fetch, "HfApi", return_value=FakeHfApi(license_str=None)), \
                 patch.object(hf_fetch, "snapshot_download", side_effect=_fake_snapshot_download):
                with self.assertRaises(rcpt.UnverifiedLicenseError):
                    hf_fetch.fetch(args)

    def test_no_token_omits_token_kwarg_entirely_unchanged_default(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "hfdata"
            args = hf_fetch.build_parser().parse_args(["org/name", "--dest", str(dest)])
            with patch.object(hf_fetch, "HfApi") as mock_hfapi_cls, \
                 patch.object(hf_fetch, "snapshot_download") as mock_snapshot:
                mock_hfapi_cls.return_value = FakeHfApi()
                mock_snapshot.side_effect = _fake_snapshot_download
                hf_fetch.fetch(args)

            mock_hfapi_cls.assert_called_once_with()
            _, snapshot_kwargs = mock_snapshot.call_args
            self.assertNotIn("token", snapshot_kwargs)

    def test_cli_hf_token_forwarded_to_hfapi_and_snapshot_download(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "hfdata"
            args = hf_fetch.build_parser().parse_args(
                ["org/name", "--dest", str(dest), "--hf-token", "secret-cli-token"]
            )
            with patch.object(hf_fetch, "HfApi") as mock_hfapi_cls, \
                 patch.object(hf_fetch, "snapshot_download") as mock_snapshot:
                mock_hfapi_cls.return_value = FakeHfApi()
                mock_snapshot.side_effect = _fake_snapshot_download
                hf_fetch.fetch(args)

            mock_hfapi_cls.assert_called_once_with(token="secret-cli-token")
            _, snapshot_kwargs = mock_snapshot.call_args
            self.assertEqual(snapshot_kwargs.get("token"), "secret-cli-token")

    def test_env_hf_token_used_when_cli_flag_omitted(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "hfdata"
            args = hf_fetch.build_parser().parse_args(["org/name", "--dest", str(dest)])
            with patch.object(hf_fetch, "HfApi") as mock_hfapi_cls, \
                 patch.object(hf_fetch, "snapshot_download") as mock_snapshot:
                mock_hfapi_cls.return_value = FakeHfApi()
                mock_snapshot.side_effect = _fake_snapshot_download
                with mock.patch.dict(os.environ, {"HF_TOKEN": "secret-env-token"}):
                    hf_fetch.fetch(args)

            mock_hfapi_cls.assert_called_once_with(token="secret-env-token")

    def test_license_override_applies_when_metadata_has_no_license(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "hfdata"
            args = hf_fetch.build_parser().parse_args(
                [
                    "org/name", "--dest", str(dest),
                    "--license", "CC0-1.0",
                    "--license-evidence", "lead confirmed via repo issue #42",
                ]
            )
            with patch.object(hf_fetch, "HfApi", return_value=FakeHfApi(license_str=None)), \
                 patch.object(hf_fetch, "snapshot_download", side_effect=_fake_snapshot_download):
                receipt_path = hf_fetch.fetch(args)
            data = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(data["license"], "CC0-1.0")
            self.assertEqual(data["license_evidence"], "lead confirmed via repo issue #42")

    def test_license_override_ignored_when_metadata_already_resolves_a_license(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "hfdata"
            args = hf_fetch.build_parser().parse_args(
                [
                    "org/name", "--dest", str(dest),
                    "--license", "CC0-1.0",
                    "--license-evidence", "lead confirmed via repo issue #42",
                ]
            )
            with patch.object(hf_fetch, "HfApi", return_value=FakeHfApi(license_str="mit")), \
                 patch.object(hf_fetch, "snapshot_download", side_effect=_fake_snapshot_download):
                receipt_path = hf_fetch.fetch(args)
            data = json.loads(receipt_path.read_text(encoding="utf-8"))
            # metadata's own resolved license wins -- the CLI override is never
            # silently applied on top of a license the card card already states.
            self.assertEqual(data["license"], "MIT")
            self.assertEqual(data["license_evidence"], "HuggingFace repo card metadata `license` field")

    def test_license_and_evidence_must_be_supplied_together(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "hfdata"
            args = hf_fetch.build_parser().parse_args(
                ["org/name", "--dest", str(dest), "--license", "CC0-1.0"]
            )
            with patch.object(hf_fetch, "HfApi", return_value=FakeHfApi(license_str=None)), \
                 patch.object(hf_fetch, "snapshot_download", side_effect=_fake_snapshot_download):
                with self.assertRaises(rcpt.BlockedError):
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
