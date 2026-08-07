#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from nativization_motion import build_run_import_manifest, measure_layer, run_nativization_motion


def _fixture(root: Path):
    phase = root / "tools" / "ember-restart-3b"
    phase.mkdir(parents=True)
    (phase / "model.py").write_text("MODEL = 1\n", encoding="utf-8")
    (phase / "pretrain.py").write_text("TRAIN = 1\n", encoding="utf-8")
    (phase / "run_vertical_slice.py").write_text("GROWTH = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "fixture"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)


def test_git_owned_imports_are_not_borrowed(tmp_path):
    _fixture(tmp_path)
    tools = tmp_path / "tools"
    (tools / "owned_helper.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tools / "measure.py").write_text("import torch\nimport owned_helper\nimport numpy\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "owned"], cwd=tmp_path, check=True)
    measurement = measure_layer(tmp_path, "x", ["tools/**/*.py"])
    assert "torch" in measurement.borrowed_deps
    assert "numpy" in measurement.borrowed_deps
    assert "owned_helper" not in measurement.borrowed_deps
    assert measurement.owned_loc > 0


def test_phase_transit_is_symbol_bound_not_filename_bound(tmp_path):
    _fixture(tmp_path)
    phase = tmp_path / "tools" / "ember-restart-3b"
    (phase / "model.py").write_text("import torch\nRESULT = torch.matmul(None, None)\n", encoding="utf-8")
    (phase / "pretrain.py").write_text("import torch\nloss = torch.tensor(0)\nloss.backward()\n", encoding="utf-8")
    (phase / "run_vertical_slice.py").write_text("import torch\nRESULT = torch.matmul(None, None)\n", encoding="utf-8")
    (tmp_path / "tools" / "aaa_cuda_filename_only.py").write_text("CUDA = True\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "semantic"], cwd=tmp_path, check=True)
    names = ["CUDA kernels (cuBLAS matmul, elementwise)", "Autograd (" + chr(96) + "grad_fn" + chr(96) + " graph, " + chr(96) + "backward()" + chr(96) + ")"]
    manifest_path = tmp_path / "manifest.json"
    manifest_path, _ = build_run_import_manifest(tmp_path, names, output_path=manifest_path)
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    shares = {row["name"]: row["critical_path_share"] for row in document["layers"]}
    autograd = names[1]
    assert shares[names[0]]["creation"] is True
    assert shares[autograd]["creation"] is False
    assert shares[autograd]["current_rung_training"] is True


def test_motion_requires_explicit_predecessor_authority(tmp_path):
    _fixture(tmp_path)
    docs = tmp_path / "docs" / "design"
    docs.mkdir(parents=True)
    (docs / "ember-owned-substrate-diagnostic.md").write_text(
        "## The inherited stack, bottom " + chr(0x2192) + " top, with the blocking line\n\n"
        "| layer | what | rel |\n|---|---|---|\n"
        "| CUDA kernels (cuBLAS matmul, elementwise) | x | component |\n",
        encoding="utf-8",
    )
    (tmp_path / "INVARIANT.md").write_text("owned", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "authority"], cwd=tmp_path, check=True)
    manifest_path, manifest_sha = build_run_import_manifest(tmp_path, ["CUDA kernels (cuBLAS matmul, elementwise)"], output_path=tmp_path / "manifest.json")
    receipts = tmp_path / "receipts" / "nativization-motion"
    receipts.mkdir(parents=True)
    (receipts / "nm-old.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="predecessor"):
        run_nativization_motion(
            tmp_path,
            run_import_manifest_path=manifest_path,
            expected_run_import_manifest_sha256=manifest_sha,
            prior_receipt_path=None,
            expected_prior_receipt_sha256=None,
        )