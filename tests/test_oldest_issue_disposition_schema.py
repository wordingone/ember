# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Schema/runtime agreement for the checked-in task-015 packet."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.oldest_issue_disposition import validate_packet  # noqa: E402
from scripts.verify_oldest_issue_disposition_packet import (  # noqa: E402
    verify_replay,
)

CAPTURED_MASTER = "e8a89a39cee293d793543e025a0d03fee0181e6d"

SCHEMA = (
    ROOT / "manifests" / "oldest-issue-disposition" / "schema-v1.json"
)
PACKET = (
    ROOT
    / "receipts"
    / "oldest-issue-disposition"
    / "ember-oldest-issue-disposition-015-packet-v1.json"
)
CLASSIFICATIONS = (
    ROOT / "manifests" / "oldest-issue-disposition" / "classifications-v1.json"
)
RAW_BUNDLE = (
    ROOT
    / "receipts"
    / "oldest-issue-disposition"
    / "ember-oldest-issue-disposition-015-raw-sources-v1.json"
)


def test_checked_in_packet_passes_schema_and_runtime_validator() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8", errors="strict"))
    packet = json.loads(PACKET.read_text(encoding="utf-8", errors="strict"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(
        packet,
        schema,
        cls=jsonschema.Draft202012Validator,
    )
    validate_packet(packet, expected_master=CAPTURED_MASTER)
    classifications = json.loads(
        CLASSIFICATIONS.read_text(encoding="utf-8", errors="strict")
    )
    verify_replay(
        packet,
        raw_bundle=RAW_BUNDLE,
        classifications_value=classifications,
        expected_master=CAPTURED_MASTER,
    )


def test_runtime_validator_requires_an_independent_master_pin() -> None:
    packet = json.loads(PACKET.read_text(encoding="utf-8", errors="strict"))
    try:
        validate_packet(packet)  # type: ignore[call-arg]
    except TypeError:
        return
    raise AssertionError("validate_packet accepted an omitted master pin")
