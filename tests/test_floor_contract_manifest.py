#!/usr/bin/env python3
"""TDD tests for floor_contract_manifest parsing and emission."""

import json
import pytest
import sys
from pathlib import Path

# Add scripts directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


def test_parse_floor_contract_manifest_valid():
    """Test parsing a valid floor contract with manifest output."""
    fixture_path = Path(__file__).parent / "fixtures/floor_manifest/floor-contract-valid.md"
    from ember_resident_training_gate import parse_floor_contract_manifest

    manifest, errors = parse_floor_contract_manifest(fixture_path)

    # Should have no errors
    assert not errors, f"Unexpected errors: {errors}"

    # Should have entries for all rows
    assert "Reserved vocab" in manifest
    assert "QAT" in manifest
    assert "BitNet 1.58-bit" in manifest
    assert "Sparse attention" in manifest
    assert "MoE" in manifest

    # Check structure of a deferred row entry
    bitnet_row = manifest["BitNet 1.58-bit"]
    assert bitnet_row["source_file"] == "docs/ember-floor-contract.md"
    assert bitnet_row["disposition"] in {"used_now", "preserved_trigger_gated", "blocked_with_exact_adapter_surface"}
    assert bitnet_row["trigger"] == "hardware escalation"
    assert bitnet_row["pilot"] == "ternary pilot"
    assert bitnet_row["kill_promote_condition"] == "promote on >=3B"
    assert "source_hash" in bitnet_row


def test_parse_floor_contract_manifest_missing_doc():
    """Test fail-closed on missing floor contract doc."""
    from ember_resident_training_gate import parse_floor_contract_manifest

    missing_path = Path("/nonexistent/floor-contract.md")
    manifest, errors = parse_floor_contract_manifest(missing_path)

    assert manifest is None
    assert "floor_contract.missing" in errors


def test_floor_contract_manifest_required_fields():
    """Test that manifest entries have all required fields."""
    fixture_path = Path(__file__).parent / "fixtures/floor_manifest/floor-contract-valid.md"
    from ember_resident_training_gate import parse_floor_contract_manifest

    manifest, errors = parse_floor_contract_manifest(fixture_path)

    required_fields = [
        "source_file",
        "source_hash",
        "disposition",
        "launch_vehicle_impact",
        "trigger",
        "pilot",
        "kill_promote_condition",
        "evidence_path",
    ]

    for row_name, row_data in manifest.items():
        assert isinstance(row_data, dict), f"Row {row_name} is not a dict"
        for field in required_fields:
            assert field in row_data, f"Row {row_name} missing field {field}"
            assert row_data[field] is not None, f"Row {row_name} field {field} is None"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
