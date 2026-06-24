#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import ember_avir_cli_process_supervision_gate as gate


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        launch = repo / "receipts" / "ember-preloop-resident-gate" / "launch.json"
        out = repo / "process.json"
        _write(launch, json.dumps({"ticket": "EMBER-AVIR-CLI-LAUNCH-PACKAGING-GATE", "verdict": "LAUNCH_PACKAGING_GATE_PASS"}))
        receipt = gate.build_receipt(repo=repo, launch_receipt=launch, out=out)
        assert receipt["verdict"] == "PROCESS_SUPERVISION_GATE_PASS"
        assert receipt["verification"]["checks"]["child_process_spawned_and_tracked"] is True
        assert receipt["verification"]["checks"]["timeout_terminated_child"] is True
        assert receipt["verification"]["checks"]["survivor_detection_clean"] is True
        assert receipt["verification"]["checks"]["background_lifecycle_accounted"] is True
        assert receipt["deletion_ablation"]["supervisor_deleted_blocks_spawn_and_tracking"] is True
        assert receipt["deletion_ablation"]["manual_taskkill_insufficient"] is True
    print("EMBER_AVIR_CLI_PROCESS_SUPERVISION_GATE_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
