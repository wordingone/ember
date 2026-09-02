#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Selftest for the Ember MVP Windows-native sandbox runner."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import ember_windows_sandbox as sandbox


def _assert_probe(row: dict, name: str, verdict: str) -> None:
    assert row["probe"] == name
    assert row["verdict"] == verdict, row
    assert row["receipt"]["probe"] == name
    assert row["receipt"]["verdict"] == verdict
    assert row["receipt"]["cwd_inside_temp_root"] is True
    assert row["receipt"]["network_result"] in {"denied", "not_attempted"}
    assert row["receipt"]["filesystem_result"] in {"contained", "denied"}
    assert row["receipt"]["process_cleanup_result"] in {"clean", "killed"}


def test_required_probe_battery() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-win-sandbox-") as td:
        result = sandbox.run_required_probe_battery(Path(td))
        rows = {row["probe"]: row for row in result["rows"]}

        assert result["ticket"] == "EMBER-WINDOWS-SANDBOX-SELFTEST"
        assert result["windows_native_runner"] == (os.name == "nt")
        assert result["job_object_limit_requested"] is True
        assert result["summary"]["total"] == 10
        assert result["summary"]["pass"] == 10

        _assert_probe(rows["legit-solve"], "legit-solve", "pass")
        _assert_probe(rows["eq-dispatch"], "eq-dispatch", "denied")
        _assert_probe(rows["removed-builtin-open"], "removed-builtin-open", "denied")
        _assert_probe(rows["object-reachability"], "object-reachability", "denied")
        _assert_probe(rows["timeout"], "timeout", "killed")
        _assert_probe(rows["memory-bomb"], "memory-bomb", "denied")
        _assert_probe(rows["filesystem-escape"], "filesystem-escape", "denied")
        _assert_probe(rows["subprocess-cleanup"], "subprocess-cleanup", "killed")
        _assert_probe(rows["network-attempt"], "network-attempt", "denied")
        _assert_probe(rows["deterministic-replay"], "deterministic-replay", "pass")

        assert rows["subprocess-cleanup"]["receipt"]["process_tree_marker_exists"] is False
        assert rows["filesystem-escape"]["receipt"]["escape_path_exists"] is False
        assert rows["timeout"]["receipt"]["timeout_result"] == "killed"
        assert rows["memory-bomb"]["receipt"]["memory_result"] in {"killed", "denied"}
        replay = rows["deterministic-replay"]["receipt"]["replay_result"]
        assert replay["runs"] == 2
        assert replay["outputs_match"] is True
        assert replay["stdout_sha256"].startswith("sha256:")


def test_receipt_file_is_written_and_validated() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-win-sandbox-") as td:
        result = sandbox.run_required_probe_battery(Path(td))
        receipt_path = Path(result["receipt_path"])
        assert receipt_path.exists(), receipt_path
        loaded = sandbox.load_receipt(receipt_path)
        assert loaded["summary"]["pass"] == 10
        sandbox.validate_battery_receipt(loaded)


def test_windows_receipt_requires_actual_job_assignment() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-win-sandbox-") as td:
        result = sandbox.run_required_probe_battery(Path(td))
        broken = dict(result)
        broken["rows"] = [dict(row) for row in result["rows"]]
        broken["rows"][0]["receipt"] = dict(broken["rows"][0]["receipt"])
        broken["rows"][0]["receipt"]["job_object"] = dict(broken["rows"][0]["receipt"]["job_object"])
        broken["rows"][0]["receipt"]["job_object"]["assigned"] = False

        try:
            sandbox.validate_battery_receipt(broken)
        except sandbox.SandboxValidationError as exc:
            assert "job object was not assigned" in str(exc)
        else:
            raise AssertionError("Windows sandbox receipts must reject unassigned Job Objects")


def test_production_candidate_runner_emits_readiness_enggible_receipt() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-win-sandbox-") as td:
        result = sandbox.run_production_candidate(
            Path(td),
            cycle_id="cycle-prod-sandbox-0001",
            src="def solve(n):\n    return n + 1\n",
            call_expr="solve(4)",
            expected=5,
        )

        assert result["ticket"] == "EMBER-MVP-SANDBOX-PRODUCTION"
        assert result["cycle_id"] == "cycle-prod-sandbox-0001"
        assert result["mode"] == "windows-native-production-candidate-runner"
        assert result["verdict"] == "pass"
        assert result["windows_native_runner"] is True
        assert result["job_object_limit_requested"] is True
        assert result["fresh_temp_root"] is True
        assert result["brokered_filesystem"] is True
        assert result["network_default_denied"] is True
        assert result["summary"]["pass"] == result["summary"]["total"]
        assert result["summary"]["total"] >= 9
        assert result["candidate"]["verdict"] == "pass"
        sandbox.validate_production_receipt(result)


def test_production_candidate_receipt_requires_job_assignment() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-win-sandbox-") as td:
        result = sandbox.run_production_candidate(
            Path(td),
            cycle_id="cycle-prod-sandbox-0001",
            src="def solve(n):\n    return n + 1\n",
            call_expr="solve(4)",
            expected=5,
        )
        broken = dict(result)
        broken["candidate"] = dict(result["candidate"])
        broken["candidate"]["job_object"] = dict(result["candidate"]["job_object"])
        broken["candidate"]["job_object"]["assigned"] = False

        try:
            sandbox.validate_production_receipt(broken)
        except sandbox.SandboxValidationError as exc:
            assert "production candidate job object was not assigned" in str(exc)
        else:
            raise AssertionError("production candidate receipt must reject unassigned Job Object")


def main() -> int:
    test_required_probe_battery()
    test_receipt_file_is_written_and_validated()
    test_windows_receipt_requires_actual_job_assignment()
    test_production_candidate_runner_emits_readiness_enggible_receipt()
    test_production_candidate_receipt_requires_job_assignment()
    print("EMBER_WINDOWS_SANDBOX_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
