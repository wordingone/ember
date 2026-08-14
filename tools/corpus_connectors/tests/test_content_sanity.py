# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""RED-first tests for the content-sanity gate (soft-404 defence).

Fixtures are the real payload shapes observed on 2026-08-14 while executing the
issue #1720 acquisition rows: openstax.org, itl.nist.gov and llvm.org all answer
HTTP 200 with an HTML body for URLs that name a binary artifact, so neither the
status code nor the URL alone distinguishes a hit from a miss.
"""
from __future__ import annotations

import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import http_fetch
import receipt as rcpt
import wave_manifest


# Byte-for-byte prefix of what https://openstax.org/exports/precalculus.pdf
# actually served: a 12,410-byte SPA shell, not a PDF.
OPENSTAX_SOFT_404 = b'<!doctype html><html lang="en-US"><head><title>OpenStax</title>' + b"x" * 500
NIST_SOFT_404 = b"<HTML>\n   <HEAD>\n   <TITLE>NIST/SEMATECH</TITLE>" + b"x" * 500
REAL_PDF = b"%PDF-1.7\n" + b"x" * 5000
REAL_ZIP = b"PK\x03\x04" + b"x" * 5000
REAL_GZIP = b"\x1f\x8b\x08\x00" + b"x" * 5000


class _FakeResp:
    def __init__(self, data: bytes):
        self._buf = io.BytesIO(data)

    def read(self, size=-1):
        return self._buf.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener_for(payload: bytes):
    def _opener(request, timeout=60):
        return _FakeResp(payload)

    return _opener


def _args(url: str, dest: Path, *extra: str):
    return http_fetch.build_parser().parse_args(
        [url, "--license", "CC-BY-4.0", "--license-evidence", "test evidence", "--dest", str(dest), *extra]
    )


class ContentSanityTests(unittest.TestCase):
    def test_html_served_for_pdf_url_is_blocked(self):
        """The exact 2026-08-14 openstax-math defect: 200 OK, HTML body, .pdf URL."""
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "d"
            args = _args("https://openstax.org/exports/precalculus.pdf", dest)
            with self.assertRaises(rcpt.ContentTypeMismatchError):
                http_fetch.fetch(args, opener=_opener_for(OPENSTAX_SOFT_404))

    def test_blocked_mismatch_leaves_no_file_and_no_receipt(self):
        """Fail closed: a refused fetch must not leave bytes or a receipt behind."""
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "d"
            args = _args("https://openstax.org/exports/precalculus.pdf", dest)
            with self.assertRaises(rcpt.ContentTypeMismatchError):
                http_fetch.fetch(args, opener=_opener_for(OPENSTAX_SOFT_404))
            self.assertFalse((dest / "precalculus.pdf").exists())
            self.assertFalse(list(dest.glob("_manifests/*.json")))

    def test_html_served_for_zip_url_is_blocked(self):
        """itl.nist.gov/div898/handbook/handbook.zip -> 200 text/html."""
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "d"
            args = _args("https://www.itl.nist.gov/div898/handbook/handbook.zip", dest)
            with self.assertRaises(rcpt.ContentTypeMismatchError):
                http_fetch.fetch(args, opener=_opener_for(NIST_SOFT_404))

    def test_real_pdf_passes(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "d"
            args = _args("https://example.org/book.pdf", dest)
            self.assertTrue(http_fetch.fetch(args, opener=_opener_for(REAL_PDF)).is_file())

    def test_real_zip_and_gzip_pass(self):
        for url, payload in (
            ("https://example.org/docs.zip", REAL_ZIP),
            ("https://example.org/src.tar.gz", REAL_GZIP),
        ):
            with tempfile.TemporaryDirectory() as td:
                dest = Path(td) / "d"
                self.assertTrue(http_fetch.fetch(_args(url, dest), opener=_opener_for(payload)).is_file())

    def test_html_url_serving_html_passes(self):
        """An .htm URL serving HTML is not a content mismatch -- that is the
        entry-page problem, which requires_resolution handles, not this gate."""
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "d"
            args = _args("https://www.itl.nist.gov/div898/handbook/index.htm", dest)
            self.assertTrue(http_fetch.fetch(args, opener=_opener_for(NIST_SOFT_404)).is_file())

    def test_unidentifiable_payload_passes(self):
        """No false positives: content we cannot positively type must not block."""
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "d"
            args = _args("https://example.org/book.pdf", dest)
            self.assertTrue(http_fetch.fetch(args, opener=_opener_for(b"textbook contents")).is_file())

    def test_escape_hatch_allows_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "d"
            args = _args("https://openstax.org/exports/precalculus.pdf", dest, "--allow-content-mismatch")
            receipt_path = http_fetch.fetch(args, opener=_opener_for(OPENSTAX_SOFT_404))
            self.assertTrue(receipt_path.is_file())


class SniffTests(unittest.TestCase):
    def test_sniffer_identifies_known_shapes(self):
        cases = [
            (OPENSTAX_SOFT_404, "html"),
            (NIST_SOFT_404, "html"),
            (b'\n\n<!DOCTYPE html', "html"),
            (REAL_PDF, "pdf"),
            (REAL_ZIP, "zip"),
            (REAL_GZIP, "gzip"),
            (b"textbook contents", None),
            (b"", None),
        ]
        for payload, expected in cases:
            self.assertEqual(rcpt.sniff_content_type(payload), expected, f"payload={payload[:24]!r}")

    def test_expected_type_from_url(self):
        cases = [
            ("https://e.org/a/book.pdf", "pdf"),
            ("https://e.org/a/docs.zip", "zip"),
            ("https://e.org/a/src.tar.gz", "gzip"),
            ("https://e.org/a/page.htm", "html"),
            ("https://e.org/a/page.html", "html"),
            ("https://e.org/a/set.mm", None),
            ("https://e.org/docs/", None),
        ]
        for url, expected in cases:
            self.assertEqual(rcpt.expected_content_type(url), expected, f"url={url}")


class WaveSourceResolutionTests(unittest.TestCase):
    """WaveSource had no entry-page gate at all; BulkVein got one in #1480."""

    def test_entry_page_url_is_rejected_when_resolution_required(self):
        with self.assertRaises(ValueError):
            wave_manifest.WaveSource(
                name="entry-page-row",
                domains=("F",),
                license_basis="Apache-2.0",
                connector="http_fetch",
                argv=("https://llvm.org/docs/", "--license", "Apache-2.0", "--license-evidence", "x"),
                est_tokens_low_b=0.05,
                est_tokens_high_b=0.2,
                requires_resolution=True,
            )

    def test_concrete_artifact_url_is_accepted(self):
        source = wave_manifest.WaveSource(
            name="artifact-row",
            domains=("F",),
            license_basis="Apache-2.0",
            connector="http_fetch",
            argv=(
                "https://github.com/llvm/llvm-project/archive/refs/heads/main.tar.gz",
                "--license", "Apache-2.0", "--license-evidence", "x",
            ),
            est_tokens_low_b=0.05,
            est_tokens_high_b=0.2,
            requires_resolution=True,
        )
        self.assertTrue(source.requires_resolution)

    def test_every_http_fetch_row_in_the_live_table_names_an_artifact(self):
        """The 2026-08-14 finding as a standing regression test: no shipped
        http_fetch row may point at a bare site root or directory index."""
        offenders = []
        for source in wave_manifest.WAVE2_SOURCES:
            if source.connector != "http_fetch":
                continue
            url = next((a for a in source.argv if a.startswith("http")), "")
            if wave_manifest.is_entry_page_url(url):
                offenders.append(f"{source.name} -> {url}")
        self.assertEqual(offenders, [], f"entry-page URLs still routed as artifacts: {offenders}")


if __name__ == "__main__":
    unittest.main()
