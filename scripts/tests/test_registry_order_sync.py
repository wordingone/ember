#!/usr/bin/env python3
"""TDD: ORDER list must match registry ids from conditions-v1.md.

This test ensures that when a new condition is added to the registry,
it's also added to the runner's ORDER list (preventing REGISTRY_DRIFT
at board runtime).
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
    sys.exit(0)


if __name__ == "__main__":
    test_order_matches_registry()
