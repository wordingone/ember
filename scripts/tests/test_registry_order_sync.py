#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""TDD: ORDER list must match registry ids from conditions-v1.md, and the
probe directory (scripts/ember_totality/) must mirror FILENAME_ID/ORDER.

This test ensures that when a new condition is added to the registry,
it's also added to the runner's ORDER list (preventing REGISTRY_DRIFT
at board runtime), AND that no stray test_*.py file can land in the probe
directory unregistered (preventing PROBE_DIR_DRIFT at board runtime) --
the 2026-07-07 incident where test_prev_receipt_selection.py and
test_c15_receipt_selection.py (plain TDD unit tests, not board probes)
sat in scripts/ember_totality/ unregistered and aborted every run before
any probe executed.
"""

import os
import sys
import re

# Add repo root to path for imports
HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO_ROOT)

from scripts.ember_totality import ember_totality_spec


def test_order_matches_registry():
    """Verify that the runner's ORDER list contains exactly the same
    condition ids as the registry in conditions-v1.md."""

    # Get the ORDER from the module
    runner_set = set(ember_totality_spec.ORDER)

    # Parse the registry from conditions-v1.md
    registry_ids = ember_totality_spec.parse_registry_ids(
        ember_totality_spec.CONDITIONS_SPEC_PATH
    )
    registry_set = set(registry_ids)

    # They must match exactly
    if runner_set != registry_set:
        in_registry_not_order = sorted(registry_set - runner_set)
        in_order_not_registry = sorted(runner_set - registry_set)

        msg = (
            f"ORDER/registry mismatch:\n"
            f"  In registry but NOT in ORDER: {in_registry_not_order}\n"
            f"  In ORDER but NOT in registry: {in_order_not_registry}"
        )
        print(f"RED registry-order-sync {msg}", file=sys.stderr)
        sys.exit(1)

    # If they match, report GREEN
    print(f"GREEN registry-order-sync all {len(runner_set)} condition ids match between ORDER and registry")


def test_probe_dir_matches_filename_id():
    """Verify the probe directory mirrors FILENAME_ID/ORDER exactly --
    the same mirror check ember_totality_spec.registry_sync_check() enforces
    at runtime (PROBE_DIR_DRIFT), run here standalone so a stray test_*.py
    file dropped into scripts/ember_totality/ fails in CI/tests instead of
    silently aborting the next live board run."""

    probe_dir = os.path.dirname(os.path.abspath(ember_totality_spec.__file__))
    all_test_files = {n for n in os.listdir(probe_dir)
                      if n.startswith("test_") and n.endswith(".py")}
    non_probe_tests = ember_totality_spec.NON_PROBE_TEST_FILES
    discovered = all_test_files - non_probe_tests
    filename_id = ember_totality_spec.FILENAME_ID
    runner_set = set(ember_totality_spec.ORDER)

    unregistered_files = sorted(discovered - set(filename_id))
    missing_files = sorted(set(filename_id) - discovered)
    unmapped_ids = sorted(set(filename_id.values()) - runner_set)
    missing_non_probes = sorted(non_probe_tests - all_test_files)
    overlap = sorted(non_probe_tests & set(filename_id))

    if (unregistered_files or missing_files or unmapped_ids
            or missing_non_probes or overlap):
        msg = (
            f"probe-dir/FILENAME_ID/ORDER mismatch:\n"
            f"  probe files present but not in FILENAME_ID: {unregistered_files}\n"
            f"  FILENAME_ID files missing from directory:   {missing_files}\n"
            f"  FILENAME_ID ids not in ORDER:               {unmapped_ids}\n"
            f"  NON_PROBE_TEST_FILES missing:               {missing_non_probes}\n"
            f"  probe/non-probe overlap:                     {overlap}"
        )
        print(f"RED probe-dir-sync {msg}", file=sys.stderr)
        sys.exit(1)

    print(f"GREEN probe-dir-sync all {len(discovered)} probe files match FILENAME_ID and ORDER")


if __name__ == "__main__":
    test_order_matches_registry()
    test_probe_dir_matches_filename_id()
    sys.exit(0)
