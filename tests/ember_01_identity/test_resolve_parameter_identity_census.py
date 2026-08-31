# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The real merge_adjudication_lanes function resolves parameter_identity with zero
unresolved rows, scoped to that one census category (cond3 increment-1)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_IDENTITY_DIR = ROOT / "scripts" / "ember_01_identity"
if str(_IDENTITY_DIR) not in sys.path:
    sys.path.insert(0, str(_IDENTITY_DIR))

from resolve_parameter_identity_census import CENSUS_PATH, resolve  # noqa: E402


class ResolveParameterIdentityCensusTests(unittest.TestCase):
    def test_scoped_merge_resolves_every_executable_candidate_row(self) -> None:
        census = json.loads(CENSUS_PATH.read_text(encoding="utf-8"))
        merged = resolve(census)
        self.assertEqual(merged["coverage"]["unresolved_executable_rows"], 0)
        self.assertEqual(merged["coverage"]["duplicate_dispositions"], 0)
        self.assertGreater(merged["coverage"]["source_executable_rows"], 0)
        self.assertEqual(
            merged["coverage"]["reviewed_consumer_rows"]
            + merged["coverage"]["reviewed_nonconsumer_rows"],
            merged["coverage"]["source_executable_rows"],
        )
        # validate_identity.py's parameter schema/contradiction checks are the one
        # real consumer this census snapshot contains for cond3 increment-1.
        consumer_paths = {row["path"] for row in merged["consumer_rows"]}
        self.assertEqual(consumer_paths, {"scripts/ember_01_identity/validate_identity.py"})


if __name__ == "__main__":
    unittest.main()
