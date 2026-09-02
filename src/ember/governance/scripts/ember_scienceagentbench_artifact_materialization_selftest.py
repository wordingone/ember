#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Selftest for ScienceAgentBench artifact materialization blocker receipts."""
from __future__ import annotations

import tempfile
from pathlib import Path

import ember_scienceagentbench_artifact_materialization as materialize


def test_blocked_receipt_preserves_scienceagentbench_after_unauthorized_probes() -> None:
    with tempfile.TemporaryDirectory(prefix="sab-artifact-materialization-") as td:
        out = Path(td) / "blocked.json"
        receipt = materialize.build_blocked_receipt(
            repo=Path.cwd(),
            out=out,
            artifact_url="https://example.invalid/benchmark_verified.zip",
            expected_local_path=Path(td) / "benchmark_verified.zip",
            probes=[
                {
                    "method": "HEAD",
                    "ok": False,
                    "status": 401,
                    "error_type": "HTTPError",
                    "error": "HTTP Error 401: Unauthorized",
                },
                {
                    "method": "GET",
                    "range": "bytes=0-0",
                    "ok": False,
                    "status": 401,
                    "error_type": "HTTPError",
                    "error": "HTTP Error 401: Unauthorized",
                },
            ],
        )
        assert receipt["verdict"] == "SCIENCEAGENTBENCH_ARTIFACT_MATERIALIZATION_BLOCKED"
        assert receipt["blocked_reasons"] == ["sharepoint_artifact_requires_authorized_access"]
        assert receipt["scienceagentbench_artifact_status"]["full_artifact_exists"] is False
        assert receipt["next_benchmark"]["selected"] == "scienceagentbench"
        assert "ember_scienceagentbench_admission.py" in receipt["next_benchmark"]["next_executable_command"]
        assert receipt["deleted_selector_routing"]["admission_state"] == "ROUTING_BLOCKED_DELETED_SELECTOR"
        assert receipt["deletion_sensitive"] is True
        assert out.exists()


def test_receipt_refuses_to_block_when_probe_succeeds() -> None:
    with tempfile.TemporaryDirectory(prefix="sab-artifact-materialization-") as td:
        try:
            materialize.build_blocked_receipt(
                repo=Path.cwd(),
                out=Path(td) / "blocked.json",
                artifact_url="https://example.invalid/benchmark_verified.zip",
                expected_local_path=Path(td) / "benchmark_verified.zip",
                probes=[{"method": "HEAD", "ok": True, "status": 200}],
            )
        except ValueError as exc:
            assert "successful artifact probe" in str(exc)
        else:
            raise AssertionError("successful probe must not produce a blocked receipt")


def main() -> int:
    for test in [
        test_blocked_receipt_preserves_scienceagentbench_after_unauthorized_probes,
        test_receipt_refuses_to_block_when_probe_succeeds,
    ]:
        test()
    print("EMBER_SCIENCEAGENTBENCH_ARTIFACT_MATERIALIZATION_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
