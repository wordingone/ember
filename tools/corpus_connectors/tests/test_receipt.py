# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Offline unit tests for receipt.py -- schema, hashing, fail-closed behavior.
No network. Run from anywhere: this file inserts the package dir onto
sys.path so `import receipt` resolves regardless of cwd."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import receipt as rcpt


def _mk_receipt(dest_root: Path, **overrides) -> rcpt.Receipt:
    files = overrides.pop("files", [rcpt.FileEntry(path="a.txt", bytes=3, sha256="deadbeef")])
    defaults = dict(
        source="http",
        source_id="https://example.org/a.txt",
        canonical_url="https://example.org/a.txt",
        license="CC0-1.0",
        license_evidence="test fixture",
        revision=None,
        files=files,
        fetched_at="2026-07-09T00:00:00Z",
        connector=rcpt.ConnectorInfo(name="test_connector"),
        dest_root=str(dest_root),
        notes="",
    )
    defaults.update(overrides)
    return rcpt.Receipt(**defaults)


class HashingTests(unittest.TestCase):
    def test_sha256_file_matches_hashlib(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "f.bin"
            data = b"hello world" * 100
            p.write_bytes(data)
            self.assertEqual(rcpt.sha256_file(p), hashlib.sha256(data).hexdigest())

    def test_sha256_of_manifest_is_order_independent(self):
        hashes = ["bbb", "aaa", "ccc"]
        self.assertEqual(rcpt.sha256_of_manifest(hashes), rcpt.sha256_of_manifest(list(reversed(hashes))))
        expected = hashlib.sha256("\n".join(sorted(hashes)).encode("utf-8")).hexdigest()
        self.assertEqual(rcpt.sha256_of_manifest(hashes), expected)

    def test_safe_key_strips_unsafe_chars(self):
        self.assertEqual(rcpt.safe_key("org/name:v1 (beta)"), "org-name-v1-beta")
        self.assertEqual(rcpt.safe_key("###"), "source")


class ReceiptSchemaTests(unittest.TestCase):
    def test_to_dict_has_frozen_schema_fields(self):
        with tempfile.TemporaryDirectory() as td:
            r = _mk_receipt(Path(td))
            d = r.to_dict()
            expected_keys = {
                "schema", "source", "source_id", "canonical_url", "license",
                "license_evidence", "revision", "files", "total_bytes",
                "sha256_manifest", "fetched_at", "connector", "l3_statement",
                "dest_root", "notes",
            }
            self.assertEqual(set(d.keys()), expected_keys)
            self.assertEqual(d["schema"], "corpus-connector-receipt-v1")
            self.assertIn("fetch-only", d["l3_statement"])

    def test_total_bytes_and_sha256_manifest_derived_from_files(self):
        with tempfile.TemporaryDirectory() as td:
            files = [
                rcpt.FileEntry(path="a.txt", bytes=10, sha256="h1"),
                rcpt.FileEntry(path="b.txt", bytes=20, sha256="h2"),
            ]
            r = _mk_receipt(Path(td), files=files)
            self.assertEqual(r.total_bytes, 30)
            self.assertEqual(r.sha256_manifest, rcpt.sha256_of_manifest(["h1", "h2"]))


class RelativeFilesUnderTests(unittest.TestCase):
    def test_excludes_manifests_and_dotcache_dirs_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")
            manifests_dir = root / "_manifests"
            manifests_dir.mkdir()
            (manifests_dir / "20260709T000000Z-x.json").write_text("{}", encoding="utf-8")
            # huggingface_hub client bookkeeping under a .cache/ subtree of
            # the destination -- must never land in files[].
            hf_cache_dir = root / ".cache" / "huggingface" / "download"
            hf_cache_dir.mkdir(parents=True)
            (hf_cache_dir / "some-blob.json").write_text("{}", encoding="utf-8")
            (root / ".cache" / "CACHEDIR.TAG").write_text("Signature: 8a477f597d28d172789f06886806bc55", encoding="utf-8")

            rel = rcpt.relative_files_under(root)
            rel_strs = {p.as_posix() for p in rel}
            self.assertEqual(rel_strs, {"data.csv"})


class WriteReceiptTests(unittest.TestCase):
    def test_write_receipt_creates_manifest_json(self):
        with tempfile.TemporaryDirectory() as td:
            dest_root = Path(td)
            r = _mk_receipt(dest_root)
            out_path = rcpt.write_receipt(r, dest_root)
            self.assertTrue(out_path.is_file())
            self.assertEqual(out_path.parent.name, "_manifests")
            loaded = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["source_id"], r.source_id)
            self.assertEqual(loaded["license"], "CC0-1.0")

    def test_write_receipt_raises_dest_collision_on_existing_path(self):
        with tempfile.TemporaryDirectory() as td:
            dest_root = Path(td)
            r = _mk_receipt(dest_root)
            fixed_ts = "20260709T000000Z"
            orig = rcpt.utc_stamp_compact
            rcpt.utc_stamp_compact = lambda: fixed_ts
            try:
                out_path = rcpt.write_receipt(r, dest_root)
                with self.assertRaises(rcpt.DestCollisionError):
                    rcpt.write_receipt(r, dest_root)
            finally:
                rcpt.utc_stamp_compact = orig

    def test_write_receipt_fail_closed_when_manifests_dir_unwritable(self):
        with tempfile.TemporaryDirectory() as td:
            dest_root = Path(td)
            # Occupy the _manifests path with a FILE so mkdir(parents=True) fails.
            (dest_root / "_manifests").write_text("blocker", encoding="utf-8")
            r = _mk_receipt(dest_root)
            with self.assertRaises(rcpt.ReceiptWriteError):
                rcpt.write_receipt(r, dest_root)


