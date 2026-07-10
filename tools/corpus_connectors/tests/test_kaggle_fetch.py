"""Mocked test for kaggle_fetch.py -- no network, no real kaggle CLI. Fakes the
subprocess runner and the credential-presence check."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import kaggle_fetch
import receipt as rcpt


def _arg_after(cmd, flag):
    return cmd[cmd.index(flag) + 1]


def _fake_runner(cmd):
    if "metadata" in cmd:
        meta_dir = Path(_arg_after(cmd, "-p"))
        meta_dir.mkdir(parents=True, exist_ok=True)
        (meta_dir / "dataset-metadata.json").write_text(
            json.dumps({"licenses": [{"name": "CC0-1.0"}]}), encoding="utf-8"
        )
        return SimpleNamespace(returncode=0, stderr="")
    if "download" in cmd:
        dest_dir = Path(_arg_after(cmd, "-p"))
        dest_dir.mkdir(parents=True, exist_ok=True)
        zpath = dest_dir / "bundle.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("rows.csv", "a,b\n1,2\n")
        return SimpleNamespace(returncode=0, stderr="")
    raise AssertionError(f"unexpected kaggle command: {cmd}")


def _failing_metadata_runner(cmd):
    if "metadata" in cmd:
        return SimpleNamespace(returncode=1, stderr="no internet")
    raise AssertionError(f"unexpected kaggle command: {cmd}")


class KaggleFetchMockedTests(unittest.TestCase):
    def test_fetch_writes_receipt_when_credentials_present(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "kagdata"
            args = kaggle_fetch.build_parser().parse_args(["owner/dataset", "--dest", str(dest)])
            receipt_path = kaggle_fetch.fetch(args, runner=_fake_runner, creds_present=lambda: True)
            data = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(data["source"], "kaggle")
            self.assertEqual(data["license"], "CC0-1.0")
            self.assertEqual(len(data["files"]), 1)
            self.assertTrue((dest / "rows.csv").is_file())

    def test_fetch_blocks_when_credentials_absent(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "kagdata"
            args = kaggle_fetch.build_parser().parse_args(["owner/dataset", "--dest", str(dest)])
            with self.assertRaises(rcpt.MissingCredentialsError):
                kaggle_fetch.fetch(args, runner=_fake_runner, creds_present=lambda: False)

    def test_fetch_blocks_on_metadata_command_failure(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "kagdata"
            args = kaggle_fetch.build_parser().parse_args(["owner/dataset", "--dest", str(dest)])
            with self.assertRaises(rcpt.UnverifiedLicenseError):
                kaggle_fetch.fetch(args, runner=_failing_metadata_runner, creds_present=lambda: True)

    def test_main_blocked_line_when_credentials_absent(self):
        import contextlib
        import io
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "kagdata"
            argv = ["owner/dataset", "--dest", str(dest)]
            args = kaggle_fetch.build_parser().parse_args(argv)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = rcpt.run_cli(lambda: kaggle_fetch.fetch(args, runner=_fake_runner, creds_present=lambda: False))
            self.assertEqual(code, 1)
            self.assertTrue(buf.getvalue().strip().startswith("BLOCKED"))


if __name__ == "__main__":
    unittest.main()
