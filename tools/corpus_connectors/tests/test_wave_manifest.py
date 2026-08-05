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

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import wave_manifest as wm  # noqa: E402


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


class BuildArgvTests(unittest.TestCase):
    def test_build_argv_prefixes_the_connector_script_path(self):
        source = wm.WAVE2_SOURCES[0]
        argv = wm.build_argv(source)
        self.assertEqual(argv[0], str(wm.CONNECTOR_SCRIPTS[source.connector]))
        self.assertEqual(tuple(argv[1:]), source.argv)

    def test_bulk_vein_build_argv_requires_positive_budget(self):
        vein = wm.WAVE2_BULK_VEINS[0]
        with self.assertRaises(ValueError):
            vein.build_argv(0)
        with self.assertRaises(ValueError):
            vein.build_argv(-1)
        argv = vein.build_argv(1024)
        self.assertIn("--budget-bytes", argv)
        self.assertIn("1024", argv)
        self.assertIn(vein.url, argv)


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

    def test_execute_bulk_with_budget_dispatches(self):
        with mock.patch("wave_manifest.subprocess.run") as run_mock:
            rc = wm.main([
                "--domain", "baseline", "--include-bulk", "--execute",
                "--bulk-budget-bytes", "1000000",
            ])
        self.assertEqual(rc, 0)
        run_mock.assert_called_once()
        cmd = run_mock.call_args.args[0]
        self.assertIn("--budget-bytes", cmd)
        self.assertIn("1000000", cmd)


if __name__ == "__main__":
    unittest.main()
