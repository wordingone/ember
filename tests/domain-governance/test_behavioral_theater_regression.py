#!/usr/bin/env python3
"""Behavioral theater-regression: proves parse_floor_contract_manifest capability is NEW.

Run tests against PRE-CHANGE module and show RAW FAILURES.
Current module should PASS all tests; pre-change should FAIL or skip them.
"""

import json
import sys
from pathlib import Path

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


def test_parse_floor_contract_manifest_returns_dict_keyed_by_component():
    """BEHAVIORAL: manifest is dict keyed by component name with all fields."""
    try:
        from ember_resident_training_gate import parse_floor_contract_manifest
    except ImportError:
        print("SKIP: parse_floor_contract_manifest not found in module (PRE-CHANGE)")
        return

    fixture_path = Path(__file__).parent / "fixtures/floor_manifest/floor-contract-valid.md"
    manifest, errors = parse_floor_contract_manifest(fixture_path)

    assert manifest is not None, "Manifest should be dict (not None)"
    assert isinstance(manifest, dict), f"Manifest should be dict, got {type(manifest)}"
    assert len(manifest) > 0, "Manifest should have component entries"

    # Verify structure: each key is component name, each value is field dict
    for component_name, fields_dict in manifest.items():
        assert isinstance(component_name, str), f"Component key must be string, got {type(component_name)}"
        assert isinstance(fields_dict, dict), f"Component {component_name} value must be dict"

        # Verify required fields
        required_fields = {
            "source_file", "source_sha256", "disposition", "launch_vehicle_impact",
            "trigger", "pilot", "kill_promote_condition", "evidence_path"
        }
        for field in required_fields:
            assert field in fields_dict, f"Component {component_name} missing field {field}"
            assert fields_dict[field] is not None, f"Component {component_name} field {field} is None"

    print(f"PASS: Manifest correctly keyed by component name ({len(manifest)} entries)")


def test_missing_floor_contract_doc_returns_blocked():
    """BEHAVIORAL: missing doc returns (None, errors) with error code."""
    try:
        from ember_resident_training_gate import parse_floor_contract_manifest
    except ImportError:
        print("SKIP: parse_floor_contract_manifest not found in module (PRE-CHANGE)")
        return

    missing_path = Path("/nonexistent/floor-contract.md")
    manifest, errors = parse_floor_contract_manifest(missing_path)

    assert manifest is None, f"Manifest should be None for missing doc, got {manifest}"
    assert len(errors) > 0, f"Errors should not be empty, got {errors}"
    assert any("floor_contract.missing" in err for err in errors), \
        f"Should have floor_contract.missing error, got {errors}"

    print(f"PASS: Missing doc returns (None, errors) with correct code")


def test_unparseable_doc_returns_blocked():
    """BEHAVIORAL: unparseable doc (no valid tables) returns (None, errors)."""
    try:
        from ember_resident_training_gate import parse_floor_contract_manifest
    except ImportError:
        print("SKIP: parse_floor_contract_manifest not found in module (PRE-CHANGE)")
        return

    # Create a temp unparseable fixture (just text, no tables)
    unparseable_path = Path(__file__).parent / "fixtures/floor_manifest/floor-contract-unparseable.md"
    unparseable_path.parent.mkdir(parents=True, exist_ok=True)
    unparseable_path.write_text("# Ember Floor Contract\n\nNo valid tables here, just text.\n")

    manifest, errors = parse_floor_contract_manifest(unparseable_path)

    assert manifest is None, f"Manifest should be None for unparseable doc"
    assert len(errors) > 0, f"Errors should not be empty"

    print(f"PASS: Unparseable doc returns (None, errors)")


def test_parse_failure_blocks_gate_verdict():
    """BEHAVIORAL VERDICT-COUPLING: parse failure makes GATE VERDICT BLOCKED."""
    try:
        from ember_resident_training_gate import inspect_floor_contracts
    except ImportError:
        print("SKIP: inspect_floor_contracts not found (PRE-CHANGE)")
        return

    # Test with a repo that has no floor-contract.md
    missing_repo = Path(__file__).parent / "fixtures/floor_manifest/missing-repo"
    missing_repo.mkdir(parents=True, exist_ok=True)

    result, errors = inspect_floor_contracts(missing_repo)

    # The key behavioral test: gate verdict should be BLOCKED, not PASS
    assert result["status"] == "BLOCKED", \
        f"Gate verdict should be BLOCKED when floor contract missing, got {result['status']}"

    # And there should be errors in the errors list
    assert len(errors) > 0, "Errors list should not be empty"

    print(f"PASS: Parse failure blocks gate verdict (status={result['status']}, errors={len(errors)})")


