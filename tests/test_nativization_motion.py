#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""
TDD tests for nativization_motion runner.

Fixture-driven, zero network, CI-unconditional.
"""

import json
import sys
import tempfile
from pathlib import Path

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from nativization_motion import (
    collect_imports,
    compute_deltas,
    get_invariant_sha,
    identify_next_home_candidate,
    load_prior_receipt,
    measure_layer,
    parse_diagnostic_map,
    run_nativization_motion,
    scan_binaries,
    sha256_file,
)


class TestImportCollection:
    """Test import parsing from Python files."""

    def test_collect_imports_basic(self, tmp_path):
        """Test basic import collection."""
        test_file = tmp_path / "test.py"
        test_file.write_text(
            """\
import sys
import torch
from numpy import array

x = 1
""",
            encoding="utf-8",
        )

        imports, line_count = collect_imports(test_file)

        # Should find torch and numpy; sys is stdlib
        assert "torch" in imports
        assert "numpy" in imports
        assert "sys" not in imports  # stdlib excluded
        assert line_count == 3  # Three import lines (sys, torch, numpy)

    def test_collect_imports_excludes_stdlib(self, tmp_path):
        """Test that stdlib modules are excluded."""
        test_file = tmp_path / "test.py"
        test_file.write_text(
            """\
import os
import sys
import json
import torch
""",
            encoding="utf-8",
        )

        imports, _ = collect_imports(test_file)

        # Should only find torch
        assert "torch" in imports
        assert "os" not in imports
        assert "sys" not in imports
        assert "json" not in imports

    def test_collect_imports_empty_file(self, tmp_path):
        """Test empty Python file."""
        test_file = tmp_path / "empty.py"
        test_file.write_text("", encoding="utf-8")

        imports, line_count = collect_imports(test_file)

        assert len(imports) == 0
        assert line_count == 0

    def test_collect_imports_nonexistent_file(self, tmp_path):
        """Test handling of nonexistent file."""
        imports, line_count = collect_imports(tmp_path / "nonexistent.py")

        assert len(imports) == 0
        assert line_count == 0


class TestBinaryScanning:
    """Test binary/subprocess detection."""

    def test_scan_binaries_subprocess_run(self, tmp_path):
        """Test detection of subprocess.run calls."""
        test_file = tmp_path / "test.py"
        test_file.write_text(
            """\
import subprocess
subprocess.run("git clone ...")
subprocess.run("docker run ...")
""",
            encoding="utf-8",
        )

        binaries = scan_binaries(test_file)

        # Should detect git and docker
        assert any("git" in b for b in binaries)
        assert any("docker" in b for b in binaries)

    def test_scan_binaries_subprocess_popen(self, tmp_path):
        """Test detection of Popen calls."""
        test_file = tmp_path / "test.py"
        test_file.write_text(
            """\
import subprocess
p = subprocess.Popen("bun run script")
""",
            encoding="utf-8",
        )

        binaries = scan_binaries(test_file)

        assert any("bun" in b for b in binaries)

    def test_scan_binaries_empty_file(self, tmp_path):
        """Test empty file returns no binaries."""
        test_file = tmp_path / "test.py"
        test_file.write_text("", encoding="utf-8")

        binaries = scan_binaries(test_file)

        assert len(binaries) == 0


class TestDiagnosticParsing:
    """Test diagnostic map parsing."""

    def test_parse_diagnostic_basic(self, tmp_path):
        """Test parsing a valid diagnostic map."""
        diagnostic_file = tmp_path / "diagnostic.md"
        diagnostic_file.write_text(
            """\
# Diagnostic

## The inherited stack, bottom → top, with the blocking line

| layer | what it is | ember's relationship |
|---|---|---|
| CUDA kernels (cuBLAS matmul, elementwise) | raw GPU compute | **component** |
| Tensor abstraction (storage/strides/dtype) | array container | **component** |
| Autograd (grad_fn graph, backward()) | builds a reverse-mode graph | **BLOCKS** |
""",
            encoding="utf-8",
        )

        layers = parse_diagnostic_map(diagnostic_file)

        assert len(layers) == 3
        assert "CUDA kernels (cuBLAS matmul, elementwise)" in layers
        assert "Tensor abstraction (storage/strides/dtype)" in layers
        assert "Autograd (grad_fn graph, backward())" in layers

    def test_parse_diagnostic_missing_heading(self, tmp_path):
        """Test failure when expected heading is missing."""
        diagnostic_file = tmp_path / "diagnostic.md"
        diagnostic_file.write_text(
            """\
# Diagnostic

## Wrong Heading

