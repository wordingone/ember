# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Tests for spdx_gate.py -- issue #1720 mechanical licence-mismatch gate.

Offline only: no network I/O. The gate binds to the training-admission
allow-list at runtime, so the binding tests patch that allow-list at its
owning module and assert the gate's verdicts move with it.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

import spdx_gate  # noqa: E402
import wave_manifest as wm  # noqa: E402


class MalformedExpressionTests(unittest.TestCase):
    """Syntax defects refuse fail-closed and name the correction."""

    def test_hyphenated_or_is_refused_and_names_the_spaced_form(self):
        with self.assertRaises(spdx_gate.MalformedExpressionError) as caught:
            spdx_gate.evaluate("MIT-OR-Apache-2.0")
        self.assertIn("MIT OR Apache-2.0", str(caught.exception))

    def test_hyphenated_with_is_refused_and_names_the_spaced_form(self):
        with self.assertRaises(spdx_gate.MalformedExpressionError) as caught:
            spdx_gate.evaluate("Apache-2.0-WITH-LLVM-exception")
        self.assertIn("Apache-2.0 WITH LLVM-exception", str(caught.exception))

    def test_deprecated_lowercase_with_form_is_refused(self):
        with self.assertRaises(spdx_gate.MalformedExpressionError):
            spdx_gate.evaluate("GPL-3.0-with-GCC-exception")

    def test_empty_expression_is_refused(self):
        for value in ("", "   ", "\t"):
            with self.subTest(value=value):
                with self.assertRaises(spdx_gate.MalformedExpressionError):
                    spdx_gate.evaluate(value)

    def test_dangling_operators_are_refused(self):
        for value in ("MIT OR", "OR MIT", "MIT OR OR Apache-2.0", "MIT WITH", "WITH LLVM-exception"):
            with self.subTest(value=value):
                with self.assertRaises(spdx_gate.MalformedExpressionError):
                    spdx_gate.evaluate(value)

    def test_parentheses_are_refused_rather_than_silently_ignored(self):
        with self.assertRaises(spdx_gate.MalformedExpressionError):
            spdx_gate.evaluate("(MIT OR Apache-2.0)")

    def test_or_later_suffix_is_refused_as_unbounded(self):
        with self.assertRaises(spdx_gate.MalformedExpressionError) as caught:
            spdx_gate.evaluate("Apache-2.0+")
        self.assertIn("+", str(caught.exception))

    def test_mixed_or_and_at_one_level_is_refused_as_ambiguous(self):
        with self.assertRaises(spdx_gate.MalformedExpressionError):
            spdx_gate.evaluate("MIT OR Apache-2.0 AND CC0-1.0")

    def test_lowercase_operators_are_refused(self):
        for value in ("MIT or Apache-2.0", "MIT and CC0-1.0", "Apache-2.0 with LLVM-exception"):
            with self.subTest(value=value):
                with self.assertRaises(spdx_gate.MalformedExpressionError):
                    spdx_gate.evaluate(value)

    def test_free_prose_in_the_spdx_field_is_refused(self):
        with self.assertRaises(spdx_gate.MalformedExpressionError):
            spdx_gate.evaluate("arXiv bulk access terms (per-paper CC filter applied downstream)")


class SingleIdentifierTests(unittest.TestCase):
    def test_allow_listed_identifier_is_admitted(self):
        verdict = spdx_gate.evaluate("MIT")
        self.assertEqual(verdict.status, spdx_gate.ADMITTED)
        self.assertTrue(verdict.admitted)
        self.assertIsNone(verdict.elected)

    def test_identifier_outside_the_allow_list_is_reported_not_admitted(self):
        verdict = spdx_gate.evaluate("Python-2.0")
        self.assertEqual(verdict.status, spdx_gate.NOT_ALLOWED)
        self.assertFalse(verdict.admitted)

    def test_non_spdx_identifier_is_reported_not_admitted_not_malformed(self):
        verdict = spdx_gate.evaluate("public-domain-us-gov")
        self.assertEqual(verdict.status, spdx_gate.NOT_ALLOWED)

    def test_election_on_a_non_choice_expression_is_a_defect(self):
        verdict = spdx_gate.evaluate("MIT", elected="MIT")
        self.assertEqual(verdict.status, spdx_gate.ELECTION_NOT_APPLICABLE)
        self.assertFalse(verdict.admitted)


class OrExpressionTests(unittest.TestCase):
    def test_or_without_a_recorded_election_is_not_admitted(self):
        verdict = spdx_gate.evaluate("MIT OR Apache-2.0")
        self.assertEqual(verdict.status, spdx_gate.ELECTION_MISSING)
        self.assertFalse(verdict.admitted)

    def test_or_with_an_allow_listed_election_is_admitted(self):
        verdict = spdx_gate.evaluate("MIT OR Apache-2.0", elected="MIT")
        self.assertEqual(verdict.status, spdx_gate.ADMITTED)
        self.assertEqual(verdict.elected, "MIT")

    def test_election_that_is_not_a_branch_is_refused(self):
        verdict = spdx_gate.evaluate("MIT OR Apache-2.0", elected="GPL-3.0-only")
        self.assertEqual(verdict.status, spdx_gate.ELECTION_NOT_A_BRANCH)

    def test_electing_a_disallowed_branch_when_an_allowed_one_exists_is_a_defect(self):
        verdict = spdx_gate.evaluate("MIT OR Python-2.0", elected="Python-2.0")
        self.assertEqual(verdict.status, spdx_gate.ELECTION_NOT_ALLOWED)

    def test_or_with_no_allow_listed_branch_is_plainly_not_allowed(self):
        verdict = spdx_gate.evaluate("Python-2.0 OR Ruby", elected="Python-2.0")
        self.assertEqual(verdict.status, spdx_gate.NOT_ALLOWED)