def test_disposition_mapping_correct():
    """BEHAVIORAL: Unknown statuses map to UNMAPPED-STATUS:<verbatim>, not preserved_trigger_gated."""
    try:
        from ember_resident_training_gate import _map_status_to_disposition
    except ImportError:
        print("SKIP: _map_status_to_disposition not found (PRE-CHANGE)")
        return

    # Test known status
    assert _map_status_to_disposition("RE-STAGED") == "preserved_trigger_gated"

    # Test unknown status - should NOT be preserved_trigger_gated
    unknown_result = _map_status_to_disposition("FUTURE_UNKNOWN_STATUS")
    assert "UNMAPPED-STATUS" in unknown_result, \
        f"Unknown status should map to UNMAPPED-STATUS, got {unknown_result}"
    assert unknown_result == "UNMAPPED-STATUS:FUTURE_UNKNOWN_STATUS", \
        f"Should preserve unknown status verbatim, got {unknown_result}"

    print(f"PASS: Unknown status maps to UNMAPPED-STATUS:<verbatim>")


def test_missing_fields_get_undeclared_in_doc():
    """BEHAVIORAL: Missing table columns map to UNDECLARED-IN-DOC."""
    try:
        from ember_resident_training_gate import parse_floor_contract_manifest
    except ImportError:
        print("SKIP: parse_floor_contract_manifest not found (PRE-CHANGE)")
        return

    fixture_path = Path(__file__).parent / "fixtures/floor_manifest/floor-contract-sparse.md"
    fixture_path.parent.mkdir(parents=True, exist_ok=True)

    # Fixture with minimal columns (missing many expected columns)
    fixture_path.write_text("""# Ember Floor Contract

## What v0 already carries

| Component |
|-----------|
| MinimalComponent |

## Deferral rows

| Component | Status |
|-----------|--------|
| TestComponent | RE-STAGED |
""")

    manifest, errors = parse_floor_contract_manifest(fixture_path)

    assert manifest is not None
    # Check that missing fields are filled with UNDECLARED-IN-DOC
    for component_name, fields in manifest.items():
        # At least some fields should be UNDECLARED-IN-DOC since fixture is sparse
        undeclared_count = sum(1 for v in fields.values() if v == "UNDECLARED-IN-DOC")
        assert undeclared_count > 0, \
            f"Component {component_name} should have UNDECLARED-IN-DOC for missing fields"

    print(f"PASS: Missing fields correctly map to UNDECLARED-IN-DOC")


if __name__ == "__main__":
    import io
    from contextlib import redirect_stdout

    tests = [
        ("test_parse_floor_contract_manifest_returns_dict_keyed_by_component", test_parse_floor_contract_manifest_returns_dict_keyed_by_component),
        ("test_missing_floor_contract_doc_returns_blocked", test_missing_floor_contract_doc_returns_blocked),
        ("test_unparseable_doc_returns_blocked", test_unparseable_doc_returns_blocked),
        ("test_parse_failure_blocks_gate_verdict", test_parse_failure_blocks_gate_verdict),
        ("test_disposition_mapping_correct", test_disposition_mapping_correct),
        ("test_missing_fields_get_undeclared_in_doc", test_missing_fields_get_undeclared_in_doc),
    ]

    print("=" * 80)
    print("BEHAVIORAL THEATER-REGRESSION TESTS")
    print("=" * 80)
    print()

    passed = 0
    skipped = 0
    failed = 0

    for test_name, test_func in tests:
        try:
            # Capture output to check for SKIP
            output = io.StringIO()
            with redirect_stdout(output):
                test_func()
            output_str = output.getvalue()

            if "SKIP" in output_str:
                print(f"[SKIP] {test_name}")
                print(f"       {output_str.strip()}")
                skipped += 1
            else:
                print(f"[PASS] {test_name}")
                if output_str.strip():
                    print(f"       {output_str.strip()}")
                passed += 1
        except AssertionError as e:
            print(f"[FAIL] {test_name}")
            print(f"       {str(e)}")
            failed += 1
        except Exception as e:
            print(f"[ERROR] {test_name}")
            print(f"        {type(e).__name__}: {str(e)}")
            failed += 1

    print()
    print("=" * 80)
    print(f"Results: {passed} passed, {skipped} skipped, {failed} failed")
    print("=" * 80)

    sys.exit(0 if failed == 0 else 1)
