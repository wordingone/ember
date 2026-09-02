#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""CLI contract selftest for ember_train_multimodal_resident_adapter."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    repo = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
    with tempfile.TemporaryDirectory(prefix="ember-train-adapter-cli-") as td:
        out_dir = Path(td) / "adapter-out"
        proc = subprocess.run(
            [
                sys.executable,
                str(repo / "scripts" / "ember_train_multimodal_resident_adapter.py"),
                "--train-script",
                "scripts\\train_multimodal_v0.py",
                "--out-dir",
                str(out_dir),
            ],
            cwd=str(repo),
            text=True,
            capture_output=True,
            timeout=60,
        )
        assert proc.returncode == 0, proc.stderr + proc.stdout
        assert (out_dir / "resident_training_candidate_manifest.json").exists()
        assert (out_dir / "train_multimodal_resident_adapter_receipt.json").exists()
    print("EMBER_TRAIN_MULTIMODAL_RESIDENT_ADAPTER_CLI_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
