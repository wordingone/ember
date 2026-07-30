#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Expand reviewed issue classifications into source-complete decisions."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.oldest_issue_disposition import (
    _AUTHORITY,
    PacketError,
    _list,
    _load_mapping,
    _mapping,
    _strict_keys,
    _text,
    _write_json,
    validate_capture,
)

_CLASSIFICATION_KEYS = {
    "issue_number",
    "disposition",
    "unbound_description",
    "smallest_binding_action",
    "replacement_citation",
    "retained_lesson",
}
_NON_CLOSE = {"PARTIAL", "SUPERSEDED", "NEGATIVE-KEEP"}


def build_decisions(
    capture_value: Mapping[str, Any],
    classifications_value: Mapping[str, Any],
) -> dict[str, Any]:
    capture = validate_capture(capture_value)
    classifications = _mapping(
        classifications_value,
        field="classifications",
    )
    _strict_keys(
        classifications,
        {"schema_version", "expected_issue_numbers", "rows"},
        field="classifications",
    )
    if (
        classifications["schema_version"]
        != "ember-oldest-issue-classifications-v1"
    ):
        raise PacketError("classification schema is invalid")
    expected_numbers = _list(
        classifications["expected_issue_numbers"],
        field="classifications.expected_issue_numbers",
    )
    capture_numbers = [issue["number"] for issue in capture["issues"]]
    if expected_numbers != capture_numbers:
        raise PacketError(
            "classification issue population does not match live selection"
        )
    rows = _list(classifications["rows"], field="classifications.rows")
    if len(rows) != len(capture_numbers):
        raise PacketError("classifications must match the live selection")
    by_number: dict[int, Mapping[str, Any]] = {}
    for index, raw in enumerate(rows):
        field = f"classifications.rows[{index}]"
        row = _mapping(raw, field=field)
        _strict_keys(row, _CLASSIFICATION_KEYS, field=field)
        number = row["issue_number"]
        if (
            isinstance(number, bool)
            or not isinstance(number, int)
            or number < 1
            or number in by_number
        ):
            raise PacketError(f"{field}.issue_number is invalid or duplicate")
        if row["disposition"] not in _NON_CLOSE:
            raise PacketError(
                f"{field} cannot generate CLOSE; exact authority-reviewed "
                "production evidence must be authored separately"
            )
        _text(
            row["smallest_binding_action"],
            field=f"{field}.smallest_binding_action",
        )
        if row["disposition"] == "PARTIAL":
            _text(
                row["unbound_description"],
                field=f"{field}.unbound_description",
            )
            if (
                row["replacement_citation"] is not None
                or row["retained_lesson"] is not None
            ):
                raise PacketError(f"{field} PARTIAL has incompatible fields")
        elif row["disposition"] == "SUPERSEDED":
            _text(
                row["replacement_citation"],
                field=f"{field}.replacement_citation",
            )
            if (
                row["unbound_description"] is not None
                or row["retained_lesson"] is not None
            ):
                raise PacketError(
                    f"{field} SUPERSEDED has incompatible fields"
                )
        else:
            _text(
                row["retained_lesson"],
                field=f"{field}.retained_lesson",
            )
            if (
                row["unbound_description"] is not None
                or row["replacement_citation"] is not None
            ):
                raise PacketError(
                    f"{field} NEGATIVE-KEEP has incompatible fields"
                )
        by_number[number] = row
    if set(by_number) != set(capture_numbers):
        raise PacketError("classifications omit or add selected issues")

    decisions = []
    for issue in capture["issues"]:
        row = by_number[issue["number"]]
        status = {
            "PARTIAL": "UNBOUND",
            "SUPERSEDED": "SUPERSEDED",
            "NEGATIVE-KEEP": "NEGATIVE",
        }[row["disposition"]]
        source_inventory = [
            {
                "source_kind": "issue_body",
                "citation": issue["url"],
                "source_sha256": issue["body_sha256"],
                "status": status,
            },
            *[
                {
                    "source_kind": "issue_comment",
                    "citation": comment["url"],
                    "source_sha256": comment["body_sha256"],
                    "status": status,
                }
                for comment in issue["comments"]
            ],
        ]
        unbound = None
        if row["disposition"] == "PARTIAL":
            unbound = {
                "citation": issue["url"],
                "source_sha256": issue["body_sha256"],
                "description": row["unbound_description"],
            }
        decisions.append(
            {
                "issue_number": issue["number"],
                "disposition": row["disposition"],
                "source_clause_inventory": source_inventory,
                "unbound_clause": unbound,
                "smallest_binding_action": row[
                    "smallest_binding_action"
                ],
                "replacement_citation": row["replacement_citation"],
                "retained_lesson": row["retained_lesson"],
                "close_evidence": [],
                "authority_review": None,
            }
        )
    return {
        "authority": dict(_AUTHORITY),
        "schema_version": "ember-oldest-issue-decisions-v1",
        "master_sha": capture["master_sha"],
        "selection_sha256": capture["selection_sha256"],
        "rows": decisions,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--classifications", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        decisions = build_decisions(
            _load_mapping(args.capture, field="capture"),
            _load_mapping(args.classifications, field="classifications"),
        )
        _write_json(args.output, decisions)
    except PacketError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