Some content here.
""",
            encoding="utf-8",
        )

        try:
            parse_diagnostic_map(diagnostic_file)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Expected heading not found" in str(e)

    def test_parse_diagnostic_missing_table(self, tmp_path):
        """Test failure when table is missing."""
        diagnostic_file = tmp_path / "diagnostic.md"
        diagnostic_file.write_text(
            """\
# Diagnostic

## The inherited stack, bottom → top, with the blocking line

No table here.
""",
            encoding="utf-8",
        )

        try:
            parse_diagnostic_map(diagnostic_file)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Expected table format not found" in str(e)


class TestMeasureLayer:
    """Test layer measurement."""

    def test_measure_layer_single_file(self, tmp_path):
        """Test measuring a layer with a single file."""
        # Create test file structure
        layer_dir = tmp_path / "tools"
        layer_dir.mkdir()

        test_file = layer_dir / "test.py"
        test_file.write_text(
            """\
import torch
import numpy as np
import sys

x = 1
""",
            encoding="utf-8",
        )

        # Measure layer
        measurement = measure_layer(tmp_path, "Test Layer", ["tools/**/*.py"])

        assert measurement.name == "Test Layer"
        assert "torch" in measurement.borrowed_deps
        assert "numpy" in measurement.borrowed_deps
        assert "sys" not in measurement.borrowed_deps
        assert measurement.borrowed_deps_count == 2

    def test_measure_layer_multiple_files(self, tmp_path):
        """Test measuring a layer with multiple files."""
        layer_dir = tmp_path / "tools"
        layer_dir.mkdir()

        # File 1
        (layer_dir / "file1.py").write_text("import torch\nimport sys\n")

        # File 2
        (layer_dir / "file2.py").write_text("import numpy\nimport torch\n")

        # Measure layer
        measurement = measure_layer(tmp_path, "Test Layer", ["tools/**/*.py"])

        # Should find torch and numpy (deduplicated)
        assert measurement.borrowed_deps_count == 2
        assert set(measurement.borrowed_deps) == {"torch", "numpy"}

    def test_measure_layer_no_matching_files(self, tmp_path):
        """Test measuring layer with no matching files."""
        measurement = measure_layer(tmp_path, "Empty Layer", ["nonexistent/**/*.py"])

        assert measurement.borrowed_deps_count == 0
        assert len(measurement.borrowed_deps) == 0


class TestComputeDeltas:
    """Test delta computation."""

    def test_compute_deltas_first_receipt(self):
        """Test first receipt has null delta."""
        from nativization_motion import LayerMeasurement

        layers = [
            LayerMeasurement(
                name="Layer A",
                borrowed_deps=["torch"],
                borrowed_deps_count=1,
                borrowed_loc=10,
                owned_loc=50,
                borrowed_binaries=[],
            ),
        ]

        deltas = compute_deltas(layers, None)

        assert deltas is None

    def test_compute_deltas_vs_prior(self):
        """Test delta computation vs prior receipt."""
        from nativization_motion import LayerMeasurement

        current = [
            LayerMeasurement(
                name="Layer A",
                borrowed_deps=["torch", "numpy"],
                borrowed_deps_count=2,
                borrowed_loc=15,
                owned_loc=50,
                borrowed_binaries=[],
            ),
        ]

        prior = {
            "layers": [
                {
                    "name": "Layer A",
                    "borrowed_deps_count": 1,
                    "borrowed_loc": 10,
                },
            ],
        }

        deltas = compute_deltas(current, prior)

        assert deltas is not None
        assert deltas["Layer A"]["borrowed_deps_delta"] == 1
        assert deltas["Layer A"]["borrowed_loc_delta"] == 5


class TestIdentifyNextHomeCandidate:
    """Test next home candidate identification."""

    def test_identify_next_home_highest_deps(self, tmp_path):
        """Test that highest borrowed_deps layer is selected."""
        from nativization_motion import LayerMeasurement

        layers = [
            LayerMeasurement(
                name="Layer A",
                borrowed_deps=["torch"],
                borrowed_deps_count=1,
                borrowed_loc=10,
                owned_loc=50,
                borrowed_binaries=[],
            ),
            LayerMeasurement(
                name="Layer B",
                borrowed_deps=["torch", "numpy", "scipy"],
                borrowed_deps_count=3,
                borrowed_loc=20,
                owned_loc=30,
                borrowed_binaries=[],
            ),
        ]

        diagnostic_file = tmp_path / "diagnostic.md"
        diagnostic_file.write_text("")

        candidate = identify_next_home_candidate(layers, diagnostic_file)

        assert candidate == "Layer B"

    def test_identify_next_home_empty_layers(self, tmp_path):
        """Test with empty layer list."""
        diagnostic_file = tmp_path / "diagnostic.md"
        diagnostic_file.write_text("")

        candidate = identify_next_home_candidate([], diagnostic_file)

        assert candidate is None


class TestEndToEnd:
    """End-to-end integration tests."""

    def test_run_nativization_motion_fixture(self, tmp_path):
        """Test full runner with fixture mini-tree."""
        # Create fixture structure
        docs_dir = tmp_path / "docs" / "design"
        docs_dir.mkdir(parents=True)

        diagnostic_file = docs_dir / "ember-owned-substrate-diagnostic.md"
        diagnostic_file.write_text(
            """\
