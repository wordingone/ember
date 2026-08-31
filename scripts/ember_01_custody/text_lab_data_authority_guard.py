#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""C0 TEXT_LAB_DATA_AUTHORITY guard: every consumed training shard is cross-
referenced against the accepted-training-input-authority registry at cycle start.

The C0 ledger's blocking_reason for TEXT_LAB_DATA_AUTHORITY is exact:
``accepted-training-input-authorities-v1.json`` exists as a manifest, but "no
executable guard cross-references every consumed training shard against it at
cycle start." The existing consumer of that registry
(``src/ember/governance/scripts/ember_01_identity/validate_identity.py``'s ``_pinned_accepted_training_
input`` / the ``admission.training_input_authority`` finding) binds ONE claim --
a whole checkpoint's ``data.accepted_input`` -- at admission time. It never checks
that every INDIVIDUAL shard about to be consumed in a training cycle actually
carries that same authority binding. A cycle that starts from a shard census
containing even one shard bound to a stale, revoked, or absent authority would
sail through the whole-checkpoint check as long as the OTHER shards' declared
authority happened to be the accepted one -- an untraceable training-signal origin
hiding inside an otherwise-compliant cycle.

This module closes exactly that gap: given a receipted data-source census (the
list of shard sources a training cycle is about to consume) and the live registry,
it fails closed unless EVERY shard entry's authority_id/input_id exactly match the
registry's current CURRENT_EXECUTABLE authority. It does not duplicate the
registry-parsing logic -- it imports and reuses ``validate_identity``'s own
``_pinned_accepted_training_input`` so this guard can never drift from what the
production admission consumer accepts as the active authority.

Zero live lab data required: the census is a JSON structure describing WHICH
authority each shard source claims, not the shard bytes themselves -- exactly the
provenance-audit boundary the ledger row asks for. When a real per-cycle shard
census does not yet exist on this checkout, this guard is the checkable mechanism
that will reject an uncensused or unauthorized cycle the moment one is attempted;
it does not itself require live shards to be buildable or testable.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_IDENTITY_DIR = Path(__file__).resolve().parents[1] / "ember_01_identity"
if str(_IDENTITY_DIR) not in sys.path:
    sys.path.insert(0, str(_IDENTITY_DIR))

import validate_identity

CENSUS_GUARD_SCHEMA = "ember-01-text-lab-data-authority-census-guard-v1"
REQUIRED_CENSUS_TOP_KEYS = {"schema", "cycle_id", "shards"}
CENSUS_SCHEMA = "ember-training-shard-census-v1"
REQUIRED_SHARD_KEYS = {"shard_id", "authority_id", "input_id"}


class TextLabDataAuthorityError(ValueError):
    """A training-shard census could not be evaluated against the accepted
    training-input-authority registry."""


def load_accepted_authority() -> tuple[dict[str, Any], str]:
    """Load the live, CURRENT_EXECUTABLE accepted-training-input authority via the
    exact same parser the production admission consumer uses. Fails closed
    (raises) when the registry file is missing, malformed, or its active entry is
    not CURRENT_EXECUTABLE -- never silently treats an unreadable registry as
    "no authority required"."""
    pinned = validate_identity._pinned_accepted_training_input()
    if pinned is None:
        raise TextLabDataAuthorityError(
            "accepted-training-input-authority registry is missing, malformed, or "
            "its active entry is not CURRENT_EXECUTABLE -- refusing to authorize "
            "any training cycle against an unreadable authority"
        )
    return pinned


