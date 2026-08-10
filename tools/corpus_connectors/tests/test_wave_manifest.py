# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Tests for wave_manifest.py -- issue #1439 wave-2 source routing table.

Offline only: this module performs no network I/O of its own (it only
builds argv lists and, under --execute, shells out to the already-tested
connector CLIs), so these tests exercise the table's own invariants and the
CLI's print/dry-run/--execute wiring, mocking subprocess.run for --execute.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
import unittest
import json
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import wave_manifest as wm  # noqa: E402


def resolution_receipt_sha256(vein_name, urls):
    payload = {
        "schema": "ember-wave2-bulk-resolution-v1",
        "vein": vein_name,
        "urls": list(urls),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class SourceTableInvariantTests(unittest.TestCase):
    def test_every_source_routes_to_a_known_connector(self):
        for s in wm.WAVE2_SOURCES:
            self.assertIn(s.connector, wm.CONNECTOR_SCRIPTS)
            self.assertTrue(wm.CONNECTOR_SCRIPTS[s.connector].is_file(), s.connector)

    def test_every_source_names_a_license_basis(self):
        for s in wm.WAVE2_SOURCES:
            self.assertTrue(s.license_basis.strip(), s.name)

    def test_every_source_has_at_least_one_charter_domain(self):
        for s in wm.WAVE2_SOURCES:
            self.assertGreater(len(s.domains), 0, s.name)
            for d in s.domains:
                self.assertIn(d, wm.CHARTER_DOMAINS, f"{s.name}: {d}")

    def test_source_names_are_unique(self):
        names = [s.name for s in wm.WAVE2_SOURCES]
        self.assertEqual(len(names), len(set(names)), "duplicate source name in WAVE2_SOURCES")

    def test_bulk_vein_names_are_unique(self):
        names = [v.name for v in wm.WAVE2_BULK_VEINS]
        self.assertEqual(len(names), len(set(names)), "duplicate vein name in WAVE2_BULK_VEINS")

    def test_bulk_entry_pages_require_resolution_and_direct_artifact_does_not(self):
        entry_pages = [v for v in wm.WAVE2_BULK_VEINS if v.name != "wikipedia-en-baseline"]
        self.assertTrue(entry_pages)
        self.assertTrue(all(v.requires_resolution for v in entry_pages))
        self.assertFalse(next(v for v in wm.WAVE2_BULK_VEINS if v.name == "wikipedia-en-baseline").requires_resolution)

    def test_bad_source_rejected_at_construction(self):
        with self.assertRaises(ValueError):
            wm.WaveSource(
                name="bad-connector",
                domains=("A",),
                license_basis="x",
                connector="not-a-real-connector",
                argv=("--x",),
                est_tokens_low_b=0.1,
                est_tokens_high_b=0.2,
            )
        with self.assertRaises(ValueError):
            wm.WaveSource(
                name="bad-domain",
                domains=("Z",),
                license_basis="x",
                connector="http_fetch",
                argv=("--x",),
                est_tokens_low_b=0.1,
                est_tokens_high_b=0.2,
            )
        with self.assertRaises(ValueError):
            wm.WaveSource(
                name="empty-argv",
                domains=("A",),
                license_basis="x",
                connector="http_fetch",
                argv=(),
                est_tokens_low_b=0.1,
                est_tokens_high_b=0.2,
            )
        with self.assertRaises(ValueError):
            wm.WaveSource(
                name="bad-token-bounds",
                domains=("A",),
                license_basis="x",
                connector="http_fetch",
                argv=("--x",),
                est_tokens_low_b=5.0,
                est_tokens_high_b=1.0,
            )

    def test_bad_bulk_vein_rejected_at_construction(self):
        with self.assertRaises(ValueError):
            wm.BulkVein(
                name="bad-domain",
                domains=("Z",),
                license_basis="x",
                url="https://example.invalid/dump",
                est_tokens_low_b=1.0,
                est_tokens_high_b=2.0,
            )
        with self.assertRaises(ValueError):
            wm.BulkVein(
                name="empty-url",
                domains=("A",),
                license_basis="x",
                url="",
                est_tokens_low_b=1.0,
                est_tokens_high_b=2.0,
            )

    def test_charter_coverage_claim_is_backed_by_the_table(self):
        # corpus-sizing-v1.md claims every charter domain A-K plus baseline
        # has at least one routed source (single-shot or bulk). This is the
        # machine-checkable form of that claim.
        covered = wm.domains_covered()
        missing = set(wm.CHARTER_DOMAINS) - covered
        self.assertEqual(missing, set(), f"charter domains with no routed source: {sorted(missing)}")


class ProseGapPlanTests(unittest.TestCase):
    def test_rule_based_plan_has_all_charter_domains_and_nonempty_estimates(self):
        plan = wm.build_prose_gap_plan()
        self.assertEqual(plan.selection_policy, "RULE_BASED")
        self.assertTrue(set(plan.domain_coverage) >= set("ABCDEFGHIJK"))
        self.assertGreater(plan.current_clean_prose_tokens_b, 0)
        self.assertTrue(all(row.license_evidence for row in plan.sources))
        self.assertTrue(all(row.estimated_tokens_low_b > 0 for row in plan.sources))
        self.assertTrue(all(row.estimated_tokens_high_b >= row.estimated_tokens_low_b for row in plan.sources))

    def test_plan_is_deterministic_and_has_no_model_derived_filter(self):
        first = wm.build_prose_gap_plan()
        second = wm.build_prose_gap_plan()
        self.assertEqual(first, second)
        forbidden = ("fasttext", "classifier", "embedding", "llm", "model-derived")
        self.assertFalse(any(term in repr(first).lower() for term in forbidden))

    def test_rendered_plan_is_numbered_and_dry_run_only(self):
        rendered = wm.render_prose_gap_plan(wm.build_prose_gap_plan())
        self.assertIn("1. Current clean prose total", rendered)
        self.assertIn("2. Rule-based target addition", rendered)
        self.assertIn("3. Candidate additions", rendered)
        self.assertIn("4. Domain coverage", rendered)
        self.assertIn("RULE_BASED", rendered)
        self.assertNotIn("--execute", rendered)


class BuildArgvTests(unittest.TestCase):
    def test_build_argv_prefixes_the_connector_script_path(self):
        source = wm.WAVE2_SOURCES[0]
        argv = wm.build_argv(source)
        self.assertEqual(argv[0], str(wm.CONNECTOR_SCRIPTS[source.connector]))
        self.assertEqual(tuple(argv[1:]), source.argv)

    def test_bulk_vein_build_argv_requires_positive_budget(self):
        vein = wm.WAVE2_BULK_VEINS[0]
        with self.assertRaises(ValueError):
            vein.build_argv(0, license_evidence="external license page")
        with self.assertRaises(ValueError):
            vein.build_argv(-1, license_evidence="external license page")
        argv = vein.build_argv(
            1024,
            license_evidence="arXiv bulk access terms at arxiv.org/help/bulk_data",
            resolved_url="https://arxiv.org/bulk/2026.tar",
        )
        self.assertIn("--budget-bytes", argv)
        self.assertIn("1024", argv)
        self.assertIn("https://arxiv.org/bulk/2026.tar", argv)

    def test_bulk_vein_rejects_missing_or_self_referential_license_evidence(self):
        vein = wm.WAVE2_BULK_VEINS[0]
        with self.assertRaises(ValueError):
            vein.build_argv(1024, license_evidence="")
        with self.assertRaises(ValueError):
            vein.build_argv(1024, license_evidence="wave_manifest.py named-source license determination")

    def test_charter_domain_diversity_requires_two_sources_or_explicit_waiver(self):
        self.assertEqual(wm.validate_domain_diversity(), {})

    def test_charter_domain_diversity_rejects_same_register_and_license_aliases(self):
        aliases = [
            wm.WaveSource(
                name="h-register-alias-a",
                domains=("H",),
                license_basis="MIT",
                connector="http_fetch",
                argv=("https://docs.example/reference/", "--license-evidence", "MIT license"),
                est_tokens_low_b=0.1,
                est_tokens_high_b=0.2,
            ),
            wm.WaveSource(
                name="h-register-alias-b",
                domains=("H",),
                license_basis="MIT",
                connector="http_fetch",
                argv=("https://docs.example/reference/", "--license-evidence", "MIT license"),
                est_tokens_low_b=0.1,
                est_tokens_high_b=0.2,
            ),
        ]
        with mock.patch.object(wm, "WAVE2_SOURCES", aliases), mock.patch.object(wm, "WAVE2_BULK_VEINS", []):
            deficits = wm.validate_domain_diversity()
        self.assertIn("H", deficits)

    def test_charter_domain_diversity_rejects_same_host_different_paths(self):
        aliases = [
            wm.WaveSource(
                name="h-register-page-a",
                domains=("H",),
                license_basis="MIT",
                connector="http_fetch",
                argv=("https://docs.example/reference/", "--license-evidence", "MIT license"),
                est_tokens_low_b=0.1,
                est_tokens_high_b=0.2,
            ),
            wm.WaveSource(
                name="h-register-page-b",
                domains=("H",),
                license_basis="Apache-2.0",
                connector="http_fetch",
                argv=("https://docs.example/tutorial/", "--license-evidence", "Apache license"),
                est_tokens_low_b=0.1,
                est_tokens_high_b=0.2,
            ),
        ]
        with mock.patch.object(wm, "WAVE2_SOURCES", aliases), mock.patch.object(wm, "WAVE2_BULK_VEINS", []):
            deficits = wm.validate_domain_diversity()
        self.assertIn("H", deficits)


class FilterTests(unittest.TestCase):
    def test_iter_sources_filters_by_domain(self):
        all_sources = wm.iter_sources()
        domain_a = wm.iter_sources("A")
        self.assertTrue(all(("A" in s.domains) for s in domain_a))
        self.assertLessEqual(len(domain_a), len(all_sources))
        self.assertGreater(len(domain_a), 0)

    def test_iter_sources_domain_with_no_matches_is_empty(self):
        # every WAVE2_SOURCES entry so far uses a lettered domain; "baseline"
        # (Wikipedia) is bulk-only, so the single-shot table has none.
        self.assertEqual(wm.iter_sources("baseline"), [])

    def test_iter_bulk_veins_filters_by_domain(self):
        veins = wm.iter_bulk_veins("baseline")
        self.assertEqual([v.name for v in veins], ["wikipedia-en-baseline"])


class CliTests(unittest.TestCase):
    def test_dry_run_default_prints_without_executing(self):
        with mock.patch.object(subprocess, "run") as run_mock:
            rc = wm.main(["--domain", "A"])
        self.assertEqual(rc, 0)
        run_mock.assert_not_called()

    def test_execute_shells_out_to_each_routed_connector(self):
        with mock.patch("wave_manifest.subprocess.run") as run_mock:
            rc = wm.main(["--domain", "A", "--execute"])
        self.assertEqual(rc, 0)
        self.assertGreater(run_mock.call_count, 0)
        for call in run_mock.call_args_list:
            cmd = call.args[0]
            self.assertEqual(cmd[0], sys.executable)

    def test_include_bulk_without_execute_never_calls_subprocess(self):
        with mock.patch("wave_manifest.subprocess.run") as run_mock:
            rc = wm.main(["--domain", "baseline", "--include-bulk"])
        self.assertEqual(rc, 0)
        run_mock.assert_not_called()

    def test_execute_bulk_without_budget_is_blocked(self):
        with mock.patch("wave_manifest.subprocess.run") as run_mock:
            rc = wm.main(["--domain", "baseline", "--include-bulk", "--execute"])
        self.assertEqual(rc, 1)
        run_mock.assert_not_called()

    def test_execute_bulk_with_nonpositive_budget_refuses_before_subprocess(self):
        with mock.patch("wave_manifest.subprocess.run") as run_mock:
            rc = wm.main([
                "--domain", "baseline", "--include-bulk", "--execute",
                "--bulk-budget-bytes", "-1",
            ])
        self.assertEqual(rc, 1)
        run_mock.assert_not_called()

    def test_execute_entry_page_without_resolution_refuses_before_subprocess(self):
        with mock.patch("wave_manifest.subprocess.run") as run_mock:
            rc = wm.main([
                "--domain", "A", "--include-bulk", "--execute",
                "--bulk-budget-bytes", "1000000",
                "--bulk-license-evidence-file", "missing-evidence.json",
            ])
        self.assertEqual(rc, 1)
        run_mock.assert_not_called()

    def test_execute_bulk_rejects_self_citing_evidence_before_subprocess(self):
        vein_name = "wikipedia-en-baseline"
        with tempfile.TemporaryDirectory() as tmp:
            resolution = Path(tmp) / "resolution.json"
            evidence = Path(tmp) / "evidence.json"
            resolution.write_text(json.dumps({vein_name: {
                "urls": [wm.WAVE2_BULK_VEINS[-1].url],
                "resolution_receipt_sha256": resolution_receipt_sha256(vein_name, [wm.WAVE2_BULK_VEINS[-1].url]),
            }}), encoding="utf-8")
            evidence.write_text(json.dumps({vein_name: "wave_manifest.py generated license claim"}), encoding="utf-8")
            with mock.patch("wave_manifest.subprocess.run") as run_mock:
                rc = wm.main([
                    "--domain", "baseline", "--include-bulk", "--execute",
                    "--bulk-budget-bytes", "1000000",
                    "--bulk-resolution-file", str(resolution),
                    "--bulk-license-evidence-file", str(evidence),
                ])
        self.assertEqual(rc, 1)
        run_mock.assert_not_called()

    def test_execute_entry_page_dispatches_only_resolved_artifact_urls(self):
        selected = wm.iter_bulk_veins("A")
        with tempfile.TemporaryDirectory() as tmp:
            resolution = Path(tmp) / "resolution.json"
            evidence = Path(tmp) / "evidence.json"
            resolution.write_text(json.dumps({
                vein.name: {
                    "urls": [f"https://example.test/{vein.name}.tar"],
                    "resolution_receipt_sha256": resolution_receipt_sha256(
                        vein.name, [f"https://example.test/{vein.name}.tar"]
                    ),
                }
                for vein in selected
            }), encoding="utf-8")
            evidence.write_text(json.dumps({
                vein.name: f"{vein.name} external license page"
                for vein in selected
            }), encoding="utf-8")
            with mock.patch("wave_manifest.subprocess.run") as run_mock:
                rc = wm.main([
                    "--domain", "A", "--include-bulk", "--execute",
                    "--bulk-budget-bytes", "1000000",
                    "--bulk-resolution-file", str(resolution),
                    "--bulk-license-evidence-file", str(evidence),
                ])
        self.assertEqual(rc, 0)
        bulk_commands = [call.args[0] for call in run_mock.call_args_list if "bulk_fetch.py" in str(call.args[0])]
        self.assertEqual(len(bulk_commands), len(selected))
        for vein, command in zip(selected, bulk_commands):
            self.assertIn(f"https://example.test/{vein.name}.tar", command)
            self.assertNotIn(vein.url, command)

    def test_execute_bulk_rejects_rehashed_but_wrong_resolution_receipt_before_subprocess(self):
        vein_name = "wikipedia-en-baseline"
        with tempfile.TemporaryDirectory() as tmp:
            resolution = Path(tmp) / "resolution.json"
            evidence = Path(tmp) / "evidence.json"
            resolution.write_text(json.dumps({vein_name: {
                "urls": ["https://dumps.wikimedia.org/enwiki/latest/enwiki-latest-pages-articles.xml.bz2"],
                "resolution_receipt_sha256": "a" * 64,
            }}), encoding="utf-8")
            evidence.write_text(json.dumps({vein_name: "Wikimedia dump license page and terms"}), encoding="utf-8")
            with mock.patch("wave_manifest.subprocess.run") as run_mock:
                rc = wm.main([
                    "--domain", "baseline", "--include-bulk", "--execute",
                    "--bulk-budget-bytes", "1000000",
                    "--bulk-resolution-file", str(resolution),
                    "--bulk-license-evidence-file", str(evidence),
                ])
        self.assertEqual(rc, 1)
        run_mock.assert_not_called()

    def test_execute_bulk_with_budget_dispatches(self):
        vein_name = "wikipedia-en-baseline"
        with tempfile.TemporaryDirectory() as tmp:
            resolution = Path(tmp) / "resolution.json"
            evidence = Path(tmp) / "evidence.json"
            resolution.write_text(json.dumps({vein_name: {
                "urls": ["https://dumps.wikimedia.org/enwiki/latest/enwiki-latest-pages-articles.xml.bz2"],
                "resolution_receipt_sha256": resolution_receipt_sha256(
                    vein_name,
                    ["https://dumps.wikimedia.org/enwiki/latest/enwiki-latest-pages-articles.xml.bz2"],
                ),
            }}), encoding="utf-8")
            evidence.write_text(json.dumps({vein_name: "Wikimedia dump license page and terms"}), encoding="utf-8")
            with mock.patch("wave_manifest.subprocess.run") as run_mock:
                rc = wm.main([
                    "--domain", "baseline", "--include-bulk", "--execute",
                    "--bulk-budget-bytes", "1000000",
                    "--bulk-resolution-file", str(resolution),
                    "--bulk-license-evidence-file", str(evidence),
                ])
        self.assertEqual(rc, 0)
        run_mock.assert_called_once()
        cmd = run_mock.call_args.args[0]
        self.assertIn("--budget-bytes", cmd)
        self.assertIn("1000000", cmd)


if __name__ == "__main__":
    unittest.main()
