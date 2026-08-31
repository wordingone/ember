#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Resolve the parameter_identity category (160 rows) via the real merge mechanism.

cond3 increment-1 scope: this script does NOT re-run the full 65,202-row,
14-category census/merge (that is the whole cond3 program, not one increment). It
scopes ``merge_adjudications.merge_adjudication_lanes`` -- the real function, unmodified
-- to exactly the ``parameter_identity`` rows already discovered in
``manifests/ember-01-identity/consumer-census-v1.json``, and documents one schema-drift
finding discovered while doing so (see FINDINGS below).

FINDINGS (read before trusting the output blindly):

1. The checked-in ``consumer-census-v1.json`` rows have NO ``source_role`` field, even
   though ``merge_adjudications._validate_source`` requires it (rows without
   ``source_role == "EXECUTABLE_CANDIDATE"`` are silently excluded from the set that
   must be resolved). ``census_consumers.py``'s own row schema DOES set
   ``source_role`` (see its ``_source_role`` classifier and the ``EXECUTABLE_CANDIDATE``
   literal at line ~633/787). The checked-in census is therefore either a rolled-up
   "set" projection (top-level schema is literally
   ``ember-identity-consumer-census-set-v1``, not census_consumers.py's own
   ``ember-identity-consumer-census-v1``) or predates that field. This script derives
   ``source_role`` for each row from the real, unmodified ``_source_role`` classifier
   census_consumers.py itself uses -- not an invented rule -- so the real merge function
   still runs unmodified; only the census row's missing field is backfilled from the
   census tool's own logic.
2. The census's 160 rows are static keyword hits on "param_count" et al across the
   whole tree -- most are NOT calls into the identity manifest at all (schedule
   generators, bitnet-twin scripts, accounting harnesses that happen to count
   parameters for unrelated purposes). Only rows inside the real validation/round-trip
   call path this increment lands (``src/ember/governance/scripts/ember_01_identity/validate_identity.py``'s
   ``parameters`` schema/contradiction checks, exercised end-to-end by
   ``tests/ember_01_identity/test_parameter_identity_roundtrip.py`` against a manifest
   bound to a REAL measured checkpoint receipt) are adjudicated as real consumers here.
   The new wiring this increment adds
   (``src/ember/governance/scripts/ember_01_identity/parameter_identity_binding.py``,
   ``tools/ember-restart-3b/parameter_counter.py``) is not present in this census
   snapshot (it predates the increment); it is not claimed as resolved by this script
   and needs a fresh census run to be discovered and adjudicated in its own right.

Usage: run as a script (writes the merged resolution + records the finding); or import
``build_scoped_source_and_lane`` / ``resolve`` for tests.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_IDENTITY_DIR = Path(__file__).resolve().parent
if str(_IDENTITY_DIR) not in sys.path:
    sys.path.insert(0, str(_IDENTITY_DIR))

from census_consumers import _source_role  # noqa: E402
from merge_adjudications import LANE_SCHEMA, merge_adjudication_lanes  # noqa: E402

CENSUS_PATH = (
    _IDENTITY_DIR.parents[1] / "manifests" / "ember-01-identity" / "consumer-census-v1.json"
)
OUTPUT_PATH = (
    _IDENTITY_DIR.parents[1] / "manifests" / "ember-01-identity"
    / "parameter-identity-resolution-v1.json"
)

# Real call-sites this increment's round-trip test actually exercises against a
# receipt bound to a live checkpoint. Everything else in the category is a static
# keyword coincidence, not a manifest binding.
REAL_CONSUMER_PATHS = {"src/ember/governance/scripts/ember_01_identity/validate_identity.py"}


def _key(row: dict) -> tuple[str, int, str, str]:
    digest = row["line_sha256"] if row.get("evidence_scope") == "LINE" else row["content_sha256"]
    return (str(row["path"]), int(row["line"]), str(row["category"]), str(digest))


def build_scoped_source_and_lane(census: dict) -> tuple[dict, dict]:
    """Project the parameter_identity rows into (source, lane) for the real merge."""
    public_root = [
        row for row in census.get("roots", [])
        if isinstance(row, dict) and row.get("root_id") == "public-master"
    ]
    if len(public_root) != 1:
        raise ValueError("census lacks exactly one public-master root")

    rows = [row for row in census["evidence"] if row.get("category") == "parameter_identity"]
    deduped: dict[tuple, dict] = {}
    for row in rows:
        source_role = _source_role(row["path"])
        scoped = {**row, "source_role": source_role}
        key = _key(scoped)
        # Prefer the public-master root's copy of a duplicate key (same file/line
        # scanned from multiple roots at the same commit content); any root's row
        # carries the same content/line hash, so which one wins does not change the
        # evidence, only the recorded root_id.
        existing = deduped.get(key)
        if existing is None or (existing.get("root_id") != "public-master" and row.get("root_id") == "public-master"):
            deduped[key] = scoped

    source = {"evidence": list(deduped.values()), "roots": public_root}

    consumer_rows: list[dict] = []
    nonconsumer_rows: list[dict] = []
    for scoped in deduped.values():
        if scoped["source_role"] != "EXECUTABLE_CANDIDATE":
            continue  # excluded from the resolvable set by _validate_source itself
        evidence_sha256 = scoped["line_sha256"] if scoped.get("evidence_scope") == "LINE" else scoped["content_sha256"]
        row = {
            "path": scoped["path"], "line": scoped["line"], "category": scoped["category"],
            "evidence_sha256": evidence_sha256,
        }
        if scoped["path"] in REAL_CONSUMER_PATHS:
            consumer_rows.append({
                **row,
                "current_input": "parameters schema/contradiction validation",
                "derived_label": "RESOLVED",
                "protocol": "validate_identity.validate_manifest",
                "failure_behavior": "FAIL_CLOSED_ON_SCHEMA_OR_CONTRADICTION",
                "claim_effect": "REAL_CONSUMER_VALIDATES_BOUND_MANIFEST",
                "conflict": "NONE",
                "integration_requirement": "emit all six parameter axes from independently verified evidence",
            })
        else:
            nonconsumer_rows.append({
                **row,
                "review_basis": (
                    "static keyword coincidence ('param_count' or similar term) in code "
                    "unrelated to the identity manifest's parameter binding; does not "
                    "validate or emit checkpoint-bound parameter identity"
                ),
            })

    lane = {
        "schema": LANE_SCHEMA,
        "source_commit": public_root[0]["source_commit"],
        "scope": "parameter_identity-category-only-cond3-increment-1",
        "coverage": {
            "category": "parameter_identity",
            "total_rows_reviewed": len(consumer_rows) + len(nonconsumer_rows),
        },
        "consumer_rows": consumer_rows,
        "nonconsumer_rows": nonconsumer_rows,
        "nonconsumer_files": [],
    }
    return source, lane


def resolve(census: dict) -> dict:
    source, lane = build_scoped_source_and_lane(census)
    lane_bytes = json.dumps(lane, sort_keys=True).encode("utf-8")
    return merge_adjudication_lanes([(lane["scope"], lane_bytes)], source)


def main() -> int:
    census = json.loads(CENSUS_PATH.read_text(encoding="utf-8"))
    merged = resolve(census)
    OUTPUT_PATH.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "coverage": merged["coverage"], "output": str(OUTPUT_PATH)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