def _validate_census_shape(census: Any) -> list[dict[str, Any]]:
    if not isinstance(census, Mapping):
        raise TextLabDataAuthorityError("census must be a JSON object")
    if set(census) != REQUIRED_CENSUS_TOP_KEYS:
        raise TextLabDataAuthorityError(
            f"census has unexpected top-level keys (closed schema): {sorted(census)}"
        )
    if census.get("schema") != CENSUS_SCHEMA:
        raise TextLabDataAuthorityError(
            f"census schema mismatch: expected {CENSUS_SCHEMA!r}, got {census.get('schema')!r}"
        )
    cycle_id = census.get("cycle_id")
    if not isinstance(cycle_id, str) or not cycle_id:
        raise TextLabDataAuthorityError("census cycle_id must be a non-empty string")
    shards = census.get("shards")
    if not isinstance(shards, list) or not shards:
        raise TextLabDataAuthorityError(
            "census shards must be a non-empty list -- an empty or absent shard "
            "list is not a valid cycle-start census"
        )
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(shards):
        if not isinstance(row, Mapping) or set(row) != REQUIRED_SHARD_KEYS:
            raise TextLabDataAuthorityError(
                f"census shard entry #{index} has malformed shape (requires exactly "
                f"{sorted(REQUIRED_SHARD_KEYS)}): {row!r}"
            )
        if not isinstance(row.get("shard_id"), str) or not row["shard_id"]:
            raise TextLabDataAuthorityError(
                f"census shard entry #{index} has a non-string/empty shard_id: {row!r}"
            )
        normalized.append(dict(row))
    return normalized


def verify_shard_census_authority(
    census: Mapping[str, Any], *, accepted_authority: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Cross-reference every shard in ``census`` against the accepted training-
    input authority. Fails closed: a malformed census, a missing/None
    authority_id or input_id on any shard, or a shard bound to anything other
    than the registry's exact active authority_id + input_id is a violation.

    ``accepted_authority`` may be injected for testing (a fixture registry
    tuple as returned by ``load_accepted_authority``); production callers omit
    it and the LIVE registry is read.
    """
    active, _digest = (
        accepted_authority if accepted_authority is not None else load_accepted_authority()
    )
    shards = _validate_census_shape(census)

    violations: list[dict[str, str]] = []
    for row in shards:
        shard_authority_id = row.get("authority_id")
        shard_input_id = row.get("input_id")
        if not isinstance(shard_authority_id, str) or not shard_authority_id:
            violations.append(
                {
                    "shard_id": row["shard_id"],
                    "reason": "shard carries no authority_id binding",
                }
            )
            continue
        if not isinstance(shard_input_id, str) or not shard_input_id:
            violations.append(
                {
                    "shard_id": row["shard_id"],
                    "reason": "shard carries no input_id binding",
                }
            )
            continue
        if shard_authority_id != active["authority_id"] or shard_input_id != active["input_id"]:
            violations.append(
                {
                    "shard_id": row["shard_id"],
                    "reason": (
                        f"shard authority_id={shard_authority_id!r}/input_id={shard_input_id!r} "
                        f"does not match the registry's active "
                        f"authority_id={active['authority_id']!r}/"
                        f"input_id={active['input_id']!r}"
                    ),
                }
            )

    result = "REJECTED" if violations else "ACCEPTED"
    return {
        "schema": CENSUS_GUARD_SCHEMA,
        "cycle_id": census.get("cycle_id") if isinstance(census, Mapping) else None,
        "result": result,
        "shards_checked": len(shards),
        "violations": violations,
        "accepted_authority_id": active["authority_id"],
    }


def cycle_start_guard(census_path: Path) -> dict[str, Any]:
    """File-driven entry point: load a receipted shard census from disk and run
    it against the live registry. Fails closed on a missing/malformed census
    file exactly as on a malformed in-memory census."""
    import json

    path = Path(census_path)
    if not path.is_file():
        return {
            "schema": CENSUS_GUARD_SCHEMA,
            "result": "REJECTED",
            "violations": [{"shard_id": "*", "reason": f"census file missing: {path}"}],
        }
    try:
        census = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {
            "schema": CENSUS_GUARD_SCHEMA,
            "result": "REJECTED",
            "violations": [{"shard_id": "*", "reason": f"census file unreadable: {exc}"}],
        }
    try:
        return verify_shard_census_authority(census)
    except TextLabDataAuthorityError as exc:
        return {
            "schema": CENSUS_GUARD_SCHEMA,
            "result": "REJECTED",
            "violations": [{"shard_id": "*", "reason": str(exc)}],
        }


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("census_path", type=Path, help="Receipted training-shard census JSON.")
    args = parser.parse_args(argv)
    verdict = cycle_start_guard(args.census_path)
    print(json.dumps(verdict, indent=2, sort_keys=True))
    return 0 if verdict["result"] == "ACCEPTED" else 1


if __name__ == "__main__":
    sys.exit(main())