class WithExceptionTests(unittest.TestCase):
    def test_allowed_base_with_benign_exception_is_admitted(self):
        verdict = spdx_gate.evaluate("Apache-2.0 WITH LLVM-exception")
        self.assertEqual(verdict.status, spdx_gate.ADMITTED)

    def test_unreviewed_exception_is_refused_even_on_an_allowed_base(self):
        verdict = spdx_gate.evaluate("Apache-2.0 WITH Classpath-exception-2.0")
        self.assertEqual(verdict.status, spdx_gate.EXCEPTION_NOT_BENIGN)
        self.assertFalse(verdict.admitted)

    def test_benign_exception_list_is_seeded_with_llvm_exception_only(self):
        self.assertEqual(set(spdx_gate.BENIGN_EXCEPTIONS), {"LLVM-exception"})

    def test_disallowed_base_is_not_rescued_by_a_benign_exception(self):
        verdict = spdx_gate.evaluate("Python-2.0 WITH LLVM-exception")
        self.assertEqual(verdict.status, spdx_gate.NOT_ALLOWED)


class AndExpressionTests(unittest.TestCase):
    def test_and_requires_every_term_allow_listed(self):
        self.assertEqual(spdx_gate.evaluate("MIT AND CC0-1.0").status, spdx_gate.ADMITTED)

    def test_and_with_one_disallowed_term_is_not_admitted(self):
        self.assertEqual(spdx_gate.evaluate("MIT AND Python-2.0").status, spdx_gate.NOT_ALLOWED)


class RuntimeBindingTests(unittest.TestCase):
    """The gate must READ the admission allow-list, never carry a copy of it."""

    def test_allowed_licenses_is_the_admission_authority_set(self):
        import text_lab_corpus

        self.assertEqual(set(spdx_gate.allowed_licenses()), set(text_lab_corpus.LICENSES))

    def test_widening_the_authority_set_moves_the_gate_without_editing_the_gate(self):
        import text_lab_corpus

        self.assertEqual(spdx_gate.evaluate("Python-2.0").status, spdx_gate.NOT_ALLOWED)
        widened = set(text_lab_corpus.LICENSES) | {"Python-2.0"}
        with mock.patch.object(text_lab_corpus, "LICENSES", widened):
            self.assertEqual(spdx_gate.evaluate("Python-2.0").status, spdx_gate.ADMITTED)
        self.assertEqual(spdx_gate.evaluate("Python-2.0").status, spdx_gate.NOT_ALLOWED)

    def test_gate_module_does_not_hard_code_a_licence_identifier_list(self):
        source = Path(spdx_gate.__file__).read_text(encoding="utf-8")
        for identifier in ("CC0-1.0", "BSD-3-Clause", "PDDL-1.0"):
            self.assertNotIn(
                f'"{identifier}"',
                source,
                f"{identifier} appears literally in spdx_gate.py; the allow-list must be bound, not copied",
            )


class ManifestAuditTests(unittest.TestCase):
    def test_every_wave_source_declares_a_parseable_licence(self):
        malformed = [r.name for r in spdx_gate.audit_wave_sources() if r.status == spdx_gate.MALFORMED]
        self.assertEqual(malformed, [])

    def test_rust_reference_docs_elects_an_allow_listed_branch(self):
        report = {r.name: r for r in spdx_gate.audit_wave_sources()}
        row = report["rust-reference-docs"]
        self.assertEqual(row.expression, "MIT OR Apache-2.0")
        self.assertEqual(row.status, spdx_gate.ADMITTED)
        self.assertEqual(row.elected, "MIT")

    def test_electing_a_branch_absent_from_the_declared_licence_is_refused(self):
        """The row cannot elect a branch its own --license does not offer."""
        with self.assertRaises(ValueError):
            wm.WaveSource(
                name="fictitious",
                domains=("A",),
                license_basis="test",
                connector="http_fetch",
                argv=("https://example.invalid/a.tar.gz", "--license", "MIT OR Apache-2.0"),
                est_tokens_low_b=0.1,
                est_tokens_high_b=0.2,
                license_elected="GPL-3.0-only",
            )

    def test_wave_source_licence_argv_matches_the_audited_expression(self):
        """The audit must read the real argv, not a second hand-maintained table."""
        report = {r.name: r for r in spdx_gate.audit_wave_sources()}
        for source in wm.WAVE2_SOURCES:
            argv = list(source.argv)
            if "--license" not in argv:
                continue
            with self.subTest(source=source.name):
                self.assertEqual(report[source.name].expression, argv[argv.index("--license") + 1])

    def test_bulk_veins_pass_prose_into_the_spdx_field(self):
        """Pins issue #1720's second finding: BulkVein has no SPDX field at all."""
        malformed = [r.name for r in spdx_gate.audit_bulk_veins() if r.status == spdx_gate.MALFORMED]
        self.assertEqual(sorted(malformed), sorted(v.name for v in wm.WAVE2_BULK_VEINS))


if __name__ == "__main__":
    unittest.main()
