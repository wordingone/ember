#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Selftest for ScienceAgentBench artifact intake receipts."""
from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

import ember_scienceagentbench_artifact_intake as intake


def test_missing_source_blocks_and_preserves_sab() -> None:
    with tempfile.TemporaryDirectory(prefix="sab-intake-") as td:
        root = Path(td)
        out = root / "receipt.json"
        receipt = intake.build_receipt(
            repo=Path.cwd(),
            out=out,
            source=root / "missing.zip",
            target=root / "target" / "benchmark_verified.zip",
            extract_dir=root / "extract",
            do_extract=False,
        )
        assert receipt["verdict"] == "SCIENCEAGENTBENCH_ARTIFACT_INTAKE_BLOCKED"
        assert receipt["blocked_reasons"] == ["source_artifact_missing"]
        assert receipt["native_operator_routing"]["selected"] == "scienceagentbench"
        assert receipt["deleted_selector_routing"]["admission_state"] == "ROUTING_BLOCKED_DELETED_SELECTOR"
        assert receipt["deletion_sensitive"] is True
        assert out.exists()


def test_present_zip_wrong_size_copies_and_blocks_on_size_only() -> None:
    with tempfile.TemporaryDirectory(prefix="sab-intake-") as td:
        root = Path(td)
        source = root / "benchmark_verified.zip"
        with zipfile.ZipFile(source, "w") as zf:
            zf.writestr("benchmark/sample.txt", "ok")
        target = root / "target" / "benchmark_verified.zip"
        receipt = intake.build_receipt(
            repo=Path.cwd(),
            out=root / "receipt.json",
            source=source,
            target=target,
            extract_dir=root / "extract",
            do_extract=False,
        )
        assert target.exists()
        assert receipt["scienceagentbench_artifact_status"]["copied_to_target"] is True
        assert receipt["scienceagentbench_artifact_status"]["zip_password_probe"]["ok"] is True
        assert receipt["blocked_reasons"] == ["artifact_size_mismatch"]
        assert receipt["scienceagentbench_artifact_status"]["downloaded_or_unzipped_data_redistributed"] is False


def main() -> int:
    for test in [
        test_missing_source_blocks_and_preserves_sab,
        test_present_zip_wrong_size_copies_and_blocks_on_size_only,
    ]:
        test()
    print("EMBER_SCIENCEAGENTBENCH_ARTIFACT_INTAKE_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())