class ManifestCompatibilityTests(unittest.TestCase):
    def test_to_manifest_row_maps_legacy_template_fields(self):
        with tempfile.TemporaryDirectory() as td:
            files = [rcpt.FileEntry(path="a.txt", bytes=5, sha256="h1")]
            r = _mk_receipt(Path(td), files=files, notes="human note")
            rows = rcpt.to_manifest_row(r)
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(
                set(row.keys()),
                {"source_url", "sha256", "bytes", "license", "human_provenance_basis", "fetched_ts", "selection_rule"},
            )
            self.assertEqual(row["source_url"], r.canonical_url)
            self.assertEqual(row["sha256"], "h1")
            self.assertEqual(row["bytes"], 5)
            self.assertEqual(row["license"], "CC0-1.0")
            self.assertEqual(row["human_provenance_basis"], "human note")
            self.assertEqual(row["fetched_ts"], r.fetched_at)
            self.assertEqual(row["selection_rule"], r.source_id)

    def test_to_manifest_row_default_provenance_when_no_notes(self):
        with tempfile.TemporaryDirectory() as td:
            r = _mk_receipt(Path(td), notes="")
            row = rcpt.to_manifest_row(r)[0]
            self.assertIn("machine-fetched", row["human_provenance_basis"])

    def test_append_manifest_rows_appends_jsonl(self):
        with tempfile.TemporaryDirectory() as td:
            dest_root = Path(td)
            rows1 = [{"source_url": "u1", "sha256": "h1", "bytes": 1, "license": "MIT",
                      "human_provenance_basis": "x", "fetched_ts": "t1", "selection_rule": "s1"}]
            rows2 = [{"source_url": "u2", "sha256": "h2", "bytes": 2, "license": "MIT",
                      "human_provenance_basis": "x", "fetched_ts": "t2", "selection_rule": "s2"}]
            rcpt.append_manifest_rows(dest_root, rows1)
            rcpt.append_manifest_rows(dest_root, rows2)
            lines = (dest_root / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0])["source_url"], "u1")
            self.assertEqual(json.loads(lines[1])["source_url"], "u2")


class CommitReceiptFailClosedTests(unittest.TestCase):
    def test_commit_receipt_cleans_up_downloaded_files_on_failure(self):
        with tempfile.TemporaryDirectory() as td:
            dest_root = Path(td)
            downloaded = dest_root / "payload.bin"
            downloaded.write_bytes(b"data")
            self.assertTrue(downloaded.is_file())

            r = _mk_receipt(dest_root)

            def _boom(*a, **kw):
                raise rcpt.ReceiptWriteError("simulated failure")

            orig = rcpt.write_receipt
            rcpt.write_receipt = _boom
            try:
                with self.assertRaises(rcpt.ReceiptWriteError):
                    rcpt.commit_receipt(r, dest_root, [downloaded])
            finally:
                rcpt.write_receipt = orig
            self.assertFalse(downloaded.exists(), "fail-closed: downloaded file must be removed on receipt-write failure")

    def test_commit_receipt_succeeds_and_writes_both_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            dest_root = Path(td)
            downloaded = dest_root / "a.txt"
            downloaded.write_bytes(b"xyz")
            files = [rcpt.FileEntry(path="a.txt", bytes=3, sha256=rcpt.sha256_file(downloaded))]
            r = _mk_receipt(dest_root, files=files)
            receipt_path = rcpt.commit_receipt(r, dest_root, [downloaded])
            self.assertTrue(receipt_path.is_file())
            self.assertTrue((dest_root / "manifest.jsonl").is_file())
            self.assertTrue(downloaded.exists(), "success path must not delete the downloaded file")


