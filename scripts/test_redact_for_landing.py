#!/usr/bin/env python3
"""Self-test for scripts/redact_for_landing.py (ember issue #538).

Covers the AC5 corruption-class regression set at minimum:
  1. pinned-file refusal, pinning receipt named
  2. enumerated-field rewrite leaves sibling non-enumerated fields byte-identical
  3. embedded Python-regex backslashes in a non-enumerated field survive byte-exact
  4. a public URL in a non-enumerated field survives byte-exact
  5. word-boundary non-match (English-word-noise case)
  6. idempotence (running twice == running once)

Plus bonus AC1 coverage (directory refusal, glob refusal) and an AC3 .md
line-ending-preservation check. All fixtures are synthetic and live under
tempfile.TemporaryDirectory() -- this test never touches a tracked repo file
(rails, issue #538).
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO_SCRIPTS_DIR)

import redact_for_landing as rfl  # noqa: E402


def run_cli(args):
    """Invoke main() in-process; return (exit_code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    code = rfl.main(args, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


class RedactForLandingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.repo = self.tmp / "repo"
        self.work = self.tmp / "work"
        (self.repo / "receipts").mkdir(parents=True)
        self.work.mkdir(parents=True)
        self.terms_file = self.tmp / "terms.txt"
        self.terms_file.write_bytes(
            b"fixturename\t<REDACTED_NAME>\n"
            b"Z:/synthetic/fixture-tree\t<REDACTED_PATH>\n"
            b"cat\t<REDACTED_ANIMAL>\n"
        )

    def tearDown(self):
        self._tmp.cleanup()

    def write_work_file(self, name: str, content: str) -> Path:
        p = self.work / name
        p.write_bytes(content.encode("utf-8"))
        return p

    def cli(self, *file_args):
        return run_cli([
            "--terms-file", str(self.terms_file),
            "--repo-root", str(self.repo),
            *[str(a) for a in file_args],
        ])

    # ---- 1. pinned-file refusal, pinning receipt named --------------------
    def test_pinned_file_refused_with_receipt_named(self):
        pinned_content = '{"path": "Z:/synthetic/fixture-tree/model.pt"}'
        pinned_hash = hashlib.sha256(pinned_content.encode("utf-8")).hexdigest()
        pin_source = self.repo / "receipts" / "pin-source.json"
        pin_source.write_bytes(json.dumps({"sha256": pinned_hash}).encode("utf-8"))

        target = self.write_work_file("pinned.json", pinned_content)
        code, out, err = self.cli(target)

        self.assertEqual(code, 3)
        self.assertIn("receipts/pin-source.json", err)
        self.assertIn(pinned_hash, err)
        out_path = target.with_name("pinned-redacted-edition.json")
        self.assertFalse(out_path.exists(), "refused file must produce no output")
        self.assertEqual(target.read_bytes(), pinned_content.encode("utf-8"),
                          "refused file must be left untouched")

    # ---- 2. sibling non-enumerated field stays byte-identical -------------
    def test_sibling_non_enumerated_field_byte_identical(self):
        sibling_value = "plain sibling note mentioning fixturename in passing"
        content = json.dumps({
            "path": "Z:/synthetic/fixture-tree/out/model.pt",
            "notes": sibling_value,
        })
        target = self.write_work_file("sibling.json", content)
        code, _, _ = self.cli(target)

        self.assertEqual(code, 0)
        result = json.loads(target.with_name("sibling-redacted-edition.json").read_bytes())
        self.assertEqual(result["notes"], sibling_value,
                          "non-enumerated field must survive untouched even though it contains a term")
        self.assertIn("<REDACTED_PATH>", result["path"])
        self.assertNotIn("Z:/synthetic/fixture-tree", result["path"])

    # ---- 3. embedded Python regex backslashes survive byte-exact ----------
    def test_python_regex_backslashes_survive_byte_exact(self):
        regex_value = r"^(\d+)\.(\d+)\.(\d+)-fixturename$"
        content = json.dumps({
            "path": "Z:/synthetic/fixture-tree/x",
            "diagnostic_pattern": regex_value,
        })
        target = self.write_work_file("regex.json", content)
        code, _, _ = self.cli(target)

        self.assertEqual(code, 0)
        result = json.loads(target.with_name("regex-redacted-edition.json").read_bytes())
        self.assertEqual(result["diagnostic_pattern"], regex_value,
                          "backslash-bearing regex in a non-enumerated field must be byte-exact")

    # ---- 4. public URL in a non-enumerated field survives byte-exact ------
    def test_public_url_survives_byte_exact(self):
        url_value = "https://example.com/fixturename/download?item=1&ref=abc"
        content = json.dumps({
            "path": "Z:/synthetic/fixture-tree/y",
            "reference_url": url_value,
        })
        target = self.write_work_file("url.json", content)
        code, _, _ = self.cli(target)

        self.assertEqual(code, 0)
        result = json.loads(target.with_name("url-redacted-edition.json").read_bytes())
        self.assertEqual(result["reference_url"], url_value)

    # ---- 5. word-boundary non-match (English-word-noise case) -------------
    def test_word_boundary_non_match(self):
        content = json.dumps({
            "path": "cat is a standalone term here",
            "notes": "category and concatenate must not match",
        })
        target = self.write_work_file("wordboundary.json", content)
        code, _, _ = self.cli(target)

        self.assertEqual(code, 0)
        result = json.loads(target.with_name("wordboundary-redacted-edition.json").read_bytes())
        self.assertEqual(result["path"], "<REDACTED_ANIMAL> is a standalone term here")
        self.assertEqual(result["notes"], "category and concatenate must not match",
                          "'cat' must not match inside 'category'/'concatenate'")

    # ---- 6. idempotence -----------------------------------------------------
    def test_idempotence(self):
        content = json.dumps({
            "path": "Z:/synthetic/fixture-tree/a/fixturename/b",
            "cmdline": "run --name fixturename --root Z:/synthetic/fixture-tree",
        })
        first = self.write_work_file("idem-run1.json", content)
        second = self.write_work_file("idem-run2.json", content)

        code1, _, _ = self.cli(first)
        code2, _, _ = self.cli(second)
        self.assertEqual(code1, 0)
        self.assertEqual(code2, 0)
        out1 = first.with_name("idem-run1-redacted-edition.json").read_bytes()
        out2 = second.with_name("idem-run2-redacted-edition.json").read_bytes()
        self.assertEqual(out1, out2, "same input must produce byte-identical output across runs")

        # feeding the already-redacted output back in must not change it further
        third = self.write_work_file("idem-run3.json", out1.decode("utf-8"))
        code3, _, _ = self.cli(third)
        self.assertEqual(code3, 0)
        out3 = third.with_name("idem-run3-redacted-edition.json").read_bytes()
        self.assertEqual(out1, out3, "re-redacting an already-redacted file must be a no-op")

    # ---- bonus: AC1 explicit-file-list-only checks -------------------------
    def test_directory_argument_refused(self):
        code, _, err = self.cli(self.work)
        self.assertEqual(code, 2)
        self.assertIn("directory", err)

    def test_glob_argument_refused(self):
        code, _, err = self.cli(self.work / "*.json")
        self.assertEqual(code, 2)
        self.assertIn("glob", err)

    # ---- bonus: .md line-wise redaction with line-ending preservation -----
    def test_md_line_wise_preserves_line_endings(self):
        content = "line one mentions fixturename here\r\nline two is plain\nlast line no newline"
        target = self.work / "doc.md"
        target.write_bytes(content.encode("utf-8"))
        code, _, _ = self.cli(target)

        self.assertEqual(code, 0)
        out_bytes = target.with_name("doc-redacted-edition.md").read_bytes()
        self.assertIn(b"\r\n", out_bytes)
        self.assertTrue(out_bytes.endswith(b"last line no newline"))
        self.assertIn(b"<REDACTED_NAME>", out_bytes)

    # ---- 2026-07-11 follow-up (issue #538): key-miss case -------------------
    # A real receipt leaked local paths under 10 of 13 path-bearing fields
    # because the key enumeration only covered "_path". These fixtures use
    # the EXACT field-name shapes that leaked (dir / _dir / _ref / _source /
    # _receipt) to prove the fix, and were run against the actual leaked
    # receipt after the fix landed (see PR body for that raw run).
    def test_suffix_families_now_key_gated(self):
        content = json.dumps({
            "dir": "Z:/synthetic/fixture-tree/checkpoints/step-00000766",
            "control_step25_dir": "Z:/synthetic/fixture-tree/checkpoints/step-00000025",
            "source_dir": "Z:/synthetic/fixture-tree/scratch/step-00000050",
            "dest_dir": "Z:/synthetic/fixture-tree/custody/step-00000050",
            "terminal_checkpoint_ref": "Z:/synthetic/fixture-tree/checkpoints/step-00000766",
            "terminal_checkpoint_receipt": "Z:/synthetic/fixture-tree/receipts/x.json",
            "n_mtp_source": "Z:/synthetic/fixture-tree/configs/v0.json objective.n_heads=2",
        })
        target = self.write_work_file("suffix-families.json", content)
        code, _, _ = self.cli(target)

        self.assertEqual(code, 0)
        result = json.loads(target.with_name("suffix-families-redacted-edition.json").read_bytes())
        for key in ("dir", "control_step25_dir", "source_dir", "dest_dir",
                    "terminal_checkpoint_ref", "terminal_checkpoint_receipt",
                    "n_mtp_source"):
            self.assertIn("<REDACTED_PATH>", result[key], f"key {key!r} not redacted")
            self.assertNotIn("Z:/synthetic/fixture-tree", result[key], f"key {key!r} leaked")

    # ---- 2026-07-11 follow-up: key-agnostic pattern-fallback case ----------
    def test_pattern_fallback_redacts_unenumerated_key_not_in_terms_file(self):
        """A key the enumeration STILL doesn't cover, with a path that is
        NOT in the terms file either (simulating the 11th miss the fallback
        exists to survive) -- must still lose its drive-letter prefix while
        every trailing directory/basename segment survives untouched."""
        content = json.dumps({
            "totally_unenumerated_field": "Z:/synthetic/fixture-tree/models/cbase-grow-rung/rung1/step-00000766",
            "backslash_variant_field": "Z:\\synthetic\\fixture-tree\\scratch\\w1-control\\checkpoints\\step-00000050",
        })
        target = self.write_work_file("fallback.json", content)
        code, _, _ = self.cli(target)

        self.assertEqual(code, 0)
        result = json.loads(target.with_name("fallback-redacted-edition.json").read_bytes())
        self.assertEqual(
            result["totally_unenumerated_field"],
            "<LOCAL-ABS-PATH>/synthetic/fixture-tree/models/cbase-grow-rung/rung1/step-00000766",
            "drive-letter prefix must be replaced, forward-slash segments preserved verbatim")
        self.assertEqual(
            result["backslash_variant_field"],
            "<LOCAL-ABS-PATH>\\synthetic\\fixture-tree\\scratch\\w1-control\\checkpoints\\step-00000050",
            "backslash separator style must be preserved after the token")

    def test_pattern_fallback_does_not_false_positive_on_url_scheme(self):
        """The single-letter-before-colon-slash shape inside 'https://' or
        'mailto:' must never match -- the word-character lookbehind is the
        guard (the 's' in 'http**s**:' is preceded by 'p', a word char)."""
        url_value = (
            "see https://example.com/x and ftp://host/y and "
            "mailto:a@b.com for details"
        )
        content = json.dumps({"totally_unenumerated_field": url_value})
        target = self.write_work_file("url-fallback.json", content)
        code, _, _ = self.cli(target)

        self.assertEqual(code, 0)
        result = json.loads(target.with_name("url-fallback-redacted-edition.json").read_bytes())
        self.assertEqual(result["totally_unenumerated_field"], url_value)
        self.assertNotIn("<LOCAL-ABS-PATH>", result["totally_unenumerated_field"])

    def test_pattern_fallback_idempotent(self):
        content = json.dumps({
            "totally_unenumerated_field": "Z:/synthetic/fixture-tree/x/y/z",
        })
        first = self.write_work_file("fallback-idem1.json", content)
        code1, _, _ = self.cli(first)
        self.assertEqual(code1, 0)
        out1 = first.with_name("fallback-idem1-redacted-edition.json").read_bytes()

        second = self.write_work_file("fallback-idem2.json", out1.decode("utf-8"))
        code2, _, _ = self.cli(second)
        self.assertEqual(code2, 0)
        out2 = second.with_name("fallback-idem2-redacted-edition.json").read_bytes()
        self.assertEqual(out1, out2, "re-redacting an already-fallback-redacted value must be a no-op")

    # ---- 2026-07-11 follow-up: .log support ---------------------------------
    def test_log_file_gets_term_and_pattern_redaction(self):
        # NOTE: the forward-slash path here deliberately uses a synthetic drive
        # ("Y:") and tree name DISTINCT from the "Z:/synthetic/fixture-tree"
        # term registered in setUp() -- if it collided with that literal term,
        # term substitution would consume the drive-letter prefix before the
        # pattern fallback ever saw it, and this assertion would silently stop
        # exercising the fallback mechanism it exists to test.
        content = (
            "+ python script.py --shard-dir Y:/synthetic/live-tree/shards-v0 --name fixturename\r\n"
            "plain progress line, nothing to redact\n"
            '{"verdict": "REPLAY_TRUSTWORTHY", "dir": "Z:\\\\synthetic\\\\fixture-tree\\\\models\\\\x"}\n'
            "no newline at end"
        )
        target = self.work / "run.log"
        target.write_bytes(content.encode("utf-8"))
        code, _, _ = self.cli(target)

        self.assertEqual(code, 0)
        out_bytes = target.with_name("run-redacted-edition.log").read_bytes()
        out_text = out_bytes.decode("utf-8")
        self.assertIn("<REDACTED_NAME>", out_text, "term substitution must still apply per line")
        self.assertIn("<LOCAL-ABS-PATH>/synthetic/live-tree/shards-v0", out_text, "forward-slash path must be redacted")
        self.assertIn("<LOCAL-ABS-PATH>\\\\synthetic\\\\fixture-tree\\\\models\\\\x", out_text,
                      "backslash path (JSON-escaped in the log line) must be redacted")
        self.assertIn(b"\r\n", out_bytes, "line endings must be preserved, same as .md")
        self.assertTrue(out_bytes.endswith(b"no newline at end"))

    def test_log_file_public_url_survives(self):
        content = "fetching https://example.com/artifact and ftp://host/y\n"
        target = self.work / "urls.log"
        target.write_bytes(content.encode("utf-8"))
        code, _, _ = self.cli(target)

        self.assertEqual(code, 0)
        out_text = target.with_name("urls-redacted-edition.log").read_bytes().decode("utf-8")
        self.assertEqual(out_text, content)


if __name__ == "__main__":
    unittest.main()
