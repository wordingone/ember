# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.c8_prelaunch.governed_run_launcher import (
    GovernedLaunchError,
    load_launch_manifest,
    run_governed_launch,
)


class GovernedRunLauncherTests(unittest.TestCase):
    def _fixture(self, root: Path) -> Path:
        (root / "scripts").mkdir()
        (root / "configs").mkdir()
        (root / "receipts").mkdir()
        (root / "state").mkdir()
        (root / "scripts" / "worker.py").write_text(
            "from pathlib import Path\n"
            "import sys\n"
            "Path(sys.argv[1]).write_text('EXECUTED', encoding='utf-8')\n",
            encoding="utf-8",
        )
        (root / "configs" / "arm.json").write_text('{"arm":"A-scratch"}\n', encoding="utf-8")
        (root / "receipts" / "admissibility.json").write_text(
            '{"result":"PASS"}\n', encoding="utf-8"
        )
        manifest = root / "launch.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": "ember-c8-governed-launch-v1",
                    "run_id": "c8-test-run-001",
                    "arm": "A-scratch",
                    "config_path": "configs/arm.json",
                    "admissibility_receipt_path": "receipts/admissibility.json",
                    "python_script_path": "scripts/worker.py",
                    "argv": ["marker.txt"],
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return manifest

    def test_positive_launch_records_before_process_and_executes_exact_script(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = self._fixture(root)
            observed: dict[str, object] = {}

            def run_process(argv, **kwargs):
                ledger = root / "state" / "c8-run-ledger.jsonl"
                observed["ledger_before_spawn"] = ledger.exists()
                observed["rows_before_spawn"] = [
                    json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()
                ]
                observed["script_snapshot"] = Path(argv[2]).read_bytes()
                observed["script_snapshot_path"] = argv[2]
                return subprocess.run(argv, **kwargs)

            result = run_governed_launch(
                repo_root=root,
                manifest_path=manifest,
                run_process=run_process,
                now=lambda: "2026-07-31T07:00:00Z",
            )

            self.assertEqual(result.returncode, 0)
            self.assertTrue(observed["ledger_before_spawn"])
            self.assertEqual(observed["rows_before_spawn"][0]["run_id"], "c8-test-run-001")
            self.assertEqual((root / "marker.txt").read_text(encoding="utf-8"), "EXECUTED")
            self.assertEqual(result.argv[0], sys.executable)
            self.assertEqual(
                observed["script_snapshot"], (root / "scripts" / "worker.py").read_bytes()
            )
            self.assertNotEqual(Path(result.argv[2]), (root / "scripts" / "worker.py").resolve())
            self.assertEqual(result.argv[2], observed["script_snapshot_path"])
            self.assertFalse(Path(result.argv[2]).exists())

    def test_program_source_swap_after_admission_uses_owned_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = self._fixture(root)
            source = root / "scripts" / "worker.py"

            def mutate_source(**_kwargs):
                source.write_text(
                    "from pathlib import Path\n"
                    "import sys\n"
                    "Path(sys.argv[1]).write_text('TAMPERED', encoding='utf-8')\n",
                    encoding="utf-8",
                )
                return {}

            result = run_governed_launch(
                repo_root=root,
                manifest_path=manifest,
                record_launch=mutate_source,
                now=lambda: "2026-07-31T07:00:00Z",
            )

            self.assertEqual(result.returncode, 0)
            self.assertEqual(
                (root / "marker.txt").read_text(encoding="utf-8"), "EXECUTED"
            )

    def test_record_failure_blocks_process_creation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = self._fixture(root)
            calls: list[list[str]] = []

            def refuse_record(**_kwargs):
                raise SystemExit("ledger unavailable")

            with self.assertRaisesRegex(SystemExit, "ledger unavailable"):
                run_governed_launch(
                    repo_root=root,
                    manifest_path=manifest,
                    record_launch=refuse_record,
                    run_process=lambda argv, **_kwargs: calls.append(argv),
                    now=lambda: "2026-07-31T07:00:00Z",
                )
            self.assertEqual(calls, [])
            self.assertFalse((root / "marker.txt").exists())

    def test_duplicate_run_id_refuses_second_spawn(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = self._fixture(root)
            calls: list[list[str]] = []

            def fake_process(argv, **_kwargs):
                calls.append(argv)
                return subprocess.CompletedProcess(argv, 0)

            run_governed_launch(
                repo_root=root,
                manifest_path=manifest,
                run_process=fake_process,
                now=lambda: "2026-07-31T07:00:00Z",
            )
            with self.assertRaisesRegex(SystemExit, "duplicate"):
                run_governed_launch(
                    repo_root=root,
                    manifest_path=manifest,
                    run_process=fake_process,
                    now=lambda: "2026-07-31T07:01:00Z",
                )
            self.assertEqual(len(calls), 1)

    def test_manifest_is_closed_and_paths_are_repo_relative(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = self._fixture(root)
            baseline = json.loads(manifest.read_text(encoding="utf-8"))
            loaded = load_launch_manifest(root, "launch.json")
            self.assertEqual(loaded.run_id, "c8-test-run-001")


            cases = [
                {**baseline, "extra": "not allowed"},
                {**baseline, "run_id": ""},
                {**baseline, "arm": "not-an-arm"},
                {**baseline, "config_path": "../outside.json"},
                {**baseline, "admissibility_receipt_path": str((root / "x").resolve())},
                {**baseline, "python_script_path": "configs/arm.json"},
                {**baseline, "argv": ["ok", 7]},
                {**baseline, "argv": ["--config", "other.json"]},
                {**baseline, "argv": ["--admissibility-receipt=other.json"]},
                {**baseline, "argv": ["--run-id=other"]},
                {**baseline, "argv": ["--arm", "gated-grown"]},
            ]
            for index, payload in enumerate(cases):
                with self.subTest(index=index):
                    manifest.write_text(json.dumps(payload), encoding="utf-8")
                    with self.assertRaises(GovernedLaunchError):
                        load_launch_manifest(root, manifest)

    def test_manifest_requires_strict_utf8_and_unique_json_keys(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = self._fixture(root)

            manifest.write_bytes(b"{\xff}")
            with self.assertRaisesRegex(GovernedLaunchError, "strict UTF-8"):
                load_launch_manifest(root, manifest)

            manifest.write_text(
                '{"schema_version":"ember-c8-governed-launch-v1",'
                '"schema_version":"ember-c8-governed-launch-v1"}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(GovernedLaunchError, "duplicate JSON key"):
                load_launch_manifest(root, manifest)

    def test_symlinked_evidence_or_program_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = self._fixture(root)
            target = root / "configs" / "real.json"
            target.write_text("{}\n", encoding="utf-8")
            link = root / "configs" / "link.json"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation unavailable on this host")
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["config_path"] = "configs/link.json"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(GovernedLaunchError, "symlink"):
                load_launch_manifest(root, manifest)


if __name__ == "__main__":
    unittest.main()
