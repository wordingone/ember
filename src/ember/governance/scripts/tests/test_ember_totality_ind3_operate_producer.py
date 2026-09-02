# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())


def _load(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


producer = _load(
    "ind3_operate_producer_under_test",
    "src/ember/governance/scripts/ember_totality/ind3_operate_producer.py",
)
validator = _load(
    "test_c_ind_under_test",
    "src/ember/governance/scripts/ember_totality/test_c_ind.py",
)


def _valid_entries() -> list[tuple[Path, dict]]:
    return [
        (
            Path("launch.json"),
            {
                "leg": "launch",
                "verified_alive": True,
                "heartbeat_ready": {"status": "ready"},
            },
        ),
        (
            Path("teardown.json"),
            {
                "leg": "teardown",
                "exit_code": 0,
                "final_heartbeat": {"status": "stopped"},
                "post_stop_process_table": {
                    "survivors": [],
                    "orphaned_gpu_state": False,
                },
            },
        ),
        (
            Path("interrupted.json"),
            {
                "leg": "interrupted_resume",
                "interrupt_command_exit_code": 0,
                "interrupted_pid_verified_dead": True,
                "interrupted_launcher_pid_verified_dead": True,
                "resumed_verified_alive": True,
                "resumed_ready_heartbeat": {"status": "ready"},
                "final_cleanup": {"exit_code": 0, "post_stop_survivors": []},
            },
        ),
    ]


class NativeProcessProbeTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows producer")
    def test_native_probe_distinguishes_live_and_absent_pid(self) -> None:
        self.assertTrue(producer._pid_is_alive(os.getpid()))
        self.assertFalse(producer._pid_is_alive(0x7FFFFFFF))
    @unittest.skipUnless(os.name == "nt", "Windows producer")
    def test_native_termination_stops_only_owned_child(self) -> None:
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"]
        )
        try:
            self.assertTrue(producer._pid_is_alive(child.pid))
            producer._terminate_pid(child.pid)
            child.wait(timeout=5)
            self.assertFalse(producer._pid_is_alive(child.pid))
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)



class CoordinationFileTests(unittest.TestCase):
    def test_launch_removes_stale_coordination_files_before_spawn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            stale = [
                runtime / "channel-stale.jsonl",
                runtime / "heartbeat-stale.json",
                runtime / "stopmarker-stale.json",
            ]
            for path in stale:
                path.write_text("stale", encoding="utf-8")
            with mock.patch.object(producer, "RUNTIME_DIR", runtime), mock.patch.object(
                producer.subprocess, "Popen", return_value=mock.Mock()
            ) as popen:
                producer._launch_worker("stale")
            popen.assert_called_once()
            self.assertTrue(all(not path.exists() for path in stale))

class ReceiptByteTests(unittest.TestCase):
    def test_receipt_writer_uses_lf_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "receipt.json"
            producer._write_receipt_json(output, {"ticket": "EMBER-700", "ts": "x"})
            payload = output.read_bytes()
            self.assertNotIn(b"\r\n", payload)
            self.assertTrue(payload.endswith(b"\n"))

class PublicationTests(unittest.TestCase):
    def test_failed_lifecycle_publishes_no_partial_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "receipts"
            runtime = root / "runtime"
            launch = {"leg": "launch", "ts": "20260729T000000Z"}
            teardown = {"leg": "teardown", "ts": "20260729T000001Z"}
            with mock.patch.object(producer, "RECEIPTS_OUT_DIR", output), mock.patch.object(
                producer, "RUNTIME_DIR", runtime
            ), mock.patch.object(producer, "_verify_invariant"), mock.patch.object(
                producer,
                "build_launch_receipt",
                return_value=(launch, mock.Mock(), 123, Path("channel"), Path("heartbeat"), Path("stop")),
            ), mock.patch.object(
                producer, "build_teardown_receipt", return_value=teardown
            ), mock.patch.object(
                producer,
                "build_interrupted_resume_receipt",
                side_effect=RuntimeError("unproved interruption"),
            ):
                with self.assertRaisesRegex(RuntimeError, "unproved interruption"):
                    producer.main()
            self.assertEqual(list(output.glob("*.json")), [])

class Ind3ReceiptValidationTests(unittest.TestCase):
    def test_complete_executed_receipts_pass(self) -> None:
        ok, codes, _ = validator._validate_ind3(_valid_entries(), Path("."))
        self.assertTrue(ok)
        self.assertEqual(codes, set())

    def test_false_launch_liveness_is_rejected(self) -> None:
        entries = _valid_entries()
        entries[0][1]["verified_alive"] = False
        ok, codes, reason = validator._validate_ind3(entries, Path("."))
        self.assertFalse(ok)
        self.assertIn("invalid_operate_evidence", codes)
        self.assertIn("verified_alive", reason)

    def test_false_resume_liveness_is_rejected(self) -> None:
        entries = _valid_entries()
        entries[2][1]["resumed_verified_alive"] = False
        ok, codes, reason = validator._validate_ind3(entries, Path("."))
        self.assertFalse(ok)
        self.assertIn("invalid_operate_evidence", codes)
        self.assertIn("resumed_verified_alive", reason)

    def test_unclean_interruption_or_cleanup_is_rejected(self) -> None:
        entries = _valid_entries()
        entries[2][1]["interrupt_command_exit_code"] = 1
        entries[2][1]["final_cleanup"]["post_stop_survivors"] = ["bun.exe"]
        ok, codes, reason = validator._validate_ind3(entries, Path("."))
        self.assertFalse(ok)
        self.assertIn("invalid_operate_evidence", codes)
        self.assertIn("interrupt_command_exit_code", reason)
        self.assertIn("post_stop_survivors", reason)


if __name__ == "__main__":
    unittest.main()