# Diagnostic

## The inherited stack, bottom → top, with the blocking line

| layer | what it is | ember's relationship |
|---|---|---|
| CUDA kernels (cuBLAS matmul, elementwise) | raw GPU compute | component |
| Tensor abstraction (storage/strides/dtype) | array container | component |
""",
            encoding="utf-8",
        )

        # Create INVARIANT.md
        invariant_file = tmp_path / "INVARIANT.md"
        invariant_file.write_text(
            "invariant_sha256: abc123def456",
            encoding="utf-8",
        )

        # Create test Python files
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()

        (tools_dir / "cuda.py").write_text(
            """\
import torch
import sys
import subprocess
subprocess.run("llama-server")
""",
            encoding="utf-8",
        )

        (tools_dir / "tensor.py").write_text(
            """\
import numpy
import torch
""",
            encoding="utf-8",
        )

        # Run the runner
        receipt_path = run_nativization_motion(tmp_path)

        # Verify receipt was created
        assert Path(receipt_path).exists()

        # Load and verify receipt content
        with open(receipt_path) as f:
            receipt = json.load(f)

        assert receipt["method"] == "static-import-census-v1"
        assert len(receipt["layers"]) == 2
        assert receipt["deltas"] is None  # First receipt
        assert receipt["next_home_candidate"] is not None
        assert len(receipt["limits"]) > 0

        # Verify layer measurements
        cuda_layer = next(
            (l for l in receipt["layers"] if "CUDA" in l["name"]), None
        )
        tensor_layer = next(
            (l for l in receipt["layers"] if "Tensor" in l["name"]), None
        )

        assert cuda_layer is not None
        assert tensor_layer is not None
        assert "torch" in cuda_layer["borrowed_deps"]
        assert "numpy" in tensor_layer["borrowed_deps"]

    def test_run_nativization_motion_delta_receipt(self, tmp_path):
        """Test that second receipt computes deltas correctly."""
        # Create fixture structure
        docs_dir = tmp_path / "docs" / "design"
        docs_dir.mkdir(parents=True)

        diagnostic_file = docs_dir / "ember-owned-substrate-diagnostic.md"
        diagnostic_file.write_text(
            """\
# Diagnostic

## The inherited stack, bottom → top, with the blocking line

| layer | what it is | ember's relationship |
|---|---|---|
| CUDA kernels (cuBLAS matmul, elementwise) | raw GPU compute | component |
""",
            encoding="utf-8",
        )

        # Create INVARIANT.md
        invariant_file = tmp_path / "INVARIANT.md"
        invariant_file.write_text(
            "invariant_sha256: abc123def456",
            encoding="utf-8",
        )

        # Create test Python files
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()

        (tools_dir / "cuda.py").write_text(
            """\
import torch
import numpy
""",
            encoding="utf-8",
        )

        # Create prior receipt
        receipts_dir = tmp_path / "receipts" / "nativization-motion"
        receipts_dir.mkdir(parents=True)

        prior_receipt = {
            "layers": [
                {
                    "name": "CUDA kernels (cuBLAS matmul, elementwise)",
                    "borrowed_deps_count": 1,
                    "borrowed_loc": 1,
                },
            ],
        }

        with open(receipts_dir / "nm-20260701T000000Z.json", "w") as f:
            json.dump(prior_receipt, f)

        # Run the runner
        receipt_path = run_nativization_motion(tmp_path)

        # Load receipt
        with open(receipt_path) as f:
            receipt = json.load(f)

        # Should have deltas now
        assert receipt["deltas"] is not None
        cuda_deltas = receipt["deltas"]["CUDA kernels (cuBLAS matmul, elementwise)"]
        assert cuda_deltas["borrowed_deps_delta"] == 1  # 2 - 1
        assert cuda_deltas["borrowed_loc_delta"] == 1  # 2 - 1


def pytest_generate_tests(metafunc):
    """Pytest hook for fixture parameterization."""
    if "tmp_path" in metafunc.fixturenames:
        pass  # Use pytest's built-in tmp_path


if __name__ == "__main__":
    # Simple test runner
    import pytest

    pytest.main([__file__, "-v"])