class LicenseGateTests(unittest.TestCase):
    def test_gate_license_blocks_unverified_by_default(self):
        with self.assertRaises(rcpt.UnverifiedLicenseError):
            rcpt.gate_license(rcpt.UNVERIFIED, allow_unverified=False)

    def test_gate_license_allows_unverified_when_flagged(self):
        rcpt.gate_license(rcpt.UNVERIFIED, allow_unverified=True)  # must not raise

    def test_gate_license_never_blocks_known_license(self):
        rcpt.gate_license("MIT", allow_unverified=False)  # must not raise


class KaggleCredentialTests(unittest.TestCase):
    def test_credentials_present_via_env_vars(self):
        env = {"KAGGLE_USERNAME": "u", "KAGGLE_KEY": "k"}
        self.assertTrue(rcpt.kaggle_credentials_present(env))

    def test_credentials_absent_when_nothing_set(self):
        with tempfile.TemporaryDirectory() as td:
            env = {"KAGGLE_CONFIG_DIR": td}
            self.assertFalse(rcpt.kaggle_credentials_present(env))

    def test_credentials_present_via_config_file(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "kaggle.json").write_text("{}", encoding="utf-8")
            env = {"KAGGLE_CONFIG_DIR": td}
            self.assertTrue(rcpt.kaggle_credentials_present(env))


class DownloadUrlTests(unittest.TestCase):
    class _FakeResp:
        def __init__(self, data: bytes):
            self._buf = io.BytesIO(data)

        def read(self, size=-1):
            return self._buf.read(size)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def test_download_url_writes_file_and_returns_hash(self):
        payload = b"payload-bytes"

        def opener(request, timeout=60):
            return self._FakeResp(payload)

        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "out.bin"
            size, digest = rcpt.download_url("https://example.org/x", dest, opener=opener)
            self.assertEqual(size, len(payload))
            self.assertEqual(digest, hashlib.sha256(payload).hexdigest())
            self.assertEqual(dest.read_bytes(), payload)
            self.assertFalse(dest.with_name(dest.name + ".partial").exists())

    def test_download_url_hash_mismatch_cleans_up_partial(self):
        payload = b"payload-bytes"

        def opener(request, timeout=60):
            return self._FakeResp(payload)

        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "out.bin"
            with self.assertRaises(rcpt.HashMismatchError):
                rcpt.download_url("https://example.org/x", dest, expected_sha256="0" * 64, opener=opener)
            self.assertFalse(dest.exists())
            self.assertFalse(dest.with_name(dest.name + ".partial").exists())

    def test_download_url_refuses_dest_collision(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "out.bin"
            dest.write_bytes(b"already here")
            with self.assertRaises(rcpt.DestCollisionError):
                rcpt.download_url("https://example.org/x", dest, opener=lambda *a, **kw: None)

    def test_download_url_caps_oversized_stream(self):
        """Opener returning unbounded/looping stream raises DownloadTooLargeError
        and leaves no .partial file behind."""
        class _LoopingResp:
            def __init__(self):
                self._count = 0

            def read(self, size=-1):
                # Infinite stream: always return data, never EOF
                self._count += 1
                return b"x" * (1024 * 1024)  # 1 MiB per chunk

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def opener(request, timeout=60):
            return _LoopingResp()

        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "out.bin"
            # Set a small cap to trigger the error quickly
            small_cap = 5 * 1024 * 1024  # 5 MiB
            with self.assertRaises(rcpt.DownloadTooLargeError):
                rcpt.download_url("https://example.org/x", dest, max_bytes=small_cap, opener=opener)
            # Verify no .partial left behind
            partial = dest.with_name(dest.name + ".partial")
            self.assertFalse(partial.exists(), "runaway download must not leave .partial behind")


class RunCliContractTests(unittest.TestCase):
    def _capture(self, fn):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = rcpt.run_cli(fn)
        return code, buf.getvalue().strip()

    def test_run_cli_success_prints_receipt_line(self):
        fake_path = Path("some_dir") / "fake-receipt.json"
        code, out = self._capture(lambda: fake_path)
        self.assertEqual(code, 0)
        self.assertEqual(out, f"RECEIPT {fake_path}")

    def test_run_cli_blocked_error_prints_blocked_line(self):
        def _fn():
            raise rcpt.BlockedError("credentials absent")

        code, out = self._capture(_fn)
        self.assertEqual(code, 1)
        self.assertEqual(out, "BLOCKED credentials absent")

    def test_run_cli_unexpected_exception_is_fail_closed(self):
        def _fn():
            raise ValueError("boom")

        code, out = self._capture(_fn)
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("BLOCKED unexpected error:"))


if __name__ == "__main__":
    unittest.main()
