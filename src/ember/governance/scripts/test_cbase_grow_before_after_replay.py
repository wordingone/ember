# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
SCRIPT = ROOT / "scripts" / "cbase_grow_before_after_replay.py"
SPEC = importlib.util.spec_from_file_location("before_after", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
replay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay)


class BeforeAfterReplayTests(unittest.TestCase):
    def snapshot(self, head: str = "1" * 40) -> dict:
        return {
            "head_sha": head,
            "probe_sha256": "2" * 64,
            "evidence_path": "receipts/cbase-grow-rung/evidence.json",
            "evidence_sha256": "3" * 64,
            "stdout": "GREEN C-GROW: present in receipts/cbase-grow-rung/evidence.json",
            "stderr": "",
            "exit_code": 0,
            "clean": True,
        }

    def test_build_binds_distinct_clean_snapshots_and_authority(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            historical = root / "historical.json"
            historical.write_text(
                json.dumps({"ticket": "C-GROW-BEFORE-AFTER-PROBE"}),
                encoding="utf-8",
            )
            baseline = self.snapshot()
            candidate = self.snapshot("4" * 40)
            with (
                mock.patch.object(
                    replay, "capture_snapshot", side_effect=[baseline, candidate]
                ),
                mock.patch.object(replay, "sha256_file", return_value="5" * 64),
                mock.patch.object(replay, "__file__", str(root / "producer.py")),
                mock.patch.object(
                    replay,
                    "stamp",
                    side_effect=lambda receipt, _: {
                        **receipt,
                        "invariant_sha256": "0" * 64,
                    },
                ),
            ):
                receipt = replay.build_receipt(
                    root, root, historical, timestamp="2026-07-29T11:00:00Z"
                )
        self.assertEqual(receipt["ticket"], "C-GROW-BEFORE-AFTER-PROBE")
        self.assertEqual(receipt["goal_id"], "EMBER-02")
        self.assertTrue(receipt["verdict_unchanged"])
        self.assertEqual(
            receipt["sha_convention"],
            "bytes on disk as-is (binary read, no normalization)",
        )
        self.assertEqual(receipt["baseline"]["head_sha"], "1" * 40)
        self.assertEqual(receipt["candidate"]["head_sha"], "4" * 40)

    def test_probe_or_evidence_drift_refuses_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            historical = root / "historical.json"
            historical.write_text(
                json.dumps({"ticket": "C-GROW-BEFORE-AFTER-PROBE"}),
                encoding="utf-8",
            )
            baseline = self.snapshot()
            candidate = self.snapshot("4" * 40)
            candidate["evidence_sha256"] = "9" * 64
            with mock.patch.object(
                replay, "capture_snapshot", side_effect=[baseline, candidate]
            ):
                with self.assertRaisesRegex(RuntimeError, "evidence_sha256"):
                    replay.build_receipt(root, root, historical)

    def test_publish_is_exclusive_lf_only_and_confined(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            allowed = root / "receipts" / "cbase-grow-rung"
            allowed.mkdir(parents=True)
            target = allowed / "receipt.json"
            replay.publish({"ticket": "x"}, target, root)
            self.assertNotIn(b"\r\n", target.read_bytes())
            with self.assertRaises(FileExistsError):
                replay.publish({"ticket": "x"}, target, root)
            with self.assertRaisesRegex(ValueError, "output must be under"):
                replay.publish({"ticket": "x"}, root / "elsewhere.json", root)


if __name__ == "__main__":
    unittest.main()